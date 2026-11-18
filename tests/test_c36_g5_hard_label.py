"""Cycle 36 G5, rule ll: the search overview and the criterion labels say a commute limit is hard when the app enforces it ("40 min or less, hard limit"),
in Claude's create_search/get_overview/update_search replies, the score items (Compare, place) and the page; a soft limit says nothing of the kind."""
import pytest
from conftest import local_client
from mcp_util import call, server, text

from prophelper import scoring


def _anchors():
    return [{"name": "Hospital", "address": "1 A St", "lat": 40.0, "lng": -88.0}, {"name": "Office", "address": "2 B St", "lat": 40.1, "lng": -88.1}]


def _create(store, criteria):
    return text(call(server(store), "create_search", name="t", mode="rent", anchors=_anchors(), criteria=criteria))


def _crit_line(out):
    return next(x for x in out.splitlines() if x.startswith("Criteria:"))


@pytest.mark.parametrize("mode,mins", [("drive", 40), ("bike", 20), ("walk", 15), ("transit", 35)])
def test_create_search_reply_and_overview_say_hard(store, mode, mins):
    out = _create(store, [{"kind": "commute", "target": {"anchor": "Hospital", "mode": mode, "minutes": mins, "hard": True}},
                          {"kind": "commute", "target": {"anchor": "Office", "mode": mode, "minutes": mins}}])
    line = _crit_line(out)
    assert f"to Hospital, {mins} min or less, hard limit" in line
    assert f"to Office, {mins} min or less</untrusted>" in line and "Office, " + str(mins) + " min or less, hard" not in line
    ov = _crit_line(text(call(server(store), "get_overview")))
    assert f"to Hospital, {mins} min or less, hard limit" in ov and "Office, " + str(mins) + " min or less, hard" not in ov


def test_a_custom_name_gets_the_words_too_but_never_twice(store):
    out = _create(store, [{"kind": "commute", "label": "Campus by bike", "target": {"anchor": "Hospital", "mode": "bike", "minutes": 20, "hard": True}},
                          {"kind": "commute", "label": "Office, hard limit", "target": {"anchor": "Office", "mode": "bike", "minutes": 20, "hard": True}}])
    line = _crit_line(out)
    assert "Campus by bike, hard limit" in line
    assert line.count("hard limit") == 2  # one for each, none doubled


def test_other_kinds_and_soft_commutes_say_nothing_of_hard(store):
    out = _create(store, [{"kind": "price", "target": {"max": 1600}}, {"kind": "commute", "target": {"anchor": "Hospital", "mode": "bike", "minutes": 20}}])
    assert "hard" not in _crit_line(out)


def test_score_items_and_the_page_use_the_label(store):
    srv = server(store)
    _create(store, [{"kind": "commute", "target": {"anchor": "Hospital", "mode": "drive", "minutes": 40, "hard": True}}])
    s = store.current_search()
    c = store.list_criteria(s["id"])[0]
    assert scoring.hard_label("Drive to Hospital", "commute", c["target"]) == "Drive to Hospital, hard limit"
    assert scoring.hard_label("Rent", "price", {"hard": True}) == "Rent"
    html = local_client(store).get("/search").text
    assert "Drive to Hospital, 40 min or less, hard limit" in html


def test_web_form_label_follows_the_hard_checkbox(store):
    _create(store, [{"kind": "commute", "target": {"anchor": "Hospital", "mode": "bike", "minutes": 20}}])
    s = store.current_search()
    cl = local_client(store)
    a = store.list_anchors(s["id"])[0]
    r = cl.post(f"/search/{s['id']}/criteria", data={"kind": "commute", "t_anchor_id": str(a["id"]), "t_mode": "bike", "t_minutes": "20", "t_hard": "1", "weight": "10"}, follow_redirects=False)
    assert r.status_code in (302, 303)
    hard = [c for c in store.list_criteria(s["id"]) if c["target"].get("hard")][0]
    assert hard["label"].endswith("20 min or less, hard limit") or not hard["label"]
    out = _crit_line(text(call(server(store), "get_overview")))
    assert "20 min or less, hard limit" in out
