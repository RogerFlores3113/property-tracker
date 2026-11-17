"""Cycle 29 group G1: utilities reader. "Everything but X included" (both payers, every word order), "Landlord pays A, tenant pays B" with no
false conflict note, standalone "typical" or "estimated" sentences next to a tenant-pays list, two "all except" lines that disagree, a flat
package next to an estimate, a stale estimate after an update, and the utility admin fee counted once."""
import os

import pytest

from prophelper import money
from prophelper.parsers import parse_listing

HEAD = "Rent $1,800. "


def P(text):
    return parse_listing(text, "")


def notes(r):
    return r.get("found_in_listing") or ""


def _set(v):
    return {w.strip() for w in (v or "").split(",") if w.strip()}


def pays(r):
    return _set(r.get("tenant_pays"))


def inc(r):
    return _set(r.get("utilities_included"))


def listing(name):
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel")
    return open(os.path.join(base, name), encoding="utf-8").read()


# ---- 1. "everything but X": the tenant pays X, in every order, with either payer
LANDLORD_SIDE = [
    ("Everything but trash included in rent.", "trash"),
    ("Everything but trash is paid by the landlord.", "trash"),
    ("All except trash included.", "trash"),
    ("Everything except trash is included in the rent.", "trash"),
    ("All utilities except trash are included.", "trash"),
    ("Utilities: all except trash included", "trash"),
    ("Everything but trash included in rent. Cats ok.", "trash"),
    ("- Everything but trash is covered by the owner\n- Cats ok", "trash"),
    ("Everything but water paid by landlord", "water"),
    ("Everything other than sewer is included.", "sewer"),
]


@pytest.mark.parametrize("text,item", LANDLORD_SIDE)
def test_everything_but_x_included_means_tenant_pays_x(text, item):
    r = P(HEAD + text)
    assert item in pays(r)
    assert item not in inc(r)
    assert {"electric", "gas"} <= inc(r)
    assert "utilities_estimate" not in r


TENANT_SIDE = [
    ("Everything but trash is paid by tenant, about $140/mo. Trash is included.", "trash", 140),
    ("Everything but trash is paid by the tenant (budget about $140/mo). Trash is included.", "trash", 140),
    ("Tenant pays everything but trash, about $140/mo. Trash is included.", "trash", 140),
    ("Utilities: all except trash paid by tenant, est $140. Trash included.", "trash", 140),
    ("Tenant responsible for everything but trash, estimate $140 a month.", "trash", 140),
]


@pytest.mark.parametrize("text,item,est", TENANT_SIDE)
def test_everything_but_x_paid_by_tenant_estimate_is_for_the_rest(text, item, est):
    r = P(HEAD + text)
    assert item not in pays(r)
    assert {"electric", "gas", "water", "sewer"} <= pays(r)
    assert r["utilities_estimate"] == est
    assert f"{item.capitalize()} is about" not in notes(r)
    assert "not counted" not in notes(r)


def test_nontech_l46_l42_everything_but_trash():
    for name in ("r28-nontech-l46.txt", "r28-nontech-l42.txt"):
        r = P(listing(name))
        assert "trash" not in inc(r)
        assert "trash" in pays(r)
        assert {"electric", "gas", "water", "sewer"} <= inc(r)


def test_uiuc_l4_trash_included_estimate_not_labelled_trash():
    r = P(listing("r28-uiuc-l4.txt"))
    assert inc(r) == {"trash"}
    assert pays(r) == {"electric", "gas", "water", "sewer"}
    assert r["utilities_estimate"] == 140
    n = notes(r)
    assert "Trash is about" not in n
    assert "disagree" not in n and "unclear" not in n
    assert "not counted" not in n


def test_a_landlord_question_is_not_an_answer():
    r = P(HEAD + "Everything but trash is paid by tenant, about $140/mo. Landlord covers water/sewer? No - tenant pays. Trash is included.")
    assert pays(r) == {"electric", "gas", "water", "sewer"}
    assert "disagree" not in notes(r)


# ---- 2. "Landlord pays A, tenant pays B": no false disagree note
SPLIT = [
    ("Landlord pays water/sewer, tenant pays electric.", {"water", "sewer"}, {"electric"}),
    ("Tenant pays electric, landlord pays water and sewer.", {"water", "sewer"}, {"electric"}),
    ("Owner covers water/sewer, renter pays electric and gas.", {"water", "sewer"}, {"electric", "gas"}),
    ("Landlord pays trash, resident pays electric.", {"trash"}, {"electric"}),
    ("- Landlord pays water/sewer\n- Tenant pays electric", {"water", "sewer"}, {"electric"}),
    ("Water/sewer paid by landlord, electric paid by tenant.", {"water", "sewer"}, {"electric"}),
    ("Landlord pays water/sewer, tenant pays electric. Garage included. Updated: pet rent now $30.", {"water", "sewer"}, {"electric"}),
]


@pytest.mark.parametrize("text,landlord,tenant", SPLIT)
def test_two_parts_name_different_utilities(text, landlord, tenant):
    r = P(HEAD + text)
    assert inc(r) == landlord
    assert pays(r) == tenant
    assert "disagree" not in notes(r) and "unclear about" not in notes(r)


def test_nontech_l48_saved_listing():
    r = P(listing("r28-nontech-l48.txt"))
    assert inc(r) == {"water", "sewer"} and pays(r) == {"electric"}
    assert "unclear about" not in notes(r)


# ---- 3. estimates in their own sentence
ESTIMATES = [
    ("Tenant pays electric and gas. Estimated $110 per month.", 110, {"electric", "gas"}),
    ("Tenant pays electric and gas. Typical total $110.", 110, {"electric", "gas"}),
    ("Tenant pays electric and gas. Typically about $110 a month.", 110, {"electric", "gas"}),
    ("Tenant pays electric and gas.\nTypical monthly bills: $110", 110, {"electric", "gas"}),
    ("Tenant pays electric and gas. Budget $110/mo.", 110, {"electric", "gas"}),
    ("Tenant pays electric and gas | Typical bills run about $110 monthly", 110, {"electric", "gas"}),
    ("Tenant pays all utilities. Typical bills run about $150 monthly for everyone here.", 150, {"electric", "gas", "water", "sewer", "trash"}),
    ("Tenant pays all utilities except trash. Typical total $200.", 200, {"electric", "gas", "water", "sewer"}),
]


@pytest.mark.parametrize("text,est,names", ESTIMATES)
def test_standalone_estimate_is_the_utilities_estimate(text, est, names):
    r = P(HEAD + text)
    assert r["utilities_estimate"] == est
    assert pays(r) == names
    n = notes(r)
    assert "not counted" not in n and "monthly fee" not in n


@pytest.mark.parametrize("text", [
    "Tenant pays all utilities except water | Estimated electric+gas $120 | Water is included",
    "Tenant pays all utilities except water.\nEstimated electric+gas $120.",
    "All utilities paid by tenant, except water. Est. $120 for electric and gas. Water is included.",
])
def test_estimate_after_all_except_water_covers_the_named_ones(text):
    r = P(HEAD + text)
    assert r["utilities_estimate"] == 120
    assert pays(r) == {"electric", "gas", "sewer", "trash"}
    assert inc(r) == {"water"}
    assert "not counted" not in notes(r)


def test_roommates_l3_saved_listing():
    r = P(listing("r28-roommates-l3.txt"))
    assert r["utilities_estimate"] == 120
    assert "not counted" not in notes(r)
    assert inc(r) == {"water"}


def test_uiuc_l13_typical_total_beside_tenant_pays_list():
    r = P(listing("r28-uiuc-l13.txt"))
    assert r["utilities_estimate"] == 115
    assert pays(r) == {"electric", "gas", "water"} and inc(r) == {"sewer", "trash"}
    n = notes(r)
    assert "not counted" not in n and "does not say which utilities" not in n


def test_nontech_l43_typical_bills_monthly():
    r = P(listing("r28-nontech-l43.txt"))
    assert r["utilities_estimate"] == 150
    assert "Typical bills" not in notes(r)


def test_a_typical_range_still_counts_the_higher_figure():
    r = P(HEAD + "Tenant pays all utilities except trash. Typical total $135-$160 per month.")
    assert r["utilities_estimate"] == 160


def test_an_estimate_sentence_after_a_parking_line_is_not_a_utilities_estimate():
    r = P(HEAD + "Tenant pays electric and gas. Garage parking available. Estimated $110 per month.")
    assert r.get("utilities_estimate") in (None, 110)  # whichever way it is read it is never both a fee and a utilities figure
    assert not (r.get("utilities_estimate") == 110 and r.get("other_monthly_fees"))


# ---- 4. two lines that disagree
DISAGREE = [
    "Tenant responsible for everything but trash, about $200 a month. Resident pays all utilities except landlord covers water/sewer.",
    "Tenant pays everything but trash, about $200 a month. Tenant pays all utilities except water/sewer.",
    "Everything but trash is paid by the tenant, about $200/mo.\nAll utilities except water and sewer are paid by the tenant.",
    "Utilities: all except trash paid by tenant, about $200. Tenant pays all utilities except water and sewer.",
]


@pytest.mark.parametrize("text", DISAGREE)
def test_two_except_lines_that_disagree_leave_the_disputed_unknown(text):
    r = P(HEAD + text)
    assert inc(r) == set()
    assert pays(r) == {"electric", "gas", "water", "sewer", "trash"}
    assert notes(r).count("do not match") == 1
    assert "water, sewer and trash" in notes(r)


def test_family_l43():
    r = P(listing("r28-family-l43.txt"))
    assert inc(r) == set()
    assert pays(r) == {"electric", "gas", "water", "sewer", "trash"}
    assert r["utilities_estimate"] == 200
    assert notes(r).count("do not match") == 1


def test_two_except_lines_that_agree_have_no_note():
    r = P(HEAD + "Tenant pays all utilities except trash. Everything but trash is paid by tenant.")
    assert inc(r) == {"trash"}
    assert "do not match" not in notes(r)


# ---- 5. a flat package next to an estimate, and a stale estimate
def test_flat_package_next_to_a_total_estimate_is_counted_once():
    r = P(HEAD + "Tenant pays all utilities. Estimated $170/mo. Water/sewer/trash flat $45/mo.")
    assert r["utilities_estimate"] == 170
    n = notes(r)
    assert "not counted" not in n and "counted once" in n


@pytest.mark.parametrize("text", [
    "Tenant pays all utilities except trash. Estimated $125/mo for the utilities. Flat $45 water/sewer/trash package.",
    "All utilities paid by tenant except trash. Estimated $125/mo for the utilities. Flat $45 water/sewer/trash package.",
    "Tenant pays all utilities except trash. Estimated $125/mo for the utilities.\nWater/sewer/trash flat package $45 per month.",
])
def test_flat_package_that_prices_the_excepted_trash(text):
    r = P(HEAD + text)
    assert r["utilities_estimate"] == 170
    assert "trash" in pays(r) and "trash" not in inc(r)
    n = notes(r)
    assert "not counted" not in n and "overlap" in n


def test_uiuc_l6_cost_never_says_included_and_missing_trash():
    t = listing("r28-uiuc-l6.txt")
    r = P(t)
    assert r["utilities_estimate"] == 170
    assert "trash" not in inc(r)
    place = dict(r, listing_text=t)
    c = money.true_monthly_cost(place)
    # cycle 29 G3: the "Own garage included, price TBD" line leaves the parking cost unknown; nothing about utilities is missing
    assert [m for m in c["missing"] if m != "parking cost"] == [] and [u for u in c["uncounted"] if u != "parking"] == []
    util = next(l for l in c["lines"] if l["key"] == "utilities")
    assert "includes: trash" not in (util["note"] or "")


@pytest.mark.parametrize("text", [
    "Utilities: Tenant pays all utilities except sewer. Estimate $100 for all of it. Sewer included in rent. Update: Utilities are now paid by tenant entirely (est. $130).",
    "Utilities: Tenant pays all utilities except sewer. Estimate $100. Sewer included in rent.\nUpdate: Utilities are now paid by tenant entirely (est. $130).",
    "Tenant pays all utilities except sewer. Est. $100 for all of it. Update: all utilities are now paid by tenant (est. $130).",
])
def test_stale_estimate_after_an_update_is_superseded(text):
    r = P(HEAD + text)
    assert r["utilities_estimate"] == 130
    assert "heat" not in pays(r)
    assert inc(r) == set()
    n = notes(r)
    assert "not counted" not in n and "Check what it is for" not in n


def test_uiuc_l10_saved_listing_is_complete():
    t = listing("r28-uiuc-l10.txt")
    r = P(t)
    assert r["utilities_estimate"] == 130
    assert "heat" not in pays(r)
    assert "not counted" not in notes(r)
    c = money.true_monthly_cost(dict(r, listing_text=t))
    assert c["missing"] == []


def test_all_except_sewer_does_not_add_heat():
    r = P("1 bed. Rent $1,500. Heated garage $90/mo. Tenant pays all utilities except sewer. Sewer included in rent.")
    assert "heat" not in pays(r)


# ---- 6. the utility admin fee is one monthly fee
ADMIN = [
    ("Admin fee $25 per month utility billing.", 25),
    ("Monthly utility admin fee $25.", 25),
    ("Utility billing admin fee: $25/month.", 25),
    ("$25/mo utility billing admin fee.", 25),
    ("Tenant pays electric and gas. Admin fee of $25 per month for utility billing.", 25),
    ("- Utility billing fee: $25/mo\n- Cats ok", 25),
]


@pytest.mark.parametrize("text,fee", ADMIN)
def test_utility_admin_fee_is_a_monthly_fee_only(text, fee):
    r = P(HEAD + text)
    assert r["other_monthly_fees"] == fee
    assert not r.get("move_in_fees")
    assert "not counted" not in notes(r)


def test_a_one_time_admin_fee_stays_in_move_in_next_to_the_utility_admin_fee():
    r = P(HEAD + "Admin fee $250 one time. Utility admin fee $10/month.")
    assert r["other_monthly_fees"] == 10
    assert r["move_in_fees"] == 250


def test_nontech_l40_saved_listing_counts_the_admin_fee_once():
    r = P(listing("r28-nontech-l40.txt"))
    assert r["other_monthly_fees"] == 25
    assert not r.get("move_in_fees")
    assert r["utilities_estimate"] == 135
    assert inc(r) == {"sewer"}


def test_uiuc_l13_monthly_utility_admin_fee_not_in_move_in():
    r = P(listing("r28-uiuc-l13.txt"))
    assert r["other_monthly_fees"] == 10
    assert not r.get("move_in_fees")
    assert r["application_fee"] == 50
