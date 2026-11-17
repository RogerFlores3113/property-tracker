"""Cycle 32, G4: Compare, the headline and the missing list name a buyer's "$1,800 prepaid taxes and insurance" by what the listing calls it."""
from __future__ import annotations

import os

import pytest

from prophelper import compare, money, parsers as P

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel")


def place_of(text: str) -> dict:
    r = P.parse_listing(text, "", buying=True)
    pl = dict(r, reader_notes=r.get("found_in_listing"), listing_text=text)
    pl["cost"] = money.true_monthly_cost(pl, "buy")
    pl["score"] = {"unknown": [], "items": []}
    return pl


def test_reviewer_listing():
    with open(os.path.join(FIX, "r31-buyer-l6.txt"), encoding="utf-8") as fh:
        pl = place_of(fh.read())
    label = pl["cost"]["listing_notes_label"]
    assert label == "the $1,800 prepaid taxes and insurance in the listing notes"
    assert compare.cost_unknowns(pl) == [label]
    assert "$1,800 insurance" not in pl["cost"]["headline"] and "prepaid taxes and insurance" in pl["cost"]["headline"]


HEAD = "Olde Towne East Condo - $329,900\n980 Oak St #5, Columbus, OH 43205\n2BR 2BA. Condo fee $310/month. Property tax $4,200/yr. Insurance $900/yr. "


@pytest.mark.parametrize("line,word", [
    ("Prepaid taxes and insurance $1,800 at closing.", "prepaid taxes and insurance"),
    ("Buyer prepaids of $1,800.", "prepaids"),
    ("Prepaid taxes $1,800.", "prepaid taxes"),
    ("$1,800 for prepaid insurance.", "prepaid insurance"),
    ("There is a $1,800 prepaid taxes and insurance charge, payer not stated.", "prepaid taxes and insurance"),
])
def test_other_wordings(line, word):
    pl = place_of(HEAD + line)
    label = str(pl["cost"].get("listing_notes_label") or "")
    if label:
        assert "$1,800" in label and f"insurance in the listing notes" not in label.replace("prepaid taxes and insurance", "").replace("prepaid insurance", "")


def test_plain_insurance_is_still_insurance():
    pl = place_of("Olde Towne East Condo - $329,900\n2BR 2BA. Condo fee $310/month. Property tax $4,200/yr. Home insurance estimate $1,800 not counted.")
    label = str(pl["cost"].get("listing_notes_label") or "")
    assert "prepaid" not in label
