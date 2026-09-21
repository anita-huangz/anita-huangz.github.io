"""Are there cycles in the curve factors? An FFT, and a null to read it against.

Rates have no reason to be seasonal the way electricity demand or retail sales
are, but "no reason to be" is not evidence, and the cost of being wrong is a
model missing a periodic term it should have had. So the question gets asked
properly: take the periodogram of each factor's daily scores and compare its
peaks against what white noise of the same length and variance produces.

The comparison matters because a periodogram of pure noise is not flat. It is
exponentially distributed around the mean power, so the largest of a few
thousand bins is several times the mean *by construction*. Reading the tallest
spike off a periodogram and calling it a cycle is the standard way to find a
business cycle in a random walk.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

TRADING_DAYS = 252


@dataclass(frozen=True)
class Periodogram:
    """Spectral power by period, with the noise threshold it has to clear."""

    factor: str
    period_days: np.ndarray
    power: np.ndarray
    threshold: float
    draws: int
    #: How many factors were tested together. The threshold is already
    #: corrected for it; this is kept so the caller can report it.
    family_size: int = 1

    @property
    def peak_period(self) -> float:
        return float(self.period_days[int(np.argmax(self.power))])

    @property
    def peak_power(self) -> float:
        return float(self.power.max())

    @property
    def has_cycle(self) -> bool:
        return bool(self.peak_power > self.threshold)

    @property
    def margin(self) -> float:
        """How far above the threshold the peak sits. Near zero means near nothing."""
        return self.peak_power - self.threshold

    def describe(self) -> str:
        verdict = (
            f"a {self.peak_period:.0f}-day cycle clears it"
            if self.has_cycle
            else "nothing clears it"
        )
        if self.has_cycle and self.margin < 0.5:
            verdict += ", but only just -- do not trade it"
        family = f", corrected for {self.family_size} tests" if self.family_size > 1 else ""
        return (
            f"{self.factor}: strongest period {self.peak_period:.0f} days, power "
            f"{self.peak_power:.2f} against a noise threshold of "
            f"{self.threshold:.2f}{family} -- {verdict}"
        )


def periodogram(
    scores: pd.Series,
    draws: int = 200,
    seed: int = 0,
    min_period: float = 2.0,
    family_size: int = 1,
) -> Periodogram:
    """Power spectrum of a factor score, against a white-noise threshold.

    The threshold is a high quantile of the *maximum* power seen across
    `draws` white-noise series of the same length -- the maximum, not the
    mean, because the question is whether the tallest observed peak is
    surprising, and testing a maximum against a mean is how noise becomes a
    finding.

    `family_size` is the number of series being examined together. Looking at
    three factors at the 95th percentile gives roughly a one-in-seven chance
    of a spurious cycle somewhere, so the quantile is raised to 1 - 0.05/k.
    Both peaks this finds on the Treasury factors are close enough to the
    line that the correction changes whether they count.
    """
    if family_size < 1:
        raise ValueError("family_size must be at least 1")
    values = scores.dropna().to_numpy(dtype=float)
    if len(values) < 16:
        raise ValueError("too few observations for a meaningful spectrum")
    values = values - values.mean()

    def power_of(series: np.ndarray) -> np.ndarray:
        spectrum = np.abs(np.fft.rfft(series)) ** 2
        # Drop the zero frequency: it is the mean, which has been removed.
        return spectrum[1:] / spectrum[1:].mean()

    frequencies = np.fft.rfftfreq(len(values), d=1.0)[1:]
    periods = 1.0 / frequencies
    keep = periods >= min_period
    observed = power_of(values)[keep]

    rng = np.random.default_rng(seed)
    maxima = np.empty(draws)
    for draw in range(draws):
        noise = rng.normal(0.0, values.std(), size=len(values))
        maxima[draw] = power_of(noise)[keep].max()

    return Periodogram(
        factor=str(scores.name),
        period_days=periods[keep],
        power=observed,
        threshold=float(np.quantile(maxima, 1.0 - 0.05 / family_size)),
        draws=draws,
        family_size=family_size,
    )
