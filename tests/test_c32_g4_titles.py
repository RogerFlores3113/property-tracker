"""Cycle 32, G4: titles. A plan range with "also available" is not part of the name, and a descriptive first line beats an area line."""
from __future__ import annotations

import os

import pytest

from prophelper import parsers as P

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel")


def read(text: str) -> dict:
    return P.parse_listing(text, "")


def fixture(name: str) -> str:
    with open(os.path.join(FIX, name), encoding="utf-8") as fh:
        return fh.read()


@pytest.mark.parametrize("first,name", [
    ("Sunset Row 3BR Townhouse 1 - 2 Beds also available", "Sunset Row 3BR Townhouse"),
    ("Sunset Row 3BR Townhouse 1 - 2 Beds", "Sunset Row 3BR Townhouse"),
    ("Sunset Row 3BR Townhouse (1 - 2 Beds also available)", "Sunset Row 3BR Townhouse"),
    ("Sunset Row 3BR Townhouse, 1 to 2 bedrooms also available!", "Sunset Row 3BR Townhouse"),
    ("Sunset Row 3BR Townhouse | 1-2 BR also available", "Sunset Row 3BR Townhouse"),
    ("Sunset Row 3BR Townhouse - 1 - 2 Beds now available", "Sunset Row 3BR Townhouse"),
    ("Lakeview Lofts 1 - 2 Beds also available", "Lakeview Lofts"),
])
def test_range_tail_is_not_in_the_name(first, name):
    r = read(first + "\n77 Sunset Row Unit C, Redwood City CA 94061\nRent $2,290.")
    assert r["title"] == name


def test_family_l3_whole_listing():
    r = read(fixture("r31-family-l3.txt"))
    assert r["title"] == "Sunset Row 3BR Townhouse"
    assert r["address"] == "77 Sunset Row" and r["unit"] == "C" and r["beds"] == 3


@pytest.mark.parametrize("text,name", [
    ("Sunny 1 - 2 Bedroom Apartments\nRent $1,290.", "Sunny 1 - 2 Bedroom Apartments"),
    ("Maple Court Apartments\n1 - 2 Beds also available\nRent $1,290.", "Maple Court Apartments"),
])
def test_range_in_a_real_name_stays(text, name):
    assert read(text)["title"] == name


def test_range_only_first_line_still_falls_to_the_address():
    r = read("Brand-new 1 - 2 Beds\n418 W Orchard Ln, Champaign, IL 61820\nRent $1,290.")
    assert r["title"] == "418 W Orchard Ln"


@pytest.mark.parametrize("first", [
    "Bright Two Bedroom in Grandview - Now Renting",
    "Bright Two Bedroom in Grandview",
    "Bright Two Bedroom in Grandview | Now Leasing",
])
@pytest.mark.parametrize("rest", [
    "1 - 2 Beds | 2 Bed 1 Bath | 880 sq ft\nGrandview Heights, Columbus, OH 43212\nRent $1,425.",
    "Grandview Heights, Columbus, OH 43212\nRent $1,425. 2 bed 1 bath",
    "2 Bed 1 Bath\nRent $1,425.",
])
def test_descriptive_headline_beats_the_area_line(first, rest):
    assert read(first + "\n" + rest)["title"] == "Bright Two Bedroom in Grandview"


def test_nontech_l3_whole_listing():
    r = read(fixture("r31-nontech-l3.txt"))
    assert r["title"] == "Bright Two Bedroom in Grandview"
    assert r["price"] == 1425 and r["beds"] == 2 and r["baths"] == 1


@pytest.mark.parametrize("text,name", [
    ("Grandview Heights\nColumbus, OH 43212\n2 bed 1 bath. Rent $1,425.", "Grandview Heights"),
    ("Grandview Heights Apartments\nColumbus, OH 43212\n2 bed 1 bath. Rent $1,425.", "Grandview Heights Apartments"),
    ("Rent $1,425\nGrandview Heights, Columbus, OH 43212\n2 bed 1 bath.", "Grandview Heights"),
])
def test_real_area_or_building_names_still_win(text, name):
    assert read(text)["title"] == name


@pytest.mark.parametrize("sent,want", [
    ("Hartwell Place | Zillow-ish listing - 1 Bed Rent $1,425 (previously $1,490", "Hartwell Place | 1 Bed Rent $1,425"),
    ("Stadium View | 1 Bed (was $1,350", "Stadium View | 1 Bed"),
    ("Cozy 2BR [reduced from $1,600", "Cozy 2BR"),
    ("Zillow-ish listing - Stadium View | 1 Bed (formerly $1,350", "Stadium View | 1 Bed"),
    ("Hartwell Place \u2014 Craigslist: 1 Bed", "Hartwell Place \u2014 1 Bed"),
])
def test_sent_title_label_and_dangling_bracket(sent, want):
    assert P.strip_site_label(sent) == want


@pytest.mark.parametrize("sent", [
    "Hartwell Place (Building A)", "Hartwell Place (reduced from $1,490)", "Zillow Heights Apartments", "Cozy 2BR (pets ok",
])
def test_sent_title_negatives(sent):
    assert P.strip_site_label(sent) == sent
