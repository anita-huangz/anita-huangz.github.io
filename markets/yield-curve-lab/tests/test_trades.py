"""DV01 arithmetic, and the difference between the two ways to weight a fly."""

from __future__ import annotations

import numpy as np
import pytest

from curve_lab.pca import CurveFactors, fit_factors
from curve_lab.trades import (
    Butterfly,
    dv01_neutral_weights,
    factor_neutral_weights,
    par_bond_dv01,
    residual_risk,
)


class TestParBondDv01:
    @pytest.mark.parametrize(
        ("maturity", "yield_pct", "expected_duration"),
        [(2, 4.0, 1.90), (5, 4.0, 4.49), (10, 4.0, 8.18), (30, 4.0, 17.38)],
    )
    def test_it_matches_textbook_par_bond_durations(self, maturity, yield_pct, expected_duration):
        # DV01 per 100 face divided by (100 * 1bp) recovers modified duration.
        duration = par_bond_dv01(yield_pct, maturity) / (100 * 1e-4)
        assert duration == pytest.approx(expected_duration, abs=0.02)

    def test_a_bill_has_duration_equal_to_its_maturity(self):
        # Under six months there are no coupons left, so it is a zero.
        duration = par_bond_dv01(5.0, 0.25) / (100 * 1e-4)
        assert duration == pytest.approx(0.25, abs=0.01)

    def test_duration_rises_with_maturity(self):
        durations = [par_bond_dv01(4.0, n) for n in (1, 2, 5, 10, 30)]
        assert durations == sorted(durations)

    def test_duration_falls_as_yields_rise(self):
        # Higher discount rates pull the cash flows' weight forward.
        assert par_bond_dv01(8.0, 10) < par_bond_dv01(2.0, 10)

    def test_it_scales_with_face(self):
        assert par_bond_dv01(4.0, 10, face=200) == pytest.approx(2 * par_bond_dv01(4.0, 10))

    def test_a_zero_maturity_bond_is_refused(self):
        with pytest.raises(ValueError, match="maturity must be positive"):
            par_bond_dv01(4.0, 0)


class TestWeighting:
    def test_the_textbook_fly_nets_to_zero_dv01(self, synthetic):
        factors = fit_factors(synthetic)
        fly = dv01_neutral_weights(factors.tenors, ("DGS2", "DGS10"), "DGS5")
        assert fly.net_dv01 == pytest.approx(0.0)
        assert fly.leg("DGS5") == -1.0
        assert fly.leg("DGS2") == fly.leg("DGS10") == 0.5

    def test_the_factor_weighted_fly_zeroes_level_and_slope(self, synthetic):
        factors = fit_factors(synthetic)
        fly = factor_neutral_weights(factors, ("DGS2", "DGS10"), "DGS5")
        exposure = factors.exposure(fly.weights)
        assert exposure[0] == pytest.approx(0.0, abs=1e-12)
        assert exposure[1] == pytest.approx(0.0, abs=1e-12)
        assert abs(exposure[2]) > 1e-6, "it should still hold curvature"

    def test_factor_neutrality_costs_dv01_neutrality(self, real):
        # The trade-off worth stating: you can have one or the other.
        factors = fit_factors(real)
        fly = factor_neutral_weights(factors, ("DGS2", "DGS10"), "DGS5")
        assert abs(fly.net_dv01) > 1e-6

    def test_a_tenor_the_curve_lacks_is_refused(self, synthetic):
        factors = fit_factors(synthetic)
        with pytest.raises(KeyError, match="DGS99"):
            dv01_neutral_weights(factors.tenors, ("DGS2", "DGS99"), "DGS5")
        with pytest.raises(KeyError, match="DGS99"):
            factor_neutral_weights(factors, ("DGS2", "DGS10"), "DGS99")

    def test_two_wings_cannot_neutralise_three_factors(self, synthetic):
        factors = fit_factors(synthetic)
        with pytest.raises(ValueError, match="exactly two factors"):
            factor_neutral_weights(factors, ("DGS2", "DGS10"), "DGS5", neutral_to=(0, 1, 2))

    def test_the_same_tenor_twice_is_not_a_butterfly(self, synthetic):
        factors = fit_factors(synthetic)
        with pytest.raises(ValueError, match="belly between its wings"):
            factor_neutral_weights(factors, ("DGS2", "DGS2"), "DGS5")

    def test_wings_that_load_alike_are_refused_rather_than_least_squared(self, synthetic):
        # Unreachable with the bundled curve once the ordering check is in
        # front of it -- the smallest determinant over every valid fly there is
        # 0.022 -- so the degenerate factor model is built explicitly. Without
        # the guard this least-squares to weights nobody can interpret.
        fitted = fit_factors(synthetic)
        identical = fitted.loadings.copy()
        identical[:, fitted.tenors.index("DGS10")] = identical[
            :, fitted.tenors.index("DGS2")
        ]
        degenerate = CurveFactors(
            maturities=fitted.maturities,
            tenors=fitted.tenors,
            loadings=identical,
            explained=fitted.explained,
            mean_change=fitted.mean_change,
        )
        with pytest.raises(ValueError, match="not identified"):
            factor_neutral_weights(degenerate, ("DGS2", "DGS10"), "DGS5")

    def test_the_label_names_the_legs(self, synthetic):
        factors = fit_factors(synthetic)
        assert dv01_neutral_weights(factors.tenors, ("DGS2", "DGS10"), "DGS5").label.startswith(
            "2s5s10s"
        )
        assert dv01_neutral_weights(factors.tenors, ("DGS3MO", "DGS10"), "DGS2").label.startswith(
            "0.25m2s10s"
        )


class TestResidualRisk:
    def test_the_shares_are_a_decomposition(self, real):
        factors = fit_factors(real)
        variances = factors.scores(real.changes).var().to_numpy()
        fly = dv01_neutral_weights(factors.tenors, ("DGS2", "DGS10"), "DGS5")
        risk = residual_risk(fly, factors, variances)
        assert risk.variance_share.sum() == pytest.approx(1.0)
        assert (risk.variance_share >= 0).all()

    def test_the_textbook_2s5s10s_fly_barely_trades_curvature(self, real):
        # The headline finding. It is sold as a curvature trade.
        factors = fit_factors(real)
        variances = factors.scores(real.changes).var().to_numpy()
        risk = residual_risk(
            dv01_neutral_weights(factors.tenors, ("DGS2", "DGS10"), "DGS5"), factors, variances
        )
        assert risk.variance_share[2] < 0.05
        assert risk.unintended_share > 0.95

    def test_centring_the_fly_on_the_real_belly_fixes_it_without_reweighting(self, real):
        # Placement, not weighting: plain 50-50 DV01 weights on 1s2s5s.
        factors = fit_factors(real)
        variances = factors.scores(real.changes).var().to_numpy()
        risk = residual_risk(
            dv01_neutral_weights(factors.tenors, ("DGS1", "DGS5"), "DGS2"), factors, variances
        )
        assert risk.variance_share[2] > 0.90

    def test_factor_weighting_also_fixes_it(self, real):
        factors = fit_factors(real)
        variances = factors.scores(real.changes).var().to_numpy()
        risk = residual_risk(
            factor_neutral_weights(factors, ("DGS2", "DGS10"), "DGS5"), factors, variances
        )
        assert risk.variance_share[2] == pytest.approx(1.0, abs=1e-6)

    def test_a_trade_with_no_risk_at_all_is_refused(self, synthetic):
        factors = fit_factors(synthetic)
        empty = Butterfly(
            tenors=factors.tenors,
            weights=np.zeros(len(factors.tenors)),
            wings=("DGS2", "DGS10"),
            belly="DGS5",
            label="nothing",
        )
        with pytest.raises(ValueError, match="no factor risk"):
            residual_risk(empty, factors, factors.scores(synthetic.changes).var().to_numpy())

    def test_describe_names_every_factor(self, real):
        factors = fit_factors(real)
        variances = factors.scores(real.changes).var().to_numpy()
        text = residual_risk(
            dv01_neutral_weights(factors.tenors, ("DGS2", "DGS10"), "DGS5"), factors, variances
        ).describe()
        for name in ("level", "slope", "curvature"):
            assert name in text
