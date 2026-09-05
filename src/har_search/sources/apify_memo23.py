"""Adapter for the memo23/har-scraper Apify actor."""

from __future__ import annotations

from har_search.core.models import Criteria

DEFAULT_ACTOR = "memo23/har-scraper"


def _actor_path(actor: str) -> str:
    """The API path uses `~` where the actor's own name uses `/`."""
    return actor.replace("/", "~")


def _run_sync_url(actor: str) -> str:
    return f"https://api.apify.com/v2/acts/{_actor_path(actor)}/run-sync-get-dataset-items"


# Criteria property types map onto the actor's own vocabulary.
_TYPE_TO_ACTOR = {
    "single_family": "single-family",
    "townhouse_condo": "townhouse-condo",
    "duplex": "multi-family",
    "fourplex": "multi-family",
    "multi_family": "multi-family",
    "lots": "lots",
}

# This is a similarity finder, not a filter (see core/scoring.py). The
# vendor-side window below only caps fetch volume; client-side scoring
# stays the authority on ranking. Each factor mirrors the point in the
# scoring curve past which a listing can no longer rank meaningfully.

# ceiling_score (tau=CEILING_TAU=0.16) has decayed to ~0.29 at 25% over
# the ceiling — widen maxPrice/maxPricePerSqft that far so the tolerant
# tail scoring describes can actually be fetched.
CEILING_WIDEN_FACTOR = 1.25

# target_score's tau_under for beds/baths (0.82) puts one unit below
# target at ~0.40 — drop the vendor-side minimum by one unit to match,
# floored at 1 so the payload never asks for zero or negative rooms.
TARGET_MIN_STEPDOWN = 1


def criteria_to_actor_input(criteria: Criteria, limit: int) -> dict:
    payload: dict = {
        "listingType": "sale",
        "locations": [criteria.area],
        "includeDetails": True,
        "includeAvm": True,
        "maxItems": limit,
        "sortBy": "newest",
    }
    if criteria.beds is not None:
        payload["minBeds"] = max(1, criteria.beds - TARGET_MIN_STEPDOWN)
    if criteria.baths is not None:
        payload["minBaths"] = max(1, criteria.baths - TARGET_MIN_STEPDOWN)
    if criteria.max_price is not None:
        payload["maxPrice"] = int(criteria.max_price * CEILING_WIDEN_FACTOR)
    if criteria.max_price_per_sqft is not None:
        payload["maxPricePerSqft"] = int(criteria.max_price_per_sqft * CEILING_WIDEN_FACTOR)
    if criteria.sqft is not None:
        payload["minSqft"] = int(criteria.sqft * 0.75)
    if criteria.property_types:
        mapped = {
            _TYPE_TO_ACTOR[value]
            for value in criteria.property_types
            if value in _TYPE_TO_ACTOR
        }
        if mapped:
            payload["propertyTypes"] = sorted(mapped)
    return payload


class ApifyMemo23Source:
    name = "apify_memo23"

    def __init__(
        self,
        token: str,
        actor: str = DEFAULT_ACTOR,
        http=None,
        timeout: float = 180.0,
    ):
        self._token = token
        self._actor = actor
        self._run_sync_url = _run_sync_url(actor)
        self._timeout = timeout
        if http is None:
            import httpx

            http = httpx.Client(timeout=timeout)
        self._http = http

    def _run(self, payload: dict) -> list[dict]:
        response = self._http.post(
            self._run_sync_url,
            json=payload,
            params={"token": self._token},
            timeout=self._timeout,
        )
        response.raise_for_status()
        return response.json()

    def fetch_for_sale(self, criteria: Criteria, limit: int) -> list[dict]:
        return self._run(criteria_to_actor_input(criteria, limit))

    def fetch_sold(self, area: str, agent_depth: int = 25, limit: int = 200) -> list[dict]:
        return self._run(
            {
                "listingType": "sold",
                "locations": [area],
                "maxSoldAgents": agent_depth,
                "maxItems": limit,
            }
        )
