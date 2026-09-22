"""The HTTP surface, against the real engine.

No mocking here, deliberately: the routes are thin, so a test that fakes the
engine underneath them checks only that FastAPI can serialise a dict. What is
worth asserting is that the numbers coming out of the API are the same numbers
the CLI and the browser port produce -- three surfaces over one engine is only
a virtue if they agree.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from curve_lab.pca import fit_factors
from curve_lab.service import create_app
from curve_lab.trades import dv01_neutral_weights, residual_risk


@pytest.fixture(scope="module")
def client(real_curve):
    with TestClient(create_app(real_curve)) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def real_curve():
    from curve_lab import load

    return load()


class TestHealth:
    def test_it_reports_what_is_loaded(self, client):
        body = client.get("/health").json()
        assert body["status"] == "ok"
        assert body["days"] == 11261
        assert body["first"] == "1981-09-01"
        assert len(body["tenors"]) == 9


class TestCurveRoutes:
    def test_the_summary_has_a_row_per_tenor_in_maturity_order(self, client):
        rows = client.get("/curve/summary").json()
        assert len(rows) == 9
        assert [r["maturity"] for r in rows] == sorted(r["maturity"] for r in rows)

    def test_a_spread_is_thinned_for_the_wire(self, client):
        body = client.get("/curve/spread", params={"short": "DGS2", "long": "DGS10"}).json()
        # 11,261 daily points is 300 KB of JSON to draw one line.
        assert len(body["spreadBp"]) <= 600
        assert len(body["dates"]) == len(body["spreadBp"])

    def test_an_unknown_tenor_is_refused(self, client):
        assert client.get("/curve/spread", params={"short": "DGS99"}).status_code == 422


class TestFactors:
    def test_it_matches_the_engine(self, client, real_curve):
        body = client.post("/factors", json={}).json()
        expected = fit_factors(real_curve)
        assert body["names"] == ["level", "slope", "curvature"]
        for i, value in enumerate(expected.explained):
            assert body["explained"][i] == pytest.approx(value, abs=1e-6)

    def test_a_window_refits_rather_than_slicing_the_answer(self, client):
        everything = client.post("/factors", json={}).json()
        recent = client.post("/factors", json={"start": "2010-01-01"}).json()
        assert recent["days"] < everything["days"]
        assert recent["explained"] != everything["explained"]

    def test_a_window_too_short_for_a_covariance_is_refused(self, client):
        response = client.post("/factors", json={"start": "2026-09-01"})
        assert response.status_code == 422
        assert "too few" in response.json()["detail"]


class TestTrade:
    def test_it_reproduces_the_headline(self, client):
        body = client.post("/trade", json={"wings": ["DGS2", "DGS10"], "belly": "DGS5"}).json()
        assert body["varianceShare"][2] < 0.02
        assert body["unintendedShare"] > 0.95
        assert body["netDv01"] == pytest.approx(0.0, abs=1e-9)

    def test_it_matches_the_engine_exactly(self, client, real_curve):
        body = client.post("/trade", json={"wings": ["DGS1", "DGS5"], "belly": "DGS2"}).json()
        factors = fit_factors(real_curve)
        fly = dv01_neutral_weights(factors.tenors, ("DGS1", "DGS5"), "DGS2")
        expected = residual_risk(
            fly, factors, factors.scores(real_curve.changes).var().to_numpy()
        )
        for i, share in enumerate(expected.variance_share):
            assert body["varianceShare"][i] == pytest.approx(share, abs=1e-6)

    def test_factor_weighting_zeroes_the_first_two_exposures(self, client):
        body = client.post("/trade", json={"weighting": "factor"}).json()
        assert body["exposure"][0] == pytest.approx(0.0, abs=1e-6)
        assert body["exposure"][1] == pytest.approx(0.0, abs=1e-6)

    def test_a_belly_outside_its_wings_is_refused(self, client):
        response = client.post(
            "/trade", json={"wings": ["DGS10", "DGS30"], "belly": "DGS2"}
        )
        assert response.status_code == 422

    def test_an_unknown_tenor_is_refused_by_the_schema(self, client):
        assert client.post("/trade", json={"belly": "DGS99"}).status_code == 422

    def test_an_unexpected_field_is_refused(self, client):
        # `extra="forbid"`: a typo'd field should fail loudly rather than
        # silently running with the default it was meant to override.
        assert client.post("/trade", json={"bely": "DGS5"}).status_code == 422


class TestBacktest:
    def test_it_matches_the_documented_numbers(self, client):
        body = client.post(
            "/backtest", json={"start": "2000-01-01", "weighting": "factor"}
        ).json()
        assert body["total"] == pytest.approx(143.11, abs=0.05)
        assert body["informationRatio"] == pytest.approx(0.24, abs=0.005)
        assert body["lookAhead"] is False

    def test_look_ahead_flips_the_sign(self, client):
        honest = client.post(
            "/backtest", json={"start": "2000-01-01", "weighting": "factor"}
        ).json()
        leaky = client.post(
            "/backtest",
            json={"start": "2000-01-01", "weighting": "factor", "look_ahead": True},
        ).json()
        assert honest["total"] > 0 > leaky["total"]
        assert leaky["lookAhead"] is True

    def test_the_contribution_adds_up_to_the_total(self, client):
        body = client.post("/backtest", json={"start": "2010-01-01"}).json()
        assert sum(body["contribution"].values()) == pytest.approx(body["total"], abs=0.01)

    def test_the_equity_curve_is_thinned_but_aligned(self, client):
        body = client.post("/backtest", json={"start": "2000-01-01"}).json()
        assert len(body["equity"]) <= 600
        assert len(body["dates"]) == len(body["equity"])

    def test_costs_out_of_range_are_refused(self, client):
        assert client.post("/backtest", json={"cost_bp": 90}).status_code == 422
        assert client.post("/backtest", json={"rebalance_days": 0}).status_code == 422


class TestCarryAndCycles:
    def test_carry_covers_every_tenor_past_the_bill(self, client):
        rows = client.post("/carry", json={"start": "2015-01-01"}).json()
        assert {r["tenor"] for r in rows} == {
            "DGS6MO", "DGS1", "DGS2", "DGS3", "DGS5", "DGS7", "DGS10", "DGS30",
        }
        assert all(r["total_bp"] == pytest.approx(r["carry_bp"] + r["rolldown_bp"], abs=0.01)
                   for r in rows)

    def test_cycles_reports_a_verdict_per_factor(self, client):
        rows = client.post("/cycles", json={"start": "2000-01-01"}).json()
        assert [r["factor"] for r in rows] == ["level", "slope", "curvature"]
        assert all("threshold" in r["verdict"] for r in rows)


class TestStrategyParsing:
    def test_it_returns_the_same_validated_object_the_cli_uses(self, client):
        body = client.post(
            "/strategy/parse",
            json={"text": "factor-neutral 1s2s5s since 2010, weekly, 1bp"},
        ).json()
        assert body["wings"] == ["DGS1", "DGS5"]
        assert body["belly"] == "DGS2"
        assert body["weighting"] == "factor"
        assert body["rebalanceDays"] == 5
        assert body["costBp"] == 1.0
        assert body["start"] == "2010-01-01"

    def test_an_unreadable_request_is_a_422_with_the_reason(self, client):
        response = client.post("/strategy/parse", json={"text": "2s10s fly"})
        assert response.status_code == 422
        assert "two-leg spread" in response.json()["detail"]

    def test_an_empty_request_is_refused_by_the_schema(self, client):
        assert client.post("/strategy/parse", json={"text": ""}).status_code == 422


class TestForecast:
    def test_it_does_not_beat_a_random_walk(self, client):
        body = client.post(
            "/forecast", json={"start": "2000-01-01", "factor": "curvature", "folds": 2}
        ).json()
        assert body["beatsBaseline"] is False
        assert body["r2VsBaseline"] < 0
        assert body["nFeatures"] > 50
        assert len(body["scatter"]) <= 400

    def test_the_horizon_is_bounded(self, client):
        assert client.post("/forecast", json={"horizon_days": 0}).status_code == 422
        assert client.post("/forecast", json={"folds": 99}).status_code == 422
