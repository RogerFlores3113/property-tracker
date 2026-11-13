"""Cycle 4, fixer G3: starter must-haves, honest budget lines, per-person commutes, late openings, unknown caps, Today."""
from __future__ import annotations

from prophelper import enrich, scoring, today


def _row(store, search, place):
    return enrich.enrich_places(store, search, [place])[0]


def _kinds(store, s):
    return [c["kind"] for c in store.list_criteria(s["id"])]


def test_web_search_with_bedrooms_and_budget_adds_must_haves(client, store):
    r = client.post("/search", data={"name": "One bed", "mode": "rent", "budget_max": "1700", "bedrooms": "1"}, follow_redirects=False)
    assert r.status_code in (302, 303)
    s = store.current_search()
    crit = {c["kind"]: c for c in store.list_criteria(s["id"])}
    assert crit["beds"]["dealbreaker"] and crit["beds"]["target"]["min"] == 1
    assert crit["price"]["dealbreaker"] and crit["price"]["target"]["max"] == 1700
    p, _ = store.add_place(title="Studio", address="1 A St", price=1000, utilities_estimate=50, beds=0, sqft=480)
    e = _row(store, s, p)
    assert e["score"]["fit"] == "doesnt_fit"
    assert e["score"]["fit_reasons"] == ["Studio, you need 1 bedroom"]


def test_no_bedrooms_or_budget_means_no_starter_criteria(client, store):
    client.post("/search", data={"name": "Open", "mode": "rent"}, follow_redirects=False)
    assert store.list_criteria(store.current_search()["id"]) == []


def test_user_price_rule_replaces_the_automatic_one(client, store):
    client.post("/search", data={"name": "S", "mode": "rent", "budget_max": "1700"}, follow_redirects=False)
    s = store.current_search()
    client.post(f"/search/{s['id']}/criteria", data={"kind": "price", "weight": "10", "t_max": "1500", "dealbreaker": "1"})
    prices = [c for c in store.list_criteria(s["id"]) if c["kind"] == "price"]
    assert len(prices) == 1 and prices[0]["target"]["max"] == 1500


def test_starter_criteria_skips_kinds_already_given():
    assert [c["kind"] for c in scoring.starter_criteria("rent", 1500, 2, {"price"})] == ["beds"]
    assert scoring.starter_criteria("buy", None, None) == []


def test_budget_line_says_what_was_compared():
    cost = {"total": 3330, "lines": [{"key": "price", "amount": 3150}, {"key": "utilities", "amount": 180, "estimated": True}]}
    c = {"kind": "price", "weight": 10, "dealbreaker": True, "label": "Rent at most $3300", "target": {"max": 3300}}
    r = scoring.score_criterion(c, {}, {"cost": cost, "mode": "rent", "anchors": {}})
    assert r["gap"] == "$3,330 a month all in (rent $3,150 + utilities guess $180), over $3,300 by $30"
    # 1% over only because of the guess: a near miss, not a hard fail
    assert r["dealbreaker_status"] == "near"
    rent_only = scoring.score_criterion({**c, "target": {"max": 3300, "count": "rent"}}, {}, {"cost": cost, "mode": "rent", "anchors": {}})
    assert rent_only["dealbreaker_status"] == "pass" and "rent only" in rent_only["value"]


def test_small_guess_overage_does_not_cliff(store):
    s = store.add_search("R", "rent", budget_max=3300)
    store.add_criterion(s["id"], "price", weight=30, dealbreaker=True, target={"max": 3300})
    store.add_criterion(s["id"], "beds", weight=10, target={"min": 1})
    p, _ = store.add_place(title="Near", address="1 A St", price=3150, utilities_estimate=180, beds=2)
    e = _row(store, s, p)
    assert e["score"]["fit"] == "near_miss" and e["score"]["near"] and e["score_total"] >= 70
    assert not today.is_best_fit(e) and today.near_miss_text(e).startswith("$30 over because the utilities guess counts")


def test_each_persons_commute_is_checked(store):
    s = store.add_search("Roommates", "rent", people=2)
    cam = store.add_anchor("Cam", "x", 40.0, -88.0)
    jo = store.add_anchor("Jo", "y", 40.001, -88.0)
    store.add_criterion(s["id"], "commute", weight=10, target={"mode": "transit", "minutes": 40})
    p, _ = store.add_place(title="Far from Jo", address="1 A St", price=900, lat=40.001, lng=-88.0)
    store.set_commute(p["id"], cam["id"], "transit", 20, "you")
    store.set_commute(p["id"], jo["id"], "transit", 70, "you")
    e = _row(store, s, p)
    item = e["score"]["items"][0]
    assert "Jo: 70 min, limit 40" in item["gap"]
    assert "Jo: 70 min, limit 40" in e["score"]["concerns"]
    assert e["score_total"] <= scoring.CAP_FAR_COMMUTE


def test_late_opening_counts_against_fit(store):
    s = store.add_search("R", "rent", move_in="2027-01-15")
    store.add_criterion(s["id"], "beds", weight=10, target={"min": 1})
    p, _ = store.add_place(title="Late", address="1 A St", price=900, beds=1, available_from="2027-03-01")
    q, _ = store.add_place(title="On time", address="2 A St", price=900, beds=1, available_from="2027-01-15")
    late, ok = _row(store, s, p), _row(store, s, q)
    assert late["score_total"] < ok["score_total"]
    assert any("after your move-in" in c for c in late["score"]["concerns"])


def test_unknown_must_haves_cap_the_score():
    crit = [{"id": i, "kind": k, "weight": 10, "dealbreaker": True, "target": {}} for i, k in enumerate(("dishwasher", "parking", "fenced_yard"))]
    crit.append({"id": 9, "kind": "beds", "weight": 10, "dealbreaker": False, "target": {"min": 1}})
    r = scoring.score_place({"beds": 2}, crit, serious_flag=False)
    assert r["unknown_count"] == 3 and r["total"] <= 55


def test_best_fits_need_a_reasonable_score_and_near_miss_fires_for_any_must_have():
    good = {"hidden": False, "stage": "Saved", "title": "G", "score_total": 80, "score": {}}
    low = {"hidden": False, "stage": "Saved", "title": "L", "score_total": 34, "score": {}}
    assert [p["title"] for p in today.best_fits([good, low])] == ["G"]
    near = {"hidden": False, "stage": "Saved", "title": "N", "score_total": 45, "possible_scam": False,
            "score": {"items": [{"kind": "commute", "dealbreaker_status": "fail", "over_amount": 1, "over_pct": 0.02,
                                 "gap": "Commute 41 min, limit 40"}]}}
    assert today.near_miss_text(near) == "Commute 41 min, limit 40"


def test_mcp_create_search_adds_budget_and_bedroom_must_haves(store):
    import sys
    sys.path.insert(0, "tests")
    from mcp_util import call, server, structured

    srv = server(store)
    sid = structured(call(srv, "create_search", name="1-bed", budget_max=1700, bedrooms=1,
                          criteria=[{"kind": "price", "target": {"max": 1500}, "dealbreaker": True}]))["search_id"]
    crit = store.list_criteria(sid)
    assert sorted(c["kind"] for c in crit) == ["beds", "price"]  # the user's own price rule is not doubled
    assert next(c for c in crit if c["kind"] == "price")["target"]["max"] == 1500
