"""Cycle 30 G2: "reduced to" and "($Y before / previously)" for HOA, tax, seller credit, closing costs, deposit, application fee and parking:
the later figure is saved, the replaced one is named once as not used and is never quoted as an uncounted or asking-price figure."""
import pytest

from prophelper.parsers import parse_listing


def read(t, buying=False):
    return parse_listing(t, "", buying=buying)


def notes(r):
    return r.get("found_in_listing", "") or ""


B = "Condo 2 bed 1 bath, $300,000. "


@pytest.mark.parametrize("t,field,new,old", [
    (B + "HOA $340/mo (reduced to $310/mo). Property tax $4,200 per year.", "hoa", 310, 340),
    (B + "HOA reduced to $310/mo ($340 before). Property tax $4,200 per year.", "hoa", 310, 340),
    (B + "HOA $310/mo ($340 previously). Property tax $4,200 per year.", "hoa", 310, 340),
    (B + "HOA: $310 a month (was $340). Property tax $4,200 per year.", "hoa", 310, 340),
    (B + "HOA $340/mo. Property tax $4,200 per year (reduced to $3,900 per year).", "property_tax", 3900, 4200),
    (B + "Property taxes reduced to $3,900/yr (were $4,200). HOA $300/mo.", "property_tax", 3900, 4200),
    (B + "Property taxes $3,900/yr ($4,200 before). HOA $300/mo.", "property_tax", 3900, 4200),
    (B + "Taxes $4,200 a year, reduced to $3,900 a year. HOA $300/mo.", "property_tax", 3900, 4200),
    (B + "Seller credit $2,000 (reduced to $1,500). HOA $300/mo.", "seller_credit", 1500, 2000),
    (B + "Seller credit now $3,500 ($2,000 before). HOA $300/mo.", "seller_credit", 3500, 2000),
    (B + "Seller credit: $3,500 ($2,000 previously). HOA $300/mo.", "seller_credit", 3500, 2000),
    (B + "Closing costs estimate $6,500 (reduced to $6,000). HOA $300/mo.", "closing_costs", 6000, 6500),
    (B + "Closing costs $6,000 ($6,500 previously). HOA $300/mo.", "closing_costs", 6000, 6500),
    (B + "Closing costs: $6,000\nPreviously $6,500\nHOA $300/mo.", "closing_costs", 6000, 6500),
])
def test_buyer_money_corrections_both_orders(t, field, new, old):
    r = read(t, buying=True)
    assert r[field] == new
    n = notes(r)
    assert f"${old:,}" in n and "is not used" in n and f"${new:,}" in n
    assert "not counted anywhere" not in n and "looks like a monthly amount" not in n and "Check what it is for" not in n


@pytest.mark.parametrize("t,field,new,old", [
    ("2 bed 1 bath, rent $1,800. Security deposit $1,800 (reduced to $1,500). Application fee $50.", "deposit", 1500, 1800),
    ("2 bed 1 bath, rent $1,800. Security deposit reduced to $1,500 ($1,800 before). Application fee $50.", "deposit", 1500, 1800),
    ("2 bed 1 bath, rent $1,800. Security deposit $1,500 ($1,800 previously). Application fee $50.", "deposit", 1500, 1800),
    ("2 bed 1 bath, rent $1,800. Security deposit: $1,500 (was $1,800). Application fee $50.", "deposit", 1500, 1800),
    ("2 bed 1 bath, rent $1,800. Security deposit $1,800. Application fee $50 (reduced to $25).", "application_fee", 25, 50),
    ("2 bed 1 bath, rent $1,800. Security deposit $1,800. Application fee $25 ($50 before).", "application_fee", 25, 50),
    ("2 bed 1 bath, rent $1,800. Security deposit $1,800. Application fee $25 (was $50).", "application_fee", 25, 50),
])
def test_renter_money_corrections_both_orders(t, field, new, old):
    r = read(t)
    assert r["price"] == 1800
    assert r[field] == new
    n = notes(r)
    assert f"${old:,}" in n and "is not used" in n
    assert "not counted anywhere" not in n and "Check what it is for" not in n


def test_before_move_in_is_not_an_old_figure():
    r = read("2 bed 1 bath, rent $1,800. Security deposit $1,800. First month $1,800 before move-in. Application fee $50.")
    assert r["price"] == 1800 and r["deposit"] == 1800 and r["application_fee"] == 50
    assert "is not used" not in notes(r)
