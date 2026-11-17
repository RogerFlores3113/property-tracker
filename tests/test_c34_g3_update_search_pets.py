"""Cycle 34 group G3 item 6: after update_search changes the pet kind, per-kind amounts are picked again for the new kind."""
import os

import pytest

from mcp_util import call, server, text as mtext
from prophelper import enrich

HERE = os.path.join(os.path.dirname(__file__), "fixtures", "panel")


def F(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as fh:
        return fh.read()


LAYOUTS = [
    "Hartwell Place 1BR - $1,480. 15 E Hartwell Dr, Champaign, IL 61820\nPets welcome: pet rent $25 per cat, $50 per dog. Pet deposit $300 (cat), $500 (dog).",
    "1BR $1,480. 15 E Hartwell Dr, Champaign, IL 61820. Pet rent: $50 per dog, $25 per cat. Pet deposit: $500 for dogs, $300 for cats.",
    "1BR $1,480 | 15 E Hartwell Dr, Champaign, IL 61820 | Pets ok | Pet rent $25 (cat) / $50 (dog) | Pet deposit $300 (cat) / $500 (dog)",
    "1BR $1,480. 15 E Hartwell Dr, Champaign, IL 61820. Cat rent $25, dog rent $50. Cat deposit $300, dog deposit $500.",
    "1BR $1,480. 15 E Hartwell Dr, Champaign, IL 61820. PETS WELCOME: PET RENT $25 PER CAT, $50 PER DOG. PET DEPOSIT $300 (CAT), $500 (DOG).",
    "1BR $1,480. 15 E Hartwell Dr, Champaign, IL 61820.\nPets: cats and dogs ok\nPet rent: $25/mo per cat; $50/mo per dog\nPet deposit: $300 cat; $500 dog\n",
]


def _place(store, sid):
    return store.list_places(search_id=sid)[0]


@pytest.mark.parametrize("t", LAYOUTS)
def test_switching_the_kind_picks_the_amount_again(store, t):
    s = store.add_search("C", "rent")
    srv = server(store)
    call(srv, "add_place", title="A", address="15 E Hartwell Dr", price=1480, listing_text=t)
    p = _place(store, s["id"])
    assert "pet_rent" not in p or p["pet_rent"] is None  # no pet in the search: neither amount is saved
    store.update_search(s["id"], pet_kind="dog", pet_count=1)
    p = _place(store, s["id"])
    assert (p["pet_rent"], p["pet_deposit"]) == (50, 500)
    assert "Your search has a cat" not in (p.get("reader_notes") or "")
    store.update_search(s["id"], pet_kind="cat", pet_count=1)
    p = _place(store, s["id"])
    assert (p["pet_rent"], p["pet_deposit"]) == (25, 300)
    assert "Your search has a dog" not in (p.get("reader_notes") or "")
    assert "not counted anywhere" not in (p.get("reader_notes") or "")
    e = enrich.enrich_places(store, store.get_search(s["id"]), [p])[0]
    assert (e["pet_rent"], e["pet_deposit"]) == (25, 300)
    store.update_search(s["id"], pet_kind="dog", pet_count=1)
    p = _place(store, s["id"])
    assert (p["pet_rent"], p["pet_deposit"]) == (50, 500)
    assert "Your search has a cat" not in (p.get("reader_notes") or "")


def test_switching_to_both_empties_the_per_kind_amounts(store):
    s = store.add_search("C", "rent")
    srv = server(store)
    call(srv, "add_place", title="A", address="15 E Hartwell Dr", price=1480, listing_text=LAYOUTS[0])
    store.update_search(s["id"], pet_kind="dog", pet_count=1)
    assert _place(store, s["id"])["pet_rent"] == 50
    store.update_search(s["id"], pet_kind="both", pet_count=2)
    p = _place(store, s["id"])
    assert p["pet_rent"] is None and p["pet_deposit"] is None
    n = p.get("reader_notes") or ""
    assert "$25" in n and "$50" in n and "$300" in n and "$500" in n
    assert "Your search has a dog" not in n


def test_uiuc_l26_listing_dog_then_cat(store):
    s = store.add_search("C", "rent")
    store.update_search(s["id"], pet_kind="dog", pet_count=1)
    srv = server(store)
    call(srv, "add_place", title="Hartwell", address="15 E Hartwell Dr", price=1480, listing_text=F("r33-uiuc-l26.txt"))
    p = _place(store, s["id"])
    assert (p["pet_rent"], p["pet_deposit"]) == (50, 500)
    store.update_search(s["id"], pet_kind="cat", pet_count=1)
    p = _place(store, s["id"])
    assert (p["pet_rent"], p["pet_deposit"]) == (25, 300)
    assert "Your search has a dog" not in (p.get("reader_notes") or "")


def test_negative_a_hand_typed_amount_is_kept(store):
    s = store.add_search("C", "rent")
    store.update_search(s["id"], pet_kind="dog", pet_count=1)
    srv = server(store)
    call(srv, "add_place", title="A", address="15 E Hartwell Dr", price=1480, listing_text=LAYOUTS[0])
    pid = _place(store, s["id"])["id"]
    call(srv, "update_place", place_id=pid, pet_rent=65)
    store.update_search(s["id"], pet_kind="cat", pet_count=1)
    assert _place(store, s["id"])["pet_rent"] == 65


def test_negative_a_listing_with_one_plain_pet_fee_is_untouched(store):
    s = store.add_search("C", "rent")
    srv = server(store)
    call(srv, "add_place", title="A", address="15 E Hartwell Dr", price=1480, listing_text="1BR $1,480. 15 E Hartwell Dr, Champaign, IL 61820. Pets ok. Pet rent $35/mo. Pet deposit $250.")
    for kind in ("dog", "cat", "both", "none"):
        store.update_search(s["id"], pet_kind=kind, pet_count=1)
        p = _place(store, s["id"])
        assert (p["pet_rent"], p["pet_deposit"]) == (35, 250)
