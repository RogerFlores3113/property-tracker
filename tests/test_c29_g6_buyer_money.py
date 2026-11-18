"""Cycle 29 G6: tax and HOA per half year, quarter and week, "Monthly fee $X plus $Y reserve", HOA per square foot, closing items stated as
additional or as months of HOA, and a PMI figure the listing quotes."""
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
    out = parse_listing(text_, buying=True)
    place = {**out, "listing_text": text_}
    return out, place


def notes(out):
    return out.get("found_in_listing", "")


def parts(place):
    cash = money.cash_to_close(place)
    return cash, {p["label"]: p["amount"] for p in cash["parts"]}


# ---- item 1: tax per half year, quarter, week
@pytest.mark.parametrize("line,expected", [
    ("Taxes: $1,950 per half year.", 3900),
    ("Property taxes $1,950 per half-year.", 3900),
    ("Taxes are $1,950 semi-annually.", 3900),
    ("Semi-annual taxes: $1,950.", 3900),
    ("Taxes: $1,950, paid twice a year.", 3900),
    ("Property tax $600 per quarter.", 2400),
    ("Taxes $600/quarter.", 2400),
    ("Property taxes $600 quarterly.", 2400),
    ("Taxes: $40 per week.", 2080),
    ("Taxes $4,100 per year.", 4100),
    ("Taxes $342/mo.", 4104),
])
def test_tax_period_is_converted(line, expected):
    out, _ = read(BASE + line)
    assert out["property_tax"] == expected


def test_tax_half_year_reviewer_listing():
    t = fixture("r28-buyer-l9.txt")
    out, _ = read(t)
    assert out["property_tax"] == 3900
    assert "$1,950 per half year" in notes(out) and "$3,900 a year" in notes(out)


def test_tax_biannual_is_left_empty_with_note():
    out, _ = read(BASE + "Taxes $2,000 biannual.")
    assert out.get("property_tax") in (None, "")
    assert "$2,000" in notes(out) and "left empty" in notes(out)


def test_yearly_tax_has_no_period_note():
    out, _ = read(BASE + "Taxes $4,100 per year.")
    assert "per half year" not in notes(out) and "per quarter" not in notes(out)


# ---- item 2: HOA per quarter and per half year
@pytest.mark.parametrize("line,expected", [
    ("HOA is paid quarterly: $780 per quarter.", 260),
    ("HOA $780 per quarter.", 260),
    ("HOA dues: $780/quarter.", 260),
    ("Quarterly HOA $780.", 260),
    ("HOA $780, billed quarterly.", 260),
    ("HOA fee is billed quarterly at $780.", 260),
    ("HOA $1,560 per half year.", 260),
    ("HOA dues $1,560 per half-year.", 260),
    ("HOA $1,560 billed semi-annually.", 260),
    ("HOA is paid semi-annually: $1,560.", 260),
    ("HOA $1,560, paid twice a year.", 260),
    ("HOA $60 per week.", 260),
    ("HOA $260/mo.", 260),
])
def test_hoa_period_is_converted(line, expected):
    out, _ = read(BASE + line)
    assert out["hoa"] == expected


def test_hoa_quarter_reviewer_listing():
    out, _ = read(fixture("r28-buyer-l9.txt"))
    assert out["hoa"] == 260
    assert "HOA is paid quarterly" not in notes(out)  # not left as a "not counted" quote


def test_hoa_biannual_is_unknown():
    out, _ = read(BASE + "HOA $520 biannual.")
    assert out.get("hoa") in (None, "")
    assert "$520" in notes(out)


# ---- item 3: monthly fee plus reserve
@pytest.mark.parametrize("line", [
    "Monthly fee $290 plus $45 reserve.",
    "Monthly fee: $290 + $45 reserve.",
    "Monthly fee $290, plus a $45 monthly reserve.",
    "HOA $290/mo plus $45 reserve fee.",
    "Monthly condo fee $290 and $45 reserve.",
])
def test_monthly_fee_plus_reserve(line):
    out, _ = read(BASE + line)
    assert out["hoa"] == 335
    assert "$290" in notes(out) and "$45" in notes(out)
    assert "one-time" not in notes(out)


def test_monthly_fee_plus_reserve_reviewer_listing():
    out, place = read(fixture("r28-buyer-l8.txt"))
    assert out["hoa"] == 335
    assert "one-time amount" not in notes(out)
    assert money.buy_cost(place)["lines"][-1]["amount"] == 335


def test_monthly_fee_alone_is_hoa_and_pet_fee_is_not():
    out, _ = read(BASE + "Monthly fee $290.")
    assert out["hoa"] == 290
    out, _ = read(BASE + "Monthly pet fee $35.")
    assert out.get("hoa") in (None, "")


def test_reserve_at_closing_is_not_monthly():
    out, _ = read(BASE + "Monthly fee $290 plus $450 reserve at closing.")
    assert out["hoa"] == 290


# ---- item 4: HOA per square foot
@pytest.mark.parametrize("line,expected", [
    ("HOA: $0.42/sf monthly.", 420),
    ("HOA $0.42 per sq ft per month.", 420),
    ("Condo fee $0.42/sqft monthly (covers water).", 420),
    ("HOA dues: $0.35 per square foot annually.", 29.17),
])
def test_hoa_per_square_foot(line, expected):
    out, _ = read(BASE + line)
    assert out["hoa"] == expected
    assert "square f" in notes(out)


def test_hoa_per_square_foot_reviewer_listing():
    out, _ = read(fixture("r28-buyer-l7.txt"))
    assert out["hoa"] == 554.4
    assert "1,320" in notes(out)


def test_hoa_per_square_foot_without_sqft_is_unknown():
    out, _ = read("Condo $300,000\n2 bed 2 bath. HOA: $0.42/sf monthly.")
    assert out.get("hoa") in (None, "")
    assert "$0.42" in notes(out) and "square feet" in notes(out)


def test_hoa_per_square_foot_without_period_is_unknown():
    out, _ = read(BASE + "HOA: $0.42/sf.")
    assert out.get("hoa") in (None, "")
    assert "$0.42" in notes(out)


def test_hoa_with_cents_is_not_zero():
    out, _ = read(BASE + "HOA: $0.42/sf monthly.")
    assert out["hoa"] != 0


# ---- item 5: stated closing items
@pytest.mark.parametrize("line", [
    "Buyer closing costs about $9,000. Title and recording $1,900 additional paid by buyer.",
    "Buyer closing costs about $9,000; an additional $1,900 for title and recording, paid by buyer.",
    "Closing costs about $9,000.\n- Additional: title and recording $1,900, buyer pays",
])
def test_additional_closing_item_is_counted(line):
    out, place = read(BASE + "HOA $300/mo. " + line)
    assert out["closing_costs"] == 9000
    cash, p = parts(place)
    assert 1900 in p.values()
    assert cash["total"] == 60000 + 9000 + 1900
    assert "$1,900" in notes(out) and "title and recording" in notes(out)


def test_additional_closing_item_with_the_guess():
    out, place = read(BASE + "HOA $300/mo. Title and recording $1,900 additional paid by buyer.")
    cash, p = parts(place)
    assert 1900 in p.values() and cash["total"] == 60000 + 9000 + 1900


def test_additional_closing_item_unknown_payer_is_named_not_counted():
    out, place = read(BASE + "HOA $300/mo. Buyer closing costs about $9,000. Title and recording $1,900 additional.")
    cash, p = parts(place)
    assert 1900 not in p.values()
    assert any("$1,900" in w and "title and recording" in w for w in cash["left_out"])
    assert "$1,900" in notes(out)


def test_additional_closing_item_paid_by_seller_is_not_counted():
    out, place = read(BASE + "HOA $300/mo. Buyer closing costs about $9,000. Seller pays title and recording $1,900 additional.")
    cash, p = parts(place)
    assert 1900 not in p.values()


def test_additional_closing_item_reviewer_listing():
    out, place = read(fixture("r28-buyer-l8.txt"))
    cash, p = parts(place)
    assert cash["total"] == 67000 + 9000 + 1900 - 8000
    assert "title and recording" in notes(out)


@pytest.mark.parametrize("line,months,label", [
    ("Buyer pays HOA transfer fee equal to one month of HOA.", 1, "HOA transfer fee"),
    ("Buyer pays a transfer fee of two months of HOA dues at closing.", 2, "transfer fee"),
    ("- Buyer pays HOA transfer fee: 1 month of HOA", 1, "HOA transfer fee"),
    ("Buyer will need to pay 6 months of HOA reserves at closing.", 6, "HOA reserves"),
    ("Buyer pays reserves equal to 3 months of HOA at closing.", 3, "reserves"),
    ("At closing the buyer pays 6 months of HOA reserves.", 6, "HOA reserves"),
])
def test_fee_in_months_of_hoa_new_names(line, months, label):
    out, place = read(BASE + "HOA $290/mo. " + line)
    cash, p = parts(place)
    assert 290 * months in p.values()
    assert any(label in l for l in p)
    assert label in notes(out) and "of HOA" in notes(out)


def test_hoa_transfer_fee_reviewer_listing():
    out, place = read(fixture("r28-buyer-l12.txt"))
    cash, p = parts(place)
    assert 290 in p.values()
    assert out["hoa"] == 290


def test_hoa_reserves_reviewer_listing_counts_with_hoa_read():
    out, place = read(fixture("r28-buyer-l10.txt"))
    assert out["hoa"] == 425
    cash, p = parts(place)
    assert 6 * 425 in p.values()


def test_hoa_reserves_unknown_hoa_is_named():
    out, place = read("Condo $300,000\n2 bed 2 bath. Buyer pays 6 months of HOA reserves at closing.")
    cash, _ = parts(place)
    assert any("6 months of HOA" in w for w in cash["left_out"])


def test_seller_pays_transfer_fee_is_not_counted():
    out, place = read(BASE + "HOA $290/mo. Seller pays HOA transfer fee equal to one month of HOA.")
    cash, p = parts(place)
    assert not any("transfer" in l for l in p)


# ---- item 6: quoted PMI
@pytest.mark.parametrize("line", [
    "PMI quoted by lender at $95/mo.",
    "PMI: $95 per month.",
    "Mortgage insurance about $95 a month.",
    "$95/mo PMI.",
    "PMI estimated at $1,140 a year.",
])
def test_quoted_pmi_is_used(line):
    out, place = read(BASE + "HOA $300/mo. Taxes $3,600/yr. Insurance $1,200/yr. " + line)
    cost = money.buy_cost(place, {"down_payment_pct": 15})
    pmi = [l for l in cost["lines"] if l["key"] == "pmi"]
    assert len(pmi) == 1 and pmi[0]["amount"] == 95
    assert "quoted" in pmi[0]["label"]
    assert any("$95" in n and "not the app's own estimate" in n for n in cost["notes"])
    assert not any("rough guess" in n for n in cost["notes"])
    assert "PMI" in notes(out) and "not counted anywhere" not in notes(out)


def test_pmi_without_a_quote_stays_an_estimate():
    out, place = read(BASE + "HOA $300/mo.")
    cost = money.buy_cost(place, {"down_payment_pct": 15})
    pmi = [l for l in cost["lines"] if l["key"] == "pmi"][0]
    assert "estimate" in pmi["label"] and pmi["amount"] != 95


@pytest.mark.parametrize("line", ["PMI not required with 20% down.", "Optional PMI $95/mo if you put less down."])  # cycle 35: a plain "No PMI required." is now a stated zero (tests/test_c35_g6_buyer_money.py)
def test_no_pmi_or_optional_pmi_is_not_a_quote(line):
    out, place = read(BASE + "HOA $300/mo. " + line)
    cost = money.buy_cost(place, {"down_payment_pct": 15})
    pmi = [l for l in cost["lines"] if l["key"] == "pmi"][0]
    assert "estimate" in pmi["label"]


def test_quoted_pmi_reviewer_listing():
    out, place = read(fixture("r28-buyer-l9.txt"))
    cost = money.buy_cost(place, {"down_payment_pct": 15})
    assert [l["amount"] for l in cost["lines"] if l["key"] == "pmi"] == [95.0]
    assert "$95" in notes(out)


def test_quoted_pmi_not_used_at_twenty_percent_down():
    out, place = read(BASE + "HOA $300/mo. PMI quoted at $95/mo.")
    cost = money.buy_cost(place)
    assert not [l for l in cost["lines"] if l["key"] == "pmi"]


def test_fee_in_months_of_hoa_no_payer_is_named_not_counted():
    out, place = read(BASE + "HOA $290/mo. - HOA transfer fee: 1 month of HOA")
    cash, p = parts(place)
    assert not any("transfer" in l for l in p)
    assert "HOA transfer fee" in notes(out) and "who pays" in notes(out)


def test_hoa_half_year_has_a_note():
    out, _ = read(BASE + "HOA $1,560 per half year.")
    assert "$1,560 per half year" in notes(out) and "$260 a month" in notes(out)


def test_closing_costs_in_parts_with_plus_are_not_additional():
    out, place = read(BASE + "HOA $300/mo. Buyer closing: title and escrow $2,100 plus lender fees $3,200.")
    cash, p = parts(place)
    assert cash["total"] == 60000 + 9000  # cycle 30: the named parts are only part of the bill, so the larger 3 percent guess stays
    assert "additional" not in notes(out)
