"""Level, slope and curvature -- the three shapes the curve actually moves in.

Nine tenors is nine numbers a day, but they do not move independently: when
the ten-year sells off the seven-year almost always does too. Principal
components on *daily changes* recover what the independent movements are, and
on this data three of them account for 95.6% of everything the curve did
between 1981 and 2026.

Changes rather than levels, deliberately. PCA on levels mostly recovers the
fact that rates were 16% in 1981 and 4% now -- the first component is then a
description of forty years of disinflation, not of how the curve moves. Risk
is about tomorrow's move given today's curve, so the input is the move.

The names are not decoration. The first component loads with the same sign at
every tenor, so it shifts the whole curve: that is *level*. The second loads
with opposite signs at the two ends, pivoting: *slope*. The third loads the
wings against the belly: *curvature*, which is what a butterfly trades.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

import numpy as np
import pandas as pd

from .data import Curve

#: Eigenvectors are only defined up to sign, so a rerun can flip one and every
#: reported loading changes sign for no reason. These fix the convention:
#: level is "yields up", slope is "long end up relative to short", curvature is
#: "wings up relative to the belly".
FACTOR_NAMES = ("level", "slope", "curvature")


@dataclass(frozen=True)
class CurveFactors:
    """A fitted decomposition of daily curve changes."""

    maturities: np.ndarray
    tenors: tuple[str, ...]
    #: (n_components, n_tenors). Row i is the shape of component i.
    loadings: np.ndarray
    #: Share of total variance each component explains.
    explained: np.ndarray
    mean_change: np.ndarray

    @property
    def n_components(self) -> int:
        return self.loadings.shape[0]

    def name(self, index: int) -> str:
        return FACTOR_NAMES[index] if index < len(FACTOR_NAMES) else f"pc{index + 1}"

    @cached_property
    def cumulative(self) -> np.ndarray:
        return np.cumsum(self.explained)

    def scores(self, changes: pd.DataFrame) -> pd.DataFrame:
        """Project daily changes onto the factors, in percentage points."""
        aligned = changes[list(self.tenors)].to_numpy(dtype=float)
        projected = (aligned - self.mean_change) @ self.loadings.T
        return pd.DataFrame(
            projected,
            index=changes.index,
            columns=[self.name(i) for i in range(self.n_components)],
        )

    def exposure(self, weights: np.ndarray) -> np.ndarray:
        """How much of each factor a set of per-tenor DV01 weights carries.

        A trade is a vector of DV01 across the tenors. Its P&L for a one-unit
        move in factor *i* is the dot product of that vector with factor *i*'s
        shape -- so this is the trade's factor risk, and a number near zero
        means the trade is genuinely neutral to that shape.
        """
        weights = np.asarray(weights, dtype=float)
        if weights.shape != (len(self.tenors),):
            raise ValueError(
                f"expected one weight per tenor ({len(self.tenors)}), got {weights.shape}"
            )
        return self.loadings @ weights

    def reconstruct(self, scores: np.ndarray) -> np.ndarray:
        """Factor scores back to a curve change. For showing what a shape looks like."""
        return np.asarray(scores, dtype=float) @ self.loadings + self.mean_change


def _orient(loadings: np.ndarray, maturities: np.ndarray) -> np.ndarray:
    """Pin the arbitrary sign of each eigenvector to a readable convention."""
    fixed = loadings.copy()
    if fixed.shape[0] >= 1 and fixed[0].sum() < 0:
        # Level: all one sign. Make it positive -- "the curve sold off".
        fixed[0] *= -1
    if fixed.shape[0] >= 2 and fixed[1][-1] < fixed[1][0]:
        # Slope: make the long end the positive end -- "steepening".
        fixed[1] *= -1
    if fixed.shape[0] >= 3:
        # Curvature: wings positive, belly negative.
        belly = int(np.argmin(np.abs(maturities - np.median(maturities))))
        if fixed[2][belly] > 0:
            fixed[2] *= -1
    return fixed


def fit_factors(curve: Curve, n_components: int = 3) -> CurveFactors:
    """Principal components of daily curve changes, largest first."""
    if n_components < 1:
        raise ValueError("n_components must be at least 1")
    changes = curve.changes
    # Strictly more observations than tenors: with exactly as many, the
    # covariance is singular and the smallest eigenvalues are numerical noise
    # that still gets reported as an explained-variance share.
    if len(changes) <= len(curve.tenors):
        raise ValueError(
            f"{len(changes)} daily changes is too few to estimate a "
            f"{len(curve.tenors)}x{len(curve.tenors)} covariance"
        )
    available = min(n_components, len(curve.tenors))

    matrix = changes.to_numpy(dtype=float)
    mean = matrix.mean(axis=0)
    centred = matrix - mean
    covariance = np.cov(centred, rowvar=False)

    values, vectors = np.linalg.eigh(covariance)
    order = np.argsort(values)[::-1]
    values, vectors = values[order], vectors[:, order]

    loadings = _orient(vectors[:, :available].T, curve.maturities)
    return CurveFactors(
        maturities=curve.maturities,
        tenors=tuple(curve.tenors),
        loadings=loadings,
        explained=values[:available] / values.sum(),
        mean_change=mean,
    )
