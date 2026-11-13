"""Cycle 1, fixer F1: scoring agrees with deal-breakers and scam flags, hiding rules, buy price, honest buyer cost,
estimate marks, Compare fixes, people sharing, Board commutes."""
from __future__ import annotations

import pytest

from prophelper import compare, enrich, money, scoring

SCAM_TEXT = "Wire the deposit by Western Union before the showing. The owner is overseas and the keys will be mailed."


def _rent(store, **crit):
    s = store.add_search("Rent", "rent", budget_max=1600)
    store.add_criterion(s["id"], "price", weight=30, dealbreaker=True, target={"max": 1600})
    store.add_criterion(s["id"], "beds", weight=10, target={"min": 1})
    return s


def _row(store, search, place):
    return enrich.enrich_places(store, search, [place])[0]


# ---- 1. score agrees with deal-breakers and scam flags
def test_failing_a_deal_breaker_shows_the_gap_not_a_high_score(store):
    s = _rent(store)
    p, _ = store.add_place(title="Near miss", address="1 A St", price=1500, utilities_estimate=106, beds=1)
    e = _row(store, s, p)
    assert e["score"]["fit"] == "doesnt_fit"
    assert e["score"]["fit_reasons"] == ["Over budget by $6"]
    assert e["score_total"] <= scoring.CAP_DEALBREAKER
    assert e["score"]["raw_total"] > e["score_total"] or e["score"]["raw_total"] <= scoring.CAP_DEALBREAKER


def test_commute_gap_names_minutes_and_limit(store):
    s = store.add_search("Rent", "rent")
    a = store.add_anchor("Office", "x", 40.0, -88.0)
    store.add_criterion(s["id"], "commute", dealbreaker=True, target={"anchor_id": a["id"], "mode": "walk", "minutes": 15})
    p, _ = store.add_place(title="Far", address="2 A St", price=900, lat=40.02, lng=-88.0)
    e = _row(store, s, p)
    assert e["score"]["fit"] == "doesnt_fit"
    assert e["score"]["fit_reasons"][0].startswith("Commute ") and ", limit 15" in e["score"]["fit_reasons"][0]


def test_scam_listing_is_capped_at_50_and_labelled(store):
    s = store.add_search("Rent", "rent")
    store.add_criterion(s["id"], "beds", weight=10, target={"min": 1})
    p, _ = store.add_place(title="Too good", address="3 A St", price=500, beds=2, listing_text=SCAM_TEXT)
    e = _row(store, s, p)
    assert e["score"]["fit"] == "check_first" and e["score_total"] <= 50
    assert e["score"]["raw_total"] == 100
    assert e["score"]["fit_reasons"][0].startswith("Check first: possible scam")


def test_board_sorts_fitting_places_first_and_shows_badges(client, store):
    s = _rent(store)
    store.add_place(title="Fine", address="4 A St", price=1000, utilities_estimate=50, beds=1)
    store.add_place(title="Miss", address="5 A St", price=1700, utilities_estimate=50, beds=1)
    store.add_place(title="Scam", address="6 A St", price=400, utilities_estimate=50, beds=3, listing_text=SCAM_TEXT)
    html = client.get("/board").text
    assert html.index("Fine") < html.index("Miss") and html.index("Fine") < html.index("Scam")
    assert "Doesn't fit" in html and "Over budget by $" in html and "Check first: possible scam" in html
    rows = enrich.enrich_places(store, s)
    ordered = sorted(rows, key=scoring.sort_key)
    assert ordered[0]["title"] == "Fine"


# ---- 2. hiding
def test_new_searches_do_not_hide_by_default_and_failing_places_stay(store):
    s = _rent(store)
    assert s["hide_dealbreakers"] == 0
    store.add_place(title="Miss", address="5 A St", price=1900, utilities_estimate=50, beds=1)
    assert not enrich.enrich_places(store, s)[0]["hidden_by_dealbreaker"]


def test_hiding_never_hides_a_place_with_a_tour_contact_or_later_stage(store, client):
    s = _rent(store)
    s = store.update_search(s["id"], hide_dealbreakers=True)
    plain, _ = store.add_place(title="Plain", address="1 H St", price=1900, utilities_estimate=50, beds=1)
    toured, _ = store.add_place(title="HasTour", address="2 H St", price=1900, utilities_estimate=50, beds=1)
    contact, _ = store.add_place(title="HasContact", address="3 H St", price=1900, utilities_estimate=50, beds=1)
    staged, _ = store.add_place(title="Later", address="4 H St", price=1900, utilities_estimate=50, beds=1)
    store.add_tour(toured["id"], "2030-01-05T15:00", advance=False)
    store.link_contact(contact["id"], store.add_contact("Pat")["id"])
    store.move_stage(staged["id"], "Contacted")
    hidden = {e["title"]: e["hidden_by_dealbreaker"] for e in enrich.enrich_places(store, s)}
    assert hidden == {"Plain": True, "HasTour": False, "HasContact": False, "Later": False}
    board = client.get("/board").text
    assert "HasTour" in board and "HasContact" in board and "Later" in board and "Plain" not in board
    mp = client.get("/map").text
    assert "HasTour" in mp and "Plain" not in mp
    assert store.protected_place_ids(s["id"]) == {toured["id"], contact["id"], staged["id"]}


# ---- 3. buy price criterion
def test_buy_price_cap_compares_the_list_price(store):
    s = store.add_search("Buy", "buy")
    store.add_criterion(s["id"], "price", dealbreaker=True, target={"max": 340000})
    over, _ = store.add_place(title="Over", address="1 B St", price=349000)
    under, _ = store.add_place(title="Under", address="2 B St", price=330000)
    a, b = _row(store, s, over), _row(store, s, under)
    assert a["score"]["fit"] == "doesnt_fit" and a["score"]["fit_reasons"] == ["Over budget by $9,000"]
    assert b["score"]["fit"] == "fits"
    item = a["score"]["items"][0]
    assert item["label"] == "Price, at most $340,000" and "a month" not in item["value"] + item["target"]


def test_rent_price_label_and_detail_stay_monthly(store):
    s = store.add_search("Rent", "rent")
    store.add_criterion(s["id"], "price", target={"max": 1600})
    p, _ = store.add_place(title="R", address="1 R St", price=1400, utilities_estimate=50)
    item = _row(store, s, p)["score"]["items"][0]
    assert item["label"].startswith("Monthly cost") and "a month" in item["target"]


# ---- 4. honest buyer cost and headline
def test_buyer_cost_shows_down_payment_loan_and_pmi_under_20_percent():
    place = {"price": 400000, "property_tax": 4800, "insurance": 1200, "hoa": 0}
    c = money.true_monthly_cost(place, "buy", {"down_payment_pct": 10, "mortgage_rate": 6.5, "loan_years": 30})
    assert c["down_payment"] == 40000 and c["loan_amount"] == 360000
    assert c["pmi"] == pytest.approx(360000 * 0.005 / 12)
    assert any(l["key"] == "pmi" and "estimate" in l["label"] for l in c["lines"])
    none = money.true_monthly_cost(place, "buy", {"down_payment_pct": 20})
    assert none["pmi"] is None and not any(l["key"] == "pmi" for l in none["lines"])
    custom = money.true_monthly_cost(place, "buy", {"down_payment_pct": 10, "pmi_rate_pct": 1.0})
    assert custom["pmi"] == pytest.approx(360000 * 0.01 / 12)


def test_headline_says_what_is_not_counted():
    c = money.true_monthly_cost({"price": 400000, "property_tax": 4800, "hoa": 0}, "buy")
    assert c["headline"].endswith(", insurance not counted yet") and c["headline"].startswith("$")
    r = money.true_monthly_cost({"price": 1500}, "rent")
    assert r["headline"] == "$1,500/mo, utilities not counted yet"
    full = money.true_monthly_cost({"price": 1500, "utilities_estimate": 80}, "rent")
    assert "not counted" not in full["headline"]


def test_place_page_shows_headline_and_buyer_numbers(client, store):
    s = store.add_search("Buy", "buy")
    store.set_setting("down_payment_pct", "10")
    p, _ = store.add_place(title="House", address="1 Home Rd", price=400000, property_tax=4800, hoa=0)
    html = client.get(f"/places/{p['id']}").text
    assert "insurance not counted yet" in html and "Down payment $40,000" in html and "Loan $360,000" in html
    assert "Mortgage insurance (PMI)" in html


def test_pmi_setting_is_editable(client, store):
    r = client.post("/settings", data={"pmi_rate_pct": "0.8"}, follow_redirects=False)
    assert r.status_code in (302, 303) and store.get_setting("pmi_rate_pct") == "0.8"


# ---- 5. estimates are marked
def test_estimated_utilities_are_labelled_a_guess(store):
    c = money.true_monthly_cost({"price": 1500, "utilities_estimate": 90}, "rent")
    line = next(l for l in c["lines"] if l["key"] == "utilities")
    assert "guess" in line["label"].lower() and line["estimated"] and "not from the listing" in line["note"]


def test_score_resting_on_unknowns_says_how_many(client, store):
    s = store.add_search("Rent", "rent")
    store.add_criterion(s["id"], "sqft", target={"min": 500})
    store.add_criterion(s["id"], "dishwasher")
    p, _ = store.add_place(title="Few facts", address="1 U St", price=1000, utilities_estimate=50)
    e = _row(store, s, p)
    assert e["score"]["unknown_count"] == 2
    assert "based on 2 unknowns" in client.get(f"/places/{p['id']}").text


# ---- 6. compare
def _two(store, **second):
    s = store.add_search("Rent", "rent")
    a, _ = store.add_place(title="Alpha", address="1 C St", price=1500, utilities_estimate=80, sqft=700, year_built=2016)
    b, _ = store.add_place(title="Beta", address="2 C St", price=1400, utilities_estimate=80, sqft=900, year_built=1999, **second)
    return s, [_row(store, s, p) for p in (a, b)]


def test_year_built_has_no_thousands_comma(store):
    _, places = _two(store)
    rows = {r["key"]: r for sec in compare.build_rows(places) for r in sec["rows"]}
    assert [c["text"] for c in rows["year_built"]["cells"]] == ["2016", "1999"]
    assert rows["year_built"]["cells"][0]["best"]  # newer is better


def test_best_direction_per_row_and_unknown_never_best(store):
    _, places = _two(store)
    places.append(_row(store, store.current_search(), store.add_place(title="Gamma", address="3 C St")[0]))
    rows = {r["key"]: r for sec in compare.build_rows(places) for r in sec["rows"]}
    assert [c["best"] for c in rows["sqft"]["cells"]] == [False, True, False]  # size: higher is better
    assert [c["best"] for c in rows["price"]["cells"]] == [False, True, False]  # price: lower is better
    assert not rows["price"]["cells"][2]["best"] and rows["price"]["cells"][2]["unknown"]
    assert not rows["beds"]["cells"][0]["best"]  # a fact where neither is better


def test_still_unknown_lists_what_is_unknown(store):
    s = store.add_search("Rent", "rent")
    store.add_criterion(s["id"], "sqft", target={"min": 500})
    a, _ = store.add_place(title="Alpha", address="1 C St", price=1500, utilities_estimate=80)
    b, _ = store.add_place(title="Beta", address="2 C St", price=1400, utilities_estimate=80, sqft=800)
    places = [_row(store, s, p) for p in (a, b)]
    rows = {r["key"]: r for sec in compare.build_rows(places) for r in sec["rows"]}
    assert "500" in rows["unknown"]["cells"][0]["text"] or "Size" in rows["unknown"]["cells"][0]["text"]
    assert rows["unknown"]["cells"][1]["text"] == "Utilities (a guess)"
    assert compare.unknown_list(places[0]) and compare.unknown_list(places[1]) == ["Utilities (a guess)"]


def test_incomplete_cost_is_not_marked_lowest(store):
    s = store.add_search("Rent", "rent")
    a, _ = store.add_place(title="Alpha", address="1 C St", price=1300)  # utilities unknown
    b, _ = store.add_place(title="Beta", address="2 C St", price=1400, utilities_estimate=80)
    places = [_row(store, s, p) for p in (a, b)]
    rows = {r["key"]: r for sec in compare.build_rows(places) for r in sec["rows"]}
    assert not any(c["best"] for c in rows["cost"]["cells"])
    assert "utilities not counted yet" in rows["cost"]["cells"][0]["text"]


def test_compare_has_one_commute_row_per_anchor_named_by_the_anchor(client, store):
    s = store.add_search("Rent", "rent")
    office = store.add_anchor("Office", "x", 40.0, -88.0)
    school = store.add_anchor("School", "y", 40.05, -88.05)
    store.add_criterion(s["id"], "commute", target={"anchor_id": office["id"], "mode": "drive", "minutes": 20})
    a, _ = store.add_place(title="Alpha", address="1 C St", price=1500, lat=40.01, lng=-88.01)
    b, _ = store.add_place(title="Beta", address="2 C St", price=1500, lat=40.02, lng=-88.02)
    places = [_row(store, s, p) for p in (a, b)]
    sections = {sec["title"]: sec for sec in compare.build_rows(places)}
    labels = [r["label"] for r in sections["Commutes"]["rows"]]
    assert labels == ["To Office (drive)", f"To School ({places[0]['commute_all'][1]['mode']})"]
    html = client.get(f"/compare?ids={a['id']},{b['id']}").text
    assert "To Office (drive)" in html and "To School" in html
    assert "Print or save as PDF" in html and "/static/compare.css" in html and "data-print" in html


def test_print_assets_exist(client):
    css = client.get("/static/compare.css")
    assert css.status_code == 200 and "@media print" in css.text
    assert client.get("/static/print.js").status_code == 200


# ---- 7. people sharing
def test_people_migration_and_edit(store, client):
    s = store.add_search("Rent", "rent")
    assert s["people"] == 1
    assert store.update_search(s["id"], people=3)["people"] == 3
    with pytest.raises(ValueError):
        store.update_search(s["id"], people=0)
    with pytest.raises(ValueError):
        store.update_search(s["id"], people="two")
    r = client.post(f"/search/{s['id']}", data={"name": "Rent", "people": "2"}, follow_redirects=False)
    assert r.status_code in (302, 303) and store.get_search(s["id"])["people"] == 2
    assert 'name="people"' in client.get(f"/search?id={s['id']}").text


def test_per_person_cost_shows_on_place_board_and_compare(client, store):
    s = store.add_search("Rent", "rent", people=2)
    a, _ = store.add_place(title="Alpha", address="1 P St", price=1900, utilities_estimate=100)
    b, _ = store.add_place(title="Beta", address="2 P St", price=1500, utilities_estimate=100)
    assert money.true_monthly_cost({"price": 1900, "utilities_estimate": 100}, "rent", None, 2)["per_person"] == 1000.0
    place_html = client.get(f"/places/{a['id']}").text
    assert "$1,000 per person" in place_html
    assert "$1,000 per person (2 people)" in client.get("/board").text
    cmp_html = client.get(f"/compare?ids={a['id']},{b['id']}").text
    assert "Per person each month" in cmp_html and "$1,000.00 (2 people)" in cmp_html
    solo = store.add_search("Solo", "rent")
    store.set_current_search(solo["id"])
    q, _ = store.add_place(title="Solo place", address="3 P St", price=900, utilities_estimate=50)
    assert "per person" not in client.get(f"/places/{q['id']}").text


# ---- 8. board commutes
def test_board_card_shows_a_commute_for_each_anchor_with_a_commute_criterion(client, store):
    s = store.add_search("Rent", "rent")
    office = store.add_anchor("Office", "x", 40.0, -88.0)
    school = store.add_anchor("School", "y", 40.05, -88.05)
    gym = store.add_anchor("Gym", "z", 40.1, -88.1)
    store.add_criterion(s["id"], "commute", target={"anchor_id": office["id"], "mode": "drive", "minutes": 20})
    store.add_criterion(s["id"], "commute", target={"anchor_id": school["id"], "mode": "walk", "minutes": 25})
    p, _ = store.add_place(title="Alpha", address="1 C St", price=1500, utilities_estimate=50, lat=40.01, lng=-88.01)
    e = _row(store, s, p)
    assert [t["anchor"] for t in e["commute_tops"]] == ["Office", "School"]
    html = client.get("/board").text
    assert "Office " in html and " min drive" in html and "School " in html and " min walk" in html and "Gym" not in html
