"""Cycle 6, group G3: per-search anchors, per-search down payment, anchor-less rule label, estimate wording."""
import sqlite3

import pytest
from conftest import local_client
from mcp_util import call, server, structured, text

from prophelper import commute, enrich, scoring
from prophelper.share import export_search
from prophelper.store import _MIGRATIONS, Store


def _two(store):
    a = store.add_search("Chicago", "rent", people=2)
    b = store.add_search("Throwaway", "rent", people=2)
    aa = store.add_anchor("UChicagoOnly", "x", 41.79, -87.60, search_id=a["id"])
    ab = store.add_anchor("ZedWorkOnly", "y", 41.85, -87.65, search_id=a["id"])
    ba = store.add_anchor("ThrowawayOnly", "z", 41.90, -87.70, search_id=b["id"])
    pa, _ = store.add_place(search_id=a["id"], title="Alpha", address="1 A St", lat=41.80, lng=-87.61, price=1000)
    pb, _ = store.add_place(search_id=b["id"], title="Beta", address="1 B St", lat=41.91, lng=-87.71, price=1000)
    for s, anc in ((a, aa), (b, ba)):
        store.add_criterion(s["id"], "commute", weight=20, dealbreaker=False, target={"mode": "transit", "minutes": 45, "all_anchors": True})
    return a, b, aa, ab, ba, pa, pb


def test_list_anchors_is_per_search_with_legacy_rows(store):
    a, b, aa, ab, ba, *_ = _two(store)
    legacy = store.add_anchor("Shared")
    assert [x["name"] for x in store.list_anchors(a["id"])] == ["UChicagoOnly", "ZedWorkOnly", "Shared"]
    assert [x["name"] for x in store.list_anchors(b["id"])] == ["ThrowawayOnly", "Shared"]
    assert len(store.list_anchors()) == 4 and legacy["search_id"] is None and aa["search_id"] == a["id"]


def test_delete_search_removes_its_anchors_not_others(store):
    a, b, aa, ab, ba, *_ = _two(store)
    store.delete_search(b["id"])
    assert [x["name"] for x in store.list_anchors()] == ["UChicagoOnly", "ZedWorkOnly"]


def test_pages_see_only_their_own_anchors(store):
    a, b, aa, ab, ba, pa, pb = _two(store)
    c = local_client(store)
    store.set_current_search(a["id"])
    for url in (f"/places/{pa['id']}", "/board", "/today", "/compare?ids=%d" % pa["id"], "/places.csv", "/map", f"/search?id={a['id']}"):
        body = c.get(url).text
        assert "ThrowawayOnly" not in body, url
    assert "UChicagoOnly" in c.get(f"/places/{pa['id']}").text
    assert "UChicagoOnly" in c.get("/places.csv").text and "ZedWorkOnly" in c.get("/places.csv").text
    store.set_current_search(b["id"])
    assert "UChicagoOnly" not in c.get("/places.csv").text
    assert "UChicagoOnly" not in c.get(f"/places/{pb['id']}").text
    assert "UChicagoOnly" not in c.get(f"/search?id={b['id']}").text


def test_enrich_commutes_only_use_own_anchors(store):
    a, b, aa, ab, ba, pa, pb = _two(store)
    e = enrich.enrich_places(store, b)[0]
    assert {r["anchor"]["name"] for r in e["commute_rows"]} == {"ThrowawayOnly"}


def test_web_anchor_form_ties_anchor_to_the_search(store):
    s = store.add_search("One", "rent")
    t = store.add_search("Two", "rent")
    c = local_client(store)
    c.post("/anchors", data={"name": "Gym", "search_id": str(t["id"])}, follow_redirects=False)
    assert [x["name"] for x in store.list_anchors(t["id"])] == ["Gym"] and store.list_anchors(s["id"]) == []


def test_mcp_anchors_belong_to_the_search_and_replies_stay_inside(store):
    srv = server(store)
    r1 = call(srv, "create_search", name="First", anchors=[{"name": "Ana office", "lat": 41.8, "lng": -87.6}], people=2,
              criteria=[{"kind": "commute", "target": {"mode": "transit", "minutes": 45}}])
    r2 = call(srv, "create_search", name="Second", anchors=[{"name": "Other", "lat": 41.9, "lng": -87.7}], people=2,
              criteria=[{"kind": "commute", "target": {"mode": "transit", "minutes": 45}}])
    t2 = text(r2)
    assert "Ana office" not in t2
    s1, s2 = structured(r1)["search_id"], structured(r2)["search_id"]
    assert [a["name"] for a in store.list_anchors(s1)] == ["Ana office"]
    assert [a["name"] for a in store.list_anchors(s2)] == ["Other"]
    # a reference to another search's anchor fails
    with pytest.raises(Exception):
        call(srv, "update_search", search_id=s2, add_criteria_list=[{"kind": "commute", "target": {"anchor": "Ana office", "mode": "walk", "minutes": 10}}])
    store.set_current_search(s2)
    ov = text(call(srv, "get_overview"))
    assert "Ana office" not in ov.split("Anchors")[-1] and "Other" in ov
    store.add_anchor("Second", "", 41.5, -87.5, search_id=s2)
    upd = text(call(srv, "update_search", search_id=s2, add_anchors_list=[{"name": "Third", "lat": 41.6, "lng": -87.4}]))
    assert "Ana office" not in upd


def test_mcp_label_of_anchorless_rule_says_everyones_places(store):
    srv = server(store)
    call(srv, "create_search", name="Roomies", people=2, anchors=[{"name": "Ana", "lat": 41.8, "lng": -87.6}, {"name": "Bo", "lat": 41.9, "lng": -87.7}])
    r = text(call(srv, "update_search", add_criteria_list=[{"kind": "commute", "target": {"mode": "transit", "minutes": 45}}]))
    assert "Transit to everyone's places, 45 min or less" in r and "Transit to Ana" not in r
    assert "Transit to everyone's places, 45 min or less" in text(call(srv, "get_overview"))
    r2 = text(call(srv, "create_search", name="Second", people=2, anchors=[{"name": "Cy", "lat": 41.8, "lng": -87.6}, {"name": "Di", "lat": 41.9, "lng": -87.7}],
                   criteria=[{"kind": "commute", "target": {"mode": "transit", "minutes": 45}}]))
    assert "Transit to everyone's places, 45 min or less" in r2 and "Cy" not in r2.split("Criteria:")[-1]


def test_down_payment_per_search(store):
    s = store.add_search("Buy", "buy", down_payment_pct=10)
    t = store.add_search("Buy2", "buy")
    store.set_setting("down_payment_pct", "25")
    assert store.buy_settings(s["id"])["down_payment_pct"] == "10"
    assert store.buy_settings(t["id"])["down_payment_pct"] == "25"
    p, _ = store.add_place(search_id=s["id"], title="House", address="1 Main", price=400000)
    q, _ = store.add_place(search_id=t["id"], title="House2", address="2 Main", price=400000)
    es = enrich.enrich_places(store, s)[0]
    et = enrich.enrich_places(store, t)[0]
    assert es["cost"]["down_payment"] == 40000 and et["cost"]["down_payment"] == 100000
    page = local_client(store).get(f"/places/{p['id']}").text
    assert "Down payment $40,000 (10%)" in page.replace("&#36;", "$")
    for bad in (-1, 101):
        with pytest.raises(ValueError):
            store.update_search(s["id"], down_payment_pct=bad)
    assert store.update_search(s["id"], down_payment_pct="")["down_payment_pct"] is None


def test_down_payment_form_and_mcp(store):
    s = store.add_search("Buy", "buy")
    c = local_client(store)
    r = c.post(f"/search/{s['id']}", data={"name": "Buy", "mode": "buy", "down_payment_pct": "15"}, follow_redirects=False)
    assert store.get_search(s["id"])["down_payment_pct"] == 15
    assert "Down payment (percent" in c.get(f"/search?id={s['id']}").text
    r = c.post(f"/search/{s['id']}", data={"name": "Buy", "mode": "buy", "down_payment_pct": "150"}, follow_redirects=True)
    assert store.get_search(s["id"])["down_payment_pct"] == 15
    srv = server(store)
    out = text(call(srv, "create_search", name="M", mode="buy", down_payment_pct=12))
    assert "12%" in out
    with pytest.raises(Exception):
        call(srv, "update_search", search_id=s["id"], down_payment_pct=120)
    call(srv, "update_search", search_id=s["id"], down_payment_pct=5)
    assert store.get_search(s["id"])["down_payment_pct"] == 5
    assert "down payment 5%" in text(call(srv, "get_overview"))


def test_json_export_import_carries_anchors_and_down_payment(store):
    s = store.add_search("Buy", "buy", down_payment_pct=7)
    an = store.add_anchor("Work", "w", 41.8, -87.6, search_id=s["id"])
    store.add_criterion(s["id"], "commute", target={"anchor_id": an["id"], "mode": "drive", "minutes": 20})
    doc = export_search(store, s["id"])
    assert doc["search"]["down_payment_pct"] == 7 and [a["name"] for a in doc["anchors"]] == ["Work"]
    import json

    from prophelper.share import apply_import, read_export
    res = apply_import(store, read_export(json.dumps(doc).encode()))
    new = res["search"]
    assert new["down_payment_pct"] == 7
    assert [a["name"] for a in store.list_anchors(new["id"])] == ["Work"]
    assert [a["name"] for a in store.list_anchors(s["id"])] == ["Work"]


def test_backup_export_all_has_search_id(store):
    s = store.add_search("S", "rent")
    store.add_anchor("A", search_id=s["id"])
    assert store.export_all()["anchors"][0]["search_id"] == s["id"]


def test_migration_from_version_8_keeps_anchors(tmp_path):
    path = tmp_path / "v8.db"
    con = sqlite3.connect(path)
    for sql in _MIGRATIONS[:8]:
        con.executescript("BEGIN;" + sql)
        con.commit()
    con.execute("PRAGMA user_version = 8")
    con.execute("INSERT INTO searches(name, mode, created_at, updated_at) VALUES ('Old', 'rent', 'x', 'x')")
    con.execute("INSERT INTO anchors(name, address) VALUES ('Old anchor', 'somewhere')")
    con.commit()
    con.close()
    s = Store(path)
    try:
        assert s.schema_version == 10
        row = s.list_anchors(1)
        assert [a["name"] for a in row] == ["Old anchor"] and row[0]["search_id"] is None
        assert s.get_search(1)["down_payment_pct"] is None
        s.update_search(1, down_payment_pct=18)
        assert s.buy_settings(1)["down_payment_pct"] == "18"
    finally:
        s.close()


def _est_detail(source):
    place = {"id": 1, "lat": 41.80, "lng": -87.61}
    anc = [{"id": 1, "name": "UChicago (Ana)", "lat": 41.79, "lng": -87.60}, {"id": 2, "name": "Work", "lat": 41.80, "lng": -87.61}]
    stored = [] if source == "estimate" else [{"anchor_id": 1, "mode": "transit", "minutes": 39, "source": source}]
    ctx = {"anchors": {a["id"]: a for a in anc}, "commutes": stored, "people": 2}
    r = scoring._score_commute({"target": {"mode": "transit", "minutes": 35, "all_anchors": True}}, place, ctx)
    return r["detail"]


def test_saved_time_is_never_called_an_estimate():
    for source, tag in (("ai", "(added by Claude)"), ("you", "(you added)")):
        d = _est_detail(source)
        assert "UChicago (Ana): 39 min " + tag + ", limit 35" in d
        assert "UChicago (Ana)" not in d.split("estimate from the map")[0].split("is an estimate")[-1] or "The time for Work is an estimate" in d
    d = _est_detail("ai")
    assert "The time for Work is an estimate from the map, so check it." in d
    assert "This is an estimate from the map" in _est_detail("estimate") or "is an estimate" in _est_detail("estimate")


def test_place_page_says_also_saved_drive(store):
    s = store.add_search("S", "rent")
    a = store.add_anchor("Office", "o", 41.79, -87.60, search_id=s["id"])
    store.add_criterion(s["id"], "commute", target={"anchor_id": a["id"], "mode": "walk", "minutes": 20})
    p, _ = store.add_place(search_id=s["id"], title="P", address="1 St", lat=41.80, lng=-87.61)
    store.set_commute(p["id"], a["id"], "drive", 4, "ai")
    html = local_client(store).get(f"/places/{p['id']}").text
    assert "Also saved: 4 min drive (added by Claude)" in html
