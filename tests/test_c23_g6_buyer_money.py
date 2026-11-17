"""Cycle 23 G6: buyer money reader. Yearly and past-tense figures, regular plus special assessments, the seller credit capped at the
closing costs, credit wordings and offers, and itemized closing costs. Each item has the reviewer's wording plus other layouts."""
from __future__ import annotations

import pytest

from prophelper.money import cash_to_close
from prophelper.parsers import parse_listing

HEAD = "Condo $289,000. 2 bed 2 bath."


def buy(text: str, head: str = HEAD) -> dict:
    sep = "\n" if "\n" in text else " "
    return parse_listing(head + sep + text, "", buying=True)


def notes(r: dict) -> str:
    return str(r.get("found_in_listing") or "")


# ---- item 1: yearly and past-tense figures
@pytest.mark.parametrize("text,hoa", [
    ("Condo dues are $2,700 per year.", 225),
    ("HOA: $2,700/yr", 225),
    ("Annual association fee $2,700.", 225),
    ("The condo fee is $2,700 annually.", 225),
    ("HOA fees are $225 a month.", 225),
])
def test_hoa_yearly_forms(text, hoa):
    assert buy(text)["hoa"] == hoa


@pytest.mark.parametrize("text", [
    "Property taxes (tax year 2025) were $3,480.",
    "Property taxes were $3,480 last year.",
    "Taxes of $3,480 (2025).",
    "$3,480 in property taxes (2025).",
])
def test_tax_past_tense(text):
    assert buy(text)["property_tax"] == 3480


@pytest.mark.parametrize("text", [
    "Homeowner's insurance in escrow, $72/mo.",
    "Insurance in escrow: $72 per month.",
    "Homeowner's insurance is held in escrow, $72/mo.",
])
def test_insurance_in_escrow(text):
    assert buy(text)["insurance"] == 864


def test_l21_whole_listing():
    r = buy("Condo dues are $2,700 per year. Property taxes were $3,480 last year. Homeowner's insurance $72/mo. Closing costs $6,500.")
    assert (r["hoa"], r["property_tax"], r["insurance"], r["closing_costs"]) == (225, 3480, 864, 6500)
    assert "not counted anywhere" not in notes(r)


# ---- item 2: regular plus special assessment
def test_l16_regular_plus_special():
    r = buy("Monthly assessment $415. Special assessment: $250 a month through 2028 for the parking deck. HO-6 $48/mo.")
    assert r["hoa"] == 415 and r["other_monthly_fees"] == 250 and "special_assessment" not in r  # cycle 30: kept apart from the HOA
    n = notes(r)
    assert "$415" in n and "$250" in n and "2028" in n and "$665" not in n


def test_regular_plus_special_one_line_and_bullets():
    r = buy("Assessment: $300/month plus special assessment of $100 per month until 2027.")
    assert r["hoa"] == 300 and r["other_monthly_fees"] == 100
    r = buy("- Monthly assessment: $300\n- Special assessment: $100/mo for 24 months")
    assert r["hoa"] == 300 and r["other_monthly_fees"] == 100 and "24 months" in notes(r)


def test_l22_hoa_dues_and_assessment_conflict_stays_unknown():
    r = buy("HOA dues: $2,400/yr. Monthly assessment $415 plus special assessment $250 per month until 2028.")
    assert "hoa" not in r
    n = notes(r)
    assert "$200" in n and "$415" in n and "$250" in n and "2028" in n


def test_plain_assessment_is_regular_hoa_not_special():
    r = buy("1,050 sq ft. Assessment: $280/month. Tax $3,700 yearly.")
    assert r["hoa"] == 280
    assert "special" not in notes(r).lower()
    r = buy("Monthly assessment $310. Tax $3,700 yearly.")
    assert r["hoa"] == 310 and "special" not in notes(r).lower()


# ---- item 3: seller credit capped at closing costs
def place(price, closing, credit, down_pct=20):
    return {"price": price, "closing_costs": closing, "seller_credit": credit}


def test_credit_larger_than_closing_is_capped():
    c = cash_to_close(place(312_500, 6900, 7812), {"down_payment_pct": 20, "closing_cost_pct": 3})
    assert c["total"] == 62_500 and "$912" in " ".join(c["left_out"])
    assert [p["amount"] for p in c["parts"]] == [62_500, 6900, -6900]


def test_credit_cap_second_and_third_cases():
    c = cash_to_close(place(335_000, 8000, 10_050), {"down_payment_pct": 20, "closing_cost_pct": 3})
    assert c["total"] == 67_000 and "$2,050" in " ".join(c["left_out"])
    c = cash_to_close(place(300_000, 6000, 4000), {"down_payment_pct": 20, "closing_cost_pct": 3})
    assert c["total"] == 62_000 and c["left_out"] == []


# ---- item 4: credit wordings
@pytest.mark.parametrize("text,credit", [
    ("Seller to provide a $4,000 closing credit.", 4000),
    ("$4,000 closing credit from the seller.", 4000),
    ("Sellers are offering $6k in concessions.", 6000),
    ("Seller will credit $6k toward closing.", 6000),
])
def test_credit_wordings(text, credit):
    r = buy(text)
    assert r["seller_credit"] == credit
    assert "free-rent" not in notes(r)


@pytest.mark.parametrize("text", [
    "Seller contribution of 3% available.",
    "Seller concessions up to 3%.",
    "Seller contribution of $9,000 available.",
])
def test_offers_not_counted(text):
    r = buy(text)
    assert "seller_credit" not in r
    assert "offer" in notes(r)


# ---- item 5: itemized closing costs
@pytest.mark.parametrize("text", [
    "Title and escrow about $2,100 plus lender fees about $3,200.",
    "Lender fees: $3,200\nTitle and escrow: $2,100",
    "Expect lender fees ~$3,200 and title and escrow roughly $2,100.",
])
def test_itemized_closing_costs(text):
    # cycle 30 (rule j): a few named parts are only part of the bill and never replace the larger 3 percent guess
    r = buy(text)
    assert "closing_costs" not in r
    assert "$5,300" in notes(r) and "only part of the closing costs" in notes(r) and "instead of a guess" not in notes(r)


def test_itemized_closing_costs_bigger_than_the_guess_are_saved():
    r = parse_listing("Condo $100,000\n2 bed. Title and escrow about $2,100 plus lender fees about $3,200.", buying=True)
    assert r["closing_costs"] == 5300 and "instead of a guess" in notes(r)


def test_itemized_not_used_when_total_given():
    r = buy("Closing costs $6,500. Title and escrow about $2,100 plus lender fees about $3,200.")
    assert r["closing_costs"] == 6500
