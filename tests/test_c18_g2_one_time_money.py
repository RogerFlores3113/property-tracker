"""Cycle 18 G2: one-time money (pet fee, application, conditional deposit, first/last each, per-adult sentence)."""
import pytest

from prophelper import money
from prophelper.parsers import app_fee_note_for_people, parse_listing


def notes(r):
    return r.get("found_in_listing", "")


@pytest.mark.parametrize("text", [
    "2BR $1,380. Cats welcome (up to 2), $35 per cat monthly. Pet fee $250 per pet. Application $40.",
    "2BR $1,380. Cats ok. Pet fee: $250 per pet. Application: $40",
    "2BR $1,380.\n- Cats ok\n- Pet fee $250 per pet\n- Application $40",
])
def test_pet_fee_and_application_are_fields(text):
    r = parse_listing(text)
    assert r["pet_fee"] == 250 and r["application_fee"] == 40
    assert "not counted anywhere" not in notes(r)


def test_monthly_word_before_pet_fee_does_not_make_it_rent():
    r = parse_listing("2BR $1,380. Cats ok, $35 per cat monthly. Pet fee $250 per pet.")
    assert r["pet_rent"] == 35 and r["pet_fee"] == 250


@pytest.mark.parametrize("text", [
    "Garfield Park 3-bed 2-bath $2,400. Deposit one month. $1,200 security deposit if credit is poor.",
    "Garfield Park 3-bed 2-bath $2,400\nDeposit one month\nSecurity deposit $1,200 if credit is poor",
    "Garfield Park 3-bed 2-bath $2,400 - deposit one month ($1,200 security deposit when credit is weak)",
])
def test_conditional_deposit_is_a_note_not_the_deposit(text):
    r = parse_listing(text)
    assert r["deposit"] == 2400
    assert "$1,200" in notes(r) and "Ask what your deposit will be" in notes(r)


def test_conditional_deposit_alone_leaves_deposit_empty():
    r = parse_listing("2BR $1,500. $800 security deposit if credit is poor.")
    assert "deposit" not in r and "$800" in notes(r)


@pytest.mark.parametrize("text", [
    "Beverly 3 bed 2 bath house $2,700. First, last and security deposit required ($2,800 each).",
    "Beverly 3 bed 2 bath house $2,700\nFirst, last and security deposit required: $2,800 each",
    "Beverly 3 bed 2 bath house $2,700. $2,800 each for first, last and security deposit.",
])
def test_first_last_and_deposit_each(text):
    r = parse_listing(text)
    assert r["deposit"] == 2800 and r["months_up_front"] == 2
    assert "$5,600" in notes(r)
    cash = money.cash_at_move_in({**r, "listing_text": text})
    assert cash["total"] == 8400
    assert [p["amount"] for p in cash["parts"]] == [2800, 2800, 2800]


def test_per_adult_sentence_goes_on_the_application_note_only():
    r = parse_listing("3 bed house $2,150. Parking permit $40/mo, a second vehicle $25/mo. Application fee $50 per adult. Water quarterly $90. Deposit $2,150.")
    r = app_fee_note_for_people(r, 2)
    lines = notes(r).split("\n")
    hits = [ln for ln in lines if "together" in ln]
    assert len(hits) == 1 and "application fee" in hits[0] and "$100 together" in hits[0]
    assert not lines[-1].endswith("together.") or "application fee" in lines[-1]
