"""Cycle 26 group G1: a bracketed or dash-attached figure covers only its own item; a payer word after the utilities; "all except" with an
estimate in the next sentence; "(water and trash only) $60 flat"; billed-back items with a figure; one gas or heat unknown; a utility
inside a fee list; two figures in one bracket; "Water/sewer $60 flat" names the rest as missing."""
import os

import pytest

from prophelper import compare, money
from prophelper.parsers import parse_listing

PANEL = os.environ.get("PH_PANEL", "/tmp/claude-0/-home-user-property-helper/be454331-cd61-59ba-9ebc-8cb8b7ec6a12/scratchpad/panel")
HEAD = "Rent $1,800. "


def P(text):
    return parse_listing(text, "")


def notes(r):
    return r.get("found_in_listing") or ""


def pays(r):
    return {w.strip() for w in (r.get("tenant_pays") or "").split(",") if w.strip()}


def missing(text):
    r = P(text)
    place = dict(r, reader_notes=r.get("found_in_listing"), listing_text=text)
    c = money.true_monthly_cost(place, "rent")
    return r, c, compare._missing_names(dict(place, cost=c, score={"unknown": []}))


def saved(name):
    path = os.path.join(PANEL, name + ".txt")
    if not os.path.exists(path):
        pytest.skip("panel listing not available")
    return open(path, encoding="utf-8").read()


# ---- 1. a bracket or dash figure covers only the item it touches
@pytest.mark.parametrize("text", [
    HEAD + "Tenant pays electric and internet (Comcast, approx $60/mo paid by tenant).",
    HEAD + "Tenant pays electric and internet - approx $60/mo.",
    HEAD + "Tenant pays electric, internet (about $60/mo).",
    HEAD + "Tenant pays electric and internet - Comcast, approx $60/mo paid by tenant.",
    HEAD + "Tenant pays:\n- electric\n- internet (about $60/mo)",
])
def test_bracket_or_dash_figure_is_for_internet_only(text):
    r, c, miss = missing(text)
    assert r["utilities_estimate"] == 60
    assert "electric" in pays(r) and "internet" in pays(r)
    assert "Electric and internet are about" not in notes(r)
    assert any("electric" in m for m in miss), (miss, notes(r))
    assert "Nothing unknown" not in c["headline"]


def test_l17_saved_listing():
    r, c, miss = missing(saved("r25-roommates-l17"))
    assert r["utilities_estimate"] == 60 and r["utilities_included"] == "water, heat, trash"
    assert pays(r) == {"electric", "internet"} and miss and "electric" in miss[0]


@pytest.mark.parametrize("text", [
    HEAD + "Tenant pays electric and gas (about $80 total).",
    HEAD + "Tenant pays electric and gas about $80 total.",
])
def test_total_words_still_cover_the_group(text):
    r = P(text)
    assert r["utilities_estimate"] == 80 and pays(r) == {"electric", "gas"}


# ---- 2. a payer word after the utilities
@pytest.mark.parametrize("text", [
    HEAD + "Water & sewer included. Electric and gas tenant (heat is gas).",
    HEAD + "Water included. Gas, electric: resident.",
    HEAD + "Water included.\nElectric - renter\nGas - renter",
    HEAD + "Utilities: electric and gas tenant. Water included.",
    HEAD + "Water included, electric and gas paid by tenant.",
])
def test_payer_word_after_the_utilities(text):
    r = P(text)
    assert pays(r) == {"electric", "gas"}, (r.get("tenant_pays"), notes(r))


def test_nontech_l24_saved_listing():
    r = P(saved("r25-nontech-l24"))
    assert pays(r) == {"electric", "gas"} and r["utilities_included"] == "water, sewer"


# ---- 3. "pays all except" with an estimate in the next sentence
@pytest.mark.parametrize("text", [
    HEAD + "Utilities: Resident pays all except trash. Estimated $180 per month total.",
    HEAD + "Resident pays all except trash. Estimated $180/month.",
    HEAD + "Tenant pays all except trash and water. Approx $180/mo.",
    HEAD + "Utilities:\n- Resident pays all except trash\n- Estimated $180 per month",
])
def test_all_except_then_an_estimate(text):
    r = P(text)
    assert r["utilities_estimate"] == 180, notes(r)
    assert "trash" not in pays(r) and {"electric", "gas"} <= pays(r)
    assert "not counted anywhere" not in notes(r)


def test_nontech_l27_saved_listing():
    r = P(saved("r25-nontech-l27"))
    assert r["utilities_estimate"] == 180 and "trash" not in pays(r)


# ---- 4. "(water and trash only) $60 flat" and trash counted once
@pytest.mark.parametrize("text", [
    HEAD + "Tenant pays (water and trash only) $60 flat; heat and electric separate. Trash is $12/mo extra.",
    HEAD + "Tenant pays (water and trash only) $60 flat. Heat and electric separate. Trash is $12/mo extra.",
    HEAD + "Tenant pays\n- (water and trash only) $60 flat\n- heat and electric separate\n- Trash $12/mo extra",
])
def test_bracket_names_the_utilities_the_flat_figure_covers(text):
    r, c, miss = missing(text)
    assert r["other_monthly_fees"] == 60 and "utilities_estimate" not in r  # the $12 is not counted on top of the $60
    assert "trash" not in pays(r) and "water" not in pays(r)
    assert any("electric" in m for m in miss) and not any("trash" in m for m in miss), miss
    assert "not counted anywhere" not in notes(r) or "$60" not in notes(r)


def test_roommates_l21_saved_listing():
    r, c, miss = missing(saved("r25-roommates-l21"))
    assert r["other_monthly_fees"] == 60 and r["utilities_estimate"] == 55
    assert not any("trash" in m or "water" in m for m in miss), miss


# ---- 5. billed-back items that got a figure drop the "no amount" note
@pytest.mark.parametrize("text", [
    HEAD + "Utilities billed back: water/sewer/trash $75 flat; electric & gas direct with utility providers.",
    HEAD + "Utilities billed back: water, sewer, trash $75 flat. Electric and gas direct with providers.",
    HEAD + "Utilities billed back: water/sewer/trash $75 flat\nElectric & gas direct with providers",
])
def test_billed_back_with_a_flat_figure_has_no_no_amount_note(text):
    r = P(text)
    assert "gives no amount" not in notes(r)
    assert r["other_monthly_fees"] == 75 or r.get("utilities_estimate") == 75


# ---- 6. "all utilities" shows one gas or heat unknown
@pytest.mark.parametrize("text", [
    HEAD + "Utilities: tenant responsible for all utilities.",
    HEAD + "Tenant pays all utilities.",
    HEAD + "Resident pays all utilities. Laundry in building.",
])
def test_all_utilities_one_gas_or_heat_unknown(text):
    r = P(text)
    assert "gas" in pays(r) and "heat" not in pays(r)


@pytest.mark.parametrize("text", [
    HEAD + "Tenant pays all utilities. Heat is electric.",
    HEAD + "Tenant pays all utilities, heat is separate.",
])
def test_heat_stays_when_the_listing_says_it_is_separate(text):
    assert "heat" in pays(P(text))


# ---- 7. a utility item inside a fee list
@pytest.mark.parametrize("text", [
    "3/2 townhome | $2,360 | Fees: Admin fee $175 | Trash $12 | Lease processing $125 | Security $1,180",
    "3/2 townhome | $2,360 | Fees: Admin fee $175, Lease processing $125, Trash $12, Key deposit $75 | Security $1,180",
    "3/2 townhome. Rent $2,360.\nFees:\n- Admin fee $175\n- Trash $12\n- Lease processing $125\nSecurity $1,180",
    "3/2 townhome. Rent $2,360. Fees: admin $175, trash $12, lease processing $125.",
])
def test_trash_in_a_fee_list_is_counted_once(text):
    r = P(text)
    total = (r.get("utilities_estimate") or 0) + (r.get("other_monthly_fees") or 0)
    assert total == 12, (r.get("utilities_estimate"), r.get("other_monthly_fees"), notes(r))
    assert "$12\". It is not counted" not in notes(r) and "Only $12" not in notes(r)


def test_fee_list_trash_with_a_period_is_not_counted_twice():
    r = P("Rent $2,360. Fees: admin $175, trash $12/mo, pest $5.")
    assert (r.get("utilities_estimate") or 0) + (r.get("other_monthly_fees") or 0) == 17


def test_fee_list_keeps_other_tenant_paid_utilities_unknown():
    r, c, miss = missing("3/2 townhome | $2,360 | Fees: Admin fee $175, Trash $12 | Utilities: electric & gas paid by resident | Security $1,180")
    assert r["utilities_estimate"] == 12 and any("electric" in m for m in miss)


# ---- 8. two figures in one bracket
@pytest.mark.parametrize("text", [
    HEAD + "Utilities: you pay electric and water ($40 and $35 typical).",
    HEAD + "You pay electric and water ($40, $35).",
    HEAD + "Tenant pays:\n- electric and water ($40 and $35 typical)",
])
def test_two_figures_go_to_the_two_names_in_order(text):
    r = P(text)
    assert r["utilities_estimate"] == 75 and pays(r) == {"electric", "water"}
    assert "Only $40" not in notes(r) and "not counted anywhere" not in notes(r)


@pytest.mark.parametrize("text", [
    HEAD + "Utilities: you pay electric, gas and water ($40 and $35 typical).",
    HEAD + "You pay electric ($40 and $35 typical).",
])
def test_two_figures_that_cannot_be_paired_stay_unknown_and_are_quoted(text):
    r = P(text)
    assert "utilities_estimate" not in r
    assert "$40 and $35" in notes(r) and "not counted anywhere" in notes(r)
    assert "the other amounts in that line are counted" not in notes(r)


# ---- 9. "Water/sewer $60 flat" names the rest as missing
@pytest.mark.parametrize("text", [
    HEAD + "Water/sewer $60 flat, electric/gas by tenant.",
    HEAD + "Water/sewer $60 flat | electric/gas by tenant | Application fee $50",
    HEAD + "Water/sewer $60 flat.\nElectric/gas by tenant.",
])
def test_water_sewer_flat_figure_leaves_electric_and_gas_missing(text):
    r, c, miss = missing(text)
    assert r["other_monthly_fees"] == 60
    assert pays(r) == {"electric", "gas"}
    assert miss and "electric and gas" in miss[0] and "utilities estimate" not in miss, miss


def test_roommates_l18_saved_listing():
    r, c, miss = missing(saved("r25-roommates-l18"))
    assert r["other_monthly_fees"] == 60 and "electric and gas" in miss[0]
