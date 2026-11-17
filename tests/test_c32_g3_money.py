"""Cycle 32 group G3: move-in lines are lists (rule t), plain Deposit, deposit ranges, a bare monthly Fee, other-kind pet charges, one parking question note."""
import os

import pytest

from prophelper.parsers import parse_listing

HERE = os.path.join(os.path.dirname(__file__), "fixtures", "panel")


def P(text, **kw):
    return parse_listing(text, "", **kw)


def F(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as fh:
        return fh.read()


def notes(r):
    return r.get("found_in_listing") or ""


TOTAL = "in total to move in"


# ---- rule t: a move-in line that lists items is never a total
@pytest.mark.parametrize("text", [
    "Rent $1,480. Move-in costs: $1,480 first month + $1,480 deposit.",
    "Rent $1,480. Move-in costs: $1,480 first month and $1,480 deposit.",
    "Rent $1,480. Move-in costs: $1,480 first month, $1,480 deposit.",
    "Rent $1,480\nMove-in costs: $1,480 first month\n+ $1,480 deposit\n",
    "Rent $1,480. Move-in costs: $1,480 deposit plus first month's rent",
    "Rent $1,480 | Move-in costs: $1,480 first month + $1,480 deposit | 2 bed",
    "Rent $1,480. MOVE-IN COSTS: $1,480 FIRST MONTH + $1,480 DEPOSIT.",
])
def test_move_in_list_is_not_a_total(text):
    r = P(text)
    assert TOTAL not in notes(r)
    assert r["deposit"] == 1480


def test_nontech_l12_whole_listing():
    r = P(F("r31-nontech-l12.txt"))
    assert TOTAL not in notes(r)
    assert r["deposit"] == 1480 and r["pets"] == "cats" and r["pet_deposit"] == 200


@pytest.mark.parametrize("text", [
    "Rent $1,480. Move-in costs: $250 non-refundable cat fee.",
    "Rent $1,480. Move-in costs: $250 non-refundable cat fee",
    "Rent $1,480\nMove-in costs: $250 non-refundable cat fee\n",
    "Rent $1,480. Move-in costs: a $250 non-refundable cat fee.",
    "Rent $1,480. Move-in costs - $250 non-refundable cat fee.",
])
def test_one_named_item_is_not_a_total_and_keeps_non_refundable(text):
    r = P(text)
    assert TOTAL not in notes(r)
    assert r["pet_fee"] == 250
    assert "not refundable" in notes(r)


def test_uiuc_l2_whole_listing_one_note_for_the_cat_fee():
    r = P(F("r31-uiuc-l2.txt"))
    assert TOTAL not in notes(r)
    assert r["pet_fee"] == 250 and r["application_fee"] == 40
    assert notes(r).count("$250") <= 2


@pytest.mark.parametrize("text", [
    "Rent $1,480. Move-in costs: $2,960 total.",
    "Rent $1,480. Move-in costs: $2,960",
    "Rent $1,480. Move in cost 2200 total",
    "Rent $1,480. Move-in costs: $2,960 (first month + deposit)",
])
def test_negatives_a_real_total_still_gets_the_note(text):
    assert TOTAL in notes(P(text))


# ---- plain "Deposit $N."
@pytest.mark.parametrize("text", [
    "Rent $3,199. Cat fee $200 non-refundable. Deposit $1,500. Broker fee $3,199.",
    "Rent $3,199. Pet fee $200 non-refundable. Deposit $1,500.",
    "Rent $3,199. Cat fee $200 non-refundable.\nDeposit $1,500.",
    "Rent $3,199. Cat fee $200 non-refundable; Deposit $1,500",
    "Rent $3,199. Deposit $1,500. Cat fee $200 non-refundable.",
    "Rent $3,199 | Cat fee $200 non-refundable | Deposit: $1,500",
    "Rent $3,199. Deposit $1,500.",
])
def test_plain_deposit_beside_a_non_refundable_cat_fee(text):
    r = P(text)
    assert r["deposit"] == 1500
    assert r.get("pet_deposit") in (None, 0)
    if "200" in text:
        assert r["pet_fee"] == 200


def test_roommates_l33_whole_listing():
    r = P(F("r31-roommates-l33.txt"))
    assert r["deposit"] == 1500 and r["pet_fee"] == 200 and r["pets"] == "cats" and r["broker_fee"] == 3199 and r["parking_cost"] == 175


def test_negatives_pet_side_deposit_in_its_own_sentence_stays_pet():
    r = P("Rent $3,199. Cats ok. $250 deposit non-refundable.")
    assert r.get("pet_fee") == 250 and r.get("deposit") in (None, 0.0)
    r = P("Rent $3,199. Deposit $1,500. Pet deposit $300.")
    assert r["deposit"] == 1500 and r["pet_deposit"] == 300


# ---- deposit ranges
@pytest.mark.parametrize("text, lo, hi", [
    ("Rent $2,000. Deposit range $1,000 - $3,225.", 1000, 3225),
    ("Rent $2,000. Deposit range: $1,000 to $3,225 depending on credit.", 1000, 3225),
    ("Rent $2,000. Deposit: $300 to $600.", 300, 600),
    ("Rent $2,000\nSecurity deposit $300 to $600\n", 300, 600),
    ("Rent $2,000. Deposit between $500 and $1,500 based on credit.", 500, 1500),
    ("Rent $2,000. Deposit ranges from $500 to $1,500.", 500, 1500),
    ("Rent $2,000. DEPOSIT RANGE $1,000 - $3,225", 1000, 3225),
])
def test_deposit_range_saves_the_low_end_and_says_at_least(text, lo, hi):
    r = P(text)
    assert r["deposit"] == lo
    assert "at least that much" in notes(r)
    assert f"${lo:,}" in notes(r) and f"${hi:,}" in notes(r)
    assert "Check what it is for" not in notes(r)


def test_roommates_l28_whole_listing_deposit_range():
    r = P(F("r31-roommates-l28.txt"))
    assert r["deposit"] == 1000 and r["pet_deposit"] == 300 and r["pet_rent"] == 35
    assert "at least that much" in notes(r)


def test_negatives_deposit_range_not_for_other_deposits_or_two_items():
    r = P("Rent $2,000. Pet deposit $200 - $400. Deposit $1,500.")
    assert r["deposit"] == 1500 and "at least that much" not in notes(r)
    r = P("Rent $2,000. Deposit $500 and $200 key deposit.")
    assert "at least that much" not in notes(r)


# ---- a bare "Fee: $N monthly" is a monthly fee
@pytest.mark.parametrize("text", [
    "Rent $1,325. 2BR. Fee: $185 monthly (valet trash & amenity package)",
    "Rent $1,325. 2BR. Fee: $185/mo (valet trash & amenity package)",
    "Rent $1,325. 2BR. Fee: $185 monthly.",
    "Rent $1,325. 2BR.\nFee: $185 per month (valet trash, amenity package)\n",
    "Rent $1,325 | Fee: $185 a month | 2BR",
    "Rent $1,325. FEE: $185 MONTHLY (VALET TRASH & AMENITY PACKAGE)",
])
def test_bare_monthly_fee_is_counted_once(text):
    r = P(text)
    assert r["other_monthly_fees"] == 185
    assert len([ln for ln in notes(r).split("\n") if "$185" in ln]) == 1
    assert "not counted anywhere" not in notes(r)


def test_nontech_l7_whole_listing_fee_counted():
    r = P(F("r31-nontech-l7.txt"))
    assert r["other_monthly_fees"] == 185 and r["deposit"] == 400 and r["pet_rent"] == 35 and r["pet_weight_limit"] == 40
    assert "not counted anywhere" not in notes(r).split("Fee: $185")[-1][:80] if "Fee: $185" in notes(r) else True


@pytest.mark.parametrize("text", [
    "Rent $1,325. 2BR. Optional fee: $185 monthly (valet trash & amenity package)",
    "Rent $1,325. 2BR. Fee: $185 one-time (amenity package)",
    "Rent $1,325. 2BR. Fee: $185 (valet trash & amenity package)",
    "Rent $1,325. 2BR. Application fee: $50 monthly",
])
def test_negatives_bare_fee_not_counted_when_optional_one_time_or_no_period(text):
    r = P(text)
    assert r.get("other_monthly_fees") in (None, 0)


# ---- a fee named for the other kind of pet is not counted
@pytest.mark.parametrize("text", [
    "Rent $1,500. 2 bed. Cats ok. $300 non-refundable cat fee.",
    "Rent $1,500. 2 bed. Cats welcome. Cat fee $300.",
    "Rent $1,500. 2 bed. Cats ok\nCat fee: $300\n",
    "Rent $1,500. 2 bed. Cats ok | $300 cat fee",
])
def test_cat_fee_is_not_counted_for_a_dog_search(text):
    r = P(text, pet_kind="dog")
    assert r.get("pet_fee") in (None, 0)
    assert "$300 cat fee" in notes(r) and "not counted" in notes(r)
    r = P(text, pet_kind="cat")
    assert r["pet_fee"] == 300
    r = P(text)
    assert r["pet_fee"] == 300


def test_cat_fee_negatives():
    r = P("Rent $1,500. Pets ok. Cat fee $300. Pet fee $300.", pet_kind="dog")
    assert r["pet_fee"] == 300
    r = P("Rent $1,500. Cats and dogs ok. Cat fee $300.", pet_kind="both")
    assert r["pet_fee"] == 300
    r = P("Rent $1,500. Pets ok. $300 pet fee.", pet_kind="dog")
    assert r["pet_fee"] == 300
    r = P("Rent $1,500. Dogs ok. Dog fee $300.", pet_kind="dog")
    assert r["pet_fee"] == 300


def test_dogs_500_pet_deposit_is_a_deposit():
    for text in ("Rent $1,500. Dogs $500 pet deposit.", "Rent $1,500. Pet policy: dogs $500 pet deposit", "Rent $1,500. Dogs ok. $500 pet deposit for dogs.",
                 "Rent $1,500\nDogs $500 pet deposit\n"):
        r = P(text)
        assert r["pet_deposit"] == 500 and r.get("pet_fee") in (None, 0) and r["pets"] == "dogs", text


# ---- one parking note for a question
@pytest.mark.parametrize("text", [
    "Price: $1,590 /mo. Washer & dryer included, dishwasher included, covered parking available at $50 per installment of rent? Ask.",
    "Rent $1,590. Is covered parking available at $50 a month? Ask us.",
    "Rent $1,590. Washer & dryer included, dishwasher included, garage parking at $75/mo available? Please call.",
    "Rent $1,590\nDoes the garage cost $90 per month? Please ask.\n",
    "Rent $1,590. Covered parking $50/mo. Is a second space available at $60?",
    "Rent $1,590 | Is covered parking $50 a month? Ask | 2 bed",
])
def test_a_parking_question_gets_one_note(text):
    r = P(text)
    assert len([ln for ln in notes(r).split("\n") if "parking" in ln.lower()]) == 1
    assert "looks optional" not in notes(r) and "not counted anywhere" not in notes(r)
    assert r.get("parking_cost") in (None, 50, 0) and "garage" not in (r.get("parking") or "")


def test_uiuc_l7_whole_listing_single_parking_note():
    r = P(F("r31-uiuc-l7.txt"))
    assert len([ln for ln in notes(r).split("\n") if "parking" in ln.lower()]) == 1
    assert r.get("parking") in (None, "") and r.get("parking_cost") is None
    assert r["application_fee"] == 30 and r["pet_deposit"] == 300
