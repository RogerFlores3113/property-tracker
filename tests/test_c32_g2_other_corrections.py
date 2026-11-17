"""Cycle 32 G2: corrections for HOA, property tax, seller credit and closing costs in every word order: "A -> B", "from A to B",
"rose to B from A", "(earlier estimate A)", "updated to B". The new figure is saved, the old one is named once as not used, and
no note calls either figure "not counted"."""
import pytest

from prophelper.parsers import parse_listing

B = "3 bed 2 bath house for sale, $450,000. 12 Oak St, Madison WI 53703. "


def read(t):
    return parse_listing(t, "", buying=True)


def notes(r):
    return r.get("found_in_listing", "") or ""


@pytest.mark.parametrize("t", [
    "HOA $340/mo -> $385/mo. Taxes $6,000/yr.",
    "HOA went from $340 to $385 a month. Taxes $6,000/yr.",
    "HOA is now $385/mo (up from $340). Taxes $6,000/yr.",
    "HOA fee rose to $385/mo from $340. Taxes $6,000/yr.",
    "HOA went up to $385/mo (it was $340). Taxes $6,000/yr.",
    "HOA was $340/mo, now $385/mo. Taxes $6,000/yr.",
    "HOA $340/mo (now $385/mo). Taxes $6,000/yr.",
    "HOA: $340/month. Correction: HOA is $385/month, not $340. Taxes $6,000/yr.",
    "HOA → from $340 to $385 per month. Taxes $6,000/yr.",
])
def test_hoa_correction_every_order(t):
    r = read(B + t)
    assert r["hoa"] == 385
    assert r["property_tax"] == 6000
    n = notes(r)
    assert "corrects the HOA: it is now $385 a month. The earlier $340 a month is not used" in n
    assert "not counted" not in n
    assert n.count("$340") == 1


@pytest.mark.parametrize("t", [
    "Taxes $6,000/yr -> $6,400/yr. HOA $300/mo.",
    "Property taxes increased to $6,400/yr from $6,000/yr. HOA $300/mo.",
    "Property tax $6,000/yr (now $6,400/yr). HOA $300/mo.",
    "Taxes $6,000/yr. Updated taxes: $6,400 per year (previously $6,000). HOA $300/mo.",
    "Taxes $6,000/yr. Correction: taxes are $6,400/yr, not $6,000. HOA $300/mo.",
    "Property taxes were $6,000, increased to $6,400 per year. HOA $300/mo.",
])
def test_tax_correction_every_order(t):
    r = read(B + t)
    assert r["property_tax"] == 6400
    assert r["hoa"] == 300
    n = notes(r)
    assert "corrects the property tax: it is now $6,400 a year. The earlier $6,000 a year is not used" in n
    assert "not counted" not in n
    assert n.count("$6,000") == 1


@pytest.mark.parametrize("t", [
    "Seller credit increased from $5,000 to $8,000. HOA $300/mo.",
    "Seller credit: $5,000 -> $8,000. HOA $300/mo.",
    "Seller credit raised to $8,000 (from $5,000). HOA $300/mo.",
    "Seller credit: now $8,000, was $5,000. HOA $300/mo.",
    "Seller credit $5,000 (updated: $8,000). HOA $300/mo.",
    "Seller credit $5,000. Correction: the seller credit is $8,000, not $5,000. HOA $300/mo.",
    "Seller concession $5,000, increased to $8,000. HOA $300/mo.",
])
def test_seller_credit_correction_every_order(t):
    r = read(B + t)
    assert r["seller_credit"] == 8000
    assert r["hoa"] == 300
    n = notes(r)
    assert "corrects the seller credit: it is now $8,000. The earlier $5,000 is not used" in n
    assert "not counted" not in n
    assert n.count("$5,000") == 1


@pytest.mark.parametrize("t", [
    "Closing cost estimate updated to $10,500 (earlier estimate $9,000). HOA $300/mo.",
    "Estimated closing costs $9,000. Corrected: closing costs are $10,500. HOA $300/mo.",
    "Closing costs $9,000 (now $10,500). HOA $300/mo.",
    "Closing costs were $9,000, now $10,500. HOA $300/mo.",
    "Closing costs: $9,000 -> $10,500. HOA $300/mo.",
    "Closing costs went from $9,000 to $10,500. HOA $300/mo.",
])
def test_closing_costs_correction_every_order(t):
    r = read(B + t)
    assert r["closing_costs"] == 10500
    assert r["hoa"] == 300
    n = notes(r)
    assert "corrects the closing costs: it is now $10,500. The earlier $9,000 is not used" in n
    assert "not counted" not in n
    assert n.count("$9,000") == 1


def test_two_facts_corrected_in_one_sentence():
    r = read(B + "HOA $340/mo, taxes $6,000/yr. Update: HOA now $385/mo and taxes now $6,400/yr.")
    assert r["hoa"] == 385 and r["property_tax"] == 6400
    n = notes(r)
    assert "corrects the HOA" in n and "corrects the property tax" in n
    assert "not counted" not in n


@pytest.mark.parametrize("t,hoa,tax", [
    ("HOA $340/mo. Taxes $6,000/yr.", 340, 6000),
    ("HOA $385/mo. Property tax $6,400/yr. Estimated closing costs $9,000.", 385, 6400),
])
def test_negatives_no_correction_without_a_correction_word(t, hoa, tax):
    r = read(B + t)
    assert r["hoa"] == hoa and r["property_tax"] == tax
    assert "corrects" not in notes(r)


def test_a_rent_step_up_is_not_a_correction_of_a_fee():
    r = parse_listing("Hyde Park 3 BR 2 BA. Rent $2,100/mo. Rent goes up to $2,250 after the first 6 months. Deposit $2,100.", "")
    assert r["price"] == 2250
    assert "corrects" not in (r.get("found_in_listing") or "")


@pytest.mark.parametrize("t", [
    "HOA $300 to $350/mo depending on the building. Taxes $6,000/yr.",
    "Taxes $5,000 to $6,000 a year depending on the assessment. HOA $300/mo.",
    "Seller credit $3,000 to $5,000 negotiable. HOA $300/mo.",
])
def test_a_range_with_to_is_never_called_a_correction(t):
    assert "corrects" not in notes(read(B + t))
