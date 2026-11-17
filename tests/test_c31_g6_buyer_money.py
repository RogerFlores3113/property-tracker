"""Cycle 31 G6: working capital is a closing item (not a special assessment), a seller credit plus "pay the buyer's title fees" names the
title fees, "2/2" before a full stop is beds and baths, "$X per installment, two installments a year" is converted, and a bare
"Fee: $185 monthly" on a condo stays unknown with a plain note."""
import os

import pytest

from prophelper import money
from prophelper.parsers import parse_listing

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "panel")
BASE = "Condo $300,000\n2 bed 2 bath, 1,000 sqft. HOA $200/month. "
GUESS = 9000  # 3 percent of $300,000
DOWN = 60000


def fixture(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


def read(text_):
    out = parse_listing(text_, buying=True)
    place = {**out, "listing_text": text_}
    return out, place, money.cash_to_close(place)


def amounts(cash):
    return {p["label"]: p["amount"] for p in cash["parts"]}


def notes(out):
    return out.get("found_in_listing", "")


# ---- 1. HOA working capital contribution is a closing item, not a special assessment
@pytest.mark.parametrize("line,label_word", [
    ("Buyer pays HOA working capital contribution of $1,200 at closing.", "working capital contribution"),
    ("Buyer pays a $1,200 HOA working capital contribution at closing.", "working capital contribution"),
    ("Working capital contribution: $1,200, due at closing from buyer.", "working capital contribution"),
    ("HOA charges a one-time $1,200 capital contribution at closing.", "capital contribution"),
    ("The association collects a $1,200 working capital fee at closing, paid by the buyer.", "working capital"),
])
def test_working_capital_is_a_closing_item_not_a_special_assessment(line, label_word):
    out, place, cash = read(BASE + line)
    assert out.get("special_assessment") in (None, "", 0) and not out.get("special_assessment_payer")
    a = amounts(cash)
    items = {k: v for k, v in a.items() if k.startswith("One-time fee at closing")}
    assert list(items.values()) == [1200] and label_word in list(items)[0]
    assert not any(k.startswith("Special assessment") for k in a)
    assert cash["total"] == DOWN + GUESS + 1200
    assert "special assessment" not in notes(out).lower()
    assert "$1,200" in notes(out) and "counted in the cash to close" in notes(out)
    assert cash["left_out"] == []


def test_reviewer_listing_l9_working_capital():
    out, place, cash = read(fixture("r30-buyer-l9.txt"))
    assert out.get("special_assessment") in (None, "", 0)
    a = amounts(cash)
    assert a["One-time fee at closing (working capital contribution)"] == 1200
    assert a["One-time fee at closing (prepaid taxes)"] == 900
    assert a["Closing costs"] == 7000 and a["Seller credit toward closing (comes off)"] == -4335
    assert cash["total"] == 57800 + 7000 + 1200 + 900 - 4335
    assert "special assessment" not in notes(out).lower()
    assert sum(1 for p in cash["parts"] if p["amount"] == 1200) == 1


def test_a_real_special_assessment_stays_a_special_assessment():
    out, place, cash = read(BASE + "Special assessment $3,000, buyer pays.")
    assert out["special_assessment"] == 3000 and out["special_assessment_payer"] == "buyer"
    assert amounts(cash)["Special assessment (you pay it)"] == 3000 and cash["total"] == DOWN + GUESS + 3000


def test_assessment_plus_working_capital_counts_both_under_their_own_names():
    out, place, cash = read(BASE + "Special assessment $3,000, buyer pays. Buyer pays a $1,200 working capital contribution at closing.")
    assert out["special_assessment"] == 3000
    a = amounts(cash)
    assert a["Special assessment (you pay it)"] == 3000 and a["One-time fee at closing (working capital contribution)"] == 1200
    assert cash["total"] == DOWN + GUESS + 4200
    assert "$1,200" in notes(out) and "counted in the cash to close" in notes(out)


def test_working_capital_the_seller_pays_is_not_counted():
    out, place, cash = read(BASE + "Seller pays the $1,200 working capital contribution.")
    assert cash["total"] == DOWN + GUESS and out.get("special_assessment") in (None, "", 0)


# ---- 2. "Seller will credit $2,000 plus pay the buyer's title fees"
@pytest.mark.parametrize("line", [
    "Seller will credit $2,000 plus pay the buyer's title fees.",
    "Seller credit $2,000 and seller covers the buyer's title and recording fees.",
    "Seller will give a $2,000 credit, also paying the buyer's title fees.",
    "Seller will credit $2,000 toward closing. Seller also pays the buyer's title fees.",
])
def test_seller_credit_plus_title_fees_is_noted(line):
    out, place, cash = read(BASE + line)
    assert out["seller_credit"] == 2000
    n = notes(out).lower()
    assert "title" in n and "fees" in n and "no amount" in n and "$2,000" in notes(out)
    assert cash["total"] == DOWN + GUESS - 2000  # only the stated $2,000 comes off


def test_seller_credit_plus_two_named_fees_names_both():
    out, place, cash = read(BASE + "Seller will credit $2,000. Seller pays the buyer's title fees and recording fees.")
    assert "title and recording fees" in notes(out)


def test_seller_credit_alone_has_no_title_fee_note():
    out, place, cash = read(BASE + "Seller will credit $2,000 toward closing costs.")
    assert out["seller_credit"] == 2000 and "title fees" not in notes(out).lower()


def test_seller_pays_a_stated_title_fee_amount_gets_no_missing_amount_note():
    out, place, cash = read(BASE + "Seller will credit $2,000. Seller pays $800 title fees.")
    assert "no amount" not in notes(out).lower()


def test_reviewer_listing_l12_title_fees():
    out, place, cash = read(fixture("r30-buyer-l12.txt"))
    assert out["seller_credit"] == 2000
    assert "title fees" in notes(out).lower() and "no amount" in notes(out).lower()
    assert out["property_tax"] == 7200 and out["hoa"] == 240


# ---- 3. "Fee: $185 monthly" on a condo with no HOA stays unknown, with a plain note
@pytest.mark.parametrize("line", ["Fee: $185 monthly.", "Fee $185 monthly.", "Fee: $185/month.", "- Fee: $185 per month"])
def test_bare_monthly_fee_on_a_condo_is_not_read_as_hoa(line):
    out, place, cash = read("Condo $275,000\n3 bed 2.5 bath. " + line + " Tax $3,000 a year.")
    assert out.get("hoa") in (None, "")
    n = notes(out)
    assert "$185" in n and "HOA" in n and "Ask" in n and "not counted" in n


def test_monthly_fee_with_a_name_is_still_the_hoa():
    out, place, cash = read("Condo $275,000\n3 bed 2.5 bath. Monthly fee: $185. Tax $3,000 a year.")
    assert out["hoa"] == 185  # current behavior kept


def test_reviewer_listing_l10_fee_and_tax():
    out, place, cash = read(fixture("r30-buyer-l10.txt"))
    assert out.get("hoa") in (None, "")
    assert out["property_tax"] == 7800 and out["special_assessment"] == 3000
    assert "$185" in notes(out) and "HOA" in notes(out)


# ---- 4. "2/2" is beds and baths
@pytest.mark.parametrize("text,beds,baths", [
    ("Condo $240,000\n2/2. HOA $280 a month.", 2, 2),
    ("Condo $240,000\n2/2, 1,150 sf. HOA $280 a month.", 2, 2),
    ("Condo $240,000\n3/2.5. HOA $280 a month.", 3, 2.5),
    ("Cozy 2/2 condo near OSU - $240,000\nHOA $280 a month.", 2, 2),
    ("Condo $240,000\n1/1 | HOA $280 a month", 1, 1),
    ("Condo $240,000\nSunny 2/1. Taxes $3,000 a year.", 2, 1),
])
def test_two_slash_two_is_beds_and_baths(text, beds, baths):
    out = parse_listing(text, buying=True)
    assert out["beds"] == beds and out["baths"] == baths


@pytest.mark.parametrize("text", [
    "Condo $240,000\n2 bed 1 bath. Closing on 2/2.",
    "Condo $240,000\n2 bed 1 bath. Inspection due by 3/2. Available 3/2.",
    "Condo $240,000\nHOA $280 a month. Sellers accept 1/2. Walk to 1/2 mile.",
    "Condo $240,000\nTaxes $3,000 a year. Lot 2/2.5 acre.",
])
def test_dates_and_fractions_are_not_beds_and_baths(text):
    out = parse_listing(text, buying=True)
    assert out.get("beds") in (None, 2) and out.get("baths") in (None, 1)
    if "bed" not in text:
        assert out.get("beds") is None and out.get("baths") is None


def test_reviewer_listing_l8_beds_baths():
    out = parse_listing(fixture("r30-buyer-l8.txt"), buying=True)
    assert out["beds"] == 2 and out["baths"] == 2 and out["hoa"] == 280 and out["property_tax"] == 3000


# ---- 5. per installment with a count
@pytest.mark.parametrize("line,tax", [
    ("Property tax $4,200 per installment, two installments a year.", 8400),
    ("Property tax $4,200 per installment (2 installments a year).", 8400),
    ("Property taxes are $2,100 per installment, paid in four installments each year.", 8400),
    ("Property tax: $4,200 per installment. Billed in two installments per year.", 8400),
    ("Property tax $4,200 per installment, due twice a year.", 8400),
])
def test_tax_per_installment_with_a_count_is_converted(line, tax):
    out, place, cash = read("Condo $300,000\n2 bed 2 bath. " + line)
    assert out["property_tax"] == tax
    assert "installment" in notes(out) and f"${tax:,}" in notes(out) and "left empty" not in notes(out)


def test_tax_per_installment_without_a_count_stays_empty():
    out, place, cash = read("Condo $300,000\n2 bed 2 bath. Property tax $4,200 per installment.")
    assert out.get("property_tax") in (None, "") and "left empty" in notes(out)


def test_tax_per_installment_with_two_different_counts_stays_empty():
    out, place, cash = read("Condo $300,000\n2 bed 2 bath. Property tax $4,200 per installment, two installments a year. Some say four installments a year.")
    assert out.get("property_tax") in (None, "")


def test_reviewer_listing_l6_installments():
    out = parse_listing(fixture("r30-buyer-l6.txt"), buying=True)
    assert out["property_tax"] == 8400 and out["hoa"] == 310


@pytest.mark.parametrize("line,hoa", [
    ("HOA $390 per installment, four installments a year.", 130),
    ("HOA dues $780 per installment, two installments a year.", 130),
])
def test_hoa_per_installment_with_a_count_is_converted(line, hoa):
    out, place, cash = read("Condo $300,000\n2 bed 2 bath. " + line)
    assert out["hoa"] == hoa
    assert "installments a year" in notes(out) and "$130 a month" in notes(out)


def test_hoa_per_installment_without_a_count_stays_empty():
    out, place, cash = read("Condo $300,000\n2 bed 2 bath. HOA $390 per installment.")
    assert out.get("hoa") in (None, "")
