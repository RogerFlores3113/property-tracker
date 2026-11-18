"""Cycle 37, G4: "2 outdoor spots, $100 each per month" is $200 for two spots (roommates l13)."""
from __future__ import annotations

import os

import pytest

from prophelper import parsers as P

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel")
BASE = "3 BR / 2 BA, 4700 N Lincoln Ave, Chicago IL 60625. Rent: $3,150/mo. "


def read(t):
    return P.parse_listing(t, "")


@pytest.mark.parametrize("line", [
    "Parking: 2 outdoor spots, $100 each per month.",
    "Parking: 2 outdoor spots, $100 each per month",
    "Parking - 2 uncovered spaces at $100 each per month",
    "Parking spots: 2 outdoor spots, $100 each per month. Laundry in building.",
    "Parking: $100 each per month for 2 outdoor spots.",
    "Parking: two outdoor spaces, $100/month each.",
    "Laundry in building\nParking: 2 outdoor spots, $100 each per month\nPets ok",
])
def test_each_times_count(line):
    r = read(BASE + line)
    assert r["price"] == 3150
    assert r["parking_cost"] == 200


@pytest.mark.parametrize("line", [
    "Parking: 1 outdoor spot, $100 each per month.",
    "Parking: outdoor spot $100 per month.",
    "Parking: 2 outdoor spots, $100 per month for both.",
])
def test_single_spot_stays_100(line):
    r = read(BASE + line)
    assert r["parking_cost"] == 100


def test_whole_listing_l13():
    with open(os.path.join(FIX, "r36-roommates-l13.txt"), encoding="utf-8") as fh:
        r = read(fh.read())
    assert r["price"] == 3150 and r["parking_cost"] == 200
    assert "$200 a month (all the spaces)" in r["found_in_listing"]
