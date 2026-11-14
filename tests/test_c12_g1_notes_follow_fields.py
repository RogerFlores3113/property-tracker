"""C12 G1: every "Also in the listing" note follows the saved fields, one-time items stay out of the monthly tag, quotes end on a
whole word, and read lines are not quoted again."""
import pytest

from conftest import local_client
from mcp_util import call, server, text
from prophelper import compare, money, parsers


def found(t, **kw):
    return parsers.parse_listing(t, **kw)


def notes(t, **kw):
    return found(t, **kw).get("found_in_listing", "")


def save(store, t, mode="rent"):
    store.add_search("S", mode)
    r = found(t, buying=(mode == "buy"))
    fields = {k: v for k, v in r.items() if k not in ("found_in_listing", "title", "source")}
    p, _ = store.add_place(title="Oak", address="1 Oak St", listing_text=t, reader_notes=r.get("found_in_listing", ""), **fields)
    return p


# ---- 1. a note about a field goes once the field is filled
RANGE = "Zephyr Commons 2 bed. Rent from $1,299 - $1,650 / mo. Utilities billed-back average $120 a month."


def test_rent_left_empty_note_goes_when_price_is_set(store):
    t = "Zephyr Commons 2 bed. Rent from $1,299 - $1,650 / mo."
    r = found(t)
    assert "price" not in r and "the rent is left empty" in r["found_in_listing"]
    p = save(store, t)
    assert "the rent is left empty" in p["reader_notes"]
    p = store.update_place(p["id"], price=1395)
    assert p["price"] == 1395 and "the rent is left empty" not in p["reader_notes"]


def test_billed_back_average_note_goes_when_estimate_is_set(store):
    t = "Zephyr 2 bed $1,395/mo. Utilities billed-back average $120 a month."
    r = found(t)
    assert "billed-back average of $120" in r["found_in_listing"]  # a fresh read keeps what the reader said
    p = store.update_place(save(store, t)["id"], utilities_estimate=65)
    assert p["utilities_estimate"] == 65 and "billed-back average" not in p["reader_notes"]


BUY = "Condo $318,000. 2 bed 1 bath. Special assessment mentioned."
BUY_AMT = "Condo $318,000. 2 bed 1 bath. Special assessment $2,000."


def test_assessment_no_amount_note_goes_after_amount_and_payer(store):
    p = save(store, BUY, "buy")
    assert "no amount is given, and the listing doesn't say who pays it" in p["reader_notes"]
    p = store.update_place(p["id"], special_assessment=4000, special_assessment_payer="seller")
    assert p["special_assessment"] == 4000 and p["special_assessment_payer"] == "seller"
    assert "special assessment" not in p["reader_notes"].lower()


def test_assessment_note_is_reworded_when_only_the_amount_is_filled(store):
    p = save(store, BUY, "buy")
    p = store.update_place(p["id"], special_assessment=4000)
    assert p["reader_notes"] == "Special assessment $4,000: the listing doesn't say who pays it, so ask."


def test_assessment_who_pays_note_goes_after_payer(store):
    p = save(store, BUY_AMT, "buy")
    assert p["reader_notes"] == "Special assessment $2,000: the listing doesn't say who pays it, so ask."
    p = store.update_place(p["id"], special_assessment_payer="buyer")
    assert "who pays" not in p["reader_notes"]


def test_assessment_note_goes_through_mcp_update_place(store):
    srv = server(store)
    call(srv, "create_search", name="B", mode="buy", target_close="2027-09-01")
    call(srv, "add_place", listing_text="Maple Court\n9 Maple St, Columbus, OH 43215\n" + BUY)
    pid = store.list_places()[0]["id"] if hasattr(store, "list_places") else 1
    call(srv, "update_place", place_id=pid, special_assessment=4000, special_assessment_payer="seller")
    assert "special assessment" not in store.get_place(pid)["reader_notes"].lower()


def test_assessment_note_goes_through_the_web_form(store):
    p = save(store, BUY, "buy")
    c = local_client(store)
    r = c.post(f"/places/{p['id']}", data={"title": "Oak", "special_assessment": "4000", "special_assessment_payer": "seller"}, follow_redirects=False)
    assert r.status_code in (200, 303)
    assert "special assessment" not in store.get_place(p["id"])["reader_notes"].lower()


def test_saved_notes_with_no_listing_text_lose_filled_notes(store):
    store.add_search("S")
    p, _ = store.add_place(title="Oak", address="1 Oak St", reader_notes="The listing gives a rent range of $1,299 to $1,650 a month, so the rent is left empty. "
                           "Ask which rent applies to the unit you want, then fill it in. Pets are fine.")
    p = store.update_place(p["id"], price=1400)
    assert p["reader_notes"] == "Pets are fine."


# ---- 2. an unchanged value still remakes the notes
def test_update_with_same_value_remakes_notes(store):
    t = "Zephyr Commons 2 bed. Rent from $1,299 - $1,650 / mo."
    p = save(store, t)
    store.update_place(p["id"], price=1395)
    store._exec("UPDATE places SET reader_notes = ? WHERE id = ?", ("The listing gives a rent range of $1,299 to $1,650 a month, so the rent is left empty. Ask which rent applies to the unit you want, then fill it in.", p["id"]))
    p = store.update_place(p["id"], price=1395)  # the same value sent again
    assert "the rent is left empty" not in p["reader_notes"]


# ---- 3. counted and included amounts
def test_pipe_move_in_fees_are_counted_and_not_noted():
    r = found("Logan Square 2bd. $2,100/mo. Move-in fee $400 | Admin fee $200.")
    assert r["move_in_fees"] == 600 and r["price"] == 2100
    assert "found_in_listing" not in r


def test_hoa_included_in_rent_is_not_a_cost_to_add():
    r = found("Brookside 2bd $1,800/mo. HOA dues of $120 per quarter included in your rent.")
    n = r["found_in_listing"]
    assert n == 'The listing says "HOA dues of $120 per quarter included in your rent". It is included in the rent, so it is not added on top.'
    assert not money.listing_notes_uncounted(n)
    cost = money.true_monthly_cost({"price": 1800, "reader_notes": n}, "rent")
    assert money.LISTING_NOTES_UNCOUNTED not in cost["uncounted"]


# ---- 4. one-time items
def test_move_in_total_and_holding_fee_are_one_time_and_do_not_fire_the_monthly_tag():
    n = notes("Move-in total $3,000. Holding fee $200 to reserve. Rent $1,500.")
    assert ("so it is not in the monthly cost, and the cash due at move-in may be more than shown. Ask what it includes.") in n
    assert 'The listing says "Holding fee $200 to reserve". It is a one-time amount, so it is not in the monthly cost.' in n
    assert "not counted" not in n
    assert not money.listing_notes_uncounted(n)
    assert money.LISTING_NOTES_UNCOUNTED not in money.true_monthly_cost({"price": 1500, "reader_notes": n}, "rent")["uncounted"]


def test_holding_fee_with_no_amount_is_one_time():
    n = notes("Rent $1,500/mo. Holding fee equal to one week's rent.")
    assert "It is not in the monthly cost, because no dollar amount is given." in n
    assert not money.listing_notes_uncounted(n)


def test_old_saved_one_time_notes_do_not_fire_the_tag():
    assert not money.listing_notes_uncounted("The listing says it costs $3,000 in total to move in. That is not the monthly rent, so it is not counted. Ask what it includes.")


def test_open_monthly_money_still_fires_the_tag():
    assert money.listing_notes_uncounted('The listing also says "Parking $75". It is not counted anywhere. Check what it is for.')


def test_stale_tag_clears_when_open_money_is_filled(store):
    p = save(store, "1 bed $1,500/mo. $75/mo utility package.")
    assert money.listing_notes_uncounted(p["reader_notes"])
    p = store.update_place(p["id"], utilities_estimate=75)
    assert not money.listing_notes_uncounted(p["reader_notes"])


# ---- 5. quotes
def test_quote_is_cut_at_a_word_edge():
    n = notes("West Loop 3br 2ba - $2,350\n50% off first month for move-ins by December 1st if you sign. Lease 12 months")
    assert '("50% off first month for move-ins by...")' in n and "by De" not in n


def test_title_is_not_quoted_as_a_note():
    assert parsers._quotes_title("Spacious 3br 2ba ... (REDUCED", "Spacious 3br 2ba ... (REDUCED")
    assert parsers._quotes_title("(REDUCED $2,000", "Spacious 3br 2ba ... (REDUCED")
    assert not parsers._quotes_title("Admin fee $200", "Spacious 3br 2ba ... (REDUCED")


def test_per_adult_sum_fragment_is_dropped():
    n = notes("Brookside 2bd $1,800/mo. Application fee $55 per adult. For 2 adults that is $110 together.")
    assert "$110" not in n and "together" not in n
    assert found("Brookside 2bd $1,800/mo. Application fee $55 per adult.")["application_fee"] == 55


def test_seen_but_not_counted_line_is_not_a_repeat(store):
    srv = server(store)
    call(srv, "create_search", name="S", mode="rent", move_in="2027-08-15", budget_max=2500)
    out = text(call(srv, "add_place", listing_text="Logan Sq\n12 Elm St, Chicago, IL 60647\n2 bed $2,100/mo. Locker $30 per month."))
    assert "Locker is $30/month" in out and "Seen but not counted" not in out


# ---- 6. lines already read are not quoted
PET_PLACE = {"pets": "cats", "pet_fee": 350, "pet_rent": 30, "pet_weight_limit": 55, "pet_count_limit": 1}


@pytest.mark.parametrize("line,place", [
    ("Pets allowed, 2 pet max, $350 non-refundable pet fee, $30/mo pet rent.", {"pets": "both", "pet_fee": 350, "pet_rent": 30, "pet_count_limit": 2}),
    ("Cats only, 1 pet, maximum 55 lbs", PET_PLACE),
    ("Dog weight limit 60 lbs", {"pets": "dogs", "pet_weight_limit": 60}),
    ("Dogs ok no weight limit", {"pets": "dogs"}),
])
def test_pet_lines_already_in_fields_are_dropped(line, place):
    assert parsers._drop_placed_facts([line + "."], place) == []


@pytest.mark.parametrize("line,place", [
    ("Pets allowed, 2 pet max, $350 non-refundable pet fee, $30/mo pet rent.", {"pets": "both", "pet_fee": 350, "pet_count_limit": 2}),
    ("Dogs ok no weight limit", {"pets": "dogs", "pet_weight_limit": 40}),
    ("Cats only, 1 pet, maximum 55 lbs", {"pets": "dogs", "pet_weight_limit": 55, "pet_count_limit": 1}),
    ("Pets negotiable, 1 dog max 65 lbs", {"pets": "dogs", "pet_weight_limit": 65, "pet_count_limit": 1}),
    ("Dogs ok, no breed restrictions", {"pets": "dogs"}),
])
def test_pet_lines_not_fully_in_fields_are_kept(line, place):
    assert parsers._drop_placed_facts([line + "."], place) == [line + "."]


def test_refresh_drops_read_pet_line_on_a_saved_place():
    place = {"listing_text": "Rent $1,500/mo.\nDog weight limit 60 lbs.", "pets": "dogs", "pet_weight_limit": 60, "price": 1500}
    assert parsers.reader_notes_for(place) == ""


# ---- 7. Compare row order
def test_compare_notes_put_per_adult_fees_and_open_money_before_one_time_deals():
    deal = 'The listing offers a discount ("50% off first month"). It is a one-time deal, so it is not taken off the monthly rent. Ask what you have to do to get it.'
    cut = "Price reduced $200."
    money_note = 'The listing also says "Locker $30 per month". It is not counted anywhere. Check what it is for.'
    adult = "The application fee $55 is charged per adult, so each adult who applies pays it."
    t = compare.listing_notes_text({"reader_notes": " ".join([deal, cut, money_note, adult])}, 500)
    assert t.index(adult) < t.index(money_note) < t.index(deal) < t.index(cut) or t.index(adult) < t.index(money_note) < t.index(cut) < t.index(deal)
