"""Cycle 3, group G2: pets only when you have them, none as a pet answer, months up front, unknown deposit, utilities you
pay, a steeper cost score, scam sort order, near misses and the checklist stage gate."""
from datetime import timedelta

import pytest

from conftest import local_client
from prophelper import enrich, helpers, money, scoring, today


def _line(cost, key):
    return next(l for l in cost["lines"] if l["key"] == key)


MAPLE = {"price": 1495, "pet_rent": 35, "pet_fee": 250, "pet_deposit": 300, "deposit": 1000, "utilities_estimate": 0,
         "parking": "street"}


# ------------------------------------------------------------------ 1 pets
def test_no_pets_leaves_pet_charges_out():
    with_pets = money.true_monthly_cost(MAPLE, "rent", pets=True)
    no_pets = money.true_monthly_cost(MAPLE, "rent", pets=False)
    assert with_pets["total"] > no_pets["total"] == 1495
    assert "not counted: you have no pets" in _line(no_pets, "pet_rent")["note"]
    assert _line(no_pets, "pet_rent")["amount"] == 0
    assert not any("Pet" in p["label"] for p in no_pets["cash_at_move_in"]["parts"])
    assert any("Pet fee" in p["label"] for p in with_pets["cash_at_move_in"]["parts"])


def test_pet_kind_decides(store):
    for kind, over in (("", False), ("none", False), ("NONE", False), ("dog", True)):
        s = store.add_search("S" + kind, "rent", budget_max=1500, pet_kind=kind)
        p, _ = store.add_place(search_id=s["id"], title="Maple", **MAPLE)
        e = enrich.enrich_place(store, store.get_place(p["id"]), s)
        assert (e["cost_total"] > 1500) is over


def test_pet_kind_none_accepted_and_stored(store):
    s = store.add_search("S", "rent", pet_kind="None")
    assert s["pet_kind"] == "none"
    s = store.update_search(s["id"], pet_kind="NONE")
    assert s["pet_kind"] == "none"
    with pytest.raises(ValueError) as ei:
        store.update_search(s["id"], pet_kind="goat")
    assert str(ei.value) == "Your pets are cat, dog, both or none." and ".." not in str(ei.value)


def test_web_form_accepts_none(store):
    s = store.add_search("S", "rent")
    c = local_client(store)
    r = c.post(f"/search/{s['id']}", data={"pet_kind": "none", "name": "S"}, follow_redirects=False)
    assert r.status_code in (302, 303)
    assert store.get_search(s["id"])["pet_kind"] == "none"


# ------------------------------------------------------------------ 3 months up front, deposit unknown
def test_months_up_front_and_deposit_unknown():
    c = money.cash_at_move_in({"price": 1000})
    assert c["total"] == 1000 and c["deposit_unknown"] is True
    c = money.cash_at_move_in({"price": 1000, "months_up_front": 2, "deposit": 500})
    assert c["total"] == 2500 and c["deposit_unknown"] is False
    assert money.cash_at_move_in({"price": 1000, "deposit": 0})["deposit_unknown"] is False
    assert money.cash_at_move_in({"price": 1000, "months_up_front": "junk"})["total"] == 1000
    assert money.rent_cost({"price": 1000})["deposit_unknown"] is True


def test_place_page_says_deposit_not_known(store):
    s = store.add_search("S", "rent")
    p, _ = store.add_place(search_id=s["id"], title="Oak", price=1200)
    html = local_client(store).get(f"/places/{p['id']}").text
    assert "Deposit not known yet, so this is low." in html
    store.update_place(p["id"], deposit=800)
    assert "Deposit not known yet" not in local_client(store).get(f"/places/{p['id']}").text


# ------------------------------------------------------------------ 4 utilities
def test_tenant_pays_named_when_no_estimate():
    cost = money.rent_cost({"price": 1000, "tenant_pays": "gas, electric", "parking": "street"})
    assert _line(cost, "utilities")["note"] == "You pay gas and electric; not counted yet"
    assert "utilities (gas and electric)" in cost["uncounted"]
    head = money.true_monthly_cost({"price": 1000, "tenant_pays": "gas, electric"})["headline"]
    assert "utilities (gas and electric) not counted yet" in head


def test_utilities_included_not_unknown():
    cost = money.rent_cost({"price": 1000, "utilities_included": "All utilities", "tenant_pays": "gas"})
    assert "utilities estimate" not in cost["missing"] and not any("utilities" in u for u in cost["uncounted"])


def test_included_parking_not_unknown():
    cost = money.rent_cost({"price": 1000, "parking": "garage", "parking_cost": 0, "utilities_estimate": 0})
    assert cost["uncounted"] == [] and _line(cost, "parking")["amount"] == 0


# ------------------------------------------------------------------ 5 scoring curve and sort
def test_steeper_curve_just_over():
    assert scoring.over_score(0) == 1.0
    assert scoring.over_score(0.05) == pytest.approx(0.6)
    assert scoring.over_score(0.25) == pytest.approx(0.0)
    assert scoring.over_score(0.15) == pytest.approx(0.3)
    crit = [{"id": 1, "kind": "price", "weight": 10, "dealbreaker": False, "target": {"max": 1000}}]
    r = scoring.score_place({"price": 1050}, crit, cost={"total": 1050, "lines": []})
    assert r["items"][0]["score"] == pytest.approx(0.6) and r["total"] == 60


def test_scam_sorts_after_failing():
    crit = [{"id": 1, "kind": "beds", "weight": 10, "dealbreaker": True, "target": {"min": 2}}]
    fit = scoring.score_place({"beds": 2}, crit, serious_flag=False)
    fail = scoring.score_place({"beds": 1}, crit, serious_flag=False)
    scam = scoring.score_place({"beds": 2}, crit, serious_flag=True)
    scam_fail = scoring.score_place({"beds": 1}, crit, serious_flag=True)
    assert [x["sort_group"] for x in (fit, fail, scam, scam_fail)] == [0, 1, 2, 2]
    rows = [{"title": n, "score": s, "score_total": s["total"]} for n, s in (("scam", scam), ("fail", fail), ("fit", fit))]
    rows.sort(key=scoring.sort_key)
    assert [r["title"] for r in rows] == ["fit", "fail", "scam"]


def test_buyer_assessment_reason_line():
    crit = [{"id": 1, "kind": "price", "weight": 10, "dealbreaker": False, "target": {"max": 300000}}]
    p = {"price": 290000, "special_assessment": 6000, "special_assessment_payer": "buyer"}
    item = scoring.score_place(p, crit, mode="buy")["items"][0]
    assert "special assessment of $6,000" in item["detail"] and "cash to close" in item["detail"]


# ------------------------------------------------------------------ 7 Today
def _near_search(store):
    s = store.add_search("Near", "rent", budget_max=1500, pet_kind="dog")
    store.add_criterion(s["id"], "price", dealbreaker=True, target={"max": 1500})
    return s


def test_near_miss_line(store):
    s = _near_search(store)
    store.add_place(search_id=s["id"], title="Maple Court", price=1495, pet_rent=35, utilities_estimate=5, parking="street")
    store.add_place(search_id=s["id"], title="Far", price=1700, utilities_estimate=0, parking="street")
    rows = enrich.enrich_places(store, s)
    texts = {p["title"]: today.near_miss_text(p) for p in rows}
    assert texts["Far"] == ""
    assert texts["Maple Court"] == "$35 over because pet rent counts"
    data = today.build(store, s)
    assert [r["place"]["title"] for r in data["near_miss"]] == ["Maple Court"] and not data["fits"]
    html = local_client(store).get("/today").text
    assert "Near miss" in html and "$35 over because pet rent counts" in html


def test_near_miss_not_for_other_failures(store):
    s = _near_search(store)
    store.add_criterion(s["id"], "beds", dealbreaker=True, target={"min": 2})
    store.add_place(search_id=s["id"], title="Two", price=1520, beds=1, utilities_estimate=0, parking="street")
    rows = enrich.enrich_places(store, s)
    assert today.near_miss_text(rows[0]) == ""


def test_checklist_gate():
    assert today.checklist_applies("Saved", "rent") and today.checklist_applies("Toured", "rent")
    assert not today.checklist_applies("Applied", "rent") and not today.checklist_applies("Approved", "rent")
    assert today.checklist_applies("Saved", "buy") and not today.checklist_applies("Offer made", "buy")


def test_apply_by_prep_only_before_applied(store):
    s = store.add_search("S", "rent")
    p, _ = store.add_place(search_id=s["id"], title="Oak")
    store.add_place_date(p["id"], "application_deadline", (helpers.today() + timedelta(days=3)).isoformat())
    row = next(r for r in today.coming_up(store, s, []) if r["kind"] == "key_date")
    assert row["prep"]
    store.move_stage(p["id"], "Applied")
    row = next(r for r in today.coming_up(store, s, []) if r["kind"] == "key_date")
    assert row["prep"] == "" and row["text"].startswith("Apply by")
