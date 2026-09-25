"""Typed boundaries.

These models are the contract between every layer: HTTP request bodies, MCP tool
arguments, tool results, model responses, and telemetry events all validate
through here. Nothing crosses a layer as a bare dict.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

TICKER_RE = re.compile(r"^[A-Z][A-Z.\-]{0,9}$")

Ticker = Annotated[str, Field(min_length=1, max_length=10)]


def utcnow() -> datetime:
    return datetime.now(UTC)


class Strict(BaseModel):
    """Base for every contract: unknown fields are an error, not a shrug."""

    model_config = ConfigDict(extra="forbid", frozen=False)


# --------------------------------------------------------------------------- #
# Domain vocabulary
# --------------------------------------------------------------------------- #


class FormType(StrEnum):
    ANNUAL = "10-K"
    QUARTERLY = "10-Q"
    CURRENT = "8-K"
    PROXY = "DEF 14A"


class FilingSection(StrEnum):
    """The sections callers actually ask for, mapped to 10-K/10-Q item numbers."""

    BUSINESS = "business"
    RISK_FACTORS = "risk_factors"
    MDA = "mda"
    FINANCIAL_STATEMENTS = "financial_statements"


class Filing(Strict):
    accession: str = Field(description="SEC accession number, dashed form.")
    ticker: str
    cik: str
    form_type: str
    filed_at: date
    period_of_report: date | None = None
    primary_document: str | None = None

    @property
    def url(self) -> str:
        """Canonical EDGAR URL for the filing's primary document."""
        bare = self.accession.replace("-", "")
        cik = self.cik.lstrip("0")
        if not self.primary_document:
            return f"https://www.sec.gov/Archives/edgar/data/{cik}/{bare}"
        return (
            f"https://www.sec.gov/Archives/edgar/data/{cik}/{bare}/{self.primary_document}"
        )


class RetrievedPassage(Strict):
    """One span of a section, and where in it the span came from."""

    text: str
    start: int
    end: int
    score: float


class SectionText(Strict):
    accession: str
    section: FilingSection
    text: str
    char_count: int
    truncated: bool = False
    #: Set when the caller supplied a query. The passages are drawn from the
    #: *whole* section rather than its first `max_chars`, which is the point:
    #: a risk-factors section runs to 115,000 characters and truncation shows
    #: about a fifth of it.
    passages: list[RetrievedPassage] = Field(default_factory=list)
    retrieval: str | None = None


class FinancialFact(Strict):
    concept: str = Field(description="US-GAAP XBRL concept, e.g. 'Revenues'.")
    unit: str
    value: float
    period_end: date
    period_start: date | None = Field(
        default=None,
        description="Start of the reporting period. Absent for instant facts.",
    )
    fiscal_year: int | None = None
    fiscal_period: str | None = None
    form_type: str | None = None

    @property
    def duration_days(self) -> int | None:
        if self.period_start is None:
            return None
        return (self.period_end - self.period_start).days

    @property
    def period_label(self) -> str:
        """'FY', 'Q', or 'as of' -- what span the number actually covers.

        XBRL returns overlapping contexts for the same end date: a quarter and
        the year-to-date that contains it. Without the span they look like two
        contradictory values for one period.
        """
        days = self.duration_days
        if days is None:
            return "as of"
        if days >= 300:
            return "FY"
        if days >= 150:
            return "H1/H2"
        return "quarter"


class PriceReaction(Strict):
    ticker: str
    event_date: date
    baseline_close: float
    windows: dict[str, float] = Field(
        description="Trading-day horizon ('1d','5d') to cumulative return as a decimal."
    )


# --------------------------------------------------------------------------- #
# Tool boundary
# --------------------------------------------------------------------------- #


class Capability(StrEnum):
    """Least-privilege buckets. A caller is granted a set; tools declare one."""

    READ_FILINGS = "read_filings"
    READ_FINANCIALS = "read_financials"
    READ_PRICES = "read_prices"


class SearchFilingsArgs(Strict):
    ticker: Ticker
    form_type: FormType = FormType.ANNUAL
    limit: int = Field(default=5, ge=1, le=25)

    @field_validator("ticker")
    @classmethod
    def _upper(cls, v: str) -> str:
        v = v.strip().upper()
        if not TICKER_RE.match(v):
            raise ValueError(f"not a plausible ticker: {v!r}")
        return v


class FetchSectionArgs(Strict):
    ticker: Ticker
    accession: str
    section: FilingSection = FilingSection.RISK_FACTORS
    max_chars: int = Field(default=20000, ge=500, le=200000)
    query: str | None = Field(
        default=None,
        max_length=500,
        description=(
            "What you are looking for. Supply it and the most relevant passages "
            "from the whole section are returned instead of its first max_chars, "
            "which for a risk-factors section is about a fifth of the text."
        ),
    )
    passages: int = Field(default=6, ge=1, le=20)

    @field_validator("ticker")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.strip().upper()


class CompanyFactsArgs(Strict):
    ticker: Ticker
    concept: str = Field(
        default="Revenues", description="US-GAAP concept name, case-sensitive."
    )
    periods: int = Field(default=8, ge=1, le=40)

    @field_validator("ticker")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.strip().upper()


class PriceReactionArgs(Strict):
    ticker: Ticker
    event_date: date
    horizons: list[int] = Field(default_factory=lambda: [1, 5, 10])

    @field_validator("ticker")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("horizons")
    @classmethod
    def _sane(cls, v: list[int]) -> list[int]:
        if not v:
            raise ValueError("at least one horizon required")
        if any(h < 1 or h > 60 for h in v):
            raise ValueError("horizons must be between 1 and 60 trading days")
        return sorted(set(v))


class ToolResult(Strict):
    """Uniform envelope so the agent loop never branches on tool identity."""

    tool: str
    ok: bool
    data: Any = None
    error: str | None = None
    error_kind: str | None = None
    cached: bool = False
    latency_ms: float = 0.0

    def for_model(self) -> str:
        """Render for a `tool_result` content block."""
        import json

        if not self.ok:
            return f"ERROR[{self.error_kind}]: {self.error}"
        return json.dumps(self.data, default=str, sort_keys=True)


# --------------------------------------------------------------------------- #
# Model boundary
# --------------------------------------------------------------------------- #


class TokenUsage(Strict):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_read_input_tokens=self.cache_read_input_tokens
            + other.cache_read_input_tokens,
            cache_creation_input_tokens=self.cache_creation_input_tokens
            + other.cache_creation_input_tokens,
        )

    @property
    def total(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_read_input_tokens
            + self.cache_creation_input_tokens
        )


class ToolCall(Strict):
    id: str
    name: str
    arguments: dict[str, Any]


class ModelResponse(Strict):
    """Provider-agnostic response. Nothing downstream imports `anthropic`."""

    text: str
    tool_calls: list[ToolCall] = Field(default_factory=list)
    stop_reason: str | None = None
    refusal_category: str | None = None
    usage: TokenUsage = Field(default_factory=TokenUsage)
    model: str = ""
    provider: str = ""
    latency_ms: float = 0.0
    raw_content: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Assistant content blocks, replayed verbatim on the next turn.",
    )


# --------------------------------------------------------------------------- #
# Research request / response
# --------------------------------------------------------------------------- #


class Citation(Strict):
    accession: str
    form_type: str
    filed_at: date
    detail: str
    url: str | None = None


class Finding(Strict):
    claim: str
    confidence: Literal["low", "medium", "high"]
    citations: list[Citation] = Field(default_factory=list)


class ResearchRequest(Strict):
    ticker: Ticker
    question: str = Field(min_length=3, max_length=2000)
    session_id: str | None = None
    capabilities: list[Capability] = Field(
        default_factory=lambda: list(Capability),
        description="Least-privilege grant for this request.",
    )

    @field_validator("ticker")
    @classmethod
    def _upper(cls, v: str) -> str:
        v = v.strip().upper()
        if not TICKER_RE.match(v):
            raise ValueError(f"not a plausible ticker: {v!r}")
        return v


class ResearchResponse(Strict):
    ticker: str
    question: str
    answer: str
    findings: list[Finding] = Field(default_factory=list)
    session_id: str
    trace_id: str
    tool_calls_made: int = 0
    usage: TokenUsage = Field(default_factory=TokenUsage)
    estimated_cost_usd: float = 0.0
    latency_ms: float = 0.0
    verified: bool = False
    verifier_note: str | None = None
