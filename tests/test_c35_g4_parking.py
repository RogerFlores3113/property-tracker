"""Cycle 35, G4: optional garage at a price, "1 spot included" with no kind, and "garage or covered, $60/mo" (uiuc l27, roommates l11, l12, nontech l6)."""
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
    return r.get("found_in_listing", "")


HEAD = "1 bed 1 bath. Rent $1,525 per month. "
TAIL = " Security deposit $1,525. 1204 N Prospect Ave, Champaign, IL 61820"


@pytest.mark.parametrize("park", [
    "Detached garage space available $85/mo.",
    "Garage available $85/mo.",
    "Garage available: $85 per month.",
    "Garage space available for $85 a month.",
    "Detached garage available for rent, $85/mo.",
    "Garage parking is available for an additional $85/month.",
    "Garage available ($85/mo).",
    "garage available $85",
    "GARAGE AVAILABLE $85/MO",
    "Optional garage $85/mo.",
    "Garage available - $85/mo.",
])
def test_garage_available_is_optional_at_its_price(park):
    r = read(HEAD + park + TAIL)
    assert "parking" not in r and "parking_cost" not in r, (r.get("parking"), r.get("parking_cost"))
    n = notes(r)
    assert "garage is available for $85 a month" in n.lower().replace("a garage", "a garage") or "$85" in n, n
    assert "optional" in n and "not counted in the monthly cost" in n, n
    assert n.lower().count("$85") == 1, n


def test_uiuc_l27_whole_listing():
    r = read(fixture("r34-uiuc-l27.txt"))
    assert r["price"] == 1525 and r["beds"] == 1 and r["baths"] == 1 and r["deposit"] == 1525 and r["application_fee"] == 50
    assert r["laundry"] == "in_unit" and r["pets"] == "none"
    assert "parking" not in r and "parking_cost" not in r
    assert "A garage is available for $85 a month. It looks optional, so it is not counted in the monthly cost." in notes(r)
    assert notes(r).count("$85") == 1


def test_a_garage_that_comes_with_the_rent_is_not_called_optional():
    r = read(HEAD + "Garage available now, included in rent." + TAIL)
    assert "$85" not in notes(r)
    assert r.get("parking") == "garage" and r.get("parking_cost") == 0


@pytest.mark.parametrize("park", [
    "Parking: 1 spot included in rent.",
    "1 spot included in rent.",
    "One parking spot included.",
    "Parking: 1 space included in the rent.",
    "Includes 1 parking space.",
    "1 parking spot is included.",
    "Parking: 1 spot included",
    "PARKING: 1 SPOT INCLUDED IN RENT",
    "1 spot included | Pets ok",
])
def test_one_spot_included_never_guesses_a_lot(park):
    r = read(HEAD + park + TAIL)
    assert "parking" not in r, (r.get("parking"), park)
    assert r.get("parking_cost") == 0
    assert "kind" in notes(r) or "type" in notes(r), notes(r)
    assert "not counted" not in notes(r)


def test_roommates_l12_whole_listing():
    r = read(fixture("r34-roommates-l12.txt"))
    assert r["price"] == 3000 and r["beds"] == 3 and r["baths"] == 2 and r["laundry"] == "in_unit"
    assert "parking" not in r and r["parking_cost"] == 0
    assert r["pets"] == "cats" and r["pet_deposit"] == 250 and r["deposit"] == 4500 and r["application_fee"] == 45 and r["broker_fee"] == 3000


def test_roommates_l11_whole_listing_is_unchanged():
    r = read(fixture("r34-roommates-l11.txt"))
    assert r["parking"] == "garage" and r["parking_cost"] == 210 and r["price"] == 3180 and r["pet_fee"] == 350 and r["pet_rent"] == 30


@pytest.mark.parametrize("park", [
    "1 surface lot spot included.",
    "Parking: 1 off-street spot included.",
    "1 garage spot included.",
    "1 covered spot included.",
    "1 driveway spot included.",
])
def test_a_spot_with_its_kind_keeps_the_kind(park):
    r = read(HEAD + park + TAIL)
    kind = {"surface": "lot", "off-street": "lot", "garage": "garage", "covered": "covered", "driveway": "lot"}[next(k for k in ("surface", "off-street", "garage", "covered", "driveway") if k in park)]
    assert r["parking"] == kind and r["parking_cost"] == 0, (r.get("parking"), r.get("parking_cost"), park)


@pytest.mark.parametrize("park", [
    "Parking: garage or covered, $60/mo.",
    "Parking: Garage or covered - $60/mo.",
    "Parking: garage/covered, $60 per month.",
    "Parking: covered or garage, $60/month.",
    "PARKING: GARAGE OR COVERED, $60/MO.",
    "Parking: garage or carport, $60/mo.",
    "Garage or covered parking, $60/mo.",
    "Parking - garage or covered ($60/mo).",
    "Parking: garage or covered, $60/mo\n",
    "Parking: garage or covered, $60/mo | Pets ok.",
])
def test_garage_or_covered_with_one_price_is_covered_at_that_price(park):
    r = read("2BR Duplex. Rent $1,495. " + park + " HOA none. 22 E 1st Ave Columbus OH 43201")
    assert r["parking"] == "covered" and r["parking_cost"] == 60, (r.get("parking"), r.get("parking_cost"), notes(r))
    assert notes(r).lower().count("garage or covered") <= 1 or "garage or carport" in notes(r).lower()


def test_nontech_l6_whole_listing():
    r = read(fixture("r34-nontech-l6.txt"))
    assert r["price"] == 1495 and r["parking"] == "covered" and r["parking_cost"] == 60
    assert r["deposit"] == 1495 and r["pet_deposit"] == 400 and r["pet_weight_limit"] == 40
    assert "alternatives" not in notes(r), notes(r)


@pytest.mark.parametrize("park,kind,cost", [
    ("Parking: garage $120, covered $60.", "garage", 120),
    ("Parking: covered $60, or garage $120.", "garage", 120),
])
def test_two_priced_choices_are_still_choices(park, kind, cost):
    r = read("2BR Duplex. Rent $1,495. " + park + " 22 E 1st Ave Columbus OH 43201")
    assert r["parking"] == kind and r["parking_cost"] == cost, (r.get("parking"), r.get("parking_cost"), notes(r))
    assert "alternatives" in notes(r)


def test_an_included_garage_with_a_priced_covered_option_keeps_the_included_one():
    r = read("2BR Duplex. Rent $1,495. Parking: garage included, covered $60. 22 E 1st Ave Columbus OH 43201")
    assert r["parking"] == "garage" and r["parking_cost"] == 0
    assert "optional" in notes(r) and "$60" in notes(r)


def test_garage_or_covered_with_an_optional_price_is_not_counted():
    r = read("2BR Duplex. Rent $1,495. Parking: garage or covered, $60/mo optional. 22 E 1st Ave Columbus OH 43201")
    assert r.get("parking_cost") in (None, 0)
