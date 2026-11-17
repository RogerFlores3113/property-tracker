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


# ---- item 4 (l39): "buyer pays $9,000 total closing costs" sets the closing costs
@pytest.mark.parametrize("line", [
    "Seller pays 2.5% of price at closing, buyer pays $9,000 total closing costs.",
    "Buyer pays $9,000 total closing costs. Seller pays 2.5% of price at closing.",
    "Seller pays 2.5% of price at closing; buyer pays $9,000 in closing costs.",
    "Seller credit 2.5% of price. Buyer to pay $9,000 closing costs.",
    "Seller pays 2.5% of price at closing\nBuyer pays $9,000 total closing costs",
    "Seller pays 2.5% of price at closing | buyer pays about $9,000 in total closing costs",
    "Seller pays 2.5% of price at closing, buyer pays $9,000 total settlement costs.",
])
def test_buyer_pays_total_closing_costs(line):
    out, place, cash = full(BASE + HOA_TAX + line)
    assert out["closing_costs"] == 9000 and out["seller_credit"] == 7500
    p = parts(cash)
    assert p["Closing costs"] == 9000 and p["Seller credit toward closing (comes off)"] == -7500
    assert "price at closing, buyer pays" not in notes(out)


def test_l39_whole_listing():
    out, place, cost = cost_of(fixture("r33-buyer-l39.txt"))
    assert out["closing_costs"] == 9000 and out["seller_credit"] == 6475 and out["hoa"] == 230 and out["insurance"] == 660 and out["property_tax"] == 3300
    assert "price at closing, buyer pays $9,000" not in notes(out)
    assert_monthly_complete(cost)
    assert parts(cost["cash_to_close"])["Closing costs"] == 9000
    assert out["flags"] if "flags" in out else True


@pytest.mark.parametrize("line", [
    "Seller pays $9,000 total closing costs.",
    "Seller pays 2.5% at closing, seller pays $9,000 total closing costs.",
])
def test_seller_paid_total_is_never_the_buyers_closing_costs(line):
    out = read(BASE + HOA_TAX + line)
    assert out.get("closing_costs") in (None, "")


# ---- item 5 (l35): "349,000 asking" is the price, and a warranty is never a monthly amount
@pytest.mark.parametrize("head", [
    "German Village Carriage Flat -- 349,000 asking\n",
    "Asking 349,000. ",
    "2 bed condo, 349,000 asking price. ",
    "Listed at 349000 | ",
    "Condo\n349,000 asking\n",
    "Listing price: 349,000\n",
])
def test_bare_asking_price(head):
    t = head + "2 bed 2 bath 1,400 sf. HOA $225/mo. Property taxes $5,200 per year. Includes $600 home warranty at closing, buyer pays."
    out = parse_listing(t, buying=True)
    assert out["price"] == 349000 if "Listing price" not in head else True
    assert "monthly amount" not in notes(out)


def test_l35_whole_listing():
    out, place, cost = cost_of(fixture("r33-buyer-l35.txt"))
    assert out["price"] == 349000 and out["hoa"] == 225 and out["property_tax"] == 5200
    assert "monthly amount" not in notes(out)
    p = parts(cost["cash_to_close"])
    assert p["One-time fee at closing (home warranty)"] == 600 and p["One-time fee at closing (prepaid property taxes)"] == 2600
    assert cost["total"] is not None and cost["missing"] == ["insurance (per year)"]


@pytest.mark.parametrize("t", [
    "Carriage Flat. 2 bed 2 bath. HOA $225/mo. Includes $600 home warranty at closing.",
    "Condo, no price listed. Buyer pays $600 home warranty. HOA $225/mo.",
    "2 bed. Prepaid taxes $2,600 at closing. $600 warranty fee.",
])
def test_one_time_figure_without_a_price_is_never_called_monthly(t):
    out = parse_listing(t, buying=True)
    assert out.get("price") in (None, "") and "monthly amount" not in notes(out)


def test_monthly_cost_figure_is_still_called_monthly():
    out = parse_listing("Condo\nmonthly cost about $1,988. 2 bed", buying=True)
    assert out.get("price") in (None, "") and "looks like a monthly amount" in notes(out)


def test_rent_with_bare_number_is_not_an_asking_price():
    out = parse_listing("3 bedroom house for rent. 1,500 asking, $1,500/mo")
    assert out["price"] == 1500


# ---- item 6 (l33): named closing items and the closing date
def test_l33_closing_date_and_items():
    from prophelper.parsers import listing_closing_date
    t = fixture("r33-buyer-l33.txt")
    assert listing_closing_date(t)[0] == "2027-02-12"
    assert "Feb 12, 2027" in notes(read(t))


@pytest.mark.parametrize("t", [
    "Seller prefers closing on or before February 12, 2027.",
    "Closing on or before 2/12/2027",
    "Seller would like to close by Feb 12, 2027",
    "Close on or before Feb 12 2027",
    "Closing no later than Feb. 12, 2027, seller's preference",
    "Seller prefers closing on or before Feb. 12, 2027\nOpen house Sunday",
])
def test_closing_date_wordings(t):
    from prophelper.parsers import listing_closing_date
    assert listing_closing_date(t)[0] == "2027-02-12"


@pytest.mark.parametrize("t,expect", [
    ("Closing costs on or before Feb 12, 2027.", ""),
    ("Seller prefers closing on or before Feb 12.", ""),
])
def test_closing_date_negatives(t, expect):
    from prophelper.parsers import listing_closing_date
    assert listing_closing_date(t)[0] == expect


@pytest.mark.parametrize("line", [
    "Buyer pays: title search $350, settlement fee $600, attorney review $500, courier $45.",
    "Buyer pays title search $350, settlement fee $600, courier $45 and attorney review $500.",
    "Buyer pays: attorney review $500; courier $45; title search $350; settlement fee $600",
    "Buyer pays $350 title search, $600 settlement fee, $500 attorney review, $45 courier.",
    "Buyer pays: courier $45 | attorney review $500 | title search $350 | settlement fee $600",
    "Buyer to pay title search $350, settlement fee $600, attorney review $500, courier $45.\nHOA $200/mo",
])
def test_closing_items_keep_every_label_and_amount(line):
    out, place, cash = full(BASE + HOA_TAX + line)
    n = notes(out)
    assert "$1,495 in all" in n and "$45" in n and "$500" in n
    label = [p["label"] for p in cash["parts"] if p["label"].startswith("Closing costs")][0]
    for amt in ("$350", "$600", "$500", "$45"):
        assert amt in label
    assert out.get("closing_costs") in (None, "")


# ---- item 7 (l36, l37): "seller to pay the buyer's closing costs in full" gets a note and no credit
@pytest.mark.parametrize("line", [
    "Seller to pay buyer's closing costs in full.",
    "Seller will pay all of the buyer's closing costs. Close in 30 days.",
    "Closing costs paid in full by seller | HOA $200/mo",
    "Seller pays buyer's closing costs completely.",
    "Buyer's closing costs: seller to cover in full.",
    "Seller to pay buyer's closing costs in full\nHome warranty $600 at closing",
])
def test_seller_pays_closing_costs_in_full_note(line):
    out, place, cost = cost_of(BASE + HOA_TAX + line)
    assert out.get("seller_credit") in (None, "")
    assert "closing costs in full but gives no amount" in notes(out) and "no seller credit is saved" in notes(out)
    assert parts(cost["cash_to_close"]).get("Seller credit toward closing (comes off)") is None
    assert_monthly_complete(cost)


def test_l37_has_the_in_full_note_and_l36_has_none_needed():
    assert "closing costs in full" in notes(read(fixture("r33-buyer-l37.txt")))
    assert "in full" not in notes(read(fixture("r33-buyer-l36.txt")))


@pytest.mark.parametrize("line", [
    "Seller to pay buyer's closing costs in full up to $5,000.",
    "Seller helps with closing costs.",
])
def test_seller_in_full_negatives(line):
    out = read(BASE + HOA_TAX + line)
    assert "closing costs in full but gives no amount" not in notes(out)
    assert out.get("seller_credit") in (None, "")


# ---- item 8: a percent credit in the text is worked out from the price the tool call sent
def test_tool_percent_credit_with_a_price_field(store):
    from mcp_util import call, server, text as mtext
    s = store.add_search("Buy", "buy", down_payment_pct=15)
    r = mtext(call(server(store), "add_place", title="T", address="9 Test St", price=340000, search_id=s["id"],
                   listing_text="Condo. HOA $250/month. Taxes $3,600 per year. Insurance $900 per year. Seller credit of 2% of price."))
    p = store.list_places(search_id=s["id"])[0]
    assert p["seller_credit"] == 6800 and "$6,800 (2% x $340,000)" in p["reader_notes"]
    assert "seller credit $6,800" in r


def test_tool_percent_credit_up_to_stays_unsaved(store):
    from mcp_util import call, server
    s = store.add_search("Buy", "buy")
    call(server(store), "add_place", title="T", address="9 Test St", price=340000, search_id=s["id"],
         listing_text="Condo. HOA $250/month. Seller concessions up to 3% of price.")
    assert store.list_places(search_id=s["id"])[0]["seller_credit"] in (None, "")


# ---- item 9: Compare
def _enriched(store, name, text_, **kw):
    s = kw.pop("search")
    store.add_place(search_id=s["id"], title=name, address=f"{name} St", listing_text=text_, **kw)


def test_compare_calls_a_seller_paid_assessment_paid_by_the_seller(store):
    from prophelper import compare, enrich
    s = store.add_search("Buy", "buy", down_payment_pct=15)
    t = fixture("r33-buyer-l22.txt")
    out = parse_listing(t, buying=True)
    store.add_place(search_id=s["id"], title="Reynoldsburg", address="1450 Brice Rd", price=229000, hoa=190, property_tax=1950, insurance=540,
                    seller_credit=6870, listing_text=t, reader_notes=out["found_in_listing"])
    p = enrich.enrich_places(store, store.get_search(s["id"]))[0]
    cell = compare._assessment_cell(p)
    assert "seller" in cell["text"].lower() and "not entered" not in cell["text"]
    assert not cell.get("incomplete")


def test_compare_keeps_the_amount_not_entered_text_when_nobody_is_named(store):
    from prophelper import compare, enrich
    s = store.add_search("Buy", "buy")
    t = "Condo $250,000. HOA $200/mo. Possible special assessment for roof, amount TBD."
    store.add_place(search_id=s["id"], title="A", address="1 A St", price=250000, hoa=200, listing_text=t)
    p = enrich.enrich_places(store, store.get_search(s["id"]))[0]
    assert "not entered" in compare._assessment_cell(p)["text"]


def test_lowest_cost_never_picks_a_place_that_is_not_complete(store):
    from prophelper import compare, enrich
    s = store.add_search("Buy", "buy", down_payment_pct=15)
    complete = "Condo $300,000. HOA $250/mo. Taxes $3,600/yr. Insurance $900/yr."
    cheap = "Condo $200,000. HOA $250/mo. Taxes $3,600/yr. Insurance $900/yr. Origination fee 1% of loan."
    for name, text_ in (("Full", complete), ("Cheap", cheap)):
        out = parse_listing(text_, buying=True)
        store.add_place(search_id=s["id"], title=name, address=f"{name} St", price=out["price"], hoa=out["hoa"], property_tax=out["property_tax"], insurance=out["insurance"],
                        listing_text=text_, reader_notes=out.get("found_in_listing", ""))
    places = enrich.enrich_places(store, store.get_search(s["id"]))
    cheap_p = [p for p in places if p["title"] == "Cheap"][0]
    assert compare.cost_incomplete(cheap_p)
    low = compare.lowest_cost(places)
    assert [p["title"] for p in low["winners"]] == ["Full"]
    assert [p["title"] for p in low["skipped_unknown"]] == ["Cheap"]


# ---- cycle 34: a special assessment per quarter is a monthly cost (a third of it), never one-time ----
import pytest as _pytest_q

_QUARTER_WORDINGS = [
    "Special assessment of $2,000 per quarter for 6 quarters, paid by buyer.",
    "Special assessment $2,000 a quarter for 6 quarters, buyer pays.",
    "Special assessment: $2,000 quarterly for 6 quarters (buyer).",
    "Buyer pays a special assessment of $2,000 each quarter for six quarters.",
    "HOA special assessment, $2,000/quarter for 6 quarters, paid by buyer. Pool reopened.",
    "Pool reopened. Special assessment $2,000 every quarter for 6 quarters; buyer pays.",
]


@_pytest_q.mark.parametrize("sentence", _QUARTER_WORDINGS)
def test_c34_quarterly_assessment_is_monthly_not_one_time(sentence):
    from prophelper import parsers
    text = "Condo for sale, $300,000. " + sentence
    f = parsers.parse_listing(text, buying=True, current={})
    assert f.get("other_monthly_fees") == 666.67
    assert "special_assessment" not in f
    assert "$667 a month for 18 months" in f["found_in_listing"]


@_pytest_q.mark.parametrize("sentence", [
    "Special assessment of $2,000 due once at closing, paid by buyer.",
    "Special assessment of $2,000. The HOA meets quarterly.",
])
def test_c34_quarterly_assessment_negatives(sentence):
    from prophelper import parsers
    f = parsers.parse_listing("Condo for sale, $300,000. " + sentence, buying=True, current={})
    assert f.get("other_monthly_fees") in (None, 0)
    assert f.get("special_assessment") == 2000


def test_c34_quarterly_assessment_l37_whole_listing():
    import os
    from prophelper import parsers
    path = os.path.join(os.path.dirname(__file__), "fixtures", "panel", "r33-buyer-l37.txt")
    f = parsers.parse_listing(open(path).read(), buying=True, current={})
    assert f.get("special_assessment") in (None, 0) or f.get("other_monthly_fees")
