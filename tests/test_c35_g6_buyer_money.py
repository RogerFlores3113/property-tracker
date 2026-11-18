"""Cycle 35 G6: buyer money. Item 1: a buyer-paid transfer fee is a named one-time closing item, never the total closing costs."""
import os

import pytest

from prophelper import money
from prophelper.parsers import parse_listing

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "panel")


def fixture(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


def read(text_, price=None):
    """The listing read the way add_place reads it: a price sent as a field is passed as the known price."""
    return parse_listing(text_, "", buying=True, current=({"price": price} if price else None))


def full(text_, price=None):
    out = read(text_, price)
    place = {**out, "listing_text": text_}
    if price:
        place["price"] = price
    return out, place, money.cash_to_close(place)


def notes(out):
    return out.get("found_in_listing", "")


def parts(cash):
    return {p["label"]: p["amount"] for p in cash["parts"]}


BASE = "HOA $200. Taxes $3,000/yr. Insurance $50/mo. "


# ---- item 1 (buyer T1): "Buyer pays $400 transfer fee." is one named item, never the whole closing costs
@pytest.mark.parametrize("line", [
    "Buyer pays $400 transfer fee.",
    "Transfer fee $400 paid by buyer",
    "Transfer fee: $400 (paid by the buyer).",
    "The buyer will pay a $400 transfer fee at closing.",
    "Buyer to pay transfer fee of $400",
    "- Buyer pays: $400 transfer fee\n- Parking: street",
    "Closing: buyer pays $400 transfer fee | Parking street",
])
def test_buyer_transfer_fee_is_not_the_closing_costs(line):
    out, place, cash = full("Condo\n" + BASE + line, 250000)
    assert out.get("closing_costs") in (None, "")
    p = parts(cash)
    assert p["One-time fee at closing (transfer fee)"] == 400
    guess = [v for k, v in p.items() if k.startswith("Closing costs (a guess")]
    assert guess == [7500]
    assert cash["total"] == 50000 + 7500 + 400
    assert "counted in the cash to close as a one-time fee" in notes(out)
    assert "not counted" not in notes(out).lower()


def test_buyer_transfer_fee_beside_stated_closing_costs_is_added_on_top():
    out, _p, cash = full("Condo\n" + BASE + "Estimated closing costs $9,800. Buyer pays one-time $3,200 transfer fee at closing.", 450000)
    assert out["closing_costs"] == 9800
    assert parts(cash)["Closing costs"] == 9800
    assert parts(cash)["One-time fee at closing (transfer fee)"] == 3200


def test_transfer_fee_inside_the_stated_closing_total_is_not_added_twice():
    out, _p, cash = full("Condo\n" + BASE + "Buyer closing costs about $9,000, including a $400 transfer fee paid by buyer.", 250000)
    assert out["closing_costs"] == 9000
    assert "One-time fee at closing (transfer fee)" not in parts(cash)


def test_seller_paid_and_unnamed_transfer_fee_stay_out():
    for line, who in (("Seller pays $400 transfer fee.", "seller"), ("Transfer fee $400.", "")):
        out, _p, cash = full("Condo\n" + BASE + line, 250000)
        assert out.get("closing_costs") in (None, "")
        assert "One-time fee at closing (transfer fee)" not in parts(cash)
        assert "$400 transfer fee" in notes(out)
        if who:
            assert "seller pays" in notes(out)


def test_transfer_fee_with_the_price_in_the_text_matches_the_price_field():
    a, _p, ca = full("Condo $250,000\n" + BASE + "Buyer pays $400 transfer fee.")
    b, _p2, cb = full("Condo\n" + BASE + "Buyer pays $400 transfer fee.", 250000)
    assert parts(ca) == parts(cb)


def test_transfer_fee_with_seller_credit_keeps_the_credit_and_the_fee():
    out, _p, cash = full("Condo\n" + BASE + "Seller will pay $7,000 in closing costs. Transfer fee paid by buyer $1,500.", 300000)
    assert out["seller_credit"] == 7000 and out.get("closing_costs") in (None, "")
    p = parts(cash)
    assert p["One-time fee at closing (transfer fee)"] == 1500
    assert cash["total"] == 60000 + 9000 + 1500 - 7000


# ---- item 2 (buyer T2, T4): one-time buyer fees at closing are named items, never a monthly gap, on both paths
def mcp_add(store, listing, **fields):
    from mcp_util import call, server, text as mtext
    s = store.add_search("Buy", "buy")
    args = {"hoa": 200, "property_tax": 3000, "insurance": 600, **fields}
    args = {k: v for k, v in args.items() if v is not None}
    r = mtext(call(server(store), "add_place", title="T", address="9 Test St", price=250000, search_id=s["id"], listing_text=listing, **args))
    return r, store.list_places(search_id=s["id"])[0]


@pytest.mark.parametrize("line,named", [
    ("Buyer pays $350 survey and $200 flood cert at closing.", ["$350 for survey", "$200 for flood cert"]),
    ("At closing the buyer pays a $200 flood cert and a $350 survey.", ["$350 for survey", "$200 for flood cert"]),
    ("Buyer pays: $350 survey; $200 flood certification", ["$350 for survey", "$200 for flood cert"]),
    ("Buyer pays $350 survey, $200 flood cert (both at closing).", ["$350 for survey", "$200 for flood cert"]),
    ("- Buyer pays $350 survey at closing\n- Buyer pays $200 flood cert at closing", ["$350 for survey", "$200 for flood cert"]),
    ("Buyer pays $350 survey at closing.", ["$350 for survey"]),
    ("Survey $350 at closing, paid by buyer.", ["$350 for survey"]),
])
def test_survey_and_flood_cert_are_named_and_never_dropped(line, named):
    out, _p, cash = full("Condo\n" + BASE + line, 250000)
    label = " ".join(p["label"] for p in cash["parts"])
    for n in named:
        assert n in label, (n, label)
    assert out.get("closing_costs") in (None, "")
    n = notes(out)
    for amount in ("$350",) + (("$200",) if "flood" in line else ()):
        assert amount in n or amount in label
    assert "Ask for the full closing cost estimate" in n or "full closing cost" in n


@pytest.mark.parametrize("line", [
    "Buyer pays $350 survey and $200 flood cert at closing.",
    "Buyer pays $350 survey at closing.",
    "$300 elevator reservation fee due at closing.",
    "Buyer pays a $300 elevator reservation fee at closing.",
    "Elevator reservation fee: $300 due at closing",
    "Due at closing: $300 elevator reservation fee.",
])
def test_one_time_fees_never_mark_the_monthly_cost_incomplete(store, line):
    r, place = mcp_add(store, line)
    assert "not complete" not in r and "missing" not in r.lower().split("monthly cost")[-1]
    assert "True monthly cost $1,764" in r
    assert "one-time amount in the listing notes" not in r


@pytest.mark.parametrize("line", [
    "$300 elevator reservation fee due at closing.",
    "Buyer pays a $300 elevator reservation fee at closing.",
    "Elevator reservation fee: $300 due at closing",
    "Due at closing: $300 elevator reservation fee.",
    "Buyer to pay $300 elevator reservation fee, due at closing.",
    "Move-in notes. $300 elevator reservation fee (due at closing) | Pets ok",
])
def test_elevator_reservation_fee_is_in_the_cash_to_close(line):
    out, _p, cash = full("Condo\n" + BASE + line, 250000)
    assert parts(cash)["One-time fee at closing (elevator reservation fee)"] == 300
    assert cash["total"] == 50000 + 7500 + 300
    assert "$300" in notes(out) and "elevator reservation fee" in notes(out)
    assert "counted in the cash to close as a one-time fee" in notes(out)


def test_fee_due_at_closing_with_no_payer_does_not_say_the_buyer_pays():
    out, _p, cash = full("Condo\n" + BASE + "$300 elevator reservation fee due at closing.", 250000)
    assert "buyer pays" not in notes(out) and "does not say who pays it" in notes(out)
    out, _p, cash = full("Condo\n" + BASE + "Buyer pays a $300 elevator reservation fee at closing.", 250000)
    assert "buyer pays the $300 elevator reservation fee" in notes(out) and "Ask who pays" not in notes(out)


@pytest.mark.parametrize("line", [
    "Seller pays the $300 elevator reservation fee at closing.",
    "$300 elevator reservation fee due at closing, paid by seller.",
    "Elevator reservation fee $20 per month.",
    "Pet fee $300 due at closing? Please ask.",
])
def test_elevator_fee_negatives_are_not_counted(line):
    out, _p, cash = full("Condo\n" + BASE + line, 250000)
    assert not any("One-time fee" in p["label"] for p in cash["parts"]), cash["parts"]


def test_price_in_text_and_price_field_read_one_time_fees_the_same(store):
    line = "Buyer pays $350 survey and $200 flood cert at closing."
    a, _p, ca = full("Condo $250,000\n" + BASE + line)
    b, _p2, cb = full("Condo\n" + BASE + line, 250000)
    assert parts(ca) == parts(cb) and notes(a) == notes(b)


# ---- item 3 (buyer compare): the special assessment row shows the entered amount and payer
def assessment_cell(store, listing, **fields):
    from prophelper import compare, enrich
    s = store.add_search("B", "buy")
    out = parse_listing(listing, "", buying=True)
    keep = {k: out[k] for k in ("price", "hoa", "property_tax", "insurance", "other_monthly_fees", "special_assessment", "special_assessment_payer", "seller_credit") if out.get(k) not in (None, "")}
    store.add_place(search_id=s["id"], title="H", address="1 A St", beds=2, listing_text=listing, **{**keep, **fields})
    rows = enrich.enrich_places(store, store.get_search(s["id"]))
    return compare._assessment_cell(rows[0]), out


@pytest.mark.parametrize("line,text,total", [
    ("Special assessment of $500 a month for 18 months, paid by buyer.", "$500 a month for 18 months (you pay it)", 9000),
    ("Special assessment: $150 per month through December 2028, buyer pays.", "$150 a month through 2028 (you pay it)", None),
    ("Special assessment of $2,000 per quarter for 6 quarters, paid by buyer.", "$667 a month for 18 months (you pay it)", 12000),
    ("Special assessment of $18,000, split evenly between owners over 36 months, buyer responsible for payments after closing.", "$500 a month for 36 months (you pay it)", 18000),
    ("Special assessment $9,000 over 36 months, buyer pays it.", "$250 a month for 36 months (you pay it)", 9000),
])
def test_compare_assessment_row_shows_the_entered_monthly_amount(store, line, text, total):
    cell, out = assessment_cell(store, "Condo $300,000\n2 bed 2 bath. HOA $200/mo. Taxes $3,000/yr. " + line)
    assert out["other_monthly_fees"]
    assert cell["text"] == text and "not entered" not in cell["text"] and not cell["incomplete"]
    assert cell["value"] == total


@pytest.mark.parametrize("name,line_text", [
    ("l37", "r34-buyer-l37.txt"), ("l40", "r34-buyer-l40.txt"),
])
def test_compare_assessment_row_for_the_reviewer_listings(store, name, line_text):
    cell, out = assessment_cell(store, fixture(line_text))
    assert "not entered" not in cell["text"] and "you pay it" in cell["text"]


def test_compare_assessment_row_still_says_amount_not_entered_when_none_was_read(store):
    cell, _o = assessment_cell(store, "Condo $300,000\n2 bed. There is a special assessment coming.")
    assert cell["text"] == "Mentioned in the listing, amount not entered" and cell["incomplete"]


def test_compare_assessment_row_seller_pays_stays_not_your_cost(store):
    cell, _o = assessment_cell(store, "Condo $300,000\n2 bed. Special assessment of $450 a month for 18 months, seller to pay.")
    assert cell["text"] == "Paid by the seller (not your cost)" and cell["value"] == 0.0


# ---- item 4 (buyer l42, V1, V2): "No PMI" and "PMI not required" are a stated zero, with a check-the-lender note
PMI_BASE = "Condo $300,000\n2 bed 2 bath. HOA $200/mo. Taxes $3,000/yr. Insurance $900/yr. "


def pmi_line(text_):
    place = {**read(text_), "listing_text": text_}
    cost = money.buy_cost(place, {"down_payment_pct": 10})
    return next((l for l in cost["lines"] if l["key"] == "pmi"), None), cost


@pytest.mark.parametrize("line,quote", [
    ("No PMI.", "No PMI"),
    ("PMI not required.", "PMI not required"),
    ("Mortgage insurance not required on this loan.", "Mortgage insurance not required"),
    ("Seller note: no private mortgage insurance needed; call us", "no private mortgage insurance needed"),
    ("PMI: none", "PMI: none"),
    ("Taxes low | No PMI | Quiet street", "No PMI"),
    ("- PMI is not required\n- Corner unit", "PMI is not required"),
    ("Is PMI required? No.", "PMI required? No"),
    ("PMI waived for this program.", "PMI waived"),
])
def test_no_pmi_is_a_stated_zero(line, quote):
    out = read(PMI_BASE + line)
    n = notes(out)
    assert quote.lower() in n.lower() and "(PMI) is set to $0 a month" in n and "ask the lender" in n.lower()
    pmi, cost = pmi_line(PMI_BASE + line)
    assert pmi["amount"] == 0 and "quoted in the listing" in pmi["label"]
    assert cost["pmi"] == 0


def test_no_pmi_reviewer_listing_l42():
    text_ = fixture("r34-buyer-l42.txt")
    out = read(text_)
    assert "Mortgage insurance not required" in notes(out) and "(PMI) is set to $0 a month" in notes(out)
    assert out["hoa"] == 180 and out["insurance"] == 900 and out["seller_credit"] == 8250
    pmi, cost = pmi_line(text_)
    assert pmi["amount"] == 0 and cost["pmi"] == 0


@pytest.mark.parametrize("line", [
    "No PMI if you put 20% down.",
    "PMI not required with 20% down.",
    "PMI is required unless you put 20% down.",
    "PMI required.",
    "Is PMI required? Please ask.",
    "No PMI? Call the lender.",
    "PMI not required once you reach 20% equity.",
])
def test_conditional_or_unanswered_pmi_is_not_a_zero(line):
    pmi, cost = pmi_line(PMI_BASE + line)
    assert pmi["amount"] is not None and pmi["amount"] > 0 and "an estimate" in pmi["label"]
    assert "(PMI) is set to $0" not in notes(read(PMI_BASE + line))


def test_a_pmi_quote_and_a_no_pmi_disagree_so_neither_is_used():
    text_ = PMI_BASE + "PMI approx $85/mo. No PMI."
    out = read(text_)
    assert "disagree" in notes(out) and "(PMI) is set to $0" not in notes(out)
    pmi, _c = pmi_line(text_)
    assert pmi["amount"] > 0 and "an estimate" in pmi["label"]


def test_a_quoted_pmi_still_wins_without_a_no_pmi():
    pmi, _c = pmi_line(PMI_BASE + "PMI approx $85/mo.")
    assert pmi["amount"] == 85 and "quoted" in pmi["label"]


# ---- item 5 (buyer V2): "HO6 insurance $40 monthly" is the insurance, $480 a year
@pytest.mark.parametrize("line", [
    "HO6 insurance $40 monthly.",
    "Monthly HO6 insurance: $40.",
    "Monthly insurance $40",
    "HO6 insurance, $40 monthly",
    "$40/month HO6",
    "HO6 insurance runs about $40 a month",
    "Condo insurance (HO6): $40 monthly",
    "Insurance - HO6 policy - $40 per month",
    "HO6 insurance required, $40 monthly",
    "- HO6 insurance $40 monthly\n- Pets ok",
])
def test_ho6_monthly_is_the_insurance(line):
    out = read(PMI_BASE.replace("Insurance $900/yr. ", "") + "PMI not required. " + line)
    assert out["insurance"] == 480
    assert "$40" not in notes(out).replace("$480", "") or "insurance" not in notes(out).lower().replace("mortgage insurance", "")
    place = {**out, "listing_text": line}
    cost = money.buy_cost(place)
    assert next(l for l in cost["lines"] if l["key"] == "insurance")["amount"] == 40
    assert not any("insurance" in m for m in cost["missing"])


def test_ho6_monthly_through_add_place_is_not_missing_or_doubled(store):
    r, place = mcp_add(store, "PMI not required. HO6 insurance $40 monthly.", insurance=None)
    assert place["insurance"] == 480
    assert "the $40 insurance in the listing notes" not in r and "missing: insurance" not in r


def test_a_yearly_figure_without_a_unit_stays_a_year_and_a_monthly_word_before_the_name_is_a_month():
    assert read(PMI_BASE.replace("Insurance $900/yr. ", "") + "Annual HO6 insurance: $480.")["insurance"] == 480
    assert read(PMI_BASE.replace("Insurance $900/yr. ", "") + "Monthly homeowner's insurance $150.")["insurance"] == 1800


@pytest.mark.parametrize("line", ["HO6 insurance optional $40 monthly.", "HO6 insurance not required, $40 monthly if you want it."])
def test_optional_ho6_is_not_the_insurance(line):
    assert read(PMI_BASE.replace("Insurance $900/yr. ", "") + line).get("insurance") in (None, "")


# ---- item 6 (buyer l43): "$1,200 first year of HOA reserve at closing" is cash to close, in buyer words
RES_BASE = "Condo $300,000\n2 bed 2 bath. HOA $100/mo. Taxes $3,000/yr. Insurance $900/yr. "


@pytest.mark.parametrize("line", [
    "Buyer pays $1,200 first year of HOA reserve at closing.",
    "$1,200 first year of HOA reserves due at closing.",
    "Buyer to pay first year of HOA reserve: $1,200 at closing.",
    "First year of HOA reserve: $1,200 (buyer, at closing)",
    "Buyer pays $1,200 for the first year of HOA reserve at closing",
    "- Buyer pays $1,200 first year of HOA reserve\n- Close in 30 days",
    "Buyer pays $1,200 first year of association reserve at closing | Quiet street",
])
def test_first_year_of_hoa_reserve_is_cash_to_close(line):
    out, _p, cash = full(RES_BASE + line)
    p = parts(cash)
    key = next((k for k in p if k.startswith("One-time fee at closing (first year of")), None)
    assert key and p[key] == 1200, p
    assert cash["total"] == 60000 + 9000 + 1200
    n = notes(out)
    assert "$1,200" in n and "counted in the cash to close as a one-time fee" in n
    assert "move-in" not in n and "taken off what you owe" not in n


def test_l43_whole_listing_first_year_reserve():
    text_ = fixture("r34-buyer-l43.txt")
    out, _p, cash = full(text_)
    assert parts(cash)["One-time fee at closing (first year of HOA reserve)"] == 1200
    assert "move-in" not in notes(out) and "taken off what you owe" not in notes(out)


@pytest.mark.parametrize("line", [
    "Seller pays $1,200 first year of HOA reserve at closing.",
    "HOA reserve $50/month.",
    "First year of HOA reserve $1,200 paid by the seller.",
])
def test_first_year_of_hoa_reserve_negatives(line):
    _o, _p, cash = full(RES_BASE + line)
    assert not any("first year of HOA reserve" in p["label"] for p in cash["parts"])


# ---- item 7 (buyer l43): the seller pays the first months of a monthly assessment, the buyer pays $400 a month after them
AS_BASE = "Condo $329,500\n1 bd 1 ba 980 sf. HOA $100/mo. Taxes $4,350/yr. HOI $55/mo. "


@pytest.mark.parametrize("line", [
    "Special assessment: $9,600 payable $400 monthly for 2 years, seller responsible for first 6 months.",
    "Special assessment $9,600, payable $400 a month over 24 months. Seller covers the first 6 months.",
    "Special assessment of $9,600 payable at $400/month for 24 months; the seller pays the first six months.",
    "Special assessment: $9,600 ($400 monthly for 2 years; first 6 months paid by the seller)",
    "- Special assessment: $9,600\n- Payable $400 monthly for 2 years\n- Seller responsible for first 6 months",
    "Special assessment | $9,600 payable $400 monthly for 24 months | seller is responsible for the first 6 months",
])
def test_seller_first_months_then_buyer_monthly(line):
    out, place, cash = full(AS_BASE + line)
    assert out["other_monthly_fees"] == 400
    assert out.get("special_assessment") in (None, "", 0) and out.get("special_assessment_payer") in (None, "")
    n = notes(out)
    assert "first 6 months" in n and "remaining 18 months" in n and "$7,200 in all" in n and "$400 a month" in n
    assert "not a cost to you" not in n and "the seller pays it" not in n and "Only $400" not in n and "not counted anywhere" not in n
    cost = money.buy_cost(place)
    other = next(l for l in cost["lines"] if l["key"] == "other")
    assert other["amount"] == 400 and "18 months" in other["note"]
    assert not any("assessment" in p["label"].lower() for p in cash["parts"])
    assert "special assessment" not in " ".join(cash["left_out"]).lower()


def test_l43_whole_listing_assessment():
    out = read(fixture("r34-buyer-l43.txt"))
    assert out["other_monthly_fees"] == 400 and out["hoa"] == 91.67 and out["property_tax"] == 4350 and out["insurance"] == 660 and out["seller_credit"] == 3295
    assert "remaining 18 months" in notes(out) and "Only $400 of that" not in notes(out)


def test_seller_first_months_shows_in_compare(store):
    cell, out = assessment_cell(store, fixture("r34-buyer-l43.txt"))
    assert cell["text"] == "$400 a month for 18 months (you pay it)" or "$400 a month for 18 months" in cell["text"]
    assert "not entered" not in cell["text"]


@pytest.mark.parametrize("line", [
    "Special assessment $9,600 payable $400 monthly for 2 years, seller responsible.",
    "Special assessment $9,600 payable $400 monthly for 2 years. Seller covers the first 6 months of HOA dues.",
    "Special assessment $9,600 payable $400 monthly for 2 years, paid by the seller.",
])
def test_seller_first_months_negatives_do_not_make_a_buyer_cost(line):
    out, _p, cash = full(AS_BASE + line)
    assert "remaining 18 months" not in notes(out)
    if "seller responsible." in line or "paid by the seller" in line:
        assert out.get("other_monthly_fees") in (None, "", 0)


# ---- item 8 (buyer l37, l40): a note never says "Ask who pays it" when the text names the buyer
@pytest.mark.parametrize("line,fees", [
    ("Special assessment: $150 per month through December 2028, buyer pays.", 150),
    ("Special assessment of $2,000 per quarter for 6 quarters, paid by buyer.", 666.67),
    ("Buyer pays the special assessment of $500 a month for 18 months.", 500),
    ("Special assessment $500/month for 18 months (buyer responsible)", 500),
    ("Special assessment: $500 monthly for 18 months. Paid by the buyer.", 500),
    ("- Special assessment $500 a month, 18 months\n- Buyer to pay", 500),
    ("Special assessment $9,000, buyer pays it over 36 months.", 250),
])
def test_assessment_note_does_not_ask_who_pays_when_the_buyer_is_named(line, fees):
    out = read("Condo $300,000\n2 bed 2 bath. HOA $200/mo. Taxes $3,000/yr. " + line)
    assert out["other_monthly_fees"] == fees
    n = notes(out)
    assert "who pays it" not in n.lower().replace("who pays it if you sell", "") and "ask who pays" not in n.lower()
    assert "the buyer pays it" in n or "that the buyer pays" in n


def test_reviewer_listings_l37_and_l40_do_not_ask_who_pays():
    for name in ("r34-buyer-l37.txt", "r34-buyer-l40.txt"):
        n = notes(read(fixture(name)))
        assert "ask who pays" not in n.lower() and "Ask who pays it" not in n, name


@pytest.mark.parametrize("line", [
    "Special assessment $500/month for 18 months.",
    "Special assessment: $150 per month through December 2028.",
    "Special assessment of $2,000 per quarter for 6 quarters.",
])
def test_assessment_note_still_asks_who_pays_when_no_payer_is_named(line):
    out = read("Condo $300,000\n2 bed 2 bath. HOA $200/mo. Taxes $3,000/yr. " + line)
    assert "who pays" in notes(out).lower()


# ---- item 9 (buyer T5, U4): "Seller pays $1,500 title policy" gets a "paid by the seller" note
SP_BASE = "Condo $300,000\n2 bed. HOA $200/mo. Taxes $3,000/yr. Insurance $900/yr. "


@pytest.mark.parametrize("line,named", [
    ("Seller pays $1,500 title policy.", "$1,500 title policy"),
    ("Title policy $1,500 paid by seller.", "$1,500 title policy"),
    ("The seller will pay the $1,500 title policy at closing.", "$1,500 title policy"),
    ("Seller to pay owner's title policy $1,500 and recording $120.", "$1,500 owner's title policy"),
    ("Closing: seller pays $1,500 title policy | Parking: street", "$1,500 title policy"),
    ("- Seller pays $1,500 title policy\n- Buyer pays own lender", "$1,500 title policy"),
    ("Seller pays $1,500 title policy, buyer pays $350 survey.", "$1,500 title policy"),
])
def test_seller_paid_closing_item_gets_a_paid_by_the_seller_note(line, named):
    out, _p, cash = full(SP_BASE + line)
    n = notes(out)
    assert f"the seller pays the {named}" in n and "paid by the seller" in n and "not a cost to you" in n
    assert "title policy" not in " ".join(p["label"] for p in cash["parts"])


def test_seller_paid_item_beside_a_buyer_item_keeps_the_buyer_item():
    out, _p, cash = full(SP_BASE + "Seller pays $1,500 title policy, buyer pays $350 survey.")
    label = " ".join(p["label"] for p in cash["parts"])
    assert "$350 for survey" in label and "1,500" not in label


@pytest.mark.parametrize("line", [
    "Buyer pays $1,500 title policy.",
    "Seller will credit $5,000 toward closing costs.",
    "Seller pays $7,000 toward closing costs.",
])
def test_seller_paid_note_negatives(line):
    out = read(SP_BASE + line)
    assert "the seller pays the" not in notes(out) or "toward" in line
    assert "$1,500 title policy. It is paid by the seller" not in notes(out)


# ---- item 10 (buyer): Today's closing target uses the search target until a place is in Closing
def _iso(n):
    from datetime import date, timedelta
    return (date.today() + timedelta(days=n)).isoformat()


def _buy_with_target(store, target):
    s = store.add_search("C", "buy", budget_max=400000, target_close=target)
    store.set_current_search(s["id"])
    return s


def _line_for(days):
    from prophelper import helpers
    return helpers.closing_info({"mode": "buy", "target_close": _iso(days)})["today_line"]


def _today_line(store):
    import re
    from conftest import local_client
    html = local_client(store).get("/today").text
    m = re.search(r'<p class="fine" id="closing-target">(.*?)</p>', html, re.S)
    return m.group(1) if m else None


@pytest.mark.parametrize("stage", ["Saved", "Toured", "Offer drafted", "Offer made", "Under contract", "Inspection"])
def test_a_place_before_closing_never_drives_the_countdown(store, stage):
    s = _buy_with_target(store, _iso(90))
    p, _ = store.add_place(title="Grandview", address="5 Oak St", price=300000, beds=2, search_id=s["id"])
    store.add_place_date(p["id"], "closing", _iso(87))
    for st_ in ("Toured", "Offer drafted", "Offer made", "Under contract", "Inspection"):
        if stage == "Saved":
            break
        store.move_stage(p["id"], st_)
        if st_ == stage:
            break
    line = _today_line(store)
    assert line == _line_for(90) and "(for" not in line and "in 87 days" not in line


def test_reviewer_case_saved_place_listing_date_vs_search_target(store):
    """Buyer: Saved place Grandview with a listing date of Feb 12 (87 days) beat the search target Feb 15."""
    s = _buy_with_target(store, _iso(90))
    p, _ = store.add_place(title="Grandview", address="5 Oak St", price=300000, beds=2, search_id=s["id"],
                           listing_text="Condo $300,000. 2 bed. Closing on or before February 12, 2027.")
    store.add_place_date(p["id"], "closing", _iso(87))
    assert _today_line(store) == _line_for(90)


def test_a_place_in_closing_still_wins_and_is_named(store):
    s = _buy_with_target(store, _iso(90))
    saved, _ = store.add_place(title="Grandview", address="5 Oak St", price=300000, beds=2, search_id=s["id"])
    store.add_place_date(saved["id"], "closing", _iso(87))
    p, _ = store.add_place(title="Victorian Village Condo", address="6 Oak St", price=300000, beds=2, search_id=s["id"])
    store.add_place_date(p["id"], "closing", _iso(104))
    for st_ in ("Toured", "Offer drafted", "Offer made", "Under contract", "Inspection", "Closing"):
        store.move_stage(p["id"], st_)
    assert _today_line(store) == _line_for(104) + " (for Victorian Village Condo)"


def test_no_target_and_no_place_in_closing_shows_no_line(store):
    s = store.add_search("C", "buy", budget_max=400000)
    store.set_current_search(s["id"])
    p, _ = store.add_place(title="Grandview", address="5 Oak St", price=300000, beds=2, search_id=s["id"])
    store.add_place_date(p["id"], "closing", _iso(87))
    assert _today_line(store) is None


# ---- reviewer listings pasted through add_place: every note agrees with the saved fields (rule y)
@pytest.mark.parametrize("name", ["l37", "l40", "l42", "l43"])
def test_reviewer_listings_through_add_place_notes_agree_with_fields(store, name):
    from mcp_util import call, server, text as mtext
    s = store.add_search("Buy", "buy")
    r = mtext(call(server(store), "add_place", title="T", address="9 Test St", search_id=s["id"], listing_text=fixture(f"r34-buyer-{name}.txt")))
    place = store.list_places(search_id=s["id"])[0]
    saved = place["reader_notes"]
    assert "Ask who pays it" not in saved and "ask who pays" not in saved.lower()
    assert "not counted anywhere" not in saved.lower().replace("it is a percent, so no dollar amount is saved and it is not counted anywhere", "")
    if name == "l43":
        assert place["other_monthly_fees"] == 400 and "remaining 18 months" in saved
        assert "first year of HOA reserve" in saved
    if name == "l42":
        assert "(PMI) is set to $0 a month" in saved and place["seller_credit"] == 8250
    if name in ("l37", "l40"):
        assert "The listing says the buyer pays it." in saved
