"""Cycle 33 G2: promo wording gets one plain note and never lowers or raises the saved rent.
"Months 1-3, then regular rent", "First month only free", "Month one free if you lease by Dec 15" and "first month only $1,999, then $2,350"."""
import os

import pytest

from prophelper.parsers import parse_listing

P = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel") + "/"


def read(t, **kw):
    return parse_listing(t, "", **kw)


def notes(r):
    return r.get("found_in_listing", "") or ""


def fixture(name):
    return open(P + name, encoding="utf-8").read()


# ---------------------------------------------------------------- whole reviewer listings
def test_uiuc_l5_months_1_3_and_first_month_free():
    r = read(fixture("r32-uiuc-l5.txt"))
    n = notes(r)
    assert r["price"] == 1475
    assert r["deposit"] == 500
    assert 'The listing says months 1-3 are a special ("Months 1-3, then regular rent")' in n
    assert "The saved rent is $1,475, which may be the special price." in n
    assert 'a rent concession ("First month only free")' in n
    assert n.count("$1,475") == 1


def test_roommates_l8_months_1_3_before_the_rent():
    r = read(fixture("r32-roommates-l8.txt"))
    n = notes(r)
    assert r["price"] == 3100
    assert 'months 1-3 are a special ("Months 1-3, then regular rent")' in n
    assert "The saved rent is $3,100, which may be the special price." in n


def test_nontech_l14_month_one_free_names_the_condition():
    r = read(fixture("r32-nontech-l14.txt"))
    n = notes(r)
    assert r["price"] == 1495
    assert 'a rent concession ("Month one free if you lease by Dec 15 (12 month lease)")' in n


def test_nontech_l4_figure_then_regular_rent_still_one_note():
    r = read(fixture("r32-nontech-l4.txt"))
    n = notes(r)
    assert r["price"] == 1490
    assert n.count("with no figure") == 1
    assert 'then "regular rent" with no figure' in n
    assert "is a special" not in n and "are a special" not in n


# ---------------------------------------------------------------- the same thing in other wordings (no figure for the first months)
NO_FIGURE = [
    ("2 bed 1 bath. Rent $1,475/mo. Months 1-3, then regular rent.", "months 1-3"),
    ("2 bed 1 bath\nRent $1,475/mo\nMonths 1 to 3: then regular rent", "months 1-3"),
    ("2 bed 1 bath | $1,475/mo | Months 1-3 (then regular rent) | pets ok", "months 1-3"),
    ("2 bed 1 bath. Rent $1,475/mo; first 3 months promo, then the regular rent.", "the first 3 months"),
    ("MONTHS 1-3 SPECIAL, THEN REGULAR RENT. 2 BED 1 BATH. RENT $1,475/MO.", "months 1-3"),
    ("2 bed 1 bath. Rent $1,475/mo. First month only, then regular rent.", "the first month"),
    ("2 bed 1 bath. Rent $1,475/mo. Regular rent starts in month 4.", "month 4"),
    ("Rent $1,475/mo, 2 bed 1 bath. The regular rent applies after the first 3 months.", "the first 3 months"),
]


@pytest.mark.parametrize("t,when", NO_FIGURE)
def test_promo_without_a_figure_gets_one_note_and_the_rent_is_not_changed(t, when):
    r = read(t)
    n = notes(r)
    assert r["price"] == 1475
    assert f"The listing says {when} " in n
    assert "no figure" in n
    assert "The saved rent is $1,475, which may be the special price." in n
    assert n.count("a special") == 1
    assert "not counted anywhere" not in n


@pytest.mark.parametrize("t", [
    "2 bed. Rent $1,475/mo. Is it months 1-3 then regular rent? Ask us.",
    "2 bed. Rent $1,475/mo. Regular rent starts in month 4?",
    "2 bed. Rent $1,475/mo. Typical regular rent is $1,475. First month's rent and deposit due at move-in.",
    "2 bed. Rent $1,475/mo. Pay the regular rent on the first of the month. Months of the lease: 12.",
])
def test_negatives_no_promo_note(t):
    r = read(t)
    assert r["price"] == 1475
    assert "a special" not in notes(r)


# ---------------------------------------------------------------- free months
FREE = [
    ("2 bed. Rent $2,350. First month only free.", "First month only free"),
    ("2 bed. Rent $2,350. Month one free if you lease by Dec 15 (12 month lease).", "Month one free if you lease by Dec 15 (12 month lease)"),
    ("2 bed. Rent $2,350. Month 1 free!", "Month 1 free"),
    ("2 bed\nRent $2,350\nMonths 1 and 2 free", "Months 1 and 2 free"),
    ("2 bed | $2,350 | First two months half price | pets ok", "First two months half price"),
    ("2 bed. Rent $2,350 (1st month free).", "1st month free"),
    ("2 bed. Rent $2,350, first month only free, w/d in unit.", "first month only free"),
]


@pytest.mark.parametrize("t,quote", FREE)
def test_free_months_get_a_concession_note_and_never_lower_the_rent(t, quote):
    r = read(t)
    n = notes(r)
    assert r["price"] == 2350
    assert f'The listing offers a rent concession ("{quote}")' in n
    assert "It is a one-time deal, so it is not taken off the rent." in n
    assert n.count("concession") == 1
    assert "not counted anywhere" not in n


@pytest.mark.parametrize("t", [
    "2 bed. Rent $2,350. Is the first month free? Ask us.",
    "2 bed. Rent $2,350. No free months. First month's rent due at signing.",
])
def test_negatives_no_concession_note(t):
    r = read(t)
    assert r["price"] == 2350
    assert "concession" not in notes(r)


# ---------------------------------------------------------------- a figure for the first month, then a higher rent
FIRST_MONTH_FIGURE = [
    "2 bed 1 bath. Special: first month only $1,999, then $2,350.",
    "2 bed 1 bath. $1,999 for the first month only, then $2,350.",
    "2 bed 1 bath\nFirst month $1,999\nThen $2,350 per month",
    "2 bed 1 bath | first month only $1,999, then $2,350 | pets ok",
    "2 bed 1 bath. FIRST MONTH ONLY $1,999, THEN $2,350.",
    "2 bed 1 bath. 1st month only $1,999 (then $2,350 a month).",
]


@pytest.mark.parametrize("t", FIRST_MONTH_FIGURE)
def test_first_month_figure_then_regular_rent(t):
    r = read(t)
    n = notes(r)
    assert r["price"] == 2350
    assert "The listing gives $1,999 a month for the first month, then $2,350." in n
    assert "first 1 month" not in n
    assert "not counted anywhere" not in n
    assert n.count("$1,999") == 1


def test_first_month_figure_rent_above_the_then_figure_is_not_lowered_silently():
    r = read("2 bed 1 bath. Rent $2,400/mo. Special: first month only $1,999, then $2,350.")
    n = notes(r)
    assert r["price"] == 2400
    assert "$1,999" in n and "$2,350" in n
    assert "The higher $2,400 is saved as the rent" in n
    assert "not counted anywhere" not in n
