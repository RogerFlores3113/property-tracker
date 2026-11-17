"""Cycle 27 group 3: a free first spot beside priced extras is $0, a free driveway/street/lot spot is $0, one pet deposit gets one honest
note, "pet-free" means no pets, "WD in unit" is in-unit laundry, and "Delivered 2024" / "Opened fall 2023" are the year built."""
import pytest

from prophelper.parsers import parse_listing

BASE = "1 bed 1 bath, $1,400 a month. "


def read(text):
    return parse_listing(BASE + text, "")


def notes(r):
    return r.get("found_in_listing", "") or ""


@pytest.mark.parametrize("text", [
    "Parking: 1 free assigned spot, second spot $75, covered $100",
    "Parking: first spot free; 2nd spot $75/mo; covered $100/mo",
    "Parking\n- 1 free assigned spot\n- second spot $75\n- covered $100",
    "1 free assigned spot (second $75, covered $100).",
    "Parking | First spot free | Second spot $75",
    "First spot free, second spot $75",
])
def test_free_first_spot_with_priced_extras_is_zero(text):
    r = read(text)
    assert r["parking_cost"] == 0, r
    assert r["parking"] in ("lot", "street", "covered", "garage")
    n = notes(r)
    assert "$75" in n or "$100" in n


@pytest.mark.parametrize("text", [
    "Parking: 1 car garage, driveway free",
    "1 car garage; free driveway parking",
    "Parking: garage and free driveway",
    "Parking:\n- garage\n- driveway free",
])
def test_free_driveway_beside_unpriced_garage_is_zero(text):
    r = read(text)
    assert r["parking_cost"] == 0, r
    assert r["parking"] == "lot"
    assert "garage" in notes(r) and "no price" in notes(r)


@pytest.mark.parametrize("text", ["Free street parking, garage $150/mo", "Parking: street free, covered carport", "Free lot parking, no garage"])
def test_free_street_or_lot_is_zero(text):
    r = read(text)
    assert r["parking_cost"] == 0, r


def test_included_garage_with_priced_guest_spot_has_one_note():
    r = parse_listing("Townhome at 12 Heron Pl. $2,390/mo. Attached 2-car garage included, uncovered guest spot $50/mo. Storage unit $35 a month optional.", "")
    assert r["parking_cost"] == 0
    assert "not counted anywhere" not in notes(r)
    assert notes(r).count("$50") == 1


@pytest.mark.parametrize("text", [
    "Pet deposit $250 per pet.",
    "Pet deposit: $250 each pet.",
    "$250 per pet deposit.",
])
def test_pet_deposit_gets_one_note_that_does_not_claim_it_comes_back(text):
    r = read("Cats and dogs ok. " + text)
    assert r["pet_deposit"] == 250
    lines = [x for x in notes(r).split("\n") if "pet deposit" in x.lower()]
    assert len(lines) == 1, lines
    assert "comes back, so" not in notes(r)


def test_refundable_pet_deposit_says_it_comes_back_once():
    r = read("Dogs ok. $250 refundable pet deposit per pet.")
    assert r["pet_deposit"] == 250
    assert "does not say if it comes back" not in notes(r)


def test_second_pet_rent_note_is_not_a_one_time_cost():
    r = read("Pets: Dog fee $350 one time, pet rent $35/mo for first pet, second pet $25.")
    assert r["pet_rent"] == 35 and r["pet_fee"] == 350
    assert "Only $25" not in notes(r)
    assert "$25 a month for a second pet" in notes(r)


@pytest.mark.parametrize("text", ["Pet-free community.", "Pet free building.", "No pets allowed.", "Pet-free apartment homes.", "This is a pet free community"])
def test_pet_free_means_no_pets(text):
    assert read(text)["pets"] == "none"


def test_not_pet_free_is_not_none():
    assert read("Not a pet-free building. Dogs ok.").get("pets") == "dogs"


@pytest.mark.parametrize("text", ["WD in unit, DW", "W/D in unit", "Washer/dryer in unit", "In-unit W/D", "in unit WD", "WD included"])
def test_in_unit_laundry_wordings(text):
    assert read(text)["laundry"] == "in_unit"


def test_shared_wd_is_not_in_unit():
    assert read("Shared WD in basement").get("laundry") == "in_building"
    assert read("WD hookups").get("laundry") == "hookups"


@pytest.mark.parametrize("text,year", [
    ("Delivered 2024.", 2024), ("Opened fall 2023.", 2023), ("Delivered in spring 2025", 2025),
    ("Opened in May 2022.", 2022), ("Newly delivered 2025", 2025), ("Built 1998", 1998),
])
def test_renter_year_built(text, year):
    assert read(text)["year_built"] == year


def test_year_of_other_things_is_not_year_built():
    assert read("Pool opened fall 2023. Dogs ok.").get("year_built") is None
    assert read("Lease delivered 2024.").get("year_built") is None


def test_reviewer_listings():
    P = "/tmp/claude-0/-home-user-property-helper/be454331-cd61-59ba-9ebc-8cb8b7ec6a12/scratchpad/panel/"
    import os
    if not os.path.exists(P + "r26-family-l27.txt"):
        pytest.skip("saved listings not present")
    g = lambda n: parse_listing(open(P + f"r26-{n}.txt").read(), "")
    assert g("family-l27")["parking_cost"] == 0
    assert g("family-l29")["parking_cost"] == 0
    assert g("uiuc-l3")["pets"] == "none"
    assert g("uiuc-l11")["laundry"] == "in_unit" and g("uiuc-l11")["year_built"] == 2023
    assert g("uiuc-l9")["year_built"] == 2024


def test_included_covered_space_in_brackets_keeps_its_kind():
    r = read("Parking: 1 included space (covered), 2nd space $100.")
    assert r["parking_cost"] == 0 and r["parking"] == "covered"


def test_second_pet_amount_is_not_a_second_parking_space():
    r = read("Parking: 1 assigned spot $0, 2nd space $50. Pets: cats welcome, first pet no pet rent, second $15.")
    assert r["parking_cost"] == 0
    assert "$50" in notes(r)


def test_required_parking_price_beside_free_spot_is_not_zero():
    r = read("Parking: PARKING FEE $90 REQUIRED.\nFree surface lot spot; reserved covered spot $60.")
    assert r.get("parking_cost") != 0
