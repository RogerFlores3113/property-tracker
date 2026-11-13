"""Automatic backups in the data folder's ``backups/``: make one, list them, read what's in one, put one back.

App window only. The MCP server has no way to restore (or delete) anything.
"""
from __future__ import annotations

import os
import re
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from .paths import backups_dir
from .store import Store

BACKUPS_KEPT = 10  # per reason
LISTED = 60
# Files are named "before-<reason>-YYYY-mm-dd-HHMMSS[-n].db".
NAME_RE = re.compile(r"^before-(?P<reason>[a-z0-9]+(?:-[a-z0-9]+)*?)-(?P<stamp>\d{4}-\d{2}-\d{2}-\d{6})(?:-\d+)?\.db$")
REASONS = {"import": "Before an import", "delete": "Before a delete", "sample-removal": "Before removing sample data",
           "restore": "Before a restore", "upgrade": "Before an upgrade", "manual": "Backup you asked for"}


def _prefix(reason: str) -> str:
    return "before-" + (re.sub(r"[^a-z0-9]+", "-", reason.lower()).strip("-") or "backup") + "-"


def backup_before(store: Store, reason: str = "import", keep: int = BACKUPS_KEPT) -> Path:
    """Copy the whole database into backups/ (``before-<reason>-<time>.db``) and keep the newest ``keep`` for that
    reason. Raises ValueError (plain words) when the copy can't be made, so callers stop before changing anything."""
    folder = backups_dir()
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    prefix = _prefix(reason)
    dest, n = folder / f"{prefix}{stamp}.db", 1
    while dest.exists():
        dest, n = folder / f"{prefix}{stamp}-{n}.db", n + 1
    try:
        os.close(os.open(dest, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
        store.backup_to(dest)
    except (OSError, sqlite3.Error) as exc:
        dest.unlink(missing_ok=True)
        raise ValueError(f"Couldn't save a backup first, so nothing was changed ({exc}).") from exc
    old = sorted(folder.glob(f"{prefix}*.db"), key=lambda f: (f.stat().st_mtime, f.name))
    for f in old[:-keep] if keep > 0 else []:
        f.unlink(missing_ok=True)
    return dest


def _reason(name: str) -> str:
    m = NAME_RE.match(name)
    reason = m["reason"] if m else ""
    return REASONS.get(reason) or ("Before " + reason.replace("-", " ") if reason else "Backup")


def _when(path: Path) -> datetime:
    m = NAME_RE.match(path.name)
    if m:
        try:
            return datetime.strptime(m["stamp"], "%Y-%m-%d-%H%M%S").astimezone()
        except ValueError:
            pass
    return datetime.fromtimestamp(path.stat().st_mtime).astimezone()


def read_counts(path: Path) -> dict[str, Any]:
    """Places and searches in a backup file, read without changing it. ``ok`` is False for a file we can't read."""
    try:
        conn = sqlite3.connect(path.resolve().as_uri() + "?immutable=1", uri=True)
    except sqlite3.Error:
        return {"ok": False}
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if not {"places", "searches", "settings"} <= tables:
            return {"ok": False}
        return {"ok": True, "places": conn.execute("SELECT count(*) FROM places").fetchone()[0],
                "searches": conn.execute("SELECT count(*) FROM searches").fetchone()[0]}
    except sqlite3.Error:
        return {"ok": False}
    finally:
        conn.close()


def describe(path: Path) -> dict[str, Any]:
    return {"name": path.name, "path": path, "why": _reason(path.name), "when": _when(path).isoformat(), **read_counts(path)}


def list_backups(limit: int = LISTED) -> list[dict[str, Any]]:
    """The automatic backups, newest first, each with when, why and how many places it holds."""
    files = [f for f in backups_dir().iterdir() if f.is_file() and NAME_RE.match(f.name)]
    files.sort(key=lambda f: (_when(f), f.name), reverse=True)
    return [describe(f) for f in files[:limit]]


def backup_file(name: str) -> Path | None:
    """The backup with that file name, only if it's one of ours, straight inside the backups folder."""
    if not NAME_RE.match(name or ""):
        return None
    folder = backups_dir()
    path = folder / name
    return path if path.is_file() and path.resolve().parent == folder.resolve() else None


def restore(store: Store, name: str) -> dict[str, Any]:
    """Back up the data as it is now, then put the named backup in its place.

    Returns ``{"restored": describe(backup), "saved": Path of the copy taken first}``."""
    path = backup_file(name)
    if path is None:
        raise ValueError("That backup isn't in the backups folder any more. Reload the page and pick another.")
    info = describe(path)
    if not info["ok"]:
        raise ValueError("That backup file can't be read, so nothing was changed. Pick another one.")
    check_backup_file(path)  # the same checks as a file the person picked
    saved = backup_before(store, reason="restore")
    try:
        store.restore_from(path)
    except sqlite3.Error as exc:
        raise ValueError(f"Couldn't restore that backup, so your data wasn't changed ({exc}).") from exc
    return {"restored": info, "saved": saved}


# ------------------------------------------------------------------ restoring from a file the user picked
SQLITE_HEADER = b"SQLite format 3\x00"
REQUIRED_TABLES = {"settings", "searches", "criteria", "anchors", "places", "commutes", "events", "tours", "contacts",
                   "place_contacts", "contact_log", "documents", "checklist_items", "ai_drafts"}
UPLOAD_MAX_BYTES = 200 * 1024 * 1024


SETTINGS_ALLOWED = {"current_search_id", "ai_model", "follow_up_days", "map_tiles", "geocode", "show_photos", "theme",
                    "color_mode", "strict_scraping", "down_payment_pct", "mortgage_rate", "loan_years",
                    "pmi_rate_pct", "closing_cost_pct"}
_SHIPPED: tuple[set[tuple[str, str]], set[tuple[str, str]]] | None = None
_LAYOUTS: list[dict[str, tuple[list[str], set[str]]]] | None = None


def _norm_sql(sql: str | None) -> str:
    return " ".join((sql or "").lower().split())


def shipped_objects() -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    """What a database made by this app can hold: ``(names, code)``. ``names`` is every (type, name) in the newest
    schema (tables, indexes, triggers, views); ``code`` is the exact text of every trigger and view that any version
    of the schema ever created. Built by running our own migrations on an empty database, once."""
    global _SHIPPED
    if _SHIPPED is None:
        from .store import _MIGRATIONS

        conn = sqlite3.connect(":memory:")
        names: set[tuple[str, str]] = set()
        code: set[tuple[str, str]] = set()
        try:
            for sql in _MIGRATIONS:
                conn.executescript("BEGIN;" + sql)
                conn.commit()
                for typ, name, body in conn.execute("SELECT type, name, sql FROM sqlite_master"):
                    names.add((typ, name))
                    if typ in ("trigger", "view"):
                        code.add((name, _norm_sql(body)))
        finally:
            conn.close()
        _SHIPPED = (names, code)
    return _SHIPPED


def shipped_layouts() -> list[dict[str, tuple[list[str], set[str]]]]:
    """For each schema version (index 0 is version 1): ``{table: (column names in order, index names)}``, built by
    running our own migrations on an empty database, once."""
    global _LAYOUTS
    if _LAYOUTS is None:
        from .store import _MIGRATIONS

        conn = sqlite3.connect(":memory:")
        layouts: list[dict[str, tuple[list[str], set[str]]]] = []
        try:
            for sql in _MIGRATIONS:
                conn.executescript("BEGIN;" + sql)
                conn.commit()
                layouts.append(_layout(conn))
        finally:
            conn.close()
        _LAYOUTS = layouts
    return _LAYOUTS


def _layout(conn: sqlite3.Connection) -> dict[str, tuple[list[str], set[str]]]:
    out: dict[str, tuple[list[str], set[str]]] = {}
    for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'").fetchall():
        cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{name}")')]
        idx = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = ? "
                                          "AND name NOT LIKE 'sqlite_%'", (name,))}
        out[name] = (cols, idx)
    return out


def _check_columns(conn: sqlite3.Connection, version: int) -> None:
    """Refuse a database whose tables have other columns (or a different order) or other indexes than the schema of
    its own version. Such a file would load and then break every page."""
    reference = shipped_layouts()[version - 1]
    have = _layout(conn)
    for table, (cols, idx) in reference.items():
        got = have.get(table)
        if got is None or got[0] != cols or got[1] != idx:
            raise ValueError("That file's tables don't match what Property Helper makes (a column or an index is missing or "
                             "added), so it isn't a backup this app made and nothing was changed. "
                             "Only restore backup files you downloaded from Settings yourself.")


def _check_contents(conn: sqlite3.Connection, wrong: str) -> None:
    """Refuse a database that carries anything our own schema doesn't: a trigger, view or table someone added (they
    would run on the person's computer), or settings the app never writes."""
    names, code = shipped_objects()
    for typ, name, body in conn.execute("SELECT type, name, sql FROM sqlite_master"):
        if name.startswith("sqlite_"):
            continue
        if (typ, name) not in names or (typ in ("trigger", "view") and (name, _norm_sql(body)) not in code):
            raise ValueError("That file has extra parts in it that Property Helper doesn't create (such as a hidden trigger or "
                             "an unknown table), so it isn't a backup this app made and nothing was changed. "
                             "Only restore backup files you downloaded from Settings yourself.")
    for (key,) in conn.execute("SELECT key FROM settings"):
        if key not in SETTINGS_ALLOWED:
            raise ValueError("That file has settings Property Helper doesn't use, so it isn't a backup this app made and "
                             "nothing was changed. Only restore backup files you downloaded from Settings yourself.")


def _check_rows(conn: sqlite3.Connection) -> None:
    """Refuse a file whose rows point at things that aren't there (a place whose search is missing) or whose places
    have a stage their search's mode doesn't have. Such a file would load, but pages could break."""
    from .stages import stages_for

    if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise ValueError("Some entries in that file point to things that aren't in it (for example a place whose search is "
                         "missing), so it isn't a healthy backup and nothing was changed. Try another copy.")
    for mode, stage in conn.execute("SELECT s.mode, p.stage FROM places p JOIN searches s ON s.id = p.search_id GROUP BY s.mode, p.stage"):
        if stage not in stages_for(mode):
            raise ValueError("That file has a place in a stage Property Helper doesn't have, so it isn't a healthy backup and "
                             "nothing was changed. Try another copy.")


# Text columns a person types into are capped when written (see store._TEXT_LIMITS). A restored file may hold more,
# but not wildly more: anything over the cap times this margin (or over BIG_CELL for other columns) is refused.
CELL_MARGIN = 4
BIG_CELL = 1_000_000
# What the app itself writes into the people tables (see Store.add_contact / add_touch); checked per table because a
# column called "name" or "notes" has other limits elsewhere.
_CELL_LIMITS = {("contacts", "name"): 200, ("contacts", "email"): 320, ("contacts", "phone"): 50, ("contacts", "notes"): 20_000,
                ("contact_log", "body"): 5000, ("events", "body"): 20_000, ("ai_drafts", "body"): 50_000}


def _is_time_column(table: str, column: str) -> bool:
    return column == "at" or column.endswith("_at")


def _readable_time(value: Any) -> bool:
    text = str(value).strip()
    if not text:
        return True
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def _check_values(conn: sqlite3.Connection) -> None:
    """Refuse a file with a date or time the app can't read (it would break the calendar or a page) or with a text
    cell far bigger than the app itself would ever write."""
    from .store import TEXT_LIMITS as _TEXT_LIMITS

    for (table,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'").fetchall():
        for col in [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')]:
            if _is_time_column(table, col):
                for (value,) in conn.execute(f'SELECT DISTINCT "{col}" FROM "{table}" WHERE "{col}" IS NOT NULL'):
                    if not _readable_time(value):
                        raise ValueError("That file has a date or time Property Helper can't read (for example a tour time "
                                         "that isn't a real day), so it isn't a healthy backup and nothing was changed. Try another copy.")
            cap = _CELL_LIMITS.get((table, col), _TEXT_LIMITS.get(col, BIG_CELL // CELL_MARGIN)) * CELL_MARGIN
            if conn.execute(f'SELECT 1 FROM "{table}" WHERE length("{col}") > ? LIMIT 1', (cap,)).fetchone() is not None:
                raise ValueError("That file has an entry far longer than Property Helper ever saves, so it isn't a healthy "
                                 "backup and nothing was changed. Try another copy.")


def check_backup_file(path: Path) -> dict[str, Any]:
    """Is this a Property Helper database? Checks the SQLite header, the expected tables and the version number,
    without changing the file. Returns ``{"places": n, "searches": n}`` or raises ValueError in plain words."""
    from .store import _MIGRATIONS  # the newest version this app knows

    wrong = "That file isn't a Property Helper backup, so nothing was changed. Pick the .db file you downloaded from Settings."
    try:
        with open(path, "rb") as fh:
            if fh.read(len(SQLITE_HEADER)) != SQLITE_HEADER:
                raise ValueError(wrong)
        conn = sqlite3.connect(path.resolve().as_uri() + "?immutable=1", uri=True)
    except OSError as exc:
        raise ValueError(f"Couldn't read that file, so nothing was changed ({exc}).") from exc
    except sqlite3.Error as exc:
        raise ValueError(wrong) from exc
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if not REQUIRED_TABLES <= tables:
            raise ValueError(wrong)
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version < 1:
            raise ValueError(wrong)
        if version > len(_MIGRATIONS):
            raise ValueError("That backup was made by a newer version of Property Helper. Update the app first, then try again. "
                             "Nothing was changed.")
        if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("That backup file looks damaged, so nothing was changed. Try another copy.")
        _check_contents(conn, wrong)
        _check_columns(conn, version)
        _check_rows(conn)
        _check_values(conn)
        return {"places": conn.execute("SELECT count(*) FROM places").fetchone()[0],
                "searches": conn.execute("SELECT count(*) FROM searches").fetchone()[0]}
    except sqlite3.Error as exc:
        raise ValueError(wrong) from exc
    finally:
        conn.close()


def restore_from_upload(store: Store, data: bytes) -> dict[str, Any]:
    """Check an uploaded database file, save a backup of the current data, then put the file's data in its place.

    Returns ``{"counts": {...}, "saved": Path of the copy taken first}``. Raises ValueError (plain words) before
    anything is changed when the file isn't ours."""
    if not data:
        raise ValueError("Choose the backup file first.")
    fd, tmp_name = tempfile.mkstemp(prefix="upload-", suffix=".db", dir=backups_dir())
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        counts = check_backup_file(tmp)
        saved = backup_before(store, reason="restore")
        try:
            store.restore_from(tmp)
        except sqlite3.Error as exc:
            raise ValueError(f"Couldn't restore that file, so your data wasn't changed ({exc}).") from exc
        return {"counts": counts, "saved": saved}
    finally:
        tmp.unlink(missing_ok=True)
