"""Cycle 22 G2: one-time fees counted once, optional amenity, background check per adult, last month's rent, beds/baths shorthand, promo notes."""
import os
from pathlib import Path

import pytest

from prophelper.parsers import parse_listing

P = Path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel") + "")
B = "2 bed 1 bath, $1,500/mo. 12 Oak St, Champaign IL 61820. "


def _saved(name):
    f = P / name
    if not f.exists():
        pytest.skip("saved listing not available")
    return parse_listing(f.read_text())


def _notes(o):
    return o.get("found_in_listing") or ""


@pytest.mark.parametrize("text,fees,app", [
    (B + "Lease processing fee $75, application fee $30.", 75, 30),
    (B + "Fees: lease processing fee $75; app fee $30", 75, 30),
    (B + "- Lease processing fee: $75\n- Application fee: $30", 75, 30),
    (B + "Processing fee $60 due at signing.", 60, None),
])
def test_fee_counted_once(text, fees, app):
    o = parse_listing(text)
    assert o["move_in_fees"] == fees
    assert o.get("application_fee") == app


def test_saved_l15():
    o = _saved("r21-uiuc-l15.txt")
    assert o["move_in_fees"] == 75 and o["application_fee"] == 30


@pytest.mark.parametrize("text,fees", [
    (B + "Fees: admin $150, lease processing $100, one time amenity fee $200, key deposit $75.", 525),
    (B + "Fees: admin $150, non-refundable amenity $200", 350),
    (B + "- Admin $150\n- One-time amenity $200", 350),
    (B + "$250 amenity fee one-time", 250),
    (B + "Amenity fee $35 per month, admin $100", 100),
])
def test_one_time_amenity(text, fees):
    assert parse_listing(text)["move_in_fees"] == fees


def test_saved_roommates_l30():
    o = _saved("r21-roommates-l30.txt")
    assert o["move_in_fees"] == 525 and o["deposit"] == 1260 and o["application_fee"] == 25 and o["application_fee_per_adult"] == 1
    assert "background check" in _notes(o)


@pytest.mark.parametrize("text", [
    B + "Background check $25 each.",
    B + "Background check: $25 per adult.",
    B + "Application $25 background check each.",
    B + "$25 background check each.",
])
def test_background_check_per_adult(text):
    o = parse_listing(text)
    assert o["application_fee"] == 25 and o["application_fee_per_adult"] == 1
    assert "background check" in _notes(o)


def test_background_added_to_per_adult_fee():
    o = parse_listing(B + "Application fee $35 per adult, background check $20 each.")
    assert o["application_fee"] == 55 and o["application_fee_per_adult"] == 1


def test_background_with_separate_fee_not_summed_silently():
    o = parse_listing(B + "Application fee $40. Background check $25 each.")
    assert o["application_fee"] == 40
    assert "$25" in _notes(o) and "background check" in _notes(o)


@pytest.mark.parametrize("f", ["r21-roommates-l35.txt", "r21-uiuc-l9.txt"])
def test_saved_background(f):
    o = _saved(f)
    assert o["application_fee"] == 25 and o["application_fee_per_adult"] == 1


@pytest.mark.parametrize("text", [B + "Fees: App $55, admin $200.", B + "App: $55. Admin $200", B + "Fees: App $55; admin $200"])
def test_app_fee_label(text):
    o = parse_listing(text)
    assert o["application_fee"] == 55 and o["move_in_fees"] == 200


@pytest.mark.parametrize("text", [
    B + "Last month's rent plus first month required.",
    B + "First and last month due at signing.",
    B + "First + last month's rent.",
    B + "Last month and first month's rent due at move-in.",
])
def test_last_month(text):
    o = parse_listing(text)
    assert o["months_up_front"] == 2 and not o.get("deposit")
    assert "last month" in _notes(o).lower()


def test_saved_nontech_l11():
    o = _saved("r21-nontech-l11.txt")
    assert o["months_up_front"] == 2 and not o.get("deposit")


@pytest.mark.parametrize("text,beds,baths", [
    ("3/2? No - 2 bed 1.5 bath townhome, $1,495", 2, 1.5),
    ("3/2, no, 2 bed 1 bath house $1,400", 2, 1),
    ("Updated: 3x2? actually 2 bed 1 bath, $1,200", 2, 1),
    ("Townhome Condo, 2/2, $335,000", 2, 2),
    ("Condo 3/2, $289,000 in Dayton OH", 3, 2),
    ("Studio-1BR Place | 1 Bed 1 Bath $1,545. 12 Oak", 1, 1),
    ("Studio/2BR | 2 Bed 2 Bath $1,845", 2, 2),
])
def test_beds_baths(text, beds, baths):
    o = parse_listing(text)
    assert o["beds"] == beds and o["baths"] == baths


def test_studio_range_with_two_layouts_stays_unknown():
    o = parse_listing("Studio-1BR Place | studio $900, 1 Bed 1 Bath $1,545, 2 Bed 2 Bath $1,900")
    assert o.get("beds") is None


@pytest.mark.parametrize("f,beds,baths", [("r21-nontech-l3.txt", 2, 1.5), ("r21-buyer-l6.txt", 2, 2), ("r21-uiuc-l14.txt", 1, 1)])
def test_saved_beds(f, beds, baths):
    o = _saved(f)
    assert o["beds"] == beds and o["baths"] == baths


@pytest.mark.parametrize("text,phrase", [
    (B + "Move-in special: 1/2 month free.", "1/2 month free"),
    (B + "Move-in special: half a month free.", "half a month free"),
])
def test_half_month_promo_named(text, phrase):
    assert phrase in _notes(parse_listing(text))
    assert "2 month free" not in _notes(parse_listing(text)).replace("1/2 month free", "")


@pytest.mark.parametrize("text", [
    B + "Garage $140 per month, free for the first 3 months.",
    B + "Parking: $140/mo, free for first 6 months",
])
def test_free_for_first_months_named(text):
    o = parse_listing(text)
    assert "free for" in _notes(o) and o["price"] == 1500
