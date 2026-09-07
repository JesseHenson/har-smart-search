"""The geocoder turns the address a user typed into the fixed point that
scoring measures against. Everything downstream — the radius, the centroid,
the comps distance tiers — is wrong in the same direction if this is wrong,
and wrong quietly, so the coordinate order is pinned by test."""

from har_search.sources.geocode import CensusGeocoder


class StubHttp:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": params})
        return StubResponse(self.payload)


class StubResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def match_payload(x: float, y: float) -> dict:
    return {
        "result": {
            "addressMatches": [
                {
                    "matchedAddress": "5255 BEAVERBROOK DR, HOUSTON, TX, 77084",
                    "coordinates": {"x": x, "y": y},
                }
            ]
        }
    }


def test_census_x_is_longitude_and_y_is_latitude():
    """The Census API returns x/y, not lat/lon. Swapping them puts a Houston
    address in the Indian Ocean and every distance silently becomes garbage."""
    http = StubHttp(match_payload(x=-95.6597, y=29.8329))
    located = CensusGeocoder(http=http).locate("5255 Beaverbrook Dr, Houston, TX 77084")
    assert located == (29.8329, -95.6597)


def test_no_match_returns_none():
    """A typo must not become a silent centroid at (0, 0)."""
    http = StubHttp({"result": {"addressMatches": []}})
    assert CensusGeocoder(http=http).locate("not a real address") is None


def test_malformed_response_returns_none():
    http = StubHttp({"result": {}})
    assert CensusGeocoder(http=http).locate("5255 Beaverbrook Dr") is None


def test_the_address_is_sent_as_a_one_line_query():
    http = StubHttp(match_payload(x=-95.6597, y=29.8329))
    CensusGeocoder(http=http).locate("5255 Beaverbrook Dr, Houston, TX 77084")
    assert http.calls[0]["params"]["address"] == "5255 Beaverbrook Dr, Houston, TX 77084"
    assert http.calls[0]["params"]["format"] == "json"


def test_the_place_carries_the_city_the_ladder_widens_to():
    """The last rung is the city, and the caller only gave an address. Census
    already names it in the matched address, so asking a second service for
    something we were handed would be waste."""
    http = StubHttp(match_payload(x=-95.6597, y=29.8329))
    place = CensusGeocoder(http=http).locate_place("5255 Beaverbrook Dr")
    assert (place.lat, place.lon) == (29.8329, -95.6597)
    assert place.city == "Houston"


def test_a_matched_address_without_a_city_still_places_the_point():
    """A missing city costs the ladder its last rung, nothing more. Refusing
    the whole geocode over it would lose the radius as well."""
    payload = {
        "result": {
            "addressMatches": [
                {"matchedAddress": "5255 BEAVERBROOK DR", "coordinates": {"x": -95.6, "y": 29.8}}
            ]
        }
    }
    place = CensusGeocoder(http=StubHttp(payload)).locate_place("5255 Beaverbrook Dr")
    assert place.city is None
    assert place.lat == 29.8


def test_no_match_returns_no_place():
    http = StubHttp({"result": {"addressMatches": []}})
    assert CensusGeocoder(http=http).locate_place("nowhere") is None
