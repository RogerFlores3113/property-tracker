import pytest
from conftest import local_client


@pytest.mark.parametrize("word", ["yes", "no", "true", "false", "y", "n", "Yes", "1", "0", ""])
def test_add_form_yes_no_words(store, word):
    store.add_search("Home")
    c = local_client(store)
    r = c.post("/add/save", data={"title": "Elm", "address": "1 Elm St", "dishwasher": word, "fenced_yard": word},
               follow_redirects=False)
    assert r.status_code in (302, 303), r.text[:300]


def _rent(store):
    s = store.add_search("Home")
    return s


def test_dealbreaker_and_toggles_take_words(store):
    s = _rent(store)
    c = local_client(store)
    r = c.post(f"/search/{s['id']}/criteria", data={"kind": "dishwasher", "label": "Dishwasher", "weight": "10", "dealbreaker": "yes"},
               follow_redirects=False)
    assert r.status_code in (302, 303)
    assert store.list_criteria(s["id"])[-1]["dealbreaker"] == 1


def test_web_added_place_stays_under_new_places(store):
    from prophelper import today
    s = _rent(store)
    c = local_client(store)
    r = c.post("/add/save", data={"title": "Elm Court", "address": "1 Elm St", "price": "1500"}, follow_redirects=False)
    assert r.status_code in (302, 303)
    assert "fresh=1" in r.headers["location"]
    c.get(r.headers["location"])  # land on the place page, as the browser does
    assert [x["place"]["title"] if "place" in x else x["title"] for x in today.new_places(store, s)] == ["Elm Court"]
    pid = store.list_places()[0]["id"] if hasattr(store, "list_places") else None
    c.get(f"/places/{pid}")  # opened again the normal way: now seen
    assert today.new_places(store, s) == []


def test_board_closing_countdown_on_offer_cards(store):
    from datetime import date, timedelta
    close = (date.today() + timedelta(days=30)).isoformat()
    s = store.add_search("Buy", "buy", target_close=close)
    store.add_place(search_id=s["id"], title="Saved House", price=400000)
    store.add_place(search_id=s["id"], title="Offer House", price=400000, stage="Offer drafted")
    c = local_client(store)
    html = c.get("/board").text
    assert html.count("Closing in 30 days") == 1
    i = html.index("Closing in 30 days")
    assert "Offer House" in html[:i] and "Saved House" not in html[html.rfind("<article", 0, i):i]


def test_compare_utilities_row(store):
    s = _rent(store)
    a, _ = store.add_place(search_id=s["id"], title="A", price=1500, utilities_included="Heat, water")
    b, _ = store.add_place(search_id=s["id"], title="B", price=1400, utilities_included="all")
    d, _ = store.add_place(search_id=s["id"], title="D", price=1300)
    html = local_client(store).get(f"/compare?ids={a['id']},{b['id']},{d['id']}").text
    i = html.index("Utilities included")
    row = html[i:html.index("</tr>", i)]
    assert "Heat, water" in row and ">All<" in row and "None listed" in row


def test_csv_and_json_userinfo_link_reason(store):
    from prophelper import csv_io, share
    s = _rent(store)
    plan = csv_io.plan_import(store, s["id"], ["Title", "Link"], [["A", "https://bob:pw@zillow.com/x"], ["B", "https://bob:p w@zillow.com"]], {0: "title", 1: "url"})
    for item in plan:
        assert "user name or password in it, so it will be left blank" in item["warnings"][0]
        assert "web address" not in item["warnings"][0]
        assert not item["values"].get("url")
    text = " ".join(share.left_out_lines({"link_userinfo": 1}))
    assert "user name or password" in text and "left blank" in text
    doc = {"format": "x", "search": {"name": "S"}, "places": [{"title": "A", "url": "https://bob:pw@zillow.com/x"}], "criteria": [], "anchors": []}
    rep = share.apply_import(store, share.check_doc(doc) if hasattr(share, "check_doc") else doc)
    assert rep["link_userinfo"] == 1 and rep["places"] == 1 and rep["link_unsafe"] == 0


def test_mcp_descriptions_show_nested_target():
    from prophelper import mcp_server
    src = open(mcp_server.__file__).read()
    assert '"target": {"anchor": "Campus", "mode": "bike", "minutes": 15}' in src
    assert "utilities_source" in src


def test_add_tour_reply_and_timeline_say_skipped(store):
    s = _rent(store)
    p, _ = store.add_place(search_id=s["id"], title="A", price=1500)
    store.add_tour(p["id"], "2027-01-10 10:00", by="ai")
    assert any("Contacted was skipped on purpose" in e["body"] for e in store.list_events(p["id"]))
