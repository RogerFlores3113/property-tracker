"""Cycle 13 G1: utilities reader. Conflicts stay unknown, dropped utilities come back, amounts use the right period,
and cable is not internet. Each reviewer phrasing pins the exact fields and the cost line."""
from __future__ import annotations

import pytest

from prophelper import money
from prophelper.parsers import listing_billed_amount, listing_billed_names, parse_listing

RENT = "2 bed 1 bath $1,500/month\n"


def read(text: str) -> dict:
    out = parse_listing(RENT + text)
    out.pop("source", None)
    return out


def cost(out: dict, text: str) -> dict:
    place = dict(out, listing_text=RENT + text)
    place.setdefault("price", 1500)
    r = money.true_monthly_cost(place)
    r["util"] = next(line for line in r["lines"] if line["key"] == "utilities")
    return r


def keys(out: dict) -> dict:
    return {k: out.get(k) for k in ("utilities_included", "tenant_pays", "utilities_estimate", "other_monthly_fees")}


def note(out: dict) -> str:
    return str(out.get("found_in_listing") or "")


# ---- 1. conflicts stay unknown
@pytest.mark.parametrize("text", ["Everything included except cable! Heat, water, trash all paid. Electric is separate.",
                                  "Everything included except cable! Electric is separate."])
def test_everything_except_cable_with_electric_separate(text):
    out = read(text)
    assert out["utilities_included"] != "all" and "electric" not in out["utilities_included"]
    assert out["tenant_pays"] == "electric"
    assert "utilities_estimate" not in out
    assert "electric is extra" in note(out) and "no amount" in note(out)
    r = cost(out, text)
    assert r["util"]["amount"] is None and "You pay electric" in r["util"]["note"]
    assert "utilities (electric)" in r["uncounted"]


def test_tenant_pays_pge_water_and_trash_included():
    text = "Tenant pays PG&E, water and trash included"
    out = read(text)
    assert keys(out) == {"utilities_included": "water, trash", "tenant_pays": "electric, gas", "utilities_estimate": None, "other_monthly_fees": None}
    assert "unclear" not in note(out)
    assert cost(out, text)["util"]["note"] == "You pay electric and gas; not counted yet"


@pytest.mark.parametrize("text", ["Utilities: Tenant pays all. Trash included.", "Tenant pays all utilities. Trash included."])
def test_tenant_pays_all_trash_included(text):
    out = read(text)
    assert out["utilities_included"] == "trash"
    assert out["tenant_pays"] == "electric, gas, water, sewer, heat"
    assert "utilities_estimate" not in out
    r = cost(out, text)
    assert r["util"]["amount"] is None and "You pay electric, gas, water, sewer and heat" in r["util"]["note"]
    assert "included in the rent" not in r["util"]["note"]


def test_landlord_pays_all_except_electric_with_rubs_is_a_conflict():
    text = "Landlord pays all except electric. Utilities billed back via RUBS."
    out = read(text)
    assert out.get("utilities_included") is None
    assert out["tenant_pays"] == "electric" and "utilities_estimate" not in out
    assert "also says utilities are billed back" in note(out) and "None are counted as included" in note(out)
    r = cost(out, text)
    assert r["util"]["amount"] is None and "included" not in r["util"]["note"]


def test_landlord_pays_all_with_rubs_is_not_all():
    out = read("Landlord pays all utilities. Utilities billed back via RUBS")
    assert out.get("utilities_included") is None and "also says utilities are billed back" in note(out)


# ---- 2. dropped utilities
def test_gas_heat_tenant_paid():
    text = "Gas heat tenant-paid"
    out = read(text)
    assert out["tenant_pays"] == "gas" and "utilities_included" not in out
    r = cost(out, text)
    assert r["util"]["amount"] is None and "You pay gas" in r["util"]["note"]


def test_rubs_without_amount_is_noted_and_unknown():
    text = "Utilities billed back via RUBS"
    out = read(text)
    assert keys(out) == {"utilities_included": None, "tenant_pays": None, "utilities_estimate": None, "other_monthly_fees": None}
    assert "billed back to you (RUBS)" in note(out) and "no amount" in note(out)
    r = cost(out, text)
    assert r["util"]["amount"] is None and "utilities" in r["uncounted"]


@pytest.mark.parametrize("text,want", [("Includes water, sewer and trash", "water, sewer, trash"),
                                       ("Landlord covers water and trash", "water, trash"),
                                       ("Includes water, sewer, and trash.\nPets: cats ok", "water, sewer, trash"),
                                       ("Tenant pays electric. Landlord covers water and trash", "water, trash")])
def test_included_lists_keep_every_named_utility(text, want):
    assert read(text)["utilities_included"] == want


# ---- 3. amounts
def test_quarterly_billed_back_is_a_third():
    text = "Quarterly water/sewer billed back to tenant, approx $180 per quarter"
    out = read(text)
    assert out["utilities_estimate"] == 60 and out["tenant_pays"] == "water, sewer"
    assert "$180 per quarter" in note(out) and "$60 a month" in note(out) and "$180/month" not in note(out)
    r = cost(out, text)
    assert r["util"]["amount"] == 60 and r["total"] == 1560
    assert listing_billed_amount(text) == 60


def test_trash_fee_is_not_counted_twice():
    text = "Water/sewer billed back by usage. Trash $15/mo."
    out = read(text)
    assert keys(out) == {"utilities_included": None, "tenant_pays": "water, sewer", "utilities_estimate": None, "other_monthly_fees": 15}
    r = cost(out, text)
    assert r["util"]["amount"] is None and r["total"] == 1515
    assert "utilities (water and sewer)" in r["uncounted"]


def test_named_utilities_approximate_monthly_is_tenant_estimate():
    text = "water/sewer/trash approximately $60 a month"
    out = read(text)
    assert keys(out) == {"utilities_included": None, "tenant_pays": "water, sewer, trash", "utilities_estimate": 60, "other_monthly_fees": None}
    r = cost(out, text)
    assert r["util"]["amount"] == 60 and "included" not in r["util"]["note"] and r["total"] == 1560


@pytest.mark.parametrize("text,amount", [("Resident pays electric ~$90 average", 90), ("Avg electric around $55", 55)])
def test_electric_average_is_a_counted_estimate(text, amount):
    out = read(text)
    assert keys(out) == {"utilities_included": None, "tenant_pays": "electric", "utilities_estimate": amount, "other_monthly_fees": None}
    r = cost(out, text)
    assert r["util"]["amount"] == amount and r["total"] == 1500 + amount
    assert listing_billed_names(RENT + text) == []


def test_flat_water_with_sewer_trash_included_and_electric_unknown():
    text = "water $60 flat monthly, sewer and trash included, tenant pays electric"
    out = read(text)
    assert out["utilities_estimate"] == 60 and out["utilities_included"] == "sewer, trash"
    assert out["tenant_pays"] == "electric, water"
    assert "flat fee of $60/month" in note(out) and "not counted anywhere" not in note(out)
    r = cost(out, text)
    assert r["util"]["amount"] == 60 and r["util"]["note"].startswith("Flat fee, from the listing")
    assert "utilities (electric)" in r["uncounted"] and r["total"] == 1560


def test_quarterly_utility_bill_is_a_monthly_estimate_with_a_note():
    text = "Quarterly utility bill about $210"
    out = read(text)
    assert keys(out) == {"utilities_included": None, "tenant_pays": None, "utilities_estimate": 70, "other_monthly_fees": None}
    assert "$210 per quarter" in note(out) and "$70 a month" in note(out)
    assert cost(out, text)["total"] == 1570
    assert read("Utilities approx $210 per quarter").get("utilities_estimate") != 210


def test_amounts_that_are_not_utility_bills_stay_out():
    assert "utilities_estimate" not in read("Trash $15/mo.")
    assert "utilities_estimate" not in read("Garage about $90 a month. Water and sewer included.")
    assert "utilities_estimate" not in read("Electric included, avg $90 deposit")


# ---- 4. cable is not internet
@pytest.mark.parametrize("text", ["Everything included except cable", "Cable extra", "Tenant pays electric and cable", "Cable not included"])
def test_cable_does_not_set_internet(text):
    out = read(text)
    assert "internet" not in str(out.get("tenant_pays") or "") and "internet" not in str(out.get("utilities_included") or "")
    assert "Cable is TV, not internet" in note(out)


def test_cable_extra_leaves_cost_unknown():
    out = read("Cable extra")
    assert "tenant_pays" not in out and "utilities_included" not in out
    assert cost(out, "Cable extra")["util"]["amount"] is None


def test_electric_and_cable_pays_only_electric():
    assert read("Tenant pays electric and cable")["tenant_pays"] == "electric"


def test_cable_next_to_internet_is_still_internet():
    assert read("Cable/Internet: Comcast, tenant sets up")["tenant_pays"] == "internet"
    assert read("All utilities paid except cable/internet")["tenant_pays"] == "internet"
