"""Cycle 25 group 3: questions set nothing, a free spot beside a priced upgrade, parking in an all-caps pipe layout is not also a fee,
$0 spots and $0 ranges, deeded spaces, pet weight limits that can be waived, "pet rent not charged"."""
import pytest

from prophelper import compare, money
from prophelper import parsers as P
from prophelper.parsers import parse_listing

BASE = "2 bed 1 bath, $1,350 a month. "


def read(text, **kw):
    return parse_listing(BASE + text, **kw)


def notes(r):
    return r.get("found_in_listing", "")


def _missing(text, mode="rent"):
    r = parse_listing(text, "", buying=(mode == "buy"))
    place = dict(r, reader_notes=r.get("found_in_listing"), listing_text=text)
    c = money.true_monthly_cost(place, mode)
    return r, compare._missing_names(dict(place, cost=c, score={"unknown": []}))


# 1. questions set nothing
@pytest.mark.parametrize("text", [
    "Is parking included? Pets? Please ask.",
    "Is there parking? Are pets allowed? Please ask.",
    "Parking included? Cats ok? Ask us about both.",
    "Pets? Parking?",
])
def test_questions_set_no_parking_or_pet_facts(text):
    r = read(text)
    for k in ("parking", "parking_cost", "pets", "pet_rent", "pet_fee", "pet_deposit"):
        assert k not in r, (k, r)
    assert "only asks about" in notes(r)


def test_reviewer_nontech_l22_whole_listing():
    r = parse_listing("Zumper listing: Beechwold 2BR, $1,495/month. Is parking included? Pets? Please ask. Rent is $1,495 and security deposit is $1,495. "
                      "The unit may be about $1,395 for a limited time. HOA fee $120/mo (included in rent). Cats allowed, pet fee: $200 one-time, then $15/month. "
                      "Utilities: tenant pays electric about USD 80. ", "")
    assert "parking" not in r and "parking_cost" not in r
    assert r["price"] == 1495
    assert r["pets"] == "cats" and r["pet_fee"] == 200 and r["pet_rent"] == 15  # the statements that are not questions still count


def test_a_question_does_not_remove_a_statement_next_to_it():
    r = read("Dogs welcome? Please ask. Parking: lot, $0.")
    assert "pets" not in r
    assert r["parking"] == "lot" and r["parking_cost"] == 0


def test_yard_question_sets_nothing():
    r = read("Is the yard fenced? Cats ok.")
    assert "fenced_yard" not in r
    assert r["pets"] == "cats"


# 2. a free spot beside a priced upgrade
@pytest.mark.parametrize("text", [
    "Parking: Surface lot $0. Reserved covered spot $65/mo.",
    "Surface lot $0 | Reserved covered spot $65/mo",
    "Parking: surface lot free; covered parking $65/month",
    "Parking - Free surface lot | Garage $65/mo",
    "Free parking in the lot. Garage spaces $65 per month.",
    "Parking: lot (free), premium garage spot $65/mo",
    "- Parking: Open lot, no charge\n- Reserved spot: $65/mo",
])
def test_free_spot_beside_priced_upgrade_is_the_parking(text):
    r = read(text)
    assert r["parking_cost"] == 0
    assert r["parking"] in ("lot", "street")
    assert "$65" in notes(r) and "optional" in notes(r)
    assert notes(r).count("$65") == 1
    assert "other_monthly_fees" not in r


def test_reviewer_nontech_l19_whole_listing():
    r = parse_listing("Apartments.com\nThe Maple at Short North — 2 Bedroom\nRent: $1,475 - $1,525 | Deposit: $250 | Admin Fee: $175.50\n"
                      "Pets: Cats allowed. One-time pet fee $350 (non-refundable). Monthly pet rent $20.\nParking: Surface lot $0. Reserved covered spot $65/mo.\n"
                      "Utilities: Water/sewer/trash flat fee $62.75/mo. Electric by resident.\nSpecials: 1 month free on a 14 month lease! Lease terms 12, 14 months.", "")
    assert r["parking_cost"] == 0 and r["parking"] == "lot"


def test_a_lone_priced_garage_still_counts():
    r = read("Parking: Garage $150/mo")
    assert r["parking"] == "garage" and r["parking_cost"] == 150


# 3. a figure sits in one field only
@pytest.mark.parametrize("text", [
    "HYDE PARK 3BR | $3,150/MO | HEAT & WATER INCLUDED | INTERNET THROUGH COMCAST - NOT INCLUDED | PARKING: $175/MO REQUIRED | SECURITY DEPOSIT $3,150",
    "Parking: $175/mo required. Internet: through Comcast, not included",
    "Internet through Xfinity not included, parking required $175/month",
    "- Internet: not included\n- Parking: $175/mo required",
])
def test_parking_is_not_also_another_monthly_fee(text):
    r = parse_listing(text, "")
    assert r["parking_cost"] == 175
    assert "other_monthly_fees" not in r


def test_required_internet_fee_still_counts_on_its_own_pipe_item():
    r = parse_listing("3BR $2,000/mo | Internet required $60/mo | Parking: lot, $0", "")
    assert r.get("other_monthly_fees") == 60


# 4. $0 spots and ranges, deeded spaces
@pytest.mark.parametrize("text", [
    "Parking: 1 off-street spot, $0",
    "Parking: 1 off-street spot $0",
    "1 off-street parking space, $0",
    "- Parking: one covered spot, $0",
])
def test_zero_dollar_spot_is_zero_not_missing(text):
    r = read(text)
    assert r["parking_cost"] == 0
    assert r.get("parking")


def test_reviewer_roommates_l77_not_missing_parking():
    r, missing = _missing("Ukrainian Village 3BR/2BA, $3,225. Landlord pays heat; tenant pays electric (avg $70) & water (avg $38, billed quarterly at $114). "
                          "No pets. Parking: 1 off-street spot, $0. Deposit: 1 month ($3,225).")
    assert r["parking_cost"] == 0
    assert not any("parking" in m for m in missing)


@pytest.mark.parametrize("text", [
    "Parking available $0 - $250 depending on spot.",
    "Parking: $0-$250/mo depending on the spot",
    "- Parking $0 to $250 a month, depending on spot",
])
def test_zero_to_range_parking_is_unknown_with_one_note(text):
    r, missing = _missing(BASE + text)
    assert "parking_cost" not in r
    assert notes(r).count("$250") == 1 and "$0" in notes(r)
    assert not any("$0" in m or "$250" in m for m in missing)


def test_range_above_zero_counts_the_higher_figure():
    r = read("Parking: $50 - $100 depending on spot")
    assert r["parking_cost"] == 100
    assert "$50" in notes(r) and "$100" in notes(r)


@pytest.mark.parametrize("text", [
    "Includes 1 deeded parking space.",
    "Parking: 1 deeded space included.",
    "One deeded parking space is included.",
])
def test_buyer_deeded_space_is_not_a_missing_parking_cost(text):
    r, missing = _missing("Condo $305,000. 2 beds 2 baths. HOA $340/month. " + text, "buy")
    assert not any("parking" in m for m in missing), missing
    assert "deeded" in notes(r)


# 5. pet weight caveats
@pytest.mark.parametrize("text", [
    "No pets over 40 lb without approval.",
    "Dogs welcome. Dogs up to 40 lb; larger with approval.",
    "Dogs under 40 lb. Exceptions considered.",
    "Weight limit 40 lb, exceptions may be granted.",
    "Pets: no dogs over 40 lbs unless approved.",
    "Dogs ok up to 40 lbs, larger dogs need management approval.",
])
def test_weight_limit_with_approval_says_it_can_be_waived(text):
    r = read(text)
    assert r["pet_weight_limit"] == 40
    assert "can be waived with approval" in notes(r)


def test_weight_limit_without_waiver_has_no_waiver_note():
    r = read("Dogs welcome. No dogs over 40 lb.")
    assert r["pet_weight_limit"] == 40
    assert "waived" not in notes(r)


@pytest.mark.parametrize("text", [
    "Dogs welcome. No pets over 40 lb without approval.",
    "Dogs up to 40 lb; larger with approval.",
    "Dogs ok. No dogs over 40 lbs unless approved.",
])
def test_a_60_lb_dog_is_ask_not_a_flat_fail(text):
    from prophelper import scoring
    r = read(text)
    place = dict(r, listing_text=BASE + text, reader_notes=r.get("found_in_listing"))
    assert scoring._limit_can_be_waived(place)
    res = scoring._pet_limit_problems({"kind": "dog", "weight": 60}, place)
    assert res  # the limit is below the dog, and the waiver makes it an ask instead of a fail


# 6. pet rent not charged, and no verbatim repeat of the pet fee line
@pytest.mark.parametrize("text", [
    "Cats ok. Pet rent not charged.",
    "Cats and dogs OK, pet deposit refundable $400. Pet rent: not charged.",
    "Dogs allowed. We do not charge pet rent. Pet fee $200.",
    "Cats ok, pet rent is not required.",
])
def test_pet_rent_not_charged_is_zero(text):
    r = read(text)
    assert r["pet_rent"] == 0


def test_pet_rent_not_charged_for_one_pet_only_is_not_zero():
    r = read("Cats ok, pet rent not charged for the first pet, $20 for the second.")
    assert r.get("pet_rent") != 0


def test_reviewer_family_l3_pet_rent_zero():
    r = parse_listing("3 bd 2 ba house 920 Cedar Ln, Redwood City. $2,375/mo. Yard fenced. Cats and dogs OK, no more than 2 pets, no breed restrictions, "
                      "pet deposit refundable $400. Pet rent not charged. Tenant pays PG&E and water (quarterly water bill about $270).", "")
    assert r["pet_rent"] == 0 and r["pet_deposit"] == 400 and r["pet_count_limit"] == 2


@pytest.mark.parametrize("text", [
    "Pet fee: $300 one-time, then $35/mo per pet, up to 2 pets.",
    "Pets: $300 one-time fee, then $35/mo per pet, max 2 pets.",
    "- Pet fee $300 one-time\n- Pet rent $35/mo per pet\n- up to 2 pets",
])
def test_pet_fee_line_is_not_repeated_in_the_notes(text):
    r = read("Cats allowed. " + text)
    assert r["pet_fee"] == 300 and r["pet_rent"] == 35 and r["pet_count_limit"] == 2
    assert "$300 one-time" not in notes(r)
