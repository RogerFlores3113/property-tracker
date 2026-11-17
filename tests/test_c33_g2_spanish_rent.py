"""Cycle 33 G2: a rent written in Spanish, German or French ("Alquiler $1.400 al mes") is the rent, not an uncounted amount."""
import os

import pytest

from prophelper.parsers import parse_listing

P = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel") + "/"


def read(t, **kw):
    return parse_listing(t, "", **kw)


def notes(r):
    return r.get("found_in_listing", "") or ""


def test_privacy_l6_whole_listing():
    r = read(open(P + "r32-privacy-l6.txt", encoding="utf-8").read())
    assert r["price"] == 1400
    assert "Alquiler" not in notes(r)
    assert "not counted anywhere" not in notes(r)


@pytest.mark.parametrize("t", [
    "Apartamento luminoso, 600 Calle Sol, Testville. Alquiler $1.400 al mes. 2 dormitorios, 1 baño.",
    "Apartamento, 600 Calle Sol, Testville.\nAlquiler: $1.400/mes\n2 dormitorios, 1 baño.",
    "2 dormitorios | $1.400 al mes | Alquiler mensual | Mascotas permitidas",
    "ALQUILER $1.400 AL MES. 2 DORMITORIOS.",
    "Renta mensual $1,400. 2 recamaras, 1 baño.",
    "Wohnung 2 Zimmer. Miete $1.400 pro Monat.",
    "Appartement 2 pièces. Loyer $1.400 par mois.",
    "2 dormitorios, 1 baño. Se alquila por $1.400 al mes.",
])
def test_rent_in_other_languages(t):
    r = read(t)
    assert r["price"] == 1400
    assert "not counted anywhere" not in notes(r)
    assert notes(r).count("1,400") == 0


@pytest.mark.parametrize("t", [
    "Apartamento. Depósito $1.400. 2 dormitorios.",
    "Apartamento. Cuota de mascotas $300 al mes. 2 dormitorios.",
    "Apartamento. Estacionamiento $50 al mes. 2 dormitorios.",
    "Apartamento. Gastos (luz, agua) $120 al mes. 2 dormitorios.",
    "Wohnung. Nebenkosten $120 pro Monat. 2 Zimmer.",
])
def test_negatives_a_deposit_or_a_pet_fee_is_not_the_rent(t):
    assert read(t).get("price") is None
