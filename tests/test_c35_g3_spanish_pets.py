"""Cycle 35 group G3 items 1, 2 and 6: Spanish pet sentences ("Perros hasta 70 lb con depósito de $300", "Se permiten gatos", "No mascotas",
"$25 de renta mensual") are read as pets, a weight limit, a pet deposit and a pet rent, never as the security deposit."""
import os

import pytest

from prophelper.parsers import parse_listing

HERE = os.path.join(os.path.dirname(__file__), "fixtures", "panel")


def P(text, kind="", **kw):
    return parse_listing(text, "", pet_kind=kind, **kw)


def F(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as fh:
        return fh.read()


def N(r):
    return r.get("found_in_listing") or ""


# ---- item 1: dogs up to 70 lb with a $300 pet deposit
DOGS_70 = [
    "Alquiler $2,100 al mes. Perros hasta 70 lb con depósito de $300.",
    "Alquiler $2,100. Se permiten perros hasta 70 lb con deposito de $300.",
    "Alquiler $2,100. Perros permitidos, máximo 70 libras, depósito para mascotas $300.",
    "Alquiler $2,100. Mascotas: perros hasta 70 lb (depósito $300).",
    "Alquiler $2,100.\nPerros hasta 70 lb\nCon depósito de $300\n",
    "ALQUILER $2,100. PERROS HASTA 70 LB CON DEPÓSITO DE $300.",
    "Alquiler $2,100; perros hasta 70 libras con depósito de $300; luz y gas por el inquilino.",
]


@pytest.mark.parametrize("t", DOGS_70)
def test_dogs_up_to_70_lb_with_300_pet_deposit(t):
    r = P(t, "dog")
    assert r["pets"] == "dogs" and r["pet_weight_limit"] == 70 and r["pet_deposit"] == 300
    assert r["price"] == 2100
    assert "deposit" not in r or r["deposit"] != 300
    assert "Security deposit" not in N(r)


def test_family_l3_whole_listing():
    r = P(F("r34-family-l3.txt"), "dog")
    assert r["pets"] == "dogs" and r["pet_weight_limit"] == 70 and r["pet_deposit"] == 300
    assert r["deposit"] == 2100 and r["beds"] == 3 and r["baths"] == 2
    assert "Security deposit $300" not in N(r)


def test_security_deposit_sentence_stays_the_security_deposit():
    r = P("Alquiler $1,380. Depósito de seguridad $1,380. Perros hasta 40 lb.", "dog")
    assert r["deposit"] == 1380 and r["pets"] == "dogs" and r["pet_weight_limit"] == 40 and "pet_deposit" not in r


# ---- item 2: "Se permiten gatos" and "No mascotas"
def test_nontech_l5_cats_allowed_with_pet_deposit():
    r = P(F("r34-nontech-l5.txt"), "cat")
    assert r["pets"] == "cats" and r["pet_deposit"] == 150 and r["deposit"] == 1350 and r["price"] == 1350
    assert r["utilities_included"] == "water, trash"


def test_uiuc_l29_no_pets():
    r = P(F("r34-uiuc-l29.txt"), "dog")
    assert r["pets"] == "none" and r["deposit"] == 1380 and r["price"] == 1380
    assert r["tenant_pays"] == "electric, gas"


NO_PETS = [
    "Alquiler $1,380. No mascotas.",
    "Alquiler $1,380. No se permiten mascotas.",
    "Alquiler $1,380. Sin mascotas.",
    "Alquiler $1,380. Mascotas: no.",
    "Alquiler $1,380 | No mascotas | Depósito $1,380",
    "ALQUILER $1,380. NO MASCOTAS",
    "Alquiler $1,380\nMascotas no permitidas\nDepósito $1,380",
]


@pytest.mark.parametrize("t", NO_PETS)
def test_no_pets_is_no_pets_and_keeps_the_rent(t):
    r = P(t)
    assert r["pets"] == "none" and r["price"] == 1380


CATS = [
    "Alquiler $1,350. Se permiten gatos.",
    "Alquiler $1,350. Gatos permitidos.",
    "Alquiler $1,350 - Se permiten gatos - Estacionamiento gratis",
    "Alquiler $1,350\nSe permiten gatos\n",
    "ALQUILER $1,350. SE PERMITEN GATOS.",
    "Alquiler $1,350. Aceptamos gatos.",
]


@pytest.mark.parametrize("t", CATS)
def test_cats_allowed_means_cats_only(t):
    r = P(t, "cat")
    assert r["pets"] == "cats" and r["price"] == 1350


def test_both_kinds_and_one_refused_kind():
    assert P("Alquiler $1,350. Se permiten gatos y perros.")["pets"] == "both"
    assert P("Alquiler $1,350. Perros y gatos permitidos.")["pets"] == "both"
    assert P("Alquiler $1,350. Gatos permitidos. Sin perros.")["pets"] == "cats"
    assert P("Alquiler $1,350. Sin gatos. Perros permitidos.")["pets"] == "dogs"


def test_negatives_other_spanish_words_are_not_pets():
    r = P("Alquiler $1,350. Depósito de seguridad $1,350. Cerca del parque de perros.")
    assert r.get("pets") in (None, "") and r["deposit"] == 1350
    r = P("Alquiler $1,350. Mascotas: preguntar al propietario.")
    assert r.get("pets") in (None, "none", "")  # unknown, never a yes
    assert r["price"] == 1350


# ---- item 6: "$25 de renta mensual" for cats is a pet rent
CAT_RENT = [
    "Alquiler $1,300. Gatos permitidos con $25 de renta mensual. Depósito $1,300.",
    "Alquiler $1,300. Gatos permitidos, $25 de renta mensual. Depósito $1,300.",
    "Alquiler $1,300. Se permiten gatos ($25 de renta mensual por gato). Depósito $1,300.",
    "Alquiler $1,300. Se permiten gatos. Renta mensual de mascotas $25. Depósito $1,300.",
    "Alquiler $1,300. Gatos permitidos\n$25 de renta mensual\nDepósito $1,300",
    "Alquiler $1,300. Gatos permitidos con $25 al mes de renta. Depósito $1,300.",
]


@pytest.mark.parametrize("t", CAT_RENT)
def test_cat_pet_rent_in_spanish(t):
    r = P(t, "cat")
    assert r["pets"] == "cats" and r["pet_rent"] == 25 and r["price"] == 1300 and r["deposit"] == 1300
    assert "not counted" not in N(r)


def test_nontech_l10_whole_listing():
    r = P(F("r34-nontech-l10.txt"), "cat")
    assert r["pets"] == "cats" and r["pet_rent"] == 25 and r["price"] == 1300 and r["deposit"] == 1300
    assert r["tenant_pays"] == "electric, gas"


def test_the_rent_line_is_not_pet_rent():
    r = P("Alquiler $1,300. Renta mensual $1,300. Se permiten gatos.", "cat")
    assert r["price"] == 1300 and "pet_rent" not in r
