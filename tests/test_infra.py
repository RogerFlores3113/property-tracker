"""Paths, backups, CLI, Connect and Skills pages (none of these may crash when the MCP server or skill files are absent)."""
import sys

import pytest

from prophelper import backups, integrations, paths, skills_install


def test_paths_use_the_isolated_data_dir(tmp_path):
    assert paths.data_dir() == tmp_path / "data"
    assert paths.db_path().name == "prophelper.db"
    assert paths.DEFAULT_PORT == 8767


def test_app_key_is_private_and_stable():
    key = paths.app_key()
    assert key == paths.app_key() and len(key) >= 32
    if sys.platform != "win32":
        assert (paths.data_dir() / "app.key").stat().st_mode & 0o077 == 0


def test_launch_code_is_single_use():
    code = paths.new_launch_code()
    assert paths.use_launch_code(code) and not paths.use_launch_code(code)


def test_names_are_property_helper():
    assert integrations.SERVER_KEY == "property-helper"
    spec = integrations.mcp_launch_spec()
    assert spec.args[-1] == "mcp" and "PROPHELPER_DATA_DIR" in spec.env
    assert skills_install.PLUGIN_FILE == "property-helper.plugin"


def test_connect_and_skills_pages_render(client):
    html = client.get("/connect").text
    assert "Connect an AI app" in html and "property-helper" in html and "Job App Tracker" not in html
    html = client.get("/skills").text
    assert "Skills" in html and "Job App Tracker" not in html


def test_skills_preview_without_skill_files_does_not_crash(client):
    r = client.post("/skills/all/preview", data={"claude": "1", "codex": "1"})
    assert r.status_code == 200


def test_plugin_download_is_a_download_path(client):
    r = client.get("/skills/property-helper.plugin")
    assert r.status_code in (200, 404, 503)  # whatever the skills folder holds, it must not be a server error
    assert r.status_code != 500


# ---- backups
def test_backup_download_and_restore_round_trip(client, store):
    store.add_search("S")
    store.add_place(title="Kept", address="1 A St")
    data = client.get("/backup").content
    assert data[:6] == b"SQLite"
    store.add_place(title="Added later", address="2 B St")
    r = client.post("/backups/restore-file", files={"file": ("b.db", data, "application/octet-stream")}, follow_redirects=False)
    assert r.status_code == 303
    assert [p["title"] for p in store.list_places()] == ["Kept"]
    assert backups.list_backups()  # the state from before the restore was saved first


def test_restore_refuses_a_file_that_is_not_a_backup(client, store):
    store.add_search("S")
    r = client.post("/backups/restore-file", files={"file": ("x.db", b"not a database at all", "application/octet-stream")},
                    follow_redirects=False)
    assert r.status_code == 303
    assert len(store.list_searches()) == 1  # nothing was replaced
    assert "isn't" in client.get("/backups").text or "backup" in client.get("/backups").text


def test_files_zip_when_empty_is_friendly(client):
    r = client.get("/backup/files.zip", follow_redirects=False)
    assert r.status_code in (200, 303)


# ---- CLI
def test_cli_mcp_says_so_when_the_server_is_missing(capsys):
    from prophelper import cli

    try:
        import prophelper.mcp_server  # noqa: F401
        pytest.skip("the MCP server exists in this build")
    except ImportError:
        pass
    with pytest.raises(SystemExit) as exc:
        cli.main(["mcp"])
    assert "MCP server" in str(exc.value) and "isn't part of this build" in str(exc.value)


def test_cli_sample_data_and_backup(capsys, tmp_path):
    from prophelper import cli

    cli.main(["sample-data"])
    assert "10 sample places" in capsys.readouterr().out
    cli.main(["backup", str(tmp_path / "out.db")])
    assert (tmp_path / "out.db").exists()
