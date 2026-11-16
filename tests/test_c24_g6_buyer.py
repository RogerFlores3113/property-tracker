"""Cycle 24 G6: a second monthly charge next to the HOA, closing costs in one line, quarterly dues still read."""
import pytest
from prophelper.money import buy_cost
from prophelper.parsers import parse_listing

BASE = "2 bed 2 bath condo for sale, $339,000. "


def buy(t):
    return parse_listing(BASE + t, "", buying=True)


@pytest.mark.parametrize("text,hoa", [
    ("HOA $475/month plus a $75 monthly capital reserve fee. Tax $6,400/yr.", 550),
    ("HOA $300/month and a $40 per month amenity fee. Tax $4,000/yr.", 340),
    ("HOA $300/month. Capital reserve fee: $60/month. Tax $4,000/yr.", 360),
])
def test_extra_monthly_added_to_hoa(text, hoa):
    r = buy(text)
    assert r["hoa"] == hoa
    assert "added" in r["found_in_listing"] and "monthly" in r["found_in_listing"]


def test_extra_one_time_or_yearly_not_added():
    assert buy("HOA $300/month. One-time capital reserve fee $500 at closing.")["hoa"] == 300
    assert buy("HOA $300/month. Amenity fee $600 per year.")["hoa"] == 300


@pytest.mark.parametrize("text,value", [
    ("Lender and title fees run roughly $7,400. ", 7400),
    ("Closing costs about $7,400. ", 7400),
    ("Expect around $7,400 in lender and title fees. ", 7400),
])
def test_closing_one_line(text, value):
    r = buy(text + "HOA $200/month.")
    assert r["closing_costs"] == value
    if "lender" in text.lower():
        assert "read as the closing costs" in r["found_in_listing"]


def test_seller_fees_not_closing():
    assert "closing_costs" not in buy("Seller pays lender and title fees of $7,400. HOA $200/month.")


def test_quarterly_dues():
    assert buy("Common charges: $1,020 per quarter.")["hoa"] == 340


def test_other_monthly_fees_counted_in_buy_cost():
    place = {"price": 339000, "property_tax": 4800, "insurance": 1200, "hoa": 300}
    a = buy_cost(place)["total"]
    b = buy_cost({**place, "other_monthly_fees": 75})["total"]
    assert round(b - a, 2) == 75
