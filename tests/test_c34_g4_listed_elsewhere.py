"""Cycle 34, G4: "Listed at $1,450 elsewhere" gets a plain note (another listing's price), not "Check what it is for" (nontech l16)."""
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


HEAD = "2 bed 1 bath. "


@pytest.mark.parametrize("line,quote", [
    ("Listed at $1,450 elsewhere. Rent: $1,395/mo.", "Listed at $1,450 elsewhere"),
    ("Rent: $1,395/mo. Listed at $1,450 elsewhere.", "Listed at $1,450 elsewhere"),
    ("Rent: $1,395/mo\nSame unit on Zillow: $1,450", "Same unit on Zillow: $1,450"),
    ("Rent: $1,395/mo. Priced at $1,450 on other sites.", "Priced at $1,450 on other sites"),
    ("Rent: $1,395/mo. Elsewhere it is listed for $1,450.", "Elsewhere it is listed for $1,450"),
    ("RENT $1,395. LISTED AT $1,450 ELSEWHERE", "LISTED AT $1,450 ELSEWHERE"),
    ("Rent: $1,395/mo | Advertised at $1,450 on Craigslist | Pets ok", "Advertised at $1,450 on Craigslist"),
])
def test_elsewhere_price_is_a_plain_note(line, quote):
    r = read(HEAD + line)
    n = notes(r)
    assert r["price"] == 1395
    assert f'The listing also says "{quote}". It is the price the same place has on another listing, not a cost on top of the rent.' in n, n
    assert "Check what it is for" not in n and "not counted anywhere" not in n, n


def test_nontech_l16_whole_listing():
    r = read(fixture("r33-nontech-l16.txt"))
    n = notes(r)
    assert r["price"] == 1395 and r["deposit"] == 1000 and r["utilities_estimate"] == 175
    assert r["beds"] == 2 and r["baths"] == 1 and r["sqft"] == 1000 and r["parking"] == "street"
    assert 'The listing also says "Listed at $1,450 elsewhere". It is the price the same place has on another listing' in n, n
    assert "Listed at $1,450 elsewhere\". It is not counted" not in n


def test_the_figure_is_never_a_missing_monthly_amount(store):
    s = store.add_search("C", "rent")
    store.add_criterion(s["id"], "price", weight=50, dealbreaker=False, target={"max": 4000})
    t = fixture("r33-nontech-l16.txt")
    v = read(t)
    keep = {k: v[k] for k in ("tenant_pays", "utilities_estimate", "beds", "baths", "price", "deposit") if k in v}
    store.add_place(title="P", address="1 A St", search_id=s["id"], parking_cost=0, listing_text=t, reader_notes=v.get("found_in_listing"), **keep)
    rows = enrich.enrich_places(store, store.get_search(s["id"]))
    c = rows[0].get("cost") or {}
    assert "1,450" not in money.headline(c) and "1,450" not in compare.still_unknown_text(rows[0])
    assert not any("1,450" in x["text"] for x in today.cost_check(rows))


@pytest.mark.parametrize("line,cost_field", [
    ("Rent: $1,395/mo. Parking $75/mo, garage elsewhere nearby.", "parking_cost"),
    ("Rent: $1,395/mo. Application fee $50, apply online.", "application_fee"),
    ("Rent: $1,395/mo. Pet fee $300 elsewhere on the property.", None),
])
def test_other_money_near_those_words_is_unchanged(line, cost_field):
    r = read(HEAD + line)
    assert "price the same place has on another listing" not in notes(r)
    if cost_field:
        assert r[cost_field] in (75, 50)
