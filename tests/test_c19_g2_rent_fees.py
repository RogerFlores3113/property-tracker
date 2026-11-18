"""Cycle 19 G2: price drop with an arrow, a rent that is corrected, a header price after fused beds and baths, bulleted fee lists,
application fee wording, conditional and multiple deposits, move-in admin, and penalty fees."""
import pytest

from prophelper.parsers import parse_listing


def notes(r):
    return r.get("found_in_listing", "")


# ---- 1. price drop
@pytest.mark.parametrize("text", [
    "Sunny 2 bed 1 bath apartment. $1,350 -> now $1,290 (price drop!) Pets ok. 12 Oak Ave",
    "Sunny 2 bed 1 bath apartment. $1,350 → $1,290. Call us.",
    "Sunny 2 bed 1 bath apartment. was $1,350, now $1,290. Call us.",
    "Sunny 2 bed 1 bath apartment.\n$1,350 => now $1,290\nCall us.",
])
def test_price_drop_new_price_wins(text):
    r = parse_listing(text)
    assert r["price"] == 1290
    assert "not counted anywhere" not in notes(r)


# ---- 2. correction after a wrong first number
@pytest.mark.parametrize("text", [
    "Rent 1,480 per bedroom? No: Pilsen 3bd/2ba rent 3,240. Deposit same as rent.",
    "Rent 1,480 per bedroom, sorry actually Pilsen 3bd/2ba rent 3,240. Deposit same as rent.",
    "Rent 1,480 per bedroom.\nActually no, the whole 3bd/2ba rent is 3,240.\nDeposit same as rent.",
])
def test_corrected_rent_and_deposit(text):
    r = parse_listing(text)
    assert r["price"] == 3240
    assert r["deposit"] == 3240


def test_per_bedroom_never_saved_as_whole_rent():
    r = parse_listing("Rent: 1,480 per bedroom. 3bd/2ba. Deposit one month.")
    assert r.get("price") is None and r.get("deposit") is None
    assert "1,480 per bedroom" in notes(r)


@pytest.mark.parametrize("text", [
    "1.5k a month, no sorry 2,350. 2 bed 1 bath.",
    "Rent: 1.5k a month?? no sorry 2,350 a month. 3bd house.",
    "$1,500/mo? actually $1,650/mo. 2 bed 1 bath.",
])
def test_self_correcting_rent(text):
    r = parse_listing(text)
    assert r["price"] in (2350, 1650)
    assert "corrects itself" in notes(r) or "2,350" in notes(r)


def test_no_deposit_amount_is_not_a_correction():
    r = parse_listing("2 bed 1 bath $1,500/mo, no 1,000 deposit needed.")
    assert r["price"] == 1500


# ---- 3. header price after fused beds and baths
@pytest.mark.parametrize("text", [
    "Logan Square 3BR2BA $3,250.",
    "Logan Square 3bd/2ba - $3,250",
    "Logan Square 3 BR | 2 BA | $3,250/mo",
    "Logan Square 3BR/2BA $3,250 Available now",
])
def test_header_price_after_beds_baths(text):
    r = parse_listing(text)
    assert r["price"] == 3250
    assert "not counted anywhere" not in notes(r)


def test_street_number_is_not_rent():
    r = parse_listing("1234 Logan Blvd 3BR2BA")
    assert r.get("price") is None
    r = parse_listing("3BR2BA 4120 Indianola Ave Columbus OH")
    assert r.get("price") is None


# ---- 4. bulleted fee lists
@pytest.mark.parametrize("text", [
    "Nice place 2 bed 1 bath $1,500/mo\n* Pest control $8, locker $10, valet trash $15\n",
    "Nice place 2 bed 1 bath $1,500/mo\n* Pest control $8\n* Locker $10\n* Valet trash $15\n",
    "Nice place 2 bed 1 bath $1,500/mo\nFees: pest control $8, locker $10 and valet trash $15 monthly\n",
])
def test_bulleted_fee_list_counts_every_item(text):
    r = parse_listing(text)
    assert r["other_monthly_fees"] == 33
    assert "not counted anywhere" not in notes(r)


def test_nontech_l4_shape():
    r = parse_listing("Cozy duplex in Hilltop! 2 bedrooms, 1 bath. 1.5k a month.\n* Gas heat - tenant pays about $40/mo\n* Trash & sewer: $65 monthly\n* Internet $50\n"
                      "* Pest control $8, locker $10, valet trash $15 (monthly)\nApplication fee $45 per adult. 2210 W Broad St.")
    assert r["other_monthly_fees"] == 33
    n = notes(r)
    assert not ("Internet $50" in n and "not counted anywhere" in n)
    assert "locker" in n.lower()


def test_lone_optional_locker_is_still_storage():
    r = parse_listing("2 bed 1 bath $1,500/mo. Storage locker $30/mo optional.")
    assert not r.get("other_monthly_fees")


# ---- 5. application fee wording
@pytest.mark.parametrize("text, fee", [
    ("2 bed 1 bath $1,500/mo. Application $40 each.", 40),
    ("2 bed 1 bath $1,500/mo. Apply: $55 per person", 55),
    ("2 bed 1 bath $1,500/mo.\n- Application fee: $35 each adult", 35),
])
def test_application_fee_per_adult(text, fee):
    r = parse_listing(text)
    assert r["application_fee"] == fee
    assert r["application_fee_per_adult"] == 1
    assert "not counted anywhere" not in notes(r)


# ---- 6. deposits
@pytest.mark.parametrize("text, dep", [
    ("2 bed 1 bath $2,000/mo. Security deposit 1.5x rent", 3000),
    ("2 bed 1 bath $2,000/mo. Security deposit: 1.5 x the rent", 3000),
    ("2 bed 1 bath $2,000/mo\n* Security deposit 1.5x rent", 3000),
])
def test_deposit_multiple_of_rent(text, dep):
    assert parse_listing(text)["deposit"] == dep


def test_deposit_multiple_without_rent_is_noted():
    r = parse_listing("2 bed 1 bath. Security deposit 1.5x rent")
    assert r.get("deposit") is None
    assert "1.5 months of rent" in notes(r)


@pytest.mark.parametrize("text", [
    "2 bed 1 bath $2,350/mo. Deposit $2,350 conditional on credit approval",
    "2 bed 1 bath $2,350/mo. Deposit: one month rent (conditional on credit approval)",
    "2 bed 1 bath $2,350/mo.\n* Security deposit $2,350, contingent on credit approval",
])
def test_conditional_deposit_kept_with_note(text):
    r = parse_listing(text)
    assert r["deposit"] == 2350
    assert "depends on credit approval" in notes(r)


# ---- 7. move-in admin
@pytest.mark.parametrize("text", [
    "2 bed 1 bath $1,500/mo. Move-in specials: $99 admin",
    "2 bed 1 bath $1,500/mo.\n* Move-in specials: $99 admin\n",
    "2 bed 1 bath $1,500/mo. Specials: $99 admin and no deposit offer.",
])
def test_move_in_special_admin_is_counted(text):
    r = parse_listing(text)
    assert r["move_in_fees"] == 99
    assert "not counted anywhere" not in notes(r)


# ---- 8. penalty fees
@pytest.mark.parametrize("text", [
    "2 bed 1 bath $1,500/mo. $75 late fee. Deposit $1,500.",
    "2 bed 1 bath $1,500/mo.\n* Late fee: $75\n* Returned check fee $35\n",
    "2 bed 1 bath $1,500/mo. Rent due on the 1st, $75 late fee after the 5th, NSF fee $30.",
])
def test_penalty_fees_one_plain_note(text):
    r = parse_listing(text)
    n = notes(r)
    assert "$75" in n and "not in the monthly cost" in n
    assert "not counted anywhere" not in n and "Check what it is for" not in n
    assert n.count("late fee") == 1
