"""Cycle 32, G4: "2/2 also available" beside "1 bedroom from $1,540" never sets the unit's beds or baths."""
from __future__ import annotations

import os

import pytest

from prophelper import parsers as P

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel")


def read(text: str) -> dict:
    return P.parse_listing(text, "")


@pytest.mark.parametrize("text", [
    "Sunset Row\n2/2 also available. 1 bedroom from $1,540/mo.",
    "Sunset Row\n1 bedroom from $1,540/mo. 2/2 also available.",
    "Sunset Row\n1 bedroom from $1,540; 2/2 also offered.",
    "Sunset Row\n1 bed from $1,540/mo (2x2 also available)",
    "Sunset Row\n2/2 floor plans also available! The 1 bedroom starts at $1,540/mo.",
    "Sunset Row\n1BR $1,540/mo | 2/2 available too",
    "Sunset Row\nAlso available: 2/2 units. 1 bedroom from $1,540/mo",
    "Sunset Row\nOne bedroom from $1,540 per month - 2/2 units are also available",
])
def test_other_plan_never_sets_beds_or_baths(text):
    r = read(text)
    assert r["beds"] == 1
    assert r.get("baths") in (None, 1)


def test_reviewer_listing():
    with open(os.path.join(FIX, "r31-uiuc-l3.txt"), encoding="utf-8") as fh:
        r = read(fh.read())
    assert r["beds"] == 1 and r.get("baths") in (None, 1)
    assert r["price"] == 1540


def test_count_style_other_plan():
    r = read("Sunset Row\n1 bedroom from $1,540/mo. 2 bed 2 bath also available.")
    assert r["beds"] == 1 and r.get("baths") in (None, 1)


@pytest.mark.parametrize("text,beds,baths", [
    ("Sunset Row\n2/2 townhouse available now, $1,800/mo", 2, 2),
    ("Sunset Row\n3/2 ranch, $1,800/mo. 1/2 mile to campus", 3, 2),
    ("Sunset Row\n2 bed 2 bath, $1,800/mo. Pets also welcome.", 2, 2),
    ("Sunset Row\n1 bedroom $1,540/mo. Parking also available.", 1, None),
])
def test_negatives(text, beds, baths):
    r = read(text)
    assert r["beds"] == beds and r.get("baths") == baths


def test_only_other_plan_stays_unknown():
    r = read("Sunset Row\n2/2 also available. Call for pricing.")
    assert r.get("beds") is None and r.get("baths") is None
