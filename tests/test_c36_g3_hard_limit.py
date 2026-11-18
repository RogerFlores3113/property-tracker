"""Cycle 36 group G3 item 1 (rule kk): a limit word that says no ("NO exceptions", "non-negotiable", "will not be waived") is a hard limit.
A 60 lb dog against a 25 or 30 lb hard limit is "Doesn't fit", never "Fits, but check" or "can be waived"."""
import os

import pytest

from prophelper import scoring
from prophelper.parsers import parse_listing

HERE = os.path.join(os.path.dirname(__file__), "fixtures", "panel")
DOG60 = {"kind": "dog", "weight": 60, "count": 1}


def F(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as fh:
        return fh.read()


def item(text, profile=DOG60):
    place = dict(parse_listing(text, "", pet_kind=profile.get("kind", "")))
    place["listing_text"] = text
    c = {"id": 1, "kind": "pets", "weight": 10, "dealbreaker": True, "target": {}}
    return place, scoring.score_place(place, [c], pets=profile)["items"][0]


HARD = [
    ("3 bed house. Rent $2,300. Pets: small dogs only under 25 lbs, NO exceptions.", 25),
    ("3 bed house. Rent $2,300. Pets: dogs 30 lb max, no exceptions, non-negotiable.", 30),
    ("3 bed house. Dogs 30 lb max. Non-negotiable.", 30),
    ("3 bed house. Dogs under 25 lbs.\nNO EXCEPTIONS.", 25),
    ("3 bed house. Dogs 25 lb max (no exceptions)", 25),
    ("3 bed house. Dogs 25 lb max; not negotiable", 25),
    ("3 bed house | Dogs under 25 lbs | NON-NEGOTIABLE | Cats ok", 25),
    ("3 bed house. Dogs 25 lb max. Will not be waived.", 25),
    ("3 bed house. Dogs 25 lb max, this cannot be waived.", 25),
    ("3 bed house. Dogs under 25 lbs, no exceptions to the weight limit.", 25),
    ("3 bed house. Dogs under 25 lbs. Exceptions are not considered.", 25),
    ("3 bed house. No dogs over 25 lbs, zero exceptions.", 25),
    ("3 bed house. Dogs max 25 lbs, strictly.", 25),
    ("3 bed house. Dogs max 25 lbs, firm.", 25),
]


@pytest.mark.parametrize("t,limit", HARD)
def test_hard_limits_fail_a_60_lb_dog(t, limit):
    place, it = item(t)
    assert place["pet_weight_limit"] == limit, place
    assert it["passes"] is False and it["known"] is True, it
    assert "waived" not in it["detail"] and "approval" not in it["detail"], it
    assert "waived with approval" not in str(place.get("reader_notes") or "") + str(place.get("notes") or "")


@pytest.mark.parametrize("name", ["r35-family-l2.txt", "r35-family-l9.txt"])
def test_family_whole_listing(name):
    place, it = item(F(name))
    assert place["pet_weight_limit"] == 25
    assert it["passes"] is False and it["known"] is True, it
    assert "Fits, but check" not in str(it)


SOFT = [
    "3 bed house. Dogs under 25 lbs, exceptions considered.",
    "3 bed house. Dogs 30 lb max, may be negotiable.",
    "3 bed house. Dogs 30 lb max. Negotiable.",
    "3 bed house. Dogs 30 lb max. Exceptions may be made.",
    "3 bed house. Dogs under 25 lbs. Exceptions possible, ask.",
]


@pytest.mark.parametrize("t", SOFT)
def test_waivable_limits_stay_soft(t):
    place, it = item(t)
    assert it["passes"] is not False and it["known"] is False, it
    assert "waived" in it["detail"] or "approval" in it["detail"], it


def test_no_limit_no_failure():
    place, it = item("3 bed house. Dogs welcome. No exceptions to the lease terms.")
    assert place.get("pet_weight_limit") is None
    assert it["passes"] is not False


def test_small_dog_still_fits_a_hard_limit():
    place, it = item("3 bed house. Dogs under 25 lbs, NO exceptions.", {"kind": "dog", "weight": 20, "count": 1})
    assert it["passes"] is not False, it


def test_firm_word_about_a_kind_is_not_case_by_case():
    r = parse_listing("Rent $2,300. Pets: cats ok, dogs non-negotiable.", "", pet_kind="dog")
    assert r["pets"] == "cats"
    assert "case by case" not in r["found_in_listing"] and "something firm about dogs" in r["found_in_listing"]
    r = parse_listing("Rent $2,300. Cats welcome, dogs negotiable.", "", pet_kind="dog")
    assert r["pets"] == "cats" and "case by case" in r["found_in_listing"]


@pytest.mark.parametrize("t", ["Rent $2,300. No dogs, non-negotiable.", "Rent $2,300. No pets. Non-negotiable."])
def test_a_firm_no_stays_a_no(t):
    r = parse_listing(t, "", pet_kind="dog")
    assert r.get("pets") in (None, "none") and "case by case" not in r.get("found_in_listing", "")
