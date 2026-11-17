"""Cycle 32, G4: a clearly named monthly item ("Covered carport: $40/mo") gets a plain note, not "Check what it is for"."""
from __future__ import annotations

import os

import pytest

from prophelper import parsers as P

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel")


def read(text: str) -> dict:
    return P.parse_listing(text, "")


def notes(r: dict) -> str:
    return str(r.get("found_in_listing") or "")


def fixture(name: str) -> str:
    with open(os.path.join(FIX, name), encoding="utf-8") as fh:
        return fh.read()


def test_reviewer_listing():
    r = read(fixture("r31-nontech-l5.txt"))
    n = notes(r)
    assert r["parking_cost"] == 75
    assert "The covered carport is $40 a month. It is another parking choice, so it is not counted; the parking cost counted is $75 a month. Ask which one you would use." in n
    assert '"Covered carport: $40/mo"' not in n
    assert not [line for line in n.split("\n") if "carport" in line and "Check what it is for" in line]


@pytest.mark.parametrize("line,label", [
    ("Attached garage: $75/mo. Covered carport: $40/mo", "covered carport"),
    ("Attached garage $75/mo; carport $40 per month", "carport"),
    ("Garage parking $75 a month, carport parking available at $40/mo", None),
    ("Garage $75/mo\nCarport: $40 monthly", "carport"),
    ("Garage $75/mo (carport $40/mo also)", None),
    ("Attached garage $75 per month | Covered carport $40 per month", "covered carport"),
])
def test_carport_beside_a_garage(line, label):
    r = read("2 bed 2 bath $1,495/mo. Water included.\n" + line + "\nDeposit $1,495.")
    n = notes(r)
    assert r.get("parking_cost") == 75
    assert "Check what it is for" not in n or label is None
    if label:
        assert f"The {label} is $40 a month. It is another parking choice, so it is not counted; the parking cost counted is $75 a month." in n


@pytest.mark.parametrize("line,label", [
    ("Storage unit: $50/mo", "storage unit"),
    ("Bike storage $10 per month", "bike storage"),
    ("Package locker $12 monthly", "package locker"),
])
def test_other_named_items(line, label):
    r = read("2 bed 2 bath $1,495/mo. Water included.\n" + line + "\nDeposit $1,495.")
    n = notes(r)
    if f"The {label} is" in n:
        assert "It is not counted because the listing does not say it is required." in n
        assert "Check what it is for" not in n.split(f"The {label} is")[1].split("\n")[0]


def test_unnamed_items_keep_the_old_note():
    r = read("2 bed 2 bath $1,495/mo. Water included.\nMystery charge $88 monthly\nDeposit $1,495.")
    assert "Check what it is for" in notes(r)


def test_counted_parking_has_no_note():
    r = read("2 bed 2 bath $1,495/mo. Water included.\nCovered carport: $40/mo\nDeposit $1,495.")
    assert r.get("parking_cost") == 40
    assert "carport" not in notes(r).lower() or "not counted" not in notes(r)
