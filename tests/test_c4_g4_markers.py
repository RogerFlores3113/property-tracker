"""C4 G4: one marker scheme on Compare and the share page: (best) / (tied best), no worst marks."""
from prophelper import compare, enrich
from test_c3_g3_compare_honesty import _enriched, _row, _search, _texts


def test_mark_best_and_tied_best_and_no_worst():
    cells = [compare._cell("a", 1.0), compare._cell("b", 2.0), compare._cell("c", 3.0)]
    assert compare.mark(cells, "low") == (True, "best")
    assert [c["marker"] for c in cells] == ["(best)", "", ""] and not any(c["worst"] for c in cells)
    tied = [compare._cell("a", 49.0), compare._cell("b", 49.0), compare._cell("c", 49.0), compare._cell("d", 20.0)]
    compare.mark(tied, "high")
    assert [c["marker"] for c in tied] == ["(tied best)"] * 3 + [""]
    hi = [compare._cell("a", 5.0), compare._cell("b", 9.0)]
    compare.mark(hi, "high")
    assert hi[1]["marker"] == "(best)" and hi[0]["marker"] == ""


def test_text_rows_without_an_order_have_no_best(store):
    s = _search(store)
    a, _ = store.add_place(search_id=s["id"], title="A", address="1 A St", price=1500, parking="garage", laundry="in_unit")
    b, _ = store.add_place(search_id=s["id"], title="B", address="2 B St", price=1500, parking="street", laundry="none")
    secs = compare.build_rows(_enriched(store, s, a["id"], b["id"]))
    assert not any(c["best"] for c in _row(secs, "parking")["cells"])
    assert not any(c["best"] for c in _row(secs, "pets")["cells"])
    assert _row(secs, "laundry")["cells"][0]["best"]  # in-unit beats none: a defined order


def test_pet_rent_no_pets_is_not_counted(store):
    s = _search(store)
    a, _ = store.add_place(search_id=s["id"], title="A", address="1 A St", price=1500, pet_rent=40)
    b, _ = store.add_place(search_id=s["id"], title="B", address="2 B St", price=1500)
    pet = _row(compare.build_rows(_enriched(store, s, a["id"], b["id"])), "cost-pet_rent")
    assert _texts(pet) == ["Not counted, no pets"] * 2 and not any(c["best"] for c in pet["cells"])


def test_pet_rent_with_pets_not_known_vs_real_zero(store):
    s = _search(store, pet_kind="cat")
    a, _ = store.add_place(search_id=s["id"], title="A", address="1 A St", price=1500, pet_rent=40, pets="cats")
    b, _ = store.add_place(search_id=s["id"], title="B", address="2 B St", price=1500, pet_rent=0, pets="cats")
    c, _ = store.add_place(search_id=s["id"], title="C", address="3 C St", price=1500)
    pet = _row(compare.build_rows(_enriched(store, s, a["id"], b["id"], c["id"])), "cost-pet_rent")
    assert _texts(pet)[1:] == ["$0 (none)", "Not known"] and pet["cells"][1]["best"] and not pet["cells"][2]["best"]


def test_unknown_deposit_cash_never_gets_a_marker(store):
    s = _search(store)
    a, _ = store.add_place(search_id=s["id"], title="A", address="1 A St", price=1000)
    b, _ = store.add_place(search_id=s["id"], title="B", address="2 B St", price=1500, deposit=1500)
    cash = _row(compare.build_rows(_enriched(store, s, a["id"], b["id"])), "cash_up_front")
    assert "deposit not known" in cash["cells"][0]["text"] and cash["cells"][0]["marker"] == ""


def test_special_assessment_none_listed(store):
    s = _search(store, mode="buy")
    a, _ = store.add_place(search_id=s["id"], title="A", address="1 A St", price=400000)
    b, _ = store.add_place(search_id=s["id"], title="B", address="2 B St", price=410000, special_assessment=0)
    row = _row(compare.build_rows(_enriched(store, s, a["id"], b["id"])), "assessment")
    assert _texts(row) == ["None listed", "None"] and not any(c["best"] for c in row["cells"])


def test_compare_and_share_pages_use_same_wording(client, store):
    s = _search(store)
    ids = [store.add_place(search_id=s["id"], title=t, address=f"{i} St", price=1000, sqft=p)[0]["id"]
           for i, (t, p) in enumerate([("A", 900), ("B", 900), ("C", 600)], 1)]
    q = "&".join(f"ids={i}" for i in ids)
    for url in (f"/compare?{q}", f"/compare/share.html?{q}"):
        html = client.get(url).text
        row = html.split("Size (sq ft")[1].split("</tr>")[0]
        assert row.count("(tied best)") == 2 and "(lowest)" not in row and "(highest)" not in row
