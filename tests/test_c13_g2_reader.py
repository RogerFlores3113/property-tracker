"""Cycle 13, group G2: rent, dates, rooms, lease, titles and parking reader (panel phrasings from the cycle 12 notes)."""
from __future__ import annotations

import pytest

from prophelper.parsers import parse_listing


def notes(r):
    return r.get("found_in_listing", "")


# ---- 1. optional parking after the amount -------------------------------------------------------------------------------

@pytest.mark.parametrize("line", ["Parking $100 per month optional", "Heated garage, $130 a month, optional", "Garage available, $90"])
def test_optional_parking_is_a_note_not_a_cost(line):
    r = parse_listing(f"Sunny 1BR near campus\n$1,500/mo\n{line}\n")
    assert r["price"] == 1500 and r["beds"] == 1
    assert "parking_cost" not in r
    assert "optional" in notes(r) and "not counted in the monthly cost" in notes(r)
    assert "not counted anywhere" not in notes(r)


def test_optional_parking_amounts_in_notes():
    assert "$100 a month" in notes(parse_listing("Sunny 1BR\n$1,500/mo\nParking $100 per month optional\n"))
    n = notes(parse_listing("Sunny 1BR\n$1,500/mo\nHeated garage, $130 a month, optional\n"))
    assert "A garage is available for $130 a month" in n


def test_required_parking_after_amount_still_counts():
    r = parse_listing("Sunny 1BR\n$1,500/mo\nParking $100 per month required\n")
    assert r["parking_cost"] == 100


def test_one_reserved_parking_space_included_is_free():
    r = parse_listing("Short North 1BR\n$1,500/mo\nOne reserved parking space included\n")
    assert r["parking_cost"] == 0 and r["parking"] == "lot"
    assert "parking" not in notes(r).lower()


# ---- 2. dates -----------------------------------------------------------------------------------------------------------

def test_month_only_move_in_never_invents_a_day():
    r = parse_listing("Foundry Row 1BR\n$1,575/mo\nMove in Aug 2027. 12 month lease.\n")
    assert "available_from" not in r
    assert r["lease_months"] == 12
    assert "Aug 2027" in notes(r) and "no day" in notes(r)


def test_month_only_variants():
    for line in ("Available August 2027", "Move-in: Aug 2027", "Date available: September 2027"):
        r = parse_listing(f"Foundry Row 1BR\n$1,575/mo\n{line}\n")
        assert "available_from" not in r, line
        assert "gives no day" in notes(r), line


def test_real_day_still_read():
    assert parse_listing("1BR\n$1,500/mo\nAvailable Aug 20 2027\n")["available_from"] == "2027-08-20"
    assert parse_listing("1BR\n$1,500/mo\nMove in Aug 1, 2027\n")["available_from"] == "2027-08-01"


@pytest.mark.parametrize("line", ["Lease: Aug 1 2027 to Jul 31 2028", "Lease dates Aug 1, 2027 - Jul 31, 2028", "Aug 1 2027 to Jul 31 2028"])
def test_lease_dates_read_start_and_twelve_months(line):
    r = parse_listing(f"Sunny 1BR\n$1,500/mo\n{line}\n")
    assert r["available_from"] == "2027-08-01"
    assert r["lease_months"] == 12
    assert r.get("title") != "Aug 1 2027 to Jul 31 2028"


def test_lease_dates_odd_span_gets_a_note():
    r = parse_listing("Sunny 1BR\n$1,500/mo\nLease: Aug 1 2027 to Jun 10 2028\n")
    assert r["available_from"] == "2027-08-01" and "lease_months" not in r
    assert "not a whole number of months" in notes(r)


# ---- 3. rent ------------------------------------------------------------------------------------------------------------

def test_dash_title_bedroom_price():
    r = parse_listing("Foundry Row - 1 Bedroom - $1,575\n123 Main St, Champaign, IL 61820\n")
    assert r["price"] == 1575 and r["beds"] == 1 and r["title"] == "Foundry Row"
    assert "not counted anywhere" not in notes(r) and "starting" not in notes(r)


def test_starting_at_in_dash_title_line():
    r = parse_listing("Foundry Row - Starting at $1,575\n1 bedroom, 1 bath\n")
    assert r["price"] == 1575 and r["title"] == "Foundry Row"
    assert "lowest unit price" in notes(r)


def test_dash_title_floor_plan_list_stays_unknown():
    r = parse_listing("Foundry Row\n1 Bedroom - $1,575\n2 Bedroom - $2,100\n")
    assert "price" not in r


def test_asking_worded_rent():
    r = parse_listing("Linden Park duplex\nAsking twenty-three hundred per month\n2 bed\n")
    assert r["price"] == 2300 and r["beds"] == 2


def test_was_price_is_a_reduction_not_an_uncounted_amount():
    r = parse_listing("Cozy place\nRent: $3,200 (was $3,400)\n2 bed\n")
    assert r["price"] == 3200
    assert "cut from $3,400" in notes(r)
    assert "not counted anywhere" not in notes(r) and "Check what it is for" not in notes(r)


def test_was_price_lower_than_rent_is_not_a_cut():
    r = parse_listing("Cozy place\nRent: $3,200 (was $2,900)\n2 bed\n")
    assert r["price"] == 3200 and "cut from" not in notes(r)


def test_headline_price_not_quoted_as_uncounted():
    for text in ("1BR 28 Oak Ln $1,730\nQuiet building near the park\n", "1BR 28 Oak Ln $1,730\nQuiet building\nPets: cats ok\nDeposit: $1,730\n"):
        r = parse_listing(text)
        assert r["price"] == 1730
        assert "1BR 28 Oak Ln" not in notes(r) and "not counted anywhere" not in notes(r)


def test_headline_price_not_quoted_when_price_is_already_saved():
    text = "1BR 28 Oak Ln $1,730\nQuiet building\n"
    r = parse_listing(text, current={"price": 1730})
    assert "1BR 28 Oak Ln" not in notes(r)


# ---- 4. rooms -----------------------------------------------------------------------------------------------------------

def test_listing_corrects_bedrooms_downward():
    r = parse_listing("Little Village\n$2,000/mo\nUpdated 3 bedroom (actually 2 bed plus den)\n")
    assert r["beds"] == 2
    assert "corrects itself" in notes(r)


def test_listing_corrects_bedrooms_upward_still_works():
    r = parse_listing("Duplex\n$2,000/mo\nOne-bedroom? no, THREE bedroom duplex\n")
    assert r["beds"] == 3 and "corrects itself" in notes(r)


def test_two_bath_in_words():
    r = parse_listing("Linden Park\n$2,300/mo\n3 bed two bath\n")
    assert r["beds"] == 3 and r["baths"] == 2


# ---- 5. lease choices ---------------------------------------------------------------------------------------------------

def test_lease_12_or_15_is_unknown_with_a_note():
    r = parse_listing("Family house\n$2,000/mo\n12 or 15 month lease\n")
    assert "lease_months" not in r
    assert "12 or 15 months" in notes(r)


def test_lease_terms_list():
    r = parse_listing("Westerville\n$2,000/mo\nLease terms 6, 12 or 15 months\n")
    assert "lease_months" not in r
    assert "6, 12 or 15 months" in notes(r)


def test_single_lease_and_deals_unchanged():
    assert parse_listing("Place\n$2,000/mo\n12 month lease\n")["lease_months"] == 12
    r = parse_listing("Place\n$2,000/mo\nLease: 12 months, 1 month free\n")
    assert r["lease_months"] == 12 and "more than one lease length" not in notes(r)
    r = parse_listing("Place\n$2,000/mo\nLease 12 months - 2 months free\n")
    assert "more than one lease length" not in notes(r)


# ---- 6. titles ----------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("line", ["Quarterly utility bill about $210", "Quarterly utility bill about", "Average electric is about $90"])
def test_money_line_is_never_a_title(line):
    r = parse_listing(f"{line}\n1 bed apartment\n$1,800/mo\n500 Elm St, Urbana, IL 61801\n")
    assert "bill about" not in r.get("title", "").lower() and "about" not in r.get("title", "").lower().split()
    assert r.get("title") == "1 bed apartment"
