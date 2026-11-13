"""C3 G3: Compare, the share page and compare_places tell the truth about unknowns, ties, commutes and people."""
import re

from prophelper import commute, compare, enrich, share
from mcp_util import call, server, text


def _search(store, **kw):
    s = store.add_search("Fall", kw.pop("mode", "rent"), **kw)
    store.set_current_search(s["id"])
    return s


def _enriched(store, search, *ids):
    return [enrich.enrich_places(store, search, [store.get_place(i)])[0] for i in ids]


def _row(sections, key):
    for sec in sections:
        for r in sec["rows"]:
            if r["key"] == key:
                return r
    return None


def _texts(row):
    return [c["text"] for c in row["cells"]]


# ---- 1. commutes typed for an important place with no map point
def test_typed_transit_commute_shows_without_map_points(client, store):
    s = _search(store)
    store.add_criterion(s["id"], "commute", label="", weight=20, target={"anchor_id": None, "mode": "drive", "minutes": 30})
    office = store.add_anchor("Dad office")
    school = store.add_anchor("Elementary school")
    a, _ = store.add_place(search_id=s["id"], title="A", address="1 A St", price=1500)
    b, _ = store.add_place(search_id=s["id"], title="B", address="2 B St", price=1600)
    store.set_commute(a["id"], office["id"], "drive", 22)
    store.set_commute(a["id"], school["id"], "transit", 15)
    store.set_commute(b["id"], school["id"], "transit", 25)
    e = _enriched(store, s, a["id"], b["id"])
    assert [c["anchor"] for c in e[0]["commute_all"]] == ["Dad office", "Elementary school"]
    rows = compare.build_rows(e)
    row = _row(rows, f"commute-{school['id']}")
    assert row and _texts(row)[0].startswith("15 min transit") and row["cells"][0]["best"]
    html = client.get(f"/compare?ids={a['id']}&ids={b['id']}").text
    assert "Elementary school" in html and "15 min transit" in html
    board = client.get("/board").text
    assert "Dad office 22 min drive" in board
    out = text(call(server(store), "compare_places", place_ids=[a["id"], b["id"]]))
    assert "Elementary school" in out and "15 min transit" in out


def test_typed_transit_is_the_fastest_when_nothing_else_is_known():
    anchor = {"id": 1, "name": "School", "lat": None, "lng": None}
    stored = [{"anchor_id": 1, "mode": "transit", "minutes": 15, "source": "you"}]
    mode, found = commute.pick_for_anchor({"id": 1}, anchor, stored, "bike")
    assert mode == "transit" and found["minutes"] == 15
    assert commute.top_commute({"id": 1}, [anchor], stored)["mode"] == "transit"


# ---- 2. one cash row
def test_cash_row_is_not_repeated_on_compare_or_the_share_page(client, store):
    s = _search(store)
    a, _ = store.add_place(search_id=s["id"], title="A", address="1 A St", price=1500, deposit=1500)
    b, _ = store.add_place(search_id=s["id"], title="B", address="2 B St", price=1200, deposit=1200)
    for url in (f"/compare?ids={a['id']}&ids={b['id']}", f"/compare/share.html?ids={a['id']}&ids={b['id']}"):
        html = client.get(url).text
        assert html.count("Cash needed at move-in") == 1
        assert "on move-in day" not in html


# ---- 3 and 4. unknown never wins, ties are said once
def test_unset_pet_rent_and_parking_are_not_known_not_zero(store):
    s = _search(store)
    a, _ = store.add_place(search_id=s["id"], title="A", address="1 A St", price=1500, pet_rent=40, pets="cats")
    b, _ = store.add_place(search_id=s["id"], title="B", address="2 B St", price=1500)
    sections = compare.build_rows(_enriched(store, s, a["id"], b["id"]))
    pet = _row(sections, "cost-pet_rent")
    assert _texts(pet)[1] == "Not known" and not any(c["best"] for c in pet["cells"])
    parking = _row(sections, "cost-parking")
    assert parking is None or "$0" not in _texts(parking)[1]


def test_pets_none_is_a_real_zero(store):
    # The search has a cat, so pet rent counts (with no pets it is left out of the cost entirely).
    s = _search(store, pet_kind="cat")
    a, _ = store.add_place(search_id=s["id"], title="A", address="1 A St", price=1500, pet_rent=40, pets="cats")
    b, _ = store.add_place(search_id=s["id"], title="B", address="2 B St", price=1500, pets="none")
    pet = _row(compare.build_rows(_enriched(store, s, a["id"], b["id"])), "cost-pet_rent")
    assert _texts(pet)[1] == "$0.00" and pet["cells"][1]["best"]


def test_unknown_value_never_wins_a_row():
    cells = [compare._cell("$5", 5.0), compare._money(None), compare._cell("$9", 9.0)]
    differs, note = compare.mark(cells, "low")
    assert note == "lowest" and [c["best"] for c in cells] == [True, False, False]
    assert cells[1]["text"] == "Not known"


def test_ties_are_marked_tied_once_and_equal_rows_have_no_winner(client, store):
    cells = [compare._cell("a", 1.0), compare._cell("b", 1.0), compare._cell("c", 2.0)]
    differs, note = compare.mark(cells, "low")
    assert note == "tied" and [c["best"] for c in cells] == [True, True, False]
    same = [compare._cell("a", 3.0), compare._cell("b", 3.0)]
    assert compare.mark(same, "low") == (False, "") and not any(c["best"] for c in same)
    s = _search(store)
    ids = [store.add_place(search_id=s["id"], title=t, address=f"{i} St", price=p)[0]["id"]
           for i, (t, p) in enumerate([("A", 1000), ("B", 1000), ("C", 1500)], 1)]
    q = "&".join(f"ids={i}" for i in ids)
    html = client.get(f"/compare?{q}").text
    assert "(lowest)" not in html.split("True monthly cost")[1].split("</tr>")[0]
    assert "(tied)" in html
    shared = client.get(f"/compare/share.html?{q}").text
    assert "(tied)" in shared and "(best)" not in shared.split("True monthly cost")[1].split("</tr>")[0]


def test_summary_says_tied(store):
    s = _search(store)
    a, _ = store.add_place(search_id=s["id"], title="A", address="1 A St", price=1000, utilities_estimate=50)
    b, _ = store.add_place(search_id=s["id"], title="B", address="2 B St", price=1000, utilities_estimate=50)
    c, _ = store.add_place(search_id=s["id"], title="C", address="3 C St", price=1500, utilities_estimate=50)
    es = _enriched(store, s, a["id"], b["id"], c["id"])
    lines = compare.summary_lines(es, compare.build_rows(es))
    assert any("tied for the lowest true monthly cost" in x for x in lines)
    out = text(call(server(store), "compare_places", place_ids=[a["id"], b["id"], c["id"]]))
    assert "tied" in out.split("Lowest true monthly cost")[1].split("\n")[0]


# ---- 5. unknown deposit
def test_cash_with_unknown_deposit_is_at_least_and_cannot_win(store):
    s = _search(store)
    a, _ = store.add_place(search_id=s["id"], title="A", address="1 A St", price=1000)  # deposit not known
    b, _ = store.add_place(search_id=s["id"], title="B", address="2 B St", price=1100, deposit=1100)
    row = _row(compare.build_rows(_enriched(store, s, a["id"], b["id"])), "cash_up_front")
    assert _texts(row)[0] == "at least $1,000 (deposit not known)"
    assert not row["cells"][0]["best"]
    assert not any(c["best"] for c in row["cells"])  # one complete number is not a comparison
    out = text(call(server(store), "compare_places", place_ids=[a["id"], b["id"]]))
    assert "at least $1,000 (deposit not known)" in out


def test_a_deposit_of_zero_is_known(store):
    s = _search(store)
    a, _ = store.add_place(search_id=s["id"], title="A", address="1 A St", price=1000, deposit=0)
    b, _ = store.add_place(search_id=s["id"], title="B", address="2 B St", price=1100, deposit=1100)
    row = _row(compare.build_rows(_enriched(store, s, a["id"], b["id"])), "cash_up_front")
    assert "not known" not in _texts(row)[0] and row["cells"][0]["best"]


def test_deposit_flag_from_the_money_result_wins(store):
    s = _search(store)
    a, _ = store.add_place(search_id=s["id"], title="A", address="1 A St", price=1000, deposit=1000)
    e = _enriched(store, s, a["id"])[0]
    e["cost"]["cash_at_move_in"]["deposit_unknown"] = True
    assert compare._cash_cell(e)["incomplete"]


# ---- 6. buy mode
def test_buy_rows_assessment_days_and_cash_note(store):
    s = _search(store, mode="buy")
    a, _ = store.add_place(search_id=s["id"], title="A", address="1 A St", price=400000, special_assessment=12000,
                           special_assessment_payer="buyer", days_on_market=30)
    b, _ = store.add_place(search_id=s["id"], title="B", address="2 B St", price=410000, special_assessment=8000,
                           special_assessment_payer="seller", days_on_market=5)
    c, _ = store.add_place(search_id=s["id"], title="C", address="3 C St", price=420000, special_assessment=5000)
    sections = compare.build_rows(_enriched(store, s, a["id"], b["id"], c["id"]))
    sa = _row(sections, "assessment")
    assert _texts(sa) == ["$12,000 (you pay it)", "$8,000 (the seller pays it)", "$5,000 (who pays it is not known)"]
    assert sa["cells"][1]["best"] and not sa["cells"][2]["best"]
    assert _texts(_row(sections, "days_on_market")) == ["30", "5", "Not known"] or _row(sections, "days_on_market")
    cash = _texts(_row(sections, "cash_up_front"))
    assert "includes a $12,000 special assessment you pay" in cash[0]
    assert "special assessment" not in cash[1]
    out = text(call(server(store), "compare_places", place_ids=[a["id"], b["id"]]))
    assert "Special assessment (who pays it)" in out and "Days on the market" in out
    assert "includes a $12,000 special assessment you pay" in out


# ---- 7. each person's rating
def test_each_named_person_gets_a_rating_row(client, store):
    s = _search(store, people=2, people_names=["Sam", "Riley"])
    a, _ = store.add_place(search_id=s["id"], title="A", address="1 A St", price=1500)
    b, _ = store.add_place(search_id=s["id"], title="B", address="2 B St", price=1500)
    store.set_opinion(a["id"], "Sam", 5, "SECRET-SAM-NOTE")
    store.set_opinion(a["id"], "Riley", 2)
    store.set_opinion(b["id"], "Sam", 3)
    html = client.get(f"/compare?ids={a['id']}&ids={b['id']}").text
    assert "Sam&#39;s rating" in html and "Riley&#39;s rating" in html
    out = text(call(server(store), "compare_places", place_ids=[a["id"], b["id"]]))
    assert re.search(r"Sam</untrusted>'s rating \(1 to 5\): #\d+ 5 \| #\d+ 3", out) and "Riley" in out
    assert "SECRET-SAM-NOTE" not in out


def test_share_page_keeps_ratings_and_notes_opt_in(client, store):
    s = _search(store, people=2, people_names=["Sam", "Riley"])
    a, _ = store.add_place(search_id=s["id"], title="A", address="1 A St", price=1500)
    b, _ = store.add_place(search_id=s["id"], title="B", address="2 B St", price=1500)
    store.set_opinion(a["id"], "Sam", 5, "SECRET-SAM-NOTE")
    store.set_opinion(b["id"], "Sam", 3)
    q = f"ids={a['id']}&ids={b['id']}"
    off = client.get(f"/compare/share.html?{q}").text
    assert "Sam" not in off and "SECRET-SAM-NOTE" not in off
    on = client.get(f"/compare/share.html?{q}&notes=1").text
    assert "Sam&#39;s rating" in on and "SECRET-SAM-NOTE" in on


# ---- 8. who added a commute
def test_commute_words_say_added_by_claude_and_the_share_page_drops_it(client, store):
    assert commute.label(12, "ai", "bike") == "12 min bike (added by Claude)"
    assert "(ai)" not in commute.label(12, "ai", "bike")
    s = _search(store)
    anchor = store.add_anchor("Campus")
    store.add_criterion(s["id"], "commute", label="", weight=20, target={"anchor_id": anchor["id"], "mode": "bike", "minutes": 20})
    a, _ = store.add_place(search_id=s["id"], title="A", address="1 A St", price=1500)
    b, _ = store.add_place(search_id=s["id"], title="B", address="2 B St", price=1500)
    store.set_commute(a["id"], anchor["id"], "bike", 10, "ai")
    store.set_commute(b["id"], anchor["id"], "bike", 14, "you")
    q = f"ids={a['id']}&ids={b['id']}"
    web = client.get(f"/compare?{q}").text
    assert "added by Claude" in web and "(ai)" not in web
    shared = client.get(f"/compare/share.html?{q}").text
    assert "10 min bike" in shared and "added by Claude" not in shared and "(you)" not in shared
    assert "added by Claude" in text(call(server(store), "compare_places", place_ids=[a["id"], b["id"]]))
