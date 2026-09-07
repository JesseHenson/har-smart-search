"""Where a search widens to when the area it was given comes up short.

The ladder is the same idea as the comps tiers: start at what was asked for,
widen only because the rung above it did not answer, and stop at a point past
which the result stops describing the question. Here the rungs are places
rather than distances — the requested area, then its nearest neighbouring
zips, then the city.

Adjacency is measured from Census ZCTA centroids, never inferred from the
digits. 77084 and 77094 look adjacent and are not; 77041 is next door and
shares nothing past the prefix. Vendored as a file rather than fetched so
deciding *where* to widen never needs the network — only fetching does.
"""

from __future__ import annotations

import csv
from functools import lru_cache
from math import asin, cos, radians, sin, sqrt
from pathlib import Path

CENTROIDS_PATH = Path(__file__).parent.parent / "data" / "zcta_centroids.csv"

EARTH_RADIUS_MILES = 3958.7561


def _haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * asin(sqrt(a))


@lru_cache(maxsize=1)
def _centroids() -> tuple[tuple[str, float, float], ...]:
    with CENTROIDS_PATH.open() as handle:
        return tuple(
            (row["zip"], float(row["lat"]), float(row["lon"]))
            for row in csv.DictReader(handle)
        )


def neighbouring_zips(
    center: tuple[float, float], exclude: set[str], limit: int
) -> list[str]:
    """The `limit` nearest zip centroids to `center`, nearest first.

    `limit` is a leash, not a preference. Every neighbour returned here
    becomes a vendor fetch the first time it is searched, which is the latency
    the corpus exists to avoid — widening without a cap puts it straight back.
    """
    lat, lon = center
    ranked = sorted(
        (
            (_haversine_miles(lat, lon, clat, clon), code)
            for code, clat, clon in _centroids()
            if code not in exclude
        ),
        key=lambda pair: pair[0],
    )
    return [code for _, code in ranked[:limit]]


def _is_zip(area: str) -> bool:
    return area.strip().isdigit() and len(area.strip()) == 5


def escalation_plan(
    area: str,
    center: tuple[float, float] | None,
    city: str | None,
    max_neighbours: int,
) -> list[str]:
    """Areas to try, tightest first.

    A non-zip area has no centroid to measure neighbours from, so it widens
    straight to the city. That is a real gap rather than a bug: guessing which
    places neighbour "Spring" from its name is exactly the inference this
    module exists to avoid.
    """
    plan = [area]
    seen = {area.strip().lower()}

    if _is_zip(area) and center is not None and max_neighbours > 0:
        for code in neighbouring_zips(center, exclude={area.strip()}, limit=max_neighbours):
            if code.lower() not in seen:
                plan.append(code)
                seen.add(code.lower())

    if city and city.strip().lower() not in seen:
        plan.append(city)

    return plan
