"""Cycle 22 group 3: buyer credits and closing, DOM, pet weight conflicts, parking, fenced yard, pet deposit label."""
import re

import pytest

from prophelper import money
from prophelper.parsers import parse_listing

HEAD = "Condo $200,000. 2 bed 1 bath. 12 Main St #4, Columbus, OH 43215. HOA $150 a month. Taxes $2,400 a year. Insurance $600 a year.\n"


def buy(text):
    return parse_listing(text, "", buying=True)


def notes(r):
    return r.get("found_in_listing", "")


@pytest.mark.parametrize("line,credit", [
    ("Seller to credit 2% toward closing costs.", 4000),
    ("Seller will credit 2% of the price toward closing.", 4000),
    ("Seller credit of 2% toward closing costs.", 4000),
    ("Owner will credit 2% toward closing.", 4000),
    ("Owner will credit $2,000 at closing.", 2000),
    ("Seller to credit $2,000 at closing.", 2000),
    ("Owner to credit $2,000 toward closing costs.", 2000),
])
def test_seller_credit_wordings(line, credit):
    r = buy(HEAD + line + "\n")
    assert r["seller_credit"] == credit
    assert r.get("closing_costs") is None
    if "%" in line:
        assert "confirm" in notes(r) and "2%" in notes(r)


@pytest.mark.parametrize("line", [
    "Buyer will need about $7,000 for closing.",
    "Buyer needs around $7,000 for closing costs.",
    "Buyer should budget $7,000 for closing.",
])
def test_buyer_closing_need_is_closing_costs(line):
    r = buy(HEAD + "Seller covers closing costs up to $6,000. " + line + "\n")
    assert r["closing_costs"] == 7000
    assert r.get("seller_credit") is None


@pytest.mark.parametrize("line,tax", [
    ("Real estate tax (2025): $5,100.", 5100),
    ("Property tax (2024): $5,100 per year.", 5100),
    ("Real estate taxes: $5,100/yr.", 5100),
])
def test_tax_with_year_in_parentheses(line, tax):
    r = buy("Condo $339,000. 2 bed. 1 Elm St, Columbus OH 43212\n" + line + "\n")
    assert r["property_tax"] == tax


@pytest.mark.parametrize("line", [
    "Insurance included in your loan escrow $70 per month.",
    "Homeowners insurance (in escrow) $70/mo.",
    "Insurance escrow $70 a month.",
])
def test_insurance_in_escrow(line):
    r = buy("Condo $274,500. 2 bed. 1 Elm St, Columbus OH 43212\n" + line + "\n")
    assert r["insurance"] == 840


def test_hoa_included_insurance_is_not_read_as_insurance():
    r = buy("Condo $274,500. 2 bed. 1 Elm St, Columbus OH 43212\nHOA $500/mo, insurance included in HOA.\n")
    assert r.get("insurance") is None


@pytest.mark.parametrize("line", [
    "Buyer's agent: closing cost help up to $8,000 available.",
    "Closing cost assistance up to $8,000 offered.",
    "Closing help: up to $8,000 for buyers.",
])
def test_closing_help_offer_is_not_a_cost_nor_missing(line):
    r = buy(HEAD + "Estimated closing costs $9,500. " + line + "\n")
    assert r["closing_costs"] == 9500 and r.get("seller_credit") is None
    assert "$8,000" in notes(r)
    r["reader_notes"] = notes(r)
    cost = money.true_monthly_cost(r, "buy")
    assert not cost["missing"] and not cost.get("uncounted")
    assert not money.listing_notes_uncounted(r["reader_notes"], r)


def test_buy_parking_is_not_a_missing_cost_part():
    for line in ("Street parking, permit $35/yr.", "Parking: $60/month.", "Garage parking required, $90/month."):
        r = buy(HEAD + line + "\n")
        r["reader_notes"] = notes(r)
        cost = money.true_monthly_cost(r, "buy")
        assert not any("parking" in m for m in cost["missing"]), (line, cost["missing"])
        assert not money.listing_notes_uncounted(r["reader_notes"], r), line


@pytest.mark.parametrize("line", [
    "Year built: 1999  DOM: 12",
    "Built 1999. DOM: 12",
    "Year built: 1999, Days on market: 12",
    "Year built 1999 | 12 DOM",
])
def test_dom_is_not_the_year(line):
    r = buy(HEAD + line + "\n")
    assert r["days_on_market"] == 12
    assert r["year_built"] == 1999


# ----- pets
@pytest.mark.parametrize("text", [
    "House for rent $2,450. 3 bed. Pets: No dogs over 40 lbs. Pets: Dogs allowed up to 80 lbs with $750 non-refundable fee.",
    "House for rent $2,450. 3 bed.\nNo dogs over 40 lbs.\nDogs allowed up to 80 lbs, $750 fee.",
    "House for rent $2,450. 3 bed. Dogs under 40 lbs only; Large dogs up to 80 lbs OK with $750 fee.",
])
def test_two_dog_weight_limits_conflict(text):
    r = parse_listing(text, "")
    assert r.get("pet_weight_limit") is None
    assert r["pet_fee"] == 750
    n = notes(r)
    assert "two pet weight limits" in n and "40 lbs" in n and "80 lbs" in n and "which one applies" in n


def test_one_weight_limit_still_read_and_cats_dogs_are_not_a_conflict():
    assert parse_listing("House $2,000. 2 bed. Dogs up to 50 lbs, $300 fee.", "")["pet_weight_limit"] == 50
    r = parse_listing("House $2,000. 2 bed. Cats up to 15 lbs. Dogs up to 40 lbs.", "")
    assert "do not match" not in notes(r)
    assert parse_listing("House $2,000. 2 bed. No dogs over 40 lbs. Dogs up to 40 lbs.", "")["pet_weight_limit"] == 40


# ----- parking
@pytest.mark.parametrize("text", [
    "Birchwood 1 Bed $1,485/mo. Parking: 1 space included, 2nd $90. Detached garage available at $165/mo.",
    "1 bed $1,485. 1 space included, 2nd $90.",
    "1 bed $1,485\nParking: one space included; 2nd space $75/mo",
])
def test_included_space_is_known_free_parking(text):
    r = parse_listing(text, "")
    assert r["parking_cost"] == 0
    assert r["parking"] in ("lot", "garage", "covered", "street")
    if "Detached" in text:
        assert r["parking"] == "lot"
    r["reader_notes"] = notes(r)
    cost = money.rent_cost(r, False, 1)
    assert "parking cost" not in cost["missing"]


@pytest.mark.parametrize("text", [
    "Clock Tower 1 bed $1,540. Underground garage: $140 per month, free for first 6 months.",
    "1 bed $1,540. Garage parking $140/mo, first 6 months free.",
    "1 bed $1,540\nParking: $140 a month (6 months free)",
])
def test_parking_promo_keeps_full_price_and_notes_the_offer(text):
    r = parse_listing(text, "")
    assert r["parking_cost"] == 140
    assert r.get("parking") in (None, "garage", "covered")
    assert "free for the first 6 months" in notes(r) and "$140" in notes(r)


# ----- yard
@pytest.mark.parametrize("text,fenced", [
    ("3/2 townhome | $2,360 | Pets: Dogs OK | Fenced. | Security $1,180", 1),
    ("3 bed house $2,100 | Fenced | pool access", 1),
    ("3 bed house $2,100\nFenced.\nPets ok", 1),
    ("3 bed $2,000 | Fenced pool | Pets ok", None),
])
def test_fenced_in_a_pipe_listing(text, fenced):
    assert parse_listing(text, "").get("fenced_yard") == fenced


def test_bare_pet_rent_in_a_fees_list_is_labeled():
    r = parse_listing("Beverly 3BR. Rent $2,950. Fees: Admin $200; Pet $35/mo; Trash $15/mo.", "")
    assert r["pet_rent"] == 35
    assert "monthly pet rent ($35 a month)" in notes(r)


# ----- pet deposit label
def test_pet_deposit_label_says_comes_back_only_when_listing_says_so():
    def label(text):
        r = parse_listing(text, "")
        r["listing_text"] = text
        cash = money.cash_at_move_in(r, pets=True)
        return [p["label"] for p in cash["parts"] if "Pet deposit" in p["label"]]
    assert label("Whole 2BR house $1,350. $500 pet deposit for a cat.") == ["Pet deposit"]
    assert label("2BR $1,350. $300 refundable pet deposit.") == ["Pet deposit (comes back)"]
