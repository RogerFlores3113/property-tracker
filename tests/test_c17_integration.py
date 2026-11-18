"""Cycle 17 join tests: behaviour that depends on more than one group's change."""
import pytest

from mcp_util import call, server, text
from prophelper import parsers


@pytest.mark.parametrize("paste", [
    "2 bed 1 bath, $1,300/mo, near downtown (Linden). Text 555-0100 if interested.",
    "$1,250 a month. 2BR in Linden. Heat included. No smoking.",
])
def test_mcp_add_place_with_only_listing_text_gets_a_title(store, paste):
    store.add_search("C", "rent")
    out = text(call(server(store), "add_place", listing_text=paste))
    assert "needs at least a title" not in out
    assert store.get_place(1)["title"]


def test_seller_pays_closing_is_a_credit_and_buyer_transfer_fee_is_quoted():
    text_ = ("3 bed house for sale. Price $310,000. Seller will pay $7,000 in closing costs. "
             "Transfer fee paid by buyer $1,500. HOA $0.")
    o = parsers.parse_listing(text_, buying=True)
    assert o.get("seller_credit") == 7000
    assert o.get("closing_costs") is None


def test_buyer_transfer_fee_counted_when_no_seller_help():
    o = parsers.parse_listing("Condo for sale, $240,000. Transfer fee paid by buyer $1,500.", buying=True)
    assert o.get("closing_costs") is None  # cycle 35: the fee is a named one-time item, not the total
