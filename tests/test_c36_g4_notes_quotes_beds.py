"""Cycle 36, G4: one note per concession, no empty amount in a note, quotes in the listing's own words, "Brand new 3/2" (uiuc l4, uiuc l8, roommates l4)."""
from __future__ import annotations

import os
import re

import pytest

from prophelper import parsers as P

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel")


def fixture(name: str) -> str:
    with open(os.path.join(FIX, name), encoding="utf-8") as fh:
        return fh.read()


def read(t: str, **kw) -> dict:
    return P.parse_listing(t, "", **kw)


def lines(r: dict) -> list[str]:
    return [x for x in r.get("found_in_listing", "").split("\n") if x]


BASE = "1 BR / 1 BA, 1204 W Green St, Urbana IL 61801. "


def concession_lines(r: dict) -> list[str]:
    return [x for x in lines(r) if re.search(r"concession|free|half off|one-time deal|net effective|promo", x, re.I)]


# ---- uiuc l4: one concession, one note
@pytest.mark.parametrize("line", [
    "Rent $1,620/mo, now $1,420 with concession (one month free on 14-month lease, promo total $19,880).",
    "LIMITED TIME: Half off first month!! Rent $1,620/mo, now $1,420 with concession (one month free on 14-month lease).",
    "Rent $1,620/mo; $1,420/mo with concession. One month free on a 14 month lease.",
    "Rent $1,620/mo, $1,420 net effective with 1 month free on a 14-month lease.",
    "Rent $1,620 a month, or $1,420 with a concession (1 month free, 14 month lease).",
    "Rent: $1,620/mo\nNow $1,420 with concession\nOne month free on 14-month lease",
])
def test_one_concession_gives_one_note(line):
    r = read(BASE + line)
    assert r["price"] == 1620
    got = concession_lines(r)
    assert len(got) == 1, got
    assert "$1,620" in got[0] and "$1,420" in got[0]
    assert not re.search(r"\$[.,)\"]|\$\s*$", got[0]), got[0]


def test_uiuc_l4_whole_listing():
    r = read(fixture("r35-uiuc-l4.txt"))
    assert r["price"] == 1620 and r["beds"] == 1 and r["baths"] == 1
    assert r["parking"] == "garage" and r["parking_cost"] == 0
    got = concession_lines(r)
    assert len(got) == 1, got
    assert "$19,880" in got[0] and "Half off first month" in got[0] and "14 month" in got[0]
    n = r["found_in_listing"]
    assert not re.search(r"\$[.,)\"]", n), n
    assert "split between roommates" in n and "broker fee" in n.lower() and "$30 a month" in n


@pytest.mark.parametrize("line", [
    "Rent $1,620/mo. Move-in special: half off first month's rent.",
    "Rent: $1,620 | Concession: 1 month free",
    "$1,620 a month. Special: 1 month free if you sign a 13 month lease!",
])
def test_a_lone_offer_still_gets_its_note(line):
    r = read(BASE + line)
    assert r["price"] == 1620
    assert len(concession_lines(r)) == 1, lines(r)


def test_two_different_offers_are_not_lost():
    r = read(BASE + "Rent $1,620/mo. 2 months free on 18 month lease. Half off first month on 12 month lease.")
    got = concession_lines(r)
    assert len(got) == 1
    assert "2 months free" in got[0] and "Half off first month" in got[0]


def test_roommates_l8_one_note_and_lease_months():
    r = read(fixture("r35-roommates-l8.txt"))
    assert r["price"] == 3600 and r["beds"] == 3 and r["baths"] == 2
    got = concession_lines(r)
    assert len(got) == 1 and "$3,300" in got[0] and "13 month" in got[0]


def test_a_rent_step_note_is_not_touched():
    r = read(BASE + "Rent $1,620 for the first 6 months, then $1,700.")
    assert r["price"] == 1700
    assert any("$1,620" in x for x in lines(r))


# ---- no note ends with an empty amount
@pytest.mark.parametrize("name", ["r35-uiuc-l4.txt", "r35-uiuc-l8.txt", "r35-roommates-l4.txt", "r35-roommates-l8.txt", "r35-roommates-l10.txt", "r35-roommates-l14.txt",
                                  "r35-family-l3.txt", "r35-buyer-l40.txt", "r35-nontech-l1.txt"])
def test_no_note_in_the_g4_listings_has_an_empty_amount(name):
    for buying in (False, True):
        n = P.parse_listing(fixture(name), "", buying=buying).get("found_in_listing", "")
        assert not re.search(r"\$(?=[.)\"]|\s*$|\s*\n)", n), n


# ---- uiuc l8: a quote keeps the listing's own words
def test_uiuc_l8_quote_keeps_spaced_figure():
    r = read(fixture("r35-uiuc-l8.txt"))
    n = r["found_in_listing"]
    assert '2 100 al mes for 2BR' in n and "$2,100 al mes" not in n, n
    assert r["price"] == 1525 and r["parking"] == "garage" and r["parking_cost"] == 60


@pytest.mark.parametrize("mid,shown", [
    ("2 100 al mes", "2 100 al mes"),
    ("$2 100 al mes", "$2 100 al mes"),
    ("2 100 al mes", "2 100 al mes"),
])
def test_quote_keeps_the_pasted_figure(mid, shown):
    r = read(f"Sunrise\n1 BR/1 BA at 1401 N Neil St, Champaign, IL 61820 -- $1,525/month, {mid} for 2BR.\nNo pets.")
    n = r["found_in_listing"]
    assert shown in n, n
    assert "$2,100 al mes" not in n


def test_a_quote_that_is_already_verbatim_is_left_alone():
    r = read("Sunrise\n1 BR/1 BA at 1401 N Neil St, Champaign, IL 61820 -- $1,525/month, $2,100 al mes for 2BR.\nNo pets.")
    assert "$2,100 al mes" in r["found_in_listing"]


# ---- roommates l4: "Brand new 3/2" is 3 bed, 2 bath
@pytest.mark.parametrize("line", [
    "Brand new 3/2 in Bridgeport!!! Rent $3,225.",
    "Brand new 3/2 in Bridgeport. Rent $3,225.",
    "3/2 in Bridgeport, brand new. Rent $3,225.",
    "Brand new 3 / 2 in Logan Square - Rent $3,225",
    "Newly renovated 3/2 in Pilsen\nRent $3,225",
    "Brand new 3/2 | Rent $3,225",
])
def test_brand_new_slash_layout_is_beds_and_baths(line):
    r = read(line)
    assert (r["beds"], r["baths"]) == (3, 2)
    assert r["price"] == 3225


def test_roommates_l4_whole_listing():
    r = read(fixture("r35-roommates-l4.txt"))
    assert (r["beds"], r["baths"]) == (3, 2)
    assert r["price"] == 3225 and r["deposit"] == 3225 and r["parking_cost"] == 0 and not r.get("parking")


@pytest.mark.parametrize("line", [
    "Available 3/2 for move in. Rent $3,225.",
    "Open house 3/2, bring ID. Rent $3,225.",
    "Lease signed 3/2, rent due on the 1st. Rent $3,225.",
    "Walk 1/2 mile to the lake. Rent $3,225.",
    "Trim is 3/4 in. thick. Rent $3,225.",
])
def test_dates_and_fractions_are_not_a_layout(line):
    r = read(line)
    assert r.get("beds") is None and r.get("baths") is None
