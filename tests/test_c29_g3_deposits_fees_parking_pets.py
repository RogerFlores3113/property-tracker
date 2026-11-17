"""Cycle 29 group 3: repeated identical fee lines count once, a surety bond offered instead of the deposit gets a plain note, "half one month's rent",
key fob and parking pass deposits, unpriced garages saved as a garage with the cost unknown, and "approval required for dogs" next to "pets ok"."""
import os

import pytest

from prophelper.parsers import parse_listing

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "panel")


def fixture(name):
    with open(os.path.join(FIX, name + ".txt"), encoding="utf-8") as f:
        return parse_listing(f.read(), "")


def notes(r):
    return r.get("found_in_listing", "") or ""


def read(text, base="2 bed 1 bath apartment. Rent $1,600 per month.\n"):
    return parse_listing(base + text, "")


# ---- item 1: an identical fee line counts once ----
def test_privacy_q7_thirty_pest_lines_count_once():
    r = fixture("r28-privacy-l-q7")
    assert r["other_monthly_fees"] == 5
    assert notes(r).count("Pest") == 1 and "30 times" in notes(r)


@pytest.mark.parametrize("text,total", [
    ("Pest control $5/month\n" * 4, 5),
    ("* Valet trash $20/mo\n" * 3, 20),
    ("Monthly fees: pest $5, pest $5, pest $5, package locker $4.", 9),
    ("Pest $5/month and pest $5/month and pest $5/month.", 5),
    ("Amenity fee $25/month\n" * 3, 25),
])
def test_identical_fee_lines_count_once(text, total):
    r = read(text)
    assert r["other_monthly_fees"] == total
    assert "repeats that same line" in notes(r) and notes(r).count("repeats that same line") == 1


def test_different_fees_with_the_same_amount_both_count():
    r = read("Pest $5/month, trash valet $5/month, package locker $5/month.")
    assert r["other_monthly_fees"] == 15
    assert "repeats that same line" not in notes(r)


def test_single_fee_has_no_repeat_note():
    r = read("Pest $5/month.")
    assert r["other_monthly_fees"] == 5 and "repeats" not in notes(r)


# ---- item 2: surety bond instead of the deposit ----
@pytest.mark.parametrize("name,dep", [("r28-family-l42", 2350), ("r28-uiuc-l5", 1525), ("r28-nontech-l40", 400)])
def test_surety_instead_of_deposit_corpus(name, dep):
    r = fixture(name)
    assert r["deposit"] == dep
    assert "surety bond instead of the deposit" in notes(r)


@pytest.mark.parametrize("text", [
    "Security deposit $1,000. Surety bond in lieu of deposit.",
    "Security deposit $1,000. Surety bond option available instead of deposit.",
    "Security deposit $1,000 (choose a surety bond instead of the deposit)",
    "Security deposit: $1,000\nDeposit waiver available",
])
def test_surety_plain_note(text):
    r = read(text)
    assert r["deposit"] == 1000
    assert "surety bond instead of the deposit" in notes(r)
    assert not r.get("other_monthly_fees") and not r.get("move_in_fees")


def test_no_surety_note_when_none_offered():
    r = read("Security deposit $1,000. No surety bond.")
    assert "surety" not in notes(r).lower()


def test_priced_surety_keeps_its_own_note_once():
    r = read("Security deposit $1,000. Surety bond option $39/mo.")
    assert r["deposit"] == 1000 and notes(r).count("surety bond") == 1


# ---- item 3: half of one month's rent ----
def test_nontech_l44_half_month_deposit():
    r = fixture("r28-nontech-l44")
    assert r["deposit"] == 625
    assert "$625" in notes(r) and "the listing gives no amount" not in notes(r)


@pytest.mark.parametrize("text,dep", [
    ("First and last month plus deposit of half one month's rent.", 800),
    ("Security deposit: half a month's rent.", 800),
    ("Security deposit of half of one month's rent.", 800),
    ("Deposit half rent.", 800),
])
def test_half_rent_deposit_layouts(text, dep):
    r = read(text)
    assert r["deposit"] == dep


def test_nontech_l44_gas_note_does_not_say_gas_is_included():
    r = fixture("r28-nontech-l44")
    assert "gas is included" not in notes(r)


# ---- item 4: key fob and parking pass deposits ----
def test_family_key_fob_deposit_is_move_in_fee():
    r = read("Security deposit $1,500. Key fob deposit $40.")
    assert r["deposit"] == 1500 and r["move_in_fees"] == 40
    assert "key fob deposit" in notes(r) and "not the security deposit" in notes(r)


def test_nontech_l41_parking_pass_deposit():
    r = fixture("r28-nontech-l41")
    assert r["deposit"] == 1000 and r["move_in_fees"] == 125  # key $75 + parking pass $50
    assert "parking pass deposit" in notes(r) and "Check what it is for" not in notes(r)


@pytest.mark.parametrize("text,mif", [
    ("Deposit: $1,500 | Fob deposit $40 | Gate remote deposit $30", 70),
    ("Security deposit $1,500\nParking pass deposit $50 refundable", 50),
    ("Security deposit $1,500, access card deposit $25", 25),
    ("$1,500 security deposit, $40 key fob deposit", 40),
])
def test_fob_and_pass_deposit_layouts(text, mif):
    r = read(text)
    assert r["deposit"] == 1500 and r["move_in_fees"] == mif
    assert "not the security deposit" in notes(r)


# ---- item 5: unpriced garages ----
@pytest.mark.parametrize("name", ["r28-family-l32", "r28-family-l41", "r28-uiuc-l6", "r28-roommates-l5", "r28-roommates-l6"])
def test_unpriced_garage_is_garage_with_cost_unknown(name):
    r = fixture(name)
    assert r["parking"] == "garage" and r.get("parking_cost") is None
    assert "gives no price" in notes(r)
    assert notes(r).count("gives no price") == 1


@pytest.mark.parametrize("text", [
    "Two-car attached garage.",
    "Attached 2 car garage.",
    "Own garage included, price TBD.",
    "Garage: unpriced",
    "Own garage, ask for price.",
    "Garage parking available.",
])
def test_unpriced_garage_layouts(text):
    r = read(text)
    assert r["parking"] == "garage" and r.get("parking_cost") is None
    assert "gives no price" in notes(r)


@pytest.mark.parametrize("text", ["Attached garage included in rent.", "Garage included, no extra charge.", "Free garage parking."])
def test_garage_said_included_is_still_free(text):
    r = read(text)
    assert r["parking"] == "garage" and r["parking_cost"] == 0


def test_nontech_l40_detached_garage_ask_office_has_a_note():
    r = fixture("r28-nontech-l40")
    assert r["parking"] == "lot" and r["parking_cost"] == 0
    assert "garage is available" in notes(r)


def test_priced_garage_unchanged():
    r = read("Garage parking $120/month required.")
    assert r["parking"] == "garage" and r["parking_cost"] == 120


def test_garage_of_a_home_for_sale_gets_no_price_note():
    r = parse_listing("House for sale $450,000. 3 bed 2 bath. Attached 2-car garage.", "")
    assert "gives no price for it" not in notes(r)


# ---- item 6: approval required for dogs ----
@pytest.mark.parametrize("text", [
    "10 Oak St. Pets ok, 2 max, approval required for dogs.",
    "Pets welcome; approval required for dogs. $300 pet fee.",
    "Pets allowed (approval needed for dogs)",
    "- Pets welcome\n- Permission required for dogs",
])
def test_pets_ok_with_approval_for_dogs_is_unknown(text):
    r = read(text)
    assert not r.get("pets")
    assert "pets depend on approval" in notes(r) and "Pets is left empty" in notes(r)


def test_cats_named_keeps_pets_and_approval_note():
    r = read("Pets: Cats allowed. Approval required for dogs.")
    assert r["pets"] == "cats" and "Dogs need approval" in notes(r)


def test_explicit_dogs_and_cats_keep_both():
    r = read("Dogs and cats ok. Approval required for dogs.")
    assert r["pets"] == "both" and "Dogs need approval" in notes(r)
