"""Cycle 36 G6 item 6 (buyer): update_place with an asking price more than about 30 percent from the saved price on a buying place gives a Price check, as rent does."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp_util import call, server, text  # noqa: E402

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel")


def fixture(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


def setup(store, mode="buy"):
    store.add_search("T", mode)
    return server(store)


def upd(srv, **kw):
    return text(call(srv, "update_place", place_id=1, **kw))


def test_reviewer_255000_to_450000(store):
    srv = setup(store)
    call(srv, "add_place", title="Condo", address="12 Oak St", price=255000)
    out = upd(srv, price=450000)
    assert "Price check: the asking price changed from $255,000 to $450,000, a change of more than 30 percent" in out
    assert "The old price is on the timeline." in out
    assert store.get_place(1)["price"] == 450000


@pytest.mark.parametrize("new", [450000, 450000.0, "450000", "450,000", "$450,000", "450 000", 400000, 500000, 120000])
def test_big_change_wordings(store, new):
    srv = setup(store)
    call(srv, "add_place", title="Condo", address="12 Oak St", price=255000)
    out = upd(srv, price=new)
    assert "Price check:" in out
    assert "$255,000" in out.split("Price check:")[1].split("\n")[0]


def test_decoy_in_listing_text_does_not_hide_it(store):
    srv = setup(store)
    call(srv, "add_place", title="Condo", address="12 Oak St", price=255000, listing_text="Condo 12 Oak St Columbus OH\nAsking $450,000 obo")
    out = upd(srv, price=450000)
    assert "Price check:" in out and "$255,000" in out


def test_whole_listing_l54(store):
    srv = setup(store)
    call(srv, "add_place", listing_text=fixture("r35-buyer-l54.txt"))
    assert store.get_place(1)["price"] == 298000
    out = upd(srv, price=450000)
    assert "Price check: the asking price changed from $298,000 to $450,000" in out
    out = upd(srv, price=100000)
    assert "Price check: the asking price changed from $450,000 to $100,000" in out


@pytest.mark.parametrize("new", [260000, 280000, 330000, 255000, "$250,000", 165000 + 90000 + 20000])
def test_small_change_has_no_price_check(store, new):
    srv = setup(store)
    call(srv, "add_place", title="Condo", address="12 Oak St", price=255000)
    out = upd(srv, price=new)
    assert "Price check:" not in out


def test_rent_place_keeps_its_rent_check_not_a_price_check(store):
    srv = setup(store, "rent")
    call(srv, "add_place", title="Apt", address="12 Oak St", price=1500)
    out = upd(srv, price=3000)
    assert "Rent check:" in out and "Price check:" not in out


def test_other_field_update_has_no_price_check(store):
    srv = setup(store)
    call(srv, "add_place", title="Condo", address="12 Oak St", price=255000)
    out = upd(srv, hoa=300)
    assert "Price check:" not in out
