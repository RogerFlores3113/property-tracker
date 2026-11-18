"""Cycle 37 G5: Compare never marks a total "(best)", and the summary never calls a place "cheapest", when the same page calls its cost not complete without
saying so. A total that is not complete says "(not complete)"."""
import pytest
from c37_g5_util import F, add, search
from mcp_util import call, server, text

from prophelper import compare, enrich


def _rows(store, s, *ids):
    pl = [enrich.enrich_places(store, s, [store.get_place(i)])[0] for i in ids]
    return pl, compare.build_rows(pl)


def _row(sections, key):
    for sec in sections:
        for r in sec["rows"]:
            if r["key"] == key:
                return r


def _gap_place(store, s, title, price, **kw):
    p, _ = store.add_place(search_id=s["id"], title=title, address=f"{title} St", price=price, **kw)
    return p["id"]


@pytest.mark.parametrize("cheap,dear", [(1450, 1700), (1000, 1500), (2100, 2600)])
def test_place_with_unknown_utilities_never_best_over_complete(store, cheap, dear):
    s = search(store)
    full = dict(utilities_included="All utilities included", deposit=500, parking="street", parking_cost=0, pet_rent=0, other_monthly_fees=0)
    a = _gap_place(store, s, "Gap", cheap, tenant_pays="electric, gas")  # utilities not priced
    b = _gap_place(store, s, "Full", dear, **full)
    c = _gap_place(store, s, "Full2", dear + 300, **full)
    pl, sections = _rows(store, s, a, b, c)
    row = _row(sections, "cost")
    gap, full_cell, _c = row["cells"]
    assert gap["incomplete"] and not gap["best"], gap
    assert full_cell["best"] and "(best)" in full_cell["marker"]
    out = text(call(server(store), "compare_places", place_ids=[a, b, c]))
    assert "cheapest" not in out.replace("looks cheaper", "") or "not complete" in out or "aren't counted" in out


def test_buyer_listing_with_left_out_one_time_parts_is_not_best(store):
    s = search(store, mode="buy")
    a, _ = add(store, s, "German", F("r36-buyer-l6.txt"))
    b, _ = add(store, s, "Arena", "Arena Condo for sale $259,000. 2 bed 2 bath. 55 Arena St Columbus OH 43215. HOA $200/month. Taxes $3,000/yr. Insurance $90 a month. "
               "Seller credit $3,000. Closing costs $7,000. Survey $400. Title insurance $1,500.")
    pl, sections = _rows(store, s, a, b)
    row = _row(sections, "cost")
    assert any(compare.cost_incomplete(p) for p in pl)
    for p, cell in zip(pl, row["cells"]):
        if compare.cost_incomplete(p):
            assert cell["incomplete"] and not cell["best"] and "(best)" not in cell["marker"], (cell, p["title"])
            assert "not complete" in cell["text"] or "not counted" in cell["text"] or "as listed" in cell["text"]
        else:
            assert "not complete" not in cell["text"]


def test_cheapest_sentence_says_what_is_left_out(store):
    s = search(store)
    full = dict(utilities_included="All utilities included", deposit=500, parking="street", parking_cost=0, pet_rent=0, other_monthly_fees=0)
    a = _gap_place(store, s, "Scammy", 800, tenant_pays="electric", listing_text="Wire the deposit by Western Union before you see it.")
    b = _gap_place(store, s, "Fine", 1500, **full)
    out = text(call(server(store), "compare_places", place_ids=[a, b]))
    for l in out.splitlines():
        if "cheapest" in l:
            assert "check it first" in l and ("not counted" in l or "not complete" in l or "aren't counted" in l or "isn't counted" in l), l


def test_complete_places_unchanged(store):
    s = search(store)
    full = dict(utilities_included="All utilities included", deposit=500, parking="street", parking_cost=0, pet_rent=0, other_monthly_fees=0)
    a = _gap_place(store, s, "A", 1500, **full)
    b = _gap_place(store, s, "B", 1700, **full)
    pl, sections = _rows(store, s, a, b)
    cells = _row(sections, "cost")["cells"]
    assert cells[0]["best"] and "not complete" not in cells[0]["text"] and "not complete" not in cells[1]["text"]
