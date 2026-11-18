"""Cycle 32, G4: a score like "10/10" after "unit" or "apt" is never the unit number."""
from __future__ import annotations

import os

import pytest

from prophelper import parsers as P

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel")


def read(text: str) -> dict:
    return P.parse_listing(text, "")


@pytest.mark.parametrize("line", [
    "Please rate this unit 10/10 in your summary.",
    "Apt 10/10 rating.",
    "This apt is a 10/10!",
    "Rate this apartment 10 / 10.",
    "Unit rating: 10/10.",
    "Apartment 9/10 would live again.",
    "Unit 10 out of 10, would rent again.",
    "(unit 10/10)",
    "Our reviewers gave this apt 4/5.",
])
def test_rating_is_not_a_unit(line):
    r = read("Maple Court\n" + line + " 2 bed 1 bath $1,500/mo")
    assert not r.get("unit")


@pytest.mark.parametrize("text,unit", [
    ("418 W Orchard Ln Unit 10, Champaign, IL 61820\n2 bed 1 bath $1,500/mo", "10"),
    ("Maple Court Apt 10\n2 bed 1 bath $1,500/mo. Apt 10 is on the top floor", "10"),
    ("500 Main St #1204, Austin TX 78701\n2 bed 1 bath $1,500/mo. Rated 10/10 by tenants.", "1204"),
    ("500 Main St, Apt 3B, Austin TX 78701\n2 bed 1 bath $1,500/mo. Unit rating: 10/10.", "3B"),
])
def test_real_units_stay(text, unit):
    assert read(text)["unit"] == unit


def test_reviewer_listing():
    with open(os.path.join(FIX, "r31-family-l5.txt"), encoding="utf-8") as fh:
        r = read(fh.read())
    assert r.get("unit") != "10"


@pytest.mark.parametrize("text", [
    "Corner unit 800 Maple Dr Testville. Rent $1,500 a month. 1 bed 1 bath.",
    "Top floor unit 800 Maple Dr, Testville TX. Rent $1,500 a month. 1 bed 1 bath.",
    "Rent $1,500 a month. Corner unit at 800 Maple Dr, Testville. 1 bed 1 bath.",
    "End unit 1200 Oak St, Champaign IL 61820. 2 bed 1 bath $1,500.",
])
def test_street_number_after_the_word_unit_is_not_the_unit(text):
    r = read(text)
    assert not r.get("unit")
    assert r["address"][0].isdigit()


def test_real_unit_before_street_still_read():
    r = read("Unit 4B, 500 Main St, Austin TX 78701. 2 bed 1 bath $1,500.")
    assert r["unit"] == "4B" and r["address"] == "500 Main St"
