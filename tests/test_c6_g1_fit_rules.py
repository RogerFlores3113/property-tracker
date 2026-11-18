"""Cycle 6, G1: automatic pets rule, unknown buy costs, unknown rent, commute points."""
from __future__ import annotations

import asyncio

from prophelper import enrich, scoring
from prophelper.mcp_server import build_server


def _row(store, search, place):
    return enrich.enrich_places(store, search, [place])[0]


def _call(store, name, args):
    return asyncio.run(build_server(store).call_tool(name, args))


def test_starter_criteria_adds_pets_once():
    out = scoring.starter_criteria("rent", None, None, pet_kind="cat")
    assert [c["kind"] for c in out] == ["pets"] and out[0]["dealbreaker"]
    assert scoring.starter_criteria("rent", None, None, ["pets"], pet_kind="cat") == []
    assert scoring.starter_criteria("rent", None, None, pet_kind="none") == []
    assert scoring.starter_criteria("rent", None, None) == []


def test_web_create_with_cat_makes_no_pets_listing_not_fit(client, store):
    client.post("/search", data={"name": "Cat", "mode": "rent", "pet_kind": "cat"}, follow_redirects=False)
    s = store.current_search()
    assert [c["kind"] for c in store.list_criteria(s["id"])] == ["pets"]
    p, _ = store.add_place(title="No pets here", address="1 A St", price=1000, pets="none")
    sc = _row(store, s, p)["score"]
    assert sc["fit"] == "doesnt_fit" and sc["fit_label"] != "Fits"
    assert "no pets" in sc["fit_reasons"][0] and "cats allowed" in sc["fit_reasons"][0]


def test_web_edit_setting_pet_adds_rule_and_says_so(client, store):
    s = store.add_search("S", "rent")
    store.set_current_search(s["id"])
    r = client.post(f"/search/{s['id']}", data={"name": "S", "pet_kind": "dog"}, follow_redirects=True)
    assert [c["kind"] for c in store.list_criteria(s["id"])] == ["pets"]
    assert "pet rule" in r.text
    client.post(f"/search/{s['id']}", data={"name": "S", "pet_kind": "dog"})
    assert len(store.list_criteria(s["id"])) == 1


def test_mcp_create_and_update_add_pets_rule(store):
    out = _call(store, "create_search", {"name": "M", "pet_kind": "cat"})
    assert "pets" in str(out).lower()
    s = store.current_search()
    assert [c["kind"] for c in store.list_criteria(s["id"])] == ["pets"]
    s2 = store.add_search("N", "rent")
    out = _call(store, "update_search", {"search_id": s2["id"], "pet_kind": "dog"})
    assert "pets must-have" in str(out)
    assert [c["kind"] for c in store.list_criteria(s2["id"])] == ["pets"]


def test_buy_unknown_costs_fit_but_check_capped(store):
    s = store.add_search("Buy", "buy", budget_max=400000)
    store.add_criterion(s["id"], "price", weight=20, dealbreaker=True, target={"max": 400000})
    p, _ = store.add_place(title="House", address="1 A St", price=300000)
    sc = _row(store, s, p)["score"]
    assert sc["fit"] == "fits" and sc["fit_label"] == "Fits, but check"
    assert sc["total"] == 85
    assert any("property tax, insurance and HOA not counted yet" in c for c in sc["concerns"])
    p2, _ = store.add_place(title="Known", address="2 A St", price=300000, property_tax=3600, insurance=1200, hoa=0)
    sc2 = _row(store, s, p2)["score"]
    assert sc2["fit_label"] == "Fits" and sc2["total"] == 100


def test_buy_hoa_known_none_not_listed(store):
    s = store.add_search("Buy", "buy")
    store.add_criterion(s["id"], "price", weight=20, dealbreaker=True, target={"max": 400000})
    p, _ = store.add_place(title="House", address="1 A St", price=300000, hoa=0)
    sc = _row(store, s, p)["score"]
    assert any("property tax and insurance not counted" in c for c in sc["concerns"])


def test_rent_unknown_is_check_not_yes(store):
    s = store.add_search("R", "rent")
    store.add_criterion(s["id"], "beds", weight=10, dealbreaker=False, target={"min": 1})
    p, _ = store.add_place(title="No rent", address="1 A St", beds=1)
    sc = _row(store, s, p)["score"]
    assert sc["fit_label"] == "Fits, but check" and "rent not known yet" in sc["concerns"]
    assert sc["total"] <= 85
    p2, _ = store.add_place(title="Rent", address="2 A St", price=1000, beds=1)
    assert _row(store, s, p2)["score"]["fit_label"] == "Fits"


def test_buy_no_price_says_price(store):
    s = store.add_search("B", "buy")
    store.add_criterion(s["id"], "beds", weight=10, dealbreaker=False, target={"min": 1})
    p, _ = store.add_place(title="x", address="1 A St", beds=1)
    assert "price not known yet" in _row(store, s, p)["score"]["concerns"]


def _commute_setup(store, dealbreaker):
    s = store.add_search("C", "rent")
    a = store.add_anchor("Campus", "x", 40.0, -88.0)
    store.add_criterion(s["id"], "commute", weight=20, dealbreaker=dealbreaker, target={"mode": "bike", "minutes": 20})
    store.add_criterion(s["id"], "beds", weight=20, dealbreaker=False, target={"min": 1})
    p, _ = store.add_place(title="Far", address="1 A St", price=1000, beds=1, lat=40.01, lng=-88.0)
    store.set_commute(p["id"], a["id"], "bike", 24, "you")
    return s, p


def test_nice_to_have_commute_says_points_lost(store):
    s, p = _commute_setup(store, False)
    sc = _row(store, s, p)["score"]
    # C7: a nice-to-have commute a little over its limit is a plain fit; the cost is a note in the score line
    assert sc["fit_label"] == "Fits" and not sc["concerns"]
    assert "Commute to Campus 24 min bike, over your 20 min, cost 10 points" in sc["notes"]


def test_must_have_commute_over_limit_does_not_fit(store):
    s, p = _commute_setup(store, True)
    sc = _row(store, s, p)["score"]
    assert sc["fit"] == "doesnt_fit"
