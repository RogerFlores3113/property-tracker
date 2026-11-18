"""Cycle 36, G4: titles (family l3, roommates l14, nontech, buyer l40)."""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp_util import call, server, text  # noqa: E402

from prophelper import parsers as P  # noqa: E402

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel")


def fixture(name: str) -> str:
    with open(os.path.join(FIX, name), encoding="utf-8") as fh:
        return fh.read()


def title(t: str, buying: bool = False) -> str:
    return P.parse_listing(t, "", buying=buying).get("title") or ""


ADDR = "4801 N Damen Ave 2R, Chicago IL 60625"


# ---- roommates l14: the label of a price that was cut ("- Dep") is not part of the name
@pytest.mark.parametrize("head", [
    "Ravenswood 3BR/2BA - Dep $900 - Rent 3 150 dollars a month",
    "Ravenswood 3BR/2BA - Dep $900",
    "Ravenswood 3BR/2BA - Deposit $900 - Rent $3,150/mo",
    "Ravenswood 3BR/2BA | Dep $900",
    "Ravenswood 3BR/2BA - Security deposit $900",
    "Ravenswood 3BR/2BA - $900 dep",
    "Ravenswood 3BR/2BA - Rent $3,150",
])
def test_price_label_tail_is_not_part_of_the_title(head):
    assert title(head + "\n" + ADDR + "\nTenant pays electric.") == "Ravenswood 3BR/2BA"


def test_roommates_l14_whole_listing_title():
    assert title(fixture("r35-roommates-l14.txt")) == "Ravenswood 3BR/2BA"


def test_a_name_with_a_real_label_word_inside_is_kept():
    assert title("Parkside Rent Lofts - Dep\n12 Elm St, Chicago IL 60601\nRent $1,500") == "Parkside Rent Lofts"
    assert title("Deposit Street Apartments - 2BR\n12 Elm St, Chicago IL 60601") != ""


# ---- family l3: a Spanish sales headline is no name, the street address is the title
@pytest.mark.parametrize("t", [
    "Casa de 3 recámaras y 2 baños, 28 Calle Sol, San Carlos CA. Renta 2 250 al mes.",
    "Casa de 3 recámaras y 2 baños en 28 Calle Sol, San Carlos CA. Renta $2,250 al mes.",
    "Se renta casa de 3 recámaras y 2 baños\n28 Calle Sol, San Carlos CA 94070\nRenta $2,250 al mes.",
    "Casa de 3 recámaras, 2 baños. 28 Calle Sol, San Carlos CA. Renta $2,250 al mes.",
    "Hermoso departamento de 2 recámaras - 28 Calle Sol, San Carlos CA. Renta $2,250 al mes.",
    "Departamento 2 recámaras 1 baño en renta\n28 Calle Sol, San Carlos CA 94070\nRenta $2,250/mes",
])
def test_spanish_sales_headline_gives_way_to_the_address(t):
    assert title(t) == "28 Calle Sol"


def test_family_l3_whole_listing_title_and_fields():
    r = P.parse_listing(fixture("r35-family-l3.txt"), "")
    assert r["title"] == "28 Calle Sol"
    assert r["beds"] == 3 and r["baths"] == 2 and r["price"] == 2250


def test_a_spanish_name_is_kept():
    assert title("Residencial Los Olivos, casa de 3 recámaras\n28 Calle Sol, San Carlos CA 94070").startswith("Residencial Los Olivos")


# ---- buyer l40: "Offered at $315k - Clintonville Cottage Condo" keeps the name
@pytest.mark.parametrize("head", [
    "Offered at $315k - Clintonville Cottage Condo",
    "Offered at $315,000 - Clintonville Cottage Condo",
    "Listed at $315,000: Clintonville Cottage Condo",
    "For sale $315,000 - Clintonville Cottage Condo, 2 bed 1.5 bath",
    "Asking $315k | Clintonville Cottage Condo",
    "Clintonville Cottage Condo - Offered at $315k",
    "Clintonville Cottage Condo",
])
def test_sale_price_lead_does_not_lose_the_building_name(head):
    t = head + "\n2890 N High St #2C, Columbus, OH 43202\n2 bedrooms, 1.5 baths."
    assert title(t, buying=True) == "Clintonville Cottage Condo"


def test_buyer_l40_whole_listing():
    r = P.parse_listing(fixture("r35-buyer-l40.txt"), "", buying=True)
    assert r["title"] == "Clintonville Cottage Condo"
    assert r["address"] == "2890 N High St"


def test_a_sale_price_with_only_a_bare_kind_gives_the_address():
    assert title("Offered at $315k - Condo\n2890 N High St #2C, Columbus, OH 43202", buying=True) == "2890 N High St"


# ---- nontech: hype tails and hype-only titles
def test_hype_tail_is_cut_from_a_pasted_title():
    assert title(fixture("r35-nontech-l1.txt")) == "Cozy 2 Bed Duplex in Clintonville"


@pytest.mark.parametrize("head", [
    "Cozy 2 Bed Duplex in Clintonville - Won't Last!",
    "Cozy 2 Bed Duplex in Clintonville | Won't Last!!",
    "Cozy 2 Bed Duplex in Clintonville - Hurry!",
    "Cozy 2 Bed Duplex in Clintonville, must see!",
])
def test_hype_tail_variants(head):
    assert title(head + "\n2217 Calumet St, Columbus, OH 43202\n$1,450/mo") == "Cozy 2 Bed Duplex in Clintonville"


@pytest.mark.parametrize("head", ["Sweetheart Deal!", "Hot deal!!!", "Won't last!", "Great Deal!!"])
def test_hype_only_title_gives_the_address(head):
    assert title(head + "\n2217 Calumet St, Columbus, OH 43202\n2 bed. Rent $1,450/mo") == "2217 Calumet St"


# ---- MCP add_place: the same clean-up as a pasted title
def _add(store, **kw):
    store.add_search("T", "rent")
    srv = server(store)
    call(srv, "add_place", **kw)
    return store.get_place(1)


@pytest.mark.parametrize("given,address,expected", [
    ("Cozy 2 Bed Duplex in Clintonville - Won't Last!", "2217 Calumet St", "Cozy 2 Bed Duplex in Clintonville"),
    ("Sweetheart Deal!", "100 Main St", "100 Main St"),
    ("Hot Deal!!!", "100 Main St", "100 Main St"),
    ("Won't Last - Sunny Loft", "100 Main St", "Sunny Loft"),
    ("Townhome", "88 Birch Lane", "88 Birch Lane"),
    ("Ravenswood 3BR/2BA - Dep", "4801 N Damen Ave", "Ravenswood 3BR/2BA"),
    ("Casa de 3 recámaras y 2 baños", "28 Calle Sol", "28 Calle Sol"),
    ("Zillow listing - Stadium View", "1 Main St", "Stadium View"),
])
def test_mcp_add_place_cleans_the_title(store, given, address, expected):
    assert _add(store, title=given, address=address, price=1500)["title"] == expected


@pytest.mark.parametrize("given", ["Elm Court", "Maple Court #4B", "The Lofts at Pilsen", "Clintonville Cottage Condo", "Amazing View Apartments"])
def test_mcp_add_place_keeps_a_real_name(store, given):
    assert _add(store, title=given, address="12 Elm St", price=1500)["title"] == given


def test_mcp_add_place_keeps_a_sales_title_when_there_is_no_address(store):
    assert _add(store, title="Sweetheart Deal!", url="https://example.com/x", price=1500)["title"] == "Sweetheart Deal"


def test_mcp_add_place_title_from_listing_text_address(store):
    p = _add(store, title="Sweetheart Deal!", listing_text="2 bed. 2217 Calumet St, Columbus, OH 43202. Rent $1,450/mo")
    assert p["title"] == "2217 Calumet St"
