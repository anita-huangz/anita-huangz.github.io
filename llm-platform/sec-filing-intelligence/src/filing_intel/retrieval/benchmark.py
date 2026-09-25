"""Does retrieval actually beat truncating the front of the section?

The claim a retrieval layer has to earn is not "semantic search is good". It is
that it puts the *answer* in front of the model more often than the thing it
replaces, which here is `text[:20000]`.

**The ground truth.** Each case names a query and an `anchor` -- a phrase that
appears in the passage answering it. A retrieval is correct when a returned
passage contains the anchor. That is objective and recheckable: the anchor is
in the committed fixture, at a known offset, and anyone can grep for it. It is
also a *weaker* notion of correct than "the model answered well", which is the
honest limit of what can be measured without a labelled answer set.

**Every target sits past character 20,000**, deliberately. That is the half of
the question truncation cannot answer at any quality, and it is where a
retrieval layer either earns its place or does not.

**The queries avoid the anchor's own wording** where a natural paraphrase
exists -- "returning cash to shareholders" for a passage about dividends -- so
the lexical retriever is not simply handed the answer. Where no natural
paraphrase exists the overlap is left, because inventing awkward phrasing to
handicap BM25 would be rigging the comparison in the other direction.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .retrievers import STRATEGIES, build_retriever

FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "tests" / "fixtures" / "sections" / "risk_factors.json"
)

#: The truncation the tool applies today, and the point every target sits past.
TRUNCATION_CHARS = 20_000


@dataclass(frozen=True)
class Case:
    ticker: str
    query: str
    #: Verifiable in the fixture: a passage containing this answers the query.
    anchor: str


CASES: tuple[Case, ...] = (
    # Authored by reading the passage first and then writing the question it
    # answers. Doing it the other way round -- picking a topic and grepping for
    # a word -- produced a set where "government contract" matched a passage
    # about litigation and "climate" one about a pandemic, and every retriever
    # scored zero on Microsoft for reasons that were the benchmark's fault.
    Case("AAPL", "What could stop the company returning cash to shareholders?", "dividend"),
    Case("AAPL", "What competition-law exposure does the company describe?", "antitrust"),
    Case("AAPL", "How might new European platform rules affect the commission on app sales?",
         "Digital Markets Act"),
    Case("AAPL", "Is the company exposed to movements in currency markets?", "foreign exchange"),
    Case("MSFT", "What could go wrong with how the company builds and ships AI features?",
         "AI-based solutions"),
    Case("MSFT", "What might slow down the build-out of new capacity?", "wage inflation"),
    Case("MSFT", "What happens when a defect escapes testing before release?",
         "pre-release testing"),
    Case("MSFT", "How do import duties and trade policy affect the business?", "tariffs"),
    Case("NVDA", "Is the business concentrated in particular places?", "California"),
    Case("NVDA", "What is the exposure from stakes held in young private companies?",
         "non-marketable"),
    Case("NVDA", "What if a flaw is found in the company's internal financial controls?",
         "material weakness"),
    Case("NVDA", "How does demand from cryptocurrency mining affect the business?", "Ethereum"),
)


@dataclass(frozen=True)
class Score:
    strategy: str
    hits: int
    total: int
    #: Average rank of the first correct passage, over the cases it found.
    mean_rank: float

    @property
    def recall(self) -> float:
        return self.hits / self.total if self.total else 0.0

    def describe(self) -> str:
        rank = f"{self.mean_rank:.1f}" if self.hits else "—"
        return (
            f"{self.strategy:<11} recall@k {self.recall:>6.1%} "
            f"({self.hits}/{self.total})   mean rank of the hit {rank}"
        )


def load_sections(path: Path | None = None) -> dict[str, str]:
    data = json.loads((path or FIXTURE).read_text())
    return {ticker: filing["text"] for ticker, filing in data.items()}


def reach(sections: dict[str, str]) -> dict[str, float]:
    """Share of each section truncation can see at all."""
    return {t: min(1.0, TRUNCATION_CHARS / len(text)) for t, text in sections.items()}


def run(limit: int = 5, sections: dict[str, str] | None = None) -> list[Score]:
    """Score every strategy over every case."""
    texts = sections if sections is not None else load_sections()
    scores: list[Score] = []
    for strategy in STRATEGIES:
        hits = 0
        ranks: list[int] = []
        for case in CASES:
            retriever = build_retriever(strategy, texts[case.ticker])
            found = [
                i
                for i, r in enumerate(retriever.search(case.query, limit))
                if case.anchor.lower() in r.text.lower()
            ]
            if found:
                hits += 1
                ranks.append(found[0] + 1)
        scores.append(
            Score(
                strategy=strategy,
                hits=hits,
                total=len(CASES),
                mean_rank=sum(ranks) / len(ranks) if ranks else 0.0,
            )
        )
    return scores


def report(limit: int = 5) -> str:
    sections = load_sections()
    lines = [
        f"{len(CASES)} queries over {len(sections)} real 10-K risk-factor sections, "
        f"top {limit} passages each.",
        "Every target sits past character 20,000, which is where the tool truncates.",
        "",
    ]
    lines += [f"  {t}: {len(text):>7,} chars, truncation sees {share:>4.0%}"
              for (t, text), share in zip(sections.items(), reach(sections).values(), strict=True)]
    lines.append("")
    lines += [f"  {score.describe()}" for score in run(limit, sections)]
    return "\n".join(lines)


if __name__ == "__main__":  # pragma: no cover
    print(report())
