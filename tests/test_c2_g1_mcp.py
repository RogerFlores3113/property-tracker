"""Cycle 2, group G1: Claude's tools say what the web pages say (people sharing, Today, scams, all-or-nothing searches,
one commute per important place, plain words, stage rules, photo note)."""
from datetime import datetime, timedelta, timezone

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from mcp_util import call, server, structured, text

SCAM = "Please wire the deposit by Western Union before you see it. I am out of the country."


def err(srv, tool, **args) -> str:
    with pytest.raises(ToolError) as e:
        call(srv, tool, **args)
    return str(e.value)


@pytest.fixture
def srv(store):
    s = server(store)
    call(s, "create_search", name="UIUC", mode="rent", move_in="2027-07-31", budget_max=2500, people=2,
         anchors=[{"name": "Campus", "lat": 40.1074, "lng": -88.2272}],
         criteria=[{"kind": "price", "weight": 30, "dealbreaker": True, "target": {"max": 2500}},
                   {"kind": "laundry", "weight": 20, "target": {"want": "in_unit"}},
                   {"kind": "commute", "weight": 25, "target": {"anchor": "Campus", "mode": "bike", "minutes": 15}}])
    return s


def add(srv, **kw):
    return structured(call(srv, "add_place", **kw))["place_id"]


def in_days(n, hour=10):
    d = datetime.now(timezone.utc) + timedelta(days=n)
    return d.strftime(f"%Y-%m-%d {hour:02d}:00")


# 1 ------------------------------------------------------------------------------------------------ people
def test_people_shows_per_person_everywhere(srv, store):
    a = add(srv, title="Alpha", address="1 A St", price=2000, utilities_estimate=100, lat=40.11, lng=-88.23)
    b = add(srv, title="Beta", address="2 B St", price=1800, utilities_estimate=100, lat=40.11, lng=-88.23)
    assert store.current_search()["people"] == 2
    assert "$1,050 a month each for 2 people" in text(call(srv, "get_place", place_id=a))
    assert "$1,050 a month each for 2 people" in text(call(srv, "list_places"))
    cmp = text(call(srv, "compare_places", place_ids=[a, b]))
    assert "Per person (2 people)" in cmp and "$1,050" in cmp and "$950" in cmp
    assert "2 people sharing the cost" in text(call(srv, "get_overview"))


def test_people_can_be_changed_and_is_checked(srv, store):
    call(srv, "update_search", people=3)
    assert store.current_search()["people"] == 3
    assert "1 to 20" in err(srv, "update_search", people=21)
    assert "1 to 20" in err(srv, "create_search", name="Z", people=0)
    assert not [s for s in store.list_searches() if s["name"] == "Z"]


def test_one_person_shows_no_per_person_line(store):
    s = server(store)
    call(s, "create_search", name="Solo")
    pid = add(s, title="Solo flat", address="1 S St", price=1000, utilities_estimate=50)
    assert "each for" not in text(call(s, "get_place", place_id=pid))


# 2 ------------------------------------------------------------------------------------------------ Today
def test_todays_list_matches_the_web_today(srv, store):
    from prophelper import today
    good = add(srv, title="Good Flat", address="1 G St", price=1500, utilities_estimate=50, laundry="in_unit", lat=40.1075, lng=-88.2271)
    scam = add(srv, title="Scam Flat", address="2 S St", price=900, utilities_estimate=50, listing_text=SCAM)
    over = add(srv, title="Too Dear", address="3 D St", price=3500, utilities_estimate=50)
    call(srv, "add_tour", place_id=good, starts_at=in_days(10))
    out = text(call(srv, "todays_list"))
    assert "Best fits right now:" in out and "Good Flat" in out.split("Tours in the next")[0]
    assert "Tours in the next 14 days:" in out and "Good Flat" in out.split("Tours in the next 14 days:")[1].split("Dates in")[0]
    new = out.split("New places the user has not looked at:")[1]
    assert "Scam Flat" not in new and "Too Dear" not in new
    web = today.build(store, store.current_search())
    assert [p["id"] for p in web["fits"]] == structured(call(srv, "todays_list"))["best_fits"]
    assert scam not in [p["id"] for p in web["new"]] and over not in [p["id"] for p in web["new"]]


def test_todays_list_includes_key_dates(srv, store):
    pid = add(srv, title="Dated", address="4 K St", price=1500, utilities_estimate=50)
    store.add_place_date(pid, "other", (datetime.now() + timedelta(days=9)).strftime("%Y-%m-%d"), note="Deposit due")
    assert "Deposit due" in text(call(srv, "todays_list"))


# 3 ------------------------------------------------------------------------------------------------ scams
def test_scam_sorts_last_and_never_wins_a_best_of(srv):
    good = add(srv, title="Fine Place", address="1 F St", price=1700, utilities_estimate=50, laundry="in_unit", lat=40.1075, lng=-88.2271)
    scam = add(srv, title="Too Cheap", address="2 T St", price=800, utilities_estimate=50, laundry="in_unit", lat=40.1075, lng=-88.2271,
               listing_text=SCAM)
    lst = text(call(srv, "list_places"))
    assert lst.index("Fine Place") < lst.index("Too Cheap")
    assert "Check first: possible scam" in lst.split("Too Cheap")[1]
    cmp = text(call(srv, "compare_places", place_ids=[scam, good]))
    assert "Lowest true monthly cost: #%d" % good in cmp and "Lowest true monthly cost: #%d" % scam not in cmp
    assert "Highest score: #%d" % good in cmp
    assert "Check first: possible scam" in cmp and "Cheaper, but not a place to pick: #%d" % scam in cmp


def test_no_fitting_place_means_no_lowest_cost_named(srv):
    s1 = add(srv, title="Scam A", address="1 A St", price=800, utilities_estimate=50, listing_text=SCAM)
    s2 = add(srv, title="Scam B", address="2 B St", price=900, utilities_estimate=50, listing_text=SCAM)
    cmp = text(call(srv, "compare_places", place_ids=[s1, s2]))
    assert "Lowest true monthly cost: #" not in cmp and "No place here fits" in cmp


# 4 ------------------------------------------------------------------------------------------------ create_search
def test_create_search_saves_nothing_when_anything_is_wrong(store):
    s = server(store)
    msg = err(s, "create_search", name="Half", anchors=[{"name": "Work"}],
              criteria=[{"kind": "price", "weight": 20, "target": {"max": 1500}},
                        {"kind": "laundry", "weight": 500},
                        {"kind": "commute", "target": {"anchor": "Nowhere", "mode": "bike", "minutes": 10}},
                        {"kind": "teleport"}])
    assert "Nothing was saved" in msg and "weight is optional" in msg and "0 to 100" in msg
    assert "Criterion 2" in msg and "Criterion 3" in msg and "Criterion 4" in msg and "Criterion 1" not in msg
    assert store.list_searches() == [] and store.list_anchors() == []


def test_create_search_accepts_field_and_points_at_new_anchor(store):
    s = server(store)
    r = call(s, "create_search", name="Ok", anchors=[{"name": "Work", "lat": 40.1, "lng": -88.2}],
             criteria=[{"field": "price", "target": {"max": 1500}},
                       {"kind": "commute", "target": {"anchor": "Work", "mode": "walk", "minutes": 20}}])
    assert "I read field as the criterion's kind" in text(r)
    assert len(store.list_criteria(store.current_search()["id"])) == 2


def test_update_search_example_is_right_and_changes_nothing_on_error(srv, store):
    n = len(store.list_criteria(store.current_search()["id"]))
    msg = err(srv, "update_search", name="Renamed", add_criteria_list=[{"kind": "commute", "anchor": "Campus", "weight": 5}])
    assert '"anchor": "Campus"' in msg and '"anchor": 1600' not in msg and "Nothing was changed" in msg
    assert store.current_search()["name"] == "UIUC" and len(store.list_criteria(store.current_search()["id"])) == n
    msg2 = err(srv, "update_search", add_criteria_list=[{"kind": "price", "max": 1200}])
    assert '"max": 1600' in msg2


# 5 ------------------------------------------------------------------------------------------------ commutes
def test_commute_is_shown_once_in_the_criterion_mode(srv, store):
    pid = add(srv, title="Near", address="1 N St", price=1500, utilities_estimate=50, lat=40.1075, lng=-88.2271)
    for reply_text in (text(call(srv, "list_places")), text(call(srv, "add_places", places=[{"title": "N2", "address": "2 N St", "lat": 40.108, "lng": -88.227}]))):
        line = next(x for x in reply_text.splitlines() if "Campus" in x)
        assert line.count("Campus") == 1 and "bike" in line and "walk" not in line and "drive" not in line
    out = text(call(srv, "get_place", place_id=pid))
    commutes = next(x for x in out.splitlines() if x.startswith("Commutes:"))
    assert commutes.count("Campus") == 1 and "bike" in commutes
    other = next(x for x in out.splitlines() if x.startswith("Other ways:"))
    assert "walk" in other and "bike" not in other


# 6 ------------------------------------------------------------------------------------------------ plain words
def test_no_raw_codes_in_values(srv, store):
    a = add(srv, title="Plain A", address="1 P St", price=1500, utilities_estimate=50, laundry="in_building", parking="street", pets="both",
            lat=40.1075, lng=-88.2271)
    b = add(srv, title="Plain B", address="2 P St", price=1500, utilities_estimate=50, laundry="hookups", parking="none", pets="none")
    out = text(call(srv, "get_place", place_id=a)) + text(call(srv, "compare_places", place_ids=[a, b])) + text(call(srv, "get_overview"))
    for raw in ("in_unit", "in_building", "hookups", "(rent)", "(buy)"):
        assert raw not in out
    assert "In the building" in out and "Hookups only" in out and "cats and dogs" in out and "renting" in out


def test_overview_names_criteria_with_no_label(srv):
    out = text(call(srv, "get_overview"))
    crit = next(x for x in out.splitlines() if x.startswith("Criteria:"))
    assert "Monthly cost, at most $2,500" in crit and "Bike to Campus" in crit
    assert "criterion label\">price" not in crit and ">laundry<" not in crit


def test_no_trailing_minus_and_utilities_sentence(srv):
    pid = add(srv, title="Util", address="1 U St", price=1500, utilities_estimate=80, utilities_included="x")
    out = text(call(srv, "get_place", place_id=pid))
    assert "; -" not in out and not any(x.rstrip().endswith("- ") for x in out.splitlines())
    from prophelper.mcp_server import _plain_note
    assert _plain_note("A guess, not from the listing. The listing includes: False") == "A guess, not from the listing. Utilities: not included in the rent"
    assert "includes: False" not in out


def test_utilities_false_is_stored_as_words(srv, store):
    pid = add(srv, title="Util2", address="2 U St", price=1500, utilities_estimate=80, utilities_included=False)
    assert "includes: False" not in text(call(srv, "get_place", place_id=pid))
    assert "not included in the rent" in text(call(srv, "get_place", place_id=pid))


# 7 ------------------------------------------------------------------------------------------------ stages
def test_add_place_stage_obeys_the_one_step_rule(srv, store):
    assert "one stage at a time" in err(srv, "add_place", title="X", address="1 X St", stage="Applied")
    assert store.list_places() == []
    ok = add(srv, title="Y", address="2 Y St", stage="Contacted")
    assert store.get_place(ok)["stage"] == "Contacted"
    passed = add(srv, title="Z", address="3 Z St", stage="Passed")
    assert store.get_place(passed)["stage"] == "Passed"
    assert "one stage at a time" in err(srv, "add_places", places=[{"title": "W", "address": "4 W St", "stage": "Toured"}])


def test_ai_cannot_mark_toured_before_the_tour_date(srv, store):
    pid = add(srv, title="Tour me", address="1 T St")
    call(srv, "add_tour", place_id=pid, starts_at=in_days(5))
    assert store.get_place(pid)["stage"] == "Tour booked"  # the app's own follow-on move from Saved stays allowed
    msg = err(srv, "move_place", place_id=pid, stage="Toured")
    assert msg.startswith("That tour is on ") and msg.endswith("move it to Toured after you go.")
    assert store.get_place(pid)["stage"] == "Tour booked"
    store.move_stage(pid, "Toured")  # the user may
    other = add(srv, title="Went", address="2 W St", stage="Contacted")
    call(srv, "add_tour", place_id=other, starts_at=in_days(-2))
    call(srv, "move_place", place_id=other, stage="Toured")
    assert store.get_place(other)["stage"] == "Toured"


# 8 ------------------------------------------------------------------------------------------------ photos
def test_photo_links_get_a_note(srv):
    out = text(call(srv, "add_place", title="Pics", address="1 P St", photo_urls=["https://example.com/a.jpg"]))
    assert "Photos load from whatever site the link points to" in out and "turns photos on" in out
    assert "Photos load from" not in text(call(srv, "add_place", title="NoPics", address="2 P St"))
    many = text(call(srv, "add_places", places=[{"title": "P3", "address": "3 P St", "photo_urls": ["https://example.com/b.jpg"]}]))
    assert "Photos load from" in many
