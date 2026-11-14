"""The small page edits: Add shows readable found and missing fields, Settings has Test key, Privacy lists what each call sends."""
from conftest import local_client
from prophelper import ai_key, geocode


def test_add_page_names_what_was_found_and_what_was_not(store):
    s = store.add_search("UIUC", "rent")
    store.set_current_search(s["id"])
    c = local_client(store)
    assert "/import" in c.get("/add").text
    r = c.post("/add/parse", data={"url": "", "text": "Sunny 2 bedroom, 1 bath apartment. $1,450 per month. Washer and dryer in unit."})
    assert "Filled in from what you pasted: " in r.text and "rent" in r.text and "bedrooms" in r.text
    assert "Not found in the text, so left empty:" in r.text and "address" in r.text
    assert "price," not in r.text.split("Filled in from what you pasted:")[1].split("</p>")[0]  # field keys are shown as words


def test_settings_has_test_key_only_with_a_key(store, monkeypatch):
    c = local_client(store)
    monkeypatch.setattr(ai_key, "key_status", lambda: {"set": False, "hint": "", "source": ""})
    assert "/ai/test-key" not in c.get("/settings").text
    monkeypatch.setattr(ai_key, "key_status", lambda: {"set": True, "hint": "sk-...abcd", "source": "file"})
    assert 'action="/ai/test-key"' in c.get("/settings").text


def test_privacy_lists_exactly_what_each_call_sends(store):
    html = local_client(store).get("/privacy").text
    assert geocode.USER_AGENT in html and "format=json" in html and "not its name, unit, notes" in html
    assert "claude-sonnet-5-5" in html and "listing text you pasted" in html and "only the word OK" in html
    assert "—" not in html
