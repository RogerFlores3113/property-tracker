"""Cycle 37 G6 item 5 (buyer l5): "special assessment $12,000, buyer responsible, payable $500/mo for 24 months" is $500 a month for 24 months, never $12,000 cash to close."""
import os

import pytest

from prophelper.parsers import parse_listing

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "panel")


def fixture(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


def read(body, price=300000):
    return parse_listing(f"Test Condo ${price:,}\n12 Oak St #4, Columbus, OH 43202\n2 bed 2 bath. HOA $200/mo. " + body, "", buying=True)


@pytest.mark.parametrize("line", [
    "Special assessment $12,000, buyer responsible, payable $500/mo for 24 months.",
    "Special assessment of $12,000 (buyer pays), payable $500 per month for 24 months.",
    "Special assessment $12,000; buyer pays $500 a month for 24 months.",
    "Buyer responsible for special assessment: $12,000, paid $500 monthly for 24 months",
    "- Special assessment $12,000\n- Buyer pays $500/month for 24 months",
    "Special assessment: $500/mo for 24 months ($12,000 total), buyer responsible.",
    "Special assessment $12,000 payable in installments of $500 per month for 24 months, buyer responsible",
    "SPECIAL ASSESSMENT $12,000, BUYER RESPONSIBLE, PAYABLE $500/MO FOR 24 MONTHS.",
])
def test_total_and_monthly_in_one_sentence(line):
    out = read(line)
    assert out["other_monthly_fees"] == 500
    assert out["hoa"] == 200
    assert not out.get("special_assessment")  # the $12,000 is not also cash to close
    notes = out["found_in_listing"]
    assert "$12,000" in notes and "24 months" in notes
    assert "not counted anywhere" not in notes.split("12,000")[-1][:80]


def test_reviewer_listing_l5():
    out = parse_listing(fixture("r36-buyer-l5.txt"), "", buying=True)
    assert out["other_monthly_fees"] == 500 and out["hoa"] == 200 and out["property_tax"] == 5200
    assert not out.get("special_assessment")
    assert "$500 a month for 24 months" in out["found_in_listing"]


def test_negative_amounts_that_do_not_add_up_stay_the_whole_amount():
    out = read("Special assessment $12,000, buyer responsible, payable $300/mo for 24 months.")
    assert out.get("special_assessment") == 12000
    assert out.get("other_monthly_fees") in (None, 0)


def test_negative_seller_pays_is_not_counted_monthly():
    out = read("Special assessment $12,000, seller responsible, payable $500/mo for 24 months.")
    assert out.get("other_monthly_fees") in (None, 0)


def test_negative_a_plain_lump_stays_cash_to_close():
    out = read("Special assessment $12,000, buyer responsible, due at closing.")
    assert out["special_assessment"] == 12000 and out["special_assessment_payer"] == "buyer"
    out = read("Special assessment $12,000 paid by buyer. HOA $200/mo for 24 months promo.")
    assert out.get("special_assessment") == 12000
