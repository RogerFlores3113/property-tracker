"""Cycle 34, G4: Spanish "1 habitacion, 1 bano" sets beds and baths (uiuc l24). Unclear counts stay empty."""
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


@pytest.mark.parametrize("text,beds,baths", [
    ("Apartamento de 1 habitacion, 1 bano cerca del campus. Alquiler: $1,390 al mes.", 1, 1),
    ("Apartamento de 2 habitaciones, 2 baños. Alquiler: $1,390 al mes.", 2, 2),
    ("2 dormitorios, 1 baño | Alquiler $1,390 al mes", 2, 1),
    ("3 recámaras, 2 baños. Alquiler $1,390 al mes.", 3, 2),
    ("1 HABITACIÓN | 1 BAÑO | ALQUILER $1,390 AL MES", 1, 1),
    ("Se alquila apartamento de tres habitaciones y dos baños. $1,390 al mes", 3, 2),
    ("Apartamento 2 habitaciones 1.5 baños. $1,390 al mes", 2, 1.5),
    ("2 habitaciones, 1 baño y medio. $1,390 al mes", 2, 1.5),
    ("Habitaciones: 2\nBaños: 1\nAlquiler $1,390 al mes", 2, 1),
    ("Estudio, 1 baño. Alquiler $1,390 al mes", 0, 1),
])
def test_spanish_counts(text, beds, baths):
    r = read(text)
    assert r["beds"] == beds and r["baths"] == baths, r
    assert r["price"] == 1390


def test_uiuc_l24_whole_listing():
    r = read(fixture("r33-uiuc-l24.txt"))
    assert r["beds"] == 1 and r["baths"] == 1
    assert r["price"] == 1390 and r["deposit"] == 1390 and r["laundry"] == "in_unit" and r["dishwasher"] == 1
    assert r["utilities_estimate"] == 140 and r["pets"] == "none"
    assert r["address"] == "2204 Philo Rd" and r["city"] == "Urbana" and r["state"] == "IL"


@pytest.mark.parametrize("text", [
    "Apartamento de 1 a 2 habitaciones, 1 baño. $1,390 al mes",
    "Planes: 1 habitación y 2 habitaciones. $1,390 al mes",
    "Estudio de arte cerca del campus. $1,390 al mes",
    "Apartamento cerca del campus. $1,390 al mes",
])
def test_unclear_beds_stay_empty(text):
    assert "beds" not in read(text) or read(text)["beds"] is None


def test_english_counts_win_over_spanish_words():
    r = read("2 bed 1 bath apartment. 3 habitaciones in the next building. $1,390/mo")
    assert r["beds"] == 2 and r["baths"] == 1


def test_two_different_bath_counts_stay_empty():
    r = read("1 habitación. 1 baño en la planta baja y 2 baños arriba. $1,390 al mes")
    assert r["beds"] == 1 and "baths" not in r
