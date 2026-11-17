"""Cycle 34 group G1: utilities reader.
(1) "is on us", "on the house", "we cover", "owner pays" clauses never go on the tenant pay list, and "~$90 for the elec+gas" is counted (uiuc l18).
(2) "Pay list: electric; gas; water; sewer; trash. Gas for cooking only." keeps all five (roommates l11).
(3) "Water, sewer & trash billed back by Conservice approximately $60/month; tenant pays electric; gas for cooking" counts the $60, no overlap note (uiuc l22).
(4) a "typical bills $95" figure is never called "billed back (RUBS)" (roommates l16).
(5) Spanish "luz y gas", "agua incluida" are read (nontech l25)."""
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


# ---- 1. landlord idioms
ON_US = [
    "util: you pay elec + gas, water/sewer/trash is on us. figure ~$90 a month for the elec+gas",
    "Utilities: you pay electric and gas; water, sewer and trash are on us. Figure about $90/month for electric and gas.",
    "Water/sewer/trash is on the house. You pay elec + gas, roughly $90 a month for those.",
    "We cover water, sewer and trash. Tenant pays electric and gas, ~$90/mo.",
    "Owner pays water/sewer/trash; tenant pays electric + gas, about $90 a month for electric and gas.",
    "you pay elec + gas. water, sewer & trash is on us. about $90 for the elec+gas",
    "Electric + gas: you pay, about $90 a month. Water/sewer/trash we cover.",
    "Tenant pays electric and gas. Water, sewer and trash are covered by the landlord. Typical $90.",
    "Water, sewer, trash: on us.\nTenant pays electric and gas, typical bills $90 per month.",
]


@pytest.mark.parametrize("body", ON_US)
def test_landlord_clause_stays_off_the_pay_list(body):
    r = P(HEAD + body)
    assert _set(r["tenant_pays"]) == {"electric", "gas"}, r.get("tenant_pays")
    assert _set(r["utilities_included"]) == {"water", "sewer", "trash"}, r.get("utilities_included")
    assert r["utilities_estimate"] == 90, notes(r)
    assert "not counted anywhere" not in notes(r)


def test_reviewer_listing_uiuc_l18():
    r = P(saved("r33-uiuc-l18"))
    assert _set(r["tenant_pays"]) == {"electric", "gas"}
    assert _set(r["utilities_included"]) == {"water", "sewer", "trash"}
    assert r["utilities_estimate"] == 90
    assert r["parking_cost"] == 110 and r["pets"] == "cats"
    assert "not counted anywhere" not in notes(r)


LAYOUTS = [
    "util: you pay elec + gas | water/sewer/trash is on us | ~$90/mo for elec+gas",
    "Utilities:\n- you pay elec + gas\n- water/sewer/trash is on us\n- figure ~$90/mo for the elec+gas",
    "* you pay elec + gas\n* water/sewer/trash on us\n* figure ~$90/mo for the elec+gas",
    "UTIL: YOU PAY ELEC + GAS, WATER/SEWER/TRASH IS ON US. FIGURE ~$90 A MONTH FOR THE ELEC+GAS",
    "util: you pay elec + gas; water/sewer/trash is on us; figure ~$90 a month for elec + gas",
    "Water/sewer/trash is on us, you pay the electric and gas (figure ~$90 a month for both)",
    "you pay elec + gas, water/sewer/trash on the house. figure ~$90 a month for the elec+gas",
    "utilities: elec + gas are on you, water/sewer/trash on us, figure ~$90 for elec+gas",
]


@pytest.mark.parametrize("body", LAYOUTS)
def test_landlord_clause_in_other_layouts(body):
    r = P(HEAD + body)
    assert _set(r["tenant_pays"]) == {"electric", "gas"}, r.get("tenant_pays")
    assert _set(r["utilities_included"]) == {"water", "sewer", "trash"}
    assert r["utilities_estimate"] == 90, notes(r)
    assert "unclear" not in notes(r)


def test_on_us_without_any_pay_line_is_included_only():
    for body in ("Water/sewer/trash is on us.", "Water and trash on the house.", "Water, sewer, trash: on us."):
        r = P(HEAD + body)
        assert not r.get("tenant_pays"), body
        assert r["utilities_included"]


def test_you_pay_electric_water_on_us_keeps_electric_only():
    r = P(HEAD + "You pay electric, water on us.")
    assert _set(r["tenant_pays"]) == {"electric"}
    assert _set(r["utilities_included"]) == {"water"}


def test_negated_or_conditional_on_us_is_not_included():
    for body in ("Tenant pays electric. Water is not on us.", "Tenant pays electric. Water is on us if you sign a 24 month lease.", "Is water on us? Please ask.",
                 "Tenant pays electric. Water is on us only in winter."):
        r = P(HEAD + body)
        assert "water" not in _set(r.get("utilities_included")), body


# ---- 2. "Pay list:" label
PAY_LIST = [
    "Pay list: electric; gas; water; sewer; trash. Gas for cooking only. Heat included.",
    "Pay list: electric, gas, water, sewer, trash. Gas for cooking only.",
    "Pay list:\nelectric; gas; water; sewer; trash\nGas for cooking only",
    "Gas for cooking only. Pay list: electric; gas; water; sewer; trash.",
    "PAY LIST: ELECTRIC; GAS; WATER; SEWER; TRASH. GAS FOR COOKING ONLY.",
    "Bills you pay: electric; gas; water; sewer; trash (gas for cooking only).",
    "Paid by tenant: electric; gas; water; sewer; trash. Gas for cooking only.",
    "Pays for: electric; gas; water; sewer; trash | Gas for cooking only",
]


@pytest.mark.parametrize("body", PAY_LIST)
def test_pay_list_label_keeps_all_five(body):
    r = P(HEAD + body)
    assert _set(r["tenant_pays"]) == FIVE, r.get("tenant_pays")


def test_reviewer_listing_roommates_l11():
    r = P(saved("r33-roommates-l11"))
    assert _set(r["tenant_pays"]) == FIVE
    assert r["utilities_included"] == "heat"
    assert r["price"] == 3275 and r["parking_cost"] == 120 and r["deposit"] == 1637


def test_pay_list_with_included_items_keeps_both_sides():
    r = P(HEAD + "Pay list: electric; gas. Water, sewer, trash included. Gas for cooking only.")
    assert _set(r["tenant_pays"]) == {"electric", "gas"}
    assert _set(r["utilities_included"]) == {"water", "sewer", "trash"}


def test_gas_for_cooking_alone_with_no_pay_list_is_not_a_payer():
    r = P(HEAD + "Gas for cooking only.")
    assert not r.get("tenant_pays")


# ---- 3. billed back with a pay clause
CONSERVICE = [
    "Water, sewer & trash billed back by Conservice, approximately $60/month. Tenant pays electric directly to the utility; gas for cooking.",
    "Water, sewer & trash billed back by Conservice approximately $60/month. Tenant pays electric directly to the utility; gas for cooking.",
    "Tenant pays electric directly to the utility; gas for cooking. Water, sewer and trash are billed back by Conservice, approx. $60 a month.",
    "Tenant pays electric directly to the utility. Water/sewer/trash billed back via Conservice, about $60 per month. Gas for cooking.",
    "Water, sewer & trash billed back by Conservice, approximately $60/month.\nTenant pays electric directly to the utility; gas for cooking.",
    "Tenant pays electric directly to the utility; gas for cooking. Water, sewer and trash billed back by Conservice approx $60/mo.",
]


@pytest.mark.parametrize("body", CONSERVICE)
def test_billed_back_amount_is_counted_for_its_three_utilities(body):
    r = P(HEAD + body)
    assert r["utilities_estimate"] == 60, notes(r)
    assert _set(r["tenant_pays"]) == FIVE, r.get("tenant_pays")
    assert "overlap" not in notes(r)
    assert "may overlap" not in notes(r) and "not counted" not in notes(r)


def test_billed_back_with_typical_electric_adds_the_two():
    for body in ("Water, sewer & trash billed back by Conservice, approximately $60/month. Tenant pays electric directly to the utility; gas for cooking. Typical electric bill: $55.",
                 "Tenant pays electric. Water, sewer and trash billed back by Conservice: ~$60/month. Typical electric: $55."):
        r = P(HEAD + body)
        assert r["utilities_estimate"] == 115, notes(r)
        assert "not counted anywhere" not in notes(r)
        assert "overlap" not in notes(r)


def test_reviewer_listing_uiuc_l22():
    r = P(saved("r33-uiuc-l22"))
    assert r["utilities_estimate"] == 115
    assert _set(r["tenant_pays"]) == FIVE
    assert r["price"] == 1510 and r["deposit"] == 750 and r["application_fee"] == 40
    n = notes(r)
    assert "overlap" not in n and "water $60" not in n and "not counted anywhere" not in n


# ---- 4. typical bills are never "billed back (RUBS)"
def test_reviewer_listing_roommates_l16():
    r = P(saved("r33-roommates-l16"))
    assert _set(r["tenant_pays"]) == {"electric", "gas", "internet", "water", "sewer", "trash"}
    assert r["utilities_estimate"] == 150, notes(r)
    n = notes(r)
    assert "billed back to you (RUBS), about $95" not in n
    assert "Utilities billed back by Conservice" not in n


TYPICAL_PLUS_BILLED = [
    "Tenant pays: ELECTRIC; GAS; INTERNET. Electric included? No, typical bills $95. Utilities billed back by Conservice about $55 (water/sewer/trash).",
    "Tenant pays electric, gas and internet. Typical bills $95. Water/sewer/trash billed back by Conservice about $55.",
    "Utilities billed back by Conservice about $55 (water/sewer/trash). Tenant pays electric, gas, internet; typical bills $95.",
    "Tenant pays electric, gas, internet. Typical bills $95. Water/sewer/trash billed back at $55/month.",
]


@pytest.mark.parametrize("body", TYPICAL_PLUS_BILLED)
def test_typical_bills_and_a_billed_back_figure_are_both_counted(body):
    r = P(HEAD + body)
    assert r["utilities_estimate"] == 150, notes(r)
    assert _set(r["tenant_pays"]) == {"electric", "gas", "internet", "water", "sewer", "trash"}
    assert "not counted anywhere" not in notes(r)


def test_typical_bills_beside_a_rubs_line_with_no_amount():
    r = P(HEAD + "Tenant pays electric and gas. Typical bills $95. Utilities are billed back by RUBS.")
    assert r["utilities_estimate"] == 95
    assert "billed back to you (RUBS), about $95" not in notes(r)
    assert "typical bills" in notes(r).lower() and "no billed-back amount" in notes(r)


def test_a_real_rubs_amount_keeps_its_wording():
    r = P(HEAD + "Utilities are billed back (RUBS), about $120 a month.")
    assert r["utilities_estimate"] == 120
    assert "billed-back" in notes(r)


# ---- 5. Spanish pay words
SPANISH = [
    "Servicios no incluidos, el inquilino paga luz y gas.",
    "Servicios no incluidos: el inquilino paga la luz y el gas.",
    "El inquilino paga luz y gas.",
    "El inquilino paga luz y gas. Mucha luz natural.",
]


@pytest.mark.parametrize("body", SPANISH)
def test_spanish_luz_y_gas_is_the_pay_list(body):
    r = P(HEAD + body)
    assert _set(r["tenant_pays"]) == {"electric", "gas"}, r.get("tenant_pays")
    assert not r.get("utilities_included")


def test_spanish_water_included_and_owner_pays():
    r = P(HEAD + "El inquilino paga luz y gas. Agua incluida.")
    assert _set(r["tenant_pays"]) == {"electric", "gas"} and r["utilities_included"] == "water"
    r = P(HEAD + "El propietario paga agua y basura. El inquilino paga luz y gas.")
    assert _set(r["tenant_pays"]) == {"electric", "gas"} and _set(r["utilities_included"]) == {"water", "trash"}
    r = P(HEAD + "Agua y basura incluidas. El inquilino paga luz, gas e internet.")
    assert _set(r["tenant_pays"]) == {"electric", "gas", "internet"} and _set(r["utilities_included"]) == {"water", "trash"}


def test_spanish_natural_light_is_not_electric():
    r = P(HEAD + "Mucha luz natural. Cocina grande.")
    assert not r.get("tenant_pays") and not r.get("utilities_included")


def test_reviewer_listing_nontech_l25():
    r = P(saved("r33-nontech-l25"))
    assert _set(r["tenant_pays"]) == {"electric", "gas"}
    assert r["price"] == 1290 and r["beds"] == 2 and r["baths"] == 1
    assert not r.get("utilities_included")


def test_english_negatives_unchanged():
    r = P(HEAD + "Tenant pays electric and gas. Water included.")
    assert _set(r["tenant_pays"]) == {"electric", "gas"} and r["utilities_included"] == "water"
    r = P(HEAD + "Great natural light and gas stove. Water included.")
    assert not r.get("tenant_pays") and r["utilities_included"] == "water"


def test_billed_back_note_keeps_the_listing_hedge_and_adds_none():
    r = P(HEAD + "Tenant pays electric. Water, sewer and trash billed back by Conservice approximately $60/month.")
    assert "billed back at about $60/month" in notes(r)
    r = P(HEAD + "Tenant pays electric and gas. Water & trash billed back $45.")
    assert r["utilities_estimate"] == 45 and "billed back at $45/month" in notes(r)


def test_quarterly_passed_through_figure_is_not_made_monthly():
    r = P("Rent $3,100/mo. Tenant pays electric. Quarterly water bill passed through, around $150.")
    assert r.get("utilities_estimate") == 50, notes(r)


def test_corpus_pay_list_and_spanish_neighbours():
    r = P(saved("r33-nontech-l26"))
    assert _set(r["tenant_pays"]) == FIVE and r["utilities_estimate"] == 230
