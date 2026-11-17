"""Cycle 35, G4: Spanish parking, laundry and yard words are read, and a note that quotes a Spanish listing shows its own words (uiuc l29, family l3, privacy)."""
from __future__ import annotations

import os

import pytest

from prophelper import parsers as P

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel")


def fixture(name: str) -> str:
    with open(os.path.join(FIX, name), encoding="utf-8") as fh:
        return fh.read()


def read(text: str) -> dict:
    return P.parse_listing(text, "")


def notes(r: dict) -> str:
    return r.get("found_in_listing", "")


HEAD = "Apartamento de 2 habitaciones. Alquiler $1,380 al mes. "
TAIL = " Depósito de seguridad $1,380. 2008 W Springfield Ave, Urbana IL"


@pytest.mark.parametrize("park", [
    "Estacionamiento cubierto $60.",
    "Estacionamiento cubierto: $60 al mes.",
    "Estacionamiento cubierto $60/mes.",
    "Estacionamiento cubierto $60 al mes",
    "Estacionamiento techado $60.",
    "ESTACIONAMIENTO CUBIERTO $60",
    "Estacionamiento cubierto - $60 mensuales.",
    "Estacionamiento cubierto por $60 al mes.",
])
def test_covered_parking_with_a_price(park):
    r = read(HEAD + park + TAIL)
    assert r["parking"] == "covered" and r["parking_cost"] == 60, r
    assert r["price"] == 1380 and r["deposit"] == 1380
    assert "$60" not in notes(r) and "not counted" not in notes(r), notes(r)


@pytest.mark.parametrize("park,kind,cost", [
    ("Garaje $85 al mes.", "garage", 85),
    ("Cochera $85/mes.", "garage", 85),
    ("Estacionamiento cubierto incluido.", "covered", 0),
    ("Estacionamiento cubierto gratis.", "covered", 0),
    ("Estacionamiento cubierto: incluido en la renta.", "covered", 0),
])
def test_other_spanish_parking(park, kind, cost):
    r = read(HEAD + park + TAIL)
    assert r["parking"] == kind and r["parking_cost"] == cost, (r.get("parking"), r.get("parking_cost"), notes(r))


def test_unpriced_covered_parking_is_covered_with_no_cost():
    r = read(HEAD + "Estacionamiento cubierto." + TAIL)
    assert r["parking"] == "covered" and "parking_cost" not in r


def test_optional_spanish_parking_is_never_counted():
    r = read(HEAD + "Estacionamiento cubierto opcional, $60 al mes." + TAIL)
    assert "parking_cost" not in r or r["parking_cost"] in (None, 0)
    assert "$60" in notes(r) and "optional" in notes(r).lower()


def test_no_parking_and_street_parking():
    assert read(HEAD + "Sin estacionamiento." + TAIL)["parking"] == "none"
    assert read(HEAD + "Estacionamiento en la calle." + TAIL)["parking"] == "street"


@pytest.mark.parametrize("laundry", [
    "Lavadora y secadora dentro de la unidad.",
    "Lavadora y secadora en la unidad.",
    "Lavadora y secadora en cada unidad.",
    "Lavadora y secadora en el apartamento.",
    "Lavadora/secadora dentro de la unidad.",
    "Lavadora y secadora incluidas.",
    "LAVADORA Y SECADORA DENTRO DE LA UNIDAD, lavaplatos.",
])
def test_in_unit_laundry(laundry):
    r = read(HEAD + laundry + TAIL)
    assert r["laundry"] == "in_unit", (r.get("laundry"), notes(r))
    assert "laundry" not in notes(r).lower()


@pytest.mark.parametrize("laundry", [
    "Lavandería en el edificio.",
    "Lavandería compartida.",
    "Lavandería comunitaria en el sótano.",
])
def test_building_laundry(laundry):
    assert read(HEAD + laundry + TAIL)["laundry"] == "in_building"


def test_no_laundry_and_hookups():
    assert read(HEAD + "Sin lavadora." + TAIL)["laundry"] == "none"
    assert read(HEAD + "Conexiones para lavadora y secadora." + TAIL)["laundry"] == "hookups"


def test_a_bare_washer_and_dryer_is_unknown_and_the_note_quotes_the_listing_words():
    r = read(HEAD + "Lavadora y secadora." + TAIL)
    assert "laundry" not in r
    assert "Lavadora y secadora" in notes(r) and "Washer and dryer" not in notes(r), notes(r)


@pytest.mark.parametrize("yard", [
    "Patio cercado.",
    "Patio cercado para perros.",
    "Patio trasero cercado.",
    "Jardín cercado.",
    "Patio con cerca.",
    "Patio vallado.",
    "Patio totalmente cercado.",
    "PATIO CERCADO",
])
def test_fenced_yard(yard):
    r = read("Casa de 3 recámaras. Renta $2,100 al mes. " + yard + " 15 Oak Street, Belmont, CA")
    assert r["fenced_yard"] == 1, (r.get("fenced_yard"), notes(r))


def test_a_plain_patio_or_a_shared_one_is_not_a_private_fenced_yard():
    base = "Casa de 3 recámaras. Renta $2,100 al mes. {} 15 Oak Street, Belmont, CA"
    assert "fenced_yard" not in read(base.format("Patio."))
    assert "fenced_yard" not in read(base.format("Patio compartido."))
    r = read(base.format("Patio cercado compartido."))
    assert r.get("fenced_yard") != 1 or "shared" in notes(r).lower()
    assert read(base.format("No hay patio cercado.")).get("fenced_yard") == 0


def test_uiuc_l29_whole_listing():
    r = read(fixture("r34-uiuc-l29.txt"))
    assert r["price"] == 1380 and r["beds"] == 1 and r["baths"] == 1 and r["deposit"] == 1380
    assert r["laundry"] == "in_unit" and r["parking"] == "covered" and r["parking_cost"] == 60
    assert r["tenant_pays"] == "electric, gas"
    assert r["address"] == "2008 W Springfield Ave" and r["city"] == "Urbana"
    assert "$60" not in notes(r) and "Estacionamiento" not in notes(r), notes(r)


def test_family_l3_whole_listing():
    r = read(fixture("r34-family-l3.txt"))
    assert r["beds"] == 3 and r["baths"] == 2 and r["deposit"] == 2100 and r["pets"] == "dogs"
    assert r["parking"] == "covered" and "parking_cost" not in r and r["fenced_yard"] == 1
    # a quote of the listing shows its own words
    assert "Security deposit" not in notes(r) and "Dogs allowed" not in notes(r), notes(r)


def test_english_words_are_never_swapped_into_a_note_unless_they_were_the_listings_own():
    r = read("2 bed 1 bath. Rent $1,500. Security deposit $1,500. Lavadora y secadora.\nDogs allowed up to 70 lb, $300 pet deposit.")
    assert "Security deposit" not in notes(r) or "Security deposit $1,500" not in notes(r)


# negatives: English listings are unchanged, ordinary Spanish words with no parking meaning are untouched
@pytest.mark.parametrize("text", [
    "Covered parking $60/mo. Washer and dryer in unit. Fenced yard. Rent $1,380. 12 N Main St, Urbana IL",
])
def test_english_unchanged(text):
    r = read(text)
    assert r["parking"] == "covered" and r["parking_cost"] == 60 and r["laundry"] == "in_unit" and r["fenced_yard"] == 1


def test_a_spanish_word_that_only_looks_like_parking_is_not_parking():
    r = read("Apartamento de 1 habitación. Alquiler $1,380 al mes. Cerca del estacionamiento de la universidad. 2008 W Springfield Ave, Urbana IL")
    assert r.get("parking") in (None, "", "lot")  # the reader may leave it unknown; it must never invent a price
    assert "parking_cost" not in r


@pytest.mark.parametrize("park", ["Estacionamiento $600 al año.", "Estacionamiento cubierto $600 anuales.", "Estacionamiento $600/año.", "Estacionamiento $600 por año."])
def test_yearly_spanish_parking_is_a_monthly_twelfth(park):
    r = read(HEAD + park + TAIL)
    assert r["parking_cost"] == 50, (r.get("parking_cost"), notes(r))
    assert "$600 a year" in notes(r)


def test_a_quote_of_a_spanish_deposit_keeps_the_listing_words():
    r = read("Alquiler $2,300 al mes. Depósito $1.900. 2 hab 1 baño. 5 Calle Uno, Urbana IL")
    assert "Security deposit" not in notes(r) and "Depósito $1.900" in notes(r), notes(r)
