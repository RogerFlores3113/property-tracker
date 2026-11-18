"""Cycle 36, G4: the parking kind is never guessed (roommates l4, l8, l10)."""
from __future__ import annotations

import os

import pytest

from prophelper import parsers as P

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel")


def fixture(name: str) -> str:
    with open(os.path.join(FIX, name), encoding="utf-8") as fh:
        return fh.read()


BASE = "Nice 2 bed 1 bath apartment. 100 Main St, Chicago IL 60601. Rent $1,800/mo. "


def read(line: str) -> dict:
    return P.parse_listing(BASE + line, "")


@pytest.mark.parametrize("line", [
    "Parking included.",
    "Parking: included",
    "1 spot included.",
    "Parking - 1 space included in rent.",
    "Free parking.",
    "Parking: free",
    "Parking is included in the rent.",
    "Parking: 1 spot included; laundry in building.",
    "Parking: 1 spot included\nLaundry: on-site",
    "Laundry on-site. Parking included.",
    "Free on-site parking.",
    "1 parking space included, 2nd space $90/mo.",
])
def test_included_parking_has_no_kind(line):
    r = read(line)
    assert not r.get("parking")
    assert r.get("parking_cost") == 0


@pytest.mark.parametrize("line", [
    "Parking: 1 indoor space REQUIRED $150/mo",
    "Indoor parking required, $150 a month.",
    "1 indoor spot is required ($150/mo).",
    "Parking (indoor, required): $150 per month",
    "Parking: indoor space, required, $150/mo\nLaundry: on-site",
    "Laundry: on-site | Parking: 1 indoor space REQUIRED $150/mo | Pets: none",
])
def test_required_indoor_space_is_garage_never_lot(line):
    r = read(line)
    assert r.get("parking") == "garage"
    assert r.get("parking_cost") == 150


@pytest.mark.parametrize("line,kind,cost", [
    ("Parking: surface lot included", "lot", 0),
    ("Free off-street parking.", "lot", 0),
    ("Parking: assigned spot included.", "lot", 0),
    ("Parking: street", "street", None),
    ("Garage parking included.", "garage", 0),
    ("Covered parking $60/mo.", "covered", 60),
])
def test_named_kind_is_kept(line, kind, cost):
    r = read(line)
    assert r.get("parking") == kind
    assert r.get("parking_cost") == cost


def test_note_says_kind_unknown_once():
    r = read("Parking included.")
    n = r["found_in_listing"]
    assert n.count("does not say what kind of parking") == 1
    assert "lot" not in (r.get("parking") or "")


def test_reviewer_listing_l4_one_spot_included():
    r = P.parse_listing(fixture("r35-roommates-l4.txt"), "")
    assert not r.get("parking") and r["parking_cost"] == 0


def test_reviewer_listing_l8_parking_included():
    r = P.parse_listing(fixture("r35-roommates-l8.txt"), "")
    assert not r.get("parking") and r["parking_cost"] == 0
    assert r["price"] == 3600


def test_reviewer_listing_l10_indoor_required():
    r = P.parse_listing(fixture("r35-roommates-l10.txt"), "")
    assert r["parking"] == "garage" and r["parking_cost"] == 150
    assert r["price"] == 3280
