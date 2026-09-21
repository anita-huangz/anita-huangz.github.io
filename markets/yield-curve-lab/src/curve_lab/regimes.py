"""Curve shapes, clustered -- and whether the clusters are worth having.

K-means will always return k clusters. On uniform noise it returns k clusters
that look convincing when plotted. So the question is never "what are the
clusters" but "is this data actually clustered", and the answer here comes
from comparing the silhouette of the real curve shapes against the silhouette
of the same data with each column shuffled independently, which destroys the
joint structure while keeping every marginal distribution intact.

Shapes, not levels. The input is each day's curve standardised to mean zero
and unit spread across tenors, so a 16% curve in 1981 and a 4% curve in 2021
with the same slope and hump land in the same cluster. Clustering the levels
instead mostly recovers the decade.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

from .data import Curve

RANDOM_STATE = 0


def shape_matrix(curve: Curve) -> np.ndarray:
    """Each day's curve, standardised across tenors so only the shape is left."""
    values = curve.frame.to_numpy(dtype=float)
    centred = values - values.mean(axis=1, keepdims=True)
    spread = values.std(axis=1, keepdims=True)
    # A perfectly flat curve has zero spread; leave it centred rather than
    # dividing by zero and calling the result a shape.
    spread[spread == 0] = 1.0
    return centred / spread


@dataclass(frozen=True)
class RegimeFit:
    """Clusters, with the null they were tested against."""

    k: int
    labels: pd.Series
    silhouette: float
    null_silhouettes: np.ndarray

    @property
    def null_mean(self) -> float:
        return float(self.null_silhouettes.mean())

    @property
    def z_score(self) -> float:
        deviation = self.null_silhouettes.std(ddof=1)
        return float((self.silhouette - self.null_mean) / deviation) if deviation > 0 else 0.0

    @property
    def better_than_noise(self) -> bool:
        return bool((self.null_silhouettes >= self.silhouette).mean() < 0.05)

    def sizes(self) -> pd.Series:
        return self.labels.value_counts().sort_index()

    def describe(self) -> str:
        verdict = "real structure" if self.better_than_noise else "no better than shuffled"
        return (
            f"k={self.k}: silhouette {self.silhouette:.3f} vs shuffled "
            f"{self.null_mean:.3f} (z {self.z_score:+.1f}) -- {verdict}"
        )


def fit_regimes(
    curve: Curve, k: int = 4, null_draws: int = 20, sample: int = 3000
) -> RegimeFit:
    """Cluster curve shapes and test the result against column-shuffled data."""
    if k < 2:
        raise ValueError("k must be at least 2 for a silhouette to be defined")
    shapes = shape_matrix(curve)

    model = KMeans(n_clusters=k, n_init=10, random_state=RANDOM_STATE)
    labels = model.fit_predict(shapes)

    rng = np.random.default_rng(RANDOM_STATE)
    # Silhouette is O(n^2); subsample for it, consistently for real and null.
    index = (
        rng.choice(len(shapes), size=sample, replace=False)
        if len(shapes) > sample
        else np.arange(len(shapes))
    )
    observed = float(silhouette_score(shapes[index], labels[index]))

    null = np.empty(null_draws)
    for draw in range(null_draws):
        shuffled = np.column_stack([rng.permutation(column) for column in shapes.T])
        null_labels = KMeans(n_clusters=k, n_init=10, random_state=RANDOM_STATE).fit_predict(
            shuffled
        )
        null[draw] = silhouette_score(shuffled[index], null_labels[index])

    return RegimeFit(
        k=k,
        labels=pd.Series(labels, index=curve.frame.index, name="regime"),
        silhouette=observed,
        null_silhouettes=null,
    )
