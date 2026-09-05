"""The only outward-facing layer.

Recon established three possible data paths — a licensed MLS feed, managed
scraping vendors, or nothing viable. We build on a vendor today because the
prospect's MLS status is unknown. When that answer arrives, a new adapter
lands here and nothing above it changes.
"""

from __future__ import annotations

from typing import Protocol

from har_search.core.models import Criteria


class ListingSource(Protocol):
    name: str

    def fetch_for_sale(self, criteria: Criteria, limit: int) -> list[dict]: ...

    def fetch_sold(self, area: str, agent_depth: int = 25, limit: int = 200) -> list[dict]: ...
