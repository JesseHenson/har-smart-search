import pytest

from har_search.core.models import DuplexScope, PropertyType
from har_search.core.normalize import (
    canon_property_type,
    letter_to_score,
    parse_garage,
    parse_hoa,
    parse_lot,
    parse_money_abbrev,
    parse_unit_designator,
)


@pytest.mark.parametrize(
    "raw,spaces,attached",
    [
        ("2 Attached", 2, True),
        ("3 Attached ,Oversized ,Tandem", 3, True),
        ("2 Detached ,Oversized", 2, False),
        ("3 Attached", 3, True),
    ],
)
def test_parse_garage_extracts_spaces_and_attachment(raw, spaces, attached):
    garage = parse_garage(raw)
    assert garage is not None
    assert garage.spaces == spaces
    assert garage.attached is attached


def test_parse_garage_keeps_extra_tags():
    garage = parse_garage("3 Attached ,Oversized ,Tandem")
    assert garage.tags == ("oversized", "tandem")


def test_parse_garage_returns_none_for_missing():
    assert parse_garage(None) is None
    assert parse_garage("") is None


def test_parse_hoa_normalises_to_monthly():
    assert parse_hoa("$1075 Annually").monthly_usd == pytest.approx(89.583, abs=0.01)
    assert parse_hoa("$325 Monthly").monthly_usd == pytest.approx(325.0)


def test_parse_hoa_null_is_unknown_not_zero():
    """A missing fee means we do not know, never that there is no HOA."""
    assert parse_hoa(None) is None


def test_parse_lot_handles_sqft_and_acres():
    assert parse_lot("13,987 sqft") == 13_987
    assert parse_lot("1.1 acre(s)") == 47_916
    assert parse_lot("6,600 sqft") == 6_600


def test_parse_lot_treats_zero_as_unknown():
    assert parse_lot("0 sqft") is None
    assert parse_lot(None) is None


def test_parse_money_abbrev_preserves_imprecision():
    """The displayed figure is treated as truncated at its own precision,
    so the range always contains the true value."""
    rng = parse_money_abbrev("$1.0M")
    assert rng.low == 1_000_000
    assert rng.high == 1_099_999

    rng = parse_money_abbrev("$352K")
    assert rng.low == 352_000
    assert rng.high == 352_999


def test_parse_money_abbrev_returns_none_for_missing():
    assert parse_money_abbrev(None) is None


def test_parse_money_abbrev_fallback_handles_decimal_format():
    """Fallback path correctly parses decimal-formatted prices."""
    rng = parse_money_abbrev("$425,000.00")
    assert rng.low == 425_000
    assert rng.high == 425_000

    rng = parse_money_abbrev("$425,000")
    assert rng.low == 425_000
    assert rng.high == 425_000


def test_parse_money_abbrev_fallback_rejects_malformed():
    """Fallback path returns None for invalid/malformed input."""
    assert parse_money_abbrev("$") is None
    assert parse_money_abbrev("n/a") is None
    assert parse_money_abbrev("$$$") is None


def test_canon_property_type_catches_the_hyphen_trap():
    """'Single-Family' is a sale record; 'Single Family' is a lease record."""
    assert canon_property_type("Single-Family") == (PropertyType.SINGLE_FAMILY, False)
    assert canon_property_type("Single Family") == (PropertyType.SINGLE_FAMILY, True)


def test_canon_property_type_maps_multi_family_subtypes():
    assert canon_property_type("Multi-Family - Duplex") == (PropertyType.DUPLEX, False)
    assert canon_property_type("Multi-Family - Fourplex") == (PropertyType.FOURPLEX, False)
    assert canon_property_type("Multi-Family") == (PropertyType.MULTI_FAMILY, False)
    assert canon_property_type("Multi-Family - Multiple Detached Dw") == (
        PropertyType.MULTI_FAMILY,
        False,
    )
    assert canon_property_type("Townhouse/Condo - Townhouse") == (
        PropertyType.TOWNHOUSE_CONDO,
        False,
    )
    assert canon_property_type("Lots") == (PropertyType.LOTS, False)
    assert canon_property_type(None) == (None, False)


@pytest.mark.parametrize(
    "address,scope",
    [
        ("5013 Longmeadow St A/b", DuplexScope.WHOLE),
        ("8445 Furray Rd A/b", DuplexScope.WHOLE),
        ("214 E 32nd St C-d", DuplexScope.WHOLE),
        ("5058 Mallow St A-b", DuplexScope.WHOLE),
        ("7840 Nashville Unit A/b St", DuplexScope.WHOLE),
        ("2116 Berry St", DuplexScope.UNKNOWN),
        ("3204 Napoleon St", DuplexScope.UNKNOWN),
        (None, DuplexScope.UNKNOWN),
    ],
)
def test_parse_unit_designator(address, scope):
    assert parse_unit_designator(address) is scope


def test_letter_to_score_maps_har_ratings():
    assert letter_to_score("A") == 1.0
    assert letter_to_score("B") == 0.8
    assert letter_to_score("C") == 0.6
    assert letter_to_score("D") == 0.35
    assert letter_to_score("F") == 0.0
    assert letter_to_score(None) is None
    assert letter_to_score("N/A") is None
