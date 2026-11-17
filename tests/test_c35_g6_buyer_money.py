"""Cycle 35 G6: buyer money. Item 1: a buyer-paid transfer fee is a named one-time closing item, never the total closing costs."""
import os

import pytest

from prophelper import money
from prophelper.parsers import parse_listing

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "panel")


def fixture(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


def read(text_, price=None):
    """The listing read the way add_place reads it: a price sent as a field is passed as the known price."""
    return parse_listing(text_, "", buying=True, current=({"price": price} if price else None))


def full(text_, price=None):
    out = read(text_, price)
    place = {**out, "listing_text": text_}
    if price:
        place["price"] = price
    return out, place, money.cash_to_close(place)


def notes(out):
    return out.get("found_in_listing", "")


def parts(cash):
    return {p["label"]: p["amount"] for p in cash["parts"]}


BASE = "HOA $200. Taxes $3,000/yr. Insurance $50/mo. "


# ---- item 1 (buyer T1): "Buyer pays $400 transfer fee." is one named item, never the whole closing costs
@pytest.mark.parametrize("line", [
    "Buyer pays $400 transfer fee.",
    "Transfer fee $400 paid by buyer",
    "Transfer fee: $400 (paid by the buyer).",
    "The buyer will pay a $400 transfer fee at closing.",
    "Buyer to pay transfer fee of $400",
    "- Buyer pays: $400 transfer fee\n- Parking: street",
    "Closing: buyer pays $400 transfer fee | Parking street",
])
def test_buyer_transfer_fee_is_not_the_closing_costs(line):
    out, place, cash = full("Condo\n" + BASE + line, 250000)
    assert out.get("closing_costs") in (None, "")
    p = parts(cash)
    assert p["One-time fee at closing (transfer fee)"] == 400
    guess = [v for k, v in p.items() if k.startswith("Closing costs (a guess")]
    assert guess == [7500]
    assert cash["total"] == 50000 + 7500 + 400
    assert "counted in the cash to close as a one-time fee" in notes(out)
    assert "not counted" not in notes(out).lower()


def test_buyer_transfer_fee_beside_stated_closing_costs_is_added_on_top():
    out, _p, cash = full("Condo\n" + BASE + "Estimated closing costs $9,800. Buyer pays one-time $3,200 transfer fee at closing.", 450000)
    assert out["closing_costs"] == 9800
    assert parts(cash)["Closing costs"] == 9800
    assert parts(cash)["One-time fee at closing (transfer fee)"] == 3200


def test_transfer_fee_inside_the_stated_closing_total_is_not_added_twice():
    out, _p, cash = full("Condo\n" + BASE + "Buyer closing costs about $9,000, including a $400 transfer fee paid by buyer.", 250000)
    assert out["closing_costs"] == 9000
    assert "One-time fee at closing (transfer fee)" not in parts(cash)


def test_seller_paid_and_unnamed_transfer_fee_stay_out():
    for line, who in (("Seller pays $400 transfer fee.", "seller"), ("Transfer fee $400.", "")):
        out, _p, cash = full("Condo\n" + BASE + line, 250000)
        assert out.get("closing_costs") in (None, "")
        assert "One-time fee at closing (transfer fee)" not in parts(cash)
        assert "$400 transfer fee" in notes(out)
        if who:
            assert "seller pays" in notes(out)


def test_transfer_fee_with_the_price_in_the_text_matches_the_price_field():
    a, _p, ca = full("Condo $250,000\n" + BASE + "Buyer pays $400 transfer fee.")
    b, _p2, cb = full("Condo\n" + BASE + "Buyer pays $400 transfer fee.", 250000)
    assert parts(ca) == parts(cb)


def test_transfer_fee_with_seller_credit_keeps_the_credit_and_the_fee():
    out, _p, cash = full("Condo\n" + BASE + "Seller will pay $7,000 in closing costs. Transfer fee paid by buyer $1,500.", 300000)
    assert out["seller_credit"] == 7000 and out.get("closing_costs") in (None, "")
    p = parts(cash)
    assert p["One-time fee at closing (transfer fee)"] == 1500
    assert cash["total"] == 60000 + 9000 + 1500 - 7000
