"""Cycle 32 G2: a step-up rent is read wherever the rent sentence starts and whatever it calls the unit; with step-ups for two
unit sizes the one for this listing's own size is saved and the other is named in one note. Promo wording without a new figure
("months 1-3, then regular rent", "first month only $2,800, then regular rent") gets one plain promo note."""
import os

import pytest

from prophelper.parsers import parse_listing

P = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel") + "/"


def read(t, **kw):
    return parse_listing(t, "", **kw)


def notes(r):
    return r.get("found_in_listing", "") or ""


def test_reviewer_uiuc_l1_saved_listing():
    r = read(open(P + "r31-uiuc-l1.txt").read())
    assert r["price"] == 1495
    assert r["beds"] == 1
    n = notes(r)
    assert "$1,395 a month for the first 6 months, then $1,495" in n
    assert "another lease length" not in n
    assert "not counted anywhere" not in n.split("Typical bills")[0] or "$3,075" not in n.split("not counted anywhere")[0][-80:]
    assert "2 bedroom" in n and "$3,200" in n  # the other unit's step-up is named once
    assert n.count("$3,075") == 1


def test_reviewer_uiuc_l8_saved_listing_still_reads():
    r = read(open(P + "r31-uiuc-l8.txt").read())
    assert r["price"] == 1495
    assert "$1,395 a month for the first 6 months, then $1,495" in notes(r)


@pytest.mark.parametrize("t", [
    "Orchard Lane Flats - 1 Bed / 1 Bath\nThe 1 bedroom is $1,395 for the first 6 months, then $1,495.\nDeposit $500.",
    "Orchard Lane Flats - 1 Bed / 1 Bath\nOur one-bedroom units are $1,395 for the first 6 months, then $1,495 per month.\nDeposit $500.",
    "Orchard Lane Flats | 1 Bed 1 Bath | The 1BR is $1,395 for the first 6 months; then $1,495/mo | Deposit $500",
    "Orchard Lane Flats - 1 Bed / 1 Bath\nRight now this home is $1,395 for the first six months, and then it is $1,495.\nDeposit $500.",
    "Orchard Lane Flats - 1 Bed / 1 Bath\nTour today! A 1 bed apartment is $1,395 for the first 6 months, then $1,495. Deposit $500.",
    "Orchard Lane Flats - 1 Bed / 1 Bath\n- Rent for the 1 bedroom: $1,395 for the first 6 months, then $1,495\n- Deposit $500",
    "ORCHARD LANE FLATS 1 BED 1 BATH. THE 1 BEDROOM IS $1,395 FOR THE FIRST 6 MONTHS, THEN $1,495. DEPOSIT $500.",
])
def test_leading_clause_step_up_keeps_the_steady_rent(t):
    r = read(t)
    assert r["price"] == 1495
    assert r["beds"] == 1
    assert r["deposit"] == 500
    n = notes(r)
    assert "$1,395" in n and "first 6" in n.lower().replace("six", "6")
    assert "another lease length" not in n
    assert "not counted anywhere" not in n


@pytest.mark.parametrize("t", [
    "Orchard Lane - 1 Bed / 1 Bath\n$2,075 for the first 6 months, then $2,200 -- that's the 2 bed. The 1 bedroom is $1,395 for the first 6 months, then $1,495.",
    "Orchard Lane - 1 Bed / 1 Bath\nThe 2 bedroom is $2,075 for the first 6 months, then $2,200. The 1 bedroom is $1,395 for the first 6 months, then $1,495.",
    "Orchard Lane - 1 Bed / 1 Bath\nThe 1 bedroom is $1,395 for the first 6 months, then $1,495. The 2 bedroom is $2,075 for the first 6 months, then $2,200.",
    "Orchard Lane - 1 Bed / 1 Bath\n2 bedroom: $2,075 for the first 6 months, then $2,200\n1 bedroom: $1,395 for the first 6 months, then $1,495",
    "Orchard Lane | 1 Bed 1 Bath | 1BR $1,395 first 6 months then $1,495 | 2BR $2,075 first 6 months then $2,200",
    "Orchard Lane - 1 Bed / 1 Bath\n(2BR is $2,075 for the first 6 months, then $2,200.)\nThe 1BR is $1,395 for the first 6 months, then $1,495.",
])
def test_two_unit_step_ups_pick_the_listing_s_own_size(t):
    r = read(t)
    assert r["price"] == 1495
    assert r["beds"] == 1
    n = notes(r)
    assert "$1,395 a month for the first 6 months, then $1,495" in n
    assert "2 bed" in n.lower() and "$2,200" in n
    assert n.count("$2,200") == 1
    assert "not counted anywhere" not in n
    assert "another lease length" not in n


def test_two_unit_step_ups_for_a_two_bedroom_listing():
    r = read("Orchard Lane - 2 Bed / 1 Bath\nThe 1 bedroom is $1,395 for the first 6 months, then $1,495. The 2 bedroom is $2,075 for the first 6 months, then $2,200.")
    assert r["price"] == 2200
    assert r["beds"] == 2
    n = notes(r)
    assert "$2,075 a month for the first 6 months, then $2,200" in n
    assert "$1,495" in n and n.count("$1,495") == 1


def test_two_unit_step_ups_without_a_bedroom_count_leave_the_rent_empty():
    r = read("Orchard Lane Flats\nThe 1 bedroom is $1,395 for the first 6 months, then $1,495. The 2 bedroom is $2,075 for the first 6 months, then $2,200.")
    assert r.get("price") in (None, "")
    n = notes(r)
    assert "$1,495" in n and "$2,200" in n


@pytest.mark.parametrize("t,price", [
    ("Orchard Lane - 1 Bed / 1 Bath. The 1 bedroom is $1,395. Application $45. Deposit $500.", 1395),
    ("Orchard Lane - 1 Bed / 1 Bath. Rent $1,395. Garage $350 for the first 3 months, then $400. Deposit $500.", 1395),
    ("Orchard Lane - 1 Bed / 1 Bath. Rent $1,395/mo. Pet rent $35 for the first 3 months, then $75 a month. Deposit $500.", 1395),
])
def test_negatives_no_step_up_in_the_rent(t, price):
    r = read(t)
    assert r["price"] == price
    assert "steady" not in notes(r)


# ---------------------------------------------------------------- "then regular rent" with no new figure
def test_reviewer_nontech_l10_saved_listing():
    r = read(open(P + "r31-nontech-l10.txt").read())
    assert r["price"] == 1490
    assert r["deposit"] == 1490
    n = notes(r)
    assert "months 1-3" in n or "first 3 months" in n
    assert "regular rent" in n
    assert "not counted anywhere" not in n


@pytest.mark.parametrize("t,price,phrase", [
    ("2 Bed 1 Bath. $1,490/month. Rent $1,490 for months 1-3, then regular rent.", 1490, "months 1-3"),
    ("2 Bed 1 Bath. $1,490/month.\n$1,490 for months 1 to 3, then regular rent applies.", 1490, "months 1-3"),
    ("2 Bed 1 Bath | $1,490/mo | Rent is $1,490 for months 1-3 and then regular rent.", 1490, "months 1-3"),
    ("2 Bed 1 Bath. Rent $1,490/month for months 1-3 (then regular rent).", 1490, "months 1-3"),
    ("2 Bed 1 Bath. $1,490/month.\nMonths 1-3: $1,490, then regular rent.", 1490, "months 1-3"),
    ("2 Bed 1 Bath. Rent $1,490/month. For the first 3 months the rent is $1,490, then regular rent.", 1490, "first 3 months"),
])
def test_months_then_regular_rent_gets_a_promo_note(t, price, phrase):
    r = read(t)
    assert r["price"] == price
    n = notes(r)
    assert phrase in n
    assert "regular rent" in n
    assert "not counted anywhere" not in n
    assert "Check what it is for" not in n
    assert n.count("$1,490") <= 1 or "months" in n


def test_reviewer_roommates_l29_saved_listing():
    r = read(open(P + "r31-roommates-l29.txt").read())
    assert r["price"] == 3200
    assert r["move_in_fees"] == 200
    n = notes(r)
    assert "$2,800" in n and "first month" in n
    assert "Check what it is for" not in n
    assert "not counted anywhere" not in n
    assert "monthly fee" not in n


@pytest.mark.parametrize("t,promo", [
    ("Rogers Park 3BR 2BA $3,200. Reg rent $3,200 (first month only $2,800, then regular rent). Deposit $3,200.", "first month"),
    ("Rogers Park 3BR 2BA. Rent $3,200. First month only $2,800, then regular rent. Deposit $3,200.", "first month"),
    ("Rogers Park 3BR 2BA\nRent: $3,200/mo\nSpecial: $2,800 for the first month, then regular rent\nDeposit $3,200", "first month"),
    ("Rogers Park 3BR 2BA | $3,200 | first month only $2,800; then regular rent | Deposit $3,200", "first month"),
    ("Rogers Park 3BR 2BA. Rent $3,200 (the first 2 months are $2,900, then regular rent). Deposit $3,200.", "first 2 months"),
])
def test_first_month_special_then_regular_rent_note_is_plain(t, promo):
    r = read(t)
    assert r["price"] == 3200
    n = notes(r)
    assert promo in n
    assert "regular rent" in n
    assert "Check what it is for" not in n
    assert "not counted anywhere" not in n
    assert "monthly fee" not in n
    assert "will cost" not in n


def test_regular_rent_phrase_without_a_promo_figure_is_silent():
    r = read("2 Bed 1 Bath. Rent $1,490/month. Regular rent applies after the lease renews. Deposit $1,490.")
    assert r["price"] == 1490
    assert "first" not in notes(r).lower()
