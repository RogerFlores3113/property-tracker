"""Cycle 30 G6: one-time buyer items go into cash to close, "$4,000 plus $1,200 additional", a few named closing parts never lower the guess,
and a monthly special assessment is kept apart from the HOA with its end named."""
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
    cash = money.cash_to_close(place)
    return out, place, cash


def amounts(cash):
    return {p["label"]: p["amount"] for p in cash["parts"]}


def notes(out):
    return out.get("found_in_listing", "")


# ---- one-time buyer items at closing
@pytest.mark.parametrize("line,amount,word", [
    ("HOA also charges a one-time $600 capital contribution at closing.", 600, "capital contribution"),
    ("Buyer pays a $600 capital contribution at closing.", 600, "capital contribution"),
    ("Capital contribution: $600, due at closing.", 600, "capital contribution"),
    ("Buyer pays a one-time $1,500 working capital contribution at closing.", 1500, "working capital contribution"),
    ("Working capital contribution of $1,500 due at closing from buyer.", 1500, "working capital contribution"),
    ("Buyer pays $1,500 working capital at closing.", 1500, "working capital"),
    ("Buyer pays a $350 condo document fee.", 350, "condo document fee"),
    ("Condo document fee $350 paid by buyer at closing.", 350, "condo document fee"),
    ("$350 HOA document fee due at closing.", 350, "hoa document fee"),
    ("Buyer pays prepaid taxes and insurance of $2,100 at closing.", 2100, "prepaid taxes and insurance"),
    ("At closing the buyer pays $2,100 for prepaid taxes and insurance.", 2100, "prepaid taxes and insurance"),
    ("Prepaid taxes and insurance: $2,100 (buyer, at closing).", 2100, "prepaid taxes and insurance"),
    ("Buyer pays a $500 move-in deposit to the association.", 500, "move-in deposit"),
    ("$500 move-in deposit to the association due at closing.", 500, "move-in deposit"),
    ("Association move-in deposit $500 payable at closing.", 500, "move-in deposit"),
])
def test_one_time_item_is_in_cash_to_close(line, amount, word):
    out, place, cash = read(BASE + line)
    items = [(l, a) for l, a in amounts(cash).items() if l.startswith("One-time fee at closing") or l.startswith("Special assessment")]
    assert len(items) == 1 and items[0][1] == amount  # a capital contribution on its own is read as the one-time assessment the buyer pays, counted once
    if not word.endswith("capital contribution") and word != "working capital":
        assert word in items[0][0].lower()
    assert cash["total"] == DOWN + GUESS + amount
    assert cash["left_out"] == []
    assert "not counted anywhere" not in notes(out)
    assert (f"${amount:,}" in notes(out) or out.get("special_assessment") == amount) and "counted in the cash to close" in notes(out)
    assert sum(1 for p in cash["parts"] if p["amount"] == amount) == 1


def test_items_with_no_payer_are_named_not_counted():
    out, place, cash = read(BASE + "There is a $350 condo document fee.")
    assert cash["total"] == DOWN + GUESS
    assert any("$350" in x and "who pays" in x for x in cash["left_out"])
    assert "$350" in notes(out)


def test_items_the_seller_pays_are_not_counted():
    out, place, cash = read(BASE + "Seller pays the $350 condo document fee and the $600 capital contribution.")
    assert cash["total"] == DOWN + GUESS


def test_reviewer_listing_l7_items():
    out, place, cash = read(fixture("r29-buyer-l7.txt"))
    a = amounts(cash)
    assert a["One-time fee at closing (capital contribution)"] == 600 and a["One-time fee at closing (condo document fee)"] == 350
    assert "not counted anywhere" not in notes(out)
    assert out["property_tax"] == 5800


def test_reviewer_listing_l10_items():
    out, place, cash = read(fixture("r29-buyer-l10.txt"))
    a = amounts(cash)
    assert a["One-time fee at closing (prepaid taxes and insurance)"] == 2100
    assert a["One-time fee at closing (move-in deposit to the association)"] == 500


def test_capital_contribution_read_as_the_assessment_is_not_counted_twice():
    out, place, cash = read("Condo $300,000\n2 bed. HOA $200/month. Buyer pays $1,000 one-time capital contribution at closing.")
    total_items = [p for p in cash["parts"] if "1,000" in p["label"] or p["amount"] == 1000]
    assert len(total_items) == 1
    assert cash["total"] == DOWN + GUESS + 1000


def test_working_capital_with_a_seller_paid_assessment_is_counted():
    out, place, cash = read("Condo $300,000\n2 bed. HOA $240 per month. Special assessment $6,000 for new siding, seller pays. "
                            "Buyer pays a one-time $1,500 working capital contribution at closing.")
    assert out["special_assessment"] == 6000 and out["special_assessment_payer"] == "seller"
    assert cash["total"] == DOWN + GUESS + 1500


# ---- "Closing costs $4,000 plus $1,200 additional"
@pytest.mark.parametrize("line", [
    "Closing costs $4,000 plus $1,200 additional.",
    "Closing costs are $4,000, plus $1,200 additional.",
    "Closing costs: $4,000 (additional $1,200).",
    "Closing costs $4,000 plus $1,200 extra.",
    "Closing costs $4,000. Additional $1,200 for the survey.",
])
def test_additional_amount_next_to_closing_costs_is_counted(line):
    out, place, cash = read(BASE + line)
    assert out["closing_costs"] == 4000
    assert cash["total"] == DOWN + 4000 + 1200
    assert "$1,200" in notes(out) and "additional" in notes(out) and "counted in the cash to close" in notes(out)


def test_named_additional_item_next_to_closing_costs_is_counted():
    out, place, cash = read(BASE + "Closing costs estimate $4,000 plus an additional $1,200 for title and recording.")
    assert cash["total"] == DOWN + 4000 + 1200
    assert "$1,200" in notes(out)


def test_additional_in_a_seller_sentence_is_not_counted():
    out, place, cash = read(BASE + "Seller pays closing costs $4,000 plus $1,200 additional.")
    assert cash["total"] == DOWN + GUESS


# ---- a few named closing parts never lower a larger guess
@pytest.mark.parametrize("line", [
    "Lender fee $1,900. Appraisal $550.",
    "Title and escrow about $2,100 plus lender fees about $3,200.",
    "Buyer pays lender fee $1,900 and appraisal $550.",
])
def test_partial_closing_parts_do_not_lower_the_guess(line):
    out, place, cash = read(BASE + line)
    assert "closing_costs" not in out
    assert cash["total"] == DOWN + GUESS and cash["has_estimate"]
    label = [l for l in amounts(cash) if l.startswith("Closing costs")][0]
    assert "a guess" in label and "only part of the closing costs" in label
    assert "only part of the closing costs" in notes(out)


def test_parts_the_listing_calls_the_total_are_saved():
    out, place, cash = read(BASE + "Total closing costs in all: lender fee $1,900 and appraisal $550.")
    assert out["closing_costs"] == 2450 and cash["total"] == DOWN + 2450


def test_parts_bigger_than_the_guess_are_saved():
    out, place, cash = read("Condo $100,000\n2 bed. HOA $100/mo. Title and escrow about $2,100 plus lender fees about $3,200.")
    assert out["closing_costs"] == 5300


def test_reviewer_listing_l10_partial_sum():
    out, place, cash = read(fixture("r29-buyer-l10.txt"))
    assert "closing_costs" not in out
    assert amounts(cash)[[l for l in amounts(cash) if l.startswith("Closing costs")][0]] == 9750
    assert "only part of the closing costs" in notes(out)


# ---- a monthly special assessment is kept apart from the HOA
@pytest.mark.parametrize("line,tail", [
    ("Special assessment of $200 a month for 24 months, buyer pays.", "24 months"),
    ("Special assessment: $200/month through 2029.", "2029"),
    ("- Special assessment: $200 per month until 2029", "2029"),
])
def test_monthly_special_assessment_is_kept_apart(line, tail):
    out, place, cash = read(BASE + line)
    assert out["hoa"] == 200 and out["other_monthly_fees"] == 200
    assert tail in notes(out) and "kept apart from the $200 HOA" in notes(out)
    cost = money.buy_cost(place)
    names = {l["label"]: l["amount"] for l in cost["lines"]}
    assert names["HOA"] == 200 and names["Special assessment (monthly, kept apart from the HOA)"] == 200


def test_reviewer_listing_l7_assessment():
    out, place, cash = read(fixture("r29-buyer-l7.txt"))
    assert out["hoa"] == 180 and out["other_monthly_fees"] == 200
    assert "$4,800 in all" in notes(out) and "ends after 24 months" in notes(out)
    cost = money.buy_cost(place)
    line = next(l for l in cost["lines"] if l["key"] == "other")
    assert "ends after 24 months" in line["note"] and "$4,800" in line["note"]


@pytest.mark.parametrize("line", [
    "Buyer closing costs about $7,000 (title $1,600, lender $2,900, prepaid $2,500).",
    "Buyer closing costs about $7,000 (title $1,600, lender $2,900, prepaid taxes and insurance $2,500).",
    "Buyer closing costs about $7,000, including a $350 condo document fee and prepaid taxes of $2,500.",
])
def test_items_inside_the_stated_closing_costs_are_not_added_again(line):
    out, place, cash = read(BASE + line)
    assert out["closing_costs"] == 7000
    assert cash["total"] == DOWN + 7000
    assert not any(p["label"].startswith("One-time fee") for p in cash["parts"])
