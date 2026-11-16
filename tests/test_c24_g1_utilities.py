"""Cycle 24 G1: utilities reader. Priced internet the tenant sets up or must pay is counted in the utilities estimate in every layout, a utility sent
"through provider" with no price is unknown, one figure never stands in for several bills, "HOA covers water" next to a water charge is a plain
conflict, "tenant pays all, estimate USD 220/mo" is a total, "gas incl. in rent?" is a question, and cents are kept. Each item has the reviewer's
wording plus other natural wordings, and each test pins exact field values."""
from __future__ import annotations

from pathlib import Path

import pytest

from prophelper import compare, money
from prophelper.parsers import parse_listing

HEAD = "2 bed apartment, $1,450/mo."
PANEL = Path("/tmp/claude-0/-home-user-property-helper/be454331-cd61-59ba-9ebc-8cb8b7ec6a12/scratchpad/panel")


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
    place = dict(r)
    place["reader_notes"] = notes(r)
    place["listing_text"] = text
    c = money.true_monthly_cost(place, "rent")
    return c, compare._missing_names({**place, "cost": c})


def saved(name: str) -> tuple[dict, str]:
    f = PANEL / f"{name}.txt"
    if not f.exists():
        pytest.skip("reviewer listing not on this machine")
    t = f.read_text(encoding="utf-8", errors="replace")
    return parse_listing(t, ""), t


# 1. internet the tenant sets up or must pay, with a price ---------------------------------------------------------------------------------
@pytest.mark.parametrize("text,est", [
    ("Electric $60.\nInternet: you set up your own with Spectrum, about $55/mo.", 115),
    ("Electric $60. Internet: Comcast, you set up (about $55).", 115),
    ("Electric $60. Internet $70 required through provider.", 130),
    ("Electric $60. Internet $65 (Xfinity, required).", 125),
    ("Electric $60 | Internet: Xfinity, you set up, $60/mo", 120),
    ("Electric: $60\nInternet (Spectrum, you set up) about $50.", 110),
    ("Tenant pays electric $60. Internet is required through the property's provider at $70/mo.", 130),
])
def test_priced_internet_the_tenant_pays_is_counted_in_the_estimate(text, est):
    r = read(text)
    assert r.get("utilities_estimate") == est, (r.get("utilities_estimate"), notes(r))
    assert pays_set(r) == {"electric", "internet"}
    low = notes(r)
    assert "not counted" not in low.replace("counted as your utilities estimate", "")
    c, missing = cost_of(r, HEAD + " " + text)
    assert missing == [], (missing, c.get("headline"))
    assert c["total"] == 1450 + est
    assert r.get("other_monthly_fees") in (None, 0)  # counted once, never also as a monthly fee


def test_internet_alone_is_the_whole_estimate():
    r = read("Internet: Xfinity, you set up, $60/mo. Heat included.")
    assert r.get("utilities_estimate") == 60 and pays_set(r) == {"internet"} and included_set(r) == {"heat"}
    assert cost_of(r, HEAD)[1] == []


@pytest.mark.parametrize("text", [
    "Internet optional, about $55/mo. Electric $60.",
    "Electric $60. Internet is your choice ($55/mo).",
    "Electric $60\nInternet available through Comcast for $55/mo if you want it",
])
def test_optional_internet_stays_uncounted_with_a_note(text):
    r = read(text)
    assert r.get("utilities_estimate") == 60 and "internet" not in pays_set(r)
    assert "Internet is listed as optional at $55 a month, so it is not counted." in notes(r)


@pytest.mark.parametrize("text", [
    "Tenant pays electric and internet, about $120 total.",
    "Tenant pays electric and internet (about $120 total).",
])
def test_a_total_for_electric_and_internet_is_not_split(text):
    r = read(text)
    assert r.get("utilities_estimate") == 120 and pays_set(r) == {"electric", "internet"}


@pytest.mark.parametrize("name,est,pays", [
    ("r23-nontech-l16", 165, {"electric", "gas", "internet"}),
    ("r23-uiuc-l13", 143, {"electric", "water", "sewer", "trash", "internet"}),
    ("r23-uiuc-l15", 165, {"electric", "internet"}),
    ("r23-roommates-l43", 125, {"electric", "internet"}),
    ("r23-roommates-l63", 195, {"electric", "gas", "internet"}),
])
def test_saved_listings_count_the_internet(name, est, pays):
    r, t = saved(name)
    assert r.get("utilities_estimate") == est, (r.get("utilities_estimate"), notes(r))
    assert pays_set(r) == pays
    c, missing = cost_of(r, t)
    assert "internet" not in " ".join(missing)
    assert "$55 amount" not in str(c.get("headline")) and "$60 amount" not in str(c.get("headline"))
    assert "not counted anywhere" not in notes(r) or "nternet" not in notes(r).split("not counted anywhere")[0][-120:]


# 2. through provider, no price ------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text,est,pays,missing", [
    ("Utilities: Water/trash $42 monthly; electric and internet through provider.", 42, {"water", "trash", "electric", "internet"}, ["electric and internet"]),
    ("Water $30/mo. Gas and internet through the provider.", 30, {"water", "gas", "internet"}, ["gas and internet"]),
    ("Tenant pays water $30\nElectric through provider", 30, {"water", "electric"}, ["electric"]),
])
def test_through_provider_with_no_price_is_unknown_not_dropped(text, est, pays, missing):
    r = read(text)
    assert r.get("utilities_estimate") == est and pays_set(r) == pays
    c, miss = cost_of(r, HEAD + " " + text)
    assert miss == missing, (miss, notes(r))
    assert "listed as something you pay, with no amount" in notes(r)


def test_uiuc_l7_saved_listing():
    r, t = saved("r23-uiuc-l7")
    assert r.get("utilities_estimate") == 42 and pays_set(r) == {"water", "trash", "electric", "internet"}
    assert cost_of(r, t)[1] == ["electric and internet"]


def test_through_provider_with_the_landlord_paying_is_not_the_tenants():
    r = read("Water $30/mo. Landlord pays electric and internet through provider.")
    assert pays_set(r) == {"water"}


# 3. one figure is not three bills --------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "Resident pays gas, electric and water (about $55/mo water).",
    "Resident pays gas, electric and water ($55/mo for water).",
    "Tenant pays gas, electric, water. Water is about $55/mo.",
    "Tenant pays gas, electric and water (water avg $55).",
])
def test_a_bracketed_figure_prices_only_the_utility_it_names(text):
    r = read(text)
    assert r.get("utilities_estimate") == 55 and pays_set(r) == {"gas", "electric", "water"}
    assert "Water is about $55 a month" in notes(r) and "Gas, electric and water are about" not in notes(r)
    c, missing = cost_of(r, HEAD + " " + text)
    assert missing == ["electric and gas"] and "not counted yet" in c["headline"]


def test_family_l12_saved_listing():
    r, t = saved("r23-family-l12")
    assert r.get("utilities_estimate") == 55 and pays_set(r) == {"gas", "electric", "water"}
    assert cost_of(r, t)[1][0] == "electric and gas"


@pytest.mark.parametrize("text", [
    "Utilities: tenant pays all except internet and electric (electric avg $40... actually, ask).",
    "Tenant pays all utilities except internet and electric (electric ~$40, ask).",
    "Tenant pays everything except internet and electric (electric about $40).",
])
def test_all_except_with_a_price_for_a_left_out_one_stays_unknown(text):
    r = read(text)
    assert r.get("utilities_estimate") is None
    assert pays_set(r) == {"gas", "water", "sewer", "trash", "heat"}  # cycle 25: the two left-out ones are unknown, not tenant-paid
    assert not included_set(r)
    assert "counted as your utilities estimate" not in notes(r) and "don't agree" in notes(r)
    c, missing = cost_of(r, HEAD + " " + text)
    assert missing and "not counted yet" in c["headline"] and not c["all_in"]


def test_family_l7_saved_listing():
    r, t = saved("r23-family-l7")
    assert r.get("utilities_estimate") is None and "gas" in pays_set(r) and "internet" not in pays_set(r) and "electric" not in pays_set(r)
    c, missing = cost_of(r, t)
    assert missing and not c["all_in"]


def test_all_except_without_a_price_still_reads_the_plain_way():
    r = read("Tenant pays all utilities except internet and electric.")
    assert pays_set(r) == {"gas", "water", "sewer", "trash", "heat"} and included_set(r) == {"internet", "electric"}


# 4. HOA covers water next to a water charge ------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text,amount", [
    ("Water & sewer: HOA covers water. Water charge $55/mo. Gas heat paid by tenant.", "$55"),
    ("The HOA covers water. Water charge: $55 a month. Tenant pays gas.", "$55"),
    ("Water bill $55/mo.\nHOA covers water.\nTenant pays gas.", "$55"),
])
def test_hoa_covers_water_and_a_water_charge_is_a_plain_conflict(text, amount):
    r = read(text)
    assert r.get("utilities_estimate") is None
    assert "water" in pays_set(r) and "water" not in included_set(r)
    assert f"The listing says the HOA covers water and also lists a water charge of {amount} a month. Ask which is right." in notes(r)
    c, missing = cost_of(r, HEAD + " " + text)
    assert "water" in " ".join(missing)
    assert "$55" not in str(c["headline"])


@pytest.mark.parametrize("name,amount", [("r23-roommates-l65", "$55"), ("r23-nontech-l17", "$25")])
def test_hoa_water_saved_listings(name, amount):
    r, t = saved(name)
    assert f"The listing says the HOA covers water and also lists a water charge of {amount} a month. Ask which is right." in notes(r)
    assert "water" in pays_set(r) and "water" not in included_set(r)
    c, missing = cost_of(r, t)
    assert "water" in " ".join(missing) and "water is included" not in str(c).lower()


# 5. utilities tenant pays all, estimate USD 220/mo -----------------------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "Utilities: tenant pays all, estimate USD 220/mo.",
    "Utilities: tenant pays all, estimate $220/mo.",
    "Utilities: tenant pays all, estimate US$220 a month.",
    "Utilities: tenant pays all, estimate ＄220/mo.",
])
def test_tenant_pays_all_with_an_estimate_is_a_total(text):
    r = read(text)
    assert r.get("utilities_estimate") == 220
    assert "The listing gives about $220 a month for all the utilities you pay, counted as your utilities estimate." in notes(r)
    assert cost_of(r, HEAD + " " + text)[1] == []


def test_roommates_l64_saved_listing():
    r, t = saved("r23-roommates-l64")
    assert r.get("utilities_estimate") == 220
    assert "utilities" not in " ".join(cost_of(r, t)[1])


# 6. a question is not a statement ---------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text,est,inc", [
    ("Tenant pays all utilities (est. $140/mo electric, gas incl. in rent?). Trash pickup included.", 140, {"trash"}),
    ("Tenant pays utilities. Gas included in rent? Electric about $90.", 90, set()),
    ("Utilities: electric $80, gas included?", 80, set()),
])
def test_gas_included_with_a_question_mark_is_unknown(text, est, inc):
    r = read(text)
    assert r.get("utilities_estimate") == est and included_set(r) == inc and "gas" in pays_set(r)
    assert "The listing asks whether gas is included in the rent." in notes(r) and "Ask the landlord." in notes(r)
    c, missing = cost_of(r, HEAD + " " + text)
    assert "gas" in " ".join(missing)


def test_nontech_l6_saved_listing():
    r, t = saved("r23-nontech-l6")
    assert "gas" in pays_set(r) and "gas" not in included_set(r) and included_set(r) == {"trash"}
    assert r.get("utilities_estimate") == 140


def test_gas_included_as_a_statement_still_counts():
    r = read("Tenant pays electric $60. Gas included in rent.")
    assert included_set(r) == {"gas"} and r.get("utilities_estimate") == 60


# 7. cents --------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text,est", [
    ("Tenant pays trash $8.50 monthly.", 8.5),
    ("Electric ~$42.50/mo. Tenant pays electric.", 42.5),
    ("Tenant pays electric about $42.50 a month.", 42.5),
    ("Water $31.25/mo, sewer $12.75/mo. Tenant pays both.", 44.0),
    ("Tenant pays: Electric $60.40 | Gas $35.10 | Internet $55.99", 151.49),
    ("Tenant pays electric and gas, about $110.50 combined.", 110.5),
    ("Water: $42.50 per month", 42.5),
])
def test_cents_are_kept_in_every_utility_figure(text, est):
    r = read(text)
    assert r.get("utilities_estimate") == est, (r.get("utilities_estimate"), notes(r))
    assert "not counted anywhere" not in notes(r)


def test_cents_in_the_note():
    assert "$42.50 a month" in notes(read("Electric ~$42.50/mo. Tenant pays electric."))
    assert "$8.50 a month" in notes(read("Tenant pays trash $8.50 monthly."))


def test_privacy_trash_is_counted_with_its_cents():
    r, _t = saved("r23-privacy-lmoney")
    assert r.get("other_monthly_fees") == 55.5
