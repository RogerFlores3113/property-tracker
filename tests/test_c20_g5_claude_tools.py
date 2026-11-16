"""Cycle 20, G5 items 5 and 6: add_place seller credit and utilities source, restore of a link with a space."""
import pytest

from mcp_util import call, server, text


@pytest.mark.parametrize("listing", ["Charming condo listed at $335,000. Seller credit 2% toward closing. HOA $200/month.",
                                     "Price $335,000. The seller will give 2% of the price toward closing costs.",
                                     "Listed $335,000\nSeller concession: 2% of price toward closing"])
def test_explicit_zero_seller_credit_wins_and_notes_say_so(store, listing):
    store.add_search("B", "buy")
    out = text(call(server(store), "add_place", title="Condo", address="5 B St", price=335000, seller_credit=0, listing_text=listing))
    p = store.get_place(1)
    assert p["seller_credit"] == 0
    assert "saved as the seller credit" not in out and "saved as the seller credit" not in p["reader_notes"]
    assert "not saved because the value given was $0" in p["reader_notes"] and "2%" in p["reader_notes"]
    store.update_place(1, by="ai", notes="x")  # a later save keeps the same honest note
    assert "saved as the seller credit" not in store.get_place(1)["reader_notes"]


def test_listing_percent_is_still_saved_when_no_credit_was_sent(store):
    store.add_search("B", "buy")
    call(server(store), "add_place", title="Condo", address="5 B St", price=335000, listing_text="Charming condo listed at $335,000. Seller credit 2% toward closing.")
    p = store.get_place(1)
    assert p["seller_credit"] == 6700 and "saved as the seller credit" in p["reader_notes"]


def test_utilities_estimate_without_source_is_added_by_claude(store):
    store.add_search("R", "rent")
    out = text(call(server(store), "add_place", title="Flat", address="6 B St", price=1500, utilities_estimate=120))
    assert "Utilities guessed" not in out and "added by Claude" in out
    p = store.get_place(1)
    line = [l for l in __import__("prophelper.enrich", fromlist=["x"]).enrich_place(store, p, store.current_search())["cost"]["lines"] if l["key"] == "utilities"][0]
    assert line["label"] == "Utilities (added by Claude)" and line["amount"] == 120


def test_explicit_guess_source_is_still_a_guess(store):
    store.add_search("R", "rent")
    out = text(call(server(store), "add_place", title="Flat", address="6 B St", price=1500, utilities_estimate=120, utilities_source="guess"))
    assert "Utilities guessed" in out


def test_update_place_estimate_also_added_by_claude(store):
    store.add_search("R", "rent")
    call(server(store), "add_place", title="Flat", address="6 B St", price=1500)
    out = text(call(server(store), "update_place", place_id=1, utilities_estimate=95))
    assert "Utilities guessed" not in text(call(server(store), "get_place", place_id=1))
