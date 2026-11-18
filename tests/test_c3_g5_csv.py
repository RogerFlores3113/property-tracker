"""Cycle 3, G5: places.csv carries pet and buyer fields in plain words and reads them back."""
from prophelper import csv_io, enrich


def _export(store, sid):
    places = enrich.enrich_places(store, store.get_search(sid))
    return csv_io.export_csv(places, store.list_anchors())


def _import(store, text, sid):
    headers, rows = csv_io.read_table(text.encode() if isinstance(text, str) else text)
    plan = csv_io.plan_import(store, sid, headers, rows, csv_io.match_columns(headers))
    csv_io.apply_plan(store, sid, plan)
    return store.list_places(sid)


def test_export_has_the_new_columns_in_plain_words_and_imports_back(store):
    s = store.add_search("Rent", "rent")
    p, _ = store.add_place(search_id=s["id"], by="you", title="A", laundry="in_unit", parking="lot", pets="both",
                           pet_weight_limit=50, pet_count_limit=2, pet_breed_note="No pit bulls", pet_deposit=300,
                           fenced_yard=True, dishwasher=True)
    b = store.add_search("Buy", "buy")
    q, _ = store.add_place(search_id=b["id"], by="you", title="B", days_on_market=45, special_assessment=4000,
                           special_assessment_payer="seller", closing_costs=9000, listing_agent="Pat Lee", laundry="hookups", pets="none")
    text = _export(store, s["id"])
    for h in ("Heaviest pet allowed (lb)", "Pet count limit", "Breed rules", "Pet deposit (refundable)", "Fenced yard", "Days on market",
              "Special assessment", "Who pays the special assessment", "Closing costs", "Listing agent"):
        assert h in text
    assert "In the unit" in text and "Cats and dogs" in text and "in_unit" not in text
    got = _import(store, text, store.add_search("Copy", "rent")["id"])[0]
    for k in ("laundry", "parking", "pets", "pet_weight_limit", "pet_count_limit", "pet_breed_note", "pet_deposit", "fenced_yard"):
        assert got[k] == p[k], k
    g = _import(store, _export(store, b["id"]), store.add_search("Copy2", "buy")["id"])[0]
    for k in ("days_on_market", "special_assessment", "special_assessment_payer", "closing_costs", "listing_agent", "laundry", "pets"):
        assert g[k] == q[k], k


def test_old_codes_still_import(store):
    s = store.add_search("Rent", "rent")
    data = b"Title,Laundry,Parking,Pets\nOld,in_unit,garage,both\nWords,Hookups only,Street,No pets\n"
    got = {p["title"]: p for p in _import(store, data, s["id"])}
    assert (got["Old"]["laundry"], got["Old"]["parking"], got["Old"]["pets"]) == ("in_unit", "garage", "both")
    assert (got["Words"]["laundry"], got["Words"]["parking"], got["Words"]["pets"]) == ("hookups", "street", "none")
