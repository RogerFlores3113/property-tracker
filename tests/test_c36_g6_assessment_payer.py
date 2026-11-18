"""Cycle 36 G6 item 4 (buyer l54): a seller-paid assessment shows the payer as seller in get_place and Compare even when the Who pays field was left empty."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp_util import call, server, text  # noqa: E402

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel")


def fixture(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


def saved(store, listing, payer=None):
    store.add_search("T", "buy")
    srv = server(store)
    kw = {"special_assessment_payer": payer} if payer is not None else {}
    call(srv, "add_place", listing_text=listing, **kw)
    return srv


def blank_payer(store):
    with store._lock:
        store._conn.execute("UPDATE places SET special_assessment_payer='' WHERE id=1")
        store._conn.commit()


def test_l54_get_place_says_seller_even_with_an_empty_payer_field(store):
    srv = saved(store, fixture("r35-buyer-l54.txt"))
    blank_payer(store)
    assert store.get_place(1)["special_assessment_payer"] == ""
    out = text(call(srv, "get_place", place_id=1))
    assert "special assessment $4,500 (the seller pays it)" in out
    assert "who pays it is not filled in" not in out


@pytest.mark.parametrize("line", [
    "Special assessment of $4,500 paid by seller at closing.",
    "Seller pays the $4,500 special assessment.",
    "Special assessment: $4,500, to be paid by the seller at closing",
    "Seller to pay special assessment of $4,500 at closing; parking street",
    "Special assessment $4,500 (seller pays)",
    "The seller will pay a $4,500 special assessment.",
])
def test_seller_paid_wordings(store, line):
    srv = saved(store, "Flat $298,000\n33 Mohawk St #5, Columbus, OH 43206\n2 bed 1 bath. HOA $275/mo. " + line)
    blank_payer(store)
    out = text(call(srv, "get_place", place_id=1))
    assert "(the seller pays it)" in out
    from prophelper import compare, money
    place = {**store.get_place(1), "cost": {"mode": "buy"}}
    assert compare._assessment_cell(place)["text"] == "$4,500 (the seller pays it)"
    assert compare._assessment_cell(place)["value"] == 0.0


@pytest.mark.parametrize("line", [
    "Special assessment of $4,500, buyer pays at closing.",
    "Buyer to pay special assessment of $4,500 at closing.",
])
def test_buyer_paid_stays_buyer(store, line):
    srv = saved(store, "Flat $298,000\n33 Mohawk St #5, Columbus, OH 43206\n2 bed 1 bath. HOA $275/mo. " + line)
    blank_payer(store)
    out = text(call(srv, "get_place", place_id=1))
    assert "(the buyer pays it)" in out


def test_negative_payer_not_said_stays_unfilled(store):
    srv = saved(store, "Flat $298,000\n33 Mohawk St #5, Columbus, OH 43206\n2 bed 1 bath. HOA $275/mo. Special assessment $4,500.")
    out = text(call(srv, "get_place", place_id=1))
    assert "who pays it is not filled in" in out
