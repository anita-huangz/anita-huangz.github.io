"""Getting the right part of a filing in front of the model.

A risk-factors section runs 68,000 to 123,000 characters in the three filings
this package is tested against. `fetch_filing_section` truncates at 20,000, so
between 71% and 84% of it is discarded before the model sees anything -- and
the part kept is the *front*, chosen by position rather than by relevance.

This selects by relevance instead.
"""

from .chunking import Passage, chunk_section
from .retrievers import (
    HybridRetriever,
    LexicalRetriever,
    Retrieved,
    Retriever,
    SemanticRetriever,
    TruncationRetriever,
    build_retriever,
)

__all__ = [
    "HybridRetriever",
    "LexicalRetriever",
    "Passage",
    "Retrieved",
    "Retriever",
    "SemanticRetriever",
    "TruncationRetriever",
    "build_retriever",
    "chunk_section",
]
