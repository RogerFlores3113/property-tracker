"""Cycle 36 G6 item 5 (buyer l54): "PMI not required with 20 percent down" on a search with 15% down keeps the PMI estimate and says PMI may apply at 15%."""
import os

import pytest

from prophelper import money
from prophelper.parsers import listing_pmi_condition, parse_listing

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "panel")


def fixture(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


def cost(listing, down=15.0, price=298000):
    place = {"price": price, "property_tax": 3900, "insurance": 744, "hoa": 275, "listing_text": listing}
    return money.buy_cost(place, {"down_payment_pct": down})


def note_texts(c):
    return " ".join(c["notes"])


@pytest.mark.parametrize("line", [
    "PMI not required with 20 percent down.",
    "No PMI with 20% down.",
    "No PMI if you put 20% down",
    "Mortgage insurance not required with 20 percent down; parking street",
    "PMI is not required when you put 20% down.\nParking street",
    "Parking street | No PMI with 20% down | Pets ok",
    "Buyer gets no PMI at 20% down program.",
])
def test_conditional_no_pmi_keeps_estimate_and_notes_15_percent(line):
    c = cost("Flat $298,000. " + line)
    pmi = next(x for x in c["lines"] if x["key"] == "pmi")
    assert pmi["amount"] and pmi["amount"] > 0
    t = note_texts(c)
    assert "PMI may apply at 15%" in t
    assert "Ask your lender" in t


def test_l54_whole_listing():
    c = cost(fixture("r35-buyer-l54.txt"))
    assert "PMI may apply at 15%" in note_texts(c)
    assert next(x for x in c["lines"] if x["key"] == "pmi")["amount"] > 0


def test_l51_whole_listing_no_pmi_program_line():
    c = cost(fixture("r35-buyer-l51.txt"), price=312500)
    assert "PMI may apply at 15%" in note_texts(c)


def test_no_note_at_twenty_percent_down():
    c = cost("Flat $298,000. PMI not required with 20 percent down.", down=20.0)
    assert not any(x["key"] == "pmi" for x in c["lines"])
    assert "PMI may apply" not in note_texts(c)


def test_negative_unconditional_no_pmi_is_zero_without_this_note():
    c = cost("Flat $298,000. No PMI.")
    assert next(x for x in c["lines"] if x["key"] == "pmi")["amount"] == 0
    assert "PMI may apply" not in note_texts(c)


def test_negative_no_pmi_word_at_all():
    c = cost("Flat $298,000. Quiet street.")
    assert "PMI may apply" not in note_texts(c)


def test_reader_function_values():
    assert listing_pmi_condition("PMI not required with 20 percent down.")[1] == 20.0
    assert listing_pmi_condition("No PMI.") is None
    assert parse_listing("Flat $298,000\n33 Mohawk St, Columbus, OH 43206\nPMI not required with 20 percent down.", "", buying=True).get("insurance") is None
