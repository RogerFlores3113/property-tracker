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


# ---- item 3 (bb): seller-paid and one-time buyer items never mark the monthly cost incomplete
def assert_monthly_complete(cost):
    assert cost["all_in"] is True and not cost["missing"] and not money.uncounted_display(cost) and not cost.get("one_time_left")


def test_l21_escrow_set_up_goes_to_cash_to_close():
    out, place, cost = cost_of(fixture("r33-buyer-l21.txt"))
    assert 1500 in [p["amount"] for p in cost["cash_to_close"]["parts"] if "escrow set-up" in p["label"]]
    assert out["seller_credit"] == 5000 and out["hoa"] == 420 and out["insurance"] == 900
    assert "$1,500 escrow set-up" in notes(out) and "counted in the cash to close" in notes(out)
    assert_monthly_complete(cost)


@pytest.mark.parametrize("line", [
    "Also due at closing: $1,500 escrow set-up for taxes.",
    "$1,500 escrow set-up due at closing.",
    "Escrow set-up $1,500 at closing",
    "Buyer pays $1,500 for escrow setup at closing.",
    "Due at closing | escrow set-up: $1,500",
    "Closing: escrow set-up fee of $1,500 (buyer).",
])
def test_escrow_set_up_wordings(line):
    out, place, cost = cost_of(BASE + HOA_TAX + line)
    assert any(abs(p["amount"] - 1500) < 0.01 and "escrow" in p["label"] for p in cost["cash_to_close"]["parts"]), cost["cash_to_close"]["parts"]
    assert out.get("insurance") == 900 and out.get("closing_costs") in (None, "")
    assert_monthly_complete(cost)


def test_l22_seller_paid_assessment_and_concession():
    out, place, cost = cost_of(fixture("r33-buyer-l22.txt"))
    assert out["seller_credit"] == 6870 and out["hoa"] == 190 and out["insurance"] == 540
    assert "not a cost to you" in notes(out)
    assert out.get("special_assessment") in (None, "") and out.get("other_monthly_fees") in (None, "")
    assert_monthly_complete(cost)


@pytest.mark.parametrize("line", [
    "Special assessment (windows) $450 per month for 18 months, seller to pay.",
    "Seller pays the special assessment of $450/month for 18 months (windows).",
    "Special assessment $450 a month for 18 months, paid by the seller.",
    "Special assessment: $8,100 for windows, seller pays.",
    "Windows special assessment $450/mo x 18 months - seller to pay",
    "Special assessment $8,100 over 18 months, seller pays it.",
])
def test_seller_paid_assessment_wordings_never_mark_the_cost_incomplete(line):
    out, place, cost = cost_of(BASE + HOA_TAX + line)
    assert out.get("other_monthly_fees") in (None, "") and out.get("special_assessment_payer") in (None, "", "seller")
    assert "seller" in notes(out) or any("paid by the seller" in n for n in cost["notes"])
    assert_monthly_complete(cost)
    assert not cost["cash_to_close"]["left_out"]


def test_l24_origination_percent_is_left_out_of_cash_not_monthly():
    out, place, cost = cost_of(fixture("r33-buyer-l24.txt"))
    assert out["seller_credit"] == 4000 and out["hoa"] == 210 and out["insurance"] == 720
    assert_monthly_complete(cost)
    left = cost["cash_to_close"]["left_out"]
    assert len(left) == 1 and "1% of the loan" in left[0] and "$2,252" in left[0]
    assert "not counted anywhere" not in notes(out).split("Origination")[-1]
    assert "one-time lender fee" in notes(out)


@pytest.mark.parametrize("line,pct", [
    ("Origination fee 1% of loan.", 1),
    ("Lender origination fee: 1% of the loan amount.", 1),
    ("1% origination fee.", 1),
    ("Loan origination fee 0.5% of the mortgage | HOA $200/mo", 0.5),
    ("Origination fee 1% of loan\nClose in 30 days", 1),
    ("Buyer pays origination of 1.5% of the loan at closing.", 1.5),
])
def test_origination_percent_wordings(line, pct):
    out, place, cost = cost_of(BASE + HOA_TAX + line)
    assert_monthly_complete(cost)
    left = cost["cash_to_close"]["left_out"]
    assert len(left) == 1 and f"{pct:g}% of the loan" in left[0]


def test_origination_in_dollars_is_still_a_closing_item():
    out, place, cost = cost_of(BASE + HOA_TAX + "Buyer pays origination fee $1,800 and appraisal $500.")
    assert not cost["cash_to_close"]["left_out"]
    assert "left_out" not in out


def test_l33_capitalization_fee_and_closing_items():
    out, place, cost = cost_of(fixture("r33-buyer-l33.txt"))
    assert 1000 in [p["amount"] for p in cost["cash_to_close"]["parts"] if "capitalization fee" in p["label"]]
    assert out["seller_credit"] == 6760 and out["hoa"] == 365 and out["insurance"] == 864 and out["property_tax"] == 5900
    n = notes(out)
    assert "title search $350 plus settlement fee $600 plus attorney review $500 plus courier $45, $1,495 in all" in n
    label = [p["label"] for p in cost["cash_to_close"]["parts"] if p["label"].startswith("Closing costs")][0]
    assert "$500 for attorney review" in label and "$45 for courier" in label
    assert "Lender credit 0.5% not included" in n and "no lender credit is counted" in n and "not counted anywhere" not in n
    assert_monthly_complete(cost)


@pytest.mark.parametrize("line", [
    "One-time capitalization fee of $1,000 payable by purchaser.",
    "Capitalization fee $1,000 paid by buyer at closing.",
    "Buyer pays a $1,000 capitalization fee.",
    "Purchaser to pay $1,000 capitalisation fee at closing",
    "Due at closing: $1,000 capitalization fee",
    "Condo fee | capitalization fee: $1,000 (buyer)",
])
def test_capitalization_fee_wordings(line):
    out, place, cost = cost_of(BASE + HOA_TAX + line)
    assert [p["amount"] for p in cost["cash_to_close"]["parts"] if "capitali" in p["label"]] == [1000]
    assert_monthly_complete(cost)


def test_capitalization_fee_seller_pays_is_not_counted():
    out, place, cost = cost_of(BASE + HOA_TAX + "Seller pays the $1,000 capitalization fee.")
    assert not [p for p in cost["cash_to_close"]["parts"] if "capitali" in p["label"]]


# ---- item 3: "Seller pays $5,000 in concessions" is the seller credit (l36)
@pytest.mark.parametrize("line", [
    "Seller pays $5,000 in concessions.",
    "Seller pays $5,000 in concessions\nHome warranty $600 at closing.",
    "Seller will give $5,000 as a closing credit. Close in 30 days.",
    "Seller to contribute $5,000 in credits; buyer pays own attorney.",
    "Offer: seller pays $5,000 in concessions, buyer pays survey.",
    "Seller concessions: $5,000 | HOA $200/mo",
    "Seller pays $5,000 in closing concessions.",
])
def test_seller_concessions_wordings_are_the_credit(line):
    out, place, cost = cost_of(BASE + HOA_TAX + line)
    assert out["seller_credit"] == 5000
    assert [p["amount"] for p in cost["cash_to_close"]["parts"] if p["label"].startswith("Seller credit")] == [-5000]
    assert_monthly_complete(cost)
    assert not cost["cash_to_close"]["left_out"]


def test_l36_whole_listing():
    out, place, cost = cost_of(fixture("r33-buyer-l36.txt"))
    assert out["seller_credit"] == 5000 and out["hoa"] == 310 and out["insurance"] == 768 and out["property_tax"] == 4700
    parts_ = parts(cost["cash_to_close"])
    assert parts_["Seller credit toward closing (comes off)"] == -5000 and parts_["One-time fee at closing (home warranty)"] == 600
    assert "Seller pays $5,000 in concessions" not in notes(out)
    assert_monthly_complete(cost)
    assert out["closing_date"] if "closing_date" in out else True


def test_seller_pays_in_assessments_is_not_a_credit():
    out = read(BASE + HOA_TAX + "Seller pays $5,000 in HOA assessments.")
    assert out.get("seller_credit") in (None, "")
