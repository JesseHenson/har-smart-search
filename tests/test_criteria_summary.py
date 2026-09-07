from har_search.core.labels import criteria_summary
from har_search.core.models import Criteria


def test_summary_leads_with_area_and_lists_only_stated_criteria():
    """The run header answers "what did I ask for?".

    A saved search is named by a hash of its criteria, so the page title
    alone ("Katy #f8023fe1") tells the reader nothing about what produced
    the list. Unstated criteria are omitted rather than shown as blanks:
    the absence of a bedroom target is not a bedroom target of zero.
    """
    summary = criteria_summary(
        Criteria(area="Katy", beds=3, baths=2, sqft=1800, max_price=350_000)
    )

    assert summary == "Katy · 3 bd · 2 ba · 1,800 sqft · under $350,000"


def test_area_alone_is_a_valid_summary():
    assert criteria_summary(Criteria(area="Spring")) == "Spring"


def test_budget_reads_as_a_ceiling_not_a_target():
    """`max_price` is soft — listings above it still rank. "under" is the
    honest word; "at" would suggest a filter that does not exist.
    """
    summary = criteria_summary(Criteria(area="Katy", max_price=350_000))

    assert summary == "Katy · under $350,000"


def test_price_per_sqft_and_optional_criteria_are_included_when_given():
    summary = criteria_summary(
        Criteria(
            area="Katy",
            max_price_per_sqft=160,
            no_hoa=True,
            max_age_years=15,
            property_types=["single_family"],
        )
    )

    # Age is phrased relative, not as a year: "built since 2011" would make
    # this assertion depend on the calendar and quietly rot every January.
    assert summary == (
        "Katy · under $160/sqft · single-family · no HOA · under 15 years old"
    )


def test_it_accepts_the_stored_dict_form():
    """Criteria come back out of the database as JSON, not as a dataclass."""
    summary = criteria_summary({"area": "Katy", "beds": 4})

    assert summary == "Katy · 4 bd"
