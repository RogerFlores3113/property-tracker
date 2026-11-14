"""Cycle 15, group G3: pets, parking, yard and buyer money reader. Each phrasing pins the exact fields."""
import pytest

from prophelper.parsers import parse_listing


def read(text, buying=False):
    return parse_listing(("Home for sale $350,000. " if buying else "Rent $2000. ") + text, buying=buying)


def notes(r):
    return r.get("found_in_listing") or ""


# ---- 1. pet policy
def test_one_cat_or_small_dog_is_cats_and_dogs():
    r = read("We allow one cat or small dog")
    assert r["pets"] == "both"


def test_cat_or_dog_still_reads_no():
    assert "pets" not in read("No cat or dog")
    assert read("Pets: no cats or dogs allowed").get("pets") != "dogs"


def test_small_pets_considered_stays_unknown_with_note():
    r = read("Small pets considered")
    assert "pets" not in r
    assert "ask the landlord" in notes(r)


# ---- 2. part-refundable pet deposits
@pytest.mark.parametrize("text,fee,dep", [
    ("Pet deposit $400 ($250 refundable)", 150, 250),
    ("Cats allowed. $250 deposit of which $150 is refundable", 100, 150),
    ("Pet deposit $400, $200 refundable", 200, 200),
    ("Pet deposit $500, $300 refundable. Dogs: small pets considered.", 200, 300),
    ("Cats and dogs welcome: $350 deposit ($150 refundable), $35/mo pet rent per pet, max 2.", 200, 150),
])
def test_part_refundable_pet_deposit_is_split(text, fee, dep):
    r = read(text)
    assert r["pet_fee"] == fee and r["pet_deposit"] == dep
    assert "not counted" not in notes(r) and "monthly fee" not in notes(r)
    assert "pet_rent" not in r or r["pet_rent"] == 35


def test_security_deposit_with_refundable_part_is_not_a_pet_split():
    r = read("Deposit $1500 ($1000 refundable)")
    assert "pet_fee" not in r and "pet_deposit" not in r


# ---- 3. pet rent per pet
def test_pet_rent_per_pet_gets_a_note():
    r = read("$35/mo pet rent per pet, max 2")
    assert r["pet_rent"] == 35 and r["pet_count_limit"] == 2
    assert "for each pet" in notes(r)


# ---- 4. parking
def test_offstreet_parking_included_is_zero():
    r = read("Off-street parking for 2 cars included")
    assert r["parking"] == "lot" and r["parking_cost"] == 0


def test_included_parking_with_optional_garage():
    r = read("Parking included in rent. Free parking. Garage $90 optional")
    assert r["parking"] == "lot" and r["parking_cost"] == 0
    assert "garage is available for $90" in notes(r)
    assert "could not tell" not in notes(r)


def test_parking_zero_included():
    r = read("Parking $0 included")
    assert r["parking_cost"] == 0 and r["parking"] == "lot"
    assert "could not tell" not in notes(r)


def test_parking_not_on_street_but_driveway():
    r = read("Parking not available on street, driveway fits 2 cars")
    assert r["parking"] == "lot" and "parking_cost" not in r
    assert "no parking" not in notes(r)


def test_plain_parking_not_available_is_still_none():
    assert read("Parking not available")["parking"] == "none"


def test_parking_and_water_included_is_not_free_parking():
    assert "parking_cost" not in read("Lot parking, water included")


@pytest.mark.parametrize("text", ["Andersonville required parking $140 per month per vehicle", "Parking required, $140 per vehicle per month"])
def test_required_parking_per_vehicle_counted_once_with_note(text):
    r = read(text)
    assert r["parking_cost"] == 140
    assert "for each vehicle" in notes(r) and "counted once" in notes(r)
    assert "$140" not in notes(r)


# ---- 5. yard
def test_fence_around_backyard_is_fenced():
    assert read("Fence around entire backyard")["fenced_yard"] == 1


def test_no_yard_but_shared_courtyard():
    r = read("No yard but shared courtyard")
    assert r["fenced_yard"] == 0
    assert "shared courtyard" in notes(r)


def test_no_yard_work_is_not_no_yard():
    assert "fenced_yard" not in read("No yard work needed")


# ---- 6. buyer money
def test_buyer_pays_one_time_assessment():
    r = read("Condo. Buyer to pay one-time assessment of $1,800 at closing", buying=True)
    assert r["special_assessment"] == 1800 and r["special_assessment_payer"] == "buyer"
    assert "$1,800" not in notes(r)


def test_buyer_will_owe_special_assessment_no_parking_note():
    r = read("At closing the buyer will owe a $2,000 special assessment for the parking deck repair", buying=True)
    assert r["special_assessment"] == 2000 and r["special_assessment_payer"] == "buyer"
    assert "parking" not in notes(r).lower()
    assert "not counted" not in notes(r)


@pytest.mark.parametrize("text", ["Property taxes roughly $4,100 a year", "Property taxes about $4,100 a year.", "Taxes typically $4,100 annually"])
def test_property_tax_estimate(text):
    r = read(text, buying=True)
    assert r["property_tax"] == 4100
    assert "not counted" not in notes(r)


def test_monthly_tax_still_yearly():
    assert read("Property taxes are about $342 a month", buying=True)["property_tax"] == 4104


def test_hoa_billed_quarterly_at():
    r = read("Condo. HOA fee is billed quarterly at $900", buying=True)
    assert r["hoa"] == 300
    assert "not counted" not in notes(r)
