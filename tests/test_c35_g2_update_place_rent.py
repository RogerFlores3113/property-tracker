"""Cycle 35 G2: update_place with a price more than about 30 percent from the saved rent always gives a Rent check, also when the listing text holds the new figure
as a decoy ("1550 obo"). The check never quotes a figure the reader misread."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp_util import call, server, text  # noqa: E402

P = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel") + "/"


def fixture(name):
    return open(P + name, encoding="utf-8").read()


def setup(store, mode="rent"):
    store.add_search("T", mode)
    return server(store)


def add(srv, **kw):
    return text(call(srv, "add_place", **kw))


def upd(srv, **kw):
    return text(call(srv, "update_place", place_id=1, **kw))


@pytest.mark.parametrize("new", [1550, 1550.0, "1550", "1 550", "$1,550", 1600, 1700])
def test_roommates_l3_a_big_rent_change_gets_a_rent_check(store, new):
    srv = setup(store)
    add(srv, listing_text=fixture("r34-roommates-l3.txt"))
    assert store.get_place(1)["price"] == 3275
    out = upd(srv, price=new)
    assert "Rent check:" in out
    assert "$3,275" in out.split("Rent check:")[1]


def test_decoy_in_a_listing_that_reads_the_decoy_still_gets_the_change_check(store):
    """The listing text's own rent is read as the same figure the caller sends, so the listing line stays quiet; the 30 percent line must not."""
    srv = setup(store)
    add(srv, title="Pilsen", address="1821 W 18th St", price=3275, listing_text="Pilsen 3 bed 2 bath | 1550 obo\n1821 W 18th St Chicago IL")
    assert store.get_place(1)["price"] == 3275
    out = upd(srv, price=1550)
    assert "Rent check: the rent changed from $3,275 to $1,550 a month, a change of more than 30 percent" in out
    assert "The old rent is on the timeline." in out
    assert "obo" not in out.split("Rent check:")[1].split("\n")[0]


@pytest.mark.parametrize("old,new", [(2000, 1300), (2000, 2700), (1500, 750), (3000, 3999)])
def test_change_over_30_percent_without_listing_text(store, old, new):
    srv = setup(store)
    add(srv, title="Plain", address="5 Oak St", price=old)
    out = upd(srv, price=new)
    assert "Rent check: the rent changed from" in out


@pytest.mark.parametrize("old,new", [(2000, 2050), (2000, 1500), (2000, 2500), (3275, 3200)])
def test_negatives_small_changes_say_nothing(store, old, new):
    srv = setup(store)
    add(srv, title="Plain", address="5 Oak St", price=old)
    out = upd(srv, price=new)
    assert "Rent check" not in out


def test_negative_buy_place(store):
    srv = setup(store, "buy")
    add(srv, title="Condo", address="5 Oak St", price=250000)
    out = upd(srv, price=400000)
    assert "Rent check" not in out


def test_negative_other_field_only(store):
    srv = setup(store)
    add(srv, title="Plain", address="5 Oak St", price=2000)
    assert "Rent check" not in upd(srv, deposit=500)


def test_listing_line_is_not_doubled_by_the_change_line(store):
    srv = setup(store)
    add(srv, listing_text="Sunset Row 3BR\n12 Elm St, Champaign, IL 61820\nRent $2,310/mo. 3 bed 2 bath.")
    out = upd(srv, price=1200)
    assert out.count("Rent check:") == 1
    assert "the listing text saved on this place gives a rent of $2,310" in out


def test_nontech_l2_listing_gives_the_whole_rent_in_the_listing_check(store):
    srv = setup(store)
    add(srv, listing_text=fixture("r34-nontech-l2.txt"))
    assert store.get_place(1)["price"] == 1550
    out = upd(srv, price=2400)
    assert "gives a rent of $1,550 a month" in out
    assert "$550" not in out
