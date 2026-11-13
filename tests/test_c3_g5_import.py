"""Cycle 3, G5: search import (JSON) skips or cleans bad items with counts."""
import json
import re

from prophelper import share


def _file(**over):
    doc = {"format": share.FORMAT_NAME, "version": share.FORMAT_VERSION,
           "search": {"name": "Shared", "mode": "rent"},
           "criteria": [{"kind": "price", "label": "Rent", "weight": 10, "target": {}}, {"kind": "bogus"}, "x"],
           "anchors": [], "places": [{"title": "Good", "url": "https://example.com/a"}, "junk", 5,
                                      {"title": "Bad link", "url": "javascript:alert(1)"}]}
    doc.update(over)
    return json.dumps(doc).encode()


def _upload(client, data):
    return client.post("/searches/import", files={"file": ("s.json", data, "application/json")}, follow_redirects=False)


def test_bad_items_are_skipped_and_counted_and_the_link_is_dropped(client, store):
    r = _upload(client, _file())
    assert r.status_code == 200
    html = r.text
    assert "Shared (imported)" in html
    assert "2 places can" in html and "left out" in html
    assert "2 things that matter can" in html
    assert "kept without its link" in html
    token = re.search(r'name="token" value="([^"]+)"', html).group(1)
    r2 = client.post("/searches/import/apply", data={"token": token}, follow_redirects=False)
    assert r2.status_code in (302, 303)
    s = next(x for x in store.list_searches() if x["name"] == "Shared (imported)")
    places = store.list_places(s["id"])
    assert {p["title"] for p in places} == {"Good", "Bad link"}
    assert [p for p in places if p["title"] == "Bad link"][0]["url"] in (None, "")


def test_damaged_only_when_not_json_or_no_search(client):
    assert _upload(client, b"nope").status_code in (302, 303)
    assert _upload(client, _file(search="oops")).status_code in (302, 303)
    ok = _upload(client, _file(criteria="nope", anchors=None, places=[]))
    assert ok.status_code == 200


def test_read_export_counts():
    doc = share.read_export(_file())
    assert doc["_not_objects"] == {"places": 2, "criteria": 1, "anchors": 0}
