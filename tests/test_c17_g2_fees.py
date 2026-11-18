"""Cycle 17, fixer G2: flat fees, several monthly fees, deposit given per item, half-month landlord fee, per-room rent notes,
buyer transfer fee. Each reviewer phrasing plus other natural wordings; exact values pinned."""
import pytest

from prophelper.parsers import parse_listing
from prophelper.money import cash_at_move_in  # noqa: F401  (imported to prove the module loads with the new fields)


def read(text, buying=False):
    return parse_listing(text, "", buying=buying) if buying else parse_listing(text, "")


def notes(r):
    return r.get("found_in_listing") or ""


# 1. flat monthly fee quoted but not counted
@pytest.mark.parametrize("text,fee", [
    ("Willow Creek Townhome 3BR 2.5BA $2,250. Flat $85/mo fee covers water, sewer, trash and pest control. Electric about $60. Deposit $2,250.", 85),
    ("Townhome 3BR $2,250. Flat fee $85/month covers water, sewer, trash and pest control. Electric about $60.", 85),
    ("Townhome 3BR $2,250. $85/mo flat fee for water, sewer, trash and pest control. Electric about $60.", 85),
])
def test_flat_fee_with_pest_control_counts(text, fee):
    r = read(text)
    assert r["other_monthly_fees"] == fee
    assert r["utilities_estimate"] == 60  # electric only: the covered utilities are paid through the fee, never counted twice
    assert r["tenant_pays"] == "electric"
    assert "not counted anywhere" not in notes(r)
    assert "paid through that flat fee" in notes(r)


@pytest.mark.parametrize("text,fee", [
    ("Dogwood Court - 3 BR / 2 BA duplex. $2,350/mo, includes trash. Flat $20/mo for lawn care. Security deposit $2,350.", 20),
    ("Duplex 3BR $2,350/mo. $20/mo flat fee for lawn care.", 20),
    ("Duplex 3BR $2,350/mo. Flat fee $45/month for snow removal and lawn care.", 45),
])
def test_flat_lawn_fee_counts(text, fee):
    r = read(text)
    assert r["other_monthly_fees"] == fee
    assert "not counted anywhere" not in notes(r)


# 2. several monthly fees in one line
@pytest.mark.parametrize("text", [
    'Rent $1,200 per month. Tenant must also pay a $100 monthly "community fee" and $25 monthly tech package.',
    "Rent $1,200 per month. Tenant must also pay a $100 per month community fee plus a $25 per month technology package.",
    "Rent $1,200 per month. There is a $100/month community fee and a $25/month tech package. $150 admin fee.",
])
def test_two_monthly_fees_both_counted(text):
    r = read(text)
    assert r["other_monthly_fees"] == 125
    assert r.get("move_in_fees") in (None, 150)  # a monthly community fee is never a one-time move-in fee
    assert "not counted anywhere" not in notes(r)


@pytest.mark.parametrize("text", [
    "2BR $1,395 per month. Monthly: Pest control $5, Valet trash $25, Internet $60/mo required.",
    "2BR $1,395 per month. Monthly fees: Pest control $5, valet trash $25, internet $60 required.",
    "2BR $1,395 per month. Pest control $5/mo, valet trash $25/mo, internet $60/mo required.",
])
def test_monthly_list_all_counted(text):
    r = read(text)
    assert r["other_monthly_fees"] == 90
    assert "not counted anywhere" not in notes(r)


def test_monthly_list_equal_amounts_not_collapsed():
    assert read("2BR $1,395 per month. Monthly: Pest control $25, valet trash $25.")["other_monthly_fees"] == 50


def test_monthly_list_optional_internet_not_counted():
    r = read("2BR $1,395 per month. Monthly charges: trash valet $25 and pest control $5. Internet available $60.")
    assert r["other_monthly_fees"] == 30
    assert "$60" in notes(r)  # the optional figure is quoted, never dropped


# 3. deposit given per item
@pytest.mark.parametrize("text,dep,months", [
    ("Beverly 3 bed 2 bath home for rent $2,800 a month. First, last and security deposit required ($2,800 each). Available 1/15/27.", 2800, 2),
    ("Home $1,500 a month. Move-in: first month, last month and deposit, $1,500 each.", 1500, 2),
    ("Home $1,500 a month. $1,500 each for first, last and security deposit.", 1500, 2),
])
def test_deposit_each(text, dep, months):
    r = read(text)
    assert r["deposit"] == dep
    assert r["months_up_front"] == months
    assert "gives no amount" not in notes(r)


def test_deposit_each_in_cash_at_move_in():
    from prophelper.money import cash_at_move_in
    r = read("Beverly 3 bed 2 bath home for rent $2,800 a month. First, last and security deposit required ($2,800 each).")
    cash = cash_at_move_in({"price": r["price"], "deposit": r["deposit"], "months_up_front": r["months_up_front"]})
    total = cash["total"] if isinstance(cash, dict) else cash
    assert total == 8400  # first + last rent 5,600 plus the 2,800 deposit


# 4. half a month landlord fee
@pytest.mark.parametrize("text,fee", [
    ("ROGERS PARK 3BR 2BA $3,050. Landlord fee: 1/2 month rent. Security deposit $1,500.", 1525),
    ("Medical District 2BR $2,000. Landlord fee: half a month's rent. Security deposit $2,000.", 1000),
    ("Medical District 2BR $2,000. Landlord fee equal to 1/2 month rent.", 1000),
    ("Medical District 2BR $2,000. Landlord fee: one-half month rent", 1000),
])
def test_landlord_fee_half_month(text, fee):
    r = read(text)
    assert r["move_in_fees"] == fee
    assert "half a month of rent" in notes(r)


def test_landlord_fee_half_month_no_rent():
    r = read("Great 2BR. Landlord fee: 1/2 month rent.")
    assert "move_in_fees" not in r
    assert "half a month of rent" in notes(r) and "rent was not read" in notes(r)


# 5. two rents: whole place and per room
def test_per_room_in_brackets():
    r = read("Spacious 2 bed Easton apartment $1,425 per month\nRent: $1,425 ($712 per room). 2 bedrooms 2 baths.")
    assert r["price"] == 1425
    n = notes(r)
    assert "$1,425 a month for the whole place and $712 per room" in n
    assert "not counted anywhere" not in n


@pytest.mark.parametrize("text,price,per", [
    ("Wicker Park 3 bed 2 bath. Rent: $3,225 per month; $1,075 per room. Security deposit $3,225.", 3225, 1075),
    ("3 bed apartment $2,700/mo, that is $900 per bedroom.", 2700, 900),
])
def test_per_room_other_wordings(text, price, per):
    r = read(text)
    assert r["price"] == price
    assert f"${price:,.0f} a month for the whole place and ${per:,.0f} per room" in notes(r)
    assert "not counted anywhere" not in notes(r)


def test_total_per_room_and_other_unit():
    r = read("Brookens Commons, 2 BR $1,900 total ($950 per room) / 1 BR $1,325\nChampaign IL. Security deposit $300.")
    assert r["price"] == 1900
    n = notes(r)
    assert "$1,900 a month for the whole place and $950 per room" in n
    assert "A separate 1 BR option at $1,325 is a different unit" in n


# 6. buyer transfer fee
@pytest.mark.parametrize("text", [
    "Condo $230,000. 2 bd, 1 ba. HOA $250 per month.\nTransfer fee paid by buyer $1,500.",
    "Condo $230,000. 2 bd, 1 ba. HOA $250 per month.\nBuyer pays transfer fee $1,500.",
    "Condo $230,000. 2 bd, 1 ba. HOA $250 per month.\nTransfer fee is paid by the buyer, $1,500.",
])
def test_buyer_transfer_fee_counted(text):
    r = read(text, buying=True)
    assert "closing_costs" not in r  # cycle 35: a named one-time item, never the total closing costs
    assert "$1,500 transfer fee" in notes(r)


def test_buyer_transfer_fee_seller_pays_stays_a_note():
    r = read("Condo $230,000. 2 bd, 1 ba.\nTransfer fee paid by seller $1,500.", buying=True)
    assert "closing_costs" not in r
    assert "$1,500 transfer fee" in notes(r)


def test_per_room_that_does_not_add_up_claims_nothing():
    r = read("Savoy Terrace 1BR - $1,425 / 2 people $1,100 per room?? no: rent $1,425 total\nSavoy IL. 1 bed/1 bath.")
    assert r["price"] == 1425
    n = notes(r)
    assert "do not add up" in n and "$1,100 per room" in n
    assert "part of the total" not in n
