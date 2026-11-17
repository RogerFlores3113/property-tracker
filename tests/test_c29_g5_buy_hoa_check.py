"""Cycle 29 G5 item 3: a buy place whose HOA is in the listing but not counted is "Fits, but check", like one missing its insurance."""
from __future__ import annotations

import pytest
from mcp_util import call, server, text

from prophelper import compare, enrich

NOTE = 'The listing also says "{q}". It is a monthly fee and it is not counted anywhere. Check what it is for.'
QUOTES = ["HOA: $0.42/sf monthly (includes water, trash, exterior)", "Condo fee $0.50 per sq ft per month, includes water", "Association dues are $0.35/sqft monthly"]


def _search(store):
    s = store.add_search("B", "buy", budget_max=500000)
    store.add_criterion(s["id"], "price", weight=30, dealbreaker=True, target={"max": 500000})
    return s


def _place(store, **kw):
    _place.n = getattr(_place, "n", 0) + 1
    base = dict(title="Condo", address=f"{_place.n} A St", price=329000, property_tax=5100, insurance=1050, hoa=0)
    p, _ = store.add_place(**{**base, **kw})
    return p


def _e(store, s, p):
    return next(r for r in enrich.enrich_places(store, s) if r["id"] == p["id"])


@pytest.mark.parametrize("quote", QUOTES)
def test_open_hoa_note_is_fits_but_check(store, quote):
    s = _search(store)
    p = _place(store, reader_notes=NOTE.format(q=quote))
    e = _e(store, s, p)
    assert e["score"]["fit"] == "fits" and e["score"]["fit_label"] == "Fits, but check"
    assert any("HOA not counted yet" in c for c in e["score"]["concerns"]), e["score"]["concerns"]


def test_missing_hoa_and_missing_insurance_read_the_same(store):
    s = _search(store)
    a = _e(store, s, _place(store, title="NoHOA", hoa=None))
    b = _e(store, s, _place(store, title="NoIns", insurance=None))
    assert a["score"]["fit_label"] == b["score"]["fit_label"] == "Fits, but check"
    c = _e(store, s, _place(store, title="OpenHOA", reader_notes=NOTE.format(q=QUOTES[0])))
    assert c["score"]["fit_label"] == a["score"]["fit_label"] and "HOA" in c["score"]["concerns"][0]


def test_complete_place_still_fits(store):
    s = _search(store)
    e = _e(store, s, _place(store, hoa=300))
    assert e["score"]["fit_label"] == "Fits" and not e["score"]["concerns"]
    e2 = _e(store, s, _place(store, title="Plain", hoa=0, reader_notes="The listing says the buyer pays a $400 move-in fee at closing. Ask the agent."))
    assert e2["score"]["fit_label"] == "Fits"


def test_shows_on_compare_and_claude_tools(store, client):
    s = _search(store)
    p = _place(store, reader_notes=NOTE.format(q=QUOTES[0]))
    q = _place(store, title="Done", hoa=300)
    e = _e(store, s, p)
    assert "Fits, but check" in compare._fit_cell(e)["text"] and "HOA" in compare._fit_cell(e)["text"]
    t = text(call(server(store), "compare_places", place_ids=[p["id"], q["id"]]))
    assert "Fits, but check" in t
