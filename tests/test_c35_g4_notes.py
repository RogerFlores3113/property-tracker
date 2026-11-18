"""Cycle 35, G4: one note per line (roommates l7, nontech l14, nontech l4)."""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp_util import call, server, text  # noqa: E402

from prophelper import parsers as P  # noqa: E402

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel")


def fixture(name: str) -> str:
    with open(os.path.join(FIX, name), encoding="utf-8") as fh:
        return fh.read()


def read(t: str) -> dict:
    return P.parse_listing(t, "")


def notes(r: dict) -> str:
    return r.get("found_in_listing", "")


BASE = "3 Bed 2 Bath. 2300 N Clark St, Chicago, IL 60614. "


@pytest.mark.parametrize("line", [
    "$3,600 a month, $3,300 with concession",
    "Rent $3,600 a month ($3,300 with concession).",
    "Rent: $3,600/mo; $3,300/mo with concession",
    "$3,600 per month, or $3,300 with a concession",
    "$3,600 a month, $3,300 with the concession applied.",
    "Rent $3,600/mo. $3,300 with special.",
    "$3,600/mo | $3,300 w/ concession",
])
def test_a_rent_with_a_concession_gives_one_clear_note(line):
    r = read(BASE + line)
    assert r["price"] == 3600
    n = notes(r)
    assert "Only $3,300" not in n and "not counted anywhere" not in n, n
    assert "free-rent offer" not in n, n
    assert n.count("$3,300") == 1 and len([x for x in n.split("\n") if "$3,300" in x]) == 1, n
    assert "concession" in n and "$3,600" in n, n


def test_roommates_l7_whole_listing():
    r = read(fixture("r34-roommates-l7.txt"))
    assert r["price"] == 3600 and r["beds"] == 3 and r["baths"] == 2 and r["deposit"] == 2000 and r["application_fee"] == 40
    assert r["parking_cost"] == 225 and r["utilities_included"] == "gas" and r["lease_months"] == 13
    n = notes(r)
    assert "Only $3,300" not in n and n.count("$3,300") == 1, n
    assert "free-rent offer" not in n


def test_a_concession_that_is_months_free_keeps_its_own_note():
    r = read(BASE + "Rent $3,600/mo. 1 month free on a 13 month lease.")
    assert r["price"] == 3600
    assert "concession" in notes(r) and "one-time" in notes(r)


def test_a_lower_rent_for_a_longer_lease_is_not_a_concession():
    r = read(BASE + "Rent $3,600/mo for a 12 month lease, $3,300 for a 13 month lease.")
    assert "with a concession" not in notes(r)


@pytest.mark.parametrize("line", [
    "Quarterly assessment $90.",
    "Quarterly fee $90.",
    "Assessment $90 per quarter.",
    "Building assessment of $90 each quarter.",
    "$90 quarterly fee.",
    "Quarterly dues $90",
    "Assessment: $90 every quarter",
])
def test_a_quarterly_fee_gives_one_note(line):
    r = read("2 bedroom, 1 bath ranch. Rent: $1,380 per month. 8 Neil Ave, Columbus OH 43201. " + line)
    n = notes(r)
    assert n.count("$90") == 1 and len(n.split("\n")) == 1, n
    assert "(about $30 a month)" in n and "not counted in the monthly cost" in n, n
    assert "assessment of $30" not in n and "not counted anywhere" not in n


def test_nontech_l14_quarterly_in_the_reply_headline(store):
    store.add_search("T", "rent")
    srv = server(store)
    out = text(call(srv, "add_place", listing_text=fixture("r34-nontech-l14.txt")))
    assert out.count("$90") == 1, out
    assert "the $30 assessment" not in out and "$30 assessment" not in out, out
    assert "missing: electric and gas" in out


def test_nontech_l14_whole_listing():
    r = read(fixture("r34-nontech-l14.txt"))
    assert r["price"] == 1380 and r["beds"] == 2 and r["baths"] == 1 and r["deposit"] == 2070
    assert r["tenant_pays"] == "electric, gas" and r["utilities_included"] == "water"
    assert "dogs" in notes(r) or "no dogs" in notes(r)
    assert "$30 a month" in notes(r) and "assessment of $30" not in notes(r)


def test_a_condo_fee_per_quarter_is_not_given_a_second_quarterly_note():
    r = read("2 bedroom condo. Rent: $1,380 per month. Condo fee $270 per quarter. 8 Neil Ave, Columbus OH 43201.")
    assert "quarterly fee of $270" not in notes(r)


@pytest.mark.parametrize("plan", [
    "Two Bedroom - $1,299 - $1,589",
    "Two Bedroom | $1,299 to $1,589",
    "2 Bedroom: $1,299 - $1,589",
    "Two Bedroom - $1,299 - $1,589 a month",
    "TWO BEDROOM - $1,299 - $1,589",
    "Two Bedrooms $1,299 - $1,589",
])
def test_a_rent_range_line_gets_no_not_counted_note(plan):
    r = read("Weinland Park Flats\n" + plan + "\nStarting at $1,299. 2 bed 2 bath.\n1180 N 4th St, Columbus, OH 43201")
    n = notes(r)
    assert "rent range of $1,299 to $1,589" in n, n
    assert "not counted anywhere" not in n and '"Two Bedroom' not in n and '"2 Bedroom' not in n, n
    assert "price" not in r


def test_nontech_l4_whole_listing():
    r = read(fixture("r34-nontech-l4.txt"))
    assert "price" not in r and r["beds"] == 2 and r["baths"] == 2 and r["broker_fee"] == 500 and r["deposit"] == 500
    assert r["parking"] == "covered" and r["parking_cost"] == 45 and r["laundry"] == "in_unit"
    assert r["pet_fee"] == 300 and r["pet_rent"] == 25 and r["other_monthly_fees"] == 15
    assert '"Two Bedroom' not in notes(r), notes(r)
