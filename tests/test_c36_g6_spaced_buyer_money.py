"""Cycle 36 G6 items 1 to 3 (rule ee for buyer fields): HOA, tax and square feet written with a space or dot as the thousands mark are read whole."""
import os

import pytest

from prophelper.parsers import parse_listing

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "panel")


def fixture(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


def read(body, price=250000):
    return parse_listing(f"Test Condo ${price:,}\n12 Oak St #4, Columbus, OH 43202\n2 bed 2 bath. " + body, "", buying=True)


def notes(out):
    return out.get("found_in_listing") or ""


# ---- item 1: HOA "$2 400 annual / a year / yearly" is $200 a month, never $2
@pytest.mark.parametrize("line", [
    "HOA $2 400 annual.",
    "HOA $2 400 a year",
    "HOA $2 400 yearly",
    "HOA: $2 400 annually",
    "HOA dues $2 400 per year.",
    "Condo fee $2 400 annual; parking street",
    "HOA 2 400 annual",
    "HOA: 2.400 yearly",
    "Parking street | HOA $2 400 a year | Pets ok",
    "- HOA $2 400 annual\n- Taxes $3,000/yr",
])
def test_hoa_spaced_thousands_with_a_year_word(line):
    out = read(line)
    assert out["hoa"] == 200
    assert "$2 " not in notes(out) and "the $2 amount" not in notes(out)


def test_hoa_negative_plain_monthly_and_small():
    assert read("HOA $240 monthly.")["hoa"] == 240
    assert read("HOA $2,400 annual.")["hoa"] == 200
    assert read("HOA 2 400 Main St side entrance.").get("hoa") != 2


# ---- item 2: tax "$5 200 annually" is read whole
@pytest.mark.parametrize("line", [
    "Taxes: $5 200 annually",
    "Property tax $5 200 a year",
    "Real estate taxes $5 200 yearly.",
    "Taxes: 5 200 annually",
    "Taxes $5.200 annually",
    "Taxes: $5 200 for the year",
    "Parking street; taxes $5 200 annually; pets ok",
])
def test_tax_spaced_thousands(line):
    out = read(line)
    assert out["property_tax"] == 5200
    assert "$5 amount" not in notes(out)


def test_tax_negative_does_not_invent():
    out = read("Taxes: $5,200 annually")
    assert out["property_tax"] == 5200


# ---- item 3: square feet with a space or dot thousands mark
@pytest.mark.parametrize("text,want", [
    ("1 180 sq ft", 1180),
    ("1 100 sq ft.", 1100),
    ("1.100 sf", 1100),
    ("1 050 sqft", 1050),
    ("Size: 1 180 sq ft", 1180),
    ("approx 1 150 square feet", 1150),
    ("Sq ft: 1.250", 1250),
    ("1 180 SQ FT, quiet street", 1180),
    ("1,180 sq ft", 1180),
    ("850 sq ft", 850),
])
def test_sqft_spaced_thousands(text, want):
    assert read(text)["sqft"] == want


def test_sqft_unclear_is_empty_with_a_note():
    out = parse_listing("Condo $250,000\n12 Oak St, Columbus, OH 43202\n3 2 100 sf", "", buying=True)
    assert "sqft" not in out
    assert '"3 2 100 sf"' in notes(out)


def test_sqft_negative_bath_count_before_size():
    out = read("2 bath 1 180 sf")
    assert out["sqft"] == 1180
    out = read("Walk score 90, 3 blocks from park")
    assert "sqft" not in out


# ---- the reviewer's listings, whole
def test_l51_whole():
    out = parse_listing(fixture("r35-buyer-l51.txt"), "", buying=True)
    assert out["sqft"] == 1180 and out["hoa"] == 395 and out["property_tax"] == 4800


def test_l52_whole():
    out = parse_listing(fixture("r35-buyer-l52.txt"), "", buying=True)
    assert out["sqft"] == 1350 and out["property_tax"] == 5200 and out["hoa"] == 425
    assert "not counted anywhere" not in notes(out)


def test_l54_whole():
    out = parse_listing(fixture("r35-buyer-l54.txt"), "", buying=True)
    assert out["sqft"] == 1050 and out["hoa"] == 275 and out["property_tax"] == 3900
