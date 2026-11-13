"""Cycle 8, G3: cost line names the same unknowns as compare.cost_unknowns, no nested brackets, lowest cost names what the
winner leaves out, cash at move-in says the deposit is blank, CSV rows sorted by fit state."""
from __future__ import annotations

import csv
import io

from conftest import local_client
from mcp_util import call, server, text
from prophelper import compare, enrich, share


def _es(store, s, *places):
    return enrich.enrich_places(store, s, list(places))


def test_cost_line_names_the_same_unknowns_as_compare(store):
    s = store.add_search("R", "rent")
    p, _ = store.add_place(title="Oak Row", address="1 A St", price=1500, utilities_included="heat, water", deposit=500)
    e = _es(store, s, p)[0]
    assert "electric" in " ".join(compare.cost_unknowns(e))
    out = text(call(server(store), "get_place", place_id=p["id"]))
    line = [l for l in out.split("\n") if l.startswith("True monthly cost")][0]
    assert "missing: " + ", ".join(compare.cost_unknowns(e)) in line
    assert "utilities estimate" not in line


def test_cost_line_tenant_pays_unpriced_utilities(store):
    s = store.add_search("R", "rent")
    p, _ = store.add_place(title="P", address="1 A St", price=1500, tenant_pays="electric, gas and internet", deposit=500)
    e = _es(store, s, p)[0]
    out = text(call(server(store), "get_place", place_id=p["id"]))
    line = [l for l in out.split("\n") if l.startswith("True monthly cost")][0]
    assert "missing: " + ", ".join(compare.cost_unknowns(e)) in line and "utilities estimate" not in line


def test_no_nested_brackets_in_compare_and_share(store):
    s = store.add_search("R", "rent")
    a, _ = store.add_place(title="A", address="1 A St", price=1500, tenant_pays="electric, gas and internet", deposit=500)
    b, _ = store.add_place(title="B", address="2 A St", price=1600, utilities_included="all", deposit=500)
    es = _es(store, s, a, b)
    cell = compare.build_rows(es)
    cost = [r for sec in cell for r in sec["rows"] if r["key"] == "cost"][0]["cells"][0]["text"]
    assert "utilities (" not in cost and "electric, gas and internet utilities not counted yet" in cost
    html = share.comparison_html(local_client(store).app.state.templates, es)
    assert "utilities (" not in html
    page = local_client(store).get(f"/compare?ids={a['id']}&ids={b['id']}").text
    assert "utilities (" not in page


def test_lowest_cost_names_what_the_winner_leaves_out(store):
    s = store.add_search("R", "rent")
    a, _ = store.add_place(title="Oak Row", address="1 A St", price=1500, utilities_included="heat, water", deposit=500)
    b, _ = store.add_place(title="Elm", address="2 A St", price=1600, utilities_included="heat", deposit=500)
    es = _es(store, s, a, b)
    first = compare.summary_lines(es, compare.build_rows(es))[0]
    assert first == "Oak Row has the lowest true monthly cost, but its electric, gas and internet aren't counted."
    out = text(call(server(store), "compare_places", place_ids=[a["id"], b["id"]]))
    low = [l for l in out.split("\n") if l.startswith("Lowest true")][0]
    assert "but its electric, gas and internet aren't counted" in low


def test_cash_at_move_in_says_the_security_deposit_is_blank(store):
    s = store.add_search("R", "rent")
    a, _ = store.add_place(title="Maple Row", address="1 A St", price=1500, utilities_included="all")
    b, _ = store.add_place(title="Filled", address="2 A St", price=1500, utilities_included="all", deposit=500)
    _es(store, s, a, b)
    out = text(call(server(store), "get_place", place_id=a["id"]))
    cash = [l for l in out.split("\n") if l.startswith("Cash needed on move-in day")][0]
    assert "security deposit not filled in" in cash
    out = text(call(server(store), "get_place", place_id=b["id"]))
    assert "security deposit not filled in" not in out


def test_csv_rows_sorted_by_fit_state_then_score(store):
    s = store.add_search("R", "rent")
    store.add_criterion(s["id"], "beds", weight=10, target={"min": 1})
    store.add_place(title="Scam 1", address="3 A St", price=900, beds=1, listing_text="Owner is abroad. Wire the deposit before a showing.")
    store.add_place(title="Fit Low", address="1 A St", price=1500, beds=1, utilities_included="all", deposit=500)
    store.add_place(title="Fit High", address="2 A St", price=1400, beds=2, utilities_included="all", deposit=500)
    body = local_client(store).get("/places.csv").text
    rows = list(csv.DictReader(io.StringIO(body)))
    titles = [r.get("Title") or r.get("Name") or list(r.values())[0] for r in rows]
    assert titles[-1] == "Scam 1" and set(titles) == {"Scam 1", "Fit Low", "Fit High"}


def test_nice_to_have_commute_note_shows_on_today_and_in_list_places(store):
    s = store.add_search("R", "rent")
    a = store.add_anchor("Campus", address="1 Main St", lat=40.0, lng=-88.0)
    store.add_criterion(s["id"], "commute", weight=50, dealbreaker=False, target={"anchor_id": a["id"], "mode": "bike", "minutes": 20})
    store.add_criterion(s["id"], "beds", weight=50, target={"min": 1})
    p, _ = store.add_place(title="Far", address="1 A St", price=1000, beds=1, lat=40.01, lng=-88.0, utilities_included="all", deposit=500)
    store.set_commute(p["id"], a["id"], "bike", 24, "you")
    note = "over your 20 min, cost 10 points"
    assert note in local_client(store).get("/today").text
    out = text(call(server(store), "list_places"))
    assert note in out
