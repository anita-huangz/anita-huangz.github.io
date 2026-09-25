"""Parsing and the arithmetic over public data, against mocked HTTP."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, date, datetime

import httpx
import pytest

from filing_intel.config import Settings
from filing_intel.contracts import FilingSection
from filing_intel.data import EdgarClient, PriceClient, extract_section, html_to_text
from filing_intel.data.edgar import _RateLimiter
from filing_intel.data.prices import _baseline_index
from filing_intel.errors import UpstreamDataError


@pytest.fixture
def settings() -> Settings:
    return Settings(sec_user_agent="filing-intel-tests/0.1 (tests@example.com)")


# --------------------------------------------------------------------------- #
# HTML -> text
# --------------------------------------------------------------------------- #


def test_tags_stripped_and_entities_decoded():
    assert "Risk & Reward" in html_to_text("<p>Risk &amp; Reward</p>")


def test_script_and_style_content_is_dropped():
    text = html_to_text("<style>p{color:red}</style><script>x=1</script><p>Real</p>")
    assert "color" not in text and "x=1" not in text
    assert "Real" in text


def test_block_tags_become_line_breaks():
    """Item headings must land on their own line or the section regex misses."""
    text = html_to_text("<div>Item 1A.</div><div>Risk Factors</div>")
    assert "Item 1A." in text


def test_non_breaking_spaces_are_normalized():
    assert "Item 1A" in html_to_text("<p>Item&nbsp;1A</p>")


# --------------------------------------------------------------------------- #
# Section extraction
# --------------------------------------------------------------------------- #

FILING_TEXT = """
TABLE OF CONTENTS
Item 1. Business ......... 3
Item 1A. Risk Factors .... 9
Item 7. Management's Discussion and Analysis .... 30

Item 1. Business
We design and sell consumer electronics.

Item 1A. Risk Factors
Our supply chain is concentrated in a small number of partners.
A disruption would materially harm results.

Item 1B. Unresolved Staff Comments
None.

Item 7. Management's Discussion and Analysis of Financial Condition
Revenue decreased 3% year over year.

Item 7A. Quantitative Disclosures
Not applicable.
"""


def test_risk_factors_extracted_past_the_table_of_contents():
    body = extract_section(FILING_TEXT, FilingSection.RISK_FACTORS)
    assert "supply chain is concentrated" in body
    # It must stop at the next Item, not swallow the rest of the filing.
    assert "Unresolved Staff Comments" not in body
    assert "Revenue decreased" not in body


def test_mda_extracted_and_bounded():
    body = extract_section(FILING_TEXT, FilingSection.MDA)
    assert "Revenue decreased 3%" in body
    assert "Not applicable" not in body


def test_missing_section_returns_empty_string():
    assert extract_section("no items here", FilingSection.RISK_FACTORS) == ""


# --------------------------------------------------------------------------- #
# EDGAR client
# --------------------------------------------------------------------------- #

TICKERS_PAYLOAD = {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}

SUBMISSIONS_PAYLOAD = {
    "filings": {
        "recent": {
            "form": ["10-K", "8-K", "10-K"],
            "accessionNumber": [
                "0000320193-23-000106", "0000320193-23-000090", "0000320193-22-000108"
            ],
            "filingDate": ["2023-11-03", "2023-08-04", "2022-10-28"],
            "reportDate": ["2023-09-30", "", "2022-09-24"],
            "primaryDocument": ["aapl-20230930.htm", "a8k.htm", "aapl-20220924.htm"],
        }
    }
}

CONCEPT_PAYLOAD = {
    "units": {
        "USD": [
            {"val": 383285000000, "end": "2023-09-30", "fy": 2023, "fp": "FY", "form": "10-K"},
            {"val": 394328000000, "end": "2022-09-24", "fy": 2022, "fp": "FY", "form": "10-K"},
        ]
    }
}


def edgar_with(handler) -> EdgarClient:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return EdgarClient(Settings(sec_user_agent="t/0.1 (t@e.com)"), client=client)


def default_handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if "company_tickers" in url:
        return httpx.Response(200, json=TICKERS_PAYLOAD)
    if "submissions" in url:
        return httpx.Response(200, json=SUBMISSIONS_PAYLOAD)
    if "companyconcept" in url:
        return httpx.Response(200, json=CONCEPT_PAYLOAD)
    return httpx.Response(404)


async def test_cik_is_zero_padded_to_ten_digits():
    edgar = edgar_with(default_handler)
    assert await edgar.cik_for("aapl") == "0000320193"


async def test_unknown_ticker_raises_upstream_error():
    edgar = edgar_with(default_handler)
    with pytest.raises(UpstreamDataError, match="no SEC registrant"):
        await edgar.cik_for("ZZZZ")


async def test_ticker_map_is_fetched_once_and_reused():
    hits = {"n": 0}

    def handler(request):
        if "company_tickers" in str(request.url):
            hits["n"] += 1
        return default_handler(request)

    edgar = edgar_with(handler)
    await edgar.cik_for("AAPL")
    await edgar.cik_for("AAPL")
    assert hits["n"] == 1


async def test_search_filters_by_form_type_and_respects_limit():
    edgar = edgar_with(default_handler)
    filings = await edgar.search_filings("AAPL", form_type="10-K", limit=5)
    assert len(filings) == 2
    assert all(f.form_type == "10-K" for f in filings)
    assert filings[0].filed_at == date(2023, 11, 3)

    assert len(await edgar.search_filings("AAPL", "10-K", limit=1)) == 1


async def test_blank_report_date_becomes_none():
    edgar = edgar_with(default_handler)
    eight_ks = await edgar.search_filings("AAPL", form_type="8-K")
    assert eight_ks[0].period_of_report is None


async def test_company_facts_sorted_newest_first_and_truncated():
    edgar = edgar_with(default_handler)
    facts = await edgar.company_facts("AAPL", "Revenues", periods=1)
    assert len(facts) == 1
    assert facts[0].period_end == date(2023, 9, 30)
    assert facts[0].unit == "USD"


async def test_403_explains_the_user_agent_requirement():
    edgar = edgar_with(lambda r: httpx.Response(403))
    with pytest.raises(UpstreamDataError, match="contact email"):
        await edgar.cik_for("AAPL")


async def test_missing_xbrl_concept_is_an_upstream_error():
    def handler(request):
        if "companyconcept" in str(request.url):
            return httpx.Response(200, json={"units": {}})
        return default_handler(request)

    with pytest.raises(UpstreamDataError, match="no XBRL data"):
        await edgar_with(handler).company_facts("AAPL", "NotAConcept")


def test_settings_reject_a_user_agent_without_contact_info():
    with pytest.raises(ValueError, match="contact email"):
        Settings(sec_user_agent="my-crawler")


# --------------------------------------------------------------------------- #
# Prices
# --------------------------------------------------------------------------- #


def test_baseline_index_picks_the_last_session_on_or_before_the_event():
    series = [(date(2023, 11, 1), 1.0), (date(2023, 11, 3), 2.0), (date(2023, 11, 6), 3.0)]
    assert _baseline_index(series, date(2023, 11, 3)) == 1
    # A Saturday event date falls back to Friday's close.
    assert _baseline_index(series, date(2023, 11, 4)) == 1
    assert _baseline_index(series, date(2023, 10, 1)) is None


def chart_payload(closes: list[float], start: date) -> dict:
    stamps, values, day = [], [], start
    for close in closes:
        stamps.append(
            int(datetime.combine(day, datetime.min.time(), UTC).timestamp())
        )
        values.append(close)
        day = date.fromordinal(day.toordinal() + 1)
    return {
        "chart": {
            "result": [
                {"timestamp": stamps, "indicators": {"quote": [{"close": values}]}}
            ],
            "error": None,
        }
    }


def price_client_with(payload: dict) -> PriceClient:
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json=payload))
    return PriceClient(
        Settings(sec_user_agent="t/0.1 (t@e.com)"),
        client=httpx.AsyncClient(transport=transport),
    )


async def test_event_reaction_computes_returns_off_the_baseline_close():
    payload = chart_payload([100.0, 110.0, 121.0, 90.0], date(2023, 11, 1))
    reaction = await price_client_with(payload).event_reaction(
        "AAPL", date(2023, 11, 1), [1, 2]
    )
    assert reaction.baseline_close == 100.0
    assert reaction.windows["1d"] == pytest.approx(0.10)
    assert reaction.windows["2d"] == pytest.approx(0.21)


async def test_horizon_beyond_available_history_is_omitted_not_guessed():
    payload = chart_payload([100.0, 110.0], date(2023, 11, 1))
    reaction = await price_client_with(payload).event_reaction(
        "AAPL", date(2023, 11, 1), [1, 30]
    )
    assert "1d" in reaction.windows
    assert "30d" not in reaction.windows


async def test_null_closes_are_skipped():
    payload = chart_payload([100.0, 110.0], date(2023, 11, 1))
    payload["chart"]["result"][0]["indicators"]["quote"][0]["close"] = [100.0, None]
    series = await price_client_with(payload).daily_closes(
        "AAPL", date(2023, 11, 1), date(2023, 11, 5)
    )
    assert len(series) == 1


async def test_empty_result_is_an_upstream_error():
    payload = {"chart": {"result": [], "error": "Not Found"}}
    with pytest.raises(UpstreamDataError, match="no price data"):
        await price_client_with(payload).daily_closes(
            "ZZZZ", date(2023, 11, 1), date(2023, 11, 5)
        )


# --------------------------------------------------------------------------- #
# XBRL period spans
# --------------------------------------------------------------------------- #

OVERLAPPING_CONCEPT = {
    "units": {
        "USD": [
            # Same end date, two different spans: Q3 alone and the year to date.
            {"val": 30_000, "start": "2024-04-01", "end": "2024-06-30", "form": "10-Q"},
            {"val": 90_000, "start": "2024-01-01", "end": "2024-06-30", "form": "10-Q"},
            # A restatement of an identical span in a later filing.
            {"val": 90_000, "start": "2024-01-01", "end": "2024-06-30", "form": "10-K"},
            {"val": 120_000, "start": "2023-01-01", "end": "2023-12-31", "form": "10-K"},
        ]
    }
}


def edgar_with_concept(payload):
    def handler(request):
        if "companyconcept" in str(request.url):
            return httpx.Response(200, json=payload)
        return default_handler(request)

    return edgar_with(handler)


async def test_period_start_is_captured():
    facts = await edgar_with_concept(OVERLAPPING_CONCEPT).company_facts("AAPL")
    assert facts[0].period_start is not None


async def test_identical_spans_are_deduplicated():
    """A restated period must not consume several of the requested slots."""
    facts = await edgar_with_concept(OVERLAPPING_CONCEPT).company_facts("AAPL", periods=4)
    spans = [(f.period_start, f.period_end) for f in facts]
    assert len(spans) == len(set(spans))


async def test_overlapping_quarter_and_ytd_are_both_kept_and_distinguishable():
    """They are genuinely different facts; the span is what tells them apart."""
    facts = await edgar_with_concept(OVERLAPPING_CONCEPT).company_facts("AAPL", periods=4)
    same_end = [f for f in facts if f.period_end == date(2024, 6, 30)]
    assert len(same_end) == 2
    assert {f.period_label for f in same_end} == {"quarter", "H1/H2"}


def test_period_label_names_the_span():
    from filing_intel.contracts import FinancialFact

    def fact(start, end):
        return FinancialFact(
            concept="Revenues", unit="USD", value=1.0,
            period_start=start, period_end=end,
        )

    assert fact(date(2023, 1, 1), date(2023, 12, 31)).period_label == "FY"
    assert fact(date(2024, 4, 1), date(2024, 6, 30)).period_label == "quarter"
    assert fact(None, date(2024, 6, 30)).period_label == "as of"


def test_duration_days_is_none_for_an_instant_fact():
    from filing_intel.contracts import FinancialFact

    assert FinancialFact(
        concept="Assets", unit="USD", value=1.0, period_end=date(2024, 6, 30)
    ).duration_days is None


# --------------------------------------------------------------------------- #
# Fetching a section end to end
# --------------------------------------------------------------------------- #

ACCESSION = "0000320193-23-000106"

# Two HTML files in the accession. The larger one is the filing; the other is
# the cover letter that EDGAR stores alongside it.
INDEX_JSON = {
    "directory": {
        "item": [
            {"name": "aapl-20230930-index.htm", "size": "900000"},
            {"name": "R2.htm", "size": "800000"},
            {"name": "exhibit.txt", "size": "700000"},
            {"name": "aapl-20230930.htm", "size": "120000"},
            {"name": "cover.htm", "size": "4000"},
        ]
    }
}

FILING_HTML = (
    "<div>Item 1A. Risk Factors</div>"
    "<p>Our supply chain is concentrated in a small number of partners.</p>"
    "<div>Item 1B. Unresolved Staff Comments</div><p>None.</p>"
)


def archive_handler(
    index_json=INDEX_JSON, doc_html=FILING_HTML, seen: list[str] | None = None
):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if seen is not None:
            seen.append(url)
        if "company_tickers" in url:
            return httpx.Response(200, json=TICKERS_PAYLOAD)
        if url.endswith("/index.json"):
            return httpx.Response(200, json=index_json)
        if url.endswith(".htm"):
            return httpx.Response(200, text=doc_html)
        return httpx.Response(404)

    return handler


async def test_the_primary_document_is_the_largest_real_html_file():
    # Exhibits, the index page itself, and EDGAR's generated R*.htm viewer
    # files are all larger here. Picking the largest without excluding them
    # would index the viewer markup instead of the filing.
    seen: list[str] = []
    edgar = edgar_with(archive_handler(seen=seen))
    await edgar.fetch_section("AAPL", ACCESSION, FilingSection.RISK_FACTORS)
    assert any(u.endswith("/aapl-20230930.htm") for u in seen)
    assert not any(u.endswith("/R2.htm") or u.endswith("-index.htm") for u in seen)


async def test_the_accession_dashes_are_stripped_from_the_archive_path():
    seen: list[str] = []
    edgar = edgar_with(archive_handler(seen=seen))
    await edgar.fetch_section("AAPL", ACCESSION, FilingSection.RISK_FACTORS)
    # The CIK is unpadded in Archives paths, unlike the submissions endpoint.
    assert any("/Archives/edgar/data/320193/000032019323000106/" in u for u in seen)


async def test_a_fetched_section_reports_its_true_length_when_truncated():
    edgar = edgar_with(archive_handler())
    section = await edgar.fetch_section(
        "AAPL", ACCESSION, FilingSection.RISK_FACTORS, max_chars=20
    )
    assert section.truncated is True
    assert len(section.text) == 20
    assert section.char_count > 20


async def test_an_untruncated_section_says_so():
    edgar = edgar_with(archive_handler())
    section = await edgar.fetch_section("AAPL", ACCESSION, FilingSection.RISK_FACTORS)
    assert section.truncated is False
    assert "supply chain" in section.text
    assert section.accession == ACCESSION


async def test_a_section_the_filing_does_not_contain_is_an_upstream_error():
    edgar = edgar_with(archive_handler(doc_html="<p>Nothing item-shaped here.</p>"))
    with pytest.raises(UpstreamDataError, match="risk_factors"):
        await edgar.fetch_section("AAPL", ACCESSION, FilingSection.RISK_FACTORS)


async def test_an_accession_with_no_html_document_is_an_upstream_error():
    empty = {"directory": {"item": [{"name": "exhibit.txt", "size": "10"}]}}
    edgar = edgar_with(archive_handler(index_json=empty))
    with pytest.raises(UpstreamDataError, match="no primary document"):
        await edgar.fetch_section("AAPL", ACCESSION, FilingSection.RISK_FACTORS)


# --------------------------------------------------------------------------- #
# HTTP failure modes
# --------------------------------------------------------------------------- #


async def test_a_transport_error_is_reported_as_an_upstream_error_not_a_raw_httpx_one():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("name resolution failed")

    with pytest.raises(UpstreamDataError, match="EDGAR request failed"):
        await edgar_with(handler).cik_for("AAPL")


async def test_a_404_names_the_url_that_was_missing():
    edgar = edgar_with(lambda r: httpx.Response(404))
    with pytest.raises(UpstreamDataError, match="no resource at"):
        await edgar.cik_for("AAPL")


async def test_a_500_is_surfaced_with_its_status_code():
    edgar = edgar_with(lambda r: httpx.Response(503))
    with pytest.raises(UpstreamDataError, match="503"):
        await edgar.cik_for("AAPL")


async def test_a_registrant_with_no_filing_history_returns_no_filings():
    def handler(request: httpx.Request) -> httpx.Response:
        if "company_tickers" in str(request.url):
            return httpx.Response(200, json=TICKERS_PAYLOAD)
        return httpx.Response(200, json={"filings": {"recent": {}}})

    assert await edgar_with(handler).search_filings("AAPL") == []


async def test_the_client_can_be_used_as_an_async_context_manager():
    async with edgar_with(default_handler) as edgar:
        assert await edgar.cik_for("AAPL") == "0000320193"


async def test_closing_leaves_a_caller_supplied_client_alone():
    # The caller owns the client it passed in; closing it here would break the
    # next EdgarClient built over the same shared connection pool.
    client = httpx.AsyncClient(transport=httpx.MockTransport(default_handler))
    edgar = EdgarClient(Settings(sec_user_agent="t/0.1 (t@e.com)"), client=client)
    await edgar.aclose()
    assert not client.is_closed
    await client.aclose()


async def test_a_client_the_edgar_client_created_itself_is_closed():
    edgar = EdgarClient(Settings(sec_user_agent="t/0.1 (t@e.com)"))
    await edgar.aclose()
    assert edgar._client.is_closed


# --------------------------------------------------------------------------- #
# Rate limiting
# --------------------------------------------------------------------------- #


async def test_requests_are_spaced_so_edgar_is_not_hammered():
    limiter = _RateLimiter(min_interval=0.05)
    start = time.monotonic()
    for _ in range(3):
        await limiter.wait()
    # Three waits, two of them gated: the first is free.
    assert time.monotonic() - start >= 0.09


async def test_a_slow_caller_is_never_made_to_wait():
    limiter = _RateLimiter(min_interval=0.05)
    await limiter.wait()
    await asyncio.sleep(0.06)
    start = time.monotonic()
    await limiter.wait()
    assert time.monotonic() - start < 0.02


class TestSectionBoundariesOnRealFilings:
    """The Item-1A extractor, against three real 10-Ks.

    These are committed as a fixture because the failure this guards against
    is invisible on a synthetic filing: it needs a document that cross-
    references its own Items in prose, which every large filer does and no
    hand-written test case does.
    """

    @staticmethod
    def sections() -> dict:
        import json
        from pathlib import Path

        path = Path(__file__).parent / "fixtures" / "sections" / "risk_factors.json"
        return json.loads(path.read_text())

    def test_every_section_starts_at_the_real_heading(self):
        for ticker, filing in self.sections().items():
            assert filing["text"].lower().startswith("item 1a"), ticker

    def test_a_cross_reference_is_not_mistaken_for_the_heading(self):
        # NVIDIA's 10-K says "see Item 1A. Risk factors in this annual report"
        # five times, mid sentence. Taking the last match landed on one of
        # them, found no closing boundary, and returned 123,360 characters of
        # financial-statement notes labelled as risk factors.
        nvda = self.sections()["NVDA"]["text"]
        assert 100_000 < len(nvda) < 120_000
        assert "Employee Stock Purchase Plan" not in nvda
        assert "marketable securities consist of highly liquid" not in nvda.lower()

    def test_the_sections_are_risk_prose_throughout(self):
        for ticker, filing in self.sections().items():
            text = filing["text"]
            for fraction in (0.25, 0.5, 0.75):
                window = text[int(len(text) * fraction) : int(len(text) * fraction) + 4000].lower()
                assert any(
                    word in window for word in ("risk", "adverse", "could", "may", "harm")
                ), f"{ticker} at {fraction:.0%} does not read like risk disclosure"


class TestSectionExtractionRules:
    def test_a_table_of_contents_entry_is_skipped_for_the_body(self):
        text = (
            "Item 1A. Risk Factors 9\n"
            "Item 1B. Unresolved Staff Comments 12\n"
            "Item 1A. Risk Factors\n"
            + ("Our operations face substantial risk. " * 40)
            + "\nItem 1B. Unresolved Staff Comments\nNone.\n"
        )
        body = extract_section(text, FilingSection.RISK_FACTORS)
        assert "Our operations face substantial risk." in body
        assert len(body) > 200

    def test_a_mid_sentence_cross_reference_loses_to_a_real_heading(self):
        text = (
            "Item 1A. Risk Factors\n"
            + ("The Company faces competition and regulatory exposure. " * 30)
            + "\nItem 1B. Unresolved Staff Comments\nNone.\n"
            "Item 2. Properties\nOffices.\n"
            "Note 12. See Item 1A. Risk Factors for further discussion of these matters.\n"
        )
        body = extract_section(text, FilingSection.RISK_FACTORS)
        assert body.startswith("Item 1A. Risk Factors")
        assert "The Company faces competition" in body
        assert "Note 12" not in body

    def test_a_section_with_no_closing_boundary_still_returns_something(self):
        text = "Item 1A. Risk Factors\n" + ("Risk disclosure text. " * 30)
        assert len(extract_section(text, FilingSection.RISK_FACTORS)) > 200

    def test_a_missing_section_is_empty(self):
        assert extract_section("Item 7. MD&A\nNothing here.", FilingSection.RISK_FACTORS) == ""
