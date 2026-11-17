"""Cycle 29 G5 item 6: /export.csv and /share are not dead ends. No new data leaves the machine: both only point at what exists."""
from __future__ import annotations

import pytest


def _search(store):
    s = store.add_search("R", "rent", budget_max=2000)
    a, _ = store.add_place(title="Oak", address="1 A St", price=1400)
    b, _ = store.add_place(title="Elm", address="2 A St", price=1500)
    return s, a, b


@pytest.mark.parametrize("path", ["/export.csv", "/export/places.csv", "/export", "/places.csv"])
def test_csv_paths_all_give_the_same_file(client, store, path):
    s, a, b = _search(store)
    r = client.get(path)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "Oak" in r.text and "Elm" in r.text
    assert "attachment" in r.headers["content-disposition"]


def test_export_csv_keeps_the_query_and_is_a_redirect(client, store):
    s, a, b = _search(store)
    r = client.get(f"/export.csv?search_id={s['id']}&q=Oak", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == f"/places.csv?search_id={s['id']}&q=Oak"
    r = client.get(f"/export.csv?search_id={s['id']}&q=Oak")
    assert "Oak" in r.text and "Elm" not in r.text


def test_share_with_places_goes_to_the_comparison_copy(client, store):
    s, a, b = _search(store)
    r = client.get(f"/share?ids={a['id']},{b['id']}", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == f"/compare/share.html?ids={a['id']}%2C{b['id']}" or r.headers["location"].startswith("/compare/share.html?ids=")
    r = client.get(f"/share?ids={a['id']},{b['id']}")
    assert r.status_code == 200 and "Oak" in r.text and "Elm" in r.text


@pytest.mark.parametrize("path", ["/share", "/share?x=1"])
def test_share_alone_explains_how_to_share(client, store, path):
    _search(store)
    r = client.get(path, follow_redirects=True)
    assert r.status_code == 200
    assert "Share a copy" in r.text and "Export this search" in r.text and "CSV" in r.text


def test_other_sites_cannot_pull_the_downloads(client, store):
    _search(store)
    for path in ("/export.csv", "/share"):
        r = client.get(path, headers={"sec-fetch-site": "cross-site"}, follow_redirects=False)
        assert r.status_code in (403, 400, 401, 404) or r.status_code >= 400, (path, r.status_code)
