"""The three untested modules: the loaders, the plots, and the command line.

Together they were 141 of the project's 488 statements and the whole reason it
sat at 65%, the lowest honest coverage in the repository.

None of them touch the network here. `data.py` imports yfinance, yahooquery and
pandas-datareader *inside* the functions, which is the seam that makes this
possible: the fake goes into `sys.modules` and the real reshaping logic runs on
synthetic frames. That logic is worth testing on its own — the branch between a
MultiIndex and a single-ticker frame is exactly where a loader quietly returns
the wrong shape.
"""

import sys
import types

import matplotlib
import numpy as np
import pandas as pd
import pytest

matplotlib.use("Agg")  # headless: no display in CI


DATES = pd.bdate_range("2023-01-02", periods=60)


def main_of():
    """Imported lazily, as the tests above do, so fakes are installed first."""
    from factor_sim.cli import main

    return main


def price_frame(tickers: list[str]) -> pd.DataFrame:
    """Deterministic synthetic closes, one column per ticker."""
    rng = np.random.default_rng(0)
    data = {
        t: 100 * np.cumprod(1 + rng.normal(0.0005, 0.01, len(DATES)))
        for t in tickers
    }
    return pd.DataFrame(data, index=DATES)


@pytest.fixture
def fake_yfinance(monkeypatch):
    """A yfinance whose `download` returns a MultiIndex frame, as the real one does."""

    def download(tickers, start=None, end=None, progress=False, auto_adjust=True):
        names = tickers if isinstance(tickers, list) else [tickers]
        closes = price_frame(names)
        columns = pd.MultiIndex.from_product([["Close", "Volume"], names])
        wide = pd.DataFrame(index=DATES, columns=columns, dtype=float)
        for name in names:
            wide[("Close", name)] = closes[name]
            wide[("Volume", name)] = 1000.0
        return wide

    module = types.ModuleType("yfinance")
    module.download = download
    monkeypatch.setitem(sys.modules, "yfinance", module)
    return module


class TestDownloadPrices:
    def test_it_extracts_close_from_a_multiindex(self, fake_yfinance):
        from factor_sim.data import download_prices

        prices = download_prices(["AAA", "BBB"], "2023-01-01", "2023-04-01")
        assert list(prices.columns) == ["AAA", "BBB"]
        assert len(prices) == len(DATES)

    def test_a_single_ticker_still_gives_a_named_column(self, monkeypatch):
        """yfinance collapses to a Series for one ticker; the column must survive."""

        def download(tickers, **kwargs):
            names = tickers if isinstance(tickers, list) else [tickers]
            return pd.DataFrame({"Close": price_frame(names)[names[0]]}, index=DATES)

        module = types.ModuleType("yfinance")
        module.download = download
        monkeypatch.setitem(sys.modules, "yfinance", module)
        from factor_sim.data import download_prices

        prices = download_prices(["AAA"], "2023-01-01", "2023-04-01")
        assert prices.shape[1] == 1

    def test_the_result_is_sorted_by_date(self, monkeypatch):
        def download(tickers, **kwargs):
            frame = price_frame(tickers)
            shuffled = frame.iloc[::-1]  # newest first, as some sources return
            return pd.DataFrame(
                {("Close", t): shuffled[t] for t in tickers},
            ).rename_axis(columns=[None, None])

        module = types.ModuleType("yfinance")
        module.download = download
        monkeypatch.setitem(sys.modules, "yfinance", module)
        from factor_sim.data import download_prices

        prices = download_prices(["AAA", "BBB"], "2023-01-01", "2023-04-01")
        assert prices.index.is_monotonic_increasing

    def test_an_empty_response_is_an_error_not_an_empty_frame(self, monkeypatch):
        """Silently returning nothing would give a backtest of zero days."""
        module = types.ModuleType("yfinance")
        module.download = lambda *a, **k: pd.DataFrame()
        monkeypatch.setitem(sys.modules, "yfinance", module)
        from factor_sim.data import download_prices

        with pytest.raises(ValueError, match="no price data"):
            download_prices(["AAA"], "2023-01-01", "2023-04-01")

    def test_a_none_response_is_also_an_error(self, monkeypatch):
        module = types.ModuleType("yfinance")
        module.download = lambda *a, **k: None
        monkeypatch.setitem(sys.modules, "yfinance", module)
        from factor_sim.data import download_prices

        with pytest.raises(ValueError, match="no price data"):
            download_prices(["AAA"], "2023-01-01", "2023-04-01")


class TestFundamentals:
    def _fake(self, monkeypatch, detail):
        module = types.ModuleType("yahooquery")

        class Ticker:
            def __init__(self, tickers):
                self.tickers = tickers

            @property
            def summary_detail(self):
                return detail

        module.Ticker = Ticker
        monkeypatch.setitem(sys.modules, "yahooquery", module)

    def test_it_returns_one_row_per_ticker(self, monkeypatch):
        self._fake(monkeypatch, {
            "AAA": {"trailingPE": 20.0, "marketCap": 1e9},
            "BBB": {"trailingPE": 10.0, "marketCap": 5e8},
        })
        from factor_sim.data import fetch_fundamentals

        frame = fetch_fundamentals(["AAA", "BBB"])
        assert list(frame.index) == ["AAA", "BBB"]
        assert frame.loc["AAA", "PE"] == 20.0

    def test_a_missing_ticker_becomes_nan_not_an_exception(self, monkeypatch):
        """A delisted name must not take the whole universe down."""
        self._fake(monkeypatch, {"AAA": {"trailingPE": 20.0, "marketCap": 1e9}})
        from factor_sim.data import fetch_fundamentals

        frame = fetch_fundamentals(["AAA", "MISSING"])
        assert np.isnan(frame.loc["MISSING", "PE"])

    def test_a_non_dict_response_is_tolerated(self, monkeypatch):
        """yahooquery returns an error *string* per ticker when it fails."""
        self._fake(monkeypatch, {"AAA": "Quote not found"})
        from factor_sim.data import fetch_fundamentals

        frame = fetch_fundamentals(["AAA"])
        assert np.isnan(frame.loc["AAA", "PE"])


class TestFamaFrench:
    def test_percentages_are_converted_to_decimals(self, monkeypatch):
        """The source publishes percent. Skipping the divide inflates alpha 100x."""
        raw = pd.DataFrame(
            {"Mkt-RF ": [1.0, -2.0], "SMB": [0.5, 0.25], "RF": [0.01, 0.01]},
            index=pd.to_datetime(["2023-01-03", "2023-01-04"]),
        )
        module = types.ModuleType("pandas_datareader.data")
        module.DataReader = lambda *a, **k: {0: raw}
        parent = types.ModuleType("pandas_datareader")
        parent.data = module
        monkeypatch.setitem(sys.modules, "pandas_datareader", parent)
        monkeypatch.setitem(sys.modules, "pandas_datareader.data", module)
        from factor_sim.data import load_fama_french

        frame = load_fama_french()
        assert frame["Mkt-RF"].iloc[0] == pytest.approx(0.01)
        assert "Mkt-RF" in frame.columns, "trailing whitespace must be stripped"
        assert isinstance(frame.index, pd.DatetimeIndex)


class TestPlotting:
    @staticmethod
    def _nav(values):
        # The column really is called NAV; passing anything else raises a
        # KeyError that a "does it draw" test would otherwise not notice.
        return pd.DataFrame(
            {"NAV": values}, index=pd.bdate_range("2023-01-02", periods=len(values))
        )

    def test_plot_nav_draws_without_a_display(self):
        from factor_sim.plotting import plot_nav

        figure = plot_nav(self._nav(np.linspace(100, 130, 40)), show=False)
        assert figure is not None
        assert len(figure.axes) == 1
        assert figure.axes[0].get_ylabel() == "NAV ($)"

    def test_plot_nav_takes_a_title(self):
        from factor_sim.plotting import plot_nav

        figure = plot_nav(self._nav([100.0, 101.0]), title="Custom", show=False)
        assert figure.axes[0].get_title() == "Custom"

    def test_plot_drawdown_draws_without_a_display(self):
        from factor_sim.plotting import plot_drawdown

        figure = plot_drawdown(self._nav([100, 120, 90, 95, 130.0]), show=False)
        assert figure is not None
        assert figure.axes[0].get_title() == "Drawdown"

    def test_the_drawdown_it_plots_is_never_above_zero(self):
        """It fills between -drawdown and 0, so the band must sit at or below 0."""
        from factor_sim.plotting import plot_drawdown

        figure = plot_drawdown(self._nav([100, 120, 90, 95, 130.0]), show=False)
        bottom, top = figure.axes[0].get_ylim()
        assert bottom <= 0
        assert top <= 0.05, "a positive drawdown would mean the sign is flipped"


class TestCommandLine:
    @pytest.fixture(autouse=True)
    def offline(self, monkeypatch, fake_yfinance):
        """Every CLI run here uses synthetic prices and never plots."""
        monkeypatch.setattr(
            "factor_sim.plotting.plot_nav", lambda *a, **k: None, raising=False
        )
        monkeypatch.setattr(
            "factor_sim.plotting.plot_drawdown", lambda *a, **k: None, raising=False
        )

    def test_a_momentum_backtest_runs(self, capsys):
        from factor_sim.cli import main

        assert main([
            "--tickers", "AAA,BBB,CCC", "--start", "2023-01-02", "--end", "2023-03-24",
            "--factors", "momentum", "--top-n", "2", "--rebalance-every", "5",
        ]) == 0
        assert capsys.readouterr().out.strip()

    def test_drawdowns_can_be_requested(self, capsys):
        from factor_sim.cli import main

        assert main([
            "--tickers", "AAA,BBB,CCC", "--start", "2023-01-02", "--end", "2023-03-24",
            "--factors", "momentum", "--top-n", "2", "--rebalance-every", "5",
            "--drawdowns", "3",
        ]) == 0
        assert capsys.readouterr().out.strip()

    def test_an_unknown_flag_exits_nonzero(self):
        from factor_sim.cli import main

        with pytest.raises(SystemExit) as exit:
            main(["--not-a-real-flag"])
        assert exit.value.code != 0

    def test_help_exits_cleanly(self):
        from factor_sim.cli import main

        with pytest.raises(SystemExit) as exit:
            main(["--help"])
        assert exit.value.code == 0


BASE = [
    "--tickers", "AAA,BBB,CCC", "--start", "2023-01-02", "--end", "2023-03-24",
    "--factors", "momentum", "--top-n", "2", "--rebalance-every", "5",
]


class TestCommandLineFailureModes:
    """What the CLI does when the world does not cooperate.

    Every one of these is a path a reader running it for the first time can
    hit — a typo'd factor, a ticker Yahoo does not know, a benchmark that is
    delisted — and none of them had ever been executed by a test.
    """

    @pytest.fixture(autouse=True)
    def no_plots(self, monkeypatch):
        monkeypatch.setattr(
            "factor_sim.plotting.plot_nav", lambda *a, **k: None, raising=False
        )
        monkeypatch.setattr(
            "factor_sim.plotting.plot_drawdown", lambda *a, **k: None, raising=False
        )

    def test_an_unknown_factor_lists_the_ones_that_exist(self, capsys):
        from factor_sim.cli import main

        assert main([*BASE[:8], "--factors", "vibes"]) == 2
        err = capsys.readouterr().err
        assert "unknown factor(s)" in err
        assert "momentum" in err, "the error should name what is available"

    def test_a_look_ahead_factor_warns_before_it_is_used(self, fake_yfinance, monkeypatch, capsys):
        # value and size are scored from a present-day fundamentals snapshot
        # applied to historical rebalances. That is look-ahead bias, and the
        # run must say so rather than quietly reporting a flattering number.
        import factor_sim.data as data

        monkeypatch.setattr(
            data,
            "fetch_fundamentals",
            lambda tickers: pd.DataFrame(
                {"trailingPE": [20.0, 25.0, 30.0], "marketCap": [1e9, 2e9, 3e9]},
                index=["AAA", "BBB", "CCC"],
            ),
        )
        assert main_of()([*BASE, "--factors", "value", "--benchmark", "none"]) == 0
        assert "look-ahead bias" in capsys.readouterr().err

    def test_unreachable_market_data_is_an_operational_failure(self, monkeypatch, capsys):
        import factor_sim.data as data

        def down(*args, **kwargs):
            raise RuntimeError("connection reset by peer")

        monkeypatch.setattr(data, "download_prices", down)
        # 1, not 2: nothing the caller typed was wrong.
        assert main_of()(BASE) == 1
        assert "failed to load market data" in capsys.readouterr().err

    def test_a_missing_benchmark_degrades_to_a_run_without_one(
        self, fake_yfinance, monkeypatch, capsys
    ):
        # The benchmark is a separate download precisely so it cannot enter the
        # tradable universe. When it fails, the backtest is still worth having.
        import factor_sim.data as data

        real = data.download_prices

        def only_the_universe(tickers, *args, **kwargs):
            if tickers == ["DELISTED"]:
                raise RuntimeError("no data for DELISTED")
            return real(tickers, *args, **kwargs)

        monkeypatch.setattr(data, "download_prices", only_the_universe)
        assert main_of()([*BASE, "--benchmark", "DELISTED"]) == 0
        captured = capsys.readouterr()
        assert "skipping the benchmark comparison" in captured.err
        assert "Annualised" in captured.out or captured.out.strip()

    def test_none_skips_the_benchmark_without_downloading_it(
        self, fake_yfinance, monkeypatch, capsys
    ):
        import factor_sim.data as data

        asked: list = []
        real = data.download_prices

        def record(tickers, *args, **kwargs):
            asked.append(tickers)
            return real(tickers, *args, **kwargs)

        monkeypatch.setattr(data, "download_prices", record)
        assert main_of()([*BASE, "--benchmark", "none"]) == 0
        capsys.readouterr()
        assert asked == [["AAA", "BBB", "CCC"]], "no second download for a benchmark"

    def test_an_empty_benchmark_string_is_treated_as_none(self, fake_yfinance, capsys):
        assert main_of()([*BASE, "--benchmark", "  "]) == 0
        capsys.readouterr()

    def test_a_benchmark_that_cannot_be_compared_says_so_and_keeps_going(
        self, fake_yfinance, monkeypatch, capsys
    ):
        import factor_sim.cli as cli

        def refuse(*args, **kwargs):
            raise ValueError("no overlapping dates")

        monkeypatch.setattr(cli, "benchmark_metrics", refuse)
        assert main_of()([*BASE, "--benchmark", "SPY"]) == 0
        assert "benchmark comparison unavailable" in capsys.readouterr().err

    def test_drawdowns_zero_omits_the_section_entirely(self, fake_yfinance, capsys):
        assert main_of()([*BASE, "--benchmark", "none", "--drawdowns", "0"]) == 0
        assert "Worst" not in capsys.readouterr().out


class TestOptionalSections:
    @pytest.fixture(autouse=True)
    def no_plots(self, monkeypatch):
        monkeypatch.setattr(
            "factor_sim.plotting.plot_nav", lambda *a, **k: None, raising=False
        )
        monkeypatch.setattr(
            "factor_sim.plotting.plot_drawdown", lambda *a, **k: None, raising=False
        )

    def test_attribution_is_printed_when_asked_for(self, fake_yfinance, monkeypatch, capsys):
        import factor_sim.attribution as attribution
        import factor_sim.data as data

        monkeypatch.setattr(
            data,
            "load_fama_french",
            lambda *a, **k: pd.DataFrame(
                {"Mkt-RF": 0.0001, "SMB": 0.0, "HML": 0.0, "RF": 0.0}, index=DATES
            ),
        )
        monkeypatch.setattr(
            attribution,
            "attribute",
            lambda *a, **k: types.SimpleNamespace(render=lambda: "alpha 0.00%"),
        )
        assert main_of()([*BASE, "--benchmark", "none", "--attribution"]) == 0
        assert "alpha 0.00%" in capsys.readouterr().out

    def test_attribution_failing_does_not_fail_the_run(
        self, fake_yfinance, monkeypatch, capsys
    ):
        # The Fama-French factors come from a third-party download. Losing them
        # should cost a section, not the whole backtest the user waited for.
        import factor_sim.data as data

        def unavailable(*a, **k):
            raise RuntimeError("Ken French's site is down")

        monkeypatch.setattr(data, "load_fama_french", unavailable)
        assert main_of()([*BASE, "--benchmark", "none", "--attribution"]) == 0
        assert "attribution unavailable" in capsys.readouterr().err

    def test_plot_draws_both_figures(self, fake_yfinance, monkeypatch, capsys):
        drawn: list[str] = []
        monkeypatch.setattr(
            "factor_sim.plotting.plot_nav", lambda *a, **k: drawn.append("nav")
        )
        monkeypatch.setattr(
            "factor_sim.plotting.plot_drawdown", lambda *a, **k: drawn.append("dd")
        )
        assert main_of()([*BASE, "--benchmark", "none", "--plot"]) == 0
        capsys.readouterr()
        assert drawn == ["nav", "dd"]


class TestPlots:
    """The figures themselves, rendered headless and inspected."""

    @staticmethod
    def nav() -> pd.DataFrame:
        values = np.concatenate([np.linspace(100, 140, 30), np.linspace(140, 110, 30)])
        return pd.DataFrame({"NAV": values}, index=DATES)

    def test_the_nav_plot_is_labelled_in_dollars(self):
        import matplotlib.pyplot as plt

        from factor_sim.plotting import plot_nav

        figure = plot_nav(self.nav(), show=False)
        assert "$" in figure.axes[0].get_ylabel()
        plt.close(figure)

    def test_the_drawdown_plot_is_never_positive(self):
        # Drawdown is plotted as a negative fill from the running peak. A
        # positive value would mean the peak logic is inverted.
        import matplotlib.pyplot as plt

        from factor_sim.plotting import plot_drawdown

        figure = plot_drawdown(self.nav(), show=False)
        paths = figure.axes[0].collections[0].get_paths()
        assert min(v[1] for p in paths for v in p.vertices) < 0
        assert max(v[1] for p in paths for v in p.vertices) <= 1e-12
        plt.close(figure)

    @pytest.mark.parametrize("name", ["plot_nav", "plot_drawdown"])
    def test_show_is_honoured(self, monkeypatch, name):
        import matplotlib.pyplot as plt

        import factor_sim.plotting as plotting

        shown: list[int] = []
        monkeypatch.setattr(plt, "show", lambda *a, **k: shown.append(1))
        plt.close(getattr(plotting, name)(self.nav(), show=True))
        assert shown == [1]


class TestPriceLookup:
    """`Security.price_on` — the one place a missing bar becomes a decision."""

    @staticmethod
    def security(values, index=None):
        from factor_sim.portfolio import Security

        return Security(ticker="AAA", prices=pd.Series(values, index=index or DATES[: len(values)]))

    def test_a_known_day_gives_its_price(self):
        assert self.security([10.0, 11.0]).price_on(DATES[1]) == 11.0

    def test_a_day_with_no_bar_is_none_rather_than_an_error(self):
        # A holiday or a pre-IPO date. Returning None lets the caller skip the
        # name; raising would abort a rebalance over one absent ticker.
        assert self.security([10.0, 11.0]).price_on(DATES[40]) is None

    def test_a_nan_price_is_treated_as_absent_not_as_zero(self):
        # The difference matters: NaN propagating into a weight makes the whole
        # portfolio NaN, and 0.0 would look like a total loss.
        assert self.security([10.0, float("nan")]).price_on(DATES[1]) is None
