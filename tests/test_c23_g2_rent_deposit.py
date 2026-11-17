"""Cycle 23 G2: floor-plan prices, rent tied to a lease length, non-refundable deposit, deposit in months, key deposit, one per-adult note."""
import os
from pathlib import Path

import pytest

from prophelper.parsers import app_fee_note_for_people, parse_listing

P = Path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel") + "")
B = "12 Oak St, Champaign IL 61820. "


def _saved(name):
    f = P / name
    if not f.exists():
        pytest.skip("saved listing not available")
    return parse_listing(f.read_text())


def _notes(o):
    return o.get("found_in_listing") or ""


# ---- 1. floor plan prices
def test_saved_uiuc_l21():
    o = _saved("r22-uiuc-l21.txt")
    assert o["price"] == 1395 and o["beds"] == 1
    assert "$1,445" in _notes(o) and "$1,250" in _notes(o)


@pytest.mark.parametrize("text,price", [
    ("Tower | 1 Bed | Starting at $1,250\nFloor plans: A1 1BR/1BA 640 sf $1,395; A2 1BR/1BA 702 sf $1,445", 1395),
    ("Tower | 1 Bedroom | Starting at $1,100\nPlans:\nA1 1 bed 1 bath $1,300\nA2 1 bed 1 bath $1,350", 1300),
    ("Tower - 1 BR - Starting at $1,000\n- Plan B 1BR $1,260\n- Plan C 1BR $1,210", 1210),
])
def test_starting_at_uses_matching_plan(text, price):
    o = parse_listing(text + "\n9 Elm St, Champaign IL 61820.")
    assert o["price"] == price
    assert o["beds"] == 1


def test_starting_at_beds_unknown_two_kinds_leaves_rent_empty():
    o = parse_listing("Tower - Starting at $1,000\nPlans: A1 Studio 400 sf $1,100; B1 2BR/2BA 900 sf $1,800\n9 Elm St, Champaign IL 61820.")
    assert o.get("price") is None
    assert "starting at" in _notes(o) and "$1,000" in _notes(o)


def test_starting_at_without_plans_unchanged():
    o = parse_listing("Tower | 1 Bed | Starting at $1,250\n9 Elm St, Champaign IL 61820.")
    assert o["price"] == 1250
    assert "starting at" in _notes(o)


# ---- 2. rent tied to a lease length
def test_saved_nontech_l7():
    o = _saved("r22-nontech-l7.txt")
    # cycle 25: the 12 month price (or the one closest to 12 months) is the rent, never the first one written
    assert o["price"] == 1540 and o["lease_months"] == 12
    assert "$1,490" in _notes(o) and "13 months" in _notes(o)


@pytest.mark.parametrize("text", [
    "2 bed 2 bath. $1,490 for 13 month lease; 12 month lease $1,540.",
    "2 bed 2 bath. Rent: 13 mo: $1,490 / 12 mo: $1,540",
    "2 bed 2 bath. $1,490 (13-month) or $1,540 (12-month)",
    "2 bed 2 bath. $1,490 with a 13 month lease. $1,540 with a 12 month lease.",
])
def test_rent_and_lease_from_first_option(text):
    o = parse_listing(B + text)
    assert o["price"] == 1540 and o["lease_months"] == 12  # cycle 25: the 12 month option, whichever is written first
    assert "$1,490" in _notes(o) and "13 months" in _notes(o)


@pytest.mark.parametrize("text", [
    "2 bed 2 bath. 12 mo: $1,540 / 13 mo: $1,490",
    "2 bed 2 bath. $1,540 (12-month) or $1,490 (13-month)",
    "2 bed 2 bath. $1,540 for a 12 month lease, or $1,490 for a 13 month lease.",
])
def test_first_listed_option_wins(text):
    o = parse_listing(B + text)
    assert o["price"] == 1540 and o["lease_months"] == 12
    assert "$1,490" in _notes(o)


def test_single_lease_rent_unchanged():
    o = parse_listing(B + "2 bed 2 bath. $1,490 for a 12 month lease. $99 admin fee.")
    assert o["price"] == 1490 and o["lease_months"] == 12


# ---- 3. non-refundable deposit
@pytest.mark.parametrize("text", [
    "Security deposit is $400 (not refundable, it is a cleaning fee).",
    "Deposit $400 non-refundable.",
    "$400 non-refundable cleaning deposit.",
    "Security deposit: $400, non refundable.",
])
def test_nonrefundable_deposit_is_move_in_fee(text):
    o = parse_listing("2 bed 1 bath, $1,340/mo. " + B + text)
    assert o["move_in_fees"] == 400
    assert o["deposit"] == 0
    assert "not known" not in _notes(o) and "not counted anywhere" not in _notes(o)


def test_saved_nontech_l9():
    o = _saved("r22-nontech-l9.txt")
    assert o["move_in_fees"] == 400 and o["deposit"] == 0
    assert "$400" in _notes(o)


def test_refundable_deposit_unchanged_and_pet_deposit_not_taken():
    o = parse_listing("2 bed 1 bath, $1,340/mo. " + B + "Security deposit $900. Pet deposit $300 non-refundable.")
    assert o["deposit"] == 900
    assert not o.get("move_in_fees")


# ---- 4. deposit in months
@pytest.mark.parametrize("text", [
    "1.5 months security deposit.",
    "Deposit of one and a half months' rent.",
    "1.5 months' rent deposit.",
    "Security deposit: 1.5 months rent.",
])
def test_deposit_one_and_a_half_months(text):
    o = parse_listing("2 bed 1 bath, $2,000/mo. " + B + text)
    assert o["deposit"] == 3000


def test_saved_roommates_l51():
    o = _saved("r22-roommates-l51.txt")
    assert o["deposit"] == 3900


# ---- 5. key deposit
def test_saved_roommates_l30():
    o = _saved("r22-roommates-l30.txt")
    assert o["deposit"] == 1260 and o["move_in_fees"] == 525
    assert "$75" in _notes(o)  # cycle 28: the key deposit is a move-in fee, so no note sums it into the deposit


@pytest.mark.parametrize("text,dep,fees", [
    ("Security deposit $1,000. $75 key deposit.", 1000, 75),
    ("Key deposit: $75 (refundable). Deposit: $1,000. Admin fee $100.", 1000, 175),
    ("- Security $1,000\n- Key deposit $50", 1000, 50),
])
def test_key_deposit_counted_once_not_spread(text, dep, fees):
    o = parse_listing("2 bed 1 bath, $1,500/mo. " + B + text)
    assert o["deposit"] == dep
    assert o.get("move_in_fees") == fees


def test_key_deposit_alone_stays_in_move_in_fees():
    o = parse_listing("2 bed 1 bath, $1,500/mo. " + B + "Key deposit $75.")
    assert o["move_in_fees"] == 75 and o.get("deposit") is None


def test_fob_deposit_is_not_the_security_deposit():
    o = parse_listing("2 bed 1 bath, $1,500/mo. " + B + "Fob deposit $50 refundable. Deposit $800.")
    assert o["deposit"] == 800


# ---- 6. one per-adult note
def test_saved_nontech_l1_one_application_note():
    o = _saved("r22-nontech-l1.txt")
    assert o["application_fee"] == 65
    assert len([ln for ln in _notes(o).split("\n") if "each adult" in ln or "per adult" in ln]) == 1


@pytest.mark.parametrize("text", [
    "Application fee $45 per adult. Background check $20 per adult.",
    "Application fee $45 each adult. Background check $20 each adult.",
])
def test_one_per_adult_note(text):
    o = parse_listing("2 bed 1 bath, $1,500/mo. " + B + text)
    assert o["application_fee"] == 65
    lines = [ln for ln in _notes(o).split("\n") if "adult" in ln]
    assert len(lines) == 1
    app_fee_note_for_people(o, 2)
    assert "For 2 adults that is $130 together" in o["found_in_listing"]


@pytest.mark.parametrize("text", [
    "Security deposit $2,980 + $400 non-refundable pet fee if applicable.",
    "Security deposit $900. $400 non-refundable pet fee.",
    "Pet deposit $400 non-refundable. Security deposit $900.",
])
def test_nonrefundable_words_elsewhere_do_not_turn_the_security_deposit(text):
    o = parse_listing("2 bed 1 bath, $1,340/mo. " + B + text)
    assert o["deposit"] in (2980, 900)
    assert not o.get("move_in_fees")


def test_nonrefundable_deposit_first_wording():
    o = parse_listing("2 bed 1 bath, $1,340/mo. " + B + "Non-refundable deposit: $400.")
    assert o["move_in_fees"] == 400 and o["deposit"] == 0
