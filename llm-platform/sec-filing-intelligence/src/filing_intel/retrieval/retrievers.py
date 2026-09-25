"""Four ways to choose which part of a filing the model reads.

`TruncationRetriever` is what the tool does today: take the front, discard the
rest. It is here as the baseline to beat, because a retrieval layer that cannot
beat "the first 20,000 characters" is not worth its complexity.

`LexicalRetriever` is BM25 over the passages. Term frequency, saturating, with
a length penalty. It is old, it is cheap, and on domain text with a shared
vocabulary it is genuinely hard to beat.

`SemanticRetriever` is latent semantic analysis: TF-IDF over word unigrams and
bigrams, reduced by truncated SVD, compared by cosine. **It is a vector-space
embedding, not a neural one**, and the difference is worth stating plainly
rather than letting the word "semantic" do work it has not earned. A sentence
transformer would very likely retrieve better; it also costs a model download
and a torch dependency, and this package's standard is that everything runs
offline in CI with no downloads and no keys. The `Embedder` seam exists so a
neural model can be dropped in by anyone willing to pay that.

`HybridRetriever` fuses the two by reciprocal rank. Rank fusion rather than
score averaging because BM25 scores and cosine similarities are not on the same
scale and normalising them is a free parameter nobody can tune honestly on six
eval cases.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np

from .chunking import Passage, chunk_section

#: BM25's usual defaults. Tuning them on this corpus would be fitting three
#: filings.
K1 = 1.5
B = 0.75

#: Rank-fusion constant, from the original reciprocal-rank-fusion paper. It
#: damps the influence of the very top rank so one retriever cannot dominate.
RRF_K = 60

TOKEN = re.compile(r"[a-z][a-z0-9'-]+")

#: Words too common in a 10-K to carry any signal. Deliberately short: an
#: aggressive stop list throws away "not", and in risk disclosure "not" matters.
STOPWORDS = frozenset(
    [
        "a", "an", "and", "are", "as", "at", "be", "been", "by", "for", "from",
        "has", "have", "in", "is", "it", "its", "of", "on", "or", "our", "that",
        "the", "their", "these", "this", "to", "was", "were", "will", "with",
        "we", "us",
    ]
)


def tokenize(text: str) -> list[str]:
    return [t for t in TOKEN.findall(text.lower()) if t not in STOPWORDS]


@dataclass(frozen=True)
class Retrieved:
    """A passage and why it was chosen."""

    passage: Passage
    score: float
    rank: int

    @property
    def text(self) -> str:
        return self.passage.text


class Retriever(Protocol):
    """Rank a section's passages against a query."""

    name: str

    def search(self, query: str, limit: int) -> list[Retrieved]: ...


class TruncationRetriever:
    """The current behaviour: the front of the section, query ignored.

    Kept as a first-class retriever rather than as a special case, so the
    benchmark compares like with like and the baseline cannot quietly be given
    an advantage the others do not get.
    """

    name = "truncation"

    def __init__(self, passages: list[Passage]) -> None:
        self.passages = passages

    def search(self, query: str, limit: int) -> list[Retrieved]:
        return [
            Retrieved(passage=p, score=float(len(self.passages) - i), rank=i)
            for i, p in enumerate(self.passages[:limit])
        ]


@dataclass
class LexicalRetriever:
    """BM25. Exact term overlap, saturating, penalised for length."""

    passages: list[Passage]
    name: str = "bm25"
    _docs: list[list[str]] = field(default_factory=list, repr=False)
    _frequencies: list[Counter[str]] = field(default_factory=list, repr=False)
    _document_frequency: Counter[str] = field(default_factory=Counter, repr=False)
    _average_length: float = 0.0

    def __post_init__(self) -> None:
        self._docs = [tokenize(p.text) for p in self.passages]
        self._frequencies = [Counter(d) for d in self._docs]
        for frequency in self._frequencies:
            self._document_frequency.update(frequency.keys())
        lengths = [len(d) for d in self._docs]
        self._average_length = sum(lengths) / len(lengths) if lengths else 0.0

    def _idf(self, term: str) -> float:
        total = len(self._docs)
        seen = self._document_frequency.get(term, 0)
        if total == 0 or seen == 0:
            return 0.0
        # The `1 +` inside the log is what keeps this non-negative; Robertson's
        # original form goes negative for a term on more than half the
        # documents, and then a passage improves its rank by not matching.
        return math.log(1.0 + (total - seen + 0.5) / (seen + 0.5))

    def search(self, query: str, limit: int) -> list[Retrieved]:
        terms = tokenize(query)
        if not terms or not self._docs:
            return []
        scored: list[tuple[float, int]] = []
        for index, frequency in enumerate(self._frequencies):
            length = len(self._docs[index])
            score = 0.0
            for term in terms:
                count = frequency.get(term, 0)
                if not count:
                    continue
                denominator = count + K1 * (
                    1 - B + B * (length / self._average_length if self._average_length else 1)
                )
                score += self._idf(term) * (count * (K1 + 1)) / denominator
            if score > 0:
                scored.append((score, index))
        scored.sort(key=lambda row: (-row[0], row[1]))
        return [
            Retrieved(passage=self.passages[i], score=s, rank=rank)
            for rank, (s, i) in enumerate(scored[:limit])
        ]


class Embedder(Protocol):
    """Turn texts into vectors. The seam a neural model would plug into."""

    name: str

    def fit_transform(self, texts: list[str]) -> np.ndarray: ...
    def transform(self, texts: list[str]) -> np.ndarray: ...


class LsaEmbedder:
    """TF-IDF reduced by truncated SVD, L2-normalised.

    Fitted on the section's own passages. That is a small corpus for an SVD and
    it is the honest constraint: there is no pretrained anything here, so the
    only statistics available are the document's own. It buys synonym tolerance
    within the filing's vocabulary -- "suppliers" and "supplier concentration"
    land near each other -- and nothing at all outside it.
    """

    name = "lsa"

    def __init__(self, components: int = 128, seed: int = 0) -> None:
        self.components = components
        self.seed = seed
        self._vectorizer = None
        self._svd = None

    def fit_transform(self, texts: list[str]) -> np.ndarray:
        from sklearn.decomposition import TruncatedSVD
        from sklearn.feature_extraction.text import TfidfVectorizer

        self._vectorizer = TfidfVectorizer(
            lowercase=True,
            ngram_range=(1, 2),
            min_df=1,
            sublinear_tf=True,
            stop_words=sorted(STOPWORDS),
        )
        matrix = self._vectorizer.fit_transform(texts)
        # SVD cannot produce more components than the matrix has dimensions.
        components = max(1, min(self.components, min(matrix.shape) - 1))
        self._svd = TruncatedSVD(n_components=components, random_state=self.seed)
        return _normalise(self._svd.fit_transform(matrix))

    def transform(self, texts: list[str]) -> np.ndarray:
        if self._vectorizer is None or self._svd is None:
            raise RuntimeError("fit_transform must be called before transform")
        return _normalise(self._svd.transform(self._vectorizer.transform(texts)))


def _normalise(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    # A passage whose vector is all zeros -- no term survived the vocabulary --
    # would otherwise divide by zero and come back NaN, which sorts randomly.
    norms[norms == 0] = 1.0
    return matrix / norms


@dataclass
class SemanticRetriever:
    """Cosine similarity in the embedder's space."""

    passages: list[Passage]
    embedder: Embedder = field(default_factory=LsaEmbedder)
    name: str = "lsa"
    _vectors: np.ndarray | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.passages:
            self._vectors = self.embedder.fit_transform([p.text for p in self.passages])
        self.name = self.embedder.name

    def search(self, query: str, limit: int) -> list[Retrieved]:
        if self._vectors is None or not query.strip():
            return []
        similarity = (self._vectors @ self.embedder.transform([query])[0]).ravel()
        order = np.argsort(-similarity)[:limit]
        return [
            Retrieved(passage=self.passages[int(i)], score=float(similarity[int(i)]), rank=rank)
            for rank, i in enumerate(order)
            if similarity[int(i)] > 0
        ]


@dataclass
class HybridRetriever:
    """Reciprocal rank fusion of a lexical and a semantic retriever."""

    passages: list[Passage]
    name: str = "hybrid"
    _lexical: LexicalRetriever = field(init=False, repr=False)
    _semantic: SemanticRetriever = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._lexical = LexicalRetriever(self.passages)
        self._semantic = SemanticRetriever(self.passages)

    def search(self, query: str, limit: int) -> list[Retrieved]:
        # Fuse over a deeper slice than is returned: a passage ranked eighth by
        # both retrievers should be able to beat one ranked first by neither.
        depth = max(limit * 4, 20)
        fused: dict[int, float] = {}
        holder: dict[int, Passage] = {}
        for retriever in (self._lexical, self._semantic):
            for hit in retriever.search(query, depth):
                fused[hit.passage.index] = fused.get(hit.passage.index, 0.0) + 1.0 / (
                    RRF_K + hit.rank + 1
                )
                holder[hit.passage.index] = hit.passage
        order = sorted(fused.items(), key=lambda kv: (-kv[1], kv[0]))
        return [
            Retrieved(passage=holder[index], score=score, rank=rank)
            for rank, (index, score) in enumerate(order[:limit])
        ]


STRATEGIES = ("truncation", "bm25", "lsa", "hybrid")


def build_retriever(strategy: str, text: str, **chunk_kwargs: int) -> Retriever:
    """Chunk a section and wrap it in the named strategy."""
    if strategy not in STRATEGIES:
        raise ValueError(f"unknown strategy {strategy!r}; choose from {list(STRATEGIES)}")
    passages = chunk_section(text, **chunk_kwargs)
    if strategy == "truncation":
        return TruncationRetriever(passages)
    if strategy == "bm25":
        return LexicalRetriever(passages)
    if strategy == "lsa":
        return SemanticRetriever(passages)
    return HybridRetriever(passages)
