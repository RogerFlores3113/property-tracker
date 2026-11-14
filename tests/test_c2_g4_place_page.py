"""G4: place page commutes (one row per important place), cost first, red-flag line always there."""
from conftest import local_client


def _setup(store, *, anchor=None, place=None, criteria=()):
    search = store.list_searches()[0] if store.list_searches() else store.add_search("Test")
    a = store.add_anchor("Office", **(anchor if anchor is not None else {"address": "1 Main St", "lat": 40.11, "lng": -88.23}))
    p, _ = store.add_place(search_id=search["id"], title="Elm", address="5 Elm St", price=1400, **(place or {"lat": 40.12, "lng": -88.24}))
    for kind, target in criteria:
        store.add_criterion(search["id"], kind, target=target)
    return search, a, p


def _page(store, p):
    return local_client(store).get(f"/places/{p['id']}").text


def test_one_row_per_anchor_and_other_ways_folded(store):
    _, a, p = _setup(store, criteria=[("commute", {"mode": "drive", "minutes": 20})])
    html = _page(store, p)
    assert html.count('class="commute-row"') == 1
    assert "<strong>Drive</strong>" in html
    assert "Other ways" in html
    assert html.index("Other ways") > html.index("<strong>Drive</strong>")


def test_fastest_known_when_no_criterion(store):
    _, a, p = _setup(store)
    html = _page(store, p)
    assert html.count('class="commute-row"') == 1
    assert "Other ways" in html


def test_anchor_without_location_names_it_and_links_find(store):
    _, a, p = _setup(store, anchor={"address": ""})
    html = _page(store, p)
    assert "Add a location for Office to see commutes" in html
    assert "this place has no map point" not in html.lower().split("add a location")[0]
    assert f"/search?id={store.list_searches()[0]['id']}#anchors" in html


def test_anchor_with_address_gets_find_button(store):
    _, a, p = _setup(store, anchor={"address": "1 Main St"})
    html = _page(store, p)
    assert f'action="/anchors/{a["id"]}/geocode"' in html


def test_place_without_location_says_so_and_links_its_find(store):
    _, a, p = _setup(store, place={"lat": None, "lng": None})
    html = _page(store, p)
    assert "This place has no map point yet" in html
    assert f'action="/places/{p["id"]}/geocode"' in html


def test_cost_and_move_in_cash_above_facts(store):
    _, a, p = _setup(store, place={"lat": None, "lng": None, "deposit": 1400})
    html = _page(store, p)
    assert html.index('id="cost"') < html.index('id="facts"')
    assert "Cash needed at move-in" in html
    assert html.index("Cash needed at move-in") < html.index('id="facts"')


def test_clean_place_shows_quiet_flag_line(store):
    _, a, p = _setup(store)
    html = _page(store, p)
    assert "No scam signs found in the listing text" in html


def test_flagged_place_lists_flags_not_the_quiet_line(store):
    search = store.add_search("T")
    p, _ = store.add_place(search_id=search["id"], title="X", address="1 A St", price=900,
                           listing_text="Please wire the deposit before showing.")
    html = _page(store, p)
    assert "Things to check" in html and "No scam signs found" not in html
