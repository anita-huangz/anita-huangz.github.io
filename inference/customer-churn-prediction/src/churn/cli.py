"""Run the analysis and print it.

`churn report` reproduces every number in the README, so the claims there can
be checked rather than taken on trust.
"""

from __future__ import annotations

import argparse
import sys

import numpy as np
from sklearn.metrics import roc_auc_score

from .calibration import brier_skill_score, expected_calibration_error, reliability_curve
from .classify import (
    bootstrap_interval,
    cross_validated_probabilities,
    honest_holdout_score,
    leaky_holdout_score,
    models,
)
from .data import cox_design_matrix, load
from .economics import (
    Campaign,
    best_threshold,
    customer_value,
    expected_months_remaining,
    expected_value_curve,
    targeting_comparison,
)
from .survival import (
    concordance_index,
    fit_cox,
    kaplan_meier,
    log_rank_test,
    proportional_hazards_test,
)

RULE = "-" * 74


def _heading(text: str) -> None:
    print(f"\n{text}\n{RULE}")


def survival_report(data) -> None:
    _heading("SURVIVAL — what a classifier cannot see")
    km = kaplan_meier(data.duration, data.event)
    print(f"  {len(data):,} customers, {data.censoring_rate:.1%} still subscribed at the cutoff.")
    print("  Their eventual lifetime is unknown, not 'no churn'.")
    print()
    for t in (6, 12, 24, 36, 60):
        lo, hi = km.confidence_interval()
        i = np.searchsorted(km.times, t, "right") - 1
        print(f"    S({t:>2} months) = {km.predict(t)[0]:.3f}   95% CI [{lo[i]:.3f}, {hi[i]:.3f}]")
    median = km.median_survival
    print()
    reached = "never reached inside the window" if median == float("inf") else median
    print(f"  median lifetime: {reached}")
    print(f"  expected months retained over 5 years: {km.restricted_mean(60):.1f}")

    lr = log_rank_test(data.duration, data.event, data.frame.Contract.to_numpy())
    print(
        f"\n  contract type separates the curves: "
        f"chi2 = {lr.statistic:,.0f}, p = {lr.p_value:.2e}"
    )
    for contract in ["Month-to-month", "One year", "Two year"]:
        mask = (data.frame.Contract == contract).to_numpy()
        curve = kaplan_meier(data.duration[mask], data.event[mask])
        print(f"    {contract:<16} n={mask.sum():>5}  S(24) = {curve.predict(24)[0]:.3f}")


def cox_report(data) -> None:
    _heading("COX REGRESSION — how much, and for how long")
    X = cox_design_matrix(data)
    model = fit_cox(X, data.duration, data.event)
    c_index = concordance_index(model.risk_score(X), data.duration, data.event)
    print(f"  {X.shape[1]} covariates, converged in {model.iterations} iterations.")
    print(f"  concordance index: {c_index:.4f}")
    print("\n  strongest effects (hazard ratio = multiplier on the monthly risk of leaving):")
    summary = model.summary().head(8)
    for name, row in summary.iterrows():
        print(
            f"    {name:<34} {row.hazard_ratio:>6.3f}  "
            f"[{row.hr_lower:.3f}, {row.hr_upper:.3f}]  p={row.p:.1e}"
        )

    test = proportional_hazards_test(model, X, data.duration, data.event)
    print(
        f"\n  proportional-hazards assumption: {'holds' if test.holds else 'FAILS'} "
        f"for {len(test.violations)} of {len(model.names)} covariates."
    )
    print("  Those hazard ratios are averages over effects that change with tenure.")
    return model, X


class OutOfFold:
    """Out-of-fold probabilities, computed once per model for the whole run.

    Three sections want the same two logistic fits, and each one is a full
    five-fold cross-validation over 7,043 rows -- half this command's runtime
    went on recomputing them. The estimator, the split and the seed are all
    fixed, so the repeats were bit-identical; this returns the first answer
    rather than deriving it again.

    Scoped to one dataset deliberately. A cache keyed on the model alone would
    hand back another dataset's predictions the moment `--csv` was used.
    """

    def __init__(self, data) -> None:
        self._data = data
        self._cache: dict[str, np.ndarray] = {}

    def __call__(self, estimator) -> np.ndarray:
        key = repr(estimator)
        if key not in self._cache:
            self._cache[key] = cross_validated_probabilities(self._data, estimator)
        return self._cache[key]

    @property
    def fits(self) -> int:
        """How many cross-validations actually ran. For tests."""
        return len(self._cache)


def classification_report(data, out_of_fold) -> None:
    _heading("CLASSIFICATION — and what the notebook's shortcuts were worth")
    leaky = leaky_holdout_score(data, models()["logistic"].__class__(max_iter=2000))
    honest = honest_holdout_score(data, models()["logistic"])
    print(f"  one 80/20 split, scaler fitted on everything : AUC {leaky:.4f}")
    print(f"  one 80/20 split, scaler fitted on train only : AUC {honest:.4f}")
    print(f"  the leak was worth                           : {leaky - honest:+.4f}")

    print("\n  5-fold out-of-fold, preprocessing inside the pipeline:")
    for name, estimator in models().items():
        p = out_of_fold(estimator)
        point, lo, hi = bootstrap_interval(roc_auc_score, data.event, p, draws=300)
        print(f"    {name:<20} AUC {point:.4f}  95% CI [{lo:.4f}, {hi:.4f}]")
    print("\n  The single split scored higher than the cross-validated interval")
    print("  contains. The optimism came from the split, not the leak.")


def calibration_report(data, out_of_fold) -> None:
    _heading("CALIBRATION — does 0.7 mean 70%?")
    for label, weight in (("class_weight='balanced'", "balanced"), ("unweighted", None)):
        p = out_of_fold(models(class_weight=weight)["logistic"])
        print(
            f"  {label:<24} AUC {roc_auc_score(data.event, p):.4f}  "
            f"mean predicted {p.mean():.3f} vs actual {data.event.mean():.3f}  "
            f"ECE {expected_calibration_error(p, data.event):.4f}  "
            f"skill {brier_skill_score(p, data.event):+.4f}"
        )
    print("\n  Rebalancing changed the ranking by 0.0001 of AUC and made the")
    print("  probabilities about twice too large. SMOTE does the same thing.")
    p = out_of_fold(models()["logistic"])
    curve = reliability_curve(p, data.event)
    print("\n  the balanced model's reliability:")
    for predicted, observed, count in zip(
        curve.predicted, curve.observed, curve.count, strict=True
    ):
        if count:
            print(f"    says {predicted:.2f} -> actually {observed:.2f}   (n={count})")


def decision_report(data, cox, X, probability, campaign: Campaign) -> None:
    _heading("THE DECISION — who to call, and whether to call at all")
    grid = np.arange(1, 73, dtype=float)
    months = expected_months_remaining(
        cox.predict_survival(X, grid), grid, campaign.horizon_months
    )
    value = customer_value(data.frame.MonthlyCharges.to_numpy(float), months, campaign)
    print(
        f"  assumptions: ${campaign.offer_cost:.0f} per offer, "
        f"{campaign.acceptance:.0%} accept, {campaign.margin:.0%} margin, "
        f"{campaign.horizon_months:.0f}-month horizon"
    )
    print(
        f"  value at stake: median ${np.median(value):,.0f}, "
        f"max ${value.max():,.0f} (from each customer's own survival curve)"
    )

    curve = expected_value_curve(probability, data.event, value, campaign)
    best = best_threshold(curve)
    half = min(curve, key=lambda r: abs(r.threshold - 0.5))
    print(
        f"\n  best threshold {best.threshold:.2f}: call {best.targeted:,}, "
        f"net ${best.expected_value:,.0f}"
    )
    print(
        f"  default 0.50   : call {half.targeted:,}, net ${half.expected_value:,.0f}"
        f"   (${best.expected_value - half.expected_value:,.0f} left on the table)"
    )

    budget = 1000
    print(f"\n  same budget of {budget:,} calls, three policies:")
    for name, net in targeting_comparison(
        probability, data.event, value, campaign, budget=budget
    ).items():
        print(f"    {name:<20} ${net:>10,.0f}")
    print("\n  Ranking by probability x value beats ranking by probability alone.")
    print("  The value term needs expected remaining months, which is the")
    print("  survival model's answer and not something a classifier has.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", default=None, help="Dataset path (default: bundled).")
    parser.add_argument("--offer-cost", type=float, default=30.0)
    parser.add_argument("--acceptance", type=float, default=0.30)
    parser.add_argument("--margin", type=float, default=0.30)
    parser.add_argument("--horizon", type=float, default=24.0)
    parser.add_argument(
        "--section",
        choices=["all", "survival", "cox", "classification", "calibration", "decision"],
        default="all",
    )
    args = parser.parse_args(argv)

    try:
        data = load(args.csv) if args.csv else load()
        campaign = Campaign(
            offer_cost=args.offer_cost,
            acceptance=args.acceptance,
            margin=args.margin,
            horizon_months=args.horizon,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    out_of_fold = OutOfFold(data)

    want = args.section
    if want in {"all", "survival"}:
        survival_report(data)
    if want in {"all", "cox", "decision"}:
        cox, X = cox_report(data)
    if want in {"all", "classification"}:
        classification_report(data, out_of_fold)
    if want in {"all", "calibration"}:
        calibration_report(data, out_of_fold)
    if want in {"all", "decision"}:
        probability = out_of_fold(models(class_weight=None)["logistic"])
        decision_report(data, cox, X, probability, campaign)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
