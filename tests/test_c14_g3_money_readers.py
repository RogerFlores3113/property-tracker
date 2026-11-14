"""Cycle 14, group G3: renter's insurance, HOA periods, pets, fees and buyer money. Each phrasing pins the exact fields."""
import pytest

from mcp_util import call, server, text
from prophelper import money, parsers
from prophelper.parsers import parse_listing


def rent(t, **kw):
    return parse_listing("2 bed apartment. Rent $2000/mo. " + t, **kw)


def buy(t):
    return parse_listing("3 bed house for sale. Price $500,000. " + t, buying=True)


def notes(r):
    return r.get("found_in_listing") or ""


# ---- 1. renter's insurance is a yearly amount
@pytest.mark.parametrize("t,yearly,monthly", [
    ("Renter's insurance required, approx $15/month", 180, 15),
    ("Renter's insurance required $15/mo", 180, 15),
    ("Renter's insurance through us $14/mo required", 168, 14),
])
def test_renters_insurance_monthly_is_saved_as_yearly(t, yearly, monthly):
    r = rent(t)
    assert r["insurance"] == yearly
    assert f"${monthly} a month" in notes(r) and "counted" in notes(r) and "No cost is counted" not in notes(r)
    assert "utilities_estimate" not in r and "other_monthly_fees" not in r
    line = next(l for l in money.rent_cost(r)["lines"] if l["key"] == "insurance")
    assert line["amount"] == pytest.approx(yearly / 12, abs=0.01)


def test_renters_insurance_required_without_amount_stays_a_note():
    r = rent("Renter's insurance required")
    assert "insurance" not in r and "No cost is counted for it" in notes(r)


def test_optional_renters_insurance_is_not_counted():
    r = rent("Renter's insurance $15/mo optional")
    assert "insurance" not in r


def test_insurance_warning_in_update_place(store):
    store.add_search("S", "rent")
    p, _ = store.add_place(title="Maple", address="1 Oak St", price=1500)
    out = text(call(server(store), "update_place", place_id=p["id"], insurance=15))
    assert "YEAR" in out and "insurance" in out.lower() and "$180" in out
    assert store.get_place(p["id"])["insurance"] == 15  # kept, not changed
    ok = text(call(server(store), "update_place", place_id=p["id"], insurance=180))
    assert "YEAR" not in ok


def test_insurance_warning_in_add_place_and_docs(store):
    store.add_search("S", "rent")
    srv = server(store)
    out = text(call(srv, "add_place", title="Maple Court", address="2 Oak St", price=1500, insurance=15))
    assert "YEAR" in out
    from prophelper import mcp_server
    desc = dict((n, d) for n, _, d in mcp_server.PLACE_PARAMS)["insurance"]
    assert "YEARLY" in desc and "180" in desc


def test_buy_place_gets_no_insurance_warning(store):
    store.add_search("S", "buy")
    out = text(call(server(store), "add_place", title="House", address="3 Oak St", price=400000, insurance=15))
    assert "YEAR" not in out


# ---- 2. HOA periods and who pays
@pytest.mark.parametrize("t", ["HOA $240 billed quarterly", "HOA assessments $240 billed quarterly"])
def test_hoa_billed_quarterly_is_a_third(t):
    assert rent(t)["hoa"] == 80


def test_quarterly_hoa_paid_by_owner_is_not_counted_for_a_tenant():
    r = rent("Quarterly HOA $240 paid by owner")
    assert "hoa" not in r and "owner pays the HOA" in notes(r)


def test_hoa_billed_annually_and_plain_monthly_still_work():
    assert rent("HOA $1,200 billed annually")["hoa"] == 100
    assert rent("HOA $120/mo")["hoa"] == 120


def test_hoa_assessment_with_no_period_is_not_monthly_dues():
    assert "hoa" not in buy("HOA assessment $4,000.")


# ---- 3. pets
def test_pet_deposit_part_non_refundable():
    r = rent("$350 pet deposit (non-refundable $150 of it)")
    assert r["pet_deposit"] == 200 and r["pet_fee"] == 150
    assert "not counted anywhere" not in notes(r)


def test_pet_deposit_part_larger_than_whole_stays_empty():
    r = rent("$150 pet deposit (non-refundable $350 of it)")
    assert "pet_deposit" not in r and "pet_fee" not in r and "left empty" in notes(r)


@pytest.mark.parametrize("t,amount,pets", [("cat rent $25", 25, "cats"), ("Dog rent $40", 40, "dogs")])
def test_animal_rent_is_pet_rent(t, amount, pets):
    r = rent(t)
    assert r["pet_rent"] == amount and r["pets"] == pets and "pet_fee" not in r
    assert "not counted anywhere" not in notes(r)


def test_pet_fee_per_animal_without_search_pet():
    r = rent("Pet fee $250 cat, $400 dog")
    assert "pet_fee" not in r
    n = notes(r)
    assert "$250 for a cat" in n and "$400 for a dog" in n and "not counted anywhere" not in n


@pytest.mark.parametrize("kind,fee", [("cat", 250), ("dog", 400)])
def test_pet_fee_per_animal_with_search_pet(kind, fee):
    r = rent("Pet fee $250 cat, $400 dog", pet_kind=kind)
    assert r["pet_fee"] == fee and "not counted anywhere" not in notes(r)
    assert "$250 for a cat" in notes(r) and "$400 for a dog" in notes(r)


def test_pet_fee_per_animal_with_both_pets_stays_empty():
    r = rent("Pet fee $250 cat, $400 dog", pet_kind="both")
    assert "pet_fee" not in r and "$250" in notes(r)


def test_cat_fee_and_dog_fee_each_named():
    r = rent("Cat fee $250, dog fee $400", pet_kind="dog")
    assert r["pet_fee"] == 400


def test_small_pets_considered_leaves_pets_empty_with_a_note():
    r = rent("small pets considered")
    assert "pets" not in r and "small pets may be allowed" in notes(r)


def test_pet_kind_reaches_the_reader_through_a_saved_search(store):
    sid = store.add_search("S", "rent", pet_kind="cat")["id"]
    p, _ = store.add_place(title="Maple", address="1 Oak St", price=2000, listing_text="Rent $2000. Pet fee $250 cat, $400 dog",
                           reader_notes="x")
    assert p["pet_fee"] is None
    assert "$250 for a cat" in (store.get_place(p["id"]).get("reader_notes") or "")


# ---- 4. fees
def test_non_refundable_cleaning_fee_is_a_move_in_fee():
    r = rent("$200 non-refundable cleaning fee")
    assert r["move_in_fees"] == 200 and "Check what it is for" not in notes(r)


def test_cleaning_fee_at_move_out_is_a_plain_note():
    r = rent("Cleaning fee $175 at move-out")
    assert "move_in_fees" not in r
    n = notes(r)
    assert "$175" in n and "move out" in n and "not counted in the monthly cost" in n and "Check what it is for" not in n


# ---- 5. buyer money
def test_seller_cap_and_estimated_closing_costs():
    r = buy("Seller concessions up to $5,000 toward closing costs available. Estimated closing costs: $7,800.")
    assert r["closing_costs"] == 7800 and "seller_credit" not in r
    assert "left empty" not in notes(r) and "closing costs and" not in notes(r)
    assert "$5,000" in notes(r)


def test_seller_cap_note_does_not_say_credit_is_empty_when_the_caller_passed_one():
    t = "3 bed house for sale. Price $500,000. Seller concessions up to $5,000 toward closing costs available."
    r = parse_listing(t, buying=True, current={"seller_credit": 3000})
    n = notes(r)
    assert "$5,000" in n and "left empty" not in n and "no seller credit is saved" not in n and "$3,000" in n


def test_seller_credit_passed_through_mcp_add_place(store):
    store.add_search("S", "buy")
    out = text(call(server(store), "add_place", title="House", address="3 Oak St", price=500000, seller_credit=3000,
                    listing_text="Seller concessions up to $5,000 toward closing costs available."))
    assert "left empty" not in out and "no seller credit is saved" not in out


def test_condo_assessment_payable_by_buyer_is_cash_to_close():
    r = buy("Condo assessment of $2,400 payable by buyer at closing")
    assert r["special_assessment"] == 2400 and r["special_assessment_payer"] == "buyer"
    assert "special assessment paid by the buyer" in notes(r) and "not counted anywhere" not in notes(r)
    parts = money.cash_to_close({**r, "price": 500000})["parts"]
    assert any(p["amount"] == 2400 and "Special assessment" in p["label"] for p in parts)


def test_capital_contribution_at_closing_is_cash_to_close():
    r = buy("$1,000 one-time capital contribution at closing")
    assert r["special_assessment"] == 1000 and r["special_assessment_payer"] == "buyer"
    assert "capital contribution" in notes(r) and "not counted anywhere" not in notes(r)


def test_monthly_assessment_is_not_a_one_time_buyer_cost():
    r = buy("Condo assessment of $150/month payable by buyer")
    assert "special_assessment" not in r


def test_price_cut_note_says_price_in_a_buy_search():
    r = buy("Reduced from $525,000.")
    assert " rent" not in notes(r).lower() and "current price" in notes(r)
    r2 = rent("Reduced from $2,100.")
    assert "current rent" in notes(r2)
