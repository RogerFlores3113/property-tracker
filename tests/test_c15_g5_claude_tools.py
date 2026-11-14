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


# ---- 3. Today, Compare, buyer wording
def test_under_contract_place_is_not_a_best_fit(store):
    from prophelper import enrich, today
    s = store.add_search("B", "buy", budget_max=600000)
    store.add_criterion(s["id"], "price", weight=30, dealbreaker=True, target={"max": 600000})
    a, _ = store.add_place(title="Open", address="1 A St", price=400000, property_tax=4000, insurance=1200)
    b, _ = store.add_place(title="Signed", address="2 A St", price=400000, property_tax=4000, insurance=1200)
    store.move_stage(b["id"], "Under contract", by_ai=False)
    rows = enrich.enrich_places(store, s)
    names = [p["title"] for p in today.best_fits(rows)]
    assert "Signed" not in names


def test_compare_does_not_say_no_highest_when_other_scores_differ(store):
    s = store.add_search("R", "rent", budget_max=3000)
    store.add_criterion(s["id"], "price", weight=30, target={"max": 3000})
    store.add_criterion(s["id"], "beds", weight=30, dealbreaker=True, target={"min": 2})
    ids = []
    for i, beds in enumerate([2, 2, 1]):
        p, _ = store.add_place(title=f"P{i}", address=f"{i} A St", price=1500, beds=beds, utilities_estimate=50, deposit=500)
        ids.append(p["id"])
    out = text(call(server(store), "compare_places", place_ids=ids))
    print(out)
    assert "No highest score" not in out
    assert "tied at 100" in out and "left out" in out


def test_buy_pets_note_says_seller_not_landlord():
    from prophelper.parsers import parse_listing
    note = parse_listing("Nice home. Price $500,000. Cats ok. Dogs need approval.", buying=True)["found_in_listing"]
    assert "landlord" not in note and "seller or listing agent" in note
    assert "landlord" in parse_listing("Nice flat. Rent $1500/mo. Cats ok. Dogs need approval.")["found_in_listing"]
