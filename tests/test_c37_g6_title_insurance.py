"""Cycle 37 G6 item 1 (buyer): a title policy is a one-time closing item, never the homeowner's insurance field."""
import os

import pytest

from prophelper.parsers import parse_listing

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "panel")


def fixture(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


def read(body, price=250000):
    return parse_listing(f"Test Condo ${price:,}\n12 Oak St #4, Columbus, OH 43202\n2 bed 2 bath. " + body, "", buying=True)


@pytest.mark.parametrize("line", [
    "HOA $260 per month. Tax $3,500/yr. Title insurance $1,200 paid by buyer.",
    "Buyer pays title insurance $1,500 and survey $400.",
    "Title insurance: $1,200; HOA $260 per month",
    "Owner's title policy $1,800 paid by buyer.",
    "Lender's policy $600, owner's policy $1,100 at closing",
    "HOA $260/mo | Title insurance $1,200 | Tax $3,500/yr",
    "- Title insurance $1,200\n- HOA $260 a month",
    "TITLE INSURANCE (buyer): $1,200.",
    "Survey $400, flood certification $20 and title insurance $1,800 paid by buyer.",
])
def test_title_policy_never_fills_insurance(line):
    out = read(line)
    assert "insurance" not in out
    assert "other amounts in that line are counted" not in (out.get("found_in_listing") or "")


def test_whole_reviewer_listings():
    assert "insurance" not in parse_listing(fixture("r36-buyer-l6.txt"), "", buying=True)
    out = parse_listing(fixture("r36-buyer-l2.txt"), "", buying=True)
    assert out["insurance"] == 1020  # $85 a month homeowner's insurance stays
    assert "other amounts in that line are counted" not in out["found_in_listing"]


def test_real_homeowners_insurance_next_to_title_insurance():
    out = read("Homeowner's insurance $75/mo. Title insurance $1,200 paid by buyer.")
    assert out["insurance"] == 900
    out = read("Title insurance $1,200 paid by buyer. Homeowner's insurance $75/mo.")
    assert out["insurance"] == 900


def test_negatives_plain_insurance_still_read():
    assert read("Insurance $1,100/yr.")["insurance"] == 1100
    assert read("HO6 insurance $40 monthly.")["insurance"] == 480
    assert read("Condo insurance about $60 a month.")["insurance"] == 720
