"""Cycle 27 G2: one general correction step (rent, deposit, HOA, property tax, fees), deposits in months, deposit notes that agree with the field."""
import os
import pytest

from prophelper.parsers import parse_listing

P = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel") + "/"
R = "2 bed 2 bath apartment. 100 Main St Urbana IL 61801. "
C = "Condo $250,000. 2 bed 2 bath. 100 Main St Columbus OH 43201. "


def read(t, buying=False):
    return parse_listing(t, "", buying=buying)


def notes(r):
    return r.get("found_in_listing", "") or ""


def saved(name):
    return open(P + name).read()


# ---- rent: five layouts
@pytest.mark.parametrize("t", [
    R + "Rent $1,500/mo, corrected: now $1,450/mo. Electric tenant.",  # same line
    R + "Rent $1,500/mo. Correction: rent is now $1,450.",  # next sentence
    R + "Rent: $1,500 (now $1,450). Electric tenant.",  # X (now Y)
    R + "Rent $1,500. Updated: $1,450 per month.",  # updated:
    R + "$1,500/mo. Corrected: rent now $1,450.",  # reviewer: family
    R + "Rent $1,500/mo. Corrected: 1 bath, not 2. Rent is now $1,450.",  # after a Corrected line
    R + "Corrected: rent is $1,450, not $1,500.",  # not X
    R + "Rent $1,500. Rent was $1,500, now $1,450 per month.",  # was X, now Y
])
def test_rent_correction_layouts(t):
    r = read(t)
    assert r["price"] == 1450
    n = notes(r)
    assert ("corrects the rent" in n and "not used" in n) or "price was cut from $1,500" in n  # a "was X, now Y" keeps its price-cut note
    assert "$1,500" in n and n.count("$1,500") == 1  # one short note names the old value


def test_uiuc_l15_rent_and_baths():
    r = read(saved("r26-uiuc-l15.txt"))
    assert r["price"] == 1385 and r["baths"] == 1 and r["deposit"] == 1420  # the deposit is stated as $1,420, the rent is corrected
    assert "earlier $1,420 is not used" in notes(r) and "bathroom count" in notes(r)


def test_uiuc_l9_rent_after_other_text():
    r = read(saved("r26-uiuc-l9.txt"))
    assert r["price"] == 1360
    assert "corrects the rent" in notes(r) and "earlier $1,380 is not used" in notes(r)


def test_nontech_l28_rent_and_deposit():
    r = read(saved("r26-nontech-l28.txt"))
    assert r["price"] == 1325 and r["deposit"] == 1325
    n = notes(r)
    assert "corrects the rent" in n and "corrects the deposit" in n and n.count("$1,275") == 2


def test_roommates_l30_sentences_after_a_corrected_line():
    r = read(saved("r26-roommates-l30.txt"))
    assert r["price"] == 3300 and r["deposit"] == 1650 and r["beds"] == 3
    assert "earlier $3,400 is not used" in notes(r)


def test_family_l23_rent():
    r = read(saved("r26-family-l23.txt"))
    assert r["price"] == 2325
    assert "earlier $2,350 is not used" in notes(r)


# ---- deposit: five layouts
@pytest.mark.parametrize("t", [
    R + "Rent $1,500. Deposit $1,500. Corrected: deposit now $1,400.",  # next sentence
    R + "Rent $1,500. Security deposit was $1,500, now $1,400.",  # was X, now Y
    R + "Rent $1,500. Security deposit: $1,500 (now $1,400).",  # X (now Y)
    R + "Rent $1,500. Security deposit $1,500. Updated: $1,400.",  # updated:
    R + "Rent $1,500. Security deposit $1,500. Correction: the deposit is now $1,400.",
    R + "Rent $1,500. Security deposit $1,500, corrected to $1,400.",  # same line
])
def test_deposit_correction_layouts(t):
    r = read(t)
    assert r["deposit"] == 1400 and r["price"] == 1500, t
    n = notes(r)
    assert "$1,500" in n and "deposit" in n and "not used" in n


def test_deposit_correction_never_changes_rent():
    r = read(R + "Rent $1,500. Security deposit was $1,500, now $1,400.")
    assert r["price"] == 1500 and "price was cut" not in notes(r)


# ---- HOA and property tax (buyer): five layouts each
@pytest.mark.parametrize("t,hoa", [
    (C + "HOA $150/mo. Corrected: HOA is now $210/mo.", 210),
    (C + "HOA was $340/mo, now $385/mo.", 385),
    (C + "HOA $150/mo (now $175/mo).", 175),
    (C + "HOA $150 monthly. Updated: $175 monthly.", 175),
    (C + "HOA fee $150/month. Correction: HOA fee is now $175/month.", 175),
    (C + "HOA $150/month, corrected to $175/month.", 175),
])
def test_hoa_correction_layouts(t, hoa):
    r = read(t, buying=True)
    assert r["hoa"] == hoa and r["price"] == 250000, t
    n = notes(r)
    assert "corrects the HOA" in n and "not used" in n and "landlord" not in n.replace("the seller or listing agent", "")


@pytest.mark.parametrize("t,tax", [
    (C + "Property tax was $4,200, updated: $4,800/yr.", 4800),
    (C + "Taxes $3,000/yr. Corrected: taxes now $3,300/yr.", 3300),
    (C + "Property taxes: $3,000/yr (now $3,300/yr).", 3300),
    (C + "Property tax $3,000 per year. Correction: property tax is now $3,300 a year.", 3300),
    (C + "Property tax $3,000/yr. Updated: $3,300/yr.", 3300),
    (C + "Property tax $250/mo. Corrected: property tax now $275/mo.", 3300),  # monthly figures become yearly
])
def test_tax_correction_layouts(t, tax):
    r = read(t, buying=True)
    assert r["property_tax"] == tax and r["price"] == 250000, t
    assert "corrects the property tax" in notes(r) and "not used" in notes(r)


def test_buyer_l10():
    r = read(saved("r26-buyer-l10.txt"), buying=True)
    assert r["hoa"] == 210 and r["property_tax"] == 4400 and r["baths"] == 2
    assert "earlier $150 a month is not used" in notes(r)


def test_buyer_l13():
    r = read(saved("r26-buyer-l13.txt"), buying=True)
    assert r["hoa"] == 385 and r["property_tax"] == 4800 and r["price"] == 329000
    n = notes(r)
    assert "earlier $340 a month is not used" in n and "earlier $4,200 a year is not used" in n


def test_hoa_was_now_never_becomes_the_price():
    r = read("Condo $250,000. 2 bed 2 bath. HOA was $340/mo, now $385/mo.", buying=True)
    assert r["price"] == 250000 and r["hoa"] == 385 and "monthly amount, not an asking price" not in notes(r)


# ---- fees
def test_application_fee_correction():
    r = read(R + "Rent $1,500. Application fee $50. Corrected: application fee now $40.")
    assert r["application_fee"] == 40 and "earlier $50 is not used" in notes(r)


# ---- a correction that cannot be placed is quoted, never silently dropped
def test_unplaced_correction_is_quoted():
    r = read(R + "Rent $1,500/mo. Deposit $1,500. Corrected: now $1,450 per month.")
    assert r["price"] == 1500 and r["deposit"] == 1500
    assert 'could not match' in notes(r) and "Corrected: now $1,450 per month" in notes(r)


# ---- no regression: words that are not corrections
@pytest.mark.parametrize("t,price", [
    (R + "Now leasing! Rent $1,500. Available now, deposit $1,500.", 1500),
    (R + "Rent $1,500. Was $1,500, now $1,400 if you sign by Dec 1.", 1500),
    (R + "Updated kitchen, new carpet. Rent $1,500. Deposit $1,500.", 1500),
    ("Clintonville Updated Condo $289,000. 2 bed 2 bath.", None),
])
def test_not_a_correction(t, price):
    r = read(t, buying=price is None)
    assert "corrects the" not in notes(r) and "could not match" not in notes(r)
    if price:
        assert r["price"] == price


# ---- item 2: deposits in months and refundable "deposit or fee"
@pytest.mark.parametrize("t,months", [
    ("Security deposit: half month", 0.5),
    ("Security deposit: half month's rent", 0.5),
    ("Half month security deposit", 0.5),
    ("Security deposit half month rent", 0.5),
    ("Security deposit is half a month's rent", 0.5),
    ("Sec dep 1.5 months", 1.5),
    ("Sec dep: 1.5 months of rent", 1.5),
    ("Security deposit due at signing: one month", 1.0),
    ("Deposit due at signing equal to one month", 1.0),
    ("Security deposit due at signing equal to 1.5 months", 1.5),
])
def test_deposit_in_months(t, months):
    r = read(R + "Rent $1,400. " + t + ". Application $40.")
    assert r["price"] == 1400 and r["deposit"] == months * 1400, t
    n = notes(r)
    assert f"${months * 1400:,.0f}" in n and "Worked out" in n


def test_older_month_wording_still_reads():
    r = read(R + "Rent $1,400. Deposit: two months. Application $40.")
    assert r["deposit"] == 2800


def test_deposit_months_from_saved_listings():
    for name, mult in (("r26-uiuc-l9.txt", 0.5), ("r26-uiuc-l16.txt", 1.5), ("r26-uiuc-l18.txt", 1), ("r26-nontech-l31.txt", 0.5), ("r26-family-l24.txt", 0.5),
                       ("r26-family-l27.txt", 1), ("r26-roommates-l27.txt", 0.5)):
        r = read(saved(name))
        base = r["deposit"] - (50 if name.endswith("roommates-l27.txt") else 0)  # l27 adds a $50 key deposit
        assert abs(base - mult * r["price"]) < 0.01, name


def test_deposit_or_fee_refundable():
    r = read(saved("r26-family-l25.txt"))
    assert r["deposit"] == 1000 and "refundable, so it is read as the security deposit" in notes(r)


def test_deposit_or_fee_not_refundable_stays_unread():
    r = read(R + "Rent $1,500. Deposit or fee: $1,000 non-refundable.")
    assert r.get("deposit") in (None, 0)


@pytest.mark.parametrize("t", [
    "Pet deposit: one month. Rent $1,400.",
    "Parking deposit half month. Rent $1,400.",
    "Key deposit 1.5 months. Rent $1,400.",
])
def test_named_deposit_in_months_is_not_the_security_deposit(t):
    r = read(R + t)
    assert not r.get("deposit")


def test_deposit_months_without_rent_is_left_empty():
    r = read("2 bed apartment 100 Main St Urbana IL. Sec dep 1.5 months. Call for price.")
    assert not r.get("deposit")


# ---- item 3: no note that contradicts the saved deposit
def test_sec_dep_due_at_signing_is_not_a_move_in_total():
    r = read(saved("r26-uiuc-l13.txt"))
    assert r["deposit"] == 900 and "in total to move in" not in notes(r)


@pytest.mark.parametrize("t", ["Sec dep $900 due at signing.", "Security deposit $900 due at signing.", "Deposit: $900 due at signing."])
def test_deposit_due_at_signing_layouts(t):
    r = read(R + "Rent $1,350. " + t)
    assert r["deposit"] == 900 and "in total to move in" not in notes(r)


def test_move_in_total_is_still_a_note():
    r = read(R + "Rent $1,350. $2,500 total to move in.")
    assert "in total to move in" in notes(r)


def test_nonrefundable_deposit_note_keeps_no_question_when_deposit_read():
    r = read(saved("r26-uiuc-l1.txt"))
    assert r["deposit"] == 2287.5
    assert "Ask if there is also a refundable security deposit" not in notes(r)
    assert "$250 deposit is not refundable" in notes(r)


def test_nonrefundable_only_still_asks():
    r = read(R + "Rent $1,500. Non-refundable deposit $250.")
    assert "Ask if there is also a refundable security deposit" in notes(r)


# ---- item 4: a named-clause deposit is never the security deposit's unknown
def test_compare_names_the_parking_deposit():
    from prophelper import money
    t = saved("r26-roommates-l27.txt")
    r = read(t)
    place = {k: v for k, v in r.items() if k != "found_in_listing"}
    place["reader_notes"] = r.get("found_in_listing")
    c = money.true_monthly_cost(place, "rent")
    label = c.get("listing_notes_label") or ""
    assert "$200 parking deposit" in label and label != "the $200 deposit in the listing notes"


# ---- item 5: a narrow range keeps its note on a saved place too
def test_narrow_range_note_stays_after_saving():
    from prophelper.parsers import reader_notes_for
    t = saved("r26-roommates-l33.txt")
    r = read(t)
    assert r["price"] == 3500 and "rent range of $3,300 to $3,500" in notes(r)
    place = {k: v for k, v in r.items() if k != "found_in_listing"}
    place["listing_text"] = t
    assert "rent range of $3,300 to $3,500" in reader_notes_for(place)


@pytest.mark.parametrize("t", [
    "3BR/2BA $3,300 - $3,500 depending on floor. 100 Main St Chicago IL 60608.",
    "2 bed 1 bath, rent from $1,450 to $1,500 depending on the unit. 100 Main St Chicago IL 60608.",
    "1 bed 1 bath $1,200 - $1,250 / month, 100 Main St Chicago IL 60608.",
])
def test_narrow_range_note_layouts(t):
    r = read(t)
    assert "rent range of" in notes(r) and r["price"] in (3500, 1500, 1250)
