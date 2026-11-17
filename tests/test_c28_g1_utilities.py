"""Cycle 28 group G1: "except" read the same way in every word order, an estimate right after "tenant pays all utilities",
flat utility packages and admin fees, and contradiction notes between "included" and "tenant pays" lines."""
import os
import pytest

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


def listing(name):
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel")
    return open(os.path.join(base, name), encoding="utf-8").read()


# ---- 1. "except": the tenant pays everything but the excepted item, in every word order
EXCEPT_CASES = [
    # (text, excepted item, estimate)
    (HEAD + "Utilities paid by tenant except trash, about $230.", "trash", 230),
    (HEAD + "Utilities: all except trash paid by tenant, estimate $230/mo.", "trash", 230),
    (HEAD + "Tenant responsible for everything but trash, about $230.", "trash", 230),
    (HEAD + "Tenant pays everything but trash, approx $230.", "trash", 230),
    (HEAD + "All utilities except trash paid by the resident, est. $230.", "trash", 230),
    (HEAD + "All utilities paid by tenant, except trash, about $230.", "trash", 230),
    (HEAD + "Tenant pays all utilities except trash, about $230.", "trash", 230),
    (HEAD + "Tenant pays all utilities except water, approx $150.", "water", 150),
    (HEAD + "Utilities paid by tenant except water. Approx $150.", "water", 150),
    (HEAD + "- Utilities: all except sewer paid by tenant, estimate $140/mo\n- Pets OK", "sewer", 140),
    (HEAD + "All utilities except internet paid by tenant, est. $135.", "internet", 135),
]


@pytest.mark.parametrize("text,item,est", EXCEPT_CASES)
def test_except_item_is_never_the_tenants(text, item, est):
    r = P(text)
    assert item not in pays(r)
    assert item in inc(r)
    assert pays(r) >= {"electric", "gas"}
    assert r["utilities_estimate"] == est
    assert "not counted" not in notes(r)


def test_landlord_covers_estimate_kept():
    r = P(HEAD + "Resident pays all utilities except landlord covers water/sewer. Est $180")
    assert r["utilities_estimate"] == 180
    assert inc(r) == {"water", "sewer"}
    assert pays(r) == {"electric", "gas", "trash"}


def test_landlord_covers_other_orders():
    for t in (HEAD + "Tenant pays all utilities, except the landlord pays trash. About $200.",
              HEAD + "Renter pays all utilities except owner covers trash, est. $200"):
        r = P(t)
        assert r["utilities_estimate"] == 200
        assert "trash" not in pays(r) and "trash" in inc(r)


@pytest.mark.parametrize("name,item,est", [("r27-family-l38.txt", "trash", 230), ("r27-family-l31.txt", "sewer", 140), ("r27-uiuc-l11.txt", "internet", 135)])
def test_reviewer_listings_except(name, item, est):
    r = P(listing(name))
    assert item not in pays(r)
    assert r["utilities_estimate"] == est
    assert not any(w in inc(r) for w in ("electric", "gas"))


def test_all_except_right_forms_stay_right():
    r = P(HEAD + "Tenant pays all utilities except water, approx $150.")
    assert pays(r) == {"electric", "gas", "sewer", "trash"}
    assert inc(r) == {"water"}
    r = P(HEAD + "Landlord pays all utilities except electric, about $80.")
    assert "electric" in pays(r) and "water" not in pays(r)


def test_estimate_naming_its_utilities_is_not_moved():
    r = P(listing("r27-nontech-l37.txt"))
    assert r["utilities_estimate"] == 110
    assert "water" in inc(r) and "water" not in pays(r)


# ---- 2. an estimate in the sentence right after "tenant pays all utilities"
@pytest.mark.parametrize("text", [
    HEAD + "Tenant pays all utilities. Estimated utilities $160/mo.",
    HEAD + "Tenant pays all utilities.\nApprox $160/month",
    HEAD + "Tenant pays all utilities. Approx $160 per month.",
    HEAD + "Tenant pays all utilities.\nAbout $160 per month for the utilities.",
    HEAD + "Tenant pays all utilities. Estimated utility costs: $160 a month.",
])
def test_estimate_after_tenant_pays_all(text):
    r = P(text)
    assert r["utilities_estimate"] == 160
    assert pays(r) >= {"electric", "gas", "water"}


@pytest.mark.parametrize("text", [
    HEAD + "Tenant pays all utilities. Approx $45/month parking.",
    HEAD + "Tenant pays all utilities. Approx $35 monthly pet rent.",
    HEAD + "Tenant pays all utilities.\nEstimated $50 monthly fee for admin.",
    HEAD + "Tenant pays all utilities. Approx $40 per month for a parking space.",
])
def test_figure_of_another_item_is_not_the_estimate(text):
    assert "utilities_estimate" not in P(text)


def test_reviewer_listing_nontech_l32():
    r = P(listing("r27-nontech-l32.txt"))
    assert r["utilities_estimate"] == 160
    assert r["rent"] == 1425 if "rent" in r else True
    assert "not counted anywhere" not in notes(r)


# ---- 3. flat packages and admin fees
@pytest.mark.parametrize("text", [
    HEAD + "Valet trash $25/mo. Water/sewer/trash flat package $65 per month. Tenant pays electric.",
    HEAD + "Water/sewer/trash package $65. Valet trash $25/mo. Tenant pays electric.",
    HEAD + "Water, sewer and trash package: $65/mo. Valet trash $25/mo. Tenant pays electric.",
    HEAD + "\n- Water/sewer/trash package $65\n- Valet trash $25/mo\n- Tenant pays electric",
])
def test_flat_package_is_utilities_valet_is_fee(text):
    r = P(text)
    assert r["utilities_estimate"] == 65
    assert r["other_monthly_fees"] == 25
    assert pays(r) == {"electric", "water", "sewer", "trash"}


def test_flat_package_reviewer_listing():
    r = P(listing("r27-nontech-l34.txt"))
    assert r["utilities_estimate"] == 65
    assert r["other_monthly_fees"] == 25
    assert {"water", "sewer", "trash", "electric"} <= pays(r)


@pytest.mark.parametrize("text", [
    HEAD + "Flat $55 utility admin fee monthly. Tenant pays electric.",
    HEAD + "Utility admin fee $55/month. Tenant pays electric.",
    HEAD + "Tenant pays electric.\n- Utility administration fee: $55 monthly",
])
def test_utility_admin_fee_counted_once_as_monthly_fee(text):
    r = P(text)
    assert r["other_monthly_fees"] == 55
    assert "utilities_estimate" not in r
    assert "not counted" not in notes(r)


def test_utility_admin_fee_one_time_is_not_monthly():
    r = P(HEAD + "Utility admin fee $25 one-time. Tenant pays electric.")
    assert "other_monthly_fees" not in r


def test_admin_fee_reviewer_listing_roommates_l9():
    r = P(listing("r27-roommates-l9.txt"))
    assert r["other_monthly_fees"] == 55
    assert "Flat $55 utility admin fee" not in notes(r) or "not counted anywhere" not in notes(r)


@pytest.mark.parametrize("text", [
    HEAD + "Tenant pays electric. Cold water $40 flat.",
    HEAD + "Tenant pays electric and cold water $40 flat.",
    HEAD + "Tenant pays: electricity, cold water ($40 flat, billed back quarterly), cable.",
])
def test_cold_water_flat_is_counted(text):
    r = P(text)
    assert (r.get("utilities_estimate") == 40) != (r.get("other_monthly_fees") == 40)  # counted in one place only
    assert "not counted anywhere" not in notes(r)


def test_cold_water_reviewer_listing_roommates_l11():
    r = P(listing("r27-roommates-l11.txt"))
    assert r["utilities_estimate"] == 40
    assert "water" in pays(r) and "electric" in pays(r)
    assert "not counted anywhere" not in notes(r)
    assert "unclear about" not in notes(r)  # hot water included and cold water paid is not a conflict


# ---- 4. contradiction notes
def test_heat_and_water_included_vs_all_except_water():
    r = P(listing("r27-nontech-l37.txt"))
    assert "heat" in pays(r) and "heat" not in inc(r)
    assert inc(r) == {"water"}
    assert r["utilities_estimate"] == 110
    assert notes(r).count("disagree about heat") == 1


@pytest.mark.parametrize("text", [
    HEAD + "Heat and water included. Tenant pays all utilities except water. Estimated $110 for electric and gas.",
    HEAD + "Heat included. All utilities except water paid by tenant, est. $110.",
    HEAD + "Tenant pays all utilities except water, est. $110. Heat is included.",
])
def test_conflict_about_heat_is_one_note_and_not_included(text):
    r = P(text)
    assert "heat" not in inc(r)
    assert "heat" in pays(r)
    assert notes(r).count("disagree about heat") == 1


def test_except_included_note_matches_text():
    r = P(listing("r27-uiuc-l16.txt"))
    assert inc(r) == {"water", "sewer", "trash"}
    assert pays(r) == {"electric", "gas"}
    assert r["utilities_estimate"] == 90
    assert "electric and gas are included" not in notes(r)


@pytest.mark.parametrize("text", [
    HEAD + "Utilities paid by tenant, except water/sewer/trash which are included. Electric and gas about $90 combined.",
    HEAD + "Tenant pays everything except water, sewer and trash (included). Electric and gas about $90 combined.",
    HEAD + "Tenant pays all utilities except water/sewer/trash, which are included. Electric and gas about $90 total.",
])
def test_included_except_never_says_electric_included(text):
    r = P(text)
    assert not ({"electric", "gas"} & inc(r))
    assert "electric and gas are included" not in notes(r).lower()
    assert r["utilities_estimate"] == 90
