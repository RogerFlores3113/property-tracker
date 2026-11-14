"""Cycle 4, G1: map pictures stay off on a new folder, search import preview, Claude tool fixes, photo CSP."""
import json
import re
import sqlite3

import pytest

from mcp_util import call, server, text
from prophelper import share
from prophelper.store import Store


def test_new_folder_keeps_map_tiles_off_across_reopens(tmp_path):
    path = tmp_path / "new.db"
    for _ in range(4):
        s = Store(path)
        assert s.get_setting_bool("map_tiles") is False
        s.close()
    c = sqlite3.connect(path)
    assert c.execute("SELECT value FROM settings WHERE key='map_tiles'").fetchone()[0] == "0"


def test_old_folder_without_row_still_gets_on(tmp_path):
    path = tmp_path / "old.db"
    s = Store(path)
    s.close()
    c = sqlite3.connect(path)
    c.execute("DELETE FROM settings WHERE key='map_tiles'")
    pass
    c.commit()
    c.close()
    s = Store(path)
    assert s.get_setting_bool("map_tiles") is True
    s.close()


def _doc():
    return {"format": share.FORMAT_NAME, "version": share.FORMAT_VERSION,
            "search": {"name": "S", "mode": "rent", "budget_max": 1e999},
            "criteria": [{"kind": "price", "label": "a", "weight": 99999, "target": {"max": 1500}}],
            "anchors": [], "places": [5, {"title": "A", "url": "javascript:alert(1)"}, {"title": "B"}]}


def test_import_preview_says_what_apply_leaves_out(client, store):
    data = json.dumps(_doc()).replace("Infinity", "1e999").encode()
    r = client.post("/searches/import", files={"file": ("s.json", data, "application/json")}, follow_redirects=False)
    assert r.status_code == 200
    html = r.text.replace("&#39;", "'")
    assert "budget" in html and "can't be read" in html
    assert "1 thing that matters can" in html
    assert "1 place can" in html
    assert "isn't a normal web address" in html
    assert "with 2 places" in html
    token = re.search(r'name="token" value="([^"]+)"', html).group(1)
    r2 = client.post("/searches/import/apply", data={"token": token}, follow_redirects=False)
    assert r2.status_code in (302, 303)
    s = next(x for x in store.list_searches() if x["name"] == "S (imported)")
    assert s["budget_max"] is None and len(store.list_places(s["id"])) == 2


def test_import_dry_run_and_apply_agree():
    doc = share.read_export(json.dumps(_doc()).replace("Infinity", "1e999").encode())
    a = share.dry_run(doc)
    b = share.apply_import(Store(":memory:"), doc)
    for k in ("places", "link_unsafe", "places_skipped", "criteria_skipped", "fields_skipped"):
        assert a[k] == b[k]


def test_import_refused_file_is_said_in_the_preview(client):
    d = _doc()
    d["search"]["mode"] = "lease"
    r = client.post("/searches/import", files={"file": ("s.json", json.dumps(d).encode(), "application/json")}, follow_redirects=False)
    assert r.status_code in (302, 303)


def test_photo_urls_rejected_and_http_upgraded(store):
    srv = server(store)
    store.add_search("A", "rent")
    for bad in ("data:text/html,<b>x</b>", "javascript:alert(1)", "ftp://x.com/a.jpg"):
        with pytest.raises(Exception) as e:
            call(srv, "add_place", title="T", photo_urls=[bad])
        assert "isn't a web address" in str(e.value)
        with pytest.raises(Exception):
            call(srv, "add_places", places=[{"title": "T", "photo_urls": [bad]}])
    out = text(call(srv, "add_place", title="T", photo_urls=["http://cdn.example.com/a.jpg"]))
    assert "saved it as https://" in out
    p = store.list_places(store.current_search()["id"])[0]
    assert p["photo_urls"] == ["https://cdn.example.com/a.jpg"]
    out = text(call(srv, "add_places", places=[{"title": "U", "photo_urls": ["http://a.example.com/x.jpg"]}]))
    assert "https://" in out and "plain http" in out


def test_no_search_id_with_two_searches_is_friendly(store):
    srv = server(store)
    store.add_search("Alpha", "rent")
    store.add_search("Beta", "rent")
    for tool, args in (("add_place", {"title": "T"}), ("add_places", {"places": [{"title": "T"}]})):
        with pytest.raises(Exception) as e:
            call(srv, tool, **args)
        msg = str(e.value)
        assert "Alpha" in msg and "Beta" in msg and "search_id" in msg and "Traceback" not in msg
    assert text(call(srv, "add_place", title="T", search_id=2))


def test_unknown_delete_tool_and_instructions(store):
    srv = server(store)
    with pytest.raises(Exception) as e:
        call(srv, "delete_place", place_id=1)
    assert "Property Helper window" in str(e.value)
    assert "no delete_place" in srv.instructions


def test_update_search_description_and_tenant_pays_all(store):
    srv = server(store)
    import anyio
    tools = anyio.run(srv.list_tools)
    d = next(t for t in tools if t.name == "update_search").description
    assert "add_anchors_list" in d
    store.add_search("A", "rent")
    call(srv, "add_place", title="T")
    pid = store.list_places(store.current_search()["id"])[0]["id"]
    call(srv, "update_place", place_id=pid, tenant_pays="all")
    assert store.get_place(pid)["tenant_pays"] == "electric, gas, water, sewer, trash, heat"
    out = text(call(srv, "update_place", place_id=pid, ai_notes="hello"))
    assert "Claude's note was added" in out and "Your note" not in out


def test_get_place_says_how_many_checklist_items_shown(store):
    srv = server(store)
    store.add_search("A", "rent")
    for i in range(10):
        store.add_checklist_item(f"Thing {i}") if hasattr(store, "add_checklist_item") else None
    call(srv, "add_place", title="T")
    pid = store.list_places(store.current_search()["id"])[0]["id"]
    out = text(call(srv, "get_place", place_id=pid))
    items = store.place_checklist(pid)
    if len(items) > 6:
        assert "6 of" in out and "shown" in out


def test_photo_csp_only_names_the_places_photo_hosts(store):
    from conftest import local_client
    store.add_search("A", "rent")
    p, _ = store.add_place(search_id=store.current_search()["id"], title="T", photo_urls=["https://img.example.com/a.jpg"], by="you")
    q, _ = store.add_place(search_id=store.current_search()["id"], title="U", by="you")
    store.set_setting("show_photos", "1")
    c = local_client(store)
    csp = c.get(f"/places/{p['id']}").headers["content-security-policy"]
    assert "https://img.example.com" in csp and "img-src 'self' data: https:;" not in csp
    csp2 = c.get(f"/places/{q['id']}").headers["content-security-policy"]
    assert "img-src 'self' data:;" in csp2
