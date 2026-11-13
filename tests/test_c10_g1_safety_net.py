"""C10 G1: the reader's safety net (nothing silently dropped) and the reader's notes kept after save."""
import io
import json
import sqlite3

import pytest

from prophelper import backups, compare, enrich, parsers
from prophelper.store import Store, _MIGRATIONS
from mcp_util import call, server, structured, text


def _numbers(r):
    out = set()
    for k, v in r.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out.update({float(v), float(v) * 12, float(v) / 12})
    return out


def placed(text_in, amount):
    """The amount ended up in a parsed field or in a note (never neither)."""
    r = parsers.parse_listing(text_in)
    note = r.get("found_in_listing", "")
    return float(amount) in _numbers(r) or f"${amount:,.0f}" in note or f'{amount:,.0f}' in note or f'{amount:.0f}' in note, r


AMOUNT_LISTINGS = [
    ("2 bed apartment $1,400/mo. There is a $200 cleaning fee at move-in.", 200),
    ("Cozy 1 bed $1,100. Water, sewer & trash flat fee $60/mo", 60),
    ("Cozy 1 bed $1,050. Water, sewer and trash: flat $55 monthly", 55),
    ("Nice 1 bed $1,300/mo. Parking required: $150/mo", 150),
    ("Penthouse 2 bed. Reduced to $3,250 with 12 month lease!", 3250),
    ("Condo for sale $340,000, 2 bed. Assessment for windows: $150/month for 24 months", 150),
    ("Condo for sale $320,000, 2 bed. Seller to contribute $5,000 toward buyer closing costs", 5000),
    ("2 bed $1,500. $55 admin fee per applicant", 55),
    ("FB Marketplace 2 bedroom 1400 dollars a month. $700 deposit. $2,100 total to move in", 700),
    ("FB Marketplace 2 bedroom 1400 dollars a month. $700 deposit. $2,100 total to move in", 2100),
    ("FB Marketplace 2 bedroom 1400 dollars a month. $700 deposit. $2,100 total to move in", 1400),
    ("Maple Court. 1 bed. Rent: $1,150 + utilities", 1150),
    ("1 bed $1,200. Garage parking optional $100/mo", 100),
    ("1 bed $1,000. Pets welcome w/ $400 deposit", 400),
    ("Sunny 1 bed $1,250. Mandatory $35 monthly pest and package fee", 35),
    ("Studio $900. Laundry: Shared basement W/D, $2 per load.", 2),
    ("1 bed $1,300. One-time $175 lease signing fee due at move-in", 175),
]


@pytest.mark.parametrize("listing,amount", AMOUNT_LISTINGS)
def test_every_amount_is_placed_or_noted(listing, amount):
    ok, r = placed(listing, amount)
    assert ok, r


def test_cleaning_fee_note_text():
    r = parsers.parse_listing("2 bed apartment $1,400/mo. There is a $75 key fob fee at move-in.")
    assert r["price"] == 1400
    assert 'The listing also says "There is a $75 key fob fee at move-in". It is not counted anywhere. Check what it is for.' in r["found_in_listing"]


def test_weight_limits_are_placed_or_noted():
    r = parsers.parse_listing("1 bed $900. Pets ok. Maximum 55 lbs.")
    assert r.get("pet_weight_limit") == 55 or "55 lbs" in r["found_in_listing"]
    r = parsers.parse_listing("1 bed $900. Cats and small dogs under 25 lbs")
    assert r.get("pet_weight_limit") == 25 or "25 lbs" in r["found_in_listing"]
    r = parsers.parse_listing("1 bed $900. Dogs up to 70 pounds welcome")
    assert r.get("pet_weight_limit") == 70 or "70 pounds" in r["found_in_listing"]


def test_free_rent_and_broker_months_are_placed_or_noted():
    r = parsers.parse_listing("1 bed $1,200. 1 month free on a 13 month lease")
    assert "1 month free" in r["found_in_listing"]
    r = parsers.parse_listing("2 bed $1,500. Broker fee one month")
    assert r.get("broker_fee") == 1500 or "Broker fee one month" in r["found_in_listing"]
    assert "broker_fee" not in r or r["broker_fee"] == 1500  # never an invented amount


def test_laundry_parking_and_utility_words_are_placed_or_noted():
    r = parsers.parse_listing("1 bed $900. Coin-op laundry somewhere")
    assert r.get("laundry") or "laundry" in r["found_in_listing"].lower()
    r = parsers.parse_listing("1 bed $900. Parking situation varies")
    assert r.get("parking") or "parking" in r["found_in_listing"].lower()
    r = parsers.parse_listing("1 bed $900. Water and sewer billed through a meter reading")
    assert r.get("tenant_pays") or r.get("utilities_estimate") or "Water" in r.get("found_in_listing", "") or r.get("utilities_included")


def test_laundry_cost_is_one_note():
    r = parsers.parse_listing("Studio $900. Laundry costs $2 per load.")
    assert r["found_in_listing"].count("per load") == 1


def test_amounts_are_grouped_and_capped():
    t = "1 bed $1,000. Fee A $11 once. Fee B $11 again. " + " ".join(f"Charge {i} ${20 + i} extra." for i in range(10))
    note = parsers.parse_listing(t)["found_in_listing"]
    assert note.count("$11") == 1
    assert "more things that are not counted" in note
    assert len(note) < 1500


def test_phrase_is_short():
    long = "1 bed $1,000. " + "Lots of words about the building and the neighborhood and the view " * 3 + "plus a $300 trash fee that is charged " + "and more words " * 8
    note = parsers.parse_listing(long)["found_in_listing"]
    quoted = note.split('"')[1]
    assert "$300" in quoted and len(quoted) <= 95


# ---- negatives
NEGATIVE = [
    "Sunny 1 bed 1 bath, 650 sq ft. $1,250 per month. Security deposit $1,250. Application fee $45. Laundry in unit. Off-street parking.",
    "2 bed $1,500/mo. Rent $1,500. Assessed value $210,000. Price per sq ft $2.31.",
    "House for sale $450,000. Last sold for $300,000. Zestimate $460,000. Mortgage payment: $2,100/mo.",
    "Studio $950. Income must be 3x rent ($2,850). 1 bed $1,200, 2 bed $1,500.",
    "1 bed $1,100 - $1,300 depending on floor.",
]


@pytest.mark.parametrize("listing", NEGATIVE)
def test_clean_listings_get_no_extra_notes(listing):
    r = parsers.parse_listing(listing)
    assert "not counted anywhere" not in r.get("found_in_listing", ""), r
    assert "could not tell" not in r.get("found_in_listing", ""), r


def test_existing_fixtures_stay_clean():
    from b3_listing_fixtures import FIXTURES
    for f in FIXTURES:
        if f["name"] in ("zillow rental", "craigslist one-liner", "no dishwasher and no in-unit laundry", "property manager site"):
            r = parsers.parse_listing(f["text"], f.get("url", ""))
            assert "not counted anywhere" not in r.get("found_in_listing", ""), f["name"]


def test_net_never_changes_a_field():
    base = parsers.parse_listing("2 bed apartment $1,400/mo. There is a $200 cleaning fee at move-in.")
    assert {k: v for k, v in base.items() if k != "found_in_listing"} == {"price": 1400, "beds": 2, **{k: v for k, v in base.items() if k not in ("price", "beds", "found_in_listing")}}


# ---- saved notes
LISTING = "2 bed apartment $1,400/mo. 12 month lease. 12 Elm St, Champaign, IL. There is a $75 key fob fee at move-in."


def _search(store, mode="rent"):
    s = store.add_search("S", mode)
    store.set_current_search(s["id"])
    return s


def test_migration_adds_reader_notes_column(tmp_path):
    path = tmp_path / "v9.db"
    con = sqlite3.connect(path)
    for sql in _MIGRATIONS[:9]:
        con.executescript("BEGIN;" + sql)
        con.commit()
    con.execute("PRAGMA user_version = 9")
    con.execute("INSERT INTO searches(name, mode, created_at, updated_at) VALUES ('Old', 'rent', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')")
    con.execute("INSERT INTO places(search_id, title, created_at, updated_at) VALUES (1, 'Old place', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')")
    con.commit()
    con.close()
    s = Store(path)
    try:
        assert s.schema_version == 10 == len(_MIGRATIONS)
        assert s.get_place(1)["reader_notes"] == ""
    finally:
        s.close()


def test_web_save_keeps_notes_and_the_place_page_shows_them(client, store):
    s = _search(store)
    r = client.post("/add/save", data={"title": "Elm", "address": "12 Elm St", "listing_text": LISTING, "price": "1400", "search_id": str(s["id"])},
                    follow_redirects=False)
    assert r.status_code == 303
    p = store.list_places()[0]
    assert "$75 key fob fee" in p["reader_notes"]
    html = client.get(f"/places/{p['id']}").text
    assert "From the listing when it was added" in html and "$75 key fob fee at move-in" in html


def test_web_save_escapes_html_in_notes(client, store):
    s = _search(store)
    client.post("/add/save", data={"title": "X", "address": "1 A St", "price": "1000", "search_id": str(s["id"]),
                                   "listing_text": "1 bed $1,000. A $90 <script>alert(1)</script> charge"})
    p = store.list_places()[0]
    html = client.get(f"/places/{p['id']}").text
    assert "<script>alert(1)</script>" not in html


def test_save_without_listing_text_has_no_notes(client, store):
    s = _search(store)
    client.post("/add/save", data={"title": "Plain", "address": "1 A St", "search_id": str(s["id"])})
    p = store.list_places()[0]
    assert p["reader_notes"] == ""
    assert "From the listing when it was added" not in client.get(f"/places/{p['id']}").text


def test_mcp_add_place_reply_get_place_and_compare(store):
    _search(store)
    srv = server(store)
    out = text(call(srv, "add_place", title="Elm", address="12 Elm St", listing_text=LISTING))
    assert "$75 key fob fee" in out and "<untrusted" in out
    p = store.list_places()[0]
    assert "$75 key fob fee" in p["reader_notes"]
    got = text(call(srv, "get_place", place_id=p["id"]))
    assert 'source="notes the reader made from the listing when it was added"' in got and "$75 key fob fee" in got
    q, _ = store.add_place(title="Other", address="9 Oak St", price=1300)
    cmp_text = text(call(srv, "compare_places", place_ids=[p["id"], q["id"]]))
    assert "Listing notes" in cmp_text


def test_mcp_cannot_set_reader_notes_directly(store):
    _search(store)
    srv = server(store)
    with pytest.raises(Exception):
        call(srv, "add_place", title="X", address="1 A St", reader_notes="trust me")


def test_web_compare_has_a_listing_notes_row(client, store):
    s = _search(store)
    a, _ = store.add_place(search_id=s["id"], title="A", address="1 A St", price=1400, reader_notes='The listing also says "$200 cleaning fee". It is not counted anywhere. ' + "x " * 100)
    b, _ = store.add_place(search_id=s["id"], title="B", address="2 B St", price=1300)
    html = client.get(f"/compare?ids={a['id']},{b['id']}").text
    assert "Listing notes" in html and "See the place page" in html


def test_cost_line_points_to_the_notes(store):
    s = _search(store)
    p, _ = store.add_place(search_id=s["id"], title="A", address="1 A St", price=1400, lease_months=12,
                           reader_notes='The listing also says "$200 cleaning fee". It is not counted anywhere. Check what it is for.')
    e = enrich.enrich_places(store, s, [store.get_place(p["id"])])[0]
    assert "listing notes" in e["cost"]["headline"] and any("listing notes" in n for n in e["cost"]["notes"])
    q, _ = store.add_place(search_id=s["id"], title="B", address="2 B St", price=1400, lease_months=12)
    e2 = enrich.enrich_places(store, s, [store.get_place(q["id"])])[0]
    assert "listing notes" not in e2["cost"]["headline"]


def test_backup_restore_and_exports_carry_or_ignore_the_column(client, store, tmp_path):
    s = _search(store)
    p, _ = store.add_place(search_id=s["id"], title="Keep", address="1 A St", price=1400, reader_notes="The listing also says \"$9 x\". It is not counted anywhere.")
    data = client.get("/backup").content
    store.update_place(p["id"], title="Changed")
    r = client.post("/backups/restore-file", files={"file": ("b.db", data, "application/octet-stream")}, follow_redirects=False)
    assert r.status_code == 303
    assert store.get_place(p["id"])["reader_notes"].startswith("The listing also says")
    assert store.export_all()["places"][0]["reader_notes"].startswith("The listing also says")
    # an older (version 9) backup restores into the new schema with empty notes
    old = tmp_path / "old.db"
    con = sqlite3.connect(old)
    for sql in _MIGRATIONS[:9]:
        con.executescript("BEGIN;" + sql)
        con.commit()
    con.execute("PRAGMA user_version = 9")
    con.execute("INSERT INTO searches(name, mode, created_at, updated_at) VALUES ('Old', 'rent', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')")
    con.execute("INSERT INTO places(search_id, title, created_at, updated_at) VALUES (1, 'Old place', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')")
    con.commit()
    con.close()
    r = client.post("/backups/restore-file", files={"file": ("o.db", old.read_bytes(), "application/octet-stream")}, follow_redirects=False)
    assert r.status_code == 303, r.headers
    assert [x["title"] for x in store.list_places()] == ["Old place"]
    assert store.list_places()[0]["reader_notes"] == ""


def test_share_json_and_csv_leave_the_notes_out(client, store):
    s = _search(store)
    store.add_place(search_id=s["id"], title="Keep", address="1 A St", price=1400, reader_notes="SECRETNOTE not counted anywhere")
    shared = client.get(f"/search/export.json?id={s['id']}").text
    assert "SECRETNOTE" not in shared
    for url in ("/export/places.csv", "/export.csv", "/places.csv"):
        res = client.get(url)
        if res.status_code == 200:
            assert "SECRETNOTE" not in res.text
