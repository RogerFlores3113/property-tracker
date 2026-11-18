"""Cycle 30 G5 items 3 to 5: "sold as-is" alone is a hint, not a Check first row; Today's New places leaves out places already under Check first;
a missing pet rent (search with pets) is one completeness answer on Today, the place page, Claude's tools and Compare."""
from __future__ import annotations

import os
import re

import pytest
from mcp_util import call, server, text

from prophelper import compare, enrich, redflags, today
from prophelper.parsers import parse_listing

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "panel")


def _read(name):
    return open(os.path.join(FIX, name), encoding="utf-8").read()


def _add(store, s, listing, buying=False, **extra):
    f = parse_listing(listing, buying=buying)
    f["reader_notes"] = f.pop("found_in_listing", "")
    f.update(extra)
    p, _ = store.add_place(search_id=s["id"], listing_text=listing, **f)
    return p


def _titles(items):
    return [(i["place"] if "place" in i else i)["title"] for i in items]


# ---- item 3: sold as-is alone
BUY = "Hilltop Park Condo. 1840 W Broad St #11, Columbus, OH 43223. 2 bed, 1 bath. $269,500. Condo dues $215 a month. {extra}"


@pytest.mark.parametrize("extra", ["Home sold as-is.", "Sold as is. Inspection period 10 days.", "Selling AS-IS, where is."])
def test_as_is_alone_is_a_hint_not_check_first(store, client, extra):
    s = store.add_search("B", "buy", budget_max=400000)
    p = _add(store, s, BUY.format(extra=extra), buying=True, title="Hilltop Park")
    flags = redflags.local_flags(store.get_place(p["id"]), mode="buy")
    assert any("sold as-is" in f for f in flags)
    assert redflags.scam_sign_flags(flags) == []
    out = today.build(store, store.get_search(s["id"]))
    assert "Hilltop Park" not in _titles(out["check_first"])
    assert "as-is" in re.sub(r"\s+", " ", client.get(f"/places/{p['id']}").text)  # still listed on the place page
    assert "possible scam" not in text(call(server(store), "list_places")).lower()


def test_as_is_with_a_real_scam_sign_stays_check_first(store):
    s = store.add_search("B", "buy", budget_max=400000)
    _add(store, s, BUY.format(extra="Sold as-is. Wire the earnest money today to my lawyer."), buying=True, title="Wire Place")
    out = today.build(store, store.get_search(s["id"]))
    assert "Wire Place" in _titles(out["check_first"])


def test_reviewer_buyer_l6_is_not_check_first(store):
    s = store.add_search("B", "buy", budget_max=400000)
    _add(store, s, _read("r29-buyer-l6.txt"), buying=True, title="Hilltop Park Condo")
    out = today.build(store, store.get_search(s["id"]))
    assert "Hilltop Park Condo" not in _titles(out["check_first"])


# ---- item 4: New places leaves out places under Check first
def test_email_only_place_is_check_first_and_not_new(store, client):
    s = store.add_search("R", "rent", budget_max=4000)
    store.add_criterion(s["id"], "price", weight=50, dealbreaker=False, target={"max": 4000})
    _add(store, s, _read("r29-roommates-l8.txt"), title="Bridgeport email only")
    _add(store, s, "2 bed, $1,500/mo. 12 Oak St, Urbana IL 61801. Call the office to tour.", title="Plain place")
    out = today.build(store, store.get_search(s["id"]))
    assert "Bridgeport email only" in _titles(out["check_first"])
    assert "Bridgeport email only" not in _titles(out["new"])
    assert "Plain place" in _titles(out["new"])
    page = client.get("/today").text
    new_part = page.split("New places")[1] if "New places" in page else ""
    assert "Bridgeport email only" not in new_part
    listing = text(call(server(store), "todays_list"))
    new_lines = listing.split("New places the user has not looked at:")[1]
    assert "Bridgeport" not in new_lines and "Plain place" in new_lines


@pytest.mark.parametrize("listing", [
    "2 bed, $1,500/mo. 12 Oak St, Urbana IL 61801. Text me only. No calls.",
    "2 bed, $1,500/mo. 12 Oak St, Urbana IL 61801. Contact via WhatsApp only.",
])
def test_other_check_first_wordings_not_new(store, listing):
    s = store.add_search("R", "rent", budget_max=1800)
    _add(store, s, listing, title="Hinted")
    out = today.build(store, store.get_search(s["id"]))
    assert "Hinted" in _titles(out["check_first"]) and "Hinted" not in _titles(out["new"])


# ---- item 5: one pet rent completeness answer
OAK = ("7 Oak St, Redwood City. 3 bed 2 bath $2,200. Fenced yard. Utilities: tenant pays electric and gas. Estimated $110 per month. "
       "Dogs ok up to 60 lbs, {pet}. Application fee $45. Security deposit $2,200.")


def _surfaces(store, client, s, p):
    q, _ = store.add_place(search_id=s["id"], title="Other", address="9 B St", price=2400, utilities_estimate=100, parking_cost=0, other_monthly_fees=0, pet_rent=30, pets="dogs", pet_fee=100)
    e = next(r for r in enrich.enrich_places(store, s) if r["id"] == p["id"])
    srv = server(store)
    page = re.sub(r"\s+", " ", client.get(f"/places/{p['id']}").text)
    return (e, client.get("/today").text, page, text(call(srv, "get_place", place_id=p["id"])), text(call(srv, "list_places")),
            text(call(srv, "compare_places", place_ids=[p["id"], q["id"]])), text(call(srv, "todays_list")))


@pytest.mark.parametrize("pet", ["pet fee $250", "pet deposit $300", "$250 one-time pet fee", "pet fee $250 and $300 refundable pet deposit"])
def test_pet_fee_without_pet_rent_is_not_complete_everywhere(store, client, pet):
    s = store.add_search("F", "rent", budget_max=4000, pet_kind="dog", pet_count=1)
    store.add_criterion(s["id"], "price", weight=50, dealbreaker=False, target={"max": 4000})
    p = _add(store, s, OAK.format(pet=pet), title="7 Oak St")
    assert p.get("pet_rent") is None
    e, today_html, page, got, lst, cmp_t, tl = _surfaces(store, client, s, p)
    assert compare.cost_incomplete(e) and "pet rent" in compare.cost_unknowns(e)
    assert today.unknown_cost_parts(e) == ["pet rent"] or "pet rent" in today.unknown_cost_parts(e)
    assert "not complete" in page.split('id="cost"')[1].split("</section>")[0] or "so far" in page
    assert "True monthly cost" not in got and "not complete" in got and "pet rent" in got
    line = next(l for l in lst.split("\n") if l.startswith(f"#{p['id']}"))
    assert "not complete" in line and "true cost" not in line
    still = next(l for l in cmp_t.split("\n") if l.startswith("Still unknown"))
    assert "Nothing unknown" not in still.split("|")[0] and "pet" in still.split("|")[0]
    assert "Lowest true monthly cost" not in cmp_t or f"#{p['id']} at" not in cmp_t.split("Lowest true monthly cost")[1][:40]


def test_pet_rent_given_is_complete_on_the_pet_side(store, client):
    s = store.add_search("F", "rent", budget_max=4000, pet_kind="dog", pet_count=1)
    p = _add(store, s, OAK.format(pet="pet fee $250, pet rent $35 a month"), title="7 Oak St", parking_cost=0, other_monthly_fees=0)
    e = next(r for r in enrich.enrich_places(store, s) if r["id"] == p["id"])
    assert e["pet_rent"] == 35 and "pet rent" not in compare.cost_unknowns(e) and not compare.pet_rent_unset(e)


def test_search_without_pets_leaves_pet_rent_out_the_same_everywhere(store, client):
    s = store.add_search("F", "rent", budget_max=4000)
    p = _add(store, s, OAK.format(pet="pet fee $250"), title="7 Oak St", parking_cost=0, other_monthly_fees=0)
    e, today_html, page, got, lst, cmp_t, tl = _surfaces(store, client, s, p)
    assert not compare.pet_rent_unset(e) and "pet rent" not in compare.cost_unknowns(e)
    assert "pet rent" not in today.unknown_cost_parts(e)
    assert "this search has no pets" in page and "this search has no pets" in got


def test_a_place_that_takes_no_pets_or_the_wrong_pet_has_no_pet_rent_gap(store):
    s = store.add_search("F", "rent", pet_kind="dog", pet_count=1)
    cats = _add(store, s, "2 bed, $1,500/mo. 12 Oak St 61820. Cats only, $250 pet fee.", title="Cats")
    none = _add(store, s, "2 bed, $1,500/mo. 12 Oak St 61820. No pets.", title="None")
    for p in (cats, none):
        e = next(r for r in enrich.enrich_places(store, s) if r["id"] == p["id"])
        assert not compare.pet_rent_unset(e) and "pet rent" not in today.unknown_cost_parts(e)
