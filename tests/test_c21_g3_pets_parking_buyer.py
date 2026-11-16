"""Cycle 21, group 3: buyer HOA, tax, closing and seller credit wordings, buy-mode parking, rent parking shapes, fenced yards,
"all sizes" dogs and pet lines that the fields already hold."""
import pytest

from prophelper.parsers import parse_listing, reconcile_seller_credit_note
from prophelper.scoring import _says_all_sizes

BUY = "Condo for sale $300,000. 12 Main St, Columbus OH 43201. 2 bed 2 bath 900 sq ft.\n"
RENT = "2BR apartment, $1,400/mo, 12 Main St, Springfield IL.\n"


def buy(text):
    return parse_listing(BUY + text, buying=True)


def rent(text):
    return parse_listing(RENT + text)


def notes(r):
    return r.get("found_in_listing") or ""


# ---- 1. buyer money
@pytest.mark.parametrize("line", ["No HOA info yet.", "No HOA information available.", "HOA: no details listed yet."])
def test_no_hoa_info_stays_unknown_with_a_note(line):
    r = buy(line)
    assert "hoa" not in r
    assert "HOA is left empty" in notes(r) or "hoa" in notes(r).lower()


@pytest.mark.parametrize("line", ["No HOA.", "No HOA fees.", "HOA: none"])
def test_plain_no_hoa_is_still_zero(line):
    assert buy(line)["hoa"] == 0


@pytest.mark.parametrize("line", ["Assoc fee $265/mo.", "Assoc. dues $265 per month.", "Association fee: $265/mo"])
def test_assoc_fee_is_the_hoa(line):
    r = buy(line)
    assert r["hoa"] == 265
    assert "not counted" not in notes(r)


@pytest.mark.parametrize("line", ["Monthly HOA assessment: $310 (includes water, exterior, snow removal).",
                                  "Monthly HOA assessment $310.", "Monthly HOA dues: $310 (covers water and exterior)."])
def test_monthly_hoa_assessment_is_the_hoa(line):
    r = buy(line)
    assert r["hoa"] == 310


@pytest.mark.parametrize("line,tax", [("Property taxes run roughly $3,400/yr.", 3400), ("Property taxes come to about $3,400 a year.", 3400),
                                      ("Taxes total $3,400/yr.", 3400), ("Property tax is roughly $283/mo.", 3396)])
def test_property_tax_wordings(line, tax):
    assert buy(line)["property_tax"] == tax


@pytest.mark.parametrize("line", ["Closing costs for the buyer around $6,900.", "Buyer closing costs run about $6,900.", "Closing around $6,900."])
def test_closing_cost_wordings(line):
    r = buy(line)
    assert r["closing_costs"] == 6900


def test_seller_credit_and_due_at_closing_are_not_the_closing_costs():
    r = buy("Seller credit at closing: $5,000. Earnest money due at closing $1,000.")
    assert "closing_costs" not in r


LISTING_L1 = ("Olentangy Row Condo | Offered at $312,500\n2200 Olentangy River Rd #5B, Columbus, OH 43202\n2 beds, 2 baths, 1,020 sq ft. Built 2001.\n"
              "Monthly HOA assessment: $310 (includes water, exterior, snow removal). Property taxes run roughly $3,400/yr.\n"
              "HO6 policy (about $55/mo) required by lender. Seller is offering a 2.5% credit to buyer.\n"
              "One assigned garage spot included; second spot $120/mo. Closing costs for the buyer around $6,900.\n")


def test_l1_whole_listing():
    r = parse_listing(LISTING_L1, buying=True)
    assert (r["hoa"], r["property_tax"], r["closing_costs"], r["seller_credit"], r["insurance"]) == (310, 3400, 6900, 7812.5, 660)
    n = notes(r)
    assert "utility" not in n.lower()
    assert "Monthly HOA assessment" not in n and "Property taxes run" not in n and "Closing costs for the buyer" not in n


# ---- 2. seller credit note only when the saved credit differs
NOTE = ("The listing says the seller gives 2.5% of the price toward closing. At a price of $312,500 that is $7,812 (2.5% x $312,500), "
        "saved as the seller credit. Ask the seller's agent to confirm.")


@pytest.mark.parametrize("saved", [7812.5, 7812, "7812.5", 7813])
def test_seller_credit_note_untouched_when_it_is_what_was_saved(saved):
    assert reconcile_seller_credit_note(NOTE, saved) == NOTE


def test_seller_credit_note_changes_when_a_different_credit_is_saved():
    out = reconcile_seller_credit_note(NOTE, 5000)
    assert "stays $5,000" in out and "not saved because the value given was $5,000" in out


# ---- 3. buy-mode parking
def test_buy_second_space_has_one_truthful_note():
    r = buy("HOA dues: $420/mo. Parking garage $150/mo extra for a second space.")
    assert "parking_cost" not in r and "other_monthly_fees" not in r
    assert "counted in other monthly fees" not in notes(r)
    assert notes(r).count("not counted anywhere") == 1


@pytest.mark.parametrize("line", ["Parking: free covered spot.", "Parking $0.", "2-car attached garage."])
def test_buy_free_parking_makes_no_not_counted_note(line):
    r = buy(line)
    assert "parking" not in notes(r).lower() or "not counted" not in notes(r)


@pytest.mark.parametrize("line,yearly", [("Parking: street permit $96 per year.", 96), ("Street parking permit $100/yr.", 100), ("Parking: permit $240 annually.", 240)])
def test_buy_yearly_permit_is_shown_as_yearly(line, yearly):
    r = buy(line)
    n = notes(r)
    assert f"${yearly} a year" in n
    assert "$8 parking" not in n and "is counted" not in n and "parking_cost" not in r


# ---- 4. rent parking
@pytest.mark.parametrize("line", ["Garage parking available at $165/month.", "Garage available for $165 a month.", "Parking: garage available, $165/mo."])
def test_optional_garage_with_price_is_noted(line):
    r = rent(line)
    assert r.get("parking_cost") is None
    assert "$165" in notes(r) and "optional" in notes(r)


@pytest.mark.parametrize("line", ["Parking: 1 space included, 2nd $90.", "Parking: 1 space included; 2nd space $90.", "One spot included, second spot is $90/mo."])
def test_one_space_included_second_is_an_option(line):
    r = rent(line)
    assert r["parking_cost"] == 0
    assert "$90" in notes(r) and "optional" in notes(r)
    assert "surface lot" not in notes(r)


@pytest.mark.parametrize("line", ["Parking $0, street.", "Parking: street, $0.", "Street parking $0."])
def test_street_parking_at_zero(line):
    r = rent(line)
    assert (r["parking"], r["parking_cost"]) == ("street", 0)
    assert "could not tell" not in notes(r)


@pytest.mark.parametrize("line", ["Lot parking $0. Garage by request.", "Lot parking $0. Garage on request.", "Parking: lot, $0; garage upon request."])
def test_lot_free_and_garage_by_request(line):
    r = rent(line)
    assert (r["parking"], r["parking_cost"]) == ("lot", 0)
    assert "garage" in notes(r).lower() and "no price" in notes(r)


@pytest.mark.parametrize("line", ["Garage parking $110/mo (1st car $100 if on a 12 mo lease).", "Garage $110/mo; first car $100 with a 12 month lease."])
def test_first_car_price_counted_and_other_price_noted(line):
    r = rent(line)
    assert r["parking_cost"] == 100
    n = notes(r)
    assert "$110" in n and "counted" in n and "missing" not in n


# ---- 5. pets and yard
@pytest.mark.parametrize("text", ["Pets: dogs ok. Fenced.", "Fully fenced. Dogs welcome.", "Cats ok, fenced all around."])
def test_fenced_alone_means_fenced_yard(text):
    assert rent(text)["fenced_yard"] == 1


@pytest.mark.parametrize("text", ["6-ft fence all around. Dogs OK.", "Privacy fence all around the home.", "The lot is fenced. Dogs ok.", "Fence all around the property."])
def test_fence_all_around_means_fenced_yard(text):
    assert rent(text)["fenced_yard"] == 1


@pytest.mark.parametrize("text", ["Fence around the pool. Dogs ok.", "Fenced patio.", "Not fenced.", "Fenced dog park in the complex."])
def test_other_fences_are_not_a_fenced_yard(text):
    assert rent(text).get("fenced_yard") in (None, 0)


@pytest.mark.parametrize("text,ok", [("Dogs allowed (all sizes!) with $35/mo pet rent.", True), ("Dogs of any size welcome.", True), ("No weight limit for dogs.", True),
                                     ("Dogs ok under 50 lb.", False), ("Dogs allowed, large dogs need approval.", False)])
def test_all_sizes(text, ok):
    assert _says_all_sizes({"listing_text": text}) is ok


@pytest.mark.parametrize("line", ["Pet policy: Cats only, 1 max, $35 monthly rent, $200 fee.", "Pet rules: Cats only, 1 max, $35 monthly rent, $200 fee.",
                                  "Pets: Cats only, 1 max, $35 monthly rent, $200 fee."])
def test_pet_line_held_by_fields_makes_no_monthly_fee_note(line):
    r = rent("Utilities included.\n" + line)
    assert (r["pets"], r["pet_rent"], r["pet_fee"], r["pet_count_limit"]) == ("cats", 35, 200, 1)
    assert "monthly fee" not in notes(r)
