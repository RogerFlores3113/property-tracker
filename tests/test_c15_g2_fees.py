"""Cycle 15, group G2: flat fees, internet and amenity fees, landlord fee, cleaning fee, application wording, conditional fees,
rent without a dollar sign. Each phrasing pins the exact fields."""
import pytest

from prophelper import money
from prophelper.parsers import parse_listing

RENT = "2 bed apartment. Rent $1,400/mo. "


def P(t, rent=True):
    return parse_listing((RENT if rent else "") + t)


def note(r):
    return r.get("found_in_listing") or ""


# ---- 1. flat monthly fees are counted once, in other monthly fees
@pytest.mark.parametrize("t,fee,asked", [
    ("Trash and lawn $30 flat fee", 30, True),
    ("Water/trash flat $65", 65, True),
    ("Trash and lawn $18 flat fee per month", 18, False),
    ("Water, trash and lawn: flat $75/mo fee", 75, False),
])
def test_flat_fee_is_counted_once_in_other_monthly_fees(t, fee, asked):
    r = P(t)
    assert r["other_monthly_fees"] == fee
    assert "utilities_estimate" not in r
    assert "not counted anywhere" not in note(r)
    assert "counted once in other monthly fees" in note(r)
    assert ("does not say how often" in note(r)) is asked
    cost = money.rent_cost(r)
    assert cost["total"] == pytest.approx(1400 + fee, abs=0.01)


def test_flat_fee_with_tenant_utilities_is_not_added_to_an_estimate():
    r = P("Water, trash and lawn: flat $75/mo fee. Tenant pays electric and gas.")
    assert r["other_monthly_fees"] == 75 and "utilities_estimate" not in r and r["tenant_pays"] == "electric, gas"


def test_flat_water_sewer_trash_with_a_month_is_still_the_utilities_estimate():
    r = P("Water/sewer/trash $65/mo flat")
    assert r["utilities_estimate"] == 65 and "other_monthly_fees" not in r


# ---- 2. internet and amenity fees
def test_mandatory_internet_with_provider_is_counted():
    r = P("Internet (Xfinity) $60/mo mandatory")
    assert r["other_monthly_fees"] == 60 and "utilities_estimate" not in r
    assert "not counted anywhere" not in note(r)


@pytest.mark.parametrize("t", ["$175 amenity fee monthly", "Fees | $175 amenity fee monthly | pets ok"])
def test_amenity_fee_monthly_is_counted(t):
    r = P(t)
    assert r["other_monthly_fees"] == 175 and "not counted anywhere" not in note(r)


def test_pipe_style_fees_line():
    r = P("Fees: $65 application, $175 amenity fee monthly")
    assert (r["application_fee"], r["other_monthly_fees"]) == (65, 175) and "move_in_fees" not in r
    assert "not counted anywhere" not in note(r)


# ---- 3. landlord fee and deposit in months of rent
def test_landlord_fee_one_month_is_a_move_in_fee_equal_to_rent():
    r = P("Landlord fee: 1 month's rent paid to Lakeshore Realty")
    assert r["move_in_fees"] == 1400 and "other_monthly_fees" not in r and "broker_fee" not in r
    assert "landlord fee is 1 month of rent ($1,400)" in note(r) and "one-time move-in fee" in note(r)


def test_landlord_fee_without_rent_stays_unknown_with_a_note():
    r = parse_listing("Landlord fee: 1 month's rent paid to Lakeshore Realty")
    assert "move_in_fees" not in r and "rent was not read" in note(r)


def test_security_deposit_equal_to_one_month_rent():
    r = P("Security deposit equal to one month's rent")
    assert r["deposit"] == 1400 and "move_in_fees" not in r


# ---- 4. cleaning fee at move-in
@pytest.mark.parametrize("t,fee", [("Cleaning fee at move-in $150", 150), ("Cleaning fee $200 due at move-in", 200)])
def test_cleaning_fee_at_move_in(t, fee):
    r = P(t)
    assert r["move_in_fees"] == fee and "other_monthly_fees" not in r
    assert "in total to move in" not in note(r) and "not counted anywhere" not in note(r)


def test_admin_fee_due_at_signing_is_not_a_move_in_total():
    r = P("Admin fee $150 due at signing.")
    assert r["move_in_fees"] == 150 and "in total to move in" not in note(r)


# ---- 5. application fees
def test_application_fee_pipe_style():
    r = P("Application | $65 application fee | Admin | none")
    assert r["application_fee"] == 65 and "application_fee_per_adult" not in r


def test_application_each_adult():
    r = P("$75 application each adult")
    assert r["application_fee"] == 75 and r["application_fee_per_adult"] == 1
    assert "charged per adult" in note(r) and "not counted anywhere" not in note(r)


# ---- 6. conditional fees
def test_admin_fee_reduced_if_condition_keeps_full_fee_and_a_note():
    r = P("Admin fee $75 due at signing, reduced to $0 if you apply this week")
    assert r["move_in_fees"] == 75
    assert '"if you apply this week"' in note(r) and "full $75 is what is counted" in note(r)


def test_zero_deposit_with_approved_credit_is_unknown_with_a_note():
    r = P("$0 deposit with approved credit")
    assert "deposit" not in r
    assert "best-case deposit of $0 with approved credit" in note(r) and "ask what the deposit will be" in note(r)


def test_no_deposit_plain_is_still_zero():
    assert P("No security deposit.")["deposit"] == 0


# ---- 7. rent without a dollar sign, key fee
def test_rent_without_dollar_sign_with_a_month():
    r = parse_listing("2 bed apartment. 1,299 a month")
    assert r["price"] == 1299 and "in total to move in" not in note(r)
    assert "move_in_fees" not in r and "deposit" not in r


def test_move_in_total_wording_is_not_given_to_a_rent():
    r = parse_listing("Move-in cost: 1,299 a month.")
    assert r["price"] == 1299 and "in total to move in" not in note(r)


@pytest.mark.parametrize("t", ["1,299 per month", "1,299/mo"])
def test_rent_without_dollar_sign_other_markers(t):
    assert parse_listing("2 bed apartment. " + t)["price"] == 1299


def test_bare_number_is_not_a_rent():
    assert "price" not in parse_listing("2 bed apartment near 1,299 steps from campus")


def test_deposit_first_and_key_fee():
    r = parse_listing("Grandview cottage. 1,299 a month. $1,299 deposit + $1,299 first + $100 key fee")
    assert (r["price"], r["deposit"], r["move_in_fees"]) == (1299, 1299, 100)
    assert "other_monthly_fees" not in r and "not counted anywhere" not in note(r)
