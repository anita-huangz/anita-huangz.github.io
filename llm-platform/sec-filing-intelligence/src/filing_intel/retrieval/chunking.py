"""Splitting a filing section into passages that can be ranked.

Two properties matter more than the chunk size.

**Sentence boundaries.** A chunk cut mid-sentence retrieves badly and reads
worse: the model is handed half a clause and has to guess the rest. Splitting
on sentence ends costs nothing and avoids it.

**Character offsets.** Every passage carries where it came from, so a citation
can point at a position in the filing rather than at "somewhere in the text we
sent". The verifier downstream checks claims against evidence; evidence with no
location is weaker evidence.

Overlap exists because a fact can straddle a boundary -- a risk named in one
sentence and quantified in the next. Without it, whichever chunk the split
lands in gets half the answer. It costs duplicated text in exchange for not
losing the pair, which is the right trade at this scale.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Roughly 200 tokens. Small enough that a hit is specific, large enough that a
#: risk factor's heading and its explanation usually stay together.
DEFAULT_CHUNK_CHARS = 900
DEFAULT_OVERLAP_CHARS = 150

#: A sentence end: terminal punctuation, then whitespace, then something that
#: starts a sentence. Abbreviations like "U.S." keep their following token
#: lowercase or capitalised mid-clause, which this mostly survives; filings are
#: formal prose and the failure mode is a slightly long chunk, not a wrong one.
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\"'])")


@dataclass(frozen=True)
class Passage:
    """One retrievable span of a section, and where it sits in it."""

    text: str
    start: int
    end: int
    index: int

    @property
    def length(self) -> int:
        return self.end - self.start

    def preview(self, limit: int = 120) -> str:
        flat = " ".join(self.text.split())
        return flat if len(flat) <= limit else f"{flat[: limit - 1]}…"


def sentences(text: str) -> list[tuple[str, int]]:
    """Sentences with their start offsets, in document order."""
    out: list[tuple[str, int]] = []
    position = 0
    for piece in _SENTENCE_END.split(text):
        if not piece:
            continue
        found = text.find(piece, position)
        start = found if found >= 0 else position
        out.append((piece, start))
        position = start + len(piece)
    return out


def chunk_section(
    text: str,
    chunk_chars: int = DEFAULT_CHUNK_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> list[Passage]:
    """Split a section into overlapping, sentence-aligned passages."""
    if chunk_chars <= 0:
        raise ValueError("chunk_chars must be positive")
    if not 0 <= overlap_chars < chunk_chars:
        raise ValueError("overlap_chars must be non-negative and smaller than chunk_chars")

    stripped = text.strip()
    if not stripped:
        return []

    pieces = sentences(text)
    if not pieces:
        return []

    passages: list[Passage] = []
    current: list[tuple[str, int]] = []
    size = 0

    def flush() -> None:
        if not current:
            return
        start = current[0][1]
        end = current[-1][1] + len(current[-1][0])
        body = text[start:end].strip()
        if body:
            passages.append(Passage(text=body, start=start, end=end, index=len(passages)))

    for sentence, start in pieces:
        # A single sentence longer than the target becomes its own passage
        # rather than being cut: filings contain 1,200-character sentences and
        # splitting one mid-clause is worse than an oversized chunk.
        if size and size + len(sentence) > chunk_chars:
            flush()
            keep: list[tuple[str, int]] = []
            kept = 0
            for piece in reversed(current):
                if kept + len(piece[0]) > overlap_chars:
                    break
                keep.insert(0, piece)
                kept += len(piece[0])
            current = keep
            size = kept
        current.append((sentence, start))
        size += len(sentence)

    flush()
    return passages
