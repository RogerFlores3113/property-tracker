import re

import pytest

from conftest import LOCAL_URL, local_client

NAV_PAGES = ["/today", "/board", "/search", "/add", "/settings", "/connect", "/skills", "/privacy", "/backups"]


def test_health_is_open_and_says_little(locked_client):
    r = locked_client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "version": r.json()["version"]}


def test_health_proof_and_counts_when_unlocked(client):
    r = client.get("/api/health", params={"nonce": "abc"})
    body = r.json()
    from prophelper import paths

    assert body["proof"] == paths.health_proof(paths.app_key(), "abc", 8767)
    assert body["places"] == 0


def test_locked_window_shows_how_to_unlock(locked_client):
    r = locked_client.get("/today")
    assert r.status_code == 401
    assert "prophelper open" in r.text and "Property Helper" in r.text
    assert locked_client.get("/api/anything").status_code == 401
    assert locked_client.get("/static/style.css").status_code == 200  # the locked page needs its CSS


def test_launch_code_unlocks_once(locked_client):
    from prophelper import paths

    assert locked_client.get("/launch?code=wrong", follow_redirects=False).status_code == 401
    code = paths.new_launch_code()
    r = locked_client.get(f"/launch?code={code}", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert "prophelper_key_" in r.headers["set-cookie"] and "HttpOnly" in r.headers["set-cookie"]
    assert locked_client.get("/today").status_code == 200
    # the code is spent
    from fastapi.testclient import TestClient

    from prophelper.web import create_app

    fresh = TestClient(create_app(locked_client.app.state.store), base_url=LOCAL_URL)
    assert fresh.get(f"/launch?code={code}", follow_redirects=False).status_code == 401


def test_key_header_also_unlocks(locked_client):
    from prophelper import paths

    r = locked_client.get("/today", headers={"x-prophelper-key": paths.app_key()})
    assert r.status_code == 200


def test_foreign_host_is_rejected(client):
    assert client.get("/today", headers={"host": "evil.example.com"}).status_code == 403
    assert client.get("/api/health", headers={"host": "evil.example.com:8767"}).status_code == 403
    assert client.get("/today", headers={"host": "localhost:8767"}).status_code == 200


def test_cross_site_origin_is_rejected_on_writes(client):
    assert client.post("/nothing", headers={"Origin": "https://evil.example.com"}).status_code == 403
    assert client.post("/nothing", headers={"Origin": "null"}).status_code == 403
    assert client.post("/nothing", headers={"Origin": "http://127.0.0.1:9999"}).status_code == 403
    # our own origin gets through the guard (and then a plain 404/405 because the route is not there)
    assert client.post("/nothing", headers={"Origin": LOCAL_URL}).status_code in (404, 405)
    assert client.post("/nothing", headers={"Origin": "", "Sec-Fetch-Site": "cross-site"}).status_code == 403


def test_downloads_refuse_cross_site_fetches(client):
    assert client.get("/backup", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403


def test_root_redirects_to_today(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/today"


@pytest.mark.parametrize("path", NAV_PAGES)
def test_nav_pages_return_200_after_unlock(client, path):
    r = client.get(path)
    assert r.status_code == 200
    assert "<nav" in r.text and 'href="/today"' in r.text and 'href="/add"' in r.text


def test_nav_has_every_destination(client):
    html = client.get("/today").text
    for href in ("/today", "/board", "/map", "/calendar", "/compare", "/contacts", "/search", "/add", "/settings"):
        assert f'href="{href}"' in html


def test_security_headers(client):
    r = client.get("/today")
    assert r.headers["x-frame-options"] == "DENY"
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["cache-control"] == "no-store"
    assert "<script>" not in r.text  # no inline scripts: the CSP forbids them


def test_unknown_page_is_a_friendly_404(client):
    r = client.get("/nope")
    assert r.status_code == 404 and "That page doesn&#39;t exist." in r.text
    assert client.get("/api/nope").json()["detail"]


def test_place_page_404_and_escaping(client, store):
    assert client.get("/places/999").status_code == 404
    store.add_search("S", "rent")
    app, _ = store.add_place(title="<script>alert(1)</script>", notes="<b>Evil</b>")
    html = client.get(f"/places/{app['id']}").text
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html


def test_flash_message_travels_in_a_cookie_not_the_address(client):
    from prophelper.deps import redirect

    r = redirect("/today", notice="Saved <it>")
    assert "notice=" in r.headers["location"]  # the middleware moves it into the cookie on a real response

    @client.app.get("/flash-test")
    def flash_test():
        return redirect("/today", notice="Saved <it>")

    resp = client.get("/flash-test", follow_redirects=False)
    assert resp.headers["location"] == "/today"
    assert "prophelper_flash_" in resp.headers["set-cookie"]
    page = client.get("/today")
    assert "Saved &lt;it&gt;" in page.text


def test_flash_cookie_must_be_signed(client):
    from prophelper import paths
    from prophelper.web import decode_flash, encode_flash, flash_cookie_name

    key = paths.app_key()
    good = encode_flash(key, {"notice": "hello"})
    assert decode_flash(good, key) == {"notice": "hello"}
    assert decode_flash(good.rsplit(".", 1)[0] + ".deadbeef", key) == {}
    client.cookies.set(flash_cookie_name(key), "eyJub3RpY2UiOiAiZmFrZSJ9.bad")
    assert "fake" not in client.get("/today").text


def test_unlocked_requires_the_right_key(store):
    c = local_client(store, unlocked=False)
    from prophelper.web import key_cookie_name

    c.cookies.set(key_cookie_name("x" * 40), "x" * 40)
    assert c.get("/today").status_code == 401
