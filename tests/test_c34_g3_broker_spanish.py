"""Cycle 34 group G3 items 12 and 13: a counted broker fee is never "not counted anywhere"; Spanish deposit and parking words."""
import os

import pytest

from mcp_util import call, server
from prophelper.parsers import parse_listing

HERE = os.path.join(os.path.dirname(__file__), "fixtures", "panel")


def P(text, kind="", **kw):
    return parse_listing(text, "", pet_kind=kind, **kw)


def F(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as fh:
        return fh.read()


def N(r):
    return r.get("found_in_listing") or ""


# ---- item 12: "Broker fee: $1,500 flat" is counted, so no note says it is not
BROKER = [
    "Rent $3,200. Broker fee: $1,500 flat.",
    "Rent $3,200. Broker fee: $1,500 flat. Security deposit: one month.",
    "Rent $3,200 | Broker fee: $1,500 flat | Admin fee $200",
    "Rent $3,200. Broker fee $1,500.",
    "Rent $3,200. Flat broker fee of $1,500.",
    "Rent $3,200. Broker fee is $1,500 flat.",
    "Rent $3,200. $1,500 flat broker fee.",
    "Rent $3,200\nBroker fee: $1,500\nParking none\n",
    "RENT $3,200. BROKER FEE: $1,500 FLAT.",
    "Rent $3,200. Agent fee: $1,500 flat.",
]


@pytest.mark.parametrize("t", BROKER)
def test_a_counted_broker_fee_has_no_not_counted_note(t):
    r = P(t)
    assert r["broker_fee"] == 1500 and r["price"] == 3200
    n = N(r)
    assert "not counted anywhere" not in n and "1,500" not in n


def test_roommates_l15_whole_listing():
    r = P(F("r33-roommates-l15.txt"), "dog")
    assert r["broker_fee"] == 1500 and r["price"] == 3200 and r["parking_cost"] == 175 and r["deposit"] == 3200
    assert r["pets"] == "both" and r["pet_weight_limit"] == 40
    assert r["pet_fee"] == 500  # "$300 (cat), $500 (dog) one-time" for a dog search
    n = N(r)
    assert "not counted anywhere" not in n and "Broker fee" not in n
    assert r["utilities_estimate"] == 35
    r = P(F("r33-roommates-l15.txt"), "cat")
    assert r["pet_fee"] == 300 and r["broker_fee"] == 1500
    r = P(F("r33-roommates-l15.txt"), "")
    assert "pet_fee" not in r and "$300" in N(r) and "$500" in N(r)


def test_roommates_l15_through_add_place(store):
    s = store.add_search("C", "rent")
    store.update_search(s["id"], pet_kind="dog", pet_count=1)
    call(server(store), "add_place", title="A", address="5200 N Clark St", listing_text=F("r33-roommates-l15.txt"))
    p = store.list_places(search_id=s["id"])[0]
    assert p["broker_fee"] == 1500 and p["pet_fee"] == 500
    assert "not counted anywhere" not in (p.get("reader_notes") or "")


@pytest.mark.parametrize("t", [
    "Rent $3,200. Broker fee: 50% ($1,600).",
    "Rent $3,200. Broker fee: $1,500 if you use our broker; otherwise none. Admin fee $200.",
])
def test_negative_a_broker_figure_that_is_not_saved_is_still_named(t):
    r = P(t)
    assert "$1,600" in N(r) or "$1,500" in N(r) or r.get("broker_fee")


# ---- item 13: Spanish deposit and parking words
DEPOSIT = [
    ("Wicker Park 3 Bed 2 Bath. Alquiler $3,300 al mes. Deposito $1,650. Disponible 15 de enero 2027.", 1650),
    ("Alquiler $3,300 al mes. Depósito $1,650.", 1650),
    ("Alquiler $3,300 al mes. Depósito de $1,650.", 1650),
    ("Alquiler $3,300 al mes. Depósito de seguridad: $1,650", 1650),
    ("Alquiler $3,300 al mes\nDepósito: $1,650\n", 1650),
    ("ALQUILER $3,300 AL MES. DEPÓSITO $1,650.", 1650),
    ("Alquiler $3,300 al mes | Depósito $1,650 | Estacionamiento incluido", 1650),
]


@pytest.mark.parametrize("t,want", DEPOSIT)
def test_spanish_deposit_is_the_deposit(t, want):
    r = P(t)
    assert r["deposit"] == want and r["price"] == 3300
    assert "not counted anywhere" not in N(r)


PARKING = [
    ("Alquiler $3,300 al mes. Estacionamiento $200/mes requerido.", 200),
    ("Alquiler $3,300 al mes. Estacionamiento: $200 por mes.", 200),
    ("Alquiler $3,300 al mes\nEstacionamiento $200/mes\n", 200),
    ("Alquiler $3,300 al mes | Estacionamiento $200/mes | Depósito $1,650", 200),
    ("ALQUILER $3,300 AL MES. ESTACIONAMIENTO $200/MES REQUERIDO.", 200),
]


@pytest.mark.parametrize("t,want", PARKING)
def test_spanish_parking_is_the_parking_cost(t, want):
    r = P(t)
    assert r["parking_cost"] == want and r["price"] == 3300
    assert "not counted anywhere" not in N(r)


def test_spanish_parking_included_is_free():
    r = P("Alquiler $3,300 al mes. Estacionamiento incluido.")
    assert r.get("parking_cost") in (None, 0)


def test_roommates_l7_whole_listing():
    r = P(F("r33-roommates-l7.txt"))
    assert (r["price"], r["deposit"], r["parking_cost"]) == (3300, 1650, 200)
    assert r["beds"] == 3 and r["baths"] == 2
    assert "not counted anywhere" not in N(r) and "Estacionamiento" not in N(r) and "Deposito" not in N(r)


def test_nontech_l25_whole_listing():
    r = P(F("r33-nontech-l25.txt"), "cat")
    assert r["price"] == 1290 and r["deposit"] == 1290 and r["beds"] == 2
    assert r.get("pets") == "cats"


def test_negative_english_text_is_untouched():
    t = "Rent $1,500. Deposit $1,500. Parking $50/mo. Pets welcome."
    r = P(t)
    assert (r["price"], r["deposit"], r["parking_cost"]) == (1500, 1500, 50)


def test_negative_a_pet_deposit_in_spanish_is_not_the_security_deposit():
    r = P("Alquiler $3,300 al mes. Depósito de seguridad $3,300. Depósito por mascota $400.", "dog")
    assert r["deposit"] == 3300 and r["pet_deposit"] == 400
