"""Cycle 6, G5: CSV Fit column, import preview junk rows, import grammar, photo link rules, /add/parse, Added today."""
import csv
import io
import json
import re

import pytest

from mcp_util import call, server
from prophelper import csv_io, share, enrich


def _rows(text):
    return list(csv.reader(io.StringIO(text)))


def test_csv_has_fit_column_and_reimport_ignores_it(store, client):
    s = store.add_search("A", "rent")
    store.add_place(search_id=s["id"], by="you", title="One", address="1 Main St", price=1000)
    text = client.get("/places.csv").text
    head, row = _rows(text)[:2]
    assert head.index("Fit") == head.index("Fit score") + 1
    assert row[head.index("Fit")] in ("Fits", "Fits, but check", "Near miss", "Doesn't fit", "Check first")
    headers, body = csv_io.read_table(text.encode())
    assert "fit" not in csv_io.match_columns(headers).values()
    assert csv_io.is_computed_header("Fit")
    assert "fit" not in csv_io.FIELD_LABELS


def test_import_preview_junk_rows(store):
    s = store.add_search("A", "rent")
    store.add_place(search_id=s["id"], by="you", title="Old", address="12 Oak Street", unit="Apt 3")
    data = b"Title,Address,Unit,Rent,Notes\nBad Row,,,abc,x\n,,,1200,\nB,12 OAK st.,#3,1000,\n"
    h, r = csv_io.read_table(data)
    plan = csv_io.plan_import(store, s["id"], h, r, csv_io.match_columns(h))
    assert plan[0]["status"] == "new" and "left blank" in plan[0]["warnings"][0]
    assert plan[1]["status"] == "skip" and "no title" in plan[1]["reason"]
    assert plan[2]["status"] == "match"


def test_import_preview_page_lists_blank_rent_reason(store, client):
    store.add_search("A", "rent")
    r = client.post("/import", files={"file": ("a.csv", b"Title,Rent\nBad Row,abc\n", "text/csv")})
    assert "added with price left blank" in r.text


def test_import_apply_message_plural(store, client):
    s = store.add_search("A", "rent")
    store.add_place(search_id=s["id"], by="you", title="Old", address="1 Main St")
    r = client.post("/import", files={"file": ("a.csv", b"Address,Notes\n1 Main St,n\n", "text/csv")})
    token = re.search(r'name="token" value="([^"]+)"', r.text).group(1)
    r2 = client.post("/import/apply", data={"token": token, "col_0": "address", "col_1": "notes"}, follow_redirects=True)
    assert "empty details on 1 place you already had" in r2.text


def _doc(places):
    return json.dumps({"format": share.FORMAT_NAME, "version": share.FORMAT_VERSION, "search": {"name": "S", "mode": "rent"},
                       "criteria": [], "anchors": [], "places": places}).encode()


def test_link_grammar_singular_and_plural(store, client):
    s = store.add_search("A", "rent")
    store.add_place(search_id=s["id"], by="you", title="X", url="https://example.com/a")
    r = client.post("/searches/import", files={"file": ("s.json", _doc([{"title": "P", "url": "https://example.com/a"}]), "application/json")})
    assert "that place will have no link" in r.text
    token = re.search(r'name="token" value="([^"]+)"', r.text).group(1)
    r2 = client.post("/searches/import/apply", data={"token": token}, follow_redirects=True)
    assert "that place has no link" in r2.text and "place have" not in r2.text
    lines = share.left_out_lines({"link_dropped": 2}, done=True)
    assert "2 listing links are already saved in another search, so those places have no link." in lines


def test_photo_links_import_and_mcp(store, client):
    srv = server(store)
    store.add_search("A", "rent")
    with pytest.raises(Exception) as e:
        call(srv, "add_place", title="T", photo_urls=["https://user:pw@cdn.example/a.jpg"])
    assert "user name or password" in str(e.value) and "pw" not in str(e.value)
    doc = _doc([{"title": "P", "photo_urls": ["https://user:pw@cdn.example/a.jpg", "http://cdn.example/b.jpg", "https://cdn.example/c.jpg"]}])
    r = client.post("/searches/import", files={"file": ("s.json", doc, "application/json")})
    t = r.text.replace("&#39;", "'")
    assert "1 photo link has a user name or password" in t and "1 photo link was plain http://" in t
    token = re.search(r'name="token" value="([^"]+)"', r.text).group(1)
    client.post("/searches/import/apply", data={"token": token})
    p = [x for x in store.list_searches() if x["name"].endswith("(imported)")][0]
    photos = store.list_places(p["id"])[0]["photo_urls"]
    assert photos == ["https://cdn.example/b.jpg", "https://cdn.example/c.jpg"]


def test_web_store_drops_credentialed_photo_link(store):
    s = store.add_search("A", "rent")
    pl, _ = store.add_place(search_id=s["id"], by="you", title="T", photo_urls="https://u:p@x.test/a.jpg https://x.test/b.jpg")
    assert pl["photo_urls"] == ["https://x.test/b.jpg"]


def test_add_parse_refuses_credentialed_link(store, client):
    store.add_search("A", "rent")
    r = client.post("/add/parse", data={"url": "https://user:pw@evil.test/x", "text": ""})
    assert r.status_code == 400 and "user name or password" in r.text
    assert "pw@evil" not in r.text
    r = client.post("/add/parse", data={"url": "https://example.com/x", "text": ""})
    assert r.status_code == 200


def test_added_today_only_when_some_places_are_older(store, client):
    s = store.add_search("A", "rent")
    a, _ = store.add_place(search_id=s["id"], by="you", title="One")
    assert "Added today" not in client.get("/board").text
    with store._write():
        store._conn.execute("UPDATE places SET created_at = '2020-01-01T00:00:00+00:00', stage_changed_at = '2020-01-01T00:00:00+00:00' WHERE id = ?", (a["id"],))
    store.add_place(search_id=s["id"], by="you", title="Two")
    assert "Added today" in client.get("/board").text


def test_map_no_locations_message(store, client):
    s = store.add_search("A", "rent")
    store.add_place(search_id=s["id"], by="you", title="One")
    t = client.get("/map").text
    assert "None of your places has a map location yet" in t and "The map needs JavaScript" not in t
