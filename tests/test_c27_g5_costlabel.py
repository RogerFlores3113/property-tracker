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


def _rows_text(es, key):
    for sec in compare.build_rows(es):
        for r in sec["rows"]:
            if r["key"] == key:
                return [c["text"] for c in r["cells"]]
    return []


def test_compare_never_says_nothing_unknown_beside_a_deposit_not_known(store):
    s = store.add_search("R", "rent", budget_max=3000)
    a, _ = store.add_place(title="NoDeposit", address="1 A St", price=1300, utilities_estimate=50, tenant_pays="electric", parking="none", pet_rent=0, other_monthly_fees=0)
    b, _ = store.add_place(title="HasDeposit", address="2 A St", price=1400, utilities_estimate=50, deposit=1400, tenant_pays="electric", parking="none", pet_rent=0, other_monthly_fees=0)
    es = enrich.enrich_places(store, s, [a, b])
    assert compare.cash_unknown_parts(es[0]) == ["deposit"] and compare.cash_unknown_parts(es[1]) == []
    for key in ("missing", "unknown"):
        t = _rows_text(es, key)
        assert "deposit" in t[0].lower() and t[0] != "Nothing unknown", t
        assert "deposit" not in t[1].lower(), t
    assert compare.nothing_unknown_guard(es[0], "Nothing unknown") == "Unknown: deposit"
    assert compare.nothing_unknown_guard(es[1], "Nothing unknown") == "Nothing unknown"


def test_fit_line_names_the_unknown(store, client):
    s = store.add_search("R", "rent", budget_max=1000)
    store.add_criterion(s["id"], "price", weight=30, dealbreaker=True, target={"max": 1000})
    store.add_criterion(s["id"], "parking", label="Garage", weight=10, target={"want": "garage"})
    p, _ = store.add_place(title="Pricey", address="1 A St", price=2000, utilities_estimate=50)
    e = enrich.enrich_places(store, s, [p])[0]
    assert e["score"]["fit"] == "doesnt_fit" and e["score"]["unknown_count"] == 1
    basis = compare.score_unknown_basis(e)
    assert basis == "based on 1 unknown: Garage"
    assert basis in client.get(f"/places/{p['id']}").text
    assert basis in client.get("/board").text
    assert "based on" in compare._score_cell(e)["text"] and ": " in compare.unknown_basis(e)


def test_best_fit_marks_a_lowest_unit_rent(store, client):
    s = store.add_search("R", "rent", budget_max=2500)
    store.add_criterion(s["id"], "price", weight=30, dealbreaker=True, target={"max": 2500})
    p, _ = store.add_place(title="Flats", address="1 A St", price=1085, utilities_estimate=50, deposit=1085, tenant_pays="electric", parking="none", pet_rent=0, other_monthly_fees=0,
                           reader_notes='The listing says "starting at" $1,085, so that is the lowest unit price. Ask what the rent is for the unit you want.')
    q, _ = store.add_place(title="Plain", address="2 A St", price=1100, utilities_estimate=50, deposit=1100, tenant_pays="electric", parking="none", pet_rent=0, other_monthly_fees=0)
    d = today.build(store, s)
    got = {x["title"]: x for x in d["fits"]}
    if "Flats" in got:
        assert compare.lowest_unit(got["Flats"]) and not compare.lowest_unit(got["Plain"])
        html = client.get("/today").text
        assert "(lowest unit)" in html and html.count("(lowest unit)") == 1
        assert "lowest unit rent" in text(call(server(store), "todays_list"))
    else:
        raise AssertionError("expected Flats among the best fits: " + str([x["title"] for x in d["fits"]]))


def test_compare_cash_row_of_a_flagged_place_says_as_listed(store, client):
    s, p, q = _setup(store)
    es = enrich.enrich_places(store, s, [p, q])
    cells = _rows_text(es, "cash_up_front")
    assert cells and cells[0].endswith("as listed, not checked") and "as listed" not in cells[1], cells
    assert "as listed, not checked" in client.get(f"/compare?ids={p['id']},{q['id']}").text
    out = text(call(server(store), "compare_places", place_ids=[p["id"], q["id"]]))
    cash = next(l for l in out.split("\n") if l.startswith("Cash needed up front") or "Cash needed" in l)
    assert "as listed, not checked" in cash
    gp = text(call(server(store), "get_place", place_id=p["id"]))
    assert "(as listed, not checked). Not part of the monthly cost." in gp
