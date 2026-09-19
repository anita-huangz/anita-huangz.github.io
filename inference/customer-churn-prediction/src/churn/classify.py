"""The classification view, done so the numbers mean something.

Kept alongside the survival model rather than replaced by it, because the two
answer different questions and the comparison is the point: "who will leave"
versus "when". This module is also where the notebook's methodology is
reproduced exactly, so the cost of each mistake can be measured instead of
asserted.

Three things the notebook got wrong, all of which move the score:

**The scaler was fitted on the whole dataset before the split.** The test rows
contributed their mean and variance to the transform that was then used to
evaluate on them. Small here, but it is leakage, and leakage is not a matter
of degree when you are reporting a number as out-of-sample.

**Nominal categories were label-encoded.** `InternetService` became DSL=0,
Fiber=1, No=2, which tells a linear model that fibre is halfway between DSL
and no internet at all. Trees can partly recover; logistic regression and an
SVM cannot.

**Every score came from one 80/20 split.** A single split on 7,043 rows has a
standard error around a point of AUC, which is the same size as the difference
between the models being compared.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, OrdinalEncoder, StandardScaler

from .data import NOMINAL, NUMERIC, ORDINAL, Dataset

RANDOM_STATE = 42
FOLDS = 5


def build_preprocessor(leaky: bool = False) -> ColumnTransformer:
    """Encode the columns according to what they actually are.

    `leaky=True` reproduces the notebook: one label encoder per categorical
    column, inventing an order for categories that have none.
    """
    if leaky:
        return ColumnTransformer(
            [
                ("ordinal", OrdinalEncoder(), [*NOMINAL, *ORDINAL]),
                ("numeric", StandardScaler(), NUMERIC),
            ]
        )
    return ColumnTransformer(
        [
            (
                "nominal",
                OneHotEncoder(drop="if_binary", handle_unknown="ignore"),
                NOMINAL,
            ),
            (
                "ordinal",
                OrdinalEncoder(categories=[ORDINAL[c] for c in ORDINAL]),
                list(ORDINAL),
            ),
            ("numeric", StandardScaler(), NUMERIC),
        ]
    )


def models(class_weight: str | None = "balanced") -> dict[str, object]:
    """The candidates, each wrapped so preprocessing is fitted per fold."""
    return {
        "logistic": LogisticRegression(
            max_iter=2000, class_weight=class_weight, random_state=RANDOM_STATE
        ),
        "random_forest": RandomForestClassifier(
            n_estimators=300,
            min_samples_leaf=5,
            class_weight=class_weight,
            random_state=RANDOM_STATE,
            n_jobs=-1,
        ),
        "gradient_boosting": HistGradientBoostingClassifier(
            max_iter=300, learning_rate=0.06, random_state=RANDOM_STATE
        ),
    }


def pipeline(estimator, leaky: bool = False) -> Pipeline:
    return Pipeline(
        [("prep", build_preprocessor(leaky=leaky)), ("model", estimator)]
    )


@dataclass(frozen=True)
class CrossValidated:
    """Out-of-fold probabilities for every row, and the labels to grade them."""

    name: str
    probability: np.ndarray
    label: np.ndarray

    def __len__(self) -> int:
        return len(self.label)


def cross_validated_probabilities(
    data: Dataset, estimator, leaky: bool = False, folds: int = FOLDS
) -> np.ndarray:
    """Predicted churn probability for every customer, from a fold they were not in.

    `cross_val_predict` with the preprocessing *inside* the pipeline is the
    whole point: the scaler and the encoder are refitted on each training fold,
    so no row ever influences the transform applied to itself.

    The folds are independent and every seed is fixed, so running them in
    parallel changes the wall clock and nothing else -- the boosted model's
    five folds go from 4.07s to 1.66s here, bit-identical either way. The
    forest and the permutation importances below already do this.
    """
    splitter = StratifiedKFold(n_splits=folds, shuffle=True, random_state=RANDOM_STATE)
    return cross_val_predict(
        pipeline(estimator, leaky=leaky),
        data.features,
        data.event,
        cv=splitter,
        method="predict_proba",
        n_jobs=-1,
    )[:, 1]


def leaky_holdout_score(data: Dataset, estimator) -> float:
    """Reproduce the notebook: scale everything, then split once.

    Exists to put a number on the mistake rather than describe it.
    """
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import train_test_split

    prep = build_preprocessor(leaky=True)
    # The error: the transform sees the test rows before they are held out.
    X = prep.fit_transform(data.features)
    X_train, X_test, y_train, y_test = train_test_split(
        X, data.event, test_size=0.2, random_state=RANDOM_STATE
    )
    estimator.fit(X_train, y_train)
    return float(roc_auc_score(y_test, estimator.predict_proba(X_test)[:, 1]))


def honest_holdout_score(data: Dataset, estimator) -> float:
    """The same single split, with preprocessing fitted on the training rows only."""
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import train_test_split

    X_train, X_test, y_train, y_test = train_test_split(
        data.features, data.event, test_size=0.2, random_state=RANDOM_STATE
    )
    model = pipeline(estimator, leaky=True)
    model.fit(X_train, y_train)
    return float(roc_auc_score(y_test, model.predict_proba(X_test)[:, 1]))


def permutation_importance_scores(
    data: Dataset, estimator, repeats: int = 5
) -> pd.Series:
    """Which columns the model actually uses, measured by breaking them.

    Not the tree's built-in importance, which is computed on the training data
    and inflates high-cardinality columns regardless of whether they help out
    of sample.
    """
    from sklearn.inspection import permutation_importance
    from sklearn.model_selection import train_test_split

    X_train, X_test, y_train, y_test = train_test_split(
        data.features,
        data.event,
        test_size=0.25,
        random_state=RANDOM_STATE,
        stratify=data.event,
    )
    model = pipeline(estimator)
    model.fit(X_train, y_train)
    result = permutation_importance(
        model,
        X_test,
        y_test,
        n_repeats=repeats,
        random_state=RANDOM_STATE,
        scoring="roc_auc",
        n_jobs=-1,
    )
    return pd.Series(
        result.importances_mean, index=X_test.columns
    ).sort_values(ascending=False)


def bootstrap_interval(
    metric, label: np.ndarray, score: np.ndarray, draws: int = 1000, alpha: float = 0.05
) -> tuple[float, float, float]:
    """Point estimate and a percentile bootstrap interval around it.

    A single number invites comparisons it cannot support. On 7,043 rows the
    interval around AUC is roughly a point wide, which is the same size as the
    gap between the models here -- so the honest reading is that they tie.
    """
    rng = np.random.default_rng(RANDOM_STATE)
    n = len(label)
    point = float(metric(label, score))
    samples = np.empty(draws)
    for i in range(draws):
        idx = rng.integers(0, n, n)
        # A resample can miss a class entirely on a rare label; redraw.
        while len(np.unique(label[idx])) < 2:
            idx = rng.integers(0, n, n)
        samples[i] = metric(label[idx], score[idx])
    lo, hi = np.quantile(samples, [alpha / 2, 1 - alpha / 2])
    return point, float(lo), float(hi)
