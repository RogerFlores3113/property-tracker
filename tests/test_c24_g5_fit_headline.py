"""Cycle 24 G5 item 4: the fit headline names a failed criterion."""
import pytest

from mcp_util import call, server, text
from prophelper import enrich, compare

WORDS = ["Pets: No dogs. Cats allowed.", "Cats only, no dogs.", "No dogs allowed. Cats are fine."]


def _search(store, dealbreaker):
    srv = server(store)
    call(srv, "create_search", name="Fam", mode="rent", pet_kind="dog", budget_max=3000,
         criteria=[{"kind": "pets", "weight": 15, "dealbreaker": dealbreaker, "target": {"want": "dogs"}}])
    return srv


@pytest.mark.parametrize("words", WORDS)
def test_nice_to_have_failed_is_named_in_headline(store, words):
    srv = _search(store, False)
    out = text(call(srv, "add_place", title="Cats", address="1 A St", price=2000, beds=3, utilities_estimate=100,
                    listing_text=f"{words} Sublet through June."))
    fit = next(line for line in out.splitlines() if line.startswith("Fit:"))
    assert fit.startswith("Fit: Fits, but check (")
    assert "The pet policy: cats, wanted dogs allowed" in fit and "sublet" in fit
    listed = text(call(srv, "list_places"))
    assert "The pet policy: cats, wanted dogs allowed" in listed


@pytest.mark.parametrize("words", WORDS)
def test_must_have_failed_is_doesnt_fit_with_reason(store, words):
    srv = _search(store, True)
    out = text(call(srv, "add_place", title="Cats", address="1 A St", price=2000, beds=3, utilities_estimate=100,
                    listing_text=f"{words} Sublet through June."))
    fit = next(line for line in out.splitlines() if line.startswith("Fit:"))
    assert fit.startswith("Fit: Doesn't fit (") and "The pet policy: cats, wanted dogs allowed" in fit


def test_compare_cell_names_it(store):
    srv = _search(store, False)
    call(srv, "add_place", title="Cats", address="1 A St", price=2000, beds=3, utilities_estimate=100, listing_text="Pets: No dogs. Cats allowed.")
    call(srv, "add_place", title="Dogs", address="2 A St", price=2000, beds=3, utilities_estimate=100, listing_text="Dogs ok, no weight limit.")
    rows = {p["title"]: p for p in enrich.enrich_places(store, store.get_search(1))}
    assert "The pet policy: cats, wanted dogs allowed" in compare._fit_cell(rows["Cats"])["text"]
    assert "pet policy" not in compare._fit_cell(rows["Dogs"])["text"]
