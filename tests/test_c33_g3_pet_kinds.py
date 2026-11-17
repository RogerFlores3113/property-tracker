"""Cycle 33 group G3 (rule v): an amount named for one kind of pet belongs to that kind only."""
import os

import pytest

from mcp_util import call, server, text as mtext
from prophelper import enrich
from prophelper.parsers import parse_listing

HERE = os.path.join(os.path.dirname(__file__), "fixtures", "panel")


def P(text, kind="dog", **kw):
    return parse_listing(text, "", pet_kind=kind, **kw)


def F(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as fh:
        return fh.read()


def notes(r):
    return r.get("found_in_listing") or ""


# ---- 1. one charge kind, a price for each animal, every layout: the search's own animal picks the amount
RENT_LAYOUTS = [
    "Rent $1,500. Pet rent: $25 per cat, $50 per dog.",
    "Rent $1,500. Pet rent: $50 per dog, $25 per cat.",
    "Rent $1,500\nPets: cats and dogs ok\nPet rent: $25/mo per cat; $50/mo per dog\n",
    "Rent $1,500. Pet rent is $25 per month for cats and $50 per month for dogs.",
    "Rent $1,500 | Pet rent: $25 (cat) / $50 (dog) | Parking none",
    "Rent $1,500. Cat rent $25, dog rent $50.",
    "Rent $1,500. PET RENT: $25 PER CAT, $50 PER DOG",
    "Rent $1,500. Pets welcome. Dogs: $50/mo pet rent. Cats: $25/mo pet rent.",
]


@pytest.mark.parametrize("t", RENT_LAYOUTS)
@pytest.mark.parametrize("kind,want", [("dog", 50), ("cat", 25)])
def test_pet_rent_per_kind_uses_the_searchs_kind(t, kind, want):
    r = P(t, kind)
    assert r["pet_rent"] == want
    n = notes(r)
    assert "$25" in n and "$50" in n  # both amounts are named, so nothing is a silent drop
    assert "not counted anywhere" not in n


@pytest.mark.parametrize("t", RENT_LAYOUTS)
@pytest.mark.parametrize("kind", ["both", ""])
def test_pet_rent_per_kind_with_both_or_no_pet_saves_neither(t, kind):
    r = P(t, kind)
    assert "pet_rent" not in r
    assert "$25" in notes(r) and "$50" in notes(r)
    assert "not counted anywhere" not in notes(r)


DEPOSIT_LAYOUTS = [
    "Rent $1,500. Pet deposit $300 (cat), $500 (dog).",
    "Rent $1,500. $300 pet deposit (cats) / $500 (dogs).",
    "Rent $1,500. Pet deposit: $500 for dogs, $300 for cats.",
    "Rent $1,500. Cat deposit $300. Dog deposit $500.",
    "Rent $1,500\nPet deposit\n$300 per cat\n$500 per dog\n",
    "Rent $1,500 | Pet deposit: $500 (dogs) / $300 (cats) | Parking none",
    "Rent $1,500. Pets welcome. Dogs: $50/mo pet rent, $500 deposit. Cats: $25/mo pet rent, $300 deposit.",
]


@pytest.mark.parametrize("t", DEPOSIT_LAYOUTS)
@pytest.mark.parametrize("kind,want", [("dog", 500), ("cat", 300)])
def test_pet_deposit_per_kind_uses_the_searchs_kind(t, kind, want):
    r = P(t, kind)
    assert r["pet_deposit"] == want
    assert "$300" in notes(r) and "$500" in notes(r)
    assert "not counted anywhere" not in notes(r)
    assert "pet_fee" not in r


FEE_LAYOUTS = [
    "Rent $1,500. Pet fee: $200 for cats, $350 for dogs.",
    "Rent $1,500. Pet fee $200 per cat, $350 per dog.",
    "Rent $1,500. Cat fee $200. Dog fee $350.",
    "Rent $1,500. $200 cat fee, $350 dog fee.",
    "Rent $1,500. One-time pet fee: $350 (dogs), $200 (cats).",
]


@pytest.mark.parametrize("t", FEE_LAYOUTS)
@pytest.mark.parametrize("kind,want", [("dog", 350), ("cat", 200)])
def test_pet_fee_per_kind_uses_the_searchs_kind(t, kind, want):
    r = P(t, kind)
    assert r["pet_fee"] == want
    assert "not counted anywhere" not in notes(r)


def test_family_listing_dog_search_gets_the_dog_amounts():
    t = ("Spacious 3 bed house near the park\n12 Elm St, Redwood City, CA\n$2,400/mo.\n"
         "Pet rent: $25 per cat, $50 per dog. Pet deposit $300 (cat), $500 (dog).\nCats and dogs welcome, 2 max.")
    r = P(t, "dog")
    assert (r["pet_rent"], r["pet_deposit"], r["pets"], r["price"]) == (50, 500, "both", 2400)
    assert "$50 is not counted" not in notes(r) and "$500 is not counted" not in notes(r)
    r = P(t, "cat")
    assert (r["pet_rent"], r["pet_deposit"]) == (25, 300)


# ---- 2. an amount for one kind only (a search with the other kind never counts it)
SINGLE_CAT = [
    "Rent $1,500. Cat fee $200.",
    "Rent $1,500. Cats ok. $200 cat fee.",
    "Rent $1,500. Pet fee $200 non-refundable (cats).",
    "Rent $1,500. Pet fee $200 (cat).",
    "Rent $1,500. Pets: cats welcome, fee $200 for cats.",
    "Rent $1,500 | Pets ok | Cat fee: $200 non-refundable",
]


@pytest.mark.parametrize("t", SINGLE_CAT)
def test_a_cat_fee_is_never_counted_for_a_dog_search(t):
    r = P(t, "dog")
    assert "pet_fee" not in r
    n = notes(r)
    assert "$200" in n and "dog" in n and "not counted anywhere" not in n


@pytest.mark.parametrize("t", SINGLE_CAT)
def test_a_cat_fee_is_counted_for_a_cat_search(t):
    assert P(t, "cat")["pet_fee"] == 200


def test_dog_fee_beside_cat_rent_in_a_pets_line_for_a_cat_search():
    t = "Rent $1,500. Pets: Dogs welcome with $350 dog fee; cats $25/mo pet rent"
    r = P(t, "cat")
    assert r["pet_rent"] == 25 and "pet_fee" not in r
    assert "$350" in notes(r) and "not counted anywhere" not in notes(r)
    r = P(t, "dog")
    assert r["pet_fee"] == 350 and "pet_rent" not in r
    assert "$25" in notes(r) and "not counted anywhere" not in notes(r)


def test_roommates_l1_cat_fee_in_move_in_costs_for_a_dog_search():
    r = P(F("r32-roommates-l1.txt"), "dog")
    assert "pet_fee" not in r and r["price"] == 3350
    assert "The listing has a $300 cat fee. Your search has a dog, so it is not counted." in notes(r)
    assert P(F("r32-roommates-l1.txt"), "cat")["pet_fee"] == 300


def test_roommates_l4_and_l7_cat_fees_not_counted_for_a_dog_search():
    for name, amount in (("r32-roommates-l4.txt", 200), ("r32-roommates-l7.txt", 250)):
        r = P(F(name), "dog")
        assert "pet_fee" not in r, name
        assert f"${amount}" in notes(r)


# ---- 3. negatives: nothing named for a kind, nothing changes
@pytest.mark.parametrize("t,field,want", [
    ("Rent $1,500. Pet rent: $35 per pet.", "pet_rent", 35),
    ("Rent $1,500. Pet fee $300. Dogs and cats ok.", "pet_fee", 300),
    ("Rent $1,500. Pet deposit $400. Cats ok, dogs ok.", "pet_deposit", 400),
    ("Rent $1,500. Pets ok. Dog park on site. Pet rent $30/mo.", "pet_rent", 30),
])
@pytest.mark.parametrize("kind", ["dog", "cat"])
def test_amounts_with_no_kind_are_the_same_for_every_search(t, field, want, kind):
    assert P(t, kind)[field] == want


def test_the_same_amount_for_both_kinds_is_just_that_amount():
    r = P("Rent $1,500. Cat fee $250. Dog fee $250.", "dog")
    assert r["pet_fee"] == 250


# ---- 4. a place saved before the search named its pet: the other kind's amount is not counted after update_search
@pytest.mark.parametrize("t,amount", [
    ("Rent $1,500. 2 bed. Cats ok. Pet fee $300 non-refundable (cats).", 300),
    ("Rent $1,500. 2 bed. Cats ok. Cat fee $200.", 200),
    ("Rent $1,500. 2 bed. Cats ok. $250 cat fee.", 250),
])
def test_update_search_to_dog_stops_counting_a_cat_fee(store, t, amount):
    s = store.add_search("C", "rent")
    srv = server(store)
    call(srv, "add_place", title="A", address="1 Oak St", price=1500, listing_text=t)
    assert store.get_place(1)["pet_fee"] == amount  # saved from the listing when the search had no pet
    store.update_search(s["id"], pet_kind="cat", pet_count=1)
    e = enrich.enrich_places(store, store.get_search(s["id"]), [store.get_place(1)])[0]
    assert e["pet_fee"] == amount
    cat_total = e["cost_total"]
    store.update_search(s["id"], pet_kind="dog", pet_count=1)
    e = enrich.enrich_places(store, store.get_search(s["id"]), [store.get_place(1)])[0]
    assert e["pet_fee"] is None
    assert e["cost_total"] < cat_total
