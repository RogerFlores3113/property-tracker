"""Cycle 20 G4: the no-silent-drop guard, no false missing, stale utility notes, titles and addresses."""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import c20_guard as G  # noqa: E402
from prophelper import compare, money  # noqa: E402
from prophelper.parsers import drop_filled_notes, parse_listing, reader_notes_for  # noqa: E402


def read(text):
    r = parse_listing(text, "")
    place = {k: v for k, v in r.items() if k != "found_in_listing"}
    place["reader_notes"] = r.get("found_in_listing", "")
    place["listing_text"] = text
    cost = money.true_monthly_cost(place, "rent")
    place["cost"] = cost
    return place, cost, compare._missing_names(place)


# readers' own drops the guard catches today (reader groups: shrink this list)
KNOWN_READER_DROPS = None  # filled by the corpus run; the guard itself must leave nothing


@pytest.mark.skipif(not G.listings(), reason="panel listings not available")
def test_guard_leaves_no_unaccounted_figure_in_the_corpus():
    assert G.run_all(True) == {}


def test_bare_multiple_is_not_placement():
    t = "2 BEDS | $1,475\nParking: Reserved $40 or street (free)\nFees: Application $35, Move-in fee $150, Parking permit $120/yr.\n"
    n = parse_listing(t, "")["found_in_listing"]
    assert "$120" in n and "$35" in n and "Only $35 and $120 of that are not counted" in n


def test_period_words_support_multiple():
    t = "2 BEDS | $1,475\nParking: Reserved $40/month, or $120 per quarter\n"
    assert "$120" not in parse_listing(t, "").get("found_in_listing", "")


@pytest.mark.parametrize("text", [
    "Elm Row 2 bed $1,500. 10 Elm St. Electric $50, gas $30 in winter, $15 summer.",
    "Elm Row 2 bed $1,500. 10 Elm St. Tenant pays gas (winter avg $30, summer avg $15) and electric $50.",
])
def test_seasonal_low_is_not_missing(text):
    place, cost, missing = read(text)
    assert not [m for m in missing if "$15" in m] and "$15" not in cost["headline"]


def test_superseded_figure_not_missing():
    place, cost, missing = read("Lincoln 1x1. No: rent is $1,440 (not $1,380 as earlier posted).\n1210 S Lincoln Ave, Urbana IL.")
    assert place["price"] == 1440 and "$1,380" not in cost["headline"] and not [m for m in missing if "$1,380" in m]


def test_parking_choice_not_missing():
    place, cost, missing = read("Logan 3BR2BA $3,250. 2700 N Milwaukee Ave.\nParking: garage OR driveway spot, garage $150, driveway $90.")
    assert place["parking_cost"] == 150 and not [m for m in missing if "$90" in m]


def test_wire_deposit_not_missing():
    r = parse_listing("Worthington Condo | Offered at $258,500\n2BR. Send deposit by wire to attorney.", "", buying=True)
    place = {**r, "reader_notes": r.get("found_in_listing", "")}
    assert "deposit" not in (money.true_monthly_cost(place, "buy").get("headline") or "")


def test_gas_figure_counts_heat():
    place, cost, missing = read("Beverly 3BR 2BA $2,650. 10400 S Hoyne Ave.\nTenant pays all utilities. Average ComEd $85, Nicor $95 winter. Water paid by owner.")
    assert not any("heat" in m for m in missing)


def test_rent_range_label():
    place, cost, missing = read("Greenleaf | 2 bed from $1,425\nRents range $1,425 - $1,610 depending on floor plan.\n5800 Sawmill Rd, Columbus OH 43235.")
    assert any("the rent (the listing gives a range)" in m for m in missing)
    assert not any("$1,425 and $1,610" in m for m in missing)


def test_only_sentence_is_one_plain_sentence():
    r = parse_listing("Quarry 1 bed $1,450. 410 N Mattis Ave.\nMonthly fees: pest control $6, package locker $4, valet trash $20 and a $9 thing", "")
    assert "The rest is already counted" not in r.get("found_in_listing", "")


def test_estimate_set_answers_utility_notes():
    t = open(os.path.join(G.PANEL, "r19-uiuc-l15.txt")).read() if os.path.exists(os.path.join(G.PANEL, "r19-uiuc-l15.txt")) else \
        "Quiet 1 bedroom $1,340 per month, 1401 E Florida Ave Urbana IL.\nElectric $45 seasonal (more in summer), gas $20-$60 depending on season. Water and trash included."
    r = parse_listing(t, "")
    place = {k: v for k, v in r.items() if k != "found_in_listing"}
    place.update(listing_text=t, reader_notes=r["found_in_listing"], utilities_estimate=110, tenant_pays="electric, gas")
    for notes in (reader_notes_for(place), drop_filled_notes(place["reader_notes"], place)):
        assert "$20" not in " ".join(n for n in notes.split("\n") if "not counted" in n)
        assert "answered by it" in notes


@pytest.mark.parametrize("text,title", [
    ("Chinatown 3BR 2BA $2,900.\nMonth to month possible after first year. 2300 S Wentworth Ave. Pets: 2 cats max.", "2300 S Wentworth Ave"),
    ("Month to month possible after first year\n2300 S Wentworth Ave. 3BR $2,900.", "2300 S Wentworth Ave"),
    ("Doorman building, rooftop. 3 bedroom $3,350. 1200 N State Pkwy.", "1200 N State Pkwy"),
    ("Yard fenced on all sides\n3 BR / 2 BA single family. $2,150/mo.", None),
])
def test_titles_never_from_policy_lines(text, title):
    assert parse_listing(text, "").get("title") == title


def test_correction_cut_and_parking_is_no_address():
    r = parse_listing("Gorgeous 3 bedroom house near Lincoln Elementary! No: rent 3,240 -- no wait, 2,340.\nParking: garage OR 2 driveway spots OR street permit.", "")
    assert r["title"] == "Gorgeous 3 bedroom house near Lincoln Elementary"
    assert "address" not in r
