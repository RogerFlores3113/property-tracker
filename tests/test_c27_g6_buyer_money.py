"""Cycle 27 G6: buyer credits, seller-paid fees and assessment payers, and the place's own closing date."""
import re
import pytest
from prophelper import money
from prophelper.parsers import parse_listing

BASE = "Condo $300,000\n2 bed 2 bath. Buyer closing costs about $8,000. "


def read(extra, base=BASE):
    text = base + extra
    out = parse_listing(text, buying=True)
    place = {**out, "listing_text": text}
    return out, money.cash_to_close(place), text


def labels(cash):
    return {p["label"]: p["amount"] for p in cash["parts"]}


@pytest.mark.parametrize("line", [
    "Lender credit of $2,000 applied at closing",
    "Lender credit: $2,000.",
    "$2,000 lender credit at closing",
    "- Credit at closing: $2,000",
    "Closing credit of $2,000",
    "The lender is giving a $2,000 credit at closing",
    "A $2,000 credit applied at closing",
])
def test_lender_and_closing_credits_lower_cash(line):
    out, cash, _ = read(line)
    parts = labels(cash)
    assert cash["total"] == 60000 + 8000 - 2000
    assert sum(1 for a in parts.values() if a == -2000) == 1
    notes = out["found_in_listing"]
    assert "one-time cost" not in notes and "not counted anywhere" not in notes


def test_credit_cap_with_seller_credit_and_no_double_count():
    out, cash, _ = read("Seller will pay $5,000 toward closing costs. Lender credit of $4,000 applied at closing.")
    assert cash["total"] == 60000  # credits capped at the $8,000 closing costs
    assert sum(a for a in labels(cash).values() if a < 0) == -8000
    assert any("$1,000 of the $9,000" in w for w in cash["left_out"])
    out, cash, _ = read("Seller closing credit $3,000 at closing.")
    assert cash["total"] == 60000 + 8000 - 3000  # one seller credit, not read twice


def test_credit_bigger_than_closing_costs_never_below_down_payment():
    _, cash, _ = read("Lender credit of $20,000 applied at closing")
    assert cash["total"] == 60000
    assert cash["left_out"]


@pytest.mark.parametrize("line", ["Lender may offer a credit of up to $2,000 at closing", "Credit at closing available $2,000", "Credit check required at closing, fee $45"])
def test_offers_and_credit_checks_are_not_credits(line):
    _, cash, _ = read(line)
    assert cash["total"] == 68000


@pytest.mark.parametrize("line", [
    "Transfer fee $350 paid by seller.",
    "Seller pays the $350 transfer fee.",
    "Transfer fee: $350 (seller's cost).",
    "Transfer fee $350, seller will pay.",
    "- Transfer fee $350\n- Paid in full by the seller",
])
def test_seller_paid_transfer_fee(line):
    out, cash, _ = read(line)
    assert cash["total"] == 68000
    notes = out["found_in_listing"]
    assert "ask" not in notes.lower().split("transfer fee")[-1][:120] or "who pays it" not in notes
    assert "seller pays the $350 transfer fee" in notes
    assert "who pays it" not in notes


@pytest.mark.parametrize("line", ["Reserve fund contribution $900 paid by seller.", "Seller pays the $900 reserve fund contribution.", "$900 reserve fund contribution (seller's cost)."])
def test_seller_paid_one_time_fee_note(line):
    out, cash, _ = read(line)
    assert cash["total"] == 68000
    assert "the seller pays the $900 reserve fund contribution" in out["found_in_listing"]


def test_buyer_paid_fee_still_counted():
    out, cash, _ = read("Buyer pays $900 reserve fund contribution at closing.")
    assert cash["total"] == 68900


@pytest.mark.parametrize("line", [
    "New roof assessment of $6,000 split between owners, seller is paying it in full.",
    "Special assessment $6,000, seller will pay it.",
    "Assessment of $6,000: paid in full by seller.",
    "Roof assessment $6,000 - seller covering it.",
    "Roof assessment $6,000. Seller is paying it in full.",
])
def test_assessment_seller_paying_wordings(line):
    out, cash, _ = read(line)
    assert out.get("special_assessment") == 6000 and out.get("special_assessment_payer") == "seller"
    assert cash["total"] == 68000
    assert not cash["left_out"]


@pytest.mark.parametrize("line", [
    "Special assessment of $6,000, buyer is paying it in full at closing.",
    "Roof assessment $6,000 - buyer covering it at closing.",
])
def test_assessment_buyer_paying_wordings(line):
    out, cash, _ = read(line)
    assert out.get("special_assessment_payer") == "buyer"
    assert cash["total"] == 74000


@pytest.mark.parametrize("line", ["Special assessment $6,000, split between buyer and seller.", "Special assessment $6,000, seller or buyer to be negotiated."])
def test_assessment_split_parties_stay_unknown(line):
    out, cash, _ = read(line)
    assert not out.get("special_assessment_payer")
    assert cash["total"] == 68000 and cash["left_out"]


# ---- the place's own closing date beats the search target
from datetime import date, timedelta
from conftest import local_client


def _buy_place(store, target, stage=None):
    s = store.add_search("Buy", "buy", target_close=target or "")
    store.set_current_search(s["id"])
    p, _ = store.add_place(search_id=s["id"], title="House", price=400000, **({"stage": stage} if stage else {}))
    return s, p


def _closing_lines(html):
    return re.findall(r"Closing[^<]*?\(\w{3} \d+, \d{4}\)", html)


def test_place_closing_date_replaces_search_target(store):
    c = local_client(store)
    target = date.today() + timedelta(days=90)
    own = date.today() + timedelta(days=87)
    _s, p = _buy_place(store, target.isoformat())
    store.add_place_date(p["id"], "closing", own.isoformat())
    html = c.get(f"/places/{p['id']}").text
    assert re.search(r'<p id="closing-days"[^>]*>Closing in 87 days', html)
    assert "Closing in 90 days" not in html
    assert len(re.findall(r'id="closing-days"', html)) == 1


def test_place_closing_date_without_search_target_and_past_and_prominent(store):
    c = local_client(store)
    _s, p = _buy_place(store, "")
    store.add_place_date(p["id"], "closing", (date.today() + timedelta(days=12)).isoformat())
    assert "Closing in 12 days" in c.get(f"/places/{p['id']}").text
    _s2, q = _buy_place(store, (date.today() + timedelta(days=90)).isoformat(), stage="Offer made")
    store.add_place_date(q["id"], "closing", (date.today() + timedelta(days=40)).isoformat())
    html = c.get(f"/places/{q['id']}").text
    assert re.search(r'<p id="closing-days" class="flash"><strong>Closing in 40 days', html)
    _s3, r = _buy_place(store, (date.today() + timedelta(days=90)).isoformat())
    store.add_place_date(r["id"], "closing", (date.today() - timedelta(days=3)).isoformat())
    assert "Closing was 3 days ago" in c.get(f"/places/{r['id']}").text


def test_place_without_own_closing_date_keeps_search_target(store):
    c = local_client(store)
    _s, p = _buy_place(store, (date.today() + timedelta(days=30)).isoformat())
    store.add_place_date(p["id"], "inspection", (date.today() + timedelta(days=5)).isoformat())
    assert "Closing in 30 days" in c.get(f"/places/{p['id']}").text
