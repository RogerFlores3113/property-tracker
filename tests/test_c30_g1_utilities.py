"""Cycle 30 group G1: utilities reader. "Typical bills/total for the unit about $X/mo" is the utilities estimate in every layout, a utility admin
fee keeps its cents and is never also listed as missing, "Landlord pays all utilities" next to a tenant-pays line is a conflict, two estimates
for a utility the listing also calls included leave it unknown with one note, and "Everything but internet included. Resident pays internet."
is not a conflict."""
import os

import pytest

from prophelper.parsers import parse_listing


def P(text):
    return parse_listing(text, "")


def notes(r):
    return r.get("found_in_listing") or ""


def _set(v):
    return {w.strip() for w in (v or "").split(",") if w.strip()}


def listing(name):
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel")
    return open(os.path.join(base, name), encoding="utf-8").read()


# ---- 1. typical bills / total for the unit is the utilities estimate
TYPICAL = [
    "Typical bills for the unit run about $140/mo. Tenant pays electric and gas.",
    "Tenant pays electric and gas. Typical total bills for the unit about $140/mo.",
    "Tenant pays electric and gas. Typical total for the unit runs about $140 per month.",
    "Tenant pays electric and gas.\nTypical bills for the apartment about $140/month.",
    "- Tenant pays electric and gas\n- Typical total bills for the unit about $140/mo",
]


@pytest.mark.parametrize("body", TYPICAL)
def test_typical_bills_for_the_unit_is_the_estimate(body):
    r = P("3 BR 2 BA Rogers Park. Rent $3,050/mo. " + body)
    assert r["utilities_estimate"] == 140
    assert _set(r["tenant_pays"]) == {"electric", "gas"}
    assert "not counted anywhere" not in notes(r)
    assert "$140" not in notes(r).split("counted as your utilities estimate")[0].replace("about $140 a month", "")


@pytest.mark.parametrize("body", [
    "Everything but electric included. Typical total bills for the unit about $140/mo.",
    "Everything but electric is included. Typical bills for the unit run about $140/mo.",
    "All utilities included except electric. Typical total for the unit about $140 a month.",
])
def test_typical_bills_after_everything_but_electric(body):
    r = P("Rent $2,995. " + body)
    assert r["utilities_estimate"] == 140
    assert _set(r["tenant_pays"]) == {"electric"}
    assert "electric" not in _set(r.get("utilities_included"))
    assert "not counted anywhere" not in notes(r)


# ---- 2. utility admin fee keeps cents and is never also "not counted"
@pytest.mark.parametrize("fee", [
    "Utility admin fee $9.95/mo.",
    "Utility admin fee: $9.95 per month.",
    "Monthly utility admin fee $9.95.",
    "Utility billing fee $9.95/month.",
])
def test_utility_admin_fee_keeps_cents(fee):
    r = P("Rent $3,050/mo. Tenant pays electric and gas. " + fee)
    assert r["other_monthly_fees"] == 9.95
    assert "not counted anywhere" not in notes(r)
    assert "$9/month" not in notes(r)
    assert not r.get("move_in_fees")


def test_roommates_l5_and_l13_listings():
    r = P(listing("r29-roommates-l13.txt"))
    assert r["utilities_estimate"] == 140
    assert r["other_monthly_fees"] == 9.95
    assert _set(r["tenant_pays"]) == {"electric", "gas"}
    assert "not counted anywhere" not in notes(r)
    r = P(listing("r29-roommates-l5.txt"))
    assert r["utilities_estimate"] == 140
    assert r["other_monthly_fees"] == 9.95
    assert _set(r["tenant_pays"]) == {"electric"}
    assert _set(r["utilities_included"]) == {"heat", "gas", "water"}
    assert "not counted anywhere" not in notes(r)


# ---- 3. two estimates for a utility the listing calls included: one conflict note, electric unknown
TWO_EST = [
    "All utilities included. Estimated electric $90. Estimated electric $110.",
    "All utilities included except cable and internet. Estimated electric $90. Estimated electric $110.",
    "All utilities included.\nElectric about $90.\nElectric about $110.",
]


@pytest.mark.parametrize("body", TWO_EST)
def test_two_electric_estimates_with_included_is_one_conflict(body):
    r = P("Rent $3,100/mo. " + body)
    assert "utilities_estimate" not in r
    assert "electric" in _set(r["tenant_pays"])
    assert "electric" not in _set(r.get("utilities_included"))
    n = notes(r)
    assert n.count("two different figures for electric") == 1
    assert "$90" in n and "$110" in n
    assert "not counted anywhere" not in n
    assert "is counted as" not in n.replace("Neither is counted", "")


def test_roommates_l8_listing():
    r = P(listing("r29-roommates-l8.txt"))
    assert r["utilities_estimate"] == 45
    assert "electric" in _set(r["tenant_pays"]) and "water" in _set(r["tenant_pays"])
    assert "electric" not in _set(r.get("utilities_included"))
    assert notes(r).count("two different figures for electric") == 1
    assert "not counted anywhere" not in notes(r)


def test_two_figures_for_a_tenant_paid_utility_keep_the_older_rule():
    r = P("Rent $1,800. Electric about $90. Electric about $70. Tenant pays electric.")
    assert r["utilities_estimate"] == 90


# ---- 4. Landlord pays all utilities next to a tenant-pays line
LL_ALL = [
    "Landlord pays sewer and trash, tenant pays electric, gas, water. Typical total: $180/mo. Utilities: Landlord pays all utilities.",
    "Utilities: Landlord pays all utilities. Landlord pays sewer and trash, tenant pays electric, gas, water. Typical total: $180/mo.",
]


@pytest.mark.parametrize("body", LL_ALL)
def test_landlord_pays_all_after_tenant_pays_is_a_conflict(body):
    r = P("2 Ash Ln, Belmont. Rent $2,340 per month. " + body)
    assert _set(r["tenant_pays"]) == {"electric", "gas", "water"}
    assert not ({"electric", "gas", "water"} & _set(r.get("utilities_included")))
    assert "utilities_estimate" not in r  # two lines that disagree: no amount is counted
    assert "disagree" in notes(r)
    assert "$180" in notes(r) and "is not counted" in notes(r)
    assert "counted as your utilities estimate" not in notes(r)


def test_tenant_pays_then_landlord_pays_all_on_the_next_line():
    r = P("Rent $2,340. Tenant pays electric, gas and water. Typical total $180/mo.\nLandlord pays all utilities.")
    assert "utilities_estimate" not in r
    assert _set(r["tenant_pays"]) == {"electric", "gas", "water"}
    assert not _set(r.get("utilities_included"))
    assert "also says you pay" in notes(r) and "$180" in notes(r)
    assert "counted as your utilities estimate" not in notes(r)


def test_family_l17_listing():
    r = P(listing("r29-family-l17.txt"))
    assert _set(r["tenant_pays"]) == {"electric", "gas", "water"}
    assert _set(r["utilities_included"]) == {"sewer", "trash"}
    assert "utilities_estimate" not in r
    assert notes(r).count("disagree") == 1
    assert "$180" in notes(r) and "counted as your utilities estimate" not in notes(r)


def test_family_l8_note_matches_what_is_counted():
    r = P(listing("r29-family-l8.txt"))
    assert r["utilities_estimate"] == 200
    n = notes(r)
    assert "left as something you pay with no amount" not in n
    assert "$200 a month the listing gives is counted" in n


@pytest.mark.parametrize("body", [
    "Landlord pays all utilities. Tenant pays internet.",
    "Landlord pays all utilities except electric. Tenant pays electric.",
])
def test_landlord_pays_all_with_internet_or_except_is_no_conflict(body):
    r = P("Rent $1,800. " + body)
    assert "disagree" not in notes(r)


# ---- 5. "Everything but internet included. Resident pays internet." is not a conflict
INTERNET = [
    "Everything but internet is included in rent. Resident pays internet.",
    "Everything but internet is included in rent.",
    "All utilities included except internet. Tenant pays internet.",
    "Everything but internet is covered by the owner.\nResident pays internet.",
    "Everything but wifi is included. Resident pays wifi.",
]


@pytest.mark.parametrize("body", INTERNET)
def test_everything_but_internet_is_not_a_conflict(body):
    r = P("Rent $1,800. " + body)
    assert _set(r["tenant_pays"]) == {"internet"}
    assert _set(r["utilities_included"]) >= {"electric", "gas", "water", "sewer", "trash"}
    assert "internet" not in _set(r["utilities_included"])
    assert "unclear about" not in notes(r)
    assert "one line says" not in notes(r)


def test_uiuc_l15_listing():
    r = P(listing("r29-uiuc-l15.txt"))
    assert _set(r["tenant_pays"]) == {"internet"}
    assert "unclear about internet" not in notes(r)
    assert r["other_monthly_fees"] == 12


def test_older_rubs_conflict_is_not_noted_twice():
    r = P(listing("r13-uiuc-l2.txt"))
    assert r["utilities_estimate"] == 45
    assert notes(r).count("landlord pays") == 1
    assert "also says you pay" not in notes(r)


def test_landlord_pays_all_then_tenant_electric_only_is_not_a_conflict():
    r = P("Rent $1,590. Landlord pays all utilities. Tenant electric only total $110.")
    assert r["utilities_estimate"] == 110
    assert _set(r["tenant_pays"]) == {"electric"}
    assert "disagree" not in notes(r)
