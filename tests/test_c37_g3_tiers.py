"""Cycle 37 group G3 (rule p): pet tiers and limits.
1. "Dogs under 50 lbs: no deposit. Dogs over 50 lb: additional $600 deposit." is a tiered deposit: never a 50 lb weight limit, never "can be waived" or
   "with approval", and the note and the saved deposit agree (family l9).
2. "Pets limited to two." is a pet count limit (family l9).
3. "dogs over 50 lb $500 deposit" beside "cats ok" means dogs are allowed too (roommates l6).
4. A heavy-dog deposit is said once (uiuc l7, nontech l7)."""
import os

import pytest

from prophelper import money, parsers, scoring
from prophelper.parsers import parse_listing

HERE = os.path.join(os.path.dirname(__file__), "fixtures", "panel")


def F(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as fh:
        return fh.read()


def read(t, kind="dog", count=1):
    r = parse_listing(t, "", pet_kind=kind, pet_count=count)
    return r, str(r.get("found_in_listing") or "")


def pet_item(t, profile):
    place = dict(parse_listing(t, "", pet_kind=profile.get("kind", "")))
    place["listing_text"] = t
    c = {"id": 1, "kind": "pets", "weight": 10, "dealbreaker": True, "target": {}}
    return place, scoring.score_place(place, [c], pets=profile)["items"][0]


# ---- item 1: tiered deposit
TIERS = [
    "3 bed. Rent $2,380. Dogs under 50 lbs: no deposit. Dogs over 50 lb: additional $600 deposit.",
    "3 bed. Rent $2,380. Dogs under 50 lbs, no deposit; dogs over 50 lbs, additional $600 deposit.",
    "3 bed. Rent $2,380.\nDogs over 50 lb: additional $600 deposit.\nDogs under 50 lb: no deposit.",
    "3 bed. Rent $2,380. Dogs under 50 lbs (no deposit). Dogs over 50 lbs (additional $600 deposit).",
    "3 bed. Rent $2,380 | Dogs under 50 lbs: no pet deposit | Dogs over 50 lbs: extra $600 deposit",
    "3 bed. Rent $2,380. Pets ok.\nDogs under 50 lb - no deposit\nDogs over 50 lb - additional $600 deposit",
    "3 bed. Rent $2,380. Dogs under 50 lbs: free. Dogs over 50 lbs: an additional $600 deposit applies.",
]


@pytest.mark.parametrize("t", TIERS)
def test_tier_is_not_a_weight_limit(t):
    r, notes = read(t)
    assert r.get("pet_weight_limit") is None, r
    assert r.get("pet_deposit") in (None, 0), r
    assert "waive" not in notes and "approval" not in notes and "depend" not in notes, notes
    assert "$600 deposit only for larger pets (over 50 lbs)" in notes, notes
    assert "so it is not saved as the pet deposit" not in notes, notes
    assert "counted in the cash at move-in only when your dog is over 50 lb" in notes, notes
    lines600 = [ln for ln in notes.split("\n") if "600" in ln]
    assert len(lines600) == 1, notes  # said once
    assert not any(ln.startswith("Dogs under") or ln.startswith("Dogs over") for ln in notes.split("\n")), notes


@pytest.mark.parametrize("t", TIERS)
def test_tier_scores_and_cash(t):
    place = {**parse_listing(t, "", pet_kind="dog"), "listing_text": t, "price": 2380, "deposit": 2380}
    heavy = parsers.place_without_other_kind_charges(place, "dog", 60)
    light = parsers.place_without_other_kind_charges(place, "dog", 30)
    assert heavy["pet_deposit"] == 600
    assert (light.get("pet_deposit") or 0) == 0
    for w in (30, 60):
        _p, it = pet_item(t, {"kind": "dog", "weight": w, "count": 1})
        assert it["passes"] is True and it["known"] is True, it
        assert "waive" not in it["detail"] and "limit" not in it["detail"].lower().replace("limits", ""), it


def test_family_l9_whole_listing():
    t = F("r36-family-l9.txt")
    r, notes = read(t)
    assert r["pets"] == "dogs"
    assert r.get("pet_weight_limit") is None
    assert r["pet_count_limit"] == 2
    assert r["application_fee"] == 45
    assert "waive" not in notes and "approval" not in notes
    assert "$600 deposit only for larger pets (over 50 lbs)" in notes
    assert len([ln for ln in notes.split("\n") if "600" in ln]) == 1, notes
    _p, it = pet_item(t, {"kind": "dog", "weight": 60, "count": 1})
    assert it["passes"] is True, it
    _p, it = pet_item(t, {"kind": "dog", "weight": 60, "count": 3})
    assert it["passes"] is False and it["known"] is True, it
    assert "limit 2" in it["detail"], it


@pytest.mark.parametrize("t,limit", [
    ("3 bed. Rent $2,380. Dogs under 50 lbs only, $200 deposit.", 50),
    ("3 bed. Rent $2,380. Dogs up to 40 lbs. Dogs over 40 lbs: additional $500 deposit.", 40),
    ("3 bed. Rent $2,380. Dogs under 30 lbs. $300 pet deposit.", 30),
])
def test_negative_a_real_limit_stays_a_limit(t, limit):
    r, _n = read(t)
    assert r["pet_weight_limit"] == limit, r


def test_negative_over_with_no_deposit_tier_is_not_invented():
    r, notes = read("3 bed. Rent $2,380. Dogs welcome. Pet deposit $300.")
    assert r["pet_deposit"] == 300 and "only for larger pets" not in notes


# ---- item 2: pets limited to two
COUNTS = [
    ("3 bed. Rent $2,380. Pets limited to two.", 2),
    ("3 bed. Rent $2,380. Pets are limited to 2.", 2),
    ("3 bed. Rent $2,380. Limited to two pets per home.", 2),
    ("3 bed. Rent $2,380.\nPets: limited to two\nTenant pays all utilities.", 2),
    ("3 bed. Rent $2,380. Pets limited to two (2); cats and dogs ok.", 2),
    ("3 bed. Rent $2,380. Dogs limited to 2. Cats ok", 2),
    ("3 bed. Rent $2,380 | Pets limited to three | W/D in unit", 3),
    ("3 bed. Rent $2,380. PETS LIMITED TO TWO PER UNIT.", 2),
]


@pytest.mark.parametrize("t,n", COUNTS)
def test_count_limit_is_read_and_noted(t, n):
    r, notes = read(t)
    assert r["pet_count_limit"] == n, r
    assert "imited to" in notes.lower().replace("limited to","imited to"), notes  # the line is quoted as a note


@pytest.mark.parametrize("t,n", COUNTS[:3])
def test_more_pets_than_the_limit_fail(t, n):
    _p, it = pet_item(t + " Cats ok.", {"kind": "cat", "count": n + 1})
    assert it["passes"] is False and it["known"] is True, it
    _p, it = pet_item(t + " Cats ok.", {"kind": "cat", "count": n})
    assert it["passes"] is True, it


@pytest.mark.parametrize("t", [
    "3 bed. Rent $2,380. Parking limited to two cars. Dogs ok.",
    "3 bed. Rent $2,380. Pets limited to 25 lbs.",
    "3 bed. Rent $2,380. Limited to two pets? Please ask.",
    "3 bed. Rent $2,380. Dogs limited to small breeds.",
    "3 bed. Rent $2,380. Showings limited to two per day. Pets ok.",
])
def test_negative_count_limit_not_invented(t):
    r, _n = read(t)
    assert r.get("pet_count_limit") is None, r


# ---- item 3: a charge for dogs over N lb means dogs are allowed
CATS_AND_HEAVY = [
    "3 bed. Rent $3,280. Cats ok. Dogs over 50 lb $500 deposit.",
    "3 bed. Rent $3,280. Pet policy: dogs over 50 lb $500 deposit. Cats ok.",
    "3 bed. Rent $3,280. Cats ok; $500 deposit for dogs over 50 lb.",
    "3 bed. Rent $3,280.\nCats welcome\nDogs over 50 lb: $500 deposit",
    "3 bed. Rent $3,280. Cats ok (dogs over 50 lb: $500 deposit)",
    "3 bed. Rent $3,280. Cats ok | Dogs over 50 lb - $500 deposit",
    "3 bed. Rent $3,280. Cats are ok. A $500 deposit applies to dogs over 50 lb.",
]


@pytest.mark.parametrize("t", CATS_AND_HEAVY)
def test_heavy_dog_charge_means_dogs_allowed(t):
    r, notes = read(t)
    assert r["pets"] == "both", r
    assert r.get("pet_deposit") is None, r
    assert r.get("pet_weight_limit") is None, r
    assert "$500 deposit only for larger pets (over 50 lbs)" in notes, notes
    assert len([ln for ln in notes.split("\n") if "500" in ln]) == 1, notes
    place = {**r, "listing_text": t}
    assert parsers.place_without_other_kind_charges(place, "dog", 55)["pet_deposit"] == 500
    _p, it = pet_item(t, {"kind": "dog", "weight": 55, "count": 1})
    assert it["passes"] is True, it


def test_roommates_l6_whole_listing():
    t = F("r36-roommates-l6.txt")
    r, notes = read(t)
    assert r["pets"] == "both" and r.get("pet_deposit") is None
    assert "$500 deposit only for larger pets (over 50 lbs)" in notes
    assert len([ln for ln in notes.split("\n") if "500" in ln]) == 1, notes
    assert r["price"] == 3280
    _p, it = pet_item(t, {"kind": "dog", "weight": 55, "count": 1})
    assert it["passes"] is True, it


@pytest.mark.parametrize("t", [
    "3 bed. Rent $3,280. Cats only. Dogs over 50 lb not allowed.",
    "3 bed. Rent $3,280. Cats ok. No dogs over 50 lb. No dogs.",
    "3 bed. Rent $3,280. Cats ok. Dogs: no. Dogs over 50 lb $500 deposit.",
])
def test_negative_cats_only_stays_cats(t):
    r, _n = read(t)
    assert r.get("pets") in ("cats", None), r


def test_negative_no_dogs_over_keeps_the_flat_deposit():
    r, notes = read("3 bed. Rent $2,400. No dogs over 50 lbs. Additional $600 deposit due at signing.")
    assert "only for larger pets" not in notes


# ---- item 4: said once, with the field right
def test_uiuc_l7_heavy_dog_deposit_said_once():
    r, notes = read(F("r36-uiuc-l7.txt"), kind="", count=0)
    assert r.get("pet_deposit") is None, r
    assert r["pet_fee"] == 400 and r["pet_rent"] == 30 and r["pets"] == "both"
    assert "$1,500 deposit only for larger pets (over 50 lbs)" in notes, notes
    assert not any("1500" in ln for ln in notes.split("\n")), notes
    assert len([ln for ln in notes.split("\n") if "1,500" in ln]) == 1, notes


def test_nontech_l7_heavy_dog_deposit_said_once():
    r, notes = read(F("r36-nontech-l7.txt"), kind="", count=0)
    assert r["pet_deposit"] == 350 and r["pet_rent"] == 40 and r["pets"] == "both"
    assert "$500 deposit only for larger pets (over 50 lbs)" in notes, notes
    assert len([ln for ln in notes.split("\n") if "500" in ln]) == 1, notes
    assert not any(ln.startswith("Dogs over 50 lb require") for ln in notes.split("\n")), notes
    assert money is not None
