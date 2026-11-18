"""Cycle 31 G2: "CORRECTION: the 3BR/2BA ... is $3,125 not $3,225" sets the rent and the note says what changed, never "nothing was changed"."""
import os

import pytest

from prophelper.parsers import parse_listing

P = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel") + "/"


def read(t):
    return parse_listing(t, "")


def notes(r):
    return r.get("found_in_listing", "") or ""


def test_reviewer_l24_saved_listing():
    r = read(open(P + "r30-roommates-l24.txt").read())
    assert r["price"] == 3125
    assert r["deposit"] == 3125
    assert r["other_monthly_fees"] == 60
    assert r["pet_fee"] == 350
    n = notes(r)
    assert "The listing corrects the rent: it is now $3,125. The earlier $3,225 is not used" in n
    assert "Nothing was changed" not in n
    assert "could not match" not in n


@pytest.mark.parametrize("t,new,old", [
    ("CORRECTION: the 3BR/2BA at 2700 S Wabash Ave Chicago IL 60616 is $3,125 not $3,225. Security deposit $3,125.", 3125, 3225),
    ("Correction: the 2 bed is $1,850, not $1,950. Tenant pays utilities.", 1850, 1950),
    ("Sunny 2 bed 1 bath apartment, Oak Park. UPDATE: this unit is now $2,300 (not $2,400).", 2300, 2400),
    ("Correction - rent for the 1BR at 410 W Elm St is $1,700 not $1,800/mo.", 1700, 1800),
    ("CORRECTION\nThe 3BR/2BA at 2700 S Wabash Ave is $3,125 (not $3,225).", 3125, 3225),
    ("Correction: the 2BR is $1,950 per month, was $2,050.", 1950, 2050),
    ("2BR/1BA $2,050/mo at 14 Elm St.\nCorrection: the 2BR is $1,950 not $2,050.", 1950, 2050),
])
def test_unit_correction_sets_rent_and_notes_it(t, new, old):
    r = read(t)
    assert r["price"] == new
    n = notes(r)
    assert f"The listing corrects the rent: it is now ${new:,}." in n
    assert f"The earlier ${old:,} is not used" in n
    assert "Nothing was changed" not in n
    assert "could not match" not in n


def test_unmatched_correction_beside_applied_one_does_not_say_nothing_changed():
    r = read("Rent $2,050. Correction: the 2BR is $1,950 not $2,050. Correction: the zebra widget is $77.")
    assert r["price"] == 1950
    n = notes(r)
    assert "Nothing was changed" not in n
