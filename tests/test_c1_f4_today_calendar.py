"""Cycle 1, group F4: Today, calendar file, key dates, stages, checklist."""
import re
import sqlite3
import time
from datetime import date, datetime, timedelta, timezone

import pytest

from prophelper import helpers, ics, today
from prophelper.routes_calendar import calendar_items, ics_items
from prophelper.store import Store


# time.tzset exists only on Unix. On Windows the TZ variable is ignored, and the
# test still checks that the exported time is floating local time.
_tzset = getattr(time, "tzset", lambda: None)


def _day(n: int) -> str:
    return (date.today() + timedelta(days=n)).isoformat()


def _rent(store, **kw):
    return store.add_search("Rent", "rent", **kw)


def _place(store, s, title="Maple", **kw):
    p, _ = store.add_place(search_id=s["id"], title=title, **kw)
    return p


# --------------------------------------------------------------------------- calendar file
def test_ten_am_tour_exports_as_floating_local_time(store, monkeypatch):
    monkeypatch.setenv("TZ", "America/Chicago")
    _tzset()
    try:
        s = _rent(store)
        p = _place(store, s, address="1 Main St")
        store.add_tour(p["id"], "2026-11-21T10:00")
        items = calendar_items(store, s["id"])
        text = ics.build_calendar(ics_items(items, {p["id"]: p}))
        assert "DTSTART:20261121T100000\r\n" in text
        assert "DTEND:20261121T103000\r\n" in text
        assert "DTSTART:20261121T100000Z" not in text
    finally:
        monkeypatch.undo()
        _tzset()


def test_all_day_dates_stay_date_values(store):
    s = _rent(store, move_in="2027-07-30")
    p = _place(store, s, available_from="2027-07-25")
    text = ics.build_calendar(ics_items(calendar_items(store, s["id"]), {p["id"]: p}))
    assert "DTSTART;VALUE=DATE:20270725" in text and "DTSTART;VALUE=DATE:20270730" in text


# --------------------------------------------------------------------------- key dates
def test_migration_adds_place_dates_to_an_old_database(tmp_path):
    path = tmp_path / "old.db"
    s = Store(path)
    s.close()
    con = sqlite3.connect(path)
    con.execute("DROP TABLE place_dates")
    con.execute("ALTER TABLE searches DROP COLUMN people")  # a real version-1 database has neither
    con.execute("DROP TABLE place_checklist")  # and none of what later steps add (pets and applications)
    for col in ("pet_weight_limit", "pet_count_limit", "pet_breed_note", "pet_deposit", "fenced_yard"):
        con.execute(f"ALTER TABLE places DROP COLUMN {col}")
    for col in ("pet_kind", "pet_weight", "pet_count"):
        con.execute(f"ALTER TABLE searches DROP COLUMN {col}")
    con.execute("DROP TABLE place_opinions")
    con.execute("ALTER TABLE searches DROP COLUMN people_names")
    for col in ("days_on_market", "special_assessment", "special_assessment_payer", "closing_costs", "listing_agent"):
        con.execute(f"ALTER TABLE places DROP COLUMN {col}")  # nor the buyer fields added in the later step
    for col in ("months_up_front", "tenant_pays"):
        con.execute(f"ALTER TABLE places DROP COLUMN {col}")  # nor the rent-upfront fields of the newest step
    con.execute("PRAGMA user_version = 1")
    con.commit()
    con.close()
    s2 = Store(path)
    try:
        assert s2.schema_version >= 2
        s2.list_place_dates()
    finally:
        s2.close()


def test_key_dates_kinds_depend_on_mode(store):
    r = _rent(store)
    b = store.add_search("Buy", "buy")
    pr, pb = _place(store, r), _place(store, b, "House")
    store.add_place_date(pr["id"], "application_deadline", _day(3))
    with pytest.raises(ValueError):
        store.add_place_date(pr["id"], "inspection", _day(3))
    store.add_place_date(pb["id"], "inspection", _day(4), time="09:30")
    with pytest.raises(ValueError):
        store.add_place_date(pb["id"], "move_in", _day(4))
    with pytest.raises(ValueError):
        store.add_place_date(pb["id"], "other", "not a date")
    store.add_place_date(pb["id"], "other", _day(5), note="walk the yard")


def test_key_dates_route_calendar_ics_and_today(client, store):
    s = _rent(store)
    p = _place(store, s, "Maple Row")
    r = client.post(f"/places/{p['id']}/dates", data={"kind": "application_deadline", "day": _day(5), "note": "by 5pm"})
    assert r.status_code in (200, 303)
    assert "Application deadline" in client.get(f"/places/{p['id']}").text and 'id="dates"' in client.get(f"/places/{p['id']}").text
    items = [i for i in calendar_items(store, s["id"]) if i["kind"] == "key_date"]
    assert len(items) == 1 and items[0]["kind_label"] == "Application deadline"
    assert 'class="chip key_date"' in client.get("/calendar").text or "Key date" in client.get("/calendar").text
    ics_text = client.get("/calendar.ics").text
    assert "Application deadline: Maple Row" in ics_text
    page = client.get("/today").text
    assert "Application deadline" in page and f"/places/{p['id']}" in page
    row = store.list_place_dates(p["id"])[0]
    client.post(f"/place-dates/{row['id']}/delete")
    assert store.list_place_dates(p["id"]) == []


def test_search_targets_show_on_calendar(store):
    s = _rent(store, move_in="2027-07-30")
    b = store.add_search("Buy", "buy", target_close="2027-09-15")
    assert [i["kind_label"] for i in calendar_items(store, s["id"])] == ["Your move-in date"]
    assert [i["kind_label"] for i in calendar_items(store, b["id"])] == ["Your target close date"]


# --------------------------------------------------------------------------- Today
def _criteria(store, s):
    store.add_criterion(s["id"], "beds", weight=50, target={"min": 1})
    store.add_criterion(s["id"], "price", weight=50, dealbreaker=True, target={"max": 1000})


def test_best_fits_top_three_and_exclusions(client, store):
    s = _rent(store)
    _criteria(store, s)
    names = []
    for i, price in enumerate((900, 950, 800, 700)):
        names.append(_place(store, s, f"Fit{i}", price=price, beds=1).get("title"))
    _place(store, s, "TooPricey", price=2000, beds=1)  # fails the deal-breaker
    _place(store, s, "Scammy", price=500, beds=1, listing_text="Please wire the deposit via western union, I am out of the country")
    page = client.get("/today").text
    assert "Best fits right now" in page
    fits_section = page.split('id="fits-h"')[1].split("</section>")[0]
    assert fits_section.count('class="item"') == 3
    assert "TooPricey" not in fits_section and "Scammy" not in fits_section


def test_new_places_leave_out_scams_and_misfits(client, store):
    s = _rent(store)
    _criteria(store, s)
    _place(store, s, "Good", price=900, beds=1)
    _place(store, s, "TooPricey", price=2000, beds=1)
    _place(store, s, "Scammy", price=500, beds=1, listing_text="wire the deposit by western union, the owner is abroad")
    page = client.get("/today").text
    new_section = page.split('id="new-h"')[1].split("</section>")[0]
    assert "Good" in new_section and "TooPricey" not in new_section and "Scammy" not in new_section


def test_coming_up_covers_fourteen_days_with_prep_and_links(client, store):
    s = _rent(store)
    p = _place(store, s, "Maple Row")
    q = _place(store, s, "Far Away")
    store.add_tour(p["id"], f"{_day(12)}T10:00")
    store.add_tour(q["id"], f"{_day(20)}T10:00")
    page = client.get("/today").text
    coming = page.split('id="coming-h"')[1].split("</section>")[0]
    assert "Maple Row" in coming and f'href="/places/{p["id"]}#tours"' in coming
    assert "Before you go: check water pressure" in coming
    assert "Far Away" not in coming


def test_prep_line_only_lists_unanswered_items(store):
    s = _rent(store)
    p = _place(store, s)
    cl = {k: {"state": "ok", "note": ""} for k in Store.default_tour_checklist()}
    cl["noise"] = {"state": "", "note": ""}
    t = store.add_tour(p["id"], f"{_day(1)}T10:00", checklist=cl)
    assert today.prep_line(t).startswith("Before you go: check noise.")


def test_waiting_names_person_and_place_and_links_both(client, store):
    s = _rent(store)
    p = _place(store, s, "Maple Row")
    c = store.add_contact("Dana Lee")
    store.link_contact(p["id"], c["id"])
    old = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    store.log_contact(c["id"], "email", "Is it still free?", direction="out", at=old)  # place unset on the line
    page = client.get("/today").text
    wait = page.split('id="wait-h"')[1].split("</section>")[0]
    assert f'href="/contacts/{c["id"]}"' in wait and f'href="/places/{p["id"]}"' in wait
    assert "Dana Lee" in wait and "Maple Row" in wait


def test_days_ago_is_the_same_on_today_and_contacts(client, store, monkeypatch):
    s = _rent(store)
    p = _place(store, s)
    c = store.add_contact("Dana Lee")
    store.link_contact(p["id"], c["id"])
    # 4 days ago at 23:50 local: 3.x elapsed days by the clock, 4 calendar days
    now = datetime.now().astimezone()
    written = (now - timedelta(days=4)).replace(hour=23, minute=50)
    if written > now:
        written -= timedelta(days=1)
    store.log_contact(c["id"], "email", "hi", direction="out", at=written.astimezone(timezone.utc).isoformat())
    expected = helpers.days_since(written.astimezone(timezone.utc).isoformat())
    today_page = client.get("/today").text
    contacts_page = client.get("/contacts").text
    assert f"You wrote {expected} day" in today_page
    assert f"Waiting on a reply ({expected} day" in contacts_page
    assert store.waiting_on_reply()[0]["days"] == expected


def test_availability_warning_rule():
    y = helpers.today().year
    s = {"mode": "rent", "move_in": f"{y}-07-31"}
    assert today.availability_warning({"available_from": f"{y}-08-15"}, s) == "Available Aug 15, 2 weeks after your move-in date"
    assert today.availability_warning({"available_from": f"{y}-08-07"}, s) == ""      # 7 days later is fine
    assert today.availability_warning({"available_from": f"{y}-08-10"}, s) == "Available Aug 10, 10 days after your move-in date"
    assert today.availability_warning({"available_from": f"{y}-07-01"}, s) == ""      # earlier is fine
    assert today.availability_warning({"available_from": f"{y}-08-15"}, {"mode": "buy", "move_in": None}) == ""
    assert today.availability_warning({"available_from": ""}, s) == ""


def test_availability_warning_shows_on_place_page_and_today(client, store):
    s = _rent(store, move_in=_day(30))
    p = _place(store, s, "Late One", available_from=_day(60))
    assert "after your move-in date" in client.get(f"/places/{p['id']}").text
    assert "after your move-in date" in client.get("/today").text


# --------------------------------------------------------------------------- tours and stages
def test_buy_tour_leaves_stage_alone_and_says_so(client, store):
    b = store.add_search("Buy", "buy")
    p = _place(store, b, "House")
    r = client.post(f"/places/{p['id']}/tours", data={"day": _day(3), "time": "10:00"}, follow_redirects=True)
    assert store.get_place(p["id"])["stage"] == "Saved"
    assert "stays at Saved" in r.text
    p2 = _place(store, b, "Other house")
    assert "Booking a tour doesn't change the stage" in client.get(f"/places/{p2['id']}").text
    assert "Tour booked" not in client.get(f"/places/{p2['id']}").text.split('id="tours"')[1].split("</section>")[0]


def test_rent_tour_moves_saved_to_tour_booked(client, store):
    s = _rent(store)
    p = _place(store, s)
    r = client.post(f"/places/{p['id']}/tours", data={"day": _day(3), "time": "10:00"}, follow_redirects=True)
    assert store.get_place(p["id"])["stage"] == "Tour booked" and "moved to Tour booked" in r.text


def test_app_made_changes_never_say_ai(client, store):
    s = _rent(store)
    p = _place(store, s)
    client.post(f"/places/{p['id']}/tours", data={"day": _day(3), "time": "10:00"})
    client.post(f"/places/{p['id']}/stage", data={"stage": "Contacted"})
    page = client.get(f"/places/{p['id']}").text
    assert "by an AI app" not in page
    assert any("Because a tour was booked" in e["body"] for e in store.list_events(p["id"]))
    store.add_event(p["id"], "note", "from claude", source="ai")
    assert "by an AI app" in client.get(f"/places/{p['id']}").text


def test_toured_without_a_tour_is_allowed_with_a_gentle_note(client, store):
    s = _rent(store)
    p = _place(store, s)
    r = client.post(f"/places/{p['id']}/stage", data={"stage": "Toured"}, headers={"HX-Request": "true"})
    assert r.json()["ok"] is True and "haven't logged a tour" in r.json()["note"]
    p2 = _place(store, s, "Two")
    store.add_tour(p2["id"], f"{_day(1)}T10:00")
    r2 = client.post(f"/places/{p2['id']}/stage", data={"stage": "Toured"}, headers={"HX-Request": "true"})
    assert r2.json()["note"] == ""


def test_web_tour_form_warns_on_a_close_tour(client, store):
    s = _rent(store)
    a, b = _place(store, s, "Alpha"), _place(store, s, "Beta")
    store.add_tour(a["id"], f"{_day(2)}T10:00")
    r = client.post(f"/places/{b['id']}/tours", data={"day": _day(2), "time": "10:45"}, follow_redirects=True)
    assert "Heads up" in r.text and "Alpha" in r.text
    r2 = client.post(f"/places/{b['id']}/tours", data={"day": _day(2), "time": "14:00"}, follow_redirects=True)
    assert "Heads up" not in r2.text


# --------------------------------------------------------------------------- checklist
def test_first_buy_search_gets_buyer_checklist_and_old_lists_are_left_alone(tmp_path):
    s = Store(tmp_path / "a.db")
    s.add_search("Buy", "buy")
    labels = [i["label"] for i in s.list_checklist()]
    assert "Mortgage pre-approval letter" in labels and "Proof of funds" in labels and "Inspector picked" in labels
    assert "Proof of income" not in labels
    s.close()
    s2 = Store(tmp_path / "b.db")
    s2.add_search("Rent", "rent")
    s2.add_search("Buy", "buy")
    assert "Proof of income" in [i["label"] for i in s2.list_checklist()]
    s2.close()
    s3 = Store(tmp_path / "c.db")
    s3.update_checklist_item(s3.list_checklist()[0]["id"], done=True)
    s3.add_search("Buy", "buy")
    assert "Photo ID ready" in [i["label"] for i in s3.list_checklist()] and "Mortgage pre-approval letter" not in [i["label"] for i in s3.list_checklist()]
    s3.close()


def test_checklist_page_offers_the_buyer_items(client, store):
    s1 = _rent(store)
    page = client.get("/checklist").text
    assert "landlords" in page
    b = store.add_search("Buy", "buy")
    store.set_current_search(b["id"])
    page = client.get("/checklist").text
    assert "The usual buyer items" in page
    client.post("/checklist/defaults", data={"mode": "buy"})
    assert "Mortgage pre-approval letter" in [i["label"] for i in store.list_checklist()]
    assert "The usual buyer items" not in client.get("/checklist").text
