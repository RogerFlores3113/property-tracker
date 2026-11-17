"""Cycle 35 G5: "Seller-waived inspection, but buyer inspection contingency of 10 days is allowed" is the seller skipping their own inspection and
the buyer keeping theirs. It is not a scam sign. A listing that really bars the buyer's inspection is still flagged."""
import os

import pytest

from prophelper import redflags as rf

HERE = os.path.join(os.path.dirname(__file__), "fixtures", "panel")
NO_INSPECT = "It pushes you to skip or waive the inspection"


def F(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as fh:
        return fh.read()


def flags(t, mode="buy"):
    return rf.local_flags({"listing_text": "Hilltop Starter Condo $142,000. 3900 W Broad St #8, Columbus, OH 43228. 2 bed 1 ba. " + t,
                           "address": "3900 W Broad St #8, Columbus, OH"}, mode=mode)


def waive(t, mode="buy"):
    return [f for f in flags(t, mode) if NO_INSPECT in f]


FINE = [
    "Seller-waived inspection, but buyer inspection contingency of 10 days is allowed.",
    "Seller waived inspection; buyer has a 10-day inspection contingency.",
    "Inspection waived by the seller. Buyer inspection period of 10 days allowed.",
    "Seller waives the inspection but the buyer's inspection contingency is allowed for 10 days.",
    "Sellers waived inspection, however buyers may still hire an inspector.",
    "Buyer inspection contingency of 10 days is allowed. Seller-waived inspection.",
    "Seller-waived inspection (buyer inspection contingency, 10 days, is allowed).",
    "Seller waived the inspection | Buyer inspection contingency of 10 days is welcome",
    "SELLER-WAIVED INSPECTION, BUT BUYER INSPECTION CONTINGENCY OF 10 DAYS IS ALLOWED.",
    "Owner waived inspection and the buyer inspection period is 7 days.",
    "Seller-waived inspection, but a buyer inspection contingency is permitted.",
]


@pytest.mark.parametrize("t", FINE)
def test_seller_waiver_with_a_buyer_inspection_is_not_a_scam_sign(t):
    assert waive(t) == [], flags(t)
    assert flags(t) == []


def test_the_whole_reviewer_listing_has_no_inspection_flag():
    fl = rf.local_flags({"listing_text": F("r34-buyer-l44.txt"), "address": "3900 W Broad St #8, Columbus, OH 43228"}, mode="buy")
    assert not any(NO_INSPECT in f for f in fl), fl
    # the AI-aimed sentence of the same listing is still flagged
    assert any("text aimed at AI tools" in f for f in fl), fl


# ---- negatives: a real bar on the buyer's inspection is still a sign
STILL_FLAGGED = [
    "No inspection allowed. Cash only.",
    "Inspection waived. Buyer inspection contingency is not allowed.",
    "Seller-waived inspection and no buyer inspection is allowed.",
    "Seller waived inspection; buyer inspection contingency not permitted.",
    "Skip the inspection and wire the earnest money today.",
    "We will not allow an inspection.",
]


@pytest.mark.parametrize("t", STILL_FLAGGED)
def test_a_real_bar_on_the_buyers_inspection_is_still_flagged(t):
    assert waive(t), (t, flags(t))
