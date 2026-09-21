"""Plain English in, a validated strategy out -- or a refusal that explains itself."""

from __future__ import annotations

import pytest

from curve_lab.intent import IntentError, Strategy, parse


class TestReadingTheLegs:
    @pytest.mark.parametrize(
        ("text", "wings", "belly"),
        [
            ("2s5s10s butterfly", ("DGS2", "DGS10"), "DGS5"),
            ("a 1s2s5s fly", ("DGS1", "DGS5"), "DGS2"),
            ("5s10s30s", ("DGS5", "DGS30"), "DGS10"),
            ("fly on 3m, 2y and 10y", ("DGS3MO", "DGS10"), "DGS2"),
        ],
    )
    def test_it_reads_the_three_legs(self, text, wings, belly):
        strategy = parse(text)
        assert strategy.wings == wings
        assert strategy.belly == belly

    def test_the_run_together_form_survives_neighbouring_words(self):
        # "factor-neutral1s2s5s" has no word boundary before the digits once
        # spaces are stripped, which is how an earlier version silently
        # returned the default fly for every such request.
        assert parse("a factor-neutral 1s2s5s fly").belly == "DGS2"

    def test_a_two_leg_spread_is_refused_with_a_useful_message(self):
        with pytest.raises(IntentError, match="two-leg spread"):
            parse("2s10s fly")

    def test_a_tenor_the_curve_lacks_is_named_in_the_error(self):
        with pytest.raises(IntentError, match="4s"):
            parse("4s8s12s fly")

    def test_a_belly_outside_its_wings_is_refused(self):
        with pytest.raises(IntentError, match="belly between its wings"):
            parse("a 30s2s5s fly")

    def test_naming_only_one_tenor_is_refused(self):
        with pytest.raises(IntentError, match="needs three tenors"):
            parse("a fly on the 10 year")


class TestReadingTheSettings:
    @pytest.mark.parametrize(
        ("text", "days"),
        [("daily", 1), ("weekly", 5), ("monthly", 21), ("quarterly", 63),
         ("every 3 days", 3), ("every 7 day", 7), ("every 2d", 2)],
    )
    def test_rebalance_frequency(self, text, days):
        assert parse(f"2s5s10s {text}").rebalance_days == days

    @pytest.mark.parametrize(
        ("text", "cost"), [("1bp", 1.0), ("0.25 bp", 0.25), ("frictionless", 0.0),
                           ("no costs", 0.0), ("zero cost", 0.0)]
    )
    def test_costs(self, text, cost):
        assert parse(f"2s5s10s with {text}").cost_bp == cost

    def test_dates(self):
        strategy = parse("2s5s10s since 2010 to 2020")
        assert strategy.start == "2010-01-01"
        assert strategy.end == "2020-12-31"

    def test_a_full_date_is_kept_exactly(self):
        assert parse("2s5s10s from 2015-06-01").start == "2015-06-01"

    @pytest.mark.parametrize(
        ("text", "weighting"),
        [("dv01-neutral", "dv01"), ("duration neutral", "dv01"), ("textbook", "dv01"),
         ("factor-neutral", "factor"), ("pca weighted", "factor")],
    )
    def test_weighting(self, text, weighting):
        assert parse(f"2s5s10s {text}").weighting == weighting

    def test_a_later_word_overrides_an_earlier_one(self):
        # People correct themselves mid-sentence. Resolving by dictionary
        # order instead makes both orderings mean the same thing.
        assert parse("a dv01-neutral but actually factor-neutral fly").weighting == "factor"
        assert parse("a factor-neutral but actually dv01-neutral fly").weighting == "dv01"

    def test_unmentioned_settings_keep_their_default(self):
        strategy = parse("2s5s10s")
        assert strategy.weighting == "dv01"
        assert strategy.rebalance_days == 21
        assert strategy.start is None

    def test_a_supplied_default_is_the_starting_point(self):
        base = Strategy(cost_bp=3.0, rebalance_days=7)
        assert parse("2s5s10s weekly", default=base).cost_bp == 3.0


class TestValidation:
    def test_the_parse_always_returns_something_validated(self):
        # Nothing downstream re-checks, so the parser is the only gate.
        assert parse("2s5s10s").validated() is not None

    def test_an_absurd_cost_is_refused(self):
        with pytest.raises(IntentError, match="not a Treasury market"):
            parse("2s5s10s with 90bp costs")

    def test_an_absurd_rebalance_period_is_refused(self):
        with pytest.raises(IntentError, match="between 1 and 252"):
            Strategy(rebalance_days=500).validated()

    def test_an_unknown_weighting_is_refused(self):
        with pytest.raises(IntentError, match="unknown weighting"):
            Strategy(weighting="vibes").validated()

    def test_an_unknown_tenor_is_refused(self):
        with pytest.raises(IntentError, match="unknown tenor"):
            Strategy(belly="DGS99").validated()

    def test_empty_input_is_refused(self):
        with pytest.raises(IntentError, match="nothing to read"):
            parse("   ")

    def test_describe_round_trips_the_settings(self):
        text = parse("factor-neutral 1s2s5s since 2010, weekly, 1bp").describe()
        assert "1s2s5s" in text and "factor" in text and "5d" in text and "2010" in text
