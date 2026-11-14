"""Cycle 10, fixer G6 items 1 and 2: parking rule target, one pets rule that follows the search."""
from __future__ import annotations

import pytest

from conftest import local_client
from mcp_util import call, server, structured, text
from prophelper import enrich, scoring

WARN = "This parking rule accepts any off-street parking. Say garage or covered if that's what you need."


def test_parking_want_inferred_from_label():
    assert scoring.settle_parking_target("Garage or covered", {}) == ({"want": "garage"}, "")
    assert scoring.settle_parking_target("Covered parking", None) == ({"want": "covered"}, "")
    assert scoring.settle_parking_target("Parking", {})[1] == WARN
    assert scoring.settle_parking_target("Garage", {"want": "lot"}) == ({"want": "lot"}, "")


def test_create_search_infers_garage(store):
    srv = server(store)
    r = call(srv, "create_search", name="S", criteria=[{"kind": "parking", "label": "Garage or covered", "dealbreaker": True}])
    sid = structured(r)["search_id"] if isinstance(structured(r), dict) and "search_id" in structured(r) else store.list_searches()[0]["id"]
    c = [x for x in store.list_criteria(sid) if x["kind"] == "parking"][0]
    assert c["target"] == {"want": "garage"}
    assert WARN not in text(r)


def test_create_search_warns_when_no_target_and_no_hint(store):
    srv = server(store)
    r = call(srv, "create_search", name="S", criteria=[{"kind": "parking", "label": "Somewhere to park"}])
    assert WARN in text(r)


def test_update_search_parking_and_web_form(store):
    s = store.add_search("S", "rent", budget_max=1500)
    srv = server(store)
    r = call(srv, "update_search", search_id=s["id"], add_criteria_list=[{"kind": "parking", "label": "Covered parking"}])
    assert [c["target"] for c in store.list_criteria(s["id"]) if c["kind"] == "parking"] == [{"want": "covered"}]
    assert WARN not in text(r)
    client = local_client(store)
    s2 = store.add_search("T", "rent", budget_max=1500)
    resp = client.post(f"/search/{s2['id']}/criteria", data={"kind": "parking", "label": "Garage", "weight": "10"}, follow_redirects=False)
    assert resp.status_code in (302, 303)
    assert store.list_criteria(s2["id"])[0]["target"] == {"want": "garage"}
    s3 = store.add_search("U", "rent", budget_max=1500)
    client.post(f"/search/{s3['id']}/criteria", data={"kind": "parking", "label": "Parking", "weight": "10"}, follow_redirects=False)
    page = client.get(f"/search?id={s3['id']}")
    assert "accepts any off-street parking" in page.text


def test_hand_added_pets_rule_follows_cat_setting(store):
    s = store.add_search("S", "rent", budget_max=1500, pet_kind="cat", pet_count=1)
    row = store.add_criterion(s["id"], "pets", dealbreaker=True, target={"want": "both"})
    assert "want" not in row["target"]
    with pytest.raises(ValueError, match="already has a pets rule"):
        store.add_criterion(s["id"], "pets", dealbreaker=True)
    p, _ = store.add_place(title="Cats only", address="1 A St", price=1000, pets="cats")
    e = enrich.enrich_places(store, store.get_search(s["id"]), [p])[0]
    assert e["score"]["fit"] == "fits"
    assert e["score"]["failed"] == [] and e["score"]["unknown"] == []


def test_tools_and_form_refuse_second_pets_rule(store):
    s = store.add_search("S", "rent", budget_max=1500, pet_kind="cat")
    store.add_criterion(s["id"], "pets", dealbreaker=True)
    srv = server(store)
    with pytest.raises(Exception) as ei:
        call(srv, "update_search", search_id=s["id"], add_criteria_list=[{"kind": "pets", "dealbreaker": True, "target": {"want": "both"}}])
    assert "already a pets rule" in str(ei.value)
    assert len([c for c in store.list_criteria(s["id"]) if c["kind"] == "pets"]) == 1
    client = local_client(store)
    client.post(f"/search/{s['id']}/criteria", data={"kind": "pets", "t_want_pets": "both", "weight": "10"}, follow_redirects=False)
    assert len([c for c in store.list_criteria(s["id"]) if c["kind"] == "pets"]) == 1
    assert "already has a pets rule" in client.get(f"/search?id={s['id']}").text
