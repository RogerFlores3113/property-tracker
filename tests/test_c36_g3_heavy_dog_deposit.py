"""Cycle 36 group G3 item 3: "Dogs over 50 lbs may be considered, additional $600 deposit" is a deposit only a dog over 50 lb pays. A note says so,
and the cash at move-in counts it only when the search's dog is over 50 lb."""
import os

import pytest

from prophelper import enrich, money, parsers
from prophelper.parsers import parse_listing

HERE = os.path.join(os.path.dirname(__file__), "fixtures", "panel")


def F(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as fh:
        return fh.read()


WORDINGS = [
    "3 bed. Rent $2,400. Pets allowed. Dogs up to 50 lbs. Dogs over 50 lbs may be considered, additional $600 deposit.",
    "3 bed. Rent $2,400. Dogs over 50 lbs: additional $600 deposit, with approval. Pet rent $40/mo.",
    "3 bed. Rent $2,400. Dogs over 50 lbs considered; additional $600 deposit.",
    "3 bed. Rent $2,400.\nDogs over 50 lbs may be considered\nAdditional $600 deposit",
    "3 bed. Rent $2,400. Larger dogs (over 50 lbs) considered with an extra $600 deposit.",
    "3 bed. Rent $2,400. Dogs over 50 lbs may be considered (additional $600 deposit).",
    "3 bed. Rent $2,400 | Dogs over 50 lbs considered | additional $600 deposit",
]


@pytest.mark.parametrize("t", WORDINGS)
def test_note_and_field(t):
    r = parse_listing(t, "", pet_kind="dog")
    assert r.get("pet_deposit") is None, r
    notes = r["found_in_listing"]
    assert "$600 deposit only for larger pets (over 50 lbs)" in notes, notes
    assert "counted in the cash at move-in only when your dog is over 50 lb" in notes, notes


@pytest.mark.parametrize("t", WORDINGS)
def test_only_a_heavy_dog_is_counted(t):
    place = {**parse_listing(t, "", pet_kind="dog"), "listing_text": t, "price": 2400, "deposit": 2400}
    assert parsers.place_without_other_kind_charges(place, "dog", 60)["pet_deposit"] == 600
    assert parsers.place_without_other_kind_charges(place, "dog", 30).get("pet_deposit") is None
    assert parsers.place_without_other_kind_charges(place, "dog", 50).get("pet_deposit") is None
    assert parsers.place_without_other_kind_charges(place, "dog", None).get("pet_deposit") is None
    assert parsers.place_without_other_kind_charges(place, "cat", 60).get("pet_deposit") is None
    heavy = money.cash_at_move_in(parsers.place_without_other_kind_charges(place, "dog", 60), True, 1)
    light = money.cash_at_move_in(parsers.place_without_other_kind_charges(place, "dog", 30), True, 1)
    assert heavy["total"] - light["total"] == 600


def test_a_flat_pet_deposit_beside_it_is_kept_and_added():
    t = "3 bed. Rent $2,400. Pet deposit $300. Dogs over 50 lbs require an additional $600 deposit."
    r = parse_listing(t, "", pet_kind="dog")
    assert r["pet_deposit"] == 300
    place = {**r, "listing_text": t}
    assert parsers.place_without_other_kind_charges(place, "dog", 60)["pet_deposit"] == 900
    assert parsers.place_without_other_kind_charges(place, "dog", 30).get("pet_deposit") == 300


def test_family_l4_whole_listing_through_the_app(store):
    t = F("r35-family-l4.txt")
    s = store.add_search("Family", "rent", budget_max=3000, pet_kind="dog", pet_count=1, pet_weight=60)
    r = parse_listing(t, "", pet_kind="dog", pet_count=1)
    assert r.get("pet_deposit") is None and r["pet_rent"] == 40 and r["pet_weight_limit"] == 50
    assert "only for larger pets (over 50 lbs)" in r["found_in_listing"]
    p, _ = store.add_place(title="Willow Creek", address="9 Willow Creek Dr", price=2400, listing_text=t, pet_rent=40, pets="dogs")
    heavy = enrich.enrich_places(store, store.get_search(s["id"]), [p])[0]
    assert any(x["label"] == "Pet deposit" and x["amount"] == 600 for x in heavy["cost"]["cash_at_move_in"]["parts"])
    store.update_search(s["id"], pet_weight=30)
    light = enrich.enrich_places(store, store.get_search(s["id"]), [p])[0]
    assert not any("Pet deposit" in x["label"] for x in light["cost"]["cash_at_move_in"]["parts"])


@pytest.mark.parametrize("t", [
    "3 bed. Rent $2,400. Dogs allowed. $600 pet deposit.",
    "3 bed. Rent $2,400. No dogs over 50 lbs. Additional $600 deposit due at signing.",
    "3 bed. Rent $2,400. Dogs under 50 lbs only. Pet deposit $600.",
])
def test_a_flat_deposit_is_still_the_pet_deposit_or_left_alone(t):
    r = parse_listing(t, "", pet_kind="dog")
    assert "only for larger pets" not in r.get("found_in_listing", "")
    place = {**r, "listing_text": t}
    assert parsers.conditional_deposit_for_dog(place, "dog", 60) == {}
