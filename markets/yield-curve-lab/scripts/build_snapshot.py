#!/usr/bin/env python3
"""Rebuild the committed curve snapshot from FRED.

Kept so the packaged CSV is reproducible rather than a mystery artifact:

    python scripts/build_snapshot.py

FRED publishes one series per tenor, each with its own history and its own
holidays, so the join is the whole job. Two things it has to get right:

**The 20-year tenor is not continuous.** Treasury stopped issuing 20-year
bonds at the end of 1986 and resumed in October 1993, and FRED's DGS20 has
nothing in between. Inner-joining it with the rest silently deletes 6.75
years and leaves two dates adjacent in the index that are 2,466 days apart --
a backtest then books one day of carry across most of a decade. The tenor is
excluded rather than patched; `--with-20y` includes it for anyone who wants
to see the hole.

**The 30-year is fine, despite the story.** Treasury suspended the bond
between 2002 and 2006, but FRED's DGS30 carries a published long-term rate
through the suspension, so the series has only holidays missing. That is
worth stating because the obvious assumption -- that it must have a gap --
would have it dropped for no reason.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"

#: FRED series -> years to maturity. Ordered short to long; the PCA loadings
#: and every plot depend on that order.
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

#: Excluded by default. See the module docstring.
DISCONTINUOUS = {"DGS20": 20.0}

DEFAULT_OUT = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "curve_lab"
    / "data"
    / "treasury_curve.csv"
)


def fetch(series: str, timeout: float = 30.0) -> pd.DataFrame:
    import httpx

    response = httpx.get(FRED_CSV.format(series=series), timeout=timeout, follow_redirects=True)
    response.raise_for_status()
    from io import StringIO

    return pd.read_csv(StringIO(response.text), parse_dates=[0], index_col=0)


def read_local(series: str, directory: Path) -> pd.DataFrame:
    return pd.read_csv(directory / f"fred_{series}.csv", parse_dates=[0], index_col=0)


def build(tenors: dict[str, float], source: Path | None = None) -> pd.DataFrame:
    """Join every tenor on date, keeping only days where all of them printed."""
    frames = []
    for series in tenors:
        raw = read_local(series, source) if source else fetch(series)
        column = raw.apply(pd.to_numeric, errors="coerce")
        column.columns = [series]
        frames.append(column)
    curve = pd.concat(frames, axis=1, sort=True).dropna()
    curve.index.name = "date"
    return curve


def largest_gap(curve: pd.DataFrame) -> int:
    """Longest run of calendar days between two consecutive observations."""
    return int(curve.index.to_series().diff().dt.days.max())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=None,
        help="Read fred_<SERIES>.csv from here instead of fetching.",
    )
    parser.add_argument(
        "--with-20y",
        action="store_true",
        help="Include DGS20, which costs 6.75 years to its issuance gap.",
    )
    parser.add_argument(
        "--max-gap-days",
        type=int,
        default=10,
        help="Refuse to write a snapshot with a hole bigger than this.",
    )
    args = parser.parse_args(argv)

    tenors = dict(TENORS)
    if args.with_20y:
        tenors = dict(sorted({**tenors, **DISCONTINUOUS}.items(), key=lambda kv: kv[1]))

    curve = build(tenors, args.source_dir)
    gap = largest_gap(curve)
    if gap > args.max_gap_days:
        print(
            f"error: the joined curve has a {gap}-day hole, which would put two "
            f"dates {gap} days apart next to each other in the index. Refusing "
            f"to write it.",
            file=sys.stderr,
        )
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    curve.round(2).to_csv(args.out, lineterminator="\n")
    print(
        f"{len(curve):,} days x {len(curve.columns)} tenors, "
        f"{curve.index.min().date()} to {curve.index.max().date()}, "
        f"largest gap {gap}d -> {args.out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
