"""Cycle 18 G2: one-time fees the buyer pays at closing are in the cash to close; master dues; the listing's own cash figure."""
import pytest

from prophelper import money
from prophelper.parsers import parse_listing


def notes(r):
    return r.get("found_in_listing", "")


def cash(text, **extra):
    r = parse_listing(text, buying=True)
    place = {k: v for k, v in r.items() if k != "found_in_listing"}
    place.update(extra)
    place["listing_text"] = text
    return r, money.cash_to_close(place), money.true_monthly_cost(place, "buy")


def fee_parts(c):
    return {p["label"]: p["amount"] for p in c["parts"] if p["label"].startswith("One-time fee")}


@pytest.mark.parametrize("text,label,amount", [
    ("Condo $289,000 for sale. Buyer to pay $2,400 capital improvement fee at closing.", "capital improvement fee", 2400),
    ("Condo $289,000 for sale.\nCapital improvement fee: $2,400 due at closing (buyer).", "capital improvement fee", 2400),
    ("Condo $289,000 for sale - the buyer pays a $2,400 capital improvement fee.", "capital improvement fee", 2400),
    ("Condo $289,000 for sale. Buyer agrees to pay an $1,800 reserve fund contribution at closing.", "reserve fund contribution", 1800),
    ("Condo $289,000 for sale\nReserve contribution at closing $1,800", "reserve contribution", 1800),
    ("Condo $289,000 for sale. Buyer pays $800 move-in fee to the association.", "move-in fee", 800),
    ("Condo $289,000 for sale\nMove-in fee $800 due at closing", "move-in fee", 800),
])
def test_buyer_fee_is_in_cash_to_close(text, label, amount):
    r, c, _cost = cash(text)
    assert fee_parts(c) == {f"One-time fee at closing ({label})": amount}
    base = money.cash_to_close({"price": 289000})
    assert c["total"] == base["total"] + amount
    assert "counted in the cash to close" in notes(r) and "not counted anywhere" not in notes(r)


def test_buyer_fee_with_no_payer_is_left_out_with_a_note():
    r, c, _cost = cash("Condo $289,000 for sale. Capital improvement fee $2,400.")
    assert fee_parts(c) == {} and any("2,400" in w and "isn't known" in w for w in c["left_out"])
    assert "does not say who pays" in notes(r)


def test_seller_paid_fee_is_not_the_buyers():
    r, c, _cost = cash("Condo $289,000 for sale. Seller pays the $2,400 capital improvement fee at closing.")
    assert fee_parts(c) == {}


def test_capital_contribution_still_counts_once():
    r, c, _cost = cash("Condo $275,000. Special assessment $3,000 for roof, buyer to pay.\nCapital contribution at closing $1,000.")
    assert r["special_assessment"] == 4000 and r["special_assessment_payer"] == "buyer"
    assert fee_parts(c) == {} and sum(p["amount"] for p in c["parts"] if "Special" in p["label"]) == 4000


@pytest.mark.parametrize("text", [
    "Condo $289,000. HOA fee $210/month plus $600 annual master association dues.",
    "Condo $289,000\nHOA fee $210/month\nMaster association dues $600 per year",
    "Condo $289,000. HOA: $210/mo (plus $600/yr master association fee)",
])
def test_master_dues_are_added_to_the_hoa(text):
    r = parse_listing(text, buying=True)
    assert r["hoa"] == 260
    assert "monthly fee and it is not counted" not in notes(r) and "$50/month" in notes(r)


def test_listing_cash_to_close_is_compared():
    text = "Condo $289,000 for sale. Cash to close estimate: $55,000"
    r, c, cost = cash(text)
    note = cost["listing_estimate_note"]
    assert "$55,000" in note and f"${c['total']:,.0f}" in note
    r2, c2, cost2 = cash("Condo $289,000 for sale.\nCash needed to close: about $55,000")
    assert "$55,000" in cost2["listing_estimate_note"]
