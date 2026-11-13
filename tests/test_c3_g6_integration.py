"""Cycle 3, G6: the integration pass. Claude's tools know months up front and what the tenant pays, the spreadsheet carries them,
Compare and the share page show them, the board's final steps are confirmed, and a walk through both modes renders cleanly."""
import io
import re
from html import unescape
from html.parser import HTMLParser

import anyio
import pytest

from conftest import local_client
from mcp_util import call, server, structured, text
from prophelper import csv_io, parsers


def _flat(html: str) -> str:
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S)
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", html)).split())


# ---------------------------------------------------------------------------------------------- 1. Claude's tools
def test_tools_take_and_show_months_up_front_and_tenant_pays(store):
    srv = server(store)
    store.add_search("Rent", "rent")
    out = text(call(srv, "add_place", title="First Last", address="1 Fl St", price=1000, months_up_front=2, tenant_pays="gas and electricity"))
    assert "rent due before move-in: 2 months" in out and "you pay these utilities: electric, gas" in out
    pid = store.list_places(store.current_search()["id"])[0]["id"]
    got = store.get_place(pid)
    assert got["months_up_front"] == 2 and got["tenant_pays"] == "electric, gas"
    out = text(call(srv, "get_place", place_id=pid))
    assert "rent due before move-in: 2 months" in out and "electric, gas" in out
    assert "Cash needed on move-in day: $2,000" in out
    out = text(call(srv, "update_place", place_id=pid, months_up_front=1, tenant_pays="water"))
    assert "rent due before move-in" not in out and "you pay these utilities: water" in out
    out = text(call(srv, "add_places", places=[{"title": "Two", "address": "2 Two St", "price": 900, "months_up_front": 3, "tenant_pays": "trash"}]))
    assert "Added 1" in out
    two = [p for p in store.list_places(store.current_search()["id"]) if p["title"] == "Two"][0]
    assert two["months_up_front"] == 3 and two["tenant_pays"] == "trash"
    with pytest.raises(Exception, match="0 to 12"):
        call(srv, "update_place", place_id=pid, months_up_front=13)


def test_buy_cards_do_not_show_renting_details(store):
    srv = server(store)
    b = structured(call(srv, "create_search", name="Buy", mode="buy"))["search_id"]
    call(srv, "add_place", search_id=b, title="Oak", address="5 Oak", price=250000)
    out = text(call(srv, "get_place", place_id=store.list_places(b)[0]["id"]))
    assert "Renting details" not in out and "before move-in" not in out


def test_tool_docs_and_instructions_name_the_new_fields(store):
    from prophelper import mcp_server
    srv = server(store)

    async def tools():
        return {t.name: t for t in await srv.list_tools()}
    by = anyio.run(tools)
    for tool in ("add_place", "update_place"):
        props = by[tool].inputSchema["properties"]
        assert "months_up_front" in props and "tenant_pays" in props, tool
        assert "Heaviest pet allowed" in props["pet_weight_limit"]["description"]
    assert "months_up_front" in mcp_server.INSTRUCTIONS and "tenant_pays" in mcp_server.INSTRUCTIONS
    assert "Heaviest dog" not in open(mcp_server.__file__, encoding="utf-8").read()
    from pathlib import Path
    for name in ("claude", "codex"):
        body = (Path(__file__).resolve().parent.parent / "skills" / name / "property-helper" / "SKILL.md").read_text(encoding="utf-8")
        assert "months_up_front" in body and "tenant_pays" in body


# ---------------------------------------------------------------------------------------------- 2. the spreadsheet
def test_csv_has_the_new_columns_and_pet_headings_agree_with_the_reader(store):
    assert csv_io.match_columns(["Pet deposit"]) == {0: "pet_deposit"}  # money that comes back, like the listing reader says
    assert csv_io.match_columns(["Pet fee"]) == {0: "pet_fee"}
    assert csv_io.match_columns(["Pet deposit (refundable)"]) == {0: "pet_deposit"}
    s = store.add_search("Rent", "rent")
    p, _ = store.add_place(search_id=s["id"], by="you", title="A", address="1 A St", price=1000, months_up_front=2, tenant_pays="gas, water")
    headings = [h for h, _ in csv_io.EXPORT_COLUMNS]
    assert "Months of rent due before move-in" in headings and "Utilities you pay" in headings
    data = local_client(store).get(f"/places.csv?search_id={s['id']}").content
    text_ = data.decode("utf-8-sig") if isinstance(data, bytes) else data
    assert "Months of rent due before move-in" in text_ and "Utilities you pay" in text_
    copy = store.add_search("Copy", "rent")
    headers, rows = csv_io.read_table(text_.encode("utf-8"))
    plan = csv_io.plan_import(store, copy["id"], headers, rows, csv_io.match_columns(headers))
    assert plan[0]["values"]["months_up_front"] == 2 and plan[0]["values"]["tenant_pays"] == "gas, water"


# ---------------------------------------------------------------------------------------------- 3. Compare and the share page
@pytest.fixture
def two_rent(store):
    s = store.add_search("Rent", "rent", budget_max=1500)
    a, _ = store.add_place(search_id=s["id"], title="First Last", address="1 A St", price=1000, months_up_front=2, tenant_pays="gas, electric")
    b, _ = store.add_place(search_id=s["id"], title="Plain", address="2 B St", price=1100, utilities_included="all utilities", other_monthly_fees=25)
    return s, a, b


def test_compare_and_share_show_months_and_name_the_utilities(store, two_rent):
    s, a, b = two_rent
    c = local_client(store)
    for path in (f"/compare?ids={a['id']}&ids={b['id']}", f"/compare/share.html?ids={a['id']}&ids={b['id']}&notes=0"):
        flat = _flat(c.get(path).text)
        assert "Months of rent due before move-in" in flat, path
        assert "utilities (electric and gas)" in flat or "utilities (gas and electric)" in flat or "utilities (electric, gas)" in flat, flat[:0] or path
        assert re.search(r"Other monthly fees\s+Not known\s+\$25", flat), path
        assert not re.search(r"Other monthly fees\s+\$0", flat), path


def test_compare_leaves_the_months_row_out_when_nobody_has_more_than_one(store):
    s = store.add_search("Rent", "rent")
    a, _ = store.add_place(search_id=s["id"], title="A", address="1 A", price=900)
    b, _ = store.add_place(search_id=s["id"], title="B", address="2 B", price=950, months_up_front=1)
    flat = _flat(local_client(store).get(f"/compare?ids={a['id']}&ids={b['id']}").text)
    assert "Months of rent due before move-in" not in flat


def test_place_page_cost_lines_say_not_known_for_unset_fees(store, two_rent):
    s, a, b = two_rent
    flat = _flat(local_client(store).get(f"/places/{a['id']}").text)
    assert re.search(r"Other monthly fees\s+Not known", flat)
    assert "You pay electric and gas; not counted yet" in flat or "not counted yet" in flat


# ---------------------------------------------------------------------------------------------- 4. the board and final steps
def test_board_moves_into_final_steps_go_through_the_confirm_page(store):
    s = store.add_search("Rent", "rent")
    p, _ = store.add_place(search_id=s["id"], title="Maple", address="1 M St", price=1000)
    c = local_client(store)
    hx = {"HX-Request": "true"}
    for stage in ("Lease signed", "Passed"):
        r = c.post(f"/places/{p['id']}/stage", data={"stage": stage}, headers=hx)
        assert r.status_code == 409 and r.json()["ok"] is False and "/stage-confirm?stage=" in r.json()["confirm_url"]
        assert store.get_place(p["id"])["stage"] == "Saved"
    page = c.get(r.json()["confirm_url"])
    assert page.status_code == 200 and "Move Maple to Passed?" in _flat(page.text) and 'name="confirm" value="yes"' in page.text
    assert store.get_place(p["id"])["stage"] == "Saved"
    # a normal move still works, with no confirm
    r = c.post(f"/places/{p['id']}/stage", data={"stage": "Contacted"}, headers=hx)
    assert r.status_code == 200 and r.json()["stage"] == "Contacted"
    # the confirm page's own button does the move
    r = c.post(f"/places/{p['id']}/stage", data={"stage": "Passed", "confirm": "yes"}, follow_redirects=False)
    assert r.status_code in (302, 303) and store.get_place(p["id"])["stage"] == "Passed"
    # a place page with a made-up stage or a non-final stage goes back to the place instead of a confirm page
    r = c.get(f"/places/{p['id']}/stage-confirm?stage=Toured", follow_redirects=False)
    assert r.status_code in (302, 303)


def test_board_script_follows_the_confirm_link():
    from pathlib import Path
    js = (Path(__file__).resolve().parent.parent / "src" / "prophelper" / "static" / "app.js").read_text(encoding="utf-8")
    assert "confirm_url" in js and "confirmUrl" in js


# ---------------------------------------------------------------------------------------------- 5. the walk-through
@pytest.fixture
def world(sample_store):
    s = sample_store
    rent = s.current_search()
    buy = s.add_search("Buy a home", "buy", area="Champaign", target_close="2027-09-01", budget_max=300000)
    s.add_place(search_id=buy["id"], title="Oak House", address="5 Oak St", price=280000, beds=3, baths=2, sqft=1500, property_tax=4200,
                insurance=1200, hoa=50, days_on_market=12, closing_costs=6000, listing_text="Oak House. Estimated payment $1,900/mo.")
    s.add_place(search_id=buy["id"], title="Elm Condo", address="6 Elm St", price=190000, beds=2, baths=1, hoa=200)
    nopets = s.add_search("No pets", "rent", budget_max=1200)
    cat = s.add_search("Cat", "rent", pet_kind="cat", pet_count=1, budget_max=1200)
    for sr in (nopets, cat):
        s.add_place(search_id=sr["id"], title="First and last " + sr["name"], address="1 A St", price=1000, tenant_pays="gas, electric",
                    months_up_front=2, pet_rent=30, pet_fee=200, listing_text="First and last month's rent due. Cats ok.")
        s.add_place(search_id=sr["id"], title="Bare " + sr["name"], address="2 A St", price=1100)
    return {"store": s, "client": local_client(s), "searches": {"sample": rent, "buy": buy, "nopets": nopets, "cat": cat}}


LEFTOVERS = ('value="None"', "Undefined", "{{", "{%", "nan%", "$nan", "$None", "None%")
RENTER_WORDS = re.compile(r"(?i)\b(landlord|tenant|renter|rent|lease|leasing|move-in)\b")


def _pages(s, search):
    places = s.list_places(search["id"])
    ids = "&".join(f"ids={p['id']}" for p in places[:3])
    return ["/today", "/board", "/map", "/calendar", "/search", f"/search?id={search['id']}", "/compare", f"/compare?{ids}",
            f"/compare/share.html?{ids}&notes=1", f"/compare/share.html?{ids}&notes=0",
            f"/search/export.json?id={search['id']}"] + [f"/places/{p['id']}" for p in places]


@pytest.mark.parametrize("key", ["sample", "buy", "nopets", "cat"])
def test_every_page_renders_with_no_leftovers(world, key):
    s, c = world["store"], world["client"]
    search = world["searches"][key]
    s.set_current_search(search["id"])
    for path in _pages(s, search):
        r = c.get(path)
        assert r.status_code == 200, (key, path)
        if "export.json" in path:
            continue
        body = r.text
        for bad in LEFTOVERS:
            assert bad not in body, (key, path, bad)
        flat = _flat(body)
        assert not re.search(r"Other monthly fees\s+\$0", flat), (key, path)  # fees nobody filled in never read as $0


def test_buy_pages_use_buyer_words(world):
    s, c = world["store"], world["client"]
    buy = world["searches"]["buy"]
    s.set_current_search(buy["id"])
    for path in ("/calendar", "/search", f"/search?id={buy['id']}"):
        flat = _flat(c.get(path).text)
        assert not RENTER_WORDS.search(flat.replace("Renting or buying?", "")), (path, RENTER_WORDS.search(flat.replace("Renting or buying?", "")).group(0))
    flat = _flat(c.get("/calendar").text)
    assert "Lease starts" not in flat and "Available" not in flat and "target close date" in flat.lower()
    flat = _flat(c.get(f"/search?id={buy['id']}").text)
    assert flat.count("Move in by") == 1 and flat.count("Target close date") == 2  # once each in the new-search form, then the target date only for this search and "Payment split between this many people" in flat


def test_no_pets_search_leaves_pet_costs_out_and_says_so(world):
    s, c = world["store"], world["client"]
    sr = world["searches"]["nopets"]
    s.set_current_search(sr["id"])
    p = [x for x in s.list_places(sr["id"]) if x["title"].startswith("First")][0]
    flat = _flat(c.get(f"/places/{p['id']}").text)
    assert "you have no pets" in flat and "Cash needed at move-in: $2,000" in flat
    assert "Rent due up front (2 months)" in flat
    assert "pet fee" not in flat.split("Cash needed at move-in")[1].split("This is not part")[0].lower()


def test_cat_search_counts_pet_rent_and_fee(world):
    s, c = world["store"], world["client"]
    sr = world["searches"]["cat"]
    s.set_current_search(sr["id"])
    p = [x for x in s.list_places(sr["id"]) if x["title"].startswith("First")][0]
    flat = _flat(c.get(f"/places/{p['id']}").text)
    assert "Pet rent $30.00" in flat and "Pet fee $200" in flat and "Cash needed at move-in: $2,200" in flat


def test_map_with_tiles_off_and_on(world):
    s, c = world["store"], world["client"]
    s.set_current_search(world["searches"]["sample"]["id"])
    s.set_setting("map_tiles", "0")
    flat = _flat(c.get("/map").text)
    assert "Show street map" in flat
    s.set_setting("map_tiles", "1")
    r = c.get("/map")
    assert r.status_code == 200 and "Show street map" not in _flat(r.text)
    assert c.post("/map/tiles", follow_redirects=False).status_code in (302, 303)


def test_add_parse_preview_lists_things_to_check_and_months(world):
    c = world["client"]
    text_ = ("Sunny 1BR at 12 Pine St, Urbana IL 61801. $1,050 per month. First and last month's rent due at signing. "
             "Tenant pays gas and electric. Wire the deposit by Western Union to hold the unit, no showings.")
    r = c.post("/add/parse", data={"text": text_, "search_id": str(world["searches"]["nopets"]["id"])})
    assert r.status_code == 200
    flat = _flat(r.text)
    assert "Things to check" in flat and "Months of rent due before move-in" in flat and "Utilities you pay" in flat
    assert 'value="None"' not in r.text
    r = c.post("/add/parse", data={"text": "Oak House, 5 Oak St. $280,000. 3 bed 2 bath.", "search_id": str(world["searches"]["buy"]["id"])})
    assert r.status_code == 200 and "Months of rent due before move-in" not in _flat(r.text)


def test_import_previews_render(world):
    c = world["client"]
    sr = world["searches"]["nopets"]
    csv = (b"Title,Address,Price,Pet deposit,Pet fee,Months of rent due before move-in,Utilities you pay\n"
           b"Elm,1 Elm St,900,300,50,2,\"gas, water\"\n,,,,,,\nBad,3 Bad St,Call for pricing,,,,\n")
    r = c.post("/import", files={"file": ("places.csv", io.BytesIO(csv), "text/csv")}, data={"search_id": str(sr["id"])})
    assert r.status_code == 200 and "Elm" in r.text
    flat = _flat(r.text)
    assert "left out" in flat and "Months of rent due before move-in" in flat and "Utilities you pay" in flat
    assert 'value="None"' not in r.text
    exported = c.get(f"/search/export.json?id={sr['id']}").content
    r = c.post("/searches/import", files={"file": ("housemate-search", io.BytesIO(exported), "application/json")})
    assert r.status_code == 200 and 'value="None"' not in r.text


# ---------------------------------------------------------------------------------------------- 6. plain words
BANNED = ("anchor", "criteri", "deal-breaker", "dealbreaker", "weight", "payload", "json", "schema", "token", "null", "undefined",
          "checksum", "parse error", "traceback", "htmx", "csrf", "endpoint")


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
    t = _words(html).replace("save a file", "").replace("csv", "")
    for word in BANNED:
        assert word not in t, (label, word, t[max(0, t.index(word) - 70): t.index(word) + 70])
    assert "\u2014" not in t, label  # no em-dashes


def test_new_pages_and_sections_use_plain_words(world):
    s, c = world["store"], world["client"]
    sr = world["searches"]
    # the stage confirm page
    p = s.list_places(sr["nopets"]["id"])[0]
    for stage in ("Lease signed", "Passed"):
        _plain(c.get(f"/places/{p['id']}/stage-confirm?stage={stage}").text, f"stage confirm {stage}")
        _plain(c.post(f"/places/{p['id']}/stage", data={"stage": stage}).text, f"stage confirm post {stage}")
    b = s.list_places(sr["buy"]["id"])[0]
    _plain(c.get(f"/places/{b['id']}/stage-confirm?stage=Closed").text, "stage confirm Closed")
    # a near miss card on Today: $1,000 rent + $150 fees against a $1,100 budget
    near = s.add_search("Near", "rent", budget_max=1000)
    s.add_criterion(near["id"], "price", weight=50, dealbreaker=True, target={"max": 1000})
    s.add_place(search_id=near["id"], title="Almost", address="9 N St", price=980, other_monthly_fees=30, utilities_estimate=0, parking="none")
    s.set_current_search(near["id"])
    today = c.get("/today").text
    _plain(today, "today with near miss")
    # the map: tiles button, then tiles on
    s.set_current_search(sr["sample"]["id"])
    s.set_setting("map_tiles", "0")
    _plain(c.get("/map").text, "map, tiles off")
    s.set_setting("map_tiles", "1")
    _plain(c.get("/map").text, "map, tiles on")
    # compare and share with the new row
    nop = s.list_places(sr["nopets"]["id"])
    ids = "&".join(f"ids={x['id']}" for x in nop)
    _plain(c.get(f"/compare?{ids}").text, "compare with months")
    _plain(c.get(f"/compare/share.html?{ids}&notes=1").text, "share with months")
    # the place page: applying here, facts with the new fields
    html = c.get(f"/places/{nop[0]['id']}").text
    assert 'id="applying"' in html
    _plain(html, "place page with applying here")
    # the add preview with things to check
    r = c.post("/add/parse", data={"text": "1BR, 12 Pine St. $1,050 a month. Wire the deposit by Western Union, no showings, act fast.",
                                   "search_id": str(sr["nopets"]["id"])})
    _plain(r.text, "add preview with things to check")
    # the spreadsheet preview with left-out lines, and the shared search preview with its left-out lines
    csv = b"Title,Address,Price,Pet deposit\nElm,1 Elm St,900,300\n,,,\nBad,3 Bad St,Call for pricing,\n"
    r = c.post("/import", files={"file": ("places.csv", io.BytesIO(csv), "text/csv")}, data={"search_id": str(sr["nopets"]["id"])})
    assert "left out" in _flat(r.text)
    _plain(r.text, "spreadsheet preview with left-out rows")
    exported = c.get(f"/search/export.json?id={sr['nopets']['id']}").content
    r = c.post("/searches/import", files={"file": ("shared", io.BytesIO(exported), "application/json")})
    _plain(r.text, "shared search preview")
    assert parsers  # (imported for the preview text above)
