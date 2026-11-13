"""Cycle 3, group G1: reading money and facts from pasted listing text (deposits, first and last month, utilities,
buyer text, studio-plus, pet count, per-adult fee, scam hints on the preview, title prefill)."""
from __future__ import annotations

import sqlite3

import pytest

from conftest import local_client
from prophelper import parsers
from prophelper.store import Store

P = parsers.parse_listing


# --------------------------------------------------------------------------- deposits
def test_duplex_pet_deposit_never_replaces_the_security_deposit():
    out = P("Duplex 2BR/1BA $1,450/mo plus $1,450 deposit. Cats welcome, $250 deposit non-refundable.")
    assert out["deposit"] == 1450 and out["pet_fee"] == 250 and "pet_deposit" not in out and out["price"] == 1450


def test_pet_charge_listed_before_the_security_deposit():
    out = P("Rent $1,450. Cats ok.\n$250 deposit non-refundable\nSecurity deposit $1,450")
    assert out["deposit"] == 1450 and out["pet_fee"] == 250


def test_refundable_pet_deposit_and_plain_pet_deposit_are_pet_deposit():
    assert P("1BR $1,300. Dogs ok, $400 refundable pet deposit. Security deposit $1,300.")["pet_deposit"] == 400
    out = P("Cats ok. $300 pet deposit. 1BR $1,200/mo. Deposit $1,200")
    assert out["pet_deposit"] == 300 and out["deposit"] == 1200 and "pet_fee" not in out
    assert P("Cats ok. $300 non-refundable pet deposit. $1,200/mo")["pet_fee"] == 300


def test_deposit_equal_to_the_rent_in_words():
    assert P("Rent $1,100. Security deposit one month.")["deposit"] == 1100
    assert P("2 bed $1,500/mo. Deposit equal to one month's rent.")["deposit"] == 1500
    assert P("Rent $1,000. Security deposit: two months.")["deposit"] == 2000


def test_a_real_number_beats_the_words():
    assert P("Rent $1,100. Security deposit $900.")["deposit"] == 900


# --------------------------------------------------------------------------- months up front
def test_first_and_last_month_is_two_months_up_front():
    assert P("1BR $1,200/mo. First and last month's rent due at signing.")["months_up_front"] == 2
    assert P("1BR $1,200/mo. First and last month.")["months_up_front"] == 2
    assert "months_up_front" not in P("1BR $1,200/mo. Deposit $1,200.")


def test_three_months_only_when_the_text_says_so():
    assert P("1BR $1,200/mo. Three months' rent due at signing.")["months_up_front"] == 3
    assert P("1BR $1,200/mo. First, last and security deposit $1,200.")["months_up_front"] == 2


# --------------------------------------------------------------------------- utilities and parking
def test_tenant_pays_is_a_field():
    out = P("2BR $1,200/mo. Tenant pays gas and electric.")
    assert out["tenant_pays"] == "electric, gas" and "utilities_included" not in out
    assert P("Tenant pays electric, internet, trash. $900/mo")["tenant_pays"] == "electric, trash, internet"


@pytest.mark.parametrize("text,expected", [
    ("Heat and water included. 1BR $1,200", "heat, water"),
    ("Rent includes heat and water. 1BR $1,200", "heat, water"),
    ("Utilities included in rent. 1BR $1,200", "all utilities included"),
    ("All utilities included. 1BR $1,200", "all utilities included"),
    ("Utilities included. 1BR $1,200", "all utilities included"),
])
def test_included_utilities_fill_the_field(text, expected):
    assert P(text)["utilities_included"] == expected


def test_off_street_parking_included_is_free():
    for t in ("Off-street parking included. 1BR $1,200", "Includes off-street parking. 1BR $1,200"):
        out = P(t)
        assert out["parking"] == "lot" and out["parking_cost"] == 0


# --------------------------------------------------------------------------- buyer text
def test_closing_costs_and_price_cut():
    out = P("3 bed home for sale $450,000. Estimated closing costs $9,800. Price reduced $10,000.")
    assert out["price"] == 450000 and out["closing_costs"] == 9800
    assert "Price reduced $10,000" in out["found_in_listing"]
    assert "closing_costs" not in P("1BR $1,200/mo")


# --------------------------------------------------------------------------- beds, pets, fees
def test_studio_plus_and_den():
    assert P("Studio-plus with a 1 bed layout and den. $1,000/mo")["beds"] == 1
    assert P("1 bed + den $1,300/mo")["beds"] == 1
    assert P("Studio apartment $900/mo")["beds"] == 0


def test_pet_count_limit_from_two_max():
    out = P("Dogs OK, 2 max, 75 lb limit. $900/mo 2 bed")
    assert out["pet_count_limit"] == 2 and out["pet_weight_limit"] == 75
    assert "pet_count_limit" not in P("Dogs OK, 75 lb limit. $900/mo")


def test_per_adult_fee_is_multiplied_in_the_preview_only(store):
    s = store.add_search("Pair", "rent", people=2)
    c = local_client(store)
    html = c.post("/add/parse", data={"text": "2BR $1,500/mo. Application fee $55 per adult.", "search_id": str(s["id"])}).text
    assert "per adult" in html and "$110 together" in html
    assert 'name="application_fee" value="55"' in html
    assert "together" not in P("2BR $1,500/mo. Application fee $55 per adult.")["found_in_listing"]


# --------------------------------------------------------------------------- the page
def test_preview_shows_the_scam_warning_in_the_place_page_words(store):
    store.add_search("S", "rent")
    c = local_client(store)
    html = c.post("/add/parse", data={"text": "1BR $400/mo 12 Oak St, Champaign, IL. Please wire the deposit before a showing."}).text
    assert "Things to check" in html and "hard to undo" in html


def test_preview_has_no_warning_for_a_clean_listing(store):
    store.add_search("S", "rent")
    c = local_client(store)
    html = c.post("/add/parse", data={"text": "1BR $1,200/mo 12 Oak Street, Champaign, IL 61820. Tour any weekday."}).text
    assert 'id="redflags"' not in html


def test_title_is_prefilled_with_the_street_and_has_a_placeholder(store):
    store.add_search("S", "rent")
    c = local_client(store)
    html = c.post("/add/parse", data={"text": "$1,200/mo\n12 Oak Street, Champaign, IL 61820"}).text
    assert 'name="title" value="12 Oak Street"' in html
    html = c.post("/add/parse", data={"text": "$1,200/mo"}).text
    assert 'name="title" value=""' in html and "A short name you&#39;ll recognize" in html


def test_new_fields_are_on_the_add_form_and_saved(store):
    store.add_search("S", "rent")
    c = local_client(store)
    html = c.post("/add/parse", data={"text": "1BR $1,200/mo. First and last month. Tenant pays gas and electric."}).text
    assert "Months of rent due before move-in" in html and "Utilities you pay" in html
    r = c.post("/add/save", data={"title": "T", "address": "1 A St", "price": "1200", "months_up_front": "2",
                                  "tenant_pays": "Gas and electricity, wifi"}, follow_redirects=False)
    assert r.status_code in (302, 303)
    p = store.list_places()[0]
    assert p["months_up_front"] == 2 and p["tenant_pays"] == "electric, gas, internet"
    page = c.get(f"/places/{p['id']}").text
    assert 'name="months_up_front"' in page and 'name="tenant_pays"' in page


def test_bad_months_up_front_is_refused(store):
    store.add_search("S", "rent")
    c = local_client(store)
    r = c.post("/add/save", data={"title": "T", "months_up_front": "40"})
    assert r.status_code == 400


def test_migration_adds_the_two_columns(tmp_path):
    path = tmp_path / "old.db"
    Store(path).close()
    con = sqlite3.connect(path)
    for col in ("months_up_front", "tenant_pays"):
        con.execute(f"ALTER TABLE places DROP COLUMN {col}")
    con.execute("PRAGMA user_version = 6")
    con.commit()
    con.close()
    s = Store(path)
    try:
        cols = {r["name"] for r in s._conn.execute("PRAGMA table_info(places)")}
        assert {"months_up_front", "tenant_pays"} <= cols and s.schema_version >= 7
    finally:
        s.close()
