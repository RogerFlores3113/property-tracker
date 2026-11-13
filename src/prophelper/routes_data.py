"""Settings, backups, sample data and the privacy page.

    GET  /settings                  Settings; POST /settings (map and lookups, reminders, model), /settings/look (colors),
                                    /settings/ai-key (+ /remove), /settings/strict-scraping, /settings/open-folder
    GET  /privacy                   what is stored, and the three network calls
    GET  /backup                    download a copy of the database (a download)
    GET  /backup/files.zip          download the documents added to places (a download)
    GET  /backups                   Backups page; POST /backups/{name}/restore (an automatic backup),
                                    POST /backups/restore-file (a backup file the person picked)
    POST /sample-data, POST /sample-data/remove
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import zipfile
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Form, Request
from fastapi.responses import FileResponse, Response
from starlette.background import BackgroundTask
from starlette.formparsers import MultiPartParser

from . import ai_key, backups, geocode, paths, share
from .deps import get_store, redirect, render
from .sample_data import load_sample_data
from .store import STRICT_ADDS_PER_CALL, STRICT_ADDS_PER_HOUR, NotFound, Store

router = APIRouter()


class TooBig(Exception):
    pass


async def discard_body(request: Request, cap: int) -> int:
    """Read and throw away what the browser is still sending, up to ``cap`` bytes, so that our answer ("that file is
    too big") reaches it. A server that replies and hangs up while the browser is still sending makes the browser show
    "connection reset" instead of the answer. Nothing is kept. Returns how many bytes were read."""
    seen = 0
    try:
        async for chunk in request.stream():
            seen += len(chunk)
            if seen >= cap:
                break
    except Exception:  # the browser gave up or hung up: nothing left to read
        pass
    return seen


async def read_form(request: Request, limit: int):
    """The submitted form. Uploads stay in memory (no temp files); more than ``limit`` bytes raises TooBig."""
    try:
        declared = int(request.headers.get("content-length") or 0)
    except ValueError:
        declared = 0
    if declared > limit + 512 * 1024:
        await discard_body(request, 2 * limit + 1024 * 1024)  # let the browser finish sending, so it can read our answer
        raise TooBig
    if (request.headers.get("content-type") or "").lower().startswith("multipart/form-data"):
        parser = MultiPartParser(request.headers, request.stream(), max_files=20, max_fields=500, max_part_size=limit)
        parser.spool_max_size = limit + 1024 * 1024  # keep file parts in memory instead of a temp file
        form = await parser.parse()
    else:
        form = await request.form()
    return form


def mb(n: int) -> str:
    return f"{n // (1024 * 1024)} MB"


# --------------------------------------------------------------------------- settings
def _folder_button_label() -> str:
    if sys.platform == "darwin":
        return "Show in Finder"
    if sys.platform == "win32":
        return "Show in Explorer"
    return "Show in file manager"


def _files_count() -> int:
    try:
        return sum(1 for f in (paths.data_dir() / "files").rglob("*") if f.is_file())
    except OSError:
        return 0


def _settings_context(store: Store) -> dict[str, Any]:
    return {"key": ai_key.key_status(), "model": store.get_setting("ai_model"),
            "follow_up_days": store.get_setting_int("follow_up_days", 3), "data_folder": str(paths.data_dir().resolve()),
            "places": store.count_places(include_archived=True), "archived_count": store.count_places(include_archived=True) - store.count_places(),
            "searches_count": len(store.list_searches(include_archived=True)), "files_count": _files_count(),
            "folder_button": _folder_button_label(), "map_tiles": store.get_setting_bool("map_tiles"),
            "geocode": store.get_setting_bool("geocode"), "show_photos": store.get_setting_bool("show_photos"),
            "strict": store.get_setting_bool("strict_scraping"), "strict_per_call": STRICT_ADDS_PER_CALL,
            "strict_per_hour": STRICT_ADDS_PER_HOUR, "down_payment_pct": store.get_setting("down_payment_pct"),
            "mortgage_rate": store.get_setting("mortgage_rate"), "loan_years": store.get_setting("loan_years"),
            "pmi_rate_pct": store.get_setting("pmi_rate_pct"),
            "closing_cost_pct": store.get_setting("closing_cost_pct")}


def open_folder(path: Path) -> bool:
    """Ask the operating system to show a folder in Finder, Explorer or the file manager. False if it couldn't."""
    try:
        if sys.platform == "darwin":
            cmd = ["open", str(path)]
        elif sys.platform == "win32":
            os.startfile(str(path))  # type: ignore[attr-defined]  # noqa: S606
            return True
        else:
            cmd = ["xdg-open", str(path)]
        subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # noqa: S603
        return True
    except (OSError, ValueError):
        return False


@router.post("/settings/open-folder", include_in_schema=False)
def open_data_folder(request: Request):
    """Show the data folder in Finder or Explorer. Only for the app window itself (its own cookie), never for
    the key-header links the command line and AI apps use."""
    if request.headers.get("x-prophelper-key"):
        return redirect("/settings", error="Opening the folder only works from the app window.")
    folder = paths.data_dir().resolve()
    if open_folder(folder):
        return redirect("/settings", notice=f"Opened the folder: {folder}")
    return redirect("/settings", error=f"Couldn't open it from here. The folder is: {folder}")


@router.get("/settings", include_in_schema=False)
def settings_page(request: Request):
    return render(request, "settings.html", **_settings_context(get_store(request)))


def _int_between(value: str, low: int, high: int, name: str) -> int:
    try:
        n = int(str(value).strip())
    except ValueError:
        raise ValueError(f"{name} needs to be a whole number.") from None
    if not low <= n <= high:
        raise ValueError(f"{name} needs to be between {low} and {high}.")
    return n


def _float_between(value: str, low: float, high: float, name: str) -> float:
    try:
        n = float(str(value).strip())
    except ValueError:
        raise ValueError(f"{name} needs to be a number.") from None
    if not low <= n <= high:
        raise ValueError(f"{name} needs to be between {low:g} and {high:g}.")
    return n


@router.post("/settings", include_in_schema=False)
async def save_settings(request: Request):
    """One form per section posts here; only the fields that came are changed. Checkboxes come with a hidden 0."""
    store = get_store(request)
    form = await request.form()
    try:
        if "follow_up_days" in form:
            store.set_setting("follow_up_days", _int_between(form["follow_up_days"], 1, 365, "Follow up after"))
        if "ai_model" in form:
            model = str(form["ai_model"]).strip() or store.get_setting("ai_model")
            if not re.fullmatch(r"[A-Za-z0-9._:\-]{1,100}", model or ""):
                raise ValueError("A model name has only letters, numbers, dots and dashes, like claude-sonnet-5-5.")
            store.set_setting("ai_model", model)
        for name in ("map_tiles", "geocode", "show_photos"):
            if name in form:
                store.set_setting(name, "1" if str(form[name]) == "1" else "0")
        if "down_payment_pct" in form:
            store.set_setting("down_payment_pct", _float_between(form["down_payment_pct"], 0, 100, "The down payment"))
        if "mortgage_rate" in form:
            store.set_setting("mortgage_rate", _float_between(form["mortgage_rate"], 0, 30, "The mortgage rate"))
        if "pmi_rate_pct" in form:
            store.set_setting("pmi_rate_pct", _float_between(form["pmi_rate_pct"], 0, 5, "The mortgage insurance rate"))
        if "closing_cost_pct" in form:
            store.set_setting("closing_cost_pct", _float_between(form["closing_cost_pct"], 0, 15, "The closing cost estimate"))
        if "loan_years" in form:
            store.set_setting("loan_years", _int_between(form["loan_years"], 1, 50, "The loan length"))
    except ValueError as exc:
        return redirect("/settings", error=str(exc))
    return redirect("/settings", notice="Settings saved.")


THEMES = ("sunset", "forest-night", "ocean", "midnight", "classic", "contrast")  # base.html and settings.html list the same names
THEMES_WITH_MODES = ("sunset", "classic", "contrast")  # these also have a dark version; the others keep one look
COLOR_MODES = ("auto", "light", "dark")


@router.post("/settings/look", include_in_schema=False)
def save_look(request: Request, theme: str = Form(""), color_mode: str = Form("")):
    """Save the color theme and the light or dark choice. Anything unknown is ignored, so a bad value never sticks."""
    store = get_store(request)
    if theme in THEMES:
        store.set_setting("theme", theme)
    if color_mode in COLOR_MODES:
        store.set_setting("color_mode", color_mode)
    return redirect("/settings#on-screen", notice="Colors saved.")


@router.post("/settings/strict-scraping", include_in_schema=False)
def save_strict(request: Request, on: str = Form("")):
    store = get_store(request)
    store.set_setting("strict_scraping", "1" if on == "1" else "0")
    return redirect("/settings#scraping", notice="Stricter scraping guards are on." if on == "1" else "Stricter scraping guards are off.")


@router.post("/settings/ai-key", include_in_schema=False)
def save_ai_key(request: Request, key: str = Form("")):
    try:
        ai_key.save_key(key)
    except ValueError as exc:
        return redirect("/settings#ai", error=str(exc))
    return redirect("/settings#ai", notice="Key saved. It stays in a private file on this computer.")


@router.post("/settings/ai-key/remove", include_in_schema=False)
def remove_ai_key(request: Request):
    removed = ai_key.remove_key()
    if ai_key.key_status()["source"] == "env":
        return redirect("/settings#ai", notice="The saved key is removed. A key set in your computer's environment is still in use.")
    return redirect("/settings#ai", notice="Key removed." if removed else "There was no saved key.")


# --------------------------------------------------------------------------- privacy
@router.get("/privacy", include_in_schema=False)
def privacy_page(request: Request):
    store = get_store(request)
    return render(request, "privacy.html", data_folder=str(paths.data_dir()), key=ai_key.key_status(),
                  map_tiles=store.get_setting_bool("map_tiles"), geocode=store.get_setting_bool("geocode"),
                  show_photos=store.get_setting_bool("show_photos"), geocode_agent=geocode.USER_AGENT,
                  ai_model=store.get_setting("ai_model"))


# --------------------------------------------------------------------------- downloads
@router.get("/backup", include_in_schema=False)
def backup_download(request: Request):
    store = get_store(request)
    fd, tmp = tempfile.mkstemp(prefix="download-", suffix=".db", dir=paths.backups_dir())
    os.close(fd)
    try:
        store.backup_to(tmp)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        return redirect("/settings", error="Couldn't make a backup copy just now. Try again.")
    name = f"property-helper-backup-{date.today().isoformat()}.db"
    return FileResponse(tmp, media_type="application/octet-stream", filename=name,
                        background=BackgroundTask(lambda: Path(tmp).unlink(missing_ok=True)))


@router.get("/backup/files.zip", include_in_schema=False)
def backup_files_download(request: Request):
    """The documents added to places (leases, applications, photos) as one zip. Empty folder: a friendly message."""
    root = paths.data_dir() / "files"
    found = [f for f in root.rglob("*") if f.is_file() and not f.is_symlink()] if root.is_dir() else []
    if not found:
        return redirect("/backups", error="There are no documents to download yet.")
    fd, tmp = tempfile.mkstemp(prefix="download-", suffix=".zip", dir=paths.backups_dir())
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            for f in found:
                z.write(f, f.relative_to(root).as_posix())
    except OSError:
        Path(tmp).unlink(missing_ok=True)
        return redirect("/backups", error="Couldn't pack the documents just now. Try again.")
    return FileResponse(tmp, media_type="application/zip", filename=f"property-helper-documents-{date.today().isoformat()}.zip",
                        background=BackgroundTask(lambda: Path(tmp).unlink(missing_ok=True)))


@router.get("/backups", include_in_schema=False)
def backups_page(request: Request):
    return render(request, "backups.html", backups=backups.list_backups(), places=get_store(request).count_places(include_archived=True),
                  files_count=_files_count(), files_folder=str(paths.data_dir() / "files"))


@router.post("/backups/restore-file", include_in_schema=False)
async def restore_backup_file(request: Request):
    """Restore from a backup file the user picked (one they downloaded earlier). Checked first, current data saved first."""
    try:
        form = await read_form(request, backups.UPLOAD_MAX_BYTES)
    except TooBig:
        return redirect("/backups", error=f"That file is bigger than {mb(backups.UPLOAD_MAX_BYTES)}, so it can't be a backup from this app.")
    try:
        upload = form.get("file")
        if upload is None or not hasattr(upload, "read") or not getattr(upload, "filename", ""):
            return redirect("/backups", error="Choose the backup file first.")
        data = await upload.read()
        if len(data) > backups.UPLOAD_MAX_BYTES:
            return redirect("/backups", error="That file is too big to be a backup from this app.")
    finally:
        await form.close()
    try:
        out = backups.restore_from_upload(get_store(request), data)
    except ValueError as exc:
        return redirect("/backups", error=str(exc))
    n = out["counts"]["places"]
    return redirect("/settings", notice=f"Restored your backup ({n} place{'s' if n != 1 else ''}). "
                                        f"Your data from just before is saved as {out['saved'].name}.")


@router.post("/backups/{name}/restore", include_in_schema=False)
def restore_backup(request: Request, name: str):
    try:
        info = backups.restore(get_store(request), name)
    except ValueError as exc:
        return redirect("/backups", error=str(exc))
    return redirect("/settings", notice=f"Restored the backup. Your data from just before is saved as {info['saved'].name}.")


# --------------------------------------------------------------------------- sample data
@router.post("/sample-data", include_in_schema=False)
def sample_data_load(request: Request):
    store = get_store(request)
    if store.has_sample_data():
        return redirect("/settings", notice="Sample data is already loaded.")
    n = load_sample_data(store)
    return redirect("/today", notice=f"Added a sample search with {n} made-up places so you can look around. Remove them any time in Settings.")


@router.post("/sample-data/remove", include_in_schema=False)
def sample_data_remove(request: Request):
    store = get_store(request)
    try:
        backups.backup_before(store, reason="sample-removal")
    except ValueError as exc:
        return redirect("/settings", error=str(exc))
    counts = store.remove_sample_data()
    return redirect("/settings", notice=f"Removed the sample data ({counts['places']} places). Your own entries were not touched.")


# --------------------------------------------------------------------------- share a search with a housemate
@router.get("/search/export.json", include_in_schema=False)
def search_export(request: Request, id: int | None = None):
    """Download a search as a file a housemate can read back in with "Import a search" (see ``share.py``). It holds the
    search, what matters, the important places it uses and the places with their facts and listing text. Never contacts,
    documents, notes, ratings, AI text or the AI key."""
    store = get_store(request)
    try:
        search = store.get_search(id) if id else store.current_search()
    except NotFound:
        search = None
    if search is None:
        return redirect("/search", error="That search doesn't exist.")
    return Response(share.export_bytes(store, search["id"]), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{share.export_filename(search)}"', "X-Content-Type-Options": "nosniff"})


@router.post("/searches/import", include_in_schema=False)
async def search_import_upload(request: Request):
    """Read a file made by "Export this search" and show what it would add. Writes nothing yet."""
    try:
        form = await read_form(request, share.MAX_IMPORT_BYTES)
    except TooBig:
        return redirect("/search", error="That file is too big (limit 5 MB). A shared search is usually much smaller.")
    try:
        upload = form.get("file")
        if upload is None or not hasattr(upload, "read") or not getattr(upload, "filename", ""):
            return redirect("/search", error="Choose the search file first.")
        data = await upload.read(share.MAX_IMPORT_BYTES + 1)
        filename = re.sub(r"[^\w .()-]+", "", str(upload.filename))[:80] or "your file"
    finally:
        await form.close()
    try:
        doc = share.read_export(data)
    except share.NotAnExport as exc:
        return redirect("/search", error=str(exc))
    token = share.hold(filename, doc)
    s = doc["search"]
    shown = get_store(request)
    new_name = share.imported_name(s.get("name"))
    report = share.dry_run(doc)
    left_out = share.left_out_lines({**report, "link_dropped": 0, "places_skipped": report.get("places_skipped", 0),
                                      "criteria_skipped": report.get("criteria_skipped", 0)})
    return render(request, "share_import.html", token=token, filename=filename, headline=share.preview_text(doc),
                  mode=str(s.get("mode") or "rent"), criteria=len(doc["criteria"]) - report.get("criteria_skipped", 0), anchors=len(doc["anchors"]),
                  new_name=new_name, left_out=left_out,
                  same_name=any(x["name"].lower() == new_name.lower() for x in shown.list_searches(include_archived=True)))


@router.post("/searches/import/apply", include_in_schema=False)
async def search_import_apply(request: Request):
    """Do exactly what the preview said: add the file as a NEW search. Nothing that is already saved is changed."""
    form = await request.form()
    token = str(form.get("token", ""))
    got = share.held(token)
    if got is None:
        return redirect("/search", error="That file is no longer waiting. Choose it again.")
    store = get_store(request)
    try:
        out = share.apply_import(store, got[1])
    except ValueError as exc:
        return redirect("/search", error=f"Couldn't add that search, so nothing was changed ({exc})")
    share.release(token)
    s = out["search"]
    extra = ""
    extra += "".join(" " + line.replace("will be left out", "were left out").replace("will have", "have").replace("is kept", "was kept").replace("are kept", "were kept")
                     for line in share.left_out_lines(out))
    return redirect(f"/search?id={s['id']}", notice=f"Added the search '{s['name']}' with {out['places']} place{'s' if out['places'] != 1 else ''}. "
                                                    f"It isn't your current search yet; use Switch to this when you are ready.{extra}")
