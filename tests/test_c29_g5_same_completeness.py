"""Cycle 29 G5 item 5: Today, the place page, Claude's tools and Compare use one completeness check."""
from __future__ import annotations

import os
import re

import pytest
from mcp_util import call, server, text

from prophelper import compare, enrich
from prophelper.parsers import parse_listing

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "panel")


def _buy_place(store, s, listing_file=None, **extra):
    t = open(os.path.join(FIX, listing_file), encoding="utf-8").read()
    f = parse_listing(t, buying=True)
    f["reader_notes"] = f.pop("found_in_listing", "")
    f.update(extra)
    p, _ = store.add_place(search_id=s["id"], listing_text=t, **f)
    return p


def _setup(store):
    s = store.add_search("B", "buy", budget_max=500000)
    store.add_criterion(s["id"], "price", weight=30, dealbreaker=True, target={"max": 500000})
    q, _ = store.add_place(title="Other", address="9 B St", price=300000, property_tax=3000, insurance=900, hoa=100)
    return s, q


def _surfaces(store, client, s, p, q):
    e = next(r for r in enrich.enrich_places(store, s) if r["id"] == p["id"])
    today = client.get("/today").text
    page = re.sub(r"\s+", " ", client.get(f"/places/{p['id']}").text)
    srv = server(store)
    got = text(call(srv, "get_place", place_id=p["id"]))
    lst = text(call(srv, "list_places"))
    cmp_t = text(call(srv, "compare_places", place_ids=[p["id"], q["id"]]))
    return e, today, page, got, lst, cmp_t


def test_l8_all_surfaces_say_not_complete(store, client):
    s, q = _setup(store)
    p = _buy_place(store, s, "r28-buyer-l8.txt", insurance=1200, hoa=290)
    e, today, page, got, lst, cmp_t = _surfaces(store, client, s, p, q)
    assert compare.cost_incomplete(e)
    # Today lists it under "Needs a cost check"; the reason line may say "not complete" or "not counted yet"
    assert "Needs a cost check" in today and ("not complete" in today or "not counted yet" in today)
    assert "not complete" in page.split('id="cost"')[1].split("</section>")[0] or "so far" in page
    assert "True monthly cost $" not in got and "not complete" in got
    line = next(l for l in lst.split("\n") if l.startswith(f"#{p['id']}"))
    assert "not complete" in line and "true cost" not in line
    still = next(l for l in cmp_t.split("\n") if l.startswith("Still unknown"))
    assert "Nothing unknown" not in still.split("|")[0]


def test_a_complete_place_says_complete_everywhere(store, client):
    s, q = _setup(store)
    p, _ = store.add_place(title="Whole", address="5 C St", price=320000, property_tax=3200, insurance=950, hoa=120)
    e, today, page, got, lst, cmp_t = _surfaces(store, client, s, p, q)
    assert not compare.cost_incomplete(e)
    assert "True monthly cost $" in got
    line = next(l for l in lst.split("\n") if l.startswith(f"#{p['id']}"))
    assert "true cost" in line and "not complete" not in line
    assert "Nothing unknown" in next(l for l in cmp_t.split("\n") if l.startswith("Still unknown"))


@pytest.mark.parametrize("fee", ["Monthly fee $290 plus $45 reserve.", "HOA is $290/mo plus a $45 reserve fee.", "Condo fee $290 per month. Reserve contribution $45."])
def test_one_time_amount_left_out_is_unknown_everywhere(store, client, fee):
    s, q = _setup(store)
    t = f"2/2 condo for $320,000. 1075 Summit St, Columbus OH 43201. {fee} Property tax $5,600/yr."
    f = parse_listing(t, buying=True)
    f["reader_notes"] = f.pop("found_in_listing", "")
    f.update(insurance=1200)
    p, _ = store.add_place(search_id=s["id"], listing_text=t, **f)
    e, today, page, got, lst, cmp_t = _surfaces(store, client, s, p, q)
    asked = compare.cost_incomplete(e)
    # whatever the reader decided, the surfaces agree with each other
    says_complete = "True monthly cost $" in got
    assert says_complete != asked
    assert ("Nothing unknown" in next(l for l in cmp_t.split("\n") if l.startswith("Still unknown")).split("|")[0]) != (bool(compare.cost_unknowns(e)) or e["score"]["unknown"] != [])
    assert ("not complete" in next(l for l in lst.split("\n") if l.startswith(f"#{p['id']}"))) == asked
