"""Where jobs live between submission and completion.

Two implementations behind one protocol, mirroring `cache/store.py`: Redis when
a URL is configured, in-process otherwise. The in-process one is not a test
double -- it is the real behaviour of a single-worker deployment, and it honours
the same semantics so nothing downstream can tell the difference.

**At-least-once, not at-most-once.** A worker that dies mid-job has to leave the
work recoverable, so a claim is a lease with a deadline rather than a removal.
The cost is that a job can run twice if a worker stalls past its lease and then
finishes; the alternative cost is losing work outright, which is worse for a
nine-second research call the caller is waiting on. Idempotency at the API layer
is what keeps the duplicate from reaching the caller twice.

**No Lua.** The claim is a single `LMOVE`, which Redis executes atomically, so
two workers cannot take the same job. The reaper that recovers expired leases
does not need to be atomic with the claim: it compares deadlines and puts the
job back, and a job briefly present in both lists is claimed once because the
claim itself is atomic.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Protocol

from .models import IdempotencyConflict, Job, JobState

READY_KEY = "filing_intel:jobs:ready"
RUNNING_KEY = "filing_intel:jobs:running"
RECORD_KEY = "filing_intel:jobs:record"
IDEMPOTENCY_KEY = "filing_intel:jobs:idempotency"

#: How long a worker holds a job before the reaper may take it back. Generous
#: relative to a nine-second research call: a lease shorter than the work is a
#: machine for running everything twice.
DEFAULT_LEASE_SECONDS = 120.0


def fingerprint(payload: dict[str, Any]) -> str:
    """Stable hash of a request, so a reused key with a changed body is caught."""
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:32]


class JobStore(Protocol):
    async def submit(self, job: Job) -> Job: ...
    async def get(self, job_id: str) -> Job | None: ...
    async def claim(self, worker_id: str, lease_seconds: float) -> Job | None: ...
    async def complete(self, job: Job, result: dict[str, Any]) -> Job: ...
    async def retry_later(self, job: Job, delay_seconds: float, error: BaseException) -> Job: ...
    async def fail(self, job: Job, error: BaseException) -> Job: ...
    async def reclaim_expired(self) -> list[str]: ...
    async def pending(self) -> int: ...


class InMemoryJobStore:
    """Single-process store. Real behaviour for a single-worker deployment."""

    def __init__(self, now=time.time) -> None:
        self._records: dict[str, Job] = {}
        self._ready: list[str] = []
        self._running: list[str] = []
        self._by_key: dict[str, str] = {}
        self._now = now

    async def submit(self, job: Job) -> Job:
        if job.idempotency_key:
            existing_id = self._by_key.get(job.idempotency_key)
            if existing_id is not None:
                existing = self._records[existing_id]
                if existing.request_hash != job.request_hash:
                    raise IdempotencyConflict(job.idempotency_key, existing_id)
                return existing
            self._by_key[job.idempotency_key] = job.id
        self._records[job.id] = job
        self._ready.append(job.id)
        return job

    async def get(self, job_id: str) -> Job | None:
        return self._records.get(job_id)

    async def claim(self, worker_id: str, lease_seconds: float) -> Job | None:
        now = self._now()
        for index, job_id in enumerate(self._ready):
            job = self._records[job_id]
            if job.available_at > now:
                continue  # backing off from an earlier failure
            self._ready.pop(index)
            self._running.append(job_id)
            claimed = job.touched(
                state=JobState.RUNNING,
                attempts=job.attempts + 1,
                claimed_by=worker_id,
                claim_expires_at=now + lease_seconds,
            )
            self._records[job_id] = claimed
            return claimed
        return None

    async def complete(self, job: Job, result: dict[str, Any]) -> Job:
        self._drop_running(job.id)
        done = job.touched(
            state=JobState.SUCCEEDED, result=result, claimed_by=None, claim_expires_at=None
        )
        self._records[job.id] = done
        return done

    async def retry_later(self, job: Job, delay_seconds: float, error: BaseException) -> Job:
        from .retry import describe, error_kind

        self._drop_running(job.id)
        queued = job.touched(
            state=JobState.QUEUED,
            available_at=self._now() + delay_seconds,
            claimed_by=None,
            claim_expires_at=None,
            error=describe(error),
            error_kind=error_kind(error),
        )
        self._records[job.id] = queued
        self._ready.append(job.id)
        return queued

    async def fail(self, job: Job, error: BaseException) -> Job:
        from .retry import describe, error_kind

        self._drop_running(job.id)
        dead = job.touched(
            state=JobState.FAILED,
            error=describe(error),
            error_kind=error_kind(error),
            claimed_by=None,
            claim_expires_at=None,
        )
        self._records[job.id] = dead
        return dead

    async def reclaim_expired(self) -> list[str]:
        now = self._now()
        reclaimed = []
        for job_id in list(self._running):
            job = self._records[job_id]
            if job.claim_expires_at is not None and job.claim_expires_at <= now:
                self._drop_running(job_id)
                self._records[job_id] = job.touched(
                    state=JobState.QUEUED, claimed_by=None, claim_expires_at=None
                )
                self._ready.append(job_id)
                reclaimed.append(job_id)
        return reclaimed

    async def pending(self) -> int:
        return len(self._ready) + len(self._running)

    def _drop_running(self, job_id: str) -> None:
        if job_id in self._running:
            self._running.remove(job_id)


class RedisJobStore:
    """Redis-backed, so more than one worker process can share the queue."""

    def __init__(self, redis: Any, now=time.time) -> None:
        self._redis = redis
        self._now = now

    async def submit(self, job: Job) -> Job:
        if job.idempotency_key:
            key = f"{IDEMPOTENCY_KEY}:{job.idempotency_key}"
            # SET NX is the whole of the idempotency guarantee: the first
            # submission to land claims the key, and concurrent duplicates read
            # back the winner rather than each creating a job.
            won = await self._redis.set(key, job.id, nx=True)
            if not won:
                existing_id = _text(await self._redis.get(key))
                existing = await self.get(existing_id) if existing_id else None
                if existing is None:
                    # The key outlived its job. Treat it as free rather than
                    # refusing a request forever on the strength of a ghost.
                    await self._redis.set(key, job.id)
                elif existing.request_hash != job.request_hash:
                    raise IdempotencyConflict(job.idempotency_key, existing.id)
                else:
                    return existing
        await self._write(job)
        await self._redis.rpush(READY_KEY, job.id)
        return job

    async def get(self, job_id: str) -> Job | None:
        raw = await self._redis.hget(RECORD_KEY, job_id)
        return Job.from_dict(json.loads(_text(raw))) if raw else None

    async def claim(self, worker_id: str, lease_seconds: float) -> Job | None:
        now = self._now()
        # Bounded by the queue length so a queue full of backed-off jobs cannot
        # spin forever; each pass moves one job and puts it back if not ready.
        for _ in range(max(1, await self._redis.llen(READY_KEY))):
            job_id = _text(await self._redis.lmove(READY_KEY, RUNNING_KEY, "LEFT", "RIGHT"))
            if job_id is None:
                return None
            job = await self.get(job_id)
            if job is None:
                await self._redis.lrem(RUNNING_KEY, 1, job_id)
                continue
            if job.available_at > now:
                # Still backing off. Return it to the tail so the next claim
                # tries a different job rather than this one again.
                await self._redis.lrem(RUNNING_KEY, 1, job_id)
                await self._redis.rpush(READY_KEY, job_id)
                continue
            claimed = job.touched(
                state=JobState.RUNNING,
                attempts=job.attempts + 1,
                claimed_by=worker_id,
                claim_expires_at=now + lease_seconds,
            )
            await self._write(claimed)
            return claimed
        return None

    async def complete(self, job: Job, result: dict[str, Any]) -> Job:
        await self._redis.lrem(RUNNING_KEY, 1, job.id)
        done = job.touched(
            state=JobState.SUCCEEDED, result=result, claimed_by=None, claim_expires_at=None
        )
        await self._write(done)
        return done

    async def retry_later(self, job: Job, delay_seconds: float, error: BaseException) -> Job:
        from .retry import describe, error_kind

        await self._redis.lrem(RUNNING_KEY, 1, job.id)
        queued = job.touched(
            state=JobState.QUEUED,
            available_at=self._now() + delay_seconds,
            claimed_by=None,
            claim_expires_at=None,
            error=describe(error),
            error_kind=error_kind(error),
        )
        await self._write(queued)
        await self._redis.rpush(READY_KEY, job.id)
        return queued

    async def fail(self, job: Job, error: BaseException) -> Job:
        from .retry import describe, error_kind

        await self._redis.lrem(RUNNING_KEY, 1, job.id)
        dead = job.touched(
            state=JobState.FAILED,
            error=describe(error),
            error_kind=error_kind(error),
            claimed_by=None,
            claim_expires_at=None,
        )
        await self._write(dead)
        return dead

    async def reclaim_expired(self) -> list[str]:
        now = self._now()
        reclaimed = []
        for raw in await self._redis.lrange(RUNNING_KEY, 0, -1):
            job_id = _text(raw)
            job = await self.get(job_id)
            if job is None:
                await self._redis.lrem(RUNNING_KEY, 1, job_id)
                continue
            if job.claim_expires_at is not None and job.claim_expires_at <= now:
                await self._redis.lrem(RUNNING_KEY, 1, job_id)
                await self._write(
                    job.touched(state=JobState.QUEUED, claimed_by=None, claim_expires_at=None)
                )
                await self._redis.rpush(READY_KEY, job_id)
                reclaimed.append(job_id)
        return reclaimed

    async def pending(self) -> int:
        return int(await self._redis.llen(READY_KEY)) + int(await self._redis.llen(RUNNING_KEY))

    async def _write(self, job: Job) -> None:
        await self._redis.hset(RECORD_KEY, job.id, json.dumps(job.to_dict(), default=str))


def _text(value: Any) -> Any:
    return value.decode() if isinstance(value, bytes) else value


def build_job_store(redis_url: str | None) -> JobStore:
    """Redis when a URL is configured, in-process otherwise."""
    if not redis_url:
        return InMemoryJobStore()
    from redis.asyncio import Redis

    return RedisJobStore(Redis.from_url(redis_url))
