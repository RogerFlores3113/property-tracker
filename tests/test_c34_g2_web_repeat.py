"""Cycle 34 G2: the web /add form, like MCP add_place, names a different rent when a repeat paste carries one and says how to apply it (roommates l14)."""
import html
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from conftest import local_client  # noqa: E402

P = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel") + "/"


def fixture(name):
    return open(P + name, encoding="utf-8").read()


def saved(store, price=3295, mode="rent"):
    s = store.add_search("T", mode)
    p, _ = store.add_place(search_id=s["id"], title="Jackson 3BR", address="800 W Jackson Blvd Chicago IL 60661", price=price)
    return s, p


def paste(client, store, s, listing):
    """Save what the form holds after the reader has read the paste (the preview step is its own request)."""
    from prophelper import parsers
    got = parsers.parse_listing(listing, "")
    data = {"search_id": str(s["id"]), "listing_text": listing, "address": "800 W Jackson Blvd Chicago IL 60661", "title": "Jackson 3BR"}
    if got.get("price") is not None:
        data["price"] = str(got["price"])
    r2 = client.post("/add/save", data=data, follow_redirects=False)
    assert r2.status_code == 303
    r3 = client.get(r2.headers["location"])  # the one-line notice rides in a cookie for this next page
    assert r3.status_code == 200
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", r3.text)).split())


def test_roommates_l14_whole_listing(store):
    s, p = saved(store)
    client = local_client(store)
    page = paste(client, store, s, fixture("r33-roommates-l14.txt"))
    assert "This paste gives a rent of $3,150 a month, but the rent saved on this place is $3,295, so it stays $3,295." in page
    assert "If $3,150 is right, change the rent on this page." in page
    assert "changed nothing else" in page
    assert store.get_place(p["id"])["price"] == 3295


@pytest.mark.parametrize("t,new", [
    ("800 W Jackson Blvd Chicago IL 60661 | 3BR 2BA | Rent: $3,150 per month, new price.", 3150),
    ("800 W Jackson Blvd Chicago IL 60661. 3 bed 2 bath. $3,150/mo.", 3150),
    ("800 W Jackson Blvd Chicago IL 60661\nMonthly rent: $3,150\n3 bed 2 bath", 3150),
    ("800 W Jackson Blvd Chicago IL 60661. The rent is $3,400 a month.", 3400),
    ("800 W JACKSON BLVD CHICAGO IL 60661. RENT $3,150 PER MONTH.", 3150),
    ("800 W Jackson Blvd Chicago IL 60661; 3 bed; 2 bath; rent $3,150.50/mo; pets ok", 3150.5),
])
def test_other_layouts_name_the_new_rent(store, t, new):
    s, p = saved(store)
    client = local_client(store)
    page = paste(client, store, s, t)
    shown = f"${new:,.2f}" if new != int(new) else f"${new:,.0f}"
    assert f"This paste gives a rent of {shown} a month, but the rent saved on this place is $3,295" in page
    assert f"If {shown} is right, change the rent on this page." in page
    assert store.get_place(p["id"])["price"] == 3295


@pytest.mark.parametrize("t", [
    "800 W Jackson Blvd Chicago IL 60661. Rent $3,295/mo. 3 bed 2 bath.",      # the same rent
    "800 W Jackson Blvd Chicago IL 60661. 3 bed 2 bath. Pets ok.",            # no rent in the paste
])
def test_negatives_same_rent_or_no_rent_adds_no_rent_line(store, t):
    s, _ = saved(store)
    page = paste(local_client(store), store, s, t)
    assert "This paste gives a rent" not in page
    assert "changed nothing else" in page


def test_a_new_place_gets_no_repeat_line(store):
    s = store.add_search("T", "rent")
    page = paste(local_client(store), store, s, "12 Elm St, Champaign, IL 61820\nRent $2,310/mo. 3 bed 2 bath.")
    assert "This paste gives a rent" not in page


def test_buying_search_gets_no_rent_line(store):
    s, _ = saved(store, price=410000, mode="buy")
    page = paste(local_client(store), store, s, "800 W Jackson Blvd Chicago IL 60661. Listed at $425,000. 3 bed 2 bath.")
    assert "This paste gives a rent" not in page
