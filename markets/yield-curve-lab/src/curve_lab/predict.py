"""Can the curve factors be forecast? Measured against the only honest baseline.

The baseline is a random walk: predict that tomorrow's factor score is zero,
because a factor score *is* a change and its unconditional mean is
approximately zero. That is a low bar in the sense that it requires no data,
and a high bar in the sense that decades of published work have struggled to
clear it out of sample.

Everything here is walk-forward. The model is refit on an expanding window and
scored only on days after the window ends, so no fold ever sees its own future.
That matters more than the model choice: a shuffled split on a time series
leaks tomorrow into today's training set and will report a skill that does not
exist. `sklearn`'s default `cross_val_score` shuffles.

Scoring uses three numbers because they can disagree. Out-of-sample R-squared
against the baseline says whether the errors are smaller. Directional accuracy
says whether the sign is right, which is what a trade needs. And the paired
t-statistic on the squared-error difference says whether any of it is
distinguishable from luck -- a model can post a positive R-squared on 1,000
days and still be a coin flip.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats

from .pca import CurveFactors
from .warehouse import Warehouse

#: Days ahead to forecast. One week: short enough that the factor has not
#: mean-reverted away, long enough that bid-offer does not eat the signal.
DEFAULT_HORIZON = 5


class XGBoostMissing(RuntimeError):
    """XGBoost is an optional extra; the rest of the package does not need it."""


@dataclass(frozen=True)
class Forecast:
    """Walk-forward predictions against a random-walk baseline."""

    factor: str
    horizon_days: int
    actual: pd.Series
    predicted: pd.Series
    baseline: pd.Series
    folds: int
    n_features: int

    @property
    def model_mse(self) -> float:
        return float(((self.actual - self.predicted) ** 2).mean())

    @property
    def baseline_mse(self) -> float:
        return float(((self.actual - self.baseline) ** 2).mean())

    @property
    def r2_vs_baseline(self) -> float:
        """Out-of-sample R-squared against the random walk. Negative is worse."""
        if self.baseline_mse == 0:
            return 0.0
        return 1.0 - self.model_mse / self.baseline_mse

    @property
    def directional_accuracy(self) -> float:
        """Share of days the predicted sign matched. A coin flip is 0.5."""
        moved = self.actual != 0
        if not moved.any():
            return 0.0
        return float((np.sign(self.predicted[moved]) == np.sign(self.actual[moved])).mean())

    @property
    def diebold_mariano(self) -> tuple[float, float]:
        """Paired test on squared-error differences: (t-statistic, p-value).

        Positive t means the model's errors are *larger* than the baseline's.
        The series is autocorrelated because forecasts overlap, so this
        overstates significance; it is reported as a sanity check, not as
        proof, and the README says so.
        """
        difference = (self.actual - self.predicted) ** 2 - (self.actual - self.baseline) ** 2
        if difference.std(ddof=1) == 0:
            return 0.0, 1.0
        result = stats.ttest_1samp(difference, 0.0)
        return float(result.statistic), float(result.pvalue)

    @property
    def beats_baseline(self) -> bool:
        """Lower error *and* not explainable as noise at the 5% level."""
        statistic, p_value = self.diebold_mariano
        return self.r2_vs_baseline > 0 and statistic < 0 and p_value < 0.05

    def describe(self) -> str:
        statistic, p_value = self.diebold_mariano
        verdict = "beats" if self.beats_baseline else "does not beat"
        return (
            f"{self.factor} at {self.horizon_days}d: out-of-sample R2 "
            f"{self.r2_vs_baseline:+.4f}, directional accuracy "
            f"{self.directional_accuracy:.1%}, DM t {statistic:+.2f} "
            f"(p {p_value:.3f}) -- {verdict} a random walk"
        )


def feature_matrix(warehouse: Warehouse, factors: CurveFactors) -> pd.DataFrame:
    """Per-day features: every tenor's lags, its vol, and the factor scores.

    The SQL returns one row per tenor per day; pivoting to one row per day is
    what makes it a design matrix. Column names carry the tenor so a feature
    importance is readable afterwards.
    """
    long = warehouse.features()
    long["date"] = pd.to_datetime(long["date"])
    measures = [c for c in long.columns if c not in {"date", "tenor", "maturity"}]
    wide = long.pivot(index="date", columns="tenor", values=measures)
    wide.columns = [f"{measure}_{tenor}" for measure, tenor in wide.columns]

    # Spreads: the curve's shape, which per-tenor levels do not express.
    curve_levels = long.pivot(index="date", columns="tenor", values="yield")
    for short, long_tenor in (("DGS2", "DGS10"), ("DGS3MO", "DGS2"), ("DGS5", "DGS30")):
        if short in curve_levels and long_tenor in curve_levels:
            wide[f"spread_{short}_{long_tenor}"] = (
                curve_levels[long_tenor] - curve_levels[short]
            ) * 100.0
    return wide.sort_index().dropna()


def walk_forward(
    features: pd.DataFrame,
    target: pd.Series,
    folds: int = 5,
    min_train: int = 1000,
    model=None,
) -> tuple[pd.Series, pd.Series]:
    """Expanding-window predictions. Returns (predicted, actual) on test days only."""
    aligned = features.join(target.rename("__target__"), how="inner").dropna()
    if len(aligned) < min_train + folds:
        raise ValueError(
            f"{len(aligned)} usable rows is not enough for {folds} folds "
            f"after a {min_train}-row initial training window"
        )
    X = aligned.drop(columns="__target__")
    y = aligned["__target__"]

    test_start = max(min_train, len(aligned) // (folds + 1))
    boundaries = np.linspace(test_start, len(aligned), folds + 1).astype(int)

    predictions = []
    for fold in range(folds):
        train_end, test_end = boundaries[fold], boundaries[fold + 1]
        if test_end <= train_end:
            continue
        estimator = _clone_or_default(model)
        estimator.fit(X.iloc[:train_end], y.iloc[:train_end])
        predictions.append(
            pd.Series(
                estimator.predict(X.iloc[train_end:test_end]),
                index=X.index[train_end:test_end],
            )
        )
    predicted = pd.concat(predictions)
    return predicted, y.loc[predicted.index]


def _clone_or_default(model):
    from sklearn.base import clone

    if model is not None:
        return clone(model)
    try:
        from xgboost import XGBRegressor
    except ImportError as exc:  # pragma: no cover - exercised via the CLI path
        raise XGBoostMissing(
            "XGBoost is not installed. `pip install -e '.[predict]'`, or pass "
            "your own estimator to walk_forward(model=...)."
        ) from exc
    return XGBRegressor(
        n_estimators=300,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_lambda=1.0,
        random_state=0,
        n_jobs=-1,
    )


def forecast_factor(
    warehouse: Warehouse,
    factors: CurveFactors,
    curve_changes: pd.DataFrame,
    factor_index: int = 2,
    horizon_days: int = DEFAULT_HORIZON,
    folds: int = 5,
    model=None,
) -> Forecast:
    """Try to predict one factor's move `horizon_days` ahead."""
    scores = factors.scores(curve_changes)
    name = factors.name(factor_index)
    # Cumulative factor move over the horizon, shifted back so each row's
    # target is strictly in its future.
    target = scores[name].rolling(horizon_days).sum().shift(-horizon_days)

    features = feature_matrix(warehouse, factors)
    predicted, actual = walk_forward(features, target.dropna(), folds=folds, model=model)
    return Forecast(
        factor=name,
        horizon_days=horizon_days,
        actual=actual,
        predicted=predicted,
        baseline=pd.Series(0.0, index=actual.index),
        folds=folds,
        n_features=features.shape[1],
    )
