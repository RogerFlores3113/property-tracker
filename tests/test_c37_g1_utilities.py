"""Cycle 37 group G1: utilities reader (rule oo and the included list).
(1) "Electric billed by Ameren, typical total about $130" keeps the pay list to electric, counts the $130 once, never calls it billed back (uiuc l10, nontech l3).
(2) a typical total never goes into other monthly fees next to an amenity fee (roommates l6); family l3 counts $210 once with no second "no amount" note.
(3) a billed electric with a typical total never says "no amount" and also counts a figure (nontech l10).
(4) an "on us except X" included list never guesses heat (uiuc l7, family l4).
(5) cable in a tenant-pays list gets a note (roommates l14)."""
import os

import pytest

from prophelper import money as money_mod
from prophelper.parsers import parse_listing

HEAD = "Rent $1,800. 2 bed 1 bath. "


def P(text):
    return parse_listing(text, "")


def notes(r):
    return r.get("found_in_listing") or ""


def _set(v):
    return {w.strip() for w in (v or "").split(",") if w.strip()}


def saved(name):
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel")
    return open(os.path.join(base, name + ".txt"), encoding="utf-8").read()


def _place(text):
    r = P(text)
    return r, {"price": 1800, "listing_text": text, "tenant_pays": r.get("tenant_pays"), "utilities_included": r.get("utilities_included"),
               "utilities_estimate": r.get("utilities_estimate"), "reader_notes": r.get("found_in_listing")}


BILLED_TOTAL = [
    "Electric billed by Ameren, typical total about $130 per month.\nTenant pays electric.",
    "Tenant pays electric.\nElectric billed by Ameren, typical total about $130 per month.",
    "Electric billed by Ameren, typical total about $130/mo.",
    "Electric billed by Ameren. Typical total about $130 per month. Tenant pays electric.",
    "Electric billed by Ameren; typical total about $130 a month.",
    "Tenant pays electric (billed by Ameren), typical total about $130/month.",
    "- Electric billed by Ameren\n- Typical total: about $130 per month",
]


@pytest.mark.parametrize("body", BILLED_TOTAL)
def test_billed_electric_typical_total_is_electric_only_and_counted_once(body):
    r, place = _place(HEAD + body)
    assert _set(r.get("tenant_pays")) == {"electric"}, (r.get("tenant_pays"), notes(r))
    assert r.get("utilities_estimate") == 130, notes(r)
    assert "electric and gas" not in notes(r) and "gas" not in notes(r).lower()
    assert "no amount" not in notes(r)
    assert "not counted" not in notes(r)
    assert not r.get("other_monthly_fees")
    assert money_mod._billed_names(place) == []  # never labelled "Billed back"


@pytest.mark.parametrize("name", ["r36-uiuc-l10", "r36-nontech-l3"])
def test_reviewer_listings_uiuc_l10_nontech_l3(name):
    r, place = _place(saved(name))
    assert _set(r["tenant_pays"]) == {"electric"}
    assert r["utilities_estimate"] in (130, 140)
    assert "electric and gas" not in notes(r)
    assert "no amount" not in notes(r)
    assert money_mod._billed_names(place) == []


def test_negative_ameren_alone_as_a_payer_is_still_electric_and_gas():
    r = P(HEAD + "Tenant pays Ameren. Typical total $150.")
    assert _set(r["tenant_pays"]) == {"electric", "gas"}
    assert r["utilities_estimate"] == 150


def test_negative_billed_gas_figure_of_its_own_is_still_billed_back():
    r = P(HEAD + "Tenant pays gas. Gas billed back at $70/month.")
    assert r["utilities_estimate"] == 70


# ------------------------------------------------ 2. roommates l6, family l3
def test_reviewer_listing_roommates_l6():
    r = P(saved("r36-roommates-l6"))
    assert r["other_monthly_fees"] == 45
    assert r["utilities_estimate"] == 210
    assert _set(r["tenant_pays"]) == {"electric"}
    assert _set(r["utilities_included"]) == {"heat", "water", "trash"}
    assert "not counted anywhere" not in notes(r) and "no amount" not in notes(r)


AMENITY = [
    "Amenity fee $45/mo includes package locker.\nElectric billed by ComEd; typical total utilities $210/mo",
    "Electric billed by ComEd; typical total utilities $210/mo\nAmenity fee $45/mo.",
    "Amenity fee $45/mo. Electric billed by ComEd, typical total utilities $210/mo.",
    "Heat, water, trash included | Electric billed by ComEd; typical total utilities $210/mo | Amenity fee $45/mo",
    "Electric billed by ComEd; typical total utilities about $210 per month.\n\nAmenity fee: $45 per month",
    "Electric billed by ComEd. Typical total $210/mo. Amenity fee $45 a month.",
]


@pytest.mark.parametrize("body", AMENITY)
def test_typical_total_never_joins_the_amenity_fee(body):
    r = P(HEAD + body)
    assert r["other_monthly_fees"] == 45, (r.get("other_monthly_fees"), notes(r))
    assert r["utilities_estimate"] == 210


def test_reviewer_listing_family_l3():
    r, place = _place(saved("r36-family-l3"))
    assert r["utilities_estimate"] == 210
    assert _set(r["tenant_pays"]) == {"electric", "gas", "water", "sewer"}
    assert _set(r["utilities_included"]) == {"trash"}
    assert "listed as something you pay, with no amount" not in notes(r)
    assert "does not say if that includes" not in notes(r)
    assert notes(r).count("$210") == 1
    assert money_mod._unpriced_tenant_utilities(place) == []


PGE = [
    "Electric billed by PG&E. Typical total $210. Tenant pays all utilities except trash",
    "Tenant pays all utilities except trash. Electric billed by PG&E. Typical total $210.",
    "Electric billed by PG&E.\nTypical total $210.\nTenant pays all utilities except trash.",
    "Utilities: Electric billed by PG&E; typical total $210; tenant pays all utilities except trash.",
    "Electric billed by PG&E. Typical total $210 per month. Tenant pays everything but trash.",
    "Tenant pays all utilities except trash (electric billed by PG&E). Typical total $210.",
]


@pytest.mark.parametrize("body", PGE)
def test_pge_typical_total_counted_once(body):
    r = P(HEAD + body)
    assert r["utilities_estimate"] == 210, notes(r)
    assert "trash" not in _set(r["tenant_pays"])
    assert {"electric", "gas", "water", "sewer"} <= _set(r["tenant_pays"])
    assert "listed as something you pay, with no amount" not in notes(r)
    assert not r.get("other_monthly_fees")


# ------------------------------------------------------------- 3. nontech l10
def test_reviewer_listing_nontech_l10():
    r = P(saved("r36-nontech-l10"))
    assert r["utilities_estimate"] == 180
    assert _set(r["tenant_pays"]) == {"electric", "gas"}
    assert "billed back to you, but the listing gives no amount" not in notes(r)
    assert "$180" in notes(r)


def test_negative_billed_electric_with_no_figure_says_no_amount_and_counts_nothing():
    r = P(HEAD + "Electric billed by Ameren. Tenant pays electric.")
    assert not r.get("utilities_estimate")
    assert "electric" in notes(r).lower() and "no amount" in notes(r)


def test_negative_rubs_water_with_billed_electric_stays_incomplete():
    r, place = _place(HEAD + "Tenant pays water, sewer and trash through RUBS (avg $55/mo for water and sewer). Electric billed by Ameren.\nTypical total bills $140 per month.")
    assert "electric" in money_mod._unpriced_tenant_utilities(place)


# ------------------------------------------------------------ 4. heat guesses
ON_US_HEAT = [
    "Utilities on us except electric.",
    "Utilities on us except electric. RUBS for water and sewer $85/mo.",
    "We cover all utilities except electric.",
    "Utilities: on us except electric. Parking included.",
    "All utilities on us, except electric.",
    "Great deal! Utilities on us except electric. Laundry on site.",
]


@pytest.mark.parametrize("body", ON_US_HEAT)
def test_on_us_except_electric_never_guesses_heat(body):
    r = P(HEAD + body)
    assert "heat" not in _set(r.get("utilities_included")), r.get("utilities_included")
    assert _set(r["tenant_pays"]) >= {"electric"}
    assert {"gas", "trash"} <= _set(r["utilities_included"])


def test_reviewer_listing_uiuc_l7_included_list():
    r = P(saved("r36-uiuc-l7"))
    assert _set(r["utilities_included"]) == {"gas", "trash"}
    assert _set(r["tenant_pays"]) == {"electric", "water", "sewer"}
    assert r["utilities_estimate"] == 85


def test_reviewer_listing_family_l4_included_list():
    r = P(saved("r36-family-l4"))
    assert _set(r["utilities_included"]) == {"gas", "water", "sewer", "trash"}
    assert _set(r["tenant_pays"]) == {"electric"}


def test_negative_heat_named_stays_included():
    r = P(HEAD + "Utilities on us except electric. Heat included.")
    assert "heat" in _set(r["utilities_included"])


def test_negative_landlord_pays_all_still_includes_heat():
    r = P(HEAD + "Landlord pays all utilities, tenant electric only total $110.")
    assert "heat" in _set(r["utilities_included"])


# ------------------------------------------------------------------ 5. cable
CABLE = [
    "** Tenant responsible for gas, electric, cable **\n** Water & trash incl **",
    "Tenant pays gas, electric and cable. Water included.",
    "Resident pays: electric, cable. Trash included.",
    "Tenant responsible for gas, electric, cable; water and trash included.",
]


@pytest.mark.parametrize("body", CABLE)
def test_cable_in_the_pay_list_gets_a_note_and_no_amount(body):
    r = P(HEAD + body)
    assert "pay for cable" in notes(r)
    assert "internet" not in _set(r.get("tenant_pays"))
    assert "electric" in _set(r["tenant_pays"])


def test_reviewer_listing_roommates_l14():
    r = P(saved("r36-roommates-l14"))
    assert "pay for cable" in notes(r)
    assert _set(r["tenant_pays"]) == {"electric", "gas"}
    assert _set(r["utilities_included"]) == {"water", "trash"}


def test_negative_cable_included_makes_no_note():
    r = P(HEAD + "Cable included. Tenant pays electric.")
    assert "pay for cable" not in notes(r)


def test_negative_cable_internet_is_internet():
    r = P(HEAD + "Tenant pays electric, gas, cable/internet.")
    assert "internet" in _set(r["tenant_pays"])


# ------------------------------------- 6. a typical total beside a billed-back figure
TOTAL_RUBS = [
    "RUBS for water and sewer $85/mo. Electric billed by ComEd; typical total utilities are $190/mo.",
    "Electric billed by ComEd; typical total utilities are $190/mo. RUBS for water and sewer $85/mo.",
    "RUBS for water and sewer $85/mo.\nElectric billed by ComEd.\nTypical total utilities: $190/mo.",
    "Water and sewer billed back at $85/month. Typical total utilities $190 per month. Electric billed by ComEd.",
    "Electric billed by ComEd. Typical total utilities about $190/mo. RUBS for water and sewer $85/mo.",
]


@pytest.mark.parametrize("body", TOTAL_RUBS)
def test_typical_total_is_counted_once_never_added_to_a_billed_back_figure(body):
    r = P(HEAD + body)
    assert r["utilities_estimate"] == 190, (r.get("utilities_estimate"), notes(r))
    assert "probably part of that total" in notes(r)
    assert "$275" not in notes(r)
    assert "listed as something you pay, with no amount" not in notes(r)


def test_reviewer_listing_roommates_l13_total_once():
    r = P(saved("r36-roommates-l13"))
    assert r["utilities_estimate"] == 190
    assert _set(r["tenant_pays"]) == {"electric", "water", "sewer"}
    assert notes(r).count("$85") == 1 and "$190" in notes(r)
    assert "ASSISTANT" not in notes(r)


def test_negative_typical_bills_for_other_utilities_are_still_added():
    r = P(HEAD + "Tenant pays electric, gas, internet. Typical bills $95. Water/sewer/trash billed back at $55/month.")
    assert r["utilities_estimate"] == 150


def test_negative_total_that_leaves_something_out_stays_added():
    r = P(HEAD + "Tenant pays all utilities except trash. Typical total utilities $120. Trash billed back at $20/month.")
    assert r["utilities_estimate"] == 140
