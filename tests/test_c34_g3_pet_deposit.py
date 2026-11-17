"""Cycle 34 group G3 item 1 (rule dd): every amount a pet sentence ties to its own label is kept when other amounts share the sentence."""
import os

import pytest

from prophelper.parsers import parse_listing

HERE = os.path.join(os.path.dirname(__file__), "fixtures", "panel")


def P(text, kind="dog", **kw):
    return parse_listing(text, "", pet_kind=kind, **kw)


def F(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as fh:
        return fh.read()


WORDINGS = [
    "Rent $2,375. Pet policy: Dogs welcome with a $35 per pet application, $45/month pet rent per dog, $350 deposit.",
    "Rent $2,375. Dogs welcome. $350 deposit, $45/month pet rent per dog, $35 per pet application.",
    "Rent $2,375\nPets: dogs ok; $35 application per pet; $45 monthly pet rent; $350 deposit\n",
    "Rent $2,375. Dogs welcome: $35 pet application, $45/mo pet rent, $350 pet deposit.",
    "Rent $2,375. Pet policy: Dogs welcome | $350 deposit | $45/month pet rent per dog | $35 per pet application",
    "Rent $2,375. PET POLICY: DOGS WELCOME WITH A $35 PER PET APPLICATION, $45/MONTH PET RENT PER DOG, $350 DEPOSIT.",
    "Rent $2,375. Dogs welcome with $45/month pet rent per dog, $350 deposit, and a $35 per pet application.",
    "Rent $2,375. Pets: dogs welcome, $35 per pet application, $45/month pet rent per dog and a $350 deposit.",
]


@pytest.mark.parametrize("t", WORDINGS)
@pytest.mark.parametrize("kind", ["dog", ""])
def test_pet_sentence_keeps_application_rent_and_deposit(t, kind):
    r = P(t, kind)
    assert r["pet_rent"] == 45
    assert r["pet_deposit"] == 350
    assert r.get("pets") == "dogs"
    assert "deposit" not in r  # the pet deposit is never the security deposit
    n = r.get("found_in_listing") or ""
    assert "$350 of that is not counted" not in n and "Only $350" not in n
    assert "not counted anywhere" not in n


def test_reviewer_listing_l13():
    r = P(F("r33-family-l13.txt"), "dog")
    assert (r["pet_fee"], r["pet_rent"], r["pet_deposit"]) == (35, 45, 350)
    assert r["deposit"] == 2375 and r["price"] == 2375
    assert r["pet_weight_limit"] == 70 and r["pet_count_limit"] == 2
    n = r["found_in_listing"]
    assert "Only $350" not in n and "not counted anywhere" not in n


def test_negative_security_deposit_stays_security():
    r = P("Rent $2,375. Security deposit $1,200. Pet policy: dogs welcome, $45/month pet rent per dog.", "dog")
    assert r["deposit"] == 1200 and r["pet_rent"] == 45
    assert "pet_deposit" not in r or not r["pet_deposit"]


def test_negative_deposit_as_big_as_rent_is_security():
    r = P("Rent $2,375. Pet policy: dogs welcome, $45/month pet rent per dog. Deposit $2,375.", "dog")
    assert r["deposit"] == 2375 and r["pet_rent"] == 45
    assert not r.get("pet_deposit")
