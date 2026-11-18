"""Cycle 32, G4: after update_place saves a utilities estimate, Missing and the headline no longer name the "typical bills" figure it settled,
and another plan's price ("that's the 2 bed") is never named as an amount left out."""
from __future__ import annotations

import os

import pytest

from prophelper import money, parsers as P

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel")


def fixture(name: str) -> str:
    with open(os.path.join(FIX, name), encoding="utf-8") as fh:
        return fh.read()


def cost_of(text: str, **saved) -> dict:
    r = P.parse_listing(text, "")
    pl = dict(r, reader_notes=r.get("found_in_listing"), listing_text=text, **saved)
    return money.true_monthly_cost(pl, "rent")


BASE = "2BR, $1,395/mo. Water included. Deposit $500.\n"


@pytest.mark.parametrize("line", [
    "Typical bills for the unit about $140; resident pays electric, gas.",
    "Resident pays electric, gas. Typical bills for the unit about $140 per month.",
    "Utilities: typical bills about $140/mo. Resident pays electric and gas.",
    "Average utilities about $140 a month; tenant pays electric and gas.",
    "Tenant pays electric and gas (typical bills about $140).",
    "Tenant pays electric and gas.\nTypical bills for the unit about $140.",
])
def test_saved_estimate_settles_typical_bills(line):
    c = cost_of(BASE + line, utilities_estimate=175)
    label = str(c.get("listing_notes_label") or "")
    assert "$140" not in label and "$140" not in str(c.get("headline"))
    assert "$140" not in " ".join(str(x) for x in c.get("missing") or [])


def test_reviewer_listing_names_neither_figure():
    c = cost_of(fixture("r31-uiuc-l1.txt"), utilities_estimate=175)
    text = str(c.get("listing_notes_label") or "") + str(c.get("headline")) + " ".join(str(x) for x in c.get("missing") or [])
    assert "$140" not in text and "$3,075" not in text


def test_other_open_figures_are_still_named():
    c = cost_of(BASE + "Typical bills for the unit about $140. Mystery charge $88 monthly.", utilities_estimate=175)
    assert "$88" in str(c.get("listing_notes_label"))
    assert "$140" not in str(c.get("listing_notes_label"))


def test_without_a_saved_estimate_nothing_is_hidden():
    r = P.parse_listing(BASE + "Resident pays electric, gas. Typical bills for the unit about $140.", "")
    n = str(r.get("found_in_listing"))
    assert "$140" in n or r.get("utilities_estimate") == 140
