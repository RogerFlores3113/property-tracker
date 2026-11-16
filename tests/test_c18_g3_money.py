"""Cycle 18 G3: HOA payer on a rental, pet deposit split, general parking price, pet limits, shared yard, buyer recurring money."""
import pytest

from prophelper.parsers import parse_listing


def P(text, buying=False):
    return parse_listing(text, "", buying=buying)


def notes(r):
    return r.get("found_in_listing") or ""


# 1. condo fee / HOA on a rental counts only when the tenant pays it
@pytest.mark.parametrize("line", [
    "Monthly condo fee 385 (paid by owner).",
    "Condo fee: $385/mo, paid by the owner.",
    "- HOA $385 a month, owner pays",
    "Owner-paid HOA dues of $385 monthly.",
])
def test_rental_hoa_owner_paid_not_counted(line):
    r = P(f"South Loop condo 3BR 2BA $3,300/mo.\n{line}\nHeat included.")
    assert "hoa" not in r
    assert "385" in notes(r)


@pytest.mark.parametrize("line", [
    "Condo fee $385/mo, tenant pays.",
    "HOA: $385 per month (paid by tenant)",
    "- Tenant is responsible for the HOA fee of $385 monthly",
])
def test_rental_hoa_tenant_paid_counted(line):
    r = P(f"South Loop condo 3BR 2BA $3,300/mo.\n{line}")
    assert r["hoa"] == 385


@pytest.mark.parametrize("line", ["HOA $150/mo.", "Condo fee: $150 monthly", "- Association dues $150 per month"])
def test_rental_hoa_payer_not_said_is_a_note(line):
    r = P(f"Condo 2BR $2,000/mo.\n{line}")
    assert "hoa" not in r
    assert "150" in notes(r) and "does not say the tenant pays" in notes(r)


def test_buying_hoa_still_counted():
    r = P("Condo for sale $250,000. HOA $300/mo.", buying=True)
    assert r["hoa"] == 300


# 2. pet deposit split
@pytest.mark.parametrize("text", [
    "Pet deposit: $300 refundable + $150 non-refundable. Monthly pet rent $30.",
    "Pets welcome. $150 non-refundable pet fee and $300 refundable deposit. Pet rent $30.",
    "Pets ok\n- $300 refundable pet deposit, $150 non-refundable pet fee\n- Pet rent $30",
    "Pet deposit $300 (refundable), plus $150 non-refundable. Pet rent $30/mo",
])
def test_pet_deposit_split(text):
    r = P("2BR $2,000/mo. " + text)
    assert r["pet_deposit"] == 300
    assert r["pet_fee"] == 150
    assert r["pet_rent"] == 30


def test_pet_deposit_single_tag_unchanged():
    r = P("2BR $2,000/mo. Pet deposit $350 (non-refundable $150 of it).")
    assert r["pet_deposit"] == 200 and r["pet_fee"] == 150


# 3. required and priced parking
@pytest.mark.parametrize("text,kind,cost", [
    ("Parking: reserved garage space required, $95 per space per month.", "garage", 95),
    ("One reserved garage space per unit is required at $95 per space per month.", "garage", 95),
    ("- Reserved garage space (required): $95 per space, per month", "garage", 95),
    ("Assigned covered space $60/month", "covered", 60),
    ("Parking\n- Assigned covered space, $60 monthly", "covered", 60),
    ("Covered assigned space: $60 per month.", "covered", 60),
])
def test_parking_required_priced(text, kind, cost):
    r = P("1BR $1,430.\n" + text)
    assert r["parking"] == kind
    assert r["parking_cost"] == cost


@pytest.mark.parametrize("text", ["Parking: yearly permit $240.", "Annual parking permit: $240", "- Parking permit $240 per year"])
def test_parking_yearly_permit(text):
    r = P("3BR $2,260.\n" + text)
    assert r["parking_cost"] == 20
    assert "$240 a year" in notes(r)


def test_driveway_no_price_stays_unknown():
    r = P("Duplex $1,350.\nDriveway parking.")
    assert r["parking"] == "lot" and "parking_cost" not in r
    assert "no price" in notes(r)


@pytest.mark.parametrize("text", ["Driveway parking included.", "Free driveway parking.", "Driveway parking is free."])
def test_driveway_free(text):
    r = P("Duplex $1,350.\n" + text)
    assert r["parking"] == "lot" and r["parking_cost"] == 0


# 4. pets
@pytest.mark.parametrize("text", ["No pets over 40 lbs. Exceptions may be granted.", "No pets over 40 lbs.\nExceptions considered case by case.",
                                  "Pets: no pets over 40 lbs - exceptions may be granted"])
def test_weight_rule_with_exception_is_waivable(text):
    from prophelper.scoring import _limit_can_be_waived
    r = P("3BR $2,260.\n" + text)
    assert r["pet_weight_limit"] == 40
    assert _limit_can_be_waived({"listing_text": "3BR $2,260.\n" + text})


def test_weight_rule_alone_not_waivable():
    from prophelper.scoring import _limit_can_be_waived
    assert not _limit_can_be_waived({"listing_text": "No pets over 40 lbs. Application may be approved in 2 days."})


@pytest.mark.parametrize("text", ["1 dog max.", "Max 1 dog.", "- One dog only (1 dog max)"])
def test_one_dog_max(text):
    r = P("3BR $2,200.\n" + text)
    assert r["pets"] == "dogs" and r["pet_count_limit"] == 1


@pytest.mark.parametrize("text", ["Dogs ok 80 lb.", "Fenced yard. Dogs ok, 80 lbs.", "- Dogs allowed up to 80 lb"])
def test_dogs_ok_weight(text):
    r = P("3BR $2,200.\n" + text)
    assert r["pets"] == "dogs" and r["pet_weight_limit"] == 80


@pytest.mark.parametrize("text", ["Pet-friendly: cats under 15 lbs, $400 pet deposit, $50/month.", "Cats under 15 lbs.", "- Cats up to 15 lb"])
def test_cats_under_weight(text):
    r = P("2BR townhome $1,900.\n" + text)
    assert r["pets"] == "cats" and r["pet_weight_limit"] == 15


def test_cats_only_with_dog_search_no_pet_charge_gap():
    from prophelper import compare
    p = {"pets": "cats", "cost": {"pets_counted": True, "search_pet_kind": "dog"}}
    assert compare._pet_charges_unknown(p) is False
    p["cost"]["search_pet_kind"] = "cat"
    assert compare._pet_charges_unknown(p) is True


# 5. shared fenced yard
@pytest.mark.parametrize("text", ["Fenced yard (shared).", "Shared fenced yard.", "- Fenced yard, shared with the downstairs unit"])
def test_shared_fenced_yard(text):
    r = P("3BR $3,195.\n" + text)
    assert r["fenced_yard"] == 1
    assert "shared" in notes(r)


def test_private_fenced_yard_has_no_shared_note():
    assert "shared" not in notes(P("3BR $3,195. Private fenced yard."))


# 6. buyer recurring money
@pytest.mark.parametrize("text", ["Annual tax bill $3,600.", "Tax bill: $3,600 a year", "- Property tax bill $300/mo"])
def test_buyer_tax_bill(text):
    r = P("Condo - $318,000\n" + text, buying=True)
    assert r["property_tax"] == 3600


@pytest.mark.parametrize("text", ["Homeowners policy $85/mo.", "Homeowner's policy: $85 per month", "- Home insurance policy $85 a month"])
def test_buyer_insurance_policy(text):
    r = P("Condo - $318,000\n" + text, buying=True)
    assert r["insurance"] == 1020


@pytest.mark.parametrize("text", ["Dues $330 mo.", "Condo dues: $330/mo.", "- Assessments: $330 monthly"])
def test_buyer_dues_monthly(text):
    r = P("Flat - $264,900\n" + text, buying=True)
    assert r["hoa"] == 330
    assert "not saved" not in notes(r)


def test_buyer_assessment_for_months_is_not_hoa():
    r = P("Flat - $264,900\nAssessment for windows: $150/month for 24 months.", buying=True)
    assert "hoa" not in r
