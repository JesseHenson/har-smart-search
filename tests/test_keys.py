from har_search.core.keys import resolve_saved_search, snapshot_key
from har_search.core.models import Criteria


def test_two_different_searches_in_the_same_area_get_different_keys():
    """The defect: `saved_search=area` put both of these in one bucket.

    `whats_new` then diffed a 3-bed-under-$200k run against a 5-bed-under-$600k
    run of the same city and reported every listing in each as NEW or GONE.
    """
    starter = Criteria(area="Spring", beds=3, max_price=200_000)
    family = Criteria(area="Spring", beds=5, max_price=600_000)
    assert snapshot_key(starter) != snapshot_key(family)


def test_the_same_search_always_gets_the_same_key():
    """Week-over-week diffing depends on this being stable across runs."""
    first = Criteria(area="Spring", beds=3, max_price=200_000)
    second = Criteria(area="Spring", beds=3, max_price=200_000)
    assert snapshot_key(first) == snapshot_key(second)


def test_key_is_stable_across_list_and_dict_ordering():
    """Splitting one search into two buckets is the same defect, inverted."""
    one = Criteria(
        area="Spring",
        property_types=["duplex", "fourplex"],
        must=["area", "max_price"],
        weights={"beds": 2.0, "area": 3.0},
    )
    other = Criteria(
        area="Spring",
        property_types=["fourplex", "duplex"],
        must=["max_price", "area"],
        weights={"area": 3.0, "beds": 2.0},
    )
    assert snapshot_key(one) == snapshot_key(other)


def test_key_ignores_surrounding_whitespace_and_case_in_the_area():
    """Same criteria under different casing/whitespace must land in the same
    bucket. Comparing only the hash suffix would pass even if the display
    half ('Spring' vs 'spring' vs 'SPRING') split the searches into separate
    buckets — the whole key is what `whats_new` actually looks up by.
    """
    reference = snapshot_key(Criteria(area="Spring"))
    assert snapshot_key(Criteria(area=" spring ")) == reference
    assert snapshot_key(Criteria(area="SPRING")) == reference


def test_key_still_reads_as_a_place_name():
    key = snapshot_key(Criteria(area="Spring", beds=3))
    assert key.startswith("Spring #")


def test_weights_change_the_key():
    plain = Criteria(area="Spring", beds=3)
    weighted = Criteria(area="Spring", beds=3, weights={"beds": 5.0})
    assert snapshot_key(plain) != snapshot_key(weighted)


def test_resolve_accepts_the_full_key_verbatim():
    keys = ["Spring #aaaaaaaa", "Spring #bbbbbbbb"]
    assert resolve_saved_search("Spring #bbbbbbbb", keys) == ("Spring #bbbbbbbb", None)


def test_resolve_accepts_a_bare_area_when_it_is_unambiguous():
    key, error = resolve_saved_search("spring", ["Spring #aaaaaaaa"])
    assert key == "Spring #aaaaaaaa"
    assert error is None


def test_resolve_refuses_to_guess_between_two_searches_in_one_area():
    """Guessing wrong here produces exactly the bogus diff the key prevents."""
    keys = ["Spring #aaaaaaaa", "Spring #bbbbbbbb"]
    key, error = resolve_saved_search("Spring", keys)
    assert key is None
    assert "Spring #aaaaaaaa" in error and "Spring #bbbbbbbb" in error


def test_resolve_reports_an_unknown_search_rather_than_returning_nothing():
    key, error = resolve_saved_search("Katy", ["Spring #aaaaaaaa"])
    assert key is None
    assert "Katy" in error
