"""Cycle 25 G6: buyer money reader. Who pays a special assessment, buyer closing costs in more wordings, a maintenance fee as the HOA,
a "$2,000 or 1%, whichever is greater" seller credit, a percent the listing itself gives for closing costs, and year built wordings."""
from __future__ import annotations
import os

from pathlib import Path

import pytest

from prophelper.money import cash_to_close
from prophelper.parsers import parse_listing

HEAD = "Condo for sale, $339,000. 2 bed 2 bath."


def buy(text: str, head: str = HEAD) -> dict:
    sep = "\n" if "\n" in text else " "
    return parse_listing(head + sep + text, "", buying=True)


def notes(r: dict) -> str:
    return str(r.get("found_in_listing") or "")


# ---- item 1: who pays a special assessment
@pytest.mark.parametrize("text,amount", [
    ("Buyer to pay special assessment of $3,000 at closing. HOA $300/month.", 3000),
    ("Special assessment $1,800 due from buyer at close. HOA $300/month.", 1800),
    ("Special assessment of $2,500, payable by buyer at closing. HOA $300/month.", 2500),
    ("$2,000 special assessment to be paid by buyer at closing. HOA $300/month.", 2000),
    ("Special assessment ($4,500) due from the buyer at closing. HOA $300/month.", 4500),
    ("Special assessment $2,600\nDue from buyer at close\nHOA $300/month", 2600),
    ("- Special assessment $2,600\n- Buyer pays it at closing\n- HOA $300/month", 2600),
])
def test_buyer_paid_assessment(text, amount):
    r = buy(text)
    assert r["special_assessment"] == amount and r["special_assessment_payer"] == "buyer"
    cash = cash_to_close({"price": 339000, "special_assessment": amount, "special_assessment_payer": "buyer", "closing_costs": 9000})
    assert any(p["label"].startswith("Special assessment") and p["amount"] == amount for p in cash["parts"])


def test_payer_from_listing_text_when_not_saved():
    place = {"price": 339000, "special_assessment": 3000, "closing_costs": 9000,
             "listing_text": "Buyer to pay special assessment of $3,000 at closing for the boiler."}
    cash = cash_to_close(place)
    assert any(p["label"].startswith("Special assessment") and p["amount"] == 3000 for p in cash["parts"])
    assert not any("who pays it isn't known" in x for x in cash["left_out"])


@pytest.mark.parametrize("text", [
    "A one-time $2,000 special assessment was levied in 2025 and has been paid by the seller. HOA $300/month.",
    "Special assessment of $2,000 was paid by the seller in 2024. HOA $300/month.",
    "Roof special assessment ($2,000) already paid in full by seller. HOA $300/month.",
    "- Special assessment $2,000\n- Payable by seller\n- HOA $300/month",
])
def test_seller_paid_past_assessment_is_not_a_buyer_cost(text):
    r = buy(text)
    assert r["special_assessment"] == 2000 and r["special_assessment_payer"] == "seller"
    cash = cash_to_close({"price": 339000, "special_assessment": 2000, "special_assessment_payer": "seller", "closing_costs": 9000})
    assert not any(p["label"].startswith("Special assessment") for p in cash["parts"])
    assert not any("who pays" in x for x in cash["left_out"])
    assert "who pays it isn't known" not in notes(r)


def test_assessment_no_payer_stays_unknown():
    r = buy("Special assessment $2,600. Buyer pays closing costs. HOA $300/month.")
    assert r["special_assessment"] == 2600 and "special_assessment_payer" not in r
    cash = cash_to_close({"price": 339000, "special_assessment": 2600, "closing_costs": 9000})
    assert any("who pays it isn't known" in x for x in cash["left_out"])


def test_past_seller_note_is_plain():
    n = notes(buy("A one-time $2,000 special assessment was levied in 2025 and has been paid by the seller. HOA $300/month."))
    assert "already paid by the seller" in n and "not a cost to you" in n


# ---- item 2: buyer closing costs
@pytest.mark.parametrize("text,value", [
    ("Estimated settlement costs for buyer: $7,800. HOA $300/month.", 7800),
    ("Closing costs for the buyer: about $8,300 total. HOA $300/month.", 8300),
    ("Seller will credit up to 2.5% of the sale price. Closing costs for the buyer: about $8,300 total. HOA $300/month.", 8300),
    ("Buyer's closing costs: ~$8,300. HOA $300/month.", 8300),
    ("Settlement costs (buyer): $7,800. HOA $300/month.", 7800),
    ("Buyer's estimated settlement costs are around $7,800. HOA $300/month.", 7800),
    ("- Settlement costs for the buyer: $7,800\n- HOA $300/month", 7800),
    ("Buyer costs at closing: approx. $8,300. HOA $300/month.", 8300),
])
def test_buyer_closing_costs_read(text, value):
    assert buy(text)["closing_costs"] == value


@pytest.mark.parametrize("text", [
    "Seller pays settlement costs for buyer: $7,800. HOA $300/month.",
    "Seller will pay up to $8,000 toward closing costs for the buyer. HOA $300/month.",
])
def test_seller_paid_not_buyer_closing(text):
    assert "closing_costs" not in buy(text)


def test_up_to_in_the_sentence_before_does_not_hide_closing():
    r = buy("Seller will credit up to $5,000 toward the sale. Closing costs for the buyer: $8,300. HOA $300/month.")
    assert r["closing_costs"] == 8300


# ---- item 3: maintenance fee is the HOA when no other HOA figure
@pytest.mark.parametrize("text,hoa", [
    ("Maintenance fee: $325 a month, covers snow, grass, building insurance. Tax $4,000/yr.", 325),
    ("Condo maintenance fee $325/mo. Tax $4,000/yr.", 325),
    ("- Maintenance: $325 per month\n- Tax $4,000/yr", 325),
    ("Monthly maintenance fee is $325.", 325),
    ("Maintenance fees $3,900 per year.", 325),
])
def test_maintenance_fee_is_hoa(text, hoa):
    r = buy(text)
    assert r["hoa"] == hoa
    assert "maintenance fee" in notes(r) and "not counted anywhere" not in notes(r)


@pytest.mark.parametrize("text", [
    "Garage maintenance fee $40/mo (optional). Tax $4,000/yr.",
    "Lawn maintenance fee $50/month.",
    "Maintenance fee $325.",
    "One-time maintenance fee $500 at closing.",
])
def test_other_maintenance_not_hoa(text):
    assert "hoa" not in buy(text)


def test_maintenance_does_not_replace_a_stated_hoa():
    assert buy("HOA $200/month. Maintenance fee: $325 a month.")["hoa"] == 200


# ---- item 4: "$2,000 or 1%, whichever is greater"
@pytest.mark.parametrize("text,credit", [
    ("Seller closing contribution: $2,000 or 1%, whichever is greater. HOA $300/month.", 3390),
    ("Seller concessions: 1% or $2,000, whichever is higher. HOA $300/month.", 3390),
    ("- Seller credit: greater of $2,000 or 1% of price\n- HOA $300/month", 3390),
    ("Seller will credit $5,000 or 2% of the price, whichever is greater, toward closing. HOA $300/month.", 6780),
    ("Seller closing contribution: $5,000 or 1%, whichever is greater. HOA $300/month.", 5000),
    ("Seller credit of $9,000 or 2%, whichever is less. HOA $300/month.", 6780),
])
def test_either_or_credit(text, credit):
    r = buy(text)
    assert r["seller_credit"] == credit
    assert "whichever is" in notes(r) and f"${credit:,.0f}" in notes(r)


def test_either_or_credit_capped_at_closing_costs():
    cash = cash_to_close({"price": 339000, "closing_costs": 2500, "seller_credit": 3390})
    assert [p for p in cash["parts"] if p["label"].startswith("Seller credit")][0]["amount"] == -2500


def test_either_or_credit_without_price_stays_empty():
    r = parse_listing("Condo for sale. Seller closing contribution: $2,000 or 1%, whichever is greater. HOA $300/month.", "", buying=True)
    assert "seller_credit" not in r and "whichever is greater" in notes(r)


# ---- item 5: a percent the listing gives for closing costs
@pytest.mark.parametrize("text,value", [
    ("Estimated closing: 3% of price. HOA $300/month.", 10170),
    ("Closing: approx. 3% of the purchase price. HOA $300/month.", 10170),
    ("- Estimated closing costs: 3% of price\n- HOA $300/month", 10170),
    ("Estimated settlement costs about 3% of price. HOA $300/month.", 10170),
])
def test_closing_percent_from_listing(text, value):
    r = buy(text)
    assert r["closing_costs"] == value and "from the listing, not from a guess" in notes(r)
    assert "no dollar amount is saved" not in notes(r)


def test_closing_percent_not_loan_or_seller():
    assert "closing_costs" not in buy("Closing costs 3% of the loan amount. HOA $300/month.")
    assert "closing_costs" not in buy("Seller pays closing: 3% of price. HOA $300/month.")


def test_cash_uses_listing_percent_not_guess():
    place = {"price": 325000, "listing_text": "Estimated closing: 3.5% of price."}
    cash = cash_to_close(place)
    line = [p for p in cash["parts"] if p["label"].startswith("Closing costs")][0]
    assert line["amount"] == 11375 and "from the listing" in line["label"] and "guess" not in line["label"]
    assert cash["has_estimate"] is False
    guess = cash_to_close({"price": 325000})
    assert "a guess" in [p for p in guess["parts"] if p["label"].startswith("Closing costs")][0]["label"]


# ---- item 6: year built
@pytest.mark.parametrize("text,year", [
    ("New in 2025. W/D in unit.", 2025),
    ("Completed 2024. W/D in unit.", 2024),
    ("Opened 2022. Washer/dryer included.", 2022),
    ("Built in 2019. Pool.", 2019),
    ("Constructed 2021. Gas heat.", 2021),
    ("Studio $1,200 | Opened 2022 | W/D", 2022),
    ("- Completed 2024\n- Dishwasher", 2024),
    ("Great views, new in 2025, parking.", 2025),
    ("Year of construction: 2018", 2018),
])
def test_year_built_wordings(text, year):
    assert parse_listing("1 bed apartment, rent $1,300. 611 E Green St, Champaign, IL 61820. " + text, "")["year_built"] == year
    assert buy(text)["year_built"] == year


@pytest.mark.parametrize("text", [
    "Renovation completed 2024. Lease starts 2026.",
    "Pool opened 2022. Available August 2026.",
    "Kitchen completed 2024.",
    "Lease opened 2027 for fall.",
    "Sale completed 2025.",
    "Available 2026. Lease starts 2026.",
])
def test_year_built_not_lease_or_renovation(text):
    assert "year_built" not in parse_listing("1 bed apartment, rent $1,300. " + text, "")


# ---- the reviewer's listing files
P = Path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel") + "")


@pytest.mark.skipif(not (P / "r24-buyer-l10.txt").exists(), reason="reviewer files not here")
def test_reviewer_files():
    r = parse_listing((P / "r24-buyer-l10.txt").read_text(), "", buying=True)
    assert r["closing_costs"] == 7800 and r["special_assessment"] == 3000 and r["special_assessment_payer"] == "buyer"
    r = parse_listing((P / "r24-buyer-l6.txt").read_text(), "", buying=True)
    assert r["closing_costs"] == 8300
    r = parse_listing((P / "r24-buyer-l9.txt").read_text(), "", buying=True)
    assert r["closing_costs"] == 9750 and r["special_assessment_payer"] == "buyer"
    r = parse_listing((P / "r24-buyer-l11.txt").read_text(), "", buying=True)
    assert r["hoa"] == 325 and r["seller_credit"] == 2790 and r["closing_costs"] == 6100 and r["price"] == 279000
    r = parse_listing((P / "r24-buyer-l2.txt").read_text(), "", buying=True)
    assert r["special_assessment_payer"] == "seller" and r["seller_credit"] == 5000
    for n, y in ((3, 2025), (11, 2024), (19, 2022)):
        assert parse_listing((P / f"r24-uiuc-l{n}.txt").read_text(), "")["year_built"] == y


@pytest.mark.parametrize("text", [
    "Special assessment of $4,800 for roof, paid by seller at closing. HOA $300/month.",
    "Special assessment of $6,500 for roof replacement, to be paid by seller at closing. HOA $300/month.",
])
def test_seller_pays_at_closing_is_not_called_already_paid(text):
    r = buy(text)
    assert r["special_assessment_payer"] == "seller"
    assert "already paid" not in notes(r)


def test_either_or_credit_ignores_a_tiny_misread_price():
    r = parse_listing("Seller closing contribution: $2,000 or 1%, whichever is greater. Taxes $316/mo.\nrent $316", "")
    assert "seller_credit" not in r
