"""Cycle 33 group G3: a pest and trash package is a counted monthly fee, once; a move-in total that lists its items is not a left-out amount."""
import os

import pytest

from prophelper.parsers import parse_listing

HERE = os.path.join(os.path.dirname(__file__), "fixtures", "panel")


def P(text, kind="dog"):
    return parse_listing(text, "", pet_kind=kind)


def F(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as fh:
        return fh.read()


def notes(r):
    return r.get("found_in_listing") or ""


# ---- "Fee: $40 monthly (pest & trash package)" is a monthly fee, counted once (roommates l16)
@pytest.mark.parametrize("t", [
    "Rent $1,700. Fee: $40 monthly (pest & trash package).",
    "Rent $1,700. Pest & trash package $40/month.",
    "Rent $1,700\nFee: $40 monthly (pest control and trash package)\n",
    "Rent $1,700. Monthly pest and trash package fee: $40.",
    "Rent $1,700. Pest & trash $40 per month, required.",
    "Rent $1,700 | Fee: $40 monthly (pest & trash package) | Parking none",
])
def test_pest_trash_package_is_one_monthly_fee(t):
    r = P(t)
    assert r["other_monthly_fees"] == 40
    assert "Only" not in notes(r) and "not counted" not in notes(r)
    assert "tenant_pays" not in r


def test_roommates_l16_whole_listing():
    r = P(F("r32-roommates-l16.txt"))
    assert r["other_monthly_fees"] == 40
    assert "Only" not in notes(r)


# ---- "Trash & pest $12/mo" is counted once, in other monthly fees only (nontech l12)
@pytest.mark.parametrize("t", [
    "Rent $1,700. Trash & pest $12/mo.",
    "Rent $1,700. Trash & pest: $12 per month. Tenant pays electric.",
    "Rent $1,700 | Trash and pest $12/mo | Parking $50",
    "Rent $1,700\nTrash & pest control $12 monthly\n",
    "Rent $1,700. Pest & trash: $12/month.",
    "Rent $1,700. Trash/pest $12 a month.",
])
def test_trash_and_pest_counted_once(t):
    r = P(t)
    assert r["other_monthly_fees"] == 12
    assert "utilities_estimate" not in r and "utility_estimate" not in r
    assert "Only" not in notes(r)


def test_nontech_l12_whole_listing():
    r = P(F("r32-nontech-l12.txt"))
    assert r["other_monthly_fees"] == 12
    assert not any(k.startswith("utilit") and r[k] for k in r if k not in ("found_in_listing",) and isinstance(r[k], (int, float)) and k.startswith("utilit") and k.endswith("estimate"))


# ---- a move-in total that is the rent plus the deposit is not a left-out amount (nontech l13)
@pytest.mark.parametrize("t", [
    "Rent $1,700. Security deposit $1,700. Move-in: $3,400 total (first month + deposit).",
    "Rent $1,700. Security deposit $1,700. Total to move in: $3,400.",
    "Rent $1,700. Deposit $1,700. Total due at move-in: $3,400 (rent $1,700 + deposit $1,700).",
    "Rent $1,700\nDeposit $1,700\nTotal to move in $3,400\n",
    "Rent $1,700. Deposit: $1,700. Total move-in cost: $3,400.",
    "Rent $1,700 | Deposit $1,700 | Move-in total: $3,400",
])
def test_move_in_total_that_adds_up_is_not_a_gap(t):
    r = P(t)
    assert r["price"] == 1700 and r["deposit"] == 1700
    assert "Ask what it includes" not in notes(r)
    assert "Only $3,400" not in notes(r)


def test_nontech_l13_whole_listing():
    r = P(F("r32-nontech-l13.txt"))
    assert "Ask what it includes" not in notes(r)
    assert "Only $" not in notes(r)


@pytest.mark.parametrize("t", [
    "Rent $1,700. Deposit $1,700. Total to move in $5,000.",
    "Rent $1,700. Deposit $1,700. Move-in: $4,100 total.",
])
def test_a_move_in_total_that_does_not_add_up_is_still_a_question(t):
    r = P(t)
    assert "one-time" in notes(r) or "not counted" in notes(r) or "Ask" in notes(r)
