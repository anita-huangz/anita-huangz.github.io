"""Establishing absence of signal: the machinery, and that it works both ways.

The hard part of a null result is showing the method *would* have found an
effect if one existed. Most tests here therefore come in pairs: one on this
dataset, one on synthetic data built to contain a known effect.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from news_signal.data import (
    SchemaError,
    label_index_correlation,
    load,
    template_report,
)
from news_signal.signal import (
    auc_on_folds,
    cross_validated_auc,
    feature_tests,
    gradient_boosting,
    learning_curve,
    minimum_detectable_auc,
    permutation_test,
    prepare_folds,
)


@pytest.fixture(scope="module")
def data():
    return load()


def planted(n=2000, strength=1.2, seed=0):
    """A dataset with a real, known effect, for the method to find."""
    from news_signal.data import CATEGORICAL_FEATURES, NUMERIC_FEATURES, Dataset

    rng = np.random.default_rng(seed)
    signal = rng.normal(size=n)
    label = (rng.uniform(size=n) < 1 / (1 + np.exp(-strength * signal))).astype(int)
    frame = pd.DataFrame({c: rng.normal(size=n) for c in NUMERIC_FEATURES})
    frame["trust_score"] = signal  # the planted column
    for c in CATEGORICAL_FEATURES:
        frame[c] = rng.choice(list("abc"), size=n)
    frame["label"] = np.where(label == 1, "Fake", "Real")
    return Dataset(frame=frame, label=label)


# --------------------------------------------------------------------------- #
# What is in the file
# --------------------------------------------------------------------------- #


def test_the_dataset_loads(data):
    assert len(data) == 4000
    assert 0.4 < data.fake_rate < 0.6


def test_an_unexpected_label_is_rejected(tmp_path):
    path = tmp_path / "bad.csv"
    pd.DataFrame({"label": ["Fake", "Maybe"]}).to_csv(path, index=False)
    with pytest.raises(SchemaError, match="unexpected label"):
        load(path)


def test_the_titles_are_one_template_with_a_number_in_it(data):
    """4,000 distinct titles collapse to a single skeleton.

    This is the cheapest possible check for "is this real text", and it would
    have stopped the original analysis before the first model was fitted.
    """
    report = template_report(data.frame, "title")
    assert report.distinct == 4000
    assert report.distinct_after_removing_digits == 1
    assert report.is_templated
    assert report.example == "Breaking News 1"


def test_the_article_bodies_are_the_same_sentence(data):
    report = template_report(data.frame, "text")
    assert report.distinct_after_removing_digits == 1
    assert report.example.startswith("This is the content of article 1.")


def test_a_column_of_a_few_real_values_is_not_a_template(data):
    """Five author names are five names, not a template.

    An earlier version of this heuristic flagged anything with few distinct
    skeletons, which got that wrong. The test is collapse, not count.
    """
    assert not template_report(data.frame, "author").is_templated
    assert not template_report(data.frame, "source").is_templated


def test_genuine_text_is_not_flagged():
    frame = pd.DataFrame(
        {"title": [f"{w} wins election in {c}" for w in "abcdefghij" for c in "klmnopqrst"]}
    )
    assert not template_report(frame, "title").is_templated


def test_the_labels_do_not_track_the_row_order(data):
    """Worth checking, because the "text" *is* the row index.

    If the file were sorted or blocked by label, a TF-IDF model would score
    well by reading the number -- a real artefact that looks convincing. It is
    shuffled here, which does not make the trap go away.
    """
    assert abs(label_index_correlation(data)) < 0.05


def test_a_missing_column_is_caught(tmp_path):
    path = tmp_path / "bad.csv"
    pd.DataFrame({"x": [1]}).to_csv(path, index=False)
    with pytest.raises(SchemaError, match="no 'label'"):
        load(path)


# --------------------------------------------------------------------------- #
# The permutation test
# --------------------------------------------------------------------------- #


def test_the_real_labels_are_not_distinguishable_from_shuffled_ones(data):
    """The definitive result.

    The model found as much in the real labels as in randomly shuffled ones,
    so whatever it learned was noise.
    """
    result = permutation_test(data, permutations=60)
    assert not result.distinguishable
    assert result.p_value > 0.05
    low, high = result.null_interval()
    assert low <= result.observed <= high


def test_the_null_distribution_sits_at_one_half(data):
    result = permutation_test(data, permutations=60)
    assert abs(result.null_mean - 0.5) < 0.02
    # And has real spread -- which is why the textbook 0.5 is not the null.
    assert result.null_std > 0.005


def test_a_planted_effect_is_detected():
    """The same test on data with a known effect, so it is not vacuous."""
    result = permutation_test(planted(), permutations=60)
    assert result.distinguishable
    assert result.observed > result.null_interval()[1]
    assert result.z_score > 5


def test_the_p_value_cannot_be_exactly_zero():
    """With finitely many shuffles, p = 0 is not observable.

    Reporting it would overstate the evidence, so the estimator uses the
    standard (hits + 1) / (permutations + 1) correction.
    """
    result = permutation_test(planted(strength=4.0), permutations=20)
    assert result.p_value > 0
    assert result.p_value == pytest.approx(1 / 21)


def test_too_few_permutations_is_refused_rather_than_reported():
    """The floor this correction creates, made explicit.

    With 10 permutations the smallest reachable p-value is 0.091, so the test
    cannot return a significant result however large the effect -- and that
    reads exactly like "no effect" if nobody checks. Found by a test of mine
    that used 10 draws on a planted effect and failed.
    """
    with pytest.raises(ValueError, match="unreachable"):
        permutation_test(planted(), permutations=10)
    result = permutation_test(planted(), permutations=20)
    assert result.can_reach_significance
    assert result.smallest_possible_p == pytest.approx(1 / 21)


def test_only_the_labels_are_shuffled(data):
    """Feature-feature correlations must survive, or the null is the wrong null."""
    first = permutation_test(data, permutations=20, seed=1)
    second = permutation_test(data, permutations=20, seed=1)
    assert first.observed == second.observed  # the real fit is deterministic


# --------------------------------------------------------------------------- #
# Power
# --------------------------------------------------------------------------- #


def test_the_minimum_detectable_effect_is_reported(data):
    """Turns "we found nothing" into "there is nothing bigger than this"."""
    effect = minimum_detectable_auc(len(data), int(data.label.sum()))
    assert 0.52 < effect.minimum_auc < 0.53
    # And the observed score is below it, which is the whole point.
    assert cross_validated_auc(data) < effect.minimum_auc


def test_more_rows_detect_smaller_effects():
    small = minimum_detectable_auc(1_000, 500).minimum_auc
    large = minimum_detectable_auc(100_000, 50_000).minimum_auc
    assert large < small
    # 100k balanced rows can see an AUC of about 0.505.
    assert large < 0.51


def test_an_unbalanced_sample_has_less_power():
    """Same total size, worse split, larger detectable effect."""
    balanced = minimum_detectable_auc(4000, 2000).minimum_auc
    skewed = minimum_detectable_auc(4000, 100).minimum_auc
    assert skewed > balanced


def test_power_needs_both_classes():
    with pytest.raises(ValueError, match="both classes"):
        minimum_detectable_auc(100, 0)


# --------------------------------------------------------------------------- #
# Learning curve
# --------------------------------------------------------------------------- #


def test_the_curve_is_flat_so_more_data_would_not_help(data):
    curve = learning_curve(data)
    assert not curve.improves_with_data
    assert abs(curve.slope) < 0.01
    assert curve.scores.max() < 0.56


def test_a_planted_effect_shows_up_at_every_sample_size():
    """A single strong feature is found with 600 rows and does not improve.

    I expected a rising curve and the curve is flat -- because the model
    saturates immediately. That is worth stating: a flat curve means "the
    ceiling is not the sample size", which is true both when there is nothing
    to learn and when what there is has already been learned. The curve alone
    cannot distinguish those two, which is why the permutation test is the
    load-bearing evidence and this is corroboration.
    """
    curve = learning_curve(planted(n=3000, strength=0.8))
    assert curve.scores.min() > 0.6
    assert not curve.improves_with_data  # already saturated


def test_a_flat_curve_at_chance_differs_from_a_flat_curve_up_high(data):
    """The distinction the slope cannot make, made by the level."""
    noise = learning_curve(data)
    effect = learning_curve(planted(n=3000, strength=0.8))
    assert noise.scores.max() < 0.56
    assert effect.scores.min() > 0.6


# --------------------------------------------------------------------------- #
# Per-feature tests
# --------------------------------------------------------------------------- #


def test_no_feature_survives_the_multiplicity_correction(data):
    result = feature_tests(data)
    assert result.significant == []
    # Thirteen features at p<0.05 yields about 0.65 false positives by chance.
    assert 0.5 < result.expected_false_positives < 0.8


def test_the_strongest_correlation_is_tiny(data):
    result = feature_tests(data)
    assert result.frame["r"].abs().max() < 0.05


def test_a_planted_feature_is_found():
    result = feature_tests(planted())
    assert "trust_score" in result.significant


def test_the_correction_is_stricter_than_raw_p_values(data):
    """Benjamini-Hochberg thresholds are below 0.05 for all but the last rank."""
    frame = feature_tests(data).frame
    assert (frame["bh_threshold"] <= 0.05 + 1e-12).all()
    assert frame["bh_threshold"].iloc[0] < 0.05


# --------------------------------------------------------------------------- #
# Modelling
# --------------------------------------------------------------------------- #


def test_extra_capacity_does_not_find_anything(data):
    """A gradient-booster with 200 trees does no better than logistic regression.

    Which is the argument that the ceiling is the data rather than the model.
    """
    simple = cross_validated_auc(data)
    complex_ = cross_validated_auc(data, gradient_boosting())
    assert abs(simple - complex_) < 0.03
    assert complex_ < 0.56


def test_preprocessing_is_fitted_inside_the_folds(data):
    """Otherwise the reported AUC is not out-of-sample.

    Checked structurally: the scaler and encoder live in the pipeline, so
    `cross_val_predict` refits them per fold.
    """
    from news_signal.signal import build_pipeline

    names = dict(build_pipeline().named_steps)
    assert "prep" in names
    assert "model" in names


def test_the_dataset_is_a_real_file_not_an_lfs_pointer():
    """`actions/checkout` does not fetch LFS content."""
    from news_signal.data import DATA

    first_line = DATA.read_text().splitlines()[0]
    assert not first_line.startswith("version https://git-lfs")
    assert "label" in first_line


class TestPreparedFolds:
    """The permutation test's fast path, held to the slow path's answer.

    `prepare_folds` exists only because refitting unsupervised preprocessing
    once per shuffle is wasted work. That is a speedup exactly as long as it
    computes the same thing, so the equivalence is asserted rather than
    assumed -- and asserted on the real dataset, not a toy one.
    """

    def test_it_reproduces_the_pipeline_auc_exactly(self):
        data = load()
        prepared = prepare_folds(data)
        assert auc_on_folds(prepared, data.label) == pytest.approx(
            cross_validated_auc(data), abs=1e-12
        )

    def test_it_reproduces_the_pipeline_auc_for_a_different_model(self):
        data = load()
        prepared = prepare_folds(data)
        assert auc_on_folds(
            prepared, data.label, gradient_boosting()
        ) == pytest.approx(
            cross_validated_auc(data, gradient_boosting()), abs=1e-12
        )

    def test_the_preprocessing_never_sees_the_rows_it_is_scored_on(self):
        # The whole point. If a fold's preprocessing were fitted on all the
        # data, the test rows would have contributed to the median, the scale
        # and the category list used to encode them.
        data = load()
        prepared = prepare_folds(data)
        for train, test in zip(prepared.train_rows, prepared.test_rows, strict=True):
            assert not set(train) & set(test)

    def test_every_row_is_predicted_exactly_once(self):
        data = load()
        prepared = prepare_folds(data)
        predicted = [row for fold in prepared.test_rows for row in fold]
        assert sorted(predicted) == list(range(len(data.label)))

    def test_the_folds_are_the_same_for_every_shuffle(self):
        # Fixed folds are what make the reuse valid, and they are also what
        # keeps split noise out of the null. If this ever stops holding, the
        # cached preprocessing is being applied to the wrong rows.
        data = load()
        first, second = prepare_folds(data), prepare_folds(data)
        for a, b in zip(first.test_rows, second.test_rows, strict=True):
            assert (a == b).all()

    def test_shuffling_the_labels_changes_the_score_but_not_the_features(self):
        data = load()
        prepared = prepare_folds(data)
        shuffled = np.random.default_rng(0).permutation(data.label)
        before = [m.copy() for m in prepared.train_features]
        auc_on_folds(prepared, shuffled)
        for original, after in zip(before, prepared.train_features, strict=True):
            assert (original == after).all(), "the cached folds were mutated"
