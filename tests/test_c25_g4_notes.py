"""Cycle 25 G4: figures a note explains never show as missing amounts, a note never repeats a counted value, cents are shown with cents,
a trailing dollar sign is money, small note cleanups."""
from __future__ import annotations

import os
import re

import pytest

from prophelper import compare, dropguard, helpers, money
from prophelper import parsers as P

PANEL = os.environ.get("PH_PANEL", "/tmp/claude-0/-home-user-property-helper/be454331-cd61-59ba-9ebc-8cb8b7ec6a12/scratchpad/panel")


def _place(text: str, mode: str = "rent", **extra):
    r = P.parse_listing(text, "", buying=(mode == "buy"))
    r.update(extra)
    place = dict(r, reader_notes=r.get("found_in_listing"), listing_text=text)
    c = money.true_monthly_cost(place, mode)
    return r, c, dict(place, cost=c, score={"unknown": []})


def _label(notes: str, **place) -> str:
    return money.open_notes_label(notes, place or None)


# ---- 1. explained figures never show as missing, by meaning, in several wordings
@pytest.mark.parametrize("note", [
    "The listing gives a different rent for each lease length: $1,490 for 13 months; $1,540 for 12 months. Ask which lease length you would get.",
    'The listing also says "6 month lease available at $2,550". It is not counted anywhere. Check what it is for.',
    'The listing also says "9-month lease: $1,445". It is not counted anywhere. Check what it is for.',
    "The listing gives 2 bedroom plans at $1,380; $1,520; $1,480. Ask which plan you want.",
    'The listing also says "Move-in special: $99 deposit with approved credit". It is not counted anywhere. Ask what the deposit will be.',
    "The listing gives a best-case deposit of $99 with approved credit. It is not saved. Ask what the deposit will be if it is more.",
    'The listing also says "Special assessment pending: $8,500, amount to be split among owners, vote scheduled". It is not counted anywhere. Check what it is for.',
    'The listing also says "One-time admin charge $150 at move-in". It is not counted anywhere. Check what it is for.',
    "The listing also gave $1,200 before, which is the old price and is not used. Ask if the rent saved is right.",
])
def test_explained_figures_are_not_missing(note):
    assert not money.listing_notes_uncounted(note, {})
    assert money.open_listing_notes(note, {}) == []


@pytest.mark.parametrize("note", [
    'The listing also says "Trash $20 monthly". It is not counted anywhere. Check what it is for.',
    'The listing also says "Pest control $12/mo, 12 months". It is not counted anywhere. Check what it is for.',
    "The listing mentions a $35 amenity fee but not when it is due, so it is not counted. Ask what it is for.",
])
def test_unexplained_figures_stay_missing(note):
    assert money.listing_notes_uncounted(note, {})


def test_label_names_only_the_unexplained_figure():
    notes = ("The listing gives a different rent for each lease length: $1,490 for 13 months; $1,540 for 12 months. Ask which lease length you would get.\n"
             'The listing also says "Trash $20 monthly". It is not counted anywhere. Check what it is for.')
    label = _label(notes)
    assert "$1,540" not in label and "$1,490" not in label


@pytest.mark.parametrize("name,expect_in_missing", [
    ("r24-nontech-l7", ["$1,540", "$99"]),
    ("r24-nontech-l15", ["$1,520"]),
    ("r24-uiuc-l19", ["$1,325", "$1,445"]),
    ("r24-family-l8", ["$2,550"]),
])
def test_reviewer_listings_headline_has_no_explained_amounts(name, expect_in_missing):
    path = os.path.join(PANEL, name + ".txt")
    if not os.path.exists(path):
        pytest.skip("panel listing not available")
    text = open(path, encoding="utf-8").read()
    r, c, p = _place(text)
    shown = " ".join([c["headline"], *compare._missing_names(p), compare._not_counted_text(p)])
    for fig in expect_in_missing:
        assert fig not in shown, (fig, shown)
    assert not any("listing notes" in u for u in c.get("uncounted") or []) or "$" not in (c.get("listing_notes_label") or "")


def test_buyer_pending_special_assessment_is_not_a_monthly_unknown():
    text = ("Hilltop 2BR Condo 2 bed 1 bath $189,900\nLot 4, 3500 W Broad St #C, Columbus, OH 43228\n"
            "HOA is $95/mo. Special assessment pending: $8,500, amount to be split among owners, vote scheduled. Taxes $2,300/yr.\n")
    _r, c, p = _place(text, "buy")
    shown = " ".join([c["headline"], *compare._missing_names(p)])
    assert "8,500" not in shown and "assessment" not in shown.lower()


@pytest.mark.parametrize("text", [
    "2 bed 1 bath $1,500/mo. 12 month lease $1,500, 15 month lease $1,450. Water included.",
    "2 bed 1 bath rent $1,500. Lease terms: 12 months $1,500 / 6 months $1,650. Water included.",
    "2 bed 1 bath rent $1,500.\n- 12 months: $1,500\n- 6 months: $1,650\nWater included.",
])
def test_other_lease_lengths_never_in_headline(text):
    r, c, p = _place(text)
    assert r["price"] == 1500
    shown = " ".join([c["headline"], *compare._missing_names(p)])
    assert "1,650" not in shown and "1,450" not in shown


# ---- 2. a note that repeats a counted value
@pytest.mark.parametrize("line", [
    "Move-in: $1.5 months rent deposit hold.",
    "Move-in: $1.5 months rent deposit due.",
    "Move-in: $1.5 months rent deposit hold (refundable).",
])
def test_months_count_with_a_dollar_sign_is_explained_by_the_deposit_field(line):
    months = float(re.search(r"\$(\d(?:\.\d)?)", line).group(1))
    text = f"1 bed 1 bath. Rent $1,500 per month. {line} Lease 12 months.\n"
    r, c, p = _place(text)
    assert r.get("deposit") == pytest.approx(1500 * months)
    notes = str(r.get("found_in_listing") or "")
    assert "not counted anywhere" not in notes and f"${months:g} " not in notes
    assert not any("listing notes" in u for u in c.get("uncounted") or [])
    assert not any(f"${months:g}" in n for n in compare._missing_names(p))


# ---- 3. cents shown with cents
def test_money_exact_shows_cents_only_when_the_value_has_them():
    assert helpers.money_exact(38.5) == "$38.50"
    assert helpers.money_exact(125.25) == "$125.25"
    assert helpers.money_exact(2182.5) == "$2,182.50"
    assert helpers.money_exact(2287.5) == "$2,287.50"
    assert helpers.money_exact(8.5) == "$8.50"
    assert helpers.money_exact(1200) == "$1,200"
    assert helpers.money_exact(1200.0) == "$1,200"
    assert helpers.money_exact(None) == ""


def test_cash_total_equals_the_sum_of_the_shown_items():
    text = "2 bed 1 bath. Rent $1,340 per month. Deposit $1,340. Application fee $38.50. Move-in fees $125.25.\n"
    r, c, _p = _place(text)
    cash = c["cash_at_move_in"]
    shown = [round(float(helpers.money_exact(x["amount"]).replace("$", "").replace(",", "")), 2) for x in cash["parts"]]
    assert sum(shown) == pytest.approx(cash["total"])
    assert cash["total"] == pytest.approx(1340 + 1340 + 38.5 + 125.25)
    assert helpers.money_exact(cash["total"]) == "$2,843.75"


def test_place_page_shows_cents(client, store):
    s = store.add_search(name="S") if hasattr(store, "add_search") else None
    if s is None:
        pytest.skip("no search helper")
    p, _ = store.add_place(search_id=s["id"], title="Cents", address="1 Oak St", price=1340, deposit=1340, application_fee=38.5, move_in_fees=125.25)
    html = client.get(f"/places/{p['id']}").text
    assert "$38.50" in html and "$125.25" in html and "$2,843.75" in html
    assert "Application fee: <strong>$38.50</strong>" in html or "$38.50" in html


def test_compare_cash_cell_keeps_cents():
    text = "2 bed 1 bath. Rent $1,340 per month. Deposit $1,340. Application fee $38.50. Move-in fees $125.25.\n"
    _r, _c, p = _place(text)
    assert "$2,843.75" in compare._cash_cell(p)["text"]


# ---- 4. trailing dollar sign
@pytest.mark.parametrize("t,expect", [
    ("парковка 50$", "парковка $50"),
    ("парковка 50 $", "парковка $50"),
    ("Parking: 50$/mo", "Parking: $50/mo"),
    ("Parking 50 $ per month", "Parking $50 per month"),
    ("fee 1,200$", "fee $1,200"),
    ("Parking $50 and $60", "Parking $50 and $60"),
    ("Deposit $500 $600", "Deposit $500 $600"),
])
def test_trailing_dollar_sign_is_money(t, expect):
    assert P.normalize_money(t) == expect


@pytest.mark.parametrize("line", ["парковка 50$", "парковка 50 $", "Парковка: 50 $ в месяц"])
def test_trailing_dollar_figure_is_read_or_quoted(line):
    text = f"Квартира 1 спальня. Аренда $1,500 в месяц.\n{line}\n"
    r = P.parse_listing(text, "")
    notes = str(r.get("found_in_listing") or "")
    placed = any(isinstance(r.get(k), (int, float)) and r.get(k) and abs(float(r[k]) - 50) < 0.01 for k in ("parking_cost", "other_monthly_fees"))
    assert placed or "$50" in notes


def test_english_trailing_dollar_parking_is_read():
    r = P.parse_listing("1 bed 1 bath. Rent $1,500 per month.\nParking: 50$ per month\n", "")
    assert r.get("parking_cost") == 50 or "$50" in str(r.get("found_in_listing"))


# ---- 5. small note cleanups
def test_concession_total_note_does_not_repeat_the_concession_note():
    text = "2 bed 1 bath apartment. Rent $3,100 per month.\n$6,000 in concessions, 1 month free on 13-month lease.\n"
    r = P.parse_listing(text, "")
    notes = str(r.get("found_in_listing") or "")
    assert "6,000" not in notes
    assert "concession" in notes.lower() or "free" in notes.lower()


def test_no_ask_about_lease_length_when_one_is_stated():
    text = "2 bed 1 bath apartment. Rent $3,100 per month.\n1 month free on 13-month lease.\n"
    notes = str(P.parse_listing(text, "").get("found_in_listing") or "")
    assert "Ask how long the lease is" not in notes


@pytest.mark.parametrize("text", [
    "2 bed 1 bath apt, $1,500 per month. Move-in special: $99 security deposit with approved credit. Water included.",
    "Rent $1,500 per month, 2 bed 1 bath. Water included.\nSpecial: $99 deposit with approved credit.",
    "2 bed 1 bath. $1,500/mo. Best-case deposit $99 (approved credit). Water included.",
])
def test_move_in_special_deposit_is_not_a_headline_amount(text):
    r, c, p = _place(text)
    shown = " ".join([c["headline"], *compare._missing_names(p)])
    assert "$99" not in shown and "deposit in the listing notes" not in shown


def test_single_saved_note_with_every_figure_explained_is_closed():
    note = "The listing gives a best-case deposit of $99 with approved credit. The deposit is not saved, because it may be more for you, so ask what the deposit will be."
    assert not money.listing_notes_uncounted(note, {})


def test_deposit_of_one_and_a_half_months_keeps_its_cents_on_the_place_page(client, store):
    s = store.add_search(name="S")
    p, _ = store.add_place(search_id=s["id"], title="Half", address="2 Oak St", price=1455, deposit=2182.5, other_monthly_fees=8.5)
    html = client.get(f"/places/{p['id']}").text
    assert "$2,182.50" in html and "$8.50" in html
    assert "$2,182<" not in html and "$2,182 " not in html


def test_cost_lines_show_cents(client, store):
    s = store.add_search(name="S")
    p, _ = store.add_place(search_id=s["id"], title="Cents2", address="3 Oak St", price=1300, other_monthly_fees=8.5, utilities_included="all", parking="street", parking_cost=0, pet_rent=0)
    html = client.get(f"/places/{p['id']}").text
    assert ">$8.50<" in html
