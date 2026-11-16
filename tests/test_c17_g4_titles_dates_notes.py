"""Cycle 17, group G4: titles, 1x1 beds and baths, city after the street, lease dates, notes noise, one note per line."""
import pytest

from prophelper import money, parsers
from prophelper.parsers import parse_listing

from conftest import local_client


def P(text, **kw):
    return parse_listing(text, "", **kw)


def notes(r):
    return [n for n in (r.get("found_in_listing") or "").split("\n") if n]


# ----------------------------------------------------------------------------- 1. titles
@pytest.mark.parametrize("text, title", [
    ("Rent. 4120 Indianola Ave, Call for price\nCute 2 bedroom upstairs unit.", "4120 Indianola Ave"),
    ("Rent. 4120 Indianola Ave\nCute 2 bedroom upstairs unit.", "4120 Indianola Ave"),
    ("Pricing: 2BR $1,395 per month\n4455 Sawmill Rd, Columbus, OH 43220", "4455 Sawmill Rd"),
    ("Apartments.com style: Maple Court Apartments\n2 Beds, 1 Bath | 880 Sq Ft | $1,395 - $1,445 /mo\nPricing: 2BR Plan A $1,395 per month", "Maple Court Apartments"),
    ("Zillow style: Aspen Ridge Apartments\nPricing: 1BR $1,100 per month", "Aspen Ridge Apartments"),
    ("Hi Beautiful newly built 1 bed 1 bath at 88 Prospect Ave Champaign. $1,550 a month.", "88 Prospect Ave"),
    ("Hello! Sunny 2 bed 1 bath at 12 Oak St Urbana, $1,200 a month", "12 Oak St"),
    ("Hey there, lovely 3 bed house at 9 Elm Dr Savoy for rent $2,000", "9 Elm Dr"),
    ("LUXE 1x1 | $1,585/mo | The Hub-style living\nUnit 410, 33 N Neil St, Champaign.", "LUXE 1x1"),
    ("ASPEN 2x2 | $1,900/mo | Living at its best\n12 Oak St, Champaign", "ASPEN 2x2"),
])
def test_title_is_a_name_or_the_address(text, title):
    assert P(text).get("title") == title


def test_pilsen_style_name_before_the_address_stays():
    assert P("Pilsen Courtyard 3BR/2BA 1700 S Racine Ave Chicago IL 60608\n$2,000/mo").get("title") == "Pilsen Courtyard 3BR/2BA 1700 S Racine Ave Chicago IL 60608" \
        or P("Pilsen Courtyard 3BR/2BA 1700 S Racine Ave Chicago IL 60608\n$2,000/mo").get("title", "").startswith("Pilsen Courtyard")


def test_fallback_title_from_beds_and_city():
    assert parsers.fallback_title({"beds": 1, "city": "Linden"}) == "1 bed in Linden"
    assert parsers.fallback_title({"beds": 2.0, "city": "Urbana"}) == "2 bed in Urbana"
    assert parsers.fallback_title({"beds": 0, "city": "Urbana"}) == "Studio in Urbana"
    assert parsers.fallback_title({"beds": 3}) == "3 bed place"
    assert parsers.fallback_title({"city": "Linden"}) == "Rental in Linden"
    assert parsers.fallback_title({}) == ""


CRAIGSLIST = ("Craigslist - 2br - $1,200 (Linden)\nRent $1,200 per month, water billed quarterly ~$150, tenant pays all utilities. "
              "Lease start 12/15. No dogs. One cat ok, $200 deposit. Street parking. Call/text Dave at 614-555-0100...")


def test_craigslist_paste_with_no_title_line_reads_city_and_saves(store):
    r = P(CRAIGSLIST)
    assert (r.get("beds"), r.get("city")) == (2, "Linden")
    assert parsers.fallback_title(r) == "2 bed in Linden"
    c = local_client(store)
    c.post("/search", data={"name": "R", "mode": "rent"}, follow_redirects=False)
    resp = c.post("/add/save", data={"listing_text": CRAIGSLIST, "title": "", "address": "", "url": "", "beds": "2", "city": "Linden"}, follow_redirects=False)
    assert resp.status_code in (302, 303), resp.text[:300]
    assert [p["title"] for p in store.list_places()] == ["2 bed in Linden"]


@pytest.mark.parametrize("text, expect", [
    ("Marketplace - 1br - $950 (Hilliard)\nNice place, text me", "1 bed in Hilliard"),
    ("craigslist: studio - $800 (Clintonville)\nCall 614-555-0100 anytime", "Studio in Clintonville"),
])
def test_other_paste_without_a_title_gets_beds_and_city(store, text, expect):
    c = local_client(store)
    c.post("/search", data={"name": "R", "mode": "rent"}, follow_redirects=False)
    page = c.post("/add/parse", data={"text": text, "url": ""})
    assert page.status_code == 200
    assert f'value="{expect}"' in page.text


# ----------------------------------------------------------------------------- 2. 1x1 and 2x2
@pytest.mark.parametrize("text, beds, baths", [
    ("LUXE 1x1 | $1,585/mo | The Hub-style living", 1, 1),
    ("2x2 apartment near campus, $1,900", 2, 2),
    ("Spacious 3X2 house, $2,100/mo", 3, 2),
    ("Brand new 1 x 1 apartment $900", 1, 1),
    ("2x1.5 townhome $1,700", 2, 1.5),
])
def test_beds_by_baths(text, beds, baths):
    r = P(text)
    assert (r.get("beds"), r.get("baths")) == (beds, baths)


@pytest.mark.parametrize("text", ["Closet is 3x3 ft", "Walk-in 10x12 room, rent $900", "2x4 lumber in the garage", "Pay 2x rent as deposit"])
def test_x_that_is_not_beds_and_baths(text):
    r = P(text)
    assert r.get("beds") is None and r.get("baths") is None


# ----------------------------------------------------------------------------- 3. city from the title line
@pytest.mark.parametrize("text, city", [
    ("FOR RENT - 2207 Philo Rd, Urbana - 1BR - $1,475 a month\nWasher/dryer in unit.", "Urbana"),
    ("2207 Philo Rd, Urbana | 1BR | $1,475/mo\nNo pets.", "Urbana"),
    ("For rent: 55 Green St, Champaign - 2 bed 1 bath $1,300\nAvailable now", "Champaign"),
])
def test_city_after_street_without_a_state(text, city):
    r = P(text)
    assert r.get("city") == city
    assert r.get("state") is None


def test_city_after_street_takes_the_state_when_the_listing_gives_it():
    r = P("FOR RENT - 2207 Philo Rd, Urbana - 1BR - $1,475\nNear campus in Urbana, IL.")
    assert (r.get("city"), r.get("state")) == ("Urbana", "IL")


def test_city_after_street_is_not_a_feature_word():
    r = P("123 Main St, Available now - 1BR $900")
    assert r.get("city") is None
    r = P("123 Main St, Washer dryer included - 1BR $900")
    assert r.get("city") is None


def test_city_with_state_and_zip_is_still_read():
    r = P("500 Main St, Austin TX 78701\n2 bed $2,000")
    assert (r.get("address"), r.get("city"), r.get("state"), r.get("zip")) == ("500 Main St", "Austin", "TX", "78701")


# ----------------------------------------------------------------------------- 4. lease dates
@pytest.mark.parametrize("text", [
    "FB Marketplace: 2 bed house for rent - $1,450\nLease begins 12/1 ends 11/30/2027. Text only please.",
    "2 bed house $1,450. Lease begins 12/1, ends 11/30/2027.",
    "2 bed house $1,450. Lease starts 12/1 and ends 11/30/2027.",
])
def test_lease_begins_and_ends_without_a_start_year(text):
    r = P(text)
    assert (r.get("lease_start"), r.get("lease_end"), r.get("lease_months")) == ("2026-12-01", "2027-11-30", 12)


def test_lease_begins_and_ends_with_both_years():
    r = P("Lease starts 12/1/2026 and ends 11/30/2027")
    assert (r.get("lease_start"), r.get("lease_end"), r.get("lease_months")) == ("2026-12-01", "2027-11-30", 12)


def test_lease_start_without_a_year_and_odd_end_is_not_guessed():
    r = P("Lease begins 12/1 ends 12/15/2027")
    assert r.get("lease_start") is None and r.get("lease_months") is None


@pytest.mark.parametrize("text, start", [
    ("Cottage $2,150. Lease 6 or 12 months, starts the first of April 2027. Near school.", "2027-04-01"),
    ("Cottage $2,150. Lease starts the 1st of April 2027, 12 months.", "2027-04-01"),
    ("Cottage $2,150. 12 month lease starting the fifteenth of March, 2027", "2027-03-15"),
    ("Cottage $2,150. 12 month lease starting the first of April", None),
    ("Cottage $2,150. 12 month lease starting the 15th of March 2027", "2027-03-15"),
])
def test_lease_starts_the_first_of_a_month(text, start):
    assert P(text).get("lease_start") == start


def test_ash_grove_keeps_two_lengths_unknown_but_reads_the_start():
    r = P("Ash Grove cottage, 3 bed 1.5 bath, $2,150 per month. Lease 6 or 12 months, starts the first of April 2027.")
    assert (r.get("lease_start"), r.get("lease_months")) == ("2027-04-01", None)
    assert any("more than one lease length (6 or 12 months)" in n for n in notes(r))


@pytest.mark.parametrize("text, other", [
    ("1 bed $1,500. 11-month lease available, also 12-month.", "an 11"),
    ("1 bed $1,500. We offer a 12-month lease, also 9-month leases possible.", "a 9"),
    ("1 bed $1,500. 9-month lease, also 12-month lease available.", "a 9"),
    ("1 bed $1,500. 11 month lease available, plus 12 month.", "an 11"),
])
def test_two_lengths_with_also_keeps_twelve_and_names_the_other(text, other):
    r = P(text)
    assert r.get("lease_months") == 12
    assert f"The listing also offers {other} month lease. The 12 month lease is what is saved. Ask which one you would get." in notes(r)


def test_two_lengths_with_also_neither_a_year_stays_unknown():
    r = P("1 bed $1,500. 10 month lease available, also 11 month.")
    assert r.get("lease_months") is None
    assert any("10 or 11 months" in n for n in notes(r))


def test_plain_single_lengths_unchanged():
    assert P("1 bed $1,500. 11-month lease.").get("lease_months") == 11
    assert P("1 bed $1,500. 12 month lease.").get("lease_months") == 12


# ----------------------------------------------------------------------------- 5. notes noise
def test_note_that_repeats_a_quoted_line_is_dropped():
    r = P("Grove 1BR $1,540. Pet limit 25 lbs, can be waived. Pet deposit $400 ($150 non-refundable).")
    got = notes(r)
    assert "Pet limit 25 lbs, can be waived." not in got
    assert any('"Pet limit 25 lbs, can be waived"' in n for n in got)


def test_poplar_bend_pet_line_is_not_quoted_twice():
    r = P("Poplar Bend Home - Rent: $2,260. 3 bed 2 bath. Pets: 2 dogs maximum, combined weight 100 lbs. $500 pet deposit total.")
    got = notes(r)
    assert "Pets: 2 dogs maximum, combined weight 100 lbs." not in got
    assert sum("Pets: 2 dogs maximum, combined weight 100 lbs" in n for n in got) == 1


@pytest.mark.parametrize("line, field", [
    ("Dogs ok (2 max, no aggressive breeds), dog weight cap 80 lbs, $500 pet deposit, $40 monthly pet rent per dog.", "pet_breed_note"),
    ("Dogs allowed: breed restrictions apply, up to 70 lbs, limit 2. Pet deposit $300, pet rent $35/mo.", "pet_breed_note"),
])
def test_pet_line_held_by_the_breed_note_is_not_a_note(line, field):
    r = P("Larch Way - 3BR/2BA house, $2,350/mo. " + line)
    if r.get(field):
        assert not any(n.startswith(("Dogs ok (2 max", "Dogs allowed: breed")) for n in notes(r))


def test_approval_pet_line_with_placed_numbers_is_not_repeated():
    r = P("Fir Terrace $2,395 3 bed 2.5 bath. Pets by approval only, case-by-case, no dogs over 50 lbs unless approved by management. Pet fee $250, pet rent $35.")
    got = notes(r)
    assert r.get("pet_weight_limit") == 50
    assert not any(n.startswith("Pets by approval only, case-by-case") for n in got)
    assert any('"Pets by approval only"' in n for n in got)


def test_pet_line_with_an_amount_nothing_holds_stays():
    r = P("Fir Terrace $2,395 3 bed. Pets by approval only, case-by-case, no dogs over 50 lbs, $75 monthly fee, unless approved by management. Pet fee $250.")
    assert any("$75 monthly fee" in n for n in notes(r))


WRIGHT = "Charming 1BR. 1 bed, 1 bath. $1,290/mo. Address: 701 S Wright St, Champaign IL 61820. Heat and water included, tenant pays electric. Pets considered with $250 deposit."


@pytest.mark.parametrize("text", [
    WRIGHT,
    "1 bed apt at 701 S Wright St, Champaign IL. $1,290/mo. Pets negotiable, $250 pet deposit.",
    "1BR $1,290/mo 701 S Wright St, Champaign IL 61820. Pets considered, $250 deposit.",
])
def test_pets_negotiable_with_a_saved_deposit_is_not_an_uncounted_amount(text):
    r = P(text)
    assert r.get("pet_deposit") == 250
    place = {k: v for k, v in r.items() if k != "found_in_listing"}
    place["reader_notes"] = r.get("found_in_listing") or ""
    place["listing_text"] = text
    assert money.open_listing_notes(place["reader_notes"], place) == []
    assert "listing notes" not in money.true_monthly_cost(place)["headline"]


def test_legacy_paragraph_with_left_empty_sentence_is_one_note():
    para = 'The listing says pets are negotiable ("Pets considered with $250 deposit"). Pets is left empty, so ask the landlord which pets are allowed and what they cost.'
    assert len(money.note_units(para)) == 1
    place = {"pet_deposit": 250, "price": 1290}
    assert money.open_listing_notes(para, place) == []


def test_note_without_an_amount_asking_what_it_costs_is_not_a_money_gap():
    assert money.open_listing_notes("Pets is left empty, so ask the landlord which pets are allowed and what they cost.") == []


@pytest.mark.parametrize("note_amounts, expect", [
    (['The listing also says "Water billed quarterly, about $96 per quarter". It is not counted anywhere. Check what it is for.'], "the $96 amount in the listing notes"),
    (['The listing also says "Flat $75/mo fee". It is not counted anywhere. Check what it is for.',
      'The listing also says "Locker $20/mo". It is not counted anywhere. Check what it is for.'], "the $75 and $20 amounts in the listing notes"),
    (['The listing also says "Fee $75/mo". It is not counted anywhere. Check what it is for.',
      'The listing also says "Fee $20/mo". It is not counted anywhere. Check what it is for.',
      'The listing also says "Fee $35/mo". It is not counted anywhere. Check what it is for.'], "the $75, $20 and $35 amounts in the listing notes"),
])
def test_missing_label_names_the_amounts(note_amounts, expect):
    text = "\n".join(note_amounts)
    assert money.open_notes_label(text, {"price": 1000}) == expect
    cost = money.true_monthly_cost({"price": 1000, "reader_notes": text})
    assert expect in cost["headline"]


def test_amount_label_leaves_out_a_placed_amount():
    text = ('The listing also says "Fee $75/mo". It is not counted anywhere. Check what it is for.\n'
            'The listing also says "Locker $20/mo". It is not counted anywhere. Check what it is for.')
    assert money.open_notes_label(text, {"price": 1000, "other_monthly_fees": 20}) == "the $75 fee in the listing notes" or \
        money.open_notes_label(text, {"price": 1000, "other_monthly_fees": 20}) == "the $75 amount in the listing notes"


def test_bullet_quote_stops_at_the_bullet():
    r = P("LUXE 1x1 | $1,585/mo | The Hub-style living\nUnit 410, 33 N Neil St, Champaign. W/D in unit * DW * heated garage $120/mo (required for all residents) * Water, sewer, trash all included * Electric not included, budget about $75 * pets welcome (dogs 40 lb max, 2 pets max) * built 2024 * 11-month lease available, also 12-month * Amenity package $35/month (pool, gym) *")
    assert any('"Electric not included, budget about $75"' in n for n in notes(r))
    assert not any("pets welcome (dogs 40 lb max" in n and "budget" in n for n in notes(r))


# ----------------------------------------------------------------------------- 6. one note per line
def test_notes_are_one_per_line():
    r = P("Beech Court $2,290 3 bd / 2 ba. Water billed quarterly about $90. Application fee $40 per adult. Cleaning fee at move-in $125. 12 min bike to Beech Elementary.")
    lines = (r.get("found_in_listing") or "").split("\n")
    assert len(lines) >= 3
    assert all(l.strip() and "\n" not in l for l in lines)
    assert money.note_units(r["found_in_listing"]) == lines


def test_note_units_keep_each_line_whole_even_if_it_starts_like_a_continuation():
    text = "The listing offers a discount (\"one month free\"). It is a one-time deal.\nIt is odd to start a note like this."
    assert money.note_units(text) == ["The listing offers a discount (\"one month free\"). It is a one-time deal.", "It is odd to start a note like this."]


def test_note_units_single_paragraph_still_groups_continuations():
    text = 'The listing also says "Locker $20". It is not counted anywhere. Check what it is for.'
    assert money.note_units(text) == [text]


def test_join_helper_is_one_per_line():
    assert money.join_notes(["a  b", "", "c"]) == "a b\nc"
