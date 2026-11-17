"""Cycle 34 G2: a correction pasted onto a saved place adds the pay-list items it names (roommates l12 then l13: internet), says so, and never removes one."""
import html
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from conftest import local_client  # noqa: E402
from mcp_util import call, server, text  # noqa: E402

P = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel") + "/"
ADDR = "800 W Jackson Blvd Chicago IL 60661"


def fixture(name):
    return open(P + name, encoding="utf-8").read()


def first(store, listing=None):
    store.add_search("T", "rent")
    srv = server(store)
    text(call(srv, "add_place", listing_text=listing or fixture("r33-roommates-l12.txt")))
    return srv


def pay(store):
    return store.get_place(1)["tenant_pays"]


def test_roommates_l12_then_l13_whole_listings(store):
    srv = first(store)
    assert pay(store) == "electric"
    out = text(call(srv, "add_place", listing_text=fixture("r33-roommates-l13.txt")))
    assert pay(store) == "electric, internet"
    assert "The paste names internet as a utility the tenant pays, so it was added to the pay list, which is now electric, internet." in out
    assert "Nothing was taken off the list." in out
    assert "values for tenant pays" not in out
    assert store.get_place(1)["price"] == 3295


@pytest.mark.parametrize("t,expect", [
    ("Correction: tenant pays electric and internet. 800 W Jackson Blvd Chicago IL 60661.", "electric, internet"),
    ("800 W Jackson Blvd Chicago IL 60661. Update: you pay internet and gas.", "electric, gas, internet"),
    ("UPDATE - RESIDENT PAYS ELECTRIC, INTERNET. 800 W Jackson Blvd Chicago IL 60661", "electric, internet"),
    ("800 W Jackson Blvd Chicago IL 60661\nCorrected: tenant pays electric; internet; trash.", "electric, trash, internet"),
    ("Now updated (800 W Jackson Blvd Chicago IL 60661): tenant pays electric, water and internet.", "electric, internet"),
    ("800 W Jackson Blvd Chicago IL 60661 | Correction | Tenant pays: electric / wifi", "electric, internet"),
])
def test_other_wordings_add_the_new_items(store, t, expect):
    srv = first(store)
    text(call(srv, "add_place", listing_text=t))
    assert pay(store) == expect  # "water" stays off: the place says water is included


def test_the_web_form_adds_them_and_says_so(store):
    first(store)
    client = local_client(store)
    r = client.post("/add/save", data={"listing_text": fixture("r33-roommates-l13.txt"), "address": store.get_place(1)["address"], "title": "Greektown 3BR 2BA", "tenant_pays": "electric, internet"}, follow_redirects=False)
    assert r.status_code == 303
    page = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", client.get(r.headers["location"]).text)).split())
    assert pay(store) == "electric, internet"
    assert "The paste names internet as a utility the tenant pays, so it was added to the pay list." in page


@pytest.mark.parametrize("t", [
    "800 W Jackson Blvd Chicago IL 60661. Tenant pays electric and internet.",              # a plain repeat, no correction wording: the old rule, only empty fields
    "800 W Jackson Blvd Chicago IL 60661. Correction: tenant pays gas.",                     # adds gas, never removes electric
])
def test_plain_repeat_changes_nothing_and_a_correction_never_removes(store, t):
    srv = first(store)
    text(call(srv, "add_place", listing_text=t))
    got = pay(store)
    assert "electric" in got.split(", ")
    if "Correction" not in t:
        assert got == "electric"


def test_an_item_the_place_says_is_included_is_not_added(store):
    srv = first(store)  # heat and water included
    out = text(call(srv, "add_place", listing_text="800 W Jackson Blvd Chicago IL 60661. Correction: tenant pays electric and water."))
    assert pay(store) == "electric"
    assert "added to the pay list" not in out


def test_a_new_place_is_not_affected(store):
    store.add_search("T", "rent")
    srv = server(store)
    out = text(call(srv, "add_place", listing_text="12 Elm St, Champaign, IL 61820. Rent $1,500. Correction: tenant pays electric and internet."))
    assert "added to the pay list" not in out
