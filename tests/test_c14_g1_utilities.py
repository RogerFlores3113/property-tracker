"""Cycle 14 G1: utilities reader. Conflicts stay unknown, rough figures for some utilities leave the rest listed as not
counted, averages become estimates, a fee is counted once, and no false "water is included" note. Each reviewer phrasing
pins the exact fields and the cost lines (total, missing, uncounted)."""
from __future__ import annotations

import pytest

from prophelper import money
from prophelper.parsers import listing_billed_amount, listing_estimate_names, parse_listing

RENT = "2 bed 1 bath $1,500/month\n"
ALL6 = "electric, gas, water, sewer, trash, heat"
ALL6_UNC = "utilities (electric, gas, water, sewer, trash and heat)"


def read(text: str) -> dict:
    out = parse_listing(RENT + text)
    out.pop("source", None)
    return out


def cost(text: str) -> tuple[dict, dict]:
    out = read(text)
    place = dict(out, listing_text=RENT + text)
    place.setdefault("price", 1500)
    r = money.true_monthly_cost(place)
    r["util"] = next(line for line in r["lines"] if line["key"] == "utilities")
    return out, r


def keys(out: dict) -> tuple:
    return tuple(out.get(k) for k in ("utilities_included", "tenant_pays", "utilities_estimate", "other_monthly_fees"))


def note(out: dict) -> str:
    return str(out.get("found_in_listing") or "")


# ---- 1. conflicts stay unknown
def test_plus_utilities_water_rubs_landlord_pays_all():
    text = "$2,100 plus utilities. Water on RUBS. Landlord pays all utilities."
    out, r = cost(text)
    assert keys(out) == (None, "water", None, None)
    assert "landlord pays the utilities" in note(out) and "(RUBS)" in note(out) and "None are counted as included" in note(out)
    assert (r["total"], r["missing"], r["uncounted"]) == (1500, ["utilities estimate"], ["utilities (water)"])
    assert r["util"]["note"] == "You pay water; not counted yet"


@pytest.mark.parametrize("text", ["Utilities: tenant pays all. Utilities: landlord pays all (RUBS).",
                                  "Utilities: tenant pays all. Landlord pays all utilities."])
def test_tenant_pays_all_next_to_landlord_pays_all(text):
    out, r = cost(text)
    assert keys(out) == (None, ALL6, None, None)
    assert "landlord pays" in note(out) and ("don't agree" in note(out) or "(RUBS)" in note(out))
    assert (r["total"], r["missing"], r["uncounted"]) == (1500, ["utilities estimate"], [ALL6_UNC])


def test_tenant_pays_all_next_to_landlord_pays_all_except_electric():
    out, r = cost("Tenant pays all. Landlord pays all except electric.")
    assert keys(out) == (None, ALL6, None, None)
    assert "you pay all the utilities, but it also says the landlord pays all except electric" in note(out)
    assert "don't agree" in note(out)
    assert (r["total"], r["missing"], r["uncounted"]) == (1500, ["utilities estimate"], [ALL6_UNC])


def test_all_included_except_electric_tenant_pays_all_stays_unknown():
    # Honest reading: electric is the one both lines agree the renter pays. The other five are in a real conflict (one line says
    # included, another says you pay), so they stay listed as not counted, never as included or $0.
    out, r = cost("All utilities included except electric. Tenant pays all utilities.")
    assert keys(out) == (None, ALL6, None, None)
    assert "unclear about gas, water, sewer, trash, heat: one line says they are included and another says you pay them" in note(out)
    assert (r["total"], r["missing"], r["uncounted"]) == (1500, ["utilities estimate"], [ALL6_UNC])


# ---- 2. unknowns kept
def test_electric_average_with_gas_tenant_paid_keeps_gas_missing():
    out, r = cost("Electric averages $110 a month. Gas is paid by tenant.")
    assert keys(out) == (None, "electric, gas", 110, None)
    assert (r["total"], r["missing"], r["uncounted"]) == (1610, ["gas"], ["utilities (gas)"])
    assert "you also pay gas, not counted yet" in r["util"]["note"]
    assert listing_estimate_names(RENT + "Electric averages $110 a month. Gas is paid by tenant.") == ["electric"]


def test_estimate_for_one_utility_of_all_tenant_paid_leaves_the_rest_listed():
    out, r = cost("Tenant pays all utilities. Electric averages $110 a month.")
    assert out["utilities_estimate"] == 110 and out["tenant_pays"] == ALL6
    assert (r["total"], r["missing"]) == (1610, ["gas, water, sewer, trash and heat"])
    assert r["uncounted"] == ["utilities (gas, water, sewer, trash and heat)"]


# ---- 3. averages and approximations become estimates
@pytest.mark.parametrize("text,pays,amount", [
    ("Water/sewer approximate $60 per month", "water, sewer", 60),
    ("Water is by meter, typically around $55/month", "water", 55),
    ("water avg. $70/mo", "water", 70),
    ("approximately $120/month average for heat", "heat", 120),
    ("$140 electric and gas average", "electric, gas", 140),
])
def test_average_for_named_utilities_is_an_estimate(text, pays, amount):
    out, r = cost(text)
    assert keys(out) == (None, pays, amount, None)
    assert (r["total"], r["missing"], r["uncounted"]) == (1500 + amount, [], [])
    assert r["util"]["note"] == "From the listing"
    assert "not counted anywhere" not in note(out) and "$70/mo" not in note(out).replace("about $70 a month", "")


def test_winter_total_covers_the_three_tenant_paid_utilities():
    text = "Gas heat, electric and water/sewer are on you, roughly $150 a month total in the winter."
    out, r = cost(text)
    assert keys(out) == (None, "electric, gas, water, sewer", 150, None)
    assert "doesn't say which" not in note(out) and "not counted anywhere" not in note(out)
    assert (r["total"], r["missing"], r["uncounted"]) == (1650, [], [])


def test_water_average_does_not_hide_tenant_paid_gas_and_electric():
    out, r = cost("Tenant pays gas & electric. Water avg. $70/mo.")
    assert keys(out) == (None, "electric, gas, water", 70, None)
    assert (r["total"], r["missing"], r["uncounted"]) == (1570, ["electric and gas"], ["utilities (electric and gas)"])


def test_two_conflicting_estimates_take_the_total_that_covers_more():
    out, r = cost("Electric about $70. Utilities estimate $120 total. Tenant pays utilities.")
    assert out["utilities_estimate"] == 120 and out["tenant_pays"] == ALL6
    assert "electric at about $70 a month" in note(out) and "$120, is counted" in note(out)
    assert (r["total"], r["missing"], r["uncounted"]) == (1620, [], [])


def test_two_estimates_for_the_same_utilities_keep_the_higher():
    out, r = cost("Electric about $70 and electric and gas about $140. Tenant pays electric and gas.")
    assert out["utilities_estimate"] == 140 and (r["total"], r["missing"]) == (1640, [])
    out, r = cost("Electric about $90. Electric about $70. Tenant pays electric.")
    assert out["utilities_estimate"] == 90


def test_estimates_for_different_utilities_add_up():
    out, r = cost("Electric about $70. Gas about $40. Tenant pays electric and gas.")
    assert out["utilities_estimate"] == 110 and (r["total"], r["missing"]) == (1610, [])


def test_hawthorn_flat_water_sewer_trash_plus_electric_gas_average():
    text = "Utilities: tenant pays electric and gas, approx $140/mo combined average. Water, sewer, trash $70/month flat, paid with rent."
    out, r = cost(text)
    assert keys(out) == (None, "electric, gas, water, sewer, trash", 210, None)
    assert "water is included" not in note(out) and "billed-back amount means" not in note(out)
    assert (r["total"], r["missing"], r["uncounted"]) == (1710, [], [])
    assert listing_billed_amount(RENT + text) == 210


# ---- 4. double counts
def test_flat_trash_and_lawn_fee_is_counted_once():
    out, r = cost("Tenant responsible for all utilities; flat $30 per month for trash and lawn")
    assert keys(out) == (None, ALL6, None, 30)
    assert (r["total"], r["missing"], r["uncounted"]) == (1530, ["utilities estimate"], [ALL6_UNC])


# ---- 5. false notes
def test_teller_water_flat_sewer_trash_included_has_no_false_included_note():
    text = "Utilities: water $60 flat monthly, sewer and trash included, tenant pays electric."
    out, r = cost(text)
    assert keys(out) == ("sewer, trash", "electric, water", 60, None)
    assert "water is included" not in note(out) and "billed-back amount" not in note(out)
    assert (r["total"], r["missing"], r["uncounted"]) == (1560, ["electric"], ["utilities (electric)"])


def test_water_flat_fee_really_listed_as_included_keeps_the_note():
    out = read("Water, sewer and trash paid with rent. Tenant pays gas and electric. Water flat fee $60/month.")
    assert "water is included, but a billed-back amount means you pay it" in note(out)


# ---- 6. renter's insurance is never a utilities estimate
@pytest.mark.parametrize("text,pays", [("Renter's insurance required, approx $15/month", None),
                                       ("Tenant pays all utilities. Renter's insurance required, approx $15/month", ALL6)])
def test_renters_insurance_is_not_utilities(text, pays):
    out, r = cost(text)
    assert keys(out) == (None, pays, None, None)
    assert r["util"]["amount"] is None and r["total"] == 1515  # the $15 counts once, as insurance (cycle 14 G3), never as utilities
