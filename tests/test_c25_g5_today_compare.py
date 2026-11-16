"""Cycle 25 G5 items 4 and 5: low rent is never a fit, scam headline wording, near miss unknown utility, Compare skips Passed."""
import pytest

from mcp_util import call, server, text
from prophelper import compare, enrich, today


def _rows(store, sid):
    return enrich.enrich_places(store, store.get_search(sid))


@pytest.mark.parametrize("rent,beds,listing", [
    (200, 3, "Rent: $3,200 | Garage parking optional, $200/mo"),
    (200, 2, "Garage parking optional, $200/mo. Rent: $3,200"),
    (150, 1, ""), (350, 3, ""),
])
def test_low_rent_is_check_first_not_fit(store, rent, beds, listing):
    s = store.add_search("R", "rent")
    store.add_criterion(s["id"], "price", weight=50, dealbreaker=True, target={"max": 3500})
    store.add_place(title="Low", address="1 A St", price=rent, beds=beds, listing_text=listing)
    row = _rows(store, s["id"])[0]
    assert row["score"]["rent_check"] and row["score"]["fit_label"] != "Fits" and row["score_total"] <= 49
    assert not today.is_best_fit(row) and today.low_rent(row)
    t = text(call(server(store), "list_places"))
    assert "Check the rent first" in t and "Fit: Fits" not in t and "true cost" not in t
    assert "Low" not in text(call(server(store), "todays_list")).split("Best fits right now:")[1].split("Tours")[0].replace("none yet.", "")


def test_normal_cheap_rent_is_still_fine(store):
    s = store.add_search("R", "rent")
    store.add_criterion(s["id"], "price", weight=50, dealbreaker=True, target={"max": 1000})
    store.add_place(title="Room", address="1 A St", price=450, beds=1, utilities_estimate=60)
    assert not _rows(store, s["id"])[0]["score"]["rent_check"]


def test_scam_place_headline_is_not_true_cost(store):
    s = store.add_search("R", "rent")
    store.add_place(title="Scam", address="1 A St", price=900, beds=1, listing_text="Owner is overseas, wire the deposit, keys mailed to you.", utilities_estimate=0)
    t = text(call(server(store), "list_places"))
    assert "true cost" not in t and "as listed, not checked" in t


@pytest.mark.parametrize("tenant", ["gas", "gas, electric"])
def test_near_miss_names_the_unknown_utility(store, tenant):
    s = store.add_search("U", "rent")
    store.add_criterion(s["id"], "price", weight=50, dealbreaker=True, target={"max": 1600})
    store.add_place(title="Over", address="1 A St", price=1618, beds=1, tenant_pays=tenant)
    nm = today.near_misses(_rows(store, s["id"]))
    assert nm and nm[0]["text"].startswith("at least $18 over") and "still unknown" in nm[0]["text"]
    assert tenant.split(",")[0] in nm[0]["text"]


def test_compare_skips_passed_for_lowest_cost(store):
    s = store.add_search("C", "rent")
    store.add_criterion(s["id"], "price", weight=50, dealbreaker=False, target={"max": 2000})
    a = store.add_place(title="Cheap", address="1 A St", price=900, beds=1, utilities_estimate=0)
    b = store.add_place(title="Next", address="2 B St", price=1100, beds=1, utilities_estimate=0)
    a = a[0] if isinstance(a, tuple) else a
    rows = _rows(store, s["id"])
    for r in rows:
        if r["title"] == "Cheap":
            r["stage"] = "Passed"
    lines = compare.summary_lines(rows, [])
    assert any("Next has the lowest true monthly cost" in l for l in lines)
    assert not any("Cheap is cheaper" in l or "Cheap is cheapest" in l for l in lines)


def test_compare_says_what_fails(store):
    s = store.add_search("C", "rent")
    store.add_criterion(s["id"], "laundry", weight=50, dealbreaker=True, target={"min": "in_unit"})
    store.add_place(title="Cedar", address="1 A St", price=900, beds=1, laundry="none", utilities_estimate=0)
    store.add_place(title="Oak", address="2 B St", price=1100, beds=1, laundry="in_unit", utilities_estimate=0)
    lines = compare.summary_lines(_rows(store, s["id"]), [])
    cedar = [l for l in lines if l.startswith("Cedar is cheap")]
    assert cedar and "it doesn't fit what you asked for" not in cedar[0] and "must-have" in cedar[0]
