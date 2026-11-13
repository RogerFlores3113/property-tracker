"""Cycle 5, G5: small polish (links with credentials, import wording, CSV preview, add form in buy mode, board, map, tours, Claude tools)."""
import json
import re

import pytest

from mcp_util import call, server, text
from prophelper import share


def test_link_with_credentials_is_refused_everywhere(store, client):
    srv = server(store)
    s = store.add_search("A", "rent")
    with pytest.raises(Exception) as e:
        call(srv, "add_place", title="T", url="https://user:pw@evil.test/x")
    assert "user name or password" in str(e.value)
    with pytest.raises(ValueError):
        store.add_place(search_id=s["id"], by="you", title="T", url="https://user:pw@evil.test/x")
    r = client.post("/add/save", data={"title": "T", "url": "https://user:pw@evil.test/x", "search_id": str(s["id"])})
    assert r.status_code == 400 and "user name or password" in r.text
    assert store.list_places(s["id"]) == []
    store.add_place(search_id=s["id"], by="you", title="Fine", url="https://example.com/a?x=1@2")


def _doc(**over):
    d = {"format": share.FORMAT_NAME, "version": share.FORMAT_VERSION, "search": {"name": "S", "mode": "rent", "budget_max": 1e999},
         "criteria": [{"kind": "price", "label": "a", "weight": 99999, "target": {}}], "anchors": [], "places": [{"title": "B"}]}
    d.update(over)
    return json.dumps(d).replace("Infinity", "1e999").encode()


def test_apply_wording_agrees_in_number(client, store):
    r = client.post("/searches/import", files={"file": ("s.json", _doc(), "application/json")})
    assert "1 thing that matters can" in r.text.replace("&#39;", "'")
    token = re.search(r'name="token" value="([^"]+)"', r.text).group(1)
    r2 = client.post("/searches/import/apply", data={"token": token}, follow_redirects=True)
    t = r2.text.replace("&#39;", "'")
    assert "can't be read and was left out" in t
    assert "were left out" not in t


def test_left_out_lines_done_plural():
    rep = {"places_skipped": 2, "criteria_skipped": 1, "fields_skipped": ["budget", "move-in date"]}
    lines = share.left_out_lines(rep, done=True)
    assert any("2 places can't be read and were left out" in x for x in lines)
    assert any("budget, move-in date of the search can't be read and were left out" in x for x in lines)
    assert any("1 thing that matters can't be read and was left out" in x for x in lines)
    assert all("will be" in x for x in share.left_out_lines(rep) if "left out" in x)


def _upload_csv(client, store, data):
    store.add_search("Rent", "rent")
    r = client.post("/import", files={"file": ("a.csv", data, "text/csv")})
    assert r.status_code == 200
    return r.text


def test_csv_preview_warns_on_junk_row_and_ignores_trailing_blank(client, store):
    html = _upload_csv(client, store, b"Title,Address,Rent,Beds\nGood,1 Main St,1500,2\nJunk,,abc,two\n,,abc,two\n\n\n")
    assert "empty row" not in html
    assert "1 row has values I can't read" in html.replace("&#39;", "'")
    assert "Price needs to be a number" in html and "Beds needs to be a number" in html
    assert "no title or address" in html  # the row with nothing usable is skipped with a reason
    assert "<strong>1</strong> skipped" in html


def test_csv_preview_mapping_is_compact(client, store):
    html = _upload_csv(client, store, b"Title,Address,Rent,Beds\nGood,1 Main St,1500,2\n")
    assert html.count('<details class="inline-change"') == 4 and "<summary>change</summary>" in html
    assert 'name="col_0"' in html  # still a plain form field, works without JavaScript


def test_add_form_hides_pets_in_buy_mode(client, store):
    s = store.add_search("Buy", "buy")
    r = client.post("/add/parse", data={"text": "3 bed house 450000", "search_id": str(s["id"])})
    assert r.status_code == 200
    assert 'name="pets"' in r.text and 'type="hidden" name="pets"' in r.text
    assert 'id="f-pets"' not in r.text and "One-time pet fee</label>" not in r.text
    s2 = store.add_search("Rent", "rent")
    r = client.post("/add/parse", data={"text": "2 bed 1500", "search_id": str(s2["id"])})
    assert "One-time pet fee" in r.text


def test_board_says_added_for_a_place_never_moved(client, store):
    s = store.add_search("Rent", "rent")
    p, _ = store.add_place(search_id=s["id"], by="you", title="Fresh")
    html = client.get("/board").text
    assert "Added today" in html and "Moved today" not in html
    store._exec("UPDATE places SET created_at = '2020-01-01T00:00:00Z' WHERE id = ?", (p["id"],))
    store.move_stage(p["id"], "Contacted")
    assert "Moved today" in client.get("/board").text


def test_map_without_located_places(client, store):
    s = store.add_search("Rent", "rent")
    store.add_place(search_id=s["id"], by="you", title="Nowhere")
    html = client.get("/map").text
    assert "None of your places has a map location yet" in html and "Find on map" in html
    assert "The map needs JavaScript" not in html


def test_tour_overlap_wording(client, store):
    s = store.add_search("Rent", "rent")
    a, _ = store.add_place(search_id=s["id"], by="you", title="A")
    b, _ = store.add_place(search_id=s["id"], by="you", title="B")
    store.add_tour(a["id"], "2030-05-01T10:00", duration_minutes=60)
    r = client.post(f"/places/{b['id']}/tours", data={"day": "2030-05-01", "time": "10:45", "duration_minutes": "30"}, follow_redirects=True)
    assert "overlaps your tour at A" in r.text
    r = client.post(f"/places/{b['id']}/tours", data={"day": "2030-05-01", "time": "11:30", "duration_minutes": "30"}, follow_redirects=True)
    assert "close to your tour at A" in r.text


def test_tenant_pays_none_is_not_missing_and_pet_charges_listed(store):
    srv = server(store)
    store.add_search("Rent", "rent")
    call(srv, "add_place", title="T", price=1000, tenant_pays="none", pet_fee=300, pet_rent=25, pet_deposit=200)
    pid = store.list_places()[0]["id"]
    from prophelper import money
    assert "utilities estimate" not in money.rent_cost(store.get_place(pid))["missing"]
    got = text(call(srv, "get_place", place_id=pid))
    assert "one-time pet fee" in got and "pet rent" in got and "pet deposit" in got
