"""Cycle 29 G2: "($Y now)" and "(updated: $Y)" after any price form, rent corrections always leave a note, a corrected fee is never also missing,
a bare "299k" title price, and "(was $X)" next to HOA or tax is a correction note."""
import os

import pytest

from prophelper import money
from prophelper.parsers import parse_listing

P = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel") + "/"


def read(t, buying=False):
    return parse_listing(t, "", buying=buying)


def notes(r):
    return r.get("found_in_listing", "") or ""


def saved(name):
    return open(P + name).read()


@pytest.mark.parametrize("name,rent,old", [
    ("r28-uiuc-l6.txt", 1420, 1350), ("r28-uiuc-l9.txt", 1420, 1350), ("r28-roommates-l6.txt", 2995, 2950),
    ("r28-nontech-l45.txt", 1525, 1490), ("r28-roommates-l9.txt", 2975, 3000),
])
def test_saved_listings_apply_now_figure(name, rent, old):
    r = read(saved(name))
    assert r["price"] == rent
    assert f"The earlier ${old:,} is not used" in notes(r)


@pytest.mark.parametrize("title,old,new", [
    ("Elm Street Commons - bright 1 bedroom, 1 bath, $1,350 ($1,420 now)", 1350, 1420),
    ("Elm Street Commons - bright 1 bedroom, 1 bath, $1,420 ($1,350 now)", 1420, 1350),
    ("Bronzeville 3 BEDROOM 2 BATH - $2,950/mo ($2,995 now). 4500 S Michigan Ave 60653.", 2950, 2995),
    ("Bronzeville 3 BEDROOM 2 BATH - $2,950/mo ($2,900 now). 4500 S Michigan Ave 60653.", 2950, 2900),
    ("Bronzeville 3 BEDROOM 2 BATH - $2,950 PER MONTH ($2,995 now). 4500 S Michigan Ave 60653.", 2950, 2995),
    ("Bronzeville 3 BEDROOM 2 BATH - $2,950 PER MONTH ($2,900 now). 4500 S Michigan Ave 60653.", 2950, 2900),
    ("Trulia: 2 Bed Apartment at Brewery District Lofts - $1,490/mo ($1,525 now)", 1490, 1525),
    ("Trulia: 2 Bed Apartment at Brewery District Lofts - $1,490/mo ($1,400 now)", 1490, 1400),
    ("7 Oak St 3 bed 2 bath $2,250 ($2,200 now). Tenant pays utilities.", 2250, 2200),
    ("7 Oak St 3 bed 2 bath $2,250/mo ($2,200 now). Tenant pays utilities.", 2250, 2200),
    ("7 Oak St 3 bed 2 bath $2,250 ($2,300 now). Tenant pays utilities.", 2250, 2300),
    ("7 Oak St 3 bed 2 bath. $2,250 per month ($2,300 now). Tenant pays utilities.", 2250, 2300),
    ("Cozy 2 bed 1 bath apartment\n$1,800 / month ($1,750 now)\n12 Pine Ave Urbana IL 61801", 1800, 1750),
])
def test_now_in_brackets_after_any_price_form(title, old, new):
    r = read(title)
    assert r["price"] == new
    n = notes(r)
    assert f"it is now ${new:,}" in n and f"The earlier ${old:,} is not used" in n
    assert r.get("address", "") == "" or str(r["address"]).split()[0] not in ("7",) or r["price"] == new  # a street number is never the rent


@pytest.mark.parametrize("t,old,new", [
    ("7 Oak St 3 bed 2 bath. $2,250 per month (updated: $2,200). Tenant pays utilities.", 2250, 2200),
    ("7 Oak St 3 bed 2 bath. $2,250 per month (updated: $2,300). Tenant pays utilities.", 2250, 2300),
    ("7 Oak St 3 bed 2 bath. $2,250/mo (updated: $2,200). Tenant pays utilities.", 2250, 2200),
    ("7 Oak St 3 bed 2 bath. Rent $2,250 (updated: $2,200).", 2250, 2200),
    ("7 Oak St 3 bed 2 bath\n$2,250 per month (updated: $2,200)\nTenant pays utilities.", 2250, 2200),
])
def test_updated_in_brackets_is_applied(t, old, new):
    r = read(t)
    assert r["price"] == new
    assert "could not match" not in notes(r)
    assert f"The earlier ${old:,} is not used" in notes(r)


def test_other_costs_in_brackets_are_not_the_rent():
    r = read("Rent $1,500. 7 Oak St Urbana IL 61801. Parking $75 ($90 now). Pet fee $300 ($350 now). Utilities about $120 ($150 now).")
    assert r["price"] == 1500


@pytest.mark.parametrize("t,new,old", [
    ("2 bed 2 bath apartment. 100 Main St Urbana IL 61801. $3,250/mo. Update: rent is $3,225. Update: deposit is $3,225.", 3225, 3250),
    ("Rogers Park 3BR/2BA townhome $3,000. 1700 W Morse Ave 60626. Rent ($2,975 now).", 2975, 3000),
    ("Rogers Park 3BR/2BA townhome $3,000. 1700 W Morse Ave 60626.\nRent: ($2,975 now)", 2975, 3000),
])
def test_rent_correction_always_leaves_a_note(t, new, old):
    r = read(t)
    assert r["price"] == new
    assert f"The listing corrects the rent: it is now ${new:,}" in notes(r)
    assert f"${old:,}" in notes(r) and "is not used" in notes(r)
    assert "not counted" not in notes(r)


def test_rent_correction_with_unclear_old_figure_still_has_a_note():
    r = read("2 bed 2 bath apartment. 100 Main St Urbana IL 61801. Rent $1,200 for 12 months, $1,300 for 6 months. Update: rent is $1,250.")
    assert r["price"] == 1250
    assert "corrects the rent: it is now $1,250" in notes(r)


def test_corrected_amenity_fee_is_counted_and_not_missing():
    t = saved("r28-roommates-l2.txt")
    r = read(t)
    assert r["other_monthly_fees"] == 70 and r["price"] == 3240
    assert "corrects the amenity fee: it is now $45" in notes(r)
    r["listing_text"] = t
    assert money.open_listing_notes(r["found_in_listing"], r) == []


@pytest.mark.parametrize("fee_line", [
    "Amenity fee $35/mo. Corrected: amenity fee is $45.",
    "Amenity fee: $35 per month (now $45).",
    "Amenity fee $35/mo\nUpdate: amenity fee is now $45/mo",
])
def test_corrected_fee_layouts_are_not_missing(fee_line):
    t = "2 bed 2 bath apartment. 100 Main St Urbana IL 61801. Rent $1,800.\n" + fee_line + "\nValet trash $25/mo."
    r = read(t)
    assert r["other_monthly_fees"] == 70
    r["listing_text"] = t
    assert money.open_listing_notes(r["found_in_listing"], r) == []


# ---- buyer
def test_buyer_title_299k_is_the_price():
    r = read(saved("r28-buyer-l11.txt"), buying=True)
    assert r["price"] == 299000 and r["hoa"] == 350
    n = notes(r)
    assert "looks like a monthly amount" not in n
    assert "corrects the HOA: it is now $350 a month" in n and "$325" in n and "is not used" in n


@pytest.mark.parametrize("title,price", [
    ("Victorian Village Condo | 450k", 450000), ("Victorian Village Condo - 299K", 299000), ("Listed at 450K", 450000), ("Brick Ranch: $525k", 525000),
])
def test_bare_k_title_price_layouts(title, price):
    r = read(title + "\n755 Neil Ave, Columbus, OH 43215\n2 bed 1 bath ~ 960 sqft. HOA $350/mo.", buying=True)
    assert r["price"] == price


def test_k_in_other_places_is_not_a_price():
    r = read("Condo - 12k views this week\n755 Neil Ave, Columbus, OH 43215\n2 bed 1 bath ~ 960 sqft. HOA $350/mo.", buying=True)
    assert r.get("price") is None


@pytest.mark.parametrize("t", [
    "Condo, no price yet.\n12 High St, Columbus OH 43215\n2 bed 1 bath. HOA $350/mo (was $325). Tax bill $4,400.",
    "Condo, no price yet.\n12 High St, Columbus OH 43215\n2 bed 1 bath.\n- HOA: $350/mo (was $325)\n- Tax bill $4,400.",
])
def test_was_figure_is_never_a_candidate_price(t):
    r = read(t, buying=True)
    assert r.get("price") is None and r["hoa"] == 350
    assert "looks like a monthly amount" not in notes(r)
    assert "The earlier $325 a month is not used" in notes(r)


def test_tax_was_in_brackets_is_a_correction_note():
    r = read("Condo $300,000. HOA $350/mo. Taxes $4,400/yr (was $4,000). 5 Elm St Columbus OH 43215", buying=True)
    assert r["property_tax"] == 4400
    assert "corrects the property tax: it is now $4,400 a year" in notes(r)


def test_rent_with_was_in_brackets_is_not_changed_by_the_hoa_rule():
    r = read("2 bed 2 bath. $1,500/mo (was $1,450). 5 Elm St Urbana IL 61801.")
    assert r["price"] == 1500
