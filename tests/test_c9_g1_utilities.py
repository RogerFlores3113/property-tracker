"""Cycle 9, group G1: the utilities reader. "all" only from "all utilities included"; tenant-pays words are never included."""
from __future__ import annotations

import pytest

from prophelper.money import rent_cost
from prophelper.parsers import parse_listing

# (id, text, included, tenant_pays, note words that must appear, note words that must not appear)
CASES = [
    ("vertical-no-colons", "Utilities Included\nWater\nSewer\nTrash\nTenant Pays\nElectric\nGas",
     "water, sewer, trash", "electric, gas", (), ("unclear",)),
    ("multi-line", "Utilities included:\nwater,\ntrash and sewer. Tenant pays:\nElectric\nGas\nInternet",
     "water, trash, sewer", "electric, gas, internet", (), ("unclear",)),
    ("none-dot", "Utilities included: none.", None, None, (), ()),
    ("none-line", "Utilities included\nNone", None, None, (), ()),
    ("na", "Utilities included: N/A", None, None, (), ()),
    ("included-utilities-none", "Included utilities: none", None, None, (), ()),
    ("no-utilities-included", "No utilities included. Tenant pays electric.", None, "electric", (), ()),
    ("none-then-tenant-pays", "Utilities included: none. Electric, gas, water paid by tenant.",
     None, "electric, gas, water", (), ("unclear",)),
    ("except-inverted", "Incl. utilities except electric! Heat + water + trash included.",
     "heat, water, trash", "electric", (), ()),
    ("full-list-short-included", "Utilities: Gas, Electric, Water and Sewer, Trash\nUtilities Included: Water, Trash",
     "water, trash", "electric, gas, sewer", (), ()),
    ("one-line-full-and-included", "Utilities: gas, water   Included: water", "water", "gas", (), ("unclear",)),
    ("heat-is-gas", "Heat is gas, tenant pays", None, "gas, heat", (), ()),
    ("all-other", "Utilities included: water, trash. Tenant pays all other utilities.",
     "water, trash", "electric, gas, sewer, internet", (), ()),
    ("cable-internet-sets-up", "Cable/Internet: Comcast, tenant sets up", None, "internet", (), ()),
    ("incl-utilities-but-electric-tenant", "Sunny 1BR from $1,560 incl. utilities\nElectric (Ameren) tenant pays",
     None, "electric", ("utilities are included", "electric"), ("unclear",)),
]


@pytest.mark.parametrize("cid,text,included,pays,yes,no", CASES, ids=[c[0] for c in CASES])
def test_utilities_phrasings(cid, text, included, pays, yes, no):
    out = parse_listing(text)
    assert out.get("utilities_included") == included
    assert out.get("tenant_pays") == pays
    assert out.get("utilities_included") != "all"
    note = str(out.get("found_in_listing") or "")
    for w in yes:
        assert w in note
    for w in no:
        assert w not in note
    assert "Tenant pays ." not in note
    assert "utilities_estimate" not in out


def test_all_still_comes_from_all_included():
    assert parse_listing("All utilities included. 2BR $1,500").get("utilities_included") == "all"
    assert parse_listing("Cozy studio $950/mo - utilities included - available Aug 1").get("utilities_included") == "all"


def test_none_does_not_invent_heat_or_internet():
    out = parse_listing("Utilities included: none. Electric, gas, water paid by tenant.")
    assert "heat" not in str(out.get("utilities_included") or "") and "internet" not in str(out.get("utilities_included") or "")


def test_unplaced_word_gets_a_note():
    out = parse_listing("Utilities included: water, recycling. Tenant pays electric.")
    assert out.get("utilities_included") == "water"
    assert out.get("tenant_pays") == "electric"
    assert "recycling" in out["found_in_listing"] and "Ask the landlord" in out["found_in_listing"]


def test_really_both_still_notes_conflict():
    out = parse_listing("Water included. Tenant pays water and electric.")
    assert "water" not in str(out.get("utilities_included") or "")
    assert "unclear" in out["found_in_listing"]


def test_billed_back_rubs_without_names():
    out = parse_listing("2BR $1,400. Utilities billed back via RUBS, avg $120/mo")
    assert out.get("utilities_estimate") == 120
    assert not out.get("utilities_included")
    place = dict(out, listing_text="2BR $1,400. Utilities billed back via RUBS, avg $120/mo")
    line = [l for l in rent_cost(place)["lines"] if l["key"] == "utilities"][0]
    assert line["amount"] == 120 and line["note"].startswith("Billed back, from the listing")
    assert not line["estimated"]


def test_rubs_alone_keeps_estimate_and_asks():
    text = "2BR $1,400. Utilities billed back via RUBS, avg $120/mo"
    out = parse_listing(text)
    assert out["utilities_estimate"] == 120
    assert "billed-back average of $120 a month but doesn't say which utilities it covers. Ask the landlord." in out["found_in_listing"]
    line = [l for l in rent_cost(dict(out, listing_text=text))["lines"] if l["key"] == "utilities"][0]
    assert line["amount"] == 120 and line["note"].startswith("Billed back, from the listing")


def test_rubs_plus_tenant_pays_electric_gas_stays_uncounted():
    text = "2BR $1,400. Utilities billed back via RUBS, avg $120/mo. Tenant pays electric and gas."
    out = parse_listing(text)
    assert out["utilities_estimate"] == 120
    assert out["tenant_pays"] == "electric, gas"
    cost = rent_cost(dict(out, listing_text=text))
    line = [l for l in cost["lines"] if l["key"] == "utilities"][0]
    assert "electric" in line["note"] and "gas" in line["note"] and "not counted yet" in line["note"]
    assert "utilities estimate" in cost["missing"]
