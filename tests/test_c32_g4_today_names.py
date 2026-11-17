"""Cycle 32, G4: Today's "Needs a cost check" names the amounts the cost leaves out."""
from __future__ import annotations

import pytest

from prophelper import enrich, today


def row_with(store, label, **kw):
    s = store.add_search("C", "rent")
    store.add_criterion(s["id"], "price", weight=50, dealbreaker=False, target={"max": 2000})
    store.add_place(title="Hilltop", address="1 A St", price=1300, beds=1, **kw)
    row = enrich.enrich_places(store, store.get_search(s["id"]))[0]
    return {**row, "cost": {**row["cost"], "uncounted": list(row["cost"]["uncounted"]) + ["some amounts in the listing notes"], "listing_notes_label": label}}


@pytest.mark.parametrize("label,want", [
    ("the $96 amount in the listing notes", "the $96 amount in the listing notes is not counted yet"),
    ("the $96 and $40 amounts in the listing notes", "the $96 and $40 amounts in the listing notes are not counted yet"),
    ("the $75 flat fee in the listing notes", "the $75 flat fee in the listing notes is not counted yet"),
    ("the parking cost in the listing notes", "the parking cost in the listing notes is not counted yet"),
])
def test_named_pays_list(store, label, want):
    why = today.cost_unsettled(row_with(store, label, tenant_pays="electric, gas"))
    assert why == f"you pay electric and gas and {want}"


def test_whole_utilities_bill(store):
    why = today.cost_unsettled(row_with(store, "the $140 amount in the listing notes", listing_text="Tenant pays all utilities."))
    assert "$140" in why and "were not read" not in why


def test_unnamed_stays_generic(store):
    why = today.cost_unsettled(row_with(store, "some amounts in the listing notes", tenant_pays="electric, gas"))
    assert why == "you pay electric and gas and the listing gives amounts that were not read"


def test_complete_place_says_nothing(store):
    s = store.add_search("C", "rent")
    store.add_place(title="Hilltop", address="1 A St", price=1300, beds=1, utilities_estimate=80, parking_cost=0)
    row = enrich.enrich_places(store, store.get_search(s["id"]))[0]
    assert not today.cost_unsettled(row)
