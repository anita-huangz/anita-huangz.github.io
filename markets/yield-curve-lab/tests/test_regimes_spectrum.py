"""Clustering and cycles -- both tested against the null that makes them meaningful."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from conftest import synthetic_frame
from curve_lab.data import Curve
from curve_lab.pca import fit_factors
from curve_lab.regimes import fit_regimes, shape_matrix
from curve_lab.spectrum import periodogram


class TestShapes:
    def test_each_day_is_standardised_across_tenors(self, synthetic):
        shapes = shape_matrix(synthetic)
        assert np.allclose(shapes.mean(axis=1), 0.0, atol=1e-12)
        assert np.allclose(shapes.std(axis=1), 1.0, atol=1e-9)

    def test_two_curves_with_the_same_shape_land_together(self):
        # A 16% curve in 1981 and a 4% curve in 2021 with the same slope are
        # the same shape; clustering the levels would put them in different
        # decades instead.
        base = np.array([1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0])
        frame = pd.DataFrame(
            [base, base + 12.0],
            index=pd.bdate_range("2020-01-01", periods=2, name="date"),
            columns=list(synthetic_frame(days=2).columns),
        )
        shapes = shape_matrix(Curve(frame=frame))
        assert np.allclose(shapes[0], shapes[1])

    def test_a_flat_curve_does_not_divide_by_zero(self):
        frame = pd.DataFrame(
            [[3.0] * 9] * 5,
            index=pd.bdate_range("2020-01-01", periods=5, name="date"),
            columns=list(synthetic_frame(days=2).columns),
        )
        assert np.isfinite(shape_matrix(Curve(frame=frame))).all()


class TestRegimes:
    def test_the_real_curve_has_shape_structure(self, real):
        fit = fit_regimes(real, k=3, null_draws=5, sample=800)
        assert fit.better_than_noise
        assert fit.z_score > 3

    def test_every_day_gets_a_label(self, synthetic):
        fit = fit_regimes(synthetic, k=3, null_draws=3, sample=400)
        assert len(fit.labels) == len(synthetic)
        assert set(fit.labels.unique()) <= {0, 1, 2}
        assert fit.sizes().sum() == len(synthetic)

    def test_k_below_two_is_refused(self, synthetic):
        with pytest.raises(ValueError, match="at least 2"):
            fit_regimes(synthetic, k=1)

    def test_describe_states_the_verdict(self, synthetic):
        text = fit_regimes(synthetic, k=2, null_draws=3, sample=400).describe()
        assert "silhouette" in text and "shuffled" in text


class TestSpectrum:
    def test_a_planted_cycle_is_found(self):
        days = np.arange(2000)
        series = pd.Series(np.sin(2 * np.pi * days / 40), index=days, name="planted")
        result = periodogram(series, draws=50)
        assert result.has_cycle
        assert result.peak_period == pytest.approx(40, rel=0.1)

    def test_white_noise_has_no_cycle(self):
        rng = np.random.default_rng(0)
        series = pd.Series(rng.normal(size=3000), name="noise")
        assert not periodogram(series, draws=100).has_cycle

    def test_the_threshold_is_a_maximum_not_a_mean(self):
        # A periodogram of pure noise is exponentially distributed, so the
        # largest of a few thousand bins is several times the mean by
        # construction. Testing against the mean finds a cycle in anything.
        rng = np.random.default_rng(1)
        series = pd.Series(rng.normal(size=2000), name="noise")
        result = periodogram(series, draws=100)
        assert result.threshold > 5.0

    def test_correcting_for_a_family_raises_the_bar(self):
        rng = np.random.default_rng(2)
        series = pd.Series(rng.normal(size=1500), name="noise")
        alone = periodogram(series, draws=100, family_size=1)
        corrected = periodogram(series, draws=100, family_size=3)
        assert corrected.threshold > alone.threshold

    def test_the_real_level_factor_has_no_cycle(self, real):
        factors = fit_factors(real)
        scores = factors.scores(real.changes)
        assert not periodogram(scores["level"], draws=100, family_size=3).has_cycle

    def test_a_marginal_peak_says_so(self, real):
        factors = fit_factors(real)
        scores = factors.scores(real.changes)
        text = periodogram(scores["slope"], draws=200, family_size=3).describe()
        assert "only just" in text or "nothing clears it" in text

    def test_too_short_a_series_is_refused(self):
        with pytest.raises(ValueError, match="too few"):
            periodogram(pd.Series([1.0, 2.0, 3.0], name="tiny"))

    def test_a_nonsense_family_size_is_refused(self):
        with pytest.raises(ValueError, match="at least 1"):
            periodogram(pd.Series(np.zeros(100), name="x"), family_size=0)
