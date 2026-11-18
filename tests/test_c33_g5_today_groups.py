"""Cycle 33 G5: a place whose cost is not complete is in one Today group only ("Needs a cost check"), never also counted under Best fits."""
import pytest
from conftest import local_client
from mcp_util import call, server, text

from prophelper import today


def _buy(store, complete, partial, no_tax=0):
    s = store.add_search("C", "buy", budget_max=400000)
    store.add_criterion(s["id"], "price", weight=50, dealbreaker=False, target={"max": 400000})
    ids = {"complete": [], "partial": []}
    for i in range(complete + partial):
        kw = dict(title=f"Condo {i}", address=f"{i + 1} Oak St", price=300000 + i * 1000, beds=2, property_tax=3600, hoa=0, search_id=s["id"])
        if i < complete:
            kw["insurance"] = 1200
        elif i < complete + no_tax:
            kw.pop("property_tax")
        p, _ = store.add_place(**kw)
        ids["complete" if i < complete else "partial"].append(p["id"])
    store.set_current_search(s["id"])
    return s, ids


def _groups(store, s):
    d = today.build(store, store.get_search(s["id"]))
    all_fit = {p["id"] for p in d["fits"]}
    return d, all_fit, {c["place"]["id"] for c in d["cost_check"]}


@pytest.mark.parametrize("complete,partial", [(6, 4), (4, 1), (3, 3), (5, 2), (8, 6), (1, 1)])
def test_insurance_missing_places_are_only_under_needs_a_cost_check(store, complete, partial):
    s, ids = _buy(store, complete, partial)
    d, fit, checked = _groups(store, s)
    assert checked == set(ids["partial"])
    assert not fit & checked
    assert len(d["fits"]) == min(3, complete)
    assert d["more"]["fits"] == max(0, complete - 3)
    assert d["more_fits_note"] == ""
    assert all(p["id"] in ids["complete"] for p in d["fits"])
    # the page: the count in the section heading is the number of places in it, and no check place is listed under Best fits
    html = local_client(store).get("/today").text
    best = html.split("Best fits right now")[1].split("</section>")[0] if "Best fits right now" in html else ""
    check = html.split('id="cost-check-h"')[1].split("</section>")[0]
    assert f'<span class="count">{partial}</span>' in check
    for pid in ids["partial"]:
        assert f"/places/{pid}\"" in check
        assert f"/places/{pid}\"" not in best
    assert "not complete yet" not in best
    # Claude's list
    out = text(call(server(store), "todays_list")).split("New places the user has not looked at")[0]
    assert sum(1 for x in out.splitlines() if x.startswith("Needs a cost check")) == partial
    assert "of them" not in out
    for pid in ids["partial"]:
        line = next(x for x in out.splitlines() if x.startswith("Needs a cost check") and f"#{pid} " in x)
        assert "Insurance is not counted yet" in line
        assert not any(x.startswith("  - ") and f"#{pid} " in x for x in out.splitlines())


def test_a_place_with_insurance_filled_in_stays_a_best_fit(store):
    s, ids = _buy(store, 2, 0)
    d, fit, checked = _groups(store, s)
    assert fit == set(ids["complete"]) and not checked


def test_no_complete_place_means_no_best_fit_and_each_place_is_listed_once(store):
    s, ids = _buy(store, 0, 3)
    d, fit, checked = _groups(store, s)
    assert not d["fits"] and checked == set(ids["partial"])
    assert [u["place"]["id"] for u in d["unconfirmed"]] == []  # not listed a second time under "Nothing is confirmed yet"
    out = text(call(server(store), "todays_list")).split("New places the user has not looked at")[0]
    assert out.count("Condo 0") == 1 and out.count("Condo 1") == 1 and out.count("Condo 2") == 1


def test_tax_and_insurance_unknown_is_still_one_group(store):
    s, ids = _buy(store, 2, 3, no_tax=3)
    d, fit, checked = _groups(store, s)
    assert checked == set(ids["partial"]) and not fit & checked


def test_sample_data_never_counts_a_place_in_two_groups(sample_store):
    for s in sample_store.list_searches():
        d = today.build(sample_store, s)
        top = {p["id"] for p in d["fits"]}
        checked = {c["place"]["id"] for c in d["cost_check"]}
        unconf = {c["place"]["id"] for c in d["unconfirmed"]}
        assert not top & checked and not unconf & checked and not top & unconf, s["name"]
