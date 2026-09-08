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
def corpus_actor_input(area: str, limit: int) -> dict:
    """Everything for sale in one area, unfiltered.

    Deliberately criteria-free. Passing the caller's budget or bed count to
    the vendor is what made the active comp pool circular — the pool was drawn
    from the same narrowed fetch that produced the results, so a house was
    only ever compared against houses inside the budget it was being judged
    against. Filtering happens locally, against the whole neighbourhood.
    """
    return {
        "listingType": "sale",
        "locations": [area],
        "includeDetails": True,
        "includeAvm": True,
        "maxItems": limit,
        "sortBy": "newest",
    }


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
        # The token goes in a header, never the query string. Apify accepts
        # both, but a URL is the one part of a request that everything logs:
        # ours was written in full into the desktop app's MCP log seven times
        # by a run of 403s, inside the traceback, in plaintext.
        response = self._http.post(
            self._run_sync_url,
            json=payload,
            headers={"Authorization": f"Bearer {self._token}"},
            timeout=self._timeout,
        )
        response.raise_for_status()
        return response.json()

    def fetch_corpus(self, area: str, limit: int) -> list[dict]:
        return self._run(corpus_actor_input(area, limit))

    def fetch_sold(self, area: str, agent_depth: int = 25, limit: int = 200) -> list[dict]:
        return self._run(
            {
                "listingType": "sold",
                "locations": [area],
                "maxSoldAgents": agent_depth,
                "maxItems": limit,
            }
        )
