"""Cycle 20, group 3: parking choices with their own prices, per-car prices, free and yearly parking, buyer insurance and
closing percent, pet count, pet notes and pet deposit refundability."""
import re

import pytest

from prophelper import money
from prophelper.parsers import parse_listing

HEAD = "2BR apartment, $1,400/mo, 12 Main St, Springfield IL.\n"


def read(text, buying=False):
    return parse_listing(text, buying=buying)


def notes(r):
    return r.get("found_in_listing") or ""


# ---- 1. a choice of parking kinds keeps each price on its own kind
UIUC_L15 = ("Quiet 1 bedroom, newer build (2018), 1 bath, $1,340 per month, 1401 E Florida Ave Urbana IL.\n"
            "Washer and dryer in the unit; dishwasher; free parking in a surface lot (garage spaces also offered for $75).\n"
            "Electric $45 seasonal (more in summer), gas $20-$60 depending on season. Water and trash included. No pets allowed.\n"
            "Lease through July 31, 2028.\n")


def test_uiuc_l15_garage_keeps_its_own_price():
    r = read(UIUC_L15)
    assert r["parking"] == "lot"  # cycle 25: the free lot is the parking, the priced garage is an optional upgrade
    assert r["parking_cost"] == 0
    assert "$75" in notes(r) and "optional" in notes(r)


@pytest.mark.parametrize("text", [
    "Free parking in a surface lot (garage spaces also offered for $75).",
    "Parking: free surface lot, garage $75/month.",
    "Garage parking for $75 a month or a free surface lot.",
    "Parking: garage $75/mo or surface lot (free)",
])
def test_free_lot_and_priced_garage_in_any_layout(text):
    r = read(HEAD + text)
    assert (r["parking"], r["parking_cost"]) == ("lot", 0)  # cycle 25: the free lot is the parking, the garage is an optional upgrade
    assert notes(r).count("$75") == 1 and "optional" in notes(r)


def test_three_kinds_with_prices_keep_the_best_kinds_price():
    r = read(HEAD + "Parking: covered $45/mo or surface lot (free) or garage $90/mo")
    assert (r["parking"], r["parking_cost"]) == ("lot", 0)  # cycle 25: the free lot is the parking; covered and garage are optional upgrades
    assert "$45" in notes(r) and "$90" in notes(r) and "optional" in notes(r)


def test_same_kind_two_prices_keeps_the_cheapest():
    r = read(HEAD + "Parking: garage $120/mo or garage $90/mo")
    assert (r["parking"], r["parking_cost"]) == ("garage", 90)


def test_an_extra_that_is_offered_stays_optional():
    r = read(HEAD + "Parking included. Garage available for $75.")
    assert (r["parking"], r["parking_cost"]) == ("lot", 0)
    assert "optional" in notes(r)


# ---- 2. per-car prices
@pytest.mark.parametrize("text", [
    "Parking: 1st car $100, 2nd car $120.",
    "Parking is $100 for the first car and $120 for a second car.",
    "Parking:\n- 1st car: $100\n- 2nd car: $120",
    "Parking: first vehicle $100/mo, additional vehicle $120/mo",
])
def test_first_car_price_is_the_parking_cost(text):
    r = read(HEAD + text)
    assert r["parking_cost"] == 100
    assert "second car" in notes(r) and "$120" in notes(r)


def test_roommates_l17_listing():
    r = read("Irving Park 3BR/2BA - rent $2,950\n4000 N Pulaski Rd. Heat included. Electric $50/mo avg. Parking: 1st car $100, 2nd car $120.\n"
             "Deposit 1 month rent. App fee: $40 each. Pet rent $30. Admin fee $150. Trash $15 flat.\nHO6/insurance n/a. Special: first month 50% off.\n")
    assert r["parking_cost"] == 100
    assert "$120" in notes(r)


# ---- 3. options with no prices
def test_three_kinds_no_prices_get_a_note():
    r = read("Gorgeous 3 bedroom house, rent 2,340.\nParking: garage OR 2 driveway spots OR street permit. \nDogs: approval only.\n")
    assert r["parking"] == "garage"
    assert r.get("parking_cost") is None
    n = notes(r)
    assert "driveway" in n and "street permit" in n


@pytest.mark.parametrize("text,others", [
    ("Parking: assigned garage space or surface lot.", ["surface lot"]),
    ("Parking options: garage / carport / street", ["covered parking", "street parking"]),
    ("Parking: garage, carport, or street permit available", ["covered parking", "street permit"]),
])
def test_priceless_choices_are_named(text, others):
    r = read(HEAD + text)
    assert r["parking"] == "garage"
    for o in others:
        assert o in notes(r)


def test_roommates_l6_other_prices_are_not_listed_as_missing():
    text = ("Logan Square 3BR2BA $3,250. 2700 N Milwaukee Ave. Updated kitchen, dishwasher, W/D in unit.\n"
            "Tenant pays all utilities (electric ~$60, gas ~$70). 1 dog max, 40 lb.\n"
            "Parking: garage OR street permit OR driveway spot, garage $150, driveway $90.\nSecurity deposit 1.5x rent. Broker fee one month rent.\n")
    r = read(text)
    assert (r["parking"], r["parking_cost"]) == ("garage", 150)
    n = notes(r)
    assert "street permit" in n and "driveway parking for $90 a month" in n
    place = dict(r, reader_notes=n, listing_text=text)
    cost = money.true_monthly_cost(place, "rent")
    assert "$90" not in str(cost.get("listing_notes_label") or "") and "$90" not in str(cost.get("missing"))


# ---- 4. free and yearly parking
@pytest.mark.parametrize("text", [
    "Off-street parking, free.", "Parking is free.", "Parking: Free", "Off-street parking: no charge.", "Parking (free)", "Off-street parking is free",
])
def test_free_parking_in_more_wordings_costs_zero(text):
    r = read(HEAD + text)
    assert r["parking_cost"] == 0
    assert r["parking"] in ("lot", "street")


def test_free_wifi_is_not_free_parking():
    r = read(HEAD + "Parking: garage $50, free wifi")
    assert (r["parking"], r["parking_cost"]) == ("garage", 50)


@pytest.mark.parametrize("text,monthly", [
    ("Parking permit $240/yr", 20), ("Fees: Application $35, Move-in fee $150, Parking permit $120/yr.", 10),
    ("Parking permit: $240 per year", 20), ("Yearly parking permit: $120", 10),
])
def test_yearly_permits_count_by_the_month(text, monthly):
    assert read(HEAD + text)["parking_cost"] == monthly


# ---- 5. buyer
BUYER = "Condo for sale - Asking $325,000\n410 N High St #3C, Columbus, OH 43215\n2 bed / 2 bath\nHOA: $295 monthly.\n"


@pytest.mark.parametrize("text", [
    "Homeowner's insurance (HO6) about $70 per month.",
    "HO6 insurance (about $70/mo).",
    "Insurance: HO6 about $70/month.",
    "HO6 policy ~ $70 monthly.",
])
def test_ho6_monthly_insurance_is_a_yearly_amount(text):
    assert read(BUYER + text, buying=True)["insurance"] == 840


def test_optional_insurance_is_not_a_cost():
    assert "insurance" not in read(BUYER + "HO6 insurance optional $70/mo.", buying=True)


@pytest.mark.parametrize("text", [
    "Title and closing costs approx. 2.5% of price.",
    "Closing costs: about 2.5% of the purchase price.",
    "Buyer pays closing costs of ~2.5% of price.",
])
def test_closing_percent_is_worked_out_from_the_price(text):
    r = read(BUYER + text, buying=True)
    assert r["closing_costs"] == 8125
    assert "2.5%" in notes(r) and "$8,125" in notes(r)


def test_closing_percent_without_a_price_is_only_a_note():
    r = read("Condo for sale, 2 bed. Title and closing costs approx. 2.5% of price.", buying=True)
    assert "closing_costs" not in r
    assert "2.5%" in notes(r)


def test_seller_percent_and_loan_percent_are_not_closing_costs():
    r = read(BUYER + "Seller pays 3% toward closing costs. Closing costs about 3% of the loan.", buying=True)
    assert "closing_costs" not in r


# ---- 6. pets
@pytest.mark.parametrize("text", [
    "Pets considered, one dog under 75 lb ok.", "1 dog OK, under 50 lbs.", "Dogs welcome: one dog allowed.", "Cats ok, one cat only.",
])
def test_one_pet_is_a_count_of_one(text):
    assert read(HEAD + text)["pet_count_limit"] == 1


def test_a_pet_fee_is_not_a_count():
    assert "pet_count_limit" not in read(HEAD + "Dogs ok. One pet fee $250.")


FAMILY_L26 = ("Beautiful family home, 4 bed 2 bath, $2,390. Pets considered, one dog under 75 lb ok with $500 deposit, non-refundable. HOA covers snow removal and lawn.\n"
              "Landlord pays water/sewer/trash. Electric and gas approx $140 per month in winter, $80 summer.\nApplication fee $35 per adult. Available 8/15/27. Great schools. Fenced.\n")


def test_family_l26_count_and_no_cat_note():
    r = read(FAMILY_L26)
    assert r["pets"] == "dogs" and r["pet_count_limit"] == 1
    assert r["pet_fee"] == 500 and "pet_deposit" not in r  # non-refundable: a fee
    assert not re.search(r"\bcats?\b", notes(r), re.I)


def test_pets_considered_note_names_only_listed_species():
    r = read(HEAD + "PETS: Pets considered case by case. Dogs under 40 lbs only.")
    assert not re.search(r"\bcats?\b", notes(r), re.I)
    r = read(HEAD + "Cats welcome. Dogs considered case by case.")
    assert "dogs are considered case by case" in notes(r)


@pytest.mark.parametrize("text", [
    "Pets Allowed. Pet deposit $500, $50 monthly.",
    "Cats ok, $300 pet deposit.",
    "Dogs welcome, pet deposit: $250.",
])
def test_pet_deposit_without_refundable_is_not_shown_as_coming_back(text):
    r = read(HEAD + text)
    assert "does not say if it comes back" in notes(r)
    assert "do not count on getting it back" in notes(r)


@pytest.mark.parametrize("text", [
    "Cats ok, $300 refundable pet deposit.",
    "Cats ok. Pet deposit $300 (refundable).",
    "Cats ok. $300 pet deposit, returned when you move out.",
])
def test_pet_deposit_that_says_refundable_stays(text):
    r = read(HEAD + text)
    assert r["pet_deposit"] == 300
    assert "does not say if it comes back" not in notes(r)


def test_non_refundable_deposit_is_still_a_fee():
    r = read(HEAD + "Cats ok, $300 non-refundable pet deposit.")
    assert r["pet_fee"] == 300 and "pet_deposit" not in r
