"""Cycle 35 group G3 item 5: "Pets by approval only" beside a 50 lb limit makes the limit soft for a 60 lb dog ("Fits, but check"), never "Doesn't fit"."""
import os

import pytest

from prophelper import scoring
from prophelper.parsers import parse_listing

HERE = os.path.join(os.path.dirname(__file__), "fixtures", "panel")
DOG60 = {"kind": "dog", "weight": 60, "count": 1}


def F(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as fh:
        return fh.read()


def item(text, profile=DOG60, **extra):
    place = dict(parse_listing(text, "", pet_kind=profile.get("kind", "")))
    place["listing_text"] = text
    place.update(extra)
    c = {"id": 1, "kind": "pets", "weight": 10, "dealbreaker": True, "target": {}}
    return scoring.score_place(place, [c], pets=profile)["items"][0]


SOFT = [
    "3BR house. Pets by approval only; no pets over 50 lbs.",
    "3BR house. Pets by approval only. No pets over 50 lbs.",
    "3BR house. No pets over 50 lbs. Pets by approval only.",
    "3BR house. Pets with approval only (50 lb max).",
    "3BR house. Pets: approval required, maximum weight 50 lbs.",
    "3BR house.\nPets by approval only\nNo pets over 50 lbs\n",
    "3BR house. Dogs by approval only, max 50 lb.",
    "3BR house | PETS BY APPROVAL ONLY | NO PETS OVER 50 LBS",
]


@pytest.mark.parametrize("t", SOFT)
def test_an_approval_only_policy_makes_the_limit_soft(t):
    it = item(t)
    assert it["passes"] is not False and it["known"] is False, it
    assert "Doesn't fit" not in str(it) and "Ask" in it["detail"], it


def test_family_l4_whole_listing():
    it = item(F("r34-family-l4.txt"))
    assert it["passes"] is not False and it["known"] is False
    assert "50 lb" in it["detail"] and "60 lb" in it["detail"]


def test_the_same_with_the_pets_field_filled_in():
    it = item("3BR house. Pets by approval only; no pets over 50 lbs.", pets="dogs", pet_weight_limit=50)
    assert it["passes"] is not False and it["known"] is False


@pytest.mark.parametrize("t", [
    "3BR house. Dogs allowed. No pets over 50 lbs.",
    "3BR house. No dogs over 50 lbs.",
    "3BR house. Pets ok. No pets over 50 lbs. Approved applicants only.",
    "3BR house. Pets: no pets over 50 lbs; lease approval takes two days.",
])
def test_negatives_a_plain_limit_still_fails(t):
    it = item(t)
    assert it["passes"] is False, it
    assert "60 lb" in it["gap"] and "50 lb" in it["gap"]


@pytest.mark.parametrize("t", [
    "3BR house. No dogs over 50 lbs. No pets with approval only? Please inquire.",
    "3BR house. No dogs over 50 lbs. Pets by approval only? Ask us.",
])
def test_negatives_a_question_about_approval_is_not_a_policy(t):
    assert item(t)["passes"] is False
