"""Cycle 33 group G1: utilities reader. Rule (u): a list joined by semicolons, commas, slashes, "and" or newlines keeps every item (the pay list is pinned whole).
Rule (x): a question followed by its answer is the answer ("Electric included? No." means the tenant pays electric, "Electric included? Yes." means it is
included); only a question with nothing after it stays a question. Typical bills after a pay list, after an answer, after a comma, in capitals, count as the
estimate. "Utilities billed back by Conservice about $60" is a utilities amount, and "gas for cooking" in a pay list keeps gas."""
import os

import pytest

from prophelper import compare, money
from prophelper.parsers import parse_listing

HEAD = "Rent $2,100. 2 bed 1 bath. "
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


def missing(text):
    r = P(text)
    place = dict(r, reader_notes=r.get("found_in_listing"), listing_text=text)
    c = money.true_monthly_cost(place, "rent")
    return r, c, compare._missing_names(dict(place, cost=c, score={"unknown": []}))


# ---- 1. a semicolon list keeps every item
SEMI = [
    "Tenant pays: electric; gas; water; sewer; trash. Typical bills: $165 per month.",
    "Tenant pays electric; gas; water; sewer; trash. Typical bills $165 a month.",
    "TENANT PAYS: ELECTRIC; GAS; WATER; SEWER; TRASH. TYPICAL BILLS: $165 PER MONTH.",
    "Utilities - tenant pays: electric; gas; water; sewer; trash; typical bills $165/mo.",
    "Tenant pays:\nelectric; gas; water; sewer; trash\nTypical bills $165 per month",
    "Resident pays (electric; gas; water; sewer; trash). Typical bills about $165.",
    "Tenant pays electric, gas; water / sewer; trash. Typical bills $165 per month.",
    "Tenant pays electric and gas; water; sewer and trash. Typical bills $165 per month.",
]


@pytest.mark.parametrize("body", SEMI)
def test_semicolon_pay_list_keeps_all_five_and_counts_the_bills(body):
    r = P(HEAD + body)
    assert _set(r["tenant_pays"]) == FIVE, r.get("tenant_pays")
    assert r["utilities_estimate"] == 165, notes(r)
    assert "not counted anywhere" not in notes(r)
    assert r.get("utilities_included") in (None, "")


def test_semicolon_list_three_items_with_typical_bills_no_unit():
    for body in ("Tenant pays electric; gas; water. Typical bills $150", "Tenant pays electric; gas; water. Typical bills $150 a month.",
                 "Tenant pays electric; gas; water.\nTypical bills $150"):
        r = P("1 bed 1 bath $1,450. " + body)
        assert _set(r["tenant_pays"]) == {"electric", "gas", "water"}, body
        assert r["utilities_estimate"] == 150, body


def test_two_item_semicolon_list():
    r = P(HEAD + "Tenant pays: electric; gas.")
    assert _set(r["tenant_pays"]) == {"electric", "gas"}
    r = P(HEAD + "Tenant pays electric; gas")
    assert _set(r["tenant_pays"]) == {"electric", "gas"}


def test_included_list_with_semicolons_keeps_every_item():
    r = P(HEAD + "Included: water; sewer; trash. Tenant pays: electric; gas.")
    assert _set(r["utilities_included"]) == {"water", "sewer", "trash"}
    assert _set(r["tenant_pays"]) == {"electric", "gas"}


def test_semicolon_between_different_payers_is_not_joined():
    r = P(HEAD + "Landlord pays water; tenant pays electric.")
    assert _set(r["utilities_included"]) == {"water"}
    assert _set(r["tenant_pays"]) == {"electric"}
    r = P(HEAD + "Heat included; gas separate.")
    assert _set(r["utilities_included"]) == {"heat"}
    assert _set(r["tenant_pays"]) == {"gas"}


# ---- 2. a question followed by its answer
ANSWER_NO = [
    "Electric included? No. Typical bills about $110.",
    "Electric included? No. Typical bills about $110 per month.",
    "Electric included? No, typical bills about $110.",
    "Electric included?  NO.\nTypical bills about $110.",
    "ELECTRIC INCLUDED? NO. TYPICAL BILLS ABOUT $110.",
    "Is electric included? No. Typical bills about $110.",
    "Water included. Electric included? No. Typical bills about $110.",
    "- Electric included? No\n- Typical bills about $110",
    "Electric included in rent? No. Typical bills about $110/mo.",
]


@pytest.mark.parametrize("body", ANSWER_NO)
def test_electric_included_no_means_tenant_pays_and_bills_count(body):
    r = P(HEAD + body)
    assert "electric" in _set(r["tenant_pays"]), notes(r)
    assert "electric" not in _set(r.get("utilities_included")), r
    assert r["utilities_estimate"] == 110, notes(r)
    assert "question, not an answer" not in notes(r)
    assert "not counted anywhere" not in notes(r)


def test_two_answers_then_typical_bills():
    r = P(HEAD + "Electric included? No. Gas included? No. Typical bills $110 per month.")
    assert _set(r["tenant_pays"]) == {"electric", "gas"}
    assert r["utilities_estimate"] == 110
    assert "question, not an answer" not in notes(r)


@pytest.mark.parametrize("body", ["Electric included? Yes.", "Electric included? Yes, in the rent.", "ELECTRIC INCLUDED? YES.", "Is electric included? Yes", "Electric included?\nYes."])
def test_electric_included_yes_means_included(body):
    r = P(HEAD + body)
    assert "electric" in _set(r.get("utilities_included")), r
    assert "electric" not in _set(r.get("tenant_pays")), r
    assert "question, not an answer" not in notes(r)


def test_a_question_with_no_answer_stays_a_question():
    for body in ("Is electric included?", "Is electric included? Please inquire.", "Electric included? Ask us.", "Electric included? Call for details."):
        r = P(HEAD + body)
        assert "electric" not in _set(r.get("utilities_included")), body
        assert "question, not an answer" in notes(r), body


def test_no_answer_does_not_make_a_pet_or_other_question_a_utility():
    r = P(HEAD + "Gas included? No. Do you allow dogs? Yes up to 25 lb.")
    assert "gas" in _set(r["tenant_pays"])
    assert "gas" not in _set(r.get("utilities_included"))


# ---- 3. typical bills after "all utilities", any punctuation
ALL_COMMA = [
    "Tenant pays all utilities, typical bills $210.",
    "Tenant pays all utilities, typical bills $210 per month.",
    "Tenant pays all utilities - typical bills $210.",
    "Tenant pays all utilities; typical bills $210.",
    "Tenant pays all utilities. Typical bills $210.",
    "TENANT PAYS ALL UTILITIES, TYPICAL BILLS $210.",
    "All utilities paid by tenant, typical bills $210/mo.",
    "Built 1978. Tenant pays all utilities, typical bills $210.\nPets negotiable.",
]


@pytest.mark.parametrize("body", ALL_COMMA)
def test_tenant_pays_all_utilities_comma_typical_bills(body):
    r = P(HEAD + body)
    assert _set(r["tenant_pays"]) == FIVE, r.get("tenant_pays")
    assert r["utilities_estimate"] == 210, notes(r)
    assert "not counted anywhere" not in notes(r)


def test_comma_before_a_non_utility_figure_is_not_an_estimate():
    r = P(HEAD + "Tenant pays all utilities, parking $210.")
    assert r.get("utilities_estimate") in (None, 0)


# ---- 4. capitals
CAPS = [
    "RESIDENT PAYS ELECTRIC, GAS, INTERNET. TYPICAL BILLS $165.",
    "Resident pays electric, gas, internet. Typical bills $165.",
    "RESIDENT PAYS ELECTRIC, GAS, INTERNET; TYPICAL BILLS $165.",
    "RESIDENT PAYS ELECTRIC, GAS, INTERNET\nTYPICAL BILLS $165",
    "RESIDENT PAYS ELECTRIC, GAS, INTERNET | TYPICAL BILLS $165 | PARKING $175",
]


@pytest.mark.parametrize("body", CAPS)
def test_caps_pay_list_and_typical_bills(body):
    r = P("Rent $3,120. " + body)
    assert _set(r["tenant_pays"]) == {"electric", "gas", "internet"}
    assert r["utilities_estimate"] == 165, notes(r)
    assert "TYPICAL BILLS" not in notes(r) and "Typical bills" not in notes(r).replace("typical bills", "")  # no note quotes the run-together clause


# ---- 5. billed back
BILLED = [
    "Landlord pays heat and water; resident pays electric, gas. Utilities billed back by Conservice about $60.",
    "Resident pays electric and gas. Utilities billed back by Conservice about $60/mo.",
    "Resident pays electric and gas. Utilities billed back through Conservice, about $60 a month.",
    "UTILITIES BILLED BACK BY CONSERVICE ABOUT $60.",
    "Utilities are billed back by Conservice approx. $60.",
    "Resident pays electric and gas.\nUtilities billed back by Conservice about $60",
]


@pytest.mark.parametrize("body", BILLED)
def test_billed_back_amount_is_a_utilities_amount(body):
    r = P("Rent $3,260. " + body)
    assert r["utilities_estimate"] == 60, notes(r)
    assert "not counted anywhere" not in notes(r)
    assert "billed-back average of $60" in notes(r)


def test_billed_back_next_to_a_parking_figure_stays_out_of_the_estimate_with_a_note():
    r = P("Rent $3,260. Utilities billed back by Conservice about $60. Parking $60.")
    assert r.get("utilities_estimate") in (None, 0) or r["utilities_estimate"] == 60
    assert "$60" in notes(r) or r.get("utilities_estimate") == 60


# ---- 5b. pay list, typical bills, then a billed-back figure for the others: both count
def test_typical_bills_plus_billed_back_for_other_utilities_are_added():
    r = P("Rent $3,120. Resident pays electric, gas, internet. Typical bills $165. Water/sewer/trash billed back at $62 a month.")
    assert r["utilities_estimate"] == 227, notes(r)
    assert "$165" in notes(r) and "$62" in notes(r)
    assert "not counted anywhere" not in notes(r)


def test_typical_bills_covering_all_utilities_with_billed_back_inside_is_counted_once():
    r = P("Rent $3,120. Resident pays all utilities. Typical bills $165. Water/sewer/trash billed back at $62 a month.")
    assert r["utilities_estimate"] == 165, notes(r)
    assert "counted once" in notes(r)


# ---- 6. gas for cooking stays on the pay list
COOK = [
    "Heat included; tenant pays electric ($65); typical bills for the unit about $140; gas for cooking.",
    "Heat included. Tenant pays electric and gas for cooking.",
    "Heat included; tenant pays electric; gas for cooking.",
    "Heat included. Tenant pays electric. Gas for cooking.",
    "Heat included. Tenant pays: electric, plus gas for cooking.",
    "Heat included\nTenant pays electric\nGas for cooking",
]


@pytest.mark.parametrize("body", COOK)
def test_gas_for_cooking_keeps_gas_on_the_pay_list(body):
    r = P("Rent $3,199. " + body)
    assert _set(r["tenant_pays"]) == {"electric", "gas"}, r.get("tenant_pays")
    assert _set(r["utilities_included"]) == {"heat"}


def test_gas_for_cooking_with_gas_included_stays_included_or_unset():
    r = P("Rent $3,199. Tenant pays electric. Gas included. Gas for cooking.")
    assert _set(r["tenant_pays"]) == {"electric"}


# ---- 7. the reviewers' whole listings
def test_whole_uiuc_l8():
    r = P(saved("r32-uiuc-l8"))
    assert _set(r["tenant_pays"]) == FIVE
    assert r["utilities_estimate"] == 165
    assert "not counted anywhere" not in notes(r)


def test_whole_uiuc_l12():
    r = P(saved("r32-uiuc-l12"))
    assert _set(r["tenant_pays"]) == {"electric", "gas", "water"}
    assert r["utilities_estimate"] == 150
    assert not r.get("utilities_included")


def test_whole_uiuc_l2():
    r = P(saved("r32-uiuc-l2"))
    assert "electric" in _set(r["tenant_pays"]) and "electric" not in _set(r.get("utilities_included"))
    assert r["utilities_estimate"] == 95
    assert "question, not an answer" not in notes(r)
    assert "Typical bills $95/mo\". It looks like" not in notes(r)


def test_whole_uiuc_l6():
    r = P(saved("r32-uiuc-l6"))
    assert _set(r["tenant_pays"]) == FIVE
    assert r["utilities_estimate"] == 210
    assert "typical bills $210" not in notes(r)


def test_whole_uiuc_l13_two_figures_never_lower_than_the_higher_one():
    r = P(saved("r32-uiuc-l13"))
    assert _set(r["tenant_pays"]) == FIVE
    assert r["utilities_estimate"] == 190  # $110 after "Electric included? No." and $190 after "all utilities": the higher one counts, and the note names both
    assert "$110" in notes(r) and "$190" in notes(r)
    assert "question, not an answer" not in notes(r)


def test_whole_roommates_l8():
    r = P(saved("r32-roommates-l8"))
    assert _set(r["utilities_included"]) == {"heat", "water"}
    assert _set(r["tenant_pays"]) == {"electric"}
    assert r["utilities_estimate"] == 110
    assert "question, not an answer" not in notes(r)
    assert not [n for n in notes(r).split("\n") if "Typical bills" in n and "not counted anywhere" in n]


def test_whole_roommates_l9():
    r = P(saved("r32-roommates-l9"))
    assert _set(r["utilities_included"]) == {"heat", "water"}
    assert _set(r["tenant_pays"]) == {"electric", "gas"}
    assert r["utilities_estimate"] == 60
    assert "Conservice" not in notes(r) or "not counted anywhere" not in notes(r)


def test_whole_roommates_l15():
    r = P(saved("r32-roommates-l15"))
    assert _set(r["tenant_pays"]) == FIVE | {"internet"}
    assert r["utilities_estimate"] == 227
    assert "INTERNET. TYPICAL BILLS" not in notes(r)
    assert "not counted anywhere" not in notes(r)


def test_whole_roommates_l4():
    r = P(saved("r32-roommates-l4"))
    assert _set(r["tenant_pays"]) == {"electric", "gas"}
    assert _set(r["utilities_included"]) == {"heat"}
    assert r["utilities_estimate"] == 140
