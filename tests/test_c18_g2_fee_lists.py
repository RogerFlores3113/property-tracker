"""Cycle 18 G2: a list of named monthly fees keeps every figure, whatever the layout."""
import pytest

from prophelper.parsers import parse_listing


def notes(r):
    return r.get("found_in_listing", "")


@pytest.mark.parametrize("text", [
    "2BR $1,500/mo. Monthly pest control $6, package locker $4, valet trash $20.",
    "2BR $1,500/mo. Fees: pest control $6, package locker $4, valet trash $20.",
    "2BR $1,500/mo. Monthly fees (pest control $6, package locker $4, valet trash $20)",
    "2BR $1,500/mo.\nMonthly fees:\n- pest control $6\n- package locker $4\n- valet trash $20",
    "2BR $1,500/mo. Pest control - $6/mo; package locker - $4/mo; valet trash - $20/mo",
])
def test_pest_locker_valet_is_thirty(text):
    r = parse_listing(text)
    assert r["other_monthly_fees"] == 30
    assert "not counted anywhere" not in notes(r)
    assert "optional" not in notes(r).replace("If it is optional, take it out", "")


@pytest.mark.parametrize("text", [
    "3 bed house, $2,395/mo. Monthly pest control $12, flat $10/mo package for trash valet.",
    "3 bed house, $2,395/mo.\nMonthly pest control $12\nFlat $10/mo package for trash valet",
    "3 bed house, $2,395/mo (monthly pest control $12 and a $10 package fee for trash valet)",
])
def test_pest_and_package_is_twenty_two(text):
    r = parse_listing(text)
    assert r["other_monthly_fees"] == 22
    assert "the $12, fee" not in notes(r) and "not counted anywhere" not in notes(r)


@pytest.mark.parametrize("text", [
    "2 bed 1 bath. Rent $1,380 a month. $35/month for lawn care and snow removal.",
    "2 bed 1 bath. Rent $1,380 a month.\n- $35 a month for snow removal and lawn care",
    "2 bed 1 bath. Rent $1,380 a month. Lawn care and snow removal $35 per month.",
])
def test_lawn_and_snow_is_counted_once(text):
    r = parse_listing(text)
    assert r["other_monthly_fees"] == 35
    assert "not counted anywhere" not in notes(r)


@pytest.mark.parametrize("text", [
    "2 Bedroom Townhome - Hilliard\nPrice: $1,465\nFees: $25 amenity fee monthly, $10 monthly package locker fee, $15 monthly trash valet.",
    "2 Bedroom Townhome\nPrice: $1,465\nAmenity fee $25/mo, package locker fee $10/mo, trash valet $15/mo",
    "2 Bedroom Townhome\nPrice: $1,465\nFees: amenity $25 monthly; package locker $10 monthly; trash valet $15 monthly",
])
def test_locker_and_valet_are_not_mixed_up(text):
    r = parse_listing(text)
    assert r["other_monthly_fees"] == 50
    n = notes(r)
    assert "Locker is $15" not in n and "looks optional" not in n


def test_equal_amounts_both_count():
    r = parse_listing("2BR $1,465. Pest $6/mo, valet trash $6/mo.")
    assert r["other_monthly_fees"] == 12


def test_one_time_and_optional_items_are_not_monthly():
    r = parse_listing("2BR $1,465. Pest control $6 one-time. Package locker optional $4/mo.")
    assert "other_monthly_fees" not in r


def test_quarterly_pest_control_is_not_monthly():
    r = parse_listing("2BR $1,465. Quarterly pest control fee of $30 (about $10 a month).")
    assert "other_monthly_fees" not in r
