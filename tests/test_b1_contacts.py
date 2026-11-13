"""Contacts, the conversation log and "waiting on a reply"."""
from datetime import datetime, timedelta, timezone

import pytest


def _place(store, title="Maple"):
    s = store.current_search() or store.add_search("S", "rent")
    store.set_current_search(s["id"])
    return store.add_place(search_id=s["id"], title=title)[0]


def _ago(days):
    return datetime.now(timezone.utc) - timedelta(days=days)


# ---- waiting on a reply (the logic the pages show)
def test_waiting_when_last_line_is_out_and_old_enough(store):
    place = _place(store)
    c = store.add_contact("Sam")
    store.log_contact(c["id"], "email", "Any units?", direction="out", place_id=place["id"], at=_ago(5))
    rows = store.waiting_on_reply()
    assert [r["contact"]["id"] for r in rows] == [c["id"]] and rows[0]["days"] == 5 and rows[0]["place"]["id"] == place["id"]


def test_not_waiting_when_they_replied_last_or_it_is_recent(store):
    c = store.add_contact("Sam")
    store.log_contact(c["id"], "email", "Any units?", direction="out", at=_ago(6))
    store.log_contact(c["id"], "email", "Yes!", direction="in", at=_ago(5))
    assert store.waiting_on_reply() == []
    d = store.add_contact("Pat")
    store.log_contact(d["id"], "text", "Hello", direction="out", at=_ago(1))
    assert store.waiting_on_reply() == []


def test_follow_up_days_setting_changes_the_wait(store):
    c = store.add_contact("Sam")
    store.log_contact(c["id"], "call", "Left a message", direction="out", at=_ago(2))
    assert store.waiting_on_reply() == []
    store.set_setting("follow_up_days", "1")
    assert len(store.waiting_on_reply()) == 1


def test_waiting_shows_on_today_contacts_and_the_contact_page(client, store):
    place = _place(store)
    c = store.add_contact("Sam Landlord", company="Maple Co")
    store.log_contact(c["id"], "email", "Any units?", direction="out", place_id=place["id"], at=_ago(5))
    assert "Sam Landlord" in client.get("/today").text
    listing = client.get("/contacts").text
    assert "Waiting on a reply (5 days)" in listing and "1 person has not replied" in listing
    assert "have not replied" not in client.get("/contacts").text.replace("1 person has not replied", "")
    page = client.get(f"/contacts/{c['id']}").text
    assert "they have not replied" in page
    assert "Waiting on a reply (5 days)" in client.get(f"/places/{place['id']}").text
    client.post(f"/contacts/{c['id']}/log", data={"direction": "in", "kind": "email", "body": "Reply"})
    assert "Waiting on a reply" not in client.get("/contacts").text


def test_waiting_contacts_sort_first(client, store):
    a = store.add_contact("Aaron")
    z = store.add_contact("Zed")
    store.log_contact(z["id"], "email", "hi", direction="out", at=_ago(9))
    html = client.get("/contacts").text
    assert html.index("Zed") < html.index("Aaron")


# ---- the pages
def test_contacts_pages_render(client, sample_store):
    r = client.get("/contacts")
    assert r.status_code == 200 and "Maple Row leasing office" in r.text
    cid = sample_store.list_contacts()[0]["id"]
    page = client.get(f"/contacts/{cid}")
    assert page.status_code == 200 and "Conversation log" in page.text and "Asked about the July 31" in page.text
    assert client.get("/contacts/999").status_code == 404


def test_contact_search(client, store):
    store.add_contact("Alice Smith", company="Oak")
    store.add_contact("Bob Jones", company="Elm")
    html = client.get("/contacts?q=alice").text
    assert "Alice Smith" in html and "Bob Jones" not in html


def test_add_edit_delete_contact(client, store):
    r = client.post("/contacts", data={"name": "Dana <i>Agent</i>", "role": "leasing agent", "company": "X", "email": "d@example.com",
                                       "phone": "555", "notes": "n"}, follow_redirects=False)
    assert r.status_code == 303
    c = store.list_contacts()[0]
    assert c["name"] == "Dana <i>Agent</i>" and c["role"] == "leasing agent"
    assert "<i>Agent</i>" not in client.get(f"/contacts/{c['id']}").text
    client.post(f"/contacts/{c['id']}", data={"name": "Dana B", "role": "landlord", "company": "Y", "email": "", "phone": "", "notes": ""})
    assert store.get_contact(c["id"])["name"] == "Dana B" and store.get_contact(c["id"])["role"] == "landlord"
    client.post(f"/contacts/{c['id']}/delete", data={})
    assert store.list_contacts()
    client.post(f"/contacts/{c['id']}/delete", data={"confirm": "yes"})
    assert store.list_contacts() == []


@pytest.mark.parametrize("data", [{"name": ""}, {"name": "X", "role": "wizard"}])
def test_add_contact_rejects_bad_input(client, store, data):
    r = client.post("/contacts", data=data, follow_redirects=False)
    assert r.status_code == 303 and store.list_contacts() == []


def test_log_a_conversation_all_four_kinds_and_directions(client, store):
    place = _place(store)
    c = store.add_contact("Sam")
    for kind in ("call", "email", "text", "in person"):
        client.post(f"/contacts/{c['id']}/log", data={"kind": kind, "direction": "out", "body": kind, "place_id": str(place["id"])})
    log = store.list_contact_log(contact_id=c["id"])
    assert sorted(e["kind"] for e in log) == ["call", "email", "in person", "text"] and all(e["place_id"] == place["id"] for e in log)
    assert place["id"] in [p["id"] for p in store.places_for_contact(c["id"])]  # logging against a place links it
    client.post(f"/contacts/{c['id']}/log", data={"kind": "fax", "direction": "out"})
    client.post(f"/contacts/{c['id']}/log", data={"kind": "call", "direction": "sideways"})
    assert len(store.list_contact_log(contact_id=c["id"])) == 4


def test_log_with_a_day(client, store):
    c = store.add_contact("Sam")
    client.post(f"/contacts/{c['id']}/log", data={"kind": "call", "direction": "out", "day": "2027-01-05", "body": "x"})
    assert store.list_contact_log(contact_id=c["id"])[0]["at"].startswith("2027-01-05")


def test_delete_a_log_line(client, store):
    c = store.add_contact("Sam")
    e = store.log_contact(c["id"], "call", "x")
    client.post(f"/contact-log/{e['id']}/delete")
    assert store.list_contact_log(contact_id=c["id"]) == []


def test_link_and_unlink_from_the_contact_page(client, store):
    place = _place(store)
    c = store.add_contact("Sam")
    client.post(f"/contacts/{c['id']}/link", data={"place_id": str(place["id"])})
    assert [p["id"] for p in store.places_for_contact(c["id"])] == [place["id"]]
    client.post(f"/contacts/{c['id']}/unlink", data={"place_id": str(place["id"])})
    assert store.places_for_contact(c["id"]) == []
    assert client.post(f"/contacts/{c['id']}/link", data={"place_id": "999"}, follow_redirects=False).status_code == 303


# ---- from the place page
def test_place_page_contacts_flow(client, store):
    place = _place(store)
    pid = place["id"]
    assert 'id="contacts"' in client.get(f"/places/{pid}").text
    client.post(f"/places/{pid}/contacts", data={"name": "Leasing Office", "role": "leasing agent", "email": "l@example.com"})
    c = store.contacts_for_place(pid)[0]
    assert c["name"] == "Leasing Office"
    client.post(f"/places/{pid}/contacts/log", data={"contact_id": str(c["id"]), "kind": "email", "direction": "out", "body": "Tour?"})
    assert store.list_contact_log(place_id=pid)[0]["body"] == "Tour?"
    html = client.get(f"/places/{pid}").text
    assert "Leasing Office" in html and "Tour?" in html
    other = store.add_contact("Already Saved")
    client.post(f"/places/{pid}/contacts/link", data={"contact_id": str(other["id"])})
    assert {x["name"] for x in store.contacts_for_place(pid)} == {"Leasing Office", "Already Saved"}
    client.post(f"/places/{pid}/contacts/{c['id']}/unlink")
    assert [x["name"] for x in store.contacts_for_place(pid)] == ["Already Saved"]
    assert store.list_contacts()  # taking a contact off a place never deletes it


def test_place_contact_routes_reject_bad_input(client, store):
    place = _place(store)
    pid = place["id"]
    assert client.post(f"/places/{pid}/contacts", data={"name": ""}, follow_redirects=False).status_code == 303
    assert store.list_contacts() == []
    assert client.post(f"/places/{pid}/contacts/log", data={"kind": "email"}, follow_redirects=False).status_code == 303
    assert client.post("/places/999/contacts", data={"name": "X"}).status_code == 404
