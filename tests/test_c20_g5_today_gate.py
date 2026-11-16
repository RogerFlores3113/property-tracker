"""Cycle 20, G5 item 1: Today's Best fits gate (cost unknowns, over budget, buy pages)."""
import pytest

from mcp_util import call, server, text
from prophelper import enrich, today


def _rent(store, dealbreaker=False, pets=None):
    s = store.add_search("C", "rent", **({"pet_kind": pets} if pets else {}))
    store.add_criterion(s["id"], "price", weight=50, dealbreaker=dealbreaker, target={"max": 2000})
    return s


def _rows(store, s):
    return enrich.enrich_places(store, store.get_search(s["id"]))


def test_named_utilities_unknown_leave_best_fits(store):
    s = _rent(store)
    a, _ = store.add_place(title="Hilltop", address="1 A St", price=1300, beds=1,
                           tenant_pays="electric, gas")
    b, _ = store.add_place(title="Complete", address="2 A St", price=1500, beds=1, utilities_estimate=100)
    rows = _rows(store, s)
    assert [p["title"] for p in today.best_fits(rows)] == ["Complete"]
    cc = today.cost_check(rows)
    assert [c["place"]["title"] for c in cc] == ["Hilltop"]
    assert "Ask the landlord" in cc[0]["text"]
    assert "Needs a cost check: #%d" % a["id"] in text(call(server(store), "todays_list"))


def test_pet_rent_and_utilities_unknown_for_a_pet_search(store):
    s = _rent(store, pets="dog")
    store.add_place(title="Sparse", address="1 A St", price=1300, beds=1)
    rows = _rows(store, s)
    assert today.best_fits(rows) == []


def test_over_budget_not_best_fit_even_when_price_is_soft(store):
    s = store.add_search("C", "rent")
    store.add_criterion(s["id"], "price", weight=50, dealbreaker=False, target={"max": 1600})
    store.add_place(title="Over", address="1 A St", price=1620, beds=1, utilities_estimate=0)
    store.add_place(title="Under", address="2 A St", price=1500, beds=1, utilities_estimate=0)
    rows = _rows(store, s)
    assert [p["title"] for p in today.best_fits(rows)] == ["Under"]
    nm = today.near_misses(rows)
    assert [n["place"]["title"] for n in nm] == ["Over"] and "$20 over" in nm[0]["text"]
    assert "Near miss: #" in text(call(server(store), "todays_list"))


@pytest.mark.parametrize("fields", [{}, {"property_tax": 3000, "insurance": 900}, {"hoa": 200, "insurance": 900}, {"property_tax": 3000}])
def test_buy_sparse_gate(store, fields):
    s = store.add_search("B", "buy")
    store.add_criterion(s["id"], "price", weight=50, dealbreaker=False, target={"max": 400000})
    store.add_place(title="Condo", address="1 A St", price=250000, beds=2, **fields)
    store.add_place(title="Complete", address="2 A St", price=250000, beds=2, property_tax=3000, insurance=900, hoa=100)
    rows = _rows(store, s)
    top = today.best_fits(rows)
    if len(fields) >= 2:
        assert "Condo" in [p["title"] for p in top]  # one unknown part still ranks
    else:
        assert [p["title"] for p in top] == ["Complete"]
        out = text(call(server(store), "todays_list"))
        assert "Ask the listing agent" in out and "Ask the landlord" not in out
