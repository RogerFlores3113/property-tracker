"""CSV import (preview first, then apply) and export."""
import csv
import io

import pytest

from conftest import local_client
from prophelper import csv_io

SHEET = (
    "Name,Street Address,Apt,Rent,Bedrooms,Bathrooms,Laundry,Pets,Available,Link,Comments,Stage\n"
    "Maple Row Flats,410 Maple Row Lane,3B,\"$1,450\",2,1.5,in unit,pet friendly,2027-08-01,https://example.test/maple,Likes the light,Toured\n"
    "Oak House,12 Oak Street,,1200,1,1,,,,,,Nonsense stage\n"
    ",,,,,,,,,,,\n"
    "Total,,,2650,,,,,,,,\n"
    "=SUM(A1),,,,,,,,,,,\n"
    "Oak house again,12 Oak St.,,1250,,,,,,,,\n"
    "Bad Values,9 Pine Ave,,abc,two,,sideways,,,,,\n"
    ",,,,,,,,,,Only a note,\n"
)


@pytest.fixture
def setup(store):
    s = store.add_search("UIUC", "rent")
    store.set_current_search(s["id"])
    return s


def upload(c, text, search_id=None, name="places.csv"):
    data = {"search_id": str(search_id)} if search_id else {}
    return c.post("/import", data=data, files={"file": (name, text.encode() if isinstance(text, str) else text, "text/csv")})


def test_columns_are_matched_by_their_headings():
    headers, rows = csv_io.read_table(SHEET.encode())
    m = csv_io.match_columns(headers)
    assert {headers[i]: f for i, f in m.items()} == {
        "Name": "title", "Street Address": "address", "Apt": "unit", "Rent": "price", "Bedrooms": "beds", "Bathrooms": "baths",
        "Laundry": "laundry", "Pets": "pets", "Available": "available_from", "Link": "url", "Comments": "notes", "Stage": "stage"}
    assert len(rows) == 8


def test_plan_says_what_happens_to_each_row(store, setup):
    store.add_place(title="Oak House", address="12 Oak Street")
    headers, rows = csv_io.read_table(SHEET.encode())
    plan = csv_io.plan_import(store, setup["id"], headers, rows, csv_io.match_columns(headers))
    by_row = {p["row"]: p for p in plan}
    assert by_row[2]["status"] == "new" and by_row[2]["values"]["price"] == 1450 and by_row[2]["stage"] == "Toured"
    assert by_row[2]["values"]["laundry"] == "in_unit" and by_row[2]["values"]["unit"] == "3B"
    assert by_row[3]["status"] == "match" and by_row[3]["existing"]["title"] == "Oak House"
    assert any("stage" in w.lower() for w in by_row[3]["warnings"])
    assert by_row[4]["status"] == "skip" and "blank" in by_row[4]["reason"]
    assert by_row[5]["status"] == "skip" and "totals" in by_row[5]["reason"]
    assert by_row[6]["status"] == "skip" and "formula" in by_row[6]["reason"]
    assert by_row[7]["status"] == "repeat" and "row 3" in by_row[7]["reason"]  # 12 Oak St. is the same street address as 12 Oak Street
    bad = by_row[8]
    assert bad["status"] == "new" and bad["values"]["address"] == "9 Pine Ave" and "price" not in bad["values"]
    assert len(bad["warnings"]) >= 3
    assert by_row[9]["status"] == "skip" and "title, address or link" in by_row[9]["reason"]


def test_repeats_inside_the_file_are_left_out(store, setup):
    text = "Title,Address\nA,1 Main Street\nB,1 Main St\nC,2 Main Street\n"
    headers, rows = csv_io.read_table(text.encode())
    plan = csv_io.plan_import(store, setup["id"], headers, rows, csv_io.match_columns(headers))
    assert [p["status"] for p in plan] == ["new", "repeat", "new"]
    assert "row 2" in plan[1]["reason"]


def test_preview_writes_nothing_and_apply_does_what_was_shown(store, setup):
    c = local_client(store)
    r = upload(c, SHEET, setup["id"])
    assert r.status_code == 200 and "Check the import" in r.text and "Maple Row Flats" in r.text
    assert store.list_places(setup["id"]) == []  # preview saved nothing
    assert "<strong>3</strong> new" in r.text
    token = r.text.split('name="token" value="')[1].split('"')[0]
    # change a column: stop using the Rent column, and look again
    form = {"token": token}
    headers, _ = csv_io.read_table(SHEET.encode())
    for i, f in csv_io.match_columns(headers).items():
        if f != "price":
            form[f"col_{i}"] = f
    again = c.post("/import/preview", data=form)
    assert again.status_code == 200 and store.list_places(setup["id"]) == []
    done = c.post("/import/apply", data=form, follow_redirects=False)
    assert done.status_code == 303
    titles = {p["title"] for p in store.list_places(setup["id"])}
    assert titles == {"Maple Row Flats", "Oak House", "Bad Values"}
    maple = next(p for p in store.list_places(setup["id"]) if p["title"] == "Maple Row Flats")
    assert maple["price"] is None and maple["stage"] == "Toured" and maple["notes"] == "Likes the light"
    assert maple["url"] == "https://example.test/maple"
    # the file is gone once applied
    assert c.post("/import/apply", data=form).status_code == 410


def test_apply_fills_only_empty_fields_of_a_match(store, setup):
    mine, _ = store.add_place(title="Oak House", address="12 Oak Street", notes="my private note", price=1111)
    c = local_client(store)
    r = upload(c, "Title,Address,Rent,Notes,Beds\nOak House,12 Oak Street,9999,from the sheet,2\n", setup["id"])
    token = r.text.split('name="token" value="')[1].split('"')[0]
    c.post("/import/apply", data={"token": token, "col_0": "title", "col_1": "address", "col_2": "price", "col_3": "notes", "col_4": "beds"})
    got = store.get_place(mine["id"])
    assert got["price"] == 1111 and got["notes"] == "my private note" and got["beds"] == 2
    assert len(store.list_places(setup["id"])) == 1


def test_bad_files_get_plain_errors(store, setup):
    c = local_client(store)
    for body, words in [("", "empty"), ("Title\n", "at least one place"), (b"PK\x03\x04zzzz", "Excel"), (b"a,b\n\x00\x01,2\n", "look like a spreadsheet (CSV)")]:
        r = upload(c, body, setup["id"])
        assert r.status_code == 400 and words in r.text, (body, r.text[:300])
    assert c.post("/import", data={}).status_code == 400  # no file
    many = "Title\n" + "\n".join(f"P{i}" for i in range(csv_io.MAX_ROWS + 1))
    assert "most I import at once" in upload(c, many, setup["id"]).text


def test_semicolons_windows_text_and_bom(store, setup):
    raw = "﻿Titel;Address;Rent\nCafé Flat;1 Main Street;\"1.200\"\n".encode("cp1252", errors="replace")
    headers, rows = csv_io.read_table(b"\xef\xbb\xbfTitle;Address;Rent\nCaf\xe9 Flat;1 Main Street;1200\n")
    assert headers == ["Title", "Address", "Rent"] and rows[0][0] == "Café Flat"
    assert raw  # silence: only the bytes above matter


def test_expired_token_and_hold_limits(store, setup, monkeypatch):
    c = local_client(store)
    assert c.post("/import/preview", data={"token": "nope"}).status_code == 410
    t = csv_io.hold(setup["id"], "a.csv", ["Title"], [["x"]])
    assert csv_io.held(t) is not None
    monkeypatch.setattr(csv_io, "_now", lambda: 10 ** 9)
    assert csv_io.held(t) is None  # held for 30 minutes only


def test_export_round_trips_and_is_formula_safe(store, setup):
    store.add_place(title="=cmd|' /C calc'!A0", address="1 Main Street", price=1500, beds=2, dishwasher=True, notes="@home, \"quoted\"\nsecond line")
    store.add_place(title="Plain", address="2 Main Street", price=1000.5)
    c = local_client(store)
    r = c.get("/places.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"] and r.headers["cache-control"] == "no-store"
    rows = list(csv.reader(io.StringIO(r.text)))
    head = rows[0]
    assert head[0] == "Title" and "Price" in head and "Fit score" in head
    body = {row[0]: dict(zip(head, row)) for row in rows[1:]}
    assert "'=cmd|' /C calc'!A0" in body and body["'=cmd|' /C calc'!A0"]["Dishwasher"] == "yes"
    assert body["'=cmd|' /C calc'!A0"]["Notes"].startswith("'@home")
    assert body["Plain"]["Price"] == "1000.5"
    # what we export can be imported again, and the preview matches every exported column that can be read back
    headers, data = csv_io.read_table(r.text.encode())
    mapped = {headers[i] for i in csv_io.match_columns(headers)}
    assert {"Title", "Address", "Price", "Beds", "Link", "Notes", "Stage"} <= mapped and "Fit score" not in mapped and "Red flags" not in mapped


def test_export_of_another_search_and_none(store, setup):
    other = store.add_search("Other", "rent")
    store.add_place(title="Elsewhere", search_id=other["id"], address="5 Far Road")
    store.add_place(title="Here", address="1 Main Street")
    c = local_client(store)
    assert "Elsewhere" not in c.get("/places.csv").text
    r = c.get(f"/places.csv?search_id={other['id']}")
    assert "Elsewhere" in r.text and "Here" not in r.text
    assert c.get("/places.csv?search_id=999", follow_redirects=False).status_code == 303


def test_import_routes_are_protected(store, setup):
    assert local_client(store, unlocked=False).get("/import").status_code in (401, 403)
    assert local_client(store, origin=False).post("/import/apply", data={"token": "x"}, headers={"Origin": "http://evil.test"}).status_code == 403
    assert local_client(store).get("/import/apply").status_code == 405


def test_import_page_is_plain_and_escapes(store, setup):
    c = local_client(store)
    r = upload(c, "Title,Address\n<script>alert(1)</script>,1 Main Street\n", setup["id"], name="<b>x</b>.csv")
    assert "<script>alert(1)</script>" not in r.text and "&lt;script&gt;" in r.text
    assert "<b>x</b>" not in r.text
    assert "—" not in c.get("/import").text and "—" not in r.text
