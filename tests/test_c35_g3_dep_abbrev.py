"""Cycle 35 group G3 item 3: "$1500 dep" and "Dep $1,350" are the security deposit; "Pet dep $300" is the pet deposit, never the security deposit."""
import os

import pytest

from prophelper.parsers import parse_listing

HERE = os.path.join(os.path.dirname(__file__), "fixtures", "panel")


def P(text, kind="", **kw):
    return parse_listing(text, "", pet_kind=kind, **kw)


def F(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as fh:
        return fh.read()


SEC = [
    "Rent $1,350. Dep $1,350.",
    "Rent $1,350. Dep: $1,350",
    "Rent $1,350, dep $1,350, pets ok",
    "$1,350/mo, $1,350 dep",
    "Rent $1,350\nDep $1,350\nPets ok",
    "Rent $1,350. Dep. $1,350.",
    "RENT $1,350. DEP $1,350.",
    "2BR $1,350 (dep $1,350)",
    "$1,350 rent / $1,350 dep. / no smoking",
    "Rent $1,350 | $1,350 dep refundable | Pets ok",
]


@pytest.mark.parametrize("t", SEC)
def test_dep_is_the_security_deposit(t):
    r = P(t)
    assert r["deposit"] == 1350 and r["price"] == 1350
    assert "pet_deposit" not in r and "move_in_fees" not in r


def test_nontech_l12_whole_listing():
    r = P(F("r34-nontech-l12.txt"), "cat")
    assert r["price"] == 1500 and r["deposit"] == 1500 and r["pets"] == "cats"
    assert r["utilities_estimate"] == 55 and r["utilities_included"] == "trash"


def test_nontech_l15_whole_listing():
    r = P(F("r34-nontech-l15.txt"), "cat")
    assert r["price"] == 1350 and r["deposit"] == 1350 and r["pets"] == "cats" and r["pet_rent"] == 25
    assert r["utilities_estimate"] == 70


def test_pet_dep_is_the_pet_deposit_and_the_plain_dep_the_security_deposit():
    r = P("Rent $1,350. Pet dep $300. Dep $1,350.", "dog")
    assert r["pet_deposit"] == 300 and r["deposit"] == 1350
    r = P("Rent $1,350. $1,350 dep. $300 pet dep.", "dog")
    assert r["pet_deposit"] == 300 and r["deposit"] == 1350


def test_a_lone_dep_with_no_rent_is_never_the_rent():
    r = P("Dep $900")
    assert r.get("price") is None and r["deposit"] == 900


@pytest.mark.parametrize("t", [
    "Rent $1,350. Dep 5/1. Pets ok.",
    "Rent $1,350. Dep. at 8am.",
    "Rent $1,350. Dependable landlord, deposit $1,350.",
    "Rent $1,350. Depends on credit.",
])
def test_negative_dep_words_that_are_not_a_deposit(t):
    r = P(t)
    assert r["price"] == 1350
    assert r.get("deposit") in (None, 1350)
    if "deposit $1,350" not in t:
        assert "deposit" not in r
