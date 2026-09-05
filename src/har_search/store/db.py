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

    def init_schema(self) -> None:
        self._conn.executescript(SCHEMA_PATH.read_text())
        self._conn.commit()

    def create_snapshot(
        self,
        saved_search: str,
        source: str,
        item_count: int,
        excluded_count: int,
        exclusions: dict,
    ) -> int:
        cursor = self._conn.execute(
            "INSERT INTO snapshots (saved_search, run_at, source, item_count,"
            " excluded_count, exclusions_json) VALUES (?, ?, ?, ?, ?, ?)",
            (
                saved_search,
                datetime.now().isoformat(timespec="seconds"),
                source,
                item_count,
                excluded_count,
                json.dumps(exclusions),
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
        for item in scored:
            listing = item.listing
            valuation = valuations.get(listing.listing_id, Valuation())
            self._conn.execute(
                "INSERT OR REPLACE INTO listings (snapshot_id, listing_id, mls_number,"
                " address, city, zip, subdivision, lat, lon, price, price_per_sqft,"
                " beds, baths_full, baths_half, sqft, lot_sqft, year_built,"
                " garage_spaces, hoa_monthly, property_type, duplex_scope, status,"
                " days_on_market, school_rating, tax_rate, appraisal_low,"
                " appraisal_high, url, score, coverage, why, score_breakdown_json,"
                " valuation_json, flags_json)"
                " VALUES (" + ",".join("?" * 34) + ")",
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
                    listing.garage.spaces if listing.garage else None,
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
            garage=GarageInfo(spaces=row["garage_spaces"])
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
        now = datetime.now().isoformat(timespec="seconds")
        for sale in sales:
            self._conn.execute(
                "INSERT OR REPLACE INTO sold_history (mls_number, address, city, zip,"
                " subdivision, lat, lon, list_price, sold_price, sold_date,"
                " sold_price_per_sqft, sqft, beds, baths_full, year_built, lot_sqft,"
                " property_type, first_seen)"
                " VALUES (" + ",".join("?" * 18) + ")",
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


def _valuation_to_json(valuation: Valuation) -> dict:
    data = asdict(valuation)
    appraisal = data.get("appraisal_district")
    if appraisal is not None:
        data["appraisal_district"] = {"low": appraisal["low"], "high": appraisal["high"]}
    return data
