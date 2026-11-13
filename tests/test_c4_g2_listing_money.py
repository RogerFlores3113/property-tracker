"""Cycle 4, group G2: listing reader misses, per-adult application fee, seller credit, utilities wording."""
from __future__ import annotations

from datetime import date

import pytest

from conftest import local_client
from prophelper import money, parsers
from prophelper.store import Store

P = parsers.parse_listing


# --------------------------------------------------------------------------- 1. pet deposit and pet fee
def test_pet_deposit_then_non_refundable_pet_fee():
    out = P("Pet deposit $300, non-refundable pet fee $150")
    assert out["pet_deposit"] == 300 and out["pet_fee"] == 150


@pytest.mark.parametrize("text", ["$250 pet deposit, $150 non-refundable pet fee", "$250 refundable pet deposit and a $150 non-refundable pet fee"])
def test_dollar_first_pet_deposit_variants(text):
    out = P(text)
    assert out["pet_deposit"] == 250 and out["pet_fee"] == 150


def test_non_refundable_pet_deposit_is_still_a_fee():
    out = P("Pet deposit $300 non-refundable")
    assert out["pet_fee"] == 300 and "pet_deposit" not in out
    assert P("Non-refundable $250 pet deposit")["pet_fee"] == 250


# --------------------------------------------------------------------------- 2. available dates
@pytest.mark.parametrize("text,month", [("Move in ready Feb 1", 2), ("Available Feb 1", 2), ("Ready March 1st", 3)])
def test_available_date_without_a_year_is_the_next_one(text, month, monkeypatch):
    monkeypatch.setattr(parsers, "_today", lambda: date(2026, 11, 13))
    assert P(text)["available_from"] == f"2027-{month:02d}-01"


def test_available_date_is_never_today_unless_it_says_now(monkeypatch):
    monkeypatch.setattr(parsers, "_today", lambda: date(2026, 2, 1))
    assert P("Move in ready Feb 1")["available_from"] == "2027-02-01"
    assert P("Move in ready now")["available_from"] == "2026-02-01"


# --------------------------------------------------------------------------- 3. first plus last
def test_first_plus_last_month_is_two_months_up_front():
    out = P("Rent $1,000/mo. First month's rent plus last month's rent due at signing.")
    assert out["months_up_front"] == 2


# --------------------------------------------------------------------------- 4. utilities
def test_tenant_responsible_for_all_utilities():
    out = P("Tenant responsible for all utilities")
    assert out["tenant_pays"] == "electric, gas, water, sewer, trash, heat"


def test_sewer_is_kept_in_tenant_pays(store):
    assert P("Tenant pays gas, electric and sewer")["tenant_pays"] == "electric, gas, sewer"
    s = store.add_search("S")
    p, _ = store.add_place(search_id=s["id"], title="A", tenant_pays="water, sewer, trash")
    assert p["tenant_pays"] == "water, sewer, trash"


def test_billed_back_utilities_are_counted():
    out = P("Water, sewer and trash billed back at $85/month. Rent $1,500/mo")
    assert out["tenant_pays"] == "water, sewer, trash" and out["utilities_estimate"] == 85 and out["price"] == 1500
    cost = money.rent_cost({"price": 1500, **{k: out[k] for k in ("tenant_pays", "utilities_estimate")}})
    assert cost["total"] == 1585 and not cost["uncounted"]


# --------------------------------------------------------------------------- 5. per-adult application fee
def test_per_adult_application_fee_is_flagged():
    out = P("Application fee $50 per adult")
    assert out["application_fee"] == 50 and out["application_fee_per_adult"] == 1
    assert P("$50 per adult application fee")["application_fee_per_adult"] == 1
    assert "application_fee_per_adult" not in P("Application fee $50")


def test_cost_multiplies_a_per_adult_fee_by_adults():
    place = {"price": 2000, "application_fee": 50, "application_fee_per_adult": 1, "lease_months": 12, "deposit": 0}
    one = money.true_monthly_cost(place, "rent", people=4)
    two = money.true_monthly_cost(place, "rent", people=4, adults=2)
    assert two["one_time_total"] == 100 and two["people"] == 2 and two["split_noun"] == "adults"
    assert one["one_time_total"] == 200  # no adults given: same as people
    assert "each for 2 adults" in two["headline_each"]
    cash = two["cash_at_move_in"]
    assert any(p["label"].startswith("Application fee") and p["amount"] == 100 for p in cash["parts"])


def test_search_adults_saved_and_validated(store):
    s = store.add_search("S", people=4, adults=2)
    assert s["adults"] == 2
    assert store.update_search(s["id"], adults="")["adults"] is None
    with pytest.raises(ValueError):
        store.update_search(s["id"], adults=0)


def test_search_form_has_adults_and_enrich_uses_it(store):
    s = store.add_search("S", people=4, adults=2)
    store.add_place(search_id=s["id"], title="A", price=2000, application_fee=50, application_fee_per_adult=1, lease_months=12)
    c = local_client(store)
    page = c.get(f"/search?id={s['id']}").text
    assert "Adults who will sign the lease" in page and "Kids don" in page
    assert c.post(f"/search/{s['id']}", data={"adults": "3", "people": "4"}, follow_redirects=False).status_code in (200, 303)
    assert store.get_search(s["id"])["adults"] == 3


def test_add_preview_note_counts_adults():
    v = {"application_fee": 55, "found_in_listing": "The application fee $55 is charged per adult, so each adult who applies pays it."}
    parsers.app_fee_note_for_people(v, 2)
    assert "For 2 adults that is $110 together." in v["found_in_listing"]


# --------------------------------------------------------------------------- 6. seller credit
@pytest.mark.parametrize("text", ["Seller will contribute up to $5,000 toward closing costs", "Seller concessions of $5,000 offered",
                                  "$5,000 seller credit at closing"])
def test_seller_credit_is_read(text):
    assert P(text)["seller_credit"] == 5000


def test_special_assessment_is_not_a_seller_credit():
    assert "seller_credit" not in P("Special assessment $5,000 paid by seller")


def test_cash_to_close_subtracts_the_seller_credit():
    place = {"price": 400000, "closing_costs": 12000, "seller_credit": 5000}
    c = money.cash_to_close(place)
    assert c["total"] == 80000 + 12000 - 5000
    assert any("Seller credit" in p["label"] and p["amount"] == -5000 for p in c["parts"])


def test_buy_form_shows_seller_credit_and_saves_it(store):
    s = store.add_search("Buy", "buy")
    p, _ = store.add_place(search_id=s["id"], title="H", price=400000, seller_credit=3000)
    assert p["seller_credit"] == 3000
    c = local_client(store)
    assert "Seller credit toward closing" in c.get(f"/places/{p['id']}").text
    assert "Seller credit toward closing" in c.get("/add?manual=1").text


# --------------------------------------------------------------------------- 7. smaller misses
def test_title_drops_a_trailing_bed_bath_suffix():
    assert P("Cozy Corner Home - 2 bed 1 bath\nRent $1,500/mo")["title"] == "Cozy Corner Home"
    assert P("Elm House | $1,500/mo | 2 bed")["title"] == "Elm House"


@pytest.mark.parametrize("text", ["Pets: max 2 cats", "Up to 2 pets allowed", "No more than 2 dogs"])
def test_pet_count_limit_variants(text):
    assert P(text)["pet_count_limit"] == 2


def test_off_street_parking_included():
    out = P("Rent $1,200/mo\nOff-street parking included")
    assert out["parking"] == "lot" and out["parking_cost"] == 0


def test_reserved_parking_prefers_a_better_value():
    assert P("Reserved covered parking $75/mo")["parking"] == "covered"
    assert P("Reserved garage space")["parking"] == "garage"


def test_breed_note_is_not_cut_inside_brackets():
    out = P("Breed restrictions apply (no pit bulls; no rottweilers). Cats ok.")
    assert out["pet_breed_note"] == "Breed restrictions apply (no pit bulls; no rottweilers)"


# --------------------------------------------------------------------------- 8. money wording
def test_included_utilities_are_not_called_unknown():
    cost = money.rent_cost({"price": 1500, "utilities_included": "heat, water, trash"})
    assert not cost["uncounted"] and "utilities" not in cost["missing"]
    line = next(l for l in cost["lines"] if l["key"] == "utilities")
    assert line["amount"] == 0 and "included" in line["note"]
    assert "not counted yet" not in money.headline(cost)


def test_pet_fee_alone_is_not_a_deposit_that_comes_back():
    cash = money.rent_cost({"price": 1500, "pet_fee": 300}, pets=True)["cash_at_move_in"]
    labels = [p["label"] for p in cash["parts"]]
    assert "Pet fee" in labels and not any("comes back" in l for l in labels)


def test_migration_adds_columns_to_an_old_database(tmp_path):
    s = Store(tmp_path / "x.db")
    cols = {r["name"] for r in s._conn.execute("PRAGMA table_info(places)")}
    assert {"seller_credit", "application_fee_per_adult"} <= cols
    assert "adults" in {r["name"] for r in s._conn.execute("PRAGMA table_info(searches)")}
    s.close()
