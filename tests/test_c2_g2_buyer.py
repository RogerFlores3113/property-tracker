"""Cycle 2, fixer G2: the buyer side (mode-aware forms, one-time costs, listing reader, AI wording)."""
import re

import pytest
from conftest import local_client

from prophelper import ai, money, parsers

REDFIN = """Redfin
88 Beck Row, Columbus, OH 43206
$349,000
3 beds 2 baths 1,650 sq ft
Est. payment $2,310/mo
41 days on Redfin
Special assessment $4,800, paid by seller at closing.
HOA dues $210/mo. Property tax $4,200/yr. Homeowners insurance est $1,100/yr
Listed by Jane Q. Agent, Example Realty
"""
ZILLOW = """Brick townhome near the park
88 Beck Row
Columbus, OH 43206
$349,000
3 bd 2 ba 1,650 sqft
Estimated monthly payment: $2,310
41 days on Zillow
Listing agent: Jane Q. Agent • Example Realty (555) 010-0199
Special assessment: $150/month until 2029, buyer pays
"""


def _names(html: str) -> set[str]:
    return set(re.findall(r'<(?:input|select|textarea)[^>]*\bname="(\w+)"', html))


def _visible(html: str) -> set[str]:
    return set(re.findall(r'<(?:input(?![^>]*type="hidden")|select|textarea)[^>]*\bname="(\w+)"', html))


BUYER_ONLY = {"hoa", "property_tax", "insurance", "days_on_market", "special_assessment", "special_assessment_payer",
              "closing_costs", "listing_agent"}
RENTER_ONLY = {"lease_start", "lease_end", "lease_months", "deposit", "application_fee", "pet_rent", "utilities_included"}


@pytest.fixture
def buy_place(store):
    s = store.add_search("Columbus buy", "buy")
    p, _ = store.add_place(search_id=s["id"], title="88 Beck Row", address="88 Beck Row", price=349000, beds=3, baths=2,
                           hoa=210, property_tax=4200, insurance=1100)
    return s, p


# ---------------------------------------------------------------- parser
def test_redfin_address_line_fills_address_city_state_zip():
    got = parsers.parse_listing(REDFIN)
    assert (got["address"], got["city"], got["state"], got["zip"]) == ("88 Beck Row", "Columbus", "OH", "43206")
    assert "Columbus" not in got["title"] and "43206" not in got["title"]
    got2 = parsers.parse_listing("Open house Sunday\n88 Beck Row, Columbus, OH 43206\n$349,000\n3 bd 2 ba")
    assert got2["address"] == "88 Beck Row" and got2["zip"] == "43206" and "43206" not in got2["title"]


def test_buyer_facts_are_read_from_realistic_text():
    got = parsers.parse_listing(REDFIN)
    assert got["days_on_market"] == 41
    assert got["special_assessment"] == 4800 and got["special_assessment_payer"] == "seller"
    assert got["listing_agent"] == "Jane Q. Agent, Example Realty"
    assert "$2,310/mo" in got["found_in_listing"]
    z = parsers.parse_listing(ZILLOW)
    assert z["days_on_market"] == 41 and z["listing_agent"] == "Jane Q. Agent, Example Realty"
    assert "special_assessment" not in z  # a monthly amount is not a one-time assessment
    assert parsers.listing_estimated_payment(ZILLOW) == 2310


def test_no_special_assessment_and_owner_listings_leave_fields_out():
    got = parsers.parse_listing("$1,495/mo 2 beds\nNo special assessments.\nListed by owner\n12 days on Zillow")
    assert "special_assessment" not in got and "listing_agent" not in got
    assert parsers.parse_listing("Row of shops\n$900 deposit")  # does not raise


# ---------------------------------------------------------------- store
def test_new_columns_are_saved_and_payer_is_checked(store, buy_place):
    _, p = buy_place
    out = store.update_place(p["id"], by="you", days_on_market="41", special_assessment="4800",
                             special_assessment_payer="Seller", closing_costs="9000", listing_agent="Jane, Example Realty")
    assert out["days_on_market"] == 41 and out["special_assessment"] == 4800 and out["special_assessment_payer"] == "seller"
    assert out["closing_costs"] == 9000 and out["listing_agent"] == "Jane, Example Realty"
    with pytest.raises(ValueError):
        store.update_place(p["id"], by="you", special_assessment_payer="the neighbor")
    with pytest.raises(ValueError):
        store.update_place(p["id"], by="you", special_assessment="-5")


# ---------------------------------------------------------------- cash to close
def test_cash_to_close_estimates_closing_costs_and_counts_a_buyer_assessment():
    base = {"price": 400000}
    c = money.buy_cost(base)["cash_to_close"]
    assert c["total"] == 80000 + 12000 and c["has_estimate"] and "guess" in c["parts"][1]["label"]
    entered = money.buy_cost({**base, "closing_costs": 9000})["cash_to_close"]
    assert entered["total"] == 89000 and not entered["has_estimate"]
    buyer = money.buy_cost({**base, "closing_costs": 9000, "special_assessment": 4800, "special_assessment_payer": "buyer"})
    assert buyer["cash_to_close"]["total"] == 93800
    seller = money.buy_cost({**base, "closing_costs": 9000, "special_assessment": 4800, "special_assessment_payer": "seller"})
    assert seller["cash_to_close"]["total"] == 89000
    unknown = money.buy_cost({**base, "closing_costs": 9000, "special_assessment": 4800})
    assert unknown["cash_to_close"]["total"] == 89000 and any("who pays" in n for n in unknown["notes"])
    assert buyer["total"] == money.buy_cost({**base, "closing_costs": 9000})["total"]  # one-time, not monthly
    assert money.buy_cost({})["cash_to_close"] is None


def test_closing_cost_percent_comes_from_settings():
    cfg = money.buy_settings({"closing_cost_pct": "2"})
    assert money.buy_cost({"price": 400000}, {"closing_cost_pct": "2"})["cash_to_close"]["parts"][1]["amount"] == 8000
    assert cfg["closing_cost_pct"] == 2


def test_listing_estimate_note_compares_with_ours():
    place = {"price": 349000, "hoa": 210, "property_tax": 4200, "insurance": 1100, "listing_text": REDFIN}
    cost = money.buy_cost(place)
    note = cost["listing_estimate_note"]
    assert note.startswith("The listing estimates $2,310/mo; ours is $")
    assert "PMI" not in note and "HOA" in note and "property tax" in note
    assert money.buy_cost({"price": 349000})["listing_estimate_note"] == ""


# ---------------------------------------------------------------- the place page
def test_buy_place_page_shows_buyer_fields_and_cash_to_close(store, buy_place):
    _, p = buy_place
    store.update_place(p["id"], by="you", listing_text=REDFIN, closing_costs=9000)
    c = local_client(store)
    html = c.get(f"/places/{p['id']}").text
    facts = html.split('id="facts"')[1].split("</form>")[0]
    names = _names(facts)
    assert BUYER_ONLY <= names
    assert not (RENTER_ONLY & names)
    assert "Cash needed to close" in html and "Down payment" in html
    assert 'id="listing-estimate"' in html and "The listing estimates $2,310/mo" in html


def test_rent_place_page_hides_buyer_fields(store):
    s = store.add_search("Rent", "rent")
    p, _ = store.add_place(search_id=s["id"], title="A", address="1 Main St", price=1500)
    html = local_client(store).get(f"/places/{p['id']}").text
    names = _names(html.split('id="facts"')[1].split("</form>")[0])
    assert RENTER_ONLY <= names
    assert not (BUYER_ONLY & names)
    assert "Cash needed at move-in" in html and "Cash needed to close" not in html


def test_hidden_fields_keep_their_values_on_save(store, buy_place):
    s, p = buy_place
    store.update_place(p["id"], by="you", deposit=1500, lease_months=12, pet_rent=25)
    c = local_client(store)
    html = c.get(f"/places/{p['id']}").text
    form = {n: ("" if v == "None" else v) for n, v in re.findall(r'<input[^>]*name="(\w+)"[^>]*value="([^"]*)"', html.split('id="facts"')[1].split("</form>")[0])}
    form["listing_agent"] = "Jane, Example Realty"
    r = c.post(f"/places/{p['id']}", data=form, follow_redirects=False)
    assert r.status_code == 303, re.findall(r'role="alert"[^>]*>([^<]*)', r.text)
    got = store.get_place(p["id"])
    assert (got["deposit"], got["lease_months"], got["pet_rent"]) == (1500, 12, 25)
    assert got["listing_agent"] == "Jane, Example Realty"
    # and a rent form never wipes the buyer fields
    store.update_place(p["id"], by="you", hoa=210)
    r = store.add_search("Rent", "rent")
    q, _ = store.add_place(search_id=r["id"], title="R", address="2 Main St", price=1200, hoa=55, days_on_market=9)
    c.post(f"/places/{q['id']}", data={"title": "R", "price": "1250"}, follow_redirects=False)
    after = store.get_place(q["id"])
    assert after["hoa"] == 55 and after["days_on_market"] == 9 and after["price"] == 1250


# ---------------------------------------------------------------- the add form
def test_add_review_form_for_buy_says_price_and_carries_hidden_values(store):
    store.add_search("Columbus buy", "buy")
    c = local_client(store)
    html = c.post("/add/parse", data={"text": REDFIN}).text
    assert "Filled in from what you pasted:" in html
    filled = html.split("Filled in from what you pasted:")[1].split("</p>")[0]
    assert "price" in filled and "rent" not in filled.lower()
    assert "days on the market" in filled and "listing agent" in filled
    assert {"hoa", "property_tax", "special_assessment", "days_on_market", "listing_agent"} <= _visible(html)
    assert not (RENTER_ONLY & _visible(html))
    saved = c.post("/add/save", data={"title": "88 Beck Row", "address": "88 Beck Row", "price": "349000", "days_on_market": "41",
                                      "special_assessment": "4800", "special_assessment_payer": "seller",
                                      "listing_agent": "Jane Q. Agent, Example Realty", "lease_months": "", "deposit": ""},
                   follow_redirects=False)
    assert saved.status_code == 303
    p = store.list_places()[0]
    assert p["days_on_market"] == 41 and p["special_assessment"] == 4800 and p["special_assessment_payer"] == "seller"


def test_add_review_form_for_rent_keeps_buyer_fields_as_hidden_inputs(store):
    store.add_search("Rent", "rent")
    html = local_client(store).post("/add/parse", data={"text": REDFIN}).text
    assert not (BUYER_ONLY & _visible(html))
    assert BUYER_ONLY <= _names(html)  # carried, so nothing the reader found is lost


# ---------------------------------------------------------------- criteria and compare
def test_price_criterion_wording_follows_the_mode(store):
    b = store.add_search("Columbus buy", "buy")
    c = local_client(store)
    store.add_criterion(b["id"], "price", target={"max": 350000})
    html = c.get(f"/search?id={b['id']}").text
    assert "Most you&#39;d pay for the home" in html or "Most you'd pay for the home" in html
    assert "most per month, all in" not in html.lower()
    r = store.add_search("Rent", "rent")
    store.add_criterion(r["id"], "price", target={"max": 1600})
    html = c.get(f"/search?id={r['id']}").text
    assert "Price: most per month, all in" in html and "Price: most you" not in html


def test_compare_shows_price_and_cash_to_close_for_buyers(store):
    s = store.add_search("Buy", "buy")
    a, _ = store.add_place(search_id=s["id"], title="A", address="1 Oak Ln", price=300000, closing_costs=6000)
    b, _ = store.add_place(search_id=s["id"], title="B", address="2 Oak Ln", price=400000, days_on_market=12)
    html = local_client(store).get(f"/compare?ids={a['id']}&ids={b['id']}").text
    assert "Cash needed to close" in html and "$66,000" in html and "$92,000" in html
    assert "Listed price" not in html and "Price" in html
    assert "Days on the market" in html


# ---------------------------------------------------------------- AI prompts
BANNED = ("landlord", "lease", "deposit", "ask if it is available")


def _prompts(store, place_id, feature, purpose=""):
    system, prompt, _ = ai.build_prompt(store, place_id, feature, purpose)
    return system, prompt


def test_buy_prompts_have_no_renter_words(store, buy_place):
    _, p = buy_place
    for feature in ai.FEATURES:
        for purpose in ai.PURPOSES_BUY:
            system, prompt = _prompts(store, p["id"], feature, purpose)
            low = (system + prompt).lower()
            for word in BANNED:
                assert word not in low, (feature, purpose, word)
    assert all("available" not in label.lower() for label, _ in ai.PURPOSES_BUY.values())


def test_buy_tour_questions_and_messages_cover_the_buyer_topics(store, buy_place):
    _, p = buy_place
    _, q = _prompts(store, p["id"], "questions")
    for topic in ("HOA rules", "special assessment", "roof", "HVAC", "water heater", "disclosures", "days on the market", "price history"):
        assert topic.lower() in q.lower(), topic
    _, m = _prompts(store, p["id"], "message", "questions")
    assert "listing agent" in m.lower()


def test_buy_message_goes_to_the_buyers_agent_when_one_is_saved(store, buy_place):
    _, p = buy_place
    c = store.add_contact(name="Sam Buyer-Agent", role="buyer's agent", company="Example Realty")
    store.link_contact(c["id"], p["id"])
    _, m = _prompts(store, p["id"], "message", "availability")
    assert "buyer's agent on file" in m


def test_rent_prompts_are_unchanged(store):
    s = store.add_search("Rent", "rent")
    p, _ = store.add_place(search_id=s["id"], title="A", address="1 Main St", price=1500)
    _, prompt = _prompts(store, p["id"], "questions")
    assert "landlord" in prompt.lower() and "Lease and move-in" in prompt
    _, m = _prompts(store, p["id"], "message", "availability")
    assert "still available" in m


def test_ai_panel_lists_buyer_purposes_for_a_buy_search(store, buy_place):
    _, p = buy_place
    html = local_client(store).get(f"/places/{p['id']}/ai").text
    assert "Ask about its status" in html and "Ask if it is available" not in html
    assert "landlord" not in html.lower()
