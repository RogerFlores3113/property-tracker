"""Cycle 37 G5: "cash only", "Cash/check only" and "no lease needed" are named as scam signs for a rental (one line), never for a plain
"cash or check accepted", and not as a rental flag on a sale (a sale has its own cash-only line)."""
import pytest
from c37_g5_util import F, add, search, view

from prophelper import redflags

CASH = "It wants cash only, or says no lease is needed."
BASE = "Duplex 2 bed, 1140 Cleveland Ave, Columbus OH 43211. $1,200 rent, $1,200 deposit. Cat ok."


def flags(t, mode="rent"):
    return redflags.local_flags({"listing_text": t}, mode=mode)


def hits(t, mode="rent"):
    return [f for f in flags(t, mode) if f.startswith(CASH)]


YES = ["Cash only.", "Cash/check only.", "Cash or check only", "CASH ONLY, text me", "Cash, check or money order only.", "No lease needed.", "No lease required, move in today.",
       "Rent is cash only.", "We only accept cash.", "Pay in cash only.", "No contract needed.", "Cash payments only.", "Move in without a lease.", "No lease needed, cash only, text me."]


@pytest.mark.parametrize("w", YES)
@pytest.mark.parametrize("layout", ["after", "before", "newline", "brackets", "pipes"])
def test_named_as_a_scam_sign(w, layout):
    t = {"after": BASE + " " + w, "before": w + " " + BASE, "newline": BASE + "\n" + w + "\nNo washer.", "brackets": BASE + " (" + w.rstrip(".") + ")",
         "pipes": BASE + " | " + w + " | Cat ok"}[layout]
    assert len(hits(t)) == 1, flags(t)


@pytest.mark.parametrize("w", ["We accept cash, check or money order.", "No cash accepted.", "Cashback on the app.", "Cash flow positive investment.", "Pay by check or the online portal.",
                               "Lease needed: 12 months.", "Lease break fee $500, no lease transfer.", "Not cash only: portal payments welcome.", "No cash only deals."])
def test_negatives_not_flagged(w):
    assert not hits(BASE + " " + w), flags(BASE + " " + w)


def test_sale_has_its_own_line():
    f = flags("3 bed house for sale $250,000. Cash only, as is.", mode="buy")
    assert not [x for x in f if x.startswith(CASH)]
    assert [x for x in f if x.startswith("It says cash only")]


@pytest.mark.parametrize("name", ["r36-nontech-l6.txt", "r36-roommates-l14.txt"])
def test_reviewer_listings(store, name):
    assert len(hits(F(name))) == 1
    s = search(store)
    pid, reply = add(store, s, "X", F(name))
    out = view(store, pid)
    assert "cash only" in (reply + out).lower()
