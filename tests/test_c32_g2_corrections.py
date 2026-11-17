"""Cycle 32 G2: a rent correction gives one note that names every earlier rent figure; "reduced again to $X" is applied (and a conditional one is not);
a saved title never keeps a price the rent replaced, even a bracket cut off at the end."""
import os

import pytest

from prophelper.parsers import parse_listing
from prophelper.store import drop_other_price_text, trim_stale_price_title

P = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel") + "/"


def read(t, **kw):
    return parse_listing(t, "", **kw)


def notes(r):
    return r.get("found_in_listing", "") or ""


def test_reviewer_family_l3_saved_listing_has_one_rent_correction_note():
    r = read(open(P + "r31-family-l3.txt").read())
    assert r["price"] == 2310
    n = notes(r)
    assert n.count("The listing corrects") == 1
    assert "corrects itself" not in n
    assert "$2,390" in n and "$2,290" in n
    assert n.count("$2,390") == 1 and n.count("$2,290") == 1
    assert "The listing also says \"Rent" not in n


@pytest.mark.parametrize("t", [
    "Rent $2,290. CORRECTION: rent is $2,310 not $2,390 as first posted.",
    "Rent $2,290. Correction: the rent is $2,310, not $2,390, as first posted.",
    "Rent: $2,290\nCORRECTION: rent is $2,310 (not $2,390).",
    "Rent $2,290; CORRECTION - rent is now $2,310, not $2,390 as first posted",
    "Rent $2,290 | UPDATE: rent is $2,310 (was $2,390)",
    "Rent $2,290.\n\nCorrection: rent is $2,310 not $2,390 as first posted.\nDeposit $1,500.",
])
def test_rent_correction_names_each_old_figure_once(t):
    r = read("3 bed 2 bath townhouse. " + t)
    assert r["price"] == 2310
    n = notes(r)
    assert n.count("The listing corrects") == 1
    assert "corrects itself" not in n
    assert "$2,390" in n
    assert n.count("$2,390") == 1
    assert "The earlier" in n and "not used" in n
    assert "$2,310" in n


@pytest.mark.parametrize("t", [
    "3 bed 2 bath townhouse. Rent $2,310. Deposit $1,500.",
    "3 bed 2 bath townhouse. Rent $2,290. Pets ok. Not $2,390 for the garage.",
])
def test_negatives_no_rent_correction_without_one(t):
    assert "corrects the rent" not in notes(read(t))


# ----------------------------------------------------------------------- "reduced again" and the saved title
def test_reviewer_uiuc_l12_saved_listing():
    r = read(open(P + "r31-uiuc-l12.txt").read())
    assert r["price"] == 1395
    assert r["title"] == "Stadium View Lofts"
    n = notes(r)
    assert "it is now $1,395" in n
    assert "$1,350" in n and "$1,420" in n
    assert "not counted anywhere" not in n.split("Electric")[0]
    assert "Check what it is for" not in n


@pytest.mark.parametrize("body", [
    "Price reduced again to $1,395 this week.",
    "Price reduced again to $1,395/mo.",
    "Rent reduced further to $1,395 per month.",
    "Price dropped again to $1,395!",
    "Reduced again to $1,395 this week.",
    "This week the price was reduced again to $1,395.",
    "Lowered once more to $1,395.",
    "Price reduced again, now $1,395.",
])
def test_reduced_again_to_is_applied(body):
    r = read("Stadium View Lofts, $1,350 ($1,420 now)\n1 bed, 1 bath at 24 Kirby Ave, Champaign, IL 61820. " + body + " Tenant pays electric about $60.")
    assert r["price"] == 1395
    n = notes(r)
    assert "$1,395" in n
    assert "not counted anywhere" not in n.split("Electric")[0]
    assert n.count("$1,420") == 1


@pytest.mark.parametrize("body", [
    "Price reduced again to $1,395 if you sign by Dec 1.",
    "Reduced further to $1,395 when you sign by 12/1.",
])
def test_conditional_reduced_again_is_not_applied(body):
    r = read("Stadium View Lofts, $1,350 ($1,420 now)\n1 bed, 1 bath at 24 Kirby Ave, Champaign, IL 61820. " + body + " Tenant pays electric about $60.")
    assert r["price"] == 1420
    n = notes(r)
    assert "depends on the condition, so the saved rent stays $1,420" in n
    assert "Check what it is for" not in n


def test_other_cost_reduced_again_is_not_the_rent():
    r = read("Stadium View Lofts, $1,350 ($1,420 now)\n1 bed. Garage parking reduced again to $50 a month.")
    assert r["price"] == 1420


def test_saved_title_after_reduced_again(store):
    store.add_search("R", "rent", budget_max=2000)
    r = read(open(P + "r31-uiuc-l12.txt").read())
    p, _ = store.add_place(title="Stadium View Lofts, $1,350 ($1,420 now)", address="24 Kirby Ave", price=r["price"])
    assert p["title"] == "Stadium View Lofts"


@pytest.mark.parametrize("title,price,want", [
    ("Hartwell Place | Zillow-ish listing - 1 Bed Rent $1,425 (previously $1,490", 1425, "Hartwell Place | Zillow-ish listing - 1 Bed Rent $1,425"),
    ("Hartwell Place 1 Bed $1,425 (was $1,490", 1425, "Hartwell Place 1 Bed $1,425"),
    ("Hartwell Place 1 Bed [formerly $1,490", 1425, "Hartwell Place 1 Bed"),
    ("Hartwell Place 1 Bed (previously $1,490)", 1425, "Hartwell Place 1 Bed"),
    ("Hartwell Place 1 Bed $1,425 (was $1,490 per month)", 1425, "Hartwell Place 1 Bed $1,425"),
    ("Hartwell Place 1 Bed $1,425 (reduced from $1,490", 1425, "Hartwell Place 1 Bed $1,425"),
])
def test_title_never_ends_with_a_cut_off_old_price_bracket(title, price, want):
    assert drop_other_price_text(trim_stale_price_title(title), price) == want


@pytest.mark.parametrize("title", ["Hartwell Place 1 Bed (2 BA", "Hartwell (corner unit", "Elm Place $284,000 (reduced from $295,000)"])
def test_negatives_other_brackets_are_not_cut_too_far(title):
    out = drop_other_price_text(trim_stale_price_title(title), None)
    if "reduced" in title:
        assert out == "Elm Place $284,000"
    else:
        assert out == title


def test_saved_title_with_cut_bracket_through_the_store(store):
    store.add_search("R", "rent", budget_max=2000)
    p, _ = store.add_place(title="Hartwell Place | Zillow-ish listing - 1 Bed Rent $1,425 (previously $1,490", address="31 W Hartwell St", price=1425)
    assert "previously" not in p["title"] and "(" not in p["title"] and "$1,490" not in p["title"]
