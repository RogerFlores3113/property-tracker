"""Cycle 34, G4: a utilities figure that a pasted correction gives is "from the listing", never "a guess" (roommates #15)."""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp_util import call, server, text  # noqa: E402

from prophelper import money, parsers as P  # noqa: E402

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel")


def fixture(name: str) -> str:
    with open(os.path.join(FIX, name), encoding="utf-8") as fh:
        return fh.read()


FIRST = "Greektown 3BR 2BA $3,295/mo 800 W Jackson Blvd Chicago IL 60661 | Heat and water included. Tenant pays electric. Cats ok. Deposit $3,295."


def util_line(store, pid=1):
    place = store.get_place(pid)
    cost = money.rent_cost(place)
    return next(x for x in cost["lines"] if x["key"] == "utilities"), place


def add_first(store):
    store.add_search("T", "rent")
    srv = server(store)
    text(call(srv, "add_place", listing_text=FIRST))
    return srv


@pytest.mark.parametrize("correction", [
    "Tenant pays electric about $75.",
    "CORRECTION: tenant pays electric, about $75 a month.",
    "Update: electric is about $75/mo.",
    "Update\nTenant pays electric (about $75 per month)",
    "Correction - tenant pays electric; typical bills $75.",
    "TENANT PAYS ELECTRIC ABOUT $75",
])
def test_pasted_correction_figure_is_from_the_listing(store, correction):
    srv = add_first(store)
    assert store.get_place(1).get("utilities_estimate") in (None, "")
    text(call(srv, "add_place", listing_text="800 W Jackson Blvd Chicago IL 60661. " + correction))
    line, place = util_line(store)
    assert place["utilities_estimate"] == 75
    assert line["amount"] == 75 and line["label"] == "Utilities", line
    assert "guess" not in line["note"].lower() and "not from the listing" not in line["note"], line
    assert not line.get("estimated")
    out = text(call(srv, "get_place", place_id=1))
    assert "guessed" not in out and "a guess" not in out.lower(), out


def test_roommates_l13_whole_correction(store):
    store.add_search("T", "rent")
    srv = server(store)
    text(call(srv, "add_place", listing_text=fixture("r32-roommates-l12.txt")))
    text(call(srv, "add_place", listing_text=fixture("r33-roommates-l13.txt")))
    line, place = util_line(store)
    assert place["price"] == 3295 and place["utilities_estimate"] == 75
    assert line["label"] == "Utilities" and line["note"].startswith("From the listing")
    out = text(call(srv, "get_place", place_id=1))
    assert "Utilities guessed" not in out and "a guess" not in out.lower()


def test_a_figure_nobody_read_from_a_listing_is_still_a_guess(store):
    srv = add_first(store)
    text(call(srv, "update_place", place_id=1, utilities_estimate=75))
    line, _ = util_line(store)
    assert line["label"] == "Utilities (added by Claude)" and line["estimated"] is True
    assert "not read from the listing" in line["note"]


def test_a_correction_with_no_figure_adds_no_source(store):
    srv = add_first(store)
    text(call(srv, "add_place", listing_text="800 W Jackson Blvd Chicago IL 60661. Tenant pays electric. Pets: cats ok.", utilities_estimate=60))
    place = store.get_place(1)
    assert "from the listing" not in str(place.get("ai_notes") or "")

