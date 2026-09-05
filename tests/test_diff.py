from har_search.core.diff import diff_snapshots
from har_search.core.models import Listing


def listing(listing_id, price, address="1 Main St") -> Listing:
    return Listing(listing_id=listing_id, price=price, address=address)


def by_type(changes):
    return {c.listing_id: c.change_type for c in changes}


def test_new_listing_is_detected():
    changes = diff_snapshots([], [listing("A", 200_000)])
    assert by_type(changes) == {"A": "NEW"}


def test_gone_listing_is_detected():
    changes = diff_snapshots([listing("A", 200_000)], [])
    assert by_type(changes) == {"A": "GONE"}


def test_price_cut_and_rise_are_distinguished():
    previous = [listing("A", 200_000), listing("B", 300_000)]
    current = [listing("A", 190_000), listing("B", 310_000)]
    assert by_type(diff_snapshots(previous, current)) == {
        "A": "PRICE_CUT",
        "B": "PRICE_UP",
    }


def test_unchanged_listing_is_reported_as_unchanged():
    previous = [listing("A", 200_000)]
    current = [listing("A", 200_000)]
    assert by_type(diff_snapshots(previous, current)) == {"A": "UNCHANGED"}


def test_change_carries_both_prices_and_the_address():
    changes = diff_snapshots(
        [listing("A", 200_000, "5519 Lynngate Dr")],
        [listing("A", 190_000, "5519 Lynngate Dr")],
    )
    change = changes[0]
    assert change.old_price == 200_000
    assert change.new_price == 190_000
    assert change.address == "5519 Lynngate Dr"


def test_missing_price_does_not_produce_a_false_change():
    previous = [listing("A", None)]
    current = [listing("A", None)]
    assert by_type(diff_snapshots(previous, current)) == {"A": "UNCHANGED"}


def test_none_to_price_transition_is_unchanged():
    """Previous snapshot has no price; current has a real price.

    Should classify as UNCHANGED because None means unknown, not zero.
    If missing prices were incorrectly coerced to 0, this would falsely
    become PRICE_UP (0 → 200_000).
    """
    previous = [listing("A", None, "5519 Lynngate Dr")]
    current = [listing("A", 200_000, "5519 Lynngate Dr")]
    changes = diff_snapshots(previous, current)
    assert by_type(changes) == {"A": "UNCHANGED"}

    # Verify the change carries both prices as given
    change = changes[0]
    assert change.old_price is None
    assert change.new_price == 200_000
    assert change.address == "5519 Lynngate Dr"


def test_price_to_none_transition_is_unchanged():
    """Previous snapshot has a real price; current has no price.

    Should classify as UNCHANGED because None means unknown, not zero.
    If missing prices were incorrectly coerced to 0, this would falsely
    become PRICE_CUT (200_000 → 0).
    """
    previous = [listing("A", 200_000, "5519 Lynngate Dr")]
    current = [listing("A", None, "5519 Lynngate Dr")]
    changes = diff_snapshots(previous, current)
    assert by_type(changes) == {"A": "UNCHANGED"}

    # Verify the change carries both prices as given
    change = changes[0]
    assert change.old_price == 200_000
    assert change.new_price is None
    assert change.address == "5519 Lynngate Dr"
