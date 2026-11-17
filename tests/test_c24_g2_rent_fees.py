"""Cycle 24 G2: cents in fees and deposits, "1.5 months" is never a date, a credit check inside the application fee, lease length options,
the cheapest plan for the bed count, and a corrected rent. Each item has the reviewer's saved listing and two more wordings."""
import pytest

from prophelper.parsers import parse_listing

L12 = 'Lovely 3BR 2BA ranch, 410 Hillview Dr, Redwood City. Rent: $2,325/mo. Heat is gas. Resident pays gas, electric and water (about $55/mo water). Pets: dogs only, one pet max, 65 lbs max, pet rent $50, one-time pet fee $250. Fully fenced yard with gate. Application fee $42.50 per adult. Security deposit: 1.5 months. First and last month due at signing. Garage 2 cars included. Elementary school across the street (Hoover). Showings Sat 10-2.'
L7 = '4BR/2BA home - 880 Elm St, Belmont - $2,450 monthly. Enclosed yard. No pets over 35 lbs. Cats ok. Pet charge $25 a month. Utilities: tenant pays all except internet and electric (electric avg $40... actually, ask). Move-in: 1.5 months deposit, non-refundable cleaning deposit $300. Application $45 each adult 18+. Lease 12 months.'
L10 = '3 bd 2 ba house 920 Cedar Ln, Redwood City. $2,375/mo. Yard fenced. Cats and dogs OK, no more than 2 pets, no breed restrictions, pet deposit refundable $400. Pet rent not charged. Tenant pays PG&E and water (quarterly water bill about $270). Heat is electric. Security deposit 1 month. App fee $50/adult plus $30 credit check per adult. Elementary school (Roosevelt) 6 min walk. Available Dec 15.'
RM62 = 'South Loop - 3 Bedroom, 2 Bath - 1400 S Michigan Ave, Chicago, IL 60605\nRent: $3,200 per month\nLease: 12 months (or 15 months at $3,100)\nUtilities: Water and trash billed quarterly (approx $120 per quarter). Electric: tenant. Gas: heat is gas, tenant pays.\nParking: Garage space $200/month, required.\nMove-in fees: $250 admin fee, $500 non-refundable deposit, $100 move-in elevator fee.\nPet policy: Cats and dogs welcome, $35/month pet rent.\nAvailable 01/15/2027'
RM68 = 'Uptown 3 bedroom 2 bath | 4600 N Sheridan Rd Chicago IL 60640 | $3,000 | 6k in concessions, 1 month free on 13-month lease | All utilities included except internet | no parking | Deposit 1 month | Avail 1/15/27\nCORRECTION: rent is now $3,100, ignore earlier price.'
NT15 = 'Clintonville Garden Apartments - 2BR/1BA\nFloor plans: 2BR Standard 850 sqft $1,380 | 2BR Deluxe 980 sqft $1,520 (12 mo) | 2BR Deluxe 980 sqft $1,480 (15 mo)\nUtilities: Resident pays electric; water, sewer & trash billed quarterly at $135.\nDeposit: 1.5 months rent. Administrative fee: $200 non-refundable. Pets welcome - $35/month per cat, cat deposit $300.\nParking: $0 (street). Application $40.'


def _r(text):
    r = parse_listing(text, "")
    return r, r.get("found_in_listing") or ""


def _no_false_not_counted(notes, *figures):
    for ln in notes.split("\n"):
        if "not counted" in ln.lower() or "missing" in ln.lower():
            for f in figures:
                assert f not in ln, ln


# ---- item 1: cents
def test_cents_reviewer_listing_l12():
    r, notes = _r(L12)
    assert r["application_fee"] == 42.5
    assert r["application_fee_per_adult"] == 1
    assert "$42.50" in notes and "$42 " not in notes
    _no_false_not_counted(notes, "$42.50", "$42")
    assert r["deposit"] == 3487.5


@pytest.mark.parametrize("text, expect", [
    ("2BR $1,800/mo. Application fee: $42.50", {"application_fee": 42.5}),
    ("2BR $1,800/mo\n- Application: $42.50 each\n- Admin fee: $125.50\n- Security deposit: $1,500.50",
     {"application_fee": 42.5, "move_in_fees": 125.5, "deposit": 1500.5}),
    ("2BR $1,800/mo. Fees: application $42.50, admin $60.25, lease processing $30.75", {"application_fee": 42.5, "move_in_fees": 91}),
    ("2BR $1,800/mo. $42.50 application fee. $75.25 admin fee. $1,000.75 security deposit.", {"application_fee": 42.5, "move_in_fees": 75.25, "deposit": 1000.75}),
    ("2BR $1,800/mo\nCleaning fee $87.50 due at move-in\nKey deposit $25.50 refundable\nSecurity deposit: $1,200.25\nApp fee $38.50/adult",
     {"application_fee": 38.5, "move_in_fees": 113, "deposit": 1200.25}),
    ("2BR $1,800/mo. Credit check fee $29.50 per adult. Deposit $900.", {"application_fee": 29.5, "deposit": 900}),
    ("2BR $1,800/mo. Move-in fee $99.99. Non-refundable deposit $350.50. Background check $25.50 each.", {"application_fee": 25.5, "move_in_fees": 450.49, "deposit": 0}),
])
def test_cents_other_wordings(text, expect):
    r, notes = _r(text)
    for k, v in expect.items():
        assert r[k] == v, (k, r.get(k))
    _no_false_not_counted(notes, "$42.50", "$125.50", "$87.50", "$29.50", "$25.50")
    assert "not counted anywhere" not in notes


# ---- item 2: "1.5 months" is not a date
@pytest.mark.parametrize("text, deposit", [
    (L7, 3675),
    ("4BR $2,450. Move-in: 1.5 months rent deposit. Lease 12 months.", None),
    ("2BR $1,800. Move in 1.5 x rent total. Lease 12 months.", None),
    ("2BR $1,800. Move-in 2.5 months of rent upfront. Deposit: 1.5 months.", 2700),
    ("2BR $1,800. Move-in: 1/2 month deposit.", None),
    ("2BR $1,800. Move-in: 2 mo rent. Move-in 1.5x rent.", None),
])
def test_months_are_never_a_date(text, deposit):
    r, _notes = _r(text)
    assert "available_from" not in r or r["available_from"] is None
    if deposit is not None:
        assert r["deposit"] == deposit


def test_real_dates_after_move_in_still_read():
    assert _r("2BR $1,800. Move-in: $2,000 deposit. Available 1/5/27.")[0]["available_from"] == "2027-01-05"
    assert _r("2BR $1,800. Move-in 1/5/27, 1.5 months deposit.")[0]["available_from"] == "2027-01-05"
    assert _r("2BR $1,800. Move-in: 6/1/2027 rent $1,800.")[0]["available_from"] == "2027-06-01"


# ---- item 3: a credit check inside the application fee
def test_credit_check_in_fee_has_one_note():
    r, notes = _r(L10)
    assert r["application_fee"] == 80
    assert "two fees" not in notes and "credit check fee" not in notes
    assert "$80 per adult" in notes


@pytest.mark.parametrize("text", [
    "3 bd $2,000. App fee $50/adult plus $30 credit check per adult. Deposit 1 month.",
    "3 bd $2,000/mo\nApplication fee: $50 per adult\nCredit check: $30 per adult\nDeposit 1 month",
    "3 bd $2,000/mo. Application fee $50 each adult and a $30 credit check each adult.",
])
def test_credit_check_in_fee_other_wordings(text):
    r, notes = _r(text)
    assert r["application_fee"] == 80
    assert "two fees" not in notes


def test_credit_check_included_in_fee_wording():
    r, notes = _r("3 bd $2,000/mo. Application fee $80 per adult (includes the $30 credit check). Deposit 1 month.")
    assert r["application_fee"] == 80
    assert "two fees" not in notes
    assert "not counted" not in notes


# ---- item 4: lease options
def test_other_lease_length_rent_is_an_option():
    r, notes = _r(RM62)
    assert r["price"] == 3200
    assert r["lease_months"] == 12
    assert "$3,100 for a 15 month lease" in notes
    _no_false_not_counted(notes, "$3,100")
    assert "not counted anywhere" not in notes.split("$3,100")[1].split("\n")[0]


@pytest.mark.parametrize("text", [
    "2BR 123 Main St Chicago. Rent: $3,200/mo. Lease: 12 months, or 15 months at $3,100.",
    "2BR 123 Main St Chicago\nRent: $3,200 per month\nLease options: 12 months\n- 15 months: $3,100",
])
def test_other_lease_length_other_wordings(text):
    r, notes = _r(text)
    assert r["price"] == 3200
    assert "$3,100" in notes
    assert "$3,100 is not counted" not in notes
    _no_false_not_counted(notes, "$3,100")


def test_cheapest_plan_for_bed_count_and_no_saved_rent_in_note():
    r, notes = _r(NT15)
    assert r["price"] == 1380
    assert "lease_months" not in r or r["lease_months"] is None
    assert "$1,520" in notes and "$1,480" in notes
    assert "is saved" not in notes.split("different rent for each lease length")[1].split("\n")[0]
    _no_false_not_counted(notes, "$1,380", "$1,520", "$1,480")


@pytest.mark.parametrize("text", [
    "Elm Court 2BR/1BA\nFloor plans: 2BR Basic 800 sqft $1,300 | 2BR Plus 900 sqft $1,450 (12 mo) | 2BR Plus 900 sqft $1,400 (18 mo)",
    "Elm Court 2BR/1BA\n2BR Basic $1,300\n2BR Plus $1,450 (12 mo)\n2BR Plus $1,400 (18 mo)",
])
def test_cheapest_plan_other_wordings(text):
    r, notes = _r(text)
    assert r["price"] == 1300
    assert "lease_months" not in r or r["lease_months"] is None
    _no_false_not_counted(notes, "$1,300", "$1,450", "$1,400")


def test_lease_option_note_does_not_name_saved_rent_when_first_option_is_the_rent():
    r, notes = _r("1BR 5 Oak Ave Austin. $1,540 for 12 month lease; 13 month lease $1,490.")
    assert r["price"] == 1540
    assert r["lease_months"] == 12
    assert "is saved" not in notes
    assert "$1,490 for 13 months" in notes


# ---- item 5: corrections
def test_correction_old_price_is_noted_as_old():
    r, notes = _r(RM68)
    assert r["price"] == 3100
    assert "$3,000 is the old price" in notes
    _no_false_not_counted(notes, "$3,000")
    assert 'also says "$3,000"' not in notes


@pytest.mark.parametrize("text, new, old", [
    ("2 bed 1 bath, 220 Oak St, Denver. Rent: $1,700/mo. Deposit 1 month.\nCorrection - rent is $1,725/mo. Please disregard the earlier rent.", 1725, 1700),
    ("2 bed 1 bath, 220 Oak St, Denver\n- Rent: $1,700 per month\n- UPDATE: price corrected to $1,750, disregard the old price", 1750, 1700),
    ("Sunny 1BR at 15 Pine Ave, Austin. $1,450/mo. Edit: new rent $1,495. Ignore previous price.", 1495, 1450),
])
def test_correction_other_wordings(text, new, old):
    r, notes = _r(text)
    assert r["price"] == new
    assert f"${old:,.0f} is the old price" in notes
    _no_false_not_counted(notes, f"${old:,.0f}")
    assert "not counted anywhere" not in notes


def test_conditional_now_price_is_not_a_correction():
    r, notes = _r("2BR 9 Elm St Reno. $1,490/mo, now $1,450 if you sign by Dec 15.")
    assert r["price"] == 1490
    assert "old price" not in notes
