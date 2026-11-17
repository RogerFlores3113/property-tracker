"""Cycle 34 G2: a rent written with a space as the thousands mark ("Loyer 2 300 $ par mois") is read whole or left empty with a note, never 300.
Spanish, German and French rent words are the rent. "Months 1-2 half off" gets a promo note and never lowers the rent."""
import os

import pytest

from prophelper.parsers import parse_listing

P = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel") + "/"


def read(t, **kw):
    return parse_listing(t, "", **kw)


def notes(r):
    return r.get("found_in_listing", "") or ""


def fixture(name):
    return open(P + name, encoding="utf-8").read()


# ---------------------------------------------------------------- spaced thousands
@pytest.mark.parametrize("t", [
    "Appartement 2 pièces. Loyer 2 300 $ par mois. Chiens acceptés.",
    "Appartement 2 pièces.\nLoyer: 2 300 $ / mois\nChiens acceptés.",
    "Loyer 2 300$/mois | 2 chambres | Chiens acceptés",
    "Loyer mensuel $2 300 par mois. Animaux acceptés.",
    "LOYER 2 300 $ PAR MOIS. 2 CHAMBRES.",
    "Appartement lumineux (2 chambres), loyer : 2 300,00 $ par mois; chiens acceptés.",
    "Loyer 2 300 par mois. Chiens acceptés.",
    "Wohnung, 2 Zimmer. Miete 2 300 $ pro Monat.",
    "Alquiler: 2 300 $ al mes. 2 dormitorios.",
])
def test_spaced_thousands_rent_is_read_whole(t):
    r = read(t)
    assert r["price"] == 2300
    assert "not counted anywhere" not in notes(r)


def test_fr_whole_listing_in_a_longer_text():
    t = "Quiet 2 bed 1 bath near the metro. 410 Rue Sherbrooke, Testville.\nLoyer 2 300 $ par mois. Chiens acceptés.\nAvailable 9/1/2027"
    r = read(t)
    assert r["price"] == 2300 and r["beds"] == 2 and r["baths"] == 1


@pytest.mark.parametrize("t", [
    "Rent: $2,300/mo. Loyer 2 300 $ par mois.",
    "Miete $2,300 pro Monat. Rent $2,300 per month.",
])
def test_same_rent_in_two_languages_is_one_rent(t):
    r = read(t)
    assert r["price"] == 2300
    assert "mismatch" not in notes(r).lower() and "not counted anywhere" not in notes(r)


@pytest.mark.parametrize("t", [
    "Move in $50 300 Main St",
    "Parking $50 300 sq ft garage. Rent $1,800/mo.",
    "2 bed 1 bath 1 200 sq ft. Rent $1,800/mo.",
    "Deposit $1,800. Call 555 300 4000. $1,800/mo",
])
def test_negatives_other_numbers_with_spaces_stay_as_they_were(t):
    r = read(t)
    assert r.get("price") in (None, 1800)
    assert r.get("price") != 300 and r.get("price") != 200


def test_euro_amount_is_not_saved_as_dollars_and_is_named():
    r = read("Wohnung 2 Zimmer. Miete 2.300 EUR pro Monat.")
    assert r.get("price") is None
    assert "2,300 EUR" in notes(r) and "not saved" in notes(r)


@pytest.mark.parametrize("t", [
    "Appartement. Loyer 2 300 € par mois.",
    "Appartement. Loyer: € 2 300 par mois.",
    "Piso. Alquiler 2.300 euros al mes.",
])
def test_euro_rent_is_never_a_smaller_part(t):
    r = read(t)
    assert r.get("price") in (None, 2300)
    assert r.get("price") != 300


# ---------------------------------------------------------------- other languages
@pytest.mark.parametrize("t", [
    "Alquiler: $2,300 al mes. 2 dormitorios.",
    "Alquiler $2,300 al mes",
    "Casa. 2 dormitorios, 1 baño. Alquiler: $2,300/mes. Mascotas permitidas.",
    "ALQUILER: $2,300 AL MES.",
    "Miete $2,300 pro Monat",
    "Wohnung. Miete: $2,300 pro Monat. 2 Zimmer.",
    "Wohnung | 2 Zimmer | Miete $2,300 monatlich",
    "Se alquila por $2,300 al mes. 2 dormitorios.",
])
def test_spanish_and_german_rent_words(t):
    r = read(t)
    assert r["price"] == 2300
    assert "not counted anywhere" not in notes(r)


def test_nontech_l25_spanish_whole_listing():
    r = read(fixture("r33-nontech-l25.txt"))
    assert r["price"] == 1290 and r["beds"] == 2 and r["baths"] == 1
    assert "not counted anywhere" not in notes(r)


# ---------------------------------------------------------------- half off
def test_family_l14_whole_listing():
    r = read(fixture("r33-family-l14.txt"))
    n = notes(r)
    assert r["price"] == 2295 and r["deposit"] == 2295
    assert 'a rent concession ("Months 1-2 half off")' in n
    assert "not taken off the rent" in n


@pytest.mark.parametrize("t,quote", [
    ("Home. $2,295/mo. Move-in special: Months 1-2 half off.", "Months 1-2 half off"),
    ("$2,295/mo. Half off months 1-2!", "Half off months 1-2"),
    ("Rent $2,295. Special: 50% off the first two months.", "50% off the first two months"),
    ("$2,295 a month | First 2 months half off | Dogs ok", "First 2 months half off"),
    ("Rent: $2,295\nMove-in special\nMonths 1 and 2: half price", "Months 1 and 2: half price"),
    ("$2,295/mo, half off for the first 2 months (new tenants)", "half off for the first 2 months"),
    ("Rent $2,295; months 1-2 half off; deposit $2,295.", "months 1-2 half off"),
])
def test_half_off_months_gets_a_note_and_never_lowers_the_rent(t, quote):
    r = read(t)
    assert r["price"] == 2295
    assert quote in notes(r)
    assert "not taken off" in notes(r)


@pytest.mark.parametrize("t", [
    "Rent $2,295/mo. Half bath on the main floor. Half off street parking.",
    "Rent $2,295/mo. Months 1-2 are the lease start; half of the garage is storage.",
])
def test_negatives_half_without_a_discount(t):
    r = read(t)
    assert r["price"] == 2295
    assert "concession" not in notes(r)
