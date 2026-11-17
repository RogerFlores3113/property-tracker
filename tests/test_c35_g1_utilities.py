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
