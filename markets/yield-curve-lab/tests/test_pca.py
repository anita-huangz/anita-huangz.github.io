"""The factor decomposition: does it recover shapes that were really there?"""

from __future__ import annotations

import numpy as np
import pytest

from conftest import synthetic_frame
from curve_lab.data import Curve
from curve_lab.pca import FACTOR_NAMES, fit_factors


class TestRecovery:
    def test_it_finds_three_shapes_in_data_built_from_three_shapes(self, synthetic):
        factors = fit_factors(synthetic, n_components=3)
        # The synthetic curve is driven by level, slope and curvature with
        # variances 0.060 : 0.030 : 0.012, so the components should come back
        # in that order and account for nearly everything.
        assert factors.cumulative[2] > 0.99
        assert list(factors.explained) == sorted(factors.explained, reverse=True)

    def test_level_loads_the_same_sign_everywhere(self, synthetic):
        level = fit_factors(synthetic).loadings[0]
        assert (level > 0).all(), "a level shift moves every tenor the same way"

    def test_slope_has_opposite_ends(self, synthetic):
        slope = fit_factors(synthetic).loadings[1]
        assert slope[0] < 0 < slope[-1], "the convention is long end positive"

    def test_curvature_sets_the_wings_against_the_belly(self, synthetic):
        curvature = fit_factors(synthetic).loadings[2]
        belly = int(np.argmin(curvature))
        assert 0 < belly < len(curvature) - 1
        assert curvature[0] > 0 and curvature[-1] > 0

    def test_the_orientation_is_stable_across_refits(self, synthetic):
        # Eigenvectors are only defined up to sign. Without pinning them, a
        # rerun flips one and every reported loading changes sign.
        first = fit_factors(synthetic).loadings
        second = fit_factors(Curve(frame=synthetic.frame.copy())).loadings
        assert np.allclose(first, second)


class TestRealCurve:
    def test_three_factors_explain_almost_everything(self, real):
        factors = fit_factors(real)
        assert 0.94 < factors.cumulative[2] < 0.97

    def test_the_curvature_factor_bends_at_the_two_year(self, real):
        # Which is why a 2s5s10s fly, centred on the five, trades almost no
        # curvature. The whole trade section rests on this.
        factors = fit_factors(real)
        assert factors.tenors[int(factors.loadings[2].argmin())] == "DGS2"

    def test_the_names_match_the_shapes(self, real):
        factors = fit_factors(real)
        assert tuple(factors.name(i) for i in range(3)) == FACTOR_NAMES


class TestScoresAndExposure:
    def test_scores_have_one_column_per_component(self, synthetic):
        factors = fit_factors(synthetic, n_components=3)
        scores = factors.scores(synthetic.changes)
        assert list(scores.columns) == list(FACTOR_NAMES)
        assert len(scores) == len(synthetic.changes)

    def test_the_components_are_uncorrelated(self, synthetic):
        # Which is what lets the variance shares in `residual_risk` add to one
        # without a covariance term.
        scores = fit_factors(synthetic).scores(synthetic.changes)
        off_diagonal = scores.corr().to_numpy() - np.eye(3)
        assert np.abs(off_diagonal).max() < 0.05

    def test_reconstruction_round_trips(self, synthetic):
        factors = fit_factors(synthetic, n_components=len(synthetic.tenors))
        changes = synthetic.changes
        scores = factors.scores(changes).to_numpy()
        assert np.allclose(factors.reconstruct(scores), changes.to_numpy(), atol=1e-10)

    def test_exposure_is_the_loading_dotted_with_the_weights(self, synthetic):
        factors = fit_factors(synthetic)
        weights = np.zeros(len(factors.tenors))
        weights[factors.tenors.index("DGS5")] = 1.0
        column = factors.tenors.index("DGS5")
        assert np.allclose(factors.exposure(weights), factors.loadings[:, column])

    def test_a_wrong_length_weight_vector_is_refused(self, synthetic):
        factors = fit_factors(synthetic)
        with pytest.raises(ValueError, match="one weight per tenor"):
            factors.exposure(np.ones(3))


class TestRefusals:
    def test_zero_components_is_refused(self, synthetic):
        with pytest.raises(ValueError, match="at least 1"):
            fit_factors(synthetic, n_components=0)

    def test_too_few_days_to_estimate_a_covariance_is_refused(self, short_curve):
        with pytest.raises(ValueError, match="too few"):
            fit_factors(short_curve)

    def test_asking_for_more_components_than_tenors_gives_what_exists(self, synthetic):
        factors = fit_factors(synthetic, n_components=50)
        assert factors.n_components == len(synthetic.tenors)

    def test_named_components_past_the_three_fall_back_to_pc_numbers(self, synthetic):
        factors = fit_factors(synthetic, n_components=5)
        assert factors.name(4) == "pc5"


def test_explained_shares_are_a_fraction_of_the_whole():
    factors = fit_factors(Curve(frame=synthetic_frame(days=400)), n_components=9)
    assert factors.explained.sum() == pytest.approx(1.0)
