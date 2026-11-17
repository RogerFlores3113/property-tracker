"""Cycle 30 G6: tax and HOA given every quarter, each quarter, for the half-year, each half, twice a year, four times a year or per installment."""
import os

import pytest

from prophelper.parsers import parse_listing

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "panel")
BASE = "Condo $300,000\n2 bed 2 bath, 1,000 sqft. "


def fixture(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


def read(line):
    return parse_listing(BASE + line, buying=True)


@pytest.mark.parametrize("line,expected", [
    ("Property taxes: $1,100 every quarter.", 4400),
    ("Taxes $1,100 each quarter.", 4400),
    ("Taxes are $1,100 a quarter.", 4400),
    ("Taxes $1,100 due every quarter.", 4400),
    ("Taxes (billed every quarter): $1,100.", 4400),
    ("Taxes $1,100 every 3 months.", 4400),
    ("Property tax: $1,100, due four times a year.", 4400),
    ("Taxes are $2,900 for the half-year (billed twice a year).", 5800),
    ("Taxes $2,900 each half.", 5800),
    ("Taxes: $2,900 every half year.", 5800),
    ("Taxes: $2,900 for the half year.", 5800),
    ("Taxes $2,900 every six months.", 5800),
    ("Property tax is $2,900, billed twice a year.", 5800),
    ("Taxes $2,900 twice yearly.", 5800),
    ("Taxes $4,100 per year.", 4100),
    ("Taxes $342/mo.", 4104),
])
def test_tax_period_words(line, expected):
    out = read(line)
    assert out["property_tax"] == expected
    if expected not in (4100, 4104):
        assert "$" + f"{expected:,}" + " a year" in out["found_in_listing"]


@pytest.mark.parametrize("line", [
    "Taxes: $1,100 per installment.",
    "Taxes $1,100 per bill.",
    "Taxes: $1,100 each installment.",
])
def test_tax_per_installment_is_left_empty_with_note(line):
    out = read(line)
    assert out.get("property_tax") in (None, "")
    assert "$1,100" in out["found_in_listing"] and "left empty" in out["found_in_listing"]


def test_reviewer_listing_l6_quarter_tax():
    out = parse_listing(fixture("r29-buyer-l6.txt"), buying=True)
    assert out["property_tax"] == 4400
    assert "$1,100 per quarter" in out["found_in_listing"] and "$4,400 a year" in out["found_in_listing"]
    assert out["hoa"] == 215


def test_reviewer_listing_l7_half_year_tax():
    out = parse_listing(fixture("r29-buyer-l7.txt"), buying=True)
    assert out["property_tax"] == 5800
    assert "$2,900 per half year" in out["found_in_listing"]


@pytest.mark.parametrize("line,expected", [
    ("HOA dues: $780 every quarter.", 260),
    ("HOA $780 each quarter.", 260),
    ("HOA is $780 a quarter.", 260),
    ("HOA $1,560 for the half-year.", 260),
    ("HOA dues $1,560 each half.", 260),
    ("HOA $1,560 every half year.", 260),
    ("HOA $1,560, billed twice a year.", 260),
    ("HOA $780 due four times a year.", 260),
    ("HOA fee $390 every two months.", 195),
    ("HOA $390 per two months.", 195),
    ("Condo fee: $2,400 for the year.", 200),
    ("HOA $215 each month.", 215),
    ("HOA $780, billed quarterly.", 260),
])
def test_hoa_period_words(line, expected):
    out = read(line)
    assert out["hoa"] == expected
    assert "not counted anywhere" not in out.get("found_in_listing", "")


def test_hoa_per_installment_left_empty():
    out = read("HOA $780 per installment.")
    assert out.get("hoa") in (None, "")
    assert "$780" in out["found_in_listing"]
