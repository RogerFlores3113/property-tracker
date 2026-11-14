"""C6 G4: one lowest-cost rule (web and Claude agree), commute over the limit is named, plain unknown wording,
near miss best markers, fit label beside the score."""
import pytest
from mcp_util import call, server, text

from prophelper import compare, enrich


def _search(store, **kw):
    s = store.add_search("UIUC", kw.pop("mode", "rent"), **kw)
    store.set_current_search(s["id"])
    return s


def _add(store, s, title, **kw):
    p, _ = store.add_place(search_id=s["id"], title=title, address=f"{title} St", **kw)
    return p["id"]


def _e(store, s, *ids):
    return enrich.enrich_places(store, s, [store.get_place(i) for i in ids])


def _row(sections, key):
    for sec in sections:
        for r in sec["rows"]:
            if r["key"] == key:
                return r


def _commute_setup(store, s, minutes_by_place, limit=20, dealbreaker=False):
    a = store.add_anchor("Campus", lat=40.1, lng=-88.2)
    store.add_criterion(s["id"], "commute", target={"anchor_id": a["id"], "mode": "bike", "minutes": limit}, dealbreaker=dealbreaker)
    for pid, m in minutes_by_place.items():
        store.set_commute(pid, a["id"], "bike", m)


def _full(**kw):
    return dict(utilities_included="All utilities included", deposit=500, parking="street", parking_cost=0, pet_rent=0, other_monthly_fees=0, **kw)


# ---- 1 and 2: one rule, same place on web and MCP
@pytest.mark.parametrize("dealbreaker", [False, True])
def test_over_limit_place_is_named_not_silent_winner(store, dealbreaker):
    s = _search(store)
    sav = _add(store, s, "Savoy", price=1200, **_full())
    har = _add(store, s, "Harvest", price=1300, **_full())
    _commute_setup(store, s, {sav: 24, har: 12}, dealbreaker=dealbreaker)
    es = _e(store, s, sav, har)
    r = compare.lowest_cost(es)
    # either Savoy was a near miss/doesn't fit (then it's blocked) or it is skipped for being over: never the winner
    assert [p["title"] for p in r["winners"]] != ["Savoy"]
    lines = compare.summary_lines(es, compare.build_rows(es))
    assert any("Harvest has the lowest" in l for l in lines)
    assert any(l.startswith("Savoy is cheapest, but") for l in lines)
    srv = server(store)
    out = text(call(srv, "compare_places", place_ids=[sav, har]))
    assert f"Lowest true monthly cost: #{har}" in out and f"Lowest true monthly cost: #{sav}" not in out
    assert f"#{sav}" in out.split("Lowest true monthly cost")[1]


def test_over_limit_text_says_minutes_way_and_limit(store):
    s = _search(store)
    sav = _add(store, s, "Savoy", price=1200, **_full())
    har = _add(store, s, "Harvest", price=1300, **_full())
    _commute_setup(store, s, {sav: 24, har: 12})
    es = _e(store, s, sav, har)
    assert compare.over_limit_text(es[0]) == "24 min bike vs your 20 min limit"
    assert compare.over_limit_text(es[1]) == ""
    row = _row(compare.build_rows(es), "cost")
    assert not row["cells"][0]["best"]


def test_all_over_limit_still_names_the_cheapest_with_the_warning(store):
    s = _search(store)
    a = _add(store, s, "A", price=1200, **_full())
    b = _add(store, s, "B", price=1300, **_full())
    _commute_setup(store, s, {a: 25, b: 30})
    es = _e(store, s, a, b)
    r = compare.lowest_cost(es)
    assert [p["title"] for p in r["winners"]] == ["A"]
    assert any(p["title"] == "A" for p, _ in r["over_limit"])


def test_unknown_parts_cannot_be_lowest_unless_all_have_them(store):
    s = _search(store)
    cheap = _add(store, s, "Cheap", price=900)  # utilities, deposit and so on not filled in
    full = _add(store, s, "Full", price=1100, **_full())
    es = _e(store, s, cheap, full)
    r = compare.lowest_cost(es)
    assert [p["title"] for p in r["winners"]] == ["Full"]
    assert [p["title"] for p in r["skipped_unknown"]] == ["Cheap"]
    out = text(call(server(store), "compare_places", place_ids=[cheap, full]))
    assert f"Lowest true monthly cost: #{full}" in out
    # all unknown: the lowest of what is counted, and it says so
    other = _add(store, s, "Other", price=1000)
    es = _e(store, s, cheap, other)
    r = compare.lowest_cost(es)
    assert r["all_unknown"] and [p["title"] for p in r["winners"]] == ["Cheap"]
    assert "its utilities aren't counted" in compare.summary_lines(es, compare.build_rows(es))[0]


# ---- 3: wording
def test_unknown_rows_use_plain_wording_without_nested_brackets(store):
    s = _search(store)
    a = _add(store, s, "A", price=1000, **_full())
    b = _add(store, s, "B", price=1000, utilities_estimate=80, deposit=500, parking="street", parking_cost=0, pet_rent=0, other_monthly_fees=0)
    c = _add(store, s, "C", price=1000)
    es = _e(store, s, a, b, c)
    secs = compare.build_rows(es)
    for key in ("missing", "unknown"):
        for cell in _row(secs, key)["cells"]:
            t = cell["text"]
            assert "nothing left out" not in t and "everything is filled in" not in t
            assert "((" not in t and not (t.count("(") and "(" in t.split("(", 1)[1])
    assert _row(secs, "missing")["cells"][0]["text"] == "Nothing unknown"
    assert _row(secs, "unknown")["cells"][0]["text"] == "Nothing unknown"
    assert _row(secs, "missing")["cells"][1]["text"] == "Utilities guessed"
    assert _row(secs, "missing")["cells"][2]["text"].startswith("Unknown: ")


def test_unknown_text_helper():
    assert compare.unknown_text([], []) == "Nothing unknown"
    assert compare.unknown_text(["electric and internet"], []) == "Unknown: electric and internet"
    assert compare.unknown_text([], ["utilities", "parking"]) == "Utilities and parking guessed"


def test_share_page_uses_the_same_wording(store):
    from fastapi.testclient import TestClient  # noqa: F401
    from conftest import local_client
    s = _search(store)
    a = _add(store, s, "A", price=1000, **_full())
    b = _add(store, s, "B", price=1100, **_full())
    html = local_client(store).get(f"/compare/share?ids={a},{b}").text
    assert "nothing, everything is filled in" not in html and "nothing left out" not in html
    assert "Nothing unknown" in html


# ---- 4: near miss and best markers
def _fake(title, fit, hoa):
    return {"title": title, "score": {"fit": fit, "items": []}, "possible_scam": False, "cost": {}, "cost_total": 1000}


def test_near_miss_wins_a_row_only_when_no_fitting_place_has_a_value():
    fits = _fake("Fits", "fits", 300)
    near = _fake("Near", "near_miss", 100)
    cells = [compare._cell("$300", 300.0), compare._cell("$100", 100.0)]
    row = compare._row("hoa", "HOA", cells, "low", places=[fits, near])
    assert not cells[1]["best"] and row["best_note"] == ""
    cells = [compare._cell(None), compare._cell("$100", 100.0)]
    # only one value: no best at all (needs two), so use a third place
    far = _fake("Fits2", "fits", 0)
    cells = [compare._cell(None), compare._cell("$100", 100.0), compare._cell("$150", 150.0)]
    compare._row("hoa", "HOA", cells, "low", places=[fits, near, _fake("Near2", "near_miss", 0)])
    assert cells[1]["best"] and not cells[2]["best"]
    cells = [compare._cell("$50", 50.0), compare._cell("$100", 100.0), compare._cell("$150", 150.0)]
    compare._row("hoa", "HOA", cells, "low", places=[fits, near, far])
    assert cells[0]["best"] and not cells[1]["best"]


# ---- 5: fit label beside the score
def test_score_cell_names_near_miss():
    p = {"score_total": 49, "score": {"fit": "near_miss", "unknown_count": 0}}
    assert compare._score_cell(p)["text"] == "49, near miss"
    p = {"score_total": 85, "score": {"fit": "fits", "fit_label": "Fits, but check", "unknown_count": 2}}
    assert compare._score_cell(p)["text"] == "85, fits, but check (based on 2 unknowns)"
    p = {"score_total": 90, "score": {"fit": "fits", "unknown_count": 0}}
    assert compare._score_cell(p)["text"] == "90"
