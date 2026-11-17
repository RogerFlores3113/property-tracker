"""Cycle 34, G4: "Stacked washer and dryer" in a unit's feature list is in-unit laundry, and a laundry note quotes only the laundry words (uiuc l8)."""
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


def notes(r: dict) -> str:
    return r.get("found_in_listing") or ""


HEAD = "1 bed 1 bath. Rent $1,445. "


@pytest.mark.parametrize("line", [
    "Stacked washer and dryer, dishwasher, one-car garage $90. Built 2023.",
    "Features: dishwasher; stacked washer/dryer; one-car garage $90.",
    "Amenities\n- Stacked washer and dryer\n- Dishwasher\n- One-car garage $90",
    "Dishwasher, stacked washer & dryer, one-car garage $90",
    "STACKED WASHER AND DRYER, DISHWASHER, ONE-CAR GARAGE $90",
    "Dishwasher | Stacked W/D | One-car garage $90",
    "Full size stacked washer and dryer and dishwasher. One-car garage $90.",
    "Side-by-side washer and dryer, granite counters.",
    "Front load washer and dryer. Dishwasher.",
])
def test_stacked_washer_dryer_is_in_unit(line):
    r = read(HEAD + line)
    assert r["laundry"] == "in_unit", notes(r)
    assert "laundry" not in notes(r).lower().replace("laundry costs", ""), notes(r)
    assert r["price"] == 1445


def test_uiuc_l8_whole_listing():
    r = read(fixture("r33-uiuc-l8.txt"))
    assert r["laundry"] == "in_unit" and r["dishwasher"] == 1
    assert r["price"] == 1445 and r["parking"] == "garage" and r["parking_cost"] == 90
    assert r["utilities_estimate"] == 165 and r["deposit"] == 1445 and r["move_in_fees"] == 200
    assert "could not tell what kind" not in notes(r) and "Stacked washer" not in notes(r), notes(r)


@pytest.mark.parametrize("line,kind", [
    ("Stacked washer and dryer hookups, dishwasher.", "hookups"),
    ("Shared stacked washer and dryer in the basement, dishwasher.", "in_building"),
    ("Coin laundry in the building. Dishwasher.", "in_building"),
    ("No washer or dryer. Dishwasher.", "none"),
])
def test_stacked_negatives(line, kind):
    assert read(HEAD + line)["laundry"] == kind


def test_unclear_laundry_note_quotes_only_the_laundry_item():
    r = read(HEAD + "Laundry available, dishwasher, one-car garage $90, built 2023.")
    n = notes(r)
    assert not r.get("laundry")
    assert 'laundry ("Laundry available")' in n, n
    assert "dishwasher" not in n.lower() and "garage" not in n.lower().split("laundry")[1], n
    r = read(HEAD + "Dishwasher; washer and dryer available for a fee; one-car garage.")
    assert 'laundry ("washer and dryer available for a fee")' in notes(r), notes(r)
