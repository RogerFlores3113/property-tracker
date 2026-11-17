"""Cycle 31 G2: a rent that steps up during the lease keeps the higher steady rent, with a note naming the lower first months.
A promo for the first months is never called a monthly fee."""
import os

import pytest

from prophelper.parsers import parse_listing

P = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel") + "/"


def read(t):
    return parse_listing(t, "")


def notes(r):
    return r.get("found_in_listing", "") or ""


def test_reviewer_l17_saved_listing():
    r = read(open(P + "r30-roommates-l17.txt").read())
    assert r["price"] == 3200
    assert r["deposit"] == 3075
    assert r["move_in_fees"] == 400
    n = notes(r)
    assert "$3,075 a month for the first 6 months, then $3,200" in n
    assert "another lease length" not in n
    assert "not counted anywhere" not in n


@pytest.mark.parametrize("t,low,high,months", [
    ("Hyde Park 3 BR 2 BA. Rent $2,100 for the first 6 months, then $2,250. Deposit $2,100.", 2100, 2250, "6"),
    ("Hyde Park 3 BR 2 BA. $2,100/mo for the first six months; rent increases to $2,250 in month 7. Deposit $2,100.", 2100, 2250, "6"),
    ("Hyde Park 3 BR 2 BA\n- Rent: $2,100 (first 6 months)\n- Then $2,250 per month\n- Deposit $2,100", 2100, 2250, "6"),
    ("Hyde Park 3 BR 2 BA. Rent $2,100/mo. Rent goes up to $2,250 after the first 6 months. Deposit $2,100.", 2100, 2250, "6"),
    ("Hyde Park 3 BR 2 BA. Previously $2,200, now $2,100/mo. Rent $2,100 for the first 6 months, then $2,250. Deposit $2,100.", 2100, 2250, "6"),
    ("Hyde Park 3 BR 2 BA | Rent $2,100 for the first 9 months, then goes up to $2,250 | Deposit $2,100", 2100, 2250, "9"),
])
def test_step_up_keeps_steady_rent(t, low, high, months):
    r = read(t)
    assert r["price"] == high
    assert r["deposit"] == 2100
    assert r.get("other_monthly_fees") in (None, 0)
    n = notes(r)
    assert f"${low:,} a month for the first {months} month" in n
    assert f"${high:,}" in n
    assert "not counted anywhere" not in n
    assert "monthly fee" not in n


@pytest.mark.parametrize("t", [
    "Cozy 2 bed 1 bath in Grandview\n$1,480/mo\nSpecial: $1,200/mo for the first 6 months, then regular rent.\nSecurity deposit $1,000.",
    "Cozy 2 bed 1 bath in Grandview\nRent $1,480. Promo: $1,200 a month for the first 6 months, then the regular rent. Security deposit $1,000.",
    "Cozy 2 bed 1 bath in Grandview\n- Rent $1,480\n- $1,200/mo for the first 6 months, then regular rent\n- Security deposit $1,000",
])
def test_promo_then_regular_rent_is_not_a_fee(t):
    r = read(t)
    assert r["price"] == 1480
    assert r["deposit"] == 1000
    assert r.get("other_monthly_fees") in (None, 0)
    n = notes(r)
    assert "$1,200 a month for the first 6 months" in n
    assert "monthly fee" not in n and "not counted anywhere" not in n


def test_reviewer_nontech_l3_saved_listing():
    r = read(open(P + "r30-nontech-l3.txt").read())
    assert r["price"] == 1480
    assert r["deposit"] == 1000
    n = notes(r)
    assert "$1,200 a month for the first 6 months" in n
    assert "monthly fee" not in n
    assert "$1,420 a month if you sign by Dec 15" in n


def test_plain_listing_unchanged():
    r = read("Hyde Park 3 BR 2 BA. Rent $2,100/mo. Deposit $2,100. Lease 12 months.")
    assert r["price"] == 2100
