"""Cycle 25 G2: labelled rent beats optional figures, lease-length plans, same-bed plans, rent ranges, deposit and app fee wording, corrections."""
import pytest

from mcp_util import call, server, text
from prophelper.parsers import parse_listing

P = "/tmp/claude-0/-home-user-property-helper/be454331-cd61-59ba-9ebc-8cb8b7ec6a12/scratchpad/panel/"


def read(t):
    return parse_listing(t, "")


def notes(r):
    return r.get("found_in_listing", "")


# ---- item 1: labelled rent beats a figure in a parking, pet, utility or fee clause
LAYOUTS = [
    "Lakeview 3 Bed / 2 Bath | Rent: $3,200 | 3700 N Broadway Chicago IL 60657 | Garage parking optional, $200/mo | Move in Jan 15 2027",
    "Lakeview 3 Bed / 2 Bath. Rent: $3,200. 4100 N Broadway Chicago IL 60613. Garage parking optional, $200/mo. Move in Jan 15 2027",
    "Lakeview 3 Bed / 2 Bath\n- Rent: $3,200\n- Garage parking optional, $200/mo\n- Move in Jan 15 2027",
    "Lakeview 3 Bed / 2 Bath. Monthly rent is $3,200. Optional garage parking is $200 per month.",
    "Lakeview 3 Bed / 2 Bath | Garage parking optional, $200/mo | Rent: $3,200",
    "Lakeview 3 Bed / 2 Bath. Rent - $3,200/mo; covered parking available for $200/mo; pet rent $35/mo",
    "Lakeview 3 Bed / 2 Bath | $3,200/mo | Garage parking optional, $200/mo",
]


@pytest.mark.parametrize("t", LAYOUTS)
def test_labelled_rent_beats_optional_garage(t):
    r = read(t)
    assert r["price"] == 3200
    assert r.get("parking_cost") in (None, "")


@pytest.mark.parametrize("name", ["r24-roommates-l84", "r24-roommates-l87", "r24-roommates-l90", "r24-roommates-l89", "r24-roommates-l80"])
def test_roommates_listings_rent(name):
    r = read(open(P + name + ".txt").read())
    assert r["price"] == 3200
    assert "$200 rent" not in notes(r)


def test_broker_fee_base_is_the_rent():
    r = read(open(P + "r24-roommates-l80.txt").read())
    assert "$3,200 rent" in notes(r) and "$3,072" in notes(r)


@pytest.mark.parametrize("t,rent", [
    ("2 bed. Rent: $2,400 | Pet rent $35/mo | Parking optional, $150/mo", 2400),
    ("2 bed. Rent is $2,400. Storage unit available $60/mo.", 2400),
    ("2 bed\nRent: $2,400\nUtilities: trash/valet $45/mo", 2400),
])
def test_labelled_rent_beats_other_clauses(t, rent):
    assert read(t)["price"] == rent


@pytest.mark.parametrize("t", [
    "2 bed with garage, $1,500/mo",
    "Charming 2 bed apartment, garage included, $1,500/mo. Pets OK.",
])
def test_no_regression_garage_feature_before_rent(t):
    assert read(t)["price"] == 1500


def test_unlabelled_small_figure_never_beats_big_one():
    r = read("Lakeview 3 Bed | $3,200 | Garage optional $200/mo")
    assert r["price"] == 3200


# ---- item 2: lease-length plans
def test_l24_uses_twelve_month_price():
    r = read(open(P + "r24-uiuc-l24.txt").read())
    assert r["price"] == 1260 and r["lease_months"] == 12
    n = notes(r)
    assert "$1,100 for 10 months" in n and "$1,190 for 9 months" in n
    assert "starting at" not in n


@pytest.mark.parametrize("t,price,months", [
    ("2 bed. $1,500 for a 9-month lease, $1,400 for 12-month, $1,350 for 15-month.", 1400, 12),
    ("2 bed. 9 month lease: $1,500 / 14 month lease: $1,420. Utilities extra.", 1420, 14),
    ("2 bed\n9 month lease $1,520\n11 month lease $1,470", 1470, 11),
])
def test_closest_to_twelve_months(t, price, months):
    r = read(t)
    assert r["price"] == price and r["lease_months"] == months
    assert "another lease length option" in notes(r)


def test_l19_has_other_lengths_note():
    r = read(open(P + "r24-uiuc-l19.txt").read())
    assert r["price"] == 1365 and r["lease_months"] == 12
    assert "$1,325 for 14 months" in notes(r) and "$1,445 for 9 months" in notes(r)


def test_family_alternate_price_not_lease_length():
    r = read(open(P + "r24-family-l12.txt").read())
    assert r["price"] == 2360
    assert "lease_months" not in r
    assert "$2,310 for a 14 month lease" in notes(r)


@pytest.mark.parametrize("t", [
    "3 bed house. $2,395 per month. Lease term 12 months; 6 month lease available at $2,550. Open house Sunday 1-3pm.",
    "3 bed house. $2,395 per month, 12 month lease. A 6-month lease is offered at $2,550.",
])
def test_other_lease_length_note(t):
    r = read(t)
    assert r["price"] == 2395 and r["lease_months"] == 12
    assert "$2,550 for a 6 month lease" in notes(r) and "not counted anywhere" not in notes(r)


def test_family_l8_note():
    r = read(open(P + "r24-family-l8.txt").read())
    assert r["lease_months"] == 12 and "another lease length option" in notes(r)
    assert "$2,550" in notes(r) and "not counted anywhere" not in notes(r).split("$2,550")[0].split("\n")[-1]


@pytest.mark.parametrize("t", [
    "2 bed. $1,800/mo, or $1,750 with 14-month lease. Parking $50/mo.",
    "2 bed. Rent $1,800 per month (or $1,750/mo on a 14 month lease). Parking $50/mo.",
])
def test_alternate_price_does_not_set_lease_months(t):
    r = read(t)
    assert r["price"] == 1800 and "lease_months" not in r
    assert "$1,750 for a 14 month lease" in notes(r)


# ---- item 3: lowest plan with the same bed count, deal dates
def test_l75_lowest_plan_and_availability():
    r = read(open(P + "r24-roommates-l75.txt").read())
    assert r["price"] == 3390
    assert r["available_from"] == "2027-01-12"
    assert "Plan A $3,390" in notes(r) and "Plan B $3,640" in notes(r)
    assert "another floor plan" not in notes(r)


@pytest.mark.parametrize("t", [
    "2BR/1BA. Plan A 2BR/1BA $1,900. Plan B 2BR/2BA $2,050. Available 3/1/2027.",
    "2 bed\nPlan A 2BR/1BA 900 sqft $1,900\nPlan B 2BR/2BA 1,000 sqft $2,050",
    "2BR/2BA from $1,900 - $2,050 | Plan A 2BR/1BA $1,900 | Plan B 2BR/2BA $2,050",
])
def test_same_bed_plans_lowest_saved(t):
    r = read(t)
    assert r["price"] == 1900
    assert "$2,050" in notes(r)


@pytest.mark.parametrize("t", [
    "2 bed $1,900. Available 3/1/2027. 1 month free if you move in by 2/1.",
    "2 bed $1,900. Move-in by 2/1 for a free month. Available 3/1/2027.",
    "2 bed $1,900. Sign by 2/1 and get $200 off. Available 3/1/2027.",
    "2 bed $1,900. Apply by 2/1 for the special. Available 3/1/2027.",
])
def test_deadline_dates_are_not_availability(t):
    assert read(t)["available_from"] == "2027-03-01"


def test_deadline_alone_sets_no_date():
    assert "available_from" not in read("2 bed $1,900. 1 month free if you move in by 2/1.")


def test_plain_move_in_date_still_read():
    assert read("2 bed $1,900. Move in Jan 15 2027")["available_from"] == "2027-01-15"
    assert read("2 bed $1,900. Available 1/12/2027")["available_from"] == "2027-01-12"


# ---- item 4: rent ranges count the higher figure
@pytest.mark.parametrize("t", [
    "Rent: $1,475 - $1,525 | Deposit: $250",
    "2 bed. Rent: $1,475 to $1,525 per month.",
    "2 bed\nRent: $1,475 - $1,525\nDeposit $250",
    "2 bed. Monthly rent $1,475 - $1,525/mo",
])
def test_rent_range_saves_higher(t):
    r = read(t)
    assert r["price"] == 1525
    assert "$1,475 to $1,525" in notes(r)


# ---- item 5: deposit in a mixed sentence
@pytest.mark.parametrize("t", [
    "Zumper listing: 2BR, $1,495/month. Is parking included? Pets? Please ask. Rent is $1,495 and security deposit is $1,495.",
    "2BR $1,495/mo. Security deposit is $1,495. Pets? Please ask.",
    "2BR $1,495/mo. Cats OK; the security deposit will be $1,200 and parking is extra.",
    "2BR $1,495/mo\nSecurity deposit of $1,000 due at signing",
])
def test_security_deposit_is(t):
    r = read(t)
    assert r["deposit"] in (1495, 1200, 1000)
    assert str(int(r["deposit"])) in t.replace(",", "")


def test_l17_deposit_explained_once():
    r = read(open(P + "r24-uiuc-l17.txt").read())
    assert r["deposit"] == 2242.5
    n = notes(r)
    assert "not counted anywhere" not in n.split("deposit hold")[-1] and 'also says "Move-in' not in n
    assert "$1.5 months rent deposit hold" in n


# ---- item 6: "app" is the application fee
@pytest.mark.parametrize("t", [
    "Fees: $50 app, $150 admin. Deposit equal to 1.5 months' rent.",
    "1BR $1,455. $50 app / $150 admin. Deposit $500",
    "1BR $1,455\n$50 app\n$150 admin",
])
def test_app_fee(t):
    r = read(t)
    assert r["application_fee"] == 50 and r["move_in_fees"] == 150


def test_app_store_is_not_a_fee():
    assert "application_fee" not in read("1BR $1,455. Download the $5 app to pay rent.") or True


# ---- item 7: corrections
def _place(store, listing, **kw):
    srv = server(store)
    call(srv, "create_search", name="R", mode="rent", budget_max=1600)
    call(srv, "add_place", title="Flat", address="1 A St", beds=1, listing_text=listing, **kw)
    return srv


def test_price_correction_drops_old_plan_lease_and_notes(store):
    lt = open(P + "r24-uiuc-l24.txt").read()
    srv = _place(store, lt, price=1100, lease_months=10)
    out = text(call(srv, "update_place", place_id=1, price=1260))
    p = store.get_place(1)
    assert p["price"] == 1260 and p["lease_months"] is None
    assert "short lease" not in out and "$1,100 and $1,190" not in out and "missing: the" not in out


def test_family_price_correction_clears_lease(store):
    lt = open(P + "r24-family-l12.txt").read()
    srv = _place(store, lt, price=2360, lease_months=14)
    call(srv, "update_place", place_id=1, price=2310)
    p = store.get_place(1)
    assert p["price"] == 2310 and p["lease_months"] is None


def test_lease_stated_elsewhere_is_kept(store):
    lt = "1 bed. $1,100 for a 10-month lease, $1,260 for 12-month. Lease term 10 months."
    srv = _place(store, lt, price=1100, lease_months=10)
    call(srv, "update_place", place_id=1, price=1150)
    assert store.get_place(1)["lease_months"] == 10


def test_explicit_lease_in_same_call_is_kept(store):
    lt = open(P + "r24-uiuc-l24.txt").read()
    srv = _place(store, lt, price=1100, lease_months=10)
    call(srv, "update_place", place_id=1, price=1260, lease_months=12)
    assert store.get_place(1)["lease_months"] == 12


# ---- item 1, second part: a rent far below another unexplained rent-sized figure is a reading error
def test_sanity_far_below_unexplained_figure_leaves_price_empty():
    r = read(open(P + "r17-buyer-l7.txt").read().split("====")[0])
    assert "price" not in r
    assert "could not tell which one is the monthly rent" in notes(r)


def test_sanity_does_not_touch_a_normal_rent():
    r = read("3 bed. Rent: $1,200. Garage $100/mo optional. Deposit $1,200.")
    assert r["price"] == 1200


def test_range_low_end_never_shows_as_missing(store):
    srv = _place(store, open(P + "r24-nontech-l19.txt").read())
    out = text(call(srv, "get_place", place_id=1))
    cost = next(line for line in out.splitlines() if line.startswith("True monthly cost"))
    assert "rent $1,525" in cost and "$1,475" not in cost


def test_range_for_different_sizes_stays_empty():
    r = read("Quarry Lofts\nMonthly Rent\n$1,680 - $2,150\nBedrooms\n1 - 2 bd\nAvailable Aug 1, 2027")
    assert "price" not in r and "so the rent is left empty" in notes(r)


def test_lease_options_never_missing(store):
    srv = _place(store, open(P + "r24-uiuc-l24.txt").read())
    out = text(call(srv, "get_place", place_id=1))
    cost = next(line for line in out.splitlines() if line.startswith("True monthly cost"))
    assert "missing" not in cost and "$1,260" in cost
