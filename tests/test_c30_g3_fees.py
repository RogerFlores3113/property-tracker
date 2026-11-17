"""Cycle 30 group G3: application fee beside a pet screening fee, last month's rent in a deposit line, a monthly admin fee."""
import os

from prophelper.parsers import parse_listing

HERE = os.path.join(os.path.dirname(__file__), "fixtures", "panel")


def P(text):
    return parse_listing(text, "")


def F(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as fh:
        return P(fh.read())


def notes(r):
    return r.get("found_in_listing") or ""


# ---- item 1: "Application $44/adult" is never overridden by a pet screening fee
def test_app_per_adult_beside_pet_screening():
    r = P("2 bed. Rent $1,800. Application $44/adult. Pet screening fee $20 per pet.")
    assert r["application_fee"] == 44 and r["application_fee_per_adult"] == 1
    assert "$20 pet application" in notes(r)


def test_app_per_adult_pet_screening_first():
    r = P("2 bed. Rent $1,800. Pet screening fee $20 per pet. Application $44/adult.")
    assert r["application_fee"] == 44 and r["application_fee_per_adult"] == 1


def test_app_bullets_pet_application_fee():
    r = P("Rent $1,800.\n- Application: $44 per adult\n- Pet application fee $20 per pet\n- Cats ok")
    assert r["application_fee"] == 44 and r["application_fee_per_adult"] == 1


def test_app_paren_pet_screening():
    r = P("Rent $1,800 ($44 application fee per adult, $20 pet screening per pet)")
    assert r["application_fee"] == 44


def test_pet_screening_alone_is_not_application_fee():
    r = P("Rent $1,800. Pet screening fee $20 per pet. Cats ok.")
    assert not r.get("application_fee")


# ---- item 2: last month's rent in a deposit line
def test_last_month_after_deposit_l20():
    r = F("r29-family-l20.txt")
    assert r["price"] == 2395 and r["deposit"] == 2395 and r["months_up_front"] == 2
    assert "last month" in notes(r).lower()


def test_last_month_plus_deposit_one_line():
    r = P("Rent $1,800. Deposit $1,800 plus last month")
    assert r["deposit"] == 1800 and r["months_up_front"] == 2


def test_last_month_bullet():
    r = P("Rent $1,800.\n- Deposit: $1,500\n- Last month's rent: $1,800")
    assert r["deposit"] == 1500 and r["months_up_front"] == 2


def test_last_month_move_in_dollars():
    r = P("Rent $2,000. Move-in: $500 security + last month's rent due at signing.")
    assert r["months_up_front"] == 2


def test_last_month_waived_stays_one():
    for t in ("Rent $1,800. Deposit $1,800. No last month required.",
              "Rent $1,800. Last month free. Deposit $900.",
              "Rent $1,800. Deposit equal to last month's rent."):
        assert not P(t).get("months_up_front") or P(t)["months_up_front"] == 1


# ---- item 3: a monthly admin fee is monthly
def test_admin_monthly_nontech_l5():
    r = F("r29-nontech-l5.txt")
    assert r["other_monthly_fees"] == 20 and not r.get("move_in_fees")
    assert r["months_up_front"] == 2 and r["deposit"] == 500


def test_admin_monthly_wordings():
    for t in ("Rent $1,490. Admin fee $20 monthly.", "Rent $1,490. Admin fee: $20 per month", "Rent $1,490. Monthly admin fee $20.",
              "Rent $1,490. $20/mo admin fee.", "Rent $1,490.\n- Admin fee $20 a month", "Rent $1,490. Fees: admin $20 monthly, application $40"):
        r = P(t)
        assert r["other_monthly_fees"] == 20, t
        assert not r.get("move_in_fees"), t


def test_admin_one_time_stays_move_in():
    r = P("Rent $1,490. Admin fee $75 one time.")
    assert r["move_in_fees"] == 75 and not r.get("other_monthly_fees")
    r = P("Rent $1,490. Admin fee $75 one time plus $20 monthly admin fee")
    assert r["move_in_fees"] == 75 and r["other_monthly_fees"] == 20


# ---- holding deposit with no dollar amount
def test_holding_deposit_equal_to_one_month_note():
    for t in ("Rent $1,800. Holding deposit equal to one month. Deposit $900.", "Rent $1,800. Holding deposit equal to one month's rent. Deposit $900.",
              "Rent $1,800.\n- Holding deposit: one month's rent\n- Deposit $900"):
        r = P(t)
        assert r["deposit"] == 900, t
        assert "holding fee equal to one month" in notes(r), t


# ---- non-refundable pet fee
def test_nonrefundable_pet_fee_note():
    for t in ("Rent $1,800. Pet fee $300 non-refundable per pet. Cats ok.", "Rent $1,800. Cats ok. $300 non-refundable pet fee.",
              "Rent $1,800.\n- Pets: cats ok\n- Pet fee (non-refundable): $300"):
        r = P(t)
        assert r["pet_fee"] == 300, t
        assert "$300 pet fee is not refundable" in notes(r), t


def test_refundable_pet_deposit_gets_no_nonrefundable_note():
    r = P("Rent $1,800. Cats ok, $300 pet fee, $200 refundable deposit.")
    assert r["pet_fee"] == 300 and r["pet_deposit"] == 200 and "not refundable" not in notes(r)


# ---- fenced patio and yard
def test_fenced_patio_and_yard():
    for t in ("Rent $1,800. Fenced patio and yard.", "Rent $1,800. Fenced patio & backyard", "Rent $1,800.\n- Fenced patio and yard\n- W/D",
              "Rent $1,800. Fenced patio, yard."):
        assert P(t)["fenced_yard"] == 1, t


def test_fenced_patio_alone_or_shared_yard_not_fenced_yard():
    for t in ("Rent $1,800. Fenced patio only.", "Rent $1,800. Fenced patio. No yard.", "Rent $1,800. Fenced patio and shared yard."):
        assert not P(t).get("fenced_yard"), t


def test_family_l14_fenced_patio_and_yard():
    assert F("r29-family-l14.txt")["fenced_yard"] == 1


# ---- approval required for a kind of pet is never a plain yes
def test_family_l7_pets_unknown_with_note():
    r = F("r29-family-l7.txt")
    assert not r.get("pets") and r["pet_weight_limit"] == 40 and r["pet_fee"] == 300 and r["fenced_yard"] == 1
    assert "Dogs need approval" in notes(r) and "Pets is left empty" in notes(r)


def test_approval_wordings_unknown():
    for t in ("Dogs OK, approval needed. Cats OK.", "Pet policy: dogs and cats welcome. Dogs must be approved by management.",
              "Rent $1,800. Dogs and cats ok. Approval required for dogs.", "Rent $1,800.\n- Dogs ok\n- Cats ok\n- Approval required for dogs"):
        r = P(t)
        assert not r.get("pets"), t
        assert "Dogs need approval" in notes(r), t


def test_cats_ok_with_dog_approval_keeps_cats():
    r = P("Pets: Cats allowed. Approval required for dogs.")
    assert r["pets"] == "cats" and "Dogs need approval" in notes(r)


def test_pet_application_fee_is_not_the_application_fee():
    r = P("Rent $1,425. Pets: cats yes, one-time pet fee $250, pet application fee $40. Security deposit $500.")
    assert not r.get("application_fee") and r["pet_fee"] == 250


def test_admin_comma_amount_not_monthly():
    r = P("Fees: $30 application per adult, $100 admin, $20 monthly amenity.")
    assert r["move_in_fees"] == 100 and r["other_monthly_fees"] == 20 and r["application_fee"] == 30


def test_split_pet_deposit_no_duplicate_nonrefundable_note():
    r = P("Rent $1,800. Cats ok. Pet deposit $300 ($100 non-refundable).")
    assert notes(r).count("not refundable") + notes(r).count("non-refundable") <= 2
