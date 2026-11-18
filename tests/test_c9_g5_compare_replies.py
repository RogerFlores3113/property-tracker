"""C9 G5: commute mode, people names, compare rows, buyer wording, move-in cash unknowns, per-adult wording, add_place reader line."""
from prophelper import commute, compare, enrich
from mcp_util import call, server, text


def _en(store, s, *pids):
    return [enrich.enrich_places(store, s, [store.get_place(i)])[0] for i in pids]


def _bike_search(store):
    s = store.add_search("UIUC", "rent")
    store.set_current_search(s["id"])
    campus = store.add_anchor("Campus", "x", 40.10, -88.22)
    work = store.add_anchor("Work", "y", 40.12, -88.24)
    store.add_criterion(s["id"], "commute", label="", weight=50, target={"anchor_id": campus["id"], "mode": "bike", "minutes": 20})
    p, _ = store.add_place(search_id=s["id"], title="A", address="1 A St", price=1200, lat=40.11, lng=-88.23)
    return s, campus, work, p


# 1. commute mode
def test_place_without_its_own_rule_follows_the_bike_rule_and_says_so(store, client):
    s, campus, work, p = _bike_search(store)
    e = _en(store, s, p["id"])[0]
    got = {c["anchor"]: c for c in e["commute_all"]}
    assert got["Campus"]["mode"] == "bike" and "assumed" not in got["Campus"]
    assert got["Work"]["mode"] == "bike" and got["Work"]["source"] == "estimate"
    assert got["Work"]["assumed"] == "No commute rule is set for this place, so this uses the way of your other commute rule (bike)."
    html = client.get(f"/places/{p['id']}").text
    assert "drive" not in html.split("Commute:", 1)[1].split("</p>", 1)[0]
    assert "so this uses the way of your other commute rule (bike)" in html
    csv = client.get("/export/places.csv").text if client.get("/export/places.csv").status_code == 200 else ""
    assert "drive (estimate)" not in csv


def test_no_rule_at_all_says_the_fastest_way_is_assumed(store):
    s = store.add_search("S", "rent")
    a = store.add_anchor("Work", "y", 40.12, -88.24)
    p, _ = store.add_place(search_id=s["id"], title="A", address="1 A St", price=1200, lat=40.11, lng=-88.23)
    e = _en(store, s, p["id"])[0]
    assert e["commute_all"][0]["assumed"] == commute.ASSUMED_FASTEST


def test_commute_rule_with_mode_and_minutes_through_claude_tools(store):
    srv = server(store)
    call(srv, "create_search", name="X", mode="rent", anchors=[{"name": "Campus", "lat": 40.1, "lng": -88.22}],
         criteria=[{"kind": "commute", "label": "Campus by bike", "target": {"anchor": "Campus", "mode": "bike", "minutes": 20}}])
    c = next(c for c in store.list_criteria(1) if c["kind"] == "commute")
    assert c["target"]["mode"] == "bike" and c["target"]["minutes"] == 20
    call(srv, "update_search", search_id=1, reweight=[{"id": c["id"], "target": {"anchor": "Campus", "mode": "transit", "minutes": 30}}])
    c = store.get_criterion(c["id"])
    assert c["target"]["mode"] == "transit" and c["target"]["minutes"] == 30
    desc = {t.name: t.description for t in srv._tool_manager.list_tools()}
    assert '"mode": "bike"' in desc["update_search"] and '"mode": "bike"' in desc["create_search"]


# 2. people names
def test_mcp_sets_people_names(store):
    srv = server(store)
    out = text(call(srv, "create_search", name="Trio", mode="rent", people=["Ana", "Ben", "Cam"]))
    s = store.get_search(1)
    assert s["people"] == 3 and s["people_names"] == ["Ana", "Ben", "Cam"] and "People named" in out
    call(srv, "update_search", search_id=1, people_names=["Dee", "Eli", "Fay"])
    assert store.get_search(1)["people_names"] == ["Dee", "Eli", "Fay"]
    call(srv, "create_search", name="Duo", mode="rent", people=2, people_names=["Gus", "Hal"])
    assert store.get_search(2)["people_names"] == ["Gus", "Hal"]


# 3 and 4. compare rows
def test_mcp_compare_has_utilities_pet_limits_and_yard_rows(store):
    s = store.add_search("S", "rent", pet_kind="dog", pet_weight=40)
    store.set_current_search(s["id"])
    a, _ = store.add_place(search_id=s["id"], title="A", address="1 A St", price=1500, utilities_included="heat, water",
                           pets="dogs", pet_weight_limit=50, pet_count_limit=2, fenced_yard=True)
    b, _ = store.add_place(search_id=s["id"], title="B", address="2 B St", price=1400, fenced_yard=False)
    out = text(call(server(store), "compare_places", place_ids=[a["id"], b["id"]]))
    assert "Utilities included:" in out and "heat, water" in out
    assert f"Pet limits (kinds, weight, how many): #{a['id']} Dogs, up to 50 lb, 2 pets at most | #{b['id']} unknown" in out
    assert f"Fenced yard: #{a['id']} Yes | #{b['id']} No" in out


def test_web_compare_and_share_rows_for_pets_and_yard(store):
    s = store.add_search("S", "rent")
    a, _ = store.add_place(search_id=s["id"], title="A", address="1 A St", price=1500, pets="cats", pet_count_limit=1)
    b, _ = store.add_place(search_id=s["id"], title="B", address="2 B St", price=1400)
    rows = compare.build_rows(_en(store, s, a["id"], b["id"]))
    row = {r["key"]: r for sec in rows for r in sec["rows"]}
    assert [c["text"] for c in row["pet_limits"]["cells"]] == ["Cats, 1 pet at most", "unknown"]
    assert "fenced_yard" not in row
    from prophelper import share
    keys = [r["key"] for sec in share.comparison_sections(_en(store, s, a["id"], b["id"])) for r in sec["rows"]]
    assert "pet_limits" in keys


def test_pet_and_yard_rows_show_when_the_search_has_the_criterion(store):
    s = store.add_search("S", "rent")
    store.add_criterion(s["id"], "fenced_yard", label="Fenced yard", weight=30, target={})
    a, _ = store.add_place(search_id=s["id"], title="A", address="1 A St", price=1500)
    b, _ = store.add_place(search_id=s["id"], title="B", address="2 B St", price=1400)
    row = {r["key"]: r for sec in compare.build_rows(_en(store, s, a["id"], b["id"])) for r in sec["rows"]}
    assert "fenced_yard" in row and "pet_limits" not in row


# 5. buyer wording
def test_for_buyer_rewrites_landlord_wording():
    t = "Pets is left empty, so ask the landlord which pets are allowed."
    assert compare.for_buyer(t) == "Pets is left empty, so ask the seller or listing agent which pets are allowed."


def test_special_assessment_note_says_what_to_do(store):
    s = store.add_search("B", "buy")
    p, _ = store.add_place(search_id=s["id"], title="H", address="1 H St", price=300000, special_assessment=5000)
    e = _en(store, s, p["id"])[0]
    note = next(n for n in e["cost"]["notes"] if "special assessment" in n)
    assert note.endswith("not counted. Ask who pays it, then set Who pays on this page.".replace("not counted", "so it is not counted"))


def test_buy_tour_reply_names_seller_not_landlord(store):
    s = store.add_search("B", "buy")
    store.set_current_search(s["id"])
    p, _ = store.add_place(search_id=s["id"], title="H", address="1 H St", price=300000)
    out = text(call(server(store), "add_tour", place_id=p["id"], starts_at="2030-05-01T15:00:00Z"))
    assert "seller or listing agent" in out and "landlord" not in out


# 6. move-in cash
def test_move_in_cash_says_pet_charges_not_known(store):
    s = store.add_search("S", "rent", pet_kind="dog", pet_weight=30)
    store.set_current_search(s["id"])
    p, _ = store.add_place(search_id=s["id"], title="A", address="1 A St", price=1500, deposit=1500, pets="dogs")
    e = _en(store, s, p["id"])[0]
    assert "pet charges" in e["cash_unknown"]
    out = text(call(server(store), "get_place", place_id=p["id"]))
    assert "Cash needed on move-in day: at least $" in out and "; pet charges" in out and "not known yet (" in out


# 7. per adult
def test_family_per_adult_wording_and_roommates_keep_per_person(store, client):
    fam = store.add_search("Fam", "rent", people=4, adults=2)
    store.set_current_search(fam["id"])
    p, _ = store.add_place(search_id=fam["id"], title="A", address="1 A St", price=2298)
    html = client.get(f"/places/{p['id']}").text
    assert "$1,149 each" in html and "for 2 adults" in html and "per person" not in html.split("cost-headline", 1)[1].split("</p>", 1)[0]
    room = store.add_search("Rm", "rent", people=2)
    q, _ = store.add_place(search_id=room["id"], title="B", address="2 B St", price=2298)
    html = client.get(f"/places/{q['id']}").text
    assert "per person" in html and "2 people sharing" in html


# 8. add_place reader line
def test_add_place_says_nothing_about_reader_when_all_fields_were_sent(store):
    srv = server(store)
    s = store.add_search("S", "rent")
    store.set_current_search(s["id"])
    out = text(call(srv, "add_place", title="A", address="1 A St", price=1200, listing_text="Rent $1200 a month. 1 bed 1 bath."))
    assert "found no facts" not in out
    out2 = text(call(srv, "add_place", title="C", address="3 C St", listing_text="Call us."))
    assert "found no facts" in out2


def test_move_in_cash_says_parking_not_known_for_paid_parking(store):
    s = store.add_search("S", "rent")
    store.set_current_search(s["id"])
    p, _ = store.add_place(search_id=s["id"], title="A", address="1 A St", price=1500, deposit=1500, parking="garage")
    q, _ = store.add_place(search_id=s["id"], title="B", address="2 B St", price=1500, deposit=1500)
    assert _en(store, s, p["id"])[0]["cash_unknown"] == ["parking"]
    assert _en(store, s, q["id"])[0]["cash_unknown"] == []
    out = text(call(server(store), "get_place", place_id=p["id"]))
    assert "at least $3,000; parking not known yet" in out
