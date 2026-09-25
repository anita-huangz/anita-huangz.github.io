"""HTTP surface.

Thin: parse, delegate to the runtime, serialize. The interesting behaviour lives
below this layer, which is the point -- the MCP server reaches the same runtime
without duplicating any of it.
"""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from ..config import Settings, get_settings
from ..contracts import ResearchRequest, ResearchResponse, Strict
from ..errors import ConfigError, FilingIntelError, UpstreamDataError
from ..jobs import (
    IdempotencyConflict,
    Job,
    JobStore,
    Worker,
    build_job_store,
    fingerprint,
)
from ..runtime import FilingIntelRuntime
from ..telemetry import TelemetrySummary
from .limits import SlidingWindowLimiter, enforce


class HealthResponse(Strict):
    status: str
    provider: str
    model: str
    cache: str
    tools: list[str]


class SessionResponse(Strict):
    session_id: str
    ticker: str | None
    turns: int
    estimated_cost_usd: float


class JobResponse(Strict):
    """A submitted job. `result` is populated once the state is `succeeded`."""

    id: str
    state: str
    attempts: int
    max_attempts: int
    created_at: float
    updated_at: float
    result: dict[str, Any] | None = None
    error: str | None = None
    error_kind: str | None = None


def _job_response(job: Job) -> JobResponse:
    return JobResponse(
        id=job.id,
        state=str(job.state),
        attempts=job.attempts,
        max_attempts=job.max_attempts,
        created_at=job.created_at,
        updated_at=job.updated_at,
        result=job.result,
        error=job.error,
        error_kind=job.error_kind,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    runtime = FilingIntelRuntime.build(app.state.settings)
    app.state.runtime = runtime

    store = build_job_store(app.state.settings.redis_url)
    app.state.job_store = store

    async def handle(payload: dict[str, Any]) -> dict[str, Any]:
        # Resolved per call rather than captured, so the worker always uses the
        # runtime currently installed on the app. That is what lets a test swap
        # in a scripted provider and have the queue exercise the real path.
        current: FilingIntelRuntime = app.state.runtime
        response = await current.research(ResearchRequest.model_validate(payload))
        return response.model_dump(mode="json")

    worker = Worker(store, handle)
    app.state.worker = worker
    # In-process rather than a separate container: one deployable is the right
    # default at this size, and `python -m filing_intel.jobs` runs the same
    # worker standalone against the same Redis when that stops being true.
    worker.start()
    try:
        yield
    finally:
        await worker.stop()
        await runtime.aclose()


def get_runtime(request: Request) -> FilingIntelRuntime:
    return request.app.state.runtime


#: FastAPI's modern dependency form. Using Annotated rather than a `Depends`
#: default keeps the signatures honest and avoids a call in a default arg.
Runtime = Annotated[FilingIntelRuntime, Depends(get_runtime)]


def get_job_store(request: Request) -> JobStore:
    return request.app.state.job_store


Jobs = Annotated[JobStore, Depends(get_job_store)]


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(
        title="SEC Filing Intelligence",
        version="0.1.0",
        description=(
            "A multi-agent research service over SEC EDGAR filings, with "
            "per-call token, cost, and latency telemetry."
        ),
        lifespan=lifespan,
    )
    app.state.settings = settings or get_settings()

    if app.state.settings.public_demo and app.state.settings.provider != "demo":
        raise ConfigError(
            "public_demo=true requires provider=demo. A publicly reachable "
            f"instance on provider={app.state.settings.provider!r} would let "
            "anyone spend real model credits."
        )

    limiter = SlidingWindowLimiter(
        limit=app.state.settings.rate_limit_per_minute, window_seconds=60.0
    )

    # The browser UI is served from a different origin in development.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=app.state.settings.cors_origins,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["*"],
    )

    @app.exception_handler(FilingIntelError)
    async def _domain_error(_: Request, exc: FilingIntelError) -> JSONResponse:
        # Upstream data problems are the caller's problem (bad ticker, no such
        # filing); everything else is ours.
        status = 502 if isinstance(exc, UpstreamDataError) else 500
        if isinstance(exc, UpstreamDataError) and "no SEC registrant" in str(exc):
            status = 404
        return JSONResponse(
            status_code=status, content={"error": str(exc), "kind": exc.kind}
        )

    @app.get("/healthz", response_model=HealthResponse)
    async def healthz(runtime: Runtime) -> HealthResponse:
        cache_ok = await runtime.cache.ping()
        return HealthResponse(
            status="ok",
            provider=getattr(runtime.provider, "name", "unknown"),
            model=runtime.settings.model,
            cache="ok" if cache_ok else "degraded",
            tools=runtime.registry.names,
        )

    @app.post("/v1/research", response_model=ResearchResponse)
    async def research(
        body: ResearchRequest, request: Request, runtime: Runtime
    ) -> ResearchResponse:
        enforce(limiter, request)
        return await runtime.research(body)

    @app.post("/v1/research/jobs", response_model=JobResponse, status_code=202)
    async def submit_research(
        body: ResearchRequest,
        request: Request,
        response: Response,
        jobs: Jobs,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> JobResponse:
        """Queue a research run and return immediately.

        A research call takes about nine seconds against a live model. This
        hands back a job id in milliseconds and lets the caller poll, which
        decouples their timeout from the model's latency and survives them
        disconnecting.

        `Idempotency-Key` makes a retried submission safe: the same key returns
        the same job rather than running the work twice. The same key with a
        *different* body is a client bug and gets a 409 -- answering it with the
        first request's result would be answering a question nobody asked.
        """
        enforce(limiter, request)
        payload = body.model_dump(mode="json")
        job = Job.new(
            payload,
            idempotency_key=idempotency_key,
            request_hash=fingerprint(payload),
        )
        try:
            stored = await jobs.submit(job)
        except IdempotencyConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        response.headers["Location"] = f"/v1/research/jobs/{stored.id}"
        return _job_response(stored)

    @app.get("/v1/research/jobs/{job_id}", response_model=JobResponse)
    async def get_research_job(job_id: str, jobs: Jobs) -> JobResponse:
        job = await jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"no job {job_id}")
        return _job_response(job)

    @app.get("/v1/research/stream")
    async def research_stream(request: Request, runtime: Runtime, ticker: str,
                              question: str,
                              session_id: str | None = None) -> StreamingResponse:
        """Server-sent events, one per completed graph node.

        Query parameters rather than a body because EventSource only issues
        GET requests. Validation still goes through ResearchRequest, so a bad
        ticker fails here exactly as it does on the POST route.
        """
        enforce(limiter, request)
        try:
            body = ResearchRequest(
                ticker=ticker, question=question, session_id=session_id
            )
        except ValidationError as exc:
            # Hand-built from query params, so Pydantic's error does not reach
            # FastAPI's own handler. Convert it to the same 422 the POST gives.
            raise RequestValidationError(exc.errors()) from exc

        async def emit():
            try:
                async for event in runtime.research_stream(body):
                    payload = json.dumps(event["data"], default=str)
                    yield f"event: {event['event']}\ndata: {payload}\n\n"
            except Exception as exc:
                detail = json.dumps({"message": f"{type(exc).__name__}: {exc}"})
                yield f"event: error\ndata: {detail}\n\n"
            finally:
                yield "event: close\ndata: {}\n\n"

        return StreamingResponse(
            emit(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                # Proxies that buffer will defeat the point of streaming.
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/v1/sessions/{session_id}", response_model=SessionResponse)
    async def get_session(
        session_id: str, runtime: Runtime
    ) -> SessionResponse:
        session = await runtime.sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="no such session")
        return SessionResponse(
            session_id=session.session_id,
            ticker=session.ticker,
            turns=session.turns,
            estimated_cost_usd=session.estimated_cost_usd,
        )

    @app.delete("/v1/sessions/{session_id}", status_code=204)
    async def delete_session(
        session_id: str, runtime: Runtime
    ) -> None:
        await runtime.sessions.delete(session_id)

    @app.get("/v1/telemetry/summary", response_model=TelemetrySummary)
    async def telemetry_summary(
        runtime: Runtime,
    ) -> TelemetrySummary:
        return runtime.telemetry_summary()

    @app.get("/v1/telemetry/events")
    async def telemetry_events(
        runtime: Runtime, limit: int = 100
    ) -> dict[str, Any]:
        events = runtime.telemetry.events[-limit:]
        return {
            "count": len(events),
            "events": [e.model_dump(mode="json") for e in events],
        }

    @app.get("/v1/tools")
    async def list_tools(runtime: Runtime) -> dict[str, Any]:
        from ..contracts import Capability

        return {
            "tools": [
                spec.model_dump() for spec in runtime.registry.specs_for(list(Capability))
            ]
        }

    _mount_ui(app)
    return app


def _ui_dist() -> Path | None:
    """Locate the built UI: an explicit override, the image path, or the repo.

    Three candidates because the package runs from a source checkout in
    development and from site-packages inside the container, where a path
    relative to __file__ would point into site-packages instead of the app.
    """
    override = os.environ.get("FILING_INTEL_UI_DIST")
    candidates = [
        Path(override) if override else None,
        Path("/app/web/dist"),
        Path(__file__).resolve().parents[3] / "web" / "dist",
    ]
    for candidate in candidates:
        if candidate is not None and (candidate / "index.html").exists():
            return candidate
    return None


def _mount_ui(app: FastAPI) -> None:
    """Serve the built React app at / when a build is present.

    Optional by design: the API is useful headless, and the tests and the MCP
    server never need the UI. Mounted last so it cannot shadow an API route.
    """
    dist = _ui_dist()
    if dist is None:
        return

    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(dist / "index.html")


app = create_app()
