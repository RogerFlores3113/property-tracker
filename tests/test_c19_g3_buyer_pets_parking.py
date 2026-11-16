"""Cycle 19, group G3: buyer money (closing costs, HO6 insurance, percent seller credit, monthly assessment, HOA snow), pet limits,
parking cost and options, and in-unit laundry wording. Each item has the reviewer's phrasing and at least two more layouts."""
import pytest

from prophelper import money
from prophelper.parsers import parse_listing

SALE = "Condo for sale $400,000. 2 bed 2 bath. HOA $300/mo. Taxes $5,000/yr.\n"
RENT = "Apartment for rent $1,500/mo. 1 bed 1 bath.\n"


def buy(extra):
    return parse_listing(SALE + extra, buying=True)


def rent(extra):
    return parse_listing(RENT + extra)


def notes(r):
    return r.get("found_in_listing") or ""


# 1. closing costs the listing states
@pytest.mark.parametrize("text", ["Closing costs paid by buyer: $4,800", "Buyer closing costs (est): $4,800", "$4,800 closing costs paid by buyer",
                                  "- Closing costs due from buyer $4,800"])
def test_stated_closing_costs_win(text):
    r = buy(text)
    assert r["closing_costs"] == 4800
    assert "4,800" not in notes(r)
    cash = money.cash_to_close({**r, "price": 400000})
    assert not any(p.get("estimated") for p in cash["parts"] if p["label"] == "Closing costs")


def test_seller_paid_closing_costs_are_not_the_buyer_figure():
    r = buy("Closing costs paid by seller: $4,800")
    assert "closing_costs" not in r


# 2. buyer insurance
@pytest.mark.parametrize("text,yearly", [("HO6 $55/mo", 660), ("HO-6 insurance about $55 a month", 660), ("condo insurance $660/yr", 660),
                                         ("$55/mo HO6 insurance", 660), ("Insurance:\n- HO6 policy $55 per month", 660)])
def test_ho6_fills_insurance(text, yearly):
    r = buy(text)
    assert r["insurance"] == yearly
    assert "not counted anywhere" not in notes(r)


def test_condo_word_alone_is_not_insurance():
    r = parse_listing("Condo $400,000. 2 bed 2 bath.", buying=True)
    assert "insurance" not in r


# 3. percent seller concession
@pytest.mark.parametrize("text", ["Seller will contribute 2% of the price toward closing", "Seller credit: 2% of purchase price",
                                  "Seller concessions 2% toward closing costs"])
def test_percent_credit_with_known_price(text):
    r = buy(text)
    assert r["seller_credit"] == 8000
    assert "2%" in notes(r) and "$8,000" in notes(r) and "$400,000" in notes(r)


def test_percent_credit_without_price_is_only_a_note():
    r = parse_listing("2 bed 2 bath condo for sale. Seller will contribute 2% of the price toward closing", buying=True)
    assert "seller_credit" not in r
    assert "2%" in notes(r)


@pytest.mark.parametrize("text", ["Seller concessions up to 3% toward closing costs", "Seller will pay 3% of closing costs"])
def test_percent_cap_or_percent_of_closing_stays_unknown(text):
    r = buy(text)
    assert "seller_credit" not in r and "3%" in notes(r)


# 4. monthly special assessment counts in the monthly cost
@pytest.mark.parametrize("text,end", [("special assessment $150/mo through 2029", "2029"), ("Monthly special assessment of $150 (ends 2029)", "2029"),
                                      ("- $150/month special assessment until 2029", "2029")])
def test_monthly_assessment_counts_in_hoa(text, end):
    r = buy(text)
    assert r["hoa"] == 450
    assert "special_assessment" not in r
    assert end in notes(r) and "$150" in notes(r)


def test_monthly_assessment_alone_becomes_the_hoa():
    r = parse_listing("Condo for sale $400,000. 2 bed. Special assessment $150/mo through 2029", buying=True)
    assert r["hoa"] == 150 and "2029" in notes(r)


def test_monthly_assessment_the_seller_pays_is_not_added():
    r = buy("Seller pays the special assessment $150/mo through 2029")
    assert r["hoa"] == 300


# 5. HOA covers snow
@pytest.mark.parametrize("text", ["HOA includes trash and snow removal", "HOA covers: snow removal, trash, water", "Landlord pays snow removal and lawn care."])
def test_hoa_covered_snow_has_no_note(text):
    assert "who pays" not in notes(buy(text))


def test_snow_without_a_payer_still_gets_a_note():
    assert "snow removal but doesn't say who pays" in notes(buy("Utilities: snow removal"))


# 6. pet limits
@pytest.mark.parametrize("text", ["1 dog max, 40 lb", "Pets: 1 dog max (40 lbs)", "- 1 dog max\n- 40 lb limit"])
def test_dog_count_and_weight(text):
    r = rent(text)
    assert r["pet_weight_limit"] == 40 and r["pet_count_limit"] == 1
    assert "not clear if it is a limit" not in notes(r)


@pytest.mark.parametrize("text", ["No dogs over 35 lbs. Cats ok", "Pets: cats ok, no dogs over 35 lbs", "Cats ok\nNo dogs over 35 lbs"])
def test_no_dogs_over_weight_allows_small_dogs(text):
    r = rent(text)
    assert r["pets"] == "both" and r["pet_weight_limit"] == 35


def test_pet_limit_that_can_be_waived_is_left_alone():
    r = rent("Pet limit 25 lbs, can be waived.")
    assert "pet_weight_limit" not in r


def test_case_by_case_pets_stay_unknown_with_a_weight_rule():
    r = rent("Pets considered case by case, no dogs over 50 pounds. Max 1 pet.")
    assert "pets" not in r


# 7. parking
@pytest.mark.parametrize("text", ["free off-street parking", "Surface lot, free", "Parking is free", "- Free surface lot"])
def test_free_parking_is_zero(text):
    r = rent(text)
    assert r["parking_cost"] == 0


def test_parking_permit_yearly_still_counts_monthly():
    r = rent("Parking permit $240/yr")
    assert r["parking_cost"] == 20


@pytest.mark.parametrize("text", ["Parking: $0 (open lot), Covered $45", "Parking: free surface lot\nCovered: $45/mo", "Parking: $0 open lot / $45 covered",
                                  "Parking:\n- Open lot $0\n- Covered $45/mo"])
def test_parking_options_take_the_cheapest(text):
    r = rent(text)
    assert r["parking_cost"] == 0 and r["parking"] == "lot"
    n = notes(r)
    assert "$45" in n and "not counted" not in n


def test_required_garage_with_other_fees_on_the_line_is_not_an_option_list():
    r = rent("Parking: $175/month garage, required. Admin fee $150 per applicant. Broker fee: one month.")
    assert r["parking_cost"] == 175 and r["parking"] == "garage"


def test_pipe_table_parking_cell_is_read_alone():
    r = parse_listing("South Loop 3 BR | $3,300 /mo | Parking: required garage space $185/mo | Amenity fee $100/month | Admin fee $250")
    assert r["parking_cost"] == 185


# 8. laundry
@pytest.mark.parametrize("text", ["wash/dry in unit", "W/D in unit", "washer/dryer in-unit", "Laundry: wash/dry in unit", "Wash & dry in unit"])
def test_in_unit_laundry_wordings(text):
    assert rent(text)["laundry"] == "in_unit"


@pytest.mark.parametrize("text", ["No wash/dry in unit", "No washer/dryer in unit", "In-unit W/D hookups (washer and dryer not provided)"])
def test_laundry_negatives_stay_out_of_the_unit(text):
    assert rent(text).get("laundry") != "in_unit"
