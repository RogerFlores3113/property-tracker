"""Cycle 1, fixer F2: the listing parser on realistic pasted text (fictional buildings)."""
from prophelper import parsers
from prophelper.redflags import local_flags


def parse(text, url=""):
    return parsers.parse_listing(text, url)


APARTMENTS_COM = """The Lofts at Green Street
412 Green Street, Champaign, IL 61820
$1,495/mo
2 Beds 1 Bath 880 sq ft
Available Aug 1, 2027
Rent includes: water, trash.
Tenant pays electric, internet.
Application fee: $55 per adult
Security deposit $1,500
"""


# 1 -------------------------------------------------------------------- utilities
def test_tenant_pays_is_not_included():
    assert parse(APARTMENTS_COM)["utilities_included"] == "water, trash"
    assert "utilities_included" not in parse("Maple Court Apartments\nUtilities: Tenant pays electric, internet\n$1,200/mo 1 bed")
    for text in ("Resident pays electric and gas. $1,100/mo 1 bed",
                 "Electric, internet not included. $1,100/mo 1 bed",
                 "Utilities: you pay all utilities. 2 bed $1,300/mo",
                 "Gas and electric are extra. 2 bed $1,300/mo"):
        assert not parse(text).get("utilities_included"), text


def test_included_and_not_included_in_one_line():
    out = parse("Water, sewer and trash included, tenant pays electric and internet. $1,250/mo 1 bed")
    assert out["utilities_included"] == "water, sewer, trash"
    out = parse("Landlord pays water and trash; tenant pays electric. 2 bed $1,250/mo")
    assert out["utilities_included"] == "water, trash"
    assert parse("All utilities included! $1,900/mo studio")["utilities_included"] == "all utilities included"


# 2 -------------------------------------------------------------------- price
REDFIN = """Realtor.com
Price reduced $6,500
$318,500
3 beds 2 baths 1,640 sq ft
123 Birch Hollow Rd, Normal, IL 61761
Single family home for sale
Est. payment $2,105/mo
HOA $215/mo
Property tax $5,124/yr
Home insurance est $1,100/yr
Special assessment of $4,500, buyer assumes.
"""


def test_price_reduced_is_not_the_price():
    out = parse(REDFIN)
    assert out["price"] == 318500
    assert parse("Zillow\nReduced by $6,500\nListed for $318,500\n3 beds 2 baths for sale")["price"] == 318500
    assert parse("Price cut: $6,500 (Nov 3)\nAsking price $318,500\n3 bd 2 ba for sale")["price"] == 318500
    assert parse("Price reduced to $318,500\n3 bd 2 ba house for sale")["price"] == 318500


def test_deposit_and_fee_are_not_rent():
    out = parse("Birchwood Apartments\n$1,500 deposit\n$50 application fee\nRent: $1,250 per month\n1 bed 1 bath")
    assert out["price"] == 1250 and out["deposit"] == 1500 and out["application_fee"] == 50
    out = parse("$1,500 security deposit. $50 application fee. $1,250/mo 1 bed")
    assert out["price"] == 1250


# 3 -------------------------------------------------------------------- title
def test_title_is_never_a_site_name():
    out = parse(REDFIN, "https://www.realtor.com/realestateandhomes-detail/x")
    assert out["title"] == "123 Birch Hollow Rd"
    for first in ("Realtor.com", "Zillow", "Apartments.com", "Redfin"):
        out = parse(f"{first}\n$1,100/mo 1 bed 1 bath\n77 Cedar Lane, Urbana, IL 61801")
        assert out["title"] == "77 Cedar Lane", first


def test_building_names_are_picked_up():
    assert parse(APARTMENTS_COM)["title"] == "The Lofts at Green Street"
    out = parse("Zillow\nMaple Court Apartments\n$1,350/mo 2 bed\n9 Maple Court Dr, Champaign, IL 61820")
    assert out["title"] == "Maple Court Apartments"
    out = parse("Apartments.com\nWelcome to The Lofts at Green Street!\n2 bed $1,495/mo")
    assert out["title"] == "The Lofts at Green Street"


# 4 -------------------------------------------------------------------- move-in
def test_first_and_last_month_is_not_a_fee():
    out = parse("Elm Street Flats\n$1,200/mo 1 bed. Move-in: first and last month required. $100 admin fee.")
    assert out["price"] == 1200 and out["move_in_fees"] == 100
    assert "First and last month" in out["found_in_listing"]
    out = parse("$1,000/mo 2 bed. First, last and deposit due at signing.")
    assert "move_in_fees" not in out
    assert "deposit" in out["found_in_listing"]
    assert "move_in_fees" not in parse("$1,000/mo 2 bed. First month and deposit due at signing.")


# 5 -------------------------------------------------------------------- pets
def test_pets_negotiable_with_extra_charge():
    out = parse("Cats negotiable, $50 extra. $1,100/mo 1 bed")
    assert out["pets"] == "cats" and out["pet_rent"] == 50
    out = parse("Pets: dogs welcome. $35/mo pet rent. $1,100/mo 1 bed")
    assert out["pets"] == "dogs" and out["pet_rent"] == 35


def test_pet_limits_stay_visible():
    out = parse("Pet friendly: cats and dogs under 50 lbs. No aggressive breeds. $35/mo pet rent. $1,300/mo 2 bed")
    assert out["pets"] == "both" and out["pet_rent"] == 35
    assert "50 lbs" in out["found_in_listing"] and "breeds" in out["found_in_listing"]


# 6 -------------------------------------------------------------------- laundry
def test_laundry_kinds():
    assert parse("Shared laundry in the basement. $900/mo 1 bed")["laundry"] == "in_building"
    assert parse("Laundry on site. $900/mo 1 bed")["laundry"] == "in_building"
    assert parse("In-unit washer and dryer. $900/mo 1 bed")["laundry"] == "in_unit"


def test_hookups_are_not_in_unit(monkeypatch):
    out = parse("W/D hookups in unit. $900/mo 1 bed")
    assert out.get("laundry") != "in_unit"
    assert "hookups" in out.get("found_in_listing", "") or out.get("laundry") == "hookups"
    from prophelper import store
    monkeypatch.setattr(store, "LAUNDRY_VALUES", ("in_unit", "in_building", "none", "hookups"))
    assert parse("Washer/dryer hookups available. $900/mo 1 bed")["laundry"] == "hookups"


# 7 -------------------------------------------------------------------- buyer fields
def test_buyer_fields():
    out = parse(REDFIN)
    assert out["insurance"] == 1100          # the field is per year
    assert out["hoa"] == 215                 # the field is per month
    assert out["property_tax"] == 5124       # the field is per year
    assert "Special assessment $4,500" in out["found_in_listing"] and "buyer pays" in out["found_in_listing"]
    assert parse("Home insurance about $90/mo. 3 bd 2 ba for sale $250,000")["insurance"] == 1080


def test_special_assessment_unknown_payer():
    out = parse("$4,500 special assessment on the roof. 2 bed condo for sale $210,000")
    assert "$4,500" in out["found_in_listing"] and "doesn't say who pays" in out["found_in_listing"]
    assert "found_in_listing" not in parse("No special assessments. 2 bed condo for sale $210,000")


# 8 -------------------------------------------------------------------- application fee
def test_application_fee_per_person_is_visible():
    out = parse(APARTMENTS_COM)
    assert out["application_fee"] == 55
    assert "per adult" in out["found_in_listing"]
    out = parse("$40 application fee per applicant. $1,000/mo 1 bed")
    assert out["application_fee"] == 40 and "per applicant" in out["found_in_listing"]
    assert "found_in_listing" not in parse("Application fee $50. $1,000/mo 1 bed")


# 9 -------------------------------------------------------------------- red flags
def _flags(text):
    return local_flags({"listing_text": text, "address": "1 Main St"})


def test_new_scam_phrases():
    for text in ("Send the deposit by Cash App to hold it.", "We only take Zelle only.", "Pay through Venmo.",
                 "Pay the deposit with a gift card.", "Please wire the deposit today.",
                 "Deposit before viewing is required.", "The owner is out of the country.",
                 "Keys mailed after payment."):
        assert _flags(text), text
    assert not _flags("Quiet building near campus. Tours Saturday.")


def test_one_payment_app_mention_gives_one_flag():
    assert len(_flags("Cash App only.")) == 1
    assert len(_flags("You can pay rent with Venmo.")) == 1
