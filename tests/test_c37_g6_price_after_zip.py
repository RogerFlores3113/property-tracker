"""Cycle 37 G6 item 4 (buyer): a price right after a ZIP code ("Columbus OH 43209. $299,000.") is the asking price, with or without tax or HOA after it."""
import pytest

from prophelper.parsers import parse_listing


def read(text):
    return parse_listing(text, "", buying=True)


@pytest.mark.parametrize("text", [
    "Condo near Columbus OH 43209. $299,000 Tax $3,000/yr",
    "Nice condo\nColumbus OH 43209. $299,000 tax $3,500/yr",
    "Nice condo, Columbus OH 43209. $299,000 tax $3,500/yr",
    "Nice condo\n4 Oak St, Columbus OH 43209. $299,000. HOA $260 per month. Tax $3,500/yr.",
    "Nice condo\n4 Oak St, Columbus OH 43209 - $299,000 - 2 bed",
    "Nice condo\n4 Oak St, Columbus OH 43209.\n$299,000.",
    "Columbus OH 43209. $299,000.",
    "Condo, Columbus OH 43209. $299,000 HOA $200 / mo",
    "Nice condo\nCall 555-1212. Columbus OH 43209. $299,000. 2 bed 2 bath",
])
def test_price_after_zip(text):
    out = read(text)
    assert out["price"] == 299000
    assert "clear asking price" not in (out.get("found_in_listing") or "")


def test_the_tax_after_the_price_is_still_the_tax_and_hoa_the_hoa():
    out = read("Nice condo\nColumbus OH 43209. $299,000 tax $3,500/yr HOA $260 per month")
    assert out["price"] == 299000 and out["property_tax"] == 3500 and out["hoa"] == 260


def test_negatives_a_tax_or_hoa_figure_is_never_the_price():
    out = read("Condo. HOA $260 per month. Taxes $3,500 a year. Columbus OH 43209.")
    assert out.get("price") in (None, "") 
    out = read("Condo. Property tax $29,000 per year. Columbus OH 43209.")
    assert out.get("price") in (None, "")
