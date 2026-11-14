"""Cycle 1, F6: integration pass (one scam rule, cash at move-in, hookups, plain words, URLs as typed, sample data)."""
from conftest import local_client
from prophelper import enrich, money, parsers, redflags, scoring, today

SCAM = {"title": "Dream flat", "listing_text": "Owner is abroad. Wire the deposit before you see the place. Keys will be mailed to you."}
PLAIN = {"title": "Plain flat", "listing_text": "Nice 1 bed near campus. Tours on weekends. Apply online with our portal."}


# ---- 1. one rule for "possible scam"
def test_is_serious_is_the_single_rule():
    assert redflags.is_serious(SCAM) and not redflags.is_serious(PLAIN)
    assert redflags.is_serious({"listing_text": "We only take Cash App for the deposit."})
    assert redflags.is_serious({"listing_text": "Send your SSN first to hold it, before you can see it."})
    assert scoring.has_serious_flag(SCAM) and not scoring.has_serious_flag(PLAIN)


def test_today_and_board_agree_on_a_scam(store):
    s = store.add_search("Rent", "rent")
    store.add_place(search_id=s["id"], title="Dream flat", price=500, beds=1, listing_text=SCAM["listing_text"])
    store.add_place(search_id=s["id"], title="Plain flat", price=1000, beds=1, listing_text=PLAIN["listing_text"])
    rows = {p["title"]: p for p in enrich.enrich_places(store, s)}
    assert today.possible_scam(rows["Dream flat"]) and not today.possible_scam(rows["Plain flat"])
    assert rows["Dream flat"]["score"]["fit"] == "check_first"
    assert "Dream flat" not in [p["title"] for p in today.best_fits(list(rows.values()))]


# ---- 2. first and last month is cash at move-in, not a fee
def test_first_last_is_cash_at_move_in_not_monthly_cost():
    out = parsers.parse_listing("Elm Flats\n$1,200/mo 1 bed. First and last month required. $500 deposit. $100 admin fee.", "")
    assert out["move_in_fees"] == 100
    place = {**out, "listing_text": "First and last month required.", "lease_months": 12}
    cost = money.true_monthly_cost(place, "rent")
    assert cost["cash_at_move_in"]["total"] == 1200 + 1200 + 500 + 100
    assert abs(cost["total"] - (1200 + 100 / 12)) < 0.5


def test_place_page_shows_cash_needed(store):
    s = store.add_search("Rent", "rent")
    p, _ = store.add_place(search_id=s["id"], title="Elm", price=1000, deposit=500,
                           listing_text="First and last month required.")
    html = local_client(store).get(f"/places/{p['id']}").text
    assert "Cash needed at move-in: $2,500" in html


# ---- 3. laundry hookups
def test_hookups_end_to_end(store):
    out = parsers.parse_listing("Elm Flats\n$900/mo 1 bed. W/D hookups available.", "")
    assert out["laundry"] == "hookups"
    s = store.add_search("Rent", "rent")
    p, _ = store.add_place(search_id=s["id"], title="Elm", price=900, laundry="W/D hookups")
    assert store.get_place(p["id"])["laundry"] == "hookups"
    c = {"kind": "laundry", "target": {"want": "in_unit"}, "weight": 3, "dealbreaker": False}

    def r(v):
        return scoring._score_laundry(c, {"laundry": v})["score"]
    assert r("in_building") > r("hookups") > r("none")
    cl = local_client(store)
    assert 'value="hookups"' in cl.get(f"/places/{p['id']}").text and 'value="hookups"' in cl.post("/add/parse", data={"text": "Elm\n$900/mo"}).text
    p2, _ = store.add_place(search_id=s["id"], title="B", price=950, laundry="in_unit")
    assert "Hookups only" in cl.get(f"/compare?ids={p['id']},{p2['id']}").text
