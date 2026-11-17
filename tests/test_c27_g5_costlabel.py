"""Cycle 27, G5: one cost label for a check-first place on every surface; Today caps Check first and says the advice once."""
from __future__ import annotations

import re

from mcp_util import call, server, text
from prophelper import compare, enrich, today

SCAM = "Owner is abroad. Wire the deposit before a showing. Keys by mail."


def _setup(store):
    s = store.add_search("R", "rent", budget_max=3000)
    store.add_criterion(s["id"], "price", weight=30, dealbreaker=True, target={"max": 3000})
    p, _ = store.add_place(title="Flagged", address="1 A St", price=2000, utilities_estimate=50, listing_text=SCAM)
    q, _ = store.add_place(title="Fine", address="2 A St", price=1500, utilities_estimate=50, deposit=500)
    return s, p, q


def _no_true_cost(t: str):
    low = t.lower()
    assert "true cost" not in low and "true monthly" not in low and "really costs" not in low, t


def test_flagged_place_never_says_true_cost_anywhere(store, client):
    s, p, q = _setup(store)
    e = next(r for r in enrich.enrich_places(store, s) if r["id"] == p["id"])
    assert compare.as_listed(e)
    html = client.get(f"/places/{p['id']}").text
    _no_true_cost(html.split('id="cost"')[1].split("</section>")[0])
    assert "What the listing says it costs" in html and "as listed, not checked" in html
    assert "all in" not in html.split('id="cost"')[1].split("</section>")[0].lower()
    head = html.split("<h1>")[1].split("</p>")[0]
    _no_true_cost(head)
    board = client.get("/board").text
    card = board.split(f'data-id="{p["id"]}"')[1].split("</article>")[0]
    assert "as listed, not checked" in card
    srv = server(store)
    lp = text(call(srv, "list_places"))
    line = next(l for l in lp.split("\n") if l.startswith(f"#{p['id']}"))
    assert "as listed, not checked" in line and "true cost" not in line and "not complete" not in line
    gp = text(call(srv, "get_place", place_id=p["id"]))
    assert "as listed, not checked" in gp
    _no_true_cost(re.sub(r"\n.*?(listing text|notes).*", "", gp.split("<")[0]))
    cmp_text = text(call(srv, "compare_places", place_ids=[p["id"], q["id"]]))
    assert "as listed, not checked" in cmp_text
    page = client.get(f"/compare?ids={p['id']},{q['id']}").text
    assert "as listed, not checked" in page
    # the fine place keeps the plain labels
    fl = next(l for l in lp.split("\n") if l.startswith(f"#{q['id']}"))
    assert "true cost" in fl
    assert "What it really costs" in client.get(f"/places/{q['id']}").text


def test_incomplete_flagged_place_still_says_as_listed(store, client):
    s = store.add_search("R", "rent", budget_max=3000)
    p, _ = store.add_place(title="Flagged2", address="1 A St", price=2195, listing_text=SCAM + " Tenant pays internet.")
    html = client.get(f"/places/{p['id']}").text
    sec = html.split('id="cost"')[1].split("</section>")[0]
    assert "What it really costs" not in html
    assert "as listed, not checked" in sec
    assert "$2,195/mo, " not in html.split("<h1>")[1].split("</p>")[0] or "as listed" in html.split("<h1>")[1].split("</p>")[0]


def test_today_check_first_is_capped_and_says_advice_once(store, client):
    s = store.add_search("R", "rent", budget_max=3000)
    for i in range(9):
        store.add_place(title=f"Scam {i}", address=f"{i} A St", price=900 + i, utilities_estimate=50, listing_text=SCAM)
    data = today.build(store, s)
    assert len(data["check_first"]) == today.CHECK_FIRST_SHOWN and data["more"]["check_first"] == 9 - today.CHECK_FIRST_SHOWN
    html = client.get("/today").text
    sec = html.split('id="check-first-h"')[1].split("</section>")[0]
    assert sec.count("before you pay anything") == 1
    assert "and 4 more" in sec
    assert sec.count("Scam ") == 5
    out = text(call(server(store), "todays_list"))
    assert out.count("before you pay anything") == 1 and "and 4 more to check first" in out
    assert out.count("Check first: #") == 5


def test_cost_incomplete_reads_all_in_and_uncounted():
    assert compare.cost_incomplete({"cost": {"all_in": False}}) and compare.cost_incomplete({"cost": {"uncounted": ["x"]}})
    assert not compare.cost_incomplete({"cost": {"all_in": True}})
