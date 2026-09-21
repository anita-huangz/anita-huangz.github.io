"""The DuckDB layer, and the look-ahead the window frames are written to avoid."""

from __future__ import annotations

import pandas as pd
import pytest

from curve_lab.warehouse import open_warehouse


@pytest.fixture
def warehouse(synthetic):
    with open_warehouse(synthetic) as w:
        yield w


class TestLoading:
    def test_every_day_and_tenor_lands_in_the_long_table(self, warehouse, synthetic):
        assert warehouse.rows == len(synthetic) * len(synthetic.tenors)

    def test_the_wide_table_round_trips(self, warehouse, synthetic):
        wide = warehouse.wide()
        assert list(wide.columns) == synthetic.tenors
        assert len(wide) == len(synthetic)

    def test_maturities_are_joined_on_rather_than_assumed(self, warehouse):
        summary = warehouse.summary()
        assert list(summary["maturity"]) == sorted(summary["maturity"])
        assert summary.loc[summary.tenor == "DGS10", "maturity"].iloc[0] == 10.0

    def test_it_can_be_written_to_a_file_and_reopened(self, synthetic, tmp_path):
        path = tmp_path / "curve.duckdb"
        with open_warehouse(synthetic, path) as w:
            expected = w.rows
        assert path.exists()
        import duckdb

        with duckdb.connect(str(path)) as connection:
            actual = connection.execute("SELECT count(*) FROM curve_long").fetchone()[0]
        assert actual == expected

    def test_closing_twice_is_harmless(self, synthetic):
        w = open_warehouse(synthetic)
        w.close()


class TestQueries:
    def test_a_spread_matches_the_arithmetic(self, warehouse, synthetic):
        spread = warehouse.spread("DGS2", "DGS10").set_index("date")["spread_bp"]
        expected = synthetic.spread("DGS2", "DGS10")
        assert spread.iloc[0] == pytest.approx(expected.iloc[0])
        assert len(spread) == len(expected)

    def test_the_summary_has_one_row_per_tenor(self, warehouse, synthetic):
        assert len(warehouse.summary()) == len(synthetic.tenors)

    def test_parameters_are_bound_not_formatted(self, warehouse):
        # A tenor name that would be a syntax error if it were interpolated.
        result = warehouse.spread("DGS2", "'; DROP TABLE curve_long; --")
        assert result.empty
        assert warehouse.rows > 0


class TestFeatures:
    def test_one_row_per_tenor_per_day(self, warehouse, synthetic):
        assert len(warehouse.features()) == len(synthetic) * len(synthetic.tenors)

    def test_a_lag_is_the_change_over_that_many_days(self, warehouse, synthetic):
        features = warehouse.features()
        one = features[features.tenor == "DGS10"].sort_values("date").reset_index(drop=True)
        yields = synthetic.frame["DGS10"].to_numpy()
        assert one["change_5d"].iloc[10] == pytest.approx(yields[10] - yields[5])

    def test_the_rolling_mean_excludes_the_day_it_sits_on(self, warehouse, synthetic):
        # `ROWS BETWEEN 21 PRECEDING AND 1 PRECEDING`, not CURRENT ROW. A mean
        # that includes today is a feature that already knows the answer.
        features = warehouse.features()
        one = features[features.tenor == "DGS10"].sort_values("date").reset_index(drop=True)
        yields = synthetic.frame["DGS10"].to_numpy()
        assert one["mean_21d"].iloc[30] == pytest.approx(yields[9:30].mean())

    def test_the_rolling_volatility_also_excludes_it(self, warehouse):
        features = warehouse.features()
        one = features[features.tenor == "DGS10"].sort_values("date").reset_index(drop=True)
        changes = one["change_1d"].to_numpy()
        assert one["vol_21d"].iloc[30] == pytest.approx(
            pd.Series(changes[9:30]).std(ddof=1)
        )

    def test_the_first_rows_have_no_history_and_say_so(self, warehouse):
        features = warehouse.features()
        one = features[features.tenor == "DGS10"].sort_values("date").reset_index(drop=True)
        assert pd.isna(one["change_1d"].iloc[0])
        assert pd.isna(one["mean_21d"].iloc[0])

    def test_the_lag_set_is_configurable(self, warehouse):
        features = warehouse.features(lags=(1, 2))
        assert "change_2d" in features.columns
        assert "change_63d" not in features.columns
