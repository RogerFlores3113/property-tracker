"""Cycle 19 G1: the general utility item reader reads dashes, payer words, "every 3 months" and bi-monthly wording, parentheses,
seasonal figures, pipe lists, one figure after a list of names, and "included in rent" lists. Each item has the reviewer's
phrasing plus other layouts (commas, dashes, bullets, pipes, separate lines)."""
from __future__ import annotations

import pytest

from prophelper.parsers import parse_listing

HEAD = "2 bed apartment, $1,450/mo."


def read(text: str) -> dict:
    sep = "\n" if "\n" in text else " "
    return parse_listing(HEAD + sep + text, "")


def notes(r: dict) -> str:
    return str(r.get("found_in_listing") or "")


def check(text: str, est, pays, included=None, r=None) -> dict:
    r = r or read(text)
    assert r.get("utilities_estimate") == est, (text, r.get("utilities_estimate"), notes(r))
    assert r.get("tenant_pays") == pays, (text, r.get("tenant_pays"))
    if included is not None:
        assert r.get("utilities_included") == (included or None), (text, r.get("utilities_included"))
    return r


def no_false_not_counted(r: dict) -> None:
    assert "not counted anywhere" not in notes(r), notes(r)
    assert "missing" not in notes(r).lower()


# 1. dash layout: "Electric - tenant (about $45), Gas - tenant (about $28), ..." all four count ----------------------------------
ALL4 = "electric, gas, water, sewer, trash, internet"


@pytest.mark.parametrize("text", [
    "Electric - tenant (about $45), Gas - tenant (about $28), Water/Sewer/Trash - flat $42 per month, Internet - tenant $50",
    "Utilities: Electric - tenant $45 | Gas - tenant $28 | Water/Sewer/Trash - flat $42 per month | Internet - tenant $50",
    "- Electric - tenant (about $45)\n- Gas - tenant (about $28)\n- Water/Sewer/Trash - flat $42 per month\n- Internet - tenant $50",
    "Electric tenant about $45, gas tenant about $28, water/sewer/trash flat $42 per month, internet tenant $50",
])
def test_dash_layout_all_four_count(text):
    r = check(text, 165, ALL4)
    no_false_not_counted(r)


def test_dash_layout_two_items():
    check("Electric - tenant (about $45) - Gas - tenant (about $28)", 73, "electric, gas")


def test_lantern_whole_listing():
    r = parse_listing(open_listing("r18-uiuc-l9"), "") if listing_exists("r18-uiuc-l9") else read(
        "Utilities: Electric - tenant (about $45), Gas - tenant (about $28), Water/Sewer/Trash - flat $42 per month, Internet - tenant $50.\nSecurity deposit $500.")
    assert r["utilities_estimate"] == 165
    assert "electric" in r["tenant_pays"]
    assert "$28, $42" not in notes(r) and "Only $28" not in notes(r)


# 2. bulleted lines with a payer word between the name and the amount ------------------------------------------------------------
@pytest.mark.parametrize("text, est, pays", [
    ("* Gas heat - tenant pays about $40/mo\n* Trash & sewer: $65 monthly\n* Internet $50", 155, "gas, sewer, trash, internet"),
    ("* Gas heat - tenant pays about $40/mo\n* Water $30/mo", 70, "gas, water"),
    ("Gas heat, tenant pays about $40/mo, water $30/mo", 70, "gas, water"),
    ("Gas heat: tenant pays about $40/mo. Water $30/mo.", 70, "gas, water"),
    ("Gas heat (tenant pays about $40/mo), water (tenant pays $30/mo)", 70, "gas, water"),
])
def test_payer_word_between_name_and_amount(text, est, pays):
    r = check(text, est, pays)
    no_false_not_counted(r)


# 3. "every 3 months" and bi-monthly ------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text, est, pays, shown", [
    ("Electric every 3 months about $90 (quarterly)", 30, "electric", "$90 per quarter"),
    ("Electric about $90 every 3 months, gas about $40/mo", 70, "electric, gas", "$90 per quarter"),
    ("Electric: about $90 every three months. Gas: $40 a month.", 70, "electric, gas", "$90 per quarter"),
    ("Every 3 months the water bill averages $210", 70, "water", "$210 per quarter"),
    ("Water bill averages $210 every 3 months, electric $60/mo", 130, "electric, water", "$210 per quarter"),
    ("Utilities: every 3 months the water bill averages $210, electric $60 a month", 130, "electric, water", "$210 per quarter"),
    ("Tenant pays $210 every 3 months for water", 70, "water", "$210 per quarter"),
    ("Water $75 quarterly", 25, "water", "$75 per quarter"),
    ("Water: $75 quarterly. Electric $50/mo.", 75, "electric, water", "$75 per quarter"),
])
def test_every_three_months(text, est, pays, shown):
    r = check(text, est, pays)
    assert shown in notes(r), notes(r)
    no_false_not_counted(r)


@pytest.mark.parametrize("text, est, pays", [
    ("Tenant pays electric ($65/month) and water-sewer ($70 bi-monthly)", 100, "electric, water, sewer"),
    ("Water-sewer: $70 bi-monthly. Electric $50 a month.", 85, "electric, water, sewer"),
    ("Water/sewer bi-monthly $70, gas $30", 65, "gas, water, sewer"),
    ("Water-sewer ($70 bi-monthly)", 35, "water, sewer"),
])
def test_bimonthly_is_every_two_months(text, est, pays):
    r = check(text, est, pays)
    assert "ater and sewer $70 per two months" in notes(r), notes(r)  # the note names water, not "Electric and sewer"
    assert "$70 per two months" in notes(r)
    no_false_not_counted(r)


# 4. parenthetical and approximate amounts, seasonal figures -----------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "Electric (~$90), gas (~$110 winter, $30 summer)",
    "Electric ~$90, gas ~$110 in winter and ~$30 in summer",
    "Electric: $90. Gas: $110 winter / $30 summer.",
    "Electric $90/mo, gas up to $110 in the winter, about $30 in the summer.",
])
def test_seasonal_figures_count_the_higher_and_say_both(text):
    r = check(text, 200, "electric, gas")
    n = notes(r)
    assert "$110" in n and "$30" in n and "higher one, $110, is counted" in n, n
    assert "not counted anywhere" not in n


@pytest.mark.parametrize("text", [
    "Electric is paid separately by residents (est. $58)",
    "Residents pay electric separately, est. $58.",
    "Electric (paid separately by residents): est $58",
    "Electric separately - est. $58",
])
def test_estimate_in_parentheses(text):
    r = check(text, 58, "electric")
    assert '"$58)"' not in notes(r) and "not counted" not in notes(r), notes(r)


def test_pullman_whole_listing():
    r = read("Pullman 3BR 2BA rent $2,200, 11100 S Langley Ave Chicago, security deposit equal to 1 month, tenant pays electric (~$90), gas (~$110 winter, $30 summer). Pets: cats only.")
    check("", 200, "electric, gas", r=r)
    assert "higher one, $110" in notes(r)


# 5. two figures for different utilities both count ---------------------------------------------------------------------------------
@pytest.mark.parametrize("text, pays", [
    ("PG&E (about $80), gas about $30", "electric, gas"),
    ("Tenant pays PG&E about $80 a month, plus gas about $30 a month.", "electric, gas"),
    ("Electric - about $80 | Gas - about $30", "electric, gas"),
    ("Electric: about $80\nGas: about $30", "electric, gas"),
    ("Gas about $30, PG&E about $80", "electric, gas"),
])
def test_different_utilities_both_count(text, pays):
    r = check(text, 110, pays)
    assert "Only the figure" not in notes(r) and "higher" not in notes(r), notes(r)


def test_provider_alone_still_means_electric_and_gas():
    check("Tenant pays PG&E about $110 for electric and gas", 110, "electric, gas")
    check("Tenant pays PG&E (about $80)", 80, "electric, gas")


# 6. pipe lists and separate lines ------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "Gas: $60 | Electric: $55 | Internet: $65",
    "Gas $60, electric $55, internet $65",
    "Gas: $60\nElectric: $55\nInternet: $65",
    "- Gas $60\n- Electric $55\n- Internet $65",
])
def test_internet_stays_in_the_list(text):
    r = check(text, 180, "electric, gas, internet")
    no_false_not_counted(r)


@pytest.mark.parametrize("text", [
    "UTILITIES: ELECTRIC $45 | GAS $60 | WATER $35 | TRASH INCL",
    "Utilities: Electric $45 / Gas $60 / Water $35 / Trash included",
])
def test_all_caps_pipe_list_has_no_false_note(text):
    r = check(text, 140, "electric, gas, water", "trash")
    assert "Only $45" not in notes(r) and "not counted" not in notes(r), notes(r)


def test_address_pipe_does_not_make_a_list():
    r = parse_listing("Sunrise Flats\n1 BR $1,575 /mo\nTenant pays electric about $60 a month. Internet $65.\n1010 W Main St Apt 204 | URBANA, IL 61801", "")
    assert r["utilities_estimate"] == 60


# 7. one figure after a list of names ------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "Tenant: electric, gas, water, internet ($60)",
    "Tenant pays electric, gas, water and internet ($60)",
    "Tenant: electric, gas, water, internet - $60",
])
def test_one_figure_after_several_names_counts_for_the_last(text):
    r = check(text, 60, "electric, gas, water, internet")
    n = notes(r)
    assert "counted for internet only" in n, n
    assert "Electric, gas and water are listed as something you pay, with no amount" in n, n
    assert "Electric, gas, water and internet are about $60" not in n


@pytest.mark.parametrize("text", [
    "Tenant: electric, gas, water, internet ($60 total)",
    "Tenant: electric, gas, water, internet, about $60 a month total",
    "Tenant pays electric, gas, water and internet, $60 combined",
])
def test_a_stated_total_still_covers_all(text):
    r = check(text, 60, "electric, gas, water, internet")
    assert "counted for internet only" not in notes(r)


@pytest.mark.parametrize("text, est, pays, inc", [
    ("Landlord pays all utilities, tenant electric only total $110.", 110, "electric", "gas, water, sewer, trash, heat"),
    ("Landlord pays all utilities. Tenant electric only total $110", 110, "electric", "gas, water, sewer, trash, heat"),
    ("Tenant electric only total $110", 110, "electric", None),
])
def test_electric_only_total_unchanged(text, est, pays, inc):
    check(text, est, pays, inc)


def test_tenant_total_line_unchanged():
    r = read("Tenant total $90")
    assert r.get("utilities_estimate") is None


def test_water_sewer_trash_bundle_unchanged():
    r = check("Water, sewer, trash $65/month", 65, "water, sewer, trash")
    assert "counted for" not in notes(r)


# 8. "included in rent" lists ----------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "Utilities included in rent: heat, gas, water. Electric not included.",
    "Included in rent: heat, gas, water. Electric not included.",
    "Heat, gas and water are included in the rent. Electric is not included.",
    "Included: heat, gas, water. Not included: electric.",
])
def test_included_list_and_electric_separate_is_no_conflict(text):
    r = check(text, None, "electric", "heat, gas, water")
    assert "unclear" not in notes(r) and "don't agree" not in notes(r) and "but it also says" not in notes(r), notes(r)


# 9. Quarry Heights: electric and gas priced, RUBS counted once ------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "- Utilities: electric $60, gas $35 (resident pays)\n- Water/sewer/trash flat $30/mo RUBS",
    "Utilities: electric $60, gas $35 (resident pays). Water/sewer/trash flat $30/mo RUBS.",
    "- Electric $60 (resident pays)\n- Gas $35 (resident pays)\n- Water/sewer/trash flat $30/mo RUBS",
])
def test_quarry_gas_is_counted_and_not_called_missing(text):
    r = check(text, 125, "electric, gas, water, sewer, trash")
    assert "Only $35" not in notes(r) and "not counted" not in notes(r), notes(r)


# the reviewers' saved listings (skipped when the panel folder is not on this machine) --------------------------------------------------
PANEL = "/tmp/claude-0/-home-user-property-helper/be454331-cd61-59ba-9ebc-8cb8b7ec6a12/scratchpad/panel"


def listing_exists(name: str) -> bool:
    import os
    return os.path.exists(f"{PANEL}/{name}.txt")


def open_listing(name: str) -> str:
    with open(f"{PANEL}/{name}.txt") as f:
        return f.read()


@pytest.mark.skipif(not listing_exists("r18-roommates-l14"), reason="panel listings not on this machine")
@pytest.mark.parametrize("name, est", [
    ("r18-roommates-l14", 180), ("r18-roommates-l22", 140), ("r18-uiuc-l5", 125), ("r18-uiuc-l9", 165),
    ("r18-roommates-l13", 70), ("r18-uiuc-l17", 58), ("r18-family-l17", 175), ("r18-nontech-l4", 155), ("r18-roommates-l25", 200),
])
def test_saved_listings(name, est):
    r = parse_listing(open_listing(name), "")
    assert r["utilities_estimate"] == est, (name, notes(r))
    n = notes(r)
    assert "Only $35" not in n and "Only $45" not in n and '"$58)"' not in n
    assert "Only $28" not in n and "Only $42" not in n and "Only $50" not in n
