"""Cycle 16, group G3: pet charges and wording, parking, yard, buyer money and HOA. Each phrasing pins the exact fields."""
import pytest

from prophelper.money import rent_cost
from prophelper.parsers import parse_listing

MAGNOLIA = """Magnolia Drive - Charming 3 bed / 2 bath home with fenced yard, walking distance to Magnolia Elementary
Rent: $2,275 per month
Pets: Dogs considered case by case. Maximum 2 pets. Weight limit 65 lbs. Pet application $40 per pet. $300 deposit per pet, non-refundable $100. $25 monthly pet rent.
Tenant pays electricity, gas and internet. Landlord pays water, sewer and trash. Heat: forced air gas.
Security deposit $2,275. Application fee $50 per adult. Quarterly water bill passed through. Available 1/15/2027. 12 month lease. Parking: 2-car garage, included."""


def read(text, buying=False):
    return parse_listing(("Home for sale $350,000. " if buying else "Rent $2000. ") + text, buying=buying)


def notes(r):
    return r.get("found_in_listing") or ""


# ---- 1. pet charges
def test_magnolia_pet_charges():
    r = parse_listing(MAGNOLIA)
    assert r["pet_deposit"] == 200 and r["pet_fee"] == 100 and r["pet_rent"] == 25
    n = notes(r)
    assert "$40 pet application" in n and "each pet" in n
    assert "2 adults" not in n and "$100 together" not in n
    assert "Pet rent is $25 for each pet" not in n  # the monthly pet rent is not per pet; the $40 per pet is the application


@pytest.mark.parametrize("text,deposit,fee", [
    ("Pets ok. $300 (non-refundable $150)", 150, 150),
    ("Pet deposit $300 (non-refundable $150).", 150, 150),
    ("Cats allowed. $400 deposit, $100 of it non-refundable.", 300, 100),
    ("Dogs ok. $250 pet deposit, $75 non-refundable.", 175, 75),
    ("Pets welcome. $300 deposit per pet, non-refundable $100.", 200, 100),
])
def test_part_nonrefundable_pet_deposit(text, deposit, fee):
    r = read(text)
    assert r["pet_deposit"] == deposit and r["pet_fee"] == fee


@pytest.mark.parametrize("text", ["Dogs ok. $40 pet application fee. $250 pet deposit, $75 non-refundable.",
                                  "Dogs ok. Pet application $40. $250 pet deposit, $75 non-refundable."])
def test_pet_application_is_a_note_not_the_fee(text):
    r = read(text)
    assert r["pet_fee"] == 75 and r["pet_deposit"] == 175
    assert "$40 pet application" in notes(r)


def test_pet_application_alone_is_not_a_pet_fee():
    r = read("Cats ok. Pet application $40 per pet.")
    assert "pet_fee" not in r and "pet_deposit" not in r
    assert "$40 pet application for each pet" in notes(r)


def test_nonrefundable_not_smaller_than_deposit_stays_empty():
    r = read("Pets ok. Pet deposit $300 (non-refundable $300).")
    assert "pet_deposit" not in r and "pet_fee" not in r
    assert "does not add up" in notes(r)


def test_plain_security_deposit_with_nonrefundable_is_not_a_pet_charge():
    r = read("Security deposit $1,500 (non-refundable $500).")
    assert "pet_deposit" not in r and "pet_fee" not in r


# ---- 2. pet wording
@pytest.mark.parametrize("text,pets", [
    ("Cats yes, dogs no", "cats"), ("Dog no, cats yes", "cats"), ("cats ok, no dogs", "cats"),
    ("Dogs yes, cats no.", "dogs"), ("Cats: yes. Dogs: no.", "cats"), ("Dogs no. Cats welcome.", "cats"),
])
def test_cat_dog_yes_no_wording(text, pets):
    assert read(text)["pets"] == pets


def test_dogs_no_followed_by_fee_is_not_a_no():
    assert read("Dogs ok. Dog no-fee policy").get("pets") == "dogs"


@pytest.mark.parametrize("text", ["Dog weight cap 80 lbs", "Dogs ok, weight cap of 80 lbs", "Dogs ok, 80 lb cap"])
def test_weight_cap(text):
    assert read(text)["pet_weight_limit"] == 80


@pytest.mark.parametrize("text", ["Pets: 2 allowed, max 60 lbs each", "2 allowed, max 60 lbs each", "Pets ok, two allowed, 60 lbs each"])
def test_count_and_weight_with_allowed(text):
    r = read(text)
    assert r["pet_count_limit"] == 2 and r["pet_weight_limit"] == 60


# ---- 3. parking included with an optional garage, in the whole listing
def _cost(text):
    r = parse_listing(text)
    place = dict(r)
    place["reader_notes"] = r.get("found_in_listing")
    place["listing_text"] = text
    return r, rent_cost(place)


@pytest.mark.parametrize("text", [
    "Alder Lane Townhome - 1,299 a month. 3 bedrooms, 2.5 baths. Landlord pays all utilities. HEAT INCL. Internet required, $60/mo. Flat $75/mo amenity fee. Dogs OK up to 65 lb, max 2 pets. Fenced backyard. Parking included, optional garage $100.",
    "Bronzeville 2BR $2,000. Heat included. Parking included in rent. Optional garage $90/mo.",
    "**Lakeview Greystone** 3 bd / 2 ba - $3,290\nHEAT INCL. Gas cooking, electric tenant. Parking included (garage $90 optional). Deposit $0 with approved credit.",
    "Edgewater 1BR $1,800. Free parking for residents, garage space $110 a month optional.",
])
def test_parking_included_optional_garage_is_zero_in_full_listing(text):
    r, cost = _cost(text)
    assert r["parking_cost"] == 0 and r["parking"] in ("lot", "street")
    assert "parking cost" not in cost["missing"]
    line = next(l for l in cost["lines"] if l["key"] == "parking")
    assert line["amount"] == 0


@pytest.mark.parametrize("text,kind", [
    ("Off-street parking for two cars", "lot"), ("Off-street parking for 2 cars.", "lot"),
    ("Free street parking", "street"), ("Free parking on the street", "street"), ("Free on-street parking.", "street"),
])
def test_plain_parking_statements_are_known_at_zero(text, kind):
    r = read(text)
    assert r["parking"] == kind and r["parking_cost"] == 0


def test_offstreet_parking_with_a_price_is_not_zero():
    r = read("Off-street parking for 2 cars, $50/mo each.")
    assert r.get("parking_cost") != 0


def test_optional_garage_alone_still_unknown():
    r, cost = _cost("Rent $1500. Garage available $100 a month.")
    assert r.get("parking_cost") is None


def test_free_street_parking_after_optional_carport():
    r = read("Carport available $40/mo optional. Free street parking. 13 months lease.")
    assert r["parking"] == "street" and r["parking_cost"] == 0


# ---- 4. yard
@pytest.mark.parametrize("text", ["3BR/2BA fenced house", "Spacious fenced home near the park", "Cute fenced-in property", "3BR fenced duplex"])
def test_fenced_house_is_fenced_yard(text):
    assert read(text)["fenced_yard"] == 1


def test_no_fence_still_no():
    assert read("3BR house, no fence")["fenced_yard"] == 0


# ---- 5. buyer and HOA
@pytest.mark.parametrize("text", ["Special assessment of $1,200 owed by seller at closing", "Special assessment $1,200, owed by the seller.",
                                  "Special assessment of $1,200 payable by seller"])
def test_assessment_owed_by_seller(text):
    r = read(text, buying=True)
    assert r["special_assessment"] == 1200 and r["special_assessment_payer"] == "seller"
    assert "doesn't say who pays" not in notes(r)


def test_assessment_owed_by_buyer_still_buyer():
    r = read("Special assessment of $1,200 owed by buyer at closing", buying=True)
    assert r["special_assessment_payer"] == "buyer"


@pytest.mark.parametrize("text", ["Monthly condo fee 385", "Condo fee: 385/mo", "Monthly HOA fee 385", "Condo fee $385 per month"])
def test_condo_fee_is_hoa(text):
    assert read(text, buying=True)["hoa"] == 385


def test_bare_condo_fee_number_with_no_period_is_unknown():
    assert "hoa" not in read("Condo fee 385", buying=True)


@pytest.mark.parametrize("text,hoa", [("HOA about $360 per quarter", 120), ("HOA approx $360 quarterly", 120), ("HOA: roughly $360 a quarter", 120)])
def test_hoa_about_per_quarter(text, hoa):
    assert read(text, buying=True)["hoa"] == hoa


@pytest.mark.parametrize("text", ["Closing cost help from seller: $3,000", "Closing cost assistance from the seller $3,000", "Seller credit $3,000 toward closing"])
def test_seller_closing_help_is_seller_credit(text):
    assert read(text, buying=True)["seller_credit"] == 3000


@pytest.mark.parametrize("text", ["Insurance quote $1,100/yr", "Homeowner's insurance quote $1,100 per year", "Insurance quoted at $1,100/yr"])
def test_insurance_quote(text):
    assert read(text, buying=True)["insurance"] == 1100


def test_second_one_time_buyer_charge_is_added_with_a_note_naming_both():
    r = read("Special assessment of $2,400 payable by buyer at closing. $1,000 one-time capital contribution at closing.", buying=True)
    assert r["special_assessment"] == 3400 and r["special_assessment_payer"] == "buyer"
    n = notes(r)
    assert "$2,400" in n and "$1,000" in n and "$3,400" in n


def test_second_charge_listed_first_or_condo_wording():
    for text in ("$1,000 one-time capital contribution at closing. Condo assessment of $2,400 payable by buyer at closing.",
                 "Condo assessment of $2,400 payable by buyer at closing. $1,000 one-time capital contribution at closing.",
                 "Buyer pays a $2,400 condo assessment at closing plus a $1,000 one-time capital contribution at closing."):
        r = read(text, buying=True)
        assert r["special_assessment"] == 3400 and r["special_assessment_payer"] == "buyer", text


def test_second_charge_not_added_when_seller_pays_assessment():
    r = read("Special assessment of $2,400, seller pays. $1,000 one-time capital contribution at closing.", buying=True)
    assert r["special_assessment"] == 2400 and r["special_assessment_payer"] == "seller"
    assert "$1,000 capital contribution" in notes(r) and "not added" in notes(r)


def test_capital_contribution_alone_still_read():
    r = read("$1,000 one-time capital contribution at closing.", buying=True)
    assert not r.get("special_assessment")  # cycle 31: counted as a one-time closing fee under its own name, not as a special assessment
    assert "$1,000 capital contribution at closing" in notes(r) and "counted in the cash to close" in notes(r)


# ---- 6. quarterly HOA leaves no "not counted" note
@pytest.mark.parametrize("text,hoa", [("HOA: $425 billed quarterly", 141.67), ("HOA fee $520 quarterly", 173.33),
                                      ("HOA $200 billed quarterly", 66.67), ("HOA fee: $1,000 billed annually", 83.33)])
def test_quarterly_hoa_has_no_not_counted_note(text, hoa):
    r = read(text, buying=True)
    assert r["hoa"] == hoa
    assert "not counted" not in notes(r) and "HOA" not in notes(r)
