"""Cycle 12 G3: pets, parking, laundry, rooms, title and address readers. Each phrasing pins the exact fields."""
from __future__ import annotations

from prophelper.parsers import parse_listing, split_address_unit, street_with_unit


def fields(text: str) -> dict:
    out = parse_listing(text)
    out.pop("source", None)
    return out


def notes(text: str) -> str:
    return str(parse_listing(text).get("found_in_listing") or "")


# ---- 1. per-animal pet lines
def test_cats_ok_dogs_no_pets_over_70_is_both_with_weight_70():
    out = fields("Pets: cats OK. Dogs: no pets over 70 lbs.")
    assert out["pets"] == "both"
    assert out["pet_weight_limit"] == 70
    assert "found_in_listing" not in out


def test_ridgeview_listing_reads_pets_and_free_parking():
    out = fields("Ridgeview Apartments\n3 bed 2 bath $2,100\nOff-street parking for 2 cars at no charge.\nPets: cats OK. Dogs: no pets over 70 lbs.")
    assert (out["pets"], out["pet_weight_limit"], out["parking"], out["parking_cost"]) == ("both", 70, "lot", 0)


def test_per_animal_lines():
    out = fields("Cats: ok. Dogs: up to 40 lbs.")
    assert (out["pets"], out["pet_weight_limit"]) == ("both", 40)
    assert fields("Cats: ok. Dogs: no.")["pets"] == "cats"
    assert fields("Dogs: ok. Cats: no.")["pets"] == "dogs"


# ---- 2. "no pets over 25 lbs" is a weight rule
def test_no_pets_over_25_lbs_is_allowed_up_to_25_kind_unknown():
    out = fields("Pets: no pets over 25 lbs")
    assert "pets" not in out
    assert out["pet_weight_limit"] == 25
    assert "does not say which pets" in out["found_in_listing"]


def test_prose_no_pets_over_weight():
    out = fields("Quiet building. No pets over 25 lbs.")
    assert out.get("pets") != "none"
    assert out["pet_weight_limit"] == 25


# ---- 3. a Deposit line after the pet sentence is the security deposit
def test_deposit_line_after_pet_sentence_is_security_deposit():
    out = fields("Cats only, 1 pet, maximum 55 lbs. Deposit: $1,000")
    assert out["pets"] == "cats"
    assert out["pet_weight_limit"] == 55
    assert out["pet_count_limit"] == 1
    assert out["deposit"] == 1000
    assert "pet_deposit" not in out and "pet_fee" not in out
    assert "found_in_listing" not in out  # the pet line is all in fields


def test_pet_deposit_in_the_pet_sentence_still_a_pet_deposit():
    out = fields("Pets: 1 pet, max 55 lbs., $300 deposit | $25 monthly")
    assert out["pet_deposit"] == 300
    assert "deposit" not in out


# ---- 4. n/a, none, no after a pet fee
def test_pet_fee_na_does_not_take_next_sentence_amount():
    out = fields("Rent $1,500. Pet fee n/a. Application $40 per person")
    assert "pet_fee" not in out and "pet_rent" not in out
    assert out["application_fee"] == 40


def test_pet_fee_none_and_no_pet_fee():
    assert "pet_fee" not in fields("Pet fee: none. Application $40")
    assert "pet_fee" not in fields("No pet fee. Admin $50")
    assert "pet_fee" not in fields("Pet fee n/a, application $40")


# ---- 5. "$35 each" and "Pets no."
def test_each_pet_rent_with_max_two_pets():
    out = fields("Pets welcome, $35 each, 2 pets max")
    assert (out["pets"], out["pet_rent"], out["pet_count_limit"]) == ("both", 35, 2)
    assert "each pet" in out["found_in_listing"]
    assert "one time" in out["found_in_listing"]


def test_dollar_each_pet_rent_word_order():
    out = fields("Dogs and cats welcome - $35 each pet rent, 2 pet max")
    assert (out["pet_rent"], out["pet_count_limit"]) == (35, 2)
    assert "pet_fee" not in out


def test_pets_no_in_prose_means_no_pets():
    assert fields("No smoking. Pets no. Rent $1200")["pets"] == "none"
    assert fields("Quiet building. Pets no.")["pets"] == "none"


def test_credit_check_each_adult_is_not_pet_rent():
    out = fields("Pets ok, cats only. Credit check fee $35 each adult")
    assert "pet_rent" not in out


# ---- 6. parking
def test_optional_garage_with_price_is_not_counted_and_gets_a_note():
    out = fields("Detached garage available, $90 a month")
    assert "parking_cost" not in out and "parking" not in out
    assert "$90 a month" in out["found_in_listing"] and "not counted" in out["found_in_listing"]


def test_optional_garage_without_price_is_not_free():
    out = fields("Detached garage available. Rent $1200")
    assert "parking_cost" not in out
    assert "available" in out["found_in_listing"]


def test_required_garage_counts():
    out = fields("One garage space required, $175/month")
    assert (out["parking"], out["parking_cost"]) == ("garage", 175)


def test_off_street_at_no_charge_is_free():
    out = fields("Off-street parking for 2 cars at no charge")
    assert (out["parking"], out["parking_cost"]) == ("lot", 0)
    out = fields("Off-street parking at no charge")
    assert (out["parking"], out["parking_cost"]) == ("lot", 0)


def test_off_street_with_price_is_the_cost():
    out = fields("Off-street parking, $50 per month")
    assert (out["parking"], out["parking_cost"]) == ("lot", 50)
    out = fields("Parking: off-street, $50 per month")
    assert (out["parking"], out["parking_cost"]) == ("lot", 50)


def test_attached_garage_included_is_still_free():
    out = fields("Attached 1-car garage included in rent")
    assert (out["parking"], out["parking_cost"]) == ("garage", 0)


def test_garage_then_rent_on_next_line_is_not_a_parking_price():
    out = fields("Newly renovated, W&D in unit, dishwasher, garage\n$1400")
    assert "parking_cost" not in out


# ---- 7. laundry and rooms
def test_wd_ampersand_in_unit_is_in_unit_laundry():
    assert fields("Modern.\nW&D in unit\nRent $1500")["laundry"] == "in_unit"
    assert fields("W&D in unit - Cozy 2 bed apartment\n$1500")["laundry"] == "in_unit"


def test_wd_ampersand_hookups_is_not_in_unit():
    assert fields("W&D hookups in unit. Rent $1500").get("laundry") != "in_unit"


def test_corrected_bedroom_count_uses_the_later_one_and_says_so():
    out = fields("One-bedroom? no, THREE bedroom duplex")
    assert out["beds"] == 3
    assert "two different bedroom counts" in out["found_in_listing"]


# ---- 8. titles
def test_craigslist_first_line_without_slash_gives_the_name():
    out = fields("$1,525 1br - 702ft2 - Modern 1 bed apartment near campus\nAttached 1-car garage included in rent")
    assert out["title"] == "Modern 1 bed apartment near campus"
    assert (out["price"], out["beds"], out["sqft"]) == (1525, 1, 702)


def test_feature_lines_are_not_titles():
    assert fields("Attached 1-car garage included in rent\n$1500 2br\n510 Green St, Urbana IL")["title"] == "510 Green St"
    assert fields("Shared coin laundry in the building\n123 Main St")["title"] == "123 Main St"
    assert fields("Newly renovated, W&D in unit, dishwasher, garage\n$1400\n88 Oak Ave, Champaign, IL")["title"] == "88 Oak Ave"
    assert "title" not in fields("Shared coin laundry in the building")


def test_a_real_headline_with_a_feature_word_is_still_a_title():
    assert fields("Sunny 2 bed apartment with garage\n$1500")["title"] == "Sunny 2 bed apartment with garage"


# ---- 9. address and unit
def test_pipe_apt_splits_the_unit():
    out = fields("12 SPRUCE LANE | APT B")
    assert (out["address"], out["unit"]) == ("12 Spruce Lane", "B")
    out = fields("Duplex\n12 SPRUCE LANE | APT B | CHAMPAIGN, IL 61820")
    assert (out["address"], out["unit"], out["city"]) == ("12 Spruce Lane", "B", "Champaign")


def test_split_address_unit_helper():
    assert split_address_unit("12 SPRUCE LANE | APT B", None) == ("12 SPRUCE LANE", "B")
    assert split_address_unit("210 Beck St Apt 2", "2") == ("210 Beck St", "2")
    assert split_address_unit("210 Beck St Apt 2", "3") == ("210 Beck St Apt 2", "3")
    assert split_address_unit("210 Beck St", "2") == ("210 Beck St", "2")


def test_street_with_unit_does_not_repeat_the_unit():
    assert street_with_unit("210 Beck St Apt 2", "2") == "210 Beck St Apt 2"
    assert street_with_unit("210 Beck St", "2") == "210 Beck St #2"
    assert street_with_unit("210 Beck St Apt 22", "2") == "210 Beck St Apt 22 #2"
    assert street_with_unit("", "4") == "#4"


def test_headline_with_2br_and_a_feature_word_is_a_title():
    assert fields("Bright 2BR with balcony\n300 Lake St, Duluth, MN 55802")["title"] == "Bright 2BR with balcony"


# ---- an address handed over with its unit in it (add_place)
def test_add_place_moves_the_unit_out_of_the_address(store):
    from mcp_util import call, server, structured
    srv = server(store)
    call(srv, "create_search", name="UIUC", mode="rent", move_in="2027-07-31", budget_max=2500, people=1)
    a = structured(call(srv, "add_place", title="Beck", address="210 Beck St Apt 2", unit="2"))["place_id"]
    b = structured(call(srv, "add_place", title="Spruce", address="12 SPRUCE LANE | APT B"))["place_id"]
    pa, pb = store.get_place(a), store.get_place(b)
    assert (pa["address"], pa["unit"]) == ("210 Beck St", "2")
    assert (pb["address"], pb["unit"]) == ("12 SPRUCE LANE", "B")
