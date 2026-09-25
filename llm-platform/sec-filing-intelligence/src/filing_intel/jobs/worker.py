"""The loop that runs queued work.

Claim, run, record, repeat. Everything interesting is in what happens when the
run fails: a transient error goes back on the queue with a backoff, a permanent
one is recorded as failed immediately, and a job that has used its attempts is
failed regardless of which kind it was.

The worker owns no domain logic. It is handed a coroutine that turns a payload
into a result, which is what lets it be tested against a function that raises
on the second call rather than against a model provider.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from .models import Job
from .retry import RetryPolicy, is_transient
from .store import DEFAULT_LEASE_SECONDS, JobStore

logger = logging.getLogger(__name__)

Handler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass
class WorkerStats:
    claimed: int = 0
    succeeded: int = 0
    retried: int = 0
    failed: int = 0
    reclaimed: int = 0


@dataclass
class Worker:
    """Runs jobs from a store until stopped."""

    store: JobStore
    handler: Handler
    worker_id: str = field(default_factory=lambda: f"worker-{uuid.uuid4().hex[:8]}")
    policy: RetryPolicy = field(default_factory=RetryPolicy)
    lease_seconds: float = DEFAULT_LEASE_SECONDS
    #: How long to wait when there was nothing to do. Short enough to feel
    #: responsive, long enough not to spin a core against an empty queue.
    idle_sleep: float = 0.05
    stats: WorkerStats = field(default_factory=WorkerStats)
    _task: asyncio.Task | None = field(default=None, repr=False)
    _stopping: asyncio.Event = field(default_factory=asyncio.Event, repr=False)

    async def run_once(self) -> Job | None:
        """Claim and process a single job. Returns it, or None if idle."""
        self.stats.reclaimed += len(await self.store.reclaim_expired())
        job = await self.store.claim(self.worker_id, self.lease_seconds)
        if job is None:
            return None
        self.stats.claimed += 1
        return await self._process(job)

    async def _process(self, job: Job) -> Job:
        try:
            result = await self.handler(job.payload)
        except asyncio.CancelledError:
            # Shutdown, not failure. Drop the lease so the job is picked up
            # again rather than burning an attempt on a worker going away.
            await self.store.retry_later(job, 0.0, RuntimeError("worker cancelled"))
            raise
        # Deliberately broad: a handler raising anything at all must become a
        # recorded failure, not a dead worker.
        except Exception as error:
            retryable = is_transient(error) and not job.exhausted
            if retryable:
                delay = self.policy.delay(job.attempts)
                self.stats.retried += 1
                logger.warning(
                    "job %s failed (%s), retrying in %.1fs", job.id, error, delay
                )
                return await self.store.retry_later(job, delay, error)
            self.stats.failed += 1
            logger.error("job %s failed permanently: %s", job.id, error)
            return await self.store.fail(job, error)
        self.stats.succeeded += 1
        return await self.store.complete(job, result)

    async def run_forever(self) -> None:
        while not self._stopping.is_set():
            try:
                job = await self.run_once()
            except asyncio.CancelledError:
                raise
            # Broad again: a store hiccup must not end the loop.
            except Exception:
                logger.exception("worker loop error")
                job = None
            if job is None:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._stopping.wait(), timeout=self.idle_sleep)

    def start(self) -> None:
        if self._task is None:
            self._stopping.clear()
            self._task = asyncio.create_task(self.run_forever())

    async def stop(self) -> None:
        self._stopping.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None


async def drain(worker: Worker, limit: int = 100, idle_sleep: float = 0.005) -> int:
    """Run jobs until nothing is left. For tests and one-shot processing.

    An idle claim does not mean an empty queue: a job that has just failed is
    sitting out its backoff and `claim` correctly refuses to hand it over yet.
    Returning at the first idle tick therefore stops before any retry runs,
    which made a retrying job look like a stalled one.
    """
    done = 0
    for _ in range(limit):
        job = await worker.run_once()
        if job is None:
            if await worker.store.pending() == 0:
                return done
            await asyncio.sleep(idle_sleep)
            continue
        if job.state.terminal:
            done += 1
    return done
