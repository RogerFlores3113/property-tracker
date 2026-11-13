"""Compare: row marking, picking and the page."""
import pytest

from prophelper import compare, enrich


def cell(value, text=None):
    return {"text": text or ("unknown" if value is None else str(value)), "value": value, "best": False, "unknown": value is None}


# ---- mark(): differences and the best value
def test_mark_lowest_wins_and_flags_a_difference():
    cells = [cell(1500.0), cell(1400.0), cell(1700.0)]
    differs, note = compare.mark(cells, "low")
    assert differs and note == "lowest"
    assert [c["best"] for c in cells] == [False, True, False]


def test_mark_highest_wins_and_ties_all_win():
    cells = [cell(80.0), cell(80.0), cell(60.0)]
    differs, note = compare.mark(cells, "high")
    assert differs and note == "tied" and [c["best"] for c in cells] == [True, True, False]


def test_mark_nothing_best_when_all_equal():
    cells = [cell(5.0), cell(5.0)]
    differs, _ = compare.mark(cells, "low")
    assert not differs and not any(c["best"] for c in cells)


def test_mark_unknown_cannot_win_or_lose_and_one_known_value_is_no_difference():
    cells = [cell(None), cell(3.0), cell(None)]
    differs, _ = compare.mark(cells, "low")
    assert not differs and not any(c["best"] for c in cells)
    cells = [cell(None), cell(3.0), cell(9.0)]
    compare.mark(cells, "low")
    assert [c["best"] for c in cells] == [False, True, False]


def test_mark_a_fact_with_no_better_side_only_shades():
    cells = [cell(1.0), cell(2.0)]
    differs, note = compare.mark(cells, None)
    assert differs and note == "" and not any(c["best"] for c in cells)


# ---- ids and counts
def test_parse_ids_accepts_commas_lists_and_drops_repeats():
    assert compare.parse_ids("3,5, 8,3") == [3, 5, 8]
    assert compare.parse_ids(["3", "5,8"]) == [3, 5, 8]
    assert compare.parse_ids(None) == [] and compare.parse_ids([""]) == []


@pytest.mark.parametrize("bad", ["x", "1,two", "-3", "1.5"])
def test_parse_ids_rejects_junk(bad):
    with pytest.raises(compare.CompareError):
        compare.parse_ids(bad)


def test_check_count():
    for n in (2, 3, 4):
        compare.check_count(n)
    for n in (0, 1, 5):
        with pytest.raises(compare.CompareError):
            compare.check_count(n)


# ---- build_rows on real places
def _rows(sample_store, titles):
    search = sample_store.current_search()
    wanted = [p for p in sample_store.list_places(search["id"]) if p["title"] in titles]
    wanted.sort(key=lambda p: titles.index(p["title"]))
    places = enrich.enrich_places(sample_store, search, wanted)
    sections = compare.build_rows(places)
    return places, sections, {r["key"]: r for s in sections for r in s["rows"]}


def test_build_rows_marks_the_cheapest_and_highest_score(sample_store):
    for p in sample_store.list_places(sample_store.current_search()["id"]):  # fill in what is missing so every cost is complete
        if p["utilities_estimate"] is None:
            sample_store.update_place(p["id"], utilities_estimate=60)
        if p["parking"] in ("garage", "covered", "lot") and p["parking_cost"] is None:
            sample_store.update_place(p["id"], parking_cost=0)
    places, sections, rows = _rows(sample_store, ["Maple Row Flats", "Quad View Lofts", "Prairie Commons"])
    cost = rows["cost"]
    costs = [p["cost_total"] for p in places]
    assert cost["differs"]
    # a cost with something left out ("insurance not counted yet") is never marked lowest
    assert not any(c["best"] for c, p in zip(cost["cells"], places) if p["cost"]["uncounted"])
    assert not any(p["cost"]["uncounted"] for p in places)
    assert [c["best"] for c in cost["cells"]] == [v == min(costs) for v in costs]
    scores = [p["score_total"] for p in places]
    assert [c["best"] for c in rows["score"]["cells"]] == [v == max(scores) for v in scores]
    assert any("lowest true monthly cost" in line for line in compare.summary_lines(places, sections))


def test_build_rows_has_cost_lines_commutes_and_criteria(sample_store):
    _, sections, rows = _rows(sample_store, ["Maple Row Flats", "Quad View Lofts"])
    assert "cost-price" in rows and "cost-utilities" in rows
    assert any(k.startswith("commute-") for k in rows)
    assert any(k.startswith("score-") for k in rows)
    assert rows["dishwasher"]["cells"][0]["text"] == "Yes"
    assert [s["title"] for s in sections][0] == "The short version"


def test_unknown_values_say_unknown_and_never_win(sample_store):
    _, _, rows = _rows(sample_store, ["The Elm Street House", "Quad View Lofts"])
    elm = rows["sqft"]["cells"][0]
    assert elm["text"] == "unknown" and elm["unknown"] and not elm["best"]


# ---- the page
def test_compare_picker_lists_places(client, sample_store):
    r = client.get("/compare")
    assert r.status_code == 200 and "Maple Row Flats" in r.text and 'name="ids"' in r.text


def test_compare_page_shows_rows_and_marks(client, sample_store):
    ids = {p["title"]: p["id"] for p in sample_store.list_places()}
    r = client.get(f"/compare?ids={ids['Maple Row Flats']},{ids['Quad View Lofts']}")
    assert r.status_code == 200
    assert "True monthly cost" in r.text and "Fit score" in r.text
    assert 'class="differs"' in r.text and "class=\"best\"" in r.text
    r2 = client.get(f"/compare?ids={ids['Maple Row Flats']}&ids={ids['Quad View Lofts']}&ids={ids['Prairie Commons']}")
    assert r2.status_code == 200 and "Prairie Commons" in r2.text


@pytest.mark.parametrize("query", ["ids=1", "ids=1,2,3,4,5", "ids=abc"])
def test_compare_page_says_why_when_the_count_is_wrong(client, sample_store, query):
    r = client.get(f"/compare?{query}")
    assert r.status_code == 400
    assert any(w in r.text for w in ("Pick at least", "Compare takes", "place numbers"))


def test_compare_page_skips_deleted_places(client, sample_store):
    a, b, _ = [p["id"] for p in sample_store.list_places()][:3]
    r = client.get(f"/compare?ids={a},{b},9999")
    assert r.status_code == 200 and "no longer exist" in r.text


def test_compare_escapes_titles(client, store):
    s = store.add_search("S", "rent")
    store.set_current_search(s["id"])
    a = store.add_place(search_id=s["id"], title="<script>alert(1)</script>", price=1000)[0]
    b = store.add_place(search_id=s["id"], title="Plain", price=1200)[0]
    r = client.get(f"/compare?ids={a['id']},{b['id']}")
    assert "<script>alert(1)" not in r.text and "&lt;script&gt;" in r.text
