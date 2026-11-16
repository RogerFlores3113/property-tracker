"""Cycle 18 G1: one general utility-line reader. Every item is tested in three layouts (one line with commas or parentheses,
separate sentences, bullets or dashes) plus the reviewers' whole listings. Figures for different utilities add up once, a
quarterly or "every 3 months" bill counts a third, the payer comes from the words around each utility, and a conflict stays unknown."""
from __future__ import annotations

import pytest

from prophelper.parsers import parse_listing

HEAD = "2 bed apartment, $1,450/mo. "


def read(text: str) -> dict:
    return parse_listing(text, "")


def notes(r: dict) -> str:
    return "\n".join(str(v) for v in r.values() if isinstance(v, str))


def check(text: str, est, pays: str | None, included: str | None = None) -> dict:
    r = read(text)
    assert r.get("utilities_estimate") == est, (text, r.get("utilities_estimate"), notes(r))
    assert r.get("tenant_pays") == pays, (text, r.get("tenant_pays"))
    if included is not None:
        assert r.get("utilities_included") == included, (text, r.get("utilities_included"))
    return r


# 1. "Landlord pays all utilities. Tenant electric only total $110": electric is the tenant's, the rest is included
ELECTRIC_ONLY = [
    HEAD + "Landlord pays all utilities. Tenant electric only total $110",
    HEAD + "Landlord pays all utilities. Tenant electric only, total $110",
    HEAD + "Landlord pays all utilities. Tenant electric only total $110 per month",
    HEAD + "Landlord pays all utilities, tenant electric only total $110.",
    "2 bed apartment, $1,450/mo.\nLandlord pays all utilities.\nTenant electric only total $110",
    "2 bed apartment, $1,450/mo.\n- Landlord pays all utilities\n- Tenant electric only, total $110 per month",
]


@pytest.mark.parametrize("text", ELECTRIC_ONLY)
def test_landlord_pays_all_but_tenant_electric_only(text):
    r = check(text, 110, "electric", "gas, water, sewer, trash, heat")
    assert "not counted anywhere" not in notes(r)


GENERIC_TOTAL = [
    HEAD + "Landlord pays all utilities. Tenant total utilities $90 a month.",
    "2 bed apartment, $1,450/mo.\nLandlord pays all utilities.\nTenant total utilities $90 a month.",
    "2 bed apartment, $1,450/mo.\n- Landlord pays all utilities\n- Tenant total utilities $90 a month",
]


@pytest.mark.parametrize("text", GENERIC_TOTAL)
def test_landlord_pays_all_next_to_tenant_total_is_a_conflict(text):
    r = read(text)
    assert not r.get("utilities_included")
    assert r.get("utilities_estimate") is None
    assert "don't agree" in notes(r)


# 2. water paid by owner next to two priced utilities
WATER_OWNER = [
    "3 bed house, $2,400/mo. Utilities: electric ~$65/mo, gas ~$40/mo, water paid by owner",
    "3 bed house, $2,400/mo. Electric ~$65/mo. Gas ~$40/mo. Water paid by owner.",
    "3 bed house, $2,400/mo.\n- Electric ~$65/mo\n- Gas ~$40/mo\n- Water paid by owner",
    "3 bed house, $2,400/mo. Utilities (electric ~$65/mo, gas ~$40/mo), water paid by owner",
]


@pytest.mark.parametrize("text", WATER_OWNER)
def test_water_paid_by_owner_is_never_a_tenant_water_amount(text):
    check(text, 105, "electric, gas", "water")


# 3. periods
@pytest.mark.parametrize("text,est,pays", [
    (HEAD + "Water and sewer about $210 every 3 months", 70, "water, sewer"),
    (HEAD + "Utilities: water and sewer about $210 every three months.", 70, "water, sewer"),
    ("2 bed, $1,450/mo.\n- Water and sewer about $210 every 3 months", 70, "water, sewer"),
    ("2 bed, $1,450/mo.\n- Water/sewer: $120 per quarter", 40, "water, sewer"),
    (HEAD + "Water/sewer: $120 per quarter.", 40, "water, sewer"),
    (HEAD + "Utilities: water/sewer $120 per quarter", 40, "water, sewer"),
    ("2 bed, $1,450/mo.\n- Water, sewer and trash: $140 per quarter", 46.67, "water, sewer, trash"),
    (HEAD + "Water, sewer and trash: $140 per quarter.", 46.67, "water, sewer, trash"),
    (HEAD + "Tenant pays water $75 quarterly.", 25, "water"),
    ("2 bed, $1,450/mo.\nWater $75 quarterly", 25, "water"),
    (HEAD + "Utilities: electric $50 monthly, water $75 quarterly", 75, "electric, water"),
    (HEAD + "Water $300 per year, tenant pays", 25, "water"),
])
def test_periods_count_a_share_per_month(text, est, pays):
    check(text, est, pays)


# 4. lists keep every figure
LIST_CASES = [
    (HEAD + "Utilities: Electric (avg $48), Gas (avg $32), Water/Sewer flat $38, Trash $8", 126, "electric, gas, water, sewer, trash"),
    (HEAD + "Electric avg $48, gas avg $32, water/sewer flat $38, trash $8 (all paid by tenant)", 126, "electric, gas, water, sewer, trash"),
    ("2 bed, $1,450/mo.\n- Electric avg $48\n- Gas avg $32\n- Water/Sewer flat $38\n- Trash $8", 126, "electric, gas, water, sewer, trash"),
    (HEAD + "Utilities: gas $35, electric $60, internet $55 (tenant pays all three)", 150, "electric, gas, internet"),
    (HEAD + "Utilities: electric $60, gas $35, internet $55 (all tenant)", 150, "electric, gas, internet"),
    ("2 bed, $1,450/mo.\n- Electric $60\n- Gas $35\n- Internet $55", 150, "electric, gas, internet"),
    ("2 bed, $1,450/mo.\n- Electric: $55 - Gas: $70 - Cable/internet: $80", 205, "electric, gas, internet"),
    ("2 bed, $1,450/mo.\n- Electric: $55\n- Gas: $70\n- Cable/internet: $80", 205, "electric, gas, internet"),
    (HEAD + "Tenant pays electric $60 and gas $45, water included", 105, "electric, gas"),
    ("2 bed, $1,450/mo.\nTenant pays electric $60 and gas $45\nWater included", 105, "electric, gas"),
    (HEAD + "Water included. Tenant pays electric $60 and gas $45.", 105, "electric, gas"),
    (HEAD + "Electric tenant $70", 70, "electric"),
    ("2 bed, $1,450/mo.\nElectric tenant $70", 70, "electric"),
    (HEAD + "Electric: tenant pays, $70", 70, "electric"),
    (HEAD + "$65 monthly for sewer and trash", 65, "sewer, trash"),
    (HEAD + "Sewer and trash: $65 monthly", 65, "sewer, trash"),
    ("2 bed, $1,450/mo.\n- Sewer and trash $65 monthly", 65, "sewer, trash"),
    (HEAD + "Tenant pays gas and electric, estimated $140/mo combined; water and trash are billed back at $45 flat monthly.", 185, "electric, gas, water, trash"),
    ("2 bed, $1,450/mo.\nGas and electric: tenant pays, est. $140/mo combined\nWater and trash: billed back, $45 flat monthly", 185, "electric, gas, water, trash"),
    (HEAD + "Utilities billed back via submeter: electric ~ $70, heat ~ $50 (winter). Cable included.", 120, "electric, heat"),
    ("2 bed, $1,450/mo.\nSubmeter: electric ~ $70\nHeat ~ $50", 120, "electric, heat"),
]


@pytest.mark.parametrize("text,est,pays", LIST_CASES)
def test_lists_keep_every_figure(text, est, pays):
    r = check(text, est, pays)
    assert "(RUBS)" not in notes(r) and "landlord pays the utilities" not in notes(r)


def test_edgewater_submeter_listing_has_no_false_conflict():
    text = ("Edgewater 3BR 2BA $3,000 per month. 5600 N Sheridan Rd. Utilities billed back via submeter: electric ~ $70, heat ~ $50 (winter). "
            "Cable included. Required: renter's insurance ($12/mo through landlord's program). Lease: 14 months from Jan 15 2027. "
            "Pets: 1 dog max 30 lbs, $500 non-refundable pet fee, $40/mo.")
    r = check(text, 120, "electric, heat")
    assert "landlord pays the utilities" not in notes(r) and "RUBS" not in notes(r)


# 5. RUBS next to other figures
QUAIL = ("Quail Run Townhomes - Spacious 3BR 2.5BA end unit. Rent $2,380. Tenant pays: electric and gas, avg $65 electric, $40 gas; "
         "water/sewer/trash via RUBS about $70. Pet policy: max 2 pets, 75 lb weight limit per pet, breed restrictions apply. "
         "$500 pet deposit ($250 non-refundable), $25/month pet rent per pet. Fully fenced courtyard. 2 assigned parking spaces, $35/mo each. "
         "Admin fee $150 one time. Application fee $55 per applicant. Security deposit equal to 1.5 months rent. Lease begins on the first of January 2027.")
UIUC8 = ("Quarry Heights, 1 Bed 1 Bath, $1,450 per month\n410 N Mattis Ave, Champaign IL 61820\n- Built 2021, 690 sq ft\n"
         "- Assigned covered space $60/month\n- Utilities: electric $60, gas $35 (resident pays)\n- Water/sewer/trash flat $30/mo RUBS\n"
         "- Cats and small dogs ok, $250 per pet deposit, 30 lb limit\n- Lease begins 8/1/27, 12 month\n- Security deposit: one month")
LAKEVIEW = ("Lakeview 3BR 2BA $3,350 -> $3,200 price drop. 3300 N Broadway Chicago IL 60657. RUBS billed back: water/sewer/trash $85/mo avg, "
            "plus tenant pays electric and gas about $110 combined. Valet trash $30/mo. Package locker fee $10/month. Deposit $3,200. App fee $50 per adult.")


def test_quail_run_adds_rubs_to_electric_and_gas():
    r = check(QUAIL, 175, "electric, gas, water, sewer, trash")
    assert "gives no amount" not in notes(r)


def test_quail_run_other_layouts():
    check(HEAD + "Tenant pays: avg $65 electric, $40 gas. Water/sewer/trash via RUBS about $70.", 175, "electric, gas, water, sewer, trash")
    check("2 bed, $1,450/mo.\n- Electric avg $65\n- Gas $40\n- Water/sewer/trash via RUBS about $70", 175, "electric, gas, water, sewer, trash")


def test_uiuc_l8_keeps_gas_next_to_rubs_line():
    check(UIUC8, 125, "electric, gas, water, sewer, trash")


@pytest.mark.parametrize("text", [
    HEAD + "Typical electric $60. Water/sewer/trash RUBS billed back $70/mo.",
    "2 bed, $1,450/mo.\n- Typical electric $60\n- Water/sewer/trash RUBS $70/mo",
    HEAD + "Water, sewer and trash via RUBS about $70, typical electric $60.",
])
def test_typical_electric_next_to_rubs(text):
    check(text, 130, "electric, water, sewer, trash")


def test_lakeview_rubs_is_not_also_a_monthly_fee():
    r = check(LAKEVIEW, 195, "electric, gas, water, sewer, trash")
    assert r.get("other_monthly_fees") == 30


# no regression on figures that were right
@pytest.mark.parametrize("text,est", [
    (HEAD + "Water/sewer $55, electric roughly $90 total for electric and gas", 145),
    (HEAD + "Tenant pays electric about $60 a month.", 60),
    (HEAD + "Utilities included. Rent $1,450.", None),
    (HEAD + "HOA dues: $385 per month (covers water, trash, exterior).", None),
])
def test_no_regression(text, est):
    assert read(text).get("utilities_estimate") == est


# 6. noise
SYCAMORE = ("Sycamore Square 3BR/2BA townhouse $2,340/mo. Pet policy: 1 dog max, 40 lb limit. Fenced patio only. "
            "Resident responsible for all utilities (electric, gas, water, trash). Parking: 1 assigned space $40/mo. Security deposit $1,800.")


@pytest.mark.parametrize("text", [
    SYCAMORE,
    HEAD + "Tenant pays all utilities (electric, gas, water, trash).",
    "2 bed, $1,450/mo.\n- Resident responsible for all utilities (electric, gas, water, trash)\n- Parking $40/mo",
])
def test_all_utilities_with_a_list_in_brackets_is_only_that_list(text):
    r = read(text)
    assert r.get("tenant_pays") == "electric, gas, water, trash"


GROVE = ("The Grove at Neil - Studio & 1BR from $1,540\n1BR/1BA, 700 sf, in-unit washer/dryer, DW, built 2020. Parking included, optional garage $100/mo. "
         "Utilities: Tenant pays $55 electric, avg $70 gas. Water billed quarterly, about $96 per quarter. Trash passed through at $12/mo.\n"
         "Flat $75/mo fee covers trash, pest and valet. Second vehicle $40/mo. Address: 505 S Neil St, Champaign IL 61820. Lease start 9/1/2027, 12 months.")


def test_trash_charge_and_flat_fee_pick_one_and_note_the_other():
    r = read(GROVE)
    assert r["utilities_estimate"] == 157 and r["other_monthly_fees"] == 75
    n = notes(r)
    assert n.count("counted as your utilities estimate") == 1
    assert "flat fee already covers trash" in n


CEDAR = "Cedar Row apartments\n1 BR / 1 BA, 725 sf, $1,495\nUtilities - electric: $60; gas: $40; water billed quarterly ~ $90.\nGarage $75/mo."


@pytest.mark.parametrize("text", [
    CEDAR,
    HEAD + "Electric $60, gas $40, water billed quarterly ~$90.",
    "2 bed, $1,450/mo.\n- Electric $60\n- Gas $40\n- Water billed quarterly ~$90",
])
def test_electric_gas_and_quarterly_water_is_one_note(text):
    r = read(text)
    assert r["utilities_estimate"] == 130 and r["tenant_pays"] == "electric, gas, water"
    assert notes(r).count("utilities estimate") == 1


def test_electric_only_listing_never_says_missing_gas_or_internet():
    from prophelper.money import rent_cost
    t = "Campustown 1BR $1,400/mo. Landlord pays all utilities. Tenant electric only total $110 per month. Lease 12 months."
    r = read(t)
    r["listing_text"] = t
    cost = rent_cost(r)
    assert cost["missing"] == [] or "gas" not in " ".join(cost["missing"])
    assert "internet" not in " ".join(cost["missing"])


def test_figure_for_a_utility_named_in_another_sentence_is_left_to_the_older_readers():
    r = read(HEAD + "Heat is gas, tenant pays. Gas cooking, electric tenant. Budget around $90/mo for both. Water billed quarterly about $120.")
    assert r["utilities_estimate"] == 130


@pytest.mark.parametrize("text,est,pays,included", [
    (HEAD + "$210 for water and sewer every quarter", 70, "water, sewer", None),
    (HEAD + "Water/sewer billed every three months, about $210", 70, "water, sewer", None),
    (HEAD + "Water, sewer, trash $140 quarterly", 46.67, "water, sewer, trash", None),
    (HEAD + "Owner pays water & trash; tenant pays electric $60, gas $45", 105, "electric, gas", "water, trash"),
    ("2 bed, $1,450/mo.\nElectric: $50 (tenant)\nGas: $30 (tenant)\nWater: included", 80, "electric, gas", "water"),
    (HEAD + "Utilities: electric ~$65/mo, gas ~$40/mo, water paid by landlord.", 105, "electric, gas", "water"),
    (HEAD + "Landlord covers all utilities. Resident electric only, about $95 monthly.", 95, "electric", "gas, water, sewer, trash, heat"),
    (HEAD + "Electric and gas about $120 combined, water $90 per quarter", 150, "electric, gas, water", None),
])
def test_more_wordings(text, est, pays, included):
    check(text, est, pays, included)
