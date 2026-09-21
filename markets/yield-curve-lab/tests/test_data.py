"""Loading a curve, and refusing the ones that would produce plausible lies."""

from __future__ import annotations

import pandas as pd
import pytest

from conftest import synthetic_frame
from curve_lab.data import MAX_GAP_DAYS, TENORS, Curve, SchemaError, load, validate


class TestTheBundledSnapshot:
    def test_it_loads(self, real):
        assert len(real) > 10_000
        assert real.tenors == list(TENORS)

    def test_it_is_continuous(self, real):
        # The reason the 20-year tenor is not in the file. A hole here means
        # one row of carry gets booked across however long the hole is.
        gaps = real.dates.to_series().diff().dt.days
        assert gaps.max() <= MAX_GAP_DAYS

    def test_it_starts_where_every_tenor_is_available(self, real):
        assert real.dates.min() == pd.Timestamp("1981-09-01")

    def test_yields_are_percent_not_decimals(self, real):
        # 4.5 means 4.5%. If this ever became 0.045 every DV01 would be wrong
        # by two orders of magnitude and nothing would raise.
        assert real.frame.to_numpy().min() >= 0.0
        assert 10.0 < real.frame.to_numpy().max() < 25.0

    def test_maturities_line_up_with_the_columns(self, real):
        assert list(real.maturities) == [TENORS[t] for t in real.tenors]
        assert list(real.maturities) == sorted(real.maturities)


class TestValidation:
    def test_an_unknown_column_is_refused(self):
        frame = synthetic_frame(days=20)
        frame["DGS100"] = 1.0
        with pytest.raises(SchemaError, match="unknown tenor"):
            validate(frame)

    def test_two_tenors_are_not_a_curve(self):
        frame = synthetic_frame(days=20)[["DGS2", "DGS10"]]
        with pytest.raises(SchemaError, match="at least three tenors"):
            validate(frame)

    def test_columns_out_of_order_are_reordered_not_refused(self):
        # The order is a presentation detail of the file, but every factor
        # loading is read as a shape across it, so it cannot be left shuffled.
        frame = synthetic_frame(days=20)
        shuffled = frame[list(reversed(frame.columns))]
        assert validate(shuffled).tenors == list(TENORS)

    def test_dates_out_of_order_are_refused(self):
        frame = synthetic_frame(days=20).iloc[::-1]
        with pytest.raises(SchemaError, match="not in order"):
            validate(frame)

    def test_duplicate_dates_are_refused(self):
        frame = synthetic_frame(days=20)
        doubled = pd.concat([frame, frame.iloc[[5]]]).sort_index()
        with pytest.raises(SchemaError, match="duplicate dates"):
            validate(doubled)

    def test_missing_yields_are_refused(self):
        frame = synthetic_frame(days=20)
        frame.iloc[3, 2] = None
        with pytest.raises(SchemaError, match="missing yields"):
            validate(frame)

    def test_a_hole_in_the_index_is_refused_and_says_why(self):
        # The DGS20 trap, reproduced: drop a stretch and the two rows either
        # side end up adjacent.
        frame = synthetic_frame(days=200)
        holed = pd.concat([frame.iloc[:50], frame.iloc[150:]])
        with pytest.raises(SchemaError, match="hole ends"):
            validate(holed)

    def test_a_long_weekend_is_not_a_hole(self):
        frame = synthetic_frame(days=60)
        dropped = frame.drop(frame.index[10:13])
        assert len(validate(dropped)) == 57


class TestCurve:
    def test_changes_are_first_differences(self, synthetic):
        assert len(synthetic.changes) == len(synthetic) - 1
        expected = synthetic.frame["DGS10"].iloc[5] - synthetic.frame["DGS10"].iloc[4]
        assert synthetic.changes["DGS10"].iloc[4] == pytest.approx(expected)

    def test_a_spread_is_in_basis_points_long_minus_short(self, synthetic):
        spread = synthetic.spread("DGS2", "DGS10")
        manual = (synthetic.frame["DGS10"] - synthetic.frame["DGS2"]) * 100
        assert spread.iloc[0] == pytest.approx(manual.iloc[0])

    def test_an_unknown_tenor_in_a_spread_names_what_is_available(self, synthetic):
        with pytest.raises(KeyError, match="DGS2"):
            synthetic.spread("DGS2", "DGS99")

    def test_slicing_keeps_it_a_curve(self, synthetic):
        cut = synthetic.slice("2016-01-01", "2016-12-31")
        assert isinstance(cut, Curve)
        assert cut.dates.min().year == 2016


class TestLoading:
    def test_a_missing_file_says_so(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="no curve snapshot"):
            load(tmp_path / "absent.csv")

    def test_a_written_curve_reads_back(self, tmp_path, synthetic):
        path = tmp_path / "curve.csv"
        synthetic.frame.to_csv(path)
        assert load(path).tenors == synthetic.tenors
