"""C11 G1: the "Also in the listing" notes agree with the numbers, refresh after edits, and show well."""
import csv
import io

import pytest

from conftest import local_client
from prophelper import compare, money, parsers


def P(text):
    return parsers.parse_listing(text)


def notes(text):
    return P(text).get("found_in_listing", "")


# ---- 1. never "not counted" about a counted amount
@pytest.mark.parametrize("text,fees", [
    ("2 bed apartment $1,800/mo. Valet trash $25/mo. Smart home $30/mo.", 55),
    ("2 bed apartment $1,800/mo. Amenity fee $75/month.", 75),  # c12: a flat water and trash fee is now the utilities estimate, not another monthly fee
    ("1 bed $1,495/mo\nTrash valet $25/mo mandatory\nInternet package $60/mo required", 85),
])
def test_counted_monthly_fees_are_not_noted(text, fees):
    r = P(text)
    assert r["other_monthly_fees"] == fees
    assert "found_in_listing" not in r


def test_detached_garage_counted_as_parking_is_not_noted():
    r = P("1 bed $1,700. Detached garage $85/mo. Garage parking available. Parking: street.")
    assert r["parking_cost"] == 85 and "found_in_listing" not in r


def test_quarterly_hoa_is_not_noted():
    r = P("3 bed $420,000 for sale. HOA $210 per quarter.")
    assert r["hoa"] == 70 and "found_in_listing" not in r


def test_admin_fee_per_applicant_is_described_once():
    r = P("Olentangy Flats 2 bed $1,900/mo. Admin fee $100 per applicant.")
    assert r["application_fee"] == 100
    note = r.get("found_in_listing", "")
    assert "not counted" not in note and note.count("$100") <= 1


def test_second_different_admin_fee_is_still_noted():
    r = P("1 bed $1,500/mo. $55 admin fee per applicant. Application fee $50.")
    assert r["application_fee"] == 50
    assert "$55" in r["found_in_listing"] and "not counted" in r["found_in_listing"]


def test_a_really_uncounted_amount_is_still_noted():
    r = P("1 bed $1,500/mo. Smart home $30. Valet trash $25/mo.")
    assert r["other_monthly_fees"] == 25
    assert "Smart home $30" in r["found_in_listing"]


# ---- 2. lines whose facts landed in fields are not quoted again
def test_placed_pet_and_utility_lines_are_not_quoted():
    r = P("1 bed $1,500/mo. Pets: cats and dogs allowed, max 2 pets, 50 lb limit. Tenant pays electric, gas.")
    assert r["pets"] == "both" and r["pet_count_limit"] == 2 and r["pet_weight_limit"] == 50 and r["tenant_pays"] == "electric, gas"
    assert "found_in_listing" not in r


def test_a_pet_line_with_a_breed_rule_is_kept():
    r = P("1 bed $1,500/mo. Pets welcome, max 2 pets, no aggressive breeds.")
    assert "breeds" in r.get("found_in_listing", "")


# ---- 3. a note never contradicts a saved value
def test_wire_note_does_not_say_deposit_is_blank_when_saved():
    r = P("The Lofts. 1BR $1,495/mo\nSecurity deposit $1,250\nDeposit must be wired to hold the unit. Wire the deposit today.")
    assert r["deposit"] == 1250
    note = r["found_in_listing"]
    assert "left blank" not in note and "toured" in note


def test_wire_note_keeps_blank_wording_when_nothing_saved():
    r = P("1BR $1,495/mo. Wire the deposit to hold the unit.")
    assert "deposit" not in r and "left blank" in r["found_in_listing"]


# ---- 4. stale notes
def _place(store, text):
    store.add_search("S")
    found = parsers.parse_listing(text)
    fields = {k: v for k, v in found.items() if k not in ("found_in_listing",)}
    p, _ = store.add_place(title="Oak", address="1 Oak St", listing_text=text, reader_notes=found.get("found_in_listing", ""), **{k: v for k, v in fields.items() if k not in ("title", "source")})
    return p


def test_note_clears_when_the_field_is_filled(store):
    p = _place(store, "1 bed $1,500/mo. $75/mo utility package.")
    assert "$75/mo utility package" in p["reader_notes"]
    p = store.update_place(p["id"], utilities_estimate=75)
    assert p["reader_notes"] == ""


def test_other_notes_stay_when_one_field_is_filled(store):
    p = _place(store, "3 bed $420,000 for sale. Assessment $150/mo. Parking $75 extra.")
    assert "assessment" in p["reader_notes"].lower()
    p = store.update_place(p["id"], parking_cost=75, notes="called")
    assert "assessment" in p["reader_notes"].lower()


def test_web_edit_form_refreshes_notes(store):
    p = _place(store, "1 bed $1,500/mo. $75/mo utility package.")
    c = local_client(store)
    r = c.post(f"/places/{p['id']}", data={"title": "Oak", "utilities_estimate": "75"}, follow_redirects=False)
    assert r.status_code in (200, 303)
    assert store.get_place(p["id"])["reader_notes"] == ""


# ---- 5. the tag and its wording
@pytest.mark.parametrize("note", [
    'The listing also says "Parking $75". It is not counted anywhere. Check what it is for.',
    "The listing mentions an assessment of $150 a month. It is not saved as the one-time special assessment. Add it to other monthly fees if you will pay it, and ask who pays.",
    'The listing mentions parking ("garage"), but I could not tell what it is or what it costs. Ask.',
])
def test_open_money_notes_show_the_tag(note):
    assert money.listing_notes_uncounted(note)
    cost = money.true_monthly_cost({"price": 1500, "reader_notes": note}, "rent")
    assert money.LISTING_NOTES_UNCOUNTED in cost["uncounted"]
    assert "things in the listing" not in cost["headline"] and "some amounts in the listing notes not counted yet" in cost["headline"]


def test_notes_with_nothing_open_show_no_tag():
    assert not money.listing_notes_uncounted("The application fee $100 is charged per applicant, so each adult who applies pays it.")
    assert not money.listing_notes_uncounted("")


def test_compare_sentences_have_plain_words():
    p = {"cost": {"uncounted": [money.LISTING_NOTES_UNCOUNTED]}, "utilities_included": "all", "tenant_pays": ""}
    assert compare._short_parts(p) == "some amounts in the listing notes"
    assert compare._its("some amounts in the listing notes") == "" and compare._its("utilities") == "its "
    line = compare.skipped_unknown_sentences({"skipped_unknown": [p]}, lambda x: "Oak Row")[0]
    assert line == "Oak Row looks cheaper, but some amounts in the listing notes are not counted."


# ---- 6. Compare "Listing notes" row
CONC = "The listing mentions a free-rent offer (\"2 months free on a 14 month lease\"). It is not counted anywhere. Check the terms."
MONEY = 'The listing also says "Amenity fee $300 one-time". It is not counted anywhere. Check what it is for.'
MONEY2 = 'The listing also says "Parking $75". It is not counted anywhere. Check what it is for.'


def test_money_notes_come_first_and_nothing_is_cut_mid_sentence():
    t = compare.listing_notes_text({"reader_notes": CONC + " " + MONEY + " " + MONEY2}, 150)
    assert t.startswith("The listing also says \"Amenity fee $300 one-time\".")
    assert "free-rent" not in t.split(" and ")[0] and t.endswith("more on the place page.")
    assert "..." not in t
    assert "\"Amenity fee $300 one-time\". It is not counted anywhere. Check what it is for." in t


def test_short_notes_show_whole_with_no_more_line():
    t = compare.listing_notes_text({"reader_notes": MONEY}, 150)
    assert t == MONEY


def test_one_very_long_note_is_cut_at_a_sentence():
    long = 'The listing also says "' + "x " * 120 + '$50". It is not counted anywhere.'
    t = compare.listing_notes_text({"reader_notes": long}, 100)
    assert len(t) < 400 and not t.endswith("x")


def test_quote_fragment_is_not_cut_mid_sentence():
    text = "1 bed $1,500/mo. Lots of lovely things about the building and neighbourhood and the park nearby and shops, the Wi-Fi cafe lounge access costs $40 for the weekend."
    note = notes(text)
    assert "$40" in note
    quote = note.split('"')[1]
    assert quote.endswith("weekend") and "Lots of lovely" not in quote or len(quote) < 200


# ---- 7. CSV
def test_csv_has_listing_notes_column_and_is_formula_safe(store):
    store.add_search("S")
    store.add_place(title="Oak", address="1 Oak St", price=1500, reader_notes='=HYPERLINK("x") The listing also says "Parking $75". It is not counted anywhere.')
    store.add_place(title="Plain", address="2 Oak St", price=1400)
    c = local_client(store)
    rows = list(csv.reader(io.StringIO(c.get("/places.csv").text)))
    head = rows[0]
    assert "Listing notes" in head
    by = {r[0]: dict(zip(head, r)) for r in rows[1:]}
    assert by["Oak"]["Listing notes"].startswith("'=HYPERLINK")
    assert "Parking $75" in by["Oak"]["Listing notes"] and by["Plain"]["Listing notes"] == ""


def test_listing_notes_column_is_not_imported(store):
    from prophelper import csv_io
    assert csv_io.match_columns(["Title", "Listing notes"]) == {0: "title"}
    assert csv_io.is_computed_header("Listing notes")
