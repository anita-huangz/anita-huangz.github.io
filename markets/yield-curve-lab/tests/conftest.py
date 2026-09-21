"""Shared fixtures.

Most tests run on a synthetic curve rather than the bundled 11,261 days: the
arithmetic being checked does not need forty-five years of history, and a
suite that reloads and re-decomposes the real file for every assertion is slow
enough that people stop running it. The tests that are *about* the real data --
that it loads, that it is continuous, that the headline numbers hold -- say so
and use it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from curve_lab.data import TENORS, Curve, load

#: A curve with a genuine level, slope and curvature structure built into it,
#: so PCA has something to find and the recovered shapes can be checked
#: against the ones that were put in.
SYNTHETIC_DAYS = 900


def synthetic_frame(days: int = SYNTHETIC_DAYS, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    tenors = list(TENORS)
    maturities = np.array([TENORS[t] for t in tenors])

    # Three shapes, deliberately ordered by the variance of their driver so
    # the recovered components come back in a known order.
    level = np.ones_like(maturities)
    slope = (np.log(maturities) - np.log(maturities).mean())
    slope /= np.linalg.norm(slope)
    curvature = -((np.log(maturities) - np.log(maturities).mean()) ** 2)
    curvature -= curvature.mean()
    curvature /= np.linalg.norm(curvature)

    drivers = rng.normal(0, [0.060, 0.030, 0.012], size=(days, 3))
    changes = drivers @ np.vstack([level / np.linalg.norm(level), slope, curvature])
    changes += rng.normal(0, 0.001, size=changes.shape)

    start = np.array([4.5, 4.6, 4.7, 4.8, 4.9, 5.0, 5.1, 5.2, 5.4])
    levels = start + np.cumsum(changes, axis=0)
    index = pd.bdate_range("2015-01-01", periods=days, name="date")
    return pd.DataFrame(levels, index=index, columns=tenors)


@pytest.fixture
def synthetic() -> Curve:
    return Curve(frame=synthetic_frame())


@pytest.fixture(scope="session")
def real() -> Curve:
    """The bundled snapshot. Session-scoped: it is the same file every time."""
    return load()


@pytest.fixture
def short_curve() -> Curve:
    """Ten days. For the paths that only need a couple of rows."""
    return Curve(frame=synthetic_frame(days=10))
