"""Cycle 32 G6: "(2 installments)" is a count, "PMI approximately $95/mo" is read like "approx", named closing parts beside a seller aside are
still the buyer's parts, "$9,000 buyer pays over 36 months" is paid monthly (not at closing), and a percent credit is never worked out from a rental's rent."""
import os

import pytest

from prophelper import money
from prophelper.parsers import listing_pmi_monthly, parse_listing

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "panel")
BASE = "Condo $300,000\n2 bed 2 bath, 1,000 sqft. "


def fixture(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


def read(text_):
    return parse_listing(text_, buying=True)


def notes(out):
    return out.get("found_in_listing", "")


# ---- 1. tax per installment with the count in brackets or beside it
@pytest.mark.parametrize("line,tax", [
    ("Property tax $1,550 per installment (2 installments).", 3100),
    ("Property tax $1,550 per installment (2 installments)", 3100),
    ("Property tax $1,550 per installment, 2 installments.", 3100),
    ("Property tax: $1,550 per installment; 2 installments", 3100),
    ("Taxes $1,550 each installment (two installments)", 3100),
    ("Property taxes are $1,550 per installment [2 installments]. HOA $100/mo.", 3100),
    ("Real estate tax $780 per installment (4 installments). Close in 60 days.", 3120),
    ("Property tax $1,550 per installment, paid in 2 installments.", 3100),
    ("Property tax $1,550 per installment (2 installments a year).", 3100),
    ("Property tax $1,100 per installment (3 installments)\nInspection 10 days.", 3300),
])
def test_tax_per_installment_with_count(line, tax):
    out = read(BASE + line)
    assert out["property_tax"] == tax
    assert "installments a year" in notes(out) and "left empty" not in notes(out)


@pytest.mark.parametrize("line", [
    "Property tax $1,550 per installment.",
    "Property tax $1,550 per installment (2 installments, 3 installments)",
    "Property tax $1,550 per installment. Roof has 2 installments of paint left.",
])
def test_tax_per_installment_without_a_clear_count_stays_empty(line):
    out = read(BASE + line)
    assert out.get("property_tax") in (None, "")
    assert "$1,550" in notes(out)


def test_tax_per_year_beside_installments_is_not_multiplied():
    out = read(BASE + "Property tax $4,200 per year (2 installments).")
    assert out["property_tax"] == 4200


def test_l15_whole_listing_tax_and_pmi():
    out = read(fixture("r31-buyer-l15.txt"))
    assert out["property_tax"] == 3100 and out["price"] == 262500 and out["hoa"] == 165 and out["insurance"] == 700 and out["seller_credit"] == 3500
    assert "left empty" not in notes(out) and "$3,100 a year" in notes(out)


# ---- 2. PMI "approximately"
@pytest.mark.parametrize("line", [
    "PMI approximately $95/mo.",
    "PMI approximately $95/mo",
    "PMI: approximately $95 per month.",
    "PMI is approximately $95 a month;",
    "Mortgage insurance approximately $95/month.",
    "Private mortgage insurance approximately $95 monthly.",
    "pmi approx. $95/mo",
    "PMI approx $95/mo",
    "PMI roughly $95/mo",
    "PMI, approximately $95/mo",
])
def test_pmi_approximately(line):
    got = listing_pmi_monthly(BASE + line)
    assert got is not None and got[0] == 95.0
    out = read(BASE + line)
    assert "mortgage insurance (PMI)" in notes(out) and "not counted anywhere" not in notes(out) and "Check what it is for" not in notes(out)


def test_pmi_yearly_approximately_is_divided():
    assert listing_pmi_monthly(BASE + "PMI approximately $1,140 a year.")[0] == 95.0


@pytest.mark.parametrize("line", [
    "PMI not required with 20% down, approximately $95/mo otherwise?",
    "PMI approximately 0.5% of the loan.",
    "PMI approximately $95.",
])
def test_pmi_negatives(line):
    assert listing_pmi_monthly(BASE + line) is None


# ---- 3. named closing parts next to a seller aside
@pytest.mark.parametrize("line", [
    "Buyer pays lender fees $2,000, appraisal $550, and title fees $1,100 (seller also pays title fees on their side).",
    "Buyer pays lender fees $2,000, appraisal $550, and title fees $1,100 (seller also pays title fees on their side)",
    "Buyer pays lender fees $2,000; appraisal $550; title fees $1,100 (seller also pays title fees on their side).",
    "Buyer pays lender fees $2,000, appraisal $550, title fees $1,100. (Seller also pays title fees on their side.)",
    "Buyer pays title fees $1,100 (the seller pays their own title fees), lender fees $2,000, appraisal $550.",
    "Buyer pays lender fees $2,000, appraisal $550, title fees $1,100 (seller pays theirs separately).",
])
def test_closing_parts_with_seller_aside_are_buyer_parts(line):
    out = read(BASE + "Seller credit: $3,500. " + line)
    n = notes(out)
    assert "names some closing costs" in n and "$3,650 in all" in n and "only part of the closing costs" in n
    assert out.get("closing_costs") in (None, "")
    place = {**out, "listing_text": BASE + "Seller credit: $3,500. " + line}
    labels = " ".join(p["label"] for p in money.cash_to_close(place)["parts"])
    assert "$2,000 for lender fees" in labels and "$1,100 for title fees" in labels


@pytest.mark.parametrize("line", [
    "Seller pays lender fees $2,000 and appraisal $550.",
    "Seller will pay the lender fees $2,000, appraisal $550 (buyer pays nothing).",
])
def test_seller_paid_parts_are_not_the_buyers(line):
    out = read(BASE + line)
    assert "names some closing costs" not in notes(out)


@pytest.mark.parametrize("line", [
    "Buyer pays title fees $1,100 (seller also pays title fees on their side).",
    "Buyer pays title fees $1,100 (seller also pays title and recording fees on their own side).",
])
def test_seller_side_fees_get_a_note(line):
    out = read(BASE + "Seller credit: $3,500. " + line)
    assert "seller also pays title" in notes(out) and "on their side" in notes(out) and "nothing is taken off" in notes(out)


def test_no_seller_aside_no_seller_side_note():
    out = read(BASE + "Seller credit: $3,500. Buyer pays title fees $1,100, lender fees $2,000.")
    assert "on their side" not in notes(out)


def test_l15_whole_listing_closing_note():
    out = read(fixture("r31-buyer-l15.txt"))
    assert "$3,650 in all" in notes(out) and "on their side" in notes(out)
    assert out["seller_credit"] == 3500 and out.get("closing_costs") in (None, "")


# ---- 4. a special assessment the buyer pays over many months
@pytest.mark.parametrize("line,monthly,months,total", [
    ("Special assessment: $9,000 for elevator, buyer pays over 36 months.", 250, 36, "$9,000"),
    ("Special assessment $9,000. Buyer pays it over 3 years.", 250, 36, "$9,000"),
    ("Special assessment: $9,000 (elevator). The buyer pays over 36 months.", 250, 36, "$9,000"),
    ("Buyer pays the $9,000 special assessment in 36 monthly payments.", 250, 36, "$9,000"),
    ("Special assessment of $7,200, payable by buyer over 24 months", 300, 24, "$7,200"),
    ("The special assessment ($6,000) is paid by the buyer over 12 months;", 500, 12, "$6,000"),
    ("Buyer to pay special assessment of $9,000 spread over 36 months.", 250, 36, "$9,000"),
])
def test_assessment_paid_over_months_is_monthly_not_closing(line, monthly, months, total):
    out = read(BASE + "HOA $200/month. " + line)
    assert out.get("special_assessment") in (None, "", 0)
    assert out["other_monthly_fees"] == monthly and out["hoa"] == 200
    n = notes(out)
    assert total in n and f"{months} months" in n and "not as cash at closing" in n
    cash = money.cash_to_close({**out, "listing_text": BASE + "HOA $200/month. " + line})
    assert all("assessment" not in p["label"].lower() for p in cash["parts"])


def test_l16_whole_listing():
    out = read(fixture("r31-buyer-l16.txt"))
    assert out["hoa"] == 210 and out["other_monthly_fees"] == 250 and out["property_tax"] == 2400 and out["seller_credit"] == 5970
    assert out.get("special_assessment") in (None, "", 0)
    cash = money.cash_to_close({**out, "listing_text": fixture("r31-buyer-l16.txt")})
    labels = " ".join(p["label"] for p in cash["parts"])
    assert "ssessment" not in labels and cash["total"] == 40050.0  # cycle 35: the $250 transfer fee the buyer pays is added as a one-time item


@pytest.mark.parametrize("line,who", [
    ("Special assessment of $9,000, seller pays, over 36 months.", "seller"),
    ("Special assessment of $9,000 payable over 36 months.", ""),
])
def test_assessment_over_months_with_other_or_unknown_payer_is_not_counted(line, who):
    out = read(BASE + "HOA $200/month. " + line)
    assert out.get("special_assessment") in (None, "", 0) and out.get("other_monthly_fees") in (None, "", 0)
    assert "$9,000" in notes(out) and "36 months" in notes(out)
    assert ("paid by the seller" in notes(out)) == (who == "seller")


@pytest.mark.parametrize("line,amount", [
    ("Special assessment of $9,000, buyer pays at closing.", 9000),
    ("Buyer pays special assessment of $4,000 at closing, 36 months old roof.", 4000),
])
def test_one_time_assessment_still_at_closing(line, amount):
    out = read(BASE + "HOA $200/month. " + line)
    assert out["special_assessment"] == amount and out["special_assessment_payer"] == "buyer"
    assert out.get("other_monthly_fees") in (None, "", 0)


def test_monthly_assessment_with_a_length_is_unchanged():
    out = read(BASE + "HOA $200/month. Special assessment $150/month for 24 months, paid by buyer.")
    assert out["other_monthly_fees"] == 150 and out.get("special_assessment") in (None, "", 0)


# ---- 5. a percent seller credit is never worked out from a rental's rent
def test_r30_l6_read_as_a_rental_has_no_worked_out_credit():
    out = parse_listing(fixture("r30-buyer-l6.txt"), "")
    assert out.get("seller_credit") in (None, "", 0)
    assert "$36" not in notes(out) and "3% x" not in notes(out)
    assert "3%" in notes(out)


@pytest.mark.parametrize("line", [
    "Seller will pay 3% in closing help.",
    "Seller credit 3% toward closing.",
    "Landlord rent $1,200. Seller will give a 3% credit toward closing.",
])
def test_percent_credit_on_a_rental(line):
    out = parse_listing("Apartment for rent $1,200/month. 2 bed 1 bath. " + line, "")
    assert out.get("seller_credit") in (None, "", 0)
    assert "$36" not in notes(out)


def test_percent_credit_on_a_sale_is_still_worked_out():
    out = read(BASE + "Seller will pay 3% in closing help.")
    assert out["seller_credit"] == 9000
    out2 = read(fixture("r31-buyer-l6.txt"))
    assert out2["seller_credit"] == 9897 and out2["price"] == 329900
    out3 = parse_listing("3 bed house for sale $450,000. Seller will give 2% of the price toward closing.", "")
    assert out3["seller_credit"] == 9000
