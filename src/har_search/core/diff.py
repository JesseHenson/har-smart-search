"""Compare two snapshots of the same saved search."""

from __future__ import annotations

from har_search.core.models import Listing, ListingChange


def diff_snapshots(
    previous: list[Listing], current: list[Listing]
) -> list[ListingChange]:
    before = {listing.listing_id: listing for listing in previous}
    after = {listing.listing_id: listing for listing in current}

    changes: list[ListingChange] = []

    for listing_id, listing in after.items():
        old = before.get(listing_id)
        if old is None:
            changes.append(
                ListingChange(
                    listing_id=listing_id,
                    change_type="NEW",
                    old_price=None,
                    new_price=listing.price,
                    address=listing.address,
                )
            )
            continue

        if old.price is not None and listing.price is not None:
            if listing.price < old.price:
                change_type = "PRICE_CUT"
            elif listing.price > old.price:
                change_type = "PRICE_UP"
            else:
                change_type = "UNCHANGED"
        else:
            change_type = "UNCHANGED"

        changes.append(
            ListingChange(
                listing_id=listing_id,
                change_type=change_type,
                old_price=old.price,
                new_price=listing.price,
                address=listing.address,
            )
        )

    for listing_id, listing in before.items():
        if listing_id not in after:
            changes.append(
                ListingChange(
                    listing_id=listing_id,
                    change_type="GONE",
                    old_price=listing.price,
                    new_price=None,
                    address=listing.address,
                )
            )

    return changes
