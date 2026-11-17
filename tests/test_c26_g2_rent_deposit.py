"""Cycle 26 G2: corrections name a fact, specials, extra-space figures, narrow ranges, deposits, and the correction path in update_place."""
import pytest

from mcp_util import call, server, text
from prophelper.parsers import parse_listing

P = "/tmp/claude-0/-home-user-property-helper/be454331-cd61-59ba-9ebc-8cb8b7ec6a12/scratchpad/panel/"


def read(t):
    return parse_listing(t, "")


def notes(r):
    return r.get("found_in_listing", "")


# ---- item 1: a correction line replaces the fact it names
@pytest.mark.parametrize("t", [
    "NEW: Hyde Park 3 BR 2 BA | 5500 S Blackstone Ave 60637 | $3,100 mo | Lease 12 months | Corrected: earlier listing said 2 BA, it is 1.5 BA.",
    "3 bed 2 bath, $3,100 a month. 5500 S Blackstone Ave. UPDATE: now 1.5 bath (was 2).",
    "3 bed 2 bath, $3,100 a month. 5500 S Blackstone Ave.\nCorrection: it has 1.5 bathrooms, not 2.",
])
def test_baths_correction(t):
    r = read(t)
    assert r["baths"] == 1.5 and r["price"] == 3100 and r["beds"] == 3
    assert "corrects itself about the bathroom count" in notes(r)


def test_baths_corrected_file():
    r = read(open(P + "r25-roommates-l18.txt").read())
    assert r["baths"] == 1.5 and r["price"] == 3100


def test_now_without_a_fact_is_no_correction():
    r = read("Now leasing! 3 bed 2 bath, $3,100 a month.")
    assert r["baths"] == 2 and r["beds"] == 3 and "corrects" not in notes(r)


@pytest.mark.parametrize("t", [
    "3 bed 2 bath, $3,100 a month. Security deposit $1,000. Edit: deposit is now $800.",
    "3 bed 2 bath, $3,100 a month. Deposit $1,000.\nUpdate: the deposit is $800 now.",
    "3 bed 2 bath, $3,100 a month. Deposit: $1,000 | Corrected: security deposit $800 (earlier ad said $1,000).",
])
def test_deposit_correction(t):
    r = read(t)
    assert r["deposit"] == 800 and "$1,000" in notes(r) and "$800" not in notes(r)


def test_beds_and_date_correction():
    r = read("3 bed 2 bath, $3,100 a month. Update: it is a 2 bedroom, not 3.")
    assert r["beds"] == 2
    r = read("3 bed 2 bath, $3,100 a month. Available Jan 15 2027. Update: available date is now Feb 1 2027 (was Jan 15).")
    assert r["available_from"] == "2027-02-01" and "Jan 15, 2027" in notes(r)
    r = read("3 bed 2 bath, $3,100 a month. Avail 1/15/27 | Corrected: move-in is 2/1/27")
    assert r["available_from"] == "2027-02-01"


@pytest.mark.parametrize("t", [
    "Wicker Park | 3 bedroom 2 bath | $3,400 | Update: price corrected, rent is now $3,250 (earlier ad said $3,400).",
    "3 bed 2 bath. Updated: the rent is now $3,250 per month, the earlier listing said $3,400. Pets ok.",
])
def test_rent_correction_names_old_price(t):
    r = read(t)
    assert r["price"] == 3250 and "$3,400" in notes(r) and "not used" in notes(r)


# ---- item 2: specials
@pytest.mark.parametrize("t,special,rent", [
    ("HYDE PARK 3BR/2BA $3,600/MO $3,000 IF YOU SIGN BY DEC 1 (SPECIAL) 5400 S Dorchester Ave Chicago IL 60615. Deposit $1,000.", "$3,000", 3600),
    ("2 bed 1 bath $1,500/mo. Limited time: $1,350/mo for leases signed by 12/15. Pets ok", "$1,350", 1500),
    ("Special: $2,950 if you sign by Dec 1, regularly $3,100/mo. 3bd 2ba", "$2,950", 3100),
    ("Lincoln Park 2BR/1BA $2,800/mo. Promo $2,600 a month when you sign by Nov 30.", "$2,600", 2800),
])
def test_special_keeps_regular_rent(t, special, rent):
    r = read(t)
    assert r["price"] == rent
    assert special in notes(r) and "another floor plan" not in notes(r)


def test_special_file_one_short_note():
    r = read(open(P + "r25-roommates-l6.txt").read())
    assert r["price"] == 3600 and r["deposit"] == 1000
    assert "special" in notes(r) and "Dec 1" in notes(r) and "another floor plan" not in notes(r)


# ---- item 3: extra-space figures are never the rent
@pytest.mark.parametrize("t", [
    "Lincoln Park 3 BED 2 BATH $3,350 + utilities. 2330 N Clark St, Chicago, IL 60614. Second space $200/mo. Fee $60 per adult application.",
    "Lincoln Park 3 BED 2 BATH $3,350 + utilities.\nExtra storage $200/mo\nAdditional parking space $200/mo",
    "Lincoln Park 3 BED 2 BATH | $3,350 + utilities | Second space $200/mo | Laundry in unit",
])
def test_second_space_is_not_rent(t):
    r = read(t)
    assert r["price"] == 3350 and "could not tell which" not in notes(r)


def test_l15_still_works():
    assert read(open(P + "r25-roommates-l15.txt").read())["price"] == 3350
    assert read(open(P + "r25-roommates-l20.txt").read())["price"] == 3350


# ---- item 4: narrow ranges save the higher figure
@pytest.mark.parametrize("t,high", [
    ("West Loop 3bd 2ba 1,350 sqft. Rent starting at $3,500 - $3,650. 900 W Randolph St 60607.", 3650),
    ("Olentangy Commons\n2 Bedroom 2 Bath, 1,000 sq ft, from $1,399 - $1,449\nLease terms: 12 months.", 1449),
    ("1BR/1BA $1,525-$1,575 depending on floor. Savoy IL.", 1575),
    ("Studio rent ranges $1,000 - $1,090 a month", 1090),
])
def test_narrow_range_high(t, high):
    r = read(t)
    assert r["price"] == high and "rent range" in notes(r)


def test_wide_range_stays_empty():
    r = read("2 bed 2 bath. Rent from $1,299 - $1,650 / mo")
    assert "price" not in r and "rent is left empty" in notes(r)


# ---- item 5: deposits
@pytest.mark.parametrize("t,dep", [
    ("2 bed loft $1,380/mo. Security deposit due at signing: $1,490. Credit check fee $35.", 1490),
    ("Italian Village 2 bed loft - $1,380 / mo\nSec dep is $690 (half month). Trash is $12/mo.", 690),
    ("2 bed loft $1,380/mo. Sec. dep. $690. Pets ok.", 690),
    ("2 bed loft $1,380/mo. Deposit required at lease signing: $700.", 700),
])
def test_deposit_wordings(t, dep):
    assert read(t)["deposit"] == dep


def test_deposit_months_filled_with_note():
    r = read(open(P + "r25-roommates-l11.txt").read())
    assert r["price"] == 2950 and r["deposit"] == 4425 and "1.5 months of rent" in notes(r)
    r = read("2 bed 1 bath $1,200/mo. Deposit 1.5 months. Open house Saturday. Tenant pays electric.")
    assert r["deposit"] == 1800


def test_deposit_or_fee():
    r = read(open(P + "r25-roommates-l7.txt").read())
    assert r["deposit"] == 1000 and "move_in_fees" not in r
    assert "two ways to pay" in notes(r)
    r = read("River North 3BR/2BA $3,299/mo. Security deposit $1,000 or a $450 non-refundable fee. Tenant pays utilities.")
    assert r["deposit"] == 1000 and "move_in_fees" not in r


def test_deposit_whichever_greater():
    r = read(open(P + "r25-nontech-l27.txt").read())
    assert r["deposit"] == 1086.75


# ---- item 6: a deposit in a pet or other named clause is never the security deposit
@pytest.mark.parametrize("t", [
    "Eichler 3/2, $2,340 a month. Pets: dogs OK up to 75 lb, pet rent not charged, $300 refundable deposit. Deposit 1 month.",
    "Eichler 3/2, $2,340 a month. Deposit 1 month. Pets: dogs OK, pet rent not charged, $300 refundable deposit.",
    "Eichler 3/2, $2,340 a month.\nDogs welcome (pet rent $0, $300 refundable deposit)\nSecurity deposit 1 month",
])
def test_pet_deposit_is_not_security_deposit(t):
    assert read(t)["deposit"] == 2340


def test_key_and_parking_deposit_not_security():
    r = read("2 bed. $1,400/mo. Parking deposit $100. Security deposit $1,400")
    assert r["deposit"] == 1400


# ---- item 7: update_place clears notes about the old rent
def _place(store, listing, **kw):
    srv = server(store)
    call(srv, "create_search", name="R", mode="rent", budget_max=3000)
    call(srv, "add_place", title="Flat", address="1 A St", beds=1, listing_text=listing, **kw)
    return srv


def test_update_clears_price_cut_note(store):
    srv = _place(store, open(P + "r25-family-l19.txt").read(), price=2360)
    assert "price was cut" in store.get_place(1)["reader_notes"]
    call(srv, "update_place", place_id=1, price=2310)
    p = store.get_place(1)
    assert p["price"] == 2310 and "price was cut" not in p["reader_notes"] and "old price" not in p["reader_notes"]


def test_update_clears_lease_plan_note(store):
    srv = _place(store, open(P + "r25-uiuc-l19.txt").read(), price=1365)
    call(srv, "update_place", place_id=1, price=1395)
    p = store.get_place(1)
    assert p["price"] == 1395 and "is used for the rent" not in p["reader_notes"]


def test_update_clears_special_and_range_notes(store):
    srv = _place(store, open(P + "r25-roommates-l6.txt").read(), price=3600)
    assert "special" in store.get_place(1)["reader_notes"]
    call(srv, "update_place", place_id=1, price=3400)
    assert "regular rent, $3,600" not in store.get_place(1)["reader_notes"]


def test_update_same_price_keeps_notes(store):
    srv = _place(store, open(P + "r25-family-l19.txt").read(), price=2360)
    call(srv, "update_place", place_id=1, price=2360)
    assert "price was cut" in store.get_place(1)["reader_notes"]


@pytest.mark.parametrize("t", [
    "Room in 3 bedroom house $650/month utilities not included deposit $650 no pets driveway parking available",
    "Room $650/month. Deposit $650, no pets, key pickup at noon.",
])
def test_pet_words_after_the_deposit_do_not_blank_it(t):
    assert read(t)["deposit"] == 650


def test_rent_discount_is_not_a_special():
    r = read("Wicker Park penthouse 3/2 - $3,300. Security deposit $3,300. Rent specials: $500 off first month.")
    assert r["price"] == 3300 and "has a special" not in notes(r)


def test_special_assessment_is_not_a_special():
    r = read("Condo for rent $2,100 a month. A special assessment of $2,000 a month is paid by the owner.")
    assert "has a special" not in notes(r)
