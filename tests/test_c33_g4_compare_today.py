"""Cycle 33, G4: Compare never says "Nothing unknown" for a utility on the pay list that has no price (roommates), and Today's "Needs a cost check" names the
amounts instead of "some amounts in the listing notes" (uiuc l11)."""
from __future__ import annotations

import os

import pytest

from prophelper import compare, enrich, parsers as P, today

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel")


def fixture(name: str) -> str:
    with open(os.path.join(FIX, name), encoding="utf-8") as fh:
        return fh.read()


def rows_for(store, texts, **extra):
    s = store.add_search("C", "rent")
    store.add_criterion(s["id"], "price", weight=50, dealbreaker=False, target={"max": 4000})
    for i, t in enumerate(texts):
        v = P.parse_listing(t, "")
        keep = {k: v[k] for k in ("tenant_pays", "utilities_estimate", "utilities_included", "beds", "baths", "price", "deposit", "other_monthly_fees", "pet_fee") if k in v}
        keep.setdefault("price", 3000)
        store.add_place(title=f"P{i}", address=f"{i + 1} A St", search_id=s["id"], parking_cost=0, other_monthly_fees=keep.pop("other_monthly_fees", 0), pets="none",
                        deposit=keep.pop("deposit", 3000), listing_text=t, reader_notes=v.get("found_in_listing"), **keep, **extra)
    return enrich.enrich_places(store, store.get_search(s["id"]))


def row_text(r):
    return compare.nothing_unknown_guard(r, compare.still_unknown_text(r))


@pytest.mark.parametrize("text", [
    "Tenant pays electric; internet. Electric about $60/mo.",
    "Tenant pays electric, internet. Electric about $60/mo.",
    "Resident pays electric about $70, internet.",
    "Tenant pays electric & internet. Electric $60.",
    "TENANT PAYS ELECTRIC; INTERNET. ELECTRIC ABOUT $60/MO.",
    "Utilities: tenant pays electric and internet (Comcast). Electric runs about $60 a month.",
])
def test_unpriced_internet_is_never_nothing_unknown(store, text):
    r = rows_for(store, ["3 bed 2 bath. Rent $3,000. Deposit $3,000. " + text])[0]
    assert "internet" in row_text(r).lower(), (row_text(r), r.get("tenant_pays"))
    assert row_text(r) != "Nothing unknown"


@pytest.mark.parametrize("text", [
    "Tenant pays: electric; gas; water. Typical bills $150",
    "Tenant pays electric, gas, internet. Typical bills about $165 a month.",
    "Tenant pays all utilities. Typical bills about $210 a month.",
    "Tenant pays electric; internet. Electric about $60/mo. Internet $55/mo.",
])
def test_a_figure_that_covers_the_pay_list_is_nothing_unknown(store, text):
    r = rows_for(store, ["3 bed 2 bath. Rent $3,000. Deposit $3,000. " + text])[0]
    assert "internet" not in row_text(r).lower() or "$55" in text
    assert "gas" not in row_text(r).lower() and "water" not in row_text(r).lower()


def test_pay_list_helper_ignores_except_clauses(store):
    r = rows_for(store, ["3 bed 2 bath. Rent $3,000. Tenant pays everything but trash. Trash included."])[0]
    assert "trash" not in compare.pay_list_unpriced(r)


def test_pay_list_helper_names_what_the_field_lost(store):
    r = rows_for(store, ["3 bed 2 bath. Rent $3,000. Tenant pays electric; internet. Electric about $60/mo."])[0]
    assert compare.pay_list_unpriced(r) in ([], ["internet"])  # [] once the field keeps the whole list
    assert "internet" in row_text(r).lower()


# ---- Today: the amounts are named
def test_uiuc_l11_names_its_amounts(store):
    rows = rows_for(store, [fixture("r32-uiuc-l11.txt")])
    checks = today.cost_check(rows)
    # cycle 33 G3: its only uncounted amounts were pet fees, which a search with no pets leaves out quietly,
    # so the place may have no cost check at all; any check it has names its amounts.
    for c in checks:
        assert "some amounts in the listing notes" not in c["text"].lower()


BASE = "2BR, $1,395/mo. Water included. Deposit $500. "


@pytest.mark.parametrize("line,want", [
    ("Mystery charge $88 monthly.", "The $88 amount in the listing notes is not counted yet."),
    ("Mystery charge $88 monthly. Odd item $41 monthly.", "The $88 and $41 amounts in the listing notes are not counted yet."),
])
def test_named_amounts_with_the_right_verb(store, line, want):
    rows = rows_for(store, [BASE + line])
    got = [c["text"] for c in today.cost_check(rows)]
    assert got and any(want in g for g in got), got
    assert not any("some amounts" in g.lower() for g in got)


def test_a_place_with_nothing_open_is_not_listed(store):
    rows = rows_for(store, [BASE + "Parking included. Tenant pays nothing else."])
    assert not any("listing notes" in c["text"] for c in today.cost_check(rows))
