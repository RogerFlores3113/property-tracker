"""Cycle 13 joins: items found while joining the five groups."""
from prophelper import money, parsers


def test_cat_fee_is_the_pet_fee():
    r = parsers.parse_listing("Maple Court 2bd $1,500/mo. Water/sewer billed back by usage. Trash $15/mo. Cats ok. Cat fee $150.")
    assert r["pets"] == "cats" and r["pet_fee"] == 150 and r["other_monthly_fees"] == 15
    assert "Cat fee" not in (r.get("found_in_listing") or "")


def test_dog_fee_per_month_is_pet_rent():
    r = parsers.parse_listing("2bd $1,500/mo. Dogs ok. Dog fee $25/month.")
    assert r["pet_rent"] == 25 and "pet_fee" not in r


def test_placed_amount_note_does_not_fire_the_uncounted_tag():
    r = parsers.parse_listing("Hilliard 2bd $1,450. Utilities: Tenant pays all. Trash included. Credit check $25. Gym access fee $30/mo mandatory.")
    assert r["application_fee"] == 25 and r["other_monthly_fees"] == 30
    assert not money.listing_notes_uncounted(r["found_in_listing"])
    assert money.listing_notes_uncounted("Credit check $25. It is not counted anywhere.")
