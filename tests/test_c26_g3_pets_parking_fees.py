"""Cycle 26 group 3: a priced parking line is never replaced by an unpriced one, a free spot beside priced options is $0, optional prices are one
note and never missing, "not charged for first pet", questions with "please ask", and required monthly fees by any name."""
import pytest

from prophelper import compare, money
from prophelper.parsers import parse_listing

BASE = "1 bed 1 bath, $1,400 a month. "


def read(text, **kw):
    return parse_listing(BASE + text, **kw)


def notes(r):
    return r.get("found_in_listing", "") or ""


def missing(text, **kw):
    r = parse_listing(text, "", **kw)
    place = dict(r, reader_notes=r.get("found_in_listing"), listing_text=text)
    c = money.true_monthly_cost(place, "rent")
    return r, compare._missing_names(dict(place, cost=c, score={"unknown": []}))


# 1. a line with no price never replaces a priced line
@pytest.mark.parametrize("text", [
    "Parking $85/mo. In-unit W/D. Garage parking available.",
    "Parking: $85/mo\nGarage parking available",
    "Garage parking available. Parking $85/mo.",
    "Parking $85 per month | Garage parking available | In-unit laundry",
    "Parking 85/mo. Garage parking available.",
    "Parking 85/mo\nGarage parking available\n",
])
def test_priced_parking_beats_unpriced_garage_line(text):
    r = read(text)
    assert r["parking_cost"] == 85, r
    assert "$85" not in notes(r) or "not counted" not in notes(r).split("$85")[1][:60]


def test_reviewer_uiuc_l31_whole_listing():
    r = parse_listing("Campustown Lofts. Parking $85/mo. Monthly rent: $1,410 for a 1 bedroom, 1 bath. Special: move in by July 15 and get half off first month!\n"
                      "610 E Green St Champaign IL 61820. New in 2025. In-unit washer/dryer, stainless dishwasher. Water/sewer/trash $95 flat. Internet paid by tenant. "
                      "Electric separate (avg $48).\n$50 app. Security deposit is $700 at signing. Garage parking available. Pets: no.")
    assert r["price"] == 1410 and r["parking_cost"] == 85 and r["pets"] == "none"


# 2. $0 is not missing
def test_garage_included_zero_is_not_missing():
    r, miss = missing("Prairie View Residences - Savoy. 1BR/1BA $1,525-$1,575 depending on floor. Washer and dryer, dishwasher, 1-car garage included ($0).\n"
                      "Tenant pays: electric, internet. Admin $150, app $45. Deposit $800.")
    assert r["parking"] == "garage" and r["parking_cost"] == 0
    assert not any("$0" in m for m in miss), miss
    assert "parking cost" not in miss


@pytest.mark.parametrize("text", [
    "Parking $0 first spot, covered $160 optional.",
    "Parking: $0 first spot | covered $160 optional",
    "- Parking $0 first spot\n- Covered spot $160 (optional)",
    "Parking $0 for the first spot; covered spot $160 optional",
])
def test_free_first_spot_with_optional_covered(text):
    r, miss = missing(BASE + text)
    assert r["parking_cost"] == 0, r
    assert r.get("parking") != "covered", r
    assert "parking cost" not in miss and not any("$160" in m for m in miss), miss
    assert notes(r).count("$160") == 1, notes(r)


def test_reviewer_roommates_l16_whole_listing():
    r, miss = missing("Uptown 3 bed 2 bath $3,275/mo + utils. 4600 N Broadway, Chicago, IL 60640. Deposit 1.5 months. Pet rent not charged. "
                      "Parking $0 first spot, covered $160 optional. Available 1/15/2027. $50 application. Heat and hot water paid by owner.")
    assert r["parking_cost"] == 0 and r.get("parking") != "covered" and r["pet_rent"] == 0
    assert "parking cost" not in miss


# 3. a free spot beside priced options is $0 in every layout
@pytest.mark.parametrize("text", [
    "Garage $100/mo, carport $40/mo, surface lot FREE.",
    "Parking: Garage $100 | carport $40 | surface lot FREE",
    "- Garage $100/mo\n- Carport $40/mo\n- Surface lot: FREE",
    "Garage $100/mo\nCarport $40/mo\nSurface lot free",
    "Surface lot FREE, carport $40/mo, garage $100/mo.",
    "Parking options: free surface lot; garage $100 a month; carport $40 a month",
    "Parking: $0 (open lot), garage $100, carport $40",
    "Parking: $0 open lot / $100 garage / $40 carport",
    "Parking:\n- Open lot $0\n- Garage $100/mo\n- Carport $40/mo",
])
def test_free_lot_beside_priced_garage_and_carport_is_zero(text):
    r, miss = missing(BASE + text)
    assert r["parking_cost"] == 0 and r["parking"] == "lot", r
    assert "parking cost" not in miss and not any("$100" in m or "$40" in m for m in miss), miss
    assert "$100" in notes(r) and "$40" in notes(r)


def test_reviewer_nontech_l2_and_l27_parking():
    r = parse_listing("Westerville Apartments - Maple Court\n2 Bedrooms from $1,425 | 2 Bath | 1,050 SF\n** Rent $1,425 ** Deposit $500\n"
                      "Cats & dogs OK, breed restrictions apply. Pet fee $250 per pet, pet rent $35/mo.\nGarage $100/mo, carport $40/mo, surface lot FREE.\n")
    assert r["parking_cost"] == 0
    r = parse_listing("Apartments.com | Olentangy Commons\n2 Bedroom 2 Bath, 1,000 sq ft, from $1,399 - $1,449\nAmenities: Garage $90/mo, covered parking $45/mo, open lot free. "
                      "Washer/dryer connections.\n")
    assert r["parking_cost"] == 0


# 4. an optional price is one note, never missing
@pytest.mark.parametrize("text", [
    "Free surface lot spot; reserved covered spot $60; garage $140 upgrade.",
    "Parking: 1 free spot included; reserved covered spot $55/mo, garage upgrade $130/mo.",
    "Free lot parking. Reserved covered spot $60/mo (optional). Garage $140/mo (optional).",
])
def test_optional_parking_prices_are_notes_not_missing(text):
    r, miss = missing(BASE + text)
    assert r["parking_cost"] == 0, r
    assert not any(("$60" in m or "$55" in m or "$130" in m or "$140" in m) for m in miss), miss
    assert "not counted anywhere" not in notes(r), notes(r)


def test_reviewer_family_l16_headline_and_fields():
    r, miss = missing("3 bed 2 bath townhome. $2,295/mo. Parking: 1 free spot included; reserved covered spot $55/mo, garage upgrade $130/mo. "
                      "PARKING PERMIT FEE REQUIRED $20 PER MONTH. Tenant pays electric. Trash is $12/mo. Water and sewer included.")
    assert r["parking_cost"] == 20 and r["other_monthly_fees"] == 12
    assert not any("$55" in m or "$130" in m for m in miss), miss


# 5. pet rent not charged for the first pet
@pytest.mark.parametrize("text", [
    "Dog OK under 50 lbs, $40/mo pet rent not charged for first pet.",
    "Dogs ok. Pet rent $40/mo, first pet free.",
    "Dogs ok. Pet rent is $40 per month, waived for the first pet.",
])
def test_pet_rent_not_charged_for_first_pet(text):
    r = read(text, pet_kind="dog", pet_count=1)
    assert r["pet_rent"] == 0, r
    assert "first pet" in notes(r) and "$40" in notes(r)
    r2 = read(text, pet_kind="both", pet_count=2)
    assert r2["pet_rent"] == 40, r2
    r3 = read(text)
    assert r3["pet_rent"] == 0


def test_reviewer_roommates_l3_whole_listing():
    r = parse_listing("Logan Square 3bd/2ba. $3,195/mo (was $3,295 - reduced!). 2700 N Milwaukee Ave 60647. In-unit W/D, DW. Landlord pays water and trash; you pay gas + electric "
                      "(Peoples Gas, ComEd), avg $120 combined in winter. Dog OK under 50 lbs without approval, $40/mo pet rent not charged for first pet. "
                      "One-time admin fee $250, non-refundable. Available 1/10. Sorry, no parking - street permit only?", "", pet_kind="dog", pet_count=1)
    assert r["pet_rent"] == 0 and r["pets"] == "dogs"


def test_pet_rent_charged_normally_is_unchanged():
    r = read("Dogs ok. Pet rent $40/mo.", pet_kind="dog", pet_count=1)
    assert r["pet_rent"] == 40


# 6. a question or "please ask" sets nothing
@pytest.mark.parametrize("text", [
    "Pets allowed? please ask.",
    "Pets allowed? Please ask.",
    "Pets allowed? call us.",
    "Pets allowed - please ask us.",
    "Pets allowed? please ask. Dog weight limit 75 lb without approval, 2 pet max.",
])
def test_pets_question_sets_nothing(text):
    r = read(text)
    assert "pets" not in r, r
    assert "only asks about pets" in notes(r)


def test_family_l16_pets_not_both():
    r = parse_listing("3 bed 2 bath townhome. $2,295/mo. Parking: 1 free spot included. Pets allowed? please ask. Dog weight limit 75 lb without approval, 2 pet max. "
                      "Tenant pays electric.")
    assert "pets" not in r


def test_parking_question_with_lowercase_please_ask():
    r = read("Is parking included? please ask. Pets: cats ok.")
    assert "parking" not in r and "parking_cost" not in r
    assert r["pets"] == "cats"


# 7. a required monthly fee by any name is counted once
@pytest.mark.parametrize("text,amount", [
    ("Rent is $1,400 plus $30 mandatory pest and package fee.", 30),
    ("Rent $1,400. $30 mandatory pest and package fee.", 30),
    ("Rent $1,400\n- Technology fee $30, required\n", 30),
    ("Rent $1,400 | Mandatory $30/mo pest control, billed monthly", 30),
    ("Rent $1,400. Required monthly pest and package fee: $30.", 30),
])
def test_required_monthly_fee_counted_once(text, amount):
    r, miss = missing(text)
    assert r["other_monthly_fees"] == amount, r
    assert not any(f"${amount}" in m for m in miss), miss
    assert "not counted anywhere" not in notes(r)


@pytest.mark.parametrize("text", [
    "Rent $2,260 plus $75 monthly HOA passthrough.",
    "Rent $2,260. HOA pass-through $75/mo.",
    "Rent $2,260\n- HOA dues: $75 billed monthly",
    "Rent $2,260. HOA fee $75/month, required.",
])
def test_hoa_passthrough_counted_once_on_a_rental(text):
    r, miss = missing(text)
    total = (r.get("other_monthly_fees") or 0) + (r.get("hoa") or 0)
    assert total == 75, r
    assert not (r.get("other_monthly_fees") and r.get("hoa")), r
    assert not any("$75" in m or "HOA" in m for m in miss), miss
    assert "does not say the tenant pays" not in notes(r)


def test_optional_or_owner_paid_hoa_and_fees_are_not_counted():
    r = read("Optional $30 pest fee.")
    assert not r.get("other_monthly_fees")
    r = read("HOA fee $75/mo (paid by owner).")
    assert not r.get("hoa") and not r.get("other_monthly_fees")
    r = read("HOA fee $75/mo.")
    assert not r.get("hoa") and not r.get("other_monthly_fees")


def test_required_fee_is_not_counted_twice_with_amenity_reader():
    r = read("Amenity fee $85/mo mandatory.")
    assert r["other_monthly_fees"] == 85
    r = read("Required amenity fee $40/month.")
    assert r["other_monthly_fees"] == 40
