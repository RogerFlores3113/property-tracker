"""Cycle 34, G4: "Total move-in about $2,600" is a one-time total: a note says so, and it is never in the monthly "not counted yet" line (uiuc l6)."""
from __future__ import annotations

import os

import pytest

from prophelper import compare, enrich, money, parsers as P, today

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel")


def fixture(name: str) -> str:
    with open(os.path.join(FIX, name), encoding="utf-8") as fh:
        return fh.read()


def read(text: str) -> dict:
    return P.parse_listing(text, "")


def notes(r: dict) -> str:
    return r.get("found_in_listing") or ""


HEAD = "2 bed 1 bath. Rent $1,310. Deposit $1,310. "


@pytest.mark.parametrize("line", [
    "Total move-in about $2,600.",
    "Total move in: $2,600",
    "Total due at move-in: ~$2,600",
    "TOTAL MOVE-IN ABOUT $2,600",
    "Move-in about $2,600 total",
    "Move-in cost roughly $2,600.",
    "Total move-in cost: approximately $2,600; pets ok",
    "Pets ok\nTotal move-in about $2,600\nParking: street",
    "Rent info | Total move-in about $2,600 | Street parking",
])
def test_move_in_total_wordings(line):
    r = read(HEAD + line)
    n = notes(r)
    assert r["price"] == 1310 and r["deposit"] == 1310
    assert "$2,600" in n and "in total to move in" in n and "not in the monthly cost" in n, n
    assert "not counted anywhere" not in n and "Check what it is for" not in n, n
    assert not r.get("move_in_fees")


@pytest.mark.parametrize("line", [
    "Move-in: $1,310 first month + $1,310 deposit",
    "Move-in costs: first month, deposit $1,310 and $150 key fee",
])
def test_move_in_item_lists_are_not_totals(line):
    r = read(HEAD + line)
    assert "in total to move in" not in notes(r)


def rows_for(store, text):
    s = store.add_search("C", "rent")
    store.add_criterion(s["id"], "price", weight=50, dealbreaker=False, target={"max": 4000})
    v = read(text)
    keep = {k: v[k] for k in ("tenant_pays", "utilities_estimate", "utilities_included", "beds", "baths", "price", "deposit", "other_monthly_fees") if k in v}
    store.add_place(title="P", address="1 A St", search_id=s["id"], parking_cost=0, pets="none", listing_text=text, reader_notes=v.get("found_in_listing"), **keep)
    return enrich.enrich_places(store, store.get_search(s["id"]))


@pytest.mark.parametrize("line", ["Total move-in about $2,600.", "Move-in about $2,600 total", "Total due at move-in: ~$2,600"])
def test_never_in_the_monthly_missing_line(store, line):
    rows = rows_for(store, HEAD + "Tenant pays all utilities, typical bills $210. " + line)
    r = rows[0]
    c = r.get("cost") or {}
    assert "2,600" not in money.headline(c), money.headline(c)
    assert "2,600" not in compare.still_unknown_text(r)
    assert not any("2,600" in x["text"] for x in today.cost_check(rows))
    assert not any("listing notes" in u for u in (c.get("uncounted") or []))


def test_uiuc_l6_whole_listing(store):
    t = fixture("r33-uiuc-l6.txt")
    r = read(t)
    assert r["price"] == 1310 and r["utilities_estimate"] == 210 and r["tenant_pays"] == "electric, gas, water, sewer, trash"
    assert r["application_fee"] == 45 and r["laundry"] == "hookups" and r["beds"] == 1
    assert "in total to move in" in notes(r) and "$2,600" in notes(r) and "not counted anywhere" not in notes(r)
    rows = rows_for(store, t)
    assert "2,600" not in money.headline(rows[0].get("cost") or {})
    assert not any("2,600" in x["text"] for x in today.cost_check(rows))
