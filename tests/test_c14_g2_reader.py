"""Cycle 14, group G2: parking, address, rent range, rooms, lease, title, days on market and agent (panel phrasings from the cycle 13 notes)."""
from __future__ import annotations

import pytest

from conftest import local_client  # noqa: F401
from mcp_util import call, server
from prophelper.parsers import parse_listing, split_full_address, street_with_unit


def notes(r):
    return r.get("found_in_listing", "")


def rent(extra, head="Sunny 1BR near campus\n$1,500/mo\n"):
    return parse_listing(head + extra + "\n")


# ---- 1. parking
def test_required_parking_for_all_residents_is_counted():
    r = rent("Parking required for all residents $120/month")
    assert r["parking_cost"] == 120 and r["price"] == 1500
    assert "not counted anywhere" not in notes(r)


@pytest.mark.parametrize("line,kind", [("Parking: 1 deeded space included", "lot"), ("One lot spot included", "lot")])
def test_included_space_is_free_with_no_required_note(line, kind):
    r = rent(line)
    assert r["parking_cost"] == 0 and r["parking"] == kind
    assert "required" not in notes(r) and "Ask" not in notes(r)


def test_parking_not_available_is_a_plain_no():
    r = rent("Parking not available")
    assert r["parking"] == "none" and "parking_cost" not in r
    assert notes(r) == "The listing says there is no parking."


def test_garage_optional_amount_gets_one_note():
    r = rent("Garage optional $100")
    assert "parking_cost" not in r and "parking" not in r
    n = notes(r)
    assert n.count("garage") + n.count("Garage") == 1 or n.count("$100") == 1
    assert "A garage is available for $100 a month" in n and "not counted in the monthly cost" in n
    assert "gives no price" not in n and "not counted anywhere" not in n


# ---- 2. address through MCP
@pytest.mark.parametrize("addr,extra,want", [
    ("88 N Mattis Ave, Champaign, IL 61821", {}, ("88 N Mattis Ave", "", "Champaign", "IL", "61821")),
    ("88 E Lincoln St #5, Columbus, Ohio 43201", {}, ("88 E Lincoln St", "#5", "Columbus", "OH", "43201")),
    ("17 W Starr Ave Apt 2, Columbus, OH 43201", {"unit": "2", "city": "Columbus", "state": "OH", "zip": "43201"}, ("17 W Starr Ave", "2", "Columbus", "OH", "43201")),
    ("500 Main St Unit 12, Columbus, Ohio 43201", {}, ("500 Main St", "Unit 12", "Columbus", "OH", "43201")),
])
def test_mcp_address_is_split_not_doubled(store, addr, extra, want):
    store.add_search("S", "rent")
    srv = server(store)
    call(srv, "add_place", title="T", address=addr, price=1000, **extra)
    p = store.list_places(store.current_search()["id"])[0]
    assert tuple(p[k] for k in ("address", "unit", "city", "state", "zip")) == want
    call(srv, "update_place", place_id=p["id"], address=addr, **extra)
    p = store.get_place(p["id"])
    assert tuple(p[k] for k in ("address", "unit", "city", "state", "zip")) == want


def test_unit_word_is_shown():
    assert street_with_unit("500 Main St", "Unit 12") == "500 Main St Unit 12"
    assert street_with_unit("88 E Lincoln St", "#5") == "88 E Lincoln St #5"
    assert street_with_unit("17 W Starr Ave", "Apt 2") == "17 W Starr Ave Apt 2"
    assert street_with_unit("1 A St", "2") == "1 A St #2"


def test_other_city_in_the_line_is_left_alone():
    r = split_full_address("5 Oak St, Springfield, IL 62701", None, "Columbus", "OH", "43201")
    assert r["address"] == "5 Oak St, Springfield, IL 62701" and r["city"] == "Columbus"


def test_web_paste_state_spelled_out():
    r = parse_listing("Columbus, Ohio 43201")
    assert (r["city"], r["state"], r["zip"]) == ("Columbus", "OH", "43201")
    r = parse_listing("Nice 1BR\n88 E Lincoln St #5\nColumbus, Ohio 43201\n$1000/mo")
    assert (r["address"], r["unit"], r["city"], r["state"], r["zip"]) == ("88 E Lincoln St", "5", "Columbus", "OH", "43201")


# ---- 3. rent ranges
def test_range_with_saved_rent_keeps_a_note():
    r = parse_listing("Bridgeport 2BR\n$3,000 - $3,200", current={"price": 3000})
    assert "from $3,000 up to $3,200" in notes(r) and "low end" in notes(r)


def test_range_without_saved_rent_stays_empty():
    r = parse_listing("Bridgeport 2BR\n$3,000 - $3,200 / month")
    assert "price" not in r and "rent range of $3,000 to $3,200" in notes(r)


@pytest.mark.parametrize("text,cur", [("Hyde Park\nstarting at $3,250", None), ("Hyde Park\nstarting at $3,250", {"price": 3250}),
                                      ("Hyde Park 1 bed\nStarting at $3,250/mo", None), ("Hyde Park\n1 bed from $3,250/mo", None)])
def test_starting_at_always_gets_the_lowest_unit_note(text, cur):
    r = parse_listing(text, current=cur)
    assert r.get("price") == 3250
    assert 'says "starting at" $3,250, so that is the lowest unit price' in notes(r)


def test_starting_at_a_fee_is_not_the_rent():
    r = parse_listing("Hyde\nParking starting at $50/mo")
    assert "price" not in r


# ---- 4. rooms
def test_convertible_title_and_body_count_leave_beds_empty():
    r = parse_listing("Victorian Village 1BR/2BR convertible\n$1,500/mo\n3 bedrooms, 2 bath")
    assert "beds" not in r and r["baths"] == 2
    assert '"1BR/2BR"' in notes(r) and '"3 bedrooms"' in notes(r) and "left empty" in notes(r)


def test_bath_self_correction():
    r = parse_listing("Nice\none bedroom, two bath? no, 1 bath\n$1000/mo")
    assert r["beds"] == 1 and r["baths"] == 1
    assert "bathroom counts" in notes(r) and "later count is saved" in notes(r)


def test_note_is_true_when_the_caller_sent_the_count():
    r = parse_listing("Nice\n1 bedroom? no, 3 bedroom\n$1000", current={"beds": 1})
    assert "later count is saved" not in notes(r) and "already saved was kept" in notes(r)
    r = parse_listing("Nice\none bedroom, two bath? no, 1 bath", current={"baths": 2})
    assert "later count is saved" not in notes(r) and "already saved was kept" in notes(r)


def test_mcp_caller_beds_kept_and_note_not_false(store):
    store.add_search("S", "rent")
    srv = server(store)
    call(srv, "add_place", title="T", address="1 Oak St", beds=1, listing_text="Nice\n1 bedroom? no, 3 bedroom\n$1000/mo")
    p = store.list_places(store.current_search()["id"])[0]
    assert p["beds"] == 1 and "later count is saved" not in p["reader_notes"]


# ---- 5. lease
@pytest.mark.parametrize("line", ["9 month lease or 12 month lease", "Lease: 9-month or 12-month lease"])
def test_two_lease_lengths_stay_empty(line):
    r = rent(line)
    assert "lease_months" not in r
    assert "more than one lease length (9 or 12 months)" in notes(r)


def test_single_lease_with_free_month_still_read():
    assert rent("12 month lease, 1 month free")["lease_months"] == 12


def test_lease_dates_feb_end():
    r = rent("Lease 3/1/2027 - 2/28/2028")
    assert r["lease_months"] == 12 and r["available_from"] == "2027-03-01"
    assert rent("Lease 8/1/2027 - 7/31/2028")["lease_months"] == 12


# ---- 6. titles
def test_plan_range_title_keeps_the_building_name():
    r = parse_listing("Studio-1BR Prairie Commons from $1,299 - $1,420\n123 Neil St, Champaign IL")
    assert r["title"] == "Prairie Commons"


# ---- 7. small
@pytest.mark.parametrize("line,days", [("3 weeks ago", 21), ("Listed 2 weeks ago", 14)])
def test_weeks_ago_is_days_on_market(line, days):
    assert parse_listing(f"Nice\n$300,000 3 bed\n{line}\n", buying=True)["days_on_market"] == days


def test_agent_has_no_trailing_period():
    r = parse_listing("Nice\n$300,000 3 bed\nListed by Priya Natarajan, Buckeye Realty.\n", buying=True)
    assert r["listing_agent"] == "Priya Natarajan, Buckeye Realty"
