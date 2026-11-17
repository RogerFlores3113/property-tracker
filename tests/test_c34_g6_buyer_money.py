"""Cycle 34 G6: buyer money. Item 1: "split evenly between owners" is never a buyer/seller split."""
import os

import pytest

from prophelper import money
from prophelper.parsers import parse_listing

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "panel")
BASE = "Condo $300,000\n2 bed 2 bath, 1,000 sqft. "


def fixture(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


def read(text_):
    return parse_listing(text_, buying=True)


def full(text_):
    out = read(text_)
    place = {**out, "listing_text": text_}
    return out, place, money.cash_to_close(place)


def notes(out):
    return out.get("found_in_listing", "")


def parts(cash):
    return {p["label"]: p["amount"] for p in cash["parts"]}


# ---- item 1 (l31): the full monthly amount stays with the buyer
@pytest.mark.parametrize("line", [
    "Special assessment: $18,000 for the elevator, split evenly between owners over 36 months, buyer responsible for payments after closing.",
    "Special assessment of $18,000, shared equally among all unit owners, payable over 36 months. Buyer pays the installments after closing.",
    "Buyer takes over payments after closing. Special assessment $18,000 (elevator), divided evenly between the owners, over 36 months.",
    "Special assessment $18,000 over 36 months, split evenly among the homeowners; buyer responsible for the payments.",
    "Assessment: $18,000 over 36 months (split evenly between owners, buyer pays after closing)",
    "Special assessment $18,000, split evenly between owners | over 36 months | buyer responsible for payments after closing",
])
def test_owner_split_keeps_the_full_monthly_amount(line):
    out = read(BASE + line)
    assert out["other_monthly_fees"] == 500
    n = notes(out)
    assert "split 50/50" not in n and "Your half" not in n
    assert "split between the owners" in n and "full amount is counted" in n


def test_l31_whole_listing():
    out = read(fixture("r33-buyer-l31.txt"))
    assert out["other_monthly_fees"] == 500 and out["hoa"] == 410 and out["seller_credit"] == 3000 and out["closing_costs"] == 6100
    assert "split 50/50" not in notes(out) and "Your half" not in notes(out)
    assert "full amount is counted" in notes(out)


@pytest.mark.parametrize("line", [
    "Special assessment $18,000, split evenly between owners over 36 months. Payer not stated.",
    "Special assessment $18,000 over 36 months, shared equally by all owners.",
])
def test_owner_split_without_a_payer_is_never_halved_or_counted(line):
    out = read(BASE + line)
    assert out.get("other_monthly_fees") in (None, "")
    assert "Your half" not in notes(out)


# negatives: a real buyer/seller split is still halved
@pytest.mark.parametrize("line", [
    "Special assessment $18,000 over 36 months, split 50/50 between buyer and seller.",
    "Special assessment $18,000 over 36 months, split evenly between buyer and seller.",
])
def test_real_buyer_seller_split_still_halves(line):
    out = read(BASE + line)
    assert out["other_monthly_fees"] == 250
    assert "Your half is $9,000" in notes(out)
