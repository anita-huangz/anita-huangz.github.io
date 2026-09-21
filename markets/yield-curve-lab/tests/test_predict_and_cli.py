"""Forecast evaluation, and the command line that reports it."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from sklearn.dummy import DummyRegressor
from sklearn.linear_model import Ridge

from curve_lab.cli import main
from curve_lab.pca import fit_factors
from curve_lab.predict import Forecast, feature_matrix, forecast_factor, walk_forward
from curve_lab.warehouse import open_warehouse


def forecast_of(actual, predicted) -> Forecast:
    index = pd.bdate_range("2020-01-01", periods=len(actual))
    return Forecast(
        factor="test",
        horizon_days=5,
        actual=pd.Series(actual, index=index, dtype=float),
        predicted=pd.Series(predicted, index=index, dtype=float),
        baseline=pd.Series(0.0, index=index),
        folds=2,
        n_features=3,
    )


class TestScoring:
    def test_a_perfect_forecast_scores_one(self):
        values = [1.0, -2.0, 3.0, -4.0]
        assert forecast_of(values, values).r2_vs_baseline == pytest.approx(1.0)

    def test_predicting_zero_scores_exactly_zero(self):
        # Because the baseline *is* predicting zero.
        assert forecast_of([1.0, -2.0, 3.0], [0.0, 0.0, 0.0]).r2_vs_baseline == 0.0

    def test_a_worse_than_baseline_forecast_scores_negative(self):
        assert forecast_of([1.0, -1.0], [-5.0, 5.0]).r2_vs_baseline < 0

    def test_directional_accuracy_counts_signs_only(self):
        # Right sign, hopeless magnitude: still 100% directional.
        assert forecast_of([1.0, -1.0, 2.0], [9.0, -9.0, 9.0]).directional_accuracy == 1.0
        assert forecast_of([1.0, -1.0], [-1.0, 1.0]).directional_accuracy == 0.0

    def test_days_the_factor_did_not_move_are_not_counted(self):
        assert forecast_of([0.0, 1.0], [5.0, 5.0]).directional_accuracy == 1.0

    def test_a_factor_that_never_moves_has_no_directional_accuracy(self):
        assert forecast_of([0.0, 0.0], [1.0, 1.0]).directional_accuracy == 0.0

    def test_beating_the_baseline_needs_significance_not_just_a_better_mean(self):
        rng = np.random.default_rng(0)
        actual = rng.normal(size=400)
        barely = actual * 0.01 + rng.normal(scale=1.0, size=400)
        assert not forecast_of(actual, barely).beats_baseline

    def test_a_genuinely_better_forecast_is_recognised(self):
        rng = np.random.default_rng(1)
        actual = rng.normal(size=400)
        good = actual + rng.normal(scale=0.1, size=400)
        forecast = forecast_of(actual, good)
        assert forecast.r2_vs_baseline > 0.9
        assert forecast.beats_baseline

    def test_identical_errors_are_not_a_significant_difference(self):
        values = [1.0, -1.0, 2.0, -2.0]
        statistic, p_value = forecast_of(values, [0.0] * 4).diebold_mariano
        assert statistic == 0.0 and p_value == 1.0

    def test_describe_states_the_verdict(self):
        text = forecast_of([1.0, -1.0], [0.0, 0.0]).describe()
        assert "random walk" in text and "R2" in text


class TestWalkForward:
    def test_no_fold_is_scored_on_a_day_it_trained_on(self, synthetic):
        with open_warehouse(synthetic) as warehouse:
            factors = fit_factors(synthetic)
            features = feature_matrix(warehouse, factors)
        target = features["yield_DGS10"].shift(-5).dropna()
        predicted, actual = walk_forward(
            features, target, folds=3, min_train=200, model=DummyRegressor()
        )
        # Every prediction lands after the initial training window.
        assert predicted.index.min() > features.index[199]
        assert predicted.index.equals(actual.index)
        assert not predicted.index.has_duplicates

    def test_too_little_data_for_the_window_is_refused(self, synthetic):
        with open_warehouse(synthetic) as warehouse:
            features = feature_matrix(warehouse, fit_factors(synthetic))
        with pytest.raises(ValueError, match="not enough"):
            walk_forward(features, features["yield_DGS10"], folds=3, min_train=100_000)

    def test_a_caller_supplied_model_is_used(self, synthetic):
        with open_warehouse(synthetic) as warehouse:
            features = feature_matrix(warehouse, fit_factors(synthetic))
        target = features["yield_DGS10"].shift(-5).dropna()
        predicted, _ = walk_forward(
            features, target, folds=2, min_train=300, model=Ridge(alpha=1.0)
        )
        assert len(predicted) > 0


class TestFeatureMatrix:
    def test_one_row_per_day_with_the_tenor_in_each_name(self, synthetic):
        with open_warehouse(synthetic) as warehouse:
            features = feature_matrix(warehouse, fit_factors(synthetic))
        assert features.index.is_unique
        assert any(name.startswith("yield_DGS10") for name in features.columns)
        assert "spread_DGS2_DGS10" in features.columns

    def test_it_has_no_missing_values_left(self, synthetic):
        with open_warehouse(synthetic) as warehouse:
            features = feature_matrix(warehouse, fit_factors(synthetic))
        assert not features.isna().to_numpy().any()


class TestAgainstTheRealCurve:
    def test_gradient_boosting_does_not_beat_a_random_walk(self, real):
        # The finding. Sixty-six features and a tuned model, and the honest
        # answer is that the curve factors are not forecastable at this horizon.
        factors = fit_factors(real)
        with open_warehouse(real) as warehouse:
            forecast = forecast_factor(
                warehouse, factors, real.changes, factor_index=2, folds=3
            )
        assert not forecast.beats_baseline
        assert forecast.r2_vs_baseline < 0
        assert 0.45 < forecast.directional_accuracy < 0.56


class TestCommandLine:
    @pytest.mark.parametrize(
        "section", ["factors", "trade", "backtest", "carry", "cycles"]
    )
    def test_each_section_runs(self, section, capsys):
        assert main(["--section", section, "--start", "2015-01-01"]) == 0
        assert capsys.readouterr().out.strip()

    def test_the_default_run_reports_the_headline_finding(self, capsys):
        assert main(["--section", "trade"]) == 0
        out = capsys.readouterr().out
        assert "DV01-neutral" in out and "factor-neutral" in out

    def test_a_strategy_sentence_is_honoured(self, capsys):
        assert main(["--strategy", "factor-neutral 1s2s5s since 2015, weekly, 1bp",
                     "--section", "backtest"]) == 0
        out = capsys.readouterr().out
        assert "1s2s5s" in out and "5d" in out

    def test_an_unreadable_strategy_is_a_user_error(self, capsys):
        assert main(["--strategy", "2s10s fly"]) == 2
        assert "two-leg spread" in capsys.readouterr().err

    def test_a_missing_csv_is_an_operational_error(self, capsys, tmp_path):
        assert main(["--csv", str(tmp_path / "absent.csv")]) == 1
        assert "error:" in capsys.readouterr().err

    def test_explicit_dates_override_the_sentence(self, capsys):
        assert main(["--strategy", "2s5s10s since 2010", "--start", "2018-01-01",
                     "--section", "backtest"]) == 0
        assert "2018-01-01" in capsys.readouterr().out

    def test_help_exits_cleanly(self):
        with pytest.raises(SystemExit) as exit:
            main(["--help"])
        assert exit.value.code == 0
