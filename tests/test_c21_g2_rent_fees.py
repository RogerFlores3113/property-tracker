"""Cycle 21 G2: read the whole item (a utilities figure is never the rent), price changes, fee lists, deposits, per-person fees, broker percent."""
from __future__ import annotations

import pytest

from prophelper.parsers import parse_listing


def read(text: str) -> dict:
    return parse_listing(text, "")


def notes(r: dict) -> str:
    return r.get("found_in_listing") or ""


# ---- 1. a figure in a utilities clause is never the rent
@pytest.mark.parametrize("text,rent", [
    ("Quiet cul-de-sac ranch, 3 bed 2 bath, $2,275. Tenant pays utilities, about $230 per month for electric, gas and water (all-in).", 2275),
    ("Quiet cul-de-sac ranch, 3 bed 2 bath, $2,275. Tenant pays utilities, approx. $230 per month for electric, gas and water (all-in).", 2275),
    ("Quiet cul-de-sac ranch, 3 bed 2 bath, $2,275. Tenant pays utilities, approx. $230 a month for electric, gas and water.", 2275),
    ("3/2 ranch in quiet cul-de-sac. $2,275. Tenant pays utilities. Approx. $230 per month for electric/gas/water (all-in). Fenced yard.", 2275),
    ("Rent $1,800, 2 bed. You pay electric and gas, around $150/mo.", 1800),
    ("- 2 bed 1 bath, $1,650\n- Utilities: about $175 per month, tenant pays", 1650),
    ("2 bed 1 bath $1,500. Tenant pays utilities (electric, gas, water), roughly $200 a month.", 1500),
    ("Cozy 2 bed. $1,425. $190 per month for gas and electric, you pay.", 1425),
])
def test_utility_figure_is_not_the_rent(text, rent):
    r = read(text)
    assert r["price"] == rent


def test_family_l45_whole_listing_fields():
    r = read("Quiet cul-de-sac ranch, 3 bed 2 bath, $2,275. Tenant pays utilities, about $230 per month for electric, gas and water (all-in).")
    assert (r["price"], r["beds"], r["baths"], r["utilities_estimate"]) == (2275, 3, 2, 230)
    assert "not counted" not in notes(r)


def test_one_month_deposit_follows_the_real_rent():
    r = read("3/2 ranch in quiet cul-de-sac. $2,275. Tenant pays utilities. Approx. $230 per month for electric/gas/water (all-in). Application fee is $50 per person, deposit one month's rent.")
    assert r["price"] == 2275 and r["deposit"] == 2275


@pytest.mark.parametrize("text,beds,baths", [
    ("Newly renovated 3/2 near Hoover Elementary. Rent $2,425.", 3, 2),
    ("Sunny 2/1 near campus, $950/mo", 2, 1),
    ("Charming 4/2.5 home on a corner lot, $3,100 a month", 4, 2.5),
    ("Updated 2x1 apartment, $1,100 per month", 2, 1),
])
def test_beds_baths_shorthand(text, beds, baths):
    r = read(text)
    assert (r["beds"], r["baths"]) == (beds, baths)


@pytest.mark.parametrize("text", [
    "Available 3/2. 2 bed apartment, $1,200/mo",
    "Open house 3/2 at noon. 2 bed, $1,200/mo",
    "Walk 1/2 mile to campus. 2 bed, $1,200/mo",
    "Lease starts on 3/2/27. 2 bed, $1,200/mo",
])
def test_slash_date_or_fraction_is_not_baths(text):
    assert read(text).get("baths") is None


def test_floor_plan_shorthand_rent_nontech_l4():
    r = read("The Maple at Polaris\n$1,425 - $1,610 | 2 Beds | 1-2 Baths\nFloor plan 2x1: $1,425. Pet rent: $30 per month. Pet fee $250. Cats welcome.\n"
             "Parking: 1st car $100, 2nd car $125 per month\nAdmin fee $175. Application fee $55.\n1x1. from $1,199\n8800 Polaris Pkwy, Columbus, OH 43240")
    assert (r["price"], r["beds"], r["baths"]) == (1425, 2, 1)
    assert "rent is left empty" not in notes(r)
    assert "1 bed floor plan" in notes(r) and "1,199" in notes(r)
    assert "not counted anywhere" not in notes(r).split("1,199")[0].split("\n")[-1]


@pytest.mark.parametrize("text,rent,beds,baths", [
    ("Cozy 1x1 near campus, $1,150!! Utilities all included!!", 1150, 1, 1),
    ("Cute 2x1 close to campus, $1,325!", 1325, 2, 1),
    ("Floor plan 3x2: $1,900. Pets ok.", 1900, 3, 2),
    ("Plan 2x2 - $1,640 per month", 1640, 2, 2),
])
def test_shorthand_followed_by_a_rent(text, rent, beds, baths):
    r = read(text)
    assert (r["price"], r["beds"], r["baths"]) == (rent, beds, baths)


def test_uiuc_l10_scam_listing_reads_the_rent_but_keeps_the_wire_note():
    r = read("Cozy 1x1 near campus, $1,150!! Utilities all included!! Wire the deposit via Zelle to hold it before you see it. Owner out of the country, keys mailed after payment. "
             "1105 W Oregon St Urbana. W/D in unit, dishwasher, garage. Will not allow inspection before deposit. Kindly send $1,150 now, please.")
    assert r["price"] == 1150
    assert "deposit" not in r
    assert "wire" in notes(r)


# ---- 2. price changes
@pytest.mark.parametrize("text,new,old", [
    ("Lincoln Park 3 br 2 ba. rent was $3,600, reduced to $3,325. Deposit $3,325.", 3325, "3,600"),
    ("2 bed. Rent was $2,400, dropped to $2,250 this week.", 2250, "2,400"),
    ("1 bedroom, previously $1,900, then lowered to $1,750/mo.", 1750, "1,900"),
])
def test_rent_was_reduced_to(text, new, old):
    r = read(text)
    assert r["price"] == new
    assert old in notes(r)


@pytest.mark.parametrize("text,ongoing,promo", [
    ("RENT SPECIAL!!! 3BR house, Redwood City, $2,100 first 6 months then $2,350. Large fenced yard.", 2350, "2,100"),
    ("2 bed apartment. $1,800 for the first 3 months, then $1,950.", 1950, "1,800"),
    ("2 bed. First 6 months $2,100, then $2,350 a month.", 2350, "2,100"),
])
def test_promo_then_ongoing_rent(text, ongoing, promo):
    r = read(text)
    assert r["price"] == ongoing
    assert promo in notes(r) and "first" in notes(r)


@pytest.mark.parametrize("text,rent,cond", [
    ("2 bedroom townhome Grandview\n$1,490/mo, now $1,450 if you sign by Dec 15.", 1490, "1,450"),
    ("1 bed. $1,700/mo, now $1,650 when you sign by Dec 1.", 1700, "1,650"),
    ("2 bed, $1,500 per month, special $1,400 with a 12 month lease.", 1500, "1,400"),
])
def test_conditional_lower_price_is_a_note(text, rent, cond):
    r = read(text)
    assert r["price"] == rent
    assert cond in notes(r)


def test_limited_time_price_is_still_the_rent():
    r = read("Rent: $3,500 -> now $3,280 for a limited time\nLakeview 3-bedroom, 2-bath")
    assert r["price"] == 3280


# ---- 3. fee lists, every item
def test_fees_list_uiuc_l13():
    r = read("1BR at Grove & Wright | rent 1,260 | 1 bed | 1 bath\nNo pets allowed. Fees: application $50, admin $120, lease processing $60. Security $1,260.")
    assert r["application_fee"] == 50 and r["move_in_fees"] == 180 and r["deposit"] == 1260
    assert "not counted anywhere" not in notes(r)


@pytest.mark.parametrize("text,fees", [
    ("2 bed, $1,400 per month. Fees: application $40, admin $90, lease processing $45.", 135),
    ("2 bed, $1,400 per month.\n- Application fee: $40\n- Admin fee: $100\n- Lease fee: $50", 150),
    ("2 bed, $1,400 per month. Fees (one time): application $40 / admin $110 / lease-up $30.", 140),
])
def test_fee_list_layouts(text, fees):
    r = read(text)
    assert r["application_fee"] == 40 and r["move_in_fees"] == fees


def test_amenity_one_time_and_monthly_fees_roommates_l5():
    r = read("Doorman building. 1000 N State St Chicago IL 60610. 3BR 2BA $3,450 now $3,290 (was $3,450). Fees: $250 amenity fee one-time, $35 monthly package fee, $25 monthly pest fee. Deposit $1,000.")
    assert r["move_in_fees"] == 250 and r["other_monthly_fees"] == 60 and r["price"] == 3290


@pytest.mark.parametrize("text,fee", [
    ("Albany Park 3BR 2BA $2,850. Amenity fee $200 one time.", 200),
    ("2BR 1BA $1,900. Amenity fee: $175 one-time.", 175),
    ("2BR 1BA $1,900. $225 one time amenity fee.", 225),
])
def test_one_time_amenity_fee_is_move_in_cash(text, fee):
    r = read(text)
    assert r["move_in_fees"] == fee
    assert r.get("other_monthly_fees") is None


def test_amenity_fee_with_no_period_is_not_guessed():
    r = read("2BR 1BA $1,900. Amenity fee $50.")
    assert r.get("move_in_fees") is None and r.get("other_monthly_fees") is None
    assert "50" in notes(r)


@pytest.mark.parametrize("text,fee", [
    ("Nice 2 bd apt, rent $1,450/mo.\nAdmin $125 due at signing. Deposit: 1 month.", 125),
    ("2 bd apt, rent $1,450/mo. Admin fee $90 due at signing.", 90),
    ("2 bd apt, rent $1,450/mo. Admin: $75, due at move-in.", 75),
])
def test_admin_due_at_signing_is_a_fee_not_the_total(text, fee):
    r = read(text)
    assert r["move_in_fees"] == fee
    assert "in total to move in" not in notes(r)


@pytest.mark.parametrize("text,fee", [
    ("Charming 2BR, $1,380 / month.\nMove-in costs: first month + $1,380 security deposit + $35 application per applicant + $50 lease fee.", 50),
    ("2BR, $1,380 / month. Lease fee $60 at signing.", 60),
    ("2BR, $1,380 / month. $40 lease fee.", 40),
])
def test_lease_fee_is_move_in_fee(text, fee):
    r = read(text)
    assert r["move_in_fees"] == fee
    assert "not counted anywhere" not in notes(r)


def test_nontech_l10_other_fields_stay():
    r = read("Charming 2BR Upper Flat\n$1,380 / month   |   Lease: 12 mo\nMove-in costs: first month + $1,380 security deposit + $35 application per applicant + $50 lease fee.")
    assert r["deposit"] == 1380 and r["application_fee"] == 35 and r["application_fee_per_adult"] == 1


@pytest.mark.parametrize("text,total,dep", [
    ("Spacious townhouse 3 bed / 2.5 bath, $2,295.\nFees: Application $45/adult; Admin $150; Lease-up $100; Key deposit $50 refundable.\nDeposit $1,500.", 300, 1500),
    ("3 bed, $2,295. Admin $80, lease-up $40, key deposit $20. Deposit $1,500.", 140, 1500),
    ("3 bed, $2,295.\n- Admin: $60\n- Lease-up fee: $35\n- Key deposit: $25\nDeposit $1,500.", 120, 1500),
])
def test_every_item_of_a_fee_list_is_counted(text, total, dep):
    # cycle 28: a key deposit is never the security deposit; it is counted once in the move-in fees
    r = read(text)
    assert r["move_in_fees"] == total
    assert r["deposit"] == dep
    assert "not counted anywhere" not in "\n".join(l for l in notes(r).split("\n") if "Admin" in l or "Lease" in l or "Key" in l)


def test_fee_list_does_not_count_monthly_or_pet_items():
    r = read("2 bed, $1,400 per month. Fees: admin $100 one time, pet fee $300, parking $50/month, application $40.")
    assert r["move_in_fees"] == 100
    assert r["application_fee"] == 40


# ---- 4. deposits
@pytest.mark.parametrize("text,dep", [
    ("1BR rent 1,260. Fees: application $50. Security $1,260.", 1260),
    ("1BR $1,100 per month. Security: $900.", 900),
    ("1BR $1,100 per month.\n- Security $1,100 refundable", 1100),
])
def test_security_with_amount_is_a_deposit(text, dep):
    assert read(text)["deposit"] == dep


@pytest.mark.parametrize("text,dep", [
    ("3 Bed Duplex Half | $2,450 | NOT incl. utilities\nApplication fee: $50 per adult, nonrefundable. Security 1.5x rent.", 3675),
    ("2 bed, $1,000 per month. Security deposit 2x rent.", 2000),
    ("2 bed, $1,000 per month. Deposit: 1.5 x rent", 1500),
])
def test_deposit_as_a_multiple_of_rent(text, dep):
    r = read(text)
    assert r["deposit"] == dep
    assert "confirm" in notes(r)


def test_deposit_1x1_is_one_month_not_a_layout():
    r = read("Rent: $2,395 | 3bd/2ba | Pets welcome.\nApplication $45 each adult. Deposit: 1x1.")
    assert r["price"] == 2395 and r["deposit"] == 2395
    assert (r["beds"], r["baths"]) == (3, 2)
    assert "confirm" in notes(r)
    r2 = read("Duplex $1,600 per month. Deposit 1x1 (one month).")
    assert r2["deposit"] == 1600 and r2.get("beds") is None


def test_deposit_multiple_without_rent_stays_empty():
    r = read("Security 1.5x rent. 2 bed apartment near campus.")
    assert r.get("deposit") is None
    assert "rent was not read" in notes(r)


# ---- 5. per-person fees
@pytest.mark.parametrize("text,fee", [
    ("2 bed / 1 bath. Asking $1,350 monthly.\nFees: $40 each application fee per adult, admin fee $100.", 40),
    ("3BR house, $2,350. Apply online $38/person.", 38),
    ("3BR house, $2,350. Apply now $42 per adult.", 42),
])
def test_per_person_application_fee(text, fee):
    r = read(text)
    assert r["application_fee"] == fee and r["application_fee_per_adult"] == 1


@pytest.mark.parametrize("text,fee", [
    ("Tri-level townhome, 3 bedrooms. $2,360/month. Application: $35 per adult plus $25 background check each.", 60),
    ("3 bedrooms. $2,360/month. Application fee $30 per adult plus $20 background check each.", 50),
    ("3 bedrooms. $2,360/month.\nApplication fee: $45 per adult\nBackground check: $15 per adult", 60),
])
def test_application_and_background_check_both_per_adult(text, fee):
    r = read(text)
    assert r["application_fee"] == fee and r["application_fee_per_adult"] == 1
    assert "background check" in notes(r)


# ---- 6. broker percent from the saved rent
@pytest.mark.parametrize("text,fee", [
    ("NEW CONSTRUCTION! The Foundry at Neil - 1BR/1BA - from $1,575/mo (was $1,650)\nBroker fee: 5% of annual rent for off-site agents.", 945),
    ("Brand new construction. 2BR $2,000/mo. Broker fee: 10% of annual rent.", 2400),
    ("New construction 1BR, rent $1,300/month. Agent fee: 15% of annual rent.", 2340),
])
def test_broker_percent_on_new_construction_rental(text, fee):
    r = read(text)
    assert r["broker_fee"] == fee
    assert "rent was not read" not in notes(r)
    assert "confirm" in notes(r)


def test_foundry_note_names_the_condition():
    r = read("NEW CONSTRUCTION! The Foundry at Neil - 1BR/1BA - from $1,575/mo\nBroker fee: 5% of annual rent for off-site agents.")
    assert "off-site agents" in notes(r)


# ---- no regressions on layouts next to the new readers
@pytest.mark.parametrize("text,rent,dep,app,mi", [
    ("Rent: $1,900 /mo   Application fee: $50   Admin fee: $100", 1900, None, 50, 100),
    ("Room in 3 bedroom house $650/month utilities not included deposit $650 no pets", 650, 650, None, None),
    ("2 bed $1,400/month water included. Application fee $40. Admin fee $60.", 1400, None, 40, 60),
    ("2 bed, rent $1,500/mo, utilities extra. Admin fee $75 one time.", 1500, None, None, 75),
])
def test_neighbours_keep_their_values(text, rent, dep, app, mi):
    r = read(text)
    assert r["price"] == rent
    assert r.get("deposit") == dep and r.get("application_fee") == app and r.get("move_in_fees") == mi


def test_street_number_after_rent_word_is_still_not_the_rent():
    assert read("HOUSE FOR RENT. 612 Mohawk St, 3 bed").get("price") is None


def test_rent_with_utilities_extra_after_amount_still_reads_the_rent():
    r = read("1 bed $1,150 + utilities. Tenant pays electric about $60 per month.")
    assert r["price"] == 1150
