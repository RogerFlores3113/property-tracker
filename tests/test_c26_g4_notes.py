"""Cycle 26 G4: a figure set to $0, included, optional, a special, another lease length or an old price is never named as missing or in the
monthly headline; notes say "counted" only when a field holds the figure; a "no amount" note goes when a field holds a figure; duplicates merge."""
from __future__ import annotations

import pytest

from prophelper import compare, dropguard, money
from prophelper import parsers as P


def _all(text: str, mode: str = "rent"):
    r = P.parse_listing(text, "", buying=(mode == "buy"))
    place = dict(r, reader_notes=r.get("found_in_listing"), listing_text=text)
    c = money.true_monthly_cost(place, mode)
    return r, c, compare._missing_names(dict(place, cost=c, score={"unknown": []}))


def _label(notes: str, **place):
    return money.open_notes_label(notes, place or None)


# ---- 1. figures that are closed never show as missing or in the headline (reviewer notes and other wordings)
CLOSED_NOTES = [
    'The listing also says "month-to-month at $2,525". Ask what the month to month terms and rent are.',
    'The listing also says "month to month $2,600 a month". It is not counted anywhere. Check what it is for.',
    'The listing also says "Month-to-month lease: $2,450". It is not counted anywhere. Check what it is for.',
    'The listing also says "Seller pays $6,000". It is not counted anywhere. Check what it is for.',
    'The listing also says "Seller to pay $4,500 of closing costs". It is not counted anywhere. Check what it is for.',
    'The listing also says "seller credit of $3,000". It is not counted anywhere. Check what it is for.',
    'The listing mentions laundry ("Washer and dryer, 1-car garage included ($0)"), but I could not tell what kind. Ask if it is in the unit.',
    'The listing also says "Parking $0 first spot". It is not counted anywhere. Check what it is for.',
    'The listing also says "garage upgrade $130 monthly". It is a monthly fee and it is not counted anywhere. Check what it is for.',
    'The listing also says "Optional storage locker $25/mo". It is not counted anywhere. Check what it is for.',
]


@pytest.mark.parametrize("note", CLOSED_NOTES)
def test_closed_figures_are_not_missing(note):
    assert money.open_listing_notes(note, {}) == []
    assert not money.listing_notes_uncounted(note, {})


def test_optional_note_closes_the_same_figure_in_another_note():
    notes = ("A parking space is available for $55 a month. It looks optional, so it is not counted in the monthly cost. Ask if it is required.\n"
             'The listing also says "reserved spot $55/mo". It is a monthly fee and it is not counted anywhere. Check what it is for.')
    assert money.open_listing_notes(notes, {}) == []
    notes = notes.replace("reserved spot $55/mo", "covered carport $55 a month")
    assert money.open_listing_notes(notes, {}) == []


@pytest.mark.parametrize("note", [
    'The listing also says "Trash $20 monthly". It is not counted anywhere. Check what it is for.',
    'The listing also says "Pest control $12/mo, 12 months". It is not counted anywhere. Check what it is for.',
    'The listing also says "Required parking permit $40 monthly". It is not counted anywhere. Check what it is for.',
])
def test_open_figures_stay_missing(note):
    assert money.listing_notes_uncounted(note, {})


def test_required_amount_is_not_closed_by_an_optional_note_with_another_figure():
    notes = ("A garage is available for $140 a month. It looks optional, so it is not counted in the monthly cost. Ask if it is required.\n"
             'The listing also says "Parking fee $90 required". It is not counted anywhere. Check what it is for.')
    assert money.listing_notes_uncounted(notes, {})
    assert "$90" in _label(notes)


@pytest.mark.parametrize("text", [
    "Rent $1,500. Parking: reserved covered spot $55/mo, garage upgrade $130/mo. Water included.",
    "Rent: $1,500 | Parking: covered spot $55/month optional | garage upgrade $130/month | water included",
    "Rent $1,500\n- reserved covered spot $55/mo\n- garage upgrade $130/mo\nWater included.",
])
def test_optional_parking_never_in_headline(text):
    r, c, missing = _all(text)
    assert "$55" not in c["headline"] and "$130" not in c["headline"]
    assert not any("$55" in m or "$130" in m for m in missing)


def test_family_month_to_month_not_in_headline():
    text = "2 bed 1 bath. Rent $2,325. 12 month lease, or month-to-month at $2,525. Pets by approval."
    r, c, missing = _all(text)
    assert r.get("price") == 2325
    assert "$2,525" not in c["headline"] and not any("$2,525" in m for m in missing)


def test_uiuc_garage_included_zero_not_missing():
    text = "1 bed 1 bath. Rent range $1,525-$1,575 depending on floor. Washer and dryer, dishwasher, 1-car garage included ($0)."
    r, c, missing = _all(text)
    assert not any("$0" in m for m in missing) and "$0" not in c["headline"]


def test_buyer_seller_pays_not_in_monthly_headline():
    r, c, missing = _all("3 bed 2 bath home for sale $325,000. Seller pays $6,000. HOA $100/mo.", "buy")
    assert "$6,000" not in c["headline"] and not any("$6,000" in m for m in missing)
    r, c, missing = _all("Condo for sale $300,000. Seller to pay $4,000 at closing. HOA $120 per month.", "buy")
    assert "$4,000" not in c["headline"]


# ---- 2. one sentence for utilities not counted (the page already says "missing: electric")
def test_no_second_sentence_for_unpriced_utilities():
    text = "2 bed 1 bath $1,450. Tenant pays electric. Water/sewer/trash $60 flat."
    r, c, missing = _all(text)
    assert not any("You also pay" in n for n in c["notes"])
    assert any("electric" in m for m in c["missing"]) or any("electric" in m for m in missing)


def test_same_figure_same_reason_one_note():
    facts = ['The listing also says "Cable $30 monthly". It is not counted anywhere. Check what it is for.',
             'The listing also says "Cable $30 monthly". It is not counted anywhere. Check what it is for.']
    assert len(dropguard.finalize_notes("", {}, facts)) == 1


# ---- 3. "counted" wording is checked against the final fields
def test_other_amounts_counted_is_true_or_absent_uiuc():
    text = ("1 BR $1,365. Springfield Ave, Champaign IL 61820.\n"
            "Utilities: you pay electric and water ($40 and $35 typical). Trash included.\n"
            "Application $35, lease admin $125, deposit $400.")
    r = P.parse_listing(text, "")
    notes = str(r.get("found_in_listing") or "")
    if r.get("utilities_estimate") is None:
        assert "the other amounts in that line are counted" not in notes
        assert "$40" in notes and "$35" in notes


@pytest.mark.parametrize("line", [
    "Utilities: you pay electric and water ($40 and $35 typical).",
    "You pay electric and water (about $40 and $35 typical). Application fee $35.",
    "Tenant utilities - electric ($40) and water ($35), typical figures.",
])
def test_counted_claim_matches_fields(line):
    text = "1 bed 1 bath. Rent $1,365.\n" + line + "\nApplication $35."
    r = P.parse_listing(text, "")
    for n in str(r.get("found_in_listing") or "").splitlines():
        if "the other amounts in that line are counted" in n:
            est = r.get("utilities_estimate")
            assert est is not None


def test_rewrites_a_false_counted_claim():
    facts = ['The listing also says "Utilities: electric and water ($40 and $35 typical)". Only $40 of that looks like a utility cost and it is not counted anywhere; the other amounts in that line are counted. Check what it is for.']
    out = dropguard.finalize_notes("Utilities: electric and water ($40 and $35 typical)", {"application_fee": 35.0}, facts)
    assert out and "the other amounts in that line are counted" not in out[0]
    assert "not counted anywhere" in out[0]


def test_true_counted_claim_stays():
    q = "Electric about $35. Free lot; reserved covered spot $60"
    facts = [f'The listing also says "{q}". Only $60 of that is a monthly fee and it is not counted anywhere; the other amounts in that line are counted. Check what it is for.']
    out = dropguard.finalize_notes(q, {"utilities_estimate": 35.0}, facts)
    assert out and "$60" in out[0]


# ---- 4. "no amount" note goes when a field holds a figure
RUBS = "The listing says utilities are billed back to you (RUBS), but it gives no amount and doesn't say which utilities. Ask the landlord which ones and about how much, then add a utilities estimate."


def test_roommates_no_amount_note_goes():
    text = ("Edgewater 3 Bed 2 Bath Chicago IL 60660 $3,120 / month. Utilities billed back: water/sewer/trash $75 flat; electric & gas direct with utility "
            "providers (ComEd / Peoples Gas). Internet included. Parking $0 for first spot. Security deposit $3,120.")
    r = P.parse_listing(text, "")
    notes = str(r.get("found_in_listing") or "")
    assert "gives no amount" not in notes
    assert r.get("other_monthly_fees") == 75 or r.get("utilities_estimate") == 75


def test_no_amount_note_stays_when_no_field():
    out = dropguard.finalize_notes("", {}, [RUBS])
    assert out == [RUBS]
    assert dropguard.finalize_notes("", {"utilities_estimate": 90.0}, [RUBS]) == [RUBS]  # an estimate for something else does not answer it
    out = dropguard.finalize_notes("Utilities billed back to you: water/sewer $90 flat.", {"utilities_estimate": 90.0}, [RUBS])
    assert out == []
    out = dropguard.finalize_notes("", {"other_monthly_fees": 75.0}, [RUBS, "The water/sewer/trash flat fee is $75, counted once in other monthly fees. Ask if that is right."])
    assert len(out) == 1 and "flat fee" in out[0]


def test_different_items_with_the_same_figure_stay_two_notes():
    facts = ['The listing also says "Pet rent $35". It is not counted anywhere. Check what it is for.',
             'The listing also says "Applicants: $35 per adult". It is not counted anywhere. Check what it is for.']
    assert len(dropguard.finalize_notes("", {}, facts)) == 2


def test_optional_elsewhere_does_not_rewrite_a_note_with_another_figure():
    q = "Valet parking $200/month optional. 720 sq ft. Priced $5,000 under appraisal"
    facts = ['A parking space is available for $200 a month. It looks optional, so it is not counted in the monthly cost. Ask if it is required.',
             f'The listing also says "{q}". It is a monthly fee and it is not counted anywhere. Check what it is for.']
    out = dropguard.finalize_notes(q, {}, facts)
    assert out == facts
