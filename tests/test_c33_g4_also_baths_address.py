"""Cycle 33, G4: "2 Bed/2 Bath also offered" beside a 1 bed never sets the baths (uiuc l7), and a street named Terrace keeps its own suffix and unit (buyer l21)."""
from __future__ import annotations

import os

import pytest

from prophelper import parsers as P

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel")


def fixture(name: str) -> str:
    with open(os.path.join(FIX, name), encoding="utf-8") as fh:
        return fh.read()


def read(text: str, **kw) -> dict:
    return P.parse_listing(text, "", **kw)


HEAD = "Neil Street Station - 1 Bedroom\n"


@pytest.mark.parametrize("line", [
    "2 Bed/2 Bath also offered. 1 bed rent $1,560.",
    "2BR/2BA also available. 1 bed rent $1,560.",
    "Two bed two bath also offered. 1 bed rent $1,560.",
    "1 bed rent $1,560. 2 Bed/2 Bath also offered.",
    "Rent $1,560. 2 Bedroom / 2 Bathroom also offered!",
    "Rent $1,560. Also offered: 2 Bed/2 Bath.",
    "Rent $1,560. 2 Bed/2 Bath available too.",
    "Rent $1,560. 2-bed/2-bath floor plans also offered",
    "Rent $1,560. 2 bed 2 bath (also offered)",
    "Rent $1,560.\n- 2 Bed/2 Bath also offered",
    "Rent $1,560. 2/2 also available",
    "RENT $1,560. 2 BED/2 BATH ALSO OFFERED.",
])
def test_other_plan_never_sets_baths(line):
    r = read(HEAD + line)
    assert r["beds"] == 1 and r["price"] == 1560
    assert r.get("baths") in (None, 1)  # no bath count is given for this unit, so it stays empty
    assert r.get("baths") != 2


@pytest.mark.parametrize("line", [
    "1 bed 1 bath. 2 Bed/2 Bath also offered. Rent $1,560.",
    "Rent $1,560. 1 Bath. 2 Bed/2 Bath also offered.",
    "1BR/1BA. Also offered: 2 Bed/2 Bath. Rent $1,560.",
    "Rent $1,560, 1 bathroom. Two bed two bath also available.",
])
def test_own_bath_count_is_kept(line):
    r = read(HEAD + line)
    assert r["beds"] == 1 and r["baths"] == 1


def test_uiuc_l7_whole_listing():
    r = read(fixture("r32-uiuc-l7.txt"))
    assert r["beds"] == 1 and r.get("baths") is None and r["price"] == 1560
    assert r["title"] == "Neil Street Station"


@pytest.mark.parametrize("text,beds,baths", [
    ("Neil Street Station - 2 Bedroom 2 Bath\nRent $1,860. 1 Bed/1 Bath also offered.", 2, 2),
    ("2 Bed/2 Bath\nRent $1,860.", 2, 2),
    ("2 bed 2 bath apartment. Rent $1,860. Washer dryer in unit.", 2, 2),
    ("Two bed two bath. Rent $1,860.", 2, 2),
])
def test_the_listings_own_layout_is_kept(text, beds, baths):
    r = read(text)
    assert r["beds"] == beds and r["baths"] == baths


# ---- a street named Terrace
@pytest.mark.parametrize("text", [
    "6 Terrace Dr #B, Worthington, OH 43085\nAsking $334,500. 2 bedrooms, 2 baths.",
    "Worthington Terrace Condo\n6 Terrace Dr #B, Worthington, OH 43085\nAsking $334,500.",
    "6 Terrace Dr Apt B, Worthington, OH 43085\nAsking $334,500.",
    "6 Terrace Dr Unit B, Worthington, OH 43085\nAsking $334,500.",
    "Condo at 6 Terrace Dr #B, Worthington, OH 43085. Asking $334,500.",
    "6 Terrace Dr, #B, Worthington, OH 43085\nAsking $334,500.",
    "6 TERRACE DR #B, WORTHINGTON, OH 43085\nAsking $334,500.",
])
@pytest.mark.parametrize("buying", [True, False])
def test_terrace_street_keeps_suffix_and_unit(text, buying):
    r = read(text, buying=buying)
    assert r["address"].lower() == "6 terrace dr"
    assert r["unit"] == "B"
    assert r["city"].lower() == "worthington" and r["state"] == "OH"
    assert P.street_with_unit(r["address"], r["unit"]).lower() == "6 terrace dr #b"


def test_buyer_l21_whole_listing():
    r = read(fixture("r32-buyer-l21.txt"), buying=True)
    assert r["title"] == "Worthington Terrace Condo"
    assert r["address"] == "6 Terrace Dr" and r["unit"] == "B" and r["city"] == "Worthington" and r["state"] == "OH" and r["zip"] == "43085"
    assert r["price"] == 334500 and r["beds"] == 2 and r["baths"] == 2


def test_no_title_line_uses_the_whole_street():
    r = read("6 Terrace Dr #B, Worthington, OH 43085\nAsking $334,500. 2 bedrooms, 2 baths.", buying=True)
    assert r["title"] == "6 Terrace Dr"


@pytest.mark.parametrize("text,address,unit", [
    ("6 Terrace Ln #B, Worthington, OH 43085", "6 Terrace Ln", "B"),
    ("6 Terrace Circle #B Worthington OH 43085", "6 Terrace Circle", "B"),
    ("12 Terrace Dr #4B, Worthington, OH 43085", "12 Terrace Dr", "4B"),
    ("6 Circle Dr #B, Worthington, OH 43085", "6 Circle Dr", "B"),
    ("9 Place Rd, Worthington, OH 43085", "9 Place Rd", None),
    ("5 Trail Rd Apt 2, Worthington, OH 43085", "5 Trail Rd", "2"),
    ("4 Loop Rd #3, Worthington, OH 43085", "4 Loop Rd", "3"),
])
def test_other_streets_named_like_a_suffix(text, address, unit):
    r = read(text)
    assert r["address"] == address and r.get("unit") == unit


@pytest.mark.parametrize("text,address,unit", [
    ("6 Court St #B, Worthington, OH 43085", "6 Court St", "B"),
    ("418 W Orchard Ln Unit 10, Champaign, IL 61820", "418 W Orchard Ln", "10"),
    ("77 Sunset Row Unit C, Redwood City CA 94061", "77 Sunset Row", "C"),
    ("10 Main Terrace, Worthington, OH 43085", "10 Main Terrace", None),
    ("2 Terrace, Worthington, OH 43085", "2 Terrace", None),
])
def test_plain_streets_are_unchanged(text, address, unit):
    r = read(text)
    assert r["address"] == address and r.get("unit") == unit
