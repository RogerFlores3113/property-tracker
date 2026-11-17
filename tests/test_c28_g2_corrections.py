"""Cycle 28 G2: a correction binds to the fact in its own clause, applies every fact it names (rent, deposit, utilities, fees, beds, baths, credit,
closing costs), more wordings ("$X ($Y now)", "(corrected: was X)"), and a saved figure that disagrees with the listing's correction gets a note."""
import os

import pytest

from mcp_util import call, server, structured
from prophelper import parsers
from prophelper.parsers import parse_listing

P = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel") + "/"
R = "2 bed 2 bath apartment. 100 Main St Urbana IL 61801. "
C = "Condo $245,000. 2 bed 2 bath. 100 Main St Columbus OH 43201. "


def read(t, buying=False, **kw):
    return parse_listing(t, "", buying=buying, **kw)


def notes(r):
    return r.get("found_in_listing", "") or ""


def saved(name):
    return open(P + name).read()


# ---- item 1: each correction binds to the fact in its own clause
def test_buyer_l13_not_5000_belongs_to_closing_costs():
    r = read(saved("r27-buyer-l13.txt"), buying=True)
    assert r["property_tax"] == 3000 and r["hoa"] == 225
    assert r["seller_credit"] == 5000 and r["closing_costs"] == 6500
    n = notes(r)
    assert "corrects the property tax" not in n
    assert "corrects the closing costs" in n and "corrects the seller credit" in n and "corrects the HOA" in n


@pytest.mark.parametrize("t,tax,credit,closing", [
    # layout 2: bullets, the old figure of the credit equals the tax
    (C + "\n- Property tax: $4,000/yr\n- HOA $300/mo\n- Corrected: seller credit is $6,000 (not $4,000)\n- Corrected: closing costs now $7,000 (was $4,000)\n", 4000, 6000, 7000),
    # layout 3: one line, "was X, now Y" and the old figure of closing costs equals the credit
    (C + "Taxes $5,200/yr. Seller credit $3,000. Closing costs $3,000. Corrected: seller credit was $3,000, now $4,500.", 5200, 4500, 3000),
    # layout 4: a correction about a thing with no field (earnest money) must not move the tax
    (C + "Taxes $3,000/yr. Corrected: earnest money is $2,500, not $3,000. Seller credit $2,000.", 3000, 2000, None),
])
def test_buyer_corrections_bind_to_their_own_clause(t, tax, credit, closing):
    r = read(t, buying=True)
    assert r["property_tax"] == tax
    assert r["seller_credit"] == credit
    assert r.get("closing_costs") == closing
    assert "corrects the property tax" not in notes(r)


def test_earnest_money_correction_is_quoted_not_bound():
    r = read(C + "Taxes $3,000/yr. Corrected: earnest money is $2,500, not $3,000.", buying=True)
    assert r["property_tax"] == 3000
    assert "earnest money" in notes(r)


@pytest.mark.parametrize("t,dep,fee", [
    (R + "Rent $1,500. Deposit $1,200. Pet fee $300. Corrected: pet fee is $250 (not $1,200).", 1200, None),
    (R + "Rent $1,500. Deposit $1,500. Corrected: deposit is $1,000, not $1,500.", 1000, None),
    (R + "Rent $1,500\nDeposit $900\nApplication fee $900\nCorrected: application fee $50 (was $900)", 900, 50),
])
def test_rental_old_value_equal_to_another_field(t, dep, fee):
    r = read(t)
    assert r["price"] == 1500 and r["deposit"] == dep
    if fee is not None:
        assert r["application_fee"] == fee


# ---- item 2: every fact a correction names
def test_uiuc_l17_update_rent_utilities_deposit():
    r = read(saved("r27-uiuc-l17.txt"))
    assert r["price"] == 1640 and r["deposit"] == 1640 and r["utilities_estimate"] == 110
    assert "all" not in (r.get("utilities_included") or "")
    assert "tenant_pays" in r and "electric" in r["tenant_pays"]
    n = notes(r)
    assert "corrects the utilities" in n and "corrects the rent" in n


@pytest.mark.parametrize("t", [
    R + "Rent $1,595. Utilities included in rent.\nUpdate: rent now $1,640. Utilities are paid by the tenant now (about $110).",
    R + "Rent $1,595, all utilities included. Corrected: rent $1,640, utilities now tenant pays about $110/mo.",
    R + "Rent $1,595.\n- All utilities included\n- Corrected: all utilities now paid by tenant, est. $110",
])
def test_utilities_correction_layouts(t):
    r = read(t)
    assert r["price"] in (1595, 1640)
    assert r["utilities_estimate"] == 110
    assert "all" not in (r.get("utilities_included") or "")
    assert "electric" in r["tenant_pays"]
    assert "corrects the utilities" in notes(r)


def test_utilities_correction_to_included():
    r = read(R + "Rent $1,500. Tenant pays all utilities, about $150.\nUpdate: all utilities now included in rent.")
    assert "tenant_pays" not in r or not r["tenant_pays"]
    assert "utilities_estimate" not in r
    assert "corrects the utilities" in notes(r)


def test_roommates_l7_amenity_fee_corrected():
    r = read(saved("r27-roommates-l7.txt"))
    assert r["price"] == 3240 and r["other_monthly_fees"] == 70  # amenity $45 + valet trash $25
    n = notes(r)
    assert "corrects the amenity fee: it is now $45" in n and "The earlier $35 is not used" in n and "corrects the rent" in n


@pytest.mark.parametrize("t,field,val", [
    (R + "Rent $1,500. Pet rent $50/mo. Corrected: pet rent is $40/mo.", "pet_rent", 40),
    (R + "Rent $1,500. Pet rent $50/mo. Pet rent was $50, now $40/mo.", "pet_rent", 40),
    (R + "Rent $1,500.\n- Valet trash $25/mo\n- Update: valet trash fee is now $30/mo", "other_monthly_fees", 30),
])
def test_other_fee_corrections(t, field, val):
    r = read(t)
    assert r[field] == val
    assert "corrects the" in notes(r)


def test_fee_correction_without_an_earlier_statement_is_counted():
    r = read(R + "Rent $1,500. Corrected: amenity fee is $45/mo.")
    assert r["other_monthly_fees"] == 45


@pytest.mark.parametrize("t,baths", [
    (R.replace("2 bath", "2 bath") + "Rent $1,500. Corrected: baths are 1.5.", 1.5),
    (R + "Rent $1,500. Update: bathrooms: 1.5", 1.5),
    (R + "Rent $1,500\nCorrected: baths now 1", 1),
])
def test_baths_correction_layouts(t, baths):
    r = read(t)
    assert r["baths"] == baths
    assert "bathroom count" in notes(r)


def test_roommates_l12_baths_and_deposit():
    r = read(saved("r27-roommates-l12.txt"))
    assert r["baths"] == 1.5 and r["deposit"] == 2500 and r["price"] == 3300


def test_beds_correction_by_name():
    r = read("3 bed 2 bath apartment. 100 Main St Urbana IL 61801. Rent $1,500. Corrected: beds are 2.")
    assert r["beds"] == 2 and "bedroom count" in notes(r)


# ---- item 3: more wordings
@pytest.mark.parametrize("t,rent", [
    ("Fourth Street Flats | 1 Bed 1 Bath | $1,410 ($1,370 now) | 308 S 4th St Champaign IL 61820", 1370),
    ("1 bed 1 bath. 308 S 4th St Champaign IL 61820. $1,410 ($1,370 now). Garage $70/mo", 1370),
    ("1 bed 1 bath\n308 S 4th St Champaign IL 61820\nRent: $1,410/mo ($1,370/mo now)", 1370),
])
def test_figure_then_bracket_now(t, rent):
    r = read(t)
    assert r["price"] == rent
    assert "corrects the rent" in notes(r)


def test_uiuc_l15_whole_listing():
    r = read(saved("r27-uiuc-l15.txt"))
    assert r["price"] == 1370 and r["deposit"] == 1370 and r["application_fee"] == 35
    assert "$1,410 is not used" not in notes(r) or "corrects the rent" in notes(r)


@pytest.mark.parametrize("t,credit", [
    (C + "Seller credit: $2,000 (now $3,500). Taxes $3,000/yr.", 3500),
    (C + "Seller credit $2,000. Corrected: seller credit is now $3,500.", 3500),
    (C + "Seller concessions were $2,000, now $3,500 toward closing costs. Taxes $3,000/yr.", 3500),
])
def test_seller_credit_wordings(t, credit):
    r = read(t, buying=True)
    assert r["seller_credit"] == credit and r.get("property_tax", 3000) == 3000
    assert "corrects the seller credit" in notes(r)


def test_buyer_l10_whole_listing():
    r = read(saved("r27-buyer-l10.txt"), buying=True)
    assert r["seller_credit"] == 3500 and r["hoa"] == 460 and r["property_tax"] == 6200


@pytest.mark.parametrize("t,dep", [
    (R + "Rent $1,370. Security deposit: $700 (updated: $1,370).", 1370),
    (R + "Rent $1,370. Security deposit $2,310 (corrected: was $3,000).", 2310),
    (R + "Rent $2,310. Security deposit $2,310 (corrected: was $3,000)", 2310),
    (R + "Rent $2,310.\nSecurity deposit: $2,310 (corrected, was $3,000)", 2310),
])
def test_deposit_wordings(t, dep):
    r = read(t)
    assert r["deposit"] == dep
    n = notes(r)
    assert "price was cut" not in n and "rent dropped" not in n
    assert "corrects the deposit" in n


def test_family_l35_deposit_is_not_a_price_cut():
    r = read(saved("r27-family-l35.txt"))
    assert r["price"] == 2310 and r["deposit"] == 2310
    assert "price was cut" not in notes(r) and "corrects the deposit" in notes(r)


@pytest.mark.parametrize("t", [
    "3 bed 2 bath, $3,225/mo. 1900 W Cermak Rd Chicago 60608. Lease 12 months. Rent now $3,195 with 13-month lease.",
    "3 bed 2 bath, $3,225/mo. 1900 W Cermak Rd Chicago 60608. Lease 12 months. Rent now $3,195 for a 13 month lease.",
])
def test_lease_length_price_is_one_note(t):
    r = read(t)
    assert r["price"] == 3225
    n = notes(r)
    assert n.count("$3,195") == 1 and "13 month lease" in n and "depends on the condition" not in n


def test_roommates_l10_one_note_for_13_month_price():
    r = read(saved("r27-roommates-l10.txt"))
    assert r["price"] == 3225 and notes(r).count("$3,195") == 1


# ---- item 4: the old figure is named once, as superseded, never as an amount left out
def test_old_figures_are_named_only_as_not_used():
    r = read(saved("r27-roommates-l7.txt"))
    n = notes(r)
    assert "price was cut" not in n
    for line in n.split("\n"):
        if "$3,290" in line or "$35" in line:
            assert "corrects the" in line and "is not used" in line


# ---- item 5: the saved rent disagrees with the corrected one
def test_saved_rent_differs_from_corrected_rent_in_listing_text():
    t = "2 bed 2 bath. 100 Main St Urbana IL 61801. Rent $2,350/mo. Corrected: rent now $2,325. Tenant pays electric."
    r = read(t, current={"price": 2350})
    n = notes(r)
    assert "corrected to $2,325" in n and "saved on this place is $2,350" in n
    assert "corrected to" not in notes(read(t, current={"price": 2325}))
    assert "corrected to $2,325" in parsers.reader_notes_for({"listing_text": t, "price": 2350})


def test_mcp_add_place_conflict_note(store):
    srv = server(store)
    call(srv, "create_search", name="S", mode="rent", area="Urbana", budget_max=2500)
    t = "2 bed 2 bath. 100 Main St Urbana IL 61801. Rent $2,350/mo. Corrected: rent now $2,325. Tenant pays electric."
    call(srv, "add_place", title="Elm", address="100 Main St", price=2350, listing_text=t)
    place = [p for p in store.list_places() if p["title"] == "Elm"][0]
    assert place["price"] == 2350  # what Claude sent is kept
    assert "corrected to $2,325" in place["reader_notes"] and "saved on this place is $2,350" in place["reader_notes"]
    store.update_place(place["id"], price=2325)
    assert "corrected to" not in store.get_place(place["id"])["reader_notes"]
