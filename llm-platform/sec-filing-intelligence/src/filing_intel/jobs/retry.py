"""Which failures are worth retrying, and how long to wait.

Retrying everything is as wrong as retrying nothing. A 503 from EDGAR will
probably succeed in four seconds; a malformed ticker will fail identically
three times and delay the caller's error by the whole backoff. The taxonomy in
`errors.py` already separates them, so this classifies against it rather than
against exception strings.

Backoff is exponential with full jitter. Without jitter, every job that failed
during a ten-second upstream outage retries at the same instant afterwards,
which is how a recovering dependency gets knocked over by its own clients.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from ..errors import (
    ConfigError,
    FilingIntelError,
    ProviderRefusal,
    ReplayMiss,
    ToolInputInvalid,
    ToolNotPermitted,
)

#: Failures that will fail again in exactly the same way. Retrying them costs
#: the caller latency and the platform money, and changes nothing.
PERMANENT: tuple[type[Exception], ...] = (
    ConfigError,
    ProviderRefusal,
    ReplayMiss,
    ToolInputInvalid,
    ToolNotPermitted,
    ValueError,
)


def is_transient(error: BaseException) -> bool:
    """Is this worth trying again?

    Unknown exceptions count as transient. That is the deliberate direction to
    be wrong in: a retried permanent failure wastes one extra attempt, while a
    non-retried transient failure loses the job.
    """
    return not isinstance(error, PERMANENT)


def error_kind(error: BaseException) -> str:
    return getattr(error, "kind", None) or type(error).__name__


@dataclass(frozen=True)
class RetryPolicy:
    """Exponential backoff with full jitter."""

    base_seconds: float = 1.0
    max_seconds: float = 60.0
    multiplier: float = 2.0

    def __post_init__(self) -> None:
        if self.base_seconds <= 0:
            raise ValueError("base_seconds must be positive")
        if self.max_seconds < self.base_seconds:
            raise ValueError("max_seconds cannot be below base_seconds")
        if self.multiplier < 1:
            raise ValueError("multiplier below 1 would shorten each successive wait")

    def delay(self, attempt: int, rng: random.Random | None = None) -> float:
        """Seconds to wait before attempt number `attempt` (1-based).

        Full jitter: a uniform draw from [0, ceiling] rather than the ceiling
        itself. Equal-jitter and decorrelated variants exist; full jitter is
        the one that spreads a thundering herd widest, which is the failure
        being defended against.
        """
        if attempt < 1:
            raise ValueError("attempt is 1-based")
        ceiling = min(self.max_seconds, self.base_seconds * self.multiplier ** (attempt - 1))
        return (rng or random).uniform(0.0, ceiling)


def describe(error: BaseException) -> str:
    """A one-line reason safe to hand back to a caller.

    Deliberately the exception's own message and nothing else -- no traceback,
    no module paths. A job that failed should tell the caller what went wrong
    without narrating the server's internals.
    """
    message = str(error).strip() or type(error).__name__
    if isinstance(error, FilingIntelError):
        return message
    # An unexpected exception's message can carry anything; name the type and
    # keep the text short rather than leaking a stack of internal detail.
    return f"{type(error).__name__}: {message[:200]}"
