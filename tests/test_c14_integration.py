"""Cycle 14 joins: items found while joining the four groups."""
from prophelper import money, parsers


def test_studio_to_one_bed_plan_range_leaves_beds_empty():
    r = parsers.parse_listing("Studio-1BR Prairie Commons from $1,299 - $1,420. Parking not available.")
    assert r["title"] == "Prairie Commons" and "beds" not in r
    assert '"Studio-1BR", which covers more than one layout' in r["found_in_listing"]


def test_included_parking_in_a_buy_search_gets_no_note():
    r = parsers.parse_listing("Condo 2BR $299,000. Parking: 1 deeded space included.", buying=True)
    assert r["parking"] == "lot" and "parking" not in (r.get("found_in_listing") or "").lower()


def test_buy_parking_with_a_price_still_gets_its_note():
    r = parsers.parse_listing("Condo 2BR $299,000. Parking $100/month.", buying=True)
    assert "The cost of buying does not count parking" in r["found_in_listing"]


def test_owner_paid_hoa_note_does_not_set_the_uncounted_tag():
    r = parsers.parse_listing("Oakmont townhome $2,250/mo. 3 bed 2 bath. Quarterly HOA $240 paid by owner.")
    assert "hoa" not in r and "owner pays the HOA" in r["found_in_listing"]
    assert not money.listing_notes_uncounted(r["found_in_listing"])
