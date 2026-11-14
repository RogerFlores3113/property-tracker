"""Cycle 15, group G4: lease dates, address, title, commute text and the shared notes code. Each phrasing pins exact values."""
import pytest

from prophelper import money
from prophelper.mcp_server import _extra_facts
from prophelper.parsers import amounts_all_placed, note_amounts_placed, parse_listing, reader_notes_for


def _lease(text):
    r = parse_listing(text)
    return {k: r.get(k) for k in ("lease_months", "lease_start", "lease_end")}, r.get("found_in_listing", "")


# ---- lease dates
def test_twelve_month_lease_starting():
    got, notes = _lease("Rent $1,500/mo. 12 month lease starting 3/1/2027.")
    assert got == {"lease_months": 12, "lease_start": "2027-03-01", "lease_end": None}
    assert notes == ""


def test_lease_through_with_no_start_gives_end_only():
    got, notes = _lease("Rent $1,500/mo. Lease through 2/28/2028.")
    assert got == {"lease_months": None, "lease_start": None, "lease_end": "2028-02-28"}
    assert "no start date" in notes and "left empty" in notes


def test_lease_ends_month_name():
    got, _ = _lease("Rent $1,500/mo. Lease ends Feb 28, 2027")
    assert got["lease_end"] == "2027-02-28" and got["lease_months"] is None


def test_lease_end_with_known_start_gives_months():
    got, notes = _lease("Rent $1,500/mo. Available 3/1/2027. Lease ends Feb 28, 2028.")
    assert got == {"lease_months": 12, "lease_start": None, "lease_end": "2028-02-28"}
    assert notes == ""


def test_lease_end_not_whole_months_leaves_months_empty():
    got, _ = _lease("Rent $1,500/mo. Available 3/15/2027. Lease ends 2/28/2028.")
    assert got["lease_months"] is None and got["lease_end"] == "2028-02-28"


def test_lease_end_without_year_is_not_guessed():
    got, _ = _lease("Rent $1,500/mo. Lease ends Feb 28")
    assert got["lease_end"] is None


def test_day_month_year_date():
    r = parse_listing("Rent $1,500/mo. Available 15-Jan-2027.")
    assert r["available_from"] == "2027-01-15"
    r = parse_listing("Rent $1,500/mo\nMove-in: 15 January 2027")
    assert r["available_from"] == "2027-01-15"


def test_thirteen_months_alone():
    assert parse_listing("Pilsen 1BR\nRent $1,900/mo\n13 months\nCats ok")["lease_months"] == 13
    assert parse_listing("Rent $1,500/mo. 13 months.")["lease_months"] == 13


def test_bare_months_not_read_from_a_deal_or_a_list():
    assert "lease_months" not in parse_listing("Rent $1,500/mo\n2 months\nfree rent")
    assert "lease_months" not in parse_listing("Rent $1,500/mo\n9 months\n12 months")


def test_two_lengths_offered_leaves_months_empty_with_note():
    got, notes = _lease("Rent $1,500/mo\nLease: Aug 1 2027 - Feb 28 2028 (7 months), or full year")
    assert got["lease_months"] is None and got["lease_end"] is None
    assert got["lease_start"] == "2027-08-01"
    assert "two lease lengths (7 months or a full year)" in notes


def test_whole_year_range_still_reads():
    got, _ = _lease("Rent $1,500/mo\nLease: Aug 1 2027 to Jul 31 2028")
    assert got["lease_months"] == 12 and got["lease_start"] == "2027-08-01"


# ---- address and title
def test_address_comma_before_zip():
    r = parse_listing("Cypress Run\n123 Oak St, Maple Grove, CA, 94063\n$1,500/mo 1 bed")
    assert (r["address"], r["city"], r["state"], r["zip"]) == ("123 Oak St", "Maple Grove", "CA", "94063")


def test_city_line_comma_before_zip():
    r = parse_listing("Sunny place\nMaple Grove, CA, 94063\n$1,500/mo")
    assert (r["city"], r["state"], r["zip"]) == ("Maple Grove", "CA", "94063")


@pytest.mark.parametrize("text,title", [
    ("**Sunny 2BR in Edgewater**\n$1,900/mo | 2 bd 1 ba", "Sunny 2BR in Edgewater"),
    ("# Sunny 2BR in Edgewater\n$1,900/mo", "Sunny 2BR in Edgewater"),
    ("## Sunny 2BR in Edgewater - $1,900/mo\n2 bd", "Sunny 2BR in Edgewater"),
    ("**Sunny 2BR in Edgewater, steps from the lake.** $1,900/mo", "Sunny 2BR in Edgewater, steps from the lake"),
    ("> **Sunny 2BR in Edgewater**\n$1,900/mo", "Sunny 2BR in Edgewater"),
    ("1. **Sunny 2BR in Edgewater**\n$1,900/mo", "Sunny 2BR in Edgewater"),
    ("**Sunny 2BR in Edgewater**", "Sunny 2BR in Edgewater"),
])
def test_markdown_title(text, title):
    assert parse_listing(text)["title"] == title


# ---- commute claims
@pytest.mark.parametrize("claim", ["12 min bike to Siebel", "14 min bike to the Quad"])
def test_commute_claim_is_a_note_not_a_field(claim):
    r = parse_listing(f"Foundry Apts $1,500/mo 1 bed. {claim}. Great spot.")
    assert f'"{claim}"' in r["found_in_listing"]
    assert "no commute is filled in" in r["found_in_listing"]
    assert not any(k.startswith("commute") for k in r)
    assert not money.listing_notes_uncounted(r["found_in_listing"])  # a commute claim never sets the money tag


# ---- stale and optional notes
STALE = 'The listing also says "electric avg $60, gas avg $45". It is a monthly fee and it is not counted anywhere. Check what it is for.'


def test_general_check_amounts_placed():
    assert amounts_all_placed({60.0, 45.0}, {105.0})
    assert amounts_all_placed({60.0}, {60.0, 400.0})
    assert not amounts_all_placed({60.0, 45.0}, {45.0})
    assert not amounts_all_placed(set(), {45.0})


def test_stale_note_does_not_set_the_tag_when_every_amount_is_a_field():
    place = {"utilities_estimate": 105, "price": 1800}
    assert money.listing_notes_uncounted(STALE) is True
    assert money.listing_notes_uncounted(STALE, place) is False
    assert money.listing_notes_uncounted(STALE, {"utilities_estimate": 45}) is True  # $60 is still not counted
    assert note_amounts_placed(STALE, place)


def test_stale_pet_rent_and_move_in_fee_notes():
    pet = 'The listing also says "pet rent $50". It is a monthly fee and it is not counted anywhere. Check what it is for.'
    fee = 'The listing also says "$400 move-in fee". It is a one-time cost, so it is not in the monthly cost. Check what it is for.'
    assert not money.listing_notes_uncounted(pet, {"pet_rent": 50})
    assert money.listing_notes_uncounted(pet, {"pet_rent": 40})
    assert not money.listing_notes_uncounted(fee, {"move_in_fees": 400})


def test_total_cost_tag_follows_the_fields():
    place = {"price": 1800, "utilities_estimate": 105, "reader_notes": STALE, "pets": "", "tenant_pays": "electric, gas"}
    assert money.LISTING_NOTES_UNCOUNTED not in money.true_monthly_cost(place)["uncounted"]
    place["utilities_estimate"] = 45
    assert money.LISTING_NOTES_UNCOUNTED in money.true_monthly_cost(place)["uncounted"]


def test_saved_note_refresh_drops_a_note_whose_amounts_are_in_fields():
    text = "East Garfield Park 2BR $1,800/mo\nMove-in fee $400. Optional pool membership $25/month."
    place = {"listing_text": text, "price": 1800, "move_in_fees": 400}
    notes = reader_notes_for(place)
    assert "$400" not in notes


def test_optional_pool_and_carport_fees_never_set_the_tag():
    r = parse_listing("Hawthorn 1BR $1,400/mo. Optional pool membership: $25/month.")
    assert "looks optional" in r["found_in_listing"] and "not counted anywhere" not in r["found_in_listing"]
    assert not money.listing_notes_uncounted(r["found_in_listing"])
    r = parse_listing("Alder 1BR $1,400/mo. Carport optional, $50/month.")
    assert not money.listing_notes_uncounted(r["found_in_listing"])
    assert money.listing_notes_uncounted('The listing also says "Pool fee $25/month required". It is a monthly fee and it is not counted anywhere. Check what it is for.')


def test_pet_line_not_quoted_again_once_read():
    r = parse_listing("Willow Court\n1 bed 1 bath $1,500/mo\nSecurity deposit $1,500.\nCats and dogs welcome: $350 deposit, $35/mo pet rent per pet, max 2, 50 lb limit.", pet_kind="both")
    assert (r["pets"], r["pet_rent"], r["pet_deposit"], r["pet_count_limit"], r["pet_weight_limit"], r["deposit"]) == ("both", 35, 350, 2, 50, 1500)
    # cycle 15 join: G3 adds a per-pet note for "per pet"; the pet line itself is not quoted again
    assert r.get("found_in_listing", "") in ("", "Pet rent is $35 a month for each pet, so with more than one pet it adds up.")


# ---- rentals never say "Buyer details"
def test_rental_gets_listing_label_not_buyer_label():
    rent = _extra_facts({"days_on_market": 14, "cost": {"mode": "rent"}})
    assert rent == ["Listing details: 14 days on the market"]
    assert _extra_facts({"days_on_market": 14, "cost": {"mode": "buy"}}) == ["Buyer details: 14 days on the market"]
