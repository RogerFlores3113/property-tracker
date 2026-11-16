"""Cycle 20 G1: utilities reader. Semicolon lists with "approx.", a total after a pipe or comma list, one figure after a name at the end of a
list, bi-monthly bills in more layouts, seasonal pairs, and heat named by the gas provider. Each item has the reviewer's phrasing plus other layouts."""
from __future__ import annotations

import pytest

from prophelper.parsers import parse_listing

HEAD = "2 bed apartment, $1,450/mo."


def read(text: str) -> dict:
    sep = "\n" if "\n" in text else " "
    return parse_listing(HEAD + sep + text, "")


def notes(r: dict) -> str:
    return str(r.get("found_in_listing") or "")


def pays_set(r: dict) -> set[str]:
    return {w.strip() for w in str(r.get("tenant_pays") or "").split(",") if w.strip()}


# 1. semicolon lists --------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "Resident pays: Electric ~ $40/mo; Internet (Xfinity) approx. $60/mo; Water, sewer & trash: $45 flat/mo.",
    "Resident pays: Electric ~$40/mo; Internet approx $60/mo; Water, sewer & trash $45/mo.",
    "Tenant pays electric about $40/mo; internet about $60/mo; water, sewer and trash about $45/mo.",
    "Resident pays:\nElectric ~ $40/mo; Internet approx. $60/mo;\nWater, sewer & trash: $45 flat/mo.",
])
def test_semicolon_list_keeps_internet(text):
    r = read(text)
    assert r.get("utilities_estimate") == 145, (r.get("utilities_estimate"), notes(r))
    assert pays_set(r) == {"electric", "internet", "water", "sewer", "trash"}


# 2. totals after a list ---------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text,est,pays", [
    ("Utilities: Electric | Gas | Internet - all paid by tenant, about $140 combined.", 140, {"electric", "gas", "internet"}),
    ("Utilities: Electric, Gas, Internet - all paid by tenant, about $140 combined.", 140, {"electric", "gas", "internet"}),
    ("Utilities (tenant): electric | gas | water | internet - about $210 total, varies by season.", 210, {"electric", "gas", "water", "internet"}),
    ("Utilities (tenant): electric, gas, water, internet - about $210 total.", 210, {"electric", "gas", "water", "internet"}),
    ("Tenant pays electric, gas and internet. Typical total for tenants is $175/mo. Trash/water included.", 175, {"electric", "gas", "internet"}),
    ("Tenant pays electric, gas and internet.\nCombined total about $175 a month.", 175, {"electric", "gas", "internet"}),
])
def test_total_after_list(text, est, pays):
    r = read(text)
    assert r.get("utilities_estimate") == est, (r.get("utilities_estimate"), notes(r))
    assert pays_set(r) == pays
    assert "monthly fee" not in notes(r)
    assert "Internet is about" not in notes(r)
    assert "included" not in str(r.get("utilities_included") or "").split(", ") or "electric" not in str(r.get("utilities_included"))


def test_total_note_names_all():
    r = read("Utilities (tenant): electric | gas | water | internet - about $210 total, varies by season.")
    assert "total for electric, gas, water and internet" in notes(r)


# 3. one amount after its own name at the end of a list ---------------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "Resident pays: Electric, Gas, Trash $18, Pest $6, Valet trash. Water sewer flat $75.",
    "Resident pays: Electric, Gas, Trash $18, Pest $6.",
    "Resident pays: electric, gas, trash $18 and pest control $6.",
])
def test_name_then_amount_at_list_end(text):
    r = read(text)
    assert r.get("utilities_estimate") == 18, (r.get("utilities_estimate"), notes(r))
    assert {"electric", "gas", "trash"} <= pays_set(r)
    assert "Electric and gas are about" not in notes(r)


def test_cycle19_partial_rule_still_works():
    for t in ("Tenant: electric, gas, water, internet ($60)", "Tenant pays electric, gas, water, internet ($60)"):
        r = read(t)
        assert r.get("utilities_estimate") == 60
        assert pays_set(r) == {"electric", "gas", "water", "internet"}
        assert "internet only" in notes(r) or "counted for internet" in notes(r)


# 4. bi-monthly --------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text,est", [
    ("Electric tenant-paid, bi-monthly bill around $110.", 55),
    ("Utilities: gas is tenant-paid (winter avg $70, summer avg $15). Electric tenant-paid, bi-monthly bill around $110. Water/sewer/trash included.", 125),
    ("Pine Valley Rental $2,260 bi-monthly water about $64, electric - tenant (approx $50), gas - tenant, $35/mo.", 117),
    ("Bi-monthly water about $64; electric - tenant (approx $50); gas - tenant, $35/mo.", 117),
    ("- bi-monthly water about $64\n- electric - tenant (approx $50)\n- gas - tenant, $35/mo", 117),
])
def test_bimonthly_layouts(text, est):
    r = read(text)
    assert r.get("utilities_estimate") == est, (r.get("utilities_estimate"), notes(r))


def test_l28_gas_counted_and_water_halved():
    r = read("Pine Valley Rental $2,260 bi-monthly water about $64, electric - tenant (approx $50), gas - tenant, $35/mo.")
    assert pays_set(r) == {"water", "electric", "gas"}
    assert "gas about $35" in notes(r)


# 5. seasonal pairs ----------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text,est,lower", [
    ("Landlord pays water/sewer/trash. Electric and gas approx $140 per month in winter, $80 summer.", 140, "$80"),
    ("Electric and gas about $140/mo in winter, $80 in summer.", 140, "$80"),
    ("Utilities: gas is tenant-paid (winter avg $70, summer avg $15).", 70, "$15"),
    ("Gas (winter avg $70, summer avg $15).", 70, "$15"),
    ("Gas winter $70, summer $15.", 70, "$15"),
])
def test_seasonal_lower_figure_not_missing(text, est, lower):
    r = read(text)
    assert r.get("utilities_estimate") == est, (r.get("utilities_estimate"), notes(r))
    assert f"Only {lower} of that is not counted" not in notes(r)
    assert f"{lower}" in notes(r)  # one note quotes both figures
    assert "not counted anywhere" not in notes(r)


# 6. heat named by the gas provider --------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "Tenant pays all utilities. Average ComEd $85, Nicor $95 winter. Water paid by owner.",
    "Tenant pays all utilities. ComEd about $85, Nicor about $95 in winter. Water paid by owner.",
])
def test_heat_not_separate_unknown_when_gas_priced(text):
    r = read(text)
    assert "heat" not in pays_set(r), (r.get("tenant_pays"), notes(r))
    assert {"electric", "gas"} <= pays_set(r)


def test_heat_stays_when_gas_not_priced():
    r = read("Tenant pays all utilities. Water paid by owner.")
    assert pays_set(r) == {"electric", "gas"}  # cycle 23: "heat is gas" means the gas bill is the heat, so heat is not a separate utility


def test_total_for_everything_stays_unnamed():
    r = read("Tenant pays electric and gas. Roughly $150 a month total for everything.")
    assert r.get("utilities_estimate") == 150


def test_heat_named_in_listing_stays():
    r = read("Heat is gas, tenant pays. Gas cooking, electric tenant. Budget around $90/mo for both electric and gas.")
    assert "heat" in pays_set(r)


def test_internet_after_period_is_not_pulled_into_estimate():
    r = read("Tenant pays electric about $60 a month. Internet $65.")
    assert r.get("utilities_estimate") == 60
