"""The map page: pins, rings, tiles setting, the no-location list, and safe data handoff to the script."""
import json
import re

import pytest

from prophelper import mapdata


def _page_data(html: str) -> dict:
    m = re.search(r'<script type="application/json" id="map-data">(.*?)</script>', html, re.S)
    assert m, "the page data tag is missing"
    return json.loads(m.group(1))


# ---- mapdata (pure)
def _enriched(**kw):
    base = {"id": 1, "title": "A", "lat": 40.1, "lng": -88.2, "cost_total": 1495.0, "score_total": 80, "band": "good", "stage": "Saved"}
    base.update(kw)
    return base


def test_label_is_true_monthly_cost():
    assert mapdata.label_for(_enriched()) == "$1,495"
    assert mapdata.label_for(_enriched(cost_total=None)) == "?"


def test_build_splits_located_and_unlocated_and_measures_miles():
    anchor = {"id": 7, "name": "Campus", "lat": 40.1074, "lng": -88.2272}
    out = mapdata.build([_enriched(), _enriched(id=2, title="B", lat=None, lng=None)], [anchor], tiles=False, anchor=anchor)
    assert [p["title"] for p in out["unlocated"]] == ["B"]
    assert out["located"][0]["miles"] is not None and out["located"][0]["miles"] < 2
    assert out["data"]["ring"] == {"anchorId": 7, "lat": 40.1074, "lng": -88.2272, "miles": [1, 2, 3]}
    assert out["data"]["tiles"] is False and out["data"]["places"][0]["label"] == "$1,495"


def test_pick_anchor_prefers_the_asked_one_and_zero_means_none():
    a = {"id": 1, "name": "A", "lat": 1.0, "lng": 1.0}
    b = {"id": 2, "name": "B", "lat": 2.0, "lng": 2.0}
    nopoint = {"id": 3, "name": "C", "lat": None, "lng": None}
    assert mapdata.pick_anchor([a, b], 2) == b
    assert mapdata.pick_anchor([a, b], None) == a
    assert mapdata.pick_anchor([nopoint, b], 3) == b  # an anchor with no point can't center rings
    assert mapdata.pick_anchor([a, b], 0) is None
    assert mapdata.pick_anchor([nopoint], None) is None


def test_build_with_nothing_centers_somewhere_sane():
    out = mapdata.build([], [], tiles=True, anchor=None)
    assert out["data"]["ring"] is None and len(out["data"]["center"]) == 2


# ---- the page
def test_map_renders_empty_and_with_sample(client, sample_store):
    assert client.get("/map").status_code == 200


def test_map_without_a_search(client):
    r = client.get("/map")
    assert r.status_code == 200 and "No search yet" in r.text


def test_map_has_pins_anchor_and_rings(client, sample_store):
    html = client.get("/map").text
    data = _page_data(html)
    titles = [p["title"] for p in data["places"]]
    assert "Maple Row Flats" in titles and "The Elm Street House" not in titles  # no map point
    assert data["anchors"] and data["ring"]["miles"] == [1, 2, 3]
    assert all(p["label"].startswith("$") or p["label"] == "?" for p in data["places"])
    assert {p["band"] for p in data["places"]} <= {"good", "ok", "low", "none"}
    assert "The Elm Street House" in html and 'action="/places/' in html and "/location" in html  # in the no-location list


def test_map_is_a_usable_list_without_javascript(client, sample_store):
    html = client.get("/map").text
    assert "Places on the map" in html and "mi from" in html and "<noscript>" in html


def test_ring_choice_and_no_rings(client, sample_store):
    anchor_id = sample_store.list_anchors()[0]["id"]
    assert _page_data(client.get(f"/map?anchor={anchor_id}").text)["ring"]["anchorId"] == anchor_id
    assert _page_data(client.get("/map?anchor=0").text)["ring"] is None


def test_tiles_on_and_off(client, sample_store):
    sample_store.set_setting("map_tiles", "1")
    on = client.get("/map").text
    data = _page_data(on)
    assert data["tiles"] is True and data["tileUrl"] == "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
    assert "OpenStreetMap" in data["attribution"] and "Show map pictures" not in on
    sample_store.set_setting("map_tiles", "0")
    off = client.get("/map").text
    assert _page_data(off)["tiles"] is False
    assert "Show street map (loads map pictures from OpenStreetMap)" in off


def test_find_on_map_button_is_always_shown(client, sample_store):
    assert "/geocode" in client.get("/map").text  # lookup stays opt-in, but the button is always there
    sample_store.set_setting("geocode", "1")
    html = client.get("/map").text
    elm = next(p for p in sample_store.list_places() if p["title"] == "The Elm Street House")
    assert f'action="/places/{elm["id"]}/geocode"' in html and "Find on map" in html


def test_page_uses_local_leaflet_and_no_inline_script_or_cdn(client, sample_store):
    html = client.get("/map").text
    assert "/static/vendor/leaflet/leaflet.js" in html and "/static/map.js" in html
    assert "unpkg" not in html and "cdn" not in html.lower()
    for tag in re.findall(r"<script\b([^>]*)>", html):
        assert "src=" in tag or 'type="application/json"' in tag, tag  # no executable inline script
    csp = client.get("/map").headers["content-security-policy"]
    assert "script-src 'self'" in csp and "unsafe-inline" not in csp.split("script-src")[1].split(";")[0]


def test_hostile_titles_cannot_break_out_of_the_data_tag(client, store):
    s = store.add_search("S", "rent")
    store.set_current_search(s["id"])
    store.add_place(search_id=s["id"], title='</script><script>alert(1)</script><!--"', lat=40.1, lng=-88.2, price=1000)
    html = client.get("/map").text
    assert "</script><script>alert" not in html and "<script>alert" not in html
    assert _page_data(html)["places"][0]["title"] == '</script><script>alert(1)</script><!--"'  # the data survives intact


def test_hidden_places_are_left_out_unless_asked(client, sample_store):
    p = next(p for p in sample_store.list_places() if p["title"] == "Maple Row Flats")
    sample_store.update_place(p["id"], hidden=True)
    assert "Maple Row Flats" not in [x["title"] for x in _page_data(client.get("/map").text)["places"]]
    shown = client.get("/map?show_hidden=1").text
    assert "Maple Row Flats" in [x["title"] for x in _page_data(shown)["places"]]


# ---- saving a location
def test_save_location(client, sample_store):
    elm = next(p for p in sample_store.list_places() if p["title"] == "The Elm Street House")
    r = client.post(f"/places/{elm['id']}/location", data={"lat": "40.1130", "lng": "-88.2250"}, follow_redirects=False)
    assert r.status_code == 303
    got = sample_store.get_place(elm["id"])
    assert (got["lat"], got["lng"]) == (40.113, -88.225)
    assert "The Elm Street House" in [p["title"] for p in _page_data(client.get("/map").text)["places"]]


@pytest.mark.parametrize("data", [{"lat": "", "lng": "1"}, {"lat": "95", "lng": "1"}, {"lat": "1", "lng": "-200"}, {"lat": "abc", "lng": "1"}])
def test_save_location_rejects_bad_numbers(client, sample_store, data):
    elm = next(p for p in sample_store.list_places() if p["title"] == "The Elm Street House")
    r = client.post(f"/places/{elm['id']}/location", data=data, follow_redirects=False)
    assert r.status_code == 303 and sample_store.get_place(elm["id"])["lat"] is None


def test_save_location_for_a_missing_place_is_404(client):
    assert client.post("/places/999/location", data={"lat": "1", "lng": "1"}).status_code == 404


def test_map_js_exists_and_is_valid():
    import shutil
    import subprocess
    from pathlib import Path

    js = Path(__file__).parent.parent / "src" / "prophelper" / "static" / "map.js"
    assert js.is_file()
    text = js.read_text()
    assert "innerHTML" not in text  # user text is only written with textContent
    if shutil.which("node"):
        assert subprocess.run(["node", "--check", str(js)], capture_output=True).returncode == 0
