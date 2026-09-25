"""Run the worker on its own:  python -m filing_intel.jobs

The API starts a worker in-process, which is the right default at this size:
one deployable, no second thing to forget to run. It stops being right as soon
as the queue is shared, because research is CPU-and-network bound and workers
should scale separately from the HTTP surface.

This is that second mode. Point it at the same Redis the API uses and run as
many as the upstream rate limits will bear; the claim is a single atomic
`LMOVE`, so workers cannot take the same job.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from typing import Any

from ..config import Settings
from ..contracts import ResearchRequest
from ..runtime import FilingIntelRuntime
from .store import build_job_store
from .worker import Worker

logger = logging.getLogger("filing_intel.jobs")


async def serve(settings: Settings, concurrency: int) -> int:
    if not settings.redis_url:
        print(
            "error: a standalone worker needs FILING_INTEL_REDIS_URL. Without it "
            "the queue is in-process and only the API's own worker can see it.",
            file=sys.stderr,
        )
        return 2

    runtime = FilingIntelRuntime.build(settings)
    store = build_job_store(settings.redis_url)

    async def handle(payload: dict[str, Any]) -> dict[str, Any]:
        response = await runtime.research(ResearchRequest.model_validate(payload))
        return response.model_dump(mode="json")

    workers = [Worker(store, handle) for _ in range(concurrency)]
    stopping = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        # Finish the job in hand rather than dropping it: the lease would
        # recover it, but only after the visibility timeout the caller is
        # waiting through.
        loop.add_signal_handler(sig, stopping.set)

    for worker in workers:
        worker.start()
    logger.info("%d worker(s) against %s", concurrency, settings.redis_url)

    await stopping.wait()
    logger.info("draining")
    for worker in workers:
        await worker.stop()
    await runtime.aclose()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Workers in this process. Each claims independently (default: %(default)s).",
    )
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)
    logging.basicConfig(level=args.log_level.upper(), format="%(levelname)s %(message)s")
    if args.concurrency < 1:
        print("error: --concurrency must be at least 1", file=sys.stderr)
        return 2
    return asyncio.run(serve(Settings(), args.concurrency))


if __name__ == "__main__":
    raise SystemExit(main())
