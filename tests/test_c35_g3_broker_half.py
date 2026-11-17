"""Cycle 35 group G3 item 7: "Broker fee one half month" is half the rent, counted in the cash at move-in; a broker fee the reader cannot read is named."""
import os

import pytest

from prophelper import money
from prophelper.parsers import parse_listing

HERE = os.path.join(os.path.dirname(__file__), "fixtures", "panel")


def P(text, kind=""):
    return parse_listing(text, "", pet_kind=kind)


def N(r):
    return r.get("found_in_listing") or ""


HALF = [
    "Rent $2,300. Broker fee one half month.",
    "Rent $2,300. Broker fee: one-half month.",
    "Rent $2,300. Broker fee 1/2 month.",
    "Rent $2,300. Broker fee of 0.5 months.",
    "Rent $2,300. Broker's fee: half a month's rent.",
    "Rent $2,300. Broker fee is half month.",
    "Rent $2,300\nBroker fee: one half of a month's rent\n",
    "Rent $2,300. One half month broker fee.",
    "RENT $2,300. BROKER FEE ONE HALF MONTH.",
    "Rent $2,300 | Broker fee one half month | Pets ok",
]


@pytest.mark.parametrize("t", HALF)
def test_half_a_month_of_rent(t):
    r = P(t)
    assert r["broker_fee"] == 1150 and r["price"] == 2300
    assert "not counted anywhere" not in N(r)


def test_family_l2_whole_listing_counts_the_half_month_in_cash_at_move_in():
    with open(os.path.join(HERE, "r34-family-l2.txt"), encoding="utf-8") as fh:
        r = P(fh.read())
    assert r["price"] == 2295 and r["deposit"] == 2295 and r["move_in_fees"] == 150 and r["application_fee"] == 50
    assert r["broker_fee"] == 1148 or r["broker_fee"] == 1147.5
    cash = money.cash_at_move_in(dict(r), pets=False)
    assert cash is not None
    assert cash["total"] >= 2295 + 2295 + 150 + 50 + 1147


def test_no_rent_leaves_the_fee_empty_with_a_note():
    r = P("2BR apartment. Broker fee one half month.")
    assert "broker_fee" not in r and "broker fee" in N(r).lower() and "rent was not read" in N(r)


@pytest.mark.parametrize("t", [
    "Rent $2,300. Broker fee: two weeks.",
    "Rent $2,300. Broker fee: a fortnight of rent.",
    "Rent $2,300\nBroker fee - see office\n",
])
def test_an_unreadable_broker_fee_is_named(t):
    r = P(t)
    assert "broker_fee" not in r and "could not read an amount" in N(r) and "Broker fee" in N(r)


@pytest.mark.parametrize("t", [
    "Rent $2,300. No broker fee.",
    "Rent $2,300. Broker fee paid by landlord.",
    "Rent $2,300. Broker fee: waived.",
    "Rent $2,300. Broker fee? Ask the office.",
])
def test_negatives_no_fee_means_no_note(t):
    r = P(t)
    assert "broker_fee" not in r and "could not read an amount" not in N(r)
