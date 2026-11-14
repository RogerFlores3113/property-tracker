"""Store: settings, searches, criteria, anchors, places, stages, dedupe, events, tours, contacts, backups."""
import pytest

from prophelper.store import NotFound, StageRuleError, Store


@pytest.fixture
def s(store):
    store.add_search("Test search", "rent", budget_max=1600)
    return store


def test_new_database_has_default_settings_and_version(store):
    assert store.schema_version >= 1
    assert store.get_setting("ai_model") == "claude-sonnet-5-5"
    assert store.get_setting_int("follow_up_days") == 3
    assert store.get_setting_bool("map_tiles") is False  # new folders start with map pictures off
    assert store.get_setting_bool("geocode") is False
    assert len(store.list_checklist()) >= 5  # the default tour checklist is seeded


def test_settings_round_trip(store):
    store.set_setting("follow_up_days", 5)
    assert store.get_setting_int("follow_up_days") == 5
    assert store.all_settings()["follow_up_days"] == "5"


def test_migrations_reopen_cleanly(tmp_path):
    path = tmp_path / "again.db"
    a = Store(path)
    a.add_search("S")
    v = a.schema_version
    a.close()
    b = Store(path)
    assert b.schema_version == v and len(b.list_searches()) == 1
    b.close()


# ---- searches, criteria, anchors
def test_search_crud_and_current(store):
    a = store.add_search("A", "rent")
    b = store.add_search("B", "buy", target_close="2027-05-01")
    store.set_current_search(b["id"])
    assert store.current_search()["id"] == b["id"]
    store.update_search(b["id"], name="B2", area="Here")
    assert store.get_search(b["id"])["name"] == "B2"
    store.archive_search(a["id"])
    assert [x["id"] for x in store.list_searches()] == [b["id"]]
    assert len(store.list_searches(include_archived=True)) == 2
    store.unarchive_search(a["id"])
    store.delete_search(a["id"])
    assert len(store.list_searches(include_archived=True)) == 1
    with pytest.raises(NotFound):
        store.get_search(a["id"])


def test_search_needs_a_name_and_a_known_mode(store):
    with pytest.raises(ValueError):
        store.add_search("")
    with pytest.raises(ValueError):
        store.add_search("X", "lease-to-own")


def test_criteria_crud(s):
    sid = s.current_search()["id"]
    c = s.add_criterion(sid, "price", weight=30, dealbreaker=True, target={"max": 1600})
    assert c["target"] == {"max": 1600} and c["dealbreaker"]
    s.update_criterion(c["id"], weight=50, target={"max": 1500})
    assert s.get_criterion(c["id"])["weight"] == 50
    assert s.list_criteria(sid)[0]["target"] == {"max": 1500}
    with pytest.raises(ValueError):
        s.add_criterion(sid, "colour")
    s.delete_criterion(c["id"])
    assert s.list_criteria(sid) == []


def test_anchor_crud_and_commutes(s):
    a = s.add_anchor("Work", "1 Main", 40.1, -88.2)
    p, _ = s.add_place(title="P", address="1 A St")
    s.set_commute(p["id"], a["id"], "bike", 12, "you")
    assert s.list_commutes(p["id"])[0]["minutes"] == 12
    s.clear_commute(p["id"], a["id"], "bike")
    assert s.list_commutes(p["id"]) == []
    s.set_commute(p["id"], a["id"], "bike", 9)
    s.delete_anchor(a["id"])
    assert s.list_commutes(p["id"]) == []  # they go with the anchor


# ---- places
def test_add_place_defaults(s):
    p, created = s.add_place(title="Maple", address="410 Maple Row Lane", price="1,495", beds="1", laundry="in-unit")
    assert created and p["stage"] == "Saved" and p["price"] == 1495 and p["laundry"] == "in_unit"
    assert s.get_place(p["id"])["title"] == "Maple"


def test_place_title_falls_back_to_address_then_url(s):
    p, _ = s.add_place(address="1 Oak St")
    assert p["title"] == "1 Oak St"
    q, _ = s.add_place(url="https://www.example.com/x/1")
    assert q["title"]


def test_place_needs_something(s):
    with pytest.raises(ValueError):
        s.add_place()


def test_bad_numbers_are_refused(s):
    with pytest.raises(ValueError):
        s.add_place(title="x", price="lots")


def test_update_place_logs_what_changed(s):
    p, _ = s.add_place(title="A", address="1 A St", price=1000)
    s.update_place(p["id"], price=1100)
    assert s.get_place(p["id"])["price"] == 1100
    s.update_place(p["id"], by="ai", price=1200)  # an AI replacing a value writes the old one to the timeline
    assert any("was 1100" in e["body"] for e in s.list_events(p["id"]))


def test_dedupe_by_link_and_by_address(s):
    a, c1 = s.add_place(title="A", url="https://www.example.com/l/1?utm_source=x", address="1 Oak St", price=1000, notes="mine")
    b, c2 = s.add_place(title="Other name", url="https://example.com/l/1", beds=2, price=999, notes="theirs")
    assert c1 and not c2 and a["id"] == b["id"]
    got = s.get_place(a["id"])
    assert got["price"] == 1000 and got["beds"] == 2 and got["notes"] == "mine"  # only empty fields are filled
    c, c3 = s.add_place(title="Again", address="1  OAK street", unit="")
    assert not c3 and c["id"] == a["id"]
    d, c4 = s.add_place(title="Unit 2", address="1 Oak St", unit="2")
    assert c4 and d["id"] != a["id"]  # a different unit is a different place


def test_same_address_in_another_search_is_not_a_duplicate(s):
    other = s.add_search("Other")
    a, _ = s.add_place(title="A", address="9 Elm St", search_id=s.list_searches()[0]["id"])
    b, created = s.add_place(title="A", address="9 Elm St", search_id=other["id"])
    assert created and a["id"] != b["id"]


def test_ai_never_touches_user_notes(s):
    p, _ = s.add_place(title="A", address="1 A St", notes="my private thought")
    s.update_place(p["id"], by="ai", notes="AI wants this", ai_notes="AI summary", rating=5, hidden=True)
    got = s.get_place(p["id"])
    assert got["notes"] == "my private thought" and got["rating"] is None and not got["hidden"]
    assert "AI summary" in got["ai_notes"]
    # an AI add of a repeat also leaves notes alone
    s.add_place(by="ai", address="1 A St", title="A", notes="more AI text")
    assert s.get_place(p["id"])["notes"] == "my private thought"


def test_ai_text_for_notes_on_a_new_place_goes_to_ai_notes(s):
    p, _ = s.add_place(by="ai", title="New", address="2 B St", notes="found on a site")
    assert p["notes"] == "" and "found on a site" in p["ai_notes"]


def test_stage_moves_user_anywhere_ai_forward_only(s):
    p, _ = s.add_place(title="A", address="1 A St")
    s.move_stage(p["id"], "Toured")
    s.move_stage(p["id"], "Saved")  # you can go back
    s.move_stage(p["id"], "Contacted", by_ai=True)
    with pytest.raises(StageRuleError):
        s.move_stage(p["id"], "Toured", by_ai=True)  # one stage at a time
    s.move_stage(p["id"], "Tour booked", by_ai=True)
    s.move_stage(p["id"], "Toured", by_ai=True)
    with pytest.raises(StageRuleError):
        s.move_stage(p["id"], "Saved", by_ai=True)
    s.move_stage(p["id"], "Passed", by_ai=True)
    with pytest.raises(StageRuleError):
        s.move_stage(p["id"], "Toured", by_ai=True)  # not out of Passed
    assert s.get_place(p["id"])["stage"] == "Passed"
    with pytest.raises(StageRuleError):
        s.move_stage(p["id"], "Closing")  # a buy stage in a rent search
    stages_seen = [e["body"] for e in s.list_events(p["id"]) if e["kind"] == "stage"]
    assert any("Passed" in b for b in stages_seen)


def test_buy_search_uses_buy_stages(store):
    store.add_search("Buy", "buy")
    p, _ = store.add_place(title="House", address="5 Home Rd")
    store.move_stage(p["id"], "Under contract")
    assert store.get_place(p["id"])["stage"] == "Under contract"
    assert store.counts_by_stage(store.current_search()["id"])["Under contract"] == 1


def test_archive_unarchive_delete(s):
    p, _ = s.add_place(title="A", address="1 A St")
    s.archive_place(p["id"])
    assert s.count_places() == 0 and s.count_places(include_archived=True) == 1
    s.unarchive_place(p["id"])
    assert s.count_places() == 1
    s.delete_place(p["id"])
    with pytest.raises(NotFound):
        s.get_place(p["id"])


def test_list_places_filters(s):
    s.add_place(title="Cheap", address="1 A St", price=900)
    s.add_place(title="Dear", address="2 A St", price=2000)
    assert [p["title"] for p in s.list_places(sort="price")] == ["Cheap", "Dear"]
    assert [p["title"] for p in s.list_places(query="dear")] == ["Dear"]


def test_new_places_until_opened(s):
    p, _ = s.add_place(title="A", address="1 A St")
    assert [x["id"] for x in s.new_places()] == [p["id"]]
    s.mark_seen(p["id"])
    assert s.new_places() == []


# ---- events, tours, contacts
def test_events_and_ai_add_count(s):
    p, _ = s.add_place(title="A", address="1 A St")
    s.add_event(p["id"], "note", "called")
    assert s.list_events(p["id"])[0]["body"] == "called"
    s.add_place(by="ai", title="B", address="2 B St")
    assert s.count_ai_adds_since("2000-01-01T00:00:00+00:00") == 1


def test_tour_books_and_advances_stage(s):
    p, _ = s.add_place(title="A", address="1 A St")
    t = s.add_tour(p["id"], "2099-01-01T15:00")
    assert s.get_place(p["id"])["stage"] == "Tour booked"
    assert s.list_tours(p["id"])[0]["id"] == t["id"]
    s.delete_tour(t["id"])
    assert s.list_tours(p["id"]) == []


def test_contacts_log_and_waiting_on_reply(s):
    p, _ = s.add_place(title="A", address="1 A St")
    c = s.add_contact("Office", role="leasing agent", company="Maple")
    s.link_contact(p["id"], c["id"])
    assert [x["id"] for x in s.contacts_for_place(p["id"])] == [c["id"]]
    s.log_contact(c["id"], "email", "asked about parking", direction="out", place_id=p["id"], at="2020-01-01T00:00:00+00:00")
    assert s.waiting_on_reply()[0]["contact"]["id"] == c["id"]
    s.log_contact(c["id"], "email", "they replied", direction="in", place_id=p["id"])
    assert s.waiting_on_reply() == []


# ---- backup, export, no-delete
def test_backup_and_export(s, tmp_path):
    s.add_place(title="A", address="1 A St")
    s.backup_to(tmp_path / "b.db")
    copy = Store(tmp_path / "b.db")
    assert copy.count_places() == 1
    copy.close()
    dump = s.export_all()
    assert dump["places"] and dump["searches"]


def test_no_delete_mode_refuses_every_delete(s):
    p, _ = s.add_place(title="A", address="1 A St")
    s.enable_no_delete()
    with pytest.raises(PermissionError):
        s.delete_place(p["id"])
    with pytest.raises(PermissionError):
        s.archive_place(p["id"])
    assert s.get_place(p["id"])["title"] == "A"
