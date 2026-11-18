"""Cycle 3, G5: map pictures off for new folders, the page rules, private folder modes."""
import os

import pytest

from prophelper import paths
from prophelper.store import Store


def test_new_folder_has_tiles_off_and_plain_map_with_one_button(client, sample_store):
    assert sample_store.get_setting_bool("map_tiles") is False
    html = client.get("/map").text
    assert "Show street map (loads map pictures from OpenStreetMap)" in html
    assert 'data-tiles="0"' in html


def test_the_button_turns_tiles_on(client, sample_store):
    r = client.post("/map/tiles", follow_redirects=False)
    assert r.status_code in (302, 303)
    assert sample_store.get_setting_bool("map_tiles") is True
    assert "Show street map" not in client.get("/map").text


def test_old_folder_without_a_saved_choice_keeps_tiles_on(tmp_path):
    p = tmp_path / "old.db"
    s = Store(p)
    s._conn.execute("DELETE FROM settings WHERE key = 'map_tiles'")
    s._conn.commit()
    s.close()
    s2 = Store(p)
    assert s2.get_setting_bool("map_tiles") is True
    s2.close()
    p2 = tmp_path / "old2.db"
    s3 = Store(p2)
    s3.set_setting("map_tiles", "0")
    s3.close()
    s4 = Store(p2)
    assert s4.get_setting_bool("map_tiles") is False
    s4.close()


def test_csp_allows_tiles_only_on_map_and_only_when_on(client, store):
    for path in ("/today", "/map", "/settings", "/privacy"):
        assert "openstreetmap" not in client.get(path).headers["content-security-policy"]
    store.set_setting("map_tiles", "1")
    assert "https://tile.openstreetmap.org" in client.get("/map").headers["content-security-policy"]
    for path in ("/today", "/settings", "/privacy", "/board"):
        assert "openstreetmap" not in client.get(path).headers["content-security-policy"]


@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_fresh_data_folder_is_700_and_database_600(tmp_path, monkeypatch):
    target = tmp_path / "fresh"
    monkeypatch.setenv("PROPHELPER_DATA_DIR", str(target))
    old = os.umask(0o000)
    try:
        db = paths.db_path()
        s = Store(db)
        s.close()
    finally:
        os.umask(old)
    assert target.stat().st_mode & 0o777 == 0o700
    assert db.stat().st_mode & 0o777 == 0o600


def test_connect_page_says_what_claude_can_read(client):
    html = client.get("/connect").text
    assert "can read your notes and ratings on places when you ask Claude about them" in html
    assert "Nothing is sent anywhere until you use Claude" in html
