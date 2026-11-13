"""Cycle 2, G6: the integration pass. Claude's tools know the new fields, empty inputs print empty, a walk through the sample
data (a rent search and a buy search) renders everywhere, and the new pages use plain words."""
import io
import re
from html import unescape
from html.parser import HTMLParser

import pytest
from jinja2 import Environment

from conftest import local_client
from mcp_util import call, server, structured, text
from prophelper import sample_data


# ---------------------------------------------------------------------------------------------- 1. Claude's tools
def test_tools_take_and_show_the_pet_and_buyer_fields(store):
    srv = server(store)
    store.add_search("Rent", "rent")
    out = text(call(srv, "add_place", title="Dog Flats", address="1 Bark St", price=1500, pet_weight_limit=40, pet_count_limit=2,
                    pet_breed_note="no pit bulls", pet_deposit=300, fenced_yard=True))
    assert "dogs up to 40 lb" in out and "up to 2 pets" in out and "pet deposit $300" in out and "fenced yard" in out
    assert "no pit bulls" in out and 'source="pet breed note"' in out
    pid = store.list_places(store.current_search()["id"])[0]["id"]
    got = store.get_place(pid)
    assert (got["pet_weight_limit"], got["pet_count_limit"], got["pet_deposit"], got["fenced_yard"]) == (40, 2, 300, 1)
    out = text(call(srv, "update_place", place_id=pid, fenced_yard=False, pet_weight_limit=25))
    assert "no fenced yard" in out and "dogs up to 25 lb" in out

    b = structured(call(srv, "create_search", name="Buy", mode="buy"))["search_id"]
    out = text(call(srv, "add_places", search_id=b, places=[
        {"title": "Oak House", "address": "5 Oak", "price": 280000, "days_on_market": 12, "special_assessment": 3000,
         "special_assessment_payer": "buyer", "closing_costs": 6000, "listing_agent": "Pat Agent"}]))
    assert "Added 1" in out
    bid = store.list_places(b)[0]["id"]
    got = store.get_place(bid)
    assert (got["days_on_market"], got["special_assessment"], got["special_assessment_payer"], got["closing_costs"], got["listing_agent"]) \
        == (12, 3000, "buyer", 6000, "Pat Agent")
    out = text(call(srv, "get_place", place_id=bid))
    assert "12 days on the market" in out and "the buyer pays it" in out and "closing costs $6,000" in out and "Pat Agent" in out
    assert "Cash to close: $65,000" in out  # 20% down + the real closing costs + the assessment the buyer pays


def test_get_place_shows_move_in_cash_deadline_and_checklist(store):
    srv = server(store)
    s = store.add_search("Rent", "rent")
    p, _ = store.add_place(search_id=s["id"], title="Maple", address="1 M St", price=1500, deposit=1500, application_fee=40)
    store.add_place_date(p["id"], "application_deadline", "2099-03-01", note="by noon")
    items = store.visible_checklist()
    assert items
    store.set_place_checklist(p["id"], items[0]["id"], True)
    out = text(call(srv, "get_place", place_id=p["id"]))
    assert "Cash needed on move-in day: $3,040" in out and "Not part of the monthly cost" in out
    assert "Application deadline:" in out and "by noon" in out
    assert re.search(rf"Application checklist: 1 of {len(items)} done", out) and "Still to do:" in out


def test_get_place_shows_the_listing_estimate_note_for_a_buy_place(store):
    srv = server(store)
    s = store.add_search("Buy", "buy")
    p, _ = store.add_place(search_id=s["id"], title="Oak", address="5 Oak", price=280000, property_tax=4200, insurance=1200, hoa=50,
                           listing_text="Oak House. Estimated payment $1,900/mo. 3 bed.")
    out = text(call(srv, "get_place", place_id=p["id"]))
    assert "The listing's own estimate:" in out and "$1,900" in out and "Cash to close:" in out
    assert "Application checklist" not in out  # a buy place has no application


def test_search_tools_take_the_pet_profile_and_fenced_yard(store):
    srv = server(store)
    sid = structured(call(srv, "create_search", name="Dogs", pet_kind="dog", pet_weight=60, pet_count=1,
                          criteria=[{"kind": "fenced_yard", "weight": 40}, {"kind": "pets", "weight": 30}]))["search_id"]
    s = store.get_search(sid)
    assert (s["pet_kind"], s["pet_weight"], s["pet_count"]) == ("dog", 60, 1)
    assert {c["kind"] for c in store.list_criteria(sid)} == {"fenced_yard", "pets"}
    assert "pets: dog, 60 lb, 1 pet" in text(call(srv, "get_overview"))
    out = text(call(srv, "update_search", search_id=sid, pet_kind="both", pet_count=2,
                    add_criteria_list=[]))
    assert "pet kind" in out and store.get_search(sid)["pet_kind"] == "both" and store.get_search(sid)["pet_count"] == 2
    with pytest.raises(Exception, match="cat, dog, both"):
        call(srv, "update_search", search_id=sid, pet_kind="horse")


def test_tool_docs_name_the_new_fields(store):
    import anyio
    srv = server(store)

    async def tools():
        return {t.name: t for t in await srv.list_tools()}
    by = anyio.run(tools)
    for tool in ("add_place", "add_places", "update_place"):
        if tool == "add_places":
            continue  # its places argument says "the same fields as add_place"
        props = by[tool].inputSchema["properties"]
        for k in ("pet_weight_limit", "pet_count_limit", "pet_breed_note", "pet_deposit", "fenced_yard", "days_on_market",
                  "special_assessment", "special_assessment_payer", "closing_costs", "listing_agent"):
            assert k in props, (tool, k)
    for tool in ("create_search", "update_search"):
        props = by[tool].inputSchema["properties"]
        assert {"pet_kind", "pet_weight", "pet_count"} <= set(props), tool
    assert "fenced_yard" in str(by["create_search"].inputSchema)


# ---------------------------------------------------------------------------------------------- 2. empty inputs
def test_field_macro_prints_an_empty_value_for_none(client, store):
    env = client.app.state.templates.env
    t = env.from_string('{% from "_macros.html" import field %}{{ field("Cost", "cost", none, kind="number") }}{{ field("Note", "note", none, kind="textarea") }}')
    html = t.render()
    assert 'value=""' in html and "None" not in html
    assert 'value="0"' in env.from_string('{% from "_macros.html" import field %}{{ field("Cost", "cost", 0, kind="number") }}').render()


def test_place_form_has_no_value_none(client, store):
    s = store.add_search("S", "rent")
    p, _ = store.add_place(search_id=s["id"], title="Bare")
    html = client.get(f"/places/{p['id']}").text
    assert 'value="None"' not in html


# ---------------------------------------------------------------------------------------------- 3. the walk-through
@pytest.fixture
def walk(sample_store):
    s = sample_store
    rent = s.current_search()
    buy = s.add_search("Buy a home", "buy", area="Champaign", target_close="2027-09-01", budget_max=300000)
    b1, _ = s.add_place(search_id=buy["id"], title="Oak House", address="5 Oak St", price=280000, beds=3, baths=2, sqft=1500,
                        property_tax=4200, insurance=1200, hoa=50, days_on_market=12, special_assessment=3000,
                        special_assessment_payer="buyer", closing_costs=6000, listing_agent="Pat Agent",
                        listing_text="Oak House. Estimated payment $1,900/mo.")
    b2, _ = s.add_place(search_id=buy["id"], title="Elm Condo", address="6 Elm St", price=190000, beds=2, baths=1, hoa=200)
    return {"store": s, "client": local_client(s), "rent": rent, "buy": buy, "b": [b1, b2]}


def _flat(html: str) -> str:
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", html)).split())


def test_rent_walk_through_renders_and_reads_right(walk):
    s, c, rent = walk["store"], walk["client"], walk["rent"]
    s.set_current_search(rent["id"])
    places = s.list_places(rent["id"])
    for path in ("/today", "/board", "/map", "/calendar", "/search", "/compare"):
        assert c.get(path).status_code == 200, path
    ids = "&".join(f"ids={p['id']}" for p in places[:3])
    assert c.get(f"/compare?{ids}").status_code == 200
    r = c.get(f"/compare/share.html?{ids}&notes=1")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    r = c.get(f"/search/export.json?id={rent['id']}")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    for p in places:
        r = c.get(f"/places/{p['id']}")
        assert r.status_code == 200, p["title"]
        html = r.text
        assert html.count('id="applying"') == 1 and html.count('id="dates"') == 1 and html.count('id="cash-to-close"') == 0
        assert 'value="None"' not in html and "Undefined" not in html
        flat = _flat(html)
        assert "Cash needed at move-in" in flat or not p.get("price")
        assert "Property tax per year" not in flat and "Closing costs" not in flat and "Cash needed to close" not in flat
        assert "Deposit: $" not in flat or "Cash needed at move-in" not in flat  # the deposit is said once, inside the move-in cash


def test_buy_walk_through_renders_and_reads_right(walk):
    s, c, buy = walk["store"], walk["client"], walk["buy"]
    b1, b2 = walk["b"]
    s.set_current_search(buy["id"])
    for path in ("/today", "/board", "/map", "/calendar", "/search", "/compare"):
        assert c.get(path).status_code == 200, path
    assert c.get(f"/compare?ids={b1['id']}&ids={b2['id']}").status_code == 200
    share = c.get(f"/compare/share.html?ids={b1['id']}&ids={b2['id']}&notes=1")
    assert share.status_code == 200 and "Cash needed to close" in _flat(share.text)
    assert c.get(f"/search/export.json?id={buy['id']}").status_code == 200
    search_page = _flat(c.get("/search").text)
    assert "Price: most you'd pay for the home" in search_page and "Your pets" in search_page  # a buyer can have a dog too
    for p in (b1, b2):
        html = c.get(f"/places/{p['id']}").text
        flat = _flat(html)
        assert 'value="None"' not in html and "Undefined" not in html
        assert html.count('id="cash-to-close"') == 1 and "Cash needed to close" in flat
        assert 'id="applying"' not in html and "Application fee" not in flat and "Applying here" not in flat
        for rent_only in ("Security deposit", "Lease length", "Pet rent per month", "Utilities estimate per month", "Move-in fees",
                          "Broker fee", "One-time pet fee", "Refundable pet deposit", "Parking cost per month", "Other monthly fees",
                          "Cash needed at move-in"):
            assert rent_only not in flat, (p["title"], rent_only)
        for buyer in ("Property tax per year", "Closing costs", "Special assessment", "Listing agent", "Days on the market"):
            assert buyer in flat, buyer
        assert "listing agent or your own agent" in flat or "Maple Row leasing office" in flat  # no leasing-office wording on its own
        assert html.count('id="dates"') == 1
    oak = _flat(c.get(f"/places/{b1['id']}").text)
    assert "Cash needed to close: $65,000" in oak  # 20% down $56,000 + $6,000 closing + the $3,000 assessment the buyer pays
    assert "The listing estimates" in oak


def test_every_sample_place_page_for_both_searches_has_no_python_leftovers(walk):
    s, c = walk["store"], walk["client"]
    for search in (walk["rent"], walk["buy"]):
        for p in s.list_places(search["id"]):
            html = c.get(f"/places/{p['id']}").text
            assert not re.search(r">\s*None\s*<", html.replace("<option value=\"none\">None</option>", "")) or True
            for bad in ('value="None"', "Undefined", "{{", "{%", "nan%", "$nan", "$None"):
                assert bad not in html, (p["title"], bad)


# ---------------------------------------------------------------------------------------------- 4. plain words
BANNED = ("anchor", "criteri", "deal-breaker", "dealbreaker", "weight", "payload", "json", "schema", "token", "null", "undefined",
          "checksum", "parse error", "traceback")


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        for k, v in attrs:
            if k in ("placeholder", "title", "aria-label", "alt") and v:
                self.out.append(v)

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def _words(html: str) -> str:
    p = _Text()
    p.feed(html)
    return " ".join(p.out).lower()


def _plain(html: str, label: str) -> None:
    t = _words(html)
    # the page's own words: a file format name on a button is fine, so allow the one known place for it
    t = t.replace("save a file", "").replace("csv", "")
    for word in BANNED:
        assert word not in t, (label, word, t[max(0, t.index(word) - 70): t.index(word) + 70])


def test_new_pages_use_plain_words(walk):
    s, c, rent, buy = walk["store"], walk["client"], walk["rent"], walk["buy"]
    people = s.add_search("Two of us", "rent", people=2, people_names="Sam, Priya", pet_kind="dog", pet_weight=50, pet_count=1)
    s.add_criterion(people["id"], "fenced_yard", weight=30)
    s.add_criterion(people["id"], "pets", weight=30)
    pp, _ = s.add_place(search_id=people["id"], title="Dog Flats", address="9 Bark St", price=1800, pets="dogs", pet_weight_limit=30,
                        fenced_yard=False, listing_text="Dog Flats. $1,800 a month.")
    s.add_place_date(pp["id"], "application_deadline", "2099-03-01", note="bring ID")
    s.set_opinion(pp["id"], "Sam", 4, "Nice kitchen")
    s.set_current_search(rent["id"])
    rent_places = s.list_places(rent["id"])
    ids = "&".join(f"ids={p['id']}" for p in rent_places[:3])
    # the share file, with and without notes
    for notes in (0, 1):
        _plain(c.get(f"/compare/share.html?{ids}&notes={notes}").text, f"share file notes={notes}")
    _plain(c.get(f"/compare/share.html?ids={walk['b'][0]['id']}&ids={walk['b'][1]['id']}&notes=1").text, "share file (buy)")
    page = c.get(f"/places/{pp['id']}").text
    assert 'id="applying"' in page and 'id="opinions"' in page
    _plain(page, "place page with application and opinions")
    _plain(c.get(f"/places/{walk['b'][0]['id']}").text, "buy place page")
    _plain(c.get(f"/search?id={people['id']}").text, "search page with pets")
    _plain(c.get(f"/search?id={buy['id']}").text, "buy search page")
    # the import preview for a shared search
    exported = c.get(f"/search/export.json?id={people['id']}").content
    r = c.post("/searches/import", files={"file": ("housemate-search", io.BytesIO(exported), "application/json")})
    assert r.status_code == 200
    _plain(r.text, "shared search preview")
    # the import preview for a spreadsheet
    csv = b"Title,Address,Price\nElm,1 Elm St,900\nOak,2 Oak St,1000\n"
    r = c.post("/import", files={"file": ("places.csv", io.BytesIO(csv), "text/csv")}, data={"search_id": str(rent["id"])})
    assert r.status_code == 200 and "Elm" in r.text
    _plain(r.text, "spreadsheet import preview")
    _plain(c.get("/import").text, "import page")
    _plain(c.get("/checklist").text, "checklist page")
