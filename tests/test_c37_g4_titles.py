"""Cycle 37, G4: Spanish hype titles through MCP, "3/2 Oak Street House - Huge Yard", "Hyde Park Hurry 3bd/2ba", Spanish headline (uiuc, family l2, roommates l15, l8)."""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp_util import call, server  # noqa: E402

from prophelper import parsers as P  # noqa: E402

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel")


def fixture(name: str) -> str:
    with open(os.path.join(FIX, name), encoding="utf-8") as fh:
        return fh.read()


def title(t: str) -> str:
    return P.parse_listing(t, "").get("title") or ""


ADDR = "88 Oak Street, San Carlos, CA 94070"


@pytest.mark.parametrize("head,expected", [
    ("3/2 Oak Street House - Huge Yard!!! Must see", "Oak Street House"),
    ("3/2 Oak Street House - Huge Yard", "Oak Street House"),
    ("3/2 Oak Street House | Huge Yard", "Oak Street House"),
    ("3/2 Oak Street House, Big Backyard!!", "Oak Street House"),
    ("3bd/2ba Oak Street House - Spacious Yard", "Oak Street House"),
    ("3/2 Oak Street House", "Oak Street House"),
    ("3BR/2BA Townhouse, Redwood City", "3BR/2BA Townhouse, Redwood City"),
    ("2 Bed 1 Bath Ranch Duplex - Whitehall", "2 Bed 1 Bath Ranch Duplex - Whitehall"),
    ("Hyde Park Hurry!! 3bd/2ba", "Hyde Park 3bd/2ba"),
    ("Hyde Park Hurry 3bd/2ba", "Hyde Park 3bd/2ba"),
    ("Hyde Park Wow 3bd/2ba", "Hyde Park 3bd/2ba"),
    ("Hyde Park Act fast 3bd/2ba", "Hyde Park 3bd/2ba"),
])
def test_paste_titles(head, expected):
    assert title(head + "\n" + ADDR + "\nRent $2,300/mo") == expected


@pytest.mark.parametrize("head", [
    "Renta 1,475 al mes por habitación | 3 hab 2 baños",
    "Renta $1,475 al mes por habitación",
    "Renta 1,475 al mes por habitación - 3 hab 2 baños",
    "Departamento de lujo - Renta $1,420 al mes!!",
    "¡OFERTA ESPECIAL! Apartamento de lujo cerca del campus - solo $1,395",
])
def test_spanish_headline_gives_way_to_the_address(head):
    assert title(head + "\n2500 S Kedzie Ave, Chicago IL 60623\nTotal $3,200.") == "2500 S Kedzie Ave"


@pytest.mark.parametrize("name", ["Casa Grande Lofts", "Residencias del Parque", "Calle 26 y Kedzie", "Elm Court", "The 3/2 Club Apartments"])
def test_real_names_are_kept(name):
    assert title(name + "\n12 Elm St, Champaign IL 61820\nRent $1,200/mo") == name


def test_whole_listings():
    assert title(fixture("r36-family-l2.txt")) == "Oak Street House"
    assert title(fixture("r36-roommates-l15.txt")) == "Hyde Park 3bd/2ba"
    assert title(fixture("r36-roommates-l8.txt")) == "2500 S Kedzie Ave"


def _add(store, **kw):
    store.add_search("T", "rent")
    srv = server(store)
    call(srv, "add_place", **kw)
    return store.get_place(1)


@pytest.mark.parametrize("given", [
    "¡OFERTA ESPECIAL! Apartamento de lujo cerca del campus - solo $1,395",
    "Departamento de lujo - Renta $1,420 al mes!!",
    "¡Increíble! Apartamento de lujo - solo $1,395",
    "OFERTA: Departamento nuevo cerca del campus - $1,395 al mes",
])
def test_mcp_add_place_spanish_hype_gives_the_address(store, given):
    assert _add(store, title=given, address="1204 W Green St", price=1395)["title"] == "1204 W Green St"


def test_mcp_add_places_spanish_hype_gives_the_address(store):
    store.add_search("T", "rent")
    srv = server(store)
    call(srv, "add_places", places=[
        {"title": "¡OFERTA ESPECIAL! Apartamento de lujo cerca del campus - solo $1,395", "address": "1204 W Green St", "price": 1395},
        {"title": "Departamento de lujo - Renta $1,420 al mes!!", "address": "55 Elm St", "price": 1420},
        {"title": "3/2 Oak Street House - Huge Yard", "address": "88 Oak Street", "price": 2300},
    ])
    assert [store.get_place(i)["title"] for i in (1, 2, 3)] == ["1204 W Green St", "55 Elm St", "Oak Street House"]


@pytest.mark.parametrize("given", ["Casa Grande Lofts", "Residencias del Parque", "Elm Court"])
def test_mcp_keeps_real_spanish_names(store, given):
    assert _add(store, title=given, address="12 Elm St", price=1500)["title"] == given
