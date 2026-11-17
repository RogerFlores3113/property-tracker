"""Cycle 31 G2: "$1,350 ($1,420 now)" in a title applies the current rent; a title is never cut at "previously" or "now";
a title never keeps a price that a later correction replaced; a buyer title "(price reduced from $349,000)" keeps its price."""
import os

import pytest

from prophelper.parsers import parse_listing
from prophelper.store import drop_other_price_text, trim_stale_price_title

P = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel") + "/"


def read(t, buying=False, current=None):
    return parse_listing(t, "", current=current, buying=buying)


def notes(r):
    return r.get("found_in_listing", "") or ""


def test_reviewer_nontech_l5_title_now_price_is_applied():
    r = read(open(P + "r30-nontech-l5.txt").read())
    assert r["price"] == 1420
    assert r["deposit"] == 1350
    assert r["title"] == "Beautiful 2 bedroom, Short North"
    n = notes(r)
    assert "it is now $1,420" in n and "earlier $1,350 is not used" in n


@pytest.mark.parametrize("t,new,old", [
    ("Beautiful 2 bedroom, Short North - $1,350 ($1,420 now)\nCats ok. $1,350/mo, deposit $1,350.", 1420, 1350),
    ("Sunny 2 bed 1 bath apartment - $1,350/mo ($1,420 now)\nTenant pays electric. Deposit $1,350.", 1420, 1350),
    ("Uptown 3BR $3,350 ($3,420 now)\n3 bed 2 bath. Security deposit $3,350.", 3420, 3350),
    ("Oak Park 2 bed 1 bath | $2,100 PER MONTH ($2,150 now) | Deposit $2,100", 2150, 2100),
    ("Oak Park 2 bed 1 bath\n$1,350/mo (updated: $1,420)\nSold as-is. Deposit $1,350", 1420, 1350),
])
def test_title_price_with_now_figure(t, new, old):
    r = read(t)
    assert r["price"] == new
    n = notes(r)
    assert f"${new:,}" in n and f"${old:,} is not used" in n
    assert "not counted anywhere" not in n


def test_sold_as_is_in_a_rental_is_not_a_sale():
    r = read("Sunny 2 bed 1 bath apartment. Rent $1,350 (now $1,420 corrected). Sold as-is. Deposit $1,350.")
    assert r["price"] is not None and r["price"] < 20000


@pytest.mark.parametrize("t,title", [
    ("2BR in Beechwold, Columbus - previously $1,525, now $1,445!!\nTenant pays electric. Security deposit: $1,445.", "2BR in Beechwold, Columbus"),
    ("Cozy 2BR in Clintonville previously $1,525 now $1,445\nSecurity deposit: $1,445.", "Cozy 2BR in Clintonville"),
    ("Neil Street Commons | 1 Bed | Rent $1,425 (previously $1,490)\n1 bed 1 bath. Deposit $1,425.", "Neil Street Commons"),
    ("Zillow-ish listing - Stadium View 1BR ($1,350 ($1,420 now))\nReduced to $1,395 ($1,450 before). 1 Bed. Deposit $800.", "Stadium View 1BR"),
    ("Stadium View 1BR - was $1,450, now $1,395\n1 Bed. Deposit $800.", "Stadium View 1BR"),
])
def test_parsed_title_is_never_cut_at_previously_or_now(t, title):
    r = read(t)
    assert r["title"] == title


def test_uiuc_l6_saved_listing_price_and_title():
    r = read(open(P + "r30-uiuc-l6.txt").read())
    assert r["price"] == 1395
    assert r["title"] == "Stadium View 1BR"


@pytest.mark.parametrize("title,want", [
    ("Olde Towne East Condo - $329,900 (price reduced from $349,000)", "Olde Towne East Condo - $329,900"),
    ("Olde Towne East Condo $329,900 (price dropped from $349,000)", "Olde Towne East Condo $329,900"),
    ("Olde Towne East Condo - $329,900 (reduced from $349,000)", "Olde Towne East Condo - $329,900"),
    ("Olde Towne East Condo - $329,900 (was $349,000)", "Olde Towne East Condo - $329,900"),
    ("Olde Towne East Condo - $329,900 ($349,000 previously)", "Olde Towne East Condo - $329,900"),
    ("2BR in Beechwold - previously $1,525, now $1,445!!", "2BR in Beechwold - $1,445!!"),
])
def test_trim_keeps_the_current_price(title, want):
    assert trim_stale_price_title(title) == want


@pytest.mark.parametrize("t", [
    "Olde Towne East Condo - $329,900 (price reduced from $349,000)\n980 Oak St #5, Columbus, OH 43205\n2BR 2BA 1,180 sf. Condo fee $310/month. Insurance $900/yr.",
    "Olde Towne East Condo - $329,900 (price dropped from $349,000)\n980 Oak St #5, Columbus, OH 43205\n2BR 2BA 1,180 sf. Condo fee $310/month.",
    "Olde Towne East Condo\nPrice $329,900 (price reduced from $349,000)\n980 Oak St #5, Columbus, OH 43205\n2BR 2BA. Condo fee $310/month.",
])
def test_buyer_price_reduced_from_keeps_price(t):
    r = read(t, buying=True)
    assert r["price"] == 329900
    assert r["title"] == "Olde Towne East Condo"
    n = notes(r)
    assert "$349,000" in n and "not used" in n
    assert "Ask what the price is now" not in n
    assert "looks like a monthly amount" not in n


def test_reviewer_buyer_l6_saved_listing():
    r = read(open(P + "r30-buyer-l6.txt").read(), buying=True)
    assert r["price"] == 329900
    assert r["hoa"] == 310
    assert "Ask what the price is now" not in notes(r)


@pytest.mark.parametrize("title,price,want", [
    ("Stadium View 1BR ($1,350 ($1,420 now))", 1395, "Stadium View 1BR"),
    ("Elm Street Commons - 1 bed, $1,350 ($1,420 now)", 1395, "Elm Street Commons - 1 bed"),
    ("Uptown 3BR $3,350 ($3,420 now)", 3400, "Uptown 3BR"),
    ("Stadium View 1BR ($1,350 ($1,420 now))", 1420, "Stadium View 1BR ($1,420)"),
])
def test_saved_title_never_keeps_a_price_the_rent_replaced(store, title, price, want):
    store.add_search("R", "rent", budget_max=2000)
    p, _ = store.add_place(title=title, address="908 W Elm St", price=price)
    assert p["title"] == want


def test_drop_other_price_text_without_price_is_unchanged():
    assert drop_other_price_text("Stadium View 1BR ($1,420)", None) == "Stadium View 1BR ($1,420)"


@pytest.mark.parametrize("t", [
    open(P + "r30-privacy-l5.txt").read(),
    "Rent $1,500. 1 bed. Reduced to $1,400 ($1,500 before). Deposit $1,400.",
    "Rent $1,500. 1 bed. Price reduced to $1,400 (was $1,500). Deposit $1,400.",
    "1 bed apartment.\nRent: $1,500/mo\nReduced to $1,400/mo ($1,500 before)\nDeposit $1,400",
])
def test_reduced_to_with_a_saved_rent_gives_one_note(t):
    r = parse_listing(t, "", current={"price": 1500})
    assert r["price"] == 1500  # the rent already saved is kept
    n = notes(r)
    assert "was corrected to $1,400" in n and "saved on this place is $1,500" in n
    assert "not counted anywhere" not in n.split("Utilities estimate")[0]
    assert 'Reduced to $1,400' not in n and "Price reduced to" not in n


def test_reduced_to_without_a_saved_rent_gives_one_note():
    r = parse_listing(open(P + "r30-privacy-l5.txt").read(), "")
    assert r["price"] == 1400
    n = notes(r)
    assert n.count("$1,500") == 1
    assert "not counted anywhere" not in n.split("Utilities estimate")[0]
