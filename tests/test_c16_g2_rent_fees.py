"""Cycle 16, group G2: a street number is never the rent, two rents, mandatory internet and amenity fees, flat fees, an optional
second vehicle, and a buyer's transfer fee. Each phrasing pins the exact fields."""
import pytest

from prophelper import money
from prophelper.parsers import parse_listing

RENT = "2 bed apartment. Rent $1,400/mo. "


def P(t, rent=True):
    return parse_listing((RENT if rent else "") + t)


def note(r):
    return r.get("found_in_listing") or ""


# ---- 1. street numbers are not rents
@pytest.mark.parametrize("street", ["St", "Ave", "Rd", "Dr", "Blvd", "Ln", "Ct", "Way", "Pl"])
@pytest.mark.parametrize("lead", ["HOUSE FOR RENT. ", "For rent: ", "Rent. ", ""])
def test_dollar_title_beats_street_number(street, lead):
    r = parse_listing(f"2br/1ba duplex - $1,350 (German Village)\n{lead}612 Mohawk {street} Columbus OH 43206")
    assert r["price"] == 1350


@pytest.mark.parametrize("street", ["St", "Ave", "Rd", "Dr", "Blvd", "Ln", "Ct", "Way", "Pl"])
@pytest.mark.parametrize("lead", ["Rent. ", "For rent: ", "FOR RENT 4120 ", ""])
def test_street_number_with_no_price_is_not_a_rent(street, lead):
    r = parse_listing(f"{lead}4120 Indianola {street}, Call for price")
    assert "price" not in r
    assert "gives no price" in note(r) and "Call for price" in note(r)


def test_bare_rent_with_period_still_read():
    assert parse_listing("Rent 1,299 a month. 612 Mohawk St")["price"] == 1299
    assert parse_listing("Charming house 1,299/mo, 4120 Indianola Ave")["price"] == 1299
    assert parse_listing("1,299 per month at 612 Mohawk St")["price"] == 1299


def test_dollar_rent_after_address_still_read():
    assert parse_listing("For rent: 612 Mohawk St Columbus OH. Rent $1,350")["price"] == 1350


# ---- 2. two rents
@pytest.mark.parametrize("t,unit", [
    ("2 bed apartment. 1,299 a month per bedroom... total rent 2,975", 2975),
    ("2 bed apartment. 1,299 a month per room? No: unit rent is 3,195", 3195),
    ("2 bed apartment. $1,299/mo per bedroom. Total rent $2,975", 2975),
])
def test_two_rents_save_unit_rent_with_note_naming_both(t, unit):
    r = parse_listing(t)
    assert r["price"] == unit
    n = note(r)
    assert "1,299" in n and f"{unit:,}" in n and "two rents" in n


def test_single_per_room_rent_is_unchanged():
    assert parse_listing("Room for rent. 1,299 a month per room")["price"] == 1299


# ---- 3. mandatory internet and amenity fees
@pytest.mark.parametrize("t,fee", [
    ("Internet: Spectrum required, $55/mo mandatory.", 55),
    ("Internet required, $60/mo", 60),
    ("Internet: Wide Open Net $55/mo mandatory", 55),
    ("Wifi is mandatory at $45 per month", 45),
    ("Monthly amenity fee $25", 25),
    ("Community pool, monthly amenity fee $25", 25),
    ("Monthly amenities fee: $30", 30),
])
def test_internet_and_amenity_fees_are_counted(t, fee):
    r = P(t)
    assert r["other_monthly_fees"] == fee
    assert "not counted anywhere" not in note(r)
    assert money.rent_cost(r)["total"] == pytest.approx(1400 + fee, abs=0.01)


def test_optional_internet_is_not_a_fee():
    r = P("Internet available from Spectrum, $55/mo optional.")
    assert "other_monthly_fees" not in r


def test_internet_not_counted_twice_with_utilities():
    r = P("Internet required, $60/mo. Tenant pays electric and gas.")
    assert r["other_monthly_fees"] == 60
    assert r.get("utilities_estimate") != 60


# ---- 4. flat fees
@pytest.mark.parametrize("t", [
    "Flat $75/mo fee for amenities",
    "Flat $75/mo fee covers trash and amenity",
    "Flat $75/mo fee covers trash, pest and valet",
    "Flat $75 per month fee covers amenity and trash",
])
def test_flat_fee_counts_once(t):
    r = P(t)
    assert r["other_monthly_fees"] == 75
    assert "utilities_estimate" not in r
    assert "not counted anywhere" not in note(r)
    assert money.rent_cost(r)["total"] == pytest.approx(1475, abs=0.01)


# ---- 5. optional second vehicle
@pytest.mark.parametrize("t", ["second vehicle $40/mo", "Second car $40 per month", "additional vehicle $40/mo"])
def test_second_vehicle_is_optional_not_counted(t):
    r = P(t)
    assert "other_monthly_fees" not in r and "parking_cost" not in r
    assert "optional" in note(r) and "not counted in the monthly cost" in note(r)
    assert "Check what it is for" not in note(r)


# ---- 6. buyer transfer fee
@pytest.mark.parametrize("t", [
    "Buyer pays one-time $3,200 transfer fee at closing",
    "Buyer pays a $3,200 transfer fee at closing",
])
def test_buyer_transfer_fee_counts_in_closing_costs(t):
    r = parse_listing("3 bed house for sale $450,000. " + t, buying=True)
    assert r["closing_costs"] == 3200
    assert "counted in the closing costs" in note(r)


def test_buyer_transfer_fee_does_not_double_closing_costs():
    r = parse_listing("3 bed house for sale $450,000. Estimated closing costs $9,800. Buyer pays one-time $3,200 transfer fee at closing", buying=True)
    assert r["closing_costs"] == 9800
    assert "not added again" in note(r)


def test_seller_transfer_fee_is_not_closing_costs():
    r = parse_listing("3 bed house for sale $450,000. Transfer fee $3,200 paid by seller at closing", buying=True)
    assert "closing_costs" not in r
