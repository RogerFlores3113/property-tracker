"""Cycle 35 group G3 item 4: a correction pasted onto a saved place ("Dogs now allowed under 30 lbs") adds dogs to the pets with the 30 lb limit,
never "cats up to 30 lb"; "now" between a pet and "allowed" does not hide the yes."""
import pytest

from mcp_util import call, server
from prophelper.parsers import parse_listing

BASE = "1BR $1,480. 15 E Hartwell Dr, Champaign, IL 61820. Cats ok. Cat rent $25."


def P(text, kind=""):
    return parse_listing(text, "", pet_kind=kind)


@pytest.mark.parametrize("t", [
    "Dogs now allowed under 30 lbs",
    "Dogs now allowed under 30 lbs.",
    "Update: dogs now allowed, 30 lb limit.",
    "Dogs are now allowed (under 30 lbs).",
    "Dogs are now permitted, max 30 lb",
    "Update\nDogs now allowed\nUnder 30 lbs",
    "DOGS NOW ALLOWED UNDER 30 LBS",
    "We now allow dogs under 30 lbs.",
])
def test_the_reader_takes_dogs_with_the_30_lb_limit(t):
    r = P(t)
    assert r["pets"] == "dogs" and r["pet_weight_limit"] == 30


@pytest.mark.parametrize("t,pets", [
    ("Cats now allowed.", "cats"),
    ("Pets now allowed", "both"),
    ("Pets are now welcome.", "both"),
    ("Cats and dogs are now allowed.", "both"),
])
def test_now_between_the_pet_and_allowed(t, pets):
    assert P(t)["pets"] == pets


@pytest.mark.parametrize("t", ["No dogs now.", "Dogs are not now allowed.", "Dogs no longer allowed."])
def test_negatives_a_no_stays_a_no(t):
    assert P(t).get("pets") in (None, "", "none")


def _saved(store):
    s = store.add_search("C", "rent")
    srv = server(store)
    call(srv, "add_place", title="A", address="15 E Hartwell Dr", price=1480, listing_text=BASE)
    assert store.list_places(search_id=s["id"])[0]["pets"] == "cats"
    return s, srv


@pytest.mark.parametrize("t", [
    "Dogs now allowed under 30 lbs",
    "Update: dogs now allowed, 30 lb limit.",
    "Correction: dogs are now allowed (under 30 lbs).",
    "Dogs now allowed\nunder 30 lbs",
    "Dogs under 30 lbs are now allowed.",
    "Cats ok. Dogs now allowed under 30 lbs.",
])
def test_a_correction_paste_adds_dogs_and_keeps_the_limit_for_dogs(store, t):
    s, srv = _saved(store)
    r = call(srv, "add_place", title="A", address="15 E Hartwell Dr", price=1480, listing_text=t)
    p = store.list_places(search_id=s["id"])[0]
    assert p["pets"] == "both" and p["pet_weight_limit"] == 30 and p["pet_rent"] == 25
    body = "\n".join(c.text for c in (r.content if hasattr(r, "content") else r[0]))
    assert "values for pets" not in body


def test_a_paste_with_no_correction_word_does_not_make_cats_up_to_30_lb(store):
    s, srv = _saved(store)
    r = call(srv, "add_place", title="A", address="15 E Hartwell Dr", price=1480, listing_text="Dogs allowed under 30 lbs")
    p = store.list_places(search_id=s["id"])[0]
    assert p["pets"] == "cats" and not p["pet_weight_limit"]
    body = "\n".join(c.text for c in (r.content if hasattr(r, "content") else r[0]))
    assert "30 lb pet limit for dogs" in body


def test_a_correction_for_the_same_kind_changes_nothing_about_pets(store):
    s, srv = _saved(store)
    call(srv, "add_place", title="A", address="15 E Hartwell Dr", price=1480, listing_text="Cats now allowed under 15 lbs")
    p = store.list_places(search_id=s["id"])[0]
    assert p["pets"] == "cats" and p["pet_weight_limit"] == 15
