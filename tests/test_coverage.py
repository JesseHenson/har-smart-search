"""Where the search widens to when the area it was given comes up short.

Adjacency is measured, never inferred from the numbers themselves: 77084 and
77094 look adjacent and are not, while 77041 sits next door and shares no
digits beyond the prefix. The centroids are Census ZCTA data, the same source
the geocoder already uses.
"""

import pytest

from har_search.core.coverage import escalation_plan, neighbouring_zips

BEAVERBROOK = (29.853592, -95.639297)


def test_neighbours_are_the_nearest_zips_by_centroid():
    found = neighbouring_zips(BEAVERBROOK, exclude={"77084"}, limit=3)
    assert found == ["77041", "77095", "77043"]


def test_the_requested_zip_is_never_offered_as_its_own_neighbour():
    found = neighbouring_zips(BEAVERBROOK, exclude={"77084"}, limit=5)
    assert "77084" not in found


def test_neighbour_count_is_capped():
    """Each neighbour is a vendor fetch. Widening without a leash puts back
    exactly the latency the corpus removed."""
    assert len(neighbouring_zips(BEAVERBROOK, exclude=set(), limit=2)) == 2


def test_the_plan_runs_from_the_asked_for_area_outward_to_the_city():
    """Tightest first. A rung is only ever reached because the one above it
    did not answer, so the order is the whole contract."""
    plan = escalation_plan(area="77084", center=BEAVERBROOK, city="Houston", max_neighbours=2)
    assert plan == ["77084", "77041", "77095", "Houston"]


def test_a_non_zip_area_has_nothing_to_widen_to_but_the_city():
    """'Spring' is not a zip, so there is no centroid to measure neighbours
    from. Widening straight to the city is honest; guessing is not."""
    plan = escalation_plan(area="Spring", center=None, city="Houston", max_neighbours=3)
    assert plan == ["Spring", "Houston"]


def test_the_city_rung_is_dropped_when_it_repeats_the_area():
    plan = escalation_plan(area="Houston", center=None, city="Houston", max_neighbours=3)
    assert plan == ["Houston"]


def test_no_city_means_the_ladder_simply_ends_earlier():
    plan = escalation_plan(area="77084", center=BEAVERBROOK, city=None, max_neighbours=1)
    assert plan == ["77084", "77041"]
