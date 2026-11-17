"""Cycle 30, group G4: beds from a priced unit beside a "1 - 2 Beds" range, a useful name for an all-facts title line,
and one unknown named once in the missing list. Paths are built from this file."""
from __future__ import annotations

import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from prophelper import compare, money  # noqa: E402
from prophelper import parsers as P  # noqa: E402

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel")


def fixture(name: str) -> str:
    with open(os.path.join(FIX, name), encoding="utf-8") as fh:
        return fh.read()


def read(text: str) -> dict:
    return P.parse_listing(text, "")


def notes_of(r: dict) -> str:
    return str(r.get("found_in_listing") or "")


# ---------------------------------------------------------------- 1. beds from the priced unit, never the low end of a range

class TestBedsRange:
    def test_nontech_l11(self):
        r = read(fixture("r29-nontech-l11.txt"))
        assert r["beds"] == 2 and r["baths"] == 2 and r["price"] == 1495 and r["sqft"] == 1050

    @pytest.mark.parametrize("head", [
        "1 - 2 Beds | $1,395 - $1,640\n2 Bed 2 Bath 1,050 Sq Ft  $1,495/mo",
        "1-2 Beds, $1,395 to $1,640\n2 Bed 2 Bath 1,050 Sq Ft $1,495/mo",
        "Beds: 1 - 2 | Rent range $1,395 - $1,640\n- 2 Bed 2 Bath, 1,050 Sq Ft, $1,495/mo",
        "1 to 2 Bedrooms | $1,395 - $1,640\n2 Bedroom, 2 Bath 1,050 sqft $1,495 per month",
    ])
    def test_other_layouts(self, head):
        r = read("The Lofts at Franklinton\n" + head + "\nSecurity deposit $500.")
        assert r["beds"] == 2, r
        assert r["price"] == 1495, r

    @pytest.mark.parametrize("text", [
        "Franklinton Lofts\n1 - 2 Beds | $1,395 - $1,640\nSecurity deposit $500.",
        "Franklinton Lofts\n1-2 bedroom apartments from $1,395.\nSecurity deposit $500.",
        "Franklinton Lofts\n2 - 3 Beds, $1,800 - $2,100\nSecurity deposit $500.",
    ])
    def test_range_alone_leaves_beds_empty_with_a_note(self, text):
        r = read(text)
        assert r.get("beds") in (None, ""), r.get("beds")
        assert "more than one size" in notes_of(r) and "left empty" in notes_of(r)

    def test_single_count_still_read(self):
        assert read("Oak Row\n2 Bed 1 Bath $1,400/mo")["beds"] == 2
        assert read("Oak Row\n3 bedroom house $2,400/mo")["beds"] == 3
        assert read("Oak Row studio\n$900/mo")["beds"] == 0


# ---------------------------------------------------------------- 2. a title that is all facts keeps the place

class TestFactTitle:
    @pytest.mark.parametrize("line,name", [
        ("Zillow-ish: 2/1 renovated, 1,100 sqft near Short North, $1,475", "2/1 renovated near Short North"),
        ("Zillow: 2/1 renovated, 1,100 sqft near Short North, $1,475", "2/1 renovated near Short North"),
        ("Craigslist-ish: 3 bed 2 bath updated near Lake Shore, $2,100/mo", "3 bed 2 bath updated near Lake Shore"),
        ("2 bed 1 bath, 900 sqft in Clintonville, $1,350", "2 bed 1 bath in Clintonville"),
    ])
    def test_name_kept(self, line, name):
        r = read(line + "\nTenant pays electric.\nApplication fee $50.")
        assert r["title"] == name, r["title"]
        assert "$" not in r["title"] and "sqft" not in r["title"]

    def test_nontech_l4(self):
        r = read(fixture("r29-nontech-l4.txt"))
        assert r["title"] == "2/1 renovated near Short North"
        assert r["price"] == 1475 and r["beds"] == 2 and r["sqft"] == 1100

    def test_walk_time_is_not_a_place(self):
        r = read("2 bed near campus, 5 min walk, $1,200\nSecurity deposit $500.")
        assert r["title"] != "2 bed place"


# ---------------------------------------------------------------- 3. an unknown is named once

def surfaces(text: str) -> tuple[str, list[str], list[str]]:
    r = read(text)
    place = dict(r, reader_notes=r.get("found_in_listing"), listing_text=text)
    cost = money.true_monthly_cost(place, "rent")
    pl = dict(place, cost=cost, score={"unknown": []})
    return cost.get("headline") or "", compare._missing_names(pl), [str(x) for x in cost.get("missing") or []]


class TestOnceOnly:
    def test_uiuc_l17(self):
        head, names, missing = surfaces(fixture("r29-uiuc-l17.txt"))
        assert names == ["utilities estimate", "parking cost"]
        assert "listing notes" not in head and "listing notes" not in " ".join(names)
        assert len(re.findall(r"parking", head)) == 1
        assert head.endswith("utilities and parking not counted yet")

    @pytest.mark.parametrize("text", [
        "Cheap 1BR, $650/mo. Includes garage.",
        "Campus studio $700/mo. Own garage included, price TBD.",
        "1 bed 1 bath $720 a month\nGarage parking available.",
    ])
    def test_other_listings_never_repeat(self, text):
        head, names, missing = surfaces(text)
        low = " ".join(names).lower()
        assert low.count("parking") <= 1, names
        assert len(set(names)) == len(names)


# ---------------------------------------------------------------- 4. Compare: "is cheapest" names what the cheapest leaves out

class TestCheapestSaysUnknowns:
    def _place(self, store, **kw):
        from test_c10_g6_fit_today_compare import _enriched, _search
        s = _search(store, budget_max=2000)
        return _enriched(store, s, **kw)

    @pytest.mark.parametrize("fields,expect", [
        (dict(title="Gap", address="1 A St", price=1000, tenant_pays="electric"), "its utilities aren't counted"),
        (dict(title="Gap2", address="1 A St", price=1000, tenant_pays="electric, gas"), "its utilities aren't counted"),
        (dict(title="Gap3", address="1 A St", price=1000, utilities_included="heat, water"), "aren't counted"),
    ])
    def test_blocked_and_over_limit_sentences(self, store, monkeypatch, fields, expect):
        p = self._place(store, **fields)
        assert compare._uncounted(p)
        canned = {"winners": [], "amount": None, "same": False, "all_unknown": False, "of_fit": False, "no_fit": False,
                  "skipped_unknown": [], "over_limit": [(p, "24 min bike vs your 20 min limit")], "blocked": []}
        monkeypatch.setattr(compare, "lowest_cost", lambda places: canned)
        sent = " ".join(compare.lowest_cost_sentences([p], lambda x: x["title"]))
        assert f"{fields['title']} is cheapest, but 24 min bike vs your 20 min limit, and " in sent
        assert expect in sent
        canned2 = dict(canned, over_limit=[], blocked=[(p, "it is a near miss")])
        monkeypatch.setattr(compare, "lowest_cost", lambda places: canned2)
        sent2 = " ".join(compare.lowest_cost_sentences([p], lambda x: x["title"]))
        assert "it is a near miss, and " in sent2 and expect in sent2

    def test_complete_place_gets_no_clause(self, store, monkeypatch):
        p = self._place(store, title="Full", address="1 A St", price=1000, utilities_estimate=0)
        assert compare._leaves_out_clause(p) == ""
