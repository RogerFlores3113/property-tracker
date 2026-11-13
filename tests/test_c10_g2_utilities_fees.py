"""Cycle 10 G2: flat utility fees, tenant-paid utilities named through a provider, "+ utilities", move-in fee kinds,
broker fee in months, "everything included except cable", and billed-back wording."""
import pytest

from prophelper.money import rent_cost
from prophelper.parsers import parse_listing


@pytest.mark.parametrize("text,amount", [
    ("Water, sewer & trash flat fee $60/mo", 60),
    ("Water, sewer and trash: flat $55 monthly", 55),
    ("Flat fee $85/mo covers water, sewer and trash", 85),
])
def test_flat_utility_fee_is_counted(text, amount):
    r = parse_listing(text)
    assert r["utilities_estimate"] == amount
    assert r["tenant_pays"] == "water, sewer, trash"
    assert "utilities_included" not in r
    assert "flat fee of" in r["found_in_listing"]
    cost = rent_cost({"price": 1000, "utilities_estimate": amount, "tenant_pays": r["tenant_pays"], "listing_text": text})
    assert cost["total"] == 1000 + amount
    assert cost["missing"] == []


@pytest.mark.parametrize("text,pays", [
    ("Electric through Ameren, you set up", "electric"),
    ("Electric and gas through PG&E", "electric, gas"),
    ("Tenant pays electric & gas", "electric, gas"),
])
def test_tenant_pays_named_through_provider(text, pays):
    r = parse_listing(text)
    assert r["tenant_pays"] == pays
    assert "utilities_included" not in r
    assert "utilities_estimate" not in r


def test_belmont_billed_back_keeps_electric_and_gas():
    r = parse_listing("Water/sewer/garbage billed monthly by the city, averages about $140. Electric and gas through PG&E")
    assert r["utilities_estimate"] == 140
    assert r["tenant_pays"] == "electric, gas, water, sewer, trash"
    cost = rent_cost({"price": 1000, "utilities_estimate": 140, "tenant_pays": r["tenant_pays"], "listing_text":
                      "Water/sewer/garbage billed monthly by the city, averages about $140. Electric and gas through PG&E"})
    assert cost["missing"] == ["electric and gas"]
    assert cost["total"] == 1140


def test_flat_fee_does_not_wipe_out_tenant_pays():
    r = parse_listing("Water, sewer and trash flat fee $60/mo. Tenant pays electric & gas.")
    assert r["tenant_pays"] == "electric, gas, water, sewer, trash"
    assert r["utilities_estimate"] == 60


@pytest.mark.parametrize("text", ["Rent: $1,150 + utilities", "Rent $1,150/mo + utilities"])
def test_plus_utilities_means_tenant_pays_unknown_which(text):
    r = parse_listing(text)
    assert r["price"] == 1150
    assert "utilities_included" not in r and "tenant_pays" not in r and "utilities_estimate" not in r
    assert "doesn't say which ones" in r["found_in_listing"]


def test_cleaning_fee_at_move_in_is_a_move_in_fee():
    r = parse_listing("a $200 cleaning fee at move-in")
    assert r["move_in_fees"] == 200
    assert "application_fee" not in r


def test_cleaning_fee_without_when_is_not_counted():
    r = parse_listing("There is a $200 cleaning fee.")
    assert "move_in_fees" not in r
    assert "not when it is due" in r["found_in_listing"]


def test_admin_fee_per_applicant_is_application_fee():
    r = parse_listing("$55 admin fee per applicant")
    assert r["application_fee"] == 55
    assert r["application_fee_per_adult"] == 1
    assert "move_in_fees" not in r


def test_broker_fee_one_month():
    r = parse_listing("Rent $2000/mo. Broker fee: one month's rent")
    assert r["price"] == 2000 and r["broker_fee"] == 2000
    r = parse_listing("Rent $1,800/mo. Broker fee one month")
    assert r["broker_fee"] == 1800
    r = parse_listing("Broker fee one month")
    assert "broker_fee" not in r
    assert "broker fee is 1 month of rent" in r["found_in_listing"]


def test_everything_included_except_cable():
    r = parse_listing("Everything included except cable")
    assert r["utilities_included"] == "all"
    assert r["tenant_pays"] == "internet"


def test_everything_included_except_electric_is_not_all():
    r = parse_listing("Everything included except electric")
    assert r["utilities_included"] == "gas, water, sewer, trash, heat"
    assert r["tenant_pays"] == "electric"


@pytest.mark.parametrize("text,line", [
    ("Water billed back at $45/mo", "Water is billed back at $45/month"),
    ("Water, sewer and trash billed back at $45/mo", "Water, sewer, trash are billed back at $45/month"),
])
def test_billed_back_grammar(text, line):
    assert line in parse_listing(text)["found_in_listing"]


def test_billed_back_amount_names_only_what_is_missing():
    text = "Water billed back at $45/mo. Tenant pays electric & gas."
    cost = rent_cost({"price": 1500, "utilities_estimate": 45, "tenant_pays": "water, electric, gas", "listing_text": text})
    assert cost["missing"] == ["electric and gas"]
    assert "utilities estimate" not in cost["missing"]
    covered = rent_cost({"price": 1500, "utilities_estimate": 45, "tenant_pays": "water", "listing_text": "Water billed back at $45/mo."})
    assert covered["missing"] == []
