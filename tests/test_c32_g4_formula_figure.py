"""Cycle 32, G4: a dollar figure beside formula-like text is named in a note, never silent."""
from __future__ import annotations

import os

import pytest

from prophelper import parsers as P

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel")


def read(text: str) -> dict:
    return P.parse_listing(text, "")


def notes(r: dict) -> str:
    return str(r.get("found_in_listing") or "")


def test_reviewer_listing():
    with open(os.path.join(FIX, "r31-privacy-l8.txt"), encoding="utf-8") as fh:
        r = read(fh.read())
    n = notes(r)
    assert r["price"] == 1500 and r["beds"] == 1
    assert "$35" in n
    assert "$12" in n and '"Surprise charge $99"' in n and '"Amenity fee $40"' in n
    assert "calc" not in n and "cmd" not in n and "=" not in n


@pytest.mark.parametrize("line", [
    'Valet trash $35 ="cmd|\' /C calc\'!A0" per month.',
    'Valet trash $35 =cmd|\' /C calc\'!A0 monthly.',
    'Valet trash: $35 +cmd|\' /C calc\'!A0 per month',
    'Valet trash $35 =HYPERLINK("http://x","y") per month.',
    'Valet trash $35 @SUM(A1:A9) per month.',
    'Concierge desk $35 =cmd|calc!A0 a month.',
])
def test_figure_is_named(line):
    r = read("Rent $1,500 a month. 1 bed 1 bath. Utilities included.\n" + line + "\nDeposit $1,500.")
    n = notes(r)
    assert r["price"] == 1500
    assert "$35" in n
    assert "cmd" not in n and "HYPERLINK" not in n and "SUM(" not in n and "=" not in n


def test_ordinary_lines_unchanged():
    r = read("Rent $1,500 a month. 1 bed 1 bath. Utilities included.\nValet trash $35 per month.\nDeposit $1,500.")
    assert "spreadsheet" not in notes(r)


def test_no_double_note_when_a_note_already_names_it():
    r = read("Rent $1,500 a month. 1 bed 1 bath. Utilities included.\nSurprise charge $99 =cmd|calc!A0 applies monthly.\nDeposit $1,500.")
    assert notes(r).count("$99") == 1
