"""Cycle 11, group 4: the buyer side. A buy search never reads a sale as a rental, money that is not counted is not
claimed as filled in, and the buyer facts that were silent are read or noted."""
import pytest
from mcp_util import call, server, text

from conftest import local_client
from prophelper import money, redflags
from prophelper.parsers import parse_listing


def notes(r):
    return r.get("found_in_listing", "")


GERMAN = ("German Village townhome, 3 bed 2 bath. Taxes $4,600/yr. Move-in fee $1,200. "
          "Required deeded parking $120/mo. Monthly cost about $1,988.")


def test_buy_search_fills_tax_and_never_says_rental():
    r = parse_listing(GERMAN, buying=True)
    assert r["property_tax"] == 4600
    assert "rental" not in notes(r) and "free-rent" not in notes(r)
    assert "price" not in r  # $1,988 is a monthly amount, not an asking price


def test_rent_search_still_reads_the_tax_line_as_a_rental():
    r = parse_listing(GERMAN)
    assert "property_tax" not in r and "looks like a rental" in notes(r)


def test_buy_parking_and_move_in_fee_are_notes_not_fields():
    r = parse_listing(GERMAN, buying=True)
    assert "parking_cost" not in r and "move_in_fees" not in r
    n = notes(r)
    assert "$120/month" in n and "$1,200 move-in fee" in n and "not counted anywhere" in n


def test_seller_concession_is_not_free_rent():
    t = "Brewery condo $340,000 for sale. Seller is offering a concession of up to 3% toward buyer closing costs."
    r = parse_listing(t, buying=True)
    assert "free-rent" not in notes(r) and "seller_credit" not in r
    assert "seller concessions of up to 3%" in notes(r)
    r2 = parse_listing("Condo $340,000 for sale. Seller concession of $8,000.", buying=True)
    assert r2["seller_credit"] == 8000 and "free-rent" not in notes(r2)


def test_assessment_payable_by_seller():
    r = parse_listing("Condo $340,000. Special assessment of $6,000 payable by seller at closing.", buying=True)
    assert r["special_assessment"] == 6000 and r["special_assessment_payer"] == "seller"
    assert "doesn't say who pays" not in notes(r)


def test_monthly_dues_is_hoa():
    r = parse_listing("Condo $340,000. Monthly dues $450 (includes heat and water)", buying=True)
    assert r["hoa"] == 450


def test_closing_cost_credit_from_seller():
    r = parse_listing("Condo $340,000. Closing cost credit of $6,000 from seller with accepted offer", buying=True)
    assert r["seller_credit"] == 6000


def test_brokerage_percent_and_transfer_fee_get_notes():
    r = parse_listing("Condo $340,000. Brokerage fee 1% paid by buyer. $450 transfer fee.", buying=True)
    n = notes(r)
    assert "brokerage fee of 1%, paid by the buyer" in n and "no amount is saved" in n.lower()
    assert "$450 transfer fee" in n


@pytest.mark.parametrize("phrase,days", [("12 DOM", 12), ("DOM 8", 8), ("DOM: 30", 30)])
def test_dom_is_days_on_market(phrase, days):
    assert parse_listing(f"Condo $340,000. {phrase}", buying=True)["days_on_market"] == days


def test_cash_to_close_says_unknown_payer_assessment_is_left_out():
    cash = money.cash_to_close({"price": 340000, "special_assessment": 6000})
    assert cash["left_out"] == ["a $6,000 special assessment isn't counted because who pays it isn't known"]
    assert money.cash_to_close({"price": 340000, "special_assessment": 6000, "special_assessment_payer": "seller"})["left_out"] == []
    assert money.cash_to_close({"price": 340000, "special_assessment": 6000, "special_assessment_payer": "buyer"})["left_out"] == []


def test_place_page_and_mcp_show_the_left_out_line(store):
    s = store.add_search("Buy", "buy")
    p, _ = store.add_place(by="you", search_id=s["id"], title="Condo", price=340000, special_assessment=6000)
    html = local_client(store).get(f"/places/{p['id']}").text
    assert "isn&#39;t counted because who pays it isn&#39;t known" in html or "isn't counted because who pays it isn't known" in html
    out = text(call(server(store), "get_place", place_id=p["id"]))
    assert "Left out: a $6,000 special assessment isn't counted because who pays it isn't known." in out


def test_skip_inspection_hint():
    for phrase in ("Do not do a home inspection", "Don't get an inspection", "Inspection waived please"):
        flags = redflags.local_flags({"listing_text": phrase}, mode="buy")
        assert any("skip or waive the inspection" in f for f in flags), phrase


def test_add_preview_shows_hoa_and_tax_once(store):
    store.add_search("Buy", "buy")
    r = local_client(store).post("/add/parse", data={"text": "Condo $340,000. HOA $300/mo. Taxes $4,600/yr", "url": ""})
    assert r.text.count('name="hoa"') == 1 and r.text.count('name="property_tax"') == 1 and r.text.count('name="insurance"') == 1


def test_mcp_add_place_in_buy_search_does_not_claim_parking_or_move_in(store):
    s = store.add_search("Buy", "buy")
    out = text(call(server(store), "add_place", title="GV", search_id=s["id"], listing_text="3 bed home for sale $425,000. Taxes $4,600/yr. Move-in fee $1,200. Required deeded parking $120/mo."))
    filled = next(l for l in out.splitlines() if "filled in:" in l)
    assert "parking cost" not in filled and "move in fees" not in filled and "property tax" in filled
    assert "$120/month" in out and "$1,200 move-in fee" in out  # said as notes instead
    got = text(call(server(store), "get_place", place_id=1))
    assert "$4,600" in got
