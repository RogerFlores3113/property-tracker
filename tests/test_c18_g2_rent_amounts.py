"""Cycle 18 G2: a listing with two rents, a rent without a dollar sign, a deposit written as "same as rent"."""
import pytest

from prophelper.parsers import parse_listing


def notes(r):
    return r.get("found_in_listing", "")


# ---- two prices: the quoted or current rent is saved, the other figure is a note
@pytest.mark.parametrize("text", [
    "Gold Coast luxury 3bd 2ba. Starting at $3,400, specials: 1 month free on 13 mo lease (net effective $3,138). 1000 N Dearborn.",
    "Gold Coast 3bd 2ba\nStarting at $3,400\nSpecial: 1 month free on a 13 month lease\nNet effective rent $3,138",
    "Gold Coast 3bd 2ba - starting at $3,400 / month - ($3,138 net effective after concessions)",
])
def test_net_effective_is_not_the_rent(text):
    r = parse_listing(text)
    assert r["price"] == 3400
    n = notes(r)
    assert "$3,138" in n and "net effective" in n
    assert "the $3,400, amount" not in n


@pytest.mark.parametrize("text", [
    "Lakeview 3BR 2BA $3,350 -> $3,200 price drop. 3300 N Broadway Chicago IL 60657.",
    "Lakeview 3BR 2BA\n$3,350 → $3,200 (price drop!)\n3300 N Broadway Chicago IL 60657.",
    "Lakeview 3BR 2BA, was $3,350 now $3,200. 3300 N Broadway Chicago IL 60657.",
    "Lakeview 3BR 2BA, reduced from $3,350 to $3,200 per month. 3300 N Broadway Chicago IL 60657.",
    "Lakeview 3BR 2BA ~~$3,350~~ $3,200/mo. 3300 N Broadway Chicago IL 60657.",
])
def test_price_drop_saves_the_current_rent(text):
    r = parse_listing(text)
    assert r["price"] == 3200
    assert "$3,350" in notes(r)  # the old price is named, never used


def test_two_prices_never_pick_a_higher_new_figure():
    r = parse_listing("Studio $1,200 -> $1,500 after renovation. 12 Elm St.")
    assert r.get("price") != 1200 or "1,500" in notes(r)


# ---- a rent without a dollar sign
@pytest.mark.parametrize("text,expected", [
    ("Great place at 560 S Ohio Ave. Rent 1,480 plus parking $50 per space. Available 1/1.", 1480),
    ("2 bd 1 ba\nRent: 1480\nCats ok", 1480),
    ("2 bd 1 ba - Monthly rent 1,250 - near the park", 1250),
    ("Text me!! 2 bd 1 ba, Linden, pretty good shape. 1.5k a month, you pay gas/electric.", 1500),
    ("2bd, 1.2k/mo, 12 month lease", 1200),
    ("2bd/1ba\n1.35k per month\nNo pets", 1350),
])
def test_rent_without_dollar_sign(text, expected):
    assert parse_listing(text)["price"] == expected


@pytest.mark.parametrize("text", [
    "HOUSE FOR RENT 612 Mohawk St Des Moines, 2 bd",
    "Rent 612 Mohawk St Des Moines IA, 2 bd 1 ba",
    "For rent\n4120 Indianola Ave, Columbus OH",
])
def test_street_number_is_never_a_rent(text):
    assert "price" not in parse_listing(text)


# ---- deposit written as "same as rent"
@pytest.mark.parametrize("text", [
    "2 bd 1 ba. 1.5k a month. Deposit same as rent. Cat ok.",
    "Rent $1,500/mo\nSecurity deposit: equal to one month\nAvailable now",
    "$1,500 per month, security deposit is the same as the rent, 12 month lease",
    "Rent: $1,500. Deposit equals one month's rent.",
])
def test_deposit_from_rent(text):
    r = parse_listing(text)
    assert r["price"] == 1500 and r["deposit"] == 1500
