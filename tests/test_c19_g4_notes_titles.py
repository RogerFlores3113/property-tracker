"""Cycle 19 G4: the "not counted" notes, the headline, the missing list and Compare agree with the final saved fields; titles never come
from a fee, money or policy line. Each reviewer phrasing plus other layouts (commas, parentheses, dashes, bullets, separate lines)."""
from __future__ import annotations

import pytest

from prophelper import compare, money
from prophelper.parsers import parse_listing, placed_amounts


def read(text: str, buying: bool = False):
    r = parse_listing(text, "", buying=buying)
    place = {k: v for k, v in r.items() if k != "found_in_listing"}
    place["reader_notes"] = r.get("found_in_listing", "")
    place["listing_text"] = text
    cost = money.true_monthly_cost(place, "buy" if buying else "rent")
    return place, cost, compare._missing_names({**place, "cost": cost})


def no_open_amounts(cost, missing):
    assert "listing notes" not in (cost.get("headline") or "")
    assert not [m for m in missing if "listing notes" in m], missing


# ---- item 1: amounts that a field counts are never "not counted"
@pytest.mark.parametrize("text", [
    "Italian Village Townhome Condo | $289,000\n77 E 1st Ave Columbus OH\nHOA $210/month plus $600 annual master dues. 3 bed 2 bath.",
    "Italian Village Townhome Condo | $289,000\n77 E 1st Ave Columbus OH\nHOA fee $210 a month and a $600 yearly master association dues. 3 bed 2 bath.",
    "Italian Village Townhome Condo | $289,000\n77 E 1st Ave Columbus OH\n* HOA: $210/mo\n* Master association dues: $600 per year\n3 bed 2 bath.",
])
def test_hoa_with_annual_dues_is_saved_and_not_called_uncounted(text):
    place, cost, missing = read(text, buying=True)
    assert place["hoa"] == 260
    no_open_amounts(cost, missing)
    for n in place["reader_notes"].split("\n"):
        assert not ("$600" in n and "not counted" in n)
    assert "$210" not in cost["headline"] and "$600" not in cost["headline"]


@pytest.mark.parametrize("text", [
    "Quarry Heights, 1 Bed 1 Bath, $1,450 per month\n410 N Mattis Ave, Champaign IL 61820\n- Assigned covered space $60/month\n- Utilities: electric $60, gas $35 (resident pays)\n- Water/sewer/trash flat $30/mo RUBS\n",
    "Quarry Heights, 1 Bed 1 Bath, $1,450 per month. 410 N Mattis Ave, Champaign IL. Utilities (electric $60, gas $35, resident pays). Water/sewer/trash flat $30/mo.",
    "Quarry Heights 1 bed $1,450\n410 N Mattis Ave Champaign IL\nUtilities - electric $60 - gas $35 - tenant pays\nWater, sewer and trash: $30 a month",
])
def test_utilities_line_counted_in_estimate_is_not_called_uncounted(text):
    place, cost, missing = read(text)
    assert place["utilities_estimate"] == 125
    assert "$35" not in " ".join(missing) and "$35" not in cost["headline"]
    assert not any("$35" in n and "not counted" in n for n in place["reader_notes"].split("\n"))


@pytest.mark.parametrize("text", [
    "BRONZEVILLE!!! 3 BD / 2 BA ::: $2,450 ::: 4400 S Michigan Ave Chicago IL ::: UTILITIES: ELECTRIC $45 | GAS $60 | WATER $35 | TRASH INCL ::: NO PETS ::: LEASE 12 MO",
    "BRONZEVILLE 3 BD / 2 BA | $2,450 | 4400 S Michigan Ave Chicago IL | UTILITIES: ELECTRIC $45, GAS $60, WATER $35, TRASH INCL | NO PETS",
    "Bronzeville 3 bed 2 bath $2,450\n4400 S Michigan Ave Chicago IL\nUTILITIES:\n* ELECTRIC $45\n* GAS $60\n* WATER $35\n* TRASH INCLUDED\nNo pets",
])
def test_all_caps_pipe_utilities_list_has_no_false_not_counted(text):
    place, cost, missing = read(text)
    assert place["utilities_estimate"] == 140
    assert "$45" not in " ".join(missing) and "$45" not in cost["headline"]
    assert not any("$45" in n and "not counted" in n for n in place["reader_notes"].split("\n"))


@pytest.mark.parametrize("text", [
    "Willow Creek Townhome 3BR 2.5BA $2,250. Flat $85/mo fee covers water, sewer, trash and pest control. Tenant pays electric $70 and gas $35. Application fee $50 per person.",
    "Willow Creek Townhome 3BR 2.5BA $2,250. Flat fee: $85/month covers water, sewer, trash and pest control. Tenant pays electric $70 and gas $35. Application fee $50 per person.",
])
def test_flat_fee_that_is_counted_is_not_listed_as_missing(text):
    place, cost, missing = read(text)
    assert place["other_monthly_fees"] == 85
    assert "the flat fee" not in " ".join(missing)
    assert "flat fee in the listing notes" not in cost["headline"]


def test_month_to_month_and_conditional_deposit_are_not_missing_amounts():
    for text in ("Chinatown 3BR 2BA 2800/mo 2900 S Wells St Chicago IL. Landlord pays gas, water, sewer, trash, heat. Tenant electric only about $110. Month to month possible.",
                 "Garfield Park 3-bed 2-bath, $2,650 a month. 300 N Central Park Ave Chicago IL. Security deposit $1,200 if credit is poor. Month to month possible. Gas and electric extra.",
                 "Garfield Park 3-bed 2-bath, $2,650 a month. 300 N Central Park Ave Chicago IL. Deposit $1,200 only if your credit is poor. Month-to-month available."):
        place, cost, missing = read(text)
        assert not [m for m in missing if "listing notes" in m], (text, missing)
        assert "listing notes" not in cost["headline"], text


def test_open_amount_still_named():
    place, cost, missing = read("Oak Row 2 bed $1,500. 12 Oak St Champaign IL. Tenant pays electric about $60. Valet waste $25/month optional?? ask. Parking pass $45/month required.")
    assert place.get("utilities_estimate") == 60


@pytest.mark.parametrize("phrase, want", [
    ("Locker $15, valet trash $25", {25.0}),
])
def test_placed_amounts_does_not_hide_a_left_out_figure(phrase, want):
    out = {"other_monthly_fees": 25}
    got = placed_amounts({15.0, 25.0}, {25.0}, set(), phrase, out)
    assert 15.0 not in got and 25.0 in got


def test_placed_amounts_sums_with_yearly_conversion():
    assert placed_amounts({210.0, 600.0, 50.0}, {260.0}, set(), "$210/month plus $600 annual master dues, $50/month", {"hoa": 260}) == {210.0, 600.0, 50.0}
    assert placed_amounts({210.0, 600.0}, {260.0}, set(), "HOA $210 and $600 per year", {"hoa": 260}) == {210.0, 600.0}
    assert placed_amounts({90.0}, {30.0}, set(), "water every 3 months $90", {}) == {90.0}


def test_only_the_open_amounts_are_named_and_grammar_agrees():
    place, _cost, _missing = read("Pine Row 1 bed $1,400. 5 Pine St Champaign IL. Tenant pays gas $30. Bike storage $4, kayak rack $9, gas $30.")
    notes = place["reader_notes"]
    assert "Only $4 and $9 of that is" not in notes
    if "Only $4 and $9" in notes:
        assert "Only $4 and $9 of that are" in notes


def test_one_open_amount_keeps_singular_grammar():
    place, _c, _m = read("Pine Row 1 bed $1,400. 5 Pine St Champaign IL. Tenant pays gas $30. Electric budget billing $75, gas $30.")
    assert "Only $75 of that is" in place["reader_notes"]


# ---- item 3: titles
@pytest.mark.parametrize("text, want", [
    ("Cozy duplex in Hilltop! 2 bedrooms, 1 bath. 1.5k a month.\n* Gas heat - tenant pays about $40/mo\n* Pest control $8, locker $10, valet trash $15 (monthly)\nSmall pets considered.\n2210 W Broad St.", "Cozy duplex in Hilltop"),
    ("Rent\n$1,325 / month   2 bd | 1 ba | 900 sqft\nCondo fee $240 paid by owner. Tenant pays electric avg $60.\nAvailable 12/15. 77 Indianola Ave, Columbus, OH 43201", "77 Indianola Ave"),
    ("2 Bed / 1 Bath  $1,450 (was $1,550 - price drop!)\nNet effective rent $1,380 with 1 month free on 13 month lease.\n3377 Cleveland Ave Columbus OH", "3377 Cleveland Ave"),
    ("Net effective rent $1,380 with 1 month free. 2 bed 1 bath.\n3377 Cleveland Ave Columbus OH", "3377 Cleveland Ave"),
    ("Pest control $8 a month\nLocker $10\n2 bed 1 bath $1,450\n812 N High St Columbus OH", "812 N High St"),
    ("1.5k a month 1 bed 1 bath near campus, 1202 W Clark St Urbana IL.\nLandlord pays all utilities. Tenant electric only total $80.\nLease begins 8/1/2027. Deposit: one month rent (conditional on credit approval).", "1202 W Clark St"),
    ("Lease begins 8/1/2027\nDeposit: one month rent\n1 bed 1 bath, 55 Elm St Urbana IL", "55 Elm St"),
    ("Condo fee $240 paid by owner\n2 bed 1 bath $1,325\n9 Oak Ave Columbus OH", "9 Oak Ave"),
])
def test_title_never_comes_from_a_fee_or_policy_line(text, want):
    assert parse_listing(text, "").get("title") == want


@pytest.mark.parametrize("text, want", [
    ("NEW PRICE $2,295 (was $2,450)! Gorgeous 3BR/2BA SFH on Oak Knoll Dr, Menlo Park CA. Net effective rent $2,150 with 1 month free.", "3 bed on Oak Knoll Dr"),
    ("Just reduced to $2,100! Lovely 2 bed 1 bath house on Maple Ridge Ln. Fenced yard.", "2 bed on Maple Ridge Ln"),
])
def test_street_name_without_a_number_beats_a_bare_bed_count(text, want):
    assert parse_listing(text, "").get("title") == want


@pytest.mark.parametrize("text", [
    "Duplex for rent - Clintonville\n2 bed $1,200",
    "Franklinton Lofts #5 - $214,900\n12 Rich St",
    "Short North 2BR - $1,495/mo\n812 N High St",
    "Hazel Lane 3bd townhouse in Menlo Park - rent: $2,390",
])
def test_real_headlines_still_win(text):
    title = parse_listing(text, "").get("title")
    assert title and not title.lower().startswith(("rent", "net effective", "pest"))


# ---- item 2: a correction clears the notes it answers
def test_update_place_clears_notes_the_new_estimate_answers(store):
    store.add_search("T")
    text = ("Lantern 1 bed $1,300\n608 S Goodwin Ave Urbana IL\n* Gas heat - tenant pays about $40/mo\n* Trash & sewer: $65 monthly\n* Internet $50\n"
            "Electric - tenant (about $45)")
    r = parse_listing(text, "")
    vals = {k: v for k, v in r.items() if k != "found_in_listing"}
    vals.update(reader_notes=r.get("found_in_listing", ""), listing_text=text)
    pl, _ = store.add_place(**vals)
    pl = store.update_place(pl["id"], utilities_estimate=200, tenant_pays="electric, gas, sewer, trash, internet")
    cost = money.true_monthly_cost(pl, "rent")
    missing = compare._missing_names({**pl, "cost": cost})
    assert not [m for m in missing if "listing notes" in m or "electric" in m.lower()], missing
    assert "not counted" not in (cost["headline"] or "")
    for n in (pl["reader_notes"] or "").split("\n"):
        if "utilities estimate" in n and "$" in n:
            assert "$200" in n or "counted as your utilities estimate" not in n


# ---- item 4: grammar in the headline
def test_looks_cheaper_sentence_has_no_its_the():
    from prophelper.compare import _aren_t, _its
    for label in ("the $210 and $75 amounts in the listing notes", "the $75 flat fee in the listing notes", "some amounts in the listing notes"):
        assert _its(label) == ""
    assert _its("utilities") == "its "
    assert _aren_t("the $75 flat fee in the listing notes") == "is"
    assert _aren_t("the $210 and $75 amounts in the listing notes") == "are"


def test_a_still_open_amount_is_still_named_after_the_final_pass():
    place, cost, missing = read("Oak Row 1 bed $1,400. 5 Oak St Champaign IL. Tenant pays electric about $60. Locker $15, valet trash $25 monthly, pest control $8.")
    assert any("$15" in m for m in missing) or "$15" in place["reader_notes"]
