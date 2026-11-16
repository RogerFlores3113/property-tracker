"""Cycle 21 G1: utilities reader. Read a utility list item by item, plain single lines, seasonal and bi-monthly bills, who a figure belongs to,
optional and included utilities, and a buy listing whose HOA line includes utilities. Each item has the reviewer's phrasing plus other wordings."""
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


def inc_set(r: dict) -> set[str]:
    return {w.strip() for w in str(r.get("utilities_included") or "").split(",") if w.strip()}


# 1. a list read item by item -----------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "Utilities you pay: electric ~$45, gas ~$30, water/sewer/trash flat $40, internet ~$55 -- budget roughly $170 a month total.",
    "Tenant pays electric about $45, gas about $30, water/sewer/trash flat $40, internet about $55 (roughly $170 a month total).",
    "Utilities you pay:\n- electric ~$45\n- gas ~$30\n- water/sewer/trash flat $40\n- internet ~$55\nBudget roughly $170 a month total.",
])
def test_list_with_budget_total_counts_every_item(text):
    r = read(text)
    assert r.get("utilities_estimate") == 170, (r.get("utilities_estimate"), notes(r))
    assert pays_set(r) == {"electric", "gas", "water", "sewer", "trash", "internet"}


@pytest.mark.parametrize("text,est", [
    ("Trash $18, Water $40, Electric ~$55, Gas ~$70 (winter higher). Internet $55.", 238),
    ("Trash $18, Water $40, Electric ~$55, Gas ~$70. Internet $55.", 238),
    ("Utilities: Trash $18, Water $40, Electric ~$55, Gas ~$70, Internet $55.", 238),
])
def test_internet_after_the_list_is_kept(text, est):
    r = read(text)
    assert r.get("utilities_estimate") == est, (r.get("utilities_estimate"), notes(r))
    assert pays_set(r) == {"trash", "water", "electric", "gas", "internet"}


@pytest.mark.parametrize("text", [
    "Utilities: you pay power ($90ish), gas about $40. We cover water, sewer and trash.",
    "Tenant pays power about $90 and gas about $40. Landlord covers water, sewer and trash.",
    "Utilities: gas about $40, power ~$90.",
])
def test_power_is_electric(text):
    r = read(text)
    assert r.get("utilities_estimate") == 130, (r.get("utilities_estimate"), notes(r))
    assert {"electric", "gas"} <= pays_set(r)


# 2. plain single lines ------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "Utilities (tenant): Electric about $65; Water/Sewer/Trash $55 billed monthly; Internet bundled $45.",
    "Utilities (tenant): Electric about $65; Water, Sewer, Trash $55 billed monthly; Internet bundled $45.",
    "Utilities (tenant):\nElectric about $65\nWater/Sewer/Trash $55 billed monthly\nInternet bundled $45",
])
def test_plain_lines_water_sewer_trash_and_bundled_internet(text):
    r = read(text)
    assert r.get("utilities_estimate") == 165, (r.get("utilities_estimate"), notes(r))
    assert pays_set(r) == {"electric", "water", "sewer", "trash", "internet"}


@pytest.mark.parametrize("text", [
    "Tenant pays gas and electric which averages $95 a month combined, water is $25.",
    "Tenant pays gas and electric, which average $95 a month combined, and water is $25.",
    "Tenant pays gas and electric ($95 a month combined). Water is $25.",
])
def test_water_after_a_counted_pair_is_added(text):
    r = read(text)
    assert r.get("utilities_estimate") == 120, (r.get("utilities_estimate"), notes(r))
    assert pays_set(r) == {"gas", "electric", "water"}


@pytest.mark.parametrize("text", [
    "Nice 2 bd apt ~ water+sewer+trash flat $65/mo billed by landlord ~ electric on you (typically $55) ~ no gas (all electric heat)",
    "Water, sewer and trash flat $65/mo billed by landlord. Electric is on you, typically $55. No gas.",
    "Water+sewer+trash flat $65/mo billed by the landlord; electric: tenant, typically $55; no gas",
])
def test_tilde_listing_counts_electric_and_not_no_gas(text):
    r = read(text)
    assert r.get("utilities_estimate") == 120, (r.get("utilities_estimate"), notes(r))
    assert "gas" not in pays_set(r) and "gas" not in inc_set(r)
    assert {"electric", "water", "sewer", "trash"} <= pays_set(r)


# 3. seasonal and bi-monthly -------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "Electric seasonal: $40 summer, $90 winter. Gas winter $120 summer $30.",
    "Electric: $40 in summer, $90 in winter. Gas: $30 in summer, $120 in winter.",
    "Electric seasonal ($40 summer / $90 winter). Gas winter $120, summer $30.",
])
def test_seasonal_pair_counts_the_higher(text):
    r = read(text)
    assert r.get("utilities_estimate") == 210, (r.get("utilities_estimate"), notes(r))
    assert "$90" in notes(r) and "higher" in notes(r)


@pytest.mark.parametrize("text,total", [
    ("ELECTRIC $55 | GAS $65 | WATER (BI-MONTHLY) $70 | INTERNET $60", 55 + 65 + 35 + 60),
    ("Utilities: Electric - $60, Gas - $75, Water (bi-monthly) - $80, Internet $60.", 60 + 75 + 40 + 60),
    ("Electric $55, gas $65, water $70 bi-monthly, internet $60.", 55 + 65 + 35 + 60),
    ("Electric $55, gas $65, water $70 every two months, internet $60.", 55 + 65 + 35 + 60),
])
def test_bimonthly_water_is_halved(text, total):
    r = read(text)
    assert r.get("utilities_estimate") == total, (r.get("utilities_estimate"), notes(r))
    assert "water" in pays_set(r)


@pytest.mark.parametrize("text", [
    "Utilities: Water/Sewer/Trash $85-$95 (seasonal), Electric ~ $60",
    "Utilities: Water/Sewer/Trash $85 to $95 seasonal, Electric ~ $60",
    "Tenant pays water, sewer and trash ($85-$95 depending on season) and electric about $60.",
])
def test_seasonal_range_takes_the_higher(text):
    r = read(text)
    assert r.get("utilities_estimate") == 155, (r.get("utilities_estimate"), notes(r))


@pytest.mark.parametrize("text", [
    "Tenant responsible for: Electric ~$110; Gas ~$45; Water/Sewer/Garbage ~$130 combined (billed quarterly by the city: ~$390).",
    "Tenant pays electric ~$110, gas ~$45, and water/sewer/garbage ~$130 a month combined (the city bills quarterly, about $390).",
    "Tenant responsible for:\nElectric ~$110\nGas ~$45\nWater/Sewer/Garbage ~$130 combined (billed quarterly by the city: ~$390)",
])
def test_quarterly_restatement_is_not_a_second_bill(text):
    r = read(text)
    assert r.get("utilities_estimate") == 285, (r.get("utilities_estimate"), notes(r))
    assert pays_set(r) == {"electric", "gas", "water", "sewer", "trash"}


# 4. whose figure it is ------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "Water and trash included, you pay PG&E and internet (Comcast ~$70).",
    "Water and trash included. You pay PG&E and internet (Xfinity about $70).",
    "Water and trash are included. Tenant pays electric and gas (PG&E) and internet (Comcast, ~$70).",
])
def test_internet_figure_is_not_the_electric_and_gas_bill(text):
    r = read(text)
    assert r.get("utilities_estimate") == 70, (r.get("utilities_estimate"), notes(r))
    assert pays_set(r) == {"electric", "gas", "internet"}
    assert inc_set(r) == {"water", "trash"}
    assert "Electric and gas are listed as something you pay, with no amount" in notes(r)
    assert "Electric, gas and internet are about $70" not in notes(r)


@pytest.mark.parametrize("text", [
    "Utilities: tenant pays elec + gas (avg $155 total) + $22 sewer. Landlord pays water.",
    "Tenant pays electric and gas (avg $155 total) plus $22 sewer. Landlord pays water.",
    "Utilities: tenant pays elec + gas (about $155 total), sewer $22. Landlord pays water.",
])
def test_elec_gas_total_and_sewer(text):
    r = read(text)
    assert r.get("utilities_estimate") == 177, (r.get("utilities_estimate"), notes(r))
    assert pays_set(r) == {"electric", "gas", "sewer"}
    assert inc_set(r) == {"water"}


@pytest.mark.parametrize("text", [
    "Includes: trash. Renter pays all other utilities (est. total $200).",
    "Trash included. Renter pays all other utilities (estimated total $200).",
    "Includes: trash. Renter pays all other utilities, est. $200 total.",
])
def test_all_other_utilities_total(text):
    r = read(text)
    assert r.get("utilities_estimate") == 200, (r.get("utilities_estimate"), notes(r))
    assert inc_set(r) == {"trash"}


# 5. optional and included ---------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "Utilities: Electric - $60, Gas - $75, Water (bi-monthly) - $80, Internet $55 (optional).",
    "Utilities: Electric $60, Gas $75, Water $40/mo, optional internet $55.",
    "Tenant pays electric $60, gas $75 and water $40 a month. Internet $55 (optional).",
])
def test_optional_internet_is_not_counted(text):
    r = read(text)
    assert r.get("utilities_estimate") == 175, (r.get("utilities_estimate"), notes(r))
    assert "internet" not in pays_set(r)
    assert "optional" in notes(r)


@pytest.mark.parametrize("text", [
    "Heat: gas (tenant pays, ~$60 winter). Electric ~$70. Water/Sewer/Trash: Included.",
    "Electric ~$70. Water/Sewer/Trash: included.",
    "Electric ~$70.\nWater/Sewer/Trash: Included",
])
def test_colon_included_reads_as_included(text):
    r = read(text)
    assert inc_set(r) == {"water", "sewer", "trash"}
    assert not ({"water", "sewer", "trash"} & pays_set(r))


@pytest.mark.parametrize("text", [
    "Utilities billed back; amounts vary. Rent includes: internet.",
    "Utilities are billed back to the tenant, amounts vary. Rent includes internet.",
    "Rent includes: internet. Utilities billed back (RUBS), amounts vary.",
])
def test_included_internet_with_billed_back_does_not_say_landlord_pays(text):
    r = read(text)
    assert "landlord pays the utilities" not in notes(r)
    assert inc_set(r) == {"internet"}


@pytest.mark.parametrize("text", [
    "Utilities billed back (about $140 total).",
    "Utilities billed back, about $140 total.",
    "Utilities are billed back (est. $140 total).",
])
def test_rubs_total_is_counted_with_one_note(text):
    r = read(text)
    assert r.get("utilities_estimate") == 140, (r.get("utilities_estimate"), notes(r))
    assert "gives no amount" not in notes(r)
    assert notes(r).count("billed back") == 1


# 6. buy mode ----------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "Monthly HOA assessment: $310 (includes water, exterior, snow removal).",
    "HOA dues $310/mo, which includes water, exterior maintenance and snow removal.",
    "HOA: $310 a month (snow removal and water included).",
])
def test_buy_hoa_line_is_not_a_utility_amount(text):
    r = parse_listing("Olentangy Row Condo | Offered at $312,500\n2 beds, 2 baths, 1,020 sq ft.\n" + text, "", buying=True)
    assert r.get("utilities_estimate") in (None, "")
    assert "water" in inc_set(r)
    assert "utility cost" not in notes(r)
