"""Every page renders, and the core actions work through the web layer."""
import re

import pytest


def _made_search(client, store, mode="rent"):
    return store.add_search("Test search", mode, budget_max=1600)


# ---- every page renders (empty, then with sample data)
EMPTY_PAGES = ["/today", "/board", "/search", "/add", "/settings", "/privacy", "/backups", "/connect", "/skills"]
PLACE_PAGES = ["/today", "/board", "/board?show_hidden=1", "/search", "/search?id=1", "/add", "/add?manual=1"]


@pytest.mark.parametrize("path", EMPTY_PAGES)
def test_pages_render_on_an_empty_install(client, path):
    r = client.get(path)
    assert r.status_code == 200 and "Property Helper" in r.text


def test_first_run_today_is_friendly(client):
    html = client.get("/today").text
    assert "Welcome to Property Helper" in html and "sample data" in html.lower()
    assert 'action="/sample-data"' in html


@pytest.mark.parametrize("path", PLACE_PAGES)
def test_pages_render_with_sample_data(client, sample_store, path):
    assert client.get(path).status_code == 200


def test_every_sample_place_page_renders(client, sample_store):
    for p in sample_store.list_places(include_archived=True):
        r = client.get(f"/places/{p['id']}")
        assert r.status_code == 200, p["title"]


def test_nav_labels(client):
    html = client.get("/today").text
    for label in ("Today", "Board", "Map", "Calendar", "Compare", "Contacts", "Search", "Add", "Settings"):
        assert f">{label}<" in html


def test_privacy_lists_the_network_calls(client):
    html = client.get("/privacy").text
    assert "tile.openstreetmap.org" in html and "nominatim.openstreetmap.org" in html and "api.anthropic.com" in html
    assert "Open in Claude" in html and "Listing photos" in html and "Off until you turn them on" in html


def test_settings_has_its_sections(client):
    html = client.get("/settings").text
    for name in ("Your data", "Map and lookups", "AI key and model", "On screen", "Sample data", "Stricter rules when Claude reads websites for you"):
        assert name in html


def test_settings_save_and_sample_buttons(client, store):
    r = client.post("/settings", data={"follow_up_days": "5", "map_tiles": "0", "geocode": "1"}, follow_redirects=False)
    assert r.status_code == 303
    assert store.get_setting_int("follow_up_days") == 5 and store.get_setting_bool("geocode") and not store.get_setting_bool("map_tiles")
    assert client.post("/settings", data={"follow_up_days": "0"}, follow_redirects=False).status_code == 303
    assert store.get_setting_int("follow_up_days") == 5  # a bad value is refused
    client.post("/sample-data")
    assert store.has_sample_data()
    client.post("/sample-data/remove")
    assert not store.has_sample_data()


def test_strict_scraping_switch(client, store):
    client.post("/settings/strict-scraping", data={"on": "1"})
    assert store.get_setting_bool("strict_scraping")


def test_ai_key_is_never_shown(client):
    client.post("/settings/ai-key", data={"key": "sk-ant-secret-1234567890"})
    html = client.get("/settings").text
    assert "secret" not in html and "7890" in html
    client.post("/settings/ai-key/remove")
    assert "No key set" in client.get("/settings").text


# ---- Board
def test_board_has_a_column_per_stage_and_hides_dealbreakers(client, sample_store):
    sample_store.update_search(sample_store.current_search()["id"], hide_dealbreakers=True)  # off by default now
    html = client.get("/board").text
    for stage in ("Saved", "Contacted", "Tour booked", "Toured", "Applied", "Approved", "Lease signed", "Passed"):
        assert f'data-stage="{stage}"' in html
    assert "Show hidden" in html and "miss a must have" in html
    shown = client.get("/board?show_hidden=1").text
    assert shown.count('class="card kcard"') > html.count('class="card kcard"')
    assert "Hide them again" in shown


def test_board_buy_search_uses_buy_columns(client, store):
    store.add_search("Buying", "buy")
    store.add_place(title="House", address="5 Home Rd")
    html = client.get("/board").text
    assert 'data-stage="Under contract"' in html and 'data-stage="Tour booked"' not in html


def test_stage_move_via_form_and_json(client, store):
    _made_search(client, store)
    p, _ = store.add_place(title="A", address="1 A St")
    r = client.post(f"/places/{p['id']}/stage", data={"stage": "Toured"}, follow_redirects=False)
    assert r.status_code == 303 and store.get_place(p["id"])["stage"] == "Toured"
    r = client.post(f"/places/{p['id']}/stage", data={"stage": "Contacted"}, headers={"HX-Request": "true"})
    assert r.json()["ok"] and store.get_place(p["id"])["stage"] == "Contacted"
    r = client.post(f"/places/{p['id']}/stage", data={"stage": "Nowhere"}, headers={"HX-Request": "true"})
    assert r.status_code == 400 and not r.json()["ok"]
    assert client.post("/places/999/stage", data={"stage": "Toured"}).status_code == 404


# ---- Place page
def test_place_page_shows_cost_score_commutes_timeline(client, sample_store):
    pid = next(p["id"] for p in sample_store.list_places() if p["title"].startswith("Silo Yard"))
    html = client.get(f"/places/{pid}").text
    assert "What it really costs" in html and "Not counted yet because it is missing" in html
    assert "Fit score" in html and "Commutes" in html and "Timeline" in html
    assert 'name="minutes"' in html and "(estimate)" in html


def test_place_edit_saves_and_validates(client, store):
    _made_search(client, store)
    p, _ = store.add_place(title="A", address="1 A St", price=1000)
    r = client.post(f"/places/{p['id']}", data={"title": "A", "address": "1 A St", "price": "1,250", "beds": "2",
                                                "laundry": "in_unit", "notes": "my note"}, follow_redirects=False)
    assert r.status_code == 303
    got = store.get_place(p["id"])
    assert got["price"] == 1250 and got["beds"] == 2 and got["laundry"] == "in_unit" and got["notes"] == "my note"
    bad = client.post(f"/places/{p['id']}", data={"title": "A", "price": "lots"})
    assert bad.status_code == 400 and "lots" in bad.text
    assert store.get_place(p["id"])["price"] == 1250


def test_place_cost_breakdown_updates_after_edit(client, store):
    _made_search(client, store)
    p, _ = store.add_place(title="A", address="1 A St", price=1000)
    client.post(f"/places/{p['id']}", data={"title": "A", "address": "1 A St", "price": "1000", "utilities_estimate": "100"})
    html = client.get(f"/places/{p['id']}").text
    assert "$1,100.00" in html


def test_add_note_to_timeline(client, store):
    _made_search(client, store)
    p, _ = store.add_place(title="A", address="1 A St")
    client.post(f"/places/{p['id']}/note", data={"body": "Called, voicemail", "kind": "call"})
    assert "Called, voicemail" in client.get(f"/places/{p['id']}").text
    r = client.post(f"/places/{p['id']}/note", data={"body": "  "}, follow_redirects=False)
    assert r.status_code == 303 and len(store.list_events(p["id"])) == 2  # added + the empty one refused


def test_commute_minutes_are_editable(client, store):
    _made_search(client, store)
    a = store.add_anchor("Work", "1 Main", 40.1, -88.2)
    p, _ = store.add_place(title="A", address="1 A St", lat=40.11, lng=-88.21)
    client.post(f"/places/{p['id']}/commute", data={"anchor_id": a["id"], "mode": "bike", "minutes": "14"})
    assert store.list_commutes(p["id"])[0]["minutes"] == 14
    assert "14 min" in client.get(f"/places/{p['id']}").text
    client.post(f"/places/{p['id']}/commute/clear", data={"anchor_id": a["id"], "mode": "bike"})
    assert store.list_commutes(p["id"]) == []


def test_custom_score(client, store):
    s = _made_search(client, store)
    c = store.add_criterion(s["id"], "custom", label="Natural light", weight=10)
    p, _ = store.add_place(title="A", address="1 A St")
    client.post(f"/places/{p['id']}/custom-score", data={"criterion_id": c["id"], "score": "4"})
    assert store.custom_scores(p["id"])[c["id"]] == 4
    assert "Natural light" in client.get(f"/places/{p['id']}").text


def test_hide_archive_and_delete_with_confirm(client, store):
    _made_search(client, store)
    p, _ = store.add_place(title="A", address="1 A St")
    client.post(f"/places/{p['id']}/hide", data={"on": "1"})
    assert store.get_place(p["id"])["hidden"]
    client.post(f"/places/{p['id']}/archive")
    assert store.count_places() == 0
    client.post(f"/places/{p['id']}/unarchive")
    assert store.count_places() == 1
    r = client.post(f"/places/{p['id']}/delete", data={}, follow_redirects=False)  # no tick box: nothing happens
    assert r.status_code == 303 and store.count_places() == 1
    r = client.post(f"/places/{p['id']}/delete", data={"confirm": "yes"}, follow_redirects=False)
    assert r.status_code == 303 and store.count_places(include_archived=True) == 0


def test_delete_takes_a_backup_first(client, store):
    from prophelper import backups

    _made_search(client, store)
    p, _ = store.add_place(title="A", address="1 A St")
    client.post(f"/places/{p['id']}/delete", data={"confirm": "yes"})
    assert backups.list_backups()


# ---- Search page
def test_create_switch_edit_search(client, store):
    r = client.post("/search", data={"name": "First", "mode": "rent", "area": "Here", "budget_max": "1500"}, follow_redirects=False)
    assert r.status_code == 303
    first = store.current_search()
    assert first["name"] == "First" and first["budget_max"] == 1500
    client.post("/search", data={"name": "House hunt", "mode": "buy", "target_close": "2027-05-01"})
    assert store.current_search()["mode"] == "buy"
    client.post(f"/search/{first['id']}/switch")
    assert store.current_search()["id"] == first["id"]
    client.post(f"/search/{first['id']}", data={"name": "Renamed", "mode": "rent", "hide_dealbreakers": "0"})
    got = store.get_search(first["id"])
    assert got["name"] == "Renamed" and not got["hide_dealbreakers"]
    assert "Renamed" in client.get("/search").text
    assert client.post("/search", data={"name": "", "mode": "rent"}, follow_redirects=False).status_code == 303
    assert len(store.list_searches()) == 2


def test_criteria_editor(client, store):
    s = _made_search(client, store)
    client.post(f"/search/{s['id']}/criteria", data={"kind": "price", "weight": "30", "dealbreaker": "1", "t_max": "1500"})
    client.post(f"/search/{s['id']}/criteria", data={"kind": "laundry", "weight": "20", "t_want": "in_unit"})
    crit = store.list_criteria(s["id"])
    assert [c["kind"] for c in crit] == ["price", "laundry"] and crit[0]["dealbreaker"] and crit[0]["target"] == {"max": 1500}
    client.post(f"/criteria/{crit[0]['id']}", data={"label": "Rent cap", "weight": "50", "t_max": "1400"})
    got = store.get_criterion(crit[0]["id"])
    assert got["weight"] == 50 and got["label"] == "Rent cap" and got["target"]["max"] == 1400 and not got["dealbreaker"]
    html = client.get(f"/search?id={s['id']}").text
    assert "Rent cap" in html
    client.post(f"/criteria/{crit[1]['id']}/delete")
    assert len(store.list_criteria(s["id"])) == 1
    client.post(f"/search/{s['id']}/criteria", data={"kind": "bogus"})
    assert len(store.list_criteria(s["id"])) == 1


def test_criteria_change_scores(client, store):
    s = _made_search(client, store)
    p, _ = store.add_place(title="A", address="1 A St", price=2000)
    client.post(f"/search/{s['id']}/criteria", data={"kind": "price", "weight": "10", "t_max": "1500"})
    low = client.get(f"/places/{p['id']}").text
    client.post(f"/criteria/{store.list_criteria(s['id'])[0]['id']}", data={"weight": "10", "t_max": "2500"})
    high = client.get(f"/places/{p['id']}").text
    assert low != high and "under your limit" in high


def test_anchors_editor(client, store):
    s = _made_search(client, store)
    client.post("/anchors", data={"name": "Work", "address": "1 Main", "lat": "40.1", "lng": "-88.2", "search_id": s["id"]})
    a = store.list_anchors()[0]
    assert a["lat"] == 40.1
    client.post(f"/anchors/{a['id']}", data={"name": "Office", "address": "1 Main", "lat": "40.2", "lng": "-88.2"})
    assert store.list_anchors()[0]["name"] == "Office"
    client.post(f"/anchors/{a['id']}/delete")
    assert store.list_anchors() == []


def test_archive_and_delete_search(client, store):
    s = _made_search(client, store)
    client.post(f"/search/{s['id']}/archive")
    assert store.list_searches() == []
    client.post(f"/search/{s['id']}/unarchive")
    store.add_place(title="A", address="1 A St")
    r = client.post(f"/search/{s['id']}/delete", data={}, follow_redirects=False)
    assert r.status_code == 303 and store.list_searches()
    client.post(f"/search/{s['id']}/delete", data={"confirm": "yes"})
    assert store.list_searches(include_archived=True) == [] and store.count_places(include_archived=True) == 0


# ---- Add page
def test_add_needs_a_search_first(client):
    assert "Make a search first" in client.get("/add").text


def test_add_from_paste_fills_the_form_then_saves(client, store):
    _made_search(client, store)
    text = ("Sunny 2 bedroom, 1 bath, 850 sq ft. $1,850 a month. In-unit washer/dryer. Cats ok. "
            "Deposit $1,850. 123 Oak Street, Champaign, IL")
    r = client.post("/add/parse", data={"text": text, "url": "https://www.example.com/listing/9"})
    assert r.status_code == 200
    assert re.search(r'name="price" value="1850(\.0)?"', r.text) and 'name="beds" value="2' in r.text
    assert "123 Oak Street" in r.text and "Check it" in r.text
    form = {"title": "Oak Street 2BR", "address": "123 Oak Street", "price": "1850", "beds": "2", "laundry": "in_unit",
            "url": "https://www.example.com/listing/9", "listing_text": text}
    r = client.post("/add/save", data=form, follow_redirects=False)
    assert r.status_code == 303
    p = store.list_places()[0]
    assert r.headers["location"] == f"/places/{p['id']}" and p["price"] == 1850 and p["listing_text"].startswith("Sunny")
    # saving it again does not make a second one
    again = client.post("/add/save", data=form, follow_redirects=False)
    assert again.headers["location"] == f"/places/{p['id']}" and store.count_places() == 1


def test_add_with_nothing_pasted_asks_for_something(client, store):
    _made_search(client, store)
    r = client.post("/add/parse", data={"text": "", "url": ""})
    assert r.status_code == 400 and "Paste a link" in r.text


def test_add_link_only_still_saves(client, store):
    _made_search(client, store)
    r = client.post("/add/parse", data={"url": "https://www.example.com/x/77"})
    assert r.status_code == 200
    client.post("/add/save", data={"url": "https://www.example.com/x/77", "title": ""})
    assert store.count_places() == 1


def test_add_manual_form_and_bad_number(client, store):
    _made_search(client, store)
    assert client.get("/add?manual=1").status_code == 200
    r = client.post("/add/save", data={"title": "X", "price": "cheap"})
    assert r.status_code == 400 and store.count_places() == 0


def test_text_is_escaped_everywhere(client, store):
    s = _made_search(client, store)
    store.add_criterion(s["id"], "custom", label="<img src=x onerror=alert(1)>")
    p, _ = store.add_place(title="<script>alert(1)</script>", address="1 A St", notes="<b>x</b>")
    for path in ("/board", f"/places/{p['id']}", "/today", "/search"):
        assert "<script>alert(1)" not in client.get(path).text
        assert "<img src=x" not in client.get(path).text
