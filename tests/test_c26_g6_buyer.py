"""Cycle 26 G6: buyer money reader. An assessment due at closing without the word "special", payer words (purchaser, new owner, current owner),
and seller contributions in "Seller closing contribution $5,000" / "Seller pays $6,000" wordings."""
from __future__ import annotations

import pytest

from prophelper.money import buy_cost, cash_to_close
from prophelper.parsers import parse_listing

HEAD = "Condo for sale, $339,000. 2 bed 2 bath. Closing costs for buyer about $9,000."


def buy(text: str, head: str = HEAD) -> dict:
    sep = "\n" if "\n" in text else " "
    return parse_listing(head + sep + text, "", buying=True)


def notes(r: dict) -> str:
    return str(r.get("found_in_listing") or "")


def cash(r: dict) -> dict:
    return cash_to_close({"price": 339000, **{k: r[k] for k in ("special_assessment", "special_assessment_payer", "closing_costs", "seller_credit") if k in r}})


@pytest.mark.parametrize("text", [
    "Assessment due from buyer at closing: $2,200. HOA $300/month.",
    "Assessment of $2,200 payable by purchaser at closing. HOA $300/month.",
    "Condo assessment $2,200 to be paid by the new owner at closing. HOA $300/month.",
    "Assessment $2,200, due at closing by buyer. HOA $300/month.",
    "Buyer to pay assessment of $2,200 at closing. HOA $300/month.",
    "Assessment $2,200\nDue from buyer at close\nHOA $300/month",
    "- Assessment: $2,200\n- Payable by purchaser at closing\n- HOA $300/month",
    "Special assessment $2,200 payable by purchaser at closing. HOA $300/month.",
])
def test_buyer_assessment_without_special(text):
    r = buy(text)
    assert r["special_assessment"] == 2200 and r["special_assessment_payer"] == "buyer"
    c = cash(r)
    assert any(p["label"].startswith("Special assessment") and p["amount"] == 2200 for p in c["parts"])
    assert not c["left_out"]


@pytest.mark.parametrize("text", [
    "Assessment $2,200 paid by seller at closing. HOA $300/month.",
    "Assessment of $2,200 to be paid by the current owner. HOA $300/month.",
    "Seller to pay assessment of $2,200 at closing. HOA $300/month.",
    "Special assessment $2,200, seller to pay. HOA $300/month.",
    "- Assessment $2,200\n- Paid by seller\n- HOA $300/month",
])
def test_seller_assessment_not_counted(text):
    r = buy(text)
    assert r["special_assessment"] == 2200 and r["special_assessment_payer"] == "seller"
    assert not any(p["label"].startswith("Special assessment") for p in cash(r)["parts"])


@pytest.mark.parametrize("text", [
    "Assessment $2,200 due at closing. HOA $300/month.",
    "Assessment of $2,200 due at closing, payer not stated. HOA $300/month.",
    "Special assessment $2,200 payable at closing. HOA $300/month.",
    "Assessment $2,200 paid by seller or buyer, to be negotiated. HOA $300/month.",
])
def test_unclear_payer_stays_unknown_with_note(text):
    r = buy(text)
    assert r.get("special_assessment") == 2200 and not r.get("special_assessment_payer")
    c = cash(r)
    assert not any(p["label"].startswith("Special assessment") for p in c["parts"])
    assert any("who pays it isn't known" in x for x in c["left_out"])
    assert "who pays" in notes(r)


def test_monthly_or_yearly_assessment_is_not_one_time():
    for text in ("Assessment $150/month due from buyer. HOA $300/month.", "Annual assessment $1,200 payable by buyer. HOA $300/month."):
        assert not buy(text).get("special_assessment")


def test_l7_listing_cash_to_close():
    r = parse_listing("Franklinton Brick Condo | $265,000\n1 Rich St #5, Columbus, OH 43222\n2 bed 2 bath 980 sqft. Assessment due from buyer at closing: $2,200. "
                      "Association fee $210 monthly. Property tax $2,900 per year. Buyer's closing costs: roughly $6,500. Seller concession: 2% of price.", "", buying=True)
    c = cash_to_close(r)
    assert r["special_assessment"] == 2200 and r["special_assessment_payer"] == "buyer" and r["seller_credit"] == 5300
    assert c["total"] == 53000 + 6500 + 2200 - 5300


@pytest.mark.parametrize("text", [
    "Seller closing contribution $5,000.",
    "Seller closing contribution: $5,000",
    "Seller closing credit of $5,000.",
    "Closing contribution from seller: $5,000.",
    "Seller pays $5,000.",
    "Seller pays $5,000 toward closing costs.",
    "- Seller pays $5,000\n- Taxes $4,000 per year",
])
def test_seller_contribution_is_a_closing_credit(text):
    r = buy(text)
    assert r["seller_credit"] == 5000
    c = cash(r)
    assert any(p["label"].startswith("Seller credit") and p["amount"] == -5000 for p in c["parts"])
    cost = buy_cost({"price": 339000, "hoa": 300, "property_tax": 4000, "insurance": 900, "seller_credit": 5000, "closing_costs": 9000})
    assert not any("5,000" in m for m in cost["missing"] + cost["uncounted"])
    assert not any("5,000" in m for m in r.get("not_counted", []) or [])


def test_seller_credit_never_above_closing_costs():
    r = buy("Seller pays $12,000.")
    assert r["seller_credit"] == 12000
    c = cash(r)
    assert any(p["label"].startswith("Seller credit") and p["amount"] == -9000 for p in c["parts"])
    assert any("seller credit isn't counted" in x for x in c["left_out"])


@pytest.mark.parametrize("text", [
    "Seller pays $6,000 for the new roof.",
    "Seller pays $6,000 in transfer tax.",
    "Seller will pay up to $6,000 toward closing costs.",
])
def test_seller_pays_other_or_capped_is_not_a_credit(text):
    assert not buy(text).get("seller_credit")


def test_seller_pays_is_not_a_monthly_amount_in_headline():
    r = buy("HOA $420 a month. Property taxes $5,400/yr. Seller pays $6,000. Includes 1 deeded parking space.")
    assert r["seller_credit"] == 6000
    cost = buy_cost({"price": 339000, "hoa": 420, "property_tax": 5400, "insurance": 900, "seller_credit": 6000, "closing_costs": 9000, "listing_text": r.get("listing_text", "")})
    assert not any("6,000" in m for m in cost["missing"] + cost["uncounted"])
