"""The command line: what moves the curve, what a fly really trades, what it earns."""

from __future__ import annotations

import argparse
import sys

from .backtest import BacktestConfig, run_backtest
from .carry import carry_and_roll
from .data import TENORS, SchemaError, load
from .intent import IntentError, Strategy, parse
from .pca import fit_factors
from .predict import XGBoostMissing, forecast_factor
from .regimes import fit_regimes
from .risk import summarise
from .spectrum import periodogram
from .trades import dv01_neutral_weights, factor_neutral_weights, residual_risk
from .warehouse import open_warehouse

SECTIONS = ("all", "factors", "trade", "backtest", "carry", "regimes", "cycles", "predict")


def _heading(text: str) -> None:
    print(f"\n{text}")
    print("-" * 74)


def factors_report(curve, factors) -> None:
    _heading("WHAT MOVES THE CURVE")
    for i in range(factors.n_components):
        print(
            f"  {factors.name(i):<10} {factors.explained[i]:6.2%}   "
            f"cumulative {factors.cumulative[i]:6.2%}"
        )
    print(f"\n  {'':<10}" + "".join(f"{t.replace('DGS', ''):>7}" for t in factors.tenors))
    for i in range(factors.n_components):
        print(f"  {factors.name(i):<10}" + "".join(f"{v:+7.2f}" for v in factors.loadings[i]))
    trough = factors.tenors[int(factors.loadings[2].argmin())]
    years = TENORS[trough]
    label = f"{years * 12:g}-month" if years < 1 else f"{years:g}-year"
    print(
        f"\n  Three shapes account for {factors.cumulative[2]:.1%} of every move the curve\n"
        f"  made. The curvature factor bends hardest at the {label}, which is where a\n"
        "  butterfly has to be centred to trade it."
    )


def trade_report(curve, factors, strategy: Strategy) -> None:
    _heading("WHAT A BUTTERFLY ACTUALLY TRADES")
    variances = factors.scores(curve.changes).var().to_numpy()
    flies = [
        dv01_neutral_weights(factors.tenors, strategy.wings, strategy.belly),
        factor_neutral_weights(factors, strategy.wings, strategy.belly),
    ]
    print(f"  {'construction':<28}{'level':>9}{'slope':>9}{'curvature':>11}{'net DV01':>11}")
    for fly in flies:
        risk = residual_risk(fly, factors, variances)
        shares = risk.variance_share
        print(
            f"  {fly.label:<28}{shares[0]:8.1%}{shares[1]:9.1%}{shares[2]:10.1%}"
            f"{fly.net_dv01:+11.3f}"
        )
    print(
        "\n  A DV01-neutral fly is neutral to a parallel shift. The curve does not\n"
        "  move in parallel shifts, so that is not the same as being neutral to\n"
        "  the shapes it does move in. Solving for the factor exposures directly\n"
        "  fixes that, and costs the DV01 neutrality it was sized for."
    )


def backtest_report(curve, factors, strategy: Strategy) -> None:
    _heading("WHAT IT EARNED")
    window = curve.slice(strategy.start, strategy.end)
    config = BacktestConfig(rebalance_days=strategy.rebalance_days, cost_bp=strategy.cost_bp)
    builder = (
        dv01_neutral_weights(factors.tenors, strategy.wings, strategy.belly)
        if strategy.weighting == "dv01"
        else factor_neutral_weights(factors, strategy.wings, strategy.belly)
    )
    result = run_backtest(window, builder, config)
    performance = summarise(result.total)

    print(f"  {strategy.describe()}")
    print(f"\n  {performance.describe()}")
    print(f"  hit rate {performance.hit_rate:.1%}, "
          f"annualised vol ${performance.annualised_volatility:,.0f}")
    drawdown = performance.drawdown
    recovered = (
        f"recovered {drawdown.recovered.date()}"
        if drawdown.recovered_fully
        else "never recovered"
    )
    print(f"  worst drawdown ${drawdown.depth:,.0f} from {drawdown.start.date()} "
          f"to {drawdown.trough.date()}, {recovered}")

    print("\n  where the money came from, in dollars per $1/bp of belly DV01:")
    for source, amount in result.contribution().items():
        print(f"    {source:<14}{amount:>12,.0f}")
    print(
        "\n  Carry and roll-down needed no view on rates. The directional line is\n"
        "  what the position earned for being right about direction."
    )


def carry_report(curve, strategy: Strategy) -> None:
    _heading("CARRY AND ROLL-DOWN, PER TENOR")
    window = curve.slice(strategy.start, strategy.end)
    print(f"  three-month horizon, averaged over {len(window):,} days")
    print(f"\n  {'tenor':<10}{'carry':>10}{'rolldown':>11}{'total':>10}   (bp of face)")
    for tenor in window.tenors:
        if TENORS[tenor] <= 0.25:
            continue
        summary = carry_and_roll(window, tenor, horizon_days=63).summary()
        print(
            f"  {tenor:<10}{summary['carry_bp']:>10.1f}{summary['rolldown_bp']:>11.1f}"
            f"{summary['total_bp']:>10.1f}"
        )


def regimes_report(curve) -> None:
    _heading("ARE THERE CURVE REGIMES?")
    for k in (2, 3, 4):
        print("  " + fit_regimes(curve, k=k, null_draws=10).describe())
    print(
        "\n  Tested against the same curves with each tenor shuffled independently,\n"
        "  which keeps every tenor's own distribution and destroys the joint shape."
    )


def cycles_report(curve, factors) -> None:
    _heading("ARE THERE CYCLES IN THE FACTORS?")
    scores = factors.scores(curve.changes)
    for name in scores.columns:
        spectrum = periodogram(scores[name], draws=200, family_size=len(scores.columns))
        print("  " + spectrum.describe())
    print(
        "\n  The threshold is the tallest peak white noise of the same length\n"
        "  produces, corrected for testing three factors at once. A periodogram\n"
        "  of pure noise is not flat, so the tallest bar is never the question."
    )


def predict_report(curve, factors) -> int:
    _heading("CAN THE FACTORS BE FORECAST?")
    try:
        with open_warehouse(curve) as warehouse:
            for index in range(factors.n_components):
                forecast = forecast_factor(
                    warehouse, factors, curve.changes, factor_index=index
                )
                print("  " + forecast.describe())
            print(f"\n  {forecast.n_features} features, walk-forward on an expanding window.")
    except XGBoostMissing as exc:
        print(f"  skipped: {exc}", file=sys.stderr)
        return 0
    print(
        "\n  The baseline predicts zero, because a factor score is already a change.\n"
        "  Beating it out of sample is the bar, and gradient boosting over sixty-six\n"
        "  features does not clear it."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", default=None, help="Curve snapshot (default: bundled).")
    parser.add_argument(
        "--strategy",
        default=None,
        help='Plain English, e.g. "factor-neutral 1s2s5s since 2010, weekly, 1bp".',
    )
    parser.add_argument("--section", choices=SECTIONS, default="all")
    parser.add_argument("--start", default=None, help="ISO date; overrides --strategy.")
    parser.add_argument("--end", default=None, help="ISO date; overrides --strategy.")
    args = parser.parse_args(argv)

    try:
        curve = load(args.csv) if args.csv else load()
        strategy = parse(args.strategy) if args.strategy else Strategy().validated()
    except (FileNotFoundError, SchemaError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except IntentError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.start or args.end:
        strategy = Strategy(
            wings=strategy.wings,
            belly=strategy.belly,
            weighting=strategy.weighting,
            rebalance_days=strategy.rebalance_days,
            cost_bp=strategy.cost_bp,
            start=args.start or strategy.start,
            end=args.end or strategy.end,
        ).validated()

    print(
        f"{len(curve):,} days x {len(curve.tenors)} tenors, "
        f"{curve.dates.min().date()} to {curve.dates.max().date()}"
    )
    factors = fit_factors(curve)
    want = args.section

    if want in {"all", "factors"}:
        factors_report(curve, factors)
    if want in {"all", "trade"}:
        trade_report(curve, factors, strategy)
    if want in {"all", "backtest"}:
        backtest_report(curve, factors, strategy)
    if want in {"all", "carry"}:
        carry_report(curve, strategy)
    if want in {"all", "regimes"}:
        regimes_report(curve)
    if want in {"all", "cycles"}:
        cycles_report(curve, factors)
    if want in {"all", "predict"}:
        predict_report(curve, factors)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
