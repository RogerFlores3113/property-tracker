"""Cycle 35 group G1: utilities reader.
(1) Spanish "luz y gas" and Spanish pay words, also inside an English sentence (rule hh: roommates l3, family l3, nontech l5).
(2) "tenant pays electric and gas, water sewer trash are covered by landlord" (uiuc l27).
(3) "water/sewer/trash via RUBS about $70, electric/internet tenant" (nontech l4).
(4) "Quarterly water/sewer bill split evenly" (roommates l7).
(5) "typical total bills $140" next to billed-back items (roommates l8)."""
import os

import pytest

from prophelper.parsers import parse_listing

HEAD = "Rent $1,800. 2 bed 1 bath. "
FIVE = {"electric", "gas", "water", "sewer", "trash"}


def P(text):
    return parse_listing(text, "")


def notes(r):
    return r.get("found_in_listing") or ""


def _set(v):
    return {w.strip() for w in (v or "").split(",") if w.strip()}


def saved(name):
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel")
    return open(os.path.join(base, name + ".txt"), encoding="utf-8").read()


# ---- 1. luz y gas
LUZ_GAS = [
    "Tenant pays luz y gas.",
    "Tenant pays luz y gas. Agua incluida.",
    "Tenant pays: luz, gas.",
    "Utilities: tenant pays luz y gas; water included.",
    "Luz y gas por cuenta del inquilino. Agua incluida.",
    "Luz y gas por el inquilino.",
    "Luz y gas a cargo del inquilino.",
    "Agua incluida; luz y gas por el inquilino.",
    "Tenant pays:\n- luz\n- gas",
    "Tenant pays\nluz y gas",
    "Renter pays luz / gas.",
]


@pytest.mark.parametrize("body", LUZ_GAS)
def test_luz_y_gas_are_both_on_the_pay_list(body):
    r = P(HEAD + body)
    assert _set(r["tenant_pays"]) == {"electric", "gas"}, (r.get("tenant_pays"), notes(r))
    assert not (_set(r.get("utilities_included")) & {"electric", "gas"})


def test_luz_y_gas_keeps_water_and_trash_included():
    r = P(HEAD + "Tenant pays luz y gas, water and trash included.")
    assert _set(r["tenant_pays"]) == {"electric", "gas"}
    assert _set(r["utilities_included"]) == {"water", "trash"}


def test_landlord_pays_luz_y_gas_in_spanish():
    r = P(HEAD + "Luz y gas por cuenta del propietario. Agua por el inquilino.")
    assert _set(r["utilities_included"]) == {"electric", "gas"}
    assert _set(r["tenant_pays"]) == {"water"}


@pytest.mark.parametrize("name,inc,pays", [
    ("r34-roommates-l3", {"water"}, {"electric", "gas"}),
    ("r34-family-l3", set(), {"electric", "gas"}),
    ("r34-nontech-l5", {"water", "trash"}, {"electric", "gas"}),
])
def test_reviewer_listings_luz(name, inc, pays):
    r = P(saved(name))
    assert _set(r.get("utilities_included")) == inc
    assert _set(r.get("tenant_pays")) == pays


def test_luz_natural_is_not_electric():
    r = P(HEAD + "Mucha luz natural. Tenant pays gas.")
    assert _set(r["tenant_pays"]) == {"gas"}


def test_negative_english_listing_is_unchanged():
    r = P(HEAD + "Tenant pays gas. Water included.")
    assert _set(r["tenant_pays"]) == {"gas"}
    assert _set(r["utilities_included"]) == {"water"}


# ---- 2. the landlord's clause after a pay list
LL_TAIL = [
    "Utilities: tenant pays electric and gas, water sewer trash are covered by landlord.",
    "Tenant pays electric and gas, water sewer trash are paid by landlord.",
    "Tenant pays electric and gas; water sewer trash covered by the owner.",
    "Tenant pays electric and gas. Water sewer trash included by landlord.",
    "Water sewer trash are covered by landlord. Tenant pays electric and gas.",
    "Tenant pays electric and gas, water, sewer, trash paid by landlord.",
    "Tenant pays electric and gas (water sewer trash covered by the owner).",
    "Tenant pays electric and gas - water sewer trash included by the landlord.",
    "Water sewer trash paid by owner, tenant pays electric and gas.",
    "Tenant pays electric and gas,\nwater sewer trash covered by landlord.",
]


@pytest.mark.parametrize("body", LL_TAIL)
def test_landlord_clause_keeps_water_sewer_trash_off_the_pay_list(body):
    r = P(HEAD + body)
    assert _set(r["tenant_pays"]) == {"electric", "gas"}, (r.get("tenant_pays"), notes(r))
    assert _set(r["utilities_included"]) == {"water", "sewer", "trash"}
    assert "unclear" not in notes(r)


def test_landlord_clause_with_internet_after_it():
    r = P(HEAD + "Tenant pays electric and gas, water sewer trash covered by landlord, internet by tenant.")
    assert _set(r["tenant_pays"]) == {"electric", "gas", "internet"}
    assert _set(r["utilities_included"]) == {"water", "sewer", "trash"}


def test_reviewer_listing_uiuc_l27():
    r = P(saved("r34-uiuc-l27"))
    assert _set(r["tenant_pays"]) == {"electric", "gas"}
    assert _set(r["utilities_included"]) == {"water", "sewer", "trash"}
    assert r["utilities_estimate"] == 80
    assert "unclear" not in notes(r)


@pytest.mark.parametrize("body", [
    "Tenant pays electric and gas. Is water covered by landlord?",
    "Tenant pays electric and gas, is water covered by landlord?",
])
def test_a_question_about_the_landlord_sets_nothing(body):
    r = P(HEAD + body)
    assert _set(r["tenant_pays"]) == {"electric", "gas"}
    assert not r.get("utilities_included")


def test_conditional_landlord_clause_is_not_a_plain_included():
    r = P(HEAD + "Tenant pays electric and gas, water sewer trash covered by landlord if you sign by Dec 1.")
    assert not r.get("utilities_included")


def test_not_covered_by_landlord_stays_on_the_pay_list():
    r = P(HEAD + "Tenant pays electric, gas, water not covered by landlord.")
    assert _set(r["tenant_pays"]) == {"electric", "gas", "water"}
    assert not r.get("utilities_included")


# ---- 3. a billed-back group keeps its own figure
RUBS = [
    "Trash/pest $15/mo, water/sewer/trash via RUBS about $70, electric/internet tenant.",
    "Water/sewer/trash via RUBS about $70; electric/internet tenant.",
    "Water, sewer and trash billed through RUBS, about $70/mo. Electric and internet are tenant.",
    "Electric/internet tenant. Water/sewer/trash via RUBS about $70.",
    "Utilities: water/sewer/trash via RUBS (about $70), electric/internet tenant paid.",
    "Water/sewer/trash RUBS ~$70/mo - electric and internet paid by tenant.",
    "Water/sewer/trash via Conservice about $70 a month, tenant pays electric/internet.",
    "Water/sewer/trash via RUBS about $70\nElectric/internet tenant",
]


@pytest.mark.parametrize("body", RUBS)
def test_rubs_figure_belongs_to_water_sewer_trash(body):
    r = P("Rent $1,299. " + body)
    assert _set(r["tenant_pays"]) == {"electric", "water", "sewer", "trash", "internet"}, (r.get("tenant_pays"), notes(r))
    assert r["utilities_estimate"] == 70
    low = notes(r).lower()
    assert "electric and internet are about $70" not in low
    assert "internet are about" not in low


def test_rubs_group_alone_after_a_fee():
    r = P("Rent $1,299. Pest $15/mo, water/sewer/trash via RUBS about $70")
    assert _set(r["tenant_pays"]) == {"water", "sewer", "trash"}
    assert r["utilities_estimate"] == 70


def test_reviewer_listing_nontech_l4():
    r = P(saved("r34-nontech-l4"))
    assert _set(r["tenant_pays"]) == {"electric", "water", "sewer", "trash", "internet"}
    assert r["utilities_estimate"] == 70
    assert "Electric and internet are about $70" not in notes(r)


def test_negative_one_figure_for_electric_after_a_plain_water_line():
    r = P("Rent $1,299. Water/sewer/trash included, electric/internet tenant about $90.")
    assert _set(r["utilities_included"]) == {"water", "sewer", "trash"}
    assert _set(r["tenant_pays"]) == {"electric", "internet"}
    assert r["utilities_estimate"] == 90


def test_negative_flat_fee_for_three_utilities_is_unchanged():
    r = P("Rent $1,299. Tenant pays electric. Water/sewer/trash flat $55/mo.")
    assert r["utilities_estimate"] == 55
    assert "electric" in _set(r["tenant_pays"])


# ---- 4. a quarterly bill the tenants split
QUARTERLY = [
    "Quarterly water/sewer bill split evenly among tenants. Electric via ComEd. Gas included.",
    "Tenants split the quarterly water/sewer bill. Electric via ComEd. Gas included.",
    "Electric via ComEd. Gas included.\nWater/sewer: quarterly bill, split evenly",
    "Gas included. Electric via ComEd; quarterly water/sewer bill shared by the roommates.",
    "Quarterly water & sewer bill, split evenly. Electric via ComEd. Gas included.",
    "Electric via ComEd. Gas included. Tenants share the quarterly water and sewer bill.",
]


@pytest.mark.parametrize("body", QUARTERLY)
def test_quarterly_split_bill_is_a_billed_utility(body):
    r = P("Rent $3,600. " + body)
    assert _set(r["tenant_pays"]) == {"electric", "water", "sewer"}, (r.get("tenant_pays"), notes(r))
    assert _set(r["utilities_included"]) == {"gas"}
    assert not r.get("utilities_estimate")
    assert "quarterly bill that the tenants share, but gives no amount" in notes(r)
    assert "not counted" not in notes(r).split("quarterly bill")[1].split("\n")[0]


def test_quarterly_bill_with_a_figure_is_a_third_per_month():
    r = P("Rent $3,600. Quarterly water/sewer bill $240, split evenly among tenants. Electric via ComEd. Gas included.")
    assert r["utilities_estimate"] == 80
    assert _set(r["tenant_pays"]) == {"electric", "water", "sewer"}
    assert "gives no amount" not in notes(r)


def test_reviewer_listing_roommates_l7():
    r = P(saved("r34-roommates-l7"))
    assert _set(r["tenant_pays"]) == {"electric", "water", "sewer"}
    assert _set(r["utilities_included"]) == {"gas"}
    assert "water and sewer are a quarterly bill" in notes(r)


def test_negative_quarterly_bill_that_is_included_is_not_a_pay_item():
    r = P("Rent $3,600. Water/sewer included. Quarterly pest control bill. Gas included. Electric tenant.")
    assert _set(r["tenant_pays"]) == {"electric"}
    assert _set(r["utilities_included"]) == {"gas", "water", "sewer"}


def test_negative_landlord_pays_the_quarterly_water_bill():
    r = P("Rent $3,600. Landlord pays the quarterly water bill. Tenant pays electric.")
    assert _set(r["tenant_pays"]) == {"electric"}


def test_negative_landlord_list_after_a_label_keeps_its_first_item():
    r = P(HEAD + "Utilities: water, sewer and trash covered by owner; electric & gas paid by resident, est. $100.")
    assert r["utilities_included"] == "water, sewer, trash"
    assert r["tenant_pays"] == "electric, gas"
    assert r["utilities_estimate"] == 100


# ---- 5. a typical total next to billed-back utilities
BILLED_TYPICAL = [
    "Utilities Billed Back: Gas, Water, Sewer. Resident pays electric. Typical total bills $140.",
    "Gas, water and sewer are billed back. Resident pays electric. Typical total bills $140.",
    "Utilities billed back (gas, water, sewer). Resident pays electric. Typical total bills $140.",
    "Utilities Billed Back: Gas, Water, Sewer. Resident pays electric. Typical bills for the unit $140.",
    "Resident pays electric. Gas, water, sewer billed back via RUBS. Typical total bills $140.",
    "Utilities billed back: gas, water, sewer.\nResident pays electric.\nTypical total bills $140.",
]


@pytest.mark.parametrize("body", BILLED_TYPICAL)
def test_typical_total_next_to_billed_back_keeps_the_cost_incomplete(body):
    from prophelper import money
    text = "Rent $2,880. " + body
    r = P(text)
    assert _set(r["tenant_pays"]) == {"electric", "gas", "water", "sewer"}, (r.get("tenant_pays"), notes(r))
    assert r["utilities_estimate"] == 140
    assert "Gas, water and sewer are listed as something you pay, with no amount" in notes(r)
    assert "for all the utilities you pay" not in notes(r)
    place = dict(r, listing_text=text, reader_notes=notes(r), status="saved")
    assert money.rent_cost(place)["missing"] == ["gas, water and sewer"]


def test_reviewer_listing_roommates_l8():
    from prophelper import money
    text = saved("r34-roommates-l8")
    r = P(text)
    assert _set(r["tenant_pays"]) == {"electric", "gas", "water", "sewer"}
    assert r["utilities_estimate"] == 140
    assert "does not say if that includes gas, water and sewer" in notes(r)
    place = dict(r, listing_text=text, reader_notes=notes(r), status="saved")
    assert "gas, water and sewer" in money.rent_cost(place)["missing"]


def test_negative_typical_total_with_every_utility_on_one_pay_line_is_plain():
    r = P("Rent $2,880. Resident pays electric, gas, water, sewer. Typical total bills $140.")
    assert r["utilities_estimate"] == 140
    assert "listed as something you pay" not in notes(r)


def test_negative_total_utilities_figure_covers_all():
    r = P("Rent $2,880. Resident pays electric. Gas, water, sewer billed back via RUBS. Total utilities about $140.")
    assert r["utilities_estimate"] == 140
    assert "listed as something you pay, with no amount" not in notes(r)


def test_negative_billed_amount_plus_typical_figure_stay_added():
    r = P("Rent $2,880. Gas, water, sewer billed back at $90/mo. Resident pays electric. Typical total bills $140.")
    assert r["utilities_estimate"] == 230


def test_negative_billed_back_header_with_a_flat_figure_is_left_to_the_flat_reader():
    r = P(HEAD + "Utilities billed back: water/sewer/trash $75 flat; electric & gas direct with utility providers.")
    assert "gives no amount" not in notes(r)
    assert r.get("other_monthly_fees") == 75 or r.get("utilities_estimate") == 75
