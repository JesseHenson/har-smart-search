"""Adapter for the memo23/har-scraper Apify actor."""

from __future__ import annotations

from har_search.core.models import Criteria

ACTOR_PATH = "memo23~har-scraper"
RUN_SYNC_URL = f"https://api.apify.com/v2/acts/{ACTOR_PATH}/run-sync-get-dataset-items"

# Criteria property types map onto the actor's own vocabulary.
_TYPE_TO_ACTOR = {
    "single_family": "single-family",
    "townhouse_condo": "townhouse-condo",
    "duplex": "multi-family",
    "fourplex": "multi-family",
    "multi_family": "multi-family",
    "lots": "lots",
}


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
        payload["minBeds"] = criteria.beds
    if criteria.baths is not None:
        payload["minBaths"] = criteria.baths
    if criteria.max_price is not None:
        payload["maxPrice"] = criteria.max_price
    if criteria.max_price_per_sqft is not None:
        payload["maxPricePerSqft"] = int(criteria.max_price_per_sqft)
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

    def __init__(self, token: str, http=None, timeout: float = 180.0):
        self._token = token
        self._timeout = timeout
        if http is None:
            import httpx

            http = httpx.Client(timeout=timeout)
        self._http = http

    def _run(self, payload: dict) -> list[dict]:
        response = self._http.post(
            RUN_SYNC_URL,
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
