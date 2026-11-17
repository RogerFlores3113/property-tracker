"""Cycle 34 G2: "1550 obo" with no dollar sign is the rent when nothing else in the listing names one (uiuc l18)."""
import os

import pytest

from prophelper.parsers import parse_listing

P = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel") + "/"


def read(t, **kw):
    return parse_listing(t, "", **kw)


def notes(r):
    return r.get("found_in_listing", "") or ""


def test_uiuc_l18_whole_listing():
    r = read(open(P + "r33-uiuc-l18.txt", encoding="utf-8").read())
    assert r["price"] == 1550
    assert r["beds"] == 1
    assert 'The listing gives "1550 obo" with no dollar sign or period. It is read as the monthly rent, $1,550.' in notes(r)


@pytest.mark.parametrize("t,price", [
    ("nice 1bd close to campus!! 1550 obo", 1550),
    ("2br near campus 1550 obo, pets ok", 1550),
    ("Studio. 1,550 OBO. no smoking", 1550),
    ("1bd 1550 or best offer\nw/d in unit", 1550),
    ("Cute 2 bed 1 bath | 1550 negotiable | near the quad", 1550),
    ("1bd (1550 o.b.o.) available 8/15", 1550),
    ("3 bedroom house, 2,100 obro; no pets", 2100),
])
def test_bare_number_with_obo_is_the_rent(t, price):
    r = read(t)
    assert r["price"] == price
    assert "no dollar sign" in notes(r)


def test_firm_says_firm():
    r = read("Cute 2 bed 1 bath, 1550 firm")
    assert r["price"] == 1550 and "called firm" in notes(r)


@pytest.mark.parametrize("t", [
    "Deposit 1550 obo. 1bd near campus",
    "House for sale 350000 obo",
    "123 Main St 1bd. Parking 100 obo",
    "2 bed. 1550 obo? ask us",
    "Garage 150 obo, 1bd apartment",
])
def test_negatives_not_a_rent(t):
    assert read(t).get("price") is None


def test_a_dollar_rent_beats_a_bare_obo():
    r = read("1bd $1,600/mo. Old ad said 1550 obo")
    assert r["price"] == 1600
    assert "no dollar sign" not in notes(r)
