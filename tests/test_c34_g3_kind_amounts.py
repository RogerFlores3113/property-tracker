"""Cycle 34 group G3 items 2 to 6 (rule v): amounts named for one kind of pet."""
import os

import pytest

from prophelper.parsers import parse_listing

HERE = os.path.join(os.path.dirname(__file__), "fixtures", "panel")


def P(text, kind="dog", **kw):
    return parse_listing(text, "", pet_kind=kind, **kw)


def F(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as fh:
        return fh.read()


def N(r):
    return r.get("found_in_listing") or ""


# ---- item 2: "Pets: $300 deposit for cats, $500 for dogs"
DEP_FOR = [
    "Rent $1,500. Pets: $300 deposit for cats, $500 for dogs.",
    "Rent $1,500. Pets: $300 deposit for cats, $500 deposit for dogs. Monthly pet rent $30 cat / $45 dog.",
    "Rent $1,500\nPets welcome. Deposit: $300 for cats, $500 for dogs.\n",
    "Rent $1,500. Pet deposit is $500 for dogs and $300 for cats.",
    "Rent $1,500. PETS: $300 DEPOSIT FOR CATS; $500 FOR DOGS",
    "Rent $1,500 | Pets: $300 deposit (cats) | $500 deposit (dogs) | Parking none",
]


@pytest.mark.parametrize("t", DEP_FOR)
def test_deposit_for_dogs_is_saved_for_a_dog_search(t):
    r = P(t, "dog")
    assert r["pet_deposit"] == 500
    n = N(r)
    assert "$300 of that is not counted" not in n and "Only $300" not in n
    assert "not counted anywhere" not in n


@pytest.mark.parametrize("t", DEP_FOR)
def test_deposit_for_cats_is_saved_for_a_cat_search(t):
    r = P(t, "cat")
    assert r["pet_deposit"] == 300
    assert "$500 of that is not counted" not in N(r) and "not counted anywhere" not in N(r)


@pytest.mark.parametrize("t", DEP_FOR)
def test_deposit_for_two_kinds_with_no_pet_saves_neither_and_notes_both(t):
    r = P(t, "")
    assert "pet_deposit" not in r
    n = N(r)
    assert "$300" in n and "$500" in n
    assert "not counted anywhere" not in n


def test_roommates_l1_no_pet_is_one_quiet_note():
    r = P(F("r33-roommates-l1.txt"), "")
    n = N(r)
    assert "pet_rent" not in r and "pet_fee" not in r
    assert "$25" in n and "$50" in n
    assert "not counted anywhere" not in n
    assert n.count("$25") == 1 or "$25 per cat" in n  # named once, not repeated by two notes


# ---- item 5: "Pets: $25 per cat, $50 per dog" has no word for fee or rent
UNLABELED = [
    "Rent $1,500. Pets: $25 per cat, $50 per dog.",
    "Rent $1,500. Pets: $50 per dog, $25 per cat.",
    "Rent $1,500. Pets welcome: $25 per cat; $50 per dog",
    "Rent $1,500 | Pet policy: $25/cat, $50/dog | Parking none",
    "Rent $1,500. PETS: $25 PER CAT, $50 PER DOG",
    "Rent $1,500. Pets ok - $25 per cat and $50 per dog.",
    "Rent $1,500. Pets: $25 each cat / $50 each dog",
]


@pytest.mark.parametrize("t", UNLABELED)
@pytest.mark.parametrize("kind", ["dog", "cat", ""])
def test_unlabeled_per_kind_amounts_are_read_per_kind_with_a_question(t, kind):
    r = P(t, kind)
    assert r.get("pets") == "both"
    assert "pet_rent" not in r and "pet_fee" not in r and "pet_deposit" not in r  # monthly or one time is unknown: nothing is saved
    n = N(r)
    assert "$25" in n and "$50" in n
    assert "monthly" in n and "one time" in n
    assert "not counted anywhere" not in n
    if kind:
        assert f"Your search has a {kind}" in n
        want = "$50" if kind == "dog" else "$25"
        assert f"{want} is the one that applies" in n


def test_labeled_amounts_are_unchanged():
    r = P("Rent $1,500. Pet rent: $25 per cat, $50 per dog.", "dog")
    assert r["pet_rent"] == 50 and "pet_fee" not in r


def test_negative_other_per_amounts_are_not_pet_notes():
    r = P("Rent $1,500. Parking: $50 per car, $25 per bike. Pets: no pets.", "dog")
    assert r.get("pets") == "none"
    assert "monthly or a one time" not in N(r)


def test_nontech_l20_whole_listing():
    r = P(F("r33-nontech-l20.txt"), "dog")
    assert r["pets"] == "both" and r["pet_weight_limit"] == 40 and r["pet_count_limit"] == 2
    assert r["price"] == 1395 and r["deposit"] == 1395
    assert "pet_rent" not in r and "pet_fee" not in r
    n = N(r)
    assert "$50 is the one that applies" in n and "not counted anywhere" not in n
    r2 = P(F("r33-nontech-l20.txt"), "")
    assert "pet_rent" not in r2 and "$25" in N(r2) and "$50" in N(r2)


# ---- item 3: "Cats $300 (cat), $500 (dog) one-time pet fee"
ONE_TIME = [
    "Rent $1,475. Cats $300 (cat), $500 (dog) one-time pet fee, pet rent $30 per pet.",
    "Rent $1,475. One-time pet fee: $300 (cat), $500 (dog). Pet rent $30 per pet.",
    "Rent $1,475\nPets: $300 one-time fee for a cat, $500 for a dog; pet rent $30 per pet\n",
    "Rent $1,475. Pet fee (one time): cat $300, dog $500. $30 monthly pet rent per pet.",
    "Rent $1,475. CATS $300 (CAT), $500 (DOG) ONE-TIME PET FEE, PET RENT $30 PER PET.",
    "Rent $1,475. Pet rent $30 per pet. Cat $300 / dog $500 one-time pet fee.",
    "Rent $1,475. Pets: dogs up to 40 lbs OK, $300 (cat), $500 (dog) one-time. Pet rent $30 per pet.",
]


@pytest.mark.parametrize("t", ONE_TIME)
def test_one_time_pet_fee_per_kind_dog(t):
    r = P(t, "dog")
    assert r["pet_fee"] == 500 and r["pet_rent"] == 30
    assert r.get("pets") == "both"
    n = N(r)
    assert "not counted anywhere" not in n and "$500 of that are not counted" not in n and "Only $300 and $500" not in n


@pytest.mark.parametrize("t", ONE_TIME)
def test_one_time_pet_fee_per_kind_cat(t):
    r = P(t, "cat")
    assert r["pet_fee"] == 300 and r["pet_rent"] == 30
    assert r.get("pets") == "both"


@pytest.mark.parametrize("t", ONE_TIME)
def test_one_time_pet_fee_per_kind_no_pet(t):
    r = P(t, "")
    assert "pet_fee" not in r
    n = N(r)
    assert "$300" in n and "$500" in n and "not counted anywhere" not in n


def test_nontech_l21_whole_listing_dog_and_cash():
    r = P(F("r33-nontech-l21.txt"), "dog")
    assert r["pet_fee"] == 500 and r["pet_rent"] == 30 and r["pets"] == "both"
    assert r["price"] == 1475 and r["parking_cost"] == 55
    assert "not counted anywhere" not in N(r) and "Only $300" not in N(r)


# ---- item 4: "Cat $25 per cat, $50 per dog pet rent. Pet deposit $300 (cat), $500 (dog)" is pets both
CAT_LEAD = [
    "Rent $1,455. Cat $25 per cat, $50 per dog pet rent. Pet deposit $300 (cat), $500 (dog).",
    "Rent $1,455. Cat rent $25 per cat, $50 per dog. Pet deposit $300 (cat), $500 (dog).",
    "Rent $1,455\nDog $50 per dog, $25 per cat pet rent.\nPet deposit $500 (dog), $300 (cat)\n",
    "Rent $1,455. CAT $25 PER CAT, $50 PER DOG PET RENT. PET DEPOSIT $300 (CAT), $500 (DOG).",
    "Rent $1,455. Cats $25 per cat; dogs $50 per dog (pet rent). Pet deposit: $300 for a cat, $500 for a dog.",
    "Rent $1,455 | Cat: $25 per cat, $50 per dog pet rent | Pet deposit $300 (cat), $500 (dog)",
]


@pytest.mark.parametrize("t", CAT_LEAD)
@pytest.mark.parametrize("kind,rent,dep", [("dog", 50, 500), ("cat", 25, 300)])
def test_cat_first_wording_is_both_and_picks_the_searched_kind(t, kind, rent, dep):
    r = P(t, kind)
    assert r.get("pets") == "both"
    assert r["pet_rent"] == rent and r["pet_deposit"] == dep
    n = N(r)
    assert "not counted anywhere" not in n and "Only $25" not in n


@pytest.mark.parametrize("t", CAT_LEAD)
def test_cat_first_wording_no_pet_is_both_and_saves_no_amount(t):
    r = P(t, "")
    assert r.get("pets") == "both"
    assert "pet_rent" not in r and "pet_deposit" not in r
    n = N(r)
    assert "$25" in n and "$50" in n and "$300" in n and "$500" in n
    assert "not counted anywhere" not in n


def test_uiuc_l23_whole_listing_dog_and_cat():
    r = P(F("r33-uiuc-l23.txt"), "dog")
    assert r["pets"] == "both" and r["pet_rent"] == 50 and r["pet_deposit"] == 500
    assert r["price"] == 1455 and r["parking_cost"] == 100
    assert "not counted anywhere" not in N(r) and "$25 of that" not in N(r)
    r = P(F("r33-uiuc-l23.txt"), "cat")
    assert r["pets"] == "both" and r["pet_rent"] == 25 and r["pet_deposit"] == 300


def test_negative_cats_only_listing_is_still_cats():
    r = P("Rent $1,455. Cats only, $25 per cat pet rent. Pet deposit $300 (cat).", "cat")
    assert r["pets"] == "cats" and r["pet_rent"] == 25 and r["pet_deposit"] == 300
