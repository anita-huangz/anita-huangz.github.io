#!/usr/bin/env python3
"""Build the browser payload and golden fixtures for the Yield Curve Lab demo.

Three files:

  curve.json            the curve itself, quantised to integer basis points and
                        delta-encoded, because 11,261 days x 9 tenors as plain
                        decimals is most of a megabyte of mostly-repeated digits
  curve-golden.json     answers computed by the Python engine, for the TypeScript
                        port to be checked against -- the port re-implements a
                        PCA, a bond price and a backtest, and "it looks about
                        right" is not a standard those can be held to
  curve-forecasts.json  the walk-forward XGBoost grid, precomputed. It cannot run
                        in a browser, and the result is a finding rather than a
                        control, so it ships as a result.

Run from the repository root:

    python site/scripts/generate_curve_demo.py
"""

from __future__ import annotations

import json
import sys
from itertools import pairwise
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "markets" / "yield-curve-lab" / "src"))


from curve_lab import load
from curve_lab.backtest import BacktestConfig, run_backtest
from curve_lab.data import TENORS
from curve_lab.pca import fit_factors
from curve_lab.predict import forecast_factor
from curve_lab.risk import summarise
from curve_lab.trades import (
    dv01_neutral_weights,
    factor_neutral_weights,
    par_bond_dv01,
    residual_risk,
)
from curve_lab.warehouse import open_warehouse

OUT = ROOT / "site" / "src" / "data" / "demos"
HORIZONS = (1, 5, 21, 63)


def delta_encode(values: list[int]) -> list[int]:
    """First value absolute, the rest first differences."""
    return [values[0]] + [b - a for a, b in pairwise(values)]


def write_curve(curve) -> dict:
    """The curve as integer basis points, delta-encoded per tenor."""
    basis_points = (curve.frame.to_numpy(dtype=float) * 100).round().astype(int)
    dates = curve.dates
    payload = {
        "tenors": curve.tenors,
        "labels": [f"{TENORS[t]:g}m" if TENORS[t] < 1 else f"{TENORS[t]:g}y" for t in curve.tenors],
        "maturities": [TENORS[t] for t in curve.tenors],
        "start": str(dates[0].date()),
        # Day offsets from `start`, delta-encoded: consecutive business days
        # are almost always 1 apart, so this compresses to mostly ones.
        "dayOffsets": delta_encode([int((d - dates[0]).days) for d in dates]),
        "yieldsBp": [delta_encode(basis_points[:, i].tolist()) for i in range(basis_points.shape[1])],
    }
    (OUT / "curve.json").write_text(json.dumps(payload, separators=(",", ":")))
    return payload


def write_golden(curve) -> None:
    """Reference answers the TypeScript port has to reproduce."""
    factors = fit_factors(curve)
    variances = factors.scores(curve.changes).var().to_numpy()

    flies = []
    for wings, belly in (
        (("DGS2", "DGS10"), "DGS5"),
        (("DGS1", "DGS5"), "DGS2"),
        (("DGS3MO", "DGS10"), "DGS2"),
        (("DGS5", "DGS30"), "DGS10"),
    ):
        for weighting in ("dv01", "factor"):
            fly = (
                dv01_neutral_weights(factors.tenors, wings, belly)
                if weighting == "dv01"
                else factor_neutral_weights(factors, wings, belly)
            )
            risk = residual_risk(fly, factors, variances)
            flies.append(
                {
                    "wings": list(wings),
                    "belly": belly,
                    "weighting": weighting,
                    "weights": [round(w, 10) for w in fly.weights.tolist()],
                    "netDv01": round(fly.net_dv01, 10),
                    "varianceShare": [round(v, 10) for v in risk.variance_share.tolist()],
                }
            )

    backtests = []
    cases = [
        ("2000-01-01", 21, 0.5, "dv01", "full"),
        ("2010-01-01", 5, 1.0, "dv01", "full"),
        # Both fittings of the factor model, because which one is used flips
        # the sign of this result -- see `fittedOn` below.
        ("2000-01-01", 21, 0.5, "factor", "full"),
        ("2000-01-01", 21, 0.5, "factor", "window"),
        ("1990-01-01", 21, 0.5, "factor", "window"),
    ]
    for start, rebalance, cost, weighting, fitted_on in cases:
        window = curve.slice(start, None)
        basis = factors if fitted_on == "full" else fit_factors(window)
        fly = (
            dv01_neutral_weights(basis.tenors, ("DGS2", "DGS10"), "DGS5")
            if weighting == "dv01"
            else factor_neutral_weights(basis, ("DGS2", "DGS10"), "DGS5")
        )
        result = run_backtest(window, fly, BacktestConfig(rebalance_days=rebalance, cost_bp=cost))
        performance = summarise(result.total)
        contribution = result.contribution()
        backtests.append(
            {
                "start": start,
                "rebalanceDays": rebalance,
                "costBp": cost,
                "weighting": weighting,
                "fittedOn": fitted_on,
                "days": performance.days,
                "total": round(performance.total, 8),
                "informationRatio": round(performance.information_ratio, 8),
                "maxDrawdown": round(performance.drawdown.depth, 8),
                "hitRate": round(performance.hit_rate, 8),
                "contribution": {k: round(float(v), 8) for k, v in contribution.items()},
            }
        )

    golden = {
        "factors": {
            "tenors": list(factors.tenors),
            "explained": [round(v, 10) for v in factors.explained.tolist()],
            "loadings": [[round(v, 10) for v in row] for row in factors.loadings.tolist()],
            "variances": [round(v, 12) for v in variances.tolist()],
        },
        "dv01": [
            {"yield": y, "maturity": m, "dv01": round(par_bond_dv01(y, m), 12)}
            for y, m in ((4.0, 2), (4.0, 5), (4.0, 10), (4.0, 30), (5.0, 0.25), (1.5, 7))
        ],
        "flies": flies,
        "backtests": backtests,
    }
    (OUT / "curve-golden.json").write_text(json.dumps(golden, separators=(",", ":")))


def write_forecasts(curve) -> None:
    """Walk-forward XGBoost across factors and horizons. The honest negative."""
    factors = fit_factors(curve)
    runs = []
    with open_warehouse(curve) as warehouse:
        for index in range(factors.n_components):
            for horizon in HORIZONS:
                forecast = forecast_factor(
                    warehouse, factors, curve.changes, factor_index=index,
                    horizon_days=horizon, folds=4,
                )
                statistic, p_value = forecast.diebold_mariano
                # A thinned scatter: enough to show the shape, not 8,000 points.
                step = max(1, len(forecast.actual) // 400)
                runs.append(
                    {
                        "factor": forecast.factor,
                        "horizonDays": horizon,
                        "r2": round(forecast.r2_vs_baseline, 6),
                        "directionalAccuracy": round(forecast.directional_accuracy, 6),
                        "dmStatistic": round(statistic, 4),
                        "dmPValue": round(p_value, 6),
                        "beatsBaseline": forecast.beats_baseline,
                        "nFeatures": forecast.n_features,
                        "testDays": len(forecast.actual),
                        "scatter": [
                            [round(float(a), 5), round(float(p), 5)]
                            for a, p in zip(
                                forecast.actual.to_numpy()[::step],
                                forecast.predicted.to_numpy()[::step],
                                strict=True,
                            )
                        ],
                    }
                )
                print(f"  {forecast.describe()}")
    (OUT / "curve-forecasts.json").write_text(
        json.dumps({"model": "XGBoost", "folds": 4, "runs": runs}, separators=(",", ":"))
    )


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    curve = load()
    print(f"curve: {len(curve):,} days x {len(curve.tenors)} tenors")

    write_curve(curve)
    write_golden(curve)
    print("forecast grid (this refits XGBoost 12 times):")
    write_forecasts(curve)

    for name in ("curve.json", "curve-golden.json", "curve-forecasts.json"):
        size = (OUT / name).stat().st_size
        print(f"  {name:<24}{size / 1024:8.1f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
