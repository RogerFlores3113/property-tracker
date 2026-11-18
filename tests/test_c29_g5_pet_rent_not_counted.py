"""Cycle 29 G5 item 7: a pet charge left out of the cost because the search has no pets says so on the place page and in Claude's get_place."""
from __future__ import annotations

import os
import re

import pytest
from mcp_util import call, server, text

from prophelper import compare, enrich
from prophelper.parsers import parse_listing

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "panel")


def _place(store, s, listing, **extra):
    f = parse_listing(listing)
    f["reader_notes"] = f.pop("found_in_listing", "")
    f.update(extra)
    p, _ = store.add_place(search_id=s["id"], listing_text=listing, **f)
    return p


def _page(client, p):
    return re.sub(r"\s+", " ", client.get(f"/places/{p['id']}").text)


def test_reviewer_l11(store, client):
    cp = os.path.join(FIX, "r28-roommates-l11.txt")
    t = open(cp, encoding="utf-8").read()
    s = store.add_search("R", "rent", budget_max=4000)
    p = _place(store, s, t)
    html = _page(client, p)
    assert 'id="pet-not-counted"' in html
    assert "Pet rent $35 a month is in the listing but not counted, because this search has no pets" in html
    got = text(call(server(store), "get_place", place_id=p["id"]))
    assert "Pet rent $35 a month is in the listing but not counted, because this search has no pets" in got


@pytest.mark.parametrize("listing,expect", [
    ("2 bed, $1,500/mo. 12 Oak St 61820. Cats welcome, $25 monthly pet rent.", "Pet rent $25 a month is in the listing"),
    ("2 bed, $1,500/mo. 12 Oak St 61820. Dogs ok. Pet fee $300 one time.", "A pet fee of $300 is in the listing"),
    ("2 bed, $1,500/mo. 12 Oak St 61820. Pets ok: $40/mo pet rent and $250 pet deposit.", "Pet rent $40 a month and a pet deposit of $250 are in the listing"),
])
def test_other_wordings(store, client, listing, expect):
    s = store.add_search("R", "rent", budget_max=4000)
    p = _place(store, s, listing)
    assert expect in _page(client, p)
    assert "this search has no pets" in text(call(server(store), "get_place", place_id=p["id"]))


def test_search_with_a_pet_says_nothing_of_the_kind(store, client):
    s = store.add_search("R", "rent", budget_max=4000, pet_kind="dog", pet_count=1)
    p = _place(store, s, "2 bed, $1,500/mo. 12 Oak St 61820. Dogs ok, $35 monthly pet rent.")
    assert 'id="pet-not-counted"' not in _page(client, p)
    assert "this search has no pets" not in text(call(server(store), "get_place", place_id=p["id"]))
    e = next(r for r in enrich.enrich_places(store, s) if r["id"] == p["id"])
    assert compare.pet_charges_not_counted(e) == ""


def test_no_pet_charge_says_nothing(store, client):
    s = store.add_search("R", "rent", budget_max=4000)
    p = _place(store, s, "2 bed, $1,500/mo. 12 Oak St 61820. No pets.")
    assert 'id="pet-not-counted"' not in _page(client, p)
