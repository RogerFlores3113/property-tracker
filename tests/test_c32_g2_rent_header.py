"""Cycle 32 G2: a bare rent in a pipe header ("2BR | $3,290 | West Loop") is the rent when nothing else names one, and a figure in a
"typical bills" or utilities clause is never the rent. A listed rent that differs from the saved rent is a rent mismatch note."""
import os

import pytest

from prophelper.parsers import parse_listing

P = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel") + "/"


def read(t, **kw):
    return parse_listing(t, "", **kw)


def notes(r):
    return r.get("found_in_listing", "") or ""


def test_reviewer_roommates_l31_saved_listing():
    r = read(open(P + "r31-roommates-l31.txt").read())
    assert r["price"] == 3290
    assert r["deposit"] == 3290
    assert r["beds"] == 3
    n = notes(r)
    assert "could not tell which one is the monthly rent" not in n
    assert "rent is left empty" not in n


def test_reviewer_roommates_l32_saved_listing():
    r = read(open(P + "r31-roommates-l32.txt").read())
    assert r["price"] == 3290
    assert "rent is left empty" not in notes(r)


@pytest.mark.parametrize("t", [
    "West Loop 3BR | 2.5 BA | $3,290 | 900 W Randolph St, Chicago IL 60607 | Tenant pays all utilities; typical bills about $210/mo; internet extra.",
    "2BR | $3,290 | West Loop\nTenant pays gas and electric. Utilities average $210 per month.",
    "West Loop 3BR 2BA\n$3,290\nTenant pays all utilities, typical bills about $210/mo (internet extra).",
    "West Loop 3BR | $3,290 | Typical bills about $210 a month; tenant pays all utilities.",
    "West Loop 3BR | Typical bills about $210/mo. Tenant pays all utilities. | $3,290",
    "West Loop 3BR | 2 BA | $3,290 | Tenant pays all utilities. Typical monthly bills are about $210. Internet is extra.",
    "West Loop 3BR | 2 BA | $3,290 | Utilities are tenant paid; average utilities around $210/mo.",
])
def test_pipe_header_rent_beats_a_typical_bills_figure(t):
    r = read(t)
    assert r["price"] == 3290
    assert "could not tell which one is the monthly rent" not in notes(r)


@pytest.mark.parametrize("t", [
    "3 bed 2 bath. Tenant pays all utilities; typical bills about $210/mo.",
    "West Loop 3BR\nTypical bills about $210 per month. Tenant pays all utilities.",
    "Loft. Utilities average $210/mo, paid by the tenant.",
])
def test_a_typical_bills_figure_alone_is_never_the_rent(t):
    r = read(t)
    assert r.get("price") in (None, "")


@pytest.mark.parametrize("t,price", [
    ("West Loop 3BR | $3,290/mo | Tenant pays electric about $90/mo", 3290),
    ("West Loop 3BR | Rent $3,290 | typical bills about $210/mo", 3290),
    ("Studio near campus. Rent $950/mo. Water about $30/mo.", 950),
])
def test_rent_still_read_beside_a_utility_figure(t, price):
    assert read(t)["price"] == price


# ----------------------------------------------------------------------- listed rent differs from the saved rent
@pytest.mark.parametrize("t", [
    "Cozy 1 bed 1 bath. Rent $1,650/mo. Deposit $1,650.",
    "Cozy 1 bed 1 bath. $1,650/mo. Pets ok.",
    "Cozy 1 bed 1 bath. $1,650 per month. Pets ok.",
    "Cozy 1 bed. Rent is $1,650 a month.",
    "1 bed\nMonthly rent: $1,650",
    "Cozy 1 bed | 1 bath | $1,650 | Pets ok",
])
def test_listed_rent_differs_from_saved_rent_is_a_mismatch(t):
    r = read(t, current={"price": 1500})
    assert r["price"] == 1500
    n = notes(r)
    assert "The listing gives a rent of $1,650 a month, but the rent saved on this place is $1,500" in n
    assert "monthly fee" not in n
    assert "not counted anywhere" not in n
    assert n.count("$1,650") == 1


@pytest.mark.parametrize("t,cur", [
    ("Cozy 1 bed 1 bath. Rent $1,650/mo. Deposit $1,650.", 1650),
    ("Cozy 1 bed 1 bath. Pets ok. Deposit $500.", 1500),
])
def test_no_mismatch_note_when_the_rents_agree_or_the_listing_has_none(t, cur):
    n = notes(read(t, current={"price": cur}))
    assert "rent saved on this place" not in n


def test_correction_note_and_mismatch_note_are_not_both_given():
    n = notes(read("Rent $1,500. Reduced to $1,650/mo", current={"price": 1500}))
    assert n.count("$1,650") == 1


def test_mismatch_note_replaces_the_floor_plan_guess_for_the_same_figure():
    r = read("Studio $950/mo. Move-in package $3,500 includes first month.", current={"price": 3290})
    n = notes(r)
    assert n.count("$950") == 1
    assert "another floor plan" not in n
    assert "rent saved on this place is $3,290" in n
