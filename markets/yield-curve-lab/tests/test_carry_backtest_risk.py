"""Carry, roll-down, the backtester's accounting, and the risk summary."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from conftest import synthetic_frame
from curve_lab.backtest import BacktestConfig, run_backtest
from curve_lab.carry import TRADING_DAYS, carry_and_roll, interpolate
from curve_lab.data import Curve
from curve_lab.risk import max_drawdown, summarise
from curve_lab.trades import dv01_neutral_weights


class TestInterpolation:
    def test_it_hits_the_quoted_points_exactly(self):
        maturities = np.array([1.0, 2.0, 5.0])
        yields = np.array([3.0, 3.5, 4.0])
        assert interpolate(maturities, yields, 2.0) == pytest.approx(3.5)

    def test_it_is_linear_between_them(self):
        maturities = np.array([1.0, 3.0])
        yields = np.array([2.0, 4.0])
        assert interpolate(maturities, yields, 2.0) == pytest.approx(3.0)

    def test_outside_the_quoted_range_it_holds_flat(self):
        # Extrapolating linearly past the 30-year reaches negative yields
        # within a few decades. Flat is at least defensible.
        maturities = np.array([1.0, 30.0])
        yields = np.array([3.0, 5.0])
        assert interpolate(maturities, yields, 0.1) == 3.0
        assert interpolate(maturities, yields, 100.0) == 5.0


class TestCarryAndRoll:
    def test_carry_is_the_yield_earned_over_the_horizon(self, synthetic):
        result = carry_and_roll(synthetic, "DGS10", horizon_days=63)
        expected = synthetic.frame["DGS10"] * (63 / TRADING_DAYS) * 100
        assert result.carry_bp.iloc[0] == pytest.approx(expected.iloc[0])

    def test_an_upward_sloping_curve_gives_positive_roll_down(self):
        # The bond ages into a lower-yielding point, so its price rises.
        rising = pd.DataFrame(
            [[1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0]] * 30,
            index=pd.bdate_range("2020-01-01", periods=30, name="date"),
            columns=list(synthetic_frame(days=2).columns),
        )
        result = carry_and_roll(Curve(frame=rising), "DGS10", horizon_days=63)
        assert result.rolldown_bp.iloc[0] > 0

    def test_an_inverted_curve_gives_negative_roll_down(self):
        falling = pd.DataFrame(
            [[5.0, 4.5, 4.0, 3.5, 3.0, 2.5, 2.0, 1.5, 1.0]] * 30,
            index=pd.bdate_range("2020-01-01", periods=30, name="date"),
            columns=list(synthetic_frame(days=2).columns),
        )
        result = carry_and_roll(Curve(frame=falling), "DGS10", horizon_days=63)
        assert result.rolldown_bp.iloc[0] < 0

    def test_total_is_the_two_parts(self, synthetic):
        result = carry_and_roll(synthetic, "DGS5")
        assert result.total_bp.iloc[0] == pytest.approx(
            result.carry_bp.iloc[0] + result.rolldown_bp.iloc[0]
        )

    def test_a_horizon_longer_than_the_bond_is_refused(self, synthetic):
        with pytest.raises(ValueError, match="matures before"):
            carry_and_roll(synthetic, "DGS3MO", horizon_days=200)

    def test_an_unknown_tenor_is_refused(self, synthetic):
        with pytest.raises(KeyError, match="DGS99"):
            carry_and_roll(synthetic, "DGS99")

    def test_a_zero_horizon_is_refused(self, synthetic):
        with pytest.raises(ValueError, match="must be positive"):
            carry_and_roll(synthetic, "DGS5", horizon_days=0)


class TestBacktestAccounting:
    @staticmethod
    def fly(curve):
        return dv01_neutral_weights(tuple(curve.tenors), ("DGS2", "DGS10"), "DGS5")

    def test_the_components_add_to_the_total(self, synthetic):
        result = run_backtest(synthetic, self.fly(synthetic))
        parts = result.pnl[["directional", "carry", "rolldown", "cost"]].sum(axis=1)
        assert np.allclose(parts, result.pnl["total"])

    def test_a_long_position_gains_when_its_yield_falls(self):
        # The sign convention, checked directly. One leg, yields falling.
        columns = list(synthetic_frame(days=2).columns)
        falling = pd.DataFrame(
            [[4.0] * 9, [3.9] * 9],
            index=pd.bdate_range("2020-01-01", periods=2, name="date"),
            columns=columns,
        )
        curve = Curve(frame=falling)
        long_only = dv01_neutral_weights(tuple(columns), ("DGS2", "DGS10"), "DGS5")
        # Replace with a single long leg so the sign is unambiguous.
        weights = np.zeros(len(columns))
        weights[columns.index("DGS10")] = 1.0
        long_only = type(long_only)(
            tenors=tuple(columns), weights=weights, wings=("DGS2", "DGS10"),
            belly="DGS5", label="long 10y",
        )
        result = run_backtest(curve, long_only, BacktestConfig(cost_bp=0.0))
        assert result.pnl["directional"].iloc[0] > 0

    def test_costs_are_charged_on_opening_and_on_each_rebalance(self, synthetic):
        cheap = run_backtest(synthetic, self.fly(synthetic), BacktestConfig(cost_bp=0.0))
        dear = run_backtest(synthetic, self.fly(synthetic), BacktestConfig(cost_bp=1.0))
        assert cheap.pnl["cost"].sum() == 0.0
        assert dear.pnl["cost"].sum() < 0
        # Two units of gross DV01 per rebalance, plus the opening trade.
        assert dear.pnl["cost"].sum() == pytest.approx(-2.0 * dear.rebalances, abs=1e-9)

    def test_rebalancing_more_often_costs_more(self, synthetic):
        rare = run_backtest(synthetic, self.fly(synthetic), BacktestConfig(rebalance_days=63))
        often = run_backtest(synthetic, self.fly(synthetic), BacktestConfig(rebalance_days=5))
        assert often.pnl["cost"].sum() < rare.pnl["cost"].sum()

    def test_it_is_deterministic(self, synthetic):
        first = run_backtest(synthetic, self.fly(synthetic))
        second = run_backtest(synthetic, self.fly(synthetic))
        assert first.total.equals(second.total)

    def test_the_equity_curve_is_the_running_sum(self, synthetic):
        result = run_backtest(synthetic, self.fly(synthetic))
        assert result.equity.iloc[-1] == pytest.approx(result.total.sum())

    def test_a_trade_naming_tenors_the_curve_lacks_is_refused(self, synthetic):
        fly = self.fly(synthetic)
        trimmed = Curve(frame=synthetic.frame[["DGS1", "DGS2", "DGS3"]])
        with pytest.raises(KeyError, match="does not have"):
            run_backtest(trimmed, fly)

    def test_one_day_is_not_a_backtest(self, synthetic):
        one = Curve(frame=synthetic.frame.iloc[:1])
        with pytest.raises(ValueError, match="at least two days"):
            run_backtest(one, self.fly(synthetic))

    @pytest.mark.parametrize(
        ("field", "value"), [("rebalance_days", 0), ("cost_bp", -1.0)]
    )
    def test_nonsense_settings_are_refused(self, field, value):
        with pytest.raises(ValueError):
            BacktestConfig(**{field: value})


class TestRisk:
    def test_a_rising_equity_curve_has_a_shallow_drawdown(self):
        equity = pd.Series(
            np.arange(100, dtype=float), index=pd.bdate_range("2020-01-01", periods=100)
        )
        assert max_drawdown(equity).depth == pytest.approx(0.0)

    def test_the_drawdown_finds_the_deepest_trough(self):
        values = [0, 10, 20, 5, 15, 25]
        equity = pd.Series(values, index=pd.bdate_range("2020-01-01", periods=6), dtype=float)
        drawdown = max_drawdown(equity)
        assert drawdown.depth == pytest.approx(-15.0)
        assert drawdown.recovered_fully

    def test_a_drawdown_never_recovered_says_so(self):
        values = [0, 10, 20, 5, 6, 7]
        equity = pd.Series(values, index=pd.bdate_range("2020-01-01", periods=6), dtype=float)
        drawdown = max_drawdown(equity)
        assert not drawdown.recovered_fully
        assert drawdown.days_underwater > 0

    def test_an_empty_equity_curve_is_refused(self):
        with pytest.raises(ValueError, match="no drawdown"):
            max_drawdown(pd.Series(dtype=float))

    def test_the_summary_reports_what_it_measured(self, synthetic):
        result = run_backtest(synthetic, TestBacktestAccounting.fly(synthetic))
        performance = summarise(result.total)
        assert performance.days == len(result.total)
        assert performance.total == pytest.approx(result.total.sum())
        assert 0.0 <= performance.hit_rate <= 1.0
        assert performance.worst_day <= performance.best_day

    def test_a_flat_pnl_has_no_information_ratio_rather_than_an_infinite_one(self):
        flat = pd.Series([0.0] * 50, index=pd.bdate_range("2020-01-01", periods=50))
        assert summarise(flat).information_ratio == 0.0

    def test_one_day_is_not_enough_to_say_anything_about_risk(self):
        one = pd.Series([1.0], index=pd.bdate_range("2020-01-01", periods=1))
        with pytest.raises(ValueError, match="at least two days"):
            summarise(one)
