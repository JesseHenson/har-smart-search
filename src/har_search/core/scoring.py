"""Similarity scoring.

One rational family throughout: s = 1 / (1 + (delta / tau)^2). It decays
gently near the target and keeps a long tolerant tail, which is what
"similarity finder, not filter" means in practice.
"""

from __future__ import annotations

from datetime import date

from har_search.core.labels import param_label, property_type_label, unknown_detail
from har_search.core.models import Criteria, Listing, ParamScore, PropertyType, ScoredListing

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
    """Expects known inputs. `miles=None` returns 0.0 as a defensive default —
    it does NOT mean "unknown location scores worst." Callers with an unknown
    location must branch on that themselves and mark the parameter unknown
    rather than relying on this return value."""
    if subdivision_match:
        return 1.0
    if miles is None:
        return 0.0
    return _rational(miles, GEO_TAU_MILES)


def categorical_score(
    actual: PropertyType | None, wanted: list[PropertyType]
) -> float:
    """Expects known inputs. `actual=None` returns 0.0 as a defensive default —
    it does NOT mean "unknown type scores worst." Callers with an unknown
    property type must branch on that themselves and mark the parameter
    unknown rather than relying on this return value."""
    if actual is None or not wanted:
        return 0.0
    if actual in wanted:
        return 1.0
    if actual in _MULTI_FAMILY_FAMILY and any(w in _MULTI_FAMILY_FAMILY for w in wanted):
        return 0.5
    return 0.0


MUST_THRESHOLD = 0.5
_EARTH_RADIUS_MILES = 3958.8


def _haversine_miles(lat1, lon1, lat2, lon2) -> float:
    from math import asin, cos, radians, sin, sqrt

    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * _EARTH_RADIUS_MILES * asin(sqrt(a))


def _weight(criteria: Criteria, name: str) -> float:
    overrides = criteria.weights or {}
    return float(overrides.get(name, DEFAULT_WEIGHTS.get(name, 1.0)))


def _param(name, score, weight, known, detail) -> ParamScore:
    return ParamScore(name=name, score=score, weight=weight, known=known, detail=detail)


def _target_param(criteria, name, target, actual, unit) -> ParamScore:
    weight = _weight(criteria, name)
    if actual is None:
        return _param(name, 0.0, weight, False, unknown_detail(name))
    tau_over, tau_under = TAU[name]
    score = target_score(actual, target, tau_over, tau_under)
    return _param(name, score, weight, True, f"{actual}{unit} vs {target}{unit} wanted")


def _ceiling_param(criteria, name, actual, ceiling, format_fn) -> ParamScore:
    """Score a ceiling parameter (max_price, max_price_per_sqft, max_age_years).

    Mirrors _target_param's shape and responsibilities.

    Args:
        criteria: The Criteria object.
        name: Parameter name (e.g., "max_price").
        actual: The listing's value (e.g., listing.price).
        ceiling: The criteria's ceiling value (e.g., criteria.max_price).
        format_fn: Function to format detail string given (actual, ceiling).
                   Called only when actual is not None.

    Returns:
        A ParamScore with known=False if actual is None, else known=True.
    """
    weight = _weight(criteria, name)
    if actual is None:
        # `f"no {name.replace('max_', '')}"` rendered "no price_per_sqft" on
        # screen, and the demo prospect's own example specifies a $/sqft
        # ceiling, so that string was reachable in the demo itself.
        return _param(name, 0.0, weight, False, unknown_detail(name))
    score = ceiling_score(actual, ceiling)
    detail = format_fn(actual, ceiling)
    return _param(name, score, weight, True, detail)


def score_listing(
    listing: Listing,
    criteria: Criteria,
    area_centroid: tuple[float, float] | None = None,
) -> ScoredListing | None:
    params: list[ParamScore] = []

    # Location.
    weight = _weight(criteria, "area")
    subdivision_match = bool(
        listing.subdivision
        and criteria.area.strip().lower() in listing.subdivision.lower()
    ) or bool(
        listing.city and criteria.area.strip().lower() == listing.city.strip().lower()
    ) or bool(listing.zip and criteria.area.strip() == listing.zip.strip())
    miles = None
    if area_centroid and listing.lat is not None and listing.lon is not None:
        miles = _haversine_miles(area_centroid[0], area_centroid[1], listing.lat, listing.lon)
    if subdivision_match or miles is not None:
        params.append(
            _param(
                "area",
                geo_score(subdivision_match, miles),
                weight,
                True,
                listing.subdivision or listing.city or criteria.area,
            )
        )
    else:
        params.append(_param("area", 0.0, weight, False, "no location data published"))

    # Ceiling parameters.
    if criteria.max_price is not None:
        params.append(
            _ceiling_param(
                criteria,
                "max_price",
                listing.price,
                criteria.max_price,
                lambda actual, ceiling: f"${actual:,} vs ${ceiling:,} budget",
            )
        )

    if criteria.max_price_per_sqft is not None:
        params.append(
            _ceiling_param(
                criteria,
                "max_price_per_sqft",
                listing.price_per_sqft,
                criteria.max_price_per_sqft,
                lambda actual, ceiling: f"${actual:.0f}/sqft vs ${ceiling:.0f} wanted",
            )
        )

    # Target parameters.
    if criteria.beds is not None:
        params.append(_target_param(criteria, "beds", criteria.beds, listing.beds, " bd"))
    if criteria.baths is not None:
        params.append(
            _target_param(criteria, "baths", criteria.baths, listing.baths_full, " ba")
        )
    if criteria.garage_spaces is not None:
        actual = listing.garage.spaces if listing.garage else None
        params.append(
            _target_param(criteria, "garage_spaces", criteria.garage_spaces, actual, " car")
        )
    if criteria.sqft is not None:
        params.append(_target_param(criteria, "sqft", criteria.sqft, listing.sqft, " sqft"))
    if criteria.max_age_years is not None:
        weight = _weight(criteria, "max_age_years")
        if listing.year_built is None:
            params.append(_param("max_age_years", 0.0, weight, False, unknown_detail("max_age_years")))
        else:
            age = date.today().year - listing.year_built
            params.append(
                _param(
                    "max_age_years",
                    ceiling_score(age, criteria.max_age_years),
                    weight,
                    True,
                    f"{age} years old",
                )
            )

    # Property type.
    if criteria.property_types:
        weight = _weight(criteria, "property_types")
        wanted = [PropertyType(value) for value in criteria.property_types]
        if listing.property_type is None:
            params.append(_param("property_types", 0.0, weight, False, unknown_detail("property_types")))
        else:
            params.append(
                _param(
                    "property_types",
                    categorical_score(listing.property_type, wanted),
                    weight,
                    True,
                    property_type_label(listing.property_type.value),
                )
            )

    # HOA. A missing fee is unknown, never "no HOA".
    if criteria.no_hoa:
        weight = _weight(criteria, "no_hoa")
        if listing.hoa is None:
            params.append(_param("no_hoa", 0.0, weight, False, unknown_detail("no_hoa")))
        else:
            score = 1.0 if listing.hoa.monthly_usd == 0.0 else 0.0
            detail = "no HOA" if listing.hoa.monthly_usd == 0.0 else f"HOA ${listing.hoa.monthly_usd:.0f}/mo"
            params.append(_param("no_hoa", score, weight, True, detail))

    # School rating.
    if criteria.min_school_rating:
        weight = _weight(criteria, "min_school_rating")
        if listing.school_rating is None:
            params.append(
                _param("min_school_rating", 0.0, weight, False, unknown_detail("min_school_rating"))
            )
        else:
            params.append(
                _param(
                    "min_school_rating",
                    listing.school_rating,
                    weight,
                    True,
                    f"schools {listing.school_rating:.2f}",
                )
            )

    for param in params:
        if param.name in criteria.must and param.score < MUST_THRESHOLD:
            return None

    known = [p for p in params if p.known]
    known_weight = sum(p.weight for p in known)
    total_weight = sum(p.weight for p in params)
    score = (
        sum(p.score * p.weight for p in known) / known_weight if known_weight else 0.0
    )
    coverage = known_weight / total_weight if total_weight else 0.0

    return ScoredListing(
        listing=listing,
        score=score,
        coverage=coverage,
        params=params,
        why=_build_why(params),
    )


def _build_why(params: list[ParamScore]) -> str:
    """Assembled from numbers by template, never generated.

    Parameter names go through `param_label` because this string is read by
    the user: "Included despite max_price_per_sqft" is a variable name, not an
    explanation.
    """
    known = [p for p in params if p.known]
    if not known:
        return "No comparable attributes published for this listing."
    weakest = min(known, key=lambda p: p.score)
    strong = [param_label(p.name) for p in known if p.score >= 0.9 and p.name != weakest.name]
    if weakest.score >= 0.9:
        return "Matches every requested criterion: " + ", ".join(
            param_label(p.name) for p in known
        ) + "."
    if strong:
        return (
            f"Included despite {param_label(weakest.name)} ({weakest.detail}) — "
            + ", ".join(strong)
            + " all match."
        )
    return f"Closest on {param_label(weakest.name)} ({weakest.detail})."
