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
