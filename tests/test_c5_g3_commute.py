"""C5 G3: one commute is shown everywhere, in the way of the commute rule, saved time before an estimate."""
from prophelper import commute, compare, csv_io, enrich, scoring
from mcp_util import call, server, text


def _setup(store):
    s = store.add_search("Chicago", "rent", people=2)
    store.set_current_search(s["id"])
    store.add_criterion(s["id"], "commute", label="", weight=50, target={"all_anchors": True, "mode": "transit", "minutes": 40})
    ana = store.add_anchor("UChicago (Ana)", "x", 41.79, -87.60)
    ben = store.add_anchor("The Loop (Ben)", "y", 41.88, -87.63)
    a, _ = store.add_place(search_id=s["id"], title="A", address="1 A St", price=1500, lat=41.80, lng=-87.62)
    b, _ = store.add_place(search_id=s["id"], title="B", address="2 B St", price=1500, lat=41.81, lng=-87.63)
    store.set_commute(a["id"], ana["id"], "transit", 28, "ai")
    store.set_commute(a["id"], ben["id"], "transit", 12, "ai")
    store.set_commute(b["id"], ana["id"], "transit", 35, "ai")
    store.set_commute(b["id"], ben["id"], "transit", 20, "ai")
    return s, ana, ben, a, b


def _enriched(store, s, *ids):
    return [enrich.enrich_places(store, s, [store.get_place(i)])[0] for i in ids]


def test_everyones_rule_gives_every_anchor_the_rule_mode(store):
    s, ana, ben, a, b = _setup(store)
    e = _enriched(store, s, a["id"])[0]
    got = {c["anchor"]: (c["mode"], c["minutes"], c["source"]) for c in e["commute_all"]}
    assert got == {"UChicago (Ana)": ("transit", 28, "ai"), "The Loop (Ben)": ("transit", 12, "ai")}


def test_compare_row_shows_saved_transit_and_never_a_drive_estimate(client, store):
    s, ana, ben, a, b = _setup(store)
    rows = compare.build_rows(_enriched(store, s, a["id"], b["id"]))
    row = next(r for sec in rows for r in sec["rows"] if r["key"] == f"commute-{ben['id']}")
    assert row["label"] == "To The Loop (Ben) (transit)"
    assert [c["text"] for c in row["cells"]][0].startswith("12 min transit")
    assert row["cells"][0]["best"]
    html = client.get(f"/compare?ids={a['id']},{b['id']}").text
    assert "drive" not in html.split("Commutes", 1)[1].split("</table>", 1)[0].lower()


def test_estimate_of_another_mode_is_never_ranked_against_a_saved_time():
    anchor = {"id": 1, "name": "Work", "lat": 41.9, "lng": -87.6}
    p1 = {"id": 1, "lat": 41.8, "lng": -87.6}
    p2 = {"id": 2, "lat": 41.85, "lng": -87.6}
    saved = [{"anchor_id": 1, "mode": "transit", "minutes": 50, "source": "ai"}]
    first = {"anchor": "Work", "anchor_id": 1, **commute.show_commute(p1, anchor, saved)}
    second = {"anchor": "Work", "anchor_id": 1, **commute.show_commute(p2, anchor, [])}
    assert first["mode"] == "transit" and second["mode"] != "transit" and second["source"] == "estimate"
    rows = compare._commute_rows([{"commute_all": [first]}, {"commute_all": [second]}], [(1, "Work")])
    assert not any(c["best"] for c in rows[0]["cells"])
    assert rows[0]["label"] == "To Work"


def test_show_commute_prefers_saved_over_estimate_with_no_rule():
    anchor = {"id": 1, "name": "Work", "lat": 41.9, "lng": -87.6}
    place = {"id": 1, "lat": 41.8, "lng": -87.6}
    r = commute.show_commute(place, anchor, [{"anchor_id": 1, "mode": "transit", "minutes": 70, "source": "you"}])
    assert r["source"] == "you" and r["minutes"] == 70


def test_csv_has_the_saved_transit_time(store):
    s, ana, ben, a, b = _setup(store)
    e = _enriched(store, s, a["id"])
    out = csv_io.export_csv(e, store.list_anchors(), people=2)
    assert "transit (added by Claude)" in out and "(estimate)" not in out
    assert ",12," in out


def test_mcp_replies_show_saved_transit(store):
    s, ana, ben, a, b = _setup(store)
    srv = server(store)
    for out in (text(call(srv, "list_places")), text(call(srv, "get_place", place_id=a["id"])),
                text(call(srv, "compare_places", place_ids=[a["id"], b["id"]]))):
        lines = [ln for ln in out.splitlines() if ln.startswith("Commutes") or "min transit" in ln and not ln.startswith("Other ways")]
        assert any("12 min transit" in ln for ln in lines)
        assert not any("drive" in ln.lower() for ln in lines)


def test_board_card_shows_each_persons_commute(client, store):
    s, ana, ben, a, b = _setup(store)
    html = client.get("/board").text
    assert "UChicago (Ana) 28 min transit" in html and "The Loop (Ben) 12 min transit" in html


def test_everyones_rule_label_does_not_name_one_person(store):
    s, ana, ben, a, b = _setup(store)
    c = store.list_criteria(s["id"])[0]
    ctx = {"anchors": {x["id"]: x for x in store.list_anchors()}, "people": 2}
    assert scoring._auto_label("commute", c["target"], ctx) == "Transit to everyone's places, 40 min or less"
    e = _enriched(store, s, a["id"])[0]
    assert "Transit to everyone's places, 40 min or less" in [i["label"] for i in e["score"]["items"]]


def test_place_page_nudges_find_on_map_for_an_address_with_no_point(client, store):
    s = store.add_search("S", "rent")
    store.set_current_search(s["id"])
    store.add_anchor("Work", "x", 41.9, -87.6)
    p, _ = store.add_place(search_id=s["id"], title="Pasted", address="9 Z St", price=1500)
    html = client.get(f"/places/{p['id']}").text
    assert "place-find-nudge" in html and f"/places/{p['id']}/geocode" in html
    store.update_place(p["id"], by="you", lat=41.8, lng=-87.6)
    assert "place-find-nudge" not in client.get(f"/places/{p['id']}").text
