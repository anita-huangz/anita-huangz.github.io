"""Relevance ranking.

The index previously mapped each word to the *set* of pages containing it, and
search returned that set in alphabetical order. That is retrieval without
ranking: a page mentioning "park" once and a park directory mentioning it forty
times were indistinguishable, and a two-word query had no way to prefer pages
matching both.

BM25 fixes both. It is the standard lexical scoring function and needs three
things the set could not provide: how often a term appears on a page, how long
the page is, and how many pages contain the term at all.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field

#: Term-frequency saturation. Raising it makes repeated mentions count for
#: longer before diminishing; 1.2-2.0 is the usual range.
K1 = 1.5
#: Length normalisation, 0 (off) to 1 (full). At 0.75 a long page is penalised
#: for its length but not erased by it.
B = 0.75


@dataclass
class Posting:
    """Where a term occurs, how often, and -- when known -- exactly where.

    `counts` is enough for BM25, which only asks how many times a term appears
    on a page. `positions` is what phrase search needs, because "park hours" is
    not the same query as "park" and "hours" on the same page: the words have
    to be adjacent and in order, and only a position list can say whether they
    were.

    Positions are optional because they are not free -- a list of offsets per
    term per page is much larger than a count, and an index built for ranking
    alone should not pay for a feature it will not use. `record()` is the way
    to populate both together; setting `counts` directly is supported for
    callers that will never search for a phrase.
    """

    #: URL -> occurrences on that page.
    counts: dict[str, int] = field(default_factory=dict)
    #: URL -> word offsets, ascending. Empty when the index was built without
    #: positions, which `has_positions` reports rather than leaving to be
    #: discovered as an empty result set.
    positions: dict[str, list[int]] = field(default_factory=dict)

    def record(self, url: str, offsets: list[int]) -> None:
        """Add one page's occurrences, keeping count and positions in step."""
        self.positions[url] = offsets
        self.counts[url] = len(offsets)

    @property
    def has_positions(self) -> bool:
        return bool(self.positions)

    @property
    def document_frequency(self) -> int:
        return len(self.counts)

    def urls(self) -> set[str]:
        """Set view, for callers that only want membership."""
        return set(self.counts)


@dataclass
class Corpus:
    """Page statistics BM25 needs, kept alongside the trie.

    The trie answers "which words look like this". The corpus answers "how
    important is this word on this page". Neither substitutes for the other.
    """

    #: URL -> total words on that page.
    lengths: dict[str, int] = field(default_factory=dict)

    @property
    def size(self) -> int:
        return len(self.lengths)

    @property
    def average_length(self) -> float:
        if not self.lengths:
            return 0.0
        return sum(self.lengths.values()) / len(self.lengths)

    def add(self, url: str, word_count: int) -> None:
        self.lengths[url] = word_count


def inverse_document_frequency(corpus_size: int, document_frequency: int) -> float:
    """How much a term's presence should count.

    A word on every page carries no signal. The 0.5 offsets are the standard
    BM25 smoothing, and the `1.0 +` inside the log is what keeps the result
    non-negative: Robertson's original form, `log((N - df + 0.5)/(df + 0.5))`,
    goes negative once a term is on more than half the pages, and then a page
    improves its rank by *not* matching the query. This is the variant Lucene
    uses for that reason.

    Given that, `max(..., 0)` only ever fires when `df > N` -- a term recorded
    on more pages than the corpus knows about, which means the index and the
    corpus have disagreed. Kept as a guard rather than removed, because the
    alternative is a negative score propagating silently into a ranking.
    """
    if corpus_size == 0 or document_frequency == 0:
        return 0.0
    raw = math.log(
        1.0 + (corpus_size - document_frequency + 0.5) / (document_frequency + 0.5)
    )
    return max(raw, 0.0)


def bm25_score(
    term_frequency: int,
    document_length: int,
    average_length: float,
    idf: float,
) -> float:
    """BM25 contribution of one term to one document."""
    if term_frequency <= 0 or idf <= 0:
        return 0.0
    if average_length <= 0:
        return idf
    normalised = K1 * (1 - B + B * (document_length / average_length))
    return idf * (term_frequency * (K1 + 1)) / (term_frequency + normalised)


@dataclass
class Hit:
    url: str
    score: float
    #: Matched term -> occurrences, so a result can explain itself.
    matched: dict[str, int] = field(default_factory=dict)

    @property
    def total_occurrences(self) -> int:
        return sum(self.matched.values())


def rank(
    postings: dict[str, Posting],
    corpus: Corpus,
    require_all: bool = False,
) -> list[Hit]:
    """Score every page that matches at least one term.

    `require_all` turns the query from OR into AND, which is what a user
    typing two words usually means.
    """
    if not postings or corpus.size == 0:
        return []

    average = corpus.average_length
    idfs = {
        term: inverse_document_frequency(corpus.size, posting.document_frequency)
        for term, posting in postings.items()
    }

    scores: dict[str, float] = {}
    matched: dict[str, dict[str, int]] = {}
    for term, posting in postings.items():
        for url, count in posting.counts.items():
            length = corpus.lengths.get(url, 0)
            scores[url] = scores.get(url, 0.0) + bm25_score(
                count, length, average, idfs[term]
            )
            matched.setdefault(url, {})[term] = count

    if require_all:
        needed = len(postings)
        scores = {u: s for u, s in scores.items() if len(matched[u]) == needed}

    hits = [
        Hit(url=url, score=round(score, 6), matched=matched[url])
        for url, score in scores.items()
    ]
    # Score descending, then URL, so equal scores order deterministically.
    hits.sort(key=lambda h: (-h.score, h.url))
    return hits


def count_words(words: list[str]) -> Counter[str]:
    return Counter(words)


class MissingPositions(RuntimeError):
    """A phrase query hit an index built without position data."""


def phrase_matches(postings: list[Posting], url: str) -> int:
    """How many times the terms appear consecutively, in order, on one page.

    Walks the first term's offsets and checks each following term sits exactly
    one position later. Membership is tested against sets, so the cost is
    proportional to the occurrences of the *rarest* placement rather than to
    the length of the page -- looking for "the quick brown fox" on a page with
    a thousand "the"s still only does a thousand constant-time probes.
    """
    if not postings:
        return 0
    first, *rest = postings
    if url not in first.positions:
        return 0
    later = [set(p.positions.get(url, ())) for p in rest]
    hits = 0
    for start in first.positions[url]:
        if all(start + offset + 1 in seen for offset, seen in enumerate(later)):
            hits += 1
    return hits


def rank_phrase(
    terms: list[str],
    postings: list[Posting],
    corpus: Corpus,
) -> list[Hit]:
    """Score pages containing the exact phrase.

    The phrase is scored as though it were a single term: its occurrence count
    is the number of adjacent runs, and its document frequency is the number of
    pages containing one. That is the honest reading -- a page mentioning
    "park" forty times and "hours" thirty times has not mentioned "park hours"
    at all, and summing the two terms' scores would rank it top.
    """
    if len(postings) != len(terms) or corpus.size == 0:
        return []
    for term, posting in zip(terms, postings, strict=True):
        if not posting.has_positions:
            raise MissingPositions(
                f"no positions recorded for {term!r}; build the index with "
                f"`build_search_index(..., positions=True)` to search phrases"
            )

    # Only pages carrying every term can carry the phrase.
    candidates = set(postings[0].counts)
    for posting in postings[1:]:
        candidates &= set(posting.counts)

    occurrences = {url: phrase_matches(postings, url) for url in candidates}
    occurrences = {url: n for url, n in occurrences.items() if n > 0}
    if not occurrences:
        return []

    phrase = " ".join(terms)
    idf = inverse_document_frequency(corpus.size, len(occurrences))
    average = corpus.average_length
    hits = [
        Hit(
            url=url,
            score=round(
                bm25_score(count, corpus.lengths.get(url, 0), average, idf), 6
            ),
            matched={phrase: count},
        )
        for url, count in occurrences.items()
    ]
    hits.sort(key=lambda h: (-h.score, h.url))
    return hits
