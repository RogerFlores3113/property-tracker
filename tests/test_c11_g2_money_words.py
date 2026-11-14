"""Cycle 11 G2: rent, move-in money and utilities wording. Each reviewer phrasing pins the exact fields."""
import pytest

from prophelper.parsers import parse_listing

BASE = "2 bed apartment. "


def notes(r):
    return r.get("found_in_listing", "")


# 1. rent ranges
@pytest.mark.parametrize("text,lo,hi", [
    ("2BR apartment\nRent from $1,299 - $1,650 / mo", "1,299", "1,650"),
    ("2 bed $1,350 - $1,795 / mo", "1,350", "1,795"),
])
def test_rent_range_leaves_price_empty(text, lo, hi):
    r = parse_listing(text)
    assert "price" not in r
    assert r["beds"] == 2
    assert f"${lo} to ${hi}" in notes(r)


# 2. worded prices
def test_worded_rent():
    r = parse_listing("2 bed 1 bath. Rent: three thousand two hundred fifty dollars a month. Call us.")
    assert r["price"] == 3250 and r["beds"] == 2 and r["baths"] == 1
    assert "found_in_listing" not in r


def test_dollars_a_month_label():
    r = parse_listing("Charming 2 bed near Elm St. dollars a month: 2,380")
    assert r["price"] == 2380 and r["beds"] == 2


def test_worded_rent_unclear_gets_a_note():
    r = parse_listing("2 bed. Rent: lots of dollars a month")
    assert "price" not in r


# 3. discounts
@pytest.mark.parametrize("phrase", ["$500 off first month's rent", "First month half off for move-ins by Dec 1", "50% off first month"])
def test_discount_is_a_note_only(phrase):
    r = parse_listing(f"2 bed 1 bath $1,800/mo. {phrase}")
    assert r["price"] == 1800
    assert "one-time deal" in notes(r) and "not taken off the monthly rent" in notes(r)
    assert phrase in notes(r)
    assert "Check what it is for" not in notes(r) and "not counted anywhere" not in notes(r)
    assert not {"deposit", "move_in_fees", "other_monthly_fees"} & set(r)


def test_reduced_from_old_price_is_not_the_rent():
    r = parse_listing("2 bed Reduced from $2,750!")
    assert "price" not in r
    assert "old price" in notes(r) and "$2,750" in notes(r)
    r = parse_listing("2 bed Reduced from $2,750! Rent: $2,400")
    assert r["price"] == 2400
    assert "Check what it is for" not in notes(r)


def test_reduced_to_from_reads_the_new_price():
    r = parse_listing("Reduced to $2,395 from $2,495\n2 bed 1 bath apartment")
    assert r["price"] == 2395
    n = notes(r)
    assert "$2,495" in n and "Check what it is for" not in n and "not counted anywhere" not in n
    assert "2,395" not in n  # the value read into the field is not repeated


# 4. move-in charges
def test_holding_fee_equal_to_a_week():
    r = parse_listing(BASE + "$1,800/mo. Holding fee equal to one week's rent")
    assert r["price"] == 1800 and not {"deposit", "move_in_fees"} & set(r)
    assert "holding fee equal to one week's rent" in notes(r)


def test_last_month_due_at_signing():
    r = parse_listing(BASE + "$1,800/mo. Last month's rent due at signing")
    assert r["price"] == 1800 and r["months_up_front"] == 2


def test_deposit_one_and_a_half_months():
    r = parse_listing(BASE + "$1,800/mo. deposit one and a half months rent")
    assert r["price"] == 1800 and r["deposit"] == 2700


def test_first_month_plus_one_month_security():
    r = parse_listing(BASE + "$1,800/mo. 1st month + 1 month security")
    assert r["price"] == 1800 and r["deposit"] == 1800


@pytest.mark.parametrize("phrase,total", [("Move-in cost 2200 total", "2,200"), ("$2,100 total to move in", "2,100")])
def test_move_in_total_is_a_note_never_the_price(phrase, total):
    r = parse_listing(BASE + phrase)
    assert "price" not in r and not {"deposit", "move_in_fees"} & set(r)
    assert f"${total} in total to move in" in notes(r)


def test_rent_and_deposit_both_1250():
    r = parse_listing(BASE + "$1,250 rent, $1,250 deposit")
    assert r["price"] == 1250 and r["deposit"] == 1250


# 5. lease length
def test_lease_length_not_the_offer_length():
    r = parse_listing(BASE + "$1,800/mo. Lease: 12 months. One month free on a 13-month lease!")
    assert r["lease_months"] == 12
    assert "13 month lease" in notes(r)


def test_offer_lease_alone_is_not_the_lease():
    r = parse_listing(BASE + "$1,800/mo. One month free on a 13-month lease!")
    assert "lease_months" not in r and "13 month lease" in notes(r)


def test_plain_lease_still_read():
    assert parse_listing(BASE + "$1,800/mo. 12 month lease").get("lease_months") == 12


# 6. utilities
def test_electric_through_provider_you_set_up():
    r = parse_listing(BASE + "$1,800/mo. Electric through AEP, you set up")
    assert r["tenant_pays"] == "electric" and "utilities_included" not in r
    assert "could not tell who pays" not in notes(r)


def test_gas_and_electric_you_set_up():
    r = parse_listing(BASE + "$1,800/mo. Gas and electric you set up")
    assert r["tenant_pays"] == "electric, gas" and "utilities_included" not in r


def test_you_set_up_is_no_conflict():
    r = parse_listing(BASE + "$1,800/mo. Utilities: gas and electric through PG&E, you set up")
    assert r["tenant_pays"] == "electric, gas" and "utilities_included" not in r
    assert "also that you pay" not in notes(r)


def test_you_pay_gas_electric_i_cover_water_sewer():
    r = parse_listing(BASE + "$1,800/mo. you pay your own gas and electric, I cover the water + sewer")
    assert r["tenant_pays"] == "electric, gas"
    assert r["utilities_included"] == "water, sewer"


def test_everything_included_except_cable_leaves_internet_unknown():
    r = parse_listing(BASE + "$1,800/mo. Everything included except cable")
    assert r["utilities_included"] == "all" and "tenant_pays" not in r
    assert "TV, not internet" in notes(r)


def test_everything_included_except_wifi_names_internet():
    r = parse_listing(BASE + "$1,800/mo. Everything included except wifi")
    assert r["tenant_pays"] == "internet"


def test_utilities_extra_approx_is_the_estimate_from_the_listing():
    from prophelper.money import _estimate_from_listing
    text = BASE + "$1,800/mo. Utilities extra approx $150 per month"
    r = parse_listing(text)
    assert r["utilities_estimate"] == 150 and "utilities_included" not in r
    assert _estimate_from_listing({"listing_text": text}, 150)
    assert "not counted anywhere" not in notes(r)


# 7. free parking
@pytest.mark.parametrize("phrase", ["Off-street parking at no charge", "free parking"])
def test_free_parking_is_zero(phrase):
    r = parse_listing(BASE + f"$1,800/mo. {phrase}")
    assert r["parking_cost"] == 0 and r["parking"] == "lot"
