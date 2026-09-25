"""Chunking, the four retrieval strategies, and the benchmark that ranks them.

The benchmark runs against three real 10-K risk-factor sections committed as a
fixture. That makes these tests slower than synthetic ones and worth it: the
behaviour being checked -- that selecting by relevance beats taking the front
of the text -- is invisible on a document short enough not to be truncated.
"""

from __future__ import annotations

import json
from itertools import pairwise
from pathlib import Path

import pytest

from filing_intel.retrieval import (
    HybridRetriever,
    LexicalRetriever,
    SemanticRetriever,
    TruncationRetriever,
    build_retriever,
    chunk_section,
)
from filing_intel.retrieval.benchmark import CASES, TRUNCATION_CHARS, load_sections, reach, run
from filing_intel.retrieval.chunking import sentences
from filing_intel.retrieval.retrievers import LsaEmbedder, tokenize

FIXTURE = Path(__file__).parent / "fixtures" / "sections" / "risk_factors.json"


@pytest.fixture(scope="module")
def sections() -> dict[str, str]:
    return load_sections()


@pytest.fixture(scope="module")
def apple(sections) -> str:
    return sections["AAPL"]


class TestChunking:
    def test_it_splits_on_sentence_ends(self):
        text = "First sentence here. Second sentence here. Third sentence here."
        assert len(sentences(text)) == 3

    def test_offsets_point_back_into_the_original(self):
        text = "Alpha risk here. Beta risk follows. Gamma risk ends it."
        for sentence, start in sentences(text):
            assert text[start : start + len(sentence)] == sentence

    def test_passages_are_ordered_and_anchored(self, apple):
        passages = chunk_section(apple)
        assert len(passages) > 50
        assert all(a.start <= b.start for a, b in pairwise(passages))
        for passage in passages[:20]:
            assert passage.text in apple

    def test_passages_stay_near_the_target_size(self, apple):
        # "Near" rather than "at": a single 1,200-character sentence becomes its
        # own passage instead of being cut mid-clause.
        lengths = [p.length for p in chunk_section(apple, chunk_chars=900)]
        median = sorted(lengths)[len(lengths) // 2]
        assert 400 < median < 1400

    def test_overlap_repeats_the_boundary_rather_than_losing_it(self):
        text = " ".join(f"Sentence number {i} about supply chain risk." for i in range(40))
        no_overlap = chunk_section(text, chunk_chars=200, overlap_chars=0)
        overlapped = chunk_section(text, chunk_chars=200, overlap_chars=80)
        assert len(overlapped) >= len(no_overlap)

    def test_empty_text_yields_nothing(self):
        assert chunk_section("") == []
        assert chunk_section("   \n  ") == []

    def test_a_single_short_sentence_is_one_passage(self):
        assert len(chunk_section("Only one sentence.")) == 1

    @pytest.mark.parametrize(
        ("chunk_chars", "overlap"), [(0, 0), (-1, 0), (100, 100), (100, 200), (100, -1)]
    )
    def test_nonsense_sizes_are_refused(self, chunk_chars, overlap):
        with pytest.raises(ValueError):
            chunk_section("Some text here.", chunk_chars=chunk_chars, overlap_chars=overlap)

    def test_preview_is_flattened_and_bounded(self, apple):
        preview = chunk_section(apple)[5].preview(60)
        assert len(preview) <= 60
        assert "\n" not in preview


class TestTokenizing:
    def test_it_lowercases_and_drops_stopwords(self):
        assert tokenize("The Company AND its Suppliers") == ["company", "suppliers"]

    def test_it_keeps_negations(self):
        # An aggressive stop list throws away "not", and in risk disclosure the
        # difference between "may" and "may not" is the disclosure.
        assert "not" in tokenize("The Company may not be able to obtain components")

    def test_punctuation_and_digits_do_not_become_terms(self):
        assert tokenize("2023, 15% -- (see note)") == ["see", "note"]


class TestRetrievers:
    def test_truncation_ignores_the_query_and_returns_the_front(self, apple):
        passages = chunk_section(apple)
        hits = TruncationRetriever(passages).search("anything at all", 4)
        assert [h.passage.index for h in hits] == [0, 1, 2, 3]

    def test_truncation_cannot_reach_past_its_own_cut(self, apple):
        # The whole reason the other three exist.
        passages = chunk_section(apple)
        front = [p for p in passages if p.start < TRUNCATION_CHARS]
        hits = TruncationRetriever(front).search("dividend", 5)
        assert all("dividend" not in h.text.lower() for h in hits)

    @pytest.mark.parametrize("strategy", ["bm25", "lsa", "hybrid"])
    def test_a_ranking_retriever_finds_a_distinctive_term(self, apple, strategy):
        hits = build_retriever(strategy, apple).search("Digital Markets Act commission", 5)
        assert any("digital markets act" in h.text.lower() for h in hits)

    @pytest.mark.parametrize("strategy", ["truncation", "bm25", "lsa", "hybrid"])
    def test_every_strategy_respects_the_limit(self, apple, strategy):
        assert len(build_retriever(strategy, apple).search("supply chain", 3)) <= 3

    @pytest.mark.parametrize("strategy", ["bm25", "lsa", "hybrid"])
    def test_scores_come_back_in_order(self, apple, strategy):
        hits = build_retriever(strategy, apple).search("regulatory investigation", 8)
        assert [h.score for h in hits] == sorted((h.score for h in hits), reverse=True)
        assert [h.rank for h in hits] == list(range(len(hits)))

    def test_bm25_returns_nothing_for_a_query_of_only_stopwords(self, apple):
        assert LexicalRetriever(chunk_section(apple)).search("the and of it", 5) == []

    def test_semantic_returns_nothing_for_an_empty_query(self, apple):
        assert SemanticRetriever(chunk_section(apple)).search("   ", 5) == []

    def test_retrievers_cope_with_an_empty_section(self):
        for cls in (TruncationRetriever, LexicalRetriever, SemanticRetriever, HybridRetriever):
            assert cls([]).search("anything", 3) == []

    def test_an_unknown_strategy_names_the_ones_that_exist(self, apple):
        with pytest.raises(ValueError, match="unknown strategy"):
            build_retriever("vector-magic", apple)

    def test_the_embedder_refuses_to_transform_before_it_is_fitted(self):
        with pytest.raises(RuntimeError, match="fit_transform"):
            LsaEmbedder().transform(["anything"])

    def test_embeddings_come_back_unit_length(self, apple):
        import numpy as np

        texts = [p.text for p in chunk_section(apple)[:40]]
        vectors = LsaEmbedder(components=16).fit_transform(texts)
        assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-9)

    def test_retrieval_is_deterministic(self, apple):
        first = build_retriever("lsa", apple).search("export restrictions", 5)
        second = build_retriever("lsa", apple).search("export restrictions", 5)
        assert [h.passage.index for h in first] == [h.passage.index for h in second]


class TestBenchmark:
    def test_the_fixture_holds_three_real_filings(self):
        data = json.loads(FIXTURE.read_text())
        assert set(data) == {"AAPL", "MSFT", "NVDA"}
        for filing in data.values():
            assert filing["text"].lower().startswith("item 1a")
            assert len(filing["text"]) > 60_000

    def test_every_target_sits_past_the_truncation_point(self, sections):
        # If one did not, truncation could score on it and the comparison would
        # be measuring something other than what it claims.
        for case in CASES:
            passages = chunk_section(sections[case.ticker])
            holding = [p for p in passages if case.anchor.lower() in p.text.lower()]
            assert holding, f"{case.ticker}/{case.anchor} is not in the fixture at all"
            assert all(p.start > TRUNCATION_CHARS for p in holding), case.anchor

    def test_truncation_sees_less_than_a_third_of_every_section(self, sections):
        assert all(share < 0.34 for share in reach(sections).values())

    def test_truncation_scores_zero_and_retrieval_does_not(self, sections):
        scores = {s.strategy: s for s in run(limit=5, sections=sections)}
        assert scores["truncation"].hits == 0
        assert scores["bm25"].recall > 0.5
        assert scores["lsa"].recall > 0.5

    def test_the_semantic_retriever_wins_on_this_set(self, sections):
        # By two cases out of twelve, which is one paraphrase away from a tie.
        # Asserted because it is the reported result, not because it is a law.
        scores = {s.strategy: s for s in run(limit=5, sections=sections)}
        assert scores["lsa"].hits >= scores["bm25"].hits

    def test_the_lexical_retriever_ranks_its_hits_higher(self, sections):
        # When exact terms overlap, BM25 is more precise about where.
        scores = {s.strategy: s for s in run(limit=5, sections=sections)}
        assert scores["bm25"].mean_rank < scores["lsa"].mean_rank

    def test_a_score_with_no_hits_reports_a_dash_rather_than_a_rank(self, sections):
        truncation = next(s for s in run(limit=5, sections=sections) if s.strategy == "truncation")
        assert "—" in truncation.describe()
        assert truncation.recall == 0.0
