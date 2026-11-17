"""Cycle 29 G5 item 2: a place whose only flag is "hidden characters removed" shows its cost as listed, not checked, and is never the
lowest true monthly cost."""
from __future__ import annotations

import pytest
from mcp_util import call, server, text

from prophelper import compare, enrich, redflags


def _setup(store, hidden_text):
    s = store.add_search("R", "rent", budget_max=3000)
    store.add_criterion(s["id"], "price", weight=30, dealbreaker=True, target={"max": 3000})
    p, _ = store.add_place(title="Hid", address="1 A St", price=1400, utilities_estimate=50, deposit=500, listing_text=hidden_text)
    q, _ = store.add_place(title="Fine", address="2 A St", price=1600, utilities_estimate=50, deposit=500)
    return s, p, q


TEXTS = ["Nice 2 bed.\u200b Quiet street.", "Nice 2 bed.\u200b Laundry in unit.\u200b Pets ok.", "Nice 2 bed\u2060. Pets ok.\ufeff Close to the train."]


@pytest.mark.parametrize("listing", TEXTS)
def test_hidden_only_place_is_as_listed_and_never_lowest(store, client, listing):
    s, p, q = _setup(store, listing)
    es = {r["id"]: r for r in enrich.enrich_places(store, s)}
    e = es[p["id"]]
    assert e["flags"] and all(redflags.is_hidden_note(f) for f in e["flags"]), e["flags"]
    assert compare.as_listed(e) and not compare.as_listed(es[q["id"]])
    assert compare.lowest_cost(list(es.values()))["winners"][0]["id"] == q["id"]
    html = client.get(f"/places/{p['id']}").text
    cost = html.split('id="cost"')[1].split("</section>")[0]
    assert "What the listing says it costs" in cost and "true cost" not in cost.lower() and "all in" not in cost.lower()
    srv = server(store)
    lp = text(call(srv, "list_places"))
    assert "as listed, not checked" in next(l for l in lp.split("\n") if l.startswith(f"#{p['id']}"))
    assert "true cost" in next(l for l in lp.split("\n") if l.startswith(f"#{q['id']}"))
    cmp_text = text(call(srv, "compare_places", place_ids=[p["id"], q["id"]]))
    assert f"Lowest true monthly cost: #{q['id']}" in cmp_text and f"#{p['id']} at" not in cmp_text.split("Lowest true monthly cost")[1].split("\n")[0]
    assert "$1,450 as listed, not checked" in cmp_text
    page = client.get(f"/compare?ids={p['id']},{q['id']}").text
    assert "as listed, not checked" in page


def test_hidden_only_place_alone_is_not_called_lowest(store):
    s, p, q = _setup(store, TEXTS[0])
    es = enrich.enrich_places(store, s)
    r = compare.lowest_cost([e for e in es if e["id"] == p["id"]])
    assert r["winners"] == []


def test_unknown_row_does_not_say_check_first_for_hidden_only(store):
    s, p, q = _setup(store, TEXTS[0])
    es = {r["id"]: r for r in enrich.enrich_places(store, s)}
    line = compare.nothing_unknown_guard(es[p["id"]], "Nothing unknown")
    assert "hidden characters" in line and "check first" not in line
