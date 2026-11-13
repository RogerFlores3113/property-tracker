"""Cycle 5 G2: utilities clauses, billed-back source label, pet rent per pet, buyer wording, agent and address."""
import pytest

from prophelper import money, redflags
from prophelper.parsers import parse_listing


def pays(text):
    r = parse_listing(text)
    return set(filter(None, (r.get("tenant_pays") or "").split(", "))), set(filter(None, (r.get("utilities_included") or "").split(", "))), r


def test_paid_by_tenant_then_landlord_pays():
    p, inc, _ = pays("Gas and electric paid by tenant; landlord pays water, sewer and garbage.")
    assert p == {"gas", "electric"} and inc == {"water", "sewer", "trash"}


def test_tenant_pays_then_landlord_pays():
    p, inc, _ = pays("Tenant pays gas and electric. Landlord pays water, sewer, garbage.")
    assert p == {"gas", "electric"} and inc == {"water", "sewer", "trash"}


def test_tenant_pays_then_included_suffix():
    p, inc, _ = pays("Tenant pays electric and gas. Water/sewer/trash included")
    assert p == {"gas", "electric"} and inc == {"water", "sewer", "trash"}


@pytest.mark.parametrize("text", ["Electric extra", "Rent $1,200 plus electric", "Electric not included"])
def test_extra_plus_not_included_mean_tenant_pays(text):
    p, inc, _ = pays(text)
    assert p == {"electric"} and "electric" not in inc


def test_billed_back_amount_goes_to_estimate():
    p, inc, r = pays("Water, sewer and trash billed back monthly (avg $55). Tenant pays electric and internet.")
    assert p == {"electric", "internet", "water", "sewer", "trash"}
    assert r["utilities_estimate"] == 55 and not inc


def test_billed_back_rubs_no_amount():
    p, _, r = pays("Water, sewer and trash billed back via RUBS. Tenant pays electric.")
    assert p == {"electric", "water", "sewer", "trash"}
    assert "utilities_estimate" not in r and "no amount" in r["found_in_listing"]


def test_all_utilities_included_is_all():
    assert parse_listing("All utilities included. 1BR $1,200")["utilities_included"] == "all"
    assert money.utilities_covered({"utilities_included": "all"})


def test_billed_back_estimate_is_from_the_listing():
    text = "Water, sewer and trash billed back monthly (avg $55). Tenant pays electric."
    r = parse_listing(text)
    place = {"price": 1500, "utilities_estimate": r["utilities_estimate"], "listing_text": text}
    line = next(x for x in money.rent_cost(place)["lines"] if x["key"] == "utilities")
    assert "From the listing" in line["note"] and "guess" not in line["note"]
    place["utilities_estimate"] = 90  # typed by the person
    line = next(x for x in money.rent_cost(place)["lines"] if x["key"] == "utilities")
    assert "guess" in line["note"].lower()


@pytest.mark.parametrize("text", ["$35 per month per dog", "$35 per month per dog pet rent"])
def test_pet_rent_per_dog(text):
    assert parse_listing(text)["pet_rent"] == 35


def test_pet_limits():
    r = parse_listing("Pets allowed. Up to 2 dogs, 80 lbs each")
    assert r["pet_weight_limit"] == 80 and r["pet_count_limit"] == 2
    assert parse_listing("Cats and dogs under 40 lb")["pet_weight_limit"] == 40


def test_breed_note_keeps_parenthesis():
    assert "(no pit bulls)" in parse_listing("Pets welcome. Breed restrictions apply (no pit bulls). Dogs ok")["pet_breed_note"]


def test_closing_costs_estimated_at():
    assert parse_listing("Closing costs estimated at $7,500")["closing_costs"] == 7500


def test_buy_flags_waived_inspection_and_as_is():
    flags = redflags.local_flags({"listing_text": "Sold as-is, buyer waives inspection", "address": "1 Main St"}, mode="buy")
    assert any("waive the inspection" in f for f in flags) and any("as-is" in f for f in flags)
    assert any("inspection" in f for f in redflags.local_flags({"listing_text": "Seller waives the inspection", "address": "1 Main St"}, mode="buy"))
    soft = redflags.local_flags({"listing_text": "Sold as-is.", "address": "1 Main St"}, mode="buy")
    assert len(soft) == 1 and not redflags.is_serious({"listing_text": "Sold as-is."})


def test_listing_agent_stops_at_sentence_end():
    assert parse_listing("Listing agent: Dana Whitfield, Buckeye Realty. Pets allowed.")["listing_agent"] == "Dana Whitfield, Buckeye Realty"
    assert parse_listing("Listed by Jane Q. Agent, Example Realty")["listing_agent"] == "Jane Q. Agent, Example Realty"


def test_address_with_sq_and_unit():
    r = parse_listing("700 Easton Sq Unit 12, Columbus, OH 43219")
    assert r["address"] == "700 Easton Sq" and r["unit"] == "12" and r["city"] == "Columbus" and r["zip"] == "43219"
    assert r["title"]
