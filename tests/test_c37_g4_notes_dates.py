"""Cycle 37, G4: concession note, "reduced" never "corrected", Spanish application fee and date, indoor required space (nontech l11, roommates l12, l4, l8, family l2)."""
from __future__ import annotations

import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp_util import call, server, text  # noqa: E402

from prophelper import parsers as P  # noqa: E402

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel")


def fixture(name: str) -> str:
    with open(os.path.join(FIX, name), encoding="utf-8") as fh:
        return fh.read()


def read(t: str) -> dict:
    return P.parse_listing(t, "")


def notes(r: dict) -> list[str]:
    return [x for x in r.get("found_in_listing", "").split("\n") if x]


# ---- concession with its condition
@pytest.mark.parametrize("line,quote", [
    ("Special: Move in by Dec 1 and get $500 off first month's rent.", "Move in by Dec 1 and get $500 off first month's rent"),
    ("Move in by Dec 1 and get $500 off your first month.", "Move in by Dec 1 and get $500 off your first month"),
    ("Sign by Dec 1: $500 off first month's rent", "Sign by Dec 1: $500 off first month's rent"),
    ("Tours Sat. Move in by Dec 1 and get $500 off your first month", "Move in by Dec 1 and get $500 off your first month"),
    ("Get $500 off first month's rent.", "$500 off first month's rent"),
])
def test_concession_note_keeps_its_condition(line, quote):
    r = read("2 bed, 1 bath. $1,325/mo. Security deposit $1,325.\n" + line)
    assert r["price"] == 1325
    got = [n for n in notes(r) if "discount" in n]
    assert len(got) == 1, got
    assert f'("{quote}' in got[0]
    assert "not taken off the monthly rent" in got[0]


def test_nontech_l11_whole_listing():
    r = read(fixture("r36-nontech-l11.txt"))
    assert r["price"] == 1325 and r["deposit"] == 1325
    got = [n for n in notes(r) if "discount" in n]
    assert len(got) == 1 and "Move in by Dec 1 and get $500 off first month's rent" in got[0]


# ---- "reduced" is never "corrected"
def _add(store, **kw):
    store.add_search("T", "rent")
    srv = server(store)
    out = text(call(srv, "add_place", **kw))
    return out, store.get_place(1)


@pytest.mark.parametrize("line", [
    "PRICE REDUCED to $3,250 from $3,400",
    "Price reduced to $3,250 (was $3,400).",
    "Rent reduced to $3,250/mo.",
])
def test_mcp_reduced_is_not_called_corrected(store, line):
    out, p = _add(store, title="Fulton Market 3BR", address="900 W Fulton Market", price=3400,
                  listing_text="Brand new 3BR/2BA. " + line + "\nPackage fee $25/mo.")
    allnotes = out + "\n" + (p.get("found_in_listing") or "")
    assert not re.search(r"rent was corrected", allnotes), allnotes


def test_mcp_a_real_correction_still_says_corrected(store):
    out, p = _add(store, title="Fulton Market 3BR", address="900 W Fulton Market", price=3400,
                  listing_text="3BR/2BA. Rent $3,400. Corrected: rent is now $3,250.")
    assert "rent was corrected to $3,250" in out + "\n" + (p.get("found_in_listing") or "")


# ---- Spanish application fee and date
@pytest.mark.parametrize("line", [
    "Cuota de solicitud $35.",
    "Cuota de solicitud: $35",
    "Garage parking $200 per month. Cuota de solicitud $35.",
    "Tarifa de aplicación $35",
    "Cargo por solicitud $35 por adulto",
    "Solicitud: $35",
])
def test_spanish_application_fee(line):
    r = read("Renta $1,200 al mes. " + line)
    assert r["application_fee"] == 35
    assert not any("Cuota" in n or "solicitud" in n.lower() for n in notes(r)), notes(r)


@pytest.mark.parametrize("line,iso", [
    ("Disponible 15 de enero.", "2027-01-15"),
    ("Disponible: 15 de enero", "2027-01-15"),
    ("Disponible desde el 1 de febrero de 2027", "2027-02-01"),
    ("Fecha de mudanza: 1 de marzo de 2027", "2027-03-01"),
    ("Disponible el 3 de septiembre de 2027", "2027-09-03"),
    ("Available January 15, 2027", "2027-01-15"),
])
def test_spanish_available_date(line, iso):
    assert read("Renta $1,200 al mes.\n" + line + "\n").get("available_from") == iso


def test_no_date_from_a_plain_spanish_sentence():
    r = read("Renta $1,200 al mes. Se permiten gatos. Llame de 9 de la mañana a 5.")
    assert not r.get("available_from")


def test_roommates_l4_and_l8_whole_listings():
    r = read(fixture("r36-roommates-l4.txt"))
    assert r["application_fee"] == 35 and r["price"] == 3175
    r = read(fixture("r36-roommates-l8.txt"))
    assert r["available_from"] == "2027-01-15" and r["deposit"] == 1500


# ---- 1 indoor space REQUIRED on a line with other things
@pytest.mark.parametrize("line", [
    "Fully fenced yard, dishwasher, 1 indoor space REQUIRED for parking.",
    "Fenced yard; dishwasher; 1 indoor space required for parking",
    "Dishwasher. 1 indoor space REQUIRED for parking. Fenced yard.",
    "Parking: 1 indoor space REQUIRED.",
    "Indoor parking is required. Fenced yard.",
])
def test_required_indoor_space_is_a_garage_without_a_price(line):
    r = read("Rent $2,300. " + line)
    assert r["parking"] == "garage"
    assert r.get("parking_cost") is None
    assert any("required" in n.lower() and "garage" in n for n in notes(r)), notes(r)


@pytest.mark.parametrize("line", ["1 indoor space available, $150/mo", "Fenced yard, indoor storage required"])
def test_not_a_required_garage(line):
    r = read("Rent $2,300. " + line)
    assert r.get("parking_cost") != 0
    assert not any("required indoor space" in n for n in notes(r))


def test_family_l2_whole_listing():
    r = read(fixture("r36-family-l2.txt"))
    assert r["parking"] == "garage" and r.get("parking_cost") is None
    assert r["fenced_yard"] == 1 and r["dishwasher"] == 1 and r["price"] == 2300
