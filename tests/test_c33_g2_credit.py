"""Cycle 33 G2: "Actually seller will pay up to $7,500 in buyer closing costs" corrects the seller credit; every corrected buyer figure keeps its own label."""
import os

import pytest

from prophelper.parsers import parse_listing

P = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel") + "/"


def read(t, **kw):
    return parse_listing(t, "", buying=True, **kw)


def notes(r):
    return r.get("found_in_listing", "") or ""


def test_buyer_l18_whole_listing():
    r = read(open(P + "r32-buyer-l18.txt", encoding="utf-8").read())
    n = notes(r)
    assert r["seller_credit"] == 7500
    assert r["hoa"] == 225
    assert r["price"] == 248900
    assert "The listing corrects the seller credit: it is now $7,500. The earlier $1,000 is not used." in n
    assert 'The listing says "up to", so this is the most the seller gives, not a sure amount.' in n
    assert "not counted anywhere" not in n
    assert "The listing says the buyer pays the $1,000 reserve contribution at closing." in n  # a different $1,000 keeps its own note


BASE = "Condo for sale $248,900. 2 bed 2 bath. "
CASES = [
    (BASE + "Seller credit $3,000 toward closing costs. Actually seller will pay up to $7,500 in buyer closing costs.", True),
    (BASE + "Seller will contribute $3,000 toward closing. Actually, the seller will contribute $7,500 toward closing costs.", False),
    (BASE + "\nSeller credit: $3,000\nActually seller will pay $7,500 toward the buyer's closing costs", False),
    ("Condo for sale $248,900 | Seller concessions $3,000 | Correction: seller to cover up to $7,500 of closing costs | HOA $200/mo", True),
    (BASE + "Seller pays $3,000 closing. Update: seller will give $7,500 for closing costs.", False),
    (BASE + "ACTUALLY SELLER WILL PAY UP TO $7,500 IN BUYER CLOSING COSTS. Seller credit $3,000.", True),
]


@pytest.mark.parametrize("t,upto", CASES)
def test_credit_corrected_every_wording(t, upto):
    r = read(t)
    n = notes(r)
    assert r["seller_credit"] == 7500
    assert "The listing corrects the seller credit: it is now $7,500. The earlier $3,000 is not used." in n
    assert ('The listing says "up to"' in n) is upto
    assert "not counted anywhere" not in n
    assert n.count("$3,000") == 1 and n.count("$7,500") == 1


@pytest.mark.parametrize("t,credit", [
    (BASE + "Seller credit $3,000. Actually the seller will pay $7,500 toward the roof repair.", 3000),
    (BASE + "Seller credit $3,000. Actually the buyer will pay $7,500 in closing costs.", 3000),
    (BASE + "Seller credit $3,000. The seller will pay $7,500 toward closing costs if you close by Dec 1.", None),
])
def test_negatives_other_purposes_and_other_payers_do_not_change_the_credit(t, credit):
    r = read(t)
    assert "corrects the seller credit" not in notes(r)
    if credit is not None:
        assert r["seller_credit"] == credit
