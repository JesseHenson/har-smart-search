"""SQLite persistence.

sold_history is deliberately never scoped to a run. Comp density is the
binding constraint on the product, so closed sales accumulate permanently
and every scan makes the next valuation better.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path

from har_search.core.comps import haversine_miles
from har_search.core.models import (
    DuplexScope,
    GarageInfo,
    HOA,
    Listing,
    MoneyRange,
    PropertyType,
    Sale,
    ScoredListing,
    Valuation,
)

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row

    # Columns added after the first release. CREATE TABLE IF NOT EXISTS will
    # not add a column to a table that already exists, and the demo database is
    # captured days before the meeting, so an in-place migration is the only
    # thing standing between a new column and a broken existing database.
    _ADDED_COLUMNS = (
        ("snapshots", "sold_exclusions_json", "TEXT"),
        ("snapshots", "dropped_by_must", "INTEGER NOT NULL DEFAULT 0"),
    )

    def init_schema(self) -> None:
        self._conn.executescript(SCHEMA_PATH.read_text())
        self._migrate()
        self._adopt_snapshot_listings_into_corpus()
        self._conn.commit()

    def _adopt_snapshot_listings_into_corpus(self) -> None:
        """Seed the corpus from listings earlier snapshots already captured.

        The corpus is only ever filled by a successful vendor fetch, so an
        upgrade arriving at a database with a dry vendor account had plenty of
        listings and no way to reach a single one of them. Every row in
        `listings` is a listing we did fetch, once — enough to answer offline.

        Rows are adopted with the run date of the snapshot that found them,
        never today's. Stamping them fresh would suppress the next real
        refresh for a day on data that may be months old, which is the same
        lie in the other direction.
        """
        self._conn.execute(
            "INSERT OR IGNORE INTO active_listings ("
            " listing_id, mls_number, address, city, zip, subdivision, lat, lon,"
            " price, price_per_sqft, beds, baths_full, baths_half, sqft, lot_sqft,"
            " year_built, garage_spaces, garage_attached, garage_tags_json,"
            " hoa_monthly, property_type, duplex_scope, status, days_on_market,"
            " school_rating, tax_rate, appraisal_low, appraisal_high, url,"
            " flags_json, first_seen, last_seen)"
            " SELECT l.listing_id, l.mls_number, l.address, l.city, l.zip,"
            " l.subdivision, l.lat, l.lon, l.price, l.price_per_sqft, l.beds,"
            " l.baths_full, l.baths_half, l.sqft, l.lot_sqft, l.year_built,"
            " l.garage_spaces, l.garage_attached, l.garage_tags_json,"
            " l.hoa_monthly, l.property_type, l.duplex_scope, l.status,"
            " l.days_on_market, l.school_rating, l.tax_rate, l.appraisal_low,"
            " l.appraisal_high, l.url, l.flags_json,"
            " date(s.run_at), date(s.run_at)"
            " FROM listings l JOIN snapshots s ON s.id = l.snapshot_id"
            " WHERE l.zip IS NOT NULL"
            " GROUP BY l.listing_id"
        )
        # Tagged by the listing's own zip rather than the search that found
        # it: the search may have named a city, a misspelling or a compound
        # string that resolves to nothing, and the zip is where the house
        # actually is.
        self._conn.execute(
            "INSERT OR IGNORE INTO corpus_areas (area, listing_id)"
            " SELECT lower(zip), listing_id FROM active_listings"
            " WHERE zip IS NOT NULL"
        )
        self._conn.execute(
            "INSERT OR IGNORE INTO corpus_fetches (area, fetched_on)"
            " SELECT lower(a.zip), max(a.last_seen) FROM active_listings a"
            " WHERE a.zip IS NOT NULL GROUP BY lower(a.zip)"
        )

    def _migrate(self) -> None:
        for table, column, decl in self._ADDED_COLUMNS:
            existing = {
                row["name"]
                for row in self._conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
            if column not in existing:
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")

    def record_saved_search(self, name: str, criteria) -> None:
        """Remember the criteria behind a saved-search key.

        The key is a hash of the criteria, so it is a one-way function: without
        this row the dashboard can only show "Katy #f8023fe1" and no reader can
        tell what was asked for. Re-running the same search rewrites the same
        row rather than adding one, since identical criteria always hash alike.
        """
        payload = criteria if isinstance(criteria, dict) else asdict(criteria)
        self._conn.execute(
            "INSERT INTO saved_searches (name, criteria_json, created_at)"
            " VALUES (?, ?, ?)"
            " ON CONFLICT(name) DO UPDATE SET criteria_json = excluded.criteria_json",
            (name, json.dumps(payload), datetime.now().isoformat(timespec="seconds")),
        )
        self._conn.commit()

    def get_saved_search(self, name: str) -> dict | None:
        row = self._conn.execute(
            "SELECT criteria_json FROM saved_searches WHERE name = ?", (name,)
        ).fetchone()
        return json.loads(row["criteria_json"]) if row else None

    def list_saved_searches(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT name, criteria_json FROM saved_searches ORDER BY name"
        ).fetchall()
        return [
            {"name": r["name"], "criteria": json.loads(r["criteria_json"])} for r in rows
        ]

    def create_snapshot(
        self,
        saved_search: str,
        source: str,
        item_count: int,
        excluded_count: int,
        exclusions: dict,
        sold_exclusions: dict | None = None,
        dropped_by_must: int = 0,
    ) -> int:
        cursor = self._conn.execute(
            "INSERT INTO snapshots (saved_search, run_at, source, item_count,"
            " excluded_count, exclusions_json, sold_exclusions_json, dropped_by_must)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                saved_search,
                datetime.now().isoformat(timespec="seconds"),
                source,
                item_count,
                excluded_count,
                json.dumps(exclusions),
                json.dumps(sold_exclusions or {}),
                dropped_by_must,
            ),
        )
        self._conn.commit()
        return int(cursor.lastrowid)

    def insert_scored(
        self,
        snapshot_id: int,
        scored: list[ScoredListing],
        valuations: dict[str, Valuation],
    ) -> None:
        # listing.raw is deliberately never persisted here: it's the large, re-fetchable vendor payload.
        for item in scored:
            listing = item.listing
            valuation = valuations.get(listing.listing_id, Valuation())
            garage = listing.garage
            garage_attached = (
                None if garage is None or garage.attached is None else int(garage.attached)
            )
            garage_tags_json = None if garage is None else json.dumps(list(garage.tags))
            self._conn.execute(
                "INSERT OR REPLACE INTO listings (snapshot_id, listing_id, mls_number,"
                " address, city, zip, subdivision, lat, lon, price, price_per_sqft,"
                " beds, baths_full, baths_half, sqft, lot_sqft, year_built,"
                " garage_spaces, garage_attached, garage_tags_json, hoa_monthly,"
                " property_type, duplex_scope, status,"
                " days_on_market, school_rating, tax_rate, appraisal_low,"
                " appraisal_high, url, score, coverage, why, score_breakdown_json,"
                " valuation_json, flags_json)"
                " VALUES (" + ",".join("?" * 36) + ")",
                (
                    snapshot_id,
                    listing.listing_id,
                    listing.mls_number,
                    listing.address,
                    listing.city,
                    listing.zip,
                    listing.subdivision,
                    listing.lat,
                    listing.lon,
                    listing.price,
                    listing.price_per_sqft,
                    listing.beds,
                    listing.baths_full,
                    listing.baths_half,
                    listing.sqft,
                    listing.lot_sqft,
                    listing.year_built,
                    garage.spaces if garage else None,
                    garage_attached,
                    garage_tags_json,
                    listing.hoa.monthly_usd if listing.hoa else None,
                    listing.property_type.value if listing.property_type else None,
                    listing.duplex_scope.value,
                    listing.status,
                    listing.days_on_market,
                    listing.school_rating,
                    listing.tax_rate,
                    listing.appraisal.low if listing.appraisal else None,
                    listing.appraisal.high if listing.appraisal else None,
                    listing.url,
                    item.score,
                    item.coverage,
                    item.why,
                    json.dumps([asdict(p) for p in item.params]),
                    json.dumps(_valuation_to_json(valuation)),
                    json.dumps(list(listing.flags)),
                ),
            )
        self._conn.commit()

    def _row_to_listing(self, row: sqlite3.Row) -> Listing:
        return Listing(
            listing_id=row["listing_id"],
            mls_number=row["mls_number"],
            address=row["address"],
            city=row["city"],
            zip=row["zip"],
            subdivision=row["subdivision"],
            lat=row["lat"],
            lon=row["lon"],
            price=row["price"],
            price_per_sqft=row["price_per_sqft"],
            beds=row["beds"],
            baths_full=row["baths_full"],
            baths_half=row["baths_half"],
            sqft=row["sqft"],
            lot_sqft=row["lot_sqft"],
            year_built=row["year_built"],
            garage=GarageInfo(
                spaces=row["garage_spaces"],
                attached=None
                if row["garage_attached"] is None
                else bool(row["garage_attached"]),
                tags=tuple(json.loads(row["garage_tags_json"] or "[]")),
            )
            if row["garage_spaces"] is not None
            else None,
            hoa=HOA(monthly_usd=row["hoa_monthly"])
            if row["hoa_monthly"] is not None
            else None,
            property_type=PropertyType(row["property_type"])
            if row["property_type"]
            else None,
            duplex_scope=DuplexScope(row["duplex_scope"] or "unknown"),
            status=row["status"],
            days_on_market=row["days_on_market"],
            school_rating=row["school_rating"],
            tax_rate=row["tax_rate"],
            appraisal=MoneyRange(low=row["appraisal_low"], high=row["appraisal_high"])
            if row["appraisal_low"] is not None
            else None,
            url=row["url"],
            flags=tuple(json.loads(row["flags_json"] or "[]")),
        )

    def get_snapshot_listings(self, snapshot_id: int) -> list[Listing]:
        rows = self._conn.execute(
            "SELECT * FROM listings WHERE snapshot_id = ? ORDER BY score DESC",
            (snapshot_id,),
        ).fetchall()
        return [self._row_to_listing(row) for row in rows]

    def get_scored_rows(self, snapshot_id: int) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM listings WHERE snapshot_id = ? ORDER BY score DESC",
            (snapshot_id,),
        ).fetchall()
        return [
            {
                "listing": self._row_to_listing(row),
                "score": row["score"],
                "coverage": row["coverage"],
                "why": row["why"],
                "params": json.loads(row["score_breakdown_json"] or "[]"),
                "valuation": json.loads(row["valuation_json"] or "{}"),
            }
            for row in rows
        ]

    def upsert_sales(self, sales: list[Sale]) -> None:
        # first_seen is intentionally excluded from the DO UPDATE SET clause: a
        # conflict means this mls_number was already recorded, so the original
        # discovery timestamp must survive re-upserts. Every other column is
        # refreshed from the new data.
        now = datetime.now().isoformat(timespec="seconds")
        for sale in sales:
            self._conn.execute(
                "INSERT INTO sold_history (mls_number, address, city, zip,"
                " subdivision, lat, lon, list_price, sold_price, sold_date,"
                " sold_price_per_sqft, sqft, beds, baths_full, year_built, lot_sqft,"
                " property_type, first_seen)"
                " VALUES (" + ",".join("?" * 18) + ")"
                " ON CONFLICT(mls_number) DO UPDATE SET"
                " address=excluded.address, city=excluded.city, zip=excluded.zip,"
                " subdivision=excluded.subdivision, lat=excluded.lat, lon=excluded.lon,"
                " list_price=excluded.list_price, sold_price=excluded.sold_price,"
                " sold_date=excluded.sold_date,"
                " sold_price_per_sqft=excluded.sold_price_per_sqft, sqft=excluded.sqft,"
                " beds=excluded.beds, baths_full=excluded.baths_full,"
                " year_built=excluded.year_built, lot_sqft=excluded.lot_sqft,"
                " property_type=excluded.property_type",
                (
                    sale.mls_number,
                    sale.address,
                    sale.city,
                    sale.zip,
                    sale.subdivision,
                    sale.lat,
                    sale.lon,
                    sale.list_price,
                    sale.sold_price,
                    sale.sold_date.isoformat(),
                    sale.sold_price_per_sqft,
                    sale.sqft,
                    sale.beds,
                    sale.baths_full,
                    sale.year_built,
                    sale.lot_sqft,
                    sale.property_type.value if sale.property_type else None,
                    now,
                ),
            )
        self._conn.commit()

    def upsert_actives(self, listings: list[Listing], seen_on: str | None = None) -> None:
        """Fold a refresh into the corpus.

        `first_seen` is excluded from the update clause so the original
        discovery date survives — it is the only record of how long something
        has been on the market once days_on_market resets on a relist.
        `last_seen` moves every time, and is what makes a listing that stopped
        appearing visibly stale rather than quietly wrong.
        """
        now = seen_on or datetime.now().isoformat(timespec="seconds")
        for listing in listings:
            garage = listing.garage
            self._conn.execute(
                "INSERT INTO active_listings (listing_id, mls_number, address, city, zip, subdivision, lat, lon, price, price_per_sqft, beds, baths_full, baths_half, sqft, lot_sqft, year_built, garage_spaces, garage_attached, garage_tags_json, hoa_monthly, property_type, duplex_scope, status, days_on_market, school_rating, tax_rate, appraisal_low, appraisal_high, url, flags_json, first_seen, last_seen)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(listing_id) DO UPDATE SET mls_number=excluded.mls_number, address=excluded.address, city=excluded.city, zip=excluded.zip, subdivision=excluded.subdivision, lat=excluded.lat, lon=excluded.lon, price=excluded.price, price_per_sqft=excluded.price_per_sqft, beds=excluded.beds, baths_full=excluded.baths_full, baths_half=excluded.baths_half, sqft=excluded.sqft, lot_sqft=excluded.lot_sqft, year_built=excluded.year_built, garage_spaces=excluded.garage_spaces, garage_attached=excluded.garage_attached, garage_tags_json=excluded.garage_tags_json, hoa_monthly=excluded.hoa_monthly, property_type=excluded.property_type, duplex_scope=excluded.duplex_scope, status=excluded.status, days_on_market=excluded.days_on_market, school_rating=excluded.school_rating, tax_rate=excluded.tax_rate, appraisal_low=excluded.appraisal_low, appraisal_high=excluded.appraisal_high, url=excluded.url, flags_json=excluded.flags_json, last_seen=excluded.last_seen",
                (
                    listing.listing_id,
                    listing.mls_number,
                    listing.address,
                    listing.city,
                    listing.zip,
                    listing.subdivision,
                    listing.lat,
                    listing.lon,
                    listing.price,
                    listing.price_per_sqft,
                    listing.beds,
                    listing.baths_full,
                    listing.baths_half,
                    listing.sqft,
                    listing.lot_sqft,
                    listing.year_built,
                    garage.spaces if garage else None,
                    None if garage is None or garage.attached is None else int(garage.attached),
                    json.dumps(list(garage.tags)) if garage else None,
                    listing.hoa.monthly_usd if listing.hoa else None,
                    listing.property_type.value if listing.property_type else None,
                    listing.duplex_scope.value if listing.duplex_scope else None,
                    listing.status,
                    listing.days_on_market,
                    listing.school_rating,
                    listing.tax_rate,
                    listing.appraisal.low if listing.appraisal else None,
                    listing.appraisal.high if listing.appraisal else None,
                    listing.url,
                    json.dumps(list(listing.flags)),
                    now,
                    now,
                ),
            )
        self._conn.commit()

    def tag_corpus_area(self, area: str, listing_ids: list[str]) -> None:
        for listing_id in listing_ids:
            self._conn.execute(
                "INSERT OR IGNORE INTO corpus_areas (area, listing_id) VALUES (?, ?)",
                (area.strip().lower(), listing_id),
            )
        self._conn.commit()

    def actives_in_area(self, area: str) -> list[Listing]:
        """Listings the most recent refresh of this area actually returned.

        A refresh is authoritative about its own area, so `last_seen` is
        compared against the area's own fetch date rather than a window: a row
        the latest refresh did not mention is not for sale there any more,
        whatever the cache still holds.
        """
        rows = self._conn.execute(
            "SELECT a.* FROM active_listings a"
            " JOIN corpus_areas c ON c.listing_id = a.listing_id"
            " JOIN corpus_fetches f ON f.area = c.area"
            " WHERE c.area = ? AND a.last_seen >= f.fetched_on",
            (area.strip().lower(),),
        ).fetchall()
        return [self._row_to_listing(row) for row in rows]

    def actives_near(
        self, lat: float, lon: float, miles: float, seen_since: str | None = None
    ) -> list[Listing]:
        """Corpus listings within `miles`, by real distance.

        Bounding box first, haversine second — the same shape as `sales_near`,
        because the two pools answer the same question about different data.
        """
        degrees = miles / 55.0
        # An asking comp has to still be asking. A row last seen before the
        # cutoff may have sold or been withdrawn, and pricing a house against
        # a listing that no longer exists is worse than having no comp at all.
        sql = (
            "SELECT * FROM active_listings"
            " WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?"
        )
        params = [lat - degrees, lat + degrees, lon - degrees, lon + degrees]
        if seen_since is not None:
            sql += " AND last_seen >= ?"
            params.append(seen_since)
        rows = self._conn.execute(sql, params).fetchall()
        found = []
        for row in rows:
            if row["lat"] is None or row["lon"] is None:
                continue
            if haversine_miles(lat, lon, row["lat"], row["lon"]) > miles:
                continue
            found.append(self._row_to_listing(row))
        return found

    def corpus_fetched_on(self, area: str) -> str | None:
        row = self._conn.execute(
            "SELECT fetched_on FROM corpus_fetches WHERE area = ?",
            (area.strip().lower(),),
        ).fetchone()
        return row["fetched_on"] if row else None

    def record_corpus_fetch(self, area: str, fetched_on: str) -> None:
        self._conn.execute(
            "INSERT INTO corpus_fetches (area, fetched_on) VALUES (?, ?)"
            " ON CONFLICT(area) DO UPDATE SET fetched_on = excluded.fetched_on",
            (area.strip().lower(), fetched_on),
        )
        self._conn.commit()

    def sold_fetched_on(self, area: str) -> str | None:
        """The date the sold leg last ran for this area, or None.

        Keyed on the area string the vendor was actually asked for, not on the
        listings that came back: the question asked is what can be repeated,
        and two searches naming the same area share the answer.
        """
        row = self._conn.execute(
            "SELECT fetched_on FROM sold_fetches WHERE area = ?",
            (area.strip().lower(),),
        ).fetchone()
        return row["fetched_on"] if row else None

    def record_sold_fetch(self, area: str, fetched_on: str) -> None:
        self._conn.execute(
            "INSERT INTO sold_fetches (area, fetched_on) VALUES (?, ?)"
            " ON CONFLICT(area) DO UPDATE SET fetched_on = excluded.fetched_on",
            (area.strip().lower(), fetched_on),
        )
        self._conn.commit()

    def sales_near(
        self, lat: float, lon: float, miles: float, since: date
    ) -> list[Sale]:
        # A generous bounding box first, then exact distance in Python.
        degrees = miles / 55.0
        rows = self._conn.execute(
            "SELECT * FROM sold_history WHERE sold_date >= ?"
            " AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?",
            (since.isoformat(), lat - degrees, lat + degrees, lon - degrees, lon + degrees),
        ).fetchall()

        sales = []
        for row in rows:
            if row["lat"] is None or row["lon"] is None:
                continue
            if haversine_miles(lat, lon, row["lat"], row["lon"]) > miles:
                continue
            sales.append(
                Sale(
                    mls_number=row["mls_number"],
                    sold_price=row["sold_price"],
                    sold_date=date.fromisoformat(row["sold_date"]),
                    address=row["address"],
                    city=row["city"],
                    zip=row["zip"],
                    subdivision=row["subdivision"],
                    lat=row["lat"],
                    lon=row["lon"],
                    list_price=row["list_price"],
                    sold_price_per_sqft=row["sold_price_per_sqft"],
                    sqft=row["sqft"],
                    beds=row["beds"],
                    baths_full=row["baths_full"],
                    year_built=row["year_built"],
                    lot_sqft=row["lot_sqft"],
                    property_type=PropertyType(row["property_type"])
                    if row["property_type"]
                    else None,
                )
            )
        return sales

    def recent_snapshots(self, saved_search: str, limit: int = 2) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM snapshots WHERE saved_search = ?"
            " ORDER BY id DESC LIMIT ?",
            (saved_search, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def saved_search_keys(self) -> list[str]:
        rows = self._conn.execute(
            "SELECT DISTINCT saved_search FROM snapshots ORDER BY saved_search"
        ).fetchall()
        return [row["saved_search"] for row in rows]

    def get_snapshot(self, snapshot_id: int) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM snapshots WHERE id = ?", (snapshot_id,)
        ).fetchone()
        return dict(row) if row is not None else None

    def latest_snapshots(self) -> list[dict]:
        # id, run_at and item_count are correlated by insertion order EXCEPT
        # item_count, which can legitimately shrink between runs. Selecting
        # the whole row for the newest id per saved_search (rather than
        # aggregating each column independently with MAX()) is what makes
        # item_count reflect the latest run instead of the historical max.
        rows = self._conn.execute(
            "SELECT * FROM snapshots WHERE id IN"
            " (SELECT MAX(id) FROM snapshots GROUP BY saved_search)"
            " ORDER BY saved_search"
        ).fetchall()
        return [dict(row) for row in rows]

    def previous_snapshot_id(self, saved_search: str, before_id: int) -> int | None:
        row = self._conn.execute(
            "SELECT id FROM snapshots WHERE saved_search = ? AND id < ?"
            " ORDER BY id DESC LIMIT 1",
            (saved_search, before_id),
        ).fetchone()
        return int(row["id"]) if row is not None else None


def _valuation_to_json(valuation: Valuation) -> dict:
    data = asdict(valuation)
    appraisal = data.get("appraisal_district")
    if appraisal is not None:
        data["appraisal_district"] = {"low": appraisal["low"], "high": appraisal["high"]}
    return data
