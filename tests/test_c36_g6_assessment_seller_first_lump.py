"""Cycle 36 G6 item 7 (buyer l51): "Seller pays special assessment of $6,000 first, then buyer pays $250 per month for 24 months." The seller's amount is named and not
counted; the buyer's $250 a month is counted as other monthly fees for 24 months; nothing is listed as missing."""
import os
import sys

import pytest

from prophelper import money
from prophelper.parsers import parse_listing

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp_util import call, server, text  # noqa: E402

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel")


def fixture(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


HEAD = "Condo $312,500\n401 W Nationwide Blvd #1204, Columbus, OH 43215\n2 bed 2 bath. HOA $395/mo. Taxes $4,800 per year. Insurance $480 a year. "


def read(line):
    return parse_listing(HEAD + line, "", buying=True)


def notes(out):
    return out.get("found_in_listing") or ""


WORDINGS = [
    "Seller pays special assessment of $6,000 first, then buyer pays $250 per month for 24 months.",
    "The seller pays the first $6,000 of the special assessment, then the buyer pays $250/mo for 24 months.",
    "Special assessment: seller pays $6,000 up front; then the buyer pays $250 a month for 24 months.",
    "Special assessment: seller pays $6,000 first\nThen buyer pays $250 per month for 24 months",
    "Seller covers a $6,000 special assessment initially, after that buyer pays $250 monthly for 24 months.",
    "Special assessment (seller pays $6,000 first, then buyer pays $250 each month for 24 months)",
    "Special assessment $6,000 paid by seller first, then $250 a month paid by buyer for 24 months.",
    "SELLER PAYS SPECIAL ASSESSMENT OF $6,000 FIRST, THEN BUYER PAYS $250 PER MONTH FOR 24 MONTHS.",
]


@pytest.mark.parametrize("line", WORDINGS)
def test_fields(line):
    out = read(line)
    assert out["other_monthly_fees"] == 250
    assert "special_assessment" not in out
    assert out["hoa"] == 395
    n = notes(out)
    assert "$6,000" in n and "$250 a month" in n and "24 months" in n
    assert "not counted anywhere" not in n


def test_whole_listing_l51():
    out = parse_listing(fixture("r35-buyer-l51.txt"), "", buying=True)
    assert out["other_monthly_fees"] == 250 and out["hoa"] == 395 and out["property_tax"] == 4800
    assert "special_assessment" not in out
    n = notes(out)
    assert "Only $250 of that is a monthly fee" not in n
    assert "the other amounts in that line are counted" not in n


def test_the_cost_counts_250_and_lists_nothing_missing_for_it():
    out = parse_listing(fixture("r35-buyer-l51.txt"), "", buying=True)
    place = {**out, "listing_text": fixture("r35-buyer-l51.txt"), "reader_notes": notes(out)}
    c = money.buy_cost(place)
    assert any(x["key"] == "other" and x["amount"] == 250 for x in c["lines"])
    assert not any("250" in str(m) or "assessment" in str(m).lower() for m in c["missing"])
    assert not any("250" in str(m) for m in c.get("uncounted", []))


def test_mcp_get_place_and_compare(store):
    store.add_search("T", "buy")
    srv = server(store)
    call(srv, "add_place", listing_text=fixture("r35-buyer-l51.txt"))
    p = store.get_place(1)
    assert p["other_monthly_fees"] == 250 and not p.get("special_assessment")
    out = text(call(srv, "get_place", place_id=1))
    assert "$250" in out
    from prophelper import compare
    cell = compare._assessment_cell({**p, "cost": {"mode": "buy"}})
    assert cell["text"].startswith("$250 a month for 24 months") and "(you pay it)" in cell["text"]


# ---- negatives: nothing changes for these
def test_negative_seller_only_lump():
    out = read("Seller pays special assessment of $6,000 at closing.")
    assert out["special_assessment"] == 6000 and out["special_assessment_payer"] == "seller"
    assert "other_monthly_fees" not in out


def test_negative_buyer_monthly_only():
    out = read("Special assessment: $250 per month for 24 months, buyer pays.")
    assert out["other_monthly_fees"] == 250
    assert "special_assessment" not in out


def test_negative_seller_first_months_is_the_old_reader():
    out = read("Special assessment: $9,600 payable $400 monthly for 2 years, seller responsible for first 6 months.")
    assert out["other_monthly_fees"] == 400


def test_negative_buyer_lump_then_seller_monthly_is_not_read():
    out = read("Buyer pays special assessment of $6,000 first, then seller pays $250 per month for 24 months.")
    assert "other_monthly_fees" not in out
