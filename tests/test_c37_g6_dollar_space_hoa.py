"""Cycle 37 G6 item 2 (buyer): a space after the dollar sign plus a spaced thousands number ("HOA $ 2 400 yearly") is read whole."""
import os

import pytest

from prophelper.parsers import parse_listing

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "panel")


def fixture(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


def read(body, price=250000):
    return parse_listing(f"Test Condo ${price:,}\n12 Oak St #4, Columbus, OH 43202\n2 bed 2 bath. " + body, "", buying=True)


@pytest.mark.parametrize("line,hoa", [
    ("HOA $ 2 400 yearly", 200),
    ("HOA $ 2 880 per year", 240),
    ("HOA: $ 2 400 annually.", 200),
    ("HOA dues $ 2 400 a year; pets ok", 200),
    ("Parking street | HOA $ 2 400 / year | Pets ok", 200),
    ("- HOA $ 2 400 yearly\n- Taxes $3,000/yr", 200),
    ("Condo fee $ 1 275 per quarter", 425),
    ("HOA $ 275 per month", 275),
])
def test_hoa_with_space_after_dollar(line, hoa):
    out = read(line)
    assert out["hoa"] == hoa
    notes = out.get("found_in_listing") or ""
    assert "$2 " not in notes and "$ $" not in notes and "the $2" not in notes


def test_tax_and_insurance_with_space_after_dollar():
    out = read("Taxes $ 5 200 annually. HOA $300/mo.")
    assert out["property_tax"] == 5200 and out["hoa"] == 300


def test_reviewer_listing_l5():
    out = parse_listing(fixture("r36-buyer-l5.txt"), "", buying=True)
    assert out["hoa"] == 200 and out["property_tax"] == 5200
    assert "HOA $ 2 400 yearly" not in out["found_in_listing"]
    assert "not counted anywhere. Check what it is for" not in out["found_in_listing"].split("HOA")[-1]


def test_negatives_price_and_rent_still_whole():
    assert parse_listing(fixture("r36-buyer-l3.txt"), "", buying=True)["price"] == 298000
    assert parse_listing(fixture("r36-buyer-l1.txt"), "", buying=True)["price"] == 312500
    assert read("HOA $240 monthly.")["hoa"] == 240
