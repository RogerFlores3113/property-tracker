"""Cycle 8, group G1: a corpus of realistic listing texts (rent and buy, short, run-on, multi-line, with pipes and dashes) for
the money, utilities, fee, HOA, tax, deposit, year built and parking readers. Each row: id, text, expected values (a subset
of the parsed fields), fields that must NOT be filled in, and words that must appear in the "Also in the listing" note."""
from __future__ import annotations

import pytest

from prophelper.parsers import parse_listing

# (id, text, expected, absent, note_words)
CORPUS: list[tuple[str, str, dict, tuple, tuple]] = [
    # ---- phrasings quoted in the c5r, c6r and c7r panel notes
    ("c7-uiuc-internet-via-xfinity",
     "Rent includes water, sewer and trash. Resident pays ComEd electric and Nicor gas; internet via Xfinity.",
     {"utilities_included": "water, sewer, trash", "tenant_pays": "electric, gas"}, (), ()),
    ("c7-family-pge-paren",
     "Electric (PG&E), gas and internet are tenant responsibility. Water and trash included.",
     {"tenant_pays": "electric, gas, internet", "utilities_included": "water, trash"}, (), ()),
    ("c7-pge-and-except",
     "Tenant pays PG&E. All utilities included except electric.",
     {"tenant_pays": "electric, gas"}, (), ("unclear", "gas")),
    ("c7-incl-utilities-price-line",
     "Sunny 1BR from $1,560 incl. utilities. 710 W Clark St, Champaign IL",
     {"price": 1560, "beds": 1, "utilities_included": "all"}, (), ()),
    ("c7-incl-utilities-short",
     "2BR $1,800 incl. utilities near campus",
     {"price": 1800, "beds": 2, "utilities_included": "all"}, ("tenant_pays",), ()),
    ("c7-utilities-included-price-line",
     "Cozy studio $950/mo - utilities included - available Aug 1",
     {"price": 950, "utilities_included": "all"}, (), ()),
    ("c7-garage-and-storage",
     "Rent $1,900/mo 2 bed. Heated underground garage ($110/mo), storage lockers available for $25 a month.",
     {"price": 1900, "parking": "garage", "parking_cost": 110}, ("other_monthly_fees",), ("$25",)),
    ("c7-garage-then-storage-no-comma",
     "2 bed $1,900/mo. Garage $110/mo storage lockers available for $25 a month.",
     {"parking": "garage", "parking_cost": 110}, ("other_monthly_fees",), ("$25",)),
    ("c7-assigned-covered-spot",
     "1 bed $1,500/mo. Parking: assigned covered spot $60/mo. Storage locker $30 per month.",
     {"parking": "covered", "parking_cost": 60}, (), ("$30",)),
    ("c7-trash-valet-with-trash-included",
     "Rent $1,500/mo. Water and trash included. Trash valet $20/month.",
     {"utilities_included": "water, trash", "other_monthly_fees": 20}, (), ()),
    ("c7-valet-trash-bare",
     "1 bed $1,350/mo. Valet trash $30. Pets welcome.",
     {"other_monthly_fees": 30}, (), ()),
    ("c7-surface-lot",
     "Surface lot parking. 1BR $1,200/mo near transit.",
     {"parking": "lot"}, (), ()),
    ("c7-hoa-run-on-1",
     "Oak 2 bed condo $289,500. HOA $310/mo.",
     {"price": 289500, "beds": 2, "hoa": 310}, (), ()),
    ("c7-hoa-run-on-2",
     "Oak condo $250,000 HOA $310 per month 2 bed 55 Oak Rd Columbus OH",
     {"price": 250000, "beds": 2, "hoa": 310}, (), ()),
    ("c7-hoa-arlington",
     "THE ARLINGTON LOFTS - 2BR/2BA condo $289,500. 1,200 sqft, 3329 N Broadway, Chicago, IL 60657. Updated kitchen. HOA $310/mo. "
     "Special assessment $2,000 paid by seller.",
     {"price": 289500, "beds": 2, "baths": 2, "sqft": 1200, "hoa": 310, "special_assessment": 2000}, (), ()),
    ("c7-hoa-works",
     "Oak Condo 2 bed $250,000. HOA $310/mo.",
     {"price": 250000, "hoa": 310}, (), ()),
    ("c7-deposit-1.5x-spaces",
     "Rent: $2,250 /mo   Deposit: 1.5x rent  Application fee: $50",
     {"price": 2250, "deposit": 3375, "application_fee": 50}, (), ()),
    ("c7-deposit-1.5x-multiline",
     "Rent: $2,250 /mo\nDeposit: 1.5x rent\nApplication fee: $50\nLease: 12 months",
     {"price": 2250, "deposit": 3375, "application_fee": 50}, (), ()),
    ("c7-deposit-1.5x-pipes",
     "Rent $2,250/mo | Deposit 1.5x rent | App fee $50",
     {"price": 2250, "deposit": 3375}, (), ()),
    ("c7-rental-tax-included",
     "2BR rental $1,800/mo. Property taxes $6,000 per year included in rent. Water included.",
     {"price": 1800, "beds": 2}, ("property_tax",), ("property tax",)),
    ("c7-year-2022-build", "Modern 2BR $2,100/mo, 2022 build, in-unit laundry", {"year_built": 2022}, (), ()),
    ("c7-year-1990-build", "1990 build 3 bed house $3,000/mo", {"year_built": 1990, "beds": 3}, (), ()),
    ("c7-year-built-in", "Charming bungalow built in 1998, 3 bed 2 bath, $410,000", {"year_built": 1998, "price": 410000}, (), ()),
    ("c7-year-built-label", "Year built: 2015\nPrice $525,000\n4 bed 3 bath", {"year_built": 2015, "price": 525000}, (), ()),
    ("c7-new-construction", "New construction 2024 townhome $449,900 3 bed 2.5 bath", {"year_built": 2024, "price": 449900}, (), ()),
    ("c6-tenant-all-landlord-garbage",
     "Tenant responsible for all utilities. Landlord pays garbage only.",
     {"utilities_included": "trash"}, (), ()),
    ("c6-except-electric",
     "Utilities: all utilities included except electric",
     {"utilities_included": "gas, water, sewer, trash, heat", "tenant_pays": "electric"}, (), ()),
    ("c6-billed-back-trash",
     "Water and trash included; tenant pays electric, gas and internet. $25/mo billed back for trash",
     {"utilities_estimate": 25, "tenant_pays": "electric, gas, trash, internet", "utilities_included": "water"}, (), ()),
    ("c6-storage-locker-forms",
     "1 bed $1,200/mo. Storage locker: $30/mo.",
     {"price": 1200}, ("other_monthly_fees",), ("$30",)),
    ("c6-extra-monthly-lawn",
     "House $2,400/mo. $150 extra monthly for lawn and trash.",
     {"price": 2400, "other_monthly_fees": 150}, (), ()),
    ("c5-parking-50",
     "Studio $900/mo. Parking $50 a month.",
     {"price": 900, "parking_cost": 50}, (), ()),
    ("c6-property-taxes-approx",
     "Riverside Lofts Unit 4B - 2 bed 2 bath condo $310,000, property taxes approx $4,100/yr, HOA $280/month.",
     {"price": 310000, "property_tax": 4100, "hoa": 280}, (), ()),
    # ---- new ones in the styles of Zillow, Apartments.com, Craigslist and Facebook Marketplace
    ("zillow-buy-multiline",
     "$425,000\n3 bd | 2 ba | 1,850 sqft\n412 Maple Dr, Austin, TX 78704\nBuilt in 2004\nHOA: $95/mo\nProperty taxes: $7,200/yr\nParking: 2 car garage",
     {"price": 425000, "beds": 3, "baths": 2, "hoa": 95, "property_tax": 7200, "year_built": 2004, "parking": "garage"}, (), ()),
    ("zillow-buy-monthly-tax",
     "For sale: 2 bed 1 bath ranch, $219,000. Taxes $310/mo. HOA $0. Year built 1962.",
     {"price": 219000, "year_built": 1962, "property_tax": 3720}, (), ()),
    ("apartments-rent-fees-block",
     "Elm Court Apartments\n1 Bed 1 Bath from $1,425/mo\nSecurity deposit: $500\nApplication fee: $45\nAdmin fee: $150\nParking: Surface lot $35/mo\n"
     "Rent includes water, sewer, trash. Tenant pays electric and internet.",
     {"price": 1425, "deposit": 500, "application_fee": 45, "move_in_fees": 150, "parking": "lot", "parking_cost": 35,
      "utilities_included": "water, sewer, trash", "tenant_pays": "electric, internet"}, (), ()),
    ("apartments-garage-covered",
     "2 Beds 2 Baths $1,950/mo. Garage parking $125/mo. Covered parking $75/mo.",
     {"price": 1950, "parking": "garage"}, (), ()),
    ("craigslist-style",
     "$1100 / 1br - 700ft2 - Cute 1BR near downtown (Champaign)\nUtilities included! Free off-street parking. No deposit.",
     {"price": 1100, "beds": 1, "utilities_included": "all", "deposit": 0, "parking_cost": 0}, (), ()),
    ("craigslist-plus-utils",
     "$1,250 / 2br - 900ft2 - 2 bedroom duplex. Plus utilities. Deposit $1,250. Street parking only.",
     {"price": 1250, "beds": 2, "deposit": 1250, "parking": "street"}, ("utilities_included",), ()),
    ("fb-marketplace-short",
     "2 bed apt for rent $1,400 a month, heat and water included, tenant pays electric. DM me",
     {"price": 1400, "beds": 2, "utilities_included": "water, heat", "tenant_pays": "electric"}, (), ()),
    ("fb-marketplace-runon",
     "Room in 3 bedroom house $650/month utilities not included deposit $650 no pets driveway parking available",
     {"price": 650, "deposit": 650}, ("utilities_included",), ()),
    ("rent-one-line-pipes",
     "Maple Court | 2BR/1BA | $1,675/mo | Deposit $1,675 | Water, trash included | Garage $90/mo",
     {"price": 1675, "beds": 2, "deposit": 1675, "utilities_included": "water, trash", "parking": "garage", "parking_cost": 90}, (), ()),
    ("rent-dashes",
     "Lakeview Flats - 1BR - $1,300/mo - heat & water included - tenant pays electric - parking $40/mo",
     {"price": 1300, "utilities_included": "heat, water", "tenant_pays": "electric", "parking_cost": 40}, (), ()),
    ("rent-internet-included",
     "Studio $1,000/mo. Rent includes internet and water. Resident pays electric.",
     {"utilities_included": "water, internet", "tenant_pays": "electric"}, (), ()),
    ("rent-unknown-gas",
     "2BR $1,500/mo. Water and sewer included. Electric is separate.",
     {"utilities_included": "water, sewer", "tenant_pays": "electric"}, (), ()),
    ("rent-not-incl",
     "1BR $1,100/mo, utilities not incl. Deposit $1,100.",
     {"price": 1100, "deposit": 1100}, ("utilities_included",), ()),
    ("rent-all-bills-paid",
     "Room for rent $700. All bills paid, wifi included. Deposit $350.",
     {"utilities_included": "all", "deposit": 350}, (), ()),
    ("buy-condo-fee-label",
     "Downtown condo, 1 bed 1 bath, $199,000. Condo fee $425/month. Taxes: $2,640 annually. Built 1985.",
     {"price": 199000, "hoa": 425, "property_tax": 2640, "year_built": 1985}, (), ()),
    ("buy-hoa-yearly",
     "4 bed house $560,000. HOA $1,200 annually. Property tax $5,900/yr. Year built: 2011",
     {"price": 560000, "hoa": 100, "property_tax": 5900, "year_built": 2011}, (), ()),
    ("buy-run-on-hoa-before-price",
     "Great townhome, HOA $210/mo, listed at $334,000, 3 bed 2.5 bath, 1,640 sqft, built 2008",
     {"price": 334000, "hoa": 210, "year_built": 2008}, (), ()),
    ("buy-no-hoa-in-text",
     "Charming 3 bed ranch for sale $275,000, large lot, 2 car attached garage.",
     {"price": 275000, "parking": "garage"}, ("hoa",), ()),
    ("rent-year-price-not-year",
     "Apartment $1,990 build-your-own lease, 1 bed, utilities extra",
     {"price": 1990}, ("year_built",), ()),
    ("rent-carport",
     "2 bed $1,600/mo. Carport $45/mo. Water, sewer, trash included.",
     {"parking": "covered", "parking_cost": 45, "utilities_included": "water, sewer, trash"}, (), ()),
    ("rent-gas-in-both-clear",
     "Landlord pays water. Tenant pays gas and electric.",
     {"utilities_included": "water", "tenant_pays": "electric, gas"}, (), ()),
    ("rent-comed-nicor-only",
     "Tenant sets up ComEd and Nicor accounts. Cable via Comcast.",
     {"tenant_pays": "electric, gas"}, ("utilities_included",), ()),
]


def _note(r: dict) -> str:
    return str(r.get("found_in_listing", "")).lower()


@pytest.mark.parametrize("cid,text,expected,absent,words", CORPUS, ids=[c[0] for c in CORPUS])
def test_corpus(cid, text, expected, absent, words):
    r = parse_listing(text)
    for key, want in expected.items():
        if key in ("utilities_included", "tenant_pays") and isinstance(want, str) and want != "all":
            got = r.get(key) or ""
            assert set(got.split(", ")) == set(want.split(", ")), f"{cid}: {key} = {got!r}, wanted {want!r}\nfull: {r}"
            continue
        assert r.get(key) == want, f"{cid}: {key} = {r.get(key)!r}, wanted {want!r}\nfull: {r}"
    for key in absent:
        assert key not in r, f"{cid}: {key} should not be filled in, got {r.get(key)!r}"
    for w in words:
        assert w.lower() in _note(r), f"{cid}: note should mention {w!r}: {_note(r)!r}"


def test_corpus_size():
    assert len(CORPUS) >= 40
    assert len({c[0] for c in CORPUS}) == len(CORPUS)


# ---- negative tests: rules loosened for the corpus must not break these
NEGATIVE: list[tuple[str, str, dict, tuple]] = [
    ("parking-included-not-rent", "1 bed $1,500/mo. Parking included, $1,500/mo rent. Water included.",
     {"price": 1500, "parking_cost": 0}, ()),
    ("parking-available-app-fee", "1 bed $1,500/mo. Parking available, $30 application fee",
     {"price": 1500, "application_fee": 30}, ("parking_cost",)),
    ("built-in-appliance", "2020 built-in microwave. 2 bed $1,800/mo", {"price": 1800}, ("year_built",)),
    ("excl-utilities", "1BR $1,100/mo excl. utilities", {"price": 1100}, ("utilities_included",)),
    ("not-incl-utilities", "1BR $1,000/mo not incl. utilities", {"price": 1000}, ("utilities_included",)),
    ("utilities-paren-not-included", "Utilities (electric, gas) not included. 1BR $1,000/mo", {}, ("utilities_included",)),
    ("covered-then-rent", "Parking: covered, $1,500/mo rent", {"parking": "covered", "price": 1500}, ("parking_cost",)),
    ("internet-offered-not-included", "Resident pays electric; water, sewer, trash included. Internet via Xfinity available.",
     {"utilities_included": "water, sewer, trash"}, ()),
    ("rental-tax-no-price-field", "Rent $1,000. Property taxes: $2,000/yr", {"price": 1000}, ("property_tax",)),
    ("buy-tax-still-read", "Condo for sale $199,000. Property taxes: $2,000/yr", {"price": 199000, "property_tax": 2000}, ()),
    ("year-in-price", "Apartment $1,990 build-your-own lease, 1 bed", {"price": 1990}, ("year_built",)),
    ("condo-price-not-hoa", "Condo $289,500, 2 bed", {"price": 289500}, ("hoa",)),
    ("deposit-after-rent-same-line", "Rent $1,200/mo Deposit: $600 Application fee: $40", {"price": 1200, "deposit": 600, "application_fee": 40}, ()),
    ("rent-then-fee-label-colon", "Rent: $1,900 /mo   Application fee: $50   Admin fee: $100",
     {"price": 1900, "application_fee": 50, "move_in_fees": 100}, ("deposit",)),
]


@pytest.mark.parametrize("cid,text,expected,absent", NEGATIVE, ids=[c[0] for c in NEGATIVE])
def test_negative(cid, text, expected, absent):
    r = parse_listing(text)
    for key, want in expected.items():
        assert r.get(key) == want, f"{cid}: {key} = {r.get(key)!r}, wanted {want!r}\nfull: {r}"
    for key in absent:
        assert key not in r, f"{cid}: {key} should not be filled in, got {r.get(key)!r}"


def test_clash_is_one_list_only():
    r = parse_listing("Tenant pays PG&E. All utilities included except electric.")
    inc = set((r.get("utilities_included") or "").split(", "))
    pays = set((r.get("tenant_pays") or "").split(", "))
    assert not (inc & pays)
    assert {"electric", "gas"} <= pays
    assert "unclear" in _note(r)


def test_unlisted_utility_is_unknown_not_included():
    r = parse_listing("Rent includes water, sewer and trash. Resident pays ComEd electric and Nicor gas; internet via Xfinity.")
    assert "internet" not in (r.get("utilities_included") or "")
    assert "internet" not in (r.get("tenant_pays") or "")
