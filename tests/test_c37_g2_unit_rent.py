"""Cycle 37 G2 (rule mm): a price tied to a unit type is the rent only when it matches the listing's own size."""
import os

import pytest

from prophelper.parsers import parse_listing

P = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel") + "/"


def read(t, **kw):
    return parse_listing(t, "", **kw)


def fixture(n):
    return open(P + n, encoding="utf-8").read()


@pytest.mark.parametrize("t", [
    "1 bed 1 bath\nRent $2 300 dollars a month for the 2BR; 1BR starts at $1,540 a month.",
    "1 bed 1 bath. 1BR starts at $1,540 a month. Rent $2,300 a month for the 2BR.",
    "1 bedroom apartment\nThe 2 bedroom rents for $2,300 a month and the 1 bedroom starts at $1,540.",
    "1BR condo\n1BR from $1,540/mo, 2BR from $2,300/mo",
    "Studio-ish 1 bed\nRent $2,300 a month for the two bedroom, $1,540 a month for the one bedroom.",
    "1 bed 1 bath\n2BR - $2,300 | 1BR - $1,540",
    "1 bed 1 bath\n$1,540 for the 1BR, $2,300 for the 2BR",
    "1 bed 1 bath\nRent $2,300 dollars a month for the 2BR\n1BR starts at $1,540 a month.",
])
def test_the_one_bed_price_is_the_rent_and_the_two_bed_price_is_named(t):
    r = read(t)
    assert r["price"] == 1540
    assert "$2,300" in r["found_in_listing"] and "2 bedroom" in r["found_in_listing"]


def test_two_bed_listing_keeps_its_own_price():
    r = read("2 bed 2 bath\nRent $2,300 a month for the 2BR; 1BR starts at $1,540 a month.")
    assert r["price"] == 2300 and "$1,540" in r["found_in_listing"]


def test_whole_place_rent_is_untouched():
    assert read("2 bed 1 bath. Rent $2,300 a month. Studio-style units are not available.")["price"] == 2300
    assert read("2 bed 1 bath. Rent $2,300 a month.")["price"] == 2300


def test_uiuc_l7_whole_listing():
    r = read(fixture("r36-uiuc-l7.txt"))
    assert r["price"] == 1540 and r["beds"] == 1 and r["deposit"] == 1000
    assert "$2,300" in r["found_in_listing"]


def test_r35_uiuc_l5_whole_listing():
    r = read(fixture("r35-uiuc-l5.txt"))
    assert r["price"] == 1595 and r["beds"] == 1
    n = r["found_in_listing"]
    assert "$3,275" in n and "1550" in n


# ------------------------------------------------------------------ item 2 (rule nn): spoken corrections
@pytest.mark.parametrize("t", [
    "Rent $2,300 a month?? Just kidding, it is $1,380.",
    "Rent $2 300 dollars a month?? Just kidding, it is $1,380.",
    "Rent $2,300/mo. Just kidding, $1,380.",
    "Rent is $2,300. Actually, it's $1,380.",
    "Rent $2,300. Sorry, typo: $1,380.",
    "Rent $2,300 (I meant $1,380).",
    "Rent $2,300. No wait, $1,380 a month.",
    "2 bed. $2,300 per month... jk, $1,380 per month.",
    "Cozy 2 bed. Rent: $2,300 a month. Oops I meant $1,380 a month.",
])
def test_spoken_correction_later_rent_wins_with_a_note(t):
    r = read(t)
    assert r["price"] == 1380
    n = r["found_in_listing"]
    assert "corrects" in n and "$1,380" in n


def test_nontech_l3_whole_listing():
    r = read(fixture("r36-nontech-l3.txt"))
    assert r["price"] == 1380 and r["deposit"] == 1380 and r["beds"] == 3
    assert "corrects itself" in r["found_in_listing"]


@pytest.mark.parametrize("t,field,val", [
    ("Rent $1,500 a month. Deposit $1,500. Actually $1,200.", "price", 1500),
    ("Rent $1,500 a month. Pet fee $350, sorry $300.", "price", 1500),
])
def test_a_correction_of_another_fact_never_moves_the_rent(t, field, val):
    assert read(t)[field] == val
