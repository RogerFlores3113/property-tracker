"""Cycle 34 group G5: Today's closing target uses the date of a place in the Closing stage, names it, and agrees with the place page
(buyer l24 moved to Closing)."""
import os
import re
from datetime import date, timedelta

import pytest
from conftest import local_client

from prophelper import helpers, today
from prophelper.mcp_server import build_server

HERE = os.path.join(os.path.dirname(__file__), "fixtures", "panel")


def _iso(n):
    return (date.today() + timedelta(days=n)).isoformat()


def _buy_search(store, target=None):
    s = store.add_search("C", "buy", budget_max=400000, **({"target_close": target} if target else {}))
    store.set_current_search(s["id"])
    return s


def _add(store, s, title, days=None, stage=None, listing_text=None):
    p, _ = store.add_place(title=title, address=f"{abs(hash(title)) % 900 + 1} Oak St", price=300000, beds=2, search_id=s["id"], **({"listing_text": listing_text} if listing_text else {}))
    if days is not None:
        store.add_place_date(p["id"], "closing", _iso(days))
    if stage:
        for st_ in ("Toured", "Offer drafted", "Offer made", "Under contract", "Inspection", "Closing"):
            store.move_stage(p["id"], st_)
            if st_ == stage:
                break
    return p


def _today_line(store):
    html = local_client(store).get("/today").text
    m = re.search(r'<p class="fine" id="closing-target">(.*?)</p>', html, re.S)
    return m.group(1) if m else None


def _place_line(store, pid):
    html = local_client(store).get(f"/places/{pid}").text
    m = re.search(r"Closing (?:in \d+ days|tomorrow|today|was [^<(]*)\s*\(([A-Z][a-z]{2} \d{1,2}, \d{4})\)", html)
    return m.group(0) if m else None


def _line_for(days):
    return helpers.closing_info({"mode": "buy", "target_close": _iso(days)})["today_line"]


def test_closing_stage_place_date_is_used_and_named_and_agrees_with_the_place_page(store):
    s = _buy_search(store, _iso(90))
    p = _add(store, s, "Hilliard Commons Condo", days=95, stage="Closing")
    line = _today_line(store)
    assert line == _line_for(95) + " (for Hilliard Commons Condo)"
    assert "in 95 days" in line and "in 90 days" not in line
    page = _place_line(store, p["id"])
    assert page and "in 95 days" in page
    date_text = re.search(r"\(([A-Z][a-z]{2} \d{1,2}, \d{4})\)", page).group(1)
    assert f"Closing target: {date_text}," in line


def test_closing_stage_place_beats_a_nearer_date_on_another_place(store):
    s = _buy_search(store, _iso(90))
    _add(store, s, "Saved One", days=20)
    _add(store, s, "Closing One", days=60, stage="Closing")
    line = _today_line(store)
    assert line == _line_for(60) + " (for Closing One)"


def test_closing_stage_place_on_the_search_target_day_is_named(store):
    s = _buy_search(store, _iso(40))
    _add(store, s, "Closing One", days=40, stage="Closing")
    line = _today_line(store)
    assert line == _line_for(40) + " (for Closing One)"


def test_saved_place_on_the_search_target_day_stays_plain(store):
    s = _buy_search(store, _iso(40))
    _add(store, s, "Saved One", days=40)
    assert _today_line(store) == _line_for(40)


def test_two_closing_stage_places_use_the_nearer_one(store):
    s = _buy_search(store, _iso(90))
    _add(store, s, "Closing A", days=70, stage="Closing")
    _add(store, s, "Closing B", days=50, stage="Closing")
    assert _today_line(store) == _line_for(50) + " (for Closing B)"


def test_past_date_of_a_closing_stage_place_is_still_its_own_date(store):
    s = _buy_search(store, _iso(90))
    p = _add(store, s, "Closing One", days=-3, stage="Closing")
    line = _today_line(store)
    assert line == _line_for(-3) + " (for Closing One)" and "3 days ago" in line
    assert "was" in (_place_line(store, p["id"]) or "was")  # the place page also counts from the place's own date


def test_passed_and_closed_places_are_not_used(store):
    s = _buy_search(store, _iso(90))
    p = _add(store, s, "Closing One", days=30, stage="Closing")
    store.move_stage(p["id"], "Closed")
    assert _today_line(store) == _line_for(90)
    q = _add(store, s, "Other", days=25)
    store.move_stage(q["id"], "Passed")
    assert _today_line(store) == _line_for(90)


def test_no_place_date_keeps_the_search_target_even_with_a_place_in_closing(store):
    s = _buy_search(store, _iso(90))
    _add(store, s, "Closing One", stage="Closing")
    assert _today_line(store) == _line_for(90)


def test_title_is_escaped(store):
    s = _buy_search(store, _iso(90))
    _add(store, s, "<b>x</b>", days=20, stage="Closing")
    html = local_client(store).get("/today").text
    assert "(for <b>x</b>)" not in html and "&lt;b&gt;x&lt;/b&gt;" in html


def test_reviewer_repro_buyer_l24_listing_moved_to_closing(store):
    with open(os.path.join(HERE, "r33-buyer-l24.txt"), encoding="utf-8") as fh:
        text = fh.read()
    s = store.add_search("Columbus", "buy", budget_max=340000, target_close="2027-02-15")
    store.set_current_search(s["id"])
    c = local_client(store)
    r = c.post("/add/save", data={"listing_text": text, "title": "Hilliard Commons Condo", "address": "3980 Main St #7", "search_id": str(s["id"]), "price": "265000"}, follow_redirects=False)
    assert r.status_code == 303
    pid = store.list_places()[0]["id"]
    for st_ in ("Toured", "Offer drafted", "Offer made", "Under contract", "Inspection", "Closing"):
        store.move_stage(pid, st_)
    assert [d["date"] for d in store.list_place_dates(pid)] == ["2027-02-20"]
    d = today.closing_target(store, store.get_search(s["id"]), today_=date(2026, 11, 17))
    assert d["today_line"] == "Closing target: Feb 20, 2027, in 95 days (for Hilliard Commons Condo)"
    assert d["days"] == "95"
    place_info = helpers.closing_info({"mode": "buy", "target_close": "2027-02-20"}, date(2026, 11, 17))
    assert place_info["place_line"] == "Closing in 95 days (Feb 20, 2027)"


def test_rent_search_has_no_closing_line(store):
    s = store.add_search("R", "rent")
    store.set_current_search(s["id"])
    assert _today_line(store) is None
