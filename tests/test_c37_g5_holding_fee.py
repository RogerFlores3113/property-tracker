"""Cycle 37 G5: "Pls Venmo me the holding fee of $300 today" is one holding-fee note (one-time money), never "the listing corrects the holding fee"."""
import pytest
from c37_g5_util import F, add, search, view

from prophelper.parsers import parse_listing

BASE = "Duplex near Grandview, 12 Elm St Columbus OH 43212. 2BR rent $1,425 a month. Deposit $1,425. "
WORDINGS = [
    "Pls Venmo me the holding fee of $300 today, 3 others are looking!",
    "Holding fee $300 today to reserve it.",
    "Send the $300 holding fee today.",
    "Pay a holding fee of $300 today (Zelle).",
    "To hold it: holding fee $300 today; the rest at signing.",
    "Reservation fee of $300 today to take it off the market.",
    "- holding fee: $300 today",
]


def _notes(r):
    return (r.get("found_in_listing") or "").split("\n")


@pytest.mark.parametrize("w", WORDINGS)
@pytest.mark.parametrize("layout", ["after", "before", "own_line"])
def test_holding_fee_today_is_not_a_correction(w, layout):
    t = {"after": BASE + w, "before": w + "\n" + BASE, "own_line": BASE + "\n" + w + "\nPets ok."}[layout]
    r = parse_listing(t, "")
    assert r["price"] == 1425 and r["deposit"] == 1425
    n = _notes(r)
    assert not [x for x in n if "corrects the" in x], n
    hold = [x for x in n if "holding fee" in x.lower() or "reservation fee" in x.lower()]
    assert len(hold) == 1, n
    assert "$300" in hold[0] and "not counted in the monthly cost" in hold[0]


def test_reviewer_listing_nontech_l9(store):
    r = parse_listing(F("r36-nontech-l9.txt"), "")
    n = _notes(r)
    assert not [x for x in n if "corrects" in x], n
    assert len([x for x in n if "holding fee" in x]) == 1
    assert r["price"] == 1425
    s = search(store)
    pid, reply = add(store, s, "L9", F("r36-nontech-l9.txt"))
    assert "corrects the holding fee" not in view(store, pid) and "corrects the holding fee" not in reply


@pytest.mark.parametrize("t,field,val", [
    ("Rent $1,400 ($1,350 now). Holding fee $300.", "price", 1350),
    ("Rent $1,400. Corrected: rent is now $1,350. Holding fee $300 today.", "price", 1350),
    ("Rent $1,400 per month, $1,350 currently. Holding fee $300 today.", "price", 1350),
])
def test_real_corrections_still_apply(t, field, val):
    r = parse_listing("Oak Apt 5 Oak St Columbus OH 43212. 2 bed. " + t, "")
    assert r[field] == val
    n = _notes(r)
    assert any("corrects the rent" in x for x in n), n
    assert not any("corrects the holding" in x for x in n)
