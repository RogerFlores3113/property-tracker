"""Shared fixtures. Reuse these in every test file.

* ``_isolated_data_dir`` (autouse): PROPHELPER_DATA_DIR points at a fresh temp folder, so nothing touches real data.
* ``store``: a Store on a temp database file.
* ``sample_store``: the same, with the sample data loaded.
* ``client``: a TestClient for the app window, already unlocked and sending its own Origin header.
* ``locked_client``: a TestClient that has not been unlocked.
* ``local_client(store, origin=True, unlocked=True)``: build one by hand (plain function, import it).
"""
import pytest

from prophelper.store import Store

LOCAL_URL = "http://127.0.0.1:8767"


def local_client(store, origin: bool = True, unlocked: bool = True, **kwargs):
    """origin: send our own Origin header, like the app's own pages. unlocked: carry the app window's key
    cookie, like a browser opened from the app icon."""
    from fastapi.testclient import TestClient

    from prophelper import paths
    from prophelper.web import create_app

    c = TestClient(create_app(store), base_url=LOCAL_URL, headers={"Origin": LOCAL_URL} if origin else None, **kwargs)
    if unlocked:  # the real unlock: a launch code is exchanged for a random session cookie
        c.get(f"/launch?code={paths.new_launch_code()}", follow_redirects=False)
    return c


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("PROPHELPER_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("PROPHELPER_DOWNLOADS_DIR", raising=False)


@pytest.fixture(autouse=True)
def _never_touch_a_real_claude_app(monkeypatch):
    """No test may quit, start or look for a real Claude app, or open a file manager window, whatever the machine."""
    from prophelper import integrations, skills_install

    monkeypatch.setattr(integrations, "app_running", lambda app="claude": False)
    monkeypatch.setattr(integrations, "windows_desktop_pids", lambda read=None: [])
    monkeypatch.setattr(integrations, "_run_quiet", lambda cmd, timeout=10.0: 0)
    monkeypatch.setattr(integrations, "_launch_detached", lambda cmd: None)
    monkeypatch.setattr(integrations, "restart_supported",
                        lambda platform=None: platform in ("darwin", "win32") if platform else False)
    monkeypatch.setattr(skills_install, "open_claude_app", lambda: False)
    monkeypatch.setattr(skills_install, "reveal", lambda path, platform=None: False)


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "prophelper.db")
    yield s
    s.close()


@pytest.fixture
def sample_store(store):
    from prophelper.sample_data import load_sample_data

    load_sample_data(store)
    return store


@pytest.fixture
def client(store):
    return local_client(store)


@pytest.fixture
def locked_client(store):
    return local_client(store, unlocked=False)
