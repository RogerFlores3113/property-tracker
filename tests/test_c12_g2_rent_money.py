"""C12 G2: rent, lease, fees and utilities in the listing reader, and the rental HOA in the monthly cost.
Unknown is better than wrong: a value is never read from the wrong line or backwards."""
import pytest

from mcp_util import call, server, structured, text
from prophelper import money, parsers


def P(t):
    return parsers.parse_listing(t)


def fields(r):
    return {k: v for k, v in r.items() if k != "found_in_listing"}


def note(r):
    return r.get("found_in_listing", "")


# ---- 1. a utilities amount comes only from a utilities line
def test_garage_price_is_not_a_utilities_average():
    t = "1 bed $1,395/mo. Utilities billed back monthly. Underground garage available $120/mo. Water/sewer/trash $65/mo flat."
    r = P(t)
    assert r["utilities_estimate"] == 65 and r["tenant_pays"] == "water, sewer, trash"
    assert "other_monthly_fees" not in r  # the flat fee is the utilities estimate, never counted twice
    assert "$120" in note(r) and "billed-back average" not in note(r)


@pytest.mark.parametrize("line", ["Parking $120/mo", "Storage unit $120/mo", "Pet rent $120/mo", "Application $120/mo"])
def test_other_lines_never_give_the_utilities_average(line):
    r = P(f"1 bed $1,395/mo. Utilities billed back via RUBS. {line}.")
    assert "utilities_estimate" not in r


def test_rubs_average_in_its_own_line_still_read():
    assert P("1 bed $1,395/mo. Utilities billed back via RUBS, avg $120/mo.")["utilities_estimate"] == 120


# ---- 2. except cable, who pays what
def test_all_utilities_except_cable_included_is_not_reversed():
    r = P("1 bed $1,200/mo. All utilities except cable included!")
    assert r["utilities_included"] == "all" and "tenant_pays" not in r
    assert "Cable is TV" in note(r)


def test_all_utilities_except_electric_included():
    r = P("1 bed $1,200/mo. All utilities except electric included.")
    assert r["utilities_included"] == "gas, water, sewer, trash, heat" and r["tenant_pays"] == "electric"


def test_tenant_pays_all_except_trash_still_works():
    r = P("1 bed $1,200/mo. Tenant pays all utilities except trash")
    assert r["utilities_included"] == "trash" and r["tenant_pays"] == "electric, gas, water, sewer, heat"


def test_water_sewer_through_city_trash_included_except_cable():
    r = P("3 bed house $2,100/mo. Water and sewer through the city, you set up. Trash included. Except cable.")
    assert r["utilities_included"] == "trash" and r["tenant_pays"] == "water, sewer"


def test_landlord_covers_water_and_trash():
    r = P("3 bed $2,100/mo. Landlord covers water and trash")
    assert r["utilities_included"] == "water, trash" and "tenant_pays" not in r


def test_internet_by_xfinity_tenant_sets_up():
    r = P("3 bed $2,100/mo. Internet by Xfinity, tenant sets up")
    assert r["tenant_pays"] == "internet" and "utilities_included" not in r


# ---- 3. a pet fee never goes into move-in fees
def test_pet_one_time_fee_is_not_also_a_move_in_fee():
    r = P("1 bed apt $1,100/mo. Pets: Cats ok, $300 one time fee, $25/mo. Admin fee $150.")
    assert r["pet_fee"] == 300 and r["pet_rent"] == 25 and r["move_in_fees"] == 150


def test_pet_fee_on_its_own_line_is_not_a_move_in_fee():
    r = P("1 bed apt $1,100/mo\nPets: Cats ok, $300 one time fee, $25/mo\nAdmin fee $150.")
    assert r["pet_fee"] == 300 and r["move_in_fees"] == 150


# ---- 4. lease length
def test_first_stated_lease_wins_over_a_longer_lease_deal():
    r = P("1 bed apt $1,100/mo. Lease 12 months, or sign a 18 month lease and get $100 off a month")
    assert r["lease_months"] == 12
    assert "18 month lease" in note(r) and "12 month lease is what is saved" in note(r)


def test_twelve_month_minimum():
    assert P("1 bed apt $1,100/mo. 12-month minimum")["lease_months"] == 12


def test_one_month_free_with_14_month_lease_unchanged():
    r = P("1 bed apt $1,100/mo. One month free with 14 month lease. 12 month lease")
    assert r["lease_months"] == 12


# ---- 5. rent wording
def test_rent_word_after_the_amount():
    assert P("1 bed apt. $1,299 rent.")["price"] == 1299


def test_rent_in_words():
    r = P("1 bed apt. Rent is eleven hundred a month")
    assert r["price"] == 1100


def test_rent_in_words_that_is_unclear_is_a_note():
    r = P("1 bed apt. Rent is twelve fifty a month")
    assert "price" not in r and "twelve fifty" in note(r)


# ---- 6. fees that used to vanish
def test_quarterly_amenity_fee_is_noted():
    r = P("1 bed apt $1,100/mo. Quarterly amenity fee $90. Pest fee $30/mo")
    assert r["other_monthly_fees"] == 30
    assert "quarterly amenity fee of $90 (about $30 a month)" in note(r) and "not counted" in note(r)


def test_holding_fee_with_amount_is_noted():
    r = P("1 bed apt $1,100/mo. Holding fee $200 to reserve")
    assert fields(r) == {"price": 1100, "beds": 1} and "$200 holding fee" in note(r)


def test_holding_fee_equal_to_a_week_of_rent_is_noted():
    r = P("1 bed apt $1,100/mo. Holding fee equal to one week's rent")
    assert fields(r) == {"price": 1100, "beds": 1} and "holding fee equal to one week's rent" in note(r)


@pytest.mark.parametrize("line,fee", [("Credit check fee $35 each adult", 35), ("Credit check $38 per adult", 38)])
def test_credit_check_fee_per_adult_is_the_application_fee(line, fee):
    r = P(f"1 bed apt $1,100/mo. {line}")
    assert r["application_fee"] == fee and r["application_fee_per_adult"] == 1
    assert "credit check fee is charged per adult" in note(r)


def test_credit_check_with_an_application_fee_is_noted_not_added():
    r = P("1 bed apt $1,100/mo. Application fee $50. Credit check $38 per adult")
    assert r["application_fee"] == 50 and "application_fee_per_adult" not in r
    assert "$38 credit check fee per adult" in note(r)


def test_renters_insurance_required_is_noted():
    r = P("1 bed apt $1,100/mo. Renter's insurance required")
    assert fields(r) == {"price": 1100, "beds": 1} and "renter's insurance is required" in note(r)


# ---- 7. utilities amounts
@pytest.mark.parametrize("t", ["3 bed $2,100/mo. Tenant pays all utilities. Approx $180/month"])
def test_tenant_pays_all_with_an_approximate_amount(t):
    r = P(t)
    assert r["utilities_estimate"] == 180 and r["tenant_pays"] == "electric, gas, water, sewer, trash, heat"
    assert "not counted anywhere" not in note(r)


@pytest.mark.parametrize("t", ["3 bed $2,100/mo. Utilities extra approx $150", "3 bed $2,100/mo. Utilities extra approx $150 per month"])
def test_utilities_extra_approx(t):
    r = P(t)
    assert r["utilities_estimate"] == 150 and "not counted anywhere" not in note(r)


def test_approx_amount_after_a_pet_line_is_not_utilities():
    r = P("3 bed $2,100/mo. Tenant pays electric and gas. Pets ok. Approx $180/month for pet rent")
    assert "utilities_estimate" not in r


def test_gas_average_billed_back():
    r = P("3 bed $2,100/mo. Gas average $90 billed back by landlord monthly")
    assert r["utilities_estimate"] == 90 and r["tenant_pays"] == "gas"
    assert "billed back at $90/month" in note(r)


def test_owner_flat_fee_is_described_as_flat():
    r = P("1 bed $1,395/mo. Water/sewer/trash $65/mo flat")
    assert r["utilities_estimate"] == 65 and "flat fee of $65/month" in note(r) and "other_monthly_fees" not in r


def _rent_place(listing, **kw):
    return {"price": 1395, "listing_text": listing, "pet_rent": 0, "other_monthly_fees": 0, "parking_cost": 0, **kw}


def test_flat_fee_label_in_the_cost_is_flat_not_billed_back():
    t = "1 bed $1,395/mo. Water/sewer/trash $65/mo flat"
    cost = money.rent_cost(_rent_place(t, utilities_estimate=65, tenant_pays="water, sewer, trash"))
    (line,) = [l for l in cost["lines"] if l["key"] == "utilities"]
    assert line["note"].startswith("Flat fee, from the listing") and not line["estimated"]


def test_billed_back_label_stays_for_a_real_billed_back_line():
    t = "1 bed $1,395/mo. Gas average $90 billed back by landlord monthly"
    cost = money.rent_cost(_rent_place(t, utilities_estimate=90, tenant_pays="gas"))
    (line,) = [l for l in cost["lines"] if l["key"] == "utilities"]
    assert line["note"].startswith("Billed back, from the listing")


def test_approx_amount_counts_as_from_the_listing():
    for t, amount in (("3 bed $2,100/mo. Tenant pays all utilities. Approx $180/month", 180), ("3 bed $2,100/mo. Utilities extra approx $150", 150)):
        assert money._estimate_from_listing({"listing_text": t}, amount)


def test_mcp_add_place_reads_the_approx_utilities(store):
    s = store.add_search("Rent")
    out = text(call(server(store), "add_place", title="Oak", search_id=s["id"], listing_text="3 bed $2,100/mo. Utilities extra approx $150"))
    place = store.get_place(1)
    assert place["utilities_estimate"] == 150
    assert "not counted anywhere" not in out


# ---- 8. rental HOA
@pytest.mark.parametrize("t,hoa", [("2 bed $1,500/mo. Quarterly HOA $240 paid by tenant", 80), ("2 bed $1,500/mo. HOA $90 quarterly paid by tenant", 30)])
def test_quarterly_hoa_is_a_monthly_amount(t, hoa):
    assert P(t)["hoa"] == hoa


def test_tenant_paid_hoa_counts_in_the_rent_cost_once():
    t = "2 bed $1,500/mo. Quarterly HOA $240 paid by tenant"
    place = {**P(t), "listing_text": t, "utilities_estimate": 0}
    cost = money.rent_cost(place)
    hoa_lines = [l for l in cost["lines"] if l["key"] == "hoa"]
    assert len(hoa_lines) == 1 and hoa_lines[0]["amount"] == 80
    base = money.rent_cost({**place, "hoa": None})
    assert cost["total"] == base["total"] + 80


def test_hand_set_hoa_counts_in_a_rental():
    base = money.rent_cost({"price": 1500, "utilities_estimate": 0})
    cost = money.rent_cost({"price": 1500, "utilities_estimate": 0, "hoa": 80})
    assert cost["total"] == base["total"] + 80


def test_hoa_in_the_rent_is_not_added_and_not_a_false_alarm():
    t = "2 bed $1,500/mo. HOA dues of $120 per quarter included in your rent"
    r = P(t)
    assert "hoa" not in r and "not counted anywhere" not in note(r) and "included in the rent" in note(r)
    place = {"price": 1500, "utilities_estimate": 0, "hoa": 40, "listing_text": t}
    cost = money.rent_cost(place)
    assert cost["total"] == money.rent_cost({"price": 1500, "utilities_estimate": 0})["total"]
    (line,) = [l for l in cost["lines"] if l["key"] == "hoa"]
    assert line["amount"] == 0


def test_buy_cost_hoa_unchanged():
    cost = money.buy_cost({"price": 400000, "hoa": 300})
    assert [l for l in cost["lines"] if l["key"] == "hoa"][0]["amount"] == 300
