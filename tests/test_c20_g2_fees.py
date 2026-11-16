"""Cycle 20 G2: rent, deposit, application fee, broker fee, unit prices, superseded amounts, and the "1x1." layout."""
from __future__ import annotations

import pytest

from prophelper.parsers import parse_listing


def read(text: str) -> dict:
    return parse_listing(text, "")


def notes(r: dict) -> str:
    return r.get("found_in_listing") or ""


# ---- 1. "each" application fees are per adult
@pytest.mark.parametrize("line,amount", [
    ("Application fee $40 each. Lease 13 months.", 40),
    ("Applicants pay $50 each.", 50),
    ("Applicant screening fee $38 each", 38),
    ("Each applicant pays $45.", 45),
    ("Fees: Application fee $55 each, move-in fee $150", 55),
    ("- Application: $35 each", 35),
])
def test_each_application_fee_is_per_adult(line, amount):
    r = read("Maple 3BR 2BA. $3,100 per month.\n" + line)
    assert r["application_fee"] == amount
    assert r["application_fee_per_adult"] == 1
    assert "per person" in notes(r) or "per adult" in notes(r)


def test_each_fee_does_not_touch_move_in_fee():
    r = read("Maple 3BR 2BA. $3,100 per month.\nApplication fee $40 each. Move-in fee $200.")
    assert r["move_in_fees"] == 200


# ---- 2. Fees: lists
@pytest.mark.parametrize("fees", [
    "Fees: Application $35, Move-in fee $150, Parking permit $120/yr.",
    "Fees: Application $35; Move-in fee $150",
    "Fees:\n- Application $35\n- Move-in fee $150",
])
def test_fees_list_reads_application(fees):
    r = read("2 BEDS | 1 BATH | $1,475\n" + fees)
    assert r["application_fee"] == 35
    assert r["move_in_fees"] == 150


@pytest.mark.parametrize("line", [
    "Pet policy: Cats only, 1 max, $35 monthly rent, $200 fee.",
    "Pets: 2 max, $35 pet rent, $200 one-time fee",
    "- Pets welcome ($200 fee, $35/mo)",
])
def test_pet_fee_from_pet_line(line):
    r = read("2 BEDS | 1 BATH | $1,475\n" + line)
    assert r["pet_fee"] == 200
    assert r["pet_rent"] == 35


def test_application_fee_is_not_the_pet_fee():
    r = read("2 BEDS | 1 BATH | $1,475\nPets OK. Application fee $40, move-in fee $100.")
    assert "pet_fee" not in r


# ---- 3. deposits
@pytest.mark.parametrize("line", ["1 month deposit.", "One month deposit.", "Deposit: 1 month.", "1-month security deposit"])
def test_deposit_one_month(line):
    r = read("Rogers Park 3BR 2BA $2,700/mo\n" + line)
    assert r["deposit"] == 2700


def test_deposit_two_months():
    assert read("Rogers Park 3BR 2BA $2,700/mo\nTwo month deposit.")["deposit"] == 5400


@pytest.mark.parametrize("line", [
    "Move-in cost: first month + $3,100 security + $200 move-in fee.",
    "Move-in: first month, $3,100 security, $200 move-in fee",
    "Due at signing: $3,100 security and $200 move-in fee",
])
def test_bare_security_is_the_deposit(line):
    r = read("Ravenswood 3BR 2BA. $3,100 per month.\n" + line)
    assert r["deposit"] == 3100
    assert r["move_in_fees"] == 200


def test_security_fee_is_not_a_deposit():
    r = read("2 BEDS | 1 BATH | $1,475\n$50 security fee.")
    assert "deposit" not in r


@pytest.mark.parametrize("line", [
    "Deposit: $500 (may be higher with credit)",
    "Deposit $500, may vary depending on credit",
    "Security deposit $500 - could be more with weaker credit",
])
def test_deposit_credit_dependent(line):
    r = read("Hilltop 2 Bed 1 Bath $1,225 per month\n" + line)
    assert r["deposit"] == 500
    assert "depends on credit" in notes(r)


# ---- 4. broker fee as percent
@pytest.mark.parametrize("line", [
    "Broker fee: 50% of one month's rent due at lease signing.",
    "Broker fee is half a month's rent.",
    "Broker fee - 50% of 1 month rent",
])
def test_broker_fee_percent_of_month(line):
    r = read("HYDE PARK - 3 BED 2 BATH - $3,295\n" + line)
    assert r["broker_fee"] == 1648
    assert "worked out" in notes(r).lower()


def test_broker_fee_percent_without_rent_is_unknown():
    r = read("Broker fee: 50% of one month's rent. 3 bed")
    assert "broker_fee" not in r
    assert "rent was not read" in notes(r)


# ---- 5. superseded amounts
@pytest.mark.parametrize("line", [
    "No: rent is $1,440 (not $1,380 as earlier posted).",
    "Rent is $1,440. The $1,380 we posted before was a typo.",
    "Rent $1,440 (correction, not $1,380 posted earlier)",
])
def test_superseded_rent_has_one_short_note(line):
    r = read("Lincoln Heights 1x1. " + line + "\n1210 S Lincoln Ave, Urbana, IL 61801.")
    assert r["price"] == 1440
    assert "not counted" not in notes(r)
    assert "missing" not in notes(r)
    assert notes(r).count("$1,380") <= 1


def test_stray_price_reduced_note_after_arrow():
    r = read("RENT REDUCED $2,450 -> $2,375. 3 bd, 2 ba townhouse.")
    assert r["price"] == 2375
    assert "Price reduced" not in notes(r)


# ---- 6. unit prices
def test_unit_price_picks_the_listings_own_bedrooms():
    r = read("Cedar Court Townhomes - 3 bed 2.5 bath, 1,450 sqft. $1,350 -> now $1,290?? sorry, that is the 2BR. 3BR is $2,295/mo\nApplication fee: $45 per adult.")
    assert r["price"] == 2295
    assert r["beds"] == 3


@pytest.mark.parametrize("text,beds,price", [
    ("3 bed 2 bath. 2BR: $1,290. 3BR: $2,295. Nice", 3, 2295),
    ("2 bed 1 bath apartment. $1,500/mo for the 2 bedroom, $1,900 for the 3 bedroom", 2, 1500),
    ("Maple Court. 2BR is $1,290/mo, 3BR is $2,295/mo. 2 bed 1 bath", 2, 1290),
])
def test_unit_price_layouts(text, beds, price):
    r = read(text)
    assert r["beds"] == beds
    assert r["price"] == price


@pytest.mark.parametrize("text", [
    "Sunny flat, $1,350 -> now $1,290?? sorry, that is the 2BR. 3BR is $2,295/mo",
    "Oops, $1,100 is the 1BR. The 2BR is $1,400. Call us.",
    "$1,290 is for the 2BR, sorry. $2,295 for the 3BR.",
])
def test_unit_price_unknown_never_takes_the_lower(text):
    r = read(text)
    assert "price" not in r
    assert "rent is left empty" in notes(r)


# ---- 7. beds with a trailing dot
@pytest.mark.parametrize("text,beds,baths", [
    ("Lincoln Heights 1x1. No: rent is $1,440.", 1, 1),
    ("Lincoln Heights 2x2, $1,440", 2, 2),
    ("Lincoln 2x1. W/D", 2, 1),
])
def test_x_layout_with_trailing_punctuation(text, beds, baths):
    r = read(text)
    assert r["beds"] == beds
    assert r["baths"] == baths


def test_x_ellipsis_correction_still_reads_later_layout():
    r = read("Bucktown 3BR $3,200/mo 1x1... actually 3 beds 2 baths.")
    assert r["beds"] == 3 and r["baths"] == 2
