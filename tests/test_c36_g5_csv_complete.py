"""Cycle 36 G5: the CSV export has a column saying whether the monthly cost is complete, so a sorted sheet never shows an incomplete cost as an exact one.
It agrees with the place page and Claude's get_place ("not complete"), is ignored on import, and is empty for a place that was not worked out."""
import csv
import io
import os

import pytest
from conftest import local_client
from mcp_util import call, server, text

from prophelper import csv_io, enrich

HERE = os.path.join(os.path.dirname(__file__), "fixtures", "panel")
HEAD = "Monthly cost complete"


def F(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as fh:
        return fh.read()


def _rows(store, places):
    s = store.add_search("S", budget_max=1400)
    ids = []
    for kw in places:
        p, _ = store.add_place(search_id=s["id"], **kw)
        ids.append(p["id"])
    es = enrich.enrich_places(store, store.get_search(s["id"]), [store.get_place(i) for i in ids])
    by = {e["id"]: e for e in es}
    rows = list(csv.DictReader(io.StringIO(csv_io.export_csv(es))))
    return {r["Title"]: r for r in rows}, by


FULL = dict(utilities_included="All utilities included", deposit=500, parking="street", parking_cost=0, pet_rent=0, other_monthly_fees=0, application_fee=40)


def test_complete_and_incomplete_places(store):
    rows, _ = _rows(store, [dict(title="Full", address="1 A St", price=1200, **FULL),
                            dict(title="Gap", address="2 A St", price=1200, tenant_pays="electric, gas", deposit=500, parking="street"),
                            dict(title="NoRent", address="3 A St")])
    assert rows["Full"][HEAD] == "yes"
    assert rows["Gap"][HEAD].startswith("no: ") and "electric" in rows["Gap"][HEAD] and "gas" in rows["Gap"][HEAD]
    assert rows["NoRent"][HEAD] == "no: no price yet"
    assert list(rows["Full"]).index(HEAD) == list(rows["Full"]).index("True monthly cost") + 1


def test_the_column_agrees_with_get_place(store):
    rows, by = _rows(store, [dict(title="Gap", address="2 A St", price=1200, tenant_pays="electric, gas", deposit=500, parking="street"),
                             dict(title="Full", address="1 A St", price=1200, **FULL)])
    srv = server(store)
    for e in by.values():
        out = text(call(srv, "get_place", place_id=e["id"]))
        complete = rows[e["title"]][HEAD] == "yes"
        assert ("not complete" not in out) == complete, (e["title"], rows[e["title"]][HEAD])


def test_uiuc_l2_billed_electric_is_not_a_complete_cost(store):
    rows, _ = _rows(store, [dict(title="Hartwell", address="1 B St", price=1500, listing_text=F("r35-uiuc-l2.txt"))])
    r = next(iter(rows.values()))
    assert r[HEAD].startswith("no"), r[HEAD]


def test_check_first_places_are_as_listed(store):
    rows, _ = _rows(store, [dict(title="Scam", address="9 A St", price=1000, listing_text="1 bed $1,000. Wire the deposit to hold it. Owner is abroad.", **FULL)])
    assert next(iter(rows.values()))[HEAD].startswith("no: as listed, not checked")


def test_empty_for_a_place_that_was_not_worked_out(store):
    s = store.add_search("S")
    p, _ = store.add_place(search_id=s["id"], title="Raw", address="1 A St", price=1200)
    r = next(csv.DictReader(io.StringIO(csv_io.export_csv([store.get_place(p["id"])]))))
    assert r[HEAD] == ""


def test_import_ignores_the_column_and_the_web_export_has_it(store):
    assert csv_io.is_computed_header(HEAD)
    s = store.add_search("S", budget_max=3000)
    store.add_place(search_id=s["id"], title="Full", address="1 A St", price=1200, **FULL)
    store.set_current_search(s["id"])
    body = local_client(store).get(f"/places.csv?search_id={s['id']}").text
    assert HEAD in body.splitlines()[0]
