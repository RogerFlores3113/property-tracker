"""Cycle 30 G2: "reduced to", "before", "previously" in both orders for rent and buyer prices, a conditional "now" price kept as a note,
the replaced figure never quoted as uncounted, stale price text trimmed from a title."""
import os

import pytest

from prophelper.parsers import parse_listing

P = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel") + "/"


def read(t, buying=False):
    return parse_listing(t, "", buying=buying)


def notes(r):
    return r.get("found_in_listing", "") or ""


def saved(name):
    return open(P + name).read()


def never_uncounted(r, *figs):
    n = notes(r)
    for f in figs:
        assert f"Only {f} of that is not counted" not in n
        assert f'"{f}"' not in n or "not counted anywhere" not in n
    assert "not counted anywhere" not in n or not any(f in n.split("not counted anywhere")[0][-80:] for f in figs)


@pytest.mark.parametrize("t,new,old", [
    ("Lakeview 2 bed 1 bath apartment. Rent $2,300 (reduced to $2,250). Security deposit $2,250. Tenant pays utilities.", 2250, 2300),
    ("Lakeview 2 bed 1 bath apartment. Rent: $2,300 (reduced to $2,250) per month. Security deposit $2,250.", 2250, 2300),
    ("Oak Park 2 bed 1 bath. Monthly rent $2,300 (now reduced to $2,250). Security deposit $2,250.", 2250, 2300),
    ("Oak Park 2 bed 1 bath. Rent $2,300, reduced to $2,250 this week. Security deposit $2,250.", 2250, 2300),
    ("Oak Park 2 bed 1 bath. $2,300/mo (reduced to $2,250/mo). Security deposit $2,250.", 2250, 2300),
    ("Oak Park 2 bed 1 bath\n- Rent: $2,300\n- Price reduced to $2,250\n- Security deposit: $2,250", 2250, 2300),
    ("Oak Park 2 bed 1 bath | Rent $2,300 | (lowered to $2,250) | Deposit $2,250", 2250, 2300),
])
def test_rent_then_reduced_to(t, new, old):
    r = read(t)
    assert r["price"] == new
    n = notes(r)
    assert f"${old:,}" in n and "not used" in n
    assert "not counted anywhere" not in n


@pytest.mark.parametrize("t,new,old", [
    ("LAKEVIEW | 3 BEDS / 2 BATHS | $3,295 /MO | 3200 N Clark St 60657\nSecurity deposit: $1,000. Reduced to $3,195/mo ($3,295 before).", 3195, 3295),
    ("Lakeview 3 bed 2 bath, $3,295 /mo. Security deposit: $1,000. Reduced to $3,195 per month ($3,295 before).", 3195, 3295),
    ("Lakeview 3 bed 2 bath, $3,295/mo. Reduced to $3,195/mo (was $3,295). Security deposit: $1,000.", 3195, 3295),
    ("Lakeview 3 bed 2 bath, $3,295/mo\nReduced to $3,195/mo\nSecurity deposit: $1,000", 3195, 3295),
    ("Lakeview 3 bed 2 bath | $3,295/mo | Now reduced to $3,195/mo ($3,295 previously) | Deposit $1,000", 3195, 3295),
])
def test_reduced_to_then_before(t, new, old):
    r = read(t)
    assert r["price"] == new
    assert r["deposit"] == 1000
    n = notes(r)
    assert f"${old:,}" in n and "not used" in n
    assert "not counted anywhere" not in n


def test_saved_roommates_l15():
    r = read(saved("r29-roommates-l15.txt"))
    assert r["price"] == 3195 and r["deposit"] == 1000
    assert "not counted anywhere" not in notes(r)
    assert "$3,295" in notes(r) and "not used" in notes(r)


@pytest.mark.parametrize("t,new,old", [
    ("Mayfair Court 1BR, 1BA. Rent increased to $1,510 effective next lease year (previously $1,460).\nSecurity deposit: $1,510.", 1510, 1460),
    ("Mayfair Court 1BR, 1BA. Rent $1,510 (previously $1,460). Security deposit: $1,510.", 1510, 1460),
    ("Mayfair Court 1BR, 1BA. Rent $1,510 ($1,460 before). Security deposit: $1,510.", 1510, 1460),
    ("Mayfair Court 1BR, 1BA. Rent is $1,510 now, was $1,460 before. Security deposit: $1,510.", 1510, 1460),
    ("Mayfair Court 1BR, 1BA\nRent: $1,510 per month\nPreviously $1,460 per month\nSecurity deposit: $1,510", 1510, 1460),
])
def test_rent_previously_lower_is_replaced_not_missing(t, new, old):
    r = read(t)
    assert r["price"] == new
    n = notes(r)
    assert f"${old:,}" in n and "is not used" in n
    assert "not counted anywhere" not in n and "Check what it is for" not in n


def test_saved_uiuc_l19():
    r = read(saved("r29-uiuc-l19.txt"))
    assert r["price"] == 1510
    assert "not counted anywhere" not in notes(r) and "Check what it is for" not in notes(r)
    assert "$1,460" in notes(r) and "not used" in notes(r)


@pytest.mark.parametrize("t,base,offer", [
    ("Elm St 2 bed 1 bath | $3,290 | 2200 W Chicago Ave | Rent now $3,250 if you sign by Dec 1.", 3290, 3250),
    ("Elm St 2 bed 1 bath. Rent $3,290/mo. Rent now $3,250 if you sign by Dec 1.", 3290, 3250),
    ("Elm St 2 bed 1 bath. Rent $3,290/mo. Now $3,250/mo if you sign by Dec 1.", 3290, 3250),
    ("Elm St 2 bed 1 bath\nRent: $3,290\nRent now $3,250 when you sign a lease by December 1", 3290, 3250),
])
def test_conditional_now_keeps_base(t, base, offer):
    r = read(t)
    assert r["price"] == base
    n = notes(r)
    assert f"${offer:,}" in n and "depends on the condition" in n
    assert f"${base:,}\". It is not counted" not in n and "not counted anywhere" not in n


def test_saved_roommates_l10():
    r = read(saved("r29-roommates-l10.txt"))
    assert r["price"] == 3290
    n = notes(r)
    assert "$3,250" in n and "depends on the condition" in n
    assert "not counted anywhere" not in n.replace("Utility admin fee", "")


@pytest.mark.parametrize("t", [
    "Clintonville Garden Condo - $284,000 (reduced from $295,000)\n2900 Indianola Ave #3, Columbus, OH 43202\n2 bed 1.5 bath. HOA $240 per month; tax $3,100 per year.",
    "Clintonville Garden Condo - $284,000 (reduced from $295,000)\n2900 Indianola Ave #3, Columbus, OH 43202\n2 bed 1.5 bath. HOA $240 per month; tax $3,100 per year. Buyer pays a one-time $1,500 working capital contribution at closing.",
    "Clintonville Condo - $284,000 ($295,000 before). 2 bed 1.5 bath. HOA $240 per month; tax $3,100 per year.",
    "Price reduced to $284,000 (previously $295,000). 3 bed 2 bath, 2900 Indianola Ave, Columbus OH. HOA $240 per month; tax $3,100 per year.",
    "Clintonville Condo, listed at $295,000, reduced to $284,000. 2 bed 1.5 bath. HOA $240 per month; tax $3,100 per year.",
    "Clintonville Condo\nAsking price $284,000 (was $295,000)\n2 bed 1.5 bath. HOA $240 per month; tax $3,100 per year.",
])
def test_buyer_price_with_reduced_tail(t):
    r = read(t, buying=True)
    assert r["price"] == 284000
    n = notes(r)
    assert "$295,000" in n and "not used" in n
    assert "not counted anywhere" not in n and "Check what it is for" not in n and "does not give a clear asking price" not in n


def test_saved_buyer_l11_keeps_price():
    r = read(saved("r29-buyer-l11.txt"), buying=True)
    assert r["price"] == 284000 and r["hoa"] == 240 and r["property_tax"] == 3100 and r["closing_costs"] == 6800
    n = notes(r)
    assert "price was cut from $295,000" in n
    assert "looks like a monthly amount" not in n


from prophelper.store import trim_stale_price_title  # noqa: E402


@pytest.mark.parametrize("title,want", [
    ("Elm Street Commons - bright 1 bedroom, 1 bath, $1,350 ($1,420 now)", "Elm Street Commons - bright 1 bedroom, 1 bath, $1,420"),
    ("Prairie & Green Lofts - 1BR/1BA - $1,290/month (now $1,340)", "Prairie & Green Lofts - 1BR/1BA - $1,340/month"),
    ("Bronzeville 3 BEDROOM - $2,950 PER MONTH ($2,995 now)", "Bronzeville 3 BEDROOM - $2,995 PER MONTH"),
    ("Brewery District Lofts - $1,490/mo (updated: $1,525)", "Brewery District Lofts - $1,525/mo"),
    ("Clintonville Garden Condo - $284,000 (reduced from $295,000)", "Clintonville Garden Condo - $284,000"),
    ("Lakeview 3 bed - $3,195/mo ($3,295 before)", "Lakeview 3 bed - $3,195/mo"),
    ("Elm St 2 bed - $1,850 (was $1,950)", "Elm St 2 bed - $1,850"),
    ("Elm St 2 bed (corner unit) - $1,850", "Elm St 2 bed (corner unit) - $1,850"),
    ("Elm St 2 bed - $1,850 (now $1,800 if you sign by Dec 1)", "Elm St 2 bed - $1,850 (now $1,800 if you sign by Dec 1)"),
    ("Plain title", "Plain title"),
])
def test_trim_stale_price_text_in_titles(title, want):
    assert trim_stale_price_title(title) == want


def test_saved_title_is_trimmed(store):
    store.add_search("R", "rent", budget_max=2000)
    p, _ = store.add_place(title="Elm Street Commons - bright 1 bedroom, 1 bath, $1,350 ($1,420 now)", address="908 W Elm St", price=1420)
    assert p["title"] == "Elm Street Commons - bright 1 bedroom, 1 bath, $1,420"
    p2 = store.update_place(p["id"], title="Elm Street Commons, $1,420 ($1,350 before)")
    assert p2["title"] == "Elm Street Commons, $1,420"
