"""Cycle 20, G5 items 2 and 3: plain 'no address yet' hint, commute as a hard limit."""
import pytest

from mcp_util import call, server, text
from prophelper import enrich, redflags
from conftest import local_client


def test_no_address_is_a_plain_hint_not_a_scam_sign(store):
    store.add_search("C", "rent")
    p, _ = store.add_place(title="No addr", price=1000, listing_text="Sunny flat near campus.")
    out = text(call(server(store), "list_places"))
    line = [l for l in out.splitlines() if f"#{p['id']}" in l][0]
    assert "no address yet" in line and "possible scam" not in line.lower()


def test_real_scam_flag_keeps_the_scam_tag(store):
    store.add_search("C", "rent")
    p, _ = store.add_place(title="Scam", price=1000, listing_text="Send the deposit by gift card before you see it.")
    out = text(call(server(store), "list_places"))
    line = [l for l in out.splitlines() if f"#{p['id']}" in l][0]
    assert "possible scam" in line.lower()


def test_helpers_split_hints():
    flags = ["There is no address yet. Ask for one before you go anywhere or pay anything.", "It mentions Zelle."]
    assert redflags.scam_sign_flags(flags) == ["It mentions Zelle."]
    assert redflags.is_plain_hint(flags[0]) and not redflags.is_plain_hint(flags[1])


def test_board_shows_no_address_plainly(store):
    store.add_search("C", "rent")
    store.add_place(title="No addr", price=1000, listing_text="Sunny flat near campus.")
    html = local_client(store).get("/board").text
    assert "No address yet" in html and "thing to check" not in html
