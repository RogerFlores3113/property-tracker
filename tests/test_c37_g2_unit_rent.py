"""Cycle 37 G2 (rule mm): a price tied to a unit type is the rent only when it matches the listing's own size."""
import os

import pytest

from prophelper.parsers import parse_listing

P = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel") + "/"


def read(t, **kw):
    return parse_listing(t, "", **kw)


def fixture(n):
    return open(P + n, encoding="utf-8").read()


@pytest.mark.parametrize("t", [
    "1 bed 1 bath\nRent $2 300 dollars a month for the 2BR; 1BR starts at $1,540 a month.",
    "1 bed 1 bath. 1BR starts at $1,540 a month. Rent $2,300 a month for the 2BR.",
    "1 bedroom apartment\nThe 2 bedroom rents for $2,300 a month and the 1 bedroom starts at $1,540.",
    "1BR condo\n1BR from $1,540/mo, 2BR from $2,300/mo",
    "Studio-ish 1 bed\nRent $2,300 a month for the two bedroom, $1,540 a month for the one bedroom.",
    "1 bed 1 bath\n2BR - $2,300 | 1BR - $1,540",
    "1 bed 1 bath\n$1,540 for the 1BR, $2,300 for the 2BR",
    "1 bed 1 bath\nRent $2,300 dollars a month for the 2BR\n1BR starts at $1,540 a month.",
])
def test_the_one_bed_price_is_the_rent_and_the_two_bed_price_is_named(t):
    r = read(t)
    assert r["price"] == 1540
    assert "$2,300" in r["found_in_listing"] and "2 bedroom" in r["found_in_listing"]


def test_two_bed_listing_keeps_its_own_price():
    r = read("2 bed 2 bath\nRent $2,300 a month for the 2BR; 1BR starts at $1,540 a month.")
    assert r["price"] == 2300 and "$1,540" in r["found_in_listing"]


def test_whole_place_rent_is_untouched():
    assert read("2 bed 1 bath. Rent $2,300 a month. Studio-style units are not available.")["price"] == 2300
    assert read("2 bed 1 bath. Rent $2,300 a month.")["price"] == 2300


def test_uiuc_l7_whole_listing():
    r = read(fixture("r36-uiuc-l7.txt"))
    assert r["price"] == 1540 and r["beds"] == 1 and r["deposit"] == 1000
    assert "$2,300" in r["found_in_listing"]


def test_r35_uiuc_l5_whole_listing():
    r = read(fixture("r35-uiuc-l5.txt"))
    assert r["price"] == 1595 and r["beds"] == 1
    n = r["found_in_listing"]
    assert "$3,275" in n and "1550" in n


# ------------------------------------------------------------------ item 2 (rule nn): spoken corrections
@pytest.mark.parametrize("t", [
    "Rent $2,300 a month?? Just kidding, it is $1,380.",
    "Rent $2 300 dollars a month?? Just kidding, it is $1,380.",
    "Rent $2,300/mo. Just kidding, $1,380.",
    "Rent is $2,300. Actually, it's $1,380.",
    "Rent $2,300. Sorry, typo: $1,380.",
    "Rent $2,300 (I meant $1,380).",
    "Rent $2,300. No wait, $1,380 a month.",
    "2 bed. $2,300 per month... jk, $1,380 per month.",
    "Cozy 2 bed. Rent: $2,300 a month. Oops I meant $1,380 a month.",
])
def test_spoken_correction_later_rent_wins_with_a_note(t):
    r = read(t)
    assert r["price"] == 1380
    n = r["found_in_listing"]
    assert "corrects" in n and "$1,380" in n


def test_nontech_l3_whole_listing():
    r = read(fixture("r36-nontech-l3.txt"))
    assert r["price"] == 1380 and r["deposit"] == 1380 and r["beds"] == 3
    assert "corrects itself" in r["found_in_listing"]


@pytest.mark.parametrize("t,field,val", [
    ("Rent $1,500 a month. Deposit $1,500. Actually $1,200.", "price", 1500),
    ("Rent $1,500 a month. Pet fee $350, sorry $300.", "price", 1500),
])
def test_a_correction_of_another_fact_never_moves_the_rent(t, field, val):
    assert read(t)[field] == val


# ------------------------------------------------------------------ item 3: "Asking 2,400 monthly" and a roommate share
@pytest.mark.parametrize("t", [
    "Asking 2,400 monthly. Roommate share: $800 per room if renting by the room.",
    "Asking 2,400 monthly\nRoommate share: $800 per room if renting by the room.",
    "Roommate share: $800 per room if renting by the room.\nAsking 2,400 monthly.",
    "Asking 2400 per month. Rooms for rent at $800 each.",
    "Asking 2,400/mo (or $800 per room)",
    "Rooms $800 each. Whole house asking 2,400 monthly.",
    "Rent 2,400 monthly; room share $800 per room",
])
def test_whole_place_is_the_rent_and_the_room_share_is_not(t):
    assert read(t)["price"] == 2400


def test_a_room_share_alone_is_never_the_rent():
    assert read("Roommate share: $800 per room if renting by the room.").get("price") is None
    assert read("Rent $1,475 per room. 3 bed 2 bath").get("price") is None


def test_family_l7_whole_listing():
    r = read(fixture("r36-family-l7.txt"))
    assert r["price"] == 2400 and r["deposit"] == 1500 and r["beds"] == 4
    assert "$800 per room" in r["found_in_listing"]


# ------------------------------------------------------------------ item 4: Spanish per-room figure with a whole-place total
@pytest.mark.parametrize("t", [
    "Renta 1,475 al mes por habitación | 3 hab 2 baños\nTotal $3,200. No incluye luz ni gas.",
    "3 hab 2 baños. Renta 1,475 al mes por habitación. Total $3,200.",
    "3 hab. Total $3,200. Renta 1,475 al mes por habitación.",
    "Renta $1,475 por habitación al mes. Renta total $3,200 al mes.",
    "Alquiler: 1,475 por cuarto. Total: $3,200/mes",
    "Rent $1,475 per room per month. Total $3,200. 3 bed 2 bath",
])
def test_total_is_the_rent_and_the_per_room_figure_is_a_note(t):
    r = read(t)
    assert r["price"] == 3200
    assert "$1,475" in r["found_in_listing"] and "not counted anywhere" not in r["found_in_listing"]


def test_spanish_per_room_alone_leaves_rent_empty_with_a_note():
    r = read("Renta 1,475 al mes por habitación | 3 hab 2 baños")
    assert r.get("price") is None and "1,475" in r["found_in_listing"]


def test_roommates_l8_whole_listing():
    r = read(fixture("r36-roommates-l8.txt"))
    assert r["price"] == 3200 and r["deposit"] == 1500 and r["beds"] == 3
    assert "$1,475 per room" in r["found_in_listing"] and "Total $3,200" not in r["found_in_listing"]


# ------------------------------------------------------------------ item 5: an MLS id never blocks the rent
@pytest.mark.parametrize("t", [
    "Renta 1,475 al mes. MLS# 3F9A-77B2C.",
    "MLS# 3F9A-77B2C. Renta 1,475 al mes.",
    "Renta 1,475 al mes. MLS 3F9A-77B2C",
    "Renta 1,475 al mes. MLS# 1234-5678",
    "Renta 1,475 al mes\nMLS #77B2C",
    "Rent $1,475/mo. MLS# 3F9A-77B2C.",
])
def test_an_mls_id_never_blocks_the_rent(t):
    assert read(t)["price"] == 1475


def test_privacy_l4_and_l8():
    for n in ("r36-privacy-l4.txt", "r36-privacy-l8.txt"):
        r = read(fixture(n))
        assert r["price"] == 1475 and r["deposit"] == 1475


def test_a_real_sale_with_an_mls_id_is_still_a_sale():
    assert read("MLS# 4455667 3 bed 2 bath home for sale $350,000", buying=True)["price"] == 350000


# ------------------------------------------------------------------ item 6 (rule pp): "first, last and security ($1395 each)"
@pytest.mark.parametrize("t", [
    "Rent: $1395 per month. First, last and security ($1395 each) due at signing.",
    "Rent: $1395 per month. First, last and security deposit ($1,395 each) due at move-in.",
    "Rent $1,395/mo. Move-in: first month, last month and security deposit, $1,395 each.",
    "Rent $1,395/mo\nFirst, last & security: $1,395 each",
    "Rent $1,395/mo. Due at signing: first, last, security - $1395 each.",
    "Rent $1,395/mo. First month's rent, last month's rent and a security deposit of $1,395 each are due at signing.",
    "Rent $1,395/mo. Move in costs: first + last + security at $1,395 each.",
])
def test_first_last_and_security_each_is_a_deposit_and_two_months(t):
    r = read(t)
    assert r["price"] == 1395 and r["deposit"] == 1395 and r["months_up_front"] == 2


def test_first_and_security_each_is_a_deposit():
    assert read("Rent $1,395/mo. First and security ($1,395 each) due at signing.")["deposit"] == 1395


def test_first_and_last_each_alone_is_no_deposit():
    r = read("Rent $1,395/mo. First and last month's rent ($1,395 each) due at signing.")
    assert r.get("deposit") is None and r["months_up_front"] == 2


def test_security_deposit_stated_apart_is_kept():
    r = read("Rent $1,395/mo. First and last month's rent due. Security deposit $500.")
    assert r["deposit"] == 500 and r["months_up_front"] == 2


def test_nontech_l7_whole_listing():
    r = read(fixture("r36-nontech-l7.txt"))
    assert r["price"] == 1395 and r["deposit"] == 1395 and r["months_up_front"] == 2
    assert r["pet_deposit"] == 350 and r["pet_rent"] == 40


# ------------------------------------------------------------------ item 7: two deposits that disagree
@pytest.mark.parametrize("t", [
    "Ravenswood Manor 3BR 2BA - $3,150 - Dep $900\n$1500 dep. Please email to schedule showing.",
    "Dep $900. 3 bed 2 bath, rent $3,150/mo. $1500 dep.",
    "Rent $3,150/mo. Security deposit $900. Deposit is $1,500.",
    "Rent $3,150/mo. Dep $900\nOther line: $1500 dep",
    "Rent $3,150/mo. $1500 dep. Dep $900",
    "Rent $3,150/mo. Deposit: $900. $1500 dep.",
])
def test_two_different_deposits_stay_unknown_and_both_are_named(t):
    r = read(t)
    assert r["price"] == 3150 and r.get("deposit") is None
    n = r["found_in_listing"]
    assert "$900" in n and "$1,500" in n and "two different deposits" in n


@pytest.mark.parametrize("t,dep", [
    ("Rent $3,150/mo. Deposit $900. Deposit $900 again.", 900),
    ("Rent $3,150/mo. Dep $900. Pet dep $500.", 900),
    ("Rent $3,150/mo. Security deposit $900. Key deposit $50.", 900),
])
def test_a_repeat_or_a_named_deposit_is_no_conflict(t, dep):
    assert read(t)["deposit"] == dep


def test_a_hedged_deposit_is_not_called_a_conflict():
    n = read("Rent $3,150/mo. Security deposit $1,000, or $500 with approved credit.").get("found_in_listing", "")
    assert "two different deposits" not in n


def test_roommates_l13_whole_listing():
    r = read(fixture("r36-roommates-l13.txt"))
    assert r["price"] == 3150 and r.get("deposit") is None and r["pet_rent"] == 40
    n = r["found_in_listing"]
    assert "$900" in n and "$1,500" in n and "two different deposits" in n
