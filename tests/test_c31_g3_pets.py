"""Cycle 31 group G3: "negotiable", "case by case", "ask" about a kind of pet are a maybe for that kind (rule k); a question line sets nothing (rule l)."""
import os

import pytest

from prophelper import scoring
from prophelper.parsers import parse_listing

HERE = os.path.join(os.path.dirname(__file__), "fixtures", "panel")


def P(text):
    return parse_listing(text, "")


def F(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as fh:
        return fh.read()


def notes(r):
    return r.get("found_in_listing") or ""


def fit(text, kind="dog", weight=60, count=1):
    r = P(text)
    place = dict(r)
    place["listing_text"] = text
    place["reader_notes"] = notes(r)
    want = {"cat": "cats", "dog": "dogs", "both": "both"}[kind]
    crit = {"kind": "pets", "weight": 15, "dealbreaker": True, "target": {"want": want}}
    return r, scoring._score_pets(crit, place, {"pets": {"kind": kind, "weight": weight, "count": count}})


# ---- item 1: a maybe about one kind is never a yes and never a no for that kind
@pytest.mark.parametrize("text", [
    "Pet policy: cats OK, dogs negotiable. Rent $2,200. 3 bed. Fenced yard.",
    "Cats OK. Dogs: case by case. Rent $2,200. 3 bed.",
    "Cats welcome, dogs possibly. Rent $2,200. 3 bed.",
    "Cats ok. Dogs depends on breed. Rent $2,200. 3 bed.",
    "Cats ok\nDogs: ask\nRent $2,200\n3 bed",
    "Dogs negotiable, cats ok. Rent $2,200. 3 bed.",
    "Pets: cats allowed | dogs maybe | Rent $2,200 | 3 bed",
])
def test_dogs_open_saves_cats_only_and_dog_search_is_a_maybe(text):
    r, s = fit(text, "dog")
    assert r["pets"] == "cats"
    assert "dogs" in notes(r) and "case by case" in notes(r)
    assert s["passes"] is None and s["known"] is False
    assert "maybe" in s["detail"] and "dogs" in s["detail"]


def test_cat_search_still_fits_when_dogs_are_open():
    r, s = fit("Pet policy: cats OK, dogs negotiable. Rent $2,200. 3 bed.", "cat", None, 1)
    assert s["passes"] is True


def test_both_pets_search_is_a_maybe():
    r, s = fit("Cats OK. Dogs: case by case. Rent $2,200.", "both")
    assert s["passes"] is None


@pytest.mark.parametrize("text", [
    "Dogs ok. Cats: ask. Rent $2,200. 3 bed.",
    "Dogs welcome, cats maybe. Rent $2,200. 3 bed.",
    "Dogs allowed. Cats negotiable. Rent $2,200.",
])
def test_cats_open_saves_dogs_only(text):
    r, s = fit(text, "cat", None, 1)
    assert r["pets"] == "dogs"
    assert s["passes"] is None and "cats" in s["detail"]


def test_l8_family_listing():
    r, s = fit(F("r30-family-l8.txt"), "dog")
    assert r["pets"] == "cats" and r["price"] == 2200 and r["fenced_yard"] == 1
    assert s["passes"] is None


def test_l6_family_listing_dog_search_not_a_fail():
    r, s = fit(F("r30-family-l6.txt"), "dog", 35)
    assert r["pets"] == "cats"
    assert s["passes"] is None
    assert "wanted dogs allowed" not in s["detail"]


def test_a_no_for_the_kind_stays_a_fail():
    r, s = fit("Cats OK. No dogs. Rent $2,200.", "dog")
    assert r["pets"] == "cats" and s["passes"] is False


def test_negotiable_with_a_price_is_still_the_kind():
    assert P("Cats negotiable, $50 extra. $1,100/mo 1 bed")["pets"] == "cats"


def test_negotiable_alone_is_not_saved():
    r = P("Dogs negotiable. Rent $2,200. 3 bed.")
    assert not r.get("pets")


# ---- item 2: a question line is not a rule and not an exception to one (rule l)
@pytest.mark.parametrize("text", [
    "No dogs over 30 pounds. No pets with approval only? Please inquire. Rent $2,200.",
    "No dogs over 30 lbs. Can exceptions be made? Please ask. Rent $2,200.",
    "Dogs max 30 lb.\nApproval for larger dogs?\nRent $2,200.",
    "Pets ok, no dogs over 30 pounds. Waived with approval? Rent $2,200.",
])
def test_question_is_not_a_waiver(text):
    r, s = fit(text, "dog", 60)
    assert r.get("pet_weight_limit") == 30
    assert s["passes"] is False and s["known"] is True
    assert "waived" not in s["detail"] and "approval" not in s["detail"]
    assert "30" in s["detail"]


def test_l7_family_listing_fails_a_60_lb_dog_plainly():
    r, s = fit(F("r30-family-l7.txt"), "dog", 60)
    assert r["pets"] == "dogs" and r["pet_weight_limit"] == 30
    assert s["passes"] is False and "waived" not in s["detail"]


def test_a_stated_waiver_still_is_a_maybe():
    r, s = fit("No dogs over 30 pounds unless approved by management. Rent $2,200.", "dog", 60)
    assert s["passes"] is None and "waived" in s["detail"]
    r, s = fit("No dogs over 30 pounds. Exceptions may be granted. Rent $2,200.", "dog", 60)
    assert s["passes"] is None and "waived" in s["detail"]
