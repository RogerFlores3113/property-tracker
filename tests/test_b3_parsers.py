"""The listing parser on made-up pasted texts (see b3_listing_fixtures.py)."""
from datetime import date

import pytest

from prophelper import parsers

from b3_listing_fixtures import FIXTURES


@pytest.mark.parametrize("fx", FIXTURES, ids=[f["name"] for f in FIXTURES])
def test_fixture_fields(fx, monkeypatch):
    if fx.get("today"):
        monkeypatch.setattr(parsers, "_today", lambda: date.fromisoformat(fx["today"]))
    got = parsers.parse_listing(fx["text"], fx["url"])
    expect = dict(fx["expect"], **fx.get("expect_today", {}))
    wrong = {k: (got.get(k), v) for k, v in expect.items() if got.get(k) != v}
    assert not wrong, f"(found, wanted): {wrong}\nall found: {got}"
    for key in fx.get("absent", []):
        assert key not in got, f"{key} should not be guessed, got {got[key]!r}"


def test_never_raises_on_junk():
    for junk in ("\x00\x01\x02", "$" * 500, "1 " * 5000, "bed bath " * 3000, "$1,2,3,4 / / / mo", "Jan 99 Feb 99", "#" * 200,
                 "\n" * 1000, "12345 " * 2000 + " st"):
        assert isinstance(parsers.parse_listing(junk, ""), dict)


def test_empty_and_link_only():
    assert parsers.parse_listing("", "") == {}
    assert parsers.parse_listing("", "https://www.zillow.com/x") == {"source": "Zillow"}
    assert parsers.site_name("redfin.com/IL/x") == "Redfin"
    assert parsers.site_name("not a link at all") == ""


def test_fees_are_never_the_rent():
    out = parsers.parse_listing("Security deposit $1,500. Application fee $50. Pet fee $300. Rent $1,200 per month.", "")
    assert out["price"] == 1200 and out["deposit"] == 1500 and out["pet_fee"] == 300
    out = parsers.parse_listing("Parking $75/mo. HOA $200/mo. Rent: $1,400", "")
    assert out["price"] == 1400 and out["parking_cost"] == 75 and out["hoa"] == 200


def test_not_a_street_in_a_sentence():
    out = parsers.parse_listing("Nice 2 bed 1 bath place, 850 sq ft, 5 minute drive to campus. $1,300/mo", "")
    assert "address" not in out and out["sqft"] == 850


def test_values_are_plain_numbers():
    out = parsers.parse_listing("1 bed 1 bath 600 sq ft $1,250/mo", "")
    assert out["price"] == 1250 and isinstance(out["price"], int) and out["baths"] == 1


def test_dates_without_a_year_use_the_next_one(monkeypatch):
    monkeypatch.setattr(parsers, "_today", lambda: date(2026, 11, 13))
    assert parsers.parse_listing("Available Aug 1", "")["available_from"] == "2027-08-01"
    assert parsers.parse_listing("Available 12/15", "")["available_from"] == "2026-12-15"
    assert parsers.parse_listing("Date available: 2027-07-31", "")["available_from"] == "2027-07-31"
