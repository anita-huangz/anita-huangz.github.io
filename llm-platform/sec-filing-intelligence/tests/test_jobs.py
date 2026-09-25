"""The job queue: retries, leases, idempotency, and both stores.

The two stores are tested through the same parametrised suite. That is the
point of the protocol -- if the in-process one behaved differently from Redis,
then "degrades to in-process" would be a promise the platform could not keep,
and the difference would only show up in production.
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from filing_intel.errors import ConfigError, ProviderRefusal, UpstreamDataError
from filing_intel.jobs import (
    IdempotencyConflict,
    InMemoryJobStore,
    Job,
    JobState,
    RedisJobStore,
    RetryPolicy,
    Worker,
    build_job_store,
    describe,
    drain,
    error_kind,
    fingerprint,
    is_transient,
)

FAST = RetryPolicy(base_seconds=0.001, max_seconds=0.002)


@pytest.fixture(autouse=True)
def quiet_worker_logs():
    """The worker logs every retry at WARNING; the suite retries on purpose."""
    logging.disable(logging.CRITICAL)
    yield
    logging.disable(logging.NOTSET)


@pytest.fixture(params=["memory", "redis"])
def store(request):
    if request.param == "memory":
        return InMemoryJobStore()
    fakeredis = pytest.importorskip("fakeredis")
    return RedisJobStore(fakeredis.aioredis.FakeRedis())


# --------------------------------------------------------------------------- #
# Retry classification
# --------------------------------------------------------------------------- #


class TestRetryClassification:
    @pytest.mark.parametrize(
        "error",
        [UpstreamDataError("EDGAR 503"), TimeoutError(), ConnectionError(), RuntimeError("?")],
    )
    def test_transient_failures_are_worth_retrying(self, error):
        assert is_transient(error)

    @pytest.mark.parametrize(
        "error",
        [ConfigError("no key"), ProviderRefusal("declined"), ValueError("bad ticker")],
    )
    def test_permanent_failures_are_not(self, error):
        # Retrying these costs the caller the whole backoff and changes nothing.
        assert not is_transient(error)

    def test_an_unknown_exception_counts_as_transient(self):
        class Weird(Exception):
            pass

        # The deliberate direction to be wrong in: one wasted attempt beats a
        # lost job.
        assert is_transient(Weird())

    def test_the_kind_comes_from_the_taxonomy_when_there_is_one(self):
        assert error_kind(UpstreamDataError("x")) == "upstream_data"
        assert error_kind(ValueError("x")) == "ValueError"

    def test_a_described_error_does_not_leak_internals(self):
        assert describe(UpstreamDataError("EDGAR returned 503")) == "EDGAR returned 503"
        assert "ValueError" in describe(ValueError("bad"))

    def test_a_blank_message_still_says_something(self):
        assert describe(UpstreamDataError("")) == "UpstreamDataError"


class TestBackoff:
    def test_each_attempt_waits_longer(self):
        policy = RetryPolicy(base_seconds=1, max_seconds=100, multiplier=2)
        rng = _Always(1.0)
        assert [policy.delay(n, rng) for n in (1, 2, 3, 4)] == [1, 2, 4, 8]

    def test_it_stops_growing_at_the_ceiling(self):
        policy = RetryPolicy(base_seconds=1, max_seconds=5, multiplier=10)
        assert policy.delay(9, _Always(1.0)) == 5

    def test_jitter_spreads_the_herd(self):
        # Without it, every job that failed during one outage retries at the
        # same instant afterwards.
        policy = RetryPolicy(base_seconds=10, max_seconds=10)
        draws = {policy.delay(3) for _ in range(50)}
        assert len(draws) > 40
        assert all(0 <= d <= 10 for d in draws)

    def test_attempts_are_one_based(self):
        with pytest.raises(ValueError, match="1-based"):
            RetryPolicy().delay(0)

    @pytest.mark.parametrize(
        "kwargs",
        [{"base_seconds": 0}, {"base_seconds": -1}, {"max_seconds": 0.1}, {"multiplier": 0.5}],
    )
    def test_a_nonsense_policy_is_refused(self, kwargs):
        with pytest.raises(ValueError):
            RetryPolicy(**kwargs)


class _Always:
    """A deterministic stand-in for `random`, returning the ceiling."""

    def __init__(self, fraction: float) -> None:
        self.fraction = fraction

    def uniform(self, low: float, high: float) -> float:
        return low + (high - low) * self.fraction


# --------------------------------------------------------------------------- #
# Stores
# --------------------------------------------------------------------------- #


class TestStore:
    async def test_a_submitted_job_can_be_read_back(self, store):
        job = await store.submit(Job.new({"ticker": "AAPL"}))
        found = await store.get(job.id)
        assert found is not None
        assert found.state is JobState.QUEUED
        assert found.payload == {"ticker": "AAPL"}

    async def test_an_unknown_id_is_none(self, store):
        assert await store.get("nope") is None

    async def test_claiming_moves_it_to_running_and_counts_the_attempt(self, store):
        await store.submit(Job.new({"a": 1}))
        claimed = await store.claim("worker-1", 30)
        assert claimed is not None
        assert claimed.state is JobState.RUNNING
        assert claimed.attempts == 1
        assert claimed.claimed_by == "worker-1"

    async def test_two_workers_cannot_claim_the_same_job(self, store):
        await store.submit(Job.new({"a": 1}))
        first = await store.claim("worker-1", 30)
        second = await store.claim("worker-2", 30)
        assert first is not None
        assert second is None

    async def test_an_empty_queue_claims_nothing(self, store):
        assert await store.claim("worker-1", 30) is None

    async def test_completing_records_the_result(self, store):
        job = await store.submit(Job.new({"a": 1}))
        claimed = await store.claim("w", 30)
        done = await store.complete(claimed, {"answer": 42})
        assert done.state is JobState.SUCCEEDED
        assert (await store.get(job.id)).result == {"answer": 42}
        assert await store.pending() == 0

    async def test_a_retry_goes_back_on_the_queue_with_a_delay(self, store):
        await store.submit(Job.new({"a": 1}))
        claimed = await store.claim("w", 30)
        queued = await store.retry_later(claimed, 60.0, UpstreamDataError("503"))
        assert queued.state is JobState.QUEUED
        assert queued.available_at > queued.created_at
        assert queued.error_kind == "upstream_data"
        # Not claimable yet: it is sitting out its backoff.
        assert await store.claim("w", 30) is None

    async def test_failing_is_terminal(self, store):
        await store.submit(Job.new({"a": 1}))
        claimed = await store.claim("w", 30)
        dead = await store.fail(claimed, ConfigError("no provider"))
        assert dead.state is JobState.FAILED
        assert dead.state.terminal
        assert await store.pending() == 0

    async def test_a_dead_worker_loses_its_lease(self, store):
        # The reason a claim is a lease and not a removal: a worker that dies
        # mid-job must leave the work recoverable.
        await store.submit(Job.new({"a": 1}))
        claimed = await store.claim("doomed", lease_seconds=-1)
        assert claimed is not None
        assert await store.claim("healthy", 30) is None

        reclaimed = await store.reclaim_expired()
        assert reclaimed == [claimed.id]
        recovered = await store.claim("healthy", 30)
        assert recovered is not None
        assert recovered.attempts == 2

    async def test_a_live_lease_is_left_alone(self, store):
        await store.submit(Job.new({"a": 1}))
        await store.claim("busy", lease_seconds=300)
        assert await store.reclaim_expired() == []

    async def test_pending_counts_queued_and_running(self, store):
        await store.submit(Job.new({"a": 1}))
        await store.submit(Job.new({"b": 2}))
        assert await store.pending() == 2
        await store.claim("w", 30)
        assert await store.pending() == 2


class TestIdempotency:
    async def test_the_same_key_and_body_is_the_same_job(self, store):
        payload = {"ticker": "AAPL", "question": "risks?"}
        first = await store.submit(
            Job.new(payload, idempotency_key="k1", request_hash=fingerprint(payload))
        )
        second = await store.submit(
            Job.new(payload, idempotency_key="k1", request_hash=fingerprint(payload))
        )
        assert first.id == second.id
        assert await store.pending() == 1

    async def test_the_same_key_with_a_different_body_is_refused(self, store):
        one = {"ticker": "AAPL"}
        two = {"ticker": "MSFT"}
        await store.submit(Job.new(one, idempotency_key="k1", request_hash=fingerprint(one)))
        with pytest.raises(IdempotencyConflict, match="different request body"):
            await store.submit(Job.new(two, idempotency_key="k1", request_hash=fingerprint(two)))

    async def test_no_key_means_no_deduplication(self, store):
        payload = {"ticker": "AAPL"}
        a = await store.submit(Job.new(payload))
        b = await store.submit(Job.new(payload))
        assert a.id != b.id

    def test_the_fingerprint_ignores_key_order(self):
        assert fingerprint({"a": 1, "b": 2}) == fingerprint({"b": 2, "a": 1})

    def test_the_fingerprint_notices_a_changed_value(self):
        assert fingerprint({"ticker": "AAPL"}) != fingerprint({"ticker": "MSFT"})


# --------------------------------------------------------------------------- #
# Worker
# --------------------------------------------------------------------------- #


class TestWorker:
    async def test_a_successful_job_records_its_result(self, store):
        async def handler(payload):
            return {"echo": payload["q"]}

        worker = Worker(store, handler, policy=FAST)
        job = await store.submit(Job.new({"q": "hello"}))
        await drain(worker)
        final = await store.get(job.id)
        assert final.state is JobState.SUCCEEDED
        assert final.result == {"echo": "hello"}
        assert worker.stats.succeeded == 1

    async def test_a_transient_failure_is_retried_until_it_works(self, store):
        calls = {"n": 0}

        async def flaky(payload):
            calls["n"] += 1
            if calls["n"] < 3:
                raise UpstreamDataError("EDGAR 503")
            return {"ok": True}

        worker = Worker(store, flaky, policy=FAST)
        job = await store.submit(Job.new({"q": 1}))
        await drain(worker)
        final = await store.get(job.id)
        assert final.state is JobState.SUCCEEDED
        assert final.attempts == 3
        assert worker.stats.retried == 2

    async def test_a_permanent_failure_is_not_retried(self, store):
        async def broken(payload):
            raise ConfigError("no provider configured")

        worker = Worker(store, broken, policy=FAST)
        job = await store.submit(Job.new({"q": 1}))
        await drain(worker)
        final = await store.get(job.id)
        assert final.state is JobState.FAILED
        assert final.attempts == 1, "a permanent failure should not burn attempts"
        assert final.error == "no provider configured"

    async def test_a_transient_failure_still_gives_up_eventually(self, store):
        async def always(payload):
            raise UpstreamDataError("still down")

        worker = Worker(store, always, policy=FAST)
        job = await store.submit(Job.new({"q": 1}, max_attempts=3))
        await drain(worker)
        final = await store.get(job.id)
        assert final.state is JobState.FAILED
        assert final.attempts == 3

    async def test_an_idle_worker_returns_nothing_rather_than_blocking(self, store):
        async def handler(payload):
            return {}

        assert await Worker(store, handler).run_once() is None

    async def test_the_loop_survives_a_handler_that_raises_anything(self, store):
        async def hostile(payload):
            raise BaseExceptionGroup("weird", [ValueError("nested")])

        worker = Worker(store, hostile, policy=FAST)
        await store.submit(Job.new({"q": 1}, max_attempts=1))
        await drain(worker)
        assert worker.stats.failed == 1

    async def test_start_and_stop_are_clean(self, store):
        seen = asyncio.Event()

        async def handler(payload):
            seen.set()
            return {"ok": True}

        worker = Worker(store, handler, policy=FAST)
        worker.start()
        await store.submit(Job.new({"q": 1}))
        await asyncio.wait_for(seen.wait(), timeout=5)
        await worker.stop()
        # Stopping twice must not raise: shutdown paths get called twice.
        await worker.stop()

    async def test_drain_waits_through_a_backoff(self, store):
        # An idle claim does not mean an empty queue. Returning at the first
        # idle tick stopped before any retry ran, which made a retrying job
        # look like a stalled one.
        calls = {"n": 0}

        async def flaky(payload):
            calls["n"] += 1
            if calls["n"] == 1:
                raise UpstreamDataError("once")
            return {"ok": True}

        worker = Worker(store, flaky, policy=RetryPolicy(base_seconds=0.02, max_seconds=0.03))
        job = await store.submit(Job.new({"q": 1}))
        assert await drain(worker) == 1
        assert (await store.get(job.id)).state is JobState.SUCCEEDED


class TestBuildJobStore:
    def test_no_redis_url_means_in_process(self):
        assert isinstance(build_job_store(None), InMemoryJobStore)
        assert isinstance(build_job_store(""), InMemoryJobStore)

    def test_a_redis_url_builds_the_redis_store(self):
        assert isinstance(build_job_store("redis://localhost:6379/0"), RedisJobStore)


class TestJobModel:
    def test_terminal_states_are_the_ones_that_stop(self):
        assert JobState.SUCCEEDED.terminal and JobState.FAILED.terminal
        assert JobState.CANCELLED.terminal
        assert not JobState.QUEUED.terminal and not JobState.RUNNING.terminal

    def test_a_job_round_trips_through_its_dict_form(self):
        job = Job.new({"ticker": "AAPL"}, idempotency_key="k", request_hash="h")
        assert Job.from_dict(job.to_dict()) == job

    def test_exhausted_compares_attempts_against_the_limit(self):
        assert not Job.new({}, attempts=2, max_attempts=3).exhausted
        assert Job.new({}, attempts=3, max_attempts=3).exhausted


class TestStandaloneWorker:
    """`python -m filing_intel.jobs`, the mode for scaling workers separately."""

    def test_it_refuses_to_start_without_redis(self, capsys):
        # The in-process queue is invisible to another process, so a standalone
        # worker pointed at it would sit idle forever looking healthy.
        from filing_intel.config import Settings
        from filing_intel.jobs.__main__ import serve

        settings = Settings(
            redis_url=None, sec_user_agent="tests/0.1 (tests@example.com)"
        )
        assert asyncio.run(serve(settings, concurrency=1)) == 2
        assert "needs FILING_INTEL_REDIS_URL" in capsys.readouterr().err

    def test_concurrency_below_one_is_refused(self, capsys):
        from filing_intel.jobs.__main__ import main

        assert main(["--concurrency", "0"]) == 2
        assert "at least 1" in capsys.readouterr().err

    def test_help_exits_cleanly(self):
        from filing_intel.jobs.__main__ import main

        with pytest.raises(SystemExit) as exit_info:
            main(["--help"])
        assert exit_info.value.code == 0

    async def test_many_workers_never_take_the_same_job(self, store):
        # The claim is a single atomic LMOVE on Redis, and a pop under the
        # event loop's single thread in memory. Either way, exactly once.
        handled: list[str] = []

        async def handler(payload):
            handled.append(payload["n"])
            await asyncio.sleep(0)
            return {"n": payload["n"]}

        for n in range(12):
            await store.submit(Job.new({"n": n}))

        workers = [Worker(store, handler, policy=FAST) for _ in range(4)]
        await asyncio.gather(*(drain(w) for w in workers))

        assert sorted(handled) == list(range(12))
        assert await store.pending() == 0


class TestWorkerShutdown:
    async def test_a_cancelled_job_goes_back_rather_than_burning_an_attempt(self, store):
        # Shutdown is not failure. The lease would recover the job eventually,
        # but only after the visibility timeout the caller is waiting through.
        started = asyncio.Event()

        async def slow(payload):
            started.set()
            await asyncio.sleep(30)
            return {}

        worker = Worker(store, slow, policy=FAST)
        job = await store.submit(Job.new({"q": 1}))
        worker.start()
        await asyncio.wait_for(started.wait(), timeout=5)
        await worker.stop()

        recovered = await store.get(job.id)
        assert recovered.state is JobState.QUEUED
        assert recovered.claimed_by is None

    async def test_stopping_a_worker_that_never_started_is_harmless(self, store):
        async def handler(payload):
            return {}

        await Worker(store, handler).stop()

    async def test_the_loop_keeps_going_when_the_store_misbehaves(self, store):
        # A store hiccup must not end the loop; the next tick should recover.
        calls = {"n": 0}
        original = store.claim

        async def flaky_claim(worker_id, lease_seconds):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ConnectionError("redis went away")
            return await original(worker_id, lease_seconds)

        store.claim = flaky_claim
        done = asyncio.Event()

        async def handler(payload):
            done.set()
            return {"ok": True}

        worker = Worker(store, handler, policy=FAST, idle_sleep=0.005)
        await store.submit(Job.new({"q": 1}))
        worker.start()
        await asyncio.wait_for(done.wait(), timeout=5)
        await worker.stop()
        assert calls["n"] >= 2
