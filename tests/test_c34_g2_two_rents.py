"""Cycle 34 G2: two different rents in one text get one plain note naming both and the higher one saved, never "a monthly fee ... not counted anywhere"."""
import os
import sys

import pytest

from prophelper.parsers import parse_listing

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp_util import call, server, text  # noqa: E402


def read(t, **kw):
    return parse_listing(t, "", **kw)


def notes(r):
    return r.get("found_in_listing", "") or ""


@pytest.mark.parametrize("t,hi,lo", [
    ("Rent $2,300/mo. 3 bed 2 bath. Special: first month only $1,999, then $2,350.", 2350, 2300),
    ("3 bed. $2,300/mo. Rent is $2,450 per month.", 2450, 2300),
    ("Rent $2,300/mo. Dogs ok.\nMonthly rent $2,450. Deposit $2,300", 2450, 2300),
    ("Rent $2,300/mo. Rent $2,450/mo.", 2450, 2300),
    ("Rent: $2,450 per month | 3 bed | Monthly rent: $2,300", 2450, 2300),
    ("RENT $2,300 PER MONTH. 3 BED. RENT IS $2,450 A MONTH.", 2450, 2300),
    ("3 bed 2 bath house\nRent: $2,300\nMonthly Rent: $2,450\nPets ok", 2450, 2300),
])
def test_two_different_rents_name_both_and_save_the_higher(t, hi, lo):
    r = read(t)
    n = notes(r)
    assert r["price"] == hi
    assert f"two different rents: ${lo:,} and ${hi:,}" in n
    assert f"The higher ${hi:,} is saved as the rent" in n
    assert "monthly fee" not in n and "not counted anywhere" not in n


def test_three_rents_are_named():
    r = read("Rent $2,300/mo.\nRent $2,450/mo.\nMonthly rent $2,500.")
    assert r["price"] == 2500
    assert "three different rents: $2,300, $2,450 and $2,500" in notes(r)


@pytest.mark.parametrize("t,price", [
    ("Rent $2,300/mo. Rent $2,300 per month. 3 bed.", 2300),                      # the same rent twice
    ("Rent $2,450 per month. Corrected: rent is $2,300.", 2300),                  # a correction
    ("Rent $2,300/mo (was $2,450).", 2300),                                       # an old figure
    ("Rent $2,300/mo, $2,450 for a 6 month lease", 2300),                          # a lease length
    ("Studio rent $1,800/mo. 1 bed rent $2,300/mo.", None),                        # other units
    ("Rent $2,300/mo. Parking $200/mo. Pet rent $45/mo.", 2300),                  # fees are not rents
    ("Rent $2,300/mo. Garage rent $250/mo.", 2300),
])
def test_negatives_not_two_rents(t, price):
    r = read(t)
    assert "different rents" not in notes(r)
    if price is not None:
        assert r["price"] == price


def test_add_place_reply_has_no_fee_note(store):
    store.add_search("T", "rent")
    srv = server(store)
    out = text(call(srv, "add_place", listing_text="Home. 12 Elm St, Champaign, IL 61820. Rent $2,300/mo. 3 bed 2 bath. Rent is $2,450 per month."))
    assert "two different rents: $2,300 and $2,450" in out
    assert "monthly fee" not in out and "not counted anywhere" not in out
    assert store.get_place(1)["price"] == 2450
