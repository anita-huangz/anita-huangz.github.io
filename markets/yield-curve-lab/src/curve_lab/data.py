"""Loading the curve, and refusing to load a broken one.

The packaged snapshot is nine Treasury constant-maturity tenors, daily, from
September 1981. It is built by `scripts/build_snapshot.py` from FRED and is
committed rather than fetched so the whole package runs offline.

Validation is not ceremony here. Every number downstream is a *difference* --
a daily change, a roll-down, a spread between two legs -- so anything that
corrupts the spacing of the index corrupts the result silently rather than
loudly. A curve with a hole in it still has a mean, a standard deviation and
a Sharpe ratio; they are just wrong.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

import numpy as np
import pandas as pd

BUNDLED = Path(__file__).parent / "data" / "treasury_curve.csv"

#: FRED series -> years to maturity, short to long. The order is load-bearing:
#: PCA loadings are read as a shape across the curve, and a shuffled column
#: order turns "slope" into noise that still explains 13% of the variance.
TENORS: dict[str, float] = {
    "DGS3MO": 0.25,
    "DGS6MO": 0.5,
    "DGS1": 1.0,
    "DGS2": 2.0,
    "DGS3": 3.0,
    "DGS5": 5.0,
    "DGS7": 7.0,
    "DGS10": 10.0,
    "DGS30": 30.0,
}

#: Longest acceptable hole between consecutive observations. Five covers a
#: long weekend with a holiday on either side; anything more is a gap in the
#: data rather than a gap in the calendar.
MAX_GAP_DAYS = 10


class SchemaError(ValueError):
    """The file loaded but is not a curve anything here can use."""


@dataclass(frozen=True)
class Curve:
    """A daily term structure. Yields are percent, as FRED publishes them."""

    frame: pd.DataFrame

    @property
    def tenors(self) -> list[str]:
        return list(self.frame.columns)

    @property
    def maturities(self) -> np.ndarray:
        """Years to maturity, aligned with `tenors`."""
        return np.array([TENORS[t] for t in self.tenors], dtype=float)

    @property
    def dates(self) -> pd.DatetimeIndex:
        return pd.DatetimeIndex(self.frame.index)

    def __len__(self) -> int:
        return len(self.frame)

    @cached_property
    def changes(self) -> pd.DataFrame:
        """Daily changes in percentage points. The unit every risk model wants."""
        return self.frame.diff().dropna()

    def slice(self, start: str | None = None, end: str | None = None) -> Curve:
        return Curve(self.frame.loc[start:end])

    def spread(self, short: str, long: str) -> pd.Series:
        """`long` minus `short`, in basis points. 2s10s is spread('DGS2','DGS10')."""
        for tenor in (short, long):
            if tenor not in self.frame.columns:
                raise KeyError(f"no tenor {tenor!r}; have {self.tenors}")
        return (self.frame[long] - self.frame[short]) * 100.0


def load(path: str | Path | None = None) -> Curve:
    """Read a curve snapshot and check it is usable as a time series."""
    file_path = Path(path) if path is not None else BUNDLED
    if not file_path.exists():
        raise FileNotFoundError(f"no curve snapshot at {file_path}")

    frame = pd.read_csv(file_path, parse_dates=["date"], index_col="date")
    return validate(frame)


def validate(frame: pd.DataFrame) -> Curve:
    """Every check that stands between a bad file and a plausible wrong number."""
    unknown = [c for c in frame.columns if c not in TENORS]
    if unknown:
        raise SchemaError(f"unknown tenor column(s): {unknown}")
    if len(frame.columns) < 3:
        raise SchemaError(
            f"a curve needs at least three tenors to have a shape; got {list(frame.columns)}"
        )

    ordered = [t for t in TENORS if t in frame.columns]
    if list(frame.columns) != ordered:
        # Reordering rather than raising: the data is fine, the column order
        # is a presentation detail, and every downstream shape depends on it.
        frame = frame[ordered]

    if not frame.index.is_monotonic_increasing:
        raise SchemaError("dates are not in order; every difference here assumes they are")
    if frame.index.has_duplicates:
        duplicated = frame.index[frame.index.duplicated()][:3]
        raise SchemaError(f"duplicate dates, e.g. {[str(d.date()) for d in duplicated]}")
    if frame.isna().to_numpy().any():
        raise SchemaError(
            "missing yields; the snapshot is built with an inner join for this reason"
        )

    gaps = frame.index.to_series().diff().dt.days
    if len(frame) > 1 and gaps.max() > MAX_GAP_DAYS:
        worst = gaps.idxmax()
        raise SchemaError(
            f"a {int(gaps.max())}-day hole ends {worst.date()}. Two rows that far "
            "apart sit next to each other in the index, so one row of carry gets "
            "booked across the whole hole. Rebuild the snapshot instead of filling it."
        )
    return Curve(frame=frame)
