"""Cycle 10, group 4: parking, price, bedrooms, titles, addresses and buyer money. Unknown is better than wrong."""
import asyncio

import pytest

from prophelper.mcp_server import build_server
from prophelper.parsers import parse_listing
from conftest import local_client


def notes(r):
    return r.get("found_in_listing", "")


# ----------------------------------------------------------------------------- parking
@pytest.mark.parametrize("text,cost", [
    ("Parking required: $150/mo", 150),
    ("mandatory parking $100", 100),
    ("parking fee $75/mo (required)", 75),
])
def test_required_parking_counts(text, cost):
    r = parse_listing(text)
    assert r["parking_cost"] == cost
    assert "not counted" not in notes(r)


@pytest.mark.parametrize("text", [
    "Attached garage included in rent", "Attached 1-car garage", "1 garage space included"])
def test_included_garage_is_free_garage(text):
    r = parse_listing(text)
    assert r["parking"] == "garage" and r["parking_cost"] == 0


@pytest.mark.parametrize("text", ["free parking behind building"])
def test_free_parking_behind_building(text):
    r = parse_listing(text)
    assert r["parking"] == "lot" and r["parking_cost"] == 0


def test_off_street_parking_included():
    r = parse_listing("off-street parking included")
    assert r["parking"] == "lot" and r["parking_cost"] == 0


def test_optional_garage_is_not_the_parking_type():
    r = parse_listing("Garage parking optional $100/mo")
    assert "parking" not in r and "parking_cost" not in r
    assert "A garage is available for $100 a month" in notes(r) and "not counted in the monthly cost" in notes(r)


def test_optional_garage_with_free_lot_keeps_the_lot():
    r = parse_listing("Surface lot, free. Garage parking optional $100/mo")
    assert r["parking"] == "lot" and r["parking_cost"] == 0
    assert "A garage is available for $100 a month" in notes(r)


def test_unpriced_garage_available_is_optional():
    r = parse_listing("Garage space available")
    assert "parking" not in r and "parking_cost" not in r
    assert "A garage is available" in notes(r)


# ----------------------------------------------------------------------------- price and beds
def test_rent_plus_utilities_is_the_rent():
    assert parse_listing("Rent: $1,150 + utilities")["price"] == 1150


def test_dollars_a_month_without_a_sign():
    r = parse_listing("1400 dollars a month")
    assert r["price"] == 1400
    assert "address" not in r and "unit" not in r and "title" not in r


def test_conditional_reduced_rent_keeps_listed_price_and_notes():
    r = parse_listing("Rent $3,500/mo. Reduced to $3,250 with 12 month lease!")
    assert r["price"] == 3500
    assert "The listing says the rent drops to $3,250 with a 12 month lease. Ask if that applies to you." in notes(r)


def test_conditional_reduced_rent_alone_is_not_the_price():
    r = parse_listing("Reduced to $3,250 with 12 month lease!")
    assert "price" not in r
    assert "Ask if that applies to you." in notes(r)


@pytest.mark.parametrize("text", ["1 month free", "first month free"])
def test_free_month_is_a_note_not_a_price_change(text):
    r = parse_listing("Rent $1,800/mo\n" + text)
    assert r["price"] == 1800
    assert "rent concession" in notes(r) and text in notes(r)
    assert "title" not in r or r["title"] != text


def test_converted_bedrooms():
    r = parse_listing("2BR converted to 1 bed")
    assert r["beds"] == 1
    assert "2 bedroom that was converted to a 1 bedroom" in notes(r)


# ----------------------------------------------------------------------------- titles and addresses
def test_site_label_is_not_the_title():
    r = parse_listing("FB Marketplace - 2 bedroom apartment near campus\n$1200/mo")
    assert r["title"] == "2 bedroom apartment near campus" and r["price"] == 1200 and r["beds"] == 2


def test_rental_label_is_not_the_title():
    r = parse_listing("Rental: 3 Bedroom Home in Belmont\n$2500/mo")
    assert r["title"] == "3 Bedroom Home in Belmont"


def test_title_drops_dangling_only():
    r = parse_listing("Free money 2BR 2BA downtown Columbus only\n$1500/mo")
    assert r["title"] == "Free money 2BR 2BA downtown Columbus"


def test_title_has_no_half_word():
    r = parse_listing("Cozy flat near Blue Lake and the old town square plaza walking distance downtown Chicago Illinois\n$1500/mo")
    assert r["title"] and r["title"].split()[-1] in r["title"].split() and "Blue L" != r["title"][-6:]
    assert not r["title"].endswith((" near", " and", " with", " for", " in", " -"))


def test_caps_pet_rule_headline_is_not_title_but_price_is_read():
    r = parse_listing("NO PETS ALLOWED EXCEPT SERVICE ANIMALS - $2,100\n2 bed 1 bath apartment")
    assert r["price"] == 2100
    assert r["title"] == "2 bed 1 bath apartment"
    r = parse_listing("NO PETS ALLOWED EXCEPT SERVICE ANIMALS - $2,100")
    assert r["price"] == 2100 and "title" not in r


@pytest.mark.parametrize("text", [
    "1418 W Morse Ave N", "1418 W Morse Ave N Chicago IL 60626", "1418 W Morse Ave N, Chicago, IL 60626",
    "1418 W Morse Ave N\nChicago, IL", "1418 W Morse Ave N 2 bed $1500"])
def test_trailing_direction_is_kept(text):
    r = parse_listing(text)
    assert r["address"] == "1418 W Morse Ave N" and r["title"] == "1418 W Morse Ave N"
    assert "unit" not in r


def test_trailing_direction_survives_web_save_and_mcp(store):
    client = local_client(store)
    client.post("/search", data={"name": "R", "mode": "rent"}, follow_redirects=False)
    text = "1418 W Morse Ave N\nChicago, IL 60626\n2 bed 1 bath $1200/mo"
    page = client.post("/add/parse", data={"text": text})
    assert 'value="1418 W Morse Ave N"' in page.text
    client.post("/add/save", data={"title": "Morse", "address": "1418 W Morse Ave N", "city": "Chicago", "listing_text": text}, follow_redirects=False)
    assert [p["address"] for p in store.list_places()] == ["1418 W Morse Ave N"]
    asyncio.run(build_server(store).call_tool("add_place", {"title": "Other", "listing_text": "1418 W Morse Ave N Chicago IL\nUnit 9\n$1200/mo"}))
    assert sorted((p["address"], p["unit"]) for p in store.list_places()) == [("1418 W Morse Ave N", ""), ("1418 W Morse Ave N", "9")]


@pytest.mark.parametrize("text,unit", [
    ("Unit 3B, 500 Main St, Austin TX 78701\n$1500/mo", "3B"),
    ("#1204, 500 Main St, Austin TX\n$1500/mo", "1204"),
    ("500 Main St #1204 Austin TX\n$1500/mo", "1204"),
    ("500 Main St Apt #3B, Austin TX 78701\n$1500/mo", "3B"),
])
def test_unit_goes_in_unit_field_only(text, unit):
    r = parse_listing(text)
    assert r["address"] == "500 Main St" and r["unit"] == unit
    assert r["title"] == "500 Main St"


# ----------------------------------------------------------------------------- buyer money
@pytest.mark.parametrize("text", ["Seller concessions up to 3%", "Seller pays closing costs up to 3%"])
def test_percent_concession_never_fills_credit(text):
    r = parse_listing("List price $500,000\n" + text)
    assert "seller_credit" not in r and r["price"] == 500000
    assert "The listing offers seller concessions of up to 3%. Ask what the seller will really give." in notes(r)


def test_seller_to_contribute_dollars():
    r = parse_listing("List price $500,000\nSeller to contribute $5,000 toward buyer closing costs")
    assert r["seller_credit"] == 5000


def test_monthly_assessment_is_a_note():
    r = parse_listing("List price $500,000\nAssessment for windows: $150/month for 24 months")
    assert "special_assessment" not in r
    assert "an assessment of $150 a month for 24 months ($3,600 in all)" in notes(r)
    r = parse_listing("List price $500,000\nSpecial assessment of $150/month for 24 months")
    assert "special_assessment" not in r and "$150 a month for 24 months" in notes(r)


@pytest.mark.parametrize("text", ["Special assessment pending, amount not yet determined", "Special assessment: amount TBD"])
def test_unknown_assessment_is_empty_with_note(text):
    r = parse_listing("List price $500,000\n" + text)
    assert "special_assessment" not in r
    assert "A special assessment is mentioned but no amount is given" in notes(r)


def test_title_drops_price_written_in_words():
    from prophelper import parsers
    r = parsers.parse_listing("FB Marketplace - 2 bedroom duplex 1400 dollars a month. $700 deposit. Everything included except cable. Pm me")
    assert r["title"] == "2 bedroom duplex"
    assert r["price"] == 1400
