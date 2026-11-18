"""Cycle 16 G1: utilities reader. Two estimates add up in any wording, a bill the listing charges is never called included,
"budget around $90 for both gas and electric", an exception estimate, and a total that clashes with "landlord pays all"."""
from __future__ import annotations

import pytest

from prophelper.parsers import parse_listing

RENT = "2 bed 1 bath $1,500/month\n"


def read(text: str) -> dict:
    out = parse_listing(RENT + text)
    out.pop("source", None)
    return out


def keys(out: dict) -> tuple:
    return tuple(out.get(k) for k in ("utilities_included", "tenant_pays", "utilities_estimate"))


def note(out: dict) -> str:
    return str(out.get("found_in_listing") or "")


# ---- 1. water/sewer plus a total for electric and gas
@pytest.mark.parametrize("text", [
    "Chinatown 3BR $3,100/mo. Water/sewer $55, electric roughly $90 total for electric and gas.",
    "Water/sewer $55, electric and gas roughly $90 total.",
    "Water and sewer $55, roughly $90 total for gas and electric.",
])
def test_water_sewer_plus_electric_gas_total(text):
    out = read(text)
    assert out["utilities_estimate"] == 145
    assert out["tenant_pays"] == "electric, gas, water, sewer"
    assert not out.get("utilities_included")
    assert "not counted anywhere" not in note(out)


# ---- 2. two estimates sum once
@pytest.mark.parametrize("text", [
    "Tenant pays $55 electric, avg $70 gas",
    "Tenant pays: electric $55, avg $70 gas",
    "Electric $55 and gas avg $70 per month, tenant pays",
    "$55 electric, avg $70 gas estimated",
    "Tenant pays electric about $55 and gas about $70",
])
def test_two_estimates_sum(text):
    out = read(text)
    assert keys(out) == (None, "electric, gas", 125)
    assert "not counted anywhere" not in note(out)


def test_two_estimates_ravenswood_rubs_not_covered():
    out = read("Tenant pays: electric $55, avg $70 gas. Water/sewer/trash billed back via RUBS")
    assert out["utilities_estimate"] == 125
    assert out["tenant_pays"] == "electric, gas, water, sewer, trash"
    assert "billed back to you, but the listing gives no amount" in note(out)


def test_two_estimates_rubs_other_wording():
    out = read("Electric $55 and gas avg $70 per month. Water, sewer and trash are billed back (RUBS).")
    assert out["utilities_estimate"] == 125
    assert not out.get("utilities_included")


# ---- 3. a billed utility is never included
@pytest.mark.parametrize("text", [
    "Utilities: Tenant pays electric. Water bill is quarterly, usually $120 a quarter. Sewer and trash included.",
    "Tenant pays electric. Water bill is quarterly, about $120 per quarter. Sewer and trash included.",
    "Water bill is quarterly, usually $120 a quarter. Sewer and trash included.",
])
def test_quarterly_water_bill_not_included(text):
    out = read(text)
    assert out["utilities_included"] == "sewer, trash"
    assert out["utilities_estimate"] == 40
    assert "water" in out["tenant_pays"]
    assert "not counted anywhere" not in note(out)


@pytest.mark.parametrize("text", [
    "Landlord pays water, sewer and trash. Quarterly water bill passed through.",
    "Landlord pays water. Water bill is passed through to tenants.",
    "Landlord pays water. Quarterly water bill billed to tenants.",
])
def test_landlord_pays_water_but_bill_passed_through(text):
    out = read(text)
    assert "water" not in (out.get("utilities_included") or "")
    assert "water" not in (out.get("tenant_pays") or "")
    assert out.get("utilities_estimate") is None
    assert "passed through to you" in note(out) or "billed to you" in note(out) or "water bill is" in note(out)
    assert "Water is left unknown" in note(out)


# ---- 4. both utilities named after "both"
@pytest.mark.parametrize("text,names", [
    ("Budget around $90/mo for both gas and electric", "electric, gas"),
    ("Budget around $90/mo for both electric and gas", "electric, gas"),
    ("Tenant pays. Expect about $90 a month for both gas and electric.", "electric, gas"),
])
def test_budget_for_both(text, names):
    out = read(text)
    assert out["utilities_estimate"] == 90
    assert out["tenant_pays"] == names
    assert "not counted anywhere" not in note(out)


@pytest.mark.parametrize("text", [
    "Landlord pays all utilities except they said electric is on you, about $60. Dog no.",
    "Landlord pays all utilities except electric, which is on you, about $60.",
    "Landlord pays everything but electric, probably $60 a month.",
    "Utilities included except electric, about $60 a month.",
])
def test_electric_about_60(text):
    out = read(text)
    assert out["utilities_estimate"] == 60
    assert out["tenant_pays"] == "electric"
    assert "electric" not in (out.get("utilities_included") or "")


def test_everything_but_electric_is_not_included():
    out = read("Landlord pays everything but electric.")
    assert "electric" not in (out.get("utilities_included") or "")
    assert out["tenant_pays"] == "electric"


# ---- 5. conflicts
@pytest.mark.parametrize("text", [
    "Roughly $150 total for everything. Landlord pays all utilities.",
    "Landlord pays all utilities. Roughly $150 a month total for everything.",
    "Utilities included in rent. About $150 total for all utilities.",
])
def test_total_versus_landlord_pays_all(text):
    out = read(text)
    assert not out.get("utilities_included")
    assert out.get("utilities_estimate") is None
    assert "don't agree" in note(out)


def test_gateway_no_false_unclear_note():
    out = read("Utilities: avg $70 for electric, roughly $150 a month total for everything if you run the AC. Tenant pays all.")
    assert not out.get("utilities_included")
    assert out["utilities_estimate"] == 150
    assert "unclear about" not in note(out)


@pytest.mark.parametrize("text", [
    "Utilities: about $60 for electric. Tenant pays all.",
    "Utilities: electric averages $80. Tenant pays.",
])
def test_utilities_label_with_price_is_not_included(text):
    out = read(text)
    assert "electric" not in (out.get("utilities_included") or "")
