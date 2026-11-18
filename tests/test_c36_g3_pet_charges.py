"""Cycle 36 group G3 item 2 (rules ii, dd): every amount a pet sentence ties to its own label is kept. "dogs OK, $400 non-refundable, $30/mo" is a $400 pet fee
and $30 pet rent; "Cats $35/mo and $200 fee" keeps both; "Cats only, $25 de renta mensual" is pet rent."""
import os

import pytest

from prophelper.parsers import parse_listing

HERE = os.path.join(os.path.dirname(__file__), "fixtures", "panel")


def F(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as fh:
        return fh.read()


def read(t, kind=""):
    return parse_listing(t, "", pet_kind=kind)


def pets(r):
    return r.get("pet_fee"), r.get("pet_rent"), r.get("pet_deposit")


DOG_LAYOUTS = [
    "3 bed house. Rent $2,300. Dogs OK, $400 non-refundable, $30/mo.",
    "3 bed house. Rent $2,300. Pets: dogs OK (no pit bulls), $400 non-refundable, $30/mo",
    "3 bed house. Rent $2,300. Dogs ok; $400 nonrefundable; $30 per month.",
    "3 bed house. Rent $2,300.\nDogs OK\n$400 non-refundable\n$30/mo",
    "3 bed house. Rent $2,300. Dogs OK\n- $400 non-refundable\n- $30/month",
    "3 bed house. Rent $2,300 | Dogs OK | $400 non-refundable | $30/mo",
    "3 bed house. Rent $2,300. Dogs OK, $30/mo, $400 non-refundable.",
    "3 bed house. Rent $2,300. Dogs OK: $400 non-refundable + $30/mo",
    "3 bed house. Rent $2,300. Dogs OK ($400 non-refundable, $30/mo)",
    "3 bed house. Rent $2,300. Dogs welcome, $400 one-time, $30 monthly.",
    "3 bed house. Rent $2,300. Dogs welcome, $400 up front, $30/mo.",
    "3 bed house. Rent $2,300. Dogs ok. $30/mo pet rent, $400 non-refundable fee.",
]


@pytest.mark.parametrize("t", DOG_LAYOUTS)
@pytest.mark.parametrize("kind", ["dog", ""])
def test_dog_fee_and_rent(t, kind):
    r = read(t, kind)
    assert pets(r) == (400, 30, None), r
    assert r.get("pets") == "dogs"


def test_roommates_l10_whole_listing():
    r = read(F("r35-roommates-l10.txt"), "dog")
    assert pets(r) == (400, 30, None)
    assert r["deposit"] == 1350 and r["pet_breed_note"].startswith("Pets: dogs OK")
    assert "$400 pet fee is not refundable" in r["found_in_listing"]


CAT_LAYOUTS = [
    "3 bed house. Rent $2,300. Cats $35/mo and $200 fee.",
    "3 bed house. Rent $2,300. Cats $35/month and $200 fee.",
    "3 bed house. Rent $2,300. Cats: $35/mo plus $200 non-refundable fee.",
    "3 bed house. Rent $2,300. Cats ok - $35/mo, $200 fee.",
    "3 bed house. Rent $2,300.\nCats $35/mo and $200 fee\nParking $40/mo",
    "3 bed house. Rent $2,300. Cats: $200 fee and $35/mo.",
    "3 bed house. Rent $2,300. Cats ok, $35 monthly plus $200 one-time fee.",
]


@pytest.mark.parametrize("t", CAT_LAYOUTS)
@pytest.mark.parametrize("kind", ["cat", ""])
def test_cat_fee_and_rent(t, kind):
    r = read(t, kind)
    assert pets(r) == (200, 35, None), r


@pytest.mark.parametrize("kind", ["cat", ""])
def test_nontech_l13_whole_listing(kind):
    r = read(F("r35-nontech-l13.txt"), kind)
    assert pets(r) == (200, 35, None)
    note = r["found_in_listing"]
    assert "$745 each" not in note and "each for pets" not in note, note  # the roommate share is not a pet rent
    assert "Reserved lot $40/mo" in note


def test_cat_amounts_are_not_a_dogs_amounts():
    r = read("3 bed house. Rent $2,300. Cats $35/mo and $200 fee.", "dog")
    assert pets(r) == (None, None, None)
    assert "$35 a month cat rent" in r["found_in_listing"] and "$200 cat fee" in r["found_in_listing"]


@pytest.mark.parametrize("t", [
    "3 bed house. Rent $2,300. Cats only, $25 de renta mensual.",
    "3 bed house. Rent $2,300. Cats only. $25 de renta mensual.",
    "3 bed house. Rent $2,300. Cats only, $25 al mes.",
    "3 bed house. Rent $2,300. Cats only. $25 monthly pet rent.",
    "3 bed house. Rent $2,300.\nCats only\n$25 de renta mensual",
])
def test_cats_only_with_spanish_or_plain_rent(t):
    r = read(t, "cat")
    assert pets(r) == (None, 25, None), r
    assert r["pets"] == "cats"


def test_roommates_l5_whole_listing():
    r = read(F("r35-roommates-l5.txt"), "cat")
    assert pets(r) == (None, 25, None) and r["pets"] == "cats"


@pytest.mark.parametrize("t", [
    "3 bed house. Rent $2,300. Dogs ok. $400 non-refundable application fee. Parking $30/mo.",
    "3 bed house. Rent $2,300. Dogs ok. Non-refundable $400 security deposit. Parking $30/mo.",
    "3 bed house. Rent $2,300. Pets ok. Application $50 non-refundable. Garage $30/month.",
    "3 bed house. Rent $2,300. Dogs ok.\nApplication $50 non-refundable\nParking $30/mo",
])
def test_other_charges_are_not_pet_charges(t):
    r = read(t, "dog")
    assert pets(r) == (None, None, None), r
