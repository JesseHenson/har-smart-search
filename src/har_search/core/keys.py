"""Snapshot identity.

A snapshot bucket is what `whats_new` diffs against, so two runs land in the
same bucket only if they asked the same question. Keying on the area string
alone put `beds=3, max_price=200k` and `beds=5, max_price=600k` in Spring into
one bucket, and the diff then reported every listing in each as NEW or GONE.

The key is the area the user recognises plus a short stable hash of the whole
normalized criteria, so it still reads as a place name in the dashboard while
keeping distinct searches apart.
"""

from __future__ import annotations

import hashlib
import json

from har_search.core.models import Criteria

KEY_HASH_LENGTH = 8
KEY_SEPARATOR = "#"


def _normalized(criteria: Criteria) -> dict:
    """A canonical view of the criteria, stable across list and dict ordering.

    `must` and `property_types` are sorted because they are sets in meaning but
    lists in the type; `weights` is sorted by key. Without that, two identical
    searches whose lists arrived in a different order would hash differently
    and silently split into two buckets — the same defect in the other
    direction.
    """
    return {
        "area": (criteria.area or "").strip().lower(),
        "beds": criteria.beds,
        "baths": criteria.baths,
        "garage_spaces": criteria.garage_spaces,
        "sqft": criteria.sqft,
        "max_price": criteria.max_price,
        "max_price_per_sqft": criteria.max_price_per_sqft,
        "property_types": sorted(criteria.property_types or []),
        "no_hoa": criteria.no_hoa,
        "max_age_years": criteria.max_age_years,
        "min_school_rating": criteria.min_school_rating,
        "must": sorted(criteria.must or []),
        "weights": dict(sorted((criteria.weights or {}).items())),
    }


def criteria_digest(criteria: Criteria) -> str:
    """A short, stable, deterministic digest of the criteria."""
    payload = json.dumps(_normalized(criteria), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:KEY_HASH_LENGTH]


def _display_area(area: str | None) -> str:
    """The human-readable half of the key, normalized so that capitalization
    and surrounding whitespace cannot split one search into several buckets.

    The digest already folds the area to lowercase for comparison, so this is
    purely cosmetic — but 'Spring', ' spring ', and 'SPRING' must render as the
    same bucket, not three. Title-casing reads well for place names ("spring
    branch" -> "Spring Branch") without mangling a ZIP code, which has no
    letters for `.title()` to touch.
    """
    stripped = (area or "").strip()
    if not stripped:
        return "search"
    return stripped.title()


def snapshot_key(criteria: Criteria) -> str:
    """The saved-search key a run's snapshot is filed under."""
    return f"{_display_area(criteria.area)} {KEY_SEPARATOR}{criteria_digest(criteria)}"


def resolve_saved_search(name: str, known_keys: list[str]) -> tuple[str | None, str | None]:
    """Resolve what the user or model typed to one stored snapshot key.

    Returns (key, error). Keys carry a hash the model has no way to invent, so
    `search` returns the key it used and this accepts either that key verbatim
    or the bare area name when it is unambiguous. An ambiguous area is an
    error naming the candidates, never a silent pick — picking wrong here
    produces a diff between two unrelated searches, which is the defect this
    key exists to prevent.
    """
    wanted = (name or "").strip()
    if not wanted:
        return None, "No saved search name given."
    if wanted in known_keys:
        return wanted, None

    lowered = wanted.lower()
    candidates = [
        key
        for key in known_keys
        if key.lower() == lowered
        or key.lower().split(f" {KEY_SEPARATOR}")[0] == lowered
    ]
    if len(candidates) == 1:
        return candidates[0], None
    if not candidates:
        return None, (
            f"No saved search matches {wanted!r}."
            + (f" Known searches: {', '.join(known_keys)}." if known_keys else "")
        )
    return None, (
        f"{wanted!r} matches more than one saved search in that area:"
        f" {', '.join(candidates)}. Use the full key that `search` returned."
    )
