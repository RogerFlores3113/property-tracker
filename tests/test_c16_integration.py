"""Cycle 16 join: checks across groups."""
from prophelper.parsers import parse_listing as P


def test_budget_for_both_refers_to_the_utilities_named_just_before():
    r = P("2BR $1,200/mo. Tenant pays gas and electric. Budget about $90/mo for both.")
    assert (r["utilities_estimate"], r["tenant_pays"]) == (90, "electric, gas")
    assert "not counted anywhere" not in r.get("found_in_listing", "")


def test_budget_for_both_after_tenant_cues():
    r = P("2BR $1,200/mo. Heat is gas, tenant pays. Gas cooking, electric tenant. Budget around $90/mo for both.")
    assert r["utilities_estimate"] == 90 and "electric" in r["tenant_pays"] and "gas" in r["tenant_pays"]


def test_budget_for_both_after_included_line_is_not_guessed():
    r = P("2BR $1,200/mo. Water and trash included. Budget about $90/mo for both.")
    assert r.get("utilities_estimate") is None


def test_street_number_is_never_rent():
    r = P("2br/1ba duplex - $1,350 (German Village)\nHOUSE FOR RENT. 612 Mohawk St Columbus OH 43206")
    assert r["price"] == 1350
