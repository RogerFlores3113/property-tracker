"""C13 G4: notes are made again on every field change, notes never restate a counted value, insurance counts in a rent
search, Compare never says "Nothing unknown" over an open cost, fit lines add up, MCP addresses are not doubled."""
import pytest

from conftest import local_client
from mcp_util import call, server, text
from prophelper import compare, enrich, money, parsers

RENT_TEXT = "Foundry Flats 1 bed 1 bath. Renter's insurance required.\nReduced price $1,575\nCredit check $25\n"


def save(store, listing, mode="rent", keep_text=True, **extra):
    store.add_search("S", mode)
    r = parsers.parse_listing(listing, buying=(mode == "buy"))
    fields = {k: v for k, v in r.items() if k not in ("found_in_listing", "title", "source")}
    fields.update(extra)
    p, _ = store.add_place(title="Foundry", address="1 Oak St", listing_text=listing if keep_text else "",
                           reader_notes=r.get("found_in_listing", ""), **fields)
    return p


# ---- 1. notes are made again on every field change
@pytest.mark.parametrize("keep_text", [True, False])
@pytest.mark.parametrize("field,value", [("other_monthly_fees", 14), ("insurance", 120)])
def test_renters_insurance_note_goes_when_a_cost_field_is_filled(store, keep_text, field, value):
    p = save(store, RENT_TEXT, keep_text=keep_text)
    assert "renter's insurance is required" in p["reader_notes"] or "No cost is counted for it" in p["reader_notes"]
    p = store.update_place(p["id"], **{field: value})
    assert "insurance" not in p["reader_notes"].lower() and "No cost is counted" not in p["reader_notes"]
    assert "credit check" in p["reader_notes"].lower()  # an unrelated open note stays (cycle 13 G3 reads it as the application fee)


def test_listing_notes_tag_goes_with_its_last_open_note(store):
    p = save(store, "Foundry Flats 1 bed 1 bath. Renter's insurance required.\n")
    assert money.listing_notes_uncounted(p["reader_notes"])
    p = store.update_place(p["id"], other_monthly_fees=14)
    assert p["reader_notes"] == "" and not money.listing_notes_uncounted(p["reader_notes"])
    assert money.LISTING_NOTES_UNCOUNTED not in money.true_monthly_cost(p)["uncounted"]


@pytest.mark.parametrize("keep_text", [True, False])
def test_reduced_price_note_goes_when_price_is_set(store, keep_text):
    p = save(store, RENT_TEXT, keep_text=keep_text)
    assert p["price"] is None and 'Reduced price $1,575' in p["reader_notes"]
    p = store.update_place(p["id"], price=1575)
    assert "Reduced price" not in p["reader_notes"]


BUY_SA = "Condo $318,000. 2 bed 1 bath. Special assessment $2,000."


@pytest.mark.parametrize("keep_text", [True, False])
def test_payer_note_follows_a_payer_change(store, keep_text):
    p = save(store, BUY_SA, "buy", keep_text=keep_text)
    assert "doesn't say who pays it" in p["reader_notes"]
    p = store.update_place(p["id"], special_assessment_payer="buyer")
    assert p["reader_notes"] == ""
    p = store.update_place(p["id"], special_assessment_payer="seller")
    assert "the buyer pays it" not in p["reader_notes"]


def test_a_saved_buyer_pays_note_is_dropped_when_the_payer_becomes_seller(store):
    store.add_search("S", "buy")
    p, _ = store.add_place(title="Old", address="2 Oak St", price=300000, special_assessment=2000, special_assessment_payer="buyer",
                           reader_notes="Special assessment $2,000: the buyer pays it. The listing also says \"Gym fee $40\". It is not counted anywhere. Check what it is for.")
    p = store.update_place(p["id"], special_assessment_payer="seller")
    assert p["reader_notes"] == 'The listing also says "Gym fee $40". It is not counted anywhere. Check what it is for.'
    page = local_client(store).get(f"/places/{p['id']}").text
    assert "the buyer pays it" not in page
    assert "the buyer pays it" not in text(call(server(store), "get_place", place_id=p["id"]))


def test_renters_insurance_sentence_is_said_once():
    notes = parsers.parse_listing("Rogers Park 1 bed $1,900/mo. Renter's insurance required $15/mo.\n")["found_in_listing"]
    assert notes == ("The listing says renter's insurance is required ($15/month). No cost is counted for it. "
                     "Ask what coverage you need and what it costs.")


# ---- 3. a value that was read and counted is not said again
def test_read_assessment_and_tax_are_not_repeated_in_notes():
    got = parsers.parse_listing("Clintonville Brick 2BR $299,900\nProperty taxes $3,100 per year ($258/mo)\n"
                                "Special assessment $2,000 buyer responsibility\n", buying=True)
    assert got["property_tax"] == 3100 and got["special_assessment"] == 2000 and got["special_assessment_payer"] == "buyer"
    assert got.get("found_in_listing", "") == ""


def test_add_parse_preview_has_one_also_in_the_listing_heading(store):
    store.add_search("B", "buy")
    t = "Clintonville Brick 2BR $299,900\nSpecial assessment $2,000 buyer responsibility\nGym fee $40\nTransfer fee $450\n"
    html = local_client(store).post("/add/parse", data={"text": t, "url": "", "search_id": str(store.current_search()["id"])}).text
    assert html.count("<h3>Also in the listing</h3>") == 1
    assert "the buyer pays it" not in html


# ---- 2. insurance counts in a rent search
def test_insurance_counts_in_a_rent_search_monthly_cost(store):
    s = store.add_search("R", "rent")
    p, _ = store.add_place(title="A", address="1 A St", price=1500, utilities_included="all", insurance=120)
    cost = money.true_monthly_cost(p)
    line = next(l for l in cost["lines"] if l["key"] == "insurance")
    assert line["amount"] == 10 and line["note"] == "$120 a year, counted as a twelfth each month"
    assert cost["total"] == 1510
    assert money.true_monthly_cost({**p, "insurance": None})["total"] == 1500


# ---- 4. Compare
def _en(store, s, *places):
    return enrich.enrich_places(store, s, list(places))


def test_compare_never_says_nothing_unknown_for_tenant_paid_utilities_or_the_notes_tag(store):
    s = store.add_search("C", "rent")
    a, _ = store.add_place(title="Oak", address="3 B St", price=1600, tenant_pays="gas, electric", utilities_included="all", pet_fee=0, deposit=500)
    b, _ = store.add_place(title="Brook", address="2 B St", price=1500, utilities_included="all", pet_fee=0, deposit=500,
                           reader_notes='The listing also says "Gym fee $40". It is not counted anywhere. Check what it is for.')
    es = _en(store, s, a, b)
    row = {r["key"]: r for sec in compare.build_rows(es) for r in sec["rows"]}
    assert [c["text"] for c in row["unknown"]["cells"]] == ["Unknown: utilities you pay (electric and gas)", "Unknown: amounts in the listing notes"]


def test_lowest_cost_headline_says_when_the_winner_only_fits_with_a_check(store):
    s = store.add_search("C", "rent")
    store.add_criterion(s["id"], "commute", weight=20, dealbreaker=False, target={"mode": "bike", "minutes": 20})
    an = store.add_anchor("Campus", "x", 40.0, -88.0)
    a, _ = store.add_place(title="Heron", address="1 A St", price=1400, utilities_included="all", pet_fee=0, deposit=500)
    b, _ = store.add_place(title="Brook", address="2 B St", price=1500, utilities_included="all", pet_fee=0, deposit=500)
    for p in (a, b):
        store.set_commute(p["id"], an["id"], "bike", 26, "you")
    es = _en(store, s, a, b)
    first = compare.summary_lines(es, compare.build_rows(es))[0]
    assert first == "Heron has the lowest true monthly cost, though it only fits with a check."


def test_lowest_cost_headline_says_a_quarterly_hoa_was_converted(store):
    s = store.add_search("C", "rent")
    a, _ = store.add_place(title="Quill", address="1 A St", price=1500, utilities_included="all", hoa=70, pet_fee=0, deposit=500,
                           listing_text="Quill 1 bed $1,500. HOA $210 per quarter.")
    b, _ = store.add_place(title="Oak", address="3 B St", price=1600, utilities_included="all", pet_fee=0, deposit=500)
    es = _en(store, s, a, b)
    assert compare.summary_lines(es, compare.build_rows(es))[0] == \
        "Quill has the lowest true monthly cost, counting its HOA as $70 a month (worked out from $210 per quarter)."


# ---- 5. fit and score wording
def test_fit_reason_parts_add_up_to_the_total(store):
    s = store.add_search("F", "rent")
    store.add_criterion(s["id"], "price", weight=50, dealbreaker=True, target={"max": 3000})
    p, _ = store.add_place(title="Med", address="1 A St", price=3225, hoa=80, utilities_estimate=90)
    e = _en(store, s, p)[0]
    assert e["cost"]["total"] == 3395
    assert e["score"]["fit_reasons"] == ["$3,395 a month all in (rent $3,225 + utilities guess $90 + HOA $80), over $3,000 by $395"]


def test_commute_overrun_line_does_not_claim_a_wrong_number(store):
    s = store.add_search("C", "rent")
    an = store.add_anchor("Campus", "x", 40.0, -88.0)
    store.add_criterion(s["id"], "commute", weight=20, dealbreaker=False, target={"mode": "bike", "minutes": 20})
    store.add_criterion(s["id"], "price", weight=50, dealbreaker=False, target={"max": 5000})
    p, _ = store.add_place(title="Far", address="1 A St", price=1000, beds=1, lat=40.01, lng=-88.0, utilities_included="all", deposit=500, pet_fee=0)
    store.set_commute(p["id"], an["id"], "bike", 33, "you")
    sc = _en(store, s, p)[0]["score"]
    assert sc["total"] == 69 and sc["raw_total"] == 81
    assert sc["concerns"] == ["Commute to Campus 33 min bike, over your 20 min, so the score can't go above 69"]


# ---- 6. MCP address with city, state and ZIP of their own
def test_mcp_full_address_is_not_saved_doubled(store):
    store.add_search("B", "buy")
    srv = server(store)
    call(srv, "add_place", title="T", address="10 Buttles Ave Apt 4, Columbus, OH 43215", unit="4", city="Columbus", state="OH", zip="43215", price=300000)
    p = store.list_places(store.current_search()["id"])[0]
    assert (p["address"], p["unit"], p["city"], p["state"], p["zip"]) == ("10 Buttles Ave", "4", "Columbus", "OH", "43215")
    call(srv, "update_place", place_id=p["id"], address="10 Buttles Ave Apt 4, Columbus, OH 43215", unit="4", city="Columbus", state="OH", zip="43215")
    p = store.get_place(p["id"])
    assert (p["address"], p["unit"], p["city"]) == ("10 Buttles Ave", "4", "Columbus")
    call(srv, "update_place", place_id=p["id"], address="12 Oak St, Columbus, OH 43215")  # city, state and ZIP already saved
    assert store.get_place(p["id"])["address"] == "12 Oak St"
    page = local_client(store).get(f"/places/{p['id']}").text
    assert "Columbus, OH, 43215, 4" not in page and "43215, 4, Columbus" not in page


# ---- optional garage that was not counted is never "Parking included $0"
OPT_GARAGE = "A garage is available for $90 a month. It looks optional, so it is not counted in the monthly cost. Ask if it is required."


@pytest.mark.parametrize("cost", [None, 0])
def test_optional_garage_is_not_shown_as_included_zero(store, cost):
    s = store.add_search("S", "rent")
    kw = {} if cost is None else {"parking_cost": cost}
    p, _ = store.add_place(search_id=s["id"], title="Arbor", address="1 A St", price=1500, parking="garage", reader_notes=OPT_GARAGE, **kw)
    e = _en(store, s, p)[0]
    line = next(l for l in e["cost"]["lines"] if l["key"] == "parking")
    assert line["amount"] is None and line["note"] in ("optional parking is not counted; ask what it costs", "not filled in")
    assert "parking" in e["cost"]["uncounted"] and "included" not in line["note"]
    rows = {r["key"]: r for sec in compare.build_rows([e, e]) for r in sec["rows"]}
    assert rows.get("cost-parking") is None or all(c["text"] != "$0" and not c["best"] for c in rows["cost-parking"]["cells"])
    page = local_client(store).get(f"/places/{p['id']}").text
    assert "Parking" in page and "<td class=\"amt\"><span class=\"missing\">unknown</span></td>" in page
