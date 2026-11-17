"""Cycle 33 G2: "Prices reduced again to $3,295" (plural) and a bare "Rent reduced to $1,545" are applied with a note that says "reduced", not "corrects";
"Reduced to $1,440 this week only" is a short offer (the base rent stays and the offer is named); a 1 bed step-up inside a 2BR listing never becomes the 2BR rent."""
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


# ---------------------------------------------------------------- reviewer listings
def test_roommates_l12_prices_reduced_again_is_applied():
    r = read(fixture("r32-roommates-l12.txt"))
    n = notes(r)
    assert r["price"] == 3295
    assert "The listing says the rent was reduced: it is now $3,295. The earlier $3,640 is not used." in n
    assert "not counted anywhere" not in n
    assert "corrects" not in n
    assert n.count("$3,640") == 1


def test_roommates_l7_reduced_again_says_reduced_not_corrects():
    r = read(fixture("r32-roommates-l7.txt"))
    n = notes(r)
    assert r["price"] == 3230
    assert "The listing says the rent was reduced: it is now $3,230. The earlier $3,280 is not used." in n
    assert "corrects the rent" not in n


def test_uiuc_l7_bare_rent_reduced_to_after_new_construction():
    r = read(fixture("r32-uiuc-l7.txt"))
    n = notes(r)
    assert r["price"] == 1545
    assert "The listing says the rent was reduced: it is now $1,545. The earlier $1,560 is not used." in n
    assert "not counted anywhere" not in n


def test_family_l10_price_reduced_again_says_reduced():
    r = read(fixture("r32-family-l10.txt"))
    assert r["price"] == 2295
    n = notes(r)
    assert "The listing says the rent was reduced: it is now $2,295." in n
    assert "corrects the rent" not in n


# ---------------------------------------------------------------- the same thing in other wordings
REDUCED = [
    "2 bed. Rent $1,590/mo. Rent reduced to $1,545.",
    "2 bed. Rent $1,590/mo. Prices reduced again to $1,545!",
    "2 bed. $1,590/mo. PRICES REDUCED AGAIN TO $1,545!",
    "2 bed. $1,590/mo | rent reduced to $1,545 | pets ok",
    "2 bed. $1,590/mo\nPrice lowered to $1,545",
    "2 bed. Rent $1,590/mo. Price reduced to $1,545; pets ok.",
    "Prices reduced again to $1,545. 2 bed. Rent $1,590/mo.",
    "2 bed. Rent $1,590 per month (rent reduced to $1,545 per month).",
]


@pytest.mark.parametrize("t", REDUCED)
def test_reduced_wordings_are_applied_with_a_reduced_note(t):
    r = read(t)
    n = notes(r)
    assert r["price"] == 1545
    assert "The listing says the rent was reduced: it is now $1,545." in n
    assert "The earlier $1,590 is not used." in n
    assert "corrects" not in n and "not counted anywhere" not in n
    assert n.count("$1,590") == 1


def test_a_raised_rent_says_raised():
    r = read("2 bed. $1,390/mo. Rent increased to $1,445.")
    assert r["price"] == 1445
    assert "The listing says the rent was raised: it is now $1,445. The earlier $1,390 is not used." in notes(r)


@pytest.mark.parametrize("t", [
    "2 bed. Rent $1,590/mo. Corrected: rent reduced to $1,545.",
    "2 bed. Rent $1,590/mo. Update: rent is now $1,545.",
])
def test_a_correction_word_keeps_the_corrects_note(t):
    r = read(t)
    assert r["price"] == 1545
    assert "The listing corrects the rent: it is now $1,545." in notes(r)


# ---------------------------------------------------------------- a cut that lasts a few days is an offer
def test_uiuc_l15_this_week_only_keeps_the_base_rent():
    r = read(fixture("r32-uiuc-l15.txt"))
    n = notes(r)
    assert r["price"] == 1490
    assert r["deposit"] == 1490
    assert 'The listing also offers $1,440 a month ("this week only"). That is a short offer, so it is not the rent. The saved rent stays $1,490.' in n
    assert "corrects" not in n and "reduced:" not in n
    assert n.count("$1,440") == 1


SHORT = [
    ("2 bed. Rent $1,490. Reduced to $1,440 this week only.", "this week only"),
    ("2 bed. Rent $1,490. Reduced to $1,440 for this weekend only.", "for this weekend only"),
    ("2 bed. Rent $1,490. Now $1,440 this month only.", "this month only"),
    ("2 bed. Rent $1,490. Reduced to $1,440 for a limited time.", "for a limited time"),
    ("2 bed. Rent $1,490. Reduced to $1,440 today only!", "today only"),
    ("2 bed. Rent $1,490 | Reduced to $1,440 for the next 5 days | pets ok", "for the next 5 days"),
    ("2 bed. Rent $1,490\nReduced to $1,440 (this week only)", "this week only"),
    ("REDUCED TO $1,440 THIS WEEK ONLY. 2 BED. RENT $1,490.", "THIS WEEK ONLY"),
]


@pytest.mark.parametrize("t,cond", SHORT)
def test_short_offer_wordings_keep_the_base_rent(t, cond):
    r = read(t)
    n = notes(r)
    assert r["price"] == 1490
    assert f'The listing also offers $1,440 a month ("{cond}")' in n
    assert "That is a short offer" in n
    assert "not counted anywhere" not in n
    assert n.count("$1,440") == 1


@pytest.mark.parametrize("t", [
    "2 bed. Rent $1,490. Reduced to $1,440. Available this week.",
    "2 bed. Rent $1,490. Reduced to $1,440. Tours this week only.",
    "2 bed. Rent $1,490. Reduced to $1,440 this week.",
    "2 bed. Rent $1,490, reduced again to $1,440 this week!",
])
def test_negatives_a_week_word_without_only_says_when_it_was_cut(t):
    r = read(t)
    assert r["price"] == 1440
    assert "short offer" not in notes(r)


# ---------------------------------------------------------------- a 1 bed step-up in a 2BR listing
def test_nontech_l7_one_bed_step_up_never_becomes_the_two_bed_rent():
    r = read(fixture("r32-nontech-l7.txt"))
    n = notes(r)
    assert r["price"] == 1450
    assert r["beds"] == 2
    assert "The listing also gives a step-up rent for another size (the 1 bedroom: $1,395 for the first 6 months, then $1,495)." in n
    assert "The saved rent is for this listing's own size." in n
    assert "saved as the rent" not in n


@pytest.mark.parametrize("t", [
    "2BR duplex. Rent is $1,450 per month. The 1 bedroom is $1,395 for the first 6 months, then $1,495. Deposit $1,450.",
    "2 bedroom 1 bath\nRent: $1,450/mo\nThe 1 bed is $1,395 for the first 6 months, then $1,495.",
    "2 Bed | $1,450 | the 1 bedroom: $1,395 for the first 6 months, then $1,495 | pets ok",
    "Two bedroom duplex, $1,450 a month. The one bedroom is $1,395 for the first 6 months, then $1,495 (that unit is separate).",
])
def test_one_bed_step_up_other_wordings(t):
    r = read(t)
    assert r["price"] == 1450
    assert "step-up rent for another size" in notes(r)
    assert "The ongoing" not in notes(r)


def test_own_size_step_up_is_still_applied():
    r = read("1 bedroom apartment. Rent $1,395. The 1 bedroom is $1,395 for the first 6 months, then $1,495.")
    assert r["price"] == 1495
    assert "The ongoing $1,495 is saved as the rent" in notes(r)


def test_step_up_with_no_size_named_is_still_applied():
    r = read("Cozy apartment. $1,395 for the first 6 months, then $1,495.")
    assert r["price"] == 1495
