"""Risk and performance statistics, with the denominators stated.

Every number here is computed on the realised P&L series the backtester
produced, in dollars per $1 of belly DV01. There is no benchmark and no
risk-free rate: a DV01-neutral curve trade has no capital base to compute a
return *on*, so a Sharpe ratio here is mean over standard deviation of the
daily P&L, annualised -- an information ratio in all but name. Calling it a
Sharpe would imply an excess return over cash that is not being measured.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

TRADING_DAYS = 252


@dataclass(frozen=True)
class Drawdown:
    """The worst peak-to-trough stretch of the equity curve."""

    depth: float
    start: pd.Timestamp
    trough: pd.Timestamp
    recovered: pd.Timestamp | None

    @property
    def days_underwater(self) -> int:
        end = self.recovered if self.recovered is not None else self.trough
        return int((end - self.start).days)

    @property
    def recovered_fully(self) -> bool:
        return self.recovered is not None


@dataclass(frozen=True)
class Performance:
    """Summary of a realised P&L series."""

    days: int
    total: float
    mean_daily: float
    volatility_daily: float
    annualised_volatility: float
    information_ratio: float
    hit_rate: float
    worst_day: float
    best_day: float
    drawdown: Drawdown

    def describe(self) -> str:
        return (
            f"{self.days:,} days, total ${self.total:,.0f} per $1/bp of belly DV01, "
            f"IR {self.information_ratio:+.2f}, max drawdown ${self.drawdown.depth:,.0f}"
        )


def max_drawdown(equity: pd.Series) -> Drawdown:
    """Deepest decline from a running peak, and whether it ever came back.

    Measured in dollars, not percent: the equity curve of a DV01-neutral trade
    starts at zero and can go negative, so a percentage drawdown would be
    dividing by something that is not capital.
    """
    if equity.empty:
        raise ValueError("an empty equity curve has no drawdown")
    peak = equity.cummax()
    underwater = equity - peak
    trough = underwater.idxmin()
    depth = float(underwater.loc[trough])

    before = equity.loc[:trough]
    start = before.idxmax() if len(before) else equity.index[0]

    after = equity.loc[trough:]
    recovered_points = after[after >= equity.loc[start]]
    recovered = recovered_points.index[0] if len(recovered_points) else None
    return Drawdown(depth=depth, start=start, trough=trough, recovered=recovered)


def summarise(pnl: pd.Series) -> Performance:
    """Turn a daily P&L series into the numbers worth quoting."""
    series = pnl.dropna()
    if len(series) < 2:
        raise ValueError("need at least two days of P&L to say anything about risk")

    mean = float(series.mean())
    volatility = float(series.std(ddof=1))
    # A flat P&L has no information ratio rather than an infinite one.
    ratio = mean / volatility * np.sqrt(TRADING_DAYS) if volatility > 0 else 0.0
    return Performance(
        days=len(series),
        total=float(series.sum()),
        mean_daily=mean,
        volatility_daily=volatility,
        annualised_volatility=volatility * np.sqrt(TRADING_DAYS),
        information_ratio=float(ratio),
        hit_rate=float((series > 0).mean()),
        worst_day=float(series.min()),
        best_day=float(series.max()),
        drawdown=max_drawdown(series.cumsum()),
    )
