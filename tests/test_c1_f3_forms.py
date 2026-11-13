"""Cycle 1, F3: address lookup without the coordinate wall, per-kind criteria, search create keeps its dates."""
import httpx
import pytest

from conftest import local_client
from prophelper import geocode

FOUND = [{"lat": "40.1102", "lon": "-88.2301", "display_name": "Somewhere, Champaign"}]


@pytest.fixture(autouse=True)
def fake_geocode(monkeypatch):
    monkeypatch.setattr(geocode, "_now", lambda: 1000.0)
    monkeypatch.setattr(geocode, "_sleep", lambda s: None)
    monkeypatch.setattr(geocode, "_last_start", [])
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=FOUND)
    monkeypatch.setattr(geocode, "TRANSPORT", httpx.MockTransport(handler))
    return calls


@pytest.fixture
def setup(store):
    s = store.add_search("UIUC", "rent")
    store.set_current_search(s["id"])
    return s


# ---------------------------------------------------------------- lookup opt-in
def test_anchor_find_when_off_explains_and_sends_nothing(store, setup, fake_geocode):
    a = store.add_anchor("Work", "1 Main St, Champaign")
    c = local_client(store)
    r = c.post(f"/anchors/{a['id']}/geocode", data={"search_id": str(setup["id"])})
    assert r.status_code == 200 and "Turn on and find" in r.text and "Not now" in r.text
    assert "sends only the address you typed to OpenStreetMap" in r.text
    assert fake_geocode == [] and store.get_setting_bool("geocode") is False


def test_turn_on_and_find_saves_setting_then_looks_up(store, setup, fake_geocode):
    a = store.add_anchor("Work", "1 Main St, Champaign")
    c = local_client(store)
    r = c.post(f"/anchors/{a['id']}/geocode", data={"search_id": str(setup["id"]), "enable": "1"},
               headers={"Referer": f"http://127.0.0.1:8767/anchors/{a['id']}/geocode"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith(f"/search?id={setup['id']}")
    assert store.get_setting_bool("geocode") is True and len(fake_geocode) == 1
    assert store.get_anchor(a["id"])["lat"] == 40.1102


def test_find_uses_the_address_as_typed_in_the_form(store, setup, fake_geocode):
    a = store.add_anchor("Work", "")
    store.set_setting("geocode", "1")
    c = local_client(store)
    c.post(f"/anchors/{a['id']}/geocode", data={"address": "9 Elm St, Urbana", "search_id": str(setup["id"])})
    assert store.get_anchor(a["id"])["address"] == "9 Elm St, Urbana" and store.get_anchor(a["id"])["lat"] == 40.1102


def test_place_find_when_off_shows_a_message_not_a_silent_redirect(store, setup):
    p, _ = store.add_place(title="Maple", address="410 Maple Row Lane", city="Champaign")
    r = local_client(store).post(f"/places/{p['id']}/geocode", follow_redirects=False)
    assert r.status_code == 200 and "Turn on and find" in r.text


def test_find_buttons_are_always_on_the_page(store, setup):
    store.add_anchor("Work", "1 Main St")
    html = local_client(store).get(f"/search?id={setup['id']}").text
    assert "Find on map from address" in html and "Enter coordinates yourself" in html


def test_saving_an_anchor_without_a_location_says_so(store, setup):
    c = local_client(store)
    r = c.post("/anchors", data={"name": "Work", "address": "1 Main St", "search_id": str(setup["id"])}, follow_redirects=True)
    assert "Commutes need a location" in r.text


def test_duplicate_anchor_name_warns_but_saves(store, setup):
    store.add_anchor("Work")
    r = local_client(store).post("/anchors", data={"name": "work", "search_id": str(setup["id"])}, follow_redirects=True)
    assert "already had one with that name" in r.text and len(store.list_anchors()) == 2


# ---------------------------------------------------------------- criteria
def test_commute_labels_name_the_place_and_differ(store, setup):
    work = store.add_anchor("Office", "", 40.1, -88.2)
    gym = store.add_anchor("Gym", "", 40.11, -88.21)
    c = local_client(store)
    c.post(f"/search/{setup['id']}/criteria", data={"kind": "commute", "t_anchor_id": str(work["id"]), "t_mode": "drive", "t_minutes": "15"})
    c.post(f"/search/{setup['id']}/criteria", data={"kind": "commute", "t_anchor_id": str(gym["id"]), "t_mode": "drive", "t_minutes": "15"})
    labels = [x["label"] for x in store.list_criteria(setup["id"])]
    assert labels == ["Drive to Office, 15 min or less", "Drive to Gym, 15 min or less"]


def test_commute_with_no_place_chosen_uses_the_first_one(store, setup):
    work = store.add_anchor("Office", "", 40.1, -88.2)
    local_client(store).post(f"/search/{setup['id']}/criteria", data={"kind": "commute", "t_mode": "walk", "t_minutes": "10"})
    crit = store.list_criteria(setup["id"])[0]
    assert crit["target"]["anchor_id"] == work["id"] and crit["label"] == "Walk to Office, 10 min or less"


def test_commute_needs_a_place_first(store, setup):
    r = local_client(store).post(f"/search/{setup['id']}/criteria", data={"kind": "commute", "t_minutes": "10"}, follow_redirects=True)
    assert "Add an important place first" in r.text and store.list_criteria(setup["id"]) == []


def test_editing_a_commute_keeps_a_custom_label_and_follows_an_automatic_one(store, setup):
    work = store.add_anchor("Office", "", 40.1, -88.2)
    c = local_client(store)
    c.post(f"/search/{setup['id']}/criteria", data={"kind": "commute", "t_anchor_id": str(work["id"]), "t_mode": "drive", "t_minutes": "15"})
    cid = store.list_criteria(setup["id"])[0]["id"]
    c.post(f"/criteria/{cid}", data={"label": "Drive to Office, 15 min or less", "t_anchor_id": str(work["id"]), "t_mode": "bike", "t_minutes": "20", "weight": "10"})
    assert store.get_criterion(cid)["label"] == "Bike to Office, 20 min or less"
    c.post(f"/criteria/{cid}", data={"label": "My short ride", "t_anchor_id": str(work["id"]), "t_mode": "bike", "t_minutes": "25", "weight": "10"})
    assert store.get_criterion(cid)["label"] == "My short ride"


def test_duplicate_criterion_warns_but_saves(store, setup):
    c = local_client(store)
    c.post(f"/search/{setup['id']}/criteria", data={"kind": "price", "t_max": "1600"})
    r = c.post(f"/search/{setup['id']}/criteria", data={"kind": "price", "t_max": "1600"}, follow_redirects=True)
    assert "already have one just like it" in r.text and len(store.list_criteria(setup["id"])) == 2


def test_add_form_has_one_box_group_per_kind(store, setup):
    html = local_client(store).get(f"/search?id={setup['id']}").text
    assert 'data-kinds="price"' in html and 'data-kinds="commute"' in html and "/static/search.js" in html
    assert "name=\"t_want_laundry\"" in html and "name=\"t_want_parking\"" in html


def test_laundry_choice_reaches_the_target(store, setup):
    local_client(store).post(f"/search/{setup['id']}/criteria", data={"kind": "laundry", "t_want_laundry": "in_building", "t_want_parking": "garage"})
    assert store.list_criteria(setup["id"])[0]["target"] == {"want": "in_building"}


def test_commute_to_a_place_without_a_location_does_not_say_removed(store, setup):
    from prophelper import scoring
    a = store.add_anchor("Office")
    p, _ = store.add_place(title="Flat", address="1 A St", lat=40.1, lng=-88.2)
    crit = {"id": 1, "kind": "commute", "weight": 10, "dealbreaker": 0, "label": "", "target": {"mode": "walk", "minutes": 10}}
    item = scoring.score_criterion(crit, store.get_place(p["id"]), {"anchors": {a["id"]: a}, "commutes": []})
    assert "removed" not in item["detail"] and "no location yet" in item["detail"]
    assert item["label"] == "Walk to Office, 10 min or less"


# ---------------------------------------------------------------- create search
def test_create_search_keeps_move_in_and_target_close(store):
    c = local_client(store)
    c.post("/search", data={"name": "Fall", "mode": "rent", "move_in": "2027-08-15", "budget_max": "1500"})
    c.post("/search", data={"name": "Buy", "mode": "buy", "target_close": "2027-06-30", "budget_max": "300000"})
    by_name = {s["name"]: s for s in store.list_searches()}
    assert by_name["Fall"]["move_in"] == "2027-08-15"
    assert by_name["Buy"]["target_close"] == "2027-06-30"


def test_update_search_keeps_dates(store, setup):
    local_client(store).post(f"/search/{setup['id']}", data={"name": "UIUC", "mode": "rent", "move_in": "2027-08-01"})
    assert store.get_search(setup["id"])["move_in"] == "2027-08-01"


# ---------------------------------------------------------------- privacy copy, nav, plain words
def test_footer_and_privacy_say_the_map_loads_openstreetmap_tiles(client):
    for path in ("/today", "/privacy"):
        html = client.get(path).text
        assert "OpenStreetMap" in html and "plain pins" in html
    assert "street pictures" in client.get("/today").text


def test_privacy_covers_open_in_claude_and_photos_warning(client):
    html = client.get("/privacy").text
    assert "Open in Claude" in html and "claude.ai" in html and "whatever website" in html


def test_settings_warns_next_to_the_photos_setting(client):
    html = client.get("/settings").text
    assert "could point to any site" in html


def test_nav_keeps_six_links_and_groups_the_rest_under_more(client):
    html = client.get("/today").text
    top = html.split('aria-label="Main"')[1].split("</nav>")[0]
    for label in ("Today", "Board", "Map", "Calendar", "Compare"):
        assert f">{label}</a>" in top
    assert "Settings" not in top and "Privacy" not in top and "Connect" not in top
    more = html.split('class="more"')[1].split("</details>")[0]
    for label in ("Settings", "Privacy", "Connect an AI app", "Contacts", "Checklist", "Search"):
        assert label in more
    assert 'href="/add"' in html


def test_search_page_uses_plain_words(store, setup):
    import re
    html = re.sub(r"<[^>]+>", " ", local_client(store).get(f"/search?id={setup['id']}").text).lower()  # visible words only
    for word in ("deal-breaker", "criterion", "criteria", "nominatim", "anchor", " weight"):
        assert word not in html, word
    assert "must have" in html and "how much it matters" in html and "important places" in html


def test_start_files_and_readme_say_keep_the_window_open():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    for name in ("Start Property Helper.command", "Start Property Helper.bat"):
        text = (root / name).read_text()
        assert "Keep this window open while you use it. Close it to stop." in text and "Property Helper is running" in text
    readme = (root / "README.md").read_text()
    assert readme.index("Get started") < readme.index("What it does") < readme.index("Use it with Claude") < readme.index("## Advanced")
    assert "Other AI apps and more" not in (root / "INSTALL.md").read_text()


def test_connect_page_puts_the_simple_path_first_and_mcp_only_in_the_fold(client):
    html = client.get("/connect").text
    assert html.index("Connect the Claude app") < html.index("Other apps and details")
    before_fold = html.split('id="other-apps"')[0]
    assert "STDIO" not in before_fold and "MCP" not in before_fold
