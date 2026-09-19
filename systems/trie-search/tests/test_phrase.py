"""Phrase search: adjacency, and the cases where it must say no.

The interesting tests are the negatives. A phrase search that returns pages
containing both words is not a phrase search, it is the bag-of-words query with
extra syntax, and it would look like it worked.
"""

import math
from collections import Counter

import pytest

from trie_search.crawler import build_search_index
from trie_search.ranking import (
    Corpus,
    MissingPositions,
    Posting,
    bm25_score,
    count_words,
    inverse_document_frequency,
    phrase_matches,
    rank_phrase,
)

PAGES = {
    "/adjacent": ["the", "park", "hours", "are", "posted", "at", "the", "gate"],
    "/apart": ["opening", "hours", "are", "listed", "for", "every", "park"],
    "/repeated": ["park", "hours", "park", "hours", "park", "hours"],
    "/reversed": ["hours", "park"],
    "/single": ["park"],
}


@pytest.fixture
def index():
    return build_search_index(PAGES)


def urls(hits):
    return {h.url for h in hits}


class TestAdjacency:
    def test_finds_only_pages_with_the_words_adjacent(self, index):
        assert urls(index.search('"park hours"')) == {"/adjacent", "/repeated"}

    def test_the_unquoted_query_finds_more(self, index):
        """The contrast is the point: /apart has both words, not the phrase."""
        assert "/apart" in urls(index.search("park hours"))
        assert "/apart" not in urls(index.search('"park hours"'))

    def test_order_matters(self, index):
        assert urls(index.search('"hours park"')) == {"/reversed", "/repeated"}

    def test_counts_every_occurrence(self, index):
        hit = next(h for h in index.search('"park hours"') if h.url == "/repeated")
        assert hit.matched == {"park hours": 3}

    def test_more_occurrences_rank_higher(self, index):
        ranked = [h.url for h in index.search('"park hours"')]
        assert ranked[0] == "/repeated"

    def test_a_missing_word_means_no_phrase(self, index):
        assert index.search('"park zebra"') == []

    def test_a_phrase_longer_than_the_page(self, index):
        assert index.search('"park hours are posted at the gate tomorrow"') == []

    def test_a_single_quoted_word_is_an_ordinary_search(self, index):
        assert urls(index.search('"park"')) == urls(index.search("park"))

    def test_an_empty_phrase_returns_nothing(self, index):
        assert index.search('""') == []


class TestPhraseMatches:
    def test_counts_runs_directly(self):
        a, b = Posting(), Posting()
        a.record("/x", [0, 5, 9])
        b.record("/x", [1, 6, 20])
        assert phrase_matches([a, b], "/x") == 2

    def test_overlapping_runs_of_a_repeated_word(self):
        # "ha ha ha": the phrase "ha ha" occurs twice, not three times.
        a = Posting()
        a.record("/x", [0, 1, 2])
        assert phrase_matches([a, a], "/x") == 2

    def test_a_page_without_the_term(self):
        a, b = Posting(), Posting()
        a.record("/x", [0])
        b.record("/y", [1])
        assert phrase_matches([a, b], "/x") == 0

    def test_no_postings(self):
        assert phrase_matches([], "/x") == 0


class TestWithoutPositions:
    def test_an_index_built_without_positions_says_so(self):
        index = build_search_index(PAGES, positions=False)
        assert not index.has_positions
        with pytest.raises(MissingPositions, match="without positions"):
            index.search('"park hours"')

    def test_ordinary_search_still_works_without_positions(self):
        index = build_search_index(PAGES, positions=False)
        assert urls(index.search("park hours"))

    def test_counts_agree_whether_or_not_positions_were_recorded(self):
        """The two build paths must not disagree about term frequency."""
        with_pos = build_search_index(PAGES, positions=True)
        without = build_search_index(PAGES, positions=False)
        for term in ("park", "hours", "the"):
            a, b = with_pos.posting(term), without.posting(term)
            assert a.counts == b.counts, term

    def test_positions_and_counts_stay_in_step(self):
        index = build_search_index(PAGES)
        for term in ("park", "hours", "the"):
            posting = index.posting(term)
            for url, count in posting.counts.items():
                assert len(posting.positions[url]) == count


class TestWithStemming:
    def test_a_phrase_works_on_stems(self):
        pages = {"/a": ["the", "parking", "hours", "are", "posted"]}
        index = build_search_index(pages, stemming=True)
        assert urls(index.search('"park hour"')) == {"/a"}

    def test_positions_survive_stemming(self):
        pages = {"/a": ["parks", "parking", "parked"]}
        index = build_search_index(pages, stemming=True)
        posting = index.posting("park")
        assert posting.positions["/a"] == [0, 1, 2]


class TestDegenerateInputs:
    """The guards. Each one is a division or a ranking that would go wrong.

    None of these are reachable from the CLI today, which is exactly why they
    are worth pinning: they are the contracts the scorer keeps for callers that
    do not exist yet, and a silent 0.0 beats a ZeroDivisionError in a search
    result page.
    """

    def test_an_empty_corpus_has_no_average_page_length(self):
        assert Corpus().average_length == 0.0

    def test_a_term_on_no_page_carries_no_signal(self):
        assert inverse_document_frequency(corpus_size=10, document_frequency=0) == 0.0

    def test_an_empty_corpus_scores_every_term_at_zero(self):
        assert inverse_document_frequency(corpus_size=0, document_frequency=1) == 0.0

    def test_the_smoothed_form_stays_positive_where_robertsons_goes_negative(self):
        # The `1.0 +` inside the log is doing this, not the max(). Robertson's
        # original form turns negative once a term is on more than half the
        # pages, and then a page improves its rank by *not* matching.
        for size, frequency in ((10, 6), (10, 9), (100, 99)):
            robertson = math.log((size - frequency + 0.5) / (frequency + 0.5))
            assert robertson < 0
            assert inverse_document_frequency(size, frequency) > 0

    def test_the_floor_fires_only_when_the_index_outruns_the_corpus(self):
        # df > N means the index and the corpus have disagreed. That is the one
        # case the max() is there for; for any df <= N it is unreachable.
        assert inverse_document_frequency(corpus_size=10, document_frequency=11) == 0.0
        assert inverse_document_frequency(corpus_size=10, document_frequency=20) == 0.0

    def test_a_term_that_does_not_occur_contributes_nothing(self):
        assert bm25_score(
            term_frequency=0, document_length=100, average_length=100.0, idf=2.0
        ) == 0.0

    def test_a_term_with_no_idf_contributes_nothing(self):
        assert bm25_score(
            term_frequency=5, document_length=100, average_length=100.0, idf=0.0
        ) == 0.0

    def test_with_no_average_length_the_score_falls_back_to_the_idf(self):
        # No length normalisation is possible, so the term is worth its raw
        # informativeness rather than zero or a division by zero.
        assert bm25_score(
            term_frequency=5, document_length=100, average_length=0.0, idf=2.0
        ) == 2.0

    def test_counting_words_is_a_plain_frequency_table(self):
        assert count_words(["a", "b", "a"]) == Counter({"a": 2, "b": 1})

    def test_a_phrase_with_no_postings_matches_nothing(self):
        assert phrase_matches([], "/a") == 0

    def test_a_page_missing_the_first_term_cannot_carry_the_phrase(self):
        posting = Posting()
        posting.record("/a", [0, 1])
        assert phrase_matches([posting], "/b") == 0

    def test_a_term_count_mismatch_is_refused_rather_than_mis_scored(self):
        # Scoring n postings as an m-word phrase would report a phrase that was
        # never searched for.
        posting = Posting()
        posting.record("/a", [0])
        corpus = Corpus()
        corpus.add("/a", 10)
        assert rank_phrase(["park", "hours"], [posting], corpus) == []

    def test_an_empty_corpus_ranks_no_phrase(self):
        posting = Posting()
        posting.record("/a", [0])
        assert rank_phrase(["park"], [posting], Corpus()) == []

    def test_pages_carrying_both_words_but_never_adjacent_are_not_hits(self):
        # The honest reading: a page with forty "park"s and thirty "hours"
        # has not mentioned "park hours" at all.
        park, hours = Posting(), Posting()
        park.record("/a", [0, 5, 10])
        hours.record("/a", [2, 7, 12])
        corpus = Corpus()
        corpus.add("/a", 20)
        assert rank_phrase(["park", "hours"], [park, hours], corpus) == []
