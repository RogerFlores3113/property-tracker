"""C5 G4: best markers are honest (unknown parts, guesses, places that don't fit), seller credit, share route."""
from prophelper import compare, enrich


def _search(store, **kw):
    s = store.add_search("Fall", kw.pop("mode", "rent"), **kw)
    store.set_current_search(s["id"])
    return s


def _e(store, s, *ids):
    return [enrich.enrich_places(store, s, [store.get_place(i)])[0] for i in ids]


def _row(sections, key):
    for sec in sections:
        for r in sec["rows"]:
            if r["key"] == key:
                return r


def _add(store, s, title, **kw):
    p, _ = store.add_place(search_id=s["id"], title=title, address=f"{title} St", **kw)
    return p["id"]


def test_real_assessment_never_best_over_none_listed(store):
    s = _search(store, mode="buy")
    a = _add(store, s, "A", price=300000, special_assessment=6000, special_assessment_payer="buyer")
    b = _add(store, s, "B", price=310000)
    row = _row(compare.build_rows(_e(store, s, a, b)), "assessment")
    assert not row["cells"][0]["best"] and row["cells"][1]["text"] == "None listed" and row["cells"][1]["best"]


def test_assessment_mentioned_in_listing_is_unknown(store):
    s = _search(store, mode="buy")
    a = _add(store, s, "A", price=300000, special_assessment=6000, special_assessment_payer="buyer")
    b = _add(store, s, "B", price=310000, listing_text="Pending special assessment for the roof.")
    row = _row(compare.build_rows(_e(store, s, a, b)), "assessment")
    assert not any(c["best"] for c in row["cells"])


def test_cash_with_unknown_deposit_or_pets_is_not_best(store):
    s = _search(store, pet_kind="dog")
    a = _add(store, s, "A", price=1000, deposit=500, pet_fee=100)
    b = _add(store, s, "B", price=900, deposit=500)  # pet charges not known
    row = _row(compare.build_rows(_e(store, s, a, b)), "cash_up_front")
    assert "pet charges not known" in row["cells"][1]["text"]
    assert not row["cells"][1]["best"]


def test_partly_included_utilities_zero_guess_cannot_tie(store):
    s = _search(store)
    a = _add(store, s, "A", price=1000, utilities_included="All utilities included")
    b = _add(store, s, "B", price=1000, utilities_included="Water", utilities_estimate=0)
    row = _row(compare.build_rows(_e(store, s, a, b)), "cost-utilities")
    assert row["cells"][0]["marker"] == "" or row["cells"][0]["best"] is False or not row["cells"][1]["best"]
    assert not row["cells"][1]["best"]


def test_scam_or_non_fit_never_best_and_headline(store):
    s = _search(store)
    a = _add(store, s, "Fine", price=1500)
    b = _add(store, s, "Scammy", price=900, listing_text="Wire the deposit by gift card before you see it. Owner is overseas.")
    e = _e(store, s, a, b)
    e[1]["possible_scam"] = True
    sections = compare.build_rows(e)
    row = _row(sections, "cost")
    assert not row["cells"][1]["best"]
    lines = compare.summary_lines(e, sections)
    assert not any("Scammy has the lowest" in l for l in lines)
    assert any("Scammy is cheapest, but check it first: possible scam" in l for l in lines)


def test_no_pets_search_pet_rent_not_counted(store):
    s = _search(store)
    a = _add(store, s, "A", price=1000, pet_rent=0)
    b = _add(store, s, "B", price=1000, pet_rent=50)
    row = _row(compare.build_rows(_e(store, s, a, b)), "cost-pet_rent")
    assert [c["text"] for c in row["cells"]] == ["Not counted, no pets"] * 2
    assert not any(c["best"] for c in row["cells"])


def test_seller_credit_row_and_wording(store):
    s = _search(store, mode="buy")
    a = _add(store, s, "A", price=300000, seller_credit=5000)
    b = _add(store, s, "B", price=300000, seller_credit=2000)
    c = _add(store, s, "C", price=300000)
    sections = compare.build_rows(_e(store, s, a, b, c))
    row = _row(sections, "seller_credit")
    assert row["cells"][0]["best"] and not row["cells"][2]["best"] and row["cells"][2]["unknown"]
    miss = _row(compare.build_rows(_e(store, s, a, b)), "missing")
    assert "all costs are in" not in " ".join(x["text"] for x in miss["cells"])


def test_share_route_works_without_html(client, store):
    s = _search(store)
    a = _add(store, s, "A", price=1000)
    b = _add(store, s, "B", price=1100)
    r = client.get(f"/compare/share?ids={a}&ids={b}")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    page = client.get(f"/compare?ids={a}&ids={b}").text
    assert "Share a copy" in page and "/compare/share.html" in page
