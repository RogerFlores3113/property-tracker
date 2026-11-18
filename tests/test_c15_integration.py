"""Cycle 15 join: checks across groups (G1 utilities + G2 fees)."""
from prophelper.parsers import parse_listing as P


def test_mandatory_internet_counted_once_not_in_utilities():
    r = P("Hyde Park 3BR $3,200/mo. Typically around $55 electric, avg $70 gas. Internet (Xfinity) $60/mo mandatory.")
    assert (r["utilities_estimate"], r["other_monthly_fees"]) == (125, 60)
    n = r["found_in_listing"]
    assert "Electric and gas are about $125 a month" in n and n.count("$60") == 1


def test_internet_alone_fee_has_no_utilities_estimate():
    r = P("Internet (Xfinity) $60/mo mandatory")
    assert r["other_monthly_fees"] == 60 and r.get("utilities_estimate") is None
    assert "utilities estimate" not in r["found_in_listing"]


def test_tenant_pays_internet_estimate_stays_a_utility():
    r = P("2BR $1,400/mo. Tenant pays internet, about $60/mo.")
    assert r["utilities_estimate"] == 60 and r.get("other_monthly_fees") is None
