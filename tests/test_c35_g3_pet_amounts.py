"""Cycle 35 group G3, rule (ee) for pet amounts: a pet amount with a thousands comma is read whole, never as the small part ("$1,000 pet deposit" saved as $1)."""
import pytest

from prophelper.parsers import parse_listing


def P(text, kind=""):
    return parse_listing(text, "", pet_kind=kind)


DEPOSIT = [
    "Rent $2,500. Pet deposit $1,000.",
    "Rent $2,500. $1,000 pet deposit.",
    "Rent $2,500. Pets: $1,000 deposit.",
    "Rent $2,500\nPet deposit: $1,000\nDogs ok",
    "Rent $2,500 | Pet deposit $1,000 (refundable) | Cats ok",
    "Rent $2,500, pet deposit of $1,000, dogs welcome",
    "Rent $2,500. PET DEPOSIT $1,000.",
]


@pytest.mark.parametrize("t", DEPOSIT)
def test_pet_deposit_over_a_thousand(t):
    r = P(t)
    assert r["pet_deposit"] == 1000 and r["price"] == 2500
    assert "$1 pet" not in (r.get("found_in_listing") or "")


@pytest.mark.parametrize("t,field,val", [
    ("Rent $2,500. Pet fee $1,000.", "pet_fee", 1000),
    ("Rent $2,500. One-time pet fee: $1,200 non-refundable.", "pet_fee", 1200),
    ("Rent $2,500. $1,500 pet fee.", "pet_fee", 1500),
    ("Rent $2,500\nPet rent $1,000\n", "pet_rent", 1000),
    ("Rent $2,500. Pet fee $42.50.", "pet_fee", 42.5),
    ("Rent $2,500. Pet rent $42.50/mo.", "pet_rent", 42.5),
    ("Rent $2,500. Cat fee $1,100.", "pet_fee", 1100),
])
def test_other_pet_amounts_read_whole(t, field, val):
    r = P(t)
    assert r[field] == val and r["price"] == 2500


def test_small_amounts_still_read():
    r = P("Rent $2,500. Pet deposit $300. Pet rent $35/mo. Pet fee $150.")
    assert r["pet_deposit"] == 300 and r["pet_rent"] == 35 and r["pet_fee"] == 150


def test_negative_a_comma_list_is_not_one_number():
    r = P("Rent $2,500. Pet deposit $300, pet fee $150, pet rent $35/mo.")
    assert r["pet_deposit"] == 300 and r["pet_fee"] == 150 and r["pet_rent"] == 35
