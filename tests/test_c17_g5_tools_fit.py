"""Cycle 17, G5: null clears pet and parking money, waivable pet limit fit wording, commute note in Compare, one note per line."""
import pytest

from mcp_util import call, server, text
from prophelper import enrich


# ---- 4. null clears
@pytest.mark.parametrize("field,value", [("pet_fee", 150), ("pet_deposit", 300), ("pet_rent", 35), ("parking_cost", 80), ("application_fee", 40)])
def test_null_clears_money_fields(store, field, value):
    store.add_search("C", "rent")
    srv = server(store)
    call(srv, "add_place", title="A", address="1 Oak St", price=1000, **{field: value})
    assert store.get_place(1)[field] == value
    out = text(call(srv, "update_place", place_id=1, **{field: None}))
    assert "Nothing changed" not in out
    assert store.get_place(1)[field] is None


def test_null_clears_all_four_at_once_and_leaves_others(store):
    store.add_search("C", "rent")
    srv = server(store)
    call(srv, "add_place", title="A", address="1 Oak St", price=1000, pet_fee=150, pet_deposit=300, pet_rent=35, parking_cost=80, deposit=500)
    call(srv, "update_place", place_id=1, pet_fee=None, pet_deposit=None, pet_rent=None, parking_cost=None)
    p = store.get_place(1)
    assert p["pet_fee"] is None and p["pet_deposit"] is None and p["pet_rent"] is None and p["parking_cost"] is None
    assert p["deposit"] == 500 and p["price"] == 1000


# ---- 5. fit wording
@pytest.mark.parametrize("limit_text", ["Pet limit 25 lbs, can be waived.", "No dogs over 25 lbs unless approved by management.", "Weight limit 25 lb, case-by-case exceptions."])
@pytest.mark.parametrize("dealbreaker", [True, False])
def test_waivable_pet_limit_says_fits_but_check(store, limit_text, dealbreaker):
    s = store.add_search("C", "rent")
    store.add_criterion(s["id"], "price", weight=50, dealbreaker=False, target={"max": 1500})
    store.add_criterion(s["id"], "pets", weight=20, dealbreaker=dealbreaker, target={})
    store.update_search(s["id"], pet_kind="dog", pet_weight=40, pet_count=1)
    p, _ = store.add_place(title="Dog", address="1 A St", price=1000, beds=1, pets="dogs", pet_weight_limit=25, listing_text=limit_text)
    e = enrich.enrich_places(store, store.get_search(s["id"]), [p])[0]
    assert e["score"]["fit"] == "fits" and e["score"]["fit_label"] == "Fits, but check"
    out = text(call(server(store), "get_place", place_id=p["id"]))
    assert "Fit: Fits, but check" in out and "Fit: Yes" not in out
    cmp_ = text(call(server(store), "compare_places", place_ids=[p["id"], store.add_place(title="B", address="2 A St", price=900)[0]["id"]]))
    assert "Fits, but check" in cmp_.split("Fit:")[1].split("\n")[0]


@pytest.mark.parametrize("mins,mode,name", [(44, "transit", "Hospital"), (46, "walk", "Campus"), (43, "bike", "Work")])
def test_small_commute_overage_is_noted_in_compare(store, mins, mode, name):
    s = store.add_search("C", "rent")
    a = store.add_anchor(name, "x", 40.0, -88.0)
    store.add_criterion(s["id"], "price", weight=50, dealbreaker=False, target={"max": 1500})
    store.add_criterion(s["id"], "commute", weight=10, dealbreaker=False, target={"mode": mode, "minutes": 40})
    p1, _ = store.add_place(title="Far", address="1 A St", price=1000, beds=1)
    p2, _ = store.add_place(title="Near", address="2 A St", price=1000, beds=1)
    store.set_commute(p1["id"], a["id"], mode, mins, "you")
    store.set_commute(p2["id"], a["id"], mode, 20, "you")
    out = text(call(server(store), "compare_places", place_ids=[p1["id"], p2["id"]]))
    fit_line = out.split("Fit: ")[1].split("\n")[0]
    assert f"{mins} min {mode}, over your 40" in fit_line and fit_line.rstrip().endswith("| #2 Yes")


# ---- 6. one note per line
def test_notes_one_per_line_in_add_and_get(store):
    store.add_search("C", "rent")
    srv = server(store)
    t = "2BR apt at 12 Oak St, $1,500/mo. Water/sewer $55 plus electric. Cleaning fee $200 per stay. Parking garage $90 optional."
    for out in (text(call(srv, "add_place", title="A", address="12 Oak St", listing_text=t)), text(call(srv, "get_place", place_id=1))):
        lines = [ln for ln in out.split("\n") if ln.startswith(("A garage is available", "The listing mentions a $200", "The listing also says"))]
        assert len(lines) >= 3 and len(set(lines)) == len(lines)
