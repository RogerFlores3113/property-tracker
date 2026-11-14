"""Cycle 6, G2: the listing reader (utilities roles, money phrases, pets, unit and names, seller credit)."""
from prophelper.parsers import parse_listing


def pays(v):
    return [w.strip() for w in v.get("tenant_pays", "").split(",") if w.strip()]


def test_tenant_all_utilities_landlord_pays_garbage_only():
    v = parse_listing("Rent $1500. Tenant responsible for all utilities. Landlord pays garbage only.")
    assert pays(v) == ["electric", "gas", "water", "sewer", "heat"]
    assert v["utilities_included"] == "trash"


def test_all_utilities_except_trash_or_garbage():
    for word in ("trash", "garbage"):
        v = parse_listing(f"Rent $1500. Tenant pays all utilities except {word}.")
        assert pays(v) == ["electric", "gas", "water", "sewer", "heat"], word
        assert v["utilities_included"] == "trash"
    v = parse_listing("Rent $1500. All utilities except trash.")
    assert "trash" not in pays(v) and v["utilities_included"] == "trash"


def test_deposit_one_and_a_half_times_rent():
    v = parse_listing("Rent $1,500/month. Deposit 1.5x rent.")
    assert v["deposit"] == 2250
    assert "deposit" not in parse_listing("Deposit 1.5x rent.")  # rent unknown: no guess


def test_extra_monthly_for_lawn_and_trash_is_counted_and_said():
    v = parse_listing("Rent $1500/month. $150 extra monthly for lawn and trash.")
    assert v["other_monthly_fees"] == 150
    assert "lawn and trash" in v["found_in_listing"] and "optional" in v["found_in_listing"]


def test_storage_locker_is_listed_not_counted():
    v = parse_listing("Rent $1500/month. Storage locker extra $40 per month.")
    assert "other_monthly_fees" not in v
    assert "Storage locker" in v["found_in_listing"] and "$40" in v["found_in_listing"] and "not counted" in v["found_in_listing"]


def test_billed_back_amount_first_reads_like_the_existing_phrase():
    a = parse_listing("Rent $1500/month. $25/mo billed back for trash.")
    b = parse_listing("Rent $1500/month. Trash billed back at $25/month.")
    assert a["utilities_estimate"] == b["utilities_estimate"] == 25
    assert pays(a) == pays(b) == ["trash"]


def test_two_dogs_ok():
    v = parse_listing("Two dogs ok.")
    assert v["pet_count_limit"] == 2 and v["pets"] == "dogs"


def test_pets_up_to_two_dogs_sets_select_and_count():
    v = parse_listing("Pets: up to 2 dogs.")
    assert v["pets"] == "dogs" and v["pet_count_limit"] == 2
    assert parse_listing("Pets: no")["pets"] == "none"


def test_nonrefundable_pet_deposit_is_a_fee():
    v = parse_listing("Rent $1200/mo. Pets welcome. $500 pet deposit non-refundable.")
    assert v["pet_fee"] == 500 and "pet_deposit" not in v
    assert "non-refundable" in v["found_in_listing"]


def test_unit_b_is_not_the_agent():
    v = parse_listing("Unit B. Listed by Jane Smith. 2 bed 1 bath $1200")
    assert v["listing_agent"] == "Jane Smith"
    v = parse_listing("123 Main St, Columbus, OH 43215. Listed by Jane Smith, Unit B. 2 bed $1200")
    assert v["listing_agent"] == "Jane Smith"


def test_unit_mid_text():
    assert parse_listing("Cute 2-bed in unit 2C at 123 Main St, Columbus, OH 43215. $1400")["unit"] == "2C"
    assert parse_listing("Cute place, unit 2C, 2 bed $1200/mo")["unit"] == "2C"
    assert "unit" not in parse_listing("Unit amenities include a dishwasher. 2 bed $1200/mo")


def test_listing_name_stays_the_title():
    assert parse_listing("Westgate Flats\n123 Main St, Columbus, OH 43215\n2 bed $1400/mo")["title"] == "Westgate Flats"
    assert parse_listing("Westgate\n123 Main St, Columbus, OH 43215\n2 bed $1400/mo")["title"] == "Westgate"
    assert parse_listing("Property: Westgate Flats\nRent $1400\n123 Main St, Columbus OH")["title"] == "Westgate Flats"


def test_seller_pays_closing_up_to():
    # c12: "up to" is a cap, never a sure credit (it gets a note instead)
    got = parse_listing("List price $300,000. Closing costs paid by seller up to $5,000.")
    assert "seller_credit" not in got and "closing_costs" not in got
