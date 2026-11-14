"""Cycle 15 G1: utilities reader. A plain "Landlord pays all utilities." is all included, "Gas also tenant" is kept, a total
figure covers every utility the renter pays, no invented sums, heat abbreviations, a quarterly bill as a monthly estimate."""
from __future__ import annotations

from prophelper import money
from prophelper.parsers import listing_billed_amount, listing_estimate_names, parse_listing

RENT = "2 bed 1 bath $1,500/month\n"


def read(text: str) -> dict:
    out = parse_listing(RENT + text)
    out.pop("source", None)
    return out


def keys(out: dict) -> tuple:
    return tuple(out.get(k) for k in ("utilities_included", "tenant_pays", "utilities_estimate"))


def note(out: dict) -> str:
    return str(out.get("found_in_listing") or "")


def util_line(text: str) -> dict:
    out = read(text)
    place = dict(out, listing_text=RENT + text)
    place.setdefault("price", 1500)
    return next(line for line in money.true_monthly_cost(place)["lines"] if line["key"] == "utilities")


def missing(text: str) -> list:
    out = read(text)
    place = dict(out, listing_text=RENT + text)
    place.setdefault("price", 1500)
    return money.true_monthly_cost(place)["missing"]


# ---- 1. plain "Landlord pays all utilities."
def test_plain_landlord_pays_all():
    out = read("Landlord pays all utilities.")
    assert keys(out) == ("all", None, None)
    assert "could not tell who pays" not in note(out)
    assert util_line("Landlord pays all utilities.")["amount"] == 0


def test_landlord_pays_all_in_a_longer_listing():
    out = read("Cozy flat near campus. Landlord pays all utilities. Pets welcome.")
    assert out["utilities_included"] == "all"


def test_landlord_pays_all_with_rubs_stays_unknown():
    out = read("Landlord pays all utilities (RUBS billed back to residents).")
    assert out.get("utilities_included") in (None, "")
    assert out.get("utilities_estimate") is None


def test_landlord_pays_all_vs_tenant_pays_all_stays_unknown():
    out = read("Tenant pays all utilities. Landlord pays all utilities.")
    assert out.get("utilities_included") in (None, "")
    assert out.get("utilities_estimate") is None


def test_landlord_pays_all_vs_plus_utilities_stays_unknown():
    out = read("Rent $1,150 + utilities. Landlord pays all utilities.")
    assert out.get("utilities_included") in (None, "")


def test_landlord_pays_all_vs_electric_separate_stays_unknown():
    out = read("Landlord pays all utilities. Electric is separate, tenant pays.")
    assert out.get("utilities_included") != "all"
    assert "electric" in (out.get("tenant_pays") or "")


# ---- 2. "Gas also tenant"
def test_except_electric_gas_also_tenant():
    out = read("Landlord pays all utilities except electric. Gas also tenant.")
    assert keys(out) == (None, "electric, gas", None)


def test_juniper_court_gas_stays_tenant_paid_electric_priced():
    text = "Rent includes water, sewer and trash. Landlord pays all utilities except electric. Gas also tenant. Avg $70 electric."
    out = read(text)
    assert keys(out) == ("water, sewer, trash", "electric, gas", 70)
    assert listing_estimate_names(RENT + text) == ["electric"]
    assert missing(text) == ["gas"]
    assert "gas" in util_line(text)["note"]


# ---- 3. totals cover everything the renter pays
def test_total_for_everything():
    text = "Tenant pays electric and gas. Roughly $150 a month total for everything."
    out = read(text)
    assert keys(out) == (None, "electric, gas", 150)
    assert listing_estimate_names(RENT + text) == []
    assert missing(text) == []
    assert "Electric is about" not in note(out)


def test_gas_label_total_for_all_utilities():
    text = "Gas: roughly $150 a month total for all utilities"
    out = read(text)
    assert out["utilities_estimate"] == 150
    assert listing_estimate_names(RENT + text) == []
    assert missing(text) == []
    assert "Gas is about" not in note(out)
    assert "all the utilities you pay" in note(out)


def test_water_sewer_figure_and_total_for_everything():
    text = "Typically around $55 for water/sewer, roughly $150 a month total for everything"
    out = read(text)
    assert out["utilities_estimate"] == 150
    assert out["tenant_pays"] == "water, sewer"
    assert listing_estimate_names(RENT + text) == []
    assert missing(text) == []
    assert "Water and sewer are about $150" not in note(out)
    assert "all the utilities you pay" in note(out)


def test_budget_for_both_after_electric_and_gas_tenant():
    text = "Electric and gas are tenant responsibility (budget around $90/mo for both)"
    out = read(text)
    assert keys(out) == (None, "electric, gas", 90)
    assert listing_estimate_names(RENT + text) == ["electric", "gas"]
    assert missing(text) == []
    assert "not counted anywhere" not in note(out)


# ---- 4. no invented sums
def test_no_invented_sum_electric_and_gas():
    text = "Typically around $55 electric, avg $70 gas"
    out = read(text)
    assert keys(out) == (None, "electric, gas", 125)
    assert "$140" not in note(out)
    assert "covers more" not in note(out)
    assert "not counted anywhere" not in note(out)
    assert listing_billed_amount(RENT + text) == 125


def test_water_sewer_plus_electric_total_for_electric_and_gas():
    text = "Water/sewer approx $55/mo, electric roughly $90 total for electric and gas"
    out = read(text)
    assert out["utilities_estimate"] == 145
    assert out["tenant_pays"] == "electric, gas, water, sewer"
    assert "higher figure" not in note(out) and "Only the figure" not in note(out)
    assert "not counted anywhere" not in note(out)
    assert missing(text) == []


# ---- 5. heat, gas, internet
def test_heat_incl_all_caps():
    out = read("HEAT INCL.")
    assert keys(out) == ("heat", None, None)


def test_heat_incl_then_gas_tenant():
    out = read("HEAT INCL. Gas tenant.")
    assert keys(out) == ("heat", "gas", None)


def test_heat_is_gas_tenant_pays_counts_110_once():
    text = "Heat is gas, tenant pays, about $110"
    out = read(text)
    assert keys(out) == (None, "gas, heat", 110)
    assert listing_estimate_names(RENT + text) == ["gas", "heat"]
    assert missing(text) == []


def test_gas_cooking_electric_tenant():
    out = read("Gas cooking, electric tenant")
    assert keys(out) == (None, "electric, gas", None)
    assert "Gas is counted as something you pay, with no amount" in note(out)


def test_pipe_listing_gas_cooking_electric_tenant_no_internet():
    text = ("Pipes | Rent: $3,090 | Beds: 3 | Baths: 2 | Utilities: Heat + water included | Gas cooking, electric tenant | "
            "Parking: street permit $0")
    out = parse_listing(text)
    assert out["utilities_included"] == "heat, water"
    assert out["tenant_pays"] == "electric, gas"
    assert "internet" not in str(out.get("tenant_pays"))


def test_other_utilities_do_not_invent_internet():
    out = read("Utilities included: water, trash. Tenant pays all other utilities.")
    assert out["tenant_pays"] == "electric, gas, sewer"


def test_other_utilities_keep_internet_when_mentioned():
    out = read("Utilities included: water, trash. Tenant pays all other utilities. Internet is not provided.")
    assert "internet" in out["tenant_pays"]


# ---- 6. quarterly bill
def test_quarterly_water_bill_billed_back():
    text = "Quarterly water bill of $135 billed back"
    out = read(text)
    assert keys(out) == (None, "water", 45)
    assert "quarterly bill of $135" in note(out) and "$45 a month" in note(out)
    assert "not counted anywhere" not in note(out)
    assert listing_billed_amount(RENT + text) == 45
    assert listing_estimate_names(RENT + text) == ["water"]
    line = util_line(text)
    assert line["amount"] == 45 and line["note"] == "From the listing"


def test_average_amounts_for_different_utilities_are_summed_once():
    out = read("Electric avg $60, gas avg $45")
    assert keys(out) == (None, "electric, gas", 105)
    assert "not counted anywhere" not in note(out)
    out = read("Heat avg $80, electric avg $55")
    assert keys(out) == (None, "electric, heat", 135) or keys(out) == (None, "heat, electric", 135) or out["utilities_estimate"] == 135
    assert out["utilities_estimate"] == 135
    assert set(out["tenant_pays"].split(", ")) == {"electric", "heat"}
