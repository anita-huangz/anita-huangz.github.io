"""Plain English to a validated strategy configuration, without a model.

"a factor-neutral 1s2s5s fly since 2010, rebalanced weekly, 1bp costs" is a
complete specification, and reading it takes keyword matching rather than a
language model. The value is not the parsing -- it is that the parse produces
a `Strategy`, every field of which is range-checked, and the engine downstream
only ever sees the validated object. Execution stays deterministic no matter
how the request was phrased.

That boundary is the point of doing it this way. If a model layer is added
later it maps text to the *same* validated object, so the worst a bad
completion can do is fail validation. It cannot invent a tenor, a negative
cost, or a rebalance period of zero days, because `Strategy.validated` refuses
all three before anything is priced.

Where two phrasings conflict -- "a dv01-neutral factor-neutral fly" -- the one
that appears later in the sentence wins, because that is how people correct
themselves mid-thought. Resolving by dictionary order instead makes "jazzy but
gentle" and "gentle but jazzy" the same request, which is a bug this codebase
has already shipped once elsewhere.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from .data import TENORS

#: Spoken tenor -> FRED series. Longest keys first when matching, so "3 month"
#: does not match as "3" year.
TENOR_WORDS: dict[str, str] = {
    "3 month": "DGS3MO", "3m": "DGS3MO", "0.25y": "DGS3MO",
    "6 month": "DGS6MO", "6m": "DGS6MO", "0.5y": "DGS6MO",
    "1 year": "DGS1", "1y": "DGS1", "1s": "DGS1",
    "2 year": "DGS2", "2y": "DGS2", "2s": "DGS2",
    "3 year": "DGS3", "3y": "DGS3", "3s": "DGS3",
    "5 year": "DGS5", "5y": "DGS5", "5s": "DGS5",
    "7 year": "DGS7", "7y": "DGS7", "7s": "DGS7",
    "10 year": "DGS10", "10y": "DGS10", "10s": "DGS10",
    "30 year": "DGS30", "30y": "DGS30", "30s": "DGS30",
}

#: "2s5s10s" and friends: three tenors run together. Matched against the text
#: with its spaces intact -- stripping them first destroys the word boundaries
#: these rely on, and "neutral1s2s5s" then matches nothing at all.
FLY_PATTERN = re.compile(r"\b(\d+(?:\.\d+)?)s(\d+(?:\.\d+)?)s(\d+(?:\.\d+)?)s\b")

#: "2s10s" -- a spread, not a butterfly. Recognised so it can be refused with
#: a useful message rather than silently running the default fly.
SPREAD_PATTERN = re.compile(r"\b(\d+(?:\.\d+)?)s(\d+(?:\.\d+)?)s\b")

WEIGHTING_WORDS = {
    "dv01": ("dv01", "duration-neutral", "duration neutral", "textbook", "equal"),
    "factor": ("factor-neutral", "factor neutral", "pca", "pca-weighted", "regression"),
}

REBALANCE_WORDS = {"daily": 1, "weekly": 5, "fortnightly": 10, "monthly": 21, "quarterly": 63}

DEFAULT_WINGS = ("DGS2", "DGS10")
DEFAULT_BELLY = "DGS5"


class IntentError(ValueError):
    """The request was read, and what it asked for is not a runnable strategy."""


@dataclass(frozen=True)
class Strategy:
    """A validated, runnable specification. Nothing downstream re-checks it."""

    wings: tuple[str, str] = DEFAULT_WINGS
    belly: str = DEFAULT_BELLY
    weighting: str = "dv01"
    rebalance_days: int = 21
    cost_bp: float = 0.5
    start: str | None = None
    end: str | None = None

    def validated(self) -> Strategy:
        for tenor in (*self.wings, self.belly):
            if tenor not in TENORS:
                raise IntentError(f"unknown tenor {tenor!r}; choose from {sorted(TENORS)}")
        short, long = self.wings
        maturities = (TENORS[short], TENORS[self.belly], TENORS[long])
        if not maturities[0] < maturities[1] < maturities[2]:
            raise IntentError(
                f"a butterfly needs the belly between its wings; got "
                f"{maturities[0]:g}y / {maturities[1]:g}y / {maturities[2]:g}y"
            )
        if self.weighting not in WEIGHTING_WORDS:
            raise IntentError(
                f"unknown weighting {self.weighting!r}; choose {sorted(WEIGHTING_WORDS)}"
            )
        if not 1 <= self.rebalance_days <= 252:
            raise IntentError(
                f"rebalance_days must be between 1 and 252; got {self.rebalance_days}"
            )
        if not 0.0 <= self.cost_bp <= 25.0:
            raise IntentError(
                f"cost_bp must be between 0 and 25; got {self.cost_bp}. A half-spread "
                "above 25bp is not a Treasury market."
            )
        return self

    def describe(self) -> str:
        span = f"{self.start or 'the start'} to {self.end or 'today'}"
        return (
            f"{_label(self.wings[0])}{_label(self.belly)}{_label(self.wings[1])} "
            f"{self.weighting}-neutral, rebalanced every {self.rebalance_days}d, "
            f"{self.cost_bp:g}bp costs, {span}"
        )


def _label(tenor: str) -> str:
    years = TENORS[tenor]
    return f"{years:g}m" if years < 1 else f"{years:g}s"


def _last_match(text: str, options: dict[str, tuple[str, ...]]) -> str | None:
    """Whichever option's keyword appears latest in the sentence."""
    best_position, best_key = -1, None
    for key, words in options.items():
        for word in words:
            position = text.rfind(word)
            if position > best_position:
                best_position, best_key = position, key
    return best_key


def _tenors_in(text: str) -> list[str]:
    """Every tenor named, in the order they were said."""
    found: list[tuple[int, str]] = []
    for word in sorted(TENOR_WORDS, key=len, reverse=True):
        for match in re.finditer(rf"(?<![\w.]){re.escape(word)}(?![\w])", text):
            if not any(abs(match.start() - p) < len(word) for p, _ in found):
                found.append((match.start(), TENOR_WORDS[word]))
    return [tenor for _, tenor in sorted(found)]


def parse(text: str, default: Strategy | None = None) -> Strategy:
    """Read a request. Unmentioned settings keep their default."""
    lowered = text.lower().strip()
    if not lowered:
        raise IntentError("nothing to read")
    strategy = default or Strategy()

    if fly := FLY_PATTERN.search(lowered):
        legs = [f"{g}s" for g in fly.groups()]
        tenors = [TENOR_WORDS[leg] for leg in legs if leg in TENOR_WORDS]
        if len(tenors) != 3:
            unknown = [leg for leg in legs if leg not in TENOR_WORDS]
            raise IntentError(
                f"'{fly.group(0)}' names {unknown}, which this curve does not carry; "
                f"available tenors: {sorted(TENORS)}"
            )
    elif spread := SPREAD_PATTERN.search(lowered):
        raise IntentError(
            f"'{spread.group(0)}' is a two-leg spread and this runs butterflies. "
            "Name three legs, e.g. 1s2s5s."
        )
    else:
        tenors = _tenors_in(lowered)

    if len(tenors) >= 3:
        strategy = replace(strategy, wings=(tenors[0], tenors[2]), belly=tenors[1])
    elif len(tenors) in (1, 2):
        raise IntentError(
            f"a butterfly needs three tenors; found {len(tenors)} in {text!r}. "
            "Write it as 2s5s10s, or name all three."
        )

    if weighting := _last_match(lowered, WEIGHTING_WORDS):
        strategy = replace(strategy, weighting=weighting)

    for word, days in REBALANCE_WORDS.items():
        if word in lowered:
            strategy = replace(strategy, rebalance_days=days)
    # `days?` before the bare `d`: "every 3 days" ends in a plural, and a
    # trailing \b after "day" fails against the "s" that follows it.
    if match := re.search(r"every\s+(\d+)\s*(?:days?|d)\b", lowered):
        strategy = replace(strategy, rebalance_days=int(match.group(1)))

    if match := re.search(r"(\d+(?:\.\d+)?)\s*bp", lowered):
        strategy = replace(strategy, cost_bp=float(match.group(1)))
    if "no cost" in lowered or "zero cost" in lowered or "frictionless" in lowered:
        strategy = replace(strategy, cost_bp=0.0)

    if match := re.search(r"(?:since|from|after)\s+(\d{4})(?:-(\d{2})-(\d{2}))?", lowered):
        year, month, day = match.groups()
        strategy = replace(strategy, start=f"{year}-{month or '01'}-{day or '01'}")
    if match := re.search(r"(?:until|before|through|to)\s+(\d{4})(?:-(\d{2})-(\d{2}))?", lowered):
        year, month, day = match.groups()
        strategy = replace(strategy, end=f"{year}-{month or '12'}-{day or '31'}")

    return strategy.validated()
