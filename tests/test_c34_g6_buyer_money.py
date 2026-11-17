"""Cycle 34 G6: buyer money. Item 1: "split evenly between owners" is never a buyer/seller split."""
import os

import pytest

from prophelper import money
from prophelper.parsers import parse_listing

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "panel")
BASE = "Condo $300,000\n2 bed 2 bath, 1,000 sqft. "


def fixture(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


def read(text_):
    return parse_listing(text_, buying=True)


def full(text_):
    out = read(text_)
    place = {**out, "listing_text": text_}
    return out, place, money.cash_to_close(place)


def notes(out):
    return out.get("found_in_listing", "")


def parts(cash):
    return {p["label"]: p["amount"] for p in cash["parts"]}


# ---- item 1 (l31): the full monthly amount stays with the buyer
@pytest.mark.parametrize("line", [
    "Special assessment: $18,000 for the elevator, split evenly between owners over 36 months, buyer responsible for payments after closing.",
    "Special assessment of $18,000, shared equally among all unit owners, payable over 36 months. Buyer pays the installments after closing.",
    "Buyer takes over payments after closing. Special assessment $18,000 (elevator), divided evenly between the owners, over 36 months.",
    "Special assessment $18,000 over 36 months, split evenly among the homeowners; buyer responsible for the payments.",
    "Assessment: $18,000 over 36 months (split evenly between owners, buyer pays after closing)",
    "Special assessment $18,000, split evenly between owners | over 36 months | buyer responsible for payments after closing",
])
def test_owner_split_keeps_the_full_monthly_amount(line):
    out = read(BASE + line)
    assert out["other_monthly_fees"] == 500
    n = notes(out)
    assert "split 50/50" not in n and "Your half" not in n
    assert "split between the owners" in n and "full amount is counted" in n


def test_l31_whole_listing():
    out = read(fixture("r33-buyer-l31.txt"))
    assert out["other_monthly_fees"] == 500 and out["hoa"] == 410 and out["seller_credit"] == 3000 and out["closing_costs"] == 6100
    assert "split 50/50" not in notes(out) and "Your half" not in notes(out)
    assert "full amount is counted" in notes(out)


@pytest.mark.parametrize("line", [
    "Special assessment $18,000, split evenly between owners over 36 months. Payer not stated.",
    "Special assessment $18,000 over 36 months, shared equally by all owners.",
])
def test_owner_split_without_a_payer_is_never_halved_or_counted(line):
    out = read(BASE + line)
    assert out.get("other_monthly_fees") in (None, "")
    assert "Your half" not in notes(out)


# negatives: a real buyer/seller split is still halved
@pytest.mark.parametrize("line", [
    "Special assessment $18,000 over 36 months, split 50/50 between buyer and seller.",
    "Special assessment $18,000 over 36 months, split evenly between buyer and seller.",
])
def test_real_buyer_seller_split_still_halves(line):
    out = read(BASE + line)
    assert out["other_monthly_fees"] == 250
    assert "Your half is $9,000" in notes(out)


# ---- shared helpers for the cost checks
HOA_TAX = "HOA $200/month. Taxes $3,600/yr. Insurance $900/yr. "


def cost_of(text_, down=15, current=None):
    out = parse_listing(text_, buying=True, current=current)
    place = {**out, "listing_text": text_, "reader_notes": out.get("found_in_listing", "")}
    if current:
        place.update(current)
    cost = money.true_monthly_cost(place, "buy", {"down_payment_pct": str(down)})
    return out, place, cost


# ---- item 2 (l37): an escrow deposit is a one-time amount, never the insurance; HOI is the insurance
@pytest.mark.parametrize("line", [
    "HOI $700 per year. Escrow deposit for taxes and insurance $1,900 due at closing.",
    "Escrow deposit for taxes and insurance $1,900 due at closing. HOI $700 per year.",
    "Insurance (HOI): $700/yr. At closing, buyer funds an escrow deposit for taxes and insurance of $1,900.",
    "HOI $700 per year\nEscrow deposit for taxes and insurance: $1,900 due at closing",
    "Escrow deposit for taxes and insurance, $1,900, due at closing | HOI $700 per year",
    "HOI $700 per year; initial escrow deposit $1,900 (taxes and insurance) due at closing",
    "Homeowners insurance $700 a year. Buyer pays escrow deposit for taxes and insurance, $1,900, at closing.",
])
def test_escrow_deposit_is_one_time_and_hoi_is_the_insurance(line):
    out, place, cash = full(BASE + "HOA $255/mo. " + line)
    assert out["insurance"] == 700
    assert 1900 in [p["amount"] for p in cash["parts"] if "escrow" in p["label"]]
    assert "HOI $700" not in notes(out) or "not counted anywhere" not in notes(out)
    assert "$1,900 a year" not in notes(out)


def test_l37_whole_listing():
    t = fixture("r33-buyer-l37.txt")
    out, place, cost = cost_of(t)
    assert out["insurance"] == 700 and out["hoa"] == 255 and out["property_tax"] == 3800
    cash = cost["cash_to_close"]
    assert 1900 in [p["amount"] for p in cash["parts"] if "escrow deposit" in p["label"]]
    assert cost["pmi"] == 0 and "set to $0" in notes(out)
    assert "HOI" not in notes(out) and cost["all_in"] is True
    assert [l["amount"] for l in cost["lines"] if l["key"] == "insurance"] == [pytest.approx(700 / 12, abs=0.01)]


@pytest.mark.parametrize("line", [
    "Homeowners insurance $58 a month. Escrow account for taxes and insurance is required.",
    "Insurance included in your loan escrow $70 per month.",
])
def test_insurance_negatives_keep_the_monthly_figure(line):
    out = read(BASE + "HOA $200/mo. " + line)
    assert out["insurance"] in (696, 840)


def test_escrow_deposit_alone_leaves_insurance_empty():
    out = read(BASE + "HOA $200/mo. Escrow deposit for taxes and insurance $1,900 due at closing.")
    assert out.get("insurance") in (None, "") and out.get("deposit") in (None, "")


# ---- item 2: PMI $0 with a VA loan
@pytest.mark.parametrize("line", [
    "Mortgage insurance: $0 with VA loan.",
    "Great price. PMI: $0 (VA loan). Seller motivated.",
    "Mortgage insurance $0 for VA buyers",
    "$0 mortgage insurance with a VA loan",
    "Mortgage insurance: $0 with VA loan\nClose in 30 days",
    "PMI $0/mo with a VA loan | HOA $200/mo",
])
def test_pmi_zero_with_a_note(line):
    out, place, cost = cost_of(BASE + HOA_TAX + line)
    assert cost["pmi"] == 0
    assert "set to $0" in notes(out) and "only true for the loan the listing names" in notes(out)


@pytest.mark.parametrize("line", [
    "Mortgage insurance premium is $0.55% of loan annually.",
    "PMI $0 if you put 20% down.",
    "PMI about $120/mo",
])
def test_pmi_not_zero_negatives(line):
    out, place, cost = cost_of(BASE + HOA_TAX + line)
    assert cost["pmi"] != 0 and "set to $0" not in notes(out)
