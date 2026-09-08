"""Fetch, normalize, score, value, persist — in that order, once."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import date, timedelta

from har_search.core.comps import TIERS, value_listing
from har_search.core.coverage import escalation_plan
from har_search.core.keys import snapshot_key
from har_search.core.models import Criteria, Listing, ScoredListing, Valuation
from har_search.core.normalize import normalize_listing, normalize_sale
from har_search.core.scoring import score_listing
from har_search.store.db import Database

COMP_LOOKBACK_DAYS = 365

# Derived, never typed by hand. This bounds the sold rows loaded out of the
# database, and `select_comps` can only choose from what it is handed — so a
# literal here that is narrower than the widest sold tier silently disables
# that tier, with no error and no empty-result to notice. That is exactly what
# happened when `four_miles` was added against a hardcoded 2.0.
COMP_RADIUS_MILES = max(
    tier.max_miles for tier in TIERS if tier.basis == "sold" and tier.max_miles
)


@dataclass
class SearchResult:
    snapshot_id: int
    saved_search: str
    scored: list[ScoredListing]
    valuations: dict[str, Valuation]
    exclusions: dict[str, int] = field(default_factory=dict)
    # Sold-row exclusions are counted separately from for-sale ones. They mean
    # something different: a for-sale exclusion thins the results table, a sold
    # exclusion thins the comp evidence behind every KPI in it. Folding them
    # into one number would let six leases inside a sold query disappear behind
    # a confidently smaller for-sale count.
    sold_exclusions: dict[str, int] = field(default_factory=dict)
    dropped_by_must: int = 0
    # How far the ladder walked, and which rung each match came from. A
    # result found three rungs out is not the same answer as one found in
    # the area asked for, and the caller cannot tell without these.
    areas_searched: list[str] = field(default_factory=list)
    area_of: dict[str, str] = field(default_factory=dict)
    # Set when a refresh was wanted and the vendor refused. The results are
    # still real; they are just as old as the cache is.
    vendor_unavailable: bool = False
    # Set when the caller asked to stay off the vendor entirely.
    offline: bool = False


# How long a fetched sold history stays good. Closed sales arrive in a
# trickle and the comps tiers already look back 180-365 days, so a week-old
# set moves an estimate by nothing a reader would notice. The cost it saves is
# not small: the sold leg is a second actor run, and running both leaves a
# search past the client's deadline while the work completes anyway — the
# caller is told the search failed and the rows land in the database.
SOLD_REFRESH_DAYS = 7

# How many listings one area refresh pulls. The fetch is criteria-free, so
# this is the whole neighbourhood rather than one question's answer, and it is
# the only number that costs money — searches against a fresh corpus are free.
CORPUS_LIMIT = 100

# Active listings move in a way closed sales do not: price cuts, pendings and
# withdrawals all land within a day, and every one of them changes an asking
# estimate. A week would be indefensible here even though it is right for sold.
CORPUS_REFRESH_DAYS = 1

# How far out an active comp may sit. Matches the `active` tier in comps.
ACTIVE_COMP_RADIUS_MILES = 2.0

# And how stale it may be. Wider than the refresh window so a comp is not
# lost the moment its own area falls a day behind, but far short of the
# sold lookback: an asking price nobody is asking any more is not evidence.
ACTIVE_COMP_MAX_AGE_DAYS = 3

# How many matches count as an answer. Below this the search widens to the
# next rung; at or above it, it stops. Widening past an area that already
# answered buys latency and vendor spend for nothing.
TARGET_RESULTS = 5

# How many neighbouring zips the ladder may reach. Each one is a corpus
# fetch the first time it is searched.
MAX_NEIGHBOUR_ZIPS = 3


def _area_centroid(listings: list[Listing]) -> tuple[float, float] | None:
    points = [(l.lat, l.lon) for l in listings if l.lat is not None and l.lon is not None]
    if not points:
        return None
    return (
        sum(p[0] for p in points) / len(points),
        sum(p[1] for p in points) / len(points),
    )


def _corpus_is_stale(db, area: str, today: date) -> bool:
    last = db.corpus_fetched_on(area)
    if last is None:
        return True
    return (today - date.fromisoformat(last)).days >= CORPUS_REFRESH_DAYS


def _sold_history_is_stale(db, area: str, today: date) -> bool:
    last = db.sold_fetched_on(area)
    if last is None:
        return True
    return (today - date.fromisoformat(last)).days >= SOLD_REFRESH_DAYS


def _refresh_corpus(source, db, area: str, today: date, exclusions: Counter) -> bool:
    """Pull one area into the corpus if its cache has gone stale.

    Returns True when the vendor was wanted and refused. A refusal is not an
    error to propagate: an account out of credit or a revoked token does not
    make the listings already in the database wrong, and throwing would lose
    an answer that is still worth giving. The failure is reported alongside
    the results instead, so the caller knows the data is as old as the cache.

    A failed refresh is deliberately not recorded. Marking it would cache the
    failure for a whole day and make the next search skip a vendor that may
    have come back.
    """
    if not _corpus_is_stale(db, area, today):
        return False
    try:
        raw_rows = list(source.fetch_corpus(area, CORPUS_LIMIT))
    except Exception:
        return True
    fetched: list[Listing] = []
    for raw in raw_rows:
        result = normalize_listing(raw)
        if result.listing is None:
            exclusions[result.exclusion or "unknown"] += 1
            continue
        fetched.append(result.listing)
    if fetched:
        db.upsert_actives(fetched, seen_on=today.isoformat())
        db.tag_corpus_area(area, [l.listing_id for l in fetched])
    db.record_corpus_fetch(area, today.isoformat())
    return False


def run_search(
    source,
    db: Database,
    criteria: Criteria,
    saved_search: str | None = None,
    limit: int = 25,
    today: date | None = None,
    center: tuple[float, float] | None = None,
    city: str | None = None,
    max_neighbours: int = MAX_NEIGHBOUR_ZIPS,
    target_results: int = TARGET_RESULTS,
    offline: bool = False,
) -> SearchResult:
    today = today or date.today()
    # Snapshots are keyed on the criteria, not the area. Keying on the area
    # alone put every search in a city into one bucket, so `whats_new` diffed
    # unrelated searches against each other and called every listing NEW or
    # GONE. An explicit `saved_search` is still honoured for callers that
    # manage their own buckets (the tests do).
    saved_search = saved_search or snapshot_key(criteria)

    # The criteria are the only human-readable description of this run; the
    # saved-search key is a hash of them and cannot be read backwards.
    db.record_saved_search(saved_search, criteria)

    # 2. Walk outward until an area answers.
    # The ladder is the comps tiers applied to places: the area asked for,
    # then its measured neighbours, then the city. A rung is only ever reached
    # because the one above it came up short, and each new rung costs a vendor
    # fetch the first time it is used — so the walk stops the moment it has
    # enough, and `areas_searched` records how far it went either way.
    exclusions: Counter[str] = Counter()
    plan = escalation_plan(
        area=criteria.area,
        center=center,
        city=city,
        max_neighbours=max_neighbours,
    )
    centroid = center or None
    scored: list[ScoredListing] = []
    sold_exclusions: Counter[str] = Counter()
    sales: list = []
    vendor_unavailable = False
    corpus_refreshed = False
    area_of: dict[str, str] = {}
    areas_searched: list[str] = []
    dropped_by_must = 0

    def unseen(area: str) -> list[Listing]:
        return [
            listing
            for listing in db.actives_in_area(area)
            if listing.listing_id not in area_of
        ]

    for index, area in enumerate(plan):
        areas_searched.append(area)
        # Read before fetching. Staleness is a reason to refresh when the
        # cache falls short, not a bill to pay before looking: refreshing
        # first bought an actor run on every stale marker even when the rows
        # already in the database would have answered. The vendor is the
        # fallback, and with the ladder able to reach five areas in one
        # search, the difference is five actor runs or none.
        listings = unseen(area)
        if not offline and len(scored) + len(listings) < target_results:
            if _refresh_corpus(source, db, area, today, exclusions):
                vendor_unavailable = True
            else:
                corpus_refreshed = True
                listings = unseen(area)
        if index == 0:
            # The area asked for is the only rung the caller's center and
            # radius describe.
            rung_criteria = criteria
            rung_centroid = centroid or _area_centroid(listings)
        else:
            # A widened rung is a different question — "nothing there, here is
            # what is near it" — so it is measured from its own centre. Judging
            # a neighbouring zip by the distance from an address in the
            # original one would sink every listing on it by construction, and
            # the ladder could never return anything. What keeps the answer
            # honest is that these arrive labelled with the area they came
            # from, not that they were scored against a place they are not in.
            rung_criteria = replace(criteria, center_address=None, radius_miles=None)
            rung_centroid = _area_centroid(listings)
        for listing in listings:
            result = score_listing(listing, rung_criteria, rung_centroid)
            if result is None:
                dropped_by_must += 1
                continue
            scored.append(result)
            area_of[listing.listing_id] = area
        if len(scored) >= target_results:
            break

    scored.sort(key=lambda s: s.score, reverse=True)
    # `limit` is now purely a presentation cap. It once bounded the vendor
    # fetch as well; keeping the two joined would shrink the comp pool every
    # time a caller asked for a shorter list.
    scored = scored[:limit]


    # 4a. Sold history, but only when listings were refreshed too.
    # It is a second actor run, and pairing it with the corpus refresh is what
    # makes a cached search genuinely free — refreshing it on its own schedule
    # meant every search still bought one run no matter what the cache held.
    # Comps are as fresh as the listings they price, which is the pairing a
    # reader would assume anyway.
    sold_exclusions: Counter[str] = Counter()
    sales: list = []
    if corpus_refreshed and not offline and _sold_history_is_stale(db, criteria.area, today):
        try:
            sold_rows = list(source.fetch_sold(area=criteria.area))
        except Exception:
            sold_rows = None
            vendor_unavailable = True
        for raw in sold_rows or []:
            result = normalize_sale(raw)
            if result.sale is None:
                sold_exclusions[result.exclusion or "unknown"] += 1
                continue
            sales.append(result.sale)
        if sales:
            db.upsert_sales(sales)
        # Recorded even when the fetch returned nothing usable. An area with no
        # published sales would otherwise re-run the same empty leg on every
        # search, paying full latency for a result already known.
        if sold_rows is not None:
            db.record_sold_fetch(criteria.area, today.isoformat())


    # 4. Value each survivor against accumulated sold history.
    since = today - timedelta(days=COMP_LOOKBACK_DAYS)
    valuations: dict[str, Valuation] = {}
    # The active comp pool is the corpus around the subject, not this run's
    # survivors. Drawing it from the survivors made the estimate circular: the
    # caller's budget reached the pool, so a house was only ever compared
    # against houses inside the budget it was being judged against, and the
    # estimate could not see the market it claimed to measure.
    for item in scored:
        listing = item.listing
        sales = (
            db.sales_near(listing.lat, listing.lon, COMP_RADIUS_MILES, since)
            if listing.lat is not None and listing.lon is not None
            else []
        )
        actives = (
            db.actives_near(
                listing.lat,
                listing.lon,
                ACTIVE_COMP_RADIUS_MILES,
                seen_since=(today - timedelta(days=ACTIVE_COMP_MAX_AGE_DAYS)).isoformat(),
            )
            if listing.lat is not None and listing.lon is not None
            else []
        )
        valuations[listing.listing_id] = value_listing(listing, sales, actives, today)

    # 5. Persist.
    snapshot_id = db.create_snapshot(
        saved_search=saved_search,
        source=getattr(source, "name", "unknown"),
        item_count=len(scored),
        excluded_count=sum(exclusions.values()) + dropped_by_must,
        exclusions=dict(exclusions),
        sold_exclusions=dict(sold_exclusions),
        dropped_by_must=dropped_by_must,
    )
    db.insert_scored(snapshot_id, scored, valuations)

    return SearchResult(
        snapshot_id=snapshot_id,
        saved_search=saved_search,
        scored=scored,
        valuations=valuations,
        exclusions=dict(exclusions),
        sold_exclusions=dict(sold_exclusions),
        dropped_by_must=dropped_by_must,
        areas_searched=areas_searched,
        area_of=area_of,
        vendor_unavailable=vendor_unavailable,
        offline=offline,
    )
