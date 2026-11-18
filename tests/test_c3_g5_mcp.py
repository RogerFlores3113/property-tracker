"""Cycle 3, G5: Claude's tools name the bad place, say when an update changed nothing, keep Passed out of the top
places, refuse a parking word they would have to guess, and show the move-in gap both ways."""
import pytest
from mcp.server.fastmcp.exceptions import ToolError

from mcp_util import call, server, text


def err(srv, tool, **args) -> str:
    with pytest.raises(ToolError) as e:
        call(srv, tool, **args)
    return str(e.value)


@pytest.fixture
def srv(store):
    s = server(store)
    call(s, "create_search", name="UIUC", mode="rent", move_in="2027-08-15", budget_max=2500,
         criteria=[{"kind": "price", "weight": 30, "target": {"max": 2500}}])
    return s


def test_add_places_names_the_place_with_the_bad_value(srv, store):
    msg = err(srv, "add_places", places=[{"title": "Fine", "price": 1000}, {"title": "Elm Court", "price": "lots"}])
    assert "Place 2" in msg and "Elm Court" in msg and "Nothing was saved" in msg
    assert store.count_places() == 0  # all or nothing


def test_add_place_names_the_place(srv):
    msg = err(srv, "add_place", title="Oak Flats", price="lots")
    assert "Oak Flats" in msg and "Nothing was saved" in msg


def test_reserved_parking_is_refused_with_the_allowed_list(srv, store):
    msg = err(srv, "add_place", title="Res", parking="reserved")
    assert "garage, covered, lot, street, none" in msg
    assert store.count_places() == 0
    msg = err(srv, "add_places", places=[{"title": "Two", "parking": "Reserved spot"}])
    assert "Place 1" in msg and "garage" in msg


def test_update_place_that_changes_nothing_says_so(srv, store):
    call(srv, "add_place", title="A", price=1200)
    pid = store.list_places()[0]["id"]
    first = text(call(srv, "update_place", place_id=pid, price=1300))
    assert first.startswith("Updated") and "nothing changed" not in first.lower()
    again = text(call(srv, "update_place", place_id=pid, price=1300))
    assert again.startswith("Nothing changed") and "Updated" not in again.splitlines()[0]
    events = len(store.list_events(pid))
    call(srv, "update_place", place_id=pid, price=1300)
    assert len(store.list_events(pid)) == events  # nothing was written


def test_overview_top_places_leave_out_passed(srv, store):
    call(srv, "add_place", title="Keep", price=1000)
    call(srv, "add_place", title="Dropped", price=900)
    dropped = next(p for p in store.list_places() if p["title"] == "Dropped")
    store.move_stage(dropped["id"], "Passed")
    out = text(call(srv, "get_overview"))
    top = out.split("Top places:")[1]
    assert "Keep" in top and "Dropped" not in top


def test_get_place_shows_the_move_in_gap_both_ways(srv, store):
    call(srv, "add_place", title="Early", price=1000, available_from="2027-07-01")
    call(srv, "add_place", title="Late", price=1000, available_from="2027-09-15")
    call(srv, "add_place", title="Close", price=1000, available_from="2027-08-18")
    by = {p["title"]: p["id"] for p in store.list_places()}
    assert "Available Jul 1, 2027, 6 weeks before your move-in" in text(call(srv, "get_place", place_id=by["Early"]))
    assert "4 weeks after your move-in" in text(call(srv, "get_place", place_id=by["Late"]))
    close = text(call(srv, "get_place", place_id=by["Close"]))
    assert "before your move-in" not in close and "after your move-in" not in close


def test_place_page_shows_the_early_warning(client, store):
    s = store.add_search("R", "rent", move_in="2027-08-15")
    p, _ = store.add_place(search_id=s["id"], by="you", title="Early", available_from="2027-07-01")
    html = client.get(f"/places/{p['id']}").text
    assert "6 weeks before your move-in" in html
