"""Cycle 34, G4: sales banners and greetings never become the title (nontech l22, l23)."""
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


BODY = "2 bedroom 1 bath in Westerville near Uptown. Rent $1,425. 22 W Home St, Westerville, OH 43081"


@pytest.mark.parametrize("banner", [
    "NEW LOWER PRICE!! Prices reduced again to $1,425",
    "NEW LOWER PRICE Prices reduced again",
    "New lower price! Prices reduced again.",
    "BIG SAVINGS this month!!",
    "PRICE DROP!!! NEW LOWER PRICE NOW $1,425",
    "Prices slashed - limited time offer!",
    "HOT DEAL!! Lower price!!",
    "Price reduced again!!",
])
def test_sales_banner_is_not_the_title(banner):
    r = read(banner + "\n" + BODY)
    assert r["title"] == "2 bedroom 1 bath in Westerville near Uptown", r["title"]
    assert r["price"] == 1425 and r["address"] == "22 W Home St"
    r2 = read(banner + "\nRent $1,425. 22 W Home St, Westerville, OH 43081")
    assert r2["title"] == "22 W Home St", r2["title"]


def test_nontech_l22_whole_listing():
    r = read(fixture("r33-nontech-l22.txt"))
    assert r["title"] == "2 bedroom 1 bath in Westerville near Uptown"
    assert r["price"] == 1425 and r["address"] == "22 W Home St" and r["city"] == "Westerville"
    assert r["deposit"] == 800 and r["pet_rent"] == 35 and r["pet_fee"] == 200 and r["utilities_estimate"] == 75
    assert r["tenant_pays"] == "electric" and r["utilities_included"] == "gas"


@pytest.mark.parametrize("first,title", [
    ("Hi!! Gorgeous 2 BR duplex Linden area!!!", "2 BR duplex Linden area"),
    ("Hello! Beautiful 2 BR duplex Linden area", "2 BR duplex Linden area"),
    ("Hey there!! Lovely 2 BR duplex Linden area.", "2 BR duplex Linden area"),
    ("HI!!! GORGEOUS 2 BR DUPLEX LINDEN AREA", "2 BR Duplex Linden Area"),
    ("Hi, spacious sunny 2 BR duplex Linden area", "2 BR duplex Linden area"),
    ("Hiya! Stunning 2 BR duplex Linden area!!", "2 BR duplex Linden area"),
])
def test_greeting_and_praise_are_not_the_title(first, title):
    r = read(first + "\nRent $1,100. Pets ok.")
    assert r["title"] == title, r["title"]
    assert "hi" not in r["title"].lower().split() and "hello" not in r["title"].lower().split()


def test_greeting_with_an_address_uses_the_address():
    r = read("Hi!! Gorgeous 2 BR duplex Linden area!!!\nRent $1,100. 55 Cleveland Ave Columbus OH 43211")
    assert r["address"] == "55 Cleveland Ave" and r["title"] in ("55 Cleveland Ave", "2 BR duplex Linden area"), r["title"]
    assert "Hi" not in r["title"] and "Gorgeous" not in r["title"]


def test_nontech_l23_whole_listing():
    r = read(fixture("r33-nontech-l23.txt"))
    assert r["title"] == "2 BR duplex Linden area", r["title"]
    assert r["price"] == 1100


@pytest.mark.parametrize("text,title", [
    ("Great Lakes Apartments\n2 bed 1 bath Rent $1,300", "Great Lakes Apartments"),
    ("Lower Price Hill Lofts\n2 bed 1 bath Rent $1,300", "Lower Price Hill Lofts"),
    ("Hillcrest Place\n2 bed 1 bath Rent $1,300", "Hillcrest Place"),
    ("Hi-Line Apartments\n2 bed 1 bath Rent $1,300", "Hi-Line Apartments"),
])
def test_real_names_stay(text, title):
    assert read(text)["title"] == title
