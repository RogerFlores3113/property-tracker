"""Cycle 31 G5: the Claude compare tool's "is cheapest, but" sentence names what is not counted, like the Compare page."""
import pytest
from mcp_util import call, server, text

from prophelper import compare
from test_c6_g4_compare_rules import _add, _commute_setup, _e, _full, _search


@pytest.mark.parametrize("fields,expect", [
    (dict(tenant_pays="electric"), "its electric isn't counted"),
    (dict(tenant_pays="electric, gas"), "its electric and gas aren't counted"),
    (dict(utilities_included="heat, water"), "aren't counted"),
])
def test_mcp_cheapest_names_what_is_not_counted(store, fields, expect):
    s = _search(store)
    base = dict(deposit=500, parking="street", parking_cost=0, pet_rent=0, other_monthly_fees=0)
    sav = _add(store, s, "Savoy", price=1200, **base, **fields)
    har = _add(store, s, "Harvest", price=1300, **_full())
    _commute_setup(store, s, {sav: 24, har: 12})
    line_web = next(l for l in compare.summary_lines(_e(store, s, sav, har), compare.build_rows(_e(store, s, sav, har))) if l.startswith("Savoy is cheapest, but"))
    out = text(call(server(store), "compare_places", place_ids=[sav, har]))
    mine = next(l for l in out.splitlines() if l.startswith(f"#{sav} is cheapest, but"))
    assert expect in mine, mine
    assert expect in line_web, line_web
    assert mine.split(", but ", 1)[1] == line_web.split(", but ", 1)[1]


def test_mcp_complete_cheapest_has_no_clause(store):
    s = _search(store)
    sav = _add(store, s, "Savoy", price=1200, **_full())
    har = _add(store, s, "Harvest", price=1300, **_full())
    _commute_setup(store, s, {sav: 24, har: 12})
    out = text(call(server(store), "compare_places", place_ids=[sav, har]))
    mine = next(l for l in out.splitlines() if l.startswith(f"#{sav} is cheapest, but"))
    assert "counted" not in mine
