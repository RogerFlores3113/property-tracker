"""Cycle 24 G5 item 5: a near miss says "at least" when a cost part is unknown."""
import pytest

from mcp_util import call, server, text
from prophelper import enrich, today


def _s(store, dealbreaker):
    s = store.add_search("U", "rent")
    store.add_criterion(s["id"], "price", weight=50, dealbreaker=dealbreaker, target={"max": 1600})
    return s


@pytest.mark.parametrize("dealbreaker", [True, False])
@pytest.mark.parametrize("tenant", ["gas", "gas, electric", "internet"])
def test_unknown_cost_part_says_at_least(store, dealbreaker, tenant):
    s = _s(store, dealbreaker)
    store.add_place(title="Over", address="1 A St", price=1618, beds=1, tenant_pays=tenant)
    rows = enrich.enrich_places(store, store.get_search(s["id"]))
    nm = today.near_misses(rows)
    assert nm and nm[0]["text"].startswith("at least $18 over")
    assert "at least $18 over" in text(call(server(store), "todays_list"))


@pytest.mark.parametrize("dealbreaker", [True, False])
def test_known_cost_stays_plain(store, dealbreaker):
    s = _s(store, dealbreaker)
    store.add_place(title="Over", address="1 A St", price=1618, beds=1, utilities_estimate=0)
    rows = enrich.enrich_places(store, store.get_search(s["id"]))
    nm = today.near_misses(rows)
    assert nm and nm[0]["text"].startswith("$18 over") and "at least" not in nm[0]["text"]
