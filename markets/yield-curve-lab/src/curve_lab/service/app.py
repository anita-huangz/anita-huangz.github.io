"""The quant engine over HTTP.

Thin on purpose: parse, delegate, serialise. Everything interesting lives in the
modules below this one, which is what lets the CLI, the browser port and this
service all produce the same numbers without any of them re-deriving anything.

Two things this can do that the static browser demo cannot, and they are the
reason it exists rather than the site being the whole story:

  * refit and score the walk-forward forecast on demand, for any factor and
    horizon -- XGBoost does not train in a browser
  * answer SQL against the warehouse, rather than shipping the whole curve to
    the client and re-deriving aggregates there

The curve is loaded once at startup and held. It is 11,261 immutable rows from
a committed file; re-reading it per request would be the only slow thing here
that did not need to be.
"""

# No `from __future__ import annotations` here, deliberately. FastAPI resolves
# a route's type hints against the *module* namespace, and the dependency alias
# below is defined inside `create_app`; as a string annotation it is invisible
# from module scope, and every route silently degrades to treating the engine
# as a missing query parameter.

from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

from ..backtest import BacktestConfig, run_backtest
from ..carry import carry_and_roll
from ..data import TENORS, Curve, SchemaError, load
from ..intent import IntentError, Strategy, parse
from ..pca import fit_factors
from ..predict import XGBoostMissing, forecast_factor
from ..risk import summarise
from ..spectrum import periodogram
from ..trades import dv01_neutral_weights, factor_neutral_weights, residual_risk
from ..warehouse import Warehouse, open_warehouse

#: Points kept when an equity curve is returned. 11,261 daily values is 300 KB
#: of JSON to draw a line a few hundred pixels wide.
CHART_POINTS = 600


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Window(Strict):
    start: str | None = Field(default=None, description="ISO date, inclusive.")
    end: str | None = Field(default=None, description="ISO date, inclusive.")


class TradeRequest(Window):
    wings: tuple[str, str] = ("DGS2", "DGS10")
    belly: str = "DGS5"
    weighting: Literal["dv01", "factor"] = "dv01"


class BacktestRequest(TradeRequest):
    rebalance_days: int = Field(default=21, ge=1, le=252)
    cost_bp: float = Field(default=0.5, ge=0.0, le=25.0)
    #: Fit the factor model on the whole history rather than the traded window.
    #: Worth a sign flip on the factor-neutral fly -- see the README.
    look_ahead: bool = False


class ForecastRequest(Window):
    factor: Literal["level", "slope", "curvature"] = "curvature"
    horizon_days: int = Field(default=5, ge=1, le=252)
    folds: int = Field(default=4, ge=2, le=10)


class ParseRequest(Strict):
    text: str = Field(min_length=1, max_length=500)


class Engine:
    """The curve, its warehouse and its whole-history factors, loaded once."""

    def __init__(self, curve: Curve) -> None:
        self.curve = curve
        self.factors = fit_factors(curve)
        self.warehouse: Warehouse = open_warehouse(curve)

    def close(self) -> None:
        self.warehouse.close()

    def window(self, start: str | None, end: str | None) -> Curve:
        sliced = self.curve.slice(start, end)
        if len(sliced) < 30:
            raise HTTPException(
                status_code=422,
                detail=f"{start or 'the start'} to {end or 'today'} leaves "
                f"{len(sliced)} days, which is too few to say anything about.",
            )
        return sliced

    def basis(self, window: Curve, look_ahead: bool):
        """Which factor model the weights are allowed to have been built from."""
        return self.factors if look_ahead else fit_factors(window)


def build_fly(basis, wings: tuple[str, str], belly: str, weighting: str):
    try:
        return (
            dv01_neutral_weights(basis.tenors, wings, belly)
            if weighting == "dv01"
            else factor_neutral_weights(basis, wings, belly)
        )
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def thin(values: list[Any], keep: int = CHART_POINTS) -> list[Any]:
    if len(values) <= keep:
        return values
    step = len(values) / keep
    return [values[int(i * step)] for i in range(keep)]


def create_app(curve: Curve | None = None) -> FastAPI:
    state: dict[str, Engine] = {}

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        state["engine"] = Engine(curve if curve is not None else load())
        try:
            yield
        finally:
            state.pop("engine").close()

    app = FastAPI(
        title="Yield Curve Lab",
        version="0.1.0",
        summary="Treasury curve factors, trade construction, backtests and forecasts.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        # The browser client is served from the same origin in Docker; these
        # are the Vite dev server's ports.
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    def engine() -> Engine:
        if "engine" not in state:  # pragma: no cover - only outside the lifespan
            raise HTTPException(status_code=503, detail="still starting up")
        return state["engine"]

    Injected = Annotated[Engine, Depends(engine)]

    @app.get("/health")
    def health(eng: Injected) -> dict[str, Any]:
        return {
            "status": "ok",
            "days": len(eng.curve),
            "tenors": eng.curve.tenors,
            "first": str(eng.curve.dates.min().date()),
            "last": str(eng.curve.dates.max().date()),
        }

    @app.get("/curve/summary")
    def curve_summary(eng: Injected) -> list[dict[str, Any]]:
        frame = eng.warehouse.summary()
        frame["first_date"] = frame["first_date"].astype(str)
        frame["last_date"] = frame["last_date"].astype(str)
        return frame.to_dict(orient="records")

    @app.get("/curve/spread")
    def curve_spread(
        eng: Injected,
        short: Annotated[str, Query()] = "DGS2",
        long: Annotated[str, Query()] = "DGS10",
    ) -> dict[str, Any]:
        for tenor in (short, long):
            if tenor not in TENORS:
                raise HTTPException(status_code=422, detail=f"unknown tenor {tenor!r}")
        frame = eng.warehouse.spread(short, long)
        return {
            "short": short,
            "long": long,
            "dates": [str(d) for d in thin(frame["date"].tolist())],
            "spreadBp": [round(v, 2) for v in thin(frame["spread_bp"].tolist())],
        }

    @app.post("/factors")
    def factors(eng: Injected, request: Window) -> dict[str, Any]:
        window = eng.window(request.start, request.end)
        fitted = fit_factors(window)
        return {
            "tenors": list(fitted.tenors),
            "maturities": fitted.maturities.tolist(),
            "names": [fitted.name(i) for i in range(fitted.n_components)],
            "explained": [round(v, 6) for v in fitted.explained.tolist()],
            "cumulative": [round(v, 6) for v in fitted.cumulative.tolist()],
            "loadings": [[round(v, 6) for v in row] for row in fitted.loadings.tolist()],
            "days": len(window),
        }

    @app.post("/trade")
    def trade(eng: Injected, request: TradeRequest) -> dict[str, Any]:
        window = eng.window(request.start, request.end)
        # The decomposition describes the whole history, as the write-up does.
        fly = build_fly(eng.factors, request.wings, request.belly, request.weighting)
        variances = eng.factors.scores(eng.curve.changes).var().to_numpy()
        risk = residual_risk(fly, eng.factors, variances)
        return {
            "label": fly.label,
            "weights": dict(zip(fly.tenors, [round(w, 6) for w in fly.weights], strict=True)),
            "netDv01": round(fly.net_dv01, 6),
            "factorNames": list(risk.factor_names),
            "exposure": [round(v, 6) for v in risk.exposure.tolist()],
            "varianceShare": [round(v, 6) for v in risk.variance_share.tolist()],
            "unintendedShare": round(risk.unintended_share, 6),
            "windowDays": len(window),
        }

    @app.post("/backtest")
    def backtest(eng: Injected, request: BacktestRequest) -> dict[str, Any]:
        window = eng.window(request.start, request.end)
        basis = eng.basis(window, request.look_ahead)
        fly = build_fly(basis, request.wings, request.belly, request.weighting)
        result = run_backtest(
            window,
            fly,
            BacktestConfig(rebalance_days=request.rebalance_days, cost_bp=request.cost_bp),
        )
        performance = summarise(result.total)
        drawdown = performance.drawdown
        return {
            "label": fly.label,
            "lookAhead": request.look_ahead,
            "days": performance.days,
            "total": round(performance.total, 4),
            "informationRatio": round(performance.information_ratio, 4),
            "annualisedVolatility": round(performance.annualised_volatility, 4),
            "hitRate": round(performance.hit_rate, 6),
            "maxDrawdown": round(drawdown.depth, 4),
            "drawdownStart": str(drawdown.start.date()),
            "drawdownTrough": str(drawdown.trough.date()),
            "recovered": str(drawdown.recovered.date()) if drawdown.recovered_fully else None,
            "contribution": {k: round(float(v), 4) for k, v in result.contribution().items()},
            "dates": [str(d.date()) for d in thin(list(result.pnl.index))],
            "equity": [round(v, 4) for v in thin(result.equity.tolist())],
        }

    @app.post("/carry")
    def carry(eng: Injected, request: Window) -> list[dict[str, Any]]:
        window = eng.window(request.start, request.end)
        rows = []
        for tenor in window.tenors:
            if TENORS[tenor] <= 0.25:
                continue
            summary = carry_and_roll(window, tenor, horizon_days=63).summary()
            rows.append({"tenor": tenor, **{k: round(v, 3) for k, v in summary.items()}})
        return rows

    @app.post("/forecast")
    def forecast(eng: Injected, request: ForecastRequest) -> dict[str, Any]:
        window = eng.window(request.start, request.end)
        fitted = fit_factors(window)
        index = [fitted.name(i) for i in range(fitted.n_components)].index(request.factor)
        try:
            with open_warehouse(window) as warehouse:
                result = forecast_factor(
                    warehouse,
                    fitted,
                    window.changes,
                    factor_index=index,
                    horizon_days=request.horizon_days,
                    folds=request.folds,
                )
        except XGBoostMissing as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        statistic, p_value = result.diebold_mariano
        pairs = [
            [round(float(a), 5), round(float(p), 5)]
            for a, p in zip(
                result.actual.to_numpy(), result.predicted.to_numpy(), strict=True
            )
        ]
        return {
            "factor": result.factor,
            "horizonDays": result.horizon_days,
            "r2VsBaseline": round(result.r2_vs_baseline, 6),
            "directionalAccuracy": round(result.directional_accuracy, 6),
            "dmStatistic": round(statistic, 4),
            "dmPValue": round(p_value, 6),
            "beatsBaseline": result.beats_baseline,
            "nFeatures": result.n_features,
            "testDays": len(result.actual),
            "scatter": thin(pairs, 400),
            "verdict": result.describe(),
        }

    @app.post("/cycles")
    def cycles(eng: Injected, request: Window) -> list[dict[str, Any]]:
        window = eng.window(request.start, request.end)
        fitted = fit_factors(window)
        scores = fitted.scores(window.changes)
        rows = []
        for name in scores.columns:
            spectrum = periodogram(scores[name], draws=150, family_size=len(scores.columns))
            rows.append(
                {
                    "factor": name,
                    "peakPeriodDays": round(spectrum.peak_period, 1),
                    "peakPower": round(spectrum.peak_power, 3),
                    "threshold": round(spectrum.threshold, 3),
                    "hasCycle": spectrum.has_cycle,
                    "verdict": spectrum.describe(),
                }
            )
        return rows

    @app.post("/strategy/parse")
    def strategy_parse(request: ParseRequest) -> dict[str, Any]:
        """Plain English to the same validated object every other route takes."""
        try:
            strategy: Strategy = parse(request.text)
        except IntentError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "wings": list(strategy.wings),
            "belly": strategy.belly,
            "weighting": strategy.weighting,
            "rebalanceDays": strategy.rebalance_days,
            "costBp": strategy.cost_bp,
            "start": strategy.start,
            "end": strategy.end,
            "describe": strategy.describe(),
        }

    @app.exception_handler(SchemaError)
    def _schema_error(_: Any, exc: SchemaError):  # pragma: no cover - defensive
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return app


@lru_cache(maxsize=1)
def app() -> FastAPI:
    """Entry point for `uvicorn curve_lab.service.app:app --factory`."""
    return create_app()
