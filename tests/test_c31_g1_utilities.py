"""Cycle 31 group G1: utilities reader. "Typical bills for the unit about $140." with no "/mo" (after a full stop, after a semicolon, before the payer
line, with an "included" sentence between) is the utilities estimate for what the tenant pays; a typical total that covers the tenant-paid list removes
those utilities from the missing list; "Resident pays electric ($65), water/sewer flat $40, internet" prices electric from its bracket; "electric
included" with two electric figures gives one plain note; a utility billed back with an amount is in the tenant-pays list."""
import os

import pytest

from prophelper import compare, money
from prophelper.parsers import parse_listing

HEAD = "Rent $3,050. "


def P(text):
    return parse_listing(text, "")


def notes(r):
    return r.get("found_in_listing") or ""


def pays(r):
    return {w.strip() for w in (r.get("tenant_pays") or "").split(",") if w.strip()}


def missing(text):
    r = P(text)
    place = dict(r, reader_notes=r.get("found_in_listing"), listing_text=text)
    c = money.true_monthly_cost(place, "rent")
    return r, c, compare._missing_names(dict(place, cost=c, score={"unknown": []}))


def saved(name):
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel")
    return open(os.path.join(base, name + ".txt"), encoding="utf-8").read()


# ---- 1. "Typical bills for the unit about $X." with no "/mo", in every layout
NO_MO = [
    "Typical bills for the unit about $140. Gas and water included. Resident pays electric and internet.",
    "Typical bills for the unit about $140. Gas and water included. Tenant pays electric and internet.",
    "Gas and water included. Resident pays electric and internet. Typical bills for the unit about $140.",
    "Gas and water included; resident pays electric and internet; typical bills for the unit about $140.",
    "Gas and water included.\nResident pays electric and internet.\nTypical bills for the unit about $140.",
    "- Gas and water included\n- Resident pays electric and internet\n- Typical bills for the unit about $140",
]


@pytest.mark.parametrize("body", NO_MO)
def test_typical_bills_without_per_month(body):
    r, c, miss = missing(HEAD + body)
    assert r["utilities_estimate"] == 140
    assert pays(r) == {"electric", "internet"}
    assert _set(r.get("utilities_included")) == {"gas", "water"}
    assert "not counted anywhere" not in notes(r)
    assert miss == [], miss
    assert not any("amount in the listing notes" in m for m in miss)


def _set(v):
    return {w.strip() for w in (v or "").split(",") if w.strip()}


def test_roommates_l16_whole_listing():
    r, c, miss = missing(saved("r30-roommates-l16"))
    assert r["utilities_estimate"] == 140
    assert pays(r) == {"electric", "internet"}
    assert "not counted anywhere" not in notes(r)
    assert not any("$140" in m for m in miss), miss
    assert "$140" in notes(r)  # the figure is named once, as the estimate


# ---- 2. the same after a semicolon or a dash
SEMI = [
    "Tenant pays electric and gas; typical bills for the unit about $165. Water, sewer, trash included.",
    "Resident pays electric and gas; typical bills for the unit about $165. Water, sewer, trash included.",
    "Tenant pays electric and gas - typical bills for the unit about $165. Water, sewer, trash included.",
    "Tenant pays electric and gas. Typical bills for the unit about $165. Water, sewer, trash included.",
    "Water, sewer, trash included. Tenant pays electric and gas; typical total bills for the unit about $165.",
]


@pytest.mark.parametrize("body", SEMI)
def test_estimate_after_semicolon(body):
    r, c, miss = missing(HEAD + body)
    assert r["utilities_estimate"] == 165
    assert pays(r) == {"electric", "gas"}
    assert "not counted anywhere" not in notes(r)
    assert miss == [], miss


def test_family_l1_whole_listing():
    r, c, miss = missing(saved("r30-family-l1"))
    assert r["utilities_estimate"] == 165
    assert pays(r) == {"electric", "gas"}
    assert _set(r.get("utilities_included")) == {"water", "sewer", "trash"}
    assert "not counted anywhere" not in notes(r)
    assert not any("$165" in m for m in miss), miss


# ---- 3. a typical total that covers the tenant-paid list removes them from missing
TOTALS = [
    "Heat and hot water included; resident pays electric, gas for cooking, and cable. Typical total utilities for the unit about $95. Utilities are billed back by a third party (Conservice).",
    "Heat included; tenant pays electric and gas. Typical total utilities for the unit about $95. Billed back by Conservice.",
    "Utilities are billed back by a third party (Conservice). Heat included. Resident pays electric and gas. Typical total utilities for the unit about $95.",
    "Heat included. Resident pays electric and gas.\nTypical total utilities for the unit about $95.\nBilled back by a third party.",
]


@pytest.mark.parametrize("body", TOTALS)
def test_typical_total_covers_the_tenant_paid_list(body):
    r, c, miss = missing(HEAD + body)
    assert r["utilities_estimate"] == 95
    assert {"electric", "gas"} <= pays(r)
    assert miss == [], miss
    assert "doesn't say which utilities" not in notes(r)
    assert "$95" in notes(r)


def test_roommates_l19_whole_listing():
    r, c, miss = missing(saved("r30-roommates-l19"))
    assert r["utilities_estimate"] == 95
    assert r["other_monthly_fees"] == 9.95
    assert pays(r) == {"electric", "gas"}
    assert _set(r["utilities_included"]) == {"heat", "hot water"}
    assert miss == [], miss
    assert "doesn't say which utilities" not in notes(r)
    assert "electric and gas" in notes(r)
    assert "not counted" not in notes(r)


# ---- 4. "Resident pays electric ($65), water/sewer flat $40, internet" prices electric from its bracket
BRACKET = [
    "Utilities: Resident pays electric ($65), water/sewer flat $40, internet.",
    "Resident pays electric ($65), water/sewer flat $40, internet.",
    "Tenant pays electric ($65), water/sewer flat $40, internet.",
    "Utilities: Resident pays electric (about $65), water/sewer flat $40, internet.",
    "Utilities: Resident pays:\n- electric ($65)\n- water/sewer flat $40\n- internet",
]


@pytest.mark.parametrize("body", BRACKET)
def test_electric_priced_from_its_bracket(body):
    r, c, miss = missing("Rent $1,310. " + body)
    assert r["utilities_estimate"] == 105
    assert {"electric", "water", "sewer"} <= pays(r)
    n = notes(r)
    assert "Water, sewer and internet" not in n and "Water and internet" not in n
    assert "Electric, water and sewer" in n
    assert "electric" not in " ".join(miss).lower(), miss
    assert "water" not in " ".join(miss).lower(), miss
    assert not any("amount in the listing notes" in m for m in miss)


@pytest.mark.parametrize("body, total", [
    ("Resident pays electric ($65), internet.", 65),
    ("Resident pays electric ($65), gas ($30), internet.", 95),
    ("Resident pays electric ($65) and internet.", 65),
])
def test_bracket_figure_stays_with_its_own_utility(body, total):
    r, c, miss = missing("Rent $1,310. " + body)
    assert r["utilities_estimate"] == total
    assert "internet" in " ".join(miss), miss
    assert "electric" not in " ".join(miss), miss


def test_uiuc_l7_whole_listing():
    r, c, miss = missing(saved("r30-uiuc-l7"))
    assert r["utilities_estimate"] == 105
    assert {"electric", "water", "sewer", "internet"} <= pays(r)
    assert "Electric, water and sewer are about $105" in notes(r)
    assert miss == ["internet"], miss


# ---- 5. "electric included" with two electric figures: one plain note
TWO_ELECTRIC = [
    "Electric included. Electric about $55 a month. Electric around $60. Tenant pays gas.",
    "Tenant pays gas. Electric included. Electric about $60 a month. Electric around $55.",
    "Electric included. Electric $55/mo. Electric $60/mo. Tenant pays gas.",
    "Electric included. Electric: $55/mo. Electric: $60/mo. Tenant pays gas.",
]


@pytest.mark.parametrize("body", TWO_ELECTRIC)
def test_electric_included_with_two_figures_one_note(body):
    r, c, miss = missing("Rent $1,395. " + body)
    assert r["utilities_estimate"] == 60
    assert pays(r) == {"electric", "gas"}
    assert not r.get("utilities_included")
    n = notes(r)
    electric_notes = [x for x in n.split("\n") if "electric" in x.lower()]
    assert len(electric_notes) == 2, electric_notes  # the counted amount, and one note about the clash
    assert "Only the figure that covers more" not in n
    assert "gives you a monthly amount for it" not in n
    assert "$55" in n and "$60" in n
    assert miss == ["gas"], miss


def test_uiuc_l6_whole_listing_electric_notes():
    r = P(saved("r30-uiuc-l6"))
    n = notes(r)
    assert r["utilities_estimate"] == 60
    assert "Only the figure that covers more" not in n
    assert "gives you a monthly amount for it" not in n
    assert sum(1 for x in n.split("\n") if "$55" in x) == 1


# ---- 6. water and trash billed back: both are in the tenant-pays list, and the estimate is counted once
BILLED = [
    "Water and trash billed back by landlord, about $55/mo.",
    "Trash and water billed back by the landlord, approx $55 a month.",
    "Water and trash are billed back to the tenant, about $55 per month.",
    "- Water and trash billed back, about $55/mo",
]


@pytest.mark.parametrize("body", BILLED)
def test_billed_back_trash_is_in_the_tenant_pays_list(body):
    r, c, miss = missing("Rent $1,150. " + body)
    assert r["utilities_estimate"] == 55
    assert pays(r) == {"water", "trash"}
    assert miss == [], miss


def test_nontech_l13_whole_listing():
    r, c, miss = missing(saved("r30-nontech-l13"))
    assert r["utilities_estimate"] == 55
    assert pays(r) == {"water", "trash"}
    assert miss == [], miss
