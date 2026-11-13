"""Cycle 3, G4: web wording and the buy place page."""
import html as html_mod
import re
from html.parser import HTMLParser

from conftest import local_client


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def visible(html: str) -> str:
    p = _Text()
    p.feed(html)
    return " ".join(" ".join(p.out).split())


def options_of(html: str, select_id: str) -> list[str]:
    m = re.search(rf'<select id="{select_id}"[^>]*>(.*?)</select>', html, re.S)
    return [html_mod.unescape(x) for x in re.findall(r"<option[^>]*>(.*?)</option>", m.group(1), re.S)]


def _buy(store):
    s = store.add_search("Buy", "buy")
    p, _ = store.add_place(search_id=s["id"], title="House", address="1 Oak St", city="Urbana", state="IL", price=300000)
    return s, p


def _rent(store):
    s = store.add_search("Rent", "rent")
    p, _ = store.add_place(search_id=s["id"], title="Flat", address="2 Elm St", city="Urbana", state="IL", price=900)
    return s, p


# 1. buy place page is buyer only
def test_buy_place_roles_documents_and_pets(store):
    _s, p = _buy(store)
    html = local_client(store).get(f"/places/{p['id']}").text
    roles = options_of(html, "pn-role")
    assert roles[:6] == ["Buyer's agent", "Listing agent", "Lender", "Inspector", "Title or closing", "Seller"]
    assert "Landlord" not in roles and "Leasing agent" not in roles
    assert 'selected>Buyer&#39;s agent<' in html
    kinds = options_of(html, "doc-kind")
    assert kinds[:6] == ["Offer", "Purchase contract", "Inspection report", "Appraisal", "Disclosures", "Loan estimate"]
    assert "Lease" not in kinds
    assert "Pets allowed by the HOA or building" in visible(html)


def test_buy_contact_and_document_kinds_are_accepted(store):
    _s, p = _buy(store)
    c = local_client(store)
    r = c.post(f"/places/{p['id']}/contacts", data={"name": "Lee", "role": "lender"}, follow_redirects=True)
    assert "Added Lee" in r.text
    assert store.contacts_for_place(p["id"])[0]["role"] == "lender"
    r = c.post(f"/places/{p['id']}/documents", data={"kind": "loan estimate"}, files={"file": ("le.pdf", b"x")}, follow_redirects=True)
    assert "Added le.pdf" in r.text


def test_rent_place_defaults_unchanged(store):
    _s, p = _rent(store)
    html = local_client(store).get(f"/places/{p['id']}").text
    assert options_of(html, "pn-role")[0] == "Landlord"
    assert '<option value="leasing agent" selected>' in html
    assert options_of(html, "doc-kind")[0] == "Lease"
    assert "Heaviest pet allowed (lb)" in visible(html)
    assert "Heaviest dog" not in visible(html)


# 2. search form wording and links
def test_search_form_labels_and_links(store):
    s, _p = _buy(store)
    html = local_client(store).get(f"/search?id={s['id']}").text
    text = visible(html)
    assert "most you'd pay for the home" in text.lower()
    assert "People splitting the cost (leave at 1 for a family or couple sharing one budget)" in text
    assert 'href="/compare"' in html and f'href="/search/export.json?id={s["id"]}"' in html
    assert "What each person thinks" in text


def test_search_links_are_not_404(store):
    s, _p = _buy(store)
    c = local_client(store)
    assert c.get("/compare").status_code == 200
    assert c.get(f"/search/export.json?id={s['id']}").status_code == 200


# 3. criteria
def test_criteria_dropdown_plain_and_error_plain(store):
    s, _p = _rent(store)
    c = local_client(store)
    html = c.get(f"/search?id={s['id']}").text
    labels = options_of(html, "nc-kind")
    assert labels[:5] == ["Monthly cost", "Bedrooms", "Bathrooms", "Size", "Commute"]
    assert "Fenced yard" in labels and any(x.startswith("Your own rule") for x in labels)
    assert not any("_" in x for x in labels)
    r = c.post(f"/search/{s['id']}/criteria", data={"kind": "fenced-yard", "weight": "5"}, follow_redirects=True)
    text = visible(r.text)
    assert "Pick what kind of thing matters" in text and "Monthly cost" in text and "fenced_yard" not in text
    # stored kind values are unchanged
    c.post(f"/search/{s['id']}/criteria", data={"kind": "fenced_yard", "weight": "5"})
    assert store.list_criteria(s["id"])[-1]["kind"] == "fenced_yard"


# 4. final steps need confirming
def test_final_stage_group_and_confirmation(store):
    _s, p = _rent(store)
    c = local_client(store)
    html = c.get(f"/places/{p['id']}").text
    assert '<optgroup label="Final steps">' in html
    group = html.split('<optgroup label="Final steps">')[1].split("</optgroup>")[0]
    assert "Lease signed" in group and "Passed" in group
    r = c.post(f"/places/{p['id']}/stage", data={"stage": "Lease signed"})
    assert r.status_code == 200 and "Yes, move it to Lease signed" in r.text
    assert store.get_place(p["id"])["stage"] == "Saved"
    r = c.post(f"/places/{p['id']}/stage", data={"stage": "Lease signed", "confirm": "yes"}, follow_redirects=False)
    assert r.status_code == 303 and store.get_place(p["id"])["stage"] == "Lease signed"
    # an ordinary stage needs no confirmation
    _s2, p2 = _rent(store)
    r = c.post(f"/places/{p2['id']}/stage", data={"stage": "Contacted"}, follow_redirects=False)
    assert r.status_code == 303 and store.get_place(p2["id"])["stage"] == "Contacted"


# 5. pet records only with pets
def test_pet_records_only_when_search_has_pets(store):
    s, p = _rent(store)
    c = local_client(store)
    assert "Pet records" not in visible(c.get("/checklist").text)
    assert "Pet records" not in visible(c.get(f"/places/{p['id']}").text)
    store.update_search(s["id"], pet_kind="dog")
    assert "Pet records" in visible(c.get("/checklist").text)
    assert "Pet records" in visible(c.get(f"/places/{p['id']}").text)


# 6. the two counts are explained and the Claude count says which list it is
def test_checklist_explains_and_links_places(store):
    s, p = _rent(store)
    html = local_client(store).get("/checklist").text
    assert "your own documents list" in visible(html).lower()
    assert f'href="/places/{p["id"]}#applying"' in html


def test_todays_list_names_the_list(store):
    from prophelper.mcp_server import build_server
    import asyncio

    _rent(store)
    server = build_server(store)
    res = asyncio.run(server.call_tool("todays_list", {}))
    text = str(res)
    assert "Your own documents list" in text and "Applying here" in text


# 7. key dates and calendar
def test_bad_key_date_kind_shows_an_error(store):
    _s, p = _rent(store)
    c = local_client(store)
    r = c.post(f"/places/{p['id']}/dates", data={"kind": "bogus", "day": "2027-01-05"}, follow_redirects=True)
    assert "Pick one of" in visible(r.text)
    assert store.list_place_dates(p["id"]) == []


def test_calendar_shows_close_tour_note(store):
    from datetime import datetime, timedelta, timezone

    s, p = _rent(store)
    p2, _ = store.add_place(search_id=s["id"], title="Flat 2", address="3 Elm St")
    day = (datetime.now(timezone.utc) + timedelta(days=3)).replace(hour=15, minute=0, second=0, microsecond=0)
    store.add_tour(p["id"], day.isoformat())
    store.add_tour(p2["id"], (day + timedelta(minutes=15)).isoformat())
    month = day.astimezone().strftime("%Y-%m")
    html = local_client(store).get(f"/calendar?month={month}").text
    assert "15 minutes apart; check the drive" in visible(html)


# 8. no leading comma
def test_no_leading_comma_without_street(store):
    s = store.add_search("Rent", "rent")
    p, _ = store.add_place(search_id=s["id"], title="Somewhere", city="Urbana", state="IL", url="https://example.com/x")
    html = local_client(store).get(f"/places/{p['id']}").text
    sub = re.search(r'<p class="sub">(.*?)</p>', html, re.S).group(1)
    assert sub.strip().startswith("Urbana IL")


# 9. plain words
def test_connect_and_settings_plain_words(store):
    _rent(store)
    c = local_client(store)
    connect = visible(c.get("/connect").text)
    assert "add-on file (Claude calls it a plugin)" in connect
    assert "Get the Claude plugin" not in connect
    settings = visible(c.get("/settings").text)
    assert "Stricter rules when Claude reads websites for you" in settings
    assert "scraping guards" not in settings.lower()
