"""Cycle 16, group G4: lease start dates, DW, the cost line's unknown list, stale notes, notes shown one per line."""
import pytest

from prophelper import compare, money
from prophelper.mcp_server import _extra_facts  # noqa: F401
from prophelper.money import note_units
from prophelper.parsers import note_amounts_placed, parse_listing


def _f(text, *keys):
    r = parse_listing("Rent $1,500/mo.\n" + text)
    return {k: r.get(k) for k in keys}, r.get("found_in_listing") or ""


LEASE = ("lease_months", "lease_start", "lease_end", "available_from")


@pytest.mark.parametrize("text,want", [
    ("Lease: 12 months, starting 1/15/2027", dict(lease_months=12, lease_start="2027-01-15", lease_end=None)),
    ("12 months lease starting Jan 15, 2027", dict(lease_months=12, lease_start="2027-01-15", lease_end=None)),
    ("13 months lease from 15-Jan-2027", dict(lease_months=13, lease_start="2027-01-15", lease_end=None)),
    ("13 month lease, begins 2027-01-15", dict(lease_months=13, lease_start="2027-01-15", lease_end=None)),
    ("Lease through 2/28/2028, starting 3/1/2027", dict(lease_months=12, lease_start="2027-03-01", lease_end="2028-02-28")),
    ("Lease ends Feb 28, 2028, starting March 1, 2027", dict(lease_months=12, lease_start="2027-03-01", lease_end="2028-02-28")),
    ("Lease starting 3/1/2027, 13 months.", dict(lease_months=13, lease_start="2027-03-01", lease_end=None)),
    ("Lease starting 3/1/2027, 13-month term", dict(lease_months=13, lease_start="2027-03-01", lease_end=None)),
])
def test_lease_start_phrasings(text, want):
    got, notes = _f(text, *LEASE)
    assert {k: got[k] for k in want} == want
    assert "no start date" not in notes


def test_move_in_date_before_the_label():
    got, _ = _f("15-JAN-2027 MOVE IN", *LEASE)
    assert got["available_from"] == "2027-01-15" and got["lease_months"] is None
    got, _ = _f("3/1/2027 move-in", *LEASE)
    assert got["available_from"] == "2027-03-01"


def test_available_then_lease_months_after_a_date():
    got, _ = _f("Available 3/1/2027, 13 month lease", *LEASE)
    assert got["lease_months"] == 13 and got["available_from"] == "2027-03-01"


def test_lease_end_alone_still_has_the_note():
    got, notes = _f("Lease through 2/28/2028.", *LEASE)
    assert got["lease_start"] is None and "no start date" in notes


def test_lease_choices_not_read_after_a_year():
    got, _ = _f("Lease terms 6, 12 or 15 months", *LEASE)
    assert got["lease_months"] is None


# ---- DW
@pytest.mark.parametrize("text,want", [("DW, hardwood floors", 1), ("W/D, DW", 1), ("In-unit W/D and DW", 1), ("No DW", 0), ("dishwasher", 1), ("Dowd Way, 2 bed", None)])
def test_dw_is_dishwasher(text, want):
    assert _f(text, "dishwasher")[0]["dishwasher"] == want


# ---- unknown list on the cost line
PILSEN = ("PILSEN ROW 3 BED 2 BATH | $3,200 | LANDLORD FEE: 1 MONTH'S RENT | INTERNET (XFINITY) $60/MO MANDATORY | HEAT INCL. | "
          "PARKING REQUIRED $120/MONTH | LEASE 13 MONTHS | AVAILABLE 15-JAN-2027 | 1800 W 18th St Chicago, IL, 60608")


def _place(text):
    r = parse_listing(text)
    p = dict(r)
    p["reader_notes"] = r.get("found_in_listing")
    p["listing_text"] = text
    return p


def test_counted_internet_is_not_missing():
    p = _place(PILSEN)
    assert p["other_monthly_fees"] == 60 and p["tenant_pays"] == "internet"
    c = money.true_monthly_cost(p)
    assert c["missing"] == [] and not any("internet" in u for u in c["uncounted"])
    p["cost"] = c
    assert not any("internet" in n for n in compare.cost_unknowns(p))


def test_internet_still_missing_when_not_counted():
    p = _place("Rent $1,500/mo. Tenant pays internet.")
    c = money.true_monthly_cost(p)
    assert "utilities estimate" in c["missing"]


def test_open_note_is_named():
    notes = 'The listing also says "Flat $75/mo amenity fee". It is a monthly fee and it is not counted anywhere. Check what it is for.'
    place = {"price": 1500, "reader_notes": notes}
    c = money.true_monthly_cost(place)
    assert c["listing_notes_label"] == "the $75 amenity fee in the listing notes"
    assert "the $75 amenity fee in the listing notes not counted yet" in c["headline"]
    place["cost"] = c
    assert "the $75 amenity fee in the listing notes" in compare.cost_unknowns(place)


def test_two_open_notes_name_both_amounts():  # c17: the label names the amounts instead of staying generic
    notes = ('The listing also says "Pool fee $25/month required". It is a monthly fee and it is not counted anywhere. Check what it is for. '
             'The listing also says "Valet trash $30/month required". It is a monthly fee and it is not counted anywhere. Check what it is for.')
    c = money.true_monthly_cost({"price": 1500, "reader_notes": notes})
    assert c["listing_notes_label"] == "the $25 and $30 amounts in the listing notes"


def test_no_open_note_no_tag():
    c = money.true_monthly_cost({"price": 1500, "reader_notes": "The trash and lawn flat fee is $30, counted once in other monthly fees."})
    assert "listing_notes_label" not in c and money.LISTING_NOTES_UNCOUNTED not in c["uncounted"]


# ---- stale notes
N = 'The listing also says "%s". It is not counted anywhere. Check what it is for.'


@pytest.mark.parametrize("quote,place,want", [
    ("HOA $300 per quarter", {"hoa": 100}, True),
    ("HOA dues $900 quarterly", {"hoa": 300}, True),
    ("HOA $1,200 per year", {"hoa": 100}, True),
    ("HOA $300 per quarter", {"hoa": 120}, False),
    ("Water $55, electric $70", {"utilities_estimate": 125}, True),
    ("Water $55, electric $70, gas $40", {"utilities_estimate": 165}, True),
    ("Water $55, electric $70", {"utilities_estimate": 100}, False),
    ("Water $55, electric $70, flat $48", {"utilities_estimate": 125, "other_monthly_fees": 48}, True),
    ("Water $55, electric $70, flat $48", {"utilities_estimate": 100, "other_monthly_fees": 48}, False),
])
def test_stale_note_check(quote, place, want):
    assert note_amounts_placed(N % quote, place) is want


# ---- notes one per line
def test_note_units_split_each_note():
    p = _place("Lakeview 3 bd - $3,290. Lease ends Feb 28, 2028. Garage $90 a month. Pool access $50/mo optional.")
    units = note_units(p["reader_notes"])
    assert len(units) >= 2 and all(u.endswith(".") for u in units)


def test_place_page_lists_notes_one_per_line(store):
    from conftest import local_client
    store.add_search("s")
    notes = "The garage is $90 a month. It looks optional. Ask if it is required. The pool is $50 a month, optional. Ask if it is required."
    place, _ = store.add_place(title="Lakeview", price=1500, reader_notes=notes)
    c = local_client(store)
    html = c.get(f"/places/{place['id']}").text
    section = html[html.index('id="listing-notes"'):]
    section = section[:section.index("</section>")]
    assert section.count("<li>") == 2 and "<li>The garage is $90 a month." in section
