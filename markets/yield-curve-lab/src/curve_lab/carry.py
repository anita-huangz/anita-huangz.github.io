"""Carry and roll-down: what a curve position earns if the curve does nothing.

Two separate things, routinely conflated.

**Carry** is the yield you collect for holding the bond. Over a horizon of *h*
years a par bond yielding *y* accrues roughly `y * h`.

**Roll-down** is the price gain from the bond getting shorter. Hold a 10-year
for three months and you own a 9.75-year; if the curve slopes upward the
9.75-year point yields less than the 10-year did, and a bond whose yield has
fallen is worth more. The gain is that yield drop times the position's
duration.

Neither is a forecast. Both are arithmetic on today's curve, and that is the
point: if a trade's expected return is carry and roll, it does not need a view
on where rates go. The backtester keeps them as separate columns for exactly
that reason -- so the part that required a forecast can be told apart from the
part that did not.

Roll-down needs the yield at a maturity the curve does not quote, so it is
interpolated linearly in maturity. That is the crude choice and it is stated
rather than hidden: a proper job bootstraps a discount curve and prices the
aged bond off it. Linear interpolation is close between adjacent quoted points
and worst across the 10y-30y gap, where the two are twenty years apart.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .data import TENORS, Curve
from .trades import par_bond_dv01

TRADING_DAYS = 252


def interpolate(maturities: np.ndarray, yields: np.ndarray, target: float) -> float:
    """Yield at `target` years, linear between the quoted points.

    Outside the quoted range it holds the nearest endpoint flat rather than
    extrapolating: a linear extrapolation past the 30-year produces negative
    yields within a few decades, and a flat one is at least defensible.
    """
    if target <= maturities[0]:
        return float(yields[0])
    if target >= maturities[-1]:
        return float(yields[-1])
    return float(np.interp(target, maturities, yields))


@dataclass(frozen=True)
class CarryRoll:
    """Expected return over the horizon, split into its two sources."""

    tenor: str
    horizon_years: float
    carry_bp: pd.Series
    rolldown_bp: pd.Series

    @property
    def total_bp(self) -> pd.Series:
        return self.carry_bp + self.rolldown_bp

    def summary(self) -> dict[str, float]:
        return {
            "carry_bp": float(self.carry_bp.mean()),
            "rolldown_bp": float(self.rolldown_bp.mean()),
            "total_bp": float(self.total_bp.mean()),
        }


def carry_and_roll(curve: Curve, tenor: str, horizon_days: int = 63) -> CarryRoll:
    """Carry and roll-down for a single tenor, in basis points of price.

    Both legs are expressed in basis points of face so they add to the
    backtest's P&L, which is also in basis points of face.
    """
    if tenor not in curve.tenors:
        raise KeyError(f"no tenor {tenor!r}; have {curve.tenors}")
    if horizon_days <= 0:
        raise ValueError("horizon_days must be positive")

    maturity = TENORS[tenor]
    horizon = horizon_days / TRADING_DAYS
    if horizon >= maturity:
        raise ValueError(
            f"a {horizon_days}-day horizon is longer than the {maturity}y tenor; "
            "the bond matures before the holding period ends"
        )

    maturities = curve.maturities
    frame = curve.frame
    aged = maturity - horizon

    carry = []
    rolldown = []
    for _, row in frame.iterrows():
        yields = row.to_numpy(dtype=float)
        start_yield = float(row[tenor])
        aged_yield = interpolate(maturities, yields, aged)
        # Duration of the bond at the *end* of the holding period is the more
        # common convention; the difference over a quarter is small but it is
        # a choice, so it is made explicitly.
        duration_years = par_bond_dv01(aged_yield, aged) / (100.0 * 1e-4)
        carry.append(start_yield * horizon * 100.0)
        rolldown.append(duration_years * (start_yield - aged_yield) * 100.0)

    index = frame.index
    return CarryRoll(
        tenor=tenor,
        horizon_years=horizon,
        carry_bp=pd.Series(carry, index=index, name="carry_bp"),
        rolldown_bp=pd.Series(rolldown, index=index, name="rolldown_bp"),
    )
