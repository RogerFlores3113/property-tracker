"""Cycle 32 group G1: utilities reader. Rule (s): a "typical bills", "average utilities" or "utilities about" figure is the estimate whatever sentence comes
before or after it (after "Electric included? No.", after "gas and electric are tenant paid;", before the pay list, after "heat and water included");
a figure right after its own name belongs to that name ("electric about $70, internet"); two plain figures for one utility keep the higher one with
one note ("Electric is $55/mo. Electric: $60/month."); "ALL UTILITIES INCLUDED" beside a tenant-pays line is a conflict note; an included utility's seasonal
figures are not a missing amount."""
import os

import pytest

from prophelper import compare, money
from prophelper.parsers import parse_listing

HEAD = "Rent $2,100. 2 bed 1 bath. "


def P(text):
    return parse_listing(text, "")


def notes(r):
    return r.get("found_in_listing") or ""


def _set(v):
    return {w.strip() for w in (v or "").split(",") if w.strip()}


def missing(text):
    r = P(text)
    place = dict(r, reader_notes=r.get("found_in_listing"), listing_text=text)
    c = money.true_monthly_cost(place, "rent")
    return r, c, compare._missing_names(dict(place, cost=c, score={"unknown": []}))


def saved(name):
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel")
    return open(os.path.join(base, name + ".txt"), encoding="utf-8").read()


# ---- 1. "Typical bills for the unit about $X" after a tenant-pays line, in every order and punctuation
AFTER_ALL = [
    "Tenant pays all utilities. Typical bills for the unit about $180 per month.",
    "Tenant pays all utilities. Typical bills for the unit about $180 per month; gas heat.",
    "Tenant pays all utilities. Electric included? No. Typical bills for the unit about $180 per month; gas heat.",
    "Tenant pays all utilities; typical bills for the unit about $180 per month.",
    "TENANT PAYS ALL UTILITIES. TYPICAL BILLS FOR THE UNIT ABOUT $180 PER MONTH.",
    "Tenant pays all utilities.\nTypical bills for the unit about $180 per month.",
    "Utilities: tenant pays all (typical bills for the unit about $180 per month).",
    "- Tenant pays all utilities\n- Electric included? No.\n- Typical bills for the unit about $180/mo",
    "Tenant pays all utilities | Typical bills for the unit about $180 a month | gas heat",
]


@pytest.mark.parametrize("body", AFTER_ALL)
def test_typical_bills_after_tenant_pays_all(body):
    r, c, miss = missing(HEAD + body)
    assert r["utilities_estimate"] == 180, notes(r)
    assert _set(r["tenant_pays"]) == {"electric", "gas", "water", "sewer", "trash"}
    assert "monthly fee" not in notes(r)
    assert "not counted anywhere" not in notes(r)
    assert miss == [], miss


TENANT_PAID = [
    "Utilities: gas and electric are tenant paid; Typical bills for the unit about $160/mo.",
    "Utilities: gas and electric are tenant paid; typical bills for the unit about $160/mo.",
    "Gas and electric are tenant-paid. Typical bills for the unit about $160/mo.",
    "Gas and electric: tenant paid.\nTypical bills for the unit about $160 a month.",
    "Utilities: gas and electric are resident paid; typical bills for the unit about $160/mo; water included.",
    "Gas and electric are paid by the tenant; typical bills about $160 per month.",
    "Gas and electric are the tenant's responsibility. Typical bills for the unit about $160.",
]


@pytest.mark.parametrize("body", TENANT_PAID)
def test_typical_bills_after_tenant_paid_wording(body):
    r, c, miss = missing(HEAD + body)
    assert r["utilities_estimate"] == 160, notes(r)
    assert {"electric", "gas"} <= _set(r["tenant_pays"])
    assert "not counted anywhere" not in notes(r)
    assert "monthly fee" not in notes(r)
    assert miss == [], miss


def test_nontech_l6_whole_listing():
    r, c, miss = missing(saved("r31-nontech-l6"))
    assert r["utilities_estimate"] == 180
    assert _set(r["tenant_pays"]) == {"electric", "gas", "water", "sewer", "trash"}
    assert "monthly fee" not in notes(r)
    assert not any("$180" in m for m in miss), miss


def test_nontech_l11_whole_listing():
    r, c, miss = missing(saved("r31-nontech-l11"))
    assert r["utilities_estimate"] == 180
    assert "monthly fee" not in notes(r)
    assert not any("$180" in m for m in miss), miss


def test_nontech_l12_whole_listing():
    r, c, miss = missing(saved("r31-nontech-l12"))
    assert r["utilities_estimate"] == 160
    assert _set(r["tenant_pays"]) == {"electric", "gas"}
    assert "Typical bills for the unit about $160/mo\". It" not in notes(r)  # the typical bills are the estimate, never an uncounted line
    assert "$160" in notes(r)
    assert not any("$160" in m for m in miss), miss


def test_roommates_l31_whole_listing_estimate():
    r = P(saved("r31-roommates-l31"))
    assert r["utilities_estimate"] == 210
    assert "internet" in _set(r["tenant_pays"])
    assert "not counted anywhere" not in notes(r)
    assert "$210" in notes(r)


# negatives: a figure that is not the utilities estimate is never taken for it
@pytest.mark.parametrize("body", [
    "Tenant pays all utilities. Parking about $180 per month.",
    "Tenant pays all utilities. Typical pet rent about $35 per month.",
    "Tenant pays all utilities. Typical application fee about $50.",
])
def test_negative_other_typical_figures_are_not_utilities(body):
    r = P(HEAD + body)
    assert r.get("utilities_estimate") in (None, 0)


def test_negative_typical_bills_with_no_payer_line_is_not_counted_as_the_estimate_of_included():
    r = P(HEAD + "All utilities included. Typical bills for the unit about $180 per month.")
    assert r.get("utilities_estimate") in (None, 0)
    assert "tenant_pays" not in r or not r["tenant_pays"]


# ---- 2. the estimate first, then the pay list
EST_FIRST = [
    "Typical bills for the unit about $140; resident pays electric, gas.",
    "Typical bills for the unit about $140. Resident pays electric, gas.",
    "Typical bills for the unit about $140, resident pays electric and gas.",
    "Typical bills for the unit about $140.\nResident pays electric, gas.",
    "TYPICAL BILLS FOR THE UNIT ABOUT $140; TENANT PAYS ELECTRIC, GAS.",
    "Typical bills for the unit about $140 (tenant pays electric, gas).",
]


@pytest.mark.parametrize("body", EST_FIRST)
def test_estimate_first_then_pay_list(body):
    r, c, miss = missing(HEAD + body)
    assert r["utilities_estimate"] == 140, notes(r)
    assert _set(r["tenant_pays"]) == {"electric", "gas"}
    assert "not counted anywhere" not in notes(r)
    assert miss == [], miss


def test_uiuc_l1_whole_listing():
    r, c, miss = missing(saved("r31-uiuc-l1"))
    assert r["utilities_estimate"] == 175  # $140 typical bills + the $35 flat water/sewer/trash
    assert not any("$140" in m for m in miss), miss
    assert "$140" in notes(r)


# ---- 3. "Heat and water included; typical bills ..." is never called a monthly fee
HEAT_WATER = [
    "Heat and water included; typical bills for the unit about $120 a month.",
    "Heat and water included. Typical bills for the unit about $120 a month.",
    "Heat and water are included, typical bills for the unit about $120 per month.",
    "Typical bills for the unit about $120 a month. Heat and water included.",
    "Included: heat, water\nTypical bills for the unit about $120/mo",
]


@pytest.mark.parametrize("body", HEAT_WATER)
def test_heat_water_included_typical_bills_is_not_a_monthly_fee(body):
    r = P(HEAD + body)
    assert "monthly fee" not in notes(r), notes(r)
    assert "$120" in notes(r)  # never dropped silently
    assert _set(r.get("utilities_included")) == {"heat", "water"}


def test_roommates_l26_whole_listing():
    r = P(saved("r31-roommates-l26"))
    assert "monthly fee" not in notes(r)
    assert "$120" in notes(r)
    assert _set(r.get("utilities_included")) == {"heat", "water"}
    assert r["deposit"] == 1500
    assert r["pet_fee"] == 300


# ---- 4. a figure right after its own name belongs to that name
OWN_NAME = [
    "Resident pays electric about $70, internet.",
    "Resident pays electric about $70 and internet.",
    "Resident pays electric about $70, internet, trash.",
    "Utilities: electric about $70, internet (tenant pays)",
    "Tenant pays electric approx. $70/mo, internet.",
    "Tenant pays: electric about $70\nTenant pays: internet",
    "RESIDENT PAYS ELECTRIC ABOUT $70, INTERNET.",
]


@pytest.mark.parametrize("body", OWN_NAME)
def test_figure_after_a_name_prices_that_name(body):
    r, c, miss = missing(HEAD + body)
    assert r["utilities_estimate"] == 70, notes(r)
    assert "internet" in _set(r["tenant_pays"])
    assert "electric" in _set(r["tenant_pays"])
    assert "Internet is about" not in notes(r)
    assert "Internet and trash are about" not in notes(r)
    assert "internet" in " ".join(miss), miss  # internet has no price: it stays unknown


def test_gas_figure_then_electric_prices_gas():
    r, c, miss = missing(HEAD + "Tenant pays gas about $40, electric.")
    assert r["utilities_estimate"] == 40
    assert notes(r).startswith("Gas is about $40") or "Gas is about $40" in notes(r)
    assert "electric" in " ".join(miss), miss


def test_roommates_l36_whole_listing():
    r, c, miss = missing(saved("r31-roommates-l36"))
    assert r["utilities_estimate"] == 70
    assert _set(r["tenant_pays"]) == {"electric", "internet"}
    assert "Internet is about" not in notes(r)
    assert any("internet" in m for m in miss), miss


@pytest.mark.parametrize("body", [
    "Electric $55, gas $30.",
    "Tenant pays $55 electric, $30 gas.",
    "Tenant pays electric $55, gas $30, water $20",
    "Tenant pays electric ($55) and gas ($30).",
])
def test_negative_separate_figures_for_each_name_still_add(body):
    r = P(HEAD + body)
    assert r["utilities_estimate"] in (85, 105), (body, r.get("utilities_estimate"))


# ---- 5. two plain figures for one utility: one consistent read
TWO_ELEC = [
    "Electric is $55/mo. Electric: $60/month.",
    "Electric $55/mo. Electric: $60/month.",
    "Electric is $60/month. Electric: $55/mo.",
    "Electric is $55/mo. Electric is $60/month.",
    "Tenant pays electric. Electric is $55/mo. Electric: $60/month.",
    "Electric: $55/mo\nElectric: $60/month",
    "Electric is $55/mo; electric: $60/month.",
]


@pytest.mark.parametrize("body", TWO_ELEC)
def test_two_figures_for_one_utility_keep_the_higher_with_one_note(body):
    r, c, miss = missing(HEAD + body)
    assert r["utilities_estimate"] == 60, notes(r)
    assert _set(r["tenant_pays"]) == {"electric"}
    assert "$55" in notes(r)  # the other figure is named, not dropped
    assert "not counted anywhere" not in notes(r)
    assert miss == [], miss


def test_negative_one_electric_figure_is_just_counted():
    r = P(HEAD + "Electric is $55/mo.")
    assert r["utilities_estimate"] == 55
    assert "not counted anywhere" not in notes(r)


# ---- 6. electric ($65), typical bills for the unit $140, gas for cooking
MIXED = [
    "Heat included; tenant pays electric ($65); typical bills for the unit about $140; gas for cooking.",
    "Heat included. Tenant pays electric ($65). Gas for cooking. Typical bills for the unit about $140.",
    "Tenant pays electric ($65). Typical bills for the unit about $140. Gas for cooking.",
    "Tenant pays electric ($65) and gas. Typical bills for the unit about $140.",
    "Typical bills for the unit about $140. Tenant pays electric ($65); gas for cooking.",
    "Tenant pays electric ($65)\nTypical bills for the unit about $140\nGas for cooking",
]


@pytest.mark.parametrize("body", MIXED)
def test_priced_electric_beside_a_typical_total(body):
    r, c, miss = missing(HEAD + body)
    assert r["utilities_estimate"] == 140, notes(r)  # the whole bill, never the lower $65
    assert "electric" in _set(r["tenant_pays"])
    assert "not counted anywhere" not in notes(r)
    assert miss == [], miss


def test_roommates_l33_whole_listing():
    r, c, miss = missing(saved("r31-roommates-l33"))
    assert r["utilities_estimate"] == 140
    assert _set(r.get("utilities_included")) == {"heat"}
    assert "not counted anywhere" not in notes(r)
    assert not any("$65" in m or "$140" in m for m in miss), miss


def test_negative_typical_lower_than_named_keeps_the_higher():
    r = P(HEAD + "Tenant pays electric ($95) and gas ($60). Typical bills for the unit about $120.")
    assert r["utilities_estimate"] >= 155


# ---- 7. "ALL UTILITIES INCLUDED" beside a tenant-pays line
CONFLICT = [
    "ALL UTILITIES INCLUDED\nTenant pays electric and internet. Estimated total for those: $110/month.",
    "All utilities included.\nTenant pays electric and internet. Estimated total for those: $110/month.",
    "Tenant pays electric and internet. Estimated total for those: $110/month.\nALL UTILITIES INCLUDED",
    "ALL UTILITIES INCLUDED. Tenant pays electric and internet (estimated total $110/month).",
    "ALL UTILITIES INCLUDED! Tenant pays electric and internet, est. $110 per month for both.",
]


@pytest.mark.parametrize("body", CONFLICT)
def test_all_included_headline_beside_tenant_pays_is_a_conflict(body):
    r = P("Quad Edge Residences\n1BR/1BA $1,575 per month.\n" + body)
    assert not r.get("utilities_included"), r.get("utilities_included")
    assert _set(r["tenant_pays"]) == {"electric", "internet"}
    assert "included, but it also says you pay electric, internet" in notes(r)
    assert r.get("utilities_estimate") == 110  # the higher, tenant-side figure stays counted


def test_uiuc_l10_whole_listing():
    r = P(saved("r31-uiuc-l10"))
    assert r["price"] == 1575
    assert not r.get("utilities_included")
    assert _set(r["tenant_pays"]) == {"electric", "internet"}
    assert r["utilities_estimate"] == 110
    assert "included, but it also says you pay" in notes(r)


def test_negative_all_included_alone_stays_included():
    r = P("Quad Edge Residences\n1BR/1BA $1,575 per month.\nALL UTILITIES INCLUDED\nW/D in unit.")
    assert r.get("utilities_included") == "all"
    assert "included, but it also says you pay" not in notes(r)


def test_negative_all_except_is_not_a_conflict():
    r = P("Quad Edge Residences\n1BR/1BA $1,575 per month.\nAll utilities included except electric. Electric about $70.")
    assert "included, but it also says you pay" not in notes(r)
    assert r.get("utilities_estimate") == 70


# ---- 8. an included utility's seasonal figures are not a missing amount
SEASONAL = [
    "Electric included, approx $55 summer, $60 winter. All other utilities paid by tenant.",
    "Electric is included (approx $55 in summer, $60 in winter). All other utilities paid by tenant.",
    "Electric included, about $55 in summer and $60 in winter.\nAll other utilities are paid by the tenant.",
    "Electric included - approx $55 summer / $60 winter. Gas, water and internet paid by tenant.",
    "ELECTRIC INCLUDED, APPROX $55 SUMMER, $60 WINTER. ALL OTHER UTILITIES PAID BY TENANT.",
]


@pytest.mark.parametrize("body", SEASONAL)
def test_included_electric_with_seasonal_figures_is_not_missing(body):
    r, c, miss = missing(HEAD + body)
    assert "electric" in _set(r["utilities_included"])
    assert not r.get("utilities_estimate")
    assert not any("$55" in m or "$60" in m for m in miss), miss
    assert "$55" in notes(r) and "$60" in notes(r)  # named, never dropped
    assert "not counted anywhere" not in notes(r)
    assert "$55 and $60" not in c.get("headline", "") if isinstance(c, dict) else True


def test_uiuc_l6_whole_listing():
    r, c, miss = missing(saved("r31-uiuc-l6"))
    assert r["price"] == 1480
    assert _set(r["utilities_included"]) >= {"electric", "trash"}
    assert not any("$55" in m or "$60" in m for m in miss), miss
    assert r["pet_fee"] == 200
    assert r["deposit"] == 300


def test_negative_electric_cap_is_not_called_a_plain_included():
    r = P(HEAD + "Electric included up to $40. Tenant pays the rest.")
    assert "$40" in notes(r)


def test_negative_tenant_electric_with_seasonal_figures_is_not_touched():
    r = P(HEAD + "Tenant pays electric, approx $55 summer, $60 winter.")
    assert r["utilities_estimate"] == 60
    assert "electric" in _set(r["tenant_pays"])
