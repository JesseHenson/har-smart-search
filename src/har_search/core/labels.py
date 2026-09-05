"""Machine tokens into English, in one place.

Every value in this module is an internal identifier that would otherwise
reach the user's screen verbatim: parameter names like `max_price_per_sqft`,
`Literal` tokens like `single_source` and `comp_basis="asking"`, exclusion
reason keys like `price_below_floor`, and diff classifications like
`PRICE_CUT`. Rendering them raw produced lines such as "no price_per_sqft",
"Sources single_source." and a footer reading `{"lease": 6,
"price_below_floor": 1}`.

The identifiers themselves stay machine-readable everywhere they are stored,
compared or serialized. This module is the single boundary where they become
prose, so a new token cannot leak onto a screen by being added somewhere that
happened to render it directly.

Pure: no imports, no state. `core` may not depend on `server`, `web`, `store`
or `sources`, and both of those layers depend on this.
"""

from __future__ import annotations

# --- Scoring parameters --------------------------------------------------

PARAM_LABELS: dict[str, str] = {
    "area": "location",
    "max_price": "price",
    "max_price_per_sqft": "price per sqft",
    "beds": "beds",
    "baths": "baths",
    "sqft": "size",
    "garage_spaces": "garage",
    "max_age_years": "age",
    "property_types": "property type",
    "no_hoa": "HOA",
    "min_school_rating": "school rating",
}


def param_label(name: str) -> str:
    """The English name of a scoring parameter."""
    return PARAM_LABELS.get(name, name.replace("_", " "))


def unknown_detail(name: str) -> str:
    """What to show when a listing does not publish a requested parameter."""
    return f"{param_label(name)} not published"


# --- Valuation basis (spec 6.1 tier 4) -----------------------------------

# The asking-basis wording carries a real limitation, not just a label. The
# tier-4 pool is this run's own scored listings, which survived a vendor bound
# of budget x 1.25, a result limit and the `must` gate. Every asking-basis
# estimate is therefore computed against a pool truncated near the user's
# budget, which biases estimates downward and makes pricier candidates look
# systematically overpriced. Refetching an unbounded pool is a cost and design
# change; saying so plainly is not.
BASIS_PHRASES: dict[str, str] = {
    "sold": "closed sales",
    "asking": "asking prices of listings inside your searched budget range",
    "none": "no comparable sales",
}

BASIS_NOTES: dict[str, str] = {
    "sold": "Based on closed sales nearby.",
    "asking": (
        "Based on asking prices, not closed sales — and only on listings inside"
        " the budget range you searched, not the open market. Estimates from"
        " this basis run low, so a pricier property can look more overpriced"
        " than it is."
    ),
    "none": "No comparable sales were found, so no estimate was produced.",
}


def basis_phrase(comp_basis: str | None) -> str:
    """A short noun phrase naming what the estimate rests on."""
    return BASIS_PHRASES.get(comp_basis or "none", "no comparable sales")


def basis_note(comp_basis: str | None) -> str:
    """A full sentence stating what the estimate rests on, and its limits."""
    return BASIS_NOTES.get(comp_basis or "none", BASIS_NOTES["none"])


# --- Confidence (spec 6.3) ----------------------------------------------

CONFIDENCE_PHRASES: dict[str, str] = {
    "high": "high confidence",
    "medium": "medium confidence",
    "low": "low confidence",
    "insufficient": "not enough evidence for an estimate",
}


def confidence_phrase(confidence: str | None) -> str:
    return CONFIDENCE_PHRASES.get(confidence or "insufficient", "unknown confidence")


# --- Valuation spread (spec 6.4) -----------------------------------------

SPREAD_PHRASES: dict[str, str] = {
    "clustered": (
        "Our estimate and the county appraisal district agree within 10%."
    ),
    "scattered": (
        "Our estimate and the county appraisal district disagree by more than"
        " 10% — the disagreement is the signal, so this one is worth a closer"
        " look."
    ),
    "single_source": (
        "Only one source of value is available for this property, so there is"
        " nothing to cross-check the estimate against."
    ),
}


def spread_phrase(spread_flag: str | None) -> str:
    return SPREAD_PHRASES.get(spread_flag or "single_source", SPREAD_PHRASES["single_source"])


def evidence_phrase(comp_count: int | None, comp_basis: str, confidence: str) -> str:
    """The evidence line that sits beside every estimate: "6 closed sales, medium confidence"."""
    count = comp_count or 0
    noun = basis_phrase(comp_basis)
    if comp_basis in (None, "none") or count == 0:
        return f"No comparable sales found — {confidence_phrase(confidence)}"
    return f"{count} comparable {noun}, {confidence_phrase(confidence)}"


# --- Data-quality exclusions (spec 4.2) ----------------------------------

# (singular, plural) so a count of 1 does not read "1 lease listings".
EXCLUSION_PHRASES: dict[str, tuple[str, str]] = {
    "lease": ("lease listing", "lease listings"),
    "price_below_floor": (
        "row priced below the $10,000 sale floor",
        "rows priced below the $10,000 sale floor",
    ),
    "missing_sold_price": ("row with no sold price", "rows with no sold price"),
    "missing_sold_date": (
        "row with an unreadable sold date",
        "rows with an unreadable sold date",
    ),
    "unknown": ("unrecognized row", "unrecognized rows"),
}


def exclusion_phrase(reason: str, count: int) -> str:
    singular, plural = EXCLUSION_PHRASES.get(
        reason, (reason.replace("_", " "), reason.replace("_", " "))
    )
    return f"{count} {singular if count == 1 else plural}"


def describe_exclusions(exclusions: dict | None) -> str:
    """Render an exclusion counter as prose. Empty input renders as empty."""
    if not exclusions:
        return ""
    return ", ".join(
        exclusion_phrase(reason, count)
        for reason, count in sorted(exclusions.items())
        if count
    )


# --- Diff classifications (spec 7.2) -------------------------------------

CHANGE_PHRASES: dict[str, str] = {
    "NEW": "New",
    "PRICE_CUT": "Price cut",
    "PRICE_UP": "Price increase",
    "GONE": "Off the market",
    "UNCHANGED": "Unchanged",
}


def change_phrase(change_type: str) -> str:
    return CHANGE_PHRASES.get(change_type, change_type.replace("_", " ").capitalize())
