"""Cycle 24 G5 item 7: other monthly fees count on buy places; a fee that covers the internet clears "missing: internet"."""
import pytest

from mcp_util import call, server, text
from prophelper import enrich


def _total(store, pid):
    return next(p for p in enrich.enrich_places(store, store.get_search(1)) if p["id"] == pid)["cost_total"]


@pytest.mark.parametrize("fee", [75, 40, 120.5])
def test_buy_other_monthly_fees_counted(store, fee):
    srv = server(store)
    call(srv, "create_search", name="B", mode="buy", budget_max=500000)
    call(srv, "add_place", title="Condo", address="1 A St", price=340000, beds=2, property_tax=4000, insurance=1200, hoa=475)
    before = _total(store, 1)
    out = text(call(srv, "update_place", place_id=1, other_monthly_fees=fee))
    after = _total(store, 1)
    assert round(after - before, 2) == round(fee, 2)
    assert "other monthly fees" in out and f"{after:,.0f}" in out


def test_buy_without_fees_unchanged(store):
    srv = server(store)
    call(srv, "create_search", name="B", mode="buy", budget_max=500000)
    call(srv, "add_place", title="Condo", address="1 A St", price=340000, beds=2, property_tax=4000, insurance=1200, hoa=475)
    base = _total(store, 1)
    call(srv, "update_place", place_id=1, other_monthly_fees=0)
    assert _total(store, 1) == base


@pytest.mark.parametrize("covers", ["internet", "Internet (Xfinity)", "the internet and cable"])
def test_fee_that_covers_internet_clears_missing(store, covers):
    srv = server(store)
    call(srv, "create_search", name="R", mode="rent", budget_max=4000)
    call(srv, "add_place", title="Flat", address="1 A St", price=3000, beds=2, utilities_estimate=None,
         tenant_pays="internet", listing_text="2 bed. Tenant pays internet. Xfinity available.")
    first = text(call(srv, "get_place", place_id=1))
    assert "missing" in first and "internet" in first.split("True monthly cost")[1].split("\n")[0]
    out = text(call(srv, "update_place", place_id=1, other_monthly_fees=60, other_monthly_fees_covers=covers))
    cost = next(line for line in out.splitlines() if line.startswith("True monthly cost"))
    assert "internet" not in cost and "$3,060" in cost


def test_fee_without_covers_keeps_internet_missing(store):
    srv = server(store)
    call(srv, "create_search", name="R", mode="rent", budget_max=4000)
    call(srv, "add_place", title="Flat", address="1 A St", price=3000, beds=2, tenant_pays="internet",
         listing_text="2 bed. Tenant pays internet. Xfinity available.")
    out = text(call(srv, "update_place", place_id=1, other_monthly_fees=60))
    cost = next(line for line in out.splitlines() if line.startswith("True monthly cost"))
    assert "internet" in cost


def test_covers_without_fee_amount_changes_nothing(store):
    srv = server(store)
    call(srv, "create_search", name="R", mode="rent", budget_max=4000)
    call(srv, "add_place", title="Flat", address="1 A St", price=3000, beds=2, tenant_pays="internet",
         listing_text="2 bed. Tenant pays internet. Xfinity available.")
    out = text(call(srv, "update_place", place_id=1, other_monthly_fees_covers="internet"))
    assert "no other monthly fee amount yet" in out
    assert "internet" in next(line for line in out.splitlines() if line.startswith("True monthly cost"))
