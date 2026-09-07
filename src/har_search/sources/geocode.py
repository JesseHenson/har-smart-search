"""Address to coordinate, via the US Census geocoder.

Census rather than a commercial geocoder because this tool is US-only and the
service needs no key, no account and no per-call budget — one less thing for
the user to configure before a search works. It is accurate on street
addresses and returns nothing rather than guessing when it cannot place one,
which is the behaviour a hard radius depends on.
"""

from __future__ import annotations

ONELINE_URL = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"

# The current vintage of the public address ranges. Pinned rather than left to
# the service default so a benchmark rotation cannot silently move results.
BENCHMARK = "Public_AR_Current"


class CensusGeocoder:
    def __init__(self, http=None, timeout: float = 15.0):
        self._timeout = timeout
        if http is None:
            import httpx

            http = httpx.Client(timeout=timeout)
        self._http = http

    def locate(self, address: str) -> tuple[float, float] | None:
        """Return (lat, lon), or None when the address cannot be placed.

        None is a real answer here, not an error to swallow: a mistyped
        address that fell back to a default coordinate would center the
        search somewhere the user never named and report the result as if
        they had.
        """
        response = self._http.get(
            ONELINE_URL,
            params={
                "address": address,
                "benchmark": BENCHMARK,
                "format": "json",
            },
            timeout=self._timeout,
        )
        response.raise_for_status()
        matches = (response.json().get("result") or {}).get("addressMatches") or []
        if not matches:
            return None
        coordinates = matches[0].get("coordinates") or {}
        lat = coordinates.get("y")
        lon = coordinates.get("x")
        if lat is None or lon is None:
            return None
        # Census speaks x/y. Everything downstream speaks lat/lon, and the
        # swap is invisible until a distance comes back absurd.
        return (float(lat), float(lon))
