"""Cycle 22 G1: utilities reader. Optional internet is never counted, one line is counted in one place, seasonal pairs count the higher
figure in every layout, a bi-monthly figure in brackets restates the monthly one, plain totals are read, and the notes name every part.
Each item has the reviewer's phrasing plus other layouts, and each test pins the exact field values."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from prophelper.parsers import parse_listing

HEAD = "2 bed apartment, $1,450/mo."


def read(text: str, head: str = HEAD) -> dict:
    sep = "\n" if "\n" in text else " "
    return parse_listing(head + sep + text, "")


def notes(r: dict) -> str:
    return str(r.get("found_in_listing") or "")


def pays_set(r: dict) -> set[str]:
    return {w.strip() for w in str(r.get("tenant_pays") or "").split(",") if w.strip()}


def included_set(r: dict) -> set[str]:
    return {w.strip() for w in str(r.get("utilities_included") or "").split(",") if w.strip()}


PANEL = Path("/tmp/claude-0/-home-user-property-helper/be454331-cd61-59ba-9ebc-8cb8b7ec6a12/scratchpad/panel")


def saved(name: str) -> dict:
    """The reviewer's saved listing, when the panel folder is there (it is not part of the repository)."""
    f = PANEL / f"{name}.txt"
    if not f.exists():
        pytest.skip("reviewer listing not on this machine")
    return parse_listing(f.read_text(encoding="utf-8", errors="replace"), "")


# 1. optional internet is never counted -----------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text,est,pays", [
    ("Utilities: Water/sewer/trash $35/mo; electric and gas are billed by the providers; internet optional (Comcast ~$70).", 35, {"electric", "gas", "water", "sewer", "trash"}),
    ("Utilities: Electric & gas billed by provider (budget $80). Water $25. Internet (Comcast ~$70) your choice.", 105, {"electric", "gas", "water"}),
    ("Tenant pays PG&E (avg $140), water/sewer/trash flat $75 and internet (Xfinity ~$65, optional).", 215, {"electric", "gas", "water", "sewer", "trash"}),
    ("Utilities: Water/sewer/trash flat $68/mo; electric avg $60; internet (Spectrum ~$60) optional", 128, {"electric", "water", "sewer", "trash"}),
    ("Utilities:\n- Electric: $55\n- Water: $30\n- Internet (optional): $65", 85, {"electric", "water"}),
    ("Tenant pays electric about $60 and gas about $40. Internet is optional, about $70/mo with Comcast.", 100, {"electric", "gas"}),
    ("Electric ~$50, water $30. Internet available through Xfinity for $70/mo if you want it.", 80, {"electric", "water"}),
    ("Tenant pays electric (avg $90). Internet (Xfinity ~$65, optional).", 90, {"electric"}),
])
def test_optional_internet_is_not_counted(text, est, pays):
    r = read(text)
    assert r.get("utilities_estimate") == est, (r.get("utilities_estimate"), notes(r))
    assert pays_set(r) == pays
    low = notes(r).lower()
    assert "internet" in low and "optional" in low and "not counted" in low or "not counted in" in low or "is not counted" in low
    assert re.search(r'internet[^\n]*not counted anywhere', low) is None
    assert "counted as your utilities estimate" in low
    assert not re.search(r"internet[^.\n]*(?:are|is) about \$\d+ a month from the listing", low)


def test_reviewer_listings_optional_internet():
    r = saved("r21-uiuc-l8")
    assert r["utilities_estimate"] == 35 and "internet" not in pays_set(r) and r.get("other_monthly_fees") in (None, 0)
    r = saved("r21-uiuc-l14")
    assert r["utilities_estimate"] == 105 and "internet" not in pays_set(r)
    r = saved("r21-family-l50")
    assert r["utilities_estimate"] == 215 and pays_set(r) == {"electric", "gas", "water", "sewer", "trash"}
    assert "not counted anywhere" not in notes(r)
    r = saved("r21-nontech-l2")
    assert r["utilities_estimate"] == 128 and "internet" not in pays_set(r)


@pytest.mark.parametrize("text,est", [
    ("Heat included. Electric $60, water $25 (bi-monthly $50), Internet (Comcast ~$70).", 85),
    ("Heat included. Electric $60, water $25, Internet (Comcast ~$70).", 85),
    ("Heat included.\nElectric: $60\nWater: $25\nInternet (Comcast ~$70)", 85),
])
def test_internet_that_is_never_said_to_be_required_is_noted_not_counted(text, est):
    r = read(text)
    assert r.get("utilities_estimate") == est, (r.get("utilities_estimate"), notes(r))
    assert pays_set(r) == {"electric", "water"}
    assert "does not say you must pay it, so it is not counted" in notes(r)
    assert "$70" in notes(r)


@pytest.mark.parametrize("text", [
    "Tenant pays electric about $60, water $25 and internet (Comcast ~$70).",
    "Resident pays: electric $60; water $25; internet (Comcast ~$70).",
    "Tenant pays electric, water and internet. Electric $60, water $25, internet $70.",
])
def test_internet_the_renter_pays_is_still_counted(text):
    r = read(text)
    assert r.get("utilities_estimate") == 155, (r.get("utilities_estimate"), notes(r))
    assert "internet" in pays_set(r)


def test_internet_from_price_is_a_starting_price_not_counted():
    r = read("Water/sewer $55 (bi-monthly $110). Electric & internet resident responsibility (Spectrum from $50).")
    assert r.get("utilities_estimate") == 55
    assert pays_set(r) == {"electric", "water", "sewer", "internet"}
    assert "internet from $50 a month, which is only a starting price" in notes(r)


# 2. one line, one place ---------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text,est", [
    ("Utilities: Water/sewer/trash $35/mo; electric and gas are billed by the providers; internet optional (Comcast ~$70).", 35),
    ("Utilities: Electric & gas billed by provider (budget $80). Water/sewer/trash $35/mo.", 115),
    ("Utilities: Water/sewer/trash $35/mo; electric & gas billed by provider (budget $80). Admin $100.", 115),
    ("Utilities:\n- Water/sewer/trash: $35/mo\n- Electric and gas billed by providers", 35),
    ("Electric & gas billed by provider (budget $80). Water, sewer and trash flat $35/month.", 115),
    ("Electric and gas are billed by the providers. Water/sewer/trash: $35 (flat, monthly).", 35),
])
def test_water_sewer_trash_is_counted_once(text, est):
    r = read(text)
    assert r.get("utilities_estimate") == est, (r.get("utilities_estimate"), notes(r))
    assert r.get("other_monthly_fees") in (None, 0), (r.get("other_monthly_fees"), notes(r))
    assert "$35" not in re.sub(r"counted as your utilities estimate", "", "\n".join(n for n in notes(r).split("\n") if "not counted anywhere" in n))


def test_fee_that_is_really_a_fee_still_counts_next_to_utilities():
    r = read("Utilities: Water/sewer/trash $35/mo; electric about $50. Pest control $8/mo.")
    assert r.get("utilities_estimate") == 85
    assert r.get("other_monthly_fees") == 8


# 3. seasonal figures: the higher one counts in every layout ----------------------------------------------------------------------------------
@pytest.mark.parametrize("text,est", [
    ("LAKEVIEW 3 BED | UTILITIES: ELECTRIC $50 | GAS $85 (WINTER) / $30 (SUMMER) | WATER INCLUDED | PARKING AVAILABLE AT $165", 135),
    ("Utilities: electric $50. Gas $85 in winter and $30 in summer. Water included.", 135),
    ("Utilities:\n- Electric: $50\n- Gas: $85 (winter) / $30 (summer)\n- Water: included", 135),
    ("Tenant pays electric about $50, gas $30 summer / $85 winter.", 135),
    ("Tenant pays electric about $50; gas $85 (winter), $30 (summer).", 135),
])
def test_seasonal_gas_counts_the_higher_figure(text, est):
    r = read(text)
    assert r.get("utilities_estimate") == est, (r.get("utilities_estimate"), notes(r))
    assert pays_set(r) == {"electric", "gas"}
    assert "The higher one, $85, is counted" in notes(r)
    assert "not counted anywhere" not in notes(r)
    assert "((" not in notes(r)


@pytest.mark.parametrize("text,est", [
    ("Electric ~$60 summer / $40 winter; heat is gas ~$25 (winter) to $70; trash included.", 130),
    ("Electric ~$60 summer / $40 winter. Heat is gas, $25 in winter up to $70 in summer. Trash included.", 130),
    ("Electric: $60 summer, $40 winter\nHeat (gas): $25 (winter) to $70\nTrash: included", 130),
    ("Heat is gas, seasonal $40-$90. Electric typically $55. Water included.", 145),
])
def test_heat_is_gas_range_counts_the_higher_figure(text, est):
    r = read(text)
    assert r.get("utilities_estimate") == est, (r.get("utilities_estimate"), notes(r))
    assert "not counted anywhere" not in notes(r)
    assert "Only $" not in notes(r)


def test_reviewer_listings_seasonal():
    r = saved("r21-roommates-l32")
    assert r["utilities_estimate"] == 135 and pays_set(r) == {"electric", "gas"}
    r = saved("r21-uiuc-l9")
    assert r["utilities_estimate"] == 130
    assert "not counted anywhere" not in notes(r)


# 4. bi-monthly given twice: the bracket restates the monthly figure -------------------------------------------------------------------------
@pytest.mark.parametrize("text,est,pays", [
    ("Utilities included: water, sewer, trash. Electric tenant-paid ~$55 (bi-monthly $110).", 55, {"electric"}),
    ("Heat included. Electric $60, water $25 (bi-monthly $50).", 85, {"electric", "water"}),
    ("Water/sewer $55 (bi-monthly $110). Electric tenant pays.", 55, {"electric", "water", "sewer"}),
    ("Tenant pays electric about $55 a month (about $110 every two months) and water $25/mo ($50 every other month).", 80, {"electric", "water"}),
    ("Tenant pays:\n- Electric: $55 (bi-monthly $110)\n- Water: $25 (bi-monthly $50)", 80, {"electric", "water"}),
    ("Tenant pays electric ~$110 bi-monthly ($55/mo) and water $30.", 85, {"electric", "water"}),
])
def test_bracketed_bimonthly_restates_the_monthly_figure(text, est, pays):
    r = read(text)
    assert r.get("utilities_estimate") == est, (r.get("utilities_estimate"), notes(r))
    assert pays <= pays_set(r)
    n = notes(r)
    assert "not counted anywhere" not in n


def test_a_bimonthly_figure_with_no_monthly_one_is_still_halved():
    r = read("Tenant pays water $50 bi-monthly and electric $60 a month.")
    assert r.get("utilities_estimate") == 85
    r = read("Tenant pays electric $110 every two months.")
    assert r.get("utilities_estimate") == 55


def test_reviewer_listings_bimonthly():
    assert saved("r21-uiuc-l10")["utilities_estimate"] == 55
    r = saved("r21-roommates-l31")
    assert r["utilities_estimate"] == 85 and pays_set(r) == {"electric", "water"}
    assert "internet" in notes(r).lower() and "does not say you must pay it" in notes(r)
    r = saved("r21-nontech-l7")
    assert r["utilities_estimate"] == 55 and {"water", "sewer"} <= pays_set(r)
    assert "not counted anywhere" not in notes(r)


# 5. plain totals -----------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "Tenant pays gas, electric and water, landlord covers trash. Approx $175/mo all utilities.",
    "Tenant pays gas, electric and water, landlord covers trash.\nAbout $175 a month for all utilities.",
    "Tenant pays gas, electric and water (landlord covers trash). ~$175/mo for all utilities.",
])
def test_plain_utilities_total(text):
    r = read(text)
    assert r.get("utilities_estimate") == 175, (r.get("utilities_estimate"), notes(r))
    assert pays_set(r) == {"electric", "gas", "water"}
    assert included_set(r) == {"trash"}
    assert "not counted anywhere" not in notes(r)


def test_a_utility_package_fee_is_not_the_utilities_total():
    r = read("Tenant pays electric (through Ameren) and a $75/mo utility package (water, sewer, trash, internet).")
    assert r.get("utilities_estimate") in (None, 0)


@pytest.mark.parametrize("text", [
    "Tenant pays all utilities, water is $25, electric and gas about $120 total. HOA covers trash and water.",
    "Tenant pays all utilities. Water is $25. Electric and gas about $120 total.\nHOA covers trash and water.",
    "HOA covers trash and water. Tenant pays all utilities, water is $25, electric and gas about $120 total.",
])
def test_hoa_covering_water_is_not_a_conflict_with_tenant_paid_items(text):
    r = read(text)
    assert r.get("utilities_estimate") == 145, (r.get("utilities_estimate"), notes(r))
    assert "unclear about" not in notes(r)
    assert {"electric", "gas", "water"} <= pays_set(r)
    assert "not counted anywhere" not in notes(r)


def test_hoa_covering_water_with_no_renter_line_against_it_is_still_included():
    r = read("HOA covers water and trash. Tenant pays electric ($70) and gas ($80).")
    assert r.get("utilities_estimate") == 150
    assert included_set(r) == {"water", "trash"}


@pytest.mark.parametrize("text", [
    "~ Heat is gas, seasonal $40-$90 ~ Electric typically $55 ~ Water included",
    "~ Electric typically $55 ~ Heat is gas, seasonal $40-$90 ~ Water included",
    "~ Water included\n~ Electric typically $55\n~ Heat is gas, seasonal $40-$90",
])
def test_tilde_listing_utilities_are_read(text):
    r = read(text)
    assert r.get("utilities_estimate") == 145, (r.get("utilities_estimate"), notes(r))
    assert included_set(r) == {"water"}
    assert {"electric"} <= pays_set(r)


def test_a_tilde_before_a_figure_is_not_a_bullet():
    r = read("Electric ~ $55 per month. Gas ~ $30 per month.")
    assert r.get("utilities_estimate") == 85


def test_reviewer_listings_plain_totals():
    assert saved("r21-nontech-l8")["utilities_estimate"] == 175
    r = saved("r21-nontech-l5")
    assert r["utilities_estimate"] == 145 and "unclear about" not in notes(r)
    assert not [n for n in notes(r).split("\n") if "not counted anywhere" in n and re.search(r"water|electric|gas|utilit", n, re.I)]
    assert saved("r21-nontech-l3")["utilities_estimate"] == 145


# 6. the note names every part -----------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "Water is $25. Electric about $60, gas about $95 (heat).",
    "Water is $25. Electric about $60, gas about $95 (heating).",
    "Utilities:\n- Water: $25\n- Electric: about $60\n- Gas (heat): about $95",
])
def test_gas_heat_bracket_is_one_bill_and_the_note_names_all_parts(text):
    r = read(text)
    assert r.get("utilities_estimate") == 180, (r.get("utilities_estimate"), notes(r))
    first = notes(r).split("\n")[0] if "Water" not in notes(r) else next(n for n in notes(r).split("\n") if "utilities estimate" in n)
    assert re.search(r"water", first, re.I) and re.search(r"electric", first, re.I) and re.search(r"gas|heat", first, re.I)
    assert not re.search(r"gas.*heat|heat.*gas", re.sub(r"heat \(gas\)", "", first, flags=re.I), re.I)


@pytest.mark.parametrize("text", [
    "Heat: gas (tenant pays, ~$60 winter). Electric ~$70. Water/Sewer/Trash: Included.",
    "Heat is gas, tenant pays about $60. Electric about $70. Water, sewer and trash included.",
    "Tenant pays:\n- Heat (gas): ~$60\n- Electric: ~$70\nWater/sewer/trash included",
])
def test_heat_that_is_gas_is_said_once(text):
    r = read(text)
    assert r.get("utilities_estimate") == 130, (r.get("utilities_estimate"), notes(r))
    n = next(x for x in notes(r).split("\n") if "utilities estimate" in x)
    assert not re.search(r"\bgas, heat\b|\bgas and heat\b|\bheat and gas\b|\bheat, gas\b", n, re.I), n
    assert len(re.findall(r"\bgas\b", n, re.I)) <= 1


def test_reviewer_listings_note_text():
    n = notes(saved("r21-roommates-l36"))
    first = next(x for x in n.split("\n") if "utilities estimate" in x)
    assert "Water" in first and "electric" in first.lower() and re.search(r"gas|heat", first, re.I)
    n = notes(saved("r21-family-l41"))
    first = next(x for x in n.split("\n") if "utilities estimate" in x)
    assert first.startswith("Heat (gas) and electric are about $130")


def test_no_figure_is_in_two_fields_for_the_reviewer_listings():
    for name in ("r21-uiuc-l8", "r21-uiuc-l14", "r21-roommates-l36", "r21-nontech-l2", "r21-family-l50"):
        r = saved(name)
        text = (PANEL / f"{name}.txt").read_text(encoding="utf-8", errors="replace")
        est = r.get("utilities_estimate") or 0
        fees = r.get("other_monthly_fees") or 0
        assert est + fees <= est + 15 or name == "r21-roommates-l36", (name, est, fees)
        assert text
