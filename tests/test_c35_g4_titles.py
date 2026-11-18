"""Cycle 35, G4: a sales phrase, a price tail or a bare kind of place is never the title; the street address (or the plan) is (uiuc l31, nontech l3, family l2)."""
from __future__ import annotations

import os

import pytest

from prophelper import parsers as P

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel")


def fixture(name: str) -> str:
    with open(os.path.join(FIX, name), encoding="utf-8") as fh:
        return fh.read()


def read(text: str) -> dict:
    return P.parse_listing(text, "")


BODY = "Rent $1,490/mo. 1 bed/1 bath, in unit laundry. 909 S Lincoln Ave, Urbana"


@pytest.mark.parametrize("first", [
    "Half off first month! ",
    "Half off first month!\n",
    "HALF OFF FIRST MONTH!!!\n",
    "Half off first month.\n",
    "50% off first month!\n",
    "Half off your first month - ",
    "First month free!\n",
    "Two months free!!\n",
    "Half off first month | ",
    "Move-in special: half off first month\n",
])
def test_sales_phrase_is_not_the_title(first):
    r = read(first + BODY)
    assert r["title"] == "909 S Lincoln Ave", r["title"]
    assert r["price"] == 1490 and r["address"] == "909 S Lincoln Ave"


def test_uiuc_l31_whole_listing():
    r = read(fixture("r34-uiuc-l31.txt"))
    assert r["title"] == "909 S Lincoln Ave"
    assert r["price"] == 1490 and r["address"] == "909 S Lincoln Ave" and r["city"] == "Urbana"
    assert r["parking"] == "covered" and r["laundry"] == "in_unit" and r["pets"] == "cats" and r["pet_deposit"] == 250


@pytest.mark.parametrize("first", [
    "BEAUTIFUL 2 BEDROOM DUPLEX!!! Only 1450 obo",
    "BEAUTIFUL 2 Bedroom Duplex Only 1450 obo",
    "Beautiful 2 bedroom duplex - only $1450 obo",
    "BEAUTIFUL 2 BEDROOM DUPLEX!!! 1450 OBO",
    "Beautiful 2 bedroom duplex, 1450 or best offer",
    "Beautiful 2 bedroom duplex only 1,450 firm",
    "BEAUTIFUL 2 BEDROOM DUPLEX!!! Only $1450/mo obo",
])
def test_price_tail_is_not_part_of_the_title(first):
    r = read(first + "\nLocated Whitehall. Cats fine.")
    t = r["title"]
    assert "1450" not in t and "1,450" not in t and "obo" not in t.lower() and "only" not in t.lower() and "best offer" not in t.lower() and "firm" not in t.lower(), t
    assert "2 Bedroom Duplex" in t or "2 bedroom duplex" in t.lower(), t
    assert "!" not in t


def test_nontech_l3_whole_listing():
    r = read(fixture("r34-nontech-l3.txt"))
    assert r["title"] == "Beautiful 2 Bedroom Duplex", r["title"]
    assert r["price"] == 1450 and r["beds"] == 2 and r["pets"] == "cats"
    assert r["tenant_pays"] == "electric, gas, water"


def test_the_price_tail_gives_way_to_the_address_when_there_is_one():
    r = read("BEAUTIFUL 2 BEDROOM DUPLEX!!! Only 1450 obo\n22 W Home St, Whitehall, OH 43213\nCats fine.")
    assert "1450" not in r["title"] and "obo" not in r["title"].lower()
    assert r["address"] == "22 W Home St" and r["price"] == 1450


@pytest.mark.parametrize("first", [
    "Townhome for rent - 88 Birch Lane, San Carlos, CA",
    "Townhome for rent: 88 Birch Lane, San Carlos, CA",
    "Townhome for rent | 88 Birch Lane, San Carlos, CA",
    "Townhome - 88 Birch Lane, San Carlos, CA",
    "TOWNHOME FOR RENT - 88 Birch Lane, San Carlos, CA",
    "Apartment for rent - 88 Birch Lane, San Carlos, CA",
    "House for rent - 88 Birch Lane, San Carlos, CA",
    "Beautiful townhome for lease - 88 Birch Lane, San Carlos, CA",
    "Condo for rent in San Carlos - 88 Birch Lane, San Carlos, CA",
])
def test_a_bare_kind_of_place_gives_way_to_the_address(first):
    r = read(first + "\nRent: $2,295 a month. 3 bed 2.5 bath, 1,450 sqft.")
    assert r["title"] == "88 Birch Lane", r["title"]
    assert r["address"] == "88 Birch Lane" and r["price"] == 2295


def test_family_l2_whole_listing():
    r = read(fixture("r34-family-l2.txt"))
    assert r["title"] == "88 Birch Lane", r["title"]
    assert r["price"] == 2295 and r["address"] == "88 Birch Lane" and r["city"] == "San Carlos" and r["deposit"] == 2295
    assert r["pet_fee"] == 400 and r["pet_rent"] == 50 and r["application_fee"] == 50


# negatives: real names stay
@pytest.mark.parametrize("first,title", [
    ("Birch Commons Townhomes - 88 Birch Lane, San Carlos, CA", "Birch Commons Townhomes"),
    ("Halfmoon Flats | 88 Birch Lane, San Carlos, CA", "Halfmoon Flats"),
    ("Cedar Row Townhomes - 88 Birch Lane, San Carlos, CA", "Cedar Row Townhomes"),
])
def test_real_names_stay(first, title):
    r = read(first + "\nRent: $2,295 a month.")
    assert r["title"] == title, r["title"]


def test_a_plan_with_a_price_in_it_still_keeps_its_plan_when_a_name_comes_first():
    r = read("Weinland Park Flats\nTwo Bedroom - $1,299 - $1,589\n1180 N 4th St, Columbus, OH 43201")
    assert r["title"] == "Weinland Park Flats"
