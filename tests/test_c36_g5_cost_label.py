"""Cycle 36 G5, rule ll: Compare's deal-breakers row names a cost failure as a cost failure (never "over the commute limit"),
says the amount once, and a real commute failure beside it keeps its own commute words."""
import pytest
from mcp_util import call, server, text
from test_c6_g4_compare_rules import _add, _commute_setup, _full, _search

from prophelper import compare


def _line(out, head):
    return next(x for x in out.splitlines() if x.startswith(head + ":"))


def _cells(line):
    return [c.strip() for c in line.split(":", 1)[1].split(" | ")]


def _cost_setup(store, prices, budget=1400, commute=None):
    s = _search(store, budget_max=budget)
    store.add_criterion(s["id"], "price", weight=40, dealbreaker=True, target={"max": budget})
    ids = [_add(store, s, f"Unit{i}", price=p, **_full()) for i, p in enumerate(prices)]
    if commute:
        _commute_setup(store, s, dict(zip(ids, commute)), limit=20, dealbreaker=True)
    return s, ids


@pytest.mark.parametrize("prices,budget", [([1500, 1300], 1400), ([1450, 1380, 1900], 1400), ([2500, 2300], 2400), ([1700, 1200], 1600)])
def test_cost_failure_is_named_as_cost(store, prices, budget):
    s, ids = _cost_setup(store, prices, budget)
    out = text(call(server(store), "compare_places", place_ids=ids))
    cells = _cells(_line(out, "Deal-breakers"))
    for cell, p in zip(cells, prices):
        if p > budget:
            assert "over the cost limit" in cell, cell
            assert "commute" not in cell, cell
            assert cell.count(f"${p:,}") <= 1, cell  # the amount is said once
        else:
            assert "cost limit" not in cell and "commute" not in cell, cell


def test_cost_failure_beside_a_commute_failure_keeps_both_labels(store):
    s, ids = _cost_setup(store, [1500, 1300, 1300], 1400, commute=[10, 30, 10])
    out = text(call(server(store), "compare_places", place_ids=ids))
    a, b, c = _cells(_line(out, "Deal-breakers"))
    assert "over the cost limit" in a and "commute" not in a, a
    assert "over the commute limit" in b and "cost limit" not in b, b
    assert "cost limit" not in c and "commute" not in c, c


def test_commute_only_failure_unchanged(store):
    s, ids = _cost_setup(store, [1200, 1250], 1400, commute=[10, 30])
    out = text(call(server(store), "compare_places", place_ids=ids))
    a, b = _cells(_line(out, "Deal-breakers"))
    assert "commute" not in a and "cost limit" not in a
    assert "over the commute limit" in b and "30 min" in b


def test_page_commute_row_ignores_cost_failures(store):
    s, ids = _cost_setup(store, [1500, 1300], 1400)
    from prophelper import enrich
    es = enrich.enrich_places(store, s, [store.get_place(i) for i in ids])
    assert [compare.commute_over_texts(e) for e in es] == [[], []]
    assert compare.cost_over_texts(es[0]) and not compare.cost_over_texts(es[1])
