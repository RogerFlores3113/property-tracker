"""Cycle 32 G5: Today's "and N more" under Best fits says how many have an incomplete cost; Today's closing target uses a place's own closing date;
the new-search form has the people and adults fields."""
from datetime import date, timedelta

import pytest
from conftest import local_client
from mcp_util import call, server, text

from prophelper import enrich, helpers, today


def _buy(store, complete, partial, target=None):
    s = store.add_search("C", "buy", budget_max=400000, **({"target_close": target} if target else {}))
    store.add_criterion(s["id"], "price", weight=50, dealbreaker=False, target={"max": 400000})
    ids = []
    for i in range(complete + partial):
        kw = dict(title=f"Condo {i}", address=f"{i + 1} Oak St", price=300000 + i * 1000, beds=2, property_tax=3600, hoa=0, search_id=s["id"])
        if i < complete:
            kw["insurance"] = 1200
        p, _ = store.add_place(**kw)
        ids.append(p["id"])
    store.set_current_search(s["id"])
    return s, ids


@pytest.mark.parametrize("complete,partial,more", [
    (5, 2, 2),
    (4, 1, 1),
    (3, 3, 0),
    (6, 1, 3),
    (3, 0, 0),
    (5, 0, 2),
])
def test_more_count_counts_only_complete_places(store, complete, partial, more):
    # cycle 33: a place whose cost is not complete is under "Needs a cost check", so "and N more" under Best fits counts complete places only
    s, _ = _buy(store, complete, partial)
    d = today.build(store, store.get_search(s["id"]))
    assert len(d["fits"]) == min(3, complete)
    assert d["more"]["fits"] == more
    assert d["more_fits_note"] == ""
    assert len(d["cost_check"]) == partial
    html = local_client(store).get("/today").text
    if more:
        assert f"and {more} more." in html
    else:
        assert " more" not in html.split("Best fits right now")[1].split("</section>")[0]
    out = text(call(server(store), "todays_list"))
    if more:
        assert f"... and {more} more. Use list_places for the rest." in out
    assert "not complete yet" not in out.split("Needs a cost check")[0]


def test_more_count_matches_every_place_that_passes(store):
    s, ids = _buy(store, 5, 2)
    rows = enrich.enrich_places(store, store.get_search(s["id"]))
    passing = [r for r in rows if today.is_best_fit(r)]
    d = today.build(store, store.get_search(s["id"]))
    assert len(d["fits"]) + d["more"]["fits"] == len(passing) == 5  # cycle 33: the 2 with a cost that is not complete are under "Needs a cost check"
    assert len(d["cost_check"]) == 2


# ---- closing target
def _iso(n):
    return (date.today() + timedelta(days=n)).isoformat()


def _line(store):
    html = local_client(store).get("/today").text
    import re
    m = re.search(r'<p class="fine" id="closing-target">(.*?)</p>', html, re.S)
    return m.group(1) if m else None


def test_place_closing_date_beats_search_target(store):
    s, ids = _buy(store, 1, 0, target=_iso(90))
    store.add_place_date(ids[0], "closing", _iso(87))
    nice = helpers.closing_info({"mode": "buy", "target_close": _iso(87)})
    line = _line(store)
    assert line == nice["today_line"] + " (for Condo 0)"
    assert "in 87 days" in line and "in 90 days" not in line


def test_no_place_date_keeps_search_target(store):
    s, ids = _buy(store, 1, 0, target=_iso(90))
    assert _line(store) == helpers.closing_info(store.get_search(s["id"]))["today_line"]
    assert "in 90 days" in _line(store)


def test_nearest_future_place_date_wins(store):
    s, ids = _buy(store, 3, 0, target=_iso(90))
    store.add_place_date(ids[0], "closing", _iso(60))
    store.add_place_date(ids[1], "closing", _iso(45))
    store.add_place_date(ids[2], "closing", _iso(120))
    line = _line(store)
    assert "in 45 days" in line and line.endswith("(for Condo 1)")


def test_passed_place_date_is_ignored(store):
    s, ids = _buy(store, 2, 0, target=_iso(90))
    store.add_place_date(ids[0], "closing", _iso(30))
    store.move_place(ids[0], "Passed") if hasattr(store, "move_place") else store.update_place(ids[0], stage="Passed")
    assert "in 90 days" in _line(store) and "(for" not in _line(store)


def test_past_place_date_falls_back_to_search_target(store):
    s, ids = _buy(store, 1, 0, target=_iso(90))
    store.add_place_date(ids[0], "closing", _iso(-5))
    assert "in 90 days" in _line(store) and "(for" not in _line(store)


def test_same_day_as_target_is_plain(store):
    s, ids = _buy(store, 1, 0, target=_iso(40))
    store.add_place_date(ids[0], "closing", _iso(40))
    assert "(for" not in _line(store) and "in 40 days" in _line(store)


def test_place_date_alone_without_search_target(store):
    s, ids = _buy(store, 1, 0)
    store.add_place_date(ids[0], "closing", _iso(20))
    assert _line(store) == helpers.closing_info({"mode": "buy", "target_close": _iso(20)})["today_line"] + " (for Condo 0)"


def test_title_is_escaped_in_the_line(store):
    s, ids = _buy(store, 1, 0, target=_iso(90))
    store.update_place(ids[0], title="<b>x</b>")
    store.add_place_date(ids[0], "closing", _iso(20))
    html = local_client(store).get("/today").text
    assert "(for <b>x</b>)" not in html and "&lt;b&gt;x&lt;/b&gt;" in html


def test_rent_search_has_no_closing_line(store):
    s = store.add_search("R", "rent")
    store.set_current_search(s["id"])
    assert _line(store) is None


# ---- search form
def test_new_search_form_has_people_and_adults(store):
    html = local_client(store).get("/search").text
    assert 'name="adults"' in html and 'name="people"' in html
    assert "Adults who will sign for it" in html


def test_new_search_saves_adults_and_people(store):
    c = local_client(store)
    r = c.post("/search", data={"name": "Family", "mode": "rent", "people": "4", "adults": "2", "budget_max": "2400"}, follow_redirects=False)
    assert r.status_code in (302, 303)
    s = [x for x in store.list_searches() if x["name"] == "Family"][0]
    assert s["people"] == 4 and s["adults"] == 2


def test_new_search_without_adults_leaves_it_empty(store):
    c = local_client(store)
    c.post("/search", data={"name": "Solo", "mode": "rent", "people": "2"}, follow_redirects=False)
    s = [x for x in store.list_searches() if x["name"] == "Solo"][0]
    assert s["people"] == 2 and s["adults"] is None


def test_new_buy_search_ignores_adults(store):
    c = local_client(store)
    c.post("/search", data={"name": "Buy", "mode": "buy", "adults": "2"}, follow_redirects=False)
    s = [x for x in store.list_searches() if x["name"] == "Buy"][0]
    assert s["adults"] is None


def test_bad_adults_gives_a_plain_error(store):
    c = local_client(store)
    r = c.post("/search", data={"name": "Bad", "mode": "rent", "adults": "0"}, follow_redirects=True)
    assert "whole number" in r.text
    assert not [x for x in store.list_searches() if x["name"] == "Bad"]
