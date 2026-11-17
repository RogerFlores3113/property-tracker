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
