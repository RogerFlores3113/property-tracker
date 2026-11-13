"""Cycle 2, group G3: pet limits and your pets, fenced yard, refundable pet deposit, per-place application checklist,
Today's apply-by line and close tours."""
from datetime import datetime, timedelta, timezone

import pytest

from conftest import local_client
from prophelper import enrich, helpers, money, parsers, scoring, today
from prophelper.store import Store


def _search(store, **kw):
    return store.add_search("Pets", "rent", **kw)


def _place(store, sid, **fields):
    p, _ = store.add_place(search_id=sid, title=fields.pop("title", "Maple"), **fields)
    return p


# ------------------------------------------------------------------ parser
def test_parser_pet_limits():
    out = parsers.parse_listing("Pet friendly. Dogs under 50 lbs. Max 2 pets. No aggressive breeds. "
                                "$400 refundable pet deposit. $35 pet rent. Fenced backyard.")
    assert out["pet_weight_limit"] == 50 and out["pet_count_limit"] == 2
    assert out["pet_breed_note"] == "No aggressive breeds"
    assert out["pet_deposit"] == 400 and out["pet_rent"] == 35 and "pet_fee" not in out
    assert out["fenced_yard"] == 1


def test_parser_plain_pet_deposit_is_the_pet_deposit_and_no_fence():
    # c3: a plain "pet deposit" is money that comes back (pet_deposit); a non-refundable one stays a fee
    out = parsers.parse_listing("Cats ok. Pet deposit $300. No fenced yard.")
    assert out["pet_deposit"] == 300 and "pet_fee" not in out and out["fenced_yard"] == 0
    assert "pet_weight_limit" not in parsers.parse_listing("Cats ok.")


# ------------------------------------------------------------------ scoring
def _pets_item(place, pets, **crit):
    c = {"id": 1, "kind": "pets", "weight": 10, "dealbreaker": True, "target": crit.get("target", {})}
    return scoring.score_place(place, [c], pets=pets)["items"][0]


def test_heavy_dog_fails_weight_limit():
    place = {"pets": "both", "pet_weight_limit": 50}
    item = _pets_item(place, {"kind": "dog", "weight": 60, "count": 1})
    assert item["passes"] is False and item["gap"] == "Your dog is 60 lb; limit 50 lb"
    ok = _pets_item(place, {"kind": "dog", "weight": 45, "count": 1})
    assert ok["passes"] is True and ok["score"] == 1.0


def test_too_many_pets_fail_count_limit():
    item = _pets_item({"pets": "both", "pet_count_limit": 2}, {"kind": "cat", "count": 3})
    assert item["passes"] is False and "limit 2" in item["gap"]


def test_unknown_limit_scores_half_and_no_profile_keeps_old_logic():
    item = _pets_item({"pets": "both"}, {"kind": "dog", "weight": 60})
    assert item["known"] is False and item["score"] == 0.5 and item["dealbreaker_status"] == "check"
    assert _pets_item({"pets": "both", "pet_weight_limit": 10}, {})["passes"] is True  # no profile: only the policy
    assert _pets_item({"pets": "cats"}, {"kind": "dog"})["passes"] is False  # dogs wanted, cats only
    assert _pets_item({"pets": "cats"}, {}, target={"want": "dogs"})["passes"] is False


def test_cat_owner_ignores_dog_weight_limit():
    item = _pets_item({"pets": "both", "pet_weight_limit": 10, "pet_count_limit": 2}, {"kind": "cat", "weight": 60, "count": 1})
    assert item["passes"] is True


def test_fenced_yard_criterion():
    c = {"id": 1, "kind": "fenced_yard", "weight": 10, "dealbreaker": True, "target": {}}
    assert scoring.score_place({"fenced_yard": 1}, [c])["items"][0]["passes"] is True
    assert scoring.score_place({"fenced_yard": 0}, [c])["items"][0]["passes"] is False
    unk = scoring.score_place({}, [c])["items"][0]
    assert unk["known"] is False and unk["score"] == 0.5 and unk["label"] == "Fenced yard"


def test_search_pet_profile_flows_through_enrich(store):
    s = _search(store, budget_max=3000, pet_kind="dog", pet_weight=60, pet_count=1)
    assert s["pet_kind"] == "dog" and s["pet_weight"] == 60 and s["pet_count"] == 1
    store.add_criterion(s["id"], "pets", dealbreaker=True)
    p = _place(store, s["id"], price=1200, pets="both", pet_weight_limit=50)
    row = enrich.enrich_places(store, s, [p])[0]
    assert row["score"]["fails_dealbreaker"] and "Your dog is 60 lb; limit 50 lb" in row["score"]["fit_reasons"]
    with pytest.raises(ValueError):
        store.update_search(s["id"], pet_kind="horse")


def test_place_pet_fields_round_trip(store):
    s = _search(store)
    p = _place(store, s["id"], pet_weight_limit="50", pet_count_limit="2", pet_breed_note="No aggressive breeds",
               pet_deposit="400", fenced_yard="1")
    assert p["pet_weight_limit"] == 50 and p["pet_count_limit"] == 2 and p["pet_deposit"] == 400 and p["fenced_yard"] == 1
    assert store.update_place(p["id"], fenced_yard="")["fenced_yard"] is None


# ------------------------------------------------------------------ money
def test_pet_deposit_only_in_cash_at_move_in(store):
    s = _search(store)
    p = _place(store, s["id"], price=1000, deposit=1000, pet_fee=200, pet_deposit=400)
    cost = money.true_monthly_cost(p, "rent", None, 1)
    base = money.true_monthly_cost({**p, "pet_deposit": None}, "rent", None, 1)
    assert cost["total"] == base["total"]
    cash = cost["cash_at_move_in"]
    assert cash["total"] == 1000 + 1000 + 200 + 400
    assert any(x["label"].startswith("Pet deposit") and x["amount"] == 400 for x in cash["parts"])


# ------------------------------------------------------------------ per-place checklist
def test_place_checklist_ticks_are_per_place(store):
    s = _search(store)
    a, b = _place(store, s["id"], title="A"), _place(store, s["id"], title="B")
    n = len(store.visible_checklist())
    item = store.visible_checklist()[0]
    store.set_place_checklist(a["id"], item["id"], True)
    assert store.place_checklist_left(a["id"]) == n - 1 and store.place_checklist_left(b["id"]) == n
    assert next(i for i in store.place_checklist(a["id"]) if i["id"] == item["id"])["done_here"] is True
    assert next(i for i in store.place_checklist(b["id"]) if i["id"] == item["id"])["done_here"] is False
    store.set_place_checklist(a["id"], item["id"], False)
    assert store.place_checklist_left(a["id"]) == n
    store.set_place_checklist(a["id"], item["id"], True)
    store.delete_place(a["id"])  # ticks go with the place
    store.delete_checklist_item(item["id"])


def test_place_page_and_route(store):
    s = _search(store)
    p = _place(store, s["id"], application_fee=45)
    soon = (helpers.today() + timedelta(days=3)).isoformat()
    store.add_place_date(p["id"], "application_deadline", soon)
    c = local_client(store)
    html = c.get(f"/places/{p['id']}").text
    assert "Applying here" in html and "Apply by" in html and "in 3 days" in html and "$45" in html
    item = store.visible_checklist()[0]
    r = c.post(f"/places/{p['id']}/checklist/{item['id']}", data={"value": "1"}, follow_redirects=False)
    assert r.status_code in (302, 303)
    assert store.place_checklist_left(p["id"]) == len(store.visible_checklist()) - 1
    assert c.post(f"/places/999/checklist/{item['id']}", data={"value": "1"}).status_code == 404
    assert c.post(f"/places/{p['id']}/checklist/9999", data={"value": "1"}).status_code == 404


def test_buy_search_has_no_applying_section(store):
    s = store.add_search("Buy", "buy")
    p = _place(store, s["id"])
    assert "Applying here" not in local_client(store).get(f"/places/{p['id']}").text


# ------------------------------------------------------------------ Today
def test_today_apply_by_with_items_left(store):
    s = _search(store)
    p = _place(store, s["id"], title="Oak")
    day = (helpers.today() + timedelta(days=3)).isoformat()
    store.add_place_date(p["id"], "application_deadline", day)
    rows = today.coming_up(store, s, [])
    row = next(r for r in rows if r["kind"] == "key_date")
    assert row["text"] == f"Apply by {helpers.day_text(day)}, in 3 days"
    n = len(store.visible_checklist())
    assert row["prep"] == f"{n} application items still to do for this place."
    html = local_client(store).get("/today").text
    assert "Apply by" in html and "still to do for this place" in html


def test_close_tours_note():
    base = datetime(2030, 5, 6, 17, 0, tzinfo=timezone.utc)
    tours = [{"id": 1, "starts_at": base.isoformat()}, {"id": 2, "starts_at": (base + timedelta(minutes=15)).isoformat()},
             {"id": 3, "starts_at": (base + timedelta(hours=3)).isoformat()}]
    notes = today.close_tour_notes(tours)
    assert set(notes) == {2} and "15 minutes apart; check the drive" in notes[2]
    assert today.close_tour_notes([{"id": 1, "starts_at": base.isoformat()},
                                   {"id": 2, "starts_at": (base + timedelta(days=1)).isoformat()}]) == {}


def test_today_shows_close_tour_note(store):
    s = _search(store)
    a, b = _place(store, s["id"], title="A"), _place(store, s["id"], title="B")
    start = datetime.now(timezone.utc) + timedelta(days=1)
    store.add_tour(a["id"], start.isoformat())
    store.add_tour(b["id"], (start + timedelta(minutes=20)).isoformat())
    assert "20 minutes apart; check the drive" in local_client(store).get("/today").text


def test_migration_is_idempotent_on_reopen(tmp_path):
    path = tmp_path / "x.db"
    Store(path).close()
    s = Store(path)
    assert s.schema_version >= 4
    s.close()

def test_search_form_saves_pets_and_fenced_yard_criterion(store):
    s = _search(store)
    c = local_client(store)
    r = c.post(f"/search/{s['id']}", data={"name": "Pets", "pet_kind": "dog", "pet_weight": "60", "pet_count": "2"}, follow_redirects=False)
    assert r.status_code in (302, 303)
    got = store.get_search(s["id"])
    assert (got["pet_kind"], got["pet_weight"], got["pet_count"]) == ("dog", 60, 2)
    html = c.get(f"/search?id={s['id']}").text
    assert "Your pets" in html and "Fenced yard" in html
    c.post(f"/search/{s['id']}/criteria", data={"kind": "fenced_yard", "weight": "10"})
    assert [x["kind"] for x in store.list_criteria(s["id"])] == ["fenced_yard"]
