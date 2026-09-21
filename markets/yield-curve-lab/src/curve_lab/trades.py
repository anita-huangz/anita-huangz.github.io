"""Curve trades, and the difference between two ways of weighting them.

A butterfly is meant to be a bet on *curvature* -- on the belly of the curve
moving relative to its wings -- and nothing else. The textbook construction is
to weight the legs so the position has no net DV01: sell the belly, buy the two
wings, size them so a parallel shift in yields nets out.

That makes the trade neutral to a *parallel* shift. The curve does not move in
parallel shifts. It moves in the shapes `pca.py` recovers, and the first of
those is not quite parallel -- it is flatter at the very short end and rolls
off at the long end. A DV01-neutral fly is therefore only approximately
neutral to it, and it is not remotely neutral to the second shape, slope.

`residual_risk` measures exactly how much: what share of a fly's P&L variance
comes from the factors it is supposed to be immune to. The alternative is to
solve for weights that zero the factor exposures directly, which is what
`factor_neutral_weights` does, and then the same measurement says how much
better that is.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .data import TENORS
from .pca import CurveFactors

#: US Treasury coupons pay twice a year.
COUPONS_PER_YEAR = 2
#: A basis point, as a decimal.
BP = 1e-4


def par_bond_dv01(yield_pct: float, maturity_years: float, face: float = 100.0) -> float:
    """Price change per basis point for a bond trading at par, per `face`.

    Computed from the cash flows rather than a closed form: the closed form
    for a par bond is easy to misremember, and the discounted flows are what
    it is approximating anyway. Under half a year there are no coupons left,
    so it is a bill and the simple-interest convention applies.
    """
    if maturity_years <= 0:
        raise ValueError("maturity must be positive")
    y = yield_pct / 100.0

    if maturity_years < 1.0 / COUPONS_PER_YEAR:
        # Money-market bill: one payment, simple discount.
        modified_duration = maturity_years / (1.0 + y * maturity_years)
        return modified_duration * face * BP

    periods = round(maturity_years * COUPONS_PER_YEAR)
    periodic_yield = y / COUPONS_PER_YEAR
    times = np.arange(1, periods + 1) / COUPONS_PER_YEAR
    # At par the coupon rate equals the yield, so the price comes back to face.
    flows = np.full(periods, face * periodic_yield)
    flows[-1] += face

    discounts = (1.0 + periodic_yield) ** (-np.arange(1, periods + 1))
    price = float(flows @ discounts)
    macaulay = float((times * flows) @ discounts) / price
    modified_duration = macaulay / (1.0 + periodic_yield)
    return modified_duration * price * BP


@dataclass(frozen=True)
class Butterfly:
    """A three-leg curve trade, as a DV01 weight per tenor.

    `weights` is expressed in the same order as the fitted factors' tenors, so
    it can be handed straight to `CurveFactors.exposure`. Positive means long
    the bond (gains when its yield falls).
    """

    tenors: tuple[str, ...]
    weights: np.ndarray
    wings: tuple[str, str]
    belly: str
    label: str

    @property
    def net_dv01(self) -> float:
        return float(self.weights.sum())

    def leg(self, tenor: str) -> float:
        return float(self.weights[self.tenors.index(tenor)])


def _blank(tenors: tuple[str, ...]) -> np.ndarray:
    return np.zeros(len(tenors), dtype=float)


def dv01_neutral_weights(
    tenors: tuple[str, ...], wings: tuple[str, str], belly: str
) -> Butterfly:
    """The textbook fly: short the belly, long each wing at half its DV01.

    Weights are in DV01 units directly, so "half the belly's DV01 in each
    wing" is +0.5 / -1 / +0.5 and the net is zero by construction.
    """
    for tenor in (*wings, belly):
        if tenor not in tenors:
            raise KeyError(f"no tenor {tenor!r} in the fitted curve; have {list(tenors)}")

    weights = _blank(tenors)
    weights[tenors.index(belly)] = -1.0
    for wing in wings:
        weights[tenors.index(wing)] = 0.5
    short, long = wings
    return Butterfly(
        tenors=tenors,
        weights=weights,
        wings=wings,
        belly=belly,
        label=f"{_short(short)}{_short(belly)}{_short(long)} DV01-neutral",
    )


def factor_neutral_weights(
    factors: CurveFactors,
    wings: tuple[str, str],
    belly: str,
    neutral_to: tuple[int, ...] = (0, 1),
) -> Butterfly:
    """Wing weights solved so the fly carries no level or slope exposure.

    The belly is fixed at -1 DV01 and the two wings are the unknowns, which
    makes two equations in two unknowns: one per factor being neutralised.
    Neutralising *three* factors with two wings is not possible, and asking
    for it raises rather than silently least-squaring the answer.
    """
    tenors = factors.tenors
    for tenor in (*wings, belly):
        if tenor not in tenors:
            raise KeyError(f"no tenor {tenor!r} in the fitted curve; have {list(tenors)}")
    if len(neutral_to) != len(wings):
        raise ValueError(
            f"two wings can neutralise exactly two factors, not {len(neutral_to)}"
        )

    belly_index = tenors.index(belly)
    wing_indices = [tenors.index(w) for w in wings]

    # loadings[f, wing] @ x = loadings[f, belly] for each factor f being killed
    matrix = np.array([[factors.loadings[f, i] for i in wing_indices] for f in neutral_to])
    target = np.array([factors.loadings[f, belly_index] for f in neutral_to])
    if abs(np.linalg.det(matrix)) < 1e-12:
        raise ValueError(
            f"wings {wings} load almost identically on factors {neutral_to}; "
            "the weights are not identified. Move a wing."
        )
    solved = np.linalg.solve(matrix, target)

    weights = _blank(tenors)
    weights[belly_index] = -1.0
    for index, value in zip(wing_indices, solved, strict=True):
        weights[index] = float(value)
    short, long = wings
    return Butterfly(
        tenors=tenors,
        weights=weights,
        wings=wings,
        belly=belly,
        label=f"{_short(short)}{_short(belly)}{_short(long)} factor-neutral",
    )


def _short(tenor: str) -> str:
    years = TENORS[tenor]
    return f"{years:g}m" if years < 1 else f"{years:g}s"


@dataclass(frozen=True)
class ResidualRisk:
    """How much of a trade's risk is in factors it claims not to hold."""

    label: str
    exposure: np.ndarray
    variance_share: np.ndarray
    factor_names: tuple[str, ...]

    @property
    def unintended_share(self) -> float:
        """Share of P&L variance from everything except the last factor named."""
        return float(self.variance_share[:-1].sum())

    def describe(self) -> str:
        parts = ", ".join(
            f"{name} {share:.1%}"
            for name, share in zip(self.factor_names, self.variance_share, strict=True)
        )
        return f"{self.label}: {parts}"


def residual_risk(
    butterfly: Butterfly, factors: CurveFactors, variances: np.ndarray
) -> ResidualRisk:
    """Decompose a trade's P&L variance across the curve factors.

    The factors are uncorrelated by construction, so the variance contributed
    by each one is its exposure squared times its own variance, and the shares
    add to one without a cross term to argue about.
    """
    exposure = factors.exposure(butterfly.weights)
    contributions = (exposure**2) * np.asarray(variances, dtype=float)
    total = contributions.sum()
    if total <= 0:
        raise ValueError("this trade has no factor risk at all, which cannot be right")
    return ResidualRisk(
        label=butterfly.label,
        exposure=exposure,
        variance_share=contributions / total,
        factor_names=tuple(factors.name(i) for i in range(factors.n_components)),
    )
