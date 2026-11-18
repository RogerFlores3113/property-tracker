"""Cycle 37 G6 item 3 (buyer l6): "4 percent of the price" is worked out in dollars exactly like "4%"."""
import os

import pytest

from prophelper.parsers import parse_listing

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "panel")


def fixture(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


def read(body, price=300000):
    return parse_listing(f"Test Condo ${price:,}\n12 Oak St #4, Columbus, OH 43202\n2 bed 2 bath. " + body, "", buying=True)


@pytest.mark.parametrize("line,credit", [
    ("Seller will pay 4 percent of the price in closing costs.", 12000),
    ("Seller to credit 3 percent of price toward closing.", 9000),
    ("Seller concession: 2 percent of the purchase price toward buyer's closing costs", 6000),
    ("Seller pays 3.5 percent of the price toward closing costs; HOA $200/mo", 10500),
    ("HOA $200/mo\nSeller contributes 3 per cent of the purchase price toward closing", 9000),
    ("Seller will give three percent of the price toward closing costs.", 9000),
    ("Seller credit (4 percent of price) toward closing costs.", 12000),
    ("Seller will pay 4% of the price in closing costs.", 12000),
])
def test_seller_percent_wordings(line, credit):
    out = read(line)
    assert out["seller_credit"] == credit
    assert "Ask what it comes to" not in out["found_in_listing"]


def test_reviewer_listing_l6():
    out = parse_listing(fixture("r36-buyer-l6.txt"), "", buying=True)
    assert out["seller_credit"] == 13400
    assert "Ask what it comes to" not in out["found_in_listing"]


@pytest.mark.parametrize("line,cc", [
    ("Closing costs about 3 percent of the price.", 9000),
    ("Buyer closing costs: 2.5 percent of the purchase price", 7500),
])
def test_closing_cost_percent_wordings(line, cc):
    out = read(line)
    assert out.get("closing_costs") == cc


def test_negatives_percent_of_loan_and_unrelated_percent():
    out = read("Closing costs about 3 percent of the loan.")
    assert out.get("closing_costs") is None
    out = read("Seller credit unknown. Percent of owners who live here: high. HOA $200/mo")
    assert out.get("seller_credit") is None
    assert out["hoa"] == 200
