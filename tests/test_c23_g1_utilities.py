"""Cycle 23 G1: utilities reader. A tenant-paid utility with no price is in tenant pays and unknown (every wording), a bill per two months or per
quarter is turned into a monthly figure, ranges and "up to" count the higher figure, "except electric (avg $40)" is read, "heat is gas" is gas only,
"HOA covers water" next to "water $25" stays unknown with a note, internet follows one rule, and an included trash stays included.
Each item has the reviewer's wording plus other natural wordings, and each test pins exact field values."""
from __future__ import annotations

from pathlib import Path

import pytest

from prophelper import compare, money
from prophelper.parsers import parse_listing

HEAD = "2 bed apartment, $1,450/mo."


def read(text: str, head: str = HEAD) -> dict:
    sep = "\n" if "\n" in text else " "
    return parse_listing(head + sep + text, "")


def notes(r: dict) -> str:
    return str(r.get("found_in_listing") or "")


def pays_set(r: dict) -> set[str]:
    return {w.strip() for w in str(r.get("tenant_pays") or "").split(",") if w.strip()}


def included_set(r: dict) -> set[str]:
    return {w.strip() for w in str(r.get("utilities_included") or "").split(",") if w.strip()}


def cost_of(r: dict, text: str) -> tuple[dict, list[str]]:
    """What the place page and Compare would say, from the final saved fields."""
    place = dict(r)
    place["reader_notes"] = notes(r)
    place["listing_text"] = text
    c = money.true_monthly_cost(place, "rent")
    return c, compare._missing_names({**place, "cost": c})


PANEL = Path("/tmp/claude-0/-home-user-property-helper/be454331-cd61-59ba-9ebc-8cb8b7ec6a12/scratchpad/panel")


def saved(name: str) -> tuple[dict, str]:
    f = PANEL / f"{name}.txt"
    if not f.exists():
        pytest.skip("reviewer listing not on this machine")
    t = f.read_text(encoding="utf-8", errors="replace")
    return parse_listing(t, ""), t


# 1. a tenant-paid utility with no price -------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text,pays", [
    ("Water included. Electric: tenant. Trash $15 monthly.", {"electric"}),
    ("Water included. Tenant pays electric.", {"electric"}),
    ("Water included. Electric - resident responsibility.", {"electric"}),
    ("Water included. Resident pays: electric.", {"electric"}),
    ("Water included. Electric: renter.", {"electric"}),
    ("Utilities: electric: tenant, gas: tenant, water included.", {"electric", "gas"}),
    ("Gas: tenant. Water included.", {"gas"}),
    ("Water included\nElectric: tenant\nGas - tenant pays", {"electric", "gas"}),
])
def test_unpriced_tenant_utility_is_in_tenant_pays_and_unknown(text, pays):
    r = read(text)
    assert pays_set(r) == pays
    assert "water" in included_set(r) and not (included_set(r) & pays)
    assert r.get("utilities_estimate") is None
    c, missing = cost_of(r, HEAD + " " + text)
    assert c["uncounted"] and not c["all_in"]
    assert ", ".join(sorted(pays)) in ", ".join(sorted(w for w in " ".join(missing).replace(" and ", ", ").replace(",,", ",").split(", ") if w))


def test_nontech_l5_place_page_and_compare_agree():
    r, t = saved("r22-nontech-l5")
    assert pays_set(r) == {"electric"} and included_set(r) == {"water"}
    c, missing = cost_of(r, t)
    assert c["headline_each"].endswith("utilities (electric) not counted yet")
    assert missing == ["electric"]


# 2. a bill per two months or per quarter ----------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text,est,pays", [
    ("Resident pays gas & electric (avg $110 / 2 mo), water/sewer/trash flat $48.", 103, {"electric", "gas", "water", "sewer", "trash"}),
    ("Tenant pays electric and gas (avg $110 per 2 months), water/sewer/trash flat $48.", 103, {"electric", "gas", "water", "sewer", "trash"}),
    ("Tenant pays electric and gas, $110 every 2 months. Water included.", 55, {"electric", "gas"}),
    ("Tenant pays electric and gas, $110 bi-monthly. Water included.", 55, {"electric", "gas"}),
    ("Tenant pays electric and gas, billed every other month $110. Water included.", 55, {"electric", "gas"}),
    ("Tenant pays gas & electric (avg $110 / 2 mo).", 55, {"electric", "gas"}),
    ("Gas & electric: about $110 /2 mo. Water and sewer included.", 55, {"electric", "gas"}),
    ("Electric $110 every two months. Water included.", 55, {"electric"}),
    ("Tenant pays water, about $90 per quarter. Electric included.", 30, {"water"}),
    ("Tenant pays water, $90/qtr. Electric included.", 30, {"water"}),
    ("Tenant pays water, $90 quarterly. Electric included.", 30, {"water"}),
])
def test_bill_per_period_is_a_monthly_figure(text, est, pays):
    r = read(text)
    assert r.get("utilities_estimate") == est, (r.get("utilities_estimate"), notes(r))
    assert pays_set(r) == pays
    low = notes(r).lower()
    assert ("two months" in low) or ("quarter" in low)
    assert "not counted anywhere" not in low


@pytest.mark.parametrize("text", [
    "Electric $55 (bi-monthly $110). Water included.",
    "Electric $55 a month (that is $110 every 2 months). Water included.",
    "Tenant pays electric about $55/mo ($110 bi-monthly). Water included.",
])
def test_monthly_figure_with_its_restatement_counts_once(text):
    r = read(text)
    assert r.get("utilities_estimate") == 55, (r.get("utilities_estimate"), notes(r))
    assert pays_set(r) == {"electric"}


def test_uiuc_l19_saved_listing():
    r, _t = saved("r22-uiuc-l19")
    assert r.get("utilities_estimate") == 103 and "$55 a month" in notes(r)


# 3. ranges and "up to" count the higher figure ------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text,est,pays,hi", [
    ("Gas: $80-$120 winter, $25 summer. Electric $50. Water & trash included.", 170, {"electric", "gas"}, "$120"),
    ("Tenant pays gas, $80 to $120 in winter, $25 in summer. Water included.", 120, {"gas"}, "$120"),
    ("Tenant pays gas and electric. Gas $80-$120 winter, $25 summer.", 120, {"electric", "gas"}, "$120"),
    ("Utilities: tenant pays all (electric, gas, water) - approx $215 total, summer lower, winter higher up to $260", 260, {"electric", "gas", "water"}, "$260"),
    ("Tenant pays electric, gas and water, about $215 a month, winter bills go up to $260.", 260, {"electric", "gas", "water"}, "$260"),
    ("Tenant pays electric and gas, up to $200 a month in winter. Water included.", 200, {"electric", "gas"}, "$200"),
    ("Tenant pays all utilities except trash. Typical total $135-$160 per month.", 160, {"electric", "gas", "water", "sewer", "heat"}, "$160"),
    ("Tenant pays all utilities. Utilities average $135 to $160 a month.", 160, {"electric", "gas", "water", "sewer", "trash", "heat"}, "$160"),
    ("Tenant pays electric and gas, roughly $135-$160 a month. Water included.", 160, {"electric", "gas"}, "$160"),
    ("Electric $60 to $90 a month. Tenant pays. Water included.", 90, {"electric"}, "$90"),
])
def test_range_and_up_to_count_the_higher_figure(text, est, pays, hi):
    r = read(text)
    assert r.get("utilities_estimate") == est, (r.get("utilities_estimate"), notes(r))
    assert pays_set(r) == pays
    low = notes(r).lower()
    assert "higher" in low and hi in notes(r)
    assert "not counted anywhere" not in low


def test_roommates_l45_l53_and_uiuc_l22_saved_listings():
    r, _ = saved("r22-roommates-l45")
    assert r.get("utilities_estimate") == 170 and pays_set(r) == {"electric", "gas"} and included_set(r) == {"water", "trash"}
    r, _ = saved("r22-roommates-l53")
    assert r.get("utilities_estimate") == 260 and "not counted anywhere" not in notes(r)
    r, t = saved("r22-uiuc-l22")
    assert r.get("utilities_estimate") == 160 and included_set(r) == {"trash"}
    c, missing = cost_of(r, t)
    assert not any("$135" in m or "$160" in m for m in missing)


# 4. "included except electric (electric avg $40)" ------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text,est,pays", [
    ("All utilities included in rent except internet and electric (electric avg $40).", 40, {"electric", "internet"}),
    ("All utilities included except electric (avg $40).", 40, {"electric"}),
    ("All utilities are included in the rent except electric, which averages $40 a month.", 40, {"electric"}),
    ("All utilities included, except electric ($40/mo typical).", 40, {"electric"}),
    ("Everything included except electric (~$40) and internet.", 40, {"electric", "internet"}),
])
def test_included_except_with_a_price_counts_the_price(text, est, pays):
    r = read(text)
    assert r.get("utilities_estimate") == est, (r.get("utilities_estimate"), notes(r))
    assert pays_set(r) == pays
    assert included_set(r) == {"gas", "water", "sewer", "trash", "heat"}
    c, missing = cost_of(r, HEAD + " " + text)
    assert "electric" not in " ".join(missing)
    assert "not counted anywhere" not in notes(r)


def test_roommates_l51_saved_listing():
    r, t = saved("r22-roommates-l51")
    c, missing = cost_of(r, t)
    assert r.get("utilities_estimate") == 40 and missing == ["internet"]


# 5. heat is gas -----------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "Heat is gas. Tenant pays gas, electric. Water/sewer/trash paid by owner.",
    "Heating: gas. Tenant pays electric and gas. Water, sewer and trash included.",
    "Gas heat. Tenant pays gas and electric. Water/sewer/trash included.",
    "Tenant pays heat and electric. Heat is gas. Water/sewer/trash included.",
])
def test_heat_is_gas_is_gas_only(text):
    r = read(text)
    assert pays_set(r) == {"electric", "gas"}
    assert r.get("utilities_estimate") is None
    c, missing = cost_of(r, HEAD + " " + text)
    assert missing == ["electric and gas"]


def test_family_l64_saved_listing():
    r, t = saved("r22-family-l64")
    assert pays_set(r) == {"electric", "gas"}
    assert cost_of(r, t)[1] == ["electric and gas"]


# 6. HOA covers water together with water $25 -----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "Water $25 a month. The HOA covers water.",
    "HOA covers water and trash. Tenant pays water $25, electric and gas.",
    "Water: $25/mo. Water is covered by the HOA. Electric and gas tenant.",
    "Tenant pays electric, gas, and water ($25). HOA includes water.",
])
def test_hoa_covers_water_and_water_has_a_price_is_a_conflict(text):
    r = read(text)
    assert r.get("utilities_estimate") is None, (r.get("utilities_estimate"), notes(r))
    assert "water" in pays_set(r) and "water" not in included_set(r)
    low = notes(r)
    assert "HOA covers water" in low and "$25" in low and "Ask which is right" in low
    c, missing = cost_of(r, HEAD + " " + text)
    assert "water" in " ".join(missing)


def test_family_l51_saved_listing():
    r, t = saved("r22-family-l51")
    assert "water" in pays_set(r) and "water" not in included_set(r)
    assert "ask which is right" in notes(r).lower()
    assert "water" in " ".join(cost_of(r, t)[1])


def test_hoa_covers_water_with_no_price_stays_included():
    r = read("HOA covers water and trash. Tenant pays electric ($70) and gas ($80).")
    assert r.get("utilities_estimate") == 150 and included_set(r) == {"water", "trash"}


# 7. internet: one rule ----------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "Electric $60. Internet (Comcast ~$70). Heat included.",
    "Heat included. Electric $60, internet (Xfinity ~$70).",
    "Heat included\nElectric $60\nInternet (Comcast ~$70)",
])
def test_internet_with_a_price_but_no_payer_is_unknown_and_named_as_internet(text):
    r = read(text)
    assert r.get("utilities_estimate") == 60
    assert "internet" not in pays_set(r)
    assert "does not say you must pay it" in notes(r)
    c, missing = cost_of(r, HEAD + " " + text)
    assert missing == ["internet"] and "$70" not in c["headline_each"]


@pytest.mark.parametrize("text", [
    "Electric $60. Internet (Comcast ~$70) optional. Heat included.",
    "Heat included. Electric $60. Internet is your choice (Comcast ~$70).",
    "Heat included\nElectric $60\nInternet available through Xfinity for $70/mo if you want it",
])
def test_optional_internet_is_not_counted_and_never_missing(text):
    r = read(text)
    assert r.get("utilities_estimate") == 60
    c, missing = cost_of(r, HEAD + " " + text)
    assert missing == [] and c["uncounted"] == [] and c["headline_each"] == "$1,510/mo"
    assert "internet" in notes(r).lower() and "$70" in notes(r)


@pytest.mark.parametrize("text", [
    "Heat included. Electric $60. Internet: tenant arranges own (Comcast ~$60).",
    "Heat included. Electric $60. Tenant sets up internet with Comcast, about $60.",
])
def test_internet_the_tenant_arranges_with_a_price_is_counted(text):
    r = read(text)
    assert r.get("utilities_estimate") == 120, (r.get("utilities_estimate"), notes(r))
    assert "internet" in pays_set(r)
    c, missing = cost_of(r, HEAD + " " + text)
    assert missing == []


# 8. trash pickup included ---------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "Tenant pays all utilities (est. $140/mo electric). Trash pickup included.",
    "Tenant pays all utilities (est. $140/mo electric). Trash collection included.",
    "Tenant pays all utilities, electric est. $140/mo. Trash service is included in the rent.",
])
def test_trash_included_once_wins_over_all_utilities(text):
    r = read(text)
    assert included_set(r) == {"trash"}
    assert "trash" not in pays_set(r)
    assert r.get("utilities_estimate") == 140


def test_trash_included_and_paid_stays_unknown_with_a_note():
    r = read("Tenant pays electric, gas, water, sewer and trash. Trash pickup included.")
    assert "trash" in pays_set(r) and "trash" not in included_set(r)
    assert "unclear about trash" in notes(r)


def test_nontech_l6_saved_listing():
    r, _ = saved("r22-nontech-l6")
    assert "trash" in included_set(r) and "trash" not in pays_set(r)
