"""Cycle 33, G4: a title is never cut to "3 bed place" when the listing has a name, never keeps "Rate this unit 10/10", and a city never keeps a full stop."""
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


# ---- "Rate this unit 10/10!" in front of a name
@pytest.mark.parametrize("first,name", [
    ("Rate this unit 10/10! Grandview Yard Apartments", "Grandview Yard Apartments"),
    ("Rate this apartment 10/10 - Maple Court Apartments", "Maple Court Apartments"),
    ("Please rate this unit 10/10: Maple Court Apartments", "Maple Court Apartments"),
    ("Rate this unit 10 out of 10. Maple Court Apartments", "Maple Court Apartments"),
    ("RATE THIS UNIT 10/10! MAPLE COURT APARTMENTS", "Maple Court Apartments"),
    ("Rate this unit 10/10!! Sunset Row 3BR Townhouse", "Sunset Row 3BR Townhouse"),
    ("Rate this listing 5 stars! Maple Court Apartments", "Maple Court Apartments"),
    ("Rate this unit 10/10!\nMaple Court Apartments", "Maple Court Apartments"),
])
def test_rate_request_is_not_in_the_name(first, name):
    r = read(first + "\n2 Bedroom | 2 Bath | $1,495/mo | 1100 sqft\nDeposit $1,500.")
    assert r["title"] == name
    assert "rate" not in r["title"].lower()
    assert not r.get("unit")


def test_nontech_l10_whole_listing():
    r = read(fixture("r32-nontech-l10.txt"))
    assert r["title"] == "Grandview Yard Apartments"
    assert r["address"] == "1000 Grandview Ave" and r["city"] == "Columbus" and r["state"] == "OH"
    assert r["beds"] == 2 and r["baths"] == 2 and r["price"] == 1495 and not r.get("unit")


@pytest.mark.parametrize("text,title", [
    ("Maple Court Apartments - rate this unit 10/10\n2 bed 1 bath $1,500", "Maple Court Apartments"),
    ("Rated 4.5 stars: Maple Court Apartments\n2 bed 1 bath $1,500", None),
    ("The Rate Building, 2 bed 1 bath $1,500", None),
])
def test_other_titles_are_left_alone(text, title):
    r = read(text)
    if title:
        assert r["title"] == title
    else:
        assert "Rate" in r.get("title", "") or "Rated" in r.get("title", "") or r.get("title") is None


# ---- a headline that ends in a full stop is still the name
@pytest.mark.parametrize("text,title,city", [
    ("FOR RENT: 3 bed 2 bath ranch, Foster City.\nRent $2,325.", "3 bed 2 bath ranch, Foster City", "Foster City"),
    ("For rent: 3 bed 2 bath ranch, Foster City\nRent $2,325.", "3 bed 2 bath ranch, Foster City", "Foster City"),
    ("FOR RENT: 3 bed 2 bath ranch, Foster City. 1-bed 2/2 also available.\nRent $2,325.", "3 bed 2 bath ranch, Foster City", "Foster City"),
    ("3 bed 2 bath ranch for rent, Foster City.\nRent $2,325.", "3 bed 2 bath ranch, Foster City", "Foster City"),
    ("FOR LEASE: 2 bed 1 bath duplex, Linden.\nRent $1,325.", "2 bed 1 bath duplex, Linden", "Linden"),
    ("FOR RENT: 3BR/2BA ranch home, Foster City.\nRent $2,325.", "3BR/2BA ranch home, Foster City", "Foster City"),
    ("For Rent: Sunset Ranch Homes, 3 bed 2 bath, Foster City.\nRent $2,325.", "Sunset Ranch Homes", "Foster City"),
    ("FOR RENT: Sunset Ranch Homes, 3 bed 2 bath, Foster City\nRent $2,325.", "Sunset Ranch Homes", "Foster City"),
])
def test_headline_with_a_full_stop(text, title, city):
    r = read(text)
    assert r["title"] == title
    assert r["city"] == city
    assert r["beds"] in (3, 2) and r["price"] in (2325, 1325)


def test_family_l12_whole_listing_has_a_name_and_a_city():
    r = read(fixture("r32-family-l12.txt"))
    assert r["title"] == "3 bed 2 bath ranch, Foster City"
    assert r["city"] == "Foster City"
    assert r["beds"] == 3 and r["baths"] == 2 and r["price"] == 2325


@pytest.mark.parametrize("text", [
    "Spacious 2 bedroom with a big yard. Pets are welcome.\nRent $1,325.",   # a real sentence
    "This 3 bed 2 bath ranch is close to the park. Call us.\nRent $2,325.",    # verbs and more sentences
    "Please call to see this 2 bed 1 bath.\nRent $1,325.",
])
def test_a_sentence_is_still_not_a_name(text):
    r = read(text)
    assert not r.get("city")
    assert "Pets are welcome" not in r.get("title", "") and "Please call" not in r.get("title", "")


@pytest.mark.parametrize("text", [
    "FOR RENT: 3 bed 2 bath ranch, Utilities Included.\nRent $2,325.",
    "FOR RENT: 3 bed 2 bath ranch, Pets OK.\nRent $2,325.",
    "FOR RENT: 3 bed 2 bath ranch, Washer Dryer.\nRent $2,325.",
    "FOR RENT: 3 bed 2 bath ranch, 12 Oak St.\nRent $2,325.",
])
def test_a_feature_after_the_comma_is_not_a_city(text):
    assert not read(text).get("city")


# ---- a city never keeps a trailing full stop
@pytest.mark.parametrize("text", [
    "The Mercer, 1 BR, 1 Bath, $1,500/mo. 100 S Mercer Ave, Champaign.\nWasher dryer in unit.",
    "100 S Mercer Ave, Champaign.\nRent $1,500. 1 bed 1 bath",
    "100 S Mercer Ave, Champaign. Rent $1,500. 1 bed 1 bath",
    "100 S Mercer Ave, Champaign\nRent $1,500. 1 bed 1 bath",
    "100 S Mercer Ave, Champaign - Rent $1,500. 1 bed 1 bath",
    "100 S Mercer Ave, Champaign, IL. Rent $1,500. 1 bed 1 bath",
    "100 S Mercer Ave, Champaign IL.\nRent $1,500. 1 bed 1 bath",
])
def test_city_has_no_trailing_period(text):
    r = read(text)
    assert r["city"] == "Champaign"
    assert r["address"] == "100 S Mercer Ave"


@pytest.mark.parametrize("text,city", [
    ("100 S Mercer Ave, St. Louis. Rent $1,500. 1 bed 1 bath", "St. Louis"),
    ("100 S Mercer Ave, Mt. Prospect. Rent $1,500. 1 bed 1 bath", "Mt. Prospect"),
])
def test_an_abbreviation_inside_a_city_keeps_its_dot(text, city):
    assert read(text)["city"] == city


def test_uiuc_l10_whole_listing():
    r = read(fixture("r32-uiuc-l10.txt"))
    assert r["city"] == "Champaign" and r["address"] == "100 S Mercer Ave" and r["title"] == "The Mercer"
    assert r["price"] == 1500 and r["beds"] == 1 and r["baths"] == 1


@pytest.mark.parametrize("city,want", [("Champaign.", "Champaign"), ("Champaign. ", "Champaign"), (" Urbana,", "Urbana"), ("St. Louis", "St. Louis"), ("Mt.", "Mt."), ("", ""), (None, "")])
def test_clean_city(city, want):
    assert P.clean_city(city) == want


def test_mcp_add_place_cleans_the_city(store):
    from mcp_util import call, server
    srv = server(store)
    s = store.add_search("C", "rent")
    call(srv, "add_place", title="The Mercer", address="100 S Mercer Ave", city="Champaign.", search_id=s["id"], price=1500)
    assert store.list_places(s["id"])[0]["city"] == "Champaign"


# ---- a "!" ends the headline (r18-nontech-l4, r16-uiuc-l7)
def test_exclaim_ends_headline_nontech_l4():
    r = read(fixture("r18-nontech-l4.txt"))
    assert r["title"] == "Cozy duplex in Hilltop"


def test_exclaim_ends_headline_uiuc_l7():
    r = read(fixture("r16-uiuc-l7.txt"))
    assert r["title"] == "Charming 1BR near Green & Wright"


@pytest.mark.parametrize("first", [
    "Cozy duplex in Hilltop! 2 bedrooms, 1 bath. 1.5k a month.",
    "Cozy duplex in Hilltop! 2 bedrooms, 1 bath.",
    "Cozy duplex in Hilltop!! 2 bedrooms, 1 bath. 1.5k a month.",
    "Cozy duplex in Hilltop! 2 bedrooms 1 bath $1,500/mo",
])
def test_exclaim_headline_wordings(first):
    assert read(first + "\n* Gas heat - tenant pays about $40/mo\n")["title"] == "Cozy duplex in Hilltop"


def test_exclaim_negatives_keep_other_titles():
    assert read("Call now! 2 bedrooms, 1 bath. $1,500/mo\n123 Main St Columbus OH")["title"] != "Call now"
    assert read("Maple Court Apartments\n2 bedrooms, 1 bath!\n")["title"] == "Maple Court Apartments"


# ---- the address line's city wins over a headline neighbourhood (r27/r28 roommates)
@pytest.mark.parametrize("name", ["r27-roommates-l12.txt", "r28-roommates-l4.txt"])
def test_city_from_address_line_not_neighbourhood(name):
    r = read(fixture(name))
    assert r["city"] == "Chicago"
    assert r["address"] == "1200 N Wells St"


@pytest.mark.parametrize("text,city", [
    ("Gold Coast-adjacent 3BR/2BA, Old Town. Price: $3,300. 1200 N Wells St Chicago 60610. Dog 40 lbs max.", "Chicago"),
    ("Sunny 3BR/2BA, Old Town. $3,300. 1200 N Wells St, Chicago 60610.", "Chicago"),
])
def test_city_wordings(text, city):
    assert read(text)["city"] == city


def test_headline_city_still_used_without_address_city():
    assert read("3 bed 2 bath ranch, Foster City.\n")["city"] == "Foster City"
