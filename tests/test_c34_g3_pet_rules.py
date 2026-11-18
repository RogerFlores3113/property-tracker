"""Cycle 34 group G3 items 7 to 11: pets both, weight limits, soft limits, breed notes and "per dog" wording."""
import os

import pytest

from mcp_util import call, server
from prophelper import scoring
from prophelper.parsers import parse_listing

HERE = os.path.join(os.path.dirname(__file__), "fixtures", "panel")


def P(text, kind="dog", **kw):
    return parse_listing(text, "", pet_kind=kind, **kw)


def F(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as fh:
        return fh.read()


def N(r):
    return r.get("found_in_listing") or ""


def fit(text, kind="dog", weight=60, count=1):
    r = P(text, kind)
    place = dict(r)
    place["listing_text"] = text
    place["reader_notes"] = N(r)
    want = {"cat": "cats", "dog": "dogs", "both": "both"}[kind]
    crit = {"kind": "pets", "weight": 15, "dealbreaker": True, "target": {"want": want}}
    return r, scoring._score_pets(crit, place, {"pets": {"kind": kind, "weight": weight, "count": count}})


# ---- item 7: "Cats and dogs welcome, 2 max" is pets both with a count of 2
BOTH = [
    "Rent $3,150. Cats and dogs welcome, 2 max.",
    "Rent $3,150. Pets: cats and dogs welcome, 2 max. Dogs larger than 50 lbs not permitted.",
    "Rent $3,150. Cats & dogs welcome (2 max)",
    "Rent $3,150. We welcome cats and dogs; two pets maximum.",
    "Rent $3,150\nCats and dogs welcome, 2 max\nParking required, $140/mo\n",
    "Rent $3,150. CATS AND DOGS WELCOME, 2 MAX.",
    "Rent $3,150 | Both cats and dogs welcome, 2 pet max | Parking none",
    "Utilities billed back by Conservice about $60. Resident pays electric, gas. Cats and dogs welcome, 2 max. Rent $3,150.",
]


@pytest.mark.parametrize("t", BOTH)
@pytest.mark.parametrize("kind", ["dog", "cat", ""])
def test_cats_and_dogs_welcome_is_both(t, kind):
    r = P(t, kind)
    assert r["pets"] == "both"
    assert r.get("pet_count_limit") == 2


def test_roommates_l9_whole_listing():
    for kind in ("dog", "cat", ""):
        r = P(F("r33-roommates-l9.txt"), kind)
        assert r["pets"] == "both" and r["pet_count_limit"] == 2 and r["pet_weight_limit"] == 50
        assert r["price"] == 3150 and r["parking_cost"] == 140 and r["deposit"] == 1575
    r = P(F("r33-roommates-l9.txt"), "dog")
    assert r["pet_rent"] == 50
    assert P(F("r33-roommates-l9.txt"), "cat")["pet_rent"] == 25


def test_roommates_l9_saved_through_add_place(store):
    s = store.add_search("C", "rent")
    store.update_search(s["id"], pet_kind="dog", pet_count=1)
    call(server(store), "add_place", title="E", address="5600 N Sheridan Rd", listing_text=F("r33-roommates-l9.txt"))
    p = store.list_places(search_id=s["id"])[0]
    assert p["pets"] == "both" and p["pet_count_limit"] == 2


@pytest.mark.parametrize("t", [
    "Rent $3,150. Cats and dogs welcome, 2 max. No dogs.",
    "Rent $3,150. Pets: no pets. Cats and dogs were allowed before.",
])
def test_negative_a_no_beats_the_welcome(t):
    assert P(t).get("pets") != "both"


# ---- item 8: "Dogs larger than 40 lbs not permitted" is a 40 lb limit
LIMIT = [
    "Rent $1,395. Pets: $25 per cat, $50 per dog. Max 2 pets. Dogs larger than 40 lbs not permitted.",
    "Rent $1,395. Dogs over 40 lbs are not permitted.",
    "Rent $1,395. Dogs larger than 40 lbs: not permitted.",
    "Rent $1,395. Dogs larger than 40 lbs - not allowed.",
    "Rent $1,395. Not permitted: dogs larger than 40 lbs.",
    "Rent $1,395\nDogs heavier than 40 pounds not allowed\n",
    "Rent $1,395. DOGS LARGER THAN 40 LBS NOT PERMITTED",
    "Rent $1,395. Dogs above 40 lbs: not permitted",
    "Rent $1,395. Pets: dogs welcome (dogs larger than 40 lbs not permitted).",
    "Rent $1,395. Prohibited - dogs over 40 pounds.",
]


@pytest.mark.parametrize("t", LIMIT)
def test_larger_dogs_not_permitted_is_a_limit(t):
    r = P(t, "dog")
    assert r["pet_weight_limit"] == 40
    r = P(t, "")
    assert r["pet_weight_limit"] == 40


def test_a_dog_over_the_limit_fails_the_pets_rule():
    _r, s = fit("Rent $1,395. Dogs larger than 40 lbs not permitted.", "dog", 60)
    assert s["passes"] is False
    _r, s = fit("Rent $1,395. Dogs larger than 40 lbs not permitted.", "dog", 30)
    assert s["passes"] is not False


def test_nontech_l20_limit():
    r = P(F("r33-nontech-l20.txt"), "dog")
    assert r["pet_weight_limit"] == 40 and r["pet_count_limit"] == 2


@pytest.mark.parametrize("t", [
    "Rent $1,395. Larger dogs are not permitted.",
    "Rent $1,395. Can dogs larger than 40 lbs be allowed? Ask us.",
    "Rent $1,395. Packages larger than 40 lbs not permitted in the lobby.",
])
def test_negative_no_number_or_a_question_or_a_package_is_no_limit(t):
    assert "pet_weight_limit" not in P(t, "dog")


# ---- item 9: "Larger dogs considered. Dogs under 25 lbs." (either order) is a soft limit
SOFT = [
    "Rent $1,500. Larger dogs considered. Dogs under 25 lbs.",
    "Rent $1,500. Dogs under 25 lbs. Larger dogs considered.",
    "Rent $1,500\nLarger dogs considered\nDogs under 25 lbs\n",
    "Rent $1,500. LARGER DOGS CONSIDERED. DOGS UNDER 25 LBS.",
    "Rent $1,500. Larger dogs considered; dogs up to 25 lbs.",
    "Rent $1,500. Larger dogs negotiable. Dogs up to 25 lbs ok.",
    "Rent $1,500. Bigger dogs case by case. Dogs max 25 lbs.",
    "Rent $1,500 | Larger dogs considered | Dogs under 25 lbs",
]


@pytest.mark.parametrize("t", SOFT)
def test_larger_dogs_considered_in_any_order_is_soft(t):
    r = P(t, "dog")
    assert r["pet_weight_limit"] == 25
    assert "waived" in N(r) or "larger" in N(r).lower() or "bigger" in N(r).lower()
    _r, s = fit(t, "dog", 55)
    assert s["passes"] is None and s["known"] is False
    _r, s = fit(t, "dog", 20)
    assert s["passes"] is not False


@pytest.mark.parametrize("t", [
    "Rent $1,500. Dogs under 25 lbs only. Larger dogs not accepted.",
    "Rent $1,500. Larger dogs not considered. Dogs under 25 lbs.",
])
def test_negative_a_hard_limit_still_fails_a_heavy_dog(t):
    _r, s = fit(t, "dog", 55)
    assert s["passes"] is False


# ---- item 10: "No breed restrictions apply to cats" is never the breed note
NO_BREED = [
    "Rent $2,325. Pet policy: dogs considered, ask for details. No breed restrictions apply to cats.",
    "Rent $2,325. Cats welcome. No breed restrictions apply to cats.",
    "Rent $2,325. No breed restrictions for cats.",
    "Rent $2,325. Cats ok; no breed restrictions for cats. Dogs under 30 lbs.",
    "Rent $2,325\nNo breed restrictions apply to cats\nCats welcome\n",
    "Rent $2,325. NO BREED RESTRICTIONS APPLY TO CATS.",
    "Rent $2,325. Cat breed restrictions: none.",
]


@pytest.mark.parametrize("t", NO_BREED)
@pytest.mark.parametrize("kind", ["dog", "cat", ""])
def test_no_breed_restrictions_is_never_quoted_as_a_note(t, kind):
    r = P(t, kind)
    assert "breed restriction" not in N(r).lower() and "breed rule" not in N(r).lower()
    assert "not counted anywhere" not in N(r)


@pytest.mark.parametrize("t", NO_BREED[:1] + NO_BREED[3:4])
def test_no_breed_restrictions_for_cats_is_not_the_dog_breed_note(t):
    assert not P(t, "dog").get("pet_breed_note")  # the listing names dogs too, so a line about cats says nothing about their breeds


def test_family_l12_whole_listing_and_store_path(store):
    r = P(F("r33-family-l12.txt"), "dog")
    assert not r.get("pet_breed_note")
    assert "breed restriction" not in N(r).lower()
    assert r["price"] == 2325
    s = store.add_search("C", "rent")
    call(server(store), "add_place", title="Ranch", address="1 Main St", listing_text=F("r33-family-l12.txt"))
    p = store.list_places(search_id=s["id"])[0]
    assert not p.get("pet_breed_note")
    assert "breed restriction" not in (p.get("reader_notes") or "").lower()


@pytest.mark.parametrize("t,want", [
    ("Rent $2,325. Dogs ok. No pit bulls.", "No pit bulls"),
    ("Rent $2,325. Pets: no aggressive breeds.", "aggressive breeds"),
    ("Rent $2,325. Restricted breeds: pit bulls, rottweilers", "Restricted breeds: pit bulls, rottweilers"),
])
def test_negative_a_real_breed_restriction_is_still_the_note(t, want):
    assert want in (P(t, "dog").get("pet_breed_note") or "")


# ---- item 11: "$40/mo per dog" says it is per dog, never "Ask if it is for each pet"
PER_DOG = [
    "Rent $2,000. Pets: $40/mo per dog",
    "Rent $2,000. Dogs welcome. Pets: $40/mo per dog.",
    "Rent $2,000. Pets: $40 per month per dog",
    "Rent $2,000. PETS: $40/MO PER DOG",
    "Rent $2,000\nPets: $40/mo per dog\nParking none\n",
    "Rent $2,000 | Pets: $40/mo per dog | Parking none",
]


@pytest.mark.parametrize("t", PER_DOG)
@pytest.mark.parametrize("kind", ["dog", ""])
def test_per_dog_is_said_to_be_per_dog(t, kind):
    r = P(t, kind)
    n = N(r)
    assert "Ask if it is for each pet" not in n
    assert "not counted anywhere" not in n
    if kind == "dog":
        assert r["pet_rent"] == 40
        assert "for each dog" in n


def test_negative_a_bare_pet_amount_still_asks():
    r = P("Rent $2,000. Pets: $40/mo", "dog")
    assert r["pet_rent"] == 40 and "Ask if it is for each pet" in N(r)
