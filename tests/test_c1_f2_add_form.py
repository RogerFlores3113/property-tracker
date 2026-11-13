"""Cycle 1, fixer F2: the paste-and-review form shows the key facts first and folds the rest."""
import re
from pathlib import Path

from conftest import local_client
from prophelper import parsers

TEXT = """The Lofts at Green Street
412 Green Street, Champaign, IL 61820
$1,495/mo 2 Beds 1 Bath 880 sq ft
Available Aug 1, 2027. 12 month lease. Security deposit $1,500
Rent includes: water, trash. Tenant pays electric, internet.
In-unit washer/dryer. Garage parking $75/mo.
Cats and dogs under 50 lbs, $35/mo pet rent. Application fee $55 per adult.
"""
TOP = ["price", "address", "beds", "baths", "sqft", "available_from", "lease_months", "utilities_included", "laundry", "parking", "pets", "deposit"]


def _names(html: str) -> set[str]:
    return set(re.findall(r'<(?:input|select|textarea)[^>]*\bname="(\w+)"', html))


def test_review_form_folds_the_rest_and_loses_no_field(store):
    store.add_search("UIUC", "rent")
    c = local_client(store)
    html = c.post("/add/parse", data={"text": TEXT}).text
    head, _, folded = html.partition('class="sub-card more-details"')
    assert folded, "the More details fold is missing"
    for name in TOP:
        assert f'name="{name}"' in head, name
    assert 'name="notes"' not in head and 'name="insurance"' not in head
    assert "More details" in folded
    assert "Also in the listing" in html and "50 lbs" in html and "per adult" in html
    # nothing the shared facts form has may be missing from the Add page
    partial = Path(__file__).parent.parent / "src/prophelper/templates/_place_fields.html"
    wanted = set(re.findall(r'\{\{\s*(?:field|select)\(.*?,\s*"(\w+)",\s*(?:v\.get|\[)', partial.read_text())) | {"listing_text"}
    assert wanted <= _names(html), wanted - _names(html)


def test_saving_from_the_folded_form_works(store):
    store.add_search("UIUC", "rent")
    c = local_client(store)
    r = c.post("/add/save", data={"title": "The Lofts at Green Street", "address": "412 Green Street", "price": "1495", "hoa": "10"},
               follow_redirects=False)
    assert r.status_code in (302, 303)
    assert store.list_places()[0]["title"] == "The Lofts at Green Street"


def test_parser_finds_the_top_fields():
    got = parsers.parse_listing(TEXT)
    for k in ("price", "address", "beds", "baths", "sqft", "available_from", "lease_months", "laundry", "parking", "pets", "deposit"):
        assert k in got, k
    assert got["utilities_included"] == "water, trash"
