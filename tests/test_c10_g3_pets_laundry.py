"""Cycle 10 G3: pets and laundry reader. Unknown is better than wrong."""
import pytest

from prophelper.parsers import parse_listing


def _f(text, *keys):
    got = parse_listing(text)
    return {k: got.get(k) for k in keys}


@pytest.mark.parametrize("text", [
    "Laundry: Shared basement W/D, $2 per load", "W/D in basement shared by building", "coin laundry on site",
    "laundry room in building", "shared laundry"])
def test_shared_laundry_is_in_building(text):
    assert parse_listing(text)["laundry"] == "in_building"


def test_hookups_and_in_unit_still_read():
    assert parse_listing("W/D hookups")["laundry"] == "hookups"
    for t in ("in-unit W/D", "washer/dryer in unit", "W/D in unit"):
        assert parse_listing(t)["laundry"] == "in_unit", t


def test_pet_friendly_with_named_pets():
    got = parse_listing("Pet friendly: cats ok, $25/mo")
    assert got["pets"] == "cats" and got["pet_rent"] == 25 and "pet_fee" not in got


def test_pet_friendly_alone_and_pets_welcome_stay_both():
    assert parse_listing("Pet friendly")["pets"] == "both"  # pinned by the cycle 8 corpus
    got = parse_listing("Pets welcome w/ $400 deposit")
    assert got["pets"] == "both" and got["pet_deposit"] == 400


def test_cats_and_small_dogs():
    got = parse_listing("Cats and small dogs under 25 lbs")
    assert got["pets"] == "both" and got["pet_weight_limit"] == 25
    got = parse_listing("Cats only, 15 lb limit")
    assert got["pets"] == "cats" and got["pet_weight_limit"] == 15


@pytest.mark.parametrize("text,w", [
    ("Maximum 55 lbs.", 55), ("50 pounds or less at full grown size", 50), ("under 70 lbs", 70),
    ("Weight limit: under 70 lbs", 70), ("max weight 40#", 40), ("Pets welcome. Maximum 55 lbs.", 55),
    ("Dogs ok, max weight 40#", 40)])
def test_weight_limits(text, w):
    assert parse_listing(text)["pet_weight_limit"] == w


def test_weight_not_about_pets_is_ignored():
    assert "pet_weight_limit" not in parse_listing("Elevator max 2000 lbs. Pets ok")


def test_unreadable_weight_near_pets_gets_a_note():
    got = parse_listing("Dogs welcome, about 30 lbs typical")
    assert "pet_weight_limit" not in got
    assert "not clear if it is a limit" in got["found_in_listing"]


def test_pet_deposit_and_rent_amounts():
    got = parse_listing("Total pet deposit of $500 for up to two pets")
    assert got["pet_deposit"] == 500 and "pet_fee" not in got and got["pet_count_limit"] == 2
    got = parse_listing("$35 per pet per month")
    assert got["pet_rent"] == 35 and "pet_fee" not in got


def test_pipe_layout_keeps_security_deposit():
    got = parse_listing("Cats ok | No dogs | Deposit $500")
    assert got["pets"] == "cats" and got["deposit"] == 500
    assert "pet_deposit" not in got and "pet_fee" not in got
    got = parse_listing("Cats ok\nNo dogs\nDeposit $500")
    assert got["deposit"] == 500 and "pet_deposit" not in got


def test_pet_deposit_in_pet_sentence_still_pet():
    got = parse_listing("Pets: cats ok, deposit $250 | Security deposit $1,000")
    assert got["pet_deposit"] == 250 and got["deposit"] == 1000


def test_count_one_wording():
    assert parse_listing("max 1 cat")["pet_count_limit"] == 1
    from prophelper.compare import _pet_limits_text
    from prophelper.mcp_server import _extra_facts
    assert "1 pet at most" in _pet_limits_text({"pet_count_limit": 1})
    facts = _extra_facts({"pet_count_limit": 1})
    assert any("up to 1 pet" in x and "pets" not in x for x in facts)
    assert any("up to 2 pets" in x for x in _extra_facts({"pet_count_limit": 2}))
