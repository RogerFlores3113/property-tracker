"""Cycle 7, group G4: polish (closing countdown, create form, people labels, overview, import preview, money, CSV link, folder mode)."""
import os
import re
import stat
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

from conftest import local_client
from prophelper import helpers
from prophelper.store import people_slots


def _buy(store, close=None, **kw):
    return store.add_search("Buy", "buy", target_close=close or "", **kw)


def _place(store, sid, stage=None, **kw):
    kw.setdefault("title", "House")
    p, _ = store.add_place(search_id=sid, price=400000, **({"stage": stage} if stage else {}), **kw)
    return p


# ---- 1. closing days
def test_closing_info_future_today_past():
    t = date(2026, 11, 13)
    s = {"mode": "buy", "target_close": "2027-02-15"}
    i = helpers.closing_info(s, t)
    assert i["place_line"] == "Closing in 94 days (Feb 15, 2027)"
    assert i["today_line"] == "Closing target: Feb 15, 2027, in 94 days"
    assert helpers.closing_info({"mode": "buy", "target_close": "2026-11-10"}, t)["place_line"] == "Closing target was 3 days ago (Nov 10, 2026)"
    assert helpers.closing_info({"mode": "buy", "target_close": "2026-11-14"}, t)["place_line"].startswith("Closing tomorrow")
    assert helpers.closing_info({"mode": "rent", "target_close": "2027-02-15"}, t) is None
    assert helpers.closing_info({"mode": "buy", "target_close": ""}, t) is None


def test_place_page_and_today_show_closing(store):
    c = local_client(store)
    day = (date.today() + timedelta(days=30)).isoformat()
    s = _buy(store, day)
    store.set_current_search(s["id"])
    p = _place(store, s["id"])
    html = c.get(f"/places/{p['id']}").text
    assert '<p id="closing-days" class="fine">Closing in 30 days' in html
    today = c.get("/").text
    assert "Closing target:" in today and "in 30 days" in today


def test_closing_prominent_from_offer_and_hidden_for_rent_or_passed(store):
    c = local_client(store)
    s = _buy(store, (date.today() + timedelta(days=5)).isoformat())
    p = _place(store, s["id"], stage="Offer made")
    html = c.get(f"/places/{p['id']}").text
    assert re.search(r'<p id="closing-days" class="flash"><strong>Closing in 5 days', html)
    q = _place(store, s["id"], stage="Passed", title="Old")
    assert 'id="closing-days"' not in c.get(f"/places/{q['id']}").text
    r = store.add_search("Rent", "rent")
    rp, _ = store.add_place(search_id=r["id"], title="Flat", price=1000)
    assert 'id="closing-days"' not in c.get(f"/places/{rp['id']}").text


# ---- 2. create form down payment
def test_create_form_has_down_payment_for_buying_and_saves_it(store):
    c = local_client(store)
    html = c.get("/search").text
    assert 'name="down_payment_pct"' in html and "data-buy-only" in html
    c.post("/search", data={"name": "H", "mode": "buy", "down_payment_pct": "15"}, follow_redirects=False)
    assert store.list_searches()[0]["down_payment_pct"] == 15
    js = (Path(__file__).parent.parent / "src/prophelper/static/search.js").read_text()
    assert "data-buy-only" in js


# ---- 3. people names
def test_unnamed_seat_keeps_its_number_and_opinions_follow_rename(store):
    s = store.add_search("S", "rent", people=3)
    assert people_slots(store.get_search(s["id"])) == ["Person 1", "Person 2", "Person 3"]
    p, _ = store.add_place(search_id=s["id"], title="A", price=1000)
    store.set_opinion(p["id"], "Person 1", 4, "nice")
    store.update_search(s["id"], people_names="Sam, Priya")
    assert people_slots(store.get_search(s["id"])) == ["Sam", "Priya", "Person 3"]
    slots = store.opinion_slots(p["id"])
    assert slots[0]["person"] == "Sam" and slots[0]["rating"] == 4


def test_place_page_uses_names(store):
    c = local_client(store)
    s = store.add_search("S", "rent", people=3, people_names="Sam, Priya, Lee")
    p, _ = store.add_place(search_id=s["id"], title="A", price=1000)
    html = c.get(f"/places/{p['id']}").text
    assert "Sam's rating" in html and "Lee's note" in html and "Person 1" not in html


# ---- 4. overview
def test_overview_without_area_leaves_it_out(store):
    from mcp_util import call, server, text
    srv = server(store)
    call(srv, "create_search", name="No area", mode="rent", budget_max=1500)
    out = text(call(srv, "get_overview"))
    assert "no area" not in out and "budget $1,500" in out


# ---- 5. import preview
def _post(client, doc):
    import json
    return client.post("/searches/import", files={"file": ("s.json", json.dumps(doc), "application/json")})


def test_preview_text_counts_and_plurals(store):
    from prophelper import share
    doc = {"search": {"name": "X", "mode": "rent"}, "places": [{}, {}], "criteria": [{}], "anchors": [{}, {}]}
    assert share.preview_text(doc, 2, {}) == "Adds the search 'X (imported)' (renting) with 2 places, 1 thing that matters and 2 important places."
    one = {"search": {"name": "X", "mode": "buy"}, "places": [{}], "criteria": [{}, {}], "anchors": [{}]}
    assert share.preview_text(one, 1, {}) == "Adds the search 'X (imported)' (buying) with 1 place, 2 things that matter and 1 important place."
    t = share.preview_text(doc, 0, {"places_skipped": 3, "criteria_skipped": 0, "anchors_skipped": 1})
    assert t.startswith("Adds the search 'X (imported)' (renting) but no places, 1 thing that matters and 1 important place.")
    assert "All 3 places can't be read, so none will be added." in t
    t = share.preview_text(doc, 2, {"places_skipped": 1})
    assert t.endswith("1 place can't be read and will be left out.")
    assert "The file has no places." in share.preview_text({**doc, "places": []}, 0, {})


def test_import_preview_page_and_dropped_anchor_note(client, store):
    import json
    s = store.add_search("Src", "rent")
    doc = json.loads(client.get(f"/search/export.json?id={s['id']}").content)
    doc["anchors"].append({"name": "Work", "address": "1 Main St", "lat": 40.1, "lng": -88.2})
    doc["anchors"].append({"name": "Gym", "address": "", "lat": 999, "lng": 5})
    doc["places"] = [{"title": "Good", "price": 1000}, "not a place"]
    r = _post(client, doc)
    assert r.status_code == 200
    assert "with 1 place, 0 things that matter and 1 important place." in r.text
    assert "The important place &#39;Gym&#39; has coordinates that can&#39;t be used, so it will be left out." in r.text
    assert "can&#39;t be read and will be left out" in r.text


# ---- 6. money
def test_place_page_money_has_no_cents(store):
    c = local_client(store)
    s = store.add_search("S", "rent")
    p, _ = store.add_place(search_id=s["id"], title="A", price=1500.83, hoa=0.0)
    html = c.get(f"/places/{p['id']}").text
    assert "$1,501" in html and "$1,500.83" not in html
    assert not re.search(r"\$[\d,]+\.\d\d", html.split('id="cost"')[1].split("</section>")[0])


def test_compare_money_has_no_cents(store):
    c = local_client(store)
    s = store.add_search("S", "rent")
    ids = [store.add_place(search_id=s["id"], title=t, price=1500.83)[0]["id"] for t in "AB"]
    html = c.get("/compare?ids=" + ",".join(map(str, ids))).text
    assert "$1,500.83" not in html


# ---- 7. spreadsheet link
def test_csv_link_on_search_page_and_board(store):
    c = local_client(store)
    s = store.add_search("S", "rent")
    store.set_current_search(s["id"])
    store.add_place(search_id=s["id"], title="A", price=1000)
    for page in ("/search", "/board"):
        html = c.get(page).text
        assert "Download spreadsheet (CSV)" in html and f"/places.csv?search_id={s['id']}" in html
    r = c.get(f"/places.csv?search_id={s['id']}")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")


# ---- 8. data folder mode on a real first run
def _mode(p):
    return stat.S_IMODE(p.stat().st_mode)


@pytest.mark.skipif(sys.platform == "win32", reason="Windows has no POSIX file modes or umask")
def test_first_run_makes_the_data_folder_700_in_process(tmp_path, monkeypatch):
    from prophelper import paths
    target = tmp_path / "fresh" / "PropertyHelper"
    monkeypatch.setenv("PROPHELPER_DATA_DIR", str(target))
    old = os.umask(0)
    try:
        d = paths.data_dir()
        db = paths.db_path()
    finally:
        os.umask(old)
    assert _mode(d) == 0o700 and _mode(db.parent) == 0o700


@pytest.mark.skipif(sys.platform == "win32", reason="Windows has no POSIX file modes or umask")
def test_real_first_run_command_creates_folder_700_and_database_600(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    env = {k: v for k, v in os.environ.items() if k != "PROPHELPER_DATA_DIR"}
    env.update(HOME=str(home), XDG_DATA_HOME=str(home / "share"), PROPHELPER_NO_BROWSER="1")
    code = "import os; os.umask(0); from prophelper.cli import main; main(['sample-data'])"
    subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, timeout=120)
    folders = [p for p in (home / "share").rglob("*") if p.is_dir() and (p / "prophelper.db").exists()] if (home / "share").exists() else []
    assert folders, "the first run did not create the data folder"
    assert _mode(folders[0]) == 0o700
    assert _mode(folders[0] / "prophelper.db") == 0o600
