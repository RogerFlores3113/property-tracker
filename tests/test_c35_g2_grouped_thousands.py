"""Cycle 35 G2 (rules ee, ff): a number written with a space or a dot as the thousands mark is read whole in every field, or left empty with a note that quotes it,
never as its last three digits. A figure with its own deposit or fee label is never the rent."""
import os

import pytest

from prophelper.parsers import parse_listing

P = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel") + "/"


def read(t, **kw):
    return parse_listing(t, "", **kw)


def notes(r):
    return r.get("found_in_listing", "") or ""


def fixture(name):
    return open(P + name, encoding="utf-8").read()


# ---------------------------------------------------------------- rent, every wording
@pytest.mark.parametrize("t", [
    "2BR/1BA Apartment - Hilltop - 1 550 per month",
    "Hilltop 2 bed 1 bath\n1 550/mo\n12 Oak St Columbus OH",
    "Cozy 2 bed. 1 550 a month. 12 Oak St",
    "2 bed, 12 Oak St. Rent: 1 550 USD",
    "Rent 1 550 dollars a month. 2 bed",
    "2 bed\nMonthly rent: 1 550 dollars\n12 Oak St",
    "2 bed | 1.550/mo | 12 Oak St",
    "Rent is 1.550 per month. 2 bed",
    "rent is 1.550 a month. 2 bed",
    "RENT 1 550 PER MONTH. 2 BED",
    "Rent 1 550.",
    "Rent: 1 550",
    "Rent 1.550, 2 bed 1 bath",
    "Rent 1 550; deposit one month",
    "Rent 1 550 per month",
    "Rent 1 550 dollars a month",
])
def test_rent_with_a_spaced_or_dotted_thousands_mark_is_read_whole(t):
    r = read(t)
    assert r["price"] == 1550
    assert "not counted anywhere" not in notes(r)


@pytest.mark.parametrize("t,rent", [
    ("Rent 2 300 dollars a month.", 2300),
    ("Rent: 2 300 USD", 2300),
    ("Rent: 2 300 USD\n3 bed 2 bath house", 2300),
    ("Rent 2 300 US dollars per month. 3 bed", 2300),
    ("3 bed 2 bath. Rent is 2 300 dollars a month", 2300),
    ("Casa de 3 recámaras. 2 100 al mes.", 2100),
    ("Alquiler 2 100 al mes. 3 recámaras", 2100),
    ("Renta mensual 2 100. 3 recámaras", 2100),
    ("Renta 1.900 por mes. 2 recamaras", 1900),
    ("2 bed. $1 750", 1750),
    ("2 bed. $1 750 per month", 1750),
])
def test_rent_other_words_after_the_number(t, rent):
    assert read(t)["price"] == rent


def test_nontech_l2_title_and_body_agree_and_the_deposit_is_not_the_small_part():
    r = read(fixture("r34-nontech-l2.txt"))
    assert r["price"] == 1550 and r["beds"] == 2 and r["baths"] == 1
    assert r["deposit"] == 1550  # "Deposit equals one month"
    assert r["pet_deposit"] == 200 and r["pet_rent"] == 20
    assert "two different rents" not in notes(r)
    assert "$550" not in notes(r)


def test_nontech_l7_and_l9_are_read_whole():
    r7 = read(fixture("r34-nontech-l7.txt"))
    assert r7["price"] == 1550 and r7["deposit"] == 500 and r7["beds"] == 2
    r9 = read(fixture("r34-nontech-l9.txt"))
    assert r9["price"] == 1550 and r9["beds"] == 2


def test_family_l3_spanish_rent_and_deposit():
    r = read(fixture("r34-family-l3.txt"))
    assert r["price"] == 2100 and r["deposit"] == 2100 and r["beds"] == 3 and r["baths"] == 2
    assert r["pets"] == "dogs"


# ---------------------------------------------------------------- deposit and fees, every wording
@pytest.mark.parametrize("t", [
    "Rent $2,000. Security deposit: $1.950.",
    "Rent $2,000. Security deposit: $1.950",
    "Rent $2,000.\nSecurity deposit: $1.950\nPets ok",
    "Rent $2,000 | Security deposit $1.950 | Pets ok",
    "Rent $2,000, security deposit of $1.950, pets ok",
    "Rent $2,000. Security deposit: 1.950.",
    "Rent $2,000. Security deposit: 1 950.",
    "Rent $2,000. Security deposit 1 950 dollars.",
    "Rent $2,000. Deposit 1 950",
    "RENT $2,000. SECURITY DEPOSIT: $1.950.",
])
def test_deposit_with_dotted_or_spaced_thousands_is_read_whole(t):
    r = read(t)
    assert r["price"] == 2000
    assert r["deposit"] == 1950


def test_privacy_l6_and_l9_dotted_deposit():
    r6 = read(fixture("r34-privacy-l6.txt"))
    assert r6["price"] == 1900 and r6["deposit"] == 1900
    r9 = read(fixture("r34-privacy-l9.txt"))
    assert r9["price"] == 1950 and r9["deposit"] == 1950


@pytest.mark.parametrize("t", [
    "Alquiler $1.900 al mes. Depósito $1.900.",
    "Alquiler $1.900 al mes.\nDepósito $1.900.",
    "Alquiler 1.900 al mes. Depósito 1.900.",
    "Alquiler 1 900 al mes, depósito 1 900, 2 recámaras",
])
def test_spanish_dotted_deposit(t):
    r = read(t)
    assert r["price"] == 1900 and r["deposit"] == 1900


@pytest.mark.parametrize("t", [
    "Rent $2,000. Pet deposit $1.200. Cats ok.",
    "Rent $2,000. Pet deposit 1.200. Cats ok.",
    "Rent $2,000. Pet deposit: 1 200. Cats ok.",
    "Rent $2,000. Cats ok, $1,200 pet deposit.",
    "Rent $2,000. Cats ok.\nPet deposit $1,200",
    "Rent $2,000 | Cats ok | Pet deposit $1,200",
])
def test_pet_deposit_over_a_thousand_is_read_whole(t):
    r = read(t)
    assert r["price"] == 2000 and r["pet_deposit"] == 1200
    assert "$1 pet deposit" not in notes(r)


def test_pet_rent_and_fee_still_read():
    r = read("Rent $2,000. Cats ok. Pet rent $35/mo. Pet fee $300. Pet deposit $500")
    assert r["pet_rent"] == 35 and r["pet_fee"] == 300 and r["pet_deposit"] == 500


@pytest.mark.parametrize("t,field,val", [
    ("Rent $1,500. Parking 100 a month", "parking_cost", 100),
    ("Rent $1,500. Parking: 1 100 per month. 2 bed", None, None),
])
def test_parking_amounts(t, field, val):
    r = read(t)
    assert r["price"] == 1500
    if field:
        assert r[field] == val
    else:
        assert r.get("parking_cost") != 100  # never the small part


def test_hoa_with_spaced_thousands_is_never_the_small_part():
    r = read("Rent $1,500. HOA 1 210 a month")
    assert r.get("hoa") not in (210,)
    assert "$1,210" in notes(r)


# ---------------------------------------------------------------- a number that cannot be read whole is left empty with a note
@pytest.mark.parametrize("t", [
    "Rent 1 550 2 bed 1 bath apartment, 100 Main St Columbus OH",
    "Rent 1 550 2BR",
    "Rent: 1 550 sq ft retail",
])
def test_unsure_figure_after_a_money_word_is_quoted_never_a_small_part(t):
    r = read(t)
    assert r.get("price") not in (550,)
    assert "price" not in r
    assert "1 550 looks like $1,550" in notes(r)
    assert "Check it" in notes(r)


# ---------------------------------------------------------------- negatives: not money
@pytest.mark.parametrize("t", [
    "2 bed 1 bath, 1 550 sq ft, 100 Main St Columbus. Rent $1,400/mo",
    "Rent $1,400. Call 800 555 1234. 1 200 sq ft",
    "Rent $1,400. 3 100 Main St, Columbus OH 43201",
    "Rent $1,400. Built in 1 900 sq ft. Unit 2 300",
])
def test_negatives_other_numbers_are_not_money(t):
    r = read(t)
    assert r["price"] == 1400
    assert "looks like" not in notes(r)


def test_negative_comma_figures_and_cents_unchanged():
    r = read("Rent $1,550.50 per month. Deposit $1,550.50. 2 bed")
    assert r["price"] == 1550.5 and r["deposit"] == 1550.5
    r = read("Rent $2,300/mo. Deposit $2,300. Application fee $45.")
    assert r["price"] == 2300 and r["deposit"] == 2300


# ---------------------------------------------------------------- a deposit or fee label is never the rent
@pytest.mark.parametrize("t", [
    "Birch Flats 33 Birch Ave Oakland CA 94611. 1bd $1 8 0 0 / mo. Dep $900.",
    "1bd. Dep $900.",
    "Sec dep $900. 2 bed",
    "$900 dep. 2 bed 12 Oak St",
    "Dep: $900\n2 bed",
    "2 bed. Dep. $900",
    "Security dep $900, 2 bed",
    "Deposito $900. 2 recamaras",
])
def test_a_deposit_label_is_never_the_rent_fallback(t):
    r = read(t)
    assert r.get("price") != 900


def test_privacy_l3_spaced_digits_rent_stays_empty_with_a_note():
    r = read(fixture("r34-privacy-l3.txt"))
    assert "price" not in r
    assert "spaces between its digits" in notes(r)


def test_real_rent_with_a_dep_next_to_it_is_still_the_rent():
    r = read("1bd $1,800 / mo. Dep $900.")
    assert r["price"] == 1800
    r = read("Rent $1,800. Dep $900")
    assert r["price"] == 1800


# ---------------------------------------------------------------- promo totals and roommate splits keep the rent
def test_family_l7_promo_total_in_dotted_thousands():
    r = read(fixture("r34-family-l7.txt"))
    assert r["price"] == 2390 and r["deposit"] == 2390 and r["broker_fee"] == 1000
    n = notes(r)
    assert "$1,550 in total for the first two months" in n
    assert "promo" in n
    assert "two different rents" not in n


@pytest.mark.parametrize("t", [
    "Rent $2,390/mo. Rent $1,550 total for first two months promo.",
    "Rent $2,390/mo. Rent 1.550 total for first two months promo.",
    "Rent $2,390/mo. Rent 1 550 total for first two months promo.",
    "Rent $2,390 per month\nRent $1,550 total for the first two months",
    "$2,390/mo | Rent $1,550 total for the first 2 months (promo)",
    "Rent: $2,390. Move-in special: rent $1,550 total for first two months.",
])
def test_promo_total_gets_a_note_and_the_rent_stays(t):
    r = read(t)
    assert r["price"] == 2390
    n = notes(r)
    assert "$1,550 in total for the first" in n
    assert "two different rents" not in n


def test_promo_total_alone_is_never_the_rent():
    r = read("Rent 1.550 total for first two months promo")
    assert "price" not in r
    assert "$1,550 in total for the first two months" in notes(r)


@pytest.mark.parametrize("t", [
    "Rent $2,300 split evenly among 2 roommates",
    "Rent $2,300, split evenly between two tenants.",
    "Rent $2,300. Can be split evenly between two roommates.",
    "$2,300/mo, rent can be split equally between 2 tenants",
    "Rent: $2,300\nSplit evenly w/ roommate if you want",
    "RENT $2,300 (SPLIT EVENLY BETWEEN 2 PEOPLE)",
])
def test_roommate_split_gets_a_note_and_the_rent_stays_whole(t):
    r = read(t)
    assert r["price"] == 2300
    n = notes(r)
    assert "split between roommates" in n and "$2,300 is saved as the rent for the whole place" in n


@pytest.mark.parametrize("name,rent", [("r34-uiuc-l31.txt", 1490), ("r34-uiuc-l33.txt", 1540)])
def test_uiuc_listings_get_the_split_note(name, rent):
    r = read(fixture(name))
    assert r["price"] == rent
    assert "split between roommates" in notes(r)
    assert "not counted" not in notes(r).split("split between roommates")[0]


@pytest.mark.parametrize("t", [
    "Rent $2,000. Utilities split evenly between two tenants.",
    "Rent $2,000. Electric split evenly among roommates.",
    "Rent $2,000. Water and trash are shared equally by all tenants.",
])
def test_negatives_a_split_of_something_else_is_not_a_rent_split(t):
    r = read(t)
    assert r["price"] == 2000
    assert "split between roommates" not in notes(r)


def test_split_note_never_on_a_home_for_sale():
    r = read("Home for sale, $350,000. Closing costs split evenly between buyer and seller. 3 bed 2 bath", buying=True)
    assert "split between roommates" not in notes(r)


# ---------------------------------------------------------------- roommates l3: the two-rents note
def test_roommates_l3_gives_the_correction_note():
    r = read(fixture("r34-roommates-l3.txt"))
    assert r["price"] == 3275 and r["deposit"] == 1000 and r["parking_cost"] == 100
    n = notes(r)
    assert "it first says 1550 obo and then $3,275" in n
    assert "$3,275 is saved as the rent" in n


@pytest.mark.parametrize("t", [
    "Pilsen 3 bed 2 bath | 1550 obo no wait... 3,275 per month",
    "1550 obo no wait... 3,275 per month",
    "Rent 1550 obo. no wait 3,275 per month",
    "$1550 obo, no wait... $3,275 per month",
    "Pilsen 3 bed\n1550 obo, actually 3,275 per month",
    "1550 obo, sorry, 3,275 a month",
])
def test_decoy_obo_figure_then_correction(t):
    r = read(t)
    assert r["price"] == 3275
    assert "1550" in notes(r) and "$3,275 is saved as the rent" in notes(r)


def test_negative_plain_obo_still_the_rent_with_its_own_note():
    r = read("Nice 2 bed 1550 obo. 100 Main St")
    assert r["price"] == 1550
    assert "obo" in notes(r)


# ---------------------------------------------------------------- the web preview
def _preview(store, t):
    from conftest import local_client
    sr = store.add_search("UIUC", "rent")
    store.set_current_search(sr["id"])
    return local_client(store).post("/add/parse", data={"url": "", "text": t}).text


def test_preview_whole_rent_is_filled(store):
    r = _preview(store, fixture("r34-nontech-l7.txt"))
    assert "Filled in from what you pasted: " in r
    assert "rent" in r.split("Filled in from what you pasted:")[1].split("</p>")[0]


def test_preview_unsure_rent_is_not_called_not_found(store):
    r = _preview(store, "Rent 1 550 2 bed 1 bath apartment, 100 Main St Columbus OH")
    left = r.split("Not found in the text, so left empty:")[1].split("</p>")[0] if "Not found in the text, so left empty:" in r else ""
    assert "rent" not in left
    assert "1 550 looks like $1,550" in r


@pytest.mark.parametrize("t", [
    "Rent $2,480 per month. Rent split evenly between roommates not required.",
    "Rent $2,480. No need to split the rent between roommates.",
    "Rent $2,480. Can the rent be split evenly between two tenants? Please ask.",
    "Rent $2,480. Rent cannot be split between roommates.",
])
def test_negatives_a_split_that_is_not_offered_gets_no_split_note(t):
    r = read(t)
    assert r["price"] == 2480
    assert "split between roommates" not in notes(r)


def test_family_l5_no_split_note():
    r = read(fixture("r34-family-l5.txt"))
    assert r["price"] == 2480 and r["deposit"] == 2480
    assert "split between roommates" not in notes(r)


def test_thin_and_no_break_spaces_as_the_thousands_mark():
    from prophelper.parsers import normalize_money
    assert "$1,550" in normalize_money("Rent 1 550 per month")
    assert "$2,300" in normalize_money("Rent 2 300 dollars a month")
    assert "$2,300" in normalize_money("Rent 2 300 USD")


@pytest.mark.parametrize("t,rent", [
    ("Ihre neue Wohnung in Columbus: 2 Zimmer, 1 Bad, 1.100 USD/Monat.", 1100),
    ("Wohnung, 2 Zimmer. Miete 1.200 $ pro Monat.", 1200),
    ("Wohnung 2 Zimmer, 1.100 $/Monat", 1100),
    ("Appartement 2 pièces. Loyer 1.100 $ par mois.", 1100),
    ("Chambre. 1 200 $ / mois", 1200),
])
def test_dotted_and_spaced_rent_in_german_and_french(t, rent):
    assert read(t)["price"] == rent


def test_corpus_german_listing_reads_the_rent():
    assert read(fixture("r31-nontech-l9.txt"))["price"] == 1100


@pytest.mark.parametrize("t", [
    "Cedar Rise 3BR 2BA $2,200 fenced yard dogs ok 80 lb.",
    "Rent $2,200, dogs ok, cats ok. Deposit $2,200",
])
def test_negative_a_rent_next_to_a_pet_word_keeps_its_comma_in_the_notes(t):
    r = read(t)
    assert r["price"] == 2200
    assert "$2200" not in notes(r)
