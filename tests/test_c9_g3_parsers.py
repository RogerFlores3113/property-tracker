"""Cycle 9, group 3: parking, titles, address and city, buyer money. Unknown is better than wrong."""
import pytest

from prophelper.parsers import parse_listing

OPTIONAL_NOTE = "not counted in the monthly cost"


def notes(r):
    return r.get("found_in_listing", "")


# ----------------------------------------------------------------------------- parking
def test_surface_lot_free_detached_garage_is_optional():
    r = parse_listing("2BR apartment\nSurface lot, free. Detached garage $85.")
    assert r["parking"] == "lot"
    assert r["parking_cost"] == 0
    assert "A garage is available for $85 a month" in notes(r) and OPTIONAL_NOTE in notes(r)


def test_extra_space_is_noted_not_counted():
    r = parse_listing("1 space included; additional parking $120/mo")
    assert r["parking_cost"] == 0
    assert "An extra parking space is available for $120 a month" in notes(r)


@pytest.mark.parametrize("text,what,amount", [
    ("Garage space available $175/mo", "garage", 175),
    ("(optional) garage $100", "garage", 100),
    ("Garage available for $150", "garage", 150),
])
def test_optional_garage_not_counted(text, what, amount):
    r = parse_listing(text)
    assert "parking_cost" not in r and "parking" not in r
    assert f"A {what} is available for ${amount} a month" in notes(r)


@pytest.mark.parametrize("text", ["1 spot $50/mo", "Parking: 1 spot, $50/month"])
def test_required_spot_price_counts(text):
    r = parse_listing(text)
    assert r["parking_cost"] == 50
    assert OPTIONAL_NOTE not in notes(r)


@pytest.mark.parametrize("text", ["off-street parking", "Off-street parking available", "Nice place. Off-street parking for 1 car."])
def test_off_street_parking_is_found(text):
    assert parse_listing(text)["parking"] == "lot"


# ----------------------------------------------------------------------------- titles
def test_facts_and_features_line_is_not_a_title():
    r = parse_listing("Facts & features: Bedrooms: 2, Bathrooms\nRent $1,500")
    assert "title" not in r


def test_title_not_cut_at_incl_period():
    assert parse_listing("2BR/1BA Apartment $1,295 incl. utilities")["title"] == "2BR/1BA Apartment"
    assert parse_listing("2BR/1BA Apartment $1,295 incl.")["title"] == "2BR/1BA Apartment"


def test_craigslist_headline():
    r = parse_listing("$1,375 / 1br - 640ft2 - Newer 1BR near campus (Urbana)\nQuiet building, built 2020\nRent includes water, sewer and trash")
    assert r["title"] == "Newer 1BR near campus"
    assert r["city"] == "Urbana"


def test_sentences_are_never_titles():
    r = parse_listing("Quiet building, built 2020\nRent includes water, sewer and trash\nRent $1,200")
    assert "title" not in r


def test_banner_and_price_removed_and_title_cased():
    r = parse_listing("***FREE RENT*** 3BR 2BA SOUTH LOOP CONDO FOR RENT $3,300 per month")
    assert r["title"] == "3BR 2BA South Loop Condo"


def test_title_never_cut_mid_word():
    assert parse_listing("Luxury 1BR Campus $899!!! 1 bed 1 bath a")["title"] == "Luxury 1BR Campus"
    long = "Beautifully renovated spacious sunlit two bedroom apartment steps from the campus quad extraordinarycharacters"
    t = parse_listing(long)["title"]
    assert long.startswith(t) and len(t) <= 70 and not t.endswith(" ")
    assert t.split()[-1] in long.split()


def test_listed_days_ago_is_not_a_title():
    r = parse_listing("Listed 3 days ago in Menlo Park, CA\n123 Main St, Menlo Park, CA 94025")
    assert r["title"] == "123 Main St"
    assert r["city"] == "Menlo Park"


def test_all_caps_address_and_city_in_normal_case():
    r = parse_listing("720 S DEARBORN ST\nCHICAGO, IL 60605\n$2000/mo")
    assert (r["address"], r["city"], r["state"]) == ("720 S Dearborn St", "Chicago", "IL")
    r = parse_listing("55 NE LAKE DR, SAN JOSE, CA 95112")
    assert r["address"] == "55 NE Lake Dr" and r["city"] == "San Jose"


def test_trailing_direction_kept():
    r = parse_listing("1418 W Morse Ave N, Chicago, IL 60626")
    assert r["address"] == "1418 W Morse Ave N"
    assert r["city"] == "Chicago"


# ----------------------------------------------------------------------------- buyer money
def test_assessment_without_amount_does_not_take_price():
    r = parse_listing("Home for sale $349,900 - new roof special assessment paid by seller")
    assert r["price"] == 349900
    assert "special_assessment" not in r
    assert "A special assessment is mentioned but no amount is given" in notes(r)


def test_assessment_amount_next_to_words():
    r = parse_listing("Home for sale $349,900. Special assessment of $4,000 paid by buyer")
    assert r["special_assessment"] == 4000 and r["special_assessment_payer"] == "buyer"
    r = parse_listing("Home for sale $349,900. $6,500 special assessment, seller pays")
    assert r["special_assessment"] == 6500


def test_seller_credit_percent_from_price():
    r = parse_listing("Home for sale $349,900. Seller concessions up to 3% toward closing costs")
    assert r["seller_credit"] == 10497
    assert "worked out from 3% of the $349,900 price" in notes(r)


def test_seller_credit_percent_without_price_is_empty():
    r = parse_listing("Seller concessions up to 3% toward closing costs")
    assert "seller_credit" not in r
    assert "no price to work it out from" in notes(r)


def test_seller_pays_closing_costs_no_amount_is_empty_with_note():
    r = parse_listing("Home for sale $349,900. Seller pays closing costs.")
    assert "seller_credit" not in r
    assert "gives no amount" in notes(r)


def test_seller_credit_dollars():
    assert parse_listing("Home for sale $349,900. $5,000 seller credit")["seller_credit"] == 5000


@pytest.mark.parametrize("text", ["Condo $349,900 no HOA", "Condo $349,900. No HOA fees", "Condo $349,900 HOA: none"])
def test_no_hoa_is_zero(text):
    assert parse_listing(text)["hoa"] == 0


def test_real_hoa_still_read():
    assert parse_listing("Condo $349,900 HOA $250/mo")["hoa"] == 250
