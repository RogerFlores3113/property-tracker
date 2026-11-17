"""Cycle 33, G4: a stated total of counted items and a promo figure never get "not counted anywhere" or "Only $N of that" (family l12, nontech l13)."""
from __future__ import annotations

import os

import pytest

from prophelper import parsers as P

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel")


def fixture(name: str) -> str:
    with open(os.path.join(FIX, name), encoding="utf-8") as fh:
        return fh.read()


def read(text: str) -> dict:
    return P.parse_listing(text, "")


def notes(r: dict) -> str:
    return r.get("found_in_listing") or ""


# ---- a stated total that is the sum of counted items
HEAD = "3 bed 2 bath ranch, Foster City. Rent $2,325. "


@pytest.mark.parametrize("line", [
    "Move-in: first month rent, deposit $2,325, $150 key fee = total $4,800.",
    "Move-in: first month rent, deposit $2,325 and $150 key fee, total $4,800.",
    "Move-in: first month rent + deposit $2,325 + $150 key fee = $4,800 total.",
    "Move-in: first month rent, deposit $2,325, $150 key fee (total $4,800).",
    "Move-in: first month rent, deposit $2,325, $150 key fee. Total due at move-in: $4,800.",
    "Move-in: first month rent\nDeposit $2,325\nKey fee $150\nTotal $4,800",
    "Move-in costs | first month rent | deposit $2,325 | $150 key fee | total $4,800",
    "MOVE-IN: FIRST MONTH RENT, DEPOSIT $2,325, $150 KEY FEE = TOTAL $4,800.",
])
def test_total_of_counted_items(line):
    r = read(HEAD + line)
    n = notes(r)
    assert r["price"] == 2325 and r["deposit"] == 2325 and r["move_in_fees"] == 150, n
    assert "not counted anywhere" not in n and "Only $" not in n, n
    assert "$4,800" in n and "total" in n.lower(), n
    assert "Check what it is for" not in n or "$4,800" not in n.split("Check what it is for")[0].split("\n")[-1], n


def test_family_l12_whole_listing():
    r = read(fixture("r32-family-l12.txt"))
    n = notes(r)
    assert r["price"] == 2325 and r["deposit"] == 2325 and r["move_in_fees"] == 150
    assert "not counted anywhere" not in n and "Only $4,800" not in n
    assert "The listing gives a total of $4,800. It matches the rent, deposit and fees that are read and counted" in n
    assert r["title"] == "3 bed 2 bath ranch, Foster City" and r["city"] == "Foster City"


@pytest.mark.parametrize("line", [
    "Move-in: $2,300 total ($1,150 + $1,150)",
    "Move-in: $2,300 total (first month $1,150 + deposit $1,150).",
    "Total to move in: $2,300 (rent $1,150 and deposit $1,150).",
    "Move-in total: $2,300; that is rent and deposit.",
])
def test_total_with_its_items(line):
    r = read("2 BR / 1 BA Duplex. Rent $1,150/mo. Deposit $1,150.\n" + line)
    n = notes(r)
    assert r["price"] == 1150 and r["deposit"] == 1150
    assert "not counted anywhere" not in n and "Check what it is for" not in n, n


def test_nontech_l13_whole_listing():
    r = read(fixture("r32-nontech-l13.txt"))
    n = notes(r)
    assert r["price"] == 1150 and r["deposit"] == 1150 and r["utilities_estimate"] == 200
    assert "not counted anywhere" not in n and "Check what it is for" not in n
    assert "total of $2,300" in n


def test_a_total_that_matches_nothing_stays_a_note():
    r = read(HEAD + "Move-in: first month rent, deposit $2,325, $150 key fee = total $5,900.")
    n = notes(r)
    assert "$5,900" in n and "matches" not in n


def test_a_total_that_is_one_item_is_not_a_sum():
    r = read("2 bed. Rent $1,150/mo. Total $1,150 per month.")
    assert "matches the rent, deposit" not in notes(r)


# ---- a promo figure
BASE = "2 bed 1 bath. Rent $2,350. "


@pytest.mark.parametrize("line", [
    "Special: first month only $1,999, then $2,350.",
    "Promo: pay just $1,999 for month one!",
    "Introductory rate $1,999 for the first 2 months.",
    "Limited time: first month $1,999 (regular $2,350).",
    "Special\nFirst month only $1,999, then $2,350",
    "SPECIAL: FIRST MONTH ONLY $1,999, THEN $2,350.",
    "Move-in special | first month only $1,999 | then $2,350",
])
def test_promo_figure_is_named_as_a_promo(line):
    r = read(BASE + line)
    n = notes(r)
    assert r["price"] == 2350
    assert "$1,999" in n, n
    assert "not counted anywhere" not in n and "Only $" not in n, n
    assert "promo price" in n or "special" in n.lower(), n


def test_promo_negatives_keep_their_old_notes():
    # a first month's rent in a move-in list is not a promo, and an unrelated stray fee still says what it says
    r = read(BASE + "Move-in costs: first month's rent and a $60 mystery charge.")
    n = notes(r)
    assert "promo" not in n
    r = read(BASE + "Pet fee $300 non-refundable.")
    assert "promo" not in notes(r)


def test_special_assessment_is_never_a_promo():
    from prophelper.parsers import _uncounted_kind_sentence, PROMO_SENTENCE
    for phrase in ("Dues: $450 per month plus special assessment $12,000 for elevator",
                   "special assessment of $8,000 due at closing",
                   "Buyer pays closing costs of $4,000"):
        assert _uncounted_kind_sentence(phrase) != PROMO_SENTENCE
