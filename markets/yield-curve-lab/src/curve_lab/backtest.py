"""Deterministic execution of a curve trade.

No forecast enters here. The position is a fixed set of DV01 weights, it is
rebalanced on a schedule, and the P&L is decomposed into the pieces that
caused it:

    directional   what the curve actually did, given the position
    carry         coupon accrued, which needed no view
    rolldown      the aged bond repricing down a sloping curve
    cost          paid on every unit of DV01 traded at a rebalance

Keeping those apart is the whole point. A curve trade can look profitable for
four years and turn out to have been a carry harvest with a directional loss
attached, and a single P&L line cannot tell you which you were running.

Sizing is quoted per $1 of belly DV01: the belly leg is scaled so a one basis
point move in its yield moves the leg by exactly one dollar, and every other
leg is scaled against it by the trade's weights. That makes the numbers below
comparable across trades and across eras, which a fixed notional does not --
$10m of 30-year in 1981 and in 2021 are not the same risk.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .carry import TRADING_DAYS, interpolate
from .data import TENORS, Curve
from .trades import Butterfly, par_bond_dv01


@dataclass(frozen=True)
class BacktestConfig:
    """Everything that is a choice rather than data."""

    #: Trading days between rebalances. The position drifts in between, which
    #: is realistic: weights are set on known prices, not continuously.
    rebalance_days: int = 21
    #: Half-spread paid per unit of DV01 traded, in basis points of yield.
    #: 0.5bp on the 10-year is roughly a tick in normal conditions.
    cost_bp: float = 0.5
    #: Horizon used for the roll-down calculation.
    roll_horizon_days: int = 63

    def __post_init__(self) -> None:
        if self.rebalance_days < 1:
            raise ValueError("rebalance_days must be at least 1")
        if self.cost_bp < 0:
            raise ValueError("cost_bp cannot be negative")


@dataclass(frozen=True)
class BacktestResult:
    """Daily P&L, already decomposed. Amounts are dollars per $1 of belly DV01."""

    label: str
    pnl: pd.DataFrame
    weights: np.ndarray
    tenors: tuple[str, ...]
    rebalances: int
    config: BacktestConfig = field(repr=False, default_factory=BacktestConfig)

    @property
    def total(self) -> pd.Series:
        return self.pnl["total"]

    @property
    def equity(self) -> pd.Series:
        return self.total.cumsum()

    def contribution(self) -> pd.Series:
        """Cumulative dollars from each source over the whole run."""
        return self.pnl[["directional", "carry", "rolldown", "cost"]].sum()


def _leg_faces(row: pd.Series, weights: np.ndarray, tenors: tuple[str, ...]) -> np.ndarray:
    """Face value per leg such that each leg's DV01 equals its weight, in $/bp."""
    faces = np.zeros(len(tenors))
    for i, tenor in enumerate(tenors):
        if weights[i] == 0.0:
            continue
        dv01_per_100 = par_bond_dv01(float(row[tenor]), TENORS[tenor])
        faces[i] = weights[i] / dv01_per_100 * 100.0
    return faces


def run_backtest(
    curve: Curve,
    butterfly: Butterfly,
    config: BacktestConfig | None = None,
) -> BacktestResult:
    """Hold the trade, rebalance on schedule, and account for every dollar."""
    settings = config or BacktestConfig()
    weights = butterfly.weights
    tenors = butterfly.tenors
    if set(tenors) - set(curve.tenors):
        raise KeyError("the trade names tenors the curve does not have")

    frame = curve.frame[list(tenors)]
    if len(frame) < 2:
        raise ValueError("a backtest needs at least two days")

    maturities = np.array([TENORS[t] for t in tenors])
    values = frame.to_numpy(dtype=float)
    dates = frame.index

    horizon = settings.roll_horizon_days / TRADING_DAYS
    live_faces = _leg_faces(frame.iloc[0], weights, tenors)
    rebalances = 1
    # Opening the position is a trade, so it pays the spread like any other.
    opening_cost = settings.cost_bp * float(np.abs(weights).sum())

    records = []
    for day in range(1, len(frame)):
        previous, current = values[day - 1], values[day]
        change_bp = (current - previous) * 100.0

        # Long a bond (positive DV01 weight) gains when its yield falls.
        directional = float(-(live_faces / 100.0 * _dv01s(previous, maturities)) @ change_bp)

        carry = float((live_faces * previous / 100.0).sum() / TRADING_DAYS)

        roll = 0.0
        for i, maturity in enumerate(maturities):
            if live_faces[i] == 0.0 or horizon >= maturity:
                continue
            aged = maturity - horizon
            aged_yield = interpolate(maturities, previous, aged)
            duration = par_bond_dv01(aged_yield, aged) / (100.0 * 1e-4)
            total_roll_bp = duration * (previous[i] - aged_yield) * 100.0
            roll += live_faces[i] * total_roll_bp * 1e-4 / settings.roll_horizon_days

        cost = 0.0
        if day % settings.rebalance_days == 0:
            live_faces = _leg_faces(frame.iloc[day], weights, tenors)
            cost = settings.cost_bp * float(np.abs(weights).sum())
            rebalances += 1

        records.append(
            {
                "date": dates[day],
                "directional": directional,
                "carry": carry,
                "rolldown": roll,
                "cost": -cost,
            }
        )

    pnl = pd.DataFrame(records).set_index("date")
    pnl.loc[pnl.index[0], "cost"] -= opening_cost
    pnl["total"] = pnl[["directional", "carry", "rolldown", "cost"]].sum(axis=1)
    return BacktestResult(
        label=butterfly.label,
        pnl=pnl,
        weights=weights,
        tenors=tenors,
        rebalances=rebalances,
        config=settings,
    )


def _dv01s(yields: np.ndarray, maturities: np.ndarray) -> np.ndarray:
    return np.array(
        [par_bond_dv01(y, m) for y, m in zip(yields, maturities, strict=True)]
    )
