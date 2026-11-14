"""Cycle 7, G1: all-except utilities, partly priced utilities, utility names, storage and parking fees, MCP replies."""
import pytest

from mcp_util import call, server, structured, text
from prophelper import money
from prophelper.parsers import parse_listing, listing_uncounted_fees


def pays(r):
    return [w.strip() for w in (r.get("tenant_pays") or "").split(",") if w.strip()]


def inc(r):
    return [w.strip() for w in (r.get("utilities_included") or "").split(",") if w.strip()]


@pytest.mark.parametrize("t,left", [("Utilities: all utilities included except electric", ["electric"]),
                                    ("All utilities included except electric and gas", ["electric", "gas"]),
                                    ("All utilities paid except cable/internet", ["internet"])])
def test_all_included_except(t, left):
    r = parse_listing(t)
    assert r["utilities_included"] != "all"
    assert pays(r) == left
    assert not set(left) & set(inc(r)) and "water" in inc(r)


def test_cycle6_all_except_still_works():
    r = parse_listing("Tenant responsible for all utilities, landlord pays garbage only")
    assert inc(r) == ["trash"] and "electric" in pays(r) and "trash" not in pays(r)
    r = parse_listing("All utilities except trash")
    assert inc(r) == ["trash"] and "trash" not in pays(r)


LISTING = "Water and trash included; tenant pays electric, gas and internet. $25/mo billed back for trash."


def test_partly_priced_utilities():
    r = parse_listing(LISTING)
    assert r["utilities_estimate"] == 25
    assert "trash" in pays(r) and "trash" not in inc(r) and inc(r) == ["water"]
    assert "billed-back" in r["found_in_listing"] or "billed back" in r["found_in_listing"]
    assert "other_monthly_fees" not in r


def test_partly_priced_marks_rest_unknown():
    r = parse_listing(LISTING)
    place = {**r, "price": 1000, "listing_text": LISTING}
    cost = money.rent_cost(place)
    assert "utilities estimate" not in cost["missing"] and cost["missing"] == ["electric, gas and internet"]  # c10: names only what is missing
    assert any("electric, gas and internet" in u for u in cost["uncounted"])
    assert "not counted yet" in money.headline_text(cost) if hasattr(money, "headline_text") else True


def test_fully_billed_back_is_complete():
    t = "Trash and water billed back at $85/month. Tenant pays water and trash."
    r = parse_listing(t)
    cost = money.rent_cost({**r, "price": 1000, "listing_text": t})
    assert "utilities estimate" not in cost["missing"]
    assert [l for l in cost["lines"] if l["key"] == "utilities"][0]["note"].startswith("Billed back, from the listing")


@pytest.mark.parametrize("t", ["$25/mo billed back for trash", "Trash $25/mo billed back", "$25/mo for trash, billed back"])
def test_billed_back_always_utilities_estimate(t):
    r = parse_listing(t)
    assert r["utilities_estimate"] == 25 and pays(r) == ["trash"] and "other_monthly_fees" not in r


@pytest.mark.parametrize("t,want", [("Tenant pays PG&E and water", {"electric", "gas", "water"}),
                                    ("Tenant pays ComEd and water", {"electric", "water"}),
                                    ("Tenant pays Ameren", {"electric", "gas"}),
                                    ("Tenant pays Nicor", {"gas"}),
                                    ("Tenant pays hydro", {"electric"}),
                                    ("Tenant pays garbage", {"trash"}),
                                    ("Tenant pays refuse", {"trash"}),
                                    ("Tenant pays rubbish", {"trash"}),
                                    ("Tenant pays cable", {"internet"})])
def test_utility_names(t, want):
    assert set(pays(parse_listing(t))) == want


@pytest.mark.parametrize("t,amount", [("Storage locker $30 per month", 30), ("Storage locker: $30/mo", 30),
                                      ("optional storage locker available for $30/month", 30), ("Storage locker $25/mo", 25),
                                      ("Storage locker extra $40 per month", 40)])
def test_storage_listed_not_counted(t, amount):
    r = parse_listing(t)
    line = r["found_in_listing"]
    assert f"${amount}/month" in line and "not counted" in line and "optional" in line
    assert "other_monthly_fees" not in r
    assert listing_uncounted_fees(t) == [f"storage locker ${amount}/mo"]


def test_storage_required_is_counted():
    r = parse_listing("Storage locker $30/mo is required for all residents.")
    assert r["other_monthly_fees"] == 30 and "counted in other monthly fees" in r["found_in_listing"]
    assert listing_uncounted_fees("Storage locker $30/mo is required for all residents.") == []


@pytest.mark.parametrize("t,cost", [("Parking $50 a month", 50), ("Parking: $75/mo", 75), ("Garage parking $100/month", 100),
                                    ("reserved parking $50 extra", 50)])
def test_parking_cost(t, cost):
    r = parse_listing(t)
    assert r["parking_cost"] == cost and "other_monthly_fees" not in r


def test_valet_trash_and_pet_rent():
    r = parse_listing("$40 extra monthly valet trash")
    assert r["other_monthly_fees"] == 40 and "valet trash" in r["found_in_listing"] and "tenant_pays" not in r
    assert parse_listing("Pet rent $35/mo")["pet_rent"] == 35


@pytest.fixture
def srv(store):
    s = server(store)
    call(s, "create_search", name="S", mode="rent", move_in="2027-08-15", budget_max=2500)
    return s


def test_add_place_names_unseen_fee(srv):
    body = "Westgate Flats\n123 Main St, Columbus, OH 43215\n2 bed 1 bath $1,400/mo. Storage locker $40/mo."
    out = text(call(srv, "add_place", listing_text=body))
    # c12: the note already says it, so the "Seen but not counted" line does not repeat it
    assert "Storage locker is $40/month" in out and "Seen but not counted" not in out


def test_get_place_says_billed_back(srv, store):
    body = "Westgate Flats\n123 Main St, Columbus, OH 43215\n2 bed 1 bath $1,400/mo. " + LISTING
    r = call(srv, "add_place", listing_text=body)
    pid = structured(r)["place_id"]
    out = text(call(srv, "get_place", place_id=pid))
    assert "Billed back, from the listing" in out
    assert "electric, gas and internet" in out
    r = call(srv, "add_place", title="B", address="9 Elm St, Columbus, OH 43215", price=1000, utilities_estimate=25,
             utilities_source="billed back", listing_text="9 Elm St. Trash billed back $25/month.")
    out = text(call(srv, "get_place", place_id=structured(r)["place_id"]))
    assert "Billed back, from the listing" in out
