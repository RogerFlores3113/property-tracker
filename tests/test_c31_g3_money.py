"""Cycle 31 group G3: last month's rent line, an animal-named fee in a move-in sentence, an unpriced parking kind, a pet screening fee per pet."""
import os

import pytest

from prophelper.parsers import parse_listing

HERE = os.path.join(os.path.dirname(__file__), "fixtures", "panel")


def P(text, **kw):
    return parse_listing(text, "", **kw)


def F(name, **kw):
    with open(os.path.join(HERE, name), encoding="utf-8") as fh:
        return P(fh.read(), **kw)


def notes(r):
    return r.get("found_in_listing") or ""


# ---- item 3: "Deposit $X, Last month's rent $X" never says "it costs $X in total to move in"
def test_l6_deposit_and_last_month_no_total_note():
    r = F("r30-family-l6.txt")
    assert r["deposit"] == 2450 and r["months_up_front"] == 2
    assert "in total to move in" not in notes(r)


@pytest.mark.parametrize("text", [
    "Rent $2,450. Deposit: $2,450. Last month's rent: $2,450 due at lease signing.",
    "Rent $2,450. Deposit $2,450, Last month's rent $2,450 due at signing.",
    "Rent $2,450\n- Security deposit: $2,450\n- Last month's rent: $2,450 due at move-in",
    "Rent $2,450 | Deposit $2,450 | Last month's rent $2,450 due at lease signing",
])
def test_last_month_line_is_not_a_total(text):
    r = P(text)
    assert r["price"] == 2450 and r["deposit"] == 2450 and r["months_up_front"] == 2
    assert "in total to move in" not in notes(r)


def test_a_real_total_still_gets_the_note():
    r = P("Rent $2,450. $4,900 due at signing.")
    assert "$4,900 in total to move in" in notes(r)
    r = P("Rent $1,300. Move-in cost $3,100 total.")
    assert "$3,100 in total to move in" in notes(r)


# ---- item 4: "non-refundable $200 cat fee" inside a "Move-in costs:" sentence is the pet fee
@pytest.mark.parametrize("text,pets,fee", [
    ("2 bed. Rent $1,395. Move-in costs: first month, security deposit equal to one month, and a non-refundable $200 cat fee. Cats ok.", "cats", 200),
    ("2 bed. Rent $1,395. Move-in costs: first month, deposit, and a $150 dog fee. Dogs welcome.", "dogs", 150),
    ("2 bed. Rent $1,395.\nMove-in: first month + deposit + one-time $250 cat fee\nCats ok", "cats", 250),
    ("2 bed. Rent $1,395. Due at move-in: deposit and a one time, non-refundable $175 dog fee. Dogs ok.", "dogs", 175),
])
def test_animal_fee_in_move_in_sentence_is_pet_fee(text, pets, fee):
    r = P(text)
    assert r["pets"] == pets and r["pet_fee"] == fee
    assert not r.get("pet_rent")
    assert "is a one-time cost, so it is not in the monthly cost" not in notes(r)


def test_l11_nontech_listing():
    r = F("r30-nontech-l11.txt")
    assert r["pets"] == "cats" and r["pet_fee"] == 200 and r["deposit"] == 1395
    assert r["other_monthly_fees"] == 30 and r["utilities_estimate"] == 210
    assert "$200 pet fee is not refundable" in notes(r)
    assert not r.get("move_in_fees")


def test_monthly_animal_fee_is_not_the_one_time_fee():
    r = P("Rent $1,395. Cats ok. $25 cat fee per month.")
    assert not r.get("pet_fee")


# ---- item 5: a priced parking item beside an unpriced one gets a note
@pytest.mark.parametrize("text", [
    "Parking pass $60/mo required. Garage: call for pricing.",
    "Garage: call for pricing. Parking pass $60/mo required.",
    "Parking pass $60/mo required\nGarage: ask for pricing",
    "Parking pass $60/mo required | Garage: inquire | Deposit $3,200",
])
def test_unpriced_garage_beside_priced_pass_is_noted(text):
    r = P("Rent $3,200. " + text)
    assert r["parking_cost"] == 60
    n = notes(r)
    assert "gives no price for the parking" in n and "Only the $60 a month item that has a price is counted" in n


def test_l14_and_l10_roommates():
    r = F("r30-roommates-l14.txt")
    assert r["parking_cost"] == 60 and "gives no price for the parking" in notes(r) and "Garage: call for pricing" in notes(r)
    r = F("r30-roommates-l10.txt")
    assert r["parking_cost"] == 200 and "Garage: inquire" in notes(r)


def test_priced_parking_alone_gets_no_such_note():
    r = P("Rent $3,200. Parking pass $60/mo required. Garage $150/mo.")
    assert "gives no price for the parking" not in notes(r)
    r = P("Rent $3,200. Garage parking $150/mo.")
    assert "gives no price for the parking" not in notes(r)


# ---- item 6: a pet screening fee per pet is counted for the search's pets
@pytest.mark.parametrize("text", [
    "Rent $2,000. Application $45 per adult. Pet screening fee $25 per pet. Dogs ok.",
    "Rent $2,000. Application $45 per adult. $25 pet screening fee per pet. Dogs ok.",
    "Rent $2,000.\n- Application: $45 per adult\n- Pet application fee: $25 per pet\n- Dogs ok",
    "Rent $2,000. Application $45 per adult (pet screening $25 per pet). Dogs ok.",
])
def test_pet_screening_per_pet_counted_for_one_dog(text):
    r = P(text, pet_kind="dog", pet_count=1)
    assert r["application_fee"] == 45 and r["move_in_fees"] == 25 and not r.get("pet_fee")
    assert "$25 is counted in the cash at move-in" in notes(r)
    r = P(text, pet_kind="both", pet_count=2)
    assert r["application_fee"] == 45 and r["move_in_fees"] == 50
    assert "$50 is counted in the cash at move-in" in notes(r)


def test_pet_screening_without_pets_in_search_stays_a_note():
    r = P("Rent $2,000. Application $45 per adult. Pet screening fee $25 per pet. Dogs ok.")
    assert not r.get("move_in_fees") and "$25 pet application for each pet" in notes(r)
    r = P("Rent $2,000. Application $45 per adult. Pet screening fee $25 per pet. Dogs ok.", pet_kind="dog", pet_count=0)
    assert not r.get("move_in_fees")


def test_flat_pet_application_counted_once():
    r = P("Rent $2,000. Pet application fee $40. Cats ok.", pet_kind="cat", pet_count=1)
    assert r["move_in_fees"] == 40 and not r.get("pet_fee")


def test_pet_screening_added_to_other_move_in_fees_once():
    r = P("Rent $2,000. Admin fee $100 one time. Pet screening fee $25 per pet. Dogs ok.", pet_kind="dog", pet_count=1)
    assert r["move_in_fees"] == 125


def test_l1_family_listing_counts_screening_for_one_dog():
    r = F("r30-family-l1.txt", pet_kind="dog", pet_count=1)
    assert r["application_fee"] == 45 and r["pet_fee"] == 350 and r["move_in_fees"] == 25
