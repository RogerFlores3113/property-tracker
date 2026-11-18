"""Cycle 8, group G2: a corpus of realistic listing texts and what the reader must get for the title, address, unit,
city/state/zip and pets. Every field named in an expectation must match; a field left out of an expectation is not checked,
except that "unit" and "pets" are always checked (absent means the reader must not invent one)."""
from __future__ import annotations

import pytest

from prophelper.parsers import parse_listing

# (id, text, expected). expected keys: title, address, unit, city, state, zip, pets; plus "extra" checks done in tests below.
C: list[tuple[str, str, dict]] = [
    # ---- Zillow style
    ("zillow_house", "Zillow\n$2,450/mo\n3 bd 2 ba 1,450 sqft\n418 Maple Ave, Redwood City, CA 94063\nSingle family home for rent. Dogs ok. Cats ok.\nAvailable now",
     dict(title="418 Maple Ave", address="418 Maple Ave", city="Redwood City", state="CA", zip="94063", pets="both")),
    ("zillow_condo_unit", "Riverside Lofts Unit 4B - 2 bed 2 bath condo.\n1200 sqft. 3329 N Broadway, Chicago, IL 60657\nPrice $389,000",
     dict(title="Riverside Lofts", address="3329 N Broadway", unit="4B", city="Chicago", state="IL", zip="60657")),
    ("zillow_name_unit_address", "Maple Court Townhomes, Unit B.\n3 bed, 2.5 bath. 1,600 sq ft\n55 Maple Ct, Champaign, IL 61820\n$1,950/mo. Pets: dogs ok",
     dict(title="Maple Court Townhomes", address="55 Maple Ct", unit="B", city="Champaign", state="IL", zip="61820", pets="dogs")),
    ("zillow_welcome", "Welcome to Hilltop Townhomes 3rd floor 2BR\n$1,750/mo\n902 Hilltop Rd, Urbana, IL 61801\nCats allowed",
     dict(title="Hilltop Townhomes", address="902 Hilltop Rd", city="Urbana", state="IL", zip="61801", pets="cats")),
    ("arboretum_caps", "THE ARBORETUM RESIDENCES - 1 Bedroom, 1 Bath, $1,380/mo\n1900 S Mattis Ave, Champaign, IL 61822\nWasher and dryer in unit. No pets.",
     dict(title="The Arboretum Residences", address="1900 S Mattis Ave", city="Champaign", state="IL", zip="61822", pets="none")),
    ("westgate", "Westgate Flats\n2 bed 1 bath apartment, $1,600 per month\nAvailable Aug 1. Cats ok.\nunit 2C at 14 Westgate Dr, Champaign, IL",
     dict(title="Westgate Flats", address="14 Westgate Dr", unit="2C", city="Champaign", state="IL", pets="cats")),
    ("zillow_ui_noise", "Skip to main content\nSave\nShare\nBack to search\n$1,895/mo\nCedar Pointe Apartments\n77 Cedar Ln, Austin, TX 78704\nContact property",
     dict(title="Cedar Pointe Apartments", address="77 Cedar Ln", city="Austin", state="TX", zip="78704")),
    # ---- Apartments.com style
    ("apts_com", "Apartments.com\nThe Pines at Oakwood\n1 Bed | 1 Bath | 720 Sq Ft\n$1,425 - $1,590\n2200 Oakwood Blvd, Dallas, TX 75201\nPet Policy: Dogs and cats welcome, $300 deposit",
     dict(title="The Pines at Oakwood", address="2200 Oakwood Blvd", city="Dallas", state="TX", zip="75201", pets="both")),
    ("apts_pipe_name", "LAKESHORE VILLAS | Sunny 3BR/2BA house, fenced yard, 2 car garage\n$2,500/mo\n88 Lakeshore Dr, Madison, WI 53703",
     dict(title="Lakeshore Villas", address="88 Lakeshore Dr", city="Madison", state="WI", zip="53703")),
    ("apts_pipe_name_noaddr", "LAKESHORE VILLAS | Sunny 3BR/2BA house, fenced yard, 2 car garage", dict(title="Lakeshore Villas")),
    ("apts_pipe_lower", "Birch Grove Apartments | 2 bed 2 bath | $1,800/mo | 12 Birch Way, Denver, CO 80202",
     dict(title="Birch Grove Apartments", address="12 Birch Way", city="Denver", state="CO", zip="80202")),
    ("apts_dash_name", "Harbor View Apartments - Unit 4C, 3329 N Broadway\nChicago, IL 60657\n$2,100/mo",
     dict(title="Harbor View Apartments", address="3329 N Broadway", unit="4C", city="Chicago", state="IL", zip="60657")),
    ("apts_apt_suffix", "3329 N Broadway Ave Apt 4C\nChicago, IL 60657\n1 bed 1 bath\n$1,900 / month",
     dict(title="3329 N Broadway Ave", address="3329 N Broadway Ave", unit="4C", city="Chicago", state="IL", zip="60657")),
    # ---- Craigslist style
    ("cl_short", "$1100 / 1br - 700ft2 - sunny apartment near campus (Champaign)\n\n710 W Clark St, Champaign, IL 61820\ncats ok\navailable aug 15",
     dict(address="710 W Clark St", city="Champaign", state="IL", zip="61820", pets="cats")),
    ("cl_no_address", "$1,350 / 2br - 900ft2 - Quiet 2BR near downtown (Urbana)\nW/D in unit. Dogs ok. Call 217-555-0188",
     dict(pets="dogs")),
    ("cl_rent_first", "Rent $2\nSunny studio near the park\n123 Main St, Austin, TX 78701",
     dict(title="Sunny studio near the park", address="123 Main St", city="Austin", state="TX", zip="78701")),
    ("cl_deposit_first", "Deposit: 1.5x rent\n55 Oak Ave, Austin, TX 78701\n2 bed $1,900/mo",
     dict(title="55 Oak Ave", address="55 Oak Ave", city="Austin", state="TX", zip="78701")),
    ("cl_rent_deposit_run", "Rent: $2,250 /mo   Deposit: 1.5x rent  Application fee: $45\n19 Pine St, Portland, OR 97205",
     dict(title="19 Pine St", address="19 Pine St", city="Portland", state="OR", zip="97205")),
    ("cl_labels_only", "Rent: $1,500\nDeposit: $1,500\nPets: no\nUtilities: tenant pays electric\nTaxes: n/a\nHOA: none",
     dict(pets="none")),
    ("cl_money_first", "$1,500 per month\n2 bed 1 bath\n44 Elm Dr, Boise, ID 83702",
     dict(title="44 Elm Dr", address="44 Elm Dr", city="Boise", state="ID", zip="83702")),
    ("cl_pets_first", "Pets: dogs ok\nNice 1 bedroom in a quiet fourplex\n9 Rose Ct, Tulsa, OK 74103",
     dict(title="Nice 1 bedroom in a quiet fourplex", address="9 Rose Ct", city="Tulsa", state="OK", zip="74103", pets="dogs")),
    ("cl_no_pets_first", "No pets allowed\nBright 2BR with balcony\n300 Lake St, Duluth, MN 55802",
     dict(title="Bright 2BR with balcony", address="300 Lake St", city="Duluth", state="MN", zip="55802", pets="none")),
    # ---- Facebook Marketplace style
    ("fb_short", "Apartment for rent - $1,200\nChampaign, IL\n1 bedroom 1 bathroom\nWasher/dryer hookups. Pet friendly.",
     dict(city="Champaign", state="IL", pets="both")),
    ("fb_oneline", "2BR 1BA available 9/1 $1,650/mo no pets 1201 Harvest Ln, Champaign IL 61820 text me",
     dict(address="1201 Harvest Ln", city="Champaign", state="IL", zip="61820", pets="none")),
    ("fb_allcaps", "SPACIOUS 2 BEDROOM APARTMENT NEAR CAMPUS!!! $1,400 MONTH. 305 E GREEN ST CHAMPAIGN IL 61820. NO PETS. CALL NOW",
     dict(address="305 E Green St", pets="none")),
    ("fb_run_on", "Hi, I'm renting my room in a 3 bed house at 22 Willow Way, Ames, IA 50010. $650 a month plus utilities, cats are fine but no dogs, thanks",
     dict(address="22 Willow Way", city="Ames", state="IA", zip="50010", pets="cats")),
    # ---- direction letters are never units
    ("dir_w_clark", "710 W Clark St\nUrbana, IL 61801\n2 bed $1,500/mo", dict(title="710 W Clark St", address="710 W Clark St", city="Urbana", state="IL", zip="61801")),
    ("dir_w_comma", "710 W Clark St, W\nUrbana, IL 61801", dict(address="710 W Clark St", city="Urbana", state="IL", zip="61801")),
    ("dir_s_harvest", "1201 Harvest Ln, S\nChampaign, IL 61820\n$1,300/mo", dict(address="1201 Harvest Ln", city="Champaign", state="IL", zip="61820")),
    ("dir_apt_w", "710 W Clark St, Apt W\nUrbana, IL 61801", dict(address="710 W Clark St", city="Urbana", state="IL", zip="61801")),
    ("dir_unit_ne", "55 N Main Ave Unit NE, Peoria, IL 61602", dict(address="55 N Main Ave", city="Peoria", state="IL", zip="61602")),
    ("dir_real_unit_kept", "710 W Clark St, Apt 3W\nUrbana, IL 61801", dict(address="710 W Clark St", unit="3W", city="Urbana", state="IL", zip="61801")),
    ("dir_unit_b_kept", "1201 Harvest Ln, Unit B\nChampaign, IL 61820", dict(address="1201 Harvest Ln", unit="B", city="Champaign", state="IL", zip="61820")),
    ("dir_hash_unit", "415 S Wright St #204, Champaign, IL 61820", dict(address="415 S Wright St", unit="204", city="Champaign", state="IL", zip="61820")),
    ("dir_north_word", "88 North Park Ave, Apt 6, Evanston, IL 60201", dict(address="88 North Park Ave", unit="6", city="Evanston", state="IL", zip="60201")),
    # ---- pets: clear single statements
    ("pets_no", "2 bed $1,500/mo\nNo pets", dict(pets="none")),
    ("pets_cats_ok", "Cats ok. 2 bed $1,500/mo", dict(pets="cats")),
    ("pets_dogs_ok", "Dogs ok. 2 bed $1,500/mo", dict(pets="dogs")),
    ("pets_two_dogs", "Two dogs ok. $1,500/mo", dict(pets="dogs")),
    ("pets_both_words", "Cats and dogs welcome with a pet deposit.", dict(pets="both")),
    ("pets_dogs_no_cats", "Dogs ok, no cats allowed.", dict(pets="dogs")),
    ("pets_no_cats_dogs_ok", "No cats. Dogs ok.", dict(pets="dogs")),
    ("pets_no_large_dogs", "Pet friendly. No large dogs over 50 lbs.", dict(pets="both")),
    ("pets_not_allowed_phrase", "Pets are not allowed in this building.", dict(pets="none")),
    ("pets_negotiable", "Cats negotiable, $50 extra. $1,100/mo 1 bed", dict(pets="cats")),
    # ---- pets: contradictions and approval leave it unknown
    ("conf_dogs_then_none", "Pets: dogs ok. Pets: no pets allowed.", dict()),
    ("conf_ok_then_building", "dogs ok, cats ok. No pets allowed in building", dict()),
    ("conf_dogs_cats_approval", "Dogs ok, no cats allowed? Cats considered with approval.", dict()),
    ("conf_none_then_two_dogs", "No pets allowed. Pets: up to 2 dogs", dict()),
    ("conf_multiline", "Pets: cats ok\nPets: no pets allowed\n2 bed $1,500/mo", dict()),
    ("approval_only", "Pets considered with approval. 2 bed $1,500/mo", dict()),
    ("approval_cats_only", "Cats case by case.", dict()),
    # ---- pet fees and counts
    ("fee_cats_up_to_2", "Cats up to 2, $250 fee, $30 pet rent", dict(pets="cats")),
    ("fee_dogs_max", "Dogs max 2. $300 fee, $35 pet rent per month.", dict(pets="dogs")),
    ("fee_cats_deposit", "Cats $200 deposit non-refundable", dict(pets="cats")),
]

FEES = {  # id -> expected extra pet fields
    "fee_cats_up_to_2": dict(pet_fee=250, pet_rent=30, pet_count_limit=2),
    "fee_dogs_max": dict(pet_fee=300, pet_rent=35, pet_count_limit=2),
    "fee_cats_deposit": dict(pet_fee=200),
    "pets_two_dogs": dict(pet_count_limit=2),
}

UNKNOWN_PETS = {"conf_dogs_then_none", "conf_ok_then_building", "conf_dogs_cats_approval", "conf_none_then_two_dogs", "conf_multiline",
                "approval_only", "approval_cats_only"}


def test_corpus_is_big_enough():
    assert len(C) >= 40 and len({c[0] for c in C}) == len(C)


@pytest.mark.parametrize("name,text,want", C, ids=[c[0] for c in C])
def test_corpus_listing(name, text, want):
    got = parse_listing(text)
    for key in ("title", "address", "unit", "city", "state", "zip", "pets"):
        if key in want or key in ("unit", "pets"):
            assert got.get(key) == want.get(key), f"{name}: {key} is {got.get(key)!r}, wanted {want.get(key)!r}"
    for key, value in FEES.get(name, {}).items():
        assert got.get(key) == value, f"{name}: {key} is {got.get(key)!r}, wanted {value!r}"
    if name in UNKNOWN_PETS:
        note = got.get("found_in_listing", "")
        assert "ask the landlord" in note and "pets" in note.lower(), f"{name}: no note about pets: {note!r}"
    else:
        assert "ask the landlord which pets" not in got.get("found_in_listing", ""), f"{name}: a pets note where the listing is clear"


# ---- the title never comes from a field line
@pytest.mark.parametrize("first", ["Rent $2", "Deposit: 1.5x rent", "Price: $1,200", "Taxes: $2,000/yr", "HOA: $150/mo", "Pets: dogs ok",
                                   "Utilities: tenant pays electric", "Rent: $2,250 /mo   Deposit: 1.5x rent", "$1,800 per month", "No pets allowed"])
def test_field_lines_are_never_titles(first):
    got = parse_listing(first + "\n2 bed 1 bath\n19 Pine St, Portland, OR 97205")
    assert got["title"] == "19 Pine St"


def test_field_lines_with_no_address_give_no_title_so_the_form_falls_back():
    got = parse_listing("Rent $2\nDeposit: 1.5x rent")
    assert "title" not in got


def test_names_that_start_like_labels_still_work():
    assert parse_listing("Rental Row Apartments\n12 Row St, Austin, TX 78701")["title"] == "Rental Row Apartments"
    assert parse_listing("Pets Welcome Place Apartments\n12 Row St, Austin, TX 78701")["title"] != ""
    assert parse_listing("Lease Street Lofts\n12 Row St, Austin, TX 78701")["title"] == "Lease Street Lofts"
    assert parse_listing("Catalina Court Apartments\n12 Row St, Austin, TX 78701")["title"] == "Catalina Court Apartments"
    assert parse_listing("Dogwood Villas\n12 Row St, Austin, TX 78701")["title"] == "Dogwood Villas"


def test_pipes_split_and_all_caps_is_title_cased():
    got = parse_listing("LAKESHORE VILLAS | Sunny 3BR/2BA house, fenced yard, 2 car garage")
    assert got["title"] == "Lakeshore Villas"
    assert parse_listing("OAK PARK LOFTS\n9 Oak St, Austin, TX 78701")["title"] == "Oak Park Lofts"


def test_saved_place_falls_back_to_the_address(store):
    from prophelper.store import Store  # noqa: F401
    store.add_search("S", "rent")
    sid = store.current_search()["id"]
    p, _ = store.add_place(search_id=sid, by="you", **{k: v for k, v in parse_listing("Rent $2\nDeposit: 1.5x rent\n5 Elm St, Austin, TX 78701").items() if k in ("title", "address")})
    assert p["title"] == "5 Elm St"
    assert "title" not in parse_listing("Rent $2\nDeposit: 1.5x rent")  # the form leaves it blank for you to name


# ---- a looser directional rule must not eat real units or real streets
def test_unit_letters_that_are_not_directions_stay():
    for letter in ("A", "B", "C", "D", "F", "G", "H", "K"):
        assert parse_listing(f"12 Oak St, Unit {letter}\nChampaign, IL 61820")["unit"] == letter
    assert parse_listing("12 Oak St Apt 2E\nChampaign, IL 61820")["unit"] == "2E"
    assert parse_listing("12 Oak St Apt 2E\nChampaign, IL 61820")["address"] == "12 Oak St"


# ---- a looser pets rule must not misfire
def test_clear_statements_do_not_become_unknown():
    for text, want in (("No pets", "none"), ("Cats ok", "cats"), ("Dogs ok", "dogs"), ("Two dogs ok", "dogs"), ("Pets: no", "none"),
                       ("No pets allowed.\n2 bed $1,500/mo", "none"), ("Pet friendly. Cats and dogs welcome.", "both"),
                       ("No dogs. Cats ok.", "cats"), ("No smoking. No pets.", "none"), ("Pets allowed. No smoking.", "both")):
        got = parse_listing(text)
        assert got.get("pets") == want, text
        assert "ask the landlord" not in got.get("found_in_listing", ""), text


def test_a_dollar_fee_far_from_pets_is_not_a_pet_fee():
    got = parse_listing("Dogs ok. Great light all day. Application fee $50 per adult. $45 fee for screening.")
    assert "pet_fee" not in got and "pet_rent" not in got
    got = parse_listing("Cats ok, $55 application fee")
    assert "pet_fee" not in got
    got = parse_listing("Cats ok, $55 fee for application")
    assert "pet_fee" not in got


def test_a_pet_fee_per_month_is_pet_rent():
    got = parse_listing("Cats ok, $25 fee per month")
    assert got.get("pet_rent") == 25 and "pet_fee" not in got


def test_no_pets_note_names_what_the_listing_says():
    got = parse_listing("Dogs ok, no cats allowed? Cats considered with approval.")
    note = got["found_in_listing"]
    assert "Dogs ok" in note and "Cats considered with approval" in note and "—" not in note


def test_conflicting_pets_is_fits_but_check_for_a_pet_owner(store):
    """With pets left unknown the pet rule can't say no: a pet owner sees a check, not a fail."""
    from prophelper import scoring  # noqa: F401
    store.add_search("S", "rent")
    sid = store.current_search()["id"]
    values = parse_listing("2 bed $1,500/mo\n12 Oak St, Champaign, IL 61820\nPets: dogs ok. Pets: no pets allowed.")
    assert "pets" not in values
    p, _ = store.add_place(search_id=sid, by="you", title=values["title"], address=values["address"], price=values["price"])
    assert not p.get("pets")


# ---- more realistic listings (long, multi-line, pasted straight from a page)
LONG = [
    ("long_zillow", """Zillow
Back to search
418 Maple Ave, Redwood City, CA 94063
$3,200/mo
Est. refinance payment
3 bd
2 ba
1,450 sqft
Facts and features
Pets: Cats OK, Dogs OK
Parking: 1 garage space
Laundry: In unit
Deposit & fees: $3,200 security deposit
""", dict(title="418 Maple Ave", address="418 Maple Ave", city="Redwood City", state="CA", zip="94063", pets="both")),
    ("long_apartments_com", """The Landing at Mill Creek
4410 Mill Creek Pkwy, Raleigh, NC 27612
1-3 Beds | $1,299 - $2,150
Pet Policy
Dogs and cats allowed. 2 pet limit. $350 pet fee, $35 monthly pet rent per pet.
Weight limit: 60 lbs
""", dict(title="The Landing at Mill Creek", address="4410 Mill Creek Pkwy", city="Raleigh", state="NC", zip="27612", pets="both")),
    ("long_craigslist", """2BR/1BA duplex, fenced yard - $1,550 (Savoy)
posted: 3 days ago
Nice duplex, quiet street. 2 bedrooms, 1 bath, W/D hookups, fenced backyard.
Small dogs ok with deposit. No cats please.
Rent $1,550, deposit $1,550. Lease 12 months.
Address: 1412 Prairie Ave, Savoy, IL 61874
""", dict(address="1412 Prairie Ave", city="Savoy", state="IL", zip="61874", pets="dogs")),
    ("long_fb_marketplace", """Marketplace
Sunny room for rent
$700 / month
Listed 2 days ago in Urbana, IL
Details
Bedrooms: 1
Rent includes utilities. No pets, no smoking.
Message seller
""", dict(city="Urbana", state="IL", pets="none")),
    ("pipes_everywhere", "Elm Court Apartments | 2 bed | 2 bath | $1,950 | Pets: cats ok | 15 Elm Ct, Salem, OR 97301", dict(title="Elm Court Apartments", address="15 Elm Ct", city="Salem", state="OR", zip="97301", pets="cats")),
    ("dashes_everything", "Pinecrest Villas - 3 bed - 2 bath - $2,300 - 6 Pine Ln, Reno, NV 89501 - dogs ok", dict(title="Pinecrest Villas", address="6 Pine Ln", city="Reno", state="NV", zip="89501", pets="dogs")),
    ("caps_pipe_address", "SUNSET TERRACE | 120 SUNSET BLVD, LOS ANGELES, CA 90026 | NO PETS", dict(title="Sunset Terrace", pets="none")),
]


@pytest.mark.parametrize("name,text,want", LONG, ids=[c[0] for c in LONG])
def test_long_listing(name, text, want):
    got = parse_listing(text)
    for key in ("title", "address", "unit", "city", "state", "zip", "pets"):
        if key in want or key in ("unit", "pets"):
            assert got.get(key) == want.get(key), f"{name}: {key} is {got.get(key)!r}, wanted {want.get(key)!r}"


# ---- the preview: what was filled in and what was not found, by name
def _preview(store, text, mode="rent"):
    from conftest import local_client
    store.add_search("S", mode)
    html = local_client(store).post("/add/parse", data={"text": text}).text
    filled = html.split("Filled in from what you pasted:")[1].split("</p>")[0] if "Filled in from what you pasted:" in html else ""
    missing = html.split("Not found in the text, so left empty:")[1].split(".")[0] if "Not found in the text, so left empty:" in html else ""
    return html, filled, missing


def test_preview_names_what_was_not_found_for_a_buyer(store):
    html, filled, missing = _preview(store, "88 Beck Row, Columbus, OH 43215\nPrice $349,000. 3 bed 2 bath. HOA $210/mo. Taxes $4,100/yr.", "buy")
    assert "HOA" not in missing and "property tax" not in missing
    assert "insurance" in missing and "HOA" in filled
    html, filled, missing = _preview(store, "88 Beck Row, Columbus, OH 43215\nPrice $349,000. 3 bed 2 bath.", "buy")
    assert "HOA" in missing and "insurance" in missing and "property tax" in missing


def test_preview_does_not_say_parking_not_found_when_a_parking_cost_was_read(store):
    html, filled, missing = _preview(store, "1 bed $1,400/mo\n12 Oak St, Champaign, IL 61820\nParking $50 a month. Cats ok.")
    assert "parking cost" in filled
    assert "parking" not in missing.split(", ")
    html, filled, missing = _preview(store, "1 bed $1,400/mo\n12 Oak St, Champaign, IL 61820")
    assert "parking" in missing.split(", ") and "pets" in missing.split(", ")


def test_preview_lists_have_plain_names_and_no_field_keys(store):
    html, filled, missing = _preview(store, "1 bed $1,400/mo\n12 Oak St, Champaign, IL 61820")
    for key in ("available_from", "utilities_included", "property_tax", "price"):
        assert key not in missing and key not in filled
    assert "available date" in missing and "deposit" in missing and "utilities included" in missing


def test_preview_with_conflicting_pets_says_pets_not_found_and_explains(store):
    html, filled, missing = _preview(store, "1 bed $1,400/mo\n12 Oak St, Champaign, IL 61820\nPets: dogs ok. Pets: no pets allowed.")
    assert "pets" in missing.split(", ") and "pets" not in filled.split(", ")
    assert "Also in the listing" in html and "not clear about pets" in html


def test_preview_a_zero_deposit_counts_as_found(store):
    html, filled, missing = _preview(store, "1 bed $1,400/mo\n12 Oak St, Champaign, IL 61820\nNo security deposit. Parking free.")
    assert "deposit" not in missing.split(", ")
