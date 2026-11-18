"""Cycle 9, group G2: pets, deposits, application fee and bathrooms. Unknown is better than wrong."""
from __future__ import annotations

import pytest

from prophelper.parsers import parse_listing
from prophelper.routes_pages import _not_found_names


def note(got):
    return got.get("found_in_listing", "")


def test_pet_sentence_deposit_is_not_the_security_deposit():
    got = parse_listing("2 bed apartment $1,800/mo. Pet friendly (cats only, $40/month, deposit $250). Security deposit equal to one month.")
    assert got["pets"] == "cats" and got["pet_rent"] == 40 and got["pet_deposit"] == 250
    assert got["deposit"] == 1800 and "pet_fee" not in got


def test_security_deposit_months_without_rent_is_empty_with_note():
    got = parse_listing("Pet friendly (cats only, $40/month, deposit $250). Security deposit equal to one month.")
    assert got["pets"] == "cats" and got["pet_rent"] == 40 and got["pet_deposit"] == 250
    assert "deposit" not in got
    assert "1 month of rent" in note(got) and "left empty" in note(got)


def test_pet_fee_and_monthly_pet_rent():
    got = parse_listing("Pet fee $350 one-time. Monthly pet rent $35 per pet.")
    assert got["pet_fee"] == 350 and got["pet_rent"] == 35 and "pet_deposit" not in got


def test_deposit_per_pet_is_only_a_pet_deposit():
    got = parse_listing("1 bed $1500/mo. deposit $250 per pet")
    assert got["pet_deposit"] == 250 and "pet_fee" not in got and "deposit" not in got


@pytest.mark.parametrize("text,weight", [
    ("Dogs ok, no more than 40 lbs", 40),
    ("No dogs over 50 pounds. Cats ok.", 50),
    ("Dogs ok, under 50 lbs", 50),
    ("Dogs ok. 50 lb weight limit", 50),
    ("Cats ok. No dogs over 30 lbs", 30),
])
def test_weight_limits(text, weight):
    assert parse_listing(text)["pet_weight_limit"] == weight


def test_pets_line_with_count_weight_and_breed():
    got = parse_listing("Pets: Dogs OK, 1 dog max, no more than 40 lbs, breed restrictions apply")
    assert got["pets"] == "dogs" and got["pet_count_limit"] == 1 and got["pet_weight_limit"] == 40
    assert got["pet_breed_note"] == "Breed restrictions apply"


def test_count_in_the_pet_count_field():
    got = parse_listing("Cats ok, up to 2")
    assert got["pets"] == "cats" and got["pet_count_limit"] == 2


def test_cats_ok_dogs_need_approval_leaves_pets_empty_with_note():
    got = parse_listing("Pets: Cats ok ... Dogs need approval")
    assert "pets" not in got
    assert "Dogs need approval" in note(got) and "ask the landlord" in note(got)


def test_no_pets_then_cats_allowed():
    got = parse_listing("No pets allowed ... actually cats allowed")
    assert "pets" not in got
    assert "No pets allowed" in note(got) and "ask the landlord" in note(got)


def test_approval_required_keeps_weight_limit():
    got = parse_listing("Pet policy: approval required. No dogs over 30 lbs; cats ok.")
    assert "pets" not in got and got["pet_weight_limit"] == 30
    assert "approval required" in note(got) and "ask the landlord" in note(got)


def test_pets_allowed_with_approval_is_not_a_plain_yes():
    got = parse_listing("Pets allowed with landlord approval. Max 2 pets.")
    assert "pets" not in got and got["pet_count_limit"] == 2 and "ask the landlord" in note(got)


def test_dogs_case_by_case_is_not_a_yes():
    got = parse_listing("Cats welcome. Dogs considered case by case, breed restrictions apply")
    assert got["pets"] == "cats" and got["pet_breed_note"] == "Breed restrictions apply"
    assert "dogs are considered case by case" in note(got)


def test_buy_listing_asks_the_seller():
    got = parse_listing("For sale $450,000 MLS. Pets: Cats ok ... Dogs need approval")
    assert "pets" not in got
    assert "ask the seller or listing agent" in note(got) and "landlord" not in note(got)


def test_pets_not_listed_as_not_found_when_a_fee_or_limit_was_read():
    for text in ("Pet fee $350 one-time.", "Pet rent $35", "Pet deposit $300", "No dogs over 30 lbs. Pet policy: approval required.", "1 dog max"):
        got = parse_listing(text)
        assert "pets" not in _not_found_names(got, "rent"), text
    assert "pets" in _not_found_names(parse_listing("2 bed $1500/mo"), "rent")


@pytest.mark.parametrize("text", ["no app fee", "no application fee", "$0 application fee", "No App Fee!"])
def test_no_application_fee_is_zero(text):
    got = parse_listing(text)
    assert got["application_fee"] == 0


@pytest.mark.parametrize("text", ["Baths 1.5", "1.5 ba", "1.5 bath", "2 bd | 1.5 ba", "Bathrooms: 1.5"])
def test_one_and_a_half_baths(text):
    assert parse_listing(text)["baths"] == 1.5


@pytest.mark.parametrize("text", ["$500 deposit with approved credit", "Security deposit as low as $500", "deposit starting at $500", "$500 deposit OAC"])
def test_best_case_deposit_is_not_saved(text):
    got = parse_listing("$1500/mo 1 bed. " + text)
    assert "deposit" not in got
    assert "best-case deposit of $500 with approved credit" in note(got)


def test_plain_deposit_still_saved():
    assert parse_listing("$1500/mo 1 bed. Security deposit $1,200")["deposit"] == 1200
