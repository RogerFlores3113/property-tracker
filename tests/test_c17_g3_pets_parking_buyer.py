"""Cycle 17, group G3: seller-paid closing money, fenced patio vs yard, priced parking, pet deposit and pet notes.
Each reviewer phrasing plus other natural wordings pins exact field values."""
import pytest

from prophelper.money import cash_to_close, open_listing_notes
from prophelper.parsers import parse_listing

BUY = "Condo for sale $300,000. 1 Main St Unit 2, Columbus, OH 43215. 2 bed 2 bath. HOA $300/mo. "
RENT = "2 bd apartment for rent $1,800/mo. 100 Main St, Chicago, IL 60614. "


def buy(text):
    return parse_listing(BUY + text, buying=True)


def rent(text, pet_kind="dog"):
    return parse_listing(RENT + text, pet_kind=pet_kind)


def notes(r):
    return r.get("found_in_listing") or ""


# ---- 1. seller pays closing costs: a credit only
@pytest.mark.parametrize("text,credit", [
    ("Seller will pay $7,000 in closing costs.", 7000),
    ("Seller will pay $7,000 in closing costs. Transfer fee paid by buyer $1,500.", 7000),
    ("Seller to pay $5,500 of the buyer's closing costs.", 5500),
    ("Seller-paid closing costs: $3,500.", 3500),
    ("Closing costs paid by seller up to... $4,000 credit at closing", None),
])
def test_seller_pays_closing_is_credit_not_cost(text, credit):
    r = buy(text)
    assert r.get("closing_costs") is None
    if credit:
        assert r["seller_credit"] == credit


def test_seller_pays_closing_cash_to_close_uses_estimate():
    r = buy("Seller will pay $7,000 in closing costs. Transfer fee paid by buyer $1,500.")
    place = {"price": 300000, **{k: r.get(k) for k in ("closing_costs", "seller_credit")}}
    cash = cash_to_close(place)
    # 20% down 60,000 + a 3% guess 9,000 - 7,000 credit
    assert cash["total"] == 62000 and cash["has_estimate"] is True
    assert "$1,500 transfer fee" in notes(r)


@pytest.mark.parametrize("text", [
    "Seller will pay $7,000 in closing costs. Transfer fee paid by buyer $1,500.",
    "Transfer fee paid by buyer $1,500. Seller will pay $6,000 in closing costs.",
    "Buyer pays a $1,500 transfer fee. Seller contributes $6,000 toward closing.",
])
def test_buyer_transfer_fee_is_never_dropped_silently(text):
    r = buy(text)
    assert "$1,500" in notes(r)
    assert r.get("closing_costs") is None


def test_stated_buyer_closing_costs_still_read_beside_seller_credit():
    r = buy("Estimated closing costs $8,000. Seller closing help $5,000.")
    assert r["closing_costs"] == 8000 and r["seller_credit"] == 5000
    r = buy("Seller will pay $4,000 in closing costs. Buyer's estimated closing costs $9,500.")
    assert r["closing_costs"] == 9500 and r["seller_credit"] == 4000


@pytest.mark.parametrize("text,credit", [
    ("Seller closing help: $4,500", 4500),
    ("Seller closing help $5,000", 5000),
    ("Seller help with closing: $3,000", 3000),
    ("Seller assistance toward closing costs $2,500", 2500),
    ("Seller closing assistance of $6,000", 6000),
])
def test_seller_closing_help_is_a_credit(text, credit):
    r = buy(text)
    assert r["seller_credit"] == credit and "not counted anywhere" not in notes(r)


@pytest.mark.parametrize("text", [
    "Seller will pay up to $6,000 toward closing",
    "Seller will contribute up to $6,000 toward closing costs",
    "Seller credit up to $6,000 at closing",
])
def test_seller_cap_is_not_a_missing_cost(text):
    r = buy(text)
    assert r.get("seller_credit") is None and r.get("closing_costs") is None
    assert open_listing_notes(notes(r), r) == []  # the monthly headline has nothing "not counted yet"


@pytest.mark.parametrize("text", [
    "Seller-paid assessments: $2,000",
    "Seller paid assessments $2,000",
    "Owner-paid special assessment: $2,000",
])
def test_seller_paid_assessment_is_read_with_its_payer(text):
    r = buy(text)
    assert r["special_assessment"] == 2000 and r["special_assessment_payer"] == "seller"
    assert r.get("seller_credit") is None  # the seller pays the association, so the buyer's cash is not lowered
    assert open_listing_notes(notes(r), r) == []


@pytest.mark.parametrize("text", [
    "Monthly condo fee 385", "Monthly condo fee 385.", "Monthly condo fee: 385", "Condo fee 385 per month", "Monthly HOA fee 385. Taxes $3,900/yr.",
])
def test_bare_condo_fee_is_the_hoa(text):
    r = parse_listing("Victorian Village Condo for sale - $312,500\n2 bed. " + text + "\n", buying=True)
    assert r["hoa"] == 385


def test_bare_fee_without_monthly_word_is_not_guessed():
    r = parse_listing("Condo for sale $312,500. Condo fee 385. 2 bed.", buying=True)
    assert r.get("hoa") is None


# ---- 2. fenced patio is not a yard
@pytest.mark.parametrize("text", [
    "Fenced patio only, shared green space.",
    "Fenced balcony.", "Fully fenced courtyard.", "Large fenced back patio.", "Back patio is fenced in.",
    "Fenced dog run on site.", "Gated patio with deck.", "Fence around the patio.",
])
def test_fenced_patio_is_not_a_fenced_yard(text):
    assert rent("Dogs ok. " + text).get("fenced_yard") is None


@pytest.mark.parametrize("text", [
    "Fence around back.", "Fenced back.", "Fence in the back.", "Back of the house is fenced.", "Fenced yard.", "Fully fenced backyard.", "Yard is fenced.",
])
def test_fenced_yard_wordings(text):
    assert rent("3 bd house. Dogs ok. " + text).get("fenced_yard") == 1


def test_no_yard_still_zero():
    assert rent("No yard, small patio. Dogs ok.").get("fenced_yard") == 0


# ---- 3. priced parking
@pytest.mark.parametrize("text,cost,kind", [
    ("Parking: 1 assigned space $40/mo, additional spaces $60.", 40, "lot"),
    ("1 assigned space $40/mo", 40, "lot"),
    ("Parking: 1 reserved spot, $55 a month.", 55, "lot"),
    ("1 assigned space at $40 per month", 40, "lot"),
])
def test_priced_assigned_space(text, cost, kind):
    r = rent(text)
    assert r["parking_cost"] == cost and r["parking"] == kind


def test_additional_space_price_is_quoted_not_counted():
    r = rent("Parking: 1 assigned space $40/mo, additional spaces $60.")
    assert "$60" in notes(r) and "optional" in notes(r) and "not counted in the monthly cost" in notes(r)


@pytest.mark.parametrize("text,cost", [
    ("Parking: 2 spots, required, $175 each per month.", 350),
    ("Parking required for 2 cars, $150 per space.", 300),
    ("Two parking spots required at $100 each/mo.", 200),
])
def test_required_spaces_each_are_multiplied(text, cost):
    r = rent(text)
    assert r["parking_cost"] == cost and "not counted anywhere" not in notes(r)


def test_optional_spaces_stay_notes():
    r = rent("Parking: 2 spots, optional, $175 each per month.")
    assert r.get("parking_cost") is None and "optional" in notes(r)


@pytest.mark.parametrize("text,cost", [
    ("Parking: street permit $25/yr", 2.08),
    ("Street permit: $300 per year.", 25),
    ("Parking: street permit $25 annually", 2.08),
])
def test_yearly_permit_is_a_monthly_share(text, cost):
    r = rent(text)
    assert r["parking_cost"] == cost and r["parking"] == "street"
    n = notes(r)
    assert "a year" in n and "not counted anywhere" not in n


def test_monthly_permit_still_monthly():
    assert rent("Parking permit $15/mo.")["parking_cost"] == 15


def test_surface_lot_with_covered_choice_saves_the_free_lot():
    r = rent("Parking: surface lot included, covered $35. In-unit washer/dryer.")
    assert r["parking"] == "lot" and r["parking_cost"] == 0  # cycle 26: a free spot beside a priced upgrade is $0 (was the best kind offered in cycle 19)
    assert "$35" in notes(r)


@pytest.mark.parametrize("text,kind", [
    ("Parking: surface lot included, covered $40/mo.", "lot"),  # cycle 26: the free lot is the parking, the covered spot is an optional upgrade
    ("Parking: off-street, carport $30 extra.", "lot"),
    ("Parking: covered, assigned.", "covered"),
])
def test_parking_label_first_part_sets_the_type(text, kind):
    assert rent(text)["parking"] == kind


# ---- 4. pets
@pytest.mark.parametrize("text", [
    "Dogs and cats allowed, 2 pet max, 50 lb limit. $250 per pet deposit, $25/mo per pet.",
    "Pets OK. Pet deposit: $250 per pet. $25/mo per pet.",
    "Pets OK, deposit $250 per pet, $25 per month per pet.",
    "Pets allowed: $250 deposit per pet and $25 per month per pet.",
])
def test_per_pet_deposit_and_rent(text):
    r = rent(text)
    assert r["pet_deposit"] == 250 and r["pet_rent"] == 25 and r.get("pet_fee") is None
    n = notes(r)
    assert "not counted anywhere" not in n and "monthly fee" not in n


@pytest.mark.parametrize("text", [
    "Pets welcome. Pet rent $40/mo, no pet deposit.",
    "Pets welcome. Pet rent $40 a month. No pet deposit.",
    "Cats OK, no deposit for pets, $40/mo pet rent.",
])
def test_no_pet_deposit_is_zero(text):
    r = rent(text)
    assert r["pet_deposit"] == 0 and r["pet_rent"] == 40


def test_plain_no_deposit_is_not_a_pet_deposit():
    r = rent("Pets welcome. Pet rent $40/mo. No security deposit required.")
    assert r.get("pet_deposit") is None


@pytest.mark.parametrize("text", [
    "Dogs: 2 allowed, max 60 lbs each. Pet rent $50 total.",
    "Dogs: up to 2, max 60 lbs each. Pet rent $50 total.",
    "Dogs: 2 max, 60 lb limit. Pet rent $50 a month total.",
])
def test_dogs_with_a_count_means_dogs_allowed(text):
    r = rent(text)
    assert r["pets"] == "dogs" and r["pet_rent"] == 50 and r["pet_weight_limit"] == 60 and r["pet_count_limit"] == 2
    assert "Dogs: 2 allowed" not in notes(r)  # the read pet line is not quoted again


def test_pet_charges_not_a_gap_with_pet_rent_and_known_pets():
    from prophelper.compare import _pet_charges_unknown
    place = {"cost": {"pets_counted": True}, "pets": "dogs", "pet_rent": 50}
    assert _pet_charges_unknown(place) is False


HUB = ("LUXE 1x1 | $1,585/mo | The Hub-style living\nUnit 410, 33 N Neil St, Champaign. W/D in unit * DW * heated garage $120/mo (required for all residents) * "
       "Water, sewer, trash all included * Electric not included, budget about $75 * {pets} * built 2024 * 11-month lease available, also 12-month * "
       "Amenity package $35/month (pool, gym) *\n")


@pytest.mark.parametrize("pets", [
    "pets welcome (dogs 40 lb max, 2 pets max)",
    "pets ok (dogs 40 lb max, 2 pets max)",
    "pets allowed (dogs 40 lb limit, 2 pets max)",
])
def test_bullet_quote_does_not_carry_the_pet_line(pets):
    r = parse_listing(HUB.format(pets=pets))
    assert r["pet_weight_limit"] == 40 and r["pet_count_limit"] == 2
    n = notes(r)
    assert "40 lb" not in n and "pets welcome" not in n and "pets ok" not in n and "pets allowed" not in n
    assert r.get("utilities_estimate") == 75  # cycle 17 join: G1 now counts the electric budget, so it is not quoted
