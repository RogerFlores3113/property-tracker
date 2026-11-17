"""Cycle 27 group G1: "all utilities" payer words in any order, "all except X" with an estimate, flat utility packages,
unbracketed "only $X flat" lines, heat and gas as one unknown, trash fees cover trash."""
import os
import pytest

from prophelper import compare, money
from prophelper.parsers import parse_listing

HEAD = "Rent $1,800. "


def P(text):
    return parse_listing(text, "")


def notes(r):
    return r.get("found_in_listing") or ""


def pays(r):
    return {w.strip() for w in (r.get("tenant_pays") or "").split(",") if w.strip()}


def inc(r):
    return {w.strip() for w in (r.get("utilities_included") or "").split(",") if w.strip()}


def unknown(text):
    """Utilities shown as unknown for the place, from the money and compare code on the saved fields."""
    r = P(text)
    place = {k: v for k, v in r.items() if k != "found_in_listing"}
    place.update(reader_notes=notes(r), listing_text=text)
    place["cost"] = money.rent_cost(place)
    return r, " ".join(compare._missing_names(place)).lower()


def listing(name):
    import os
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel") + "/"
    path = base + name
    if not os.path.exists(path):
        pytest.skip("saved reviewer listing not available")
    return open(path, encoding="utf-8").read()


# ---- 1. all utilities paid by tenant, in every word order
@pytest.mark.parametrize("text", [
    "Scott Park Flats 1 bed. Rent $1,330. Utilities: all utilities paid by tenant (est. $140). Security deposit: $1,330.",
    HEAD + "All utilities paid by tenant (est. $140).",
    HEAD + "Utilities: all utilities are the tenant's responsibility (est. $140).",
    HEAD + "All utilities paid by the resident, estimated $140/mo.",
    HEAD + "Tenant pays all utilities (est. $140).",
    HEAD + "Tenant-paid all utilities, approx $140 per month.",
    HEAD + "All utilities: tenant, about $140 a month.",
    HEAD + "All utilities (including heat) paid by tenant, est. $140.",
])
def test_all_utilities_tenant_pays_with_estimate(text):
    r = P(text)
    assert r.get("utilities_included") in (None, "")
    assert r["utilities_estimate"] == 140
    assert pays(r) >= {"electric", "gas", "water", "sewer", "trash"}
    _r, miss = unknown(text)
    assert miss.strip() == ""


@pytest.mark.parametrize("text", [
    HEAD + "All utilities paid by tenant.",
    HEAD + "Utilities: all utilities paid by tenant.",
    HEAD + "All utilities are the renter's responsibility.",
    HEAD + "Tenant pays all utilities including heat.",
    HEAD + "Tenant-paid all utilities.",
])
def test_all_utilities_tenant_pays_no_figure_is_unknown(text):
    r = P(text)
    assert r.get("utilities_included") in (None, "")
    assert pays(r) >= {"electric", "gas", "water", "sewer", "trash"}
    assert r.get("utilities_estimate") is None
    _r, miss = unknown(text)
    assert "electric" in miss and "trash" in miss


@pytest.mark.parametrize("text", [
    HEAD + "All utilities paid by landlord.",
    HEAD + "All utilities included, paid by the owner.",
])
def test_all_utilities_paid_by_landlord_still_included(text):
    assert P(text).get("utilities_included") == "all"


def test_corpus_family_l24():
    t = listing("r26-family-l24.txt")
    r = P(t)
    assert r.get("utilities_included") in (None, "")
    assert pays(r) >= {"electric", "gas", "water", "sewer", "trash"}


# ---- 2. all except X with an estimate
@pytest.mark.parametrize("text", [
    HEAD + "Tenant responsible for all utilities except trash, estimated $140/month.",
    HEAD + "All utilities except trash estimated $140/mo.",
    HEAD + "Utilities: all except trash, approx $140",
    HEAD + "Resident pays all utilities except trash (approx $140/mo).",
    HEAD + "Estimated $140 a month for all utilities except trash.",
])
def test_all_except_estimate_covers_the_rest(text):
    r, miss = unknown(text)
    assert r["utilities_estimate"] == 140
    assert pays(r) == {"electric", "gas", "water", "sewer"}
    assert "trash" not in miss and miss.strip() == ""
    assert "Trash is about" not in notes(r)


def test_all_except_trash_plus_separate_trash_figure():
    t = "Harvey Place 1BR. Rent $1,400. Utilities: all utilities except trash estimated $120/mo. Trash $15."
    r, miss = unknown(t)
    assert r["utilities_estimate"] == 135
    assert "trash" in pays(r) and miss.strip() == ""
    assert "not counted" not in notes(r)


@pytest.mark.parametrize("text", [
    HEAD + "Tenant pays all utilities except trash. Estimated $120/mo. Trash: $15/month.",
    HEAD + "All utilities except trash, approx $120/mo\nTrash $15 flat",
])
def test_all_except_trash_other_layouts(text):
    r, miss = unknown(text)
    assert (r["utilities_estimate"] or 0) + (r.get("other_monthly_fees") or 0) == 135 and miss.strip() == ""
    assert "trash" not in inc(r)


def test_all_except_trash_in_fee_list():
    t = HEAD + "Mandatory pass-through fees: trash $15, pest $5. Tenant responsible for all utilities except trash, estimated $140/month."
    r, miss = unknown(t)
    assert r["utilities_estimate"] == 155 and miss.strip() == ""
    assert r.get("utilities_included") in (None, "")


def test_family_l25_bracket_all_except():
    t = "Rent this 3 bed home. $2,400/mo. Tenant pays: electric, gas, water (approx $80 total, all except trash). Landlord pays trash."
    r, miss = unknown(t)
    assert r["utilities_estimate"] == 80 and pays(r) == {"electric", "gas", "water"}
    assert miss.strip() == "" and "Trash is about" not in notes(r)


def test_landlord_pays_all_except_is_not_flipped():
    r = P(HEAD + "Landlord pays all utilities except electric, about $60.")
    assert pays(r) == {"electric"} and r["utilities_estimate"] == 60


def test_except_with_named_conflict_stays_unknown():
    r = P("Tenant pays all utilities except internet and electric (electric avg $40).")
    assert r.get("utilities_estimate") is None


# ---- 3. a utility package is counted once
@pytest.mark.parametrize("text", [
    "Edgebrook 3BR $3,275/mo. Utility package $175/mo flat (heat, water, electric, trash) billed back monthly; internet by tenant.",
    HEAD + "Utility package $175/mo flat (heat, water, electric, trash) billed back.",
    HEAD + "Utilities package: $175 a month (heat, water, electric, trash).",
])
def test_utility_package_counted_once(text):
    r = P(text)
    assert r["utilities_estimate"] == 175
    assert r.get("other_monthly_fees") in (None, 0)
    assert "optional" not in notes(r)
    assert pays(r) >= {"heat", "water", "electric", "trash"}


# ---- 4. flat figures without brackets or beside a payer line
@pytest.mark.parametrize("text", [
    "Race Street Row, 1 bed. Rent $1,350. Electric and gas tenant. Water and trash only $60 flat. Sec dep $900 due at signing.",
    HEAD + "Tenant pays electric and gas. Water and trash only $60 flat.",
    HEAD + "Electric and gas tenant. Water and trash: $60 flat.",
    HEAD + "Electric and gas tenant.\n- Water and trash only $60 flat",
])
def test_water_trash_flat_counted(text):
    r, miss = unknown(text)
    assert r["utilities_estimate"] == 60
    assert r.get("other_monthly_fees") in (None, 0)
    assert pays(r) == {"electric", "gas", "water", "trash"}
    assert miss.strip() == "electric and gas"
    assert "not counted anywhere" not in notes(r)


@pytest.mark.parametrize("text", [
    "Zillow. Rates start at $1,480. Utilities: Water, sewer and trash (flat $75). Electric and gas tenant. Application $60.",
    HEAD + "Utilities: Water, sewer, trash (flat fee $75/mo). Electric and gas: tenant pays.",
    HEAD + "Electric and gas tenant. Water, sewer and trash only $75 flat.",
])
def test_water_sewer_trash_flat_counted(text):
    r, miss = unknown(text)
    assert r["utilities_estimate"] == 75
    assert miss.strip() == "electric and gas"
    assert "not counted anywhere" not in notes(r)


# ---- 5. heat and gas are one unknown
@pytest.mark.parametrize("text", [
    "PILSEN 3BR. $2,975. Heat & gas: tenant. Electric: tenant. Water/Sewer/Garbage: included in rent.",
    HEAD + "Tenant pays heat and gas. Electric: tenant.",
    HEAD + "Gas/heat: tenant pays. Electric: tenant.",
])
def test_heat_and_gas_one_unknown(text):
    r, miss = unknown(text)
    assert pays(r) == {"electric", "gas"}
    assert miss.count("gas") == 1 and "heat" not in miss


def test_all_utilities_unknown_has_one_gas_and_no_heat_twice():
    r, miss = unknown(listing("r26-roommates-l5.txt"))
    assert miss.count("gas") == 1 and "heat" not in miss


# ---- 6. a trash fee covers trash
@pytest.mark.parametrize("text", [
    "River North 3BR/2BA. $3,299/mo. Amenity fee $85/mo mandatory, valet trash $30/mo, pest control $5/mo. Tenant pays all utilities, estimated $180/mo for electric, gas, internet.",
    HEAD + "Valet trash $30/mo. Tenant pays all utilities, estimated $180/mo for electric, gas, internet.",
    HEAD + "Trash removal fee $30/mo. Tenant pays all utilities, estimated $180/mo for electric, gas, internet.",
])
def test_trash_fee_covers_trash(text):
    r, miss = unknown(text)
    assert r["other_monthly_fees"] >= 30
    assert "trash" not in pays(r) and "trash" not in miss
    assert "water" in miss and "sewer" in miss
