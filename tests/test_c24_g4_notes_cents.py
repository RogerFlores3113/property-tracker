"""Cycle 24 G4: cents in the guard and the display, figures the listing explains as not a cost stay out of the missing list, one-time amounts stay
out of the monthly headline, the Compare "Not counted yet" row agrees with the cost rows, addresses and titles, money spellings."""
from __future__ import annotations

import pytest

from prophelper import compare, dropguard, enrich, money
from prophelper import parsers as P


def _cost(text: str, mode: str = "rent", **extra):
    r = P.parse_listing(text, "")
    r.update(extra)
    place = dict(r, reader_notes=r.get("found_in_listing"), listing_text=text)
    return r, money.true_monthly_cost(place, mode)


def _enriched(text: str, mode: str = "rent"):
    r, c = _cost(text, mode)
    return dict(r, reader_notes=r.get("found_in_listing"), listing_text=text, cost=c, score={"unknown": []})


def _notes(r) -> list[str]:
    return str(r.get("found_in_listing") or "").split("\n")


# ---- 1. cents end to end
def test_guard_places_a_figure_with_cents_only_when_the_field_holds_the_cents():
    t = "Rent $1,700. Locker $12. Amenity fee $35 a month. Trash $8.50 monthly."
    assert dropguard.find_unplaced(t, {"price": 1700, "other_monthly_fees": 55.5}, "") == []
    assert dropguard.overcounted(t, {"price": 1700, "other_monthly_fees": 55.5}) == []
    # an $8 cut from $8.50 is a sum no combination of the listing's figures adds up to
    assert dropguard.overcounted(t, {"price": 1700, "other_monthly_fees": 55}) == ["other_monthly_fees 55: no combination of the listing's figures adds up to it"]


@pytest.mark.parametrize("text,field,value", [
    ("Rent $1,700. Application fee $42.50 per adult.", "application_fee", 42.5),
    ("Rent $1,700. Application fee: $42.50 each applicant.", "application_fee", 42.5),
    ("Rent $1,700.\nApplication fee\n$42.50 per adult", "application_fee", 42.5),
])
def test_guard_application_fee_cents(text, field, value):
    assert dropguard.find_unplaced(text, {"price": 1700, field: value}, "") == []
    assert [h["amount"] for h in dropguard.find_unplaced(text, {"price": 1700, field: int(value)}, "")] == [value]


def test_cents_shown_as_given():
    assert money.exact_dollars(42.5) == "$42.50"
    assert money.exact_dollars(42) == "$42"
    assert money.exact_dollars(1200.0) == "$1,200"
    assert money.exact_dollars(8.05) == "$8.05"


def test_rent_cost_keeps_cents_in_sums_and_detail():
    place = {"price": 1700, "application_fee": 42.5, "application_fee_per_adult": 1, "other_monthly_fees": 8.5, "pet_rent": 0,
             "parking_cost": 0, "parking": "street", "deposit": 1700, "utilities_included": "all"}
    c = money.true_monthly_cost(place, "rent", people=2, adults=2)
    other = next(l for l in c["lines"] if l["key"] == "other")
    assert other["amount"] == 8.5
    one = next(l for l in c["lines"] if l["key"] == "one_time")
    assert "application fee $85 ($42.50 each for 2 adults)" in one["note"]
    assert c["one_time_total"] == 85.0


# ---- 2. figures the notes explain as not a cost stay out of "missing"
UIUC = ("Campustown Collective | Efficiency/1 Bed | Starting at $1,250\nFloor plans: A1 1BR/1BA 640 sf $1,395; A2 1BR/1BA 702 sf $1,445\n"
        "611 E Green St, Champaign, IL 61820.\nUtilities: Flat utility package $85/mo (water, sewer, trash, internet). Electric separate, around $40.\n"
        "Application fee $50 (non-refundable). Admin fee $100. Deposit: $300 or Surety Bond ($35/mo).\nNo pets.")
FAMILY = ("Cute 3/1.5 duplex, 55 Birch Ave, San Mateo. $2,200/mo. Electric: tenant. Gas: tenant. Deposit $2,200.\n"
          "Floor plans: 3BR/1.5BA 1,100 sf $2,200; 3BR/2BA 1,250 sf $2,380 (12 month lease).")
ROOMMATES = ("Uptown 3 bedroom 2 bath | 4600 N Sheridan Rd Chicago IL 60640 | $3,000 | 6k in concessions, 1 month free on 13-month lease | "
             "All utilities included except internet | no parking | Deposit 1 month\nCORRECTION: rent is now $3,100, ignore earlier price.")
LEASE_OPTION = ("Lakeview 2 bed 1 bath, 700 W Belmont Ave, Chicago IL 60657. Rent $2,900. Lease: 12 months (or 15 months at $3,100). "
                "Electric and gas paid by tenant.")


@pytest.mark.parametrize("text,amounts,mark", [
    (UIUC, ("$1,250", "$1,445", "$35"), "not a cost on top of the rent"),
    (FAMILY, ("$2,380",), "not a cost on top of the rent"),
    (ROOMMATES, ("$3,000",), "is the old price and is not used"),  # cycle 24 join: the rent-correction note of G2
    (LEASE_OPTION, ("$3,100",), "another lease length option"),  # cycle 24 join: the lease-option note of G2
])
def test_explained_figures_are_not_missing(text, amounts, mark):
    r, c = _cost(text)
    p = _enriched(text)
    for a in amounts:
        assert a not in c["headline"], c["headline"]
        assert a not in compare._not_counted_text(p)
        assert a not in " ".join(compare.cost_unknowns(p))
    assert "amount" not in c["headline"] and "listing notes" not in c["headline"]
    assert "listing_notes_label" not in c  # no open money note is left
    assert any(mark in n for n in _notes(r)) or "starting at" in " ".join(_notes(r))  # the note stays


def test_notes_say_what_the_figure_is():
    ns = "\n".join(_notes(P.parse_listing(UIUC, "")))
    assert 'The listing also says "Deposit: $300 or Surety Bond ($35/mo)". It looks like an alternative to the deposit, not a cost on top of the rent.' in ns
    ns = "\n".join(_notes(P.parse_listing(FAMILY, "")))
    assert '"3BR/2BA 1,250 sf $2,380 (12 month lease)". It looks like the price of another floor plan or a starting price' in ns
    ns = "\n".join(_notes(P.parse_listing(ROOMMATES, "")))
    assert 'It first said $3,000 and then says $3,100, so the $3,000 is the old price and is not used.' in ns
    ns = "\n".join(_notes(P.parse_listing(LEASE_OPTION, "")))
    assert 'The listing also gives $3,100 for a 15 month lease. That is another lease length option, so it is not added to the cost.' in ns


def test_other_wordings_of_the_same_figures():
    # a plan list in other layouts
    t = "Maple Court\nStudio $1,100\n1 Bed $1,395\n2 Bed $1,800\nRent for this unit: $1,395. Electric: tenant."
    r, c = _cost(t)
    assert r["price"] == 1395
    assert "$1,800" not in c["headline"] and "$1,100" not in c["headline"]
    # a bond instead of a deposit
    t = "Rent $1,500. Security deposit $1,500, or choose a deposit-free option with a surety bond at $30/mo."
    r, c = _cost(t)
    assert "$30" not in c["headline"]
    # a price the listing takes back
    t = "Rent $1,800.\nUPDATE: ignore the old price, rent is now $1,750."
    r, c = _cost(t)
    assert r["price"] == 1750 and "$1,800" not in c["headline"] and "$1,750 is the old price" not in "\n".join(_notes(r))  # the new rent is never called the old one


def test_a_real_missing_cost_is_still_named():
    t = "Rent $1,500. Gym fee $44 monthly. Starting at $1,200 for studios."
    r, c = _cost(t)
    assert "$44" in c["headline"]
    assert "$1,200" not in c["headline"]


# ---- 3. one-time amounts stay out of the monthly headline
BUYER = ("Weinland Park Townhome Condo | $318,500\n88 E 5th Ave Unit 12, Columbus, OH 43201\n"
         "2 bed, 2.5 bath, 1,320 sqft. Common charges: $1,020 per quarter. Real estate taxes ran $4,210 in 2025. Insurance (HO-6) approx $55 a month. "
         "Seller concession of 2% toward buyer's costs. Lender and title fees run roughly $7,400. ")


@pytest.mark.parametrize("fees", ["Lender and title fees run roughly $7,400.", "Title and lender fees about $7,400.", "Closing fees run about $7,400."])
def test_one_time_amounts_are_not_in_the_monthly_headline(fees):
    t = BUYER.replace("Lender and title fees run roughly $7,400. ", fees)
    r, c = _cost(t, "buy")
    assert "7,400" not in c["headline"] and "listing notes" not in c["headline"]
    assert "amount" not in c["headline"]


def test_one_time_amount_still_has_its_note():
    r, c = _cost(BUYER, "buy")
    assert r.get("closing_costs") == 7400 and "saved as $7,400" in "\n".join(_notes(r))  # cycle 24 join: G6 reads the single closing figure into closing costs


# ---- 4. Compare: Not counted yet agrees with the cost rows
def test_not_counted_row_names_cost_rows_that_read_not_known():
    t = ("Newly renovated 2 Bed / 1 Bath Duplex - Linden - $1,350 a month\nHeat and hot water paid by landlord. Tenant is responsible for electric, "
         "billed every two months (about $90 per bill).\nSecurity deposit equals 1 month. Application fee $30.\n12 month lease.")
    p = _enriched(t)
    assert p.get("other_monthly_fees") is None
    assert "other monthly fees" in compare._not_counted_text(p)


def test_compare_rows_agree_for_a_place_with_no_other_fees_filled(store):
    s = store.add_search("Cats", "rent")
    store.set_current_search(s["id"])
    a, _ = store.add_place(search_id=s["id"], title="Linden", address="1 Linden St", price=1350, deposit=1350, utilities_included="all", parking="street", parking_cost=0, pet_rent=0)
    b, _ = store.add_place(search_id=s["id"], title="Grove", address="2 Grove St", price=1400, deposit=1400, utilities_included="all", parking="street", parking_cost=0, pet_rent=0, other_monthly_fees=20)
    es = enrich.enrich_places(store, s, [store.get_place(a["id"]), store.get_place(b["id"])])
    rows = {r["key"]: r for sec in compare.build_rows(es) for r in sec["rows"]}
    assert "Not known" in rows["cost-other"]["cells"][0]["text"]
    assert "other monthly fees" in rows["missing"]["cells"][0]["text"]
    assert rows["missing"]["cells"][1]["text"] == "Nothing unknown"


def test_not_counted_row_is_nothing_unknown_when_every_row_is_filled():
    place = {"price": 1500, "deposit": 1500, "parking": "street", "parking_cost": 0, "pet_rent": 0, "other_monthly_fees": 0,
             "utilities_included": "all", "pets": "none", "application_fee": 0, "move_in_fees": 0}
    c = money.true_monthly_cost(place, "rent")
    assert compare._not_counted_text(dict(place, cost=c, score={"unknown": []})) == "Nothing unknown"


def test_not_counted_row_names_parking_when_the_parking_row_is_not_known():
    t = "Reynoldsburg 2 bedroom apartment - $1,340/mo. Heat, water, sewer included. Tenant pays electric only (about $55/month). Utility package fee $20 per month mandatory."
    p = _enriched(t)
    assert "parking" in compare._not_counted_text(p)


# ---- 5. addresses and titles
@pytest.mark.parametrize("text,addr,unit", [
    ("Easton Condo for sale - $329,000\n4100 Easton Sq Pl #310, Columbus, OH 43219\n2 BR", "4100 Easton Sq Pl", "310"),
    ("Union Place, 900 Union Sq Pl Apt 4, Columbus, OH 43215. Rent $1,500", "900 Union Sq Pl", "4"),
    ("Cozy house. Lot 4, 55 Maple Ct Dr, Columbus, OH 43201. Rent $1,500", "55 Maple Ct Dr", None),
    ("12 Park Ln Apt 4, Columbus OH 43201. Rent $1,500", "12 Park Ln", "4"),
    ("Rent $1,500. 88 Cedar Cir Dr, Columbus OH 43201", "88 Cedar Cir Dr", None),
])
def test_two_word_street_suffixes(text, addr, unit):
    r = P.parse_listing(text, "")
    assert r["address"] == addr and r.get("unit") == unit


@pytest.mark.parametrize("text", [
    "Cozy Duplex in Clintonville - $1,395/mo\n2 BR / 1 BA | 950 sq ft | Available Jan 1\nSide-by-side duplex near High St. Hardwood floors.",
    "Cozy Duplex - $1,395/mo\n2 bed 1\nCorner unit near Main St. Hardwood floors.",
    "Cozy Duplex - $1,395/mo\nAvailable Jan 1\nQuiet block near Elm Ave.",
])
def test_a_number_at_the_end_of_a_line_is_not_a_street_number(text):
    assert P.parse_listing(text, "").get("address") in (None, "")


@pytest.mark.parametrize("text,title", [
    ("Hilltop 2BR Condo 2 bed 1 bath $189,900\nx", "Hilltop 2BR Condo"),
    ("Hilltop 2BR Condo, 2 bed, 1.5 bath - $1,500/mo", "Hilltop 2BR Condo"),
    ("Cozy 2 bed 1 bath $1,500\nrent", "Cozy 2 bed 1 bath"),  # no earlier bed word: kept as written
])
def test_title_does_not_repeat_beds_and_baths(text, title):
    assert P.parse_listing(text, "").get("title") == title


def test_rent_after_an_address_is_not_an_uncounted_amount():
    t = "Studio 5 Elm Ave, $1,500. Gym fee $44 monthly."
    r = P.parse_listing(t, "")
    r["price"] = 1800
    assert [h["amount"] for h in dropguard.find_unplaced(t, r, "")] == [44.0]
    assert all("$1,500" not in n for n in P._safety_net(t, r, []))


# ---- 6. money spellings reach every reader as dollars
@pytest.mark.parametrize("raw", ["estimate USD 220/mo", "estimate US$220/mo", "estimate USD220/mo", "estimate 220 USD/mo", "estimate ＄220/mo", "estimate: USD 220 / mo"])
def test_usd_inside_an_estimate_phrase_is_dollars(raw):
    assert "$220" in P.normalize_money(raw) and "USD" not in P.normalize_money(raw)


def test_fullwidth_rent_and_usd_estimate_read_like_ascii():
    a = P.parse_listing("Bronzeville 3 BR. Rent ＄3,050. Utilities: tenant pays all, estimate USD 220/mo. Cats ok with $40 monthly cat charge.", "")
    b = P.parse_listing("Bronzeville 3 BR. Rent $3,050. Utilities: tenant pays all, estimate $220/mo. Cats ok with $40 monthly cat charge.", "")
    assert a["price"] == 3050 and a == b


# ---- 6 (more). a European thousands dot is a thousand, not a cent figure
@pytest.mark.parametrize("raw,want", [
    ("alquiler $1.700", "alquiler $1,700"),
    ("Miete $1.700 warm", "Miete $1,700 warm"),
    ("$1.700,50 al mes", "$1,700.50 al mes"),
    ("Rent $1,700.50", "Rent $1,700.50"),
    ("Trash $8.50 monthly", "Trash $8.50 monthly"),
    ("Fee $8.5 monthly", "Fee $8.5 monthly"),
])
def test_thousands_dot(raw, want):
    assert P.normalize_money(raw) == want


def test_a_figure_in_a_one_line_listing_is_quoted_with_its_own_words():
    t = "Helle Wohnung, Miete $1.700 warm, Haustiere nach Absprache. Vorherige Mieter haben die Küche renoviert."
    r = P.parse_listing(t, "")
    assert dropguard.find_unplaced(t, r, r["found_in_listing"]) == []
    assert 'The listing also says "Miete $1,700". It is not counted anywhere. Check what it is for.' in r["found_in_listing"]
