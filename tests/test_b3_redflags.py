"""The local "things to check" pass: keyword and price rules, no AI."""
import pytest

from prophelper import parsers, redflags

from b3_listing_fixtures import FIXTURES

PEERS = [1500, 1600, 1550]


def flags(text, **place):
    return redflags.local_flags({"listing_text": text, "address": "410 Maple Row Lane", **place}, PEERS)


@pytest.mark.parametrize("text", [
    "Please wire the deposit to hold the unit.",
    "We only take gift cards for the first month.",
    "Pay with bitcoin and the apartment is yours.",
    "Rent is Zelle only.",
    "Owner is out of the country right now.",
    "I'm a missionary overseas so I can't show it.",
    "Deposit before viewing please.",
    "No showings, send the deposit to reserve.",
    "The keys will be mailed to you after payment.",
    "Act now, many people are interested, decide today!",
    "Send a copy of your ID before you see the place.",
    "Contact me on WhatsApp only.",
    "Address upon request.",
    "No credit check, no background check.",
    "Western Union accepted.",
])
def test_each_rule_fires(text):
    assert len(flags(text)) >= 1, text


def test_quiet_for_a_normal_listing():
    assert flags("Bright 1 bed near campus. In-unit laundry, dishwasher. Tours Tuesday and Thursday. Apply online after your tour.",
                 price=1500) == []
    assert flags("Wire shelving in the closets. Deposit is refundable.", price=1500) == []


def test_price_far_under_peers():
    assert any("far under" in f for f in flags("Nice place.", price=500))
    assert not any("far under" in f for f in flags("Nice place.", price=1400))
    assert not any("far under" in f for f in redflags.local_flags({"price": 100, "address": "1 Main St"}, [1500]))


def test_missing_and_vague_addresses():
    assert any("no address" in f.lower() for f in redflags.local_flags({"listing_text": "Cute place", "address": ""}, []))
    assert any("street number" in f for f in redflags.local_flags({"address": "Lake View"}, []))
    assert redflags.local_flags({"address": "", "lat": 40.1, "listing_text": "x"}, []) == []


def test_the_scam_fixture_gets_many_flags_and_real_ones_get_none():
    by = {f["name"]: f for f in FIXTURES}
    scam = by["scam looking listing still parses"]
    place = {**parsers.parse_listing(scam["text"], scam["url"]), "listing_text": scam["text"]}
    got = redflags.local_flags(place, PEERS)
    assert len(got) >= 5
    for name in ("zillow rental", "apartments.com floor plan with ranges and fees", "property manager site"):
        fx = by[name]
        place = {**parsers.parse_listing(fx["text"], fx["url"]), "listing_text": fx["text"]}
        assert redflags.local_flags(place, PEERS) == [], name


def test_never_calls_it_a_scam():
    for f in flags("wire the deposit, owner is abroad, no showings", price=400):
        assert "is a scam" not in f.lower()
