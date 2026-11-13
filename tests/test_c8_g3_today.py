"""Cycle 8, G3: Today and todays_list come from one place; AI-text goes to Check first; card text lists every unknown."""
from __future__ import annotations

import re

from conftest import local_client
from mcp_util import call, server, text
from prophelper import enrich, today


def _setup(store):
    s = store.add_search("R", "rent")
    store.add_criterion(s["id"], "beds", weight=10, target={"min": 1})
    store.add_place(title="Priced", address="2 A St", price=1500, beds=1, utilities_included="all", deposit=500)
    store.add_place(title="NoPrice", address="1 A St", beds=2)
    return s


def _lines(out, header):
    return [l for l in out.split("\n") if l.startswith(header)]


def test_no_price_place_stays_under_needs_a_price_after_a_commute_criterion_is_added(store):
    s = _setup(store)
    assert [p["title"] for p in today.needs_price(enrich.enrich_places(store, s))] == ["NoPrice"]
    store.add_anchor("Work", address="1 Main St")
    store.add_criterion(s["id"], "commute", weight=60, dealbreaker=True, target={"anchor": "Work", "mode": "bike", "minutes": 15})
    rows = enrich.enrich_places(store, s)
    np = [r for r in rows if r["title"] == "NoPrice"][0]
    assert np["score"]["check"] and np["score_total"] < today.MIN_FIT_SCORE
    assert [p["title"] for p in today.needs_price(rows)] == ["NoPrice"]
    page = local_client(store).get("/today").text
    assert "Needs a price" in page
    out = text(call(server(store), "todays_list"))
    assert any("NoPrice" in l for l in _lines(out, "Needs a price:"))
    data = today.build(store, s)
    assert [p["title"] for p in data["needs_price"]] == ["NoPrice"]


def test_web_and_todays_list_hold_the_same_places(store):
    s = _setup(store)
    store.add_place(title="Scammy", address="3 A St", price=900, beds=1, listing_text="Owner is abroad. Wire the deposit before a showing.")
    data = today.build(store, s)
    out = text(call(server(store), "todays_list"))
    for key, header in (("needs_price", "Needs a price:"), ("check_first", "Check first:")):
        names = [(x["place"] if "place" in x else x)["title"] for x in data[key]]
        shown = _lines(out, header)
        assert len(shown) == len(names)
        assert all(any(n in l for l in shown) for n in names)
    best = out.split("Best fits right now:")[1].split("Needs a price:")[0]
    assert all(p["title"] in best for p in data["fits"])


def test_buy_check_first_uses_contract_and_escrow_words(store):
    s = store.add_search("B", "buy")
    store.add_place(title="Odd House", address="1 A St", price=250000, beds=3, listing_text="Owner is abroad. Wire the deposit before a showing.")
    data = today.build(store, s)
    t = data["check_first"][0]["text"]
    assert "contract" in t and "escrow" in t and "lease" not in t
    out = text(call(server(store), "todays_list"))
    assert "escrow" in out and "lease" not in _lines(out, "Check first:")[0]


def test_card_lists_every_unknown_thing(store):
    s = store.add_search("R", "rent")
    store.add_criterion(s["id"], "parking", weight=20, target={"want": "garage"})
    store.add_criterion(s["id"], "laundry", weight=20, target={"want": "in_unit"})
    store.add_criterion(s["id"], "beds", weight=100, target={"min": 1})
    store.add_place(title="Elm", address="1 A St", price=1500, beds=2, utilities_included="all", deposit=500)
    rows = enrich.enrich_places(store, s)
    n = len(rows[0]["score"]["unknown"])
    page = local_client(store).get("/today").text
    m = re.search(r"(\d+) things? still to check: ([^<]*)", page)
    assert m and int(m.group(1)) == n
    assert all(lbl in m.group(2).replace("&#39;", "'") for lbl in rows[0]["score"]["unknown"][:1])
    assert len(m.group(2).split("; ")) == n
