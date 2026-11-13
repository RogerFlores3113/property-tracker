"""Cycle 7, G2: names, addresses, taxes, pets and wired deposits in the listing reader, and the CSV Pets cell."""
import pytest

from prophelper import csv_io
from prophelper.parsers import parse_listing


# ---- 1. addresses with no street suffix
def test_no_suffix_address_with_city_state_zip():
    r = parse_listing("3329 N Broadway, Chicago, IL 60657\n2 bed 1 bath $1,800/mo")
    assert r["address"] == "3329 N Broadway"
    assert r["city"] == "Chicago" and r["state"] == "IL" and r["zip"] == "60657"


def test_no_suffix_address_after_a_unit_in_a_name_line():
    r = parse_listing("Lakeview Court - Unit 4C, 3329 N Broadway\n$1,800/mo")
    assert r["address"] == "3329 N Broadway" and r["unit"] == "4C" and r["title"] == "Lakeview Court"
    r = parse_listing("Name - Unit 4C, 3329 N Broadway")
    assert r["address"] == "3329 N Broadway" and r["unit"] == "4C" and r["title"] == "Name"


def test_suffix_address_still_works():
    r = parse_listing("3329 N Broadway Ave Apt 4C\n2 bed")
    assert r["address"] == "3329 N Broadway Ave" and r["unit"] == "4C"


@pytest.mark.parametrize("text", [
    "Rent $1,500 - 2 Bedroom - 1 Bath",
    "Call 555 123 4567, Chicago, IL 60657",
    "1500 sq ft, Chicago, IL",
    "2 Bedroom, Chicago, IL 60601",
    "$1,500 Per Month, Chicago, IL",
    "Call 773 555 1234 or text",
])
def test_prices_phones_and_bedrooms_are_not_addresses(text):
    assert "address" not in parse_listing(text)


# ---- 2. listing names
def test_name_with_unit_and_facts_on_one_long_line():
    r = parse_listing("Riverside Lofts Unit 4B - 2 bed 2 bath condo with in-unit laundry and a balcony over the river. $2,000/mo. 123 Main St, Austin, TX 78701")
    assert r["title"] == "Riverside Lofts" and r["address"] == "123 Main St" and r["unit"] == "4B"


def test_all_caps_name_is_title_case():
    r = parse_listing("THE ARBORETUM RESIDENCES - 1 Bedroom 1 Bath - $1,525/month, 1200 W Green St, Urbana, IL 61801")
    assert r["title"] == "The Arboretum Residences" and r["address"] == "1200 W Green St"
    r = parse_listing("THE ARBORETUM RESIDENCES - 1 Bedroom 1 Bath - $1,525/month\n1200 W Green St\nUrbana, IL 61801")
    assert r["title"] == "The Arboretum Residences"


def test_unit_in_name_line_goes_to_unit():
    r = parse_listing("Maple Court Townhomes, Unit B.\n412 Maple Ct, Champaign, IL")
    assert r["title"] == "Maple Court Townhomes" and r["unit"] == "B" and r["address"] == "412 Maple Ct"


def test_floor_and_bedroom_words_stay_out_of_title():
    r = parse_listing("Hilltop Townhomes 3rd floor 2BR\n88 Hilltop Dr, Urbana, IL")
    assert r["title"] == "Hilltop Townhomes" and r["address"] == "88 Hilltop Dr"


def test_name_on_its_own_line():
    r = parse_listing("Westgate Flats\n210 Westgate Ave\n2 bed $1,300/mo")
    assert r["title"] == "Westgate Flats" and r["address"] == "210 Westgate Ave"


# ---- 3. taxes (property_tax is a yearly figure)
@pytest.mark.parametrize("text,yearly", [
    ("property taxes approx $4,100/yr", 4100),
    ("Taxes: $4,100 per year", 4100),
    ("annual taxes $4,100", 4100),
    ("$342/mo taxes", 4104),
])
def test_tax_phrasings(text, yearly):
    assert parse_listing("2 bed home\n" + text)["property_tax"] == yearly


# ---- 4. pets
def test_pets_dogs_ok():
    assert parse_listing("Pets: dogs ok")["pets"] == "dogs"
    assert parse_listing("dogs ok")["pets"] == "dogs"


def test_cats_with_a_fee_means_cats():
    r = parse_listing("Cats $200 deposit non-refundable")
    assert r["pets"] == "cats" and r["pet_fee"] == 200


def test_conflicting_pet_lines_keep_no_pets_and_say_so():
    r = parse_listing("No pets allowed. Pets: up to 2 dogs")
    assert r["pets"] == "none"
    assert "no pets and also says some pets are allowed" in r["found_in_listing"]


def test_plain_no_pets_has_no_conflict_note():
    r = parse_listing("No pets allowed.\n2 bed $1,500/mo")
    assert r["pets"] == "none" and "also says" not in r.get("found_in_listing", "")


# ---- 5. CSV Pets cell
def _import(store, cell):
    s = store.add_search("Rent", "rent")
    headers, rows = csv_io.read_table(f"Title,Pets\nA,{cell}\n".encode())
    plan = csv_io.plan_import(store, s["id"], headers, rows, csv_io.match_columns(headers))
    return plan[0]


@pytest.mark.parametrize("cell,code", [("dogs ok", "dogs"), ("Two dogs ok", "dogs"), ("cats only", "cats"), ("no pets", "none"),
                                       ("yes", "both"), ("Cats and dogs", "both"), ("None", "none")])
def test_csv_pets_cell_uses_the_paste_reader(store, cell, code):
    item = _import(store, cell)
    assert item["values"].get("pets") == code and not item["warnings"]


def test_csv_unreadable_pets_cell_still_gets_a_clear_note(store):
    item = _import(store, "purple")
    assert "pets" not in item["values"] and item["warnings"]


# ---- 6. wired deposit
def test_wired_deposit_is_not_filled():
    r = parse_listing("Wire $500 deposit to hold unit\n2 bed $1500/mo")
    assert "deposit" not in r and "by wire" in r["found_in_listing"]


def test_real_deposit_beside_a_wire_sentence_is_kept():
    r = parse_listing("Security deposit $1,500.\nWire $500 deposit to hold unit.\n2 bed $1500/mo")
    assert r["deposit"] == 1500
