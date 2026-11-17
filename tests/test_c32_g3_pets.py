"""Cycle 32 group G3 (rule q): a pet word that is not a yes never becomes a yes; a breed rule is not a ban; a question sets no weight limit."""
import os

import pytest

from prophelper import scoring
from prophelper.parsers import parse_listing

HERE = os.path.join(os.path.dirname(__file__), "fixtures", "panel")


def P(text, **kw):
    return parse_listing(text, "", **kw)


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


# ---- 1. "negotiable" and friends about one kind never save that kind (cats ok beside it)
@pytest.mark.parametrize("text", [
    "Rent $1,500. Pets: cats ok, dogs negotiable.",
    "Rent $1,500. Cats welcome, small dogs negotiable.",
    "Rent $1,500. Pets: Dogs negotiable; cats OK.",
    "Rent $1,500. Pets: cats ok (dogs negotiable)",
    "Rent $1,500\nPets: cats ok\nDogs: negotiable\n",
    "Rent $1,500. PETS: CATS OK, DOGS NEGOTIABLE.",
    "Rent $1,500 | Pets: cats ok | dogs negotiable",
    "Rent $1,500. Cats ok and dogs negotiable.",
    "Rent $1,500. Pets: cats ok, dogs maybe.",
])
def test_dogs_negotiable_beside_cats_ok_saves_cats_only(text):
    r = P(text)
    assert r["pets"] == "cats"
    assert "dogs" in notes(r)
    r2, s = fit(text, "dog")
    assert s["passes"] is None and s["known"] is False


@pytest.mark.parametrize("text", [
    "Rent $1,500. Pets: dogs negotiable. Cat fee $150.",
    "Rent $1,500. Dogs negotiable. $150 cat fee.",
    "Rent $1,500. Cat fee $150 non-refundable. Pets: dogs negotiable.",
    "Rent $1,500. Pets: small dogs considered. Cat fee $150.",
    "Rent $1,500\nDogs: case by case\nCat rent $25/mo\n",
    "Rent $1,500. Pets - dogs negotiable; cat deposit $200.",
])
def test_dogs_negotiable_beside_a_cat_charge_is_cats_not_dogs(text):
    r = P(text)
    assert r["pets"] == "cats"
    r2, s = fit(text, "dog")
    assert s["passes"] is None


@pytest.mark.parametrize("text", [
    "Rent $1,500. Pets: dogs negotiable.",
    "Rent $1,500. Dogs negotiable, cats negotiable.",
    "Rent $1,500. Pets negotiable.",
])
def test_only_open_words_leave_pets_empty(text):
    assert P(text).get("pets") in (None, "")


def test_negatives_a_price_or_a_yes_beside_the_word_keeps_the_kind():
    assert P("Rent $1,500. Dogs negotiable, $50/mo extra.")["pets"] == "dogs"
    assert P("Rent $1,500. Dogs welcome, fee negotiable.")["pets"] == "dogs"
    assert P("Rent $1,500. Cats and dogs welcome. Pet deposit negotiable.")["pets"] == "both"
    assert P("Rent $1,500. Small dogs ok, large dogs negotiable.")["pets"] == "dogs"


def test_reviewer_listings_nontech_l1_l11_uiuc_l9_l12():
    r = P(F("r31-nontech-l1.txt"))
    assert r["pets"] == "cats" and r["pet_fee"] == 250 and r["pet_rent"] == 25
    r = P(F("r31-nontech-l11.txt"))
    assert r["pets"] == "cats"
    r = P(F("r31-uiuc-l9.txt"))
    assert r["pets"] == "cats" and r["pet_fee"] == 150
    _r, s = fit(F("r31-uiuc-l9.txt"), "dog")
    assert s["passes"] is None
    r = P(F("r31-nontech-l12.txt"))
    assert r["pets"] == "cats" and r["pet_deposit"] == 200 and r["pet_rent"] == 25


def test_larger_dogs_considered_is_a_soft_limit_fits_but_check():
    for text in ("Rent $1,500. Dogs under 25 lbs ok, larger dogs considered with extra deposit.",
                 "Rent $1,500. Pets: Dogs under 25 lbs OK; larger dogs considered with extra deposit. Cats ok.",
                 "Rent $1,500\nDogs under 25 lbs ok\nLarger dogs considered with extra deposit\n"):
        r, s = fit(text, "dog", 60)
        assert r["pet_weight_limit"] == 25
        assert r["pets"] in ("dogs", "both")
        assert s["passes"] is None and "waived" in s["detail"], (text, s)


# ---- 2. a question never sets a weight limit
@pytest.mark.parametrize("text", [
    "Rent $2,000. Pets considered case by case; cats and dogs both ok with owner approval. Can the 40 lb limit be waived? Ask us.",
    "Rent $2,000. Dogs ok. Can the 40 lb limit be waived?",
    "Rent $2,000. Dogs ok. Is there a 40 lbs weight limit? Please inquire.",
    "Rent $2,000. Dogs ok; Can the 40 lbs limit be waived? Ask us; Cats ok",
    "Rent $2,000. Dogs ok\nCan the 40 lb limit be waived?\nFenced yard.",
    "Rent $2,000. Dogs ok | Could the 40 pound limit be waived? | Cats ok",
])
def test_a_question_sets_no_weight_limit(text):
    r = P(text)
    assert r.get("pet_weight_limit") in (None, "")
    assert "question" in notes(r)


def test_questions_keep_a_stated_limit_elsewhere():
    r = P("Rent $2,000. Dogs up to 40 lbs. Can the 40 lb limit be waived? Ask us.")
    assert r["pet_weight_limit"] == 40 and r["pets"] == "dogs"


def test_family_l2_whole_listing_no_weight_limit_and_dog_search_is_a_maybe():
    text = F("r31-family-l2.txt")
    r, s = fit(text, "dog", 60)
    assert r.get("pet_weight_limit") in (None, "")
    assert r.get("pets") in (None, "")
    assert s["passes"] is None
    assert "limit 40" not in s["detail"] and "40 lb" not in s["detail"]


# ---- 3. a breed rule is not a ban; "no breed restrictions" is not "no pets"
@pytest.mark.parametrize("text", [
    "Rent $2,000. Pet policy: no aggressive breeds.",
    "Rent $2,000. Pets: No aggressive dog breeds allowed.",
    "Rent $2,000. Pets: no pit bulls or aggressive breeds",
    "Rent $2,000\nPet policy: no restricted breeds\n",
    "Rent $2,000. Pets - no dangerous breeds; ask about fees",
    "Rent $2,000. PET POLICY: NO AGGRESSIVE BREEDS",
])
def test_a_breed_restriction_is_not_a_ban(text):
    r = P(text)
    assert r.get("pets") in (None, "")
    assert r.get("pet_breed_note")


def test_aggressive_breeds_beside_dogs_welcome_is_dogs():
    r = P("Rent $2,000. Pet policy: no aggressive breeds. Dogs welcome.")
    assert r["pets"] == "dogs" and "not clear" not in notes(r)
    r = P("Rent $2,000. Dogs welcome. Pets: no aggressive breeds.")
    assert r["pets"] == "dogs" and "not clear" not in notes(r)


@pytest.mark.parametrize("text", [
    "Rent $2,000. Pets: no breed restrictions. Dogs OK up to 70 lbs.",
    "Rent $2,000. Dogs OK up to 70 lbs. Pets: no breed restrictions.",
    "Rent $2,000. No breed restrictions; dogs up to 70 lbs ok.",
    "Rent $2,000\nPet policy: no restricted breeds\nDogs up to 70 lbs\n",
    "Rent $2,000. Pet policy: no breed restrictions, dogs ok up to 70 lbs",
    "Rent $2,000 | Pets: no breed or size restrictions | Dogs OK up to 70 lbs",
])
def test_no_breed_restrictions_beside_a_dog_weight(text):
    r = P(text)
    assert r["pets"] == "dogs" and r["pet_weight_limit"] == 70
    assert "not clear" not in notes(r)


def test_real_no_pets_still_none():
    for text in ("Rent $2,000. Pets: no.", "Rent $2,000. Pet policy: no pets allowed.", "Rent $2,000. No pets.", "Rent $2,000. Pets: none",
                 "Rent $2,000. Pet policy: no. Breed restrictions apply."):
        assert P(text)["pets"] == "none", text


def test_family_l5_whole_listing():
    r = P(F("r31-family-l5.txt"))
    assert r.get("pets") in (None, "", "dogs")
    assert r["pet_weight_limit"] == 50
    r2, s = fit(F("r31-family-l5.txt"), "dog", 60)
    assert "no pets" not in s["detail"].lower()
