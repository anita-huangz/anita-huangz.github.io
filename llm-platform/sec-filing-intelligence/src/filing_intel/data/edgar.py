"""SEC EDGAR client.

Uses only public, unauthenticated EDGAR endpoints. EDGAR requires a descriptive
User-Agent containing contact information and asks callers to stay under 10
requests/second; both are enforced here rather than left to the caller.
"""

from __future__ import annotations

import asyncio
import re
import time
from datetime import date, datetime
from html.parser import HTMLParser
from typing import ClassVar

import httpx

from ..config import Settings
from ..contracts import Filing, FilingSection, FinancialFact, SectionText
from ..errors import UpstreamDataError

COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"

#: Item headings that delimit each section in a 10-K / 10-Q. Matching is done on
#: tag-stripped text, so these must tolerate the whitespace EDGAR filings carry.
#: The en and em dashes below are deliberate -- filers use them interchangeably
#: with a hyphen after the item number.
# ruff: noqa: RUF001
SECTION_BOUNDS: dict[FilingSection, tuple[str, str]] = {
    FilingSection.BUSINESS: (r"item\s*1\s*[\.\:\-–—]?\s*business", r"item\s*1a\s*[\.\:\-–—]?"),
    FilingSection.RISK_FACTORS: (
        r"item\s*1a\s*[\.\:\-–—]?\s*risk\s*factors",
        r"item\s*1b\s*[\.\:\-–—]?|item\s*2\s*[\.\:\-–—]?\s*propert",
    ),
    FilingSection.MDA: (
        r"item\s*7\s*[\.\:\-–—]?\s*management.{0,5}s\s*discussion",
        r"item\s*7a\s*[\.\:\-–—]?|item\s*8\s*[\.\:\-–—]?\s*financial\s*statements",
    ),
    FilingSection.FINANCIAL_STATEMENTS: (
        r"item\s*8\s*[\.\:\-–—]?\s*financial\s*statements",
        r"item\s*9\s*[\.\:\-–—]?",
    ),
}


class _TextExtractor(HTMLParser):
    """Strips tags, keeping block-level breaks so Item headings stay on their own line."""

    _BLOCK: ClassVar[set[str]] = {
        "p", "div", "br", "tr", "table", "h1", "h2", "h3", "h4", "li"
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self._skip += 1
        elif tag in self._BLOCK:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._skip:
            self._skip -= 1
        elif tag in self._BLOCK:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self._parts.append(data)

    def text(self) -> str:
        raw = "".join(self._parts)
        raw = raw.replace("\xa0", " ")
        raw = re.sub(r"[ \t]+", " ", raw)
        return re.sub(r"\n\s*\n+", "\n\n", raw).strip()


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    return parser.text()


#: A section body has to be longer than this to be believable. Table-of-contents
#: entries match the same heading pattern and yield about thirty characters.
MIN_SECTION_CHARS = 200


def extract_section(text: str, section: FilingSection) -> str:
    """Slice a filing's plain text down to one Item.

    Three things make this harder than "find the heading".

    **The table of contents repeats every heading.** Its entry matches the
    start pattern and yields a couple of dozen characters before the next Item
    heading, which is why a candidate has to clear `MIN_SECTION_CHARS`.

    **Filings cross-reference their own Items in prose.** NVIDIA's 10-K says
    "see Item 1A. Risk factors in this annual report" five separate times, mid
    sentence. Taking the *last* match -- which this used to do -- landed on one
    of those, found no closing boundary after it, and returned 123,000
    characters of financial-statement notes labelled as risk factors. A heading
    sits at the start of a line and a cross-reference does not, so line-start
    matches are preferred when any exist.

    **A candidate with no closing boundary is usually the wrong candidate.**
    Real sections are followed by the next Item; a match that runs to the end
    of the document has almost always landed somewhere it should not have.
    """
    start_pat, end_pat = SECTION_BOUNDS[section]
    starts = list(re.finditer(start_pat, text, re.IGNORECASE))
    if not starts:
        return ""

    headings = [m for m in starts if m.start() == 0 or text[m.start() - 1] == "\n"]
    candidates = headings or starts

    fallback: str | None = None
    # Latest first: the body comes after the contents page.
    for match in reversed(candidates):
        tail = text[match.start() :]
        # Search for the closing boundary *after* the start heading itself, so a
        # pattern like "item 1a" cannot immediately re-match its own heading.
        # Using the heading's own length rather than a fixed offset matters: a
        # short section would otherwise run past its boundary into the next Item.
        offset = match.end() - match.start()
        end_match = re.search(end_pat, tail[offset:], re.IGNORECASE)
        if end_match is None:
            if fallback is None:
                fallback = tail.strip()
            continue
        body = tail[: offset + end_match.start()].strip()
        if len(body) >= MIN_SECTION_CHARS:
            return body
        if fallback is None:
            fallback = body

    return fallback or ""


class _RateLimiter:
    """Simple async spacing gate. EDGAR asks for <= 10 req/s."""

    def __init__(self, min_interval: float = 0.12) -> None:
        self._min_interval = min_interval
        self._last = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            delta = time.monotonic() - self._last
            if delta < self._min_interval:
                await asyncio.sleep(self._min_interval - delta)
            self._last = time.monotonic()


class EdgarClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=settings.http_timeout_seconds,
            headers={
                "User-Agent": settings.sec_user_agent,
                "Accept-Encoding": "gzip, deflate",
            },
            follow_redirects=True,
        )
        self._limiter = _RateLimiter()
        self._ticker_map: dict[str, str] | None = None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> EdgarClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def _get(self, url: str) -> httpx.Response:
        await self._limiter.wait()
        try:
            response = await self._client.get(url)
        except httpx.HTTPError as exc:
            raise UpstreamDataError(f"EDGAR request failed: {url}: {exc}") from exc
        if response.status_code == 403:
            raise UpstreamDataError(
                "EDGAR returned 403 -- the User-Agent must name a real contact email"
            )
        if response.status_code == 404:
            raise UpstreamDataError(f"EDGAR has no resource at {url}")
        if response.status_code >= 400:
            raise UpstreamDataError(f"EDGAR returned {response.status_code} for {url}")
        return response

    async def cik_for(self, ticker: str) -> str:
        """Resolve a ticker to a zero-padded 10-digit CIK."""
        if self._ticker_map is None:
            payload = (await self._get(COMPANY_TICKERS_URL)).json()
            self._ticker_map = {
                str(row["ticker"]).upper(): f"{int(row['cik_str']):010d}"
                for row in payload.values()
            }
        cik = self._ticker_map.get(ticker.upper())
        if cik is None:
            raise UpstreamDataError(f"no SEC registrant found for ticker {ticker!r}")
        return cik

    async def search_filings(
        self, ticker: str, form_type: str = "10-K", limit: int = 5
    ) -> list[Filing]:
        cik = await self.cik_for(ticker)
        url = f"{self._settings.sec_base_url}/submissions/CIK{cik}.json"
        payload = (await self._get(url)).json()
        recent = payload.get("filings", {}).get("recent", {})
        if not recent:
            return []

        forms = recent.get("form", [])
        results: list[Filing] = []
        for i, form in enumerate(forms):
            if form != form_type:
                continue
            results.append(
                Filing(
                    accession=recent["accessionNumber"][i],
                    ticker=ticker.upper(),
                    cik=cik,
                    form_type=form,
                    filed_at=_parse_date(recent["filingDate"][i]),
                    period_of_report=_parse_optional_date(
                        recent.get("reportDate", [None] * len(forms))[i]
                    ),
                    primary_document=recent.get("primaryDocument", [None] * len(forms))[i],
                )
            )
            if len(results) >= limit:
                break
        return results

    async def fetch_section(
        self,
        ticker: str,
        accession: str,
        section: FilingSection,
        max_chars: int = 20_000,
    ) -> SectionText:
        cik = (await self.cik_for(ticker)).lstrip("0")
        bare = accession.replace("-", "")
        index_url = (
            f"{self._settings.sec_www_url}/Archives/edgar/data/{cik}/{bare}/"
            f"{accession}-index.html"
        )
        primary = await self._primary_document(cik, bare, index_url)
        doc_url = f"{self._settings.sec_www_url}/Archives/edgar/data/{cik}/{bare}/{primary}"

        html = (await self._get(doc_url)).text
        body = extract_section(html_to_text(html), section)
        if not body:
            raise UpstreamDataError(
                f"could not locate section {section.value!r} in {accession}"
            )
        truncated = len(body) > max_chars
        return SectionText(
            accession=accession,
            section=section,
            text=body[:max_chars],
            char_count=len(body),
            truncated=truncated,
        )

    async def _primary_document(self, cik: str, bare: str, index_url: str) -> str:
        """Find the main filing document from the accession's file index."""
        json_url = f"{self._settings.sec_www_url}/Archives/edgar/data/{cik}/{bare}/index.json"
        payload = (await self._get(json_url)).json()
        items = payload.get("directory", {}).get("item", [])
        candidates = [
            i["name"]
            for i in items
            if i.get("name", "").endswith((".htm", ".html"))
            and "index" not in i.get("name", "")
            and not i.get("name", "").startswith("R")
        ]
        if not candidates:
            raise UpstreamDataError(f"no primary document found at {index_url}")
        # The main document is reliably the largest HTML file in the accession.
        sizes = {i["name"]: int(i.get("size", 0) or 0) for i in items}
        return max(candidates, key=lambda n: sizes.get(n, 0))

    async def company_facts(
        self, ticker: str, concept: str = "Revenues", periods: int = 8
    ) -> list[FinancialFact]:
        cik = await self.cik_for(ticker)
        url = (
            f"{self._settings.sec_base_url}/api/xbrl/companyconcept/"
            f"CIK{cik}/us-gaap/{concept}.json"
        )
        payload = (await self._get(url)).json()
        units: dict = payload.get("units", {})
        if not units:
            raise UpstreamDataError(f"no XBRL data for {ticker} concept {concept!r}")

        unit_name, entries = next(iter(units.items()))
        facts = [
            FinancialFact(
                concept=concept,
                unit=unit_name,
                value=float(e["val"]),
                period_end=_parse_date(e["end"]),
                period_start=_parse_optional_date(e.get("start")),
                fiscal_year=e.get("fy"),
                fiscal_period=e.get("fp"),
                form_type=e.get("form"),
            )
            for e in entries
            if e.get("val") is not None and e.get("end")
        ]

        # EDGAR restates the same period across later filings, so an identical
        # (span, value) shows up several times. Deduplicate on the span, keeping
        # the first occurrence, before truncating -- otherwise `periods=4` can
        # return one period four times.
        seen: set[tuple[date, date | None]] = set()
        unique: list[FinancialFact] = []
        for fact in sorted(facts, key=lambda f: (f.period_end, f.duration_days or 0),
                           reverse=True):
            key = (fact.period_end, fact.period_start)
            if key in seen:
                continue
            seen.add(key)
            unique.append(fact)
        return unique[:periods]


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _parse_optional_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return _parse_date(value)
    except ValueError:
        return None
