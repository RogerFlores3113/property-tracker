"""Cycle 33 G2: add_place on a place that is already saved names a newer rent in its reply and how to apply it (and repeats no stale note);
update_place with a price that differs from the listing text's rent gets the rent-mismatch line, and get_place keeps showing it."""
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


# ---------------------------------------------------------------- a newer rent pasted on a saved place
def test_roommates_l13_repeat_paste_names_the_new_rent_and_how_to_apply_it(store):
    srv = setup(store)
    add(srv, listing_text=fixture("r32-roommates-l12.txt"), address="800 W Jackson Blvd", title="Greektown 3BR", price=3640)
    out = add(srv, listing_text=fixture("r32-roommates-l13.txt"))
    assert "This paste gives a rent of $3,295 a month, but the rent saved on this place is $3,640." in out
    assert "If $3,295 is right, call update_place with price 3295." in out
    assert "values for price" not in out
    assert "not counted anywhere" not in out
    assert store.get_place(1)["price"] == 3640  # a repeat add never changes a filled value
    assert out.count("call update_place with price 3295") == 1


@pytest.mark.parametrize("t,new", [
    ("Greektown 3BR\n800 W Jackson Blvd Chicago IL 60661\nRent $3,295/mo. 3 bed 2 bath.", 3295),
    ("800 W Jackson Blvd Chicago IL 60661. Rent is now $3,295 per month, down from $3,640.", 3295),
    ("800 W Jackson Blvd Chicago IL 60661 | $3,295 | 3 bed | 2 bath | pets ok", 3295),
    ("CORRECTION: the 3BR at 800 W Jackson Blvd Chicago IL 60661 is $3,295 now, not $3,640.", 3295),
])
def test_repeat_paste_other_layouts(store, t, new):
    srv = setup(store)
    add(srv, address="800 W Jackson Blvd", title="Greektown 3BR", price=3640)
    out = add(srv, listing_text=t, address="800 W Jackson Blvd")
    assert f"This paste gives a rent of ${new:,} a month, but the rent saved on this place is $3,640." in out
    assert f"call update_place with price {new}" in out
    assert store.get_place(1)["price"] == 3640


@pytest.mark.parametrize("t", [
    "800 W Jackson Blvd Chicago IL 60661. Rent $3,640/mo. 3 bed 2 bath.",
    "800 W Jackson Blvd Chicago IL 60661. 3 bed 2 bath. Pets ok.",
])
def test_negatives_same_rent_or_no_rent_adds_no_rent_note(store, t):
    srv = setup(store)
    add(srv, address="800 W Jackson Blvd", title="Greektown 3BR", price=3640)
    out = add(srv, listing_text=t, address="800 W Jackson Blvd")
    assert "This paste gives a rent" not in out


def test_a_new_place_gets_no_repeat_note(store):
    srv = setup(store)
    out = add(srv, listing_text="Sunset Row 3BR\n12 Elm St, Champaign, IL 61820\nRent $2,310/mo. 3 bed 2 bath.")
    assert "This paste gives a rent" not in out


# ---------------------------------------------------------------- update_place against the listing text
TEXTS = [
    "Sunset Row 3BR\n12 Elm St, Champaign, IL 61820\nRent $2,310/mo. 3 bed 2 bath.",
    "Sunset Row 3BR\n12 Elm St, Champaign, IL 61820\n3 bed 2 bath. $2,310 per month.",
    "Sunset Row 3BR | 12 Elm St, Champaign, IL 61820 | $2,310/mo | 3 bed | 2 bath",
    "Sunset Row 3BR. 12 Elm St, Champaign, IL 61820. The rent is $2,310 a month. 3 bed 2 bath.",
    "Sunset Row 3BR\n12 Elm St, Champaign, IL 61820\nMonthly rent: $2,310\n3 bed 2 bath",
    "SUNSET ROW 3BR\n12 ELM ST, CHAMPAIGN, IL 61820\nRENT $2,310/MO. 3 BED 2 BATH.",
]


@pytest.mark.parametrize("t", TEXTS)
def test_update_price_that_differs_from_the_listing_gets_the_mismatch_line(store, t):
    srv = setup(store)
    add(srv, listing_text=t)
    out = text(call(srv, "update_place", place_id=1, price=2400))
    assert "Rent check: the listing text saved on this place gives a rent of $2,310 a month, but the rent saved on this place is $2,400, and the cost uses $2,400." in out
    got = text(call(srv, "get_place", place_id=1))
    assert "Rent check: the listing text saved on this place gives a rent of $2,310 a month" in got
    assert store.get_place(1)["price"] == 2400


def test_update_price_equal_to_the_listing_rent_says_nothing(store):
    srv = setup(store)
    add(srv, listing_text=TEXTS[0])
    out = text(call(srv, "update_place", place_id=1, price=2310))
    assert "Rent check" not in out


def test_update_price_on_a_place_without_listing_text_says_nothing(store):
    srv = setup(store)
    add(srv, title="Plain", address="5 Oak St", price=1500)
    out = text(call(srv, "update_place", place_id=1, price=1600))
    assert "Rent check" not in out


def test_update_price_on_a_buy_place_says_nothing(store):
    srv = setup(store, "buy")
    add(srv, listing_text="Condo for sale $248,900. 2 bed 2 bath. 5 Oak St, Gahanna OH 43230")
    out = text(call(srv, "update_place", place_id=1, price=250000))
    assert "Rent check" not in out


def test_update_other_field_does_not_add_the_rent_line_to_the_update_reply(store):
    srv = setup(store)
    add(srv, listing_text=TEXTS[0])
    call(srv, "update_place", place_id=1, price=2400)
    out = text(call(srv, "update_place", place_id=1, beds=3))
    assert "Rent check" not in out


def test_add_places_batch_repeat_names_the_new_rent(store):
    srv = setup(store)
    add(srv, address="800 W Jackson Blvd", title="Greektown 3BR", price=3640)
    out = text(call(srv, "add_places", places=[{"listing_text": "800 W Jackson Blvd Chicago IL 60661. Rent $3,295/mo. 3 bed 2 bath.", "address": "800 W Jackson Blvd"}]))
    assert "This paste gives a rent of $3,295 a month, but the rent saved on this place is $3,640." in out
    assert "values for price" not in out
