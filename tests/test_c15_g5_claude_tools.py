"""Cycle 15, group G5: Claude tool replies (insurance, HOA), Today/Compare, flags, links, CSV."""
from mcp_util import call, server, text


def rent_store(store, mode="rent"):
    store.add_search("S", mode)
    return store


# ---- 1. insurance warnings
def test_add_places_warns_about_small_insurance(store):
    rent_store(store)
    out = text(call(server(store), "add_places", places=[{"title": "A", "address": "1 Oak St", "price": 1500, "insurance": 15}]))
    assert "saved as $15 a YEAR" in out and "$180" in out


def test_update_place_insurance_75_warns(store):
    rent_store(store)
    p, _ = store.add_place(title="A", address="1 Oak St", price=1500)
    out = text(call(server(store), "update_place", place_id=p["id"], insurance=75))
    assert "$75 a YEAR" in out and "$900" in out
    assert "YEAR" not in text(call(server(store), "update_place", place_id=p["id"], insurance=180))


def test_reader_note_agrees_with_sent_insurance(store):
    rent_store(store)
    out = text(call(server(store), "add_place", title="A", address="1 Oak St", price=1500, insurance=14,
                    listing_text="Rent $1500/mo. Renter's insurance required $14/mo."))
    assert "saved as $168 a year" not in out
    assert "$14 a year" in out
    assert store.list_places(store.current_search()["id"])[0]["insurance"] == 14


# ---- 2. HOA
def test_hoa_quarterly_reconciliation_note(store):
    rent_store(store, "buy")
    out = text(call(server(store), "add_place", title="H", address="2 Oak St", price=400000, hoa=600,
                    listing_text="3 bed house for sale. Price $400,000. HOA $600 billed quarterly"))
    assert "every 3 months" in out and "$200 a month" in out and "kept your value" in out
    assert store.list_places(store.current_search()["id"])[0]["hoa"] == 600


def test_update_place_null_hoa_clears(store):
    rent_store(store, "buy")
    p, _ = store.add_place(title="H", address="2 Oak St", price=400000, hoa=300)
    out = text(call(server(store), "update_place", place_id=p["id"], hoa=None))
    assert store.get_place(p["id"])["hoa"] is None and "hoa" in out.lower()
    p2, _ = store.add_place(title="H2", address="3 Oak St", price=400000, hoa=300)
    call(server(store), "update_place", place_id=p2["id"], ai_notes="x")
    assert store.get_place(p2["id"])["hoa"] == 300
