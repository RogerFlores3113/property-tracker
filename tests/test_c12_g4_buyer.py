"""Cycle 12 G4: buyer reader. Asking price, seller caps, assessment payers, parking wording, commission, days ago."""
import pytest

from prophelper import parsers


def B(text, **kw):
    return parsers.parse_listing(text, buying=True, **kw)


@pytest.mark.parametrize("text,price", [
    ("Test - $318,000 / 10 Buttles Ave Apt 4, Columbus, OH 43215 / 2 bed 1 bath. / $450 transfer fee.", 318000),
    ("Clintonville Brick 2BR $299,900\nProperty taxes $3,100 per year ($258/mo)", 299900),
    ("Great condo listed at $329,000 near campus. 2 bed. rent $1,650/month tenant-occupied", 329000),
    ("Condo $300,000\nHOA $450 monthly\nSeller credit $5,000", 300000),
])
def test_asking_price_survives_a_nearby_small_amount(text, price):
    got = B(text)
    assert got["price"] == price
    assert "monthly amount" not in got.get("found_in_listing", "")


def test_monthly_note_only_when_no_price_found():
    got = B("Lovely place, monthly cost about $1,988")
    assert "price" not in got and "looks like a monthly amount" in got["found_in_listing"]


def test_no_monthly_note_when_price_was_passed():
    got = parsers.parse_listing("Lovely place, monthly cost about $1,988", buying=True, current={"price": 299900})
    assert "monthly amount" not in got.get("found_in_listing", "")


def test_seller_up_to_is_not_closing_costs_or_credit():
    got = B("Condo $300,000\nSeller will pay up to $8,000 in closing costs")
    assert got["price"] == 300000 and "closing_costs" not in got and "seller_credit" not in got
    assert "limit, not a promise" in got["found_in_listing"]


def test_seller_pays_up_to_percent_gets_one_note():
    got = B("Condo $300,000\nSeller pays closing costs up to 3% ($8,685)")
    assert "seller_credit" not in got and "closing_costs" not in got
    assert got["found_in_listing"].count("8,685") == 1 and "Check what it is for" not in got["found_in_listing"]


@pytest.mark.parametrize("phrase,payer", [("buyer responsibility", "buyer"), ("paid by owner", "seller"), ("owner pays", "seller"), ("buyer to pay", "buyer")])
def test_assessment_payer_words(phrase, payer):
    got = B(f"Condo $300,000\nSpecial assessment $2,000 {phrase}")
    assert got["special_assessment"] == 2000 and got["special_assessment_payer"] == payer
    assert "doesn't say who pays" not in got.get("found_in_listing", "")


def test_annual_assessment_for_years_is_not_one_time():
    got = B("Condo $300,000\nAnnual assessment $1,200 for 3 years")
    assert "special_assessment" not in got
    assert "$3,600 in all" in got["found_in_listing"]


def test_assessments_none_sets_zero():
    assert B("Condo $300,000\nAssessments: none")["special_assessment"] == 0


def test_required_parking_note_says_required_not_counted():
    note = B("Condo $300,000\nParking $120/month required")["found_in_listing"]
    assert "required but not counted" in note and "budget" in note and "whether it is required" not in note
    assert "parking_cost" not in B("Condo $300,000\nParking $120/month required")


def test_buyer_agent_commission_note_and_days_ago():
    got = B("Condo $300,000\nBuyer agent commission 2.5%\nListed 45 days ago")
    assert "buyer agent commission of 2.5%" in got["found_in_listing"]
    assert got["days_on_market"] == 45 and got["price"] == 300000


def test_update_place_and_form_say_buy_cost_ignores_parking(store, client):
    from mcp_util import call, server, text
    srv = server(store)
    call(srv, "create_search", name="Buy", mode="buy")
    r = call(srv, "add_place", title="Oak", price=300000, address="1 Oak St")
    pid = store.list_places()[0]["id"] if hasattr(store, "list_places") else 1
    out = text(call(srv, "update_place", place_id=pid, parking_cost=120, move_in_fees=1200))
    assert "does not use parking cost or move-in fees" in out and "not counted" in out
    resp = client.post(f"/places/{pid}", data={"title": "Oak", "parking_cost": "150"}, follow_redirects=True)
    assert "does not use parking cost" in resp.text


def test_add_place_with_price_passed_has_no_monthly_note(store):
    from mcp_util import call, server, text
    srv = server(store)
    call(srv, "create_search", name="Buy", mode="buy")
    call(srv, "add_place", title="Oak", price=299900, listing_text="Cozy home, monthly cost about $1,988")
    assert "monthly amount" not in (store.list_places()[0].get("reader_notes") or "")
