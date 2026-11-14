"""Calendar, the .ics file and tours on the place page."""
from datetime import datetime, timedelta, timezone

import pytest

from prophelper import ics
from prophelper.routes_calendar import calendar_items, ics_items, month_weeks


def _place(store, **kw):
    s = store.current_search() or store.add_search("S", "rent")
    store.set_current_search(s["id"])
    return store.add_place(search_id=s["id"], title=kw.pop("title", "Maple"), **kw)[0]


# ---- ics.py (pure)
def test_escape_text():
    assert ics.escape_text("a, b; c\\d\ne") == "a\\, b\\; c\\\\d\\ne"


def test_fold_never_exceeds_75_bytes_or_splits_a_character():
    line = "SUMMARY:" + "é" * 80
    parts = ics.fold(line)
    assert all(len(p.encode()) <= 75 for p in parts)
    assert all(p.startswith(" ") for p in parts[1:])
    assert "".join([parts[0]] + [p[1:] for p in parts[1:]]) == line


def test_build_calendar_timed_and_all_day():
    items = [
        {"uid": "tour-1", "summary": "Tour: Maple, Row", "description": "With the office", "location": "410 Maple Row",
         "starts_at": "2027-07-30T19:00:00+00:00", "duration_minutes": 45, "updated": "2027-07-01T00:00:00+00:00"},
        {"uid": "place-1-available", "summary": "Available: Maple", "date": "2027-07-31"},
    ]
    text = ics.build_calendar(items, now=datetime(2027, 7, 2, tzinfo=timezone.utc))
    assert text.startswith("BEGIN:VCALENDAR\r\n") and text.endswith("END:VCALENDAR\r\n")
    assert "\n" not in text.replace("\r\n", "")
    # Timed events are floating local time now (no Z): see tests/test_c1_f4_calendar.py
    start = datetime(2027, 7, 30, 19, 0, tzinfo=timezone.utc).astimezone()
    assert f"DTSTART:{start:%Y%m%dT%H%M%S}\r\n" in text and "DTSTART:20270730T190000Z" not in text
    assert "DTSTART;VALUE=DATE:20270731" in text and "DTEND;VALUE=DATE:20270801" in text
    assert "SUMMARY:Tour: Maple\\, Row" in text
    assert "UID:tour-1@property-helper.local" in text
    assert text.count("BEGIN:VEVENT") == text.count("END:VEVENT") == 2


def test_build_calendar_is_stable_and_skips_bad_rows():
    items = [{"uid": "a", "summary": "x", "date": "2027-01-05", "updated": "2027-01-01T00:00:00+00:00"},
             {"uid": "b", "summary": "bad date", "date": "not a date"},
             {"uid": "", "summary": "no uid", "date": "2027-01-05"},
             {"uid": "c", "summary": "bad time", "starts_at": "garbage"}]
    first = ics.build_calendar(items, now=datetime(2027, 1, 2, tzinfo=timezone.utc))
    again = ics.build_calendar(items, now=datetime(2030, 1, 2, tzinfo=timezone.utc))
    assert first == again  # DTSTAMP comes from the row, not the clock
    assert first.count("BEGIN:VEVENT") == 1


def test_ics_never_includes_notes_or_ratings(store):
    place = _place(store, address="410 Maple Row", available_from="2027-07-31")
    tour = store.add_tour(place["id"], "2027-07-30T14:00", with_whom="Sam", notes="SECRET NOTE ABOUT LANDLORD", rating=2)
    items = calendar_items(store, place["search_id"])
    text = ics.build_calendar(ics_items(items, {place["id"]: place}))
    assert "SECRET NOTE" not in text and "LANDLORD" not in text and "RATING:" not in text.upper()
    assert f"UID:tour-{tour['id']}@property-helper.local" in text and "410 Maple Row" in text


# ---- calendar items and month grid
def test_calendar_items_include_tours_and_dates_but_not_cancelled_or_passed(store):
    a = _place(store, title="A", available_from="2027-07-31", lease_start="2027-08-01", lease_end="2028-07-31")
    b = _place(store, title="B", available_from="2027-07-15")
    store.move_stage(b["id"], "Passed")
    t = store.add_tour(a["id"], "2027-07-20T10:00")
    c = store.add_tour(a["id"], "2027-07-21T10:00")
    store.update_tour(c["id"], status="cancelled")
    items = calendar_items(store, a["search_id"])
    kinds = [(i["kind"], i["title"]) for i in items]
    assert ("tour", "A") in kinds and kinds.count(("tour", "A")) == 1
    assert ("available", "A") in kinds and ("lease_start", "A") in kinds and ("lease_end", "A") in kinds
    assert all(title != "B" for _, title in kinds)
    assert t["id"] in [i["tour"]["id"] for i in items if i["kind"] == "tour"]


def test_calendar_items_window_and_order(store):
    a = _place(store, title="A", available_from="2027-07-31", lease_start="2027-09-01")
    items = calendar_items(store, a["search_id"], start=datetime(2027, 7, 1).date(), end=datetime(2027, 8, 1).date())
    assert [i["kind"] for i in items] == ["available"]
    assert calendar_items(store, None) == []


def test_month_weeks_are_whole_weeks_monday_first():
    from datetime import date

    weeks = month_weeks(date(2027, 7, 1), [{"date": date(2027, 7, 31), "title": "x"}], date(2027, 7, 15))
    assert all(len(w) == 7 for w in weeks)
    assert weeks[0][0]["date"].weekday() == 0
    flat = [c for w in weeks for c in w]
    assert [c["today"] for c in flat].count(True) == 1
    assert next(c for c in flat if c["date"] == date(2027, 7, 31))["entries"]


# ---- the page and the file
def test_calendar_page_empty_and_with_data(client, store):
    assert client.get("/calendar").status_code == 200  # no search at all
    a = _place(store, title="Maple <b>Row</b>", available_from="2027-07-31")
    r = client.get("/calendar?month=2027-07")
    assert r.status_code == 200 and "July 2027" in r.text
    assert "Maple &lt;b&gt;Row&lt;/b&gt;" in r.text and "<b>Row</b>" not in r.text
    assert "/calendar?month=2027-08" in r.text and "/calendar?month=2027-06" in r.text
    assert f'href="/places/{a["id"]}"' in r.text


def test_calendar_page_survives_a_bad_month(client, store):
    _place(store)
    assert client.get("/calendar?month=garbage").status_code == 200
    assert client.get("/calendar?month=2027-13").status_code == 200


def test_ics_download(client, store):
    place = _place(store, address="1 Main St")
    store.add_tour(place["id"], "2027-07-30T14:00")
    r = client.get("/calendar.ics")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/calendar")
    assert "attachment" in r.headers["content-disposition"]
    assert "BEGIN:VEVENT" in r.text and "Tour: Maple" in r.text


def test_ics_is_blocked_from_another_site(client, store):
    _place(store)
    r = client.get("/calendar.ics", headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
    assert client.get("/calendar.ics", headers={"Origin": "http://evil.example"}).status_code == 403


def test_calendar_pages_need_unlocking(locked_client):
    assert locked_client.get("/calendar").status_code == 401
    assert locked_client.get("/calendar.ics").status_code == 401


# ---- tours
def test_book_tour_moves_stage_and_shows_on_today_and_place_page(client, store):
    place = _place(store)
    day = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")
    r = client.post(f"/places/{place['id']}/tours", data={"day": day, "time": "14:30", "duration_minutes": "45",
                                                          "with_whom": "Front desk", "where_note": "Lobby"}, follow_redirects=False)
    assert r.status_code == 303
    tours = store.list_tours(place["id"])
    assert len(tours) == 1 and tours[0]["duration_minutes"] == 45 and tours[0]["with_whom"] == "Front desk"
    assert store.get_place(place["id"])["stage"] == "Tour booked"
    today = client.get("/today").text
    assert "Maple" in today and "Front desk" in today  # tours in the next 7 days show on Today
    page = client.get(f"/places/{place['id']}").text
    assert 'id="tours"' in page and "Front desk" in page and "Lobby" in page and "Tour checklist" in page


@pytest.mark.parametrize("data", [{"day": "", "time": "10:00"}, {"day": "2027-02-31", "time": "10:00"}, {"day": "2027-07-01", "time": "25:99"},
                                  {"day": "2027-07-01", "time": "10:00", "duration_minutes": "2"}])
def test_book_tour_rejects_bad_input(client, store, data):
    place = _place(store)
    r = client.post(f"/places/{place['id']}/tours", data=data, follow_redirects=False)
    assert r.status_code == 303 and store.list_tours(place["id"]) == []


def test_book_tour_for_a_missing_place_is_404(client):
    assert client.post("/places/999/tours", data={"day": "2027-07-01"}).status_code == 404


def test_blank_time_defaults_to_ten(client, store):
    place = _place(store)
    client.post(f"/places/{place['id']}/tours", data={"day": "2027-07-01", "time": ""})
    assert len(store.list_tours(place["id"])) == 1


def test_mark_done_and_cancel(client, store):
    place = _place(store)
    t = store.add_tour(place["id"], "2027-07-30T14:00")
    client.post(f"/tours/{t['id']}/status", data={"status": "done"})
    assert store.get_tour(t["id"])["status"] == "done"
    assert store.get_place(place["id"])["stage"] == "Toured"
    client.post(f"/tours/{t['id']}/status", data={"status": "cancelled"})
    assert store.get_tour(t["id"])["status"] == "cancelled"
    assert client.post(f"/tours/{t['id']}/status", data={"status": "nonsense"}, follow_redirects=False).status_code == 303
    assert store.get_tour(t["id"])["status"] == "cancelled"
    assert client.post("/tours/999/status", data={"status": "done"}).status_code == 404


def test_tour_checklist_rating_and_notes_are_saved_by_position(client, store):
    place = _place(store)
    t = store.add_tour(place["id"], "2027-07-30T14:00")
    names = list(t["checklist"])
    client.post(f"/tours/{t['id']}/details", data={"state_0": "ok", "note_0": "Strong", "state_1": "issue", "note_1": "Lukewarm",
                                                   "state_2": "bogus", "rating": "4", "notes": "Liked it"})
    got = store.get_tour(t["id"])
    assert got["checklist"][names[0]] == {"state": "ok", "note": "Strong"}
    assert got["checklist"][names[1]] == {"state": "issue", "note": "Lukewarm"}
    assert got["checklist"][names[2]]["state"] == ""  # a made-up state is ignored
    assert set(got["checklist"]) == set(names) and got["rating"] == 4 and got["notes"] == "Liked it"
    r = client.post(f"/tours/{t['id']}/details", data={"rating": "9"}, follow_redirects=False)
    assert r.status_code == 303 and store.get_tour(t["id"])["rating"] == 4


def test_delete_tour_needs_the_tick_box(client, store):
    place = _place(store)
    t = store.add_tour(place["id"], "2027-07-30T14:00")
    client.post(f"/tours/{t['id']}/delete", data={})
    assert len(store.list_tours(place["id"])) == 1
    client.post(f"/tours/{t['id']}/delete", data={"confirm": "yes"})
    assert store.list_tours(place["id"]) == []


def test_writes_from_another_site_are_blocked(store):
    from conftest import local_client

    place = _place(store)
    evil = local_client(store, origin=False)
    r = evil.post(f"/places/{place['id']}/tours", data={"day": "2027-07-01"}, headers={"Origin": "http://evil.example"})
    assert r.status_code == 403 and store.list_tours(place["id"]) == []
