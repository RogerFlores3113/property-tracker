"""Cycle 28 group 3: key and parking deposits are never the security deposit, "half of one month's rent", a surety option is not a missing
monthly cost, "3/2" in a title, "approval required for dogs", and an own garage with no price."""
import os

import pytest

from prophelper.parsers import parse_listing

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "panel")


def fixture(name):
    with open(os.path.join(FIX, name + ".txt"), encoding="utf-8") as f:
        return parse_listing(f.read(), "")


def notes(r):
    return r.get("found_in_listing", "") or ""


def read(text, base="2 bed 1 bath apartment. Rent $1,600 per month. "):
    return parse_listing(base + text, "")


# ---- item 1: key, parking and pet deposits ----
def test_family_l32_key_deposit_is_move_in_fee():
    r = fixture("r27-family-l32")
    assert r["deposit"] == 2290 and r["move_in_fees"] == 150 and r["pet_deposit"] == 400
    assert "key deposit" in notes(r)


def test_family_l34_key_and_parking_deposits():
    r = fixture("r27-family-l34")
    assert r["deposit"] == 2000 and r["move_in_fees"] == 300
    assert "parking deposit" in notes(r) and "not counted anywhere" not in notes(r)


def test_nontech_l34_key_deposit():
    r = fixture("r27-nontech-l34")
    assert r["deposit"] == 500 and r["move_in_fees"] == 200  # admin $150 + key $50


def test_uiuc_l11_months_deposit_and_key():
    r = fixture("r27-uiuc-l11")
    assert r["deposit"] == 2182.5 and r["move_in_fees"] == 125  # admin $75 + key $50


def test_roommates_l4_half_month_key_parking():
    r = fixture("r27-roommates-l4")
    assert r["deposit"] == 1600 and r["move_in_fees"] == 250 and r["pet_deposit"] == 300
    assert "$200 parking deposit" in notes(r) and "$50 key deposit" in notes(r)


@pytest.mark.parametrize("text,dep,mif", [
    ("Security deposit $1,200. Key deposit $40.", 1200, 40),
    ("Deposit: $1,200 (key deposit $40 refundable)", 1200, 40),
    ("Key deposit $40\nSecurity deposit $1,200", 1200, 40),
    ("Security deposit $1,200 | Parking deposit $75 | Key deposit $25", 1200, 100),
    ("$1,200 security deposit, $40 key deposit", 1200, 40),
])
def test_key_and_parking_deposit_never_summed(text, dep, mif):
    r = read(text)
    assert r["deposit"] == dep and r["move_in_fees"] == mif


def test_key_deposit_alone_is_not_the_security_deposit():
    r = read("Key deposit $40.")
    assert r.get("deposit") in (None, 0, 0.0) and r["move_in_fees"] == 40


def test_pet_deposit_stays_pet_deposit():
    r = read("Security deposit $1,200. Pet deposit $300. Key deposit $40. Dogs ok.")
    assert r["deposit"] == 1200 and r["pet_deposit"] == 300 and r["move_in_fees"] == 40


# ---- item 2: half of one month's rent ----
@pytest.mark.parametrize("text", [
    "Security deposit is half of one month's rent.",
    "Security deposit: half of the monthly rent",
    "Deposit equals 50% of one month's rent",
    "The deposit is one-half of one month's rent.",
    "Security deposit is half a month's rent.",
])
def test_half_month_deposit(text):
    assert read(text)["deposit"] == 800


def test_half_month_pet_deposit_is_not_security():
    r = read("Pet deposit is half of one month's rent. Security deposit $900.")
    assert r["deposit"] == 900


# ---- item 3: surety option ----
@pytest.mark.parametrize("text", [
    "Deposit $1,000 or $49/mo surety.",
    "Surety bond option: $49/mo in lieu of deposit.\nDeposit $1,000.",
    "Deposit $1,000 (or $49/mo deposit alternative)",
    "Security deposit $1,000. $49/month surety bond instead of the deposit.",
])
def test_surety_option_noted_not_counted(text):
    r = read(text)
    assert r["deposit"] == 1000
    assert r.get("other_monthly_fees") in (None, 0, 0.0)
    n = notes(r)
    assert "surety bond" in n and "$49" in n and "not a missing monthly cost" in n and "not a cost on top of the rent" in n
    assert "monthly fee and it is not counted anywhere" not in n


@pytest.mark.parametrize("text", [
    "Security deposit $1,000, or choose a surety bond at $49 per month instead.",
    "Deposit: $1,000 or surety bond ($49/month).",
])
def test_surety_option_guard_wording(text):
    r = read(text)
    assert r["deposit"] == 1000 and r.get("other_monthly_fees") in (None, 0, 0.0)
    n = notes(r)
    assert "alternative to the deposit" in n and "$49" in n and "not counted anywhere" not in n


def test_roommates_l14_surety():
    r = fixture("r27-roommates-l14")
    assert r["deposit"] == 1000 and "$49" in notes(r) and "surety" in notes(r)
    assert r["other_monthly_fees"] == 145


# ---- item 4: 3/2 ----
@pytest.mark.parametrize("text,beds,baths", [
    ("SINGLE FAMILY HOME FOR LEASE 3/2 at 55 Birch Ln, Belmont CA. Rent: $2,395.", 3, 2),
    ("FOR RENT: 3/2.5 house, 12 Oak St, $3,000", 3, 2.5),
    ("Charming 3BR/2BA at 12 Oak St. $2,100", 3, 2),
    ("Home for lease 2/1 at 9 Pine Rd. Rent $1,900", 2, 1),
    ("Nice unit 4/3 with garage, $3,500", 4, 3),
])
def test_slash_beds_baths(text, beds, baths):
    r = parse_listing(text, "")
    assert r["beds"] == beds and r["baths"] == baths


@pytest.mark.parametrize("text", [
    "Rent $2,000. Open house 3/2. Studio apartment.",
    "Rent $2,000. 1/2 mile to campus.",
    "Available 3/2. Rent $1,800.",
    "Lease ends 11/2. Rent $1,900/mo. 2 bed.",
    "Pets 1/2 off the first month. Rent $1,800.",
])
def test_slash_dates_and_fractions_not_beds(text):
    r = parse_listing(text, "")
    assert r.get("beds") in (None, 0, 2) and r.get("baths") is None


def test_family_l34_beds_baths():
    r = fixture("r27-family-l34")
    assert r["beds"] == 3 and r["baths"] == 2


# ---- item 5: dogs need approval ----
@pytest.mark.parametrize("text", [
    "Dogs: 2 max, 40 lb limit, $300 pet fee. Cats ok. Approval required for dogs.",
    "Dogs OK, approval needed. Cats OK.",
    "Pet policy: dogs and cats welcome. Dogs must be approved by management.",
])
def test_dogs_need_approval_note(text):
    r = read(text)
    assert r["pets"] == "both"
    assert "Dogs need approval" in notes(r)


def test_dogs_approval_fields_kept():
    r = read("Dogs: 2 max, 40 lb limit, $300 pet fee. Cats ok. Approval required for dogs.")
    assert r["pet_weight_limit"] == 40 and r["pet_fee"] == 300


def test_no_approval_note_when_not_needed():
    r = read("Dogs and cats ok. No approval needed. Credit approval required.")
    assert "need approval" not in notes(r)


# ---- item 6: own garage with no price ----
@pytest.mark.parametrize("text", [
    "Parking: 1 car garage, driveway free.",
    "Parking: attached garage, free driveway parking.",
    "Parking: 2-car garage\n- driveway free",
])
def test_own_garage_no_price(text):
    r = read(text, "3 bed 2 bath house. Rent $2,300. ")
    assert r["parking"] == "garage" and r.get("parking_cost") is None
    assert "no price for the garage" in notes(r) and "driveway" in notes(r)


def test_r26_family_l29_garage():
    r = fixture("r26-family-l29")
    assert r["parking"] == "garage" and r.get("parking_cost") is None


@pytest.mark.parametrize("text", [
    "Parking: driveway free, garage $120/mo optional.",
    "Parking: free driveway, covered carport.",
])
def test_optional_garage_keeps_free_spot(text):
    r = read(text, "3 bed 2 bath house. Rent $2,300. ")
    assert r["parking"] == "lot" and r["parking_cost"] == 0


@pytest.mark.parametrize("text", [
    "Garage and driveway both free.",
    "Parking: garage and driveway free.",
    "Garage and driveway free of charge, both.",
])
def test_garage_stated_free_stays_free(text):
    r = read(text, "3 bed 2 bath house. Rent $2,300. ")
    assert r["parking_cost"] == 0


def test_family_l36_garage_and_driveway_free():
    r = fixture("r27-family-l36")
    assert r["parking_cost"] == 0


@pytest.mark.parametrize("text", [
    "Dog friendly (60 lb limit can be waived with approval).",
    "Dogs ok. Weight limit can be waived with approval.",
    "Cats and dogs welcome. Breed restrictions may be lifted with approval.",
])
def test_approval_that_lifts_a_limit_is_not_pet_approval(text):
    r = read(text)
    assert "need approval" not in notes(r)
