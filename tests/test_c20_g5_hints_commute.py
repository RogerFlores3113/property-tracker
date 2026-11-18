"""Cycle 20, G5 items 2 and 3: plain 'no address yet' hint, commute as a hard limit."""
import pytest

from mcp_util import call, server, text
from prophelper import enrich, redflags
from conftest import local_client


def test_no_address_is_a_plain_hint_not_a_scam_sign(store):
    store.add_search("C", "rent")
    p, _ = store.add_place(title="No addr", price=1000, listing_text="Sunny flat near campus.")
    out = text(call(server(store), "list_places"))
    line = [l for l in out.splitlines() if f"#{p['id']}" in l][0]
    assert "no address yet" in line and "possible scam" not in line.lower()


def test_real_scam_flag_keeps_the_scam_tag(store):
    store.add_search("C", "rent")
    p, _ = store.add_place(title="Scam", price=1000, listing_text="Send the deposit by gift card before you see it.")
    out = text(call(server(store), "list_places"))
    line = [l for l in out.splitlines() if f"#{p['id']}" in l][0]
    assert "possible scam" in line.lower()


def test_helpers_split_hints():
    flags = ["There is no address yet. Ask for one before you go anywhere or pay anything.", "It mentions Zelle."]
    assert redflags.scam_sign_flags(flags) == ["It mentions Zelle."]
    assert redflags.is_plain_hint(flags[0]) and not redflags.is_plain_hint(flags[1])


def test_board_shows_no_address_plainly(store):
    store.add_search("C", "rent")
    store.add_place(title="No addr", price=1000, listing_text="Sunny flat near campus.")
    html = local_client(store).get("/board").text
    assert "No address yet" in html and "thing to check" not in html


# ---- 3. hard commute limit
def _commute_setup(store, hard, minutes_by_anchor=(("Hospital", 45), ("Office", 20)), all_anchors=True):
    s = store.add_search("R", "rent", people=3)
    store.add_criterion(s["id"], "price", weight=50, dealbreaker=False, target={"max": 3000})
    anchors = [store.add_anchor(n, "x", 40.0, -88.0, search_id=s["id"]) for n, _ in minutes_by_anchor]
    t = {"mode": "drive", "minutes": 40, "all_anchors": True} if all_anchors else {"mode": "drive", "minutes": 40, "anchor_id": anchors[0]["id"]}
    if hard:
        t["hard"] = True
    store.add_criterion(s["id"], "commute", weight=40, dealbreaker=False, target=t)
    p, _ = store.add_place(title="Hyde Park", address="1 A St", price=2000, beds=3, utilities_estimate=100)
    for a, (_, m) in zip(anchors, minutes_by_anchor):
        store.set_commute(p["id"], a["id"], "drive", m, "you")
    return s, p


def test_soft_commute_default_still_fits(store):
    s, p = _commute_setup(store, hard=False)
    e = enrich.enrich_place(store, store.get_place(p["id"]), store.get_search(s["id"]))
    assert e["score"]["fit"] == "fits" and not e["score"]["fails_dealbreaker"]


@pytest.mark.parametrize("all_anchors", [True, False])
def test_hard_commute_fails_like_a_deal_breaker(store, all_anchors):
    s, p = _commute_setup(store, hard=True, all_anchors=all_anchors)
    e = enrich.enrich_place(store, store.get_place(p["id"]), store.get_search(s["id"]))
    sc = e["score"]
    assert sc["fails_dealbreaker"] and sc["fit"] != "fits"
    reason = " ".join(sc["fit_reasons"])
    assert "Hospital" in reason and "45 min" in reason and "5 min over" in reason and "Office" not in reason


def test_hard_commute_within_limit_passes(store):
    s, p = _commute_setup(store, hard=True, minutes_by_anchor=(("Hospital", 38), ("Office", 20)))
    e = enrich.enrich_place(store, store.get_place(p["id"]), store.get_search(s["id"]))
    assert e["score"]["fit"] == "fits"


def test_create_search_accepts_hard_flag(store):
    r = call(server(store), "create_search", name="R", mode="rent",
             anchors=[{"name": "Hospital", "address": "1 A St", "lat": 40.0, "lng": -88.0}],
             criteria=[{"kind": "commute", "target": {"anchor": "Hospital", "mode": "drive", "minutes": 40, "hard": True}}])
    c = [x for x in store.list_criteria(store.current_search()["id"]) if x["kind"] == "commute"][0]
    assert c["target"].get("hard") is True


def test_web_form_hard_checkbox(store):
    s = store.add_search("R", "rent")
    store.add_anchor("Work", "x", 40.0, -88.0, search_id=s["id"])
    cl = local_client(store)
    r = cl.post(f"/search/{s['id']}/criteria", data={"kind": "commute", "t_mode": "bike", "t_minutes": "20", "t_hard": "1", "weight": "10"}, follow_redirects=False)
    c = [x for x in store.list_criteria(s["id"]) if x["kind"] == "commute"][0]
    assert c["target"].get("hard") is True
    cl.post(f"/criteria/{c['id']}", data={"t_mode": "bike", "t_minutes": "20", "weight": "10"}, follow_redirects=False)
    assert not store.get_criterion(c["id"])["target"].get("hard")
