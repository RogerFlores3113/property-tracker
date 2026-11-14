"""Cycle 12 joins: items found while joining the five groups."""
from prophelper import parsers


def test_one_time_fee_right_after_a_pet_sentence_is_the_pet_fee():
    r = parsers.parse_listing("1bd $1,300/mo. Pets ok. One time fee $200.")
    assert r["pet_fee"] == 200 and "move_in_fees" not in r


def test_pet_one_time_fee_leaves_other_fees_alone():
    r = parsers.parse_listing("1bd $1,300/mo. Pets ok. One-time fee: $200. Admin fee $100.")
    assert r["pet_fee"] == 200 and r["move_in_fees"] == 100


def test_one_time_fee_after_a_non_pet_sentence_stays_a_move_in_fee():
    r = parsers.parse_listing("1bd $1,300/mo. No smoking. One time fee $200.")
    assert r["move_in_fees"] == 200 and "pet_fee" not in r


def test_reduced_off_the_deposit_is_not_a_price_cut():
    r = parsers.parse_listing("Sunny 2bd $1,900/mo. (REDUCED $1,950 off the deposit) 12 month lease.")
    assert r["price"] == 1900 and r["lease_months"] == 12
    assert "Price reduced" not in (r.get("found_in_listing") or "")


def test_a_real_price_cut_is_still_read():
    r = parsers.parse_listing("House $300,000. Price reduced $10,000.", buying=True)
    assert "Price reduced $10,000" in r["found_in_listing"]
