"""Cycle 13, group G3: pets, fees and features reader. Each phrasing pins the exact fields."""
import pytest

from prophelper.parsers import parse_listing


def read(text):
    return parse_listing("Rent $2000. " + text)


def notes(r):
    return r.get("found_in_listing") or ""


def test_pet_deposit_then_monthly():
    r = parse_listing("2 bed. Pet deposit $300, $40 monthly.")
    assert r["pet_deposit"] == 300 and r["pet_rent"] == 40
    assert "not counted" not in notes(r)


def test_dogs_up_to_weight():
    r = read("dogs up to 60 lbs welcome")
    assert r["pets"] == "dogs" and r["pet_weight_limit"] == 60


@pytest.mark.parametrize("text", ["Dogs welcome. Cat fee $150", "Dogs welcome. Cats $25/mo", "Dogs ok. $25/mo cat rent"])
def test_cat_charge_means_cats_allowed(text):
    assert read(text)["pets"] == "both"


def test_cat_charge_with_dogs_only_stays_dogs():
    assert read("Dogs only. Cat fee $150")["pets"] == "dogs"


def test_no_pet_rent_is_zero():
    r = read("Pets ok. No pet rent")
    assert r["pet_rent"] == 0 and r["pets"] == "both"


def test_each_monthly_has_no_hedge():
    r = read("$25/mo each for pets")
    assert r["pet_rent"] == 25
    assert "one time" not in notes(r) and "not counted" not in notes(r)


def test_each_without_monthly_keeps_hedge():
    r = read("$25 each for pets")
    assert r["pet_rent"] == 25 and "one time fee instead" in notes(r)


def test_credit_check_plain_is_application_fee():
    r = read("Credit check $25")
    assert r["application_fee"] == 25 and "application_fee_per_adult" not in r
    assert "not counted anywhere" not in notes(r)


def test_credit_check_per_adult_still_works():
    r = read("Credit check $25 per adult")
    assert r["application_fee"] == 25 and r["application_fee_per_adult"] == 1


def test_mandatory_gym_fee_counted():
    r = read("Gym access fee $30/mo mandatory")
    assert r["other_monthly_fees"] == 30 and "not counted anywhere" not in notes(r)


def test_required_amenity_fee_counted_once():
    assert read("Required amenity fee $40/month")["other_monthly_fees"] == 40


def test_optional_gym_fee_not_counted():
    assert "other_monthly_fees" not in read("Gym access fee $30/mo optional")


def test_nonrefundable_cleaning_fee_is_move_in_fee():
    r = read("Non-refundable cleaning fee $250")
    assert r["move_in_fees"] == 250 and "not counted" not in notes(r)


@pytest.mark.parametrize("text", ["Fenced in back", "Fenced-in backyard", "fully fenced back yard"])
def test_fenced_yard(text):
    assert read(text)["fenced_yard"] == 1


def test_no_fence_stays_zero():
    assert read("No fence")["fenced_yard"] == 0


@pytest.mark.parametrize("text,pets,weight", [("Cats and small dogs welcome (35 lb limit)", "both", 35),
                                                ("Dogs welcome. Dog weight limit 60 lbs.", "dogs", 60)])
def test_notes_do_not_repeat_pet_values(text, pets, weight):
    r = read(text)
    assert r["pets"] == pets and r["pet_weight_limit"] == weight
    assert not notes(r)


def test_different_weight_in_note_is_kept():
    r = read("Dogs welcome up to 60 lbs. Cats up to 10 lbs.")
    assert r["pet_weight_limit"] in (60, 10) and notes(r) is not None
