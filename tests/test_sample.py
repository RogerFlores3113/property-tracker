"""Sample data: loads a believable search, shows the right things, and removes cleanly."""
from prophelper import enrich
from prophelper.sample_data import load_sample_data


def test_sample_loads_and_marks_everything(store):
    n = load_sample_data(store)
    assert n == 10 and store.has_sample_data()
    assert store.current_search()["is_sample"]
    assert all(p["is_sample"] for p in store.list_places(include_archived=True))
    assert store.list_anchors() and store.list_criteria(store.current_search()["id"])


def test_sample_shows_the_interesting_cases(sample_store):
    s = sample_store
    s.update_search(s.current_search()["id"], hide_dealbreakers=True)
    search = s.current_search()
    rows = {p["title"]: p for p in enrich.enrich_places(s, search)}
    scam = rows["Bright Lakeview Condo"]
    assert len(scam["flags"]) >= 3
    hidden = [p for p in rows.values() if p["hidden_by_dealbreaker"]]
    assert hidden  # deal-breakers hide some places
    assert any(p["cost"]["missing"] for p in rows.values())  # a place with a missing number
    assert any(p["lat"] is None for p in rows.values())  # one with no map point
    assert s.upcoming_tours(7)  # a tour in the next few days
    assert s.waiting_on_reply()  # a contact waiting on a reply


def test_sample_remove_keeps_your_own(store):
    mine = store.add_search("Mine", "rent")
    own, _ = store.add_place(title="My place", address="7 Real St", search_id=mine["id"])
    load_sample_data(store)
    counts = store.remove_sample_data()
    assert counts["places"] == 10
    assert not store.has_sample_data()
    assert [p["title"] for p in store.list_places(include_archived=True)] == ["My place"]
    assert [x["name"] for x in store.list_searches(include_archived=True)] == ["Mine"]
    assert store.get_place(own["id"])["title"] == "My place"
    assert store.list_anchors() == [] and store.list_contacts() == []


def test_sample_loads_once(store):
    load_sample_data(store)
    assert load_sample_data(store) == 0
    assert len(store.list_searches(include_archived=True)) == 1
