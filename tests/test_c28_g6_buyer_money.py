"""Cycle 28 G6: fees stated as months of HOA, stated closing items beside the closing guess, insurance-only places on Today,
the place's own closing date, an HOA stated after a question mark, and a percent-of-loan lender credit."""
import os
import re
from datetime import date, timedelta

import pytest

from conftest import local_client
from mcp_util import call, server, text
from prophelper import enrich, money, today
from prophelper.parsers import parse_listing

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "panel")
BASE = "Condo $300,000\n2 bed 2 bath. HOA $460/mo. Buyer closing costs about $8,000. "


def fixture(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


def read(text_, **extra):
    out = parse_listing(text_, buying=True)
    place = {**out, "listing_text": text_, **extra}
    return out, money.cash_to_close(place), place


def labels(cash):
    return {p["label"]: p["amount"] for p in cash["parts"]}


# ---- item 1: a fee stated as months of HOA
@pytest.mark.parametrize("line,months", [
    ("Buyer pays a capital improvement fee equal to two months of HOA.", 2),
    ("Buyer pays 2x monthly dues as a capital contribution at closing.", 2),
    ("Working capital contribution of 2 months' assessments due at closing.", 2),
    ("- Capital improvement fee: 1.5 months of HOA dues at closing", 1.5),
    ("Two months of HOA as a capital improvement fee, paid by buyer.", 2),
])
def test_fee_in_months_of_hoa_is_counted(line, months):
    out, cash, _ = read(BASE + line)
    assert out["hoa"] == 460
    fee = [a for l, a in labels(cash).items() if "months of HOA" in l]
    assert fee == [460 * months]
    assert cash["total"] == 60000 + 8000 + 460 * months
    assert "not counted anywhere" not in out.get("found_in_listing", "")


def test_fee_in_months_of_hoa_reviewer_listing():
    t = fixture("r27-buyer-l10.txt")
    out, cash, _ = read(t)
    assert out["hoa"] == 460
    assert 920 in labels(cash).values() and 500 in labels(cash).values()
    assert "equal to 2 months of HOA" in out["found_in_listing"]
    assert not cash["left_out"]


def test_fee_in_months_of_hoa_unknown_hoa_is_named():
    t = "Condo $300,000\n2 bed 2 bath. Buyer closing costs about $8,000. Buyer pays a capital improvement fee equal to two months of HOA."
    out, cash, _ = read(t)
    assert "hoa" not in out or out["hoa"] in (None, "")
    assert cash["total"] == 68000
    assert any("capital improvement fee" in w and "HOA isn't known" in w for w in cash["left_out"])
    assert "capital improvement fee equal to 2 months of HOA" in out["found_in_listing"]


def test_fee_in_months_of_hoa_seller_pays_and_no_payer():
    out, cash, _ = read(BASE + "Seller pays a capital improvement fee equal to two months of HOA.")
    assert cash["total"] == 68000 and not cash["left_out"]
    out, cash, _ = read(BASE + "Capital improvement fee: two months of HOA.")
    assert cash["total"] == 68000
    assert any("who pays it isn't known" in w for w in cash["left_out"])


# ---- item 2: stated closing items never added on top of the guess
GUESS = "Condo $300,000\n2 bed 2 bath. HOA $300/mo. "


@pytest.mark.parametrize("line", [
    "Buyer pays title and recording about $1,900.",
    "Buyer pays title and recording: approx $1,900",
    "- Buyer to pay title and recording fees about $1,900",
])
def test_stated_title_items_are_inside_the_guess(line):
    out, cash, _ = read(GUESS + line)
    parts = labels(cash)
    assert cash["total"] == 60000 + 9000  # the 3 percent guess only, the $1,900 is not added
    guess = [l for l in parts if l.startswith("Closing costs")]
    assert len(guess) == 1 and "includes the $1,900 for title and recording" in guess[0]
    assert cash["has_estimate"]
    assert "closing_costs" not in out
    assert "not added on top" in out["found_in_listing"]


def test_stated_title_items_reviewer_listing():
    t = fixture("r27-buyer-l8.txt")
    out, cash, _ = read(t)
    assert cash["total"] == 52400 + 7860 - 4500
    assert "title and recording about $1,900" in out["found_in_listing"] and "not counted anywhere" not in out["found_in_listing"]


def test_stated_items_bigger_than_the_guess_are_counted_alone():
    t = "Condo $100,000\n2 bed. HOA $100/mo. Buyer pays title and recording about $4,000."
    out, cash, _ = read(t)
    assert cash["total"] == 20000 + 4000
    assert any("only what the listing names" in l for l in labels(cash))


def test_seller_items_and_stated_closing_costs_unchanged():
    out, cash, _ = read(GUESS + "Seller pays title and recording about $1,900.")
    assert cash["total"] == 69000 - 0 and "includes" not in " ".join(labels(cash))
    out, cash, _ = read(GUESS + "Buyer closing costs about $8,000. Buyer pays title and recording about $1,900.")
    assert out["closing_costs"] == 8000 and cash["total"] == 68000


# ---- item 3: Today lists a place whose only unknown part is insurance
def _buy(store, **fields):
    s = store.add_search("B", "buy")
    store.add_criterion(s["id"], "price", weight=50, dealbreaker=False, target={"max": 400000})
    store.add_place(title="Condo", address="1 A St", price=250000, beds=2, **fields)
    return s


def _rows(store, s):
    return enrich.enrich_places(store, store.get_search(s["id"]))


def test_insurance_only_place_is_a_best_fit_marked_not_complete(store):
    s = _buy(store, property_tax=3000, hoa=100)
    rows = _rows(store, s)
    top = today.best_fits(rows)
    assert [p["title"] for p in top] == ["Condo"]
    assert "insurance not filled in yet" in top[0]["caution"] and "not complete" in top[0]["caution"]
    assert today.cost_check(rows) == []
    out = text(call(server(store), "todays_list"))
    assert "Best fits right now:" in out and "insurance not filled in yet" in out and "Needs a cost check" not in out
    html = local_client(store).get("/today").text
    assert "insurance not filled in yet" in html and "not complete" in html


def test_complete_place_ranks_before_insurance_only_place(store):
    s = _buy(store, property_tax=3000, hoa=100)
    store.add_place(title="Complete", address="2 A St", price=250000, beds=2, property_tax=3000, insurance=900, hoa=100)
    top = today.best_fits(_rows(store, s))
    assert [p["title"] for p in top] == ["Complete", "Condo"]
    assert top[0]["caution"] == "" or "insurance" not in top[0]["caution"]


@pytest.mark.parametrize("fields", [{"hoa": 100}, {"property_tax": 3000}, {}])
def test_two_unknown_parts_still_need_a_cost_check(store, fields):
    s = _buy(store, **fields)
    rows = _rows(store, s)
    assert today.best_fits(rows) == []
    assert [c["place"]["title"] for c in today.cost_check(rows)] == ["Condo"]


# ---- item 4: the place's own closing date, entered on the page
def test_closing_date_entered_on_the_page_replaces_the_target(store):
    c = local_client(store)
    s = store.add_search("Buy", "buy", target_close=(date.today() + timedelta(days=90)).isoformat())
    store.set_current_search(s["id"])
    p, _ = store.add_place(search_id=s["id"], title="House", price=400000)
    own = date.today() + timedelta(days=87)
    r = c.post(f"/places/{p['id']}/dates", data={"kind": "closing", "day": own.isoformat()}, follow_redirects=True)
    assert r.status_code == 200
    html = c.get(f"/places/{p['id']}").text
    assert re.search(r'<p id="closing-days"[^>]*>Closing in 87 days', html)
    assert "Closing in 90 days" not in html and "in 90 days" not in html
    assert len(re.findall(r'id="closing-days"', html)) == 1


# ---- item 5: an HOA stated after a question mark
@pytest.mark.parametrize("line,hoa", [
    ("Condo fee $0.37/sf? no - fee is $425 per month.", 425),
    ("HOA $0.40/sqft? No, the HOA fee is $380 a month.", 380),
    ("- Dues $0.35 per sf?\n- No: dues are $410/mo", 410),
    ("HOA: $0.37/sf? no, fee is $4,800 per year", 400),
])
def test_hoa_after_a_question_mark(line, hoa):
    out, cash, _ = read("Condo $300,000\n2 bed 2 bath. " + line)
    assert out["hoa"] == hoa
    assert "not counted anywhere" not in out["found_in_listing"]
    assert "monthly cost low" not in out["found_in_listing"]


def test_hoa_after_a_question_mark_reviewer_listing():
    out = parse_listing(fixture("r27-buyer-l4.txt"), buying=True)
    assert out["hoa"] == 425 and out["closing_costs"] == 8300


@pytest.mark.parametrize("line", ["HOA $0.37/sf.", "Condo fee $0.37/sf? Not sure."])
def test_price_per_square_foot_is_never_a_zero_hoa(line):
    out = parse_listing("Condo $300,000\n2 bed 2 bath. " + line, buying=True)
    assert out.get("hoa") in (None, "")


# ---- item 6: a lender credit stated as a percent of the loan stays uncounted, with a note
@pytest.mark.parametrize("line", [
    "Lender credit up to 1% of loan applied at closing.",
    "Lender credit of up to 1% of the loan amount at closing.",
    "- Lender credit: up to 1% of loan",
])
def test_lender_credit_percent_of_loan_not_counted(line):
    out, cash, _ = read(BASE + line)
    assert cash["total"] == 60000 + 8000
    assert not any("credit" in l.lower() for l in labels(cash))
    note = out["found_in_listing"]
    assert "1% of" in note and "not counted anywhere" in note


def test_lender_credit_percent_reviewer_listing():
    t = fixture("r27-buyer-l11.txt")
    out, cash, _ = read(t)
    assert not any("credit" in l.lower() for l in labels(cash))
    assert "Lender credit up to 1% of loan" in out["found_in_listing"]
