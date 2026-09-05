"""Similarity scoring.

One rational family throughout: s = 1 / (1 + (delta / tau)^2). It decays
gently near the target and keeps a long tolerant tail, which is what
"similarity finder, not filter" means in practice.
"""

from __future__ import annotations

from har_search.core.models import PropertyType

# (tau_over, tau_under) per target parameter, in that parameter's own units.
TAU: dict[str, tuple[float, float]] = {
    "beds": (2.4, 0.82),
    "baths": (2.4, 0.82),
    "garage_spaces": (1.8, 0.75),
    "sqft": (1400.0, 520.0),
    "max_age_years": (14.0, 40.0),
}

CEILING_TAU = 0.16
GEO_TAU_MILES = 3.0

DEFAULT_WEIGHTS: dict[str, float] = {
    "area": 3.0,
    "max_price": 3.0,
    "beds": 2.0,
    "sqft": 1.5,
    "baths": 1.5,
    "property_types": 1.5,
    "max_price_per_sqft": 1.5,
    "garage_spaces": 1.0,
    "max_age_years": 1.0,
    "no_hoa": 1.0,
    "min_school_rating": 1.0,
}

_MULTI_FAMILY_FAMILY = {
    PropertyType.DUPLEX,
    PropertyType.FOURPLEX,
    PropertyType.MULTI_FAMILY,
}


def _rational(delta: float, tau: float) -> float:
    if tau <= 0:
        return 1.0 if delta == 0 else 0.0
    return 1.0 / (1.0 + (delta / tau) ** 2)


def target_score(actual: float, target: float, tau_over: float, tau_under: float) -> float:
    """Overshooting a target is cheap; undershooting it is not."""
    delta = actual - target
    tau = tau_over if delta >= 0 else tau_under
    return _rational(abs(delta), tau)


def ceiling_score(actual: float, ceiling: float, tau: float = CEILING_TAU) -> float:
    """At or under the ceiling is perfect; over it decays."""
    if ceiling <= 0:
        return 0.0
    if actual <= ceiling:
        return 1.0
    over = (actual - ceiling) / ceiling
    return _rational(over, tau)


def geo_score(subdivision_match: bool, miles: float | None) -> float:
    if subdivision_match:
        return 1.0
    if miles is None:
        return 0.0
    return _rational(miles, GEO_TAU_MILES)


def categorical_score(
    actual: PropertyType | None, wanted: list[PropertyType]
) -> float:
    if actual is None or not wanted:
        return 0.0
    if actual in wanted:
        return 1.0
    if actual in _MULTI_FAMILY_FAMILY and any(w in _MULTI_FAMILY_FAMILY for w in wanted):
        return 0.5
    return 0.0
