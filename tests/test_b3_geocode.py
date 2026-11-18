"""Opt-in address lookup: only when the setting is on, one request a second, generic user agent, no real network."""
import httpx
import pytest

from conftest import local_client
from prophelper import geocode


@pytest.fixture(autouse=True)
def fresh_clock(monkeypatch):
    """A fake clock: sleeping moves time forward, so tests never wait."""
    clock = {"t": 1000.0, "slept": []}
    monkeypatch.setattr(geocode, "_now", lambda: clock["t"])
    monkeypatch.setattr(geocode, "_sleep", lambda s: (clock["slept"].append(s), clock.__setitem__("t", clock["t"] + s)))
    monkeypatch.setattr(geocode, "_last_start", [])
    return clock


@pytest.fixture
def api(monkeypatch):
    def install(payload=None, status=200, raise_exc=None):
        def handler(request: httpx.Request) -> httpx.Response:
            handler.requests.append(request)
            if raise_exc:
                raise raise_exc(request=request, message="x") if raise_exc is not Exception else raise_exc("x")
            return httpx.Response(status, json=payload if payload is not None else [])

        handler.requests = []
        monkeypatch.setattr(geocode, "TRANSPORT", httpx.MockTransport(handler))
        return handler

    install()  # by default nothing is reachable with data; tests install what they need
    return install


FOUND = [{"lat": "40.110200", "lon": "-88.230100", "display_name": "410, Maple Row Lane, Champaign, Illinois, United States"}]


@pytest.fixture
def setup(store):
    s = store.add_search("UIUC", "rent")
    store.set_current_search(s["id"])
    p, _ = store.add_place(title="Maple Row Flats", address="410 Maple Row Lane", unit="3B", city="Champaign", state="IL", zip="61820",
                           notes="private note", listing_text="secret listing words")
    a = store.add_anchor("Campus", "Main Quad, Urbana")
    return p, a


def test_lookup_request_shape(api, fresh_clock):
    h = api(FOUND)
    lat, lng, name = geocode.lookup("410 Maple Row Lane, Champaign, IL, 61820")
    assert (lat, lng) == (40.1102, -88.2301) and "Maple Row" in name
    req = h.requests[0]
    assert req.url.host == "nominatim.openstreetmap.org" and req.url.path == "/search"
    assert dict(req.url.params) == {"q": "410 Maple Row Lane, Champaign, IL, 61820", "format": "json", "limit": "1"}
    ua = req.headers["user-agent"]
    assert ua.startswith("PropertyHelper/") and "@" not in ua and "httpx" not in ua.lower()


def test_one_request_per_second(api, fresh_clock):
    api(FOUND)
    geocode.lookup("1 Main Street, Urbana, IL")
    assert fresh_clock["slept"] == []  # the first one goes straight out
    geocode.lookup("2 Main Street, Urbana, IL")
    assert fresh_clock["slept"] == [pytest.approx(1.0)]
    fresh_clock["t"] += 5
    geocode.lookup("3 Main Street, Urbana, IL")
    assert len(fresh_clock["slept"]) == 1  # five seconds had passed, no wait needed


@pytest.mark.parametrize("payload, status, words", [([], 200, "doesn't know that address"), (None, 429, "too many lookups"),
                                                    (None, 403, "refused"), (None, 503, "busy"), ({"x": 1}, 200, "couldn't be read"),
                                                    ([{"lat": "abc", "lon": "1"}], 200, "couldn't be read"),
                                                    ([{"lat": "999", "lon": "1"}], 200, "isn't on the map")])
def test_plain_errors(api, payload, status, words):
    api(payload, status)
    with pytest.raises(geocode.GeocodeError, match=words):
        geocode.lookup("410 Maple Row Lane, Champaign, IL")


def test_timeout_and_unreachable(api, monkeypatch):
    def timeout(request):
        raise httpx.ReadTimeout("slow", request=request)

    def down(request):
        raise httpx.ConnectError("down", request=request)

    monkeypatch.setattr(geocode, "TRANSPORT", httpx.MockTransport(timeout))
    with pytest.raises(geocode.GeocodeError, match="too long"):
        geocode.lookup("410 Maple Row Lane")
    monkeypatch.setattr(geocode, "TRANSPORT", httpx.MockTransport(down))
    with pytest.raises(geocode.GeocodeError, match="Couldn't reach"):
        geocode.lookup("410 Maple Row Lane")
    with pytest.raises(geocode.GeocodeError, match="no address"):
        geocode.lookup("  ")


def test_address_text_sends_only_the_address():
    text = geocode.address_text({"title": "Maple Row Flats", "address": "410 Maple Row Lane", "unit": "3B", "city": "Champaign",
                                 "state": "IL", "zip": "61820", "notes": "private", "listing_text": "secret"})
    assert text == "410 Maple Row Lane, Champaign, IL, 61820"


# ------------------------------------------------------------------ routes
def test_place_geocode_is_off_by_default(store, setup, api):
    p, _ = setup
    h = api(FOUND)
    c = local_client(store)
    r = c.post(f"/places/{p['id']}/geocode", follow_redirects=False)
    assert r.status_code == 200 and h.requests == []  # nothing was sent; the page explains and asks
    assert store.get_place(p["id"])["lat"] is None
    assert "Turn on and find" in r.text and "sends only the address you typed" in r.text


def test_place_geocode_saves_the_point_and_sends_only_the_address(store, setup, api):
    p, _ = setup
    store.set_setting("geocode", "1")
    h = api(FOUND)
    c = local_client(store)
    r = c.post(f"/places/{p['id']}/geocode", headers={"Referer": f"http://127.0.0.1:8767/places/{p['id']}"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/places/{p['id']}"
    got = store.get_place(p["id"])
    assert (got["lat"], got["lng"]) == (40.1102, -88.2301)
    sent = str(h.requests[0].url)
    assert "private" not in sent and "secret" not in sent and "3B" not in sent and "Maple%20Row%20Flats" not in sent
    assert "Found it and saved the map point" in c.get(f"/places/{p['id']}").text
    assert "Find on map from address" in c.get(f"/places/{p['id']}").text


def test_place_without_an_address_and_errors_do_not_change_anything(store, api):
    s = store.add_search("UIUC", "rent")
    store.set_current_search(s["id"])
    bare, _ = store.add_place(title="No address", url="https://example.test/a")
    store.set_setting("geocode", "1")
    h = api(FOUND)
    c = local_client(store)
    c.post(f"/places/{bare['id']}/geocode")
    assert h.requests == [] and store.get_place(bare["id"])["lat"] is None
    full, _ = store.add_place(title="Has one", address="1 Main Street")
    api([], 200)
    c.post(f"/places/{full['id']}/geocode", follow_redirects=False)
    assert store.get_place(full["id"])["lat"] is None
    assert "doesn&#39;t know that address" in c.get(f"/places/{full['id']}").text


def test_anchor_geocode(store, setup, api):
    _, a = setup
    h = api(FOUND)
    c = local_client(store)
    c.post(f"/anchors/{a['id']}/geocode")
    assert h.requests == []  # off
    store.set_setting("geocode", "1")
    r = c.post(f"/anchors/{a['id']}/geocode", data={"search_id": "1"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/search?id=1"
    got = store.get_anchor(a["id"])
    assert (got["lat"], got["lng"]) == (40.1102, -88.2301)
    assert dict(h.requests[0].url.params)["q"] == "Main Quad, Urbana"


def test_missing_things_are_404_and_posts_are_protected(store, setup, api):
    p, _ = setup
    c = local_client(store)
    assert c.post("/places/9999/geocode").status_code == 404
    assert c.post("/anchors/9999/geocode").status_code == 404
    assert local_client(store, origin=False).post(f"/places/{p['id']}/geocode", headers={"Origin": "http://evil.test"}).status_code == 403
    assert local_client(store, unlocked=False).post(f"/places/{p['id']}/geocode").status_code == 401
    assert c.get(f"/places/{p['id']}/geocode").status_code == 405  # never a GET
