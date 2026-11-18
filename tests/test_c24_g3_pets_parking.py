"""Cycle 24 group 3: pet fee layouts, refundable pet deposit, second-car-only parking, second space prices, single priced spots,
deeded space, one-pet notes, cats-only listings."""
import pytest

from prophelper.parsers import parse_listing

BASE = "2 bed 1 bath, $1,350 a month. "


def read(text, **kw):
    return parse_listing(BASE + text, **kw)


def notes(r):
    return r.get("found_in_listing", "")


# 1. one time non-refundable pet fee in every layout of a "Pet policy:" line
@pytest.mark.parametrize("text", [
    "Pet policy: cats welcome, $40 per month per cat, $250 one time non-refundable pet fee.",
    "Pet policy: cats welcome, $40 per month per cat, $250 non-refundable one-time pet fee.",
    "Pet policy: cats welcome, $250 one time, non refundable pet fee, $40/month per cat.",
    "Pet policy: cats welcome\n- $40 per month per cat\n- $250 one time non-refundable pet fee",
    "Pet policy: cats welcome ($40 per month per cat; $250 one-time nonrefundable pet fee).",
])
def test_pet_fee_with_two_modifiers(text):
    r = read(text)
    assert r["pets"] == "cats"
    assert r["pet_rent"] == 40
    assert r["pet_fee"] == 250
    assert "pet_deposit" not in r
    assert "$250" not in notes(r).replace("The listing also says", "") or "not counted" not in notes(r)


def test_reviewer_nontech_l14_whole_listing():
    r = parse_listing("Newly renovated 2 Bed / 1 Bath Duplex - Linden - $1,350 a month\nSecurity deposit equals 1 month. Pet policy: cats welcome, $40 per month per cat, "
                      "$250 one time non-refundable pet fee.\nOff-street parking, one spot included. Second vehicle: $40/month. Application fee $30.")
    assert (r["pet_rent"], r["pet_fee"]) == (40, 250)
    assert "Only $250" not in notes(r)


# 2. refundable pet deposit
@pytest.mark.parametrize("text", [
    "Cats and dogs OK, pet deposit refundable $400.",
    "Cats and dogs OK. Refundable pet deposit $400.",
    "Cats and dogs OK. Pet deposit (refundable) $400.",
    "Cats and dogs OK. $400 pet deposit, refundable.",
    "Cats and dogs OK.\n- pet deposit: $400 (refundable)",
])
def test_refundable_pet_deposit_is_a_deposit(text):
    r = read(text)
    assert r["pet_deposit"] == 400
    assert "pet_fee" not in r
    assert "does not say if it comes back" not in notes(r)


def test_nonrefundable_pet_deposit_still_a_fee():
    r = read("Dogs OK. Pet deposit non-refundable $400.")
    assert r["pet_fee"] == 400
    assert "pet_deposit" not in r


# 3. parking required only for a second car
@pytest.mark.parametrize("text", [
    "Parking in the garage is $85/month (required for 2nd car only).",
    "Garage parking $85 a month, required for a second car only.",
    "Garage: $85/month. Only required if you have a second vehicle.",
])
def test_parking_required_for_second_car_only(text):
    r = read(text)
    assert r["parking"] == "garage"
    assert r.get("parking_cost") is None
    n = notes(r)
    assert n.count("required for a second car only") == 1
    assert "$85" in n


# 4. second space price wordings
@pytest.mark.parametrize("text", [
    "Garage 1 space included, second space rent for $175.",
    "Garage 1 space included, 2nd spot $175.",
    "Garage 1 space included, another space $175/mo.",
    "Garage parking included. Second space rents for $175 a month.",
    "Garage 1 space included\n- Second space: rent for $175",
])
def test_second_space_price_is_optional_note(text):
    r = read(text)
    assert r["parking"] == "garage"
    assert r["parking_cost"] == 0
    n = notes(r)
    assert "$175" in n and "is optional" in n or "optional" in n
    assert "not counted anywhere" not in n


# 5. a single priced spot is the parking cost
@pytest.mark.parametrize("text,kind,cost", [
    ("Covered spot $75.", "covered", 75),
    ("Covered parking spot $75/mo.", "covered", 75),
    ("Reserved covered space: $75 a month", "covered", 75),
])
def test_single_priced_spot(text, kind, cost):
    r = read(text)
    assert (r["parking"], r["parking_cost"]) == (kind, cost)
    assert "not counted anywhere" not in notes(r)


@pytest.mark.parametrize("text", [
    "Reserved indoor garage space: $0 for first year, then $90.",
    "Garage space $0 for the first year, then $90 per month.",
    "Parking: indoor garage, $0 for first 12 months then $90/mo.",
])
def test_free_first_year_then_price(text):
    r = read(text)
    assert r["parking"] == "garage"
    assert r["parking_cost"] == 90
    assert "first" in notes(r) and "$0" in notes(r)


def test_optional_priced_spot_still_optional():
    r = read("Parking: lot included. Covered spot available $60.")
    assert r["parking_cost"] == 0


# 6. deeded space
@pytest.mark.parametrize("text", [
    "Includes 1 deeded parking space.",
    "One deeded parking space included.",
    "Deeded parking spot #12 conveys.",
])
def test_deeded_space_has_no_kind(text):
    r = parse_listing("2 beds 2 baths 1,010 sq ft. $350,000. " + text, buying=True)
    assert "parking" not in r
    assert "deeded space" in notes(r)


# 7. one pet household
RENT_EACH = "Cats OK. Pet rent $25 per pet, max 2 pets."


def test_adds_up_note_unknown_count():
    assert "more than one pet it adds up" in notes(read(RENT_EACH))
    assert "more than one pet it adds up" in notes(read(RENT_EACH, pet_kind="cat"))
    assert "more than one pet it adds up" in notes(read(RENT_EACH, pet_kind="cat", pet_count=2))


@pytest.mark.parametrize("text", [RENT_EACH, "Cats OK. $25 per cat per month.", "Cats OK. Pet charge $25 each."])
def test_no_adds_up_note_for_one_pet(text):
    r = read(text, pet_kind="cat", pet_count=1)
    assert r["pet_rent"] == 25
    assert "adds up" not in notes(r)


# 7b. cats only listings: a dog search fails clearly
@pytest.mark.parametrize("text", [
    "Pets: No dogs. Cats allowed.",
    "Cats allowed, dogs not allowed.",
    "Cats ok. No dogs.",
])
def test_cats_only_no_dog_limit(text):
    r = read(text, pet_kind="dog")
    assert r["pets"] == "cats"
    assert "pet_weight_limit" not in r and "pet_count_limit" not in r


def test_no_pets_over_limit_cats_ok():
    r = read("No pets over 35 lbs. Cats ok. Pet charge $25 a month.", pet_kind="dog", pet_count=1)
    assert (r["pets"], r["pet_weight_limit"], r["pet_rent"]) == ("cats", 35, 25)


def test_cat_deposit_counted_when_cats_only():
    r = read("Pets: No dogs. Cats allowed with $200 cat deposit and cat rent $15/mo.")
    assert (r["pets"], r["pet_deposit"], r["pet_rent"]) == ("cats", 200, 15)


def test_included_priced_space_is_not_the_cost():
    r = read("PARKING: 1 INDOOR SPACE $180 INCLUDED IN RENT")
    assert r["parking_cost"] == 0


def test_pet_rent_after_one_time_fee_stays_rent():
    r = read("Pet fee: $300 one-time, pet rent $30. Cats and dogs OK.")
    assert (r["pet_fee"], r["pet_rent"]) == (300, 30)
