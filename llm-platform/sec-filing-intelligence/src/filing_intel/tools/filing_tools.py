"""The four filing-research tools, and the wiring that registers them."""

from __future__ import annotations

from ..cache import CacheBackend
from ..contracts import (
    Capability,
    CompanyFactsArgs,
    FetchSectionArgs,
    PriceReactionArgs,
    RetrievedPassage,
    SearchFilingsArgs,
    SectionText,
)
from ..data import EdgarClient, PriceClient
from ..retrieval import build_retriever
from ..telemetry import TelemetryRecorder
from .registry import Tool, ToolRegistry

#: How much of a section to pull when a query is supplied. The contract caps
#: `max_chars` at 200,000 and the longest section in the test corpus is 115,143,
#: so this is "all of it" without inventing a second limit.
MAX_SECTION_CHARS = 200_000

#: Latent semantic analysis. On the twelve-query benchmark it recalls 10/12
#: against BM25's 8/12, winning the two cases whose wording shares nothing with
#: the passage. See `retrieval/benchmark.py`.
RETRIEVAL_STRATEGY = "lsa"


def build_registry(
    edgar: EdgarClient,
    prices: PriceClient,
    cache: CacheBackend,
    telemetry: TelemetryRecorder,
    default_ttl: int = 3600,
) -> ToolRegistry:
    registry = ToolRegistry(cache=cache, telemetry=telemetry, default_ttl=default_ttl)

    async def search_filings(args: SearchFilingsArgs):
        return await edgar.search_filings(
            ticker=args.ticker, form_type=args.form_type.value, limit=args.limit
        )

    async def fetch_filing_section(args: FetchSectionArgs):
        if args.query is None:
            return await edgar.fetch_section(
                ticker=args.ticker,
                accession=args.accession,
                section=args.section,
                max_chars=args.max_chars,
            )

        # With a query, fetch the section whole and select from it. Truncating
        # first and then retrieving would search the same fifth of the text the
        # unqualified call already returns, which is the problem, not the fix.
        whole = await edgar.fetch_section(
            ticker=args.ticker,
            accession=args.accession,
            section=args.section,
            max_chars=MAX_SECTION_CHARS,
        )
        retriever = build_retriever(RETRIEVAL_STRATEGY, whole.text)
        hits = retriever.search(args.query, args.passages)
        return SectionText(
            accession=whole.accession,
            section=whole.section,
            # The joined passages are what the model reads; `passages` keeps
            # them separable with their offsets so a citation can point at a
            # position rather than at "somewhere in what we sent".
            text="\n\n[…]\n\n".join(h.text for h in hits),
            char_count=whole.char_count,
            truncated=whole.truncated,
            passages=[
                RetrievedPassage(
                    text=h.text, start=h.passage.start, end=h.passage.end, score=h.score
                )
                for h in hits
            ],
            retrieval=retriever.name,
        )

    async def company_financials(args: CompanyFactsArgs):
        return await edgar.company_facts(
            ticker=args.ticker, concept=args.concept, periods=args.periods
        )

    async def price_reaction(args: PriceReactionArgs):
        return await prices.event_reaction(
            ticker=args.ticker, event_date=args.event_date, horizons=args.horizons
        )

    registry.register(
        Tool(
            name="search_filings",
            description=(
                "List a company's recent SEC filings of a given form type. Returns "
                "accession numbers, filing dates, and period-of-report dates. Use this "
                "first to find the accession number that the other tools need."
            ),
            args_model=SearchFilingsArgs,
            capability=Capability.READ_FILINGS,
            handler=search_filings,
            # Filing lists change only when a company files; a day is safe.
            cache_ttl_seconds=86_400,
        )
    )
    registry.register(
        Tool(
            name="fetch_filing_section",
            description=(
                "Fetch the text of one section of a filing (business, risk_factors, "
                "mda, or financial_statements) given its accession number. Without "
                "a query the text is truncated to max_chars -- for a risk-factors "
                "section that is roughly the first fifth -- so pass `query` "
                "describing what you need and the most relevant passages from the "
                "whole section are returned instead."
            ),
            args_model=FetchSectionArgs,
            capability=Capability.READ_FILINGS,
            handler=fetch_filing_section,
            # Filing text is immutable once filed.
            cache_ttl_seconds=604_800,
        )
    )
    registry.register(
        Tool(
            name="company_financials",
            description=(
                "Fetch reported XBRL values for a US-GAAP concept (e.g. Revenues, "
                "NetIncomeLoss, OperatingIncomeLoss, Assets) across recent periods, "
                "newest first. Use for quantitative claims instead of reading tables."
            ),
            args_model=CompanyFactsArgs,
            capability=Capability.READ_FINANCIALS,
            handler=company_financials,
            cache_ttl_seconds=86_400,
        )
    )
    registry.register(
        Tool(
            name="price_reaction",
            description=(
                "Cumulative stock return over N trading days following an event date, "
                "measured from the last close on or before that date. Use to quantify "
                "how the market reacted to a filing."
            ),
            args_model=PriceReactionArgs,
            capability=Capability.READ_PRICES,
            handler=price_reaction,
            cache_ttl_seconds=86_400,
        )
    )
    return registry
