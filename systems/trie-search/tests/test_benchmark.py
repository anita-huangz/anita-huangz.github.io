"""The benchmark is quoted in the README, so it has to keep working.

These do not assert timings -- a test that fails when the machine is busy is
worse than no test. They assert the things the README's argument rests on: that
both approaches find the same words, and that the harness reports honestly.
"""

from collections import Counter

import pytest

from trie_search.benchmark import (
    _corpus,
    _index_bytes,
    _inflected,
    compare,
    main,
    measure_index,
    print_index_cost,
    vocabulary_words,
)
from trie_search.crawler import build_search_index
from trie_search.stem import stem
from trie_search.trie import Trie


def test_vocabulary_is_distinct_and_reproducible():
    first = vocabulary_words(500)
    assert len(first) == 500
    assert len(set(first)) == 500
    assert first == vocabulary_words(500), "the table must be reproducible between runs"


def test_vocabulary_words_are_within_the_stated_shape():
    assert all(3 <= len(w) <= 10 and w.isalpha() and w.islower()
               for w in vocabulary_words(300))


def test_the_trie_and_the_scan_agree_on_prefixes():
    """The comparison is only meaningful if both find the same answers."""
    keys = vocabulary_words(3000)
    trie = Trie({k: i for i, k in enumerate(keys)})
    for prefix in ("a", "ab", "zz", "qqq"):
        assert sorted(trie.keys_with_prefix(prefix)) == sorted(
            k for k in keys if k.startswith(prefix)
        ), prefix


def test_the_trie_and_the_scan_agree_on_wildcards():
    import re

    keys = vocabulary_words(3000)
    trie = Trie({k: i for i, k in enumerate(keys)})
    for pattern in ("?ar?", "a?c", "??"):
        expected = [k for k in keys if re.fullmatch(pattern.replace("?", "."), k)]
        assert sorted(w for w, _ in trie.wildcard_search(pattern)) == sorted(expected), (
            pattern
        )


def test_compare_reports_the_same_hit_count_for_both_methods():
    row = compare(2000, "ab", "?ar?", repeats=1)
    keys = vocabulary_words(2000)
    assert row["prefix_matches"] == sum(1 for k in keys if k.startswith("ab"))
    assert row["size"] == 2000
    assert row["prefix_trie"] >= 0 and row["prefix_scan"] >= 0


@pytest.mark.parametrize("argv", [
    ["--sizes", "500"],
    ["--sizes", "500,1000", "--prefix", "a", "--pattern", "??", "--repeats", "1"],
])
def test_the_command_line_runs(argv, capsys):
    assert main(argv) == 0
    out = capsys.readouterr().out
    assert "trie" in out and "scan" in out


class TestTheInflectedVocabulary:
    """The corpus the index benchmark runs on has to have morphology.

    This is not a detail. An earlier version of the `--index` table generated
    random letter strings and then reported that stemming folded 462 terms into
    462 -- a true number that said nothing about the stemmer and everything
    about the generator. Real roots with real endings are what make the
    measurement mean anything.
    """

    def test_surface_forms_of_the_same_root_are_present(self):
        words = set(_inflected(160))
        assert {"park", "parks", "parked", "parking"} <= words

    def test_it_pads_with_filler_once_the_real_roots_run_out(self):
        assert len(_inflected(400)) == 400

    def test_it_truncates_rather_than_overshooting(self):
        assert len(_inflected(20)) == 20

    def test_it_is_reproducible(self):
        assert _inflected(400) == _inflected(400)

    def test_stemming_actually_collapses_this_vocabulary(self):
        # The claim the benchmark exists to support, checked directly rather
        # than read off a timing table.
        words = _inflected(160)
        assert len({stem(w) for w in words}) < len(set(words))


class TestTheSyntheticCorpus:
    def test_it_is_reproducible_for_a_seed(self):
        assert _corpus(3, 50) == _corpus(3, 50)

    def test_it_has_the_requested_shape(self):
        corpus = _corpus(4, 50)
        assert len(corpus) == 4
        assert all(len(words) == 50 for words in corpus.values())

    def test_word_frequencies_are_skewed_rather_than_uniform(self):
        # A uniform corpus would make positions look free: every term would
        # appear about once, so counts and positions would cost the same.
        counts = Counter(w for words in _corpus(20, 200).values() for w in words)
        most_common = counts.most_common(1)[0][1]
        assert most_common > 10 * (sum(counts.values()) / len(counts))


class TestIndexCostMeasurement:
    def test_it_reports_one_row_per_index_variant(self):
        rows = measure_index(pages=5, words_per_page=60)
        assert [row["label"] for row in rows] == [
            "counts only",
            "with positions",
            "positions + stemming",
        ]
        assert all(row["total_words"] == 300 for row in rows)

    def test_positions_cost_more_than_counts(self):
        # The whole point of the table: positions are one entry per *token*,
        # counts are one per distinct term per page. If this ever inverts, the
        # payload measurement is wrong.
        counts, positions, _ = measure_index(pages=5, words_per_page=200)
        assert positions["bytes"] > counts["bytes"]

    def test_stemming_reduces_the_term_count_on_a_corpus_with_morphology(self):
        _, positions, stemmed = measure_index(pages=5, words_per_page=200)
        assert stemmed["terms"] < positions["terms"]

    def test_the_payload_measure_grows_with_the_corpus_not_the_container(self):
        small = measure_index(pages=2, words_per_page=100)[1]["bytes"]
        large = measure_index(pages=8, words_per_page=100)[1]["bytes"]
        assert large > small

    def test_a_term_with_no_posting_is_skipped_rather_than_crashing(self):
        index = build_search_index({"/a": ["park", "parking"]}, positions=True)
        assert _index_bytes(index) > 0


class TestTheIndexTable:
    def test_the_command_line_prints_it(self, capsys):
        assert main(["--index", "--pages", "5", "--words-per-page", "80"]) == 0
        out = capsys.readouterr().out
        assert "counts only" in out
        assert "positions + stemming" in out
        assert "400 tokens" in out

    def test_it_quantifies_the_fold_when_stemming_helps(self, capsys):
        print_index_cost(pages=5, words_per_page=200)
        out = capsys.readouterr().out
        assert "Stemming folds" in out
        assert "fewer" in out

    def test_it_says_so_plainly_when_stemming_does_not_help(self, monkeypatch, capsys):
        # The honest branch. It exists because the first version of this table
        # reported no reduction and the README claimed one anyway.
        monkeypatch.setattr(
            "trie_search.benchmark._inflected",
            lambda count, seed=0: vocabulary_words(count, seed),
        )
        print_index_cost(pages=5, words_per_page=200)
        out = capsys.readouterr().out
        assert "Stemming did not reduce" in out
        assert "no inflections to collapse" in out
