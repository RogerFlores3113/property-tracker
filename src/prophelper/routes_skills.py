"""The Skills page (opt-in install of the Claude and Codex skill files).

    GET  /skills                    what would be written where, and what is installed
    POST /skills/install            target=claude|codex: write that skill file (never over a file we did not write)
    POST /skills/uninstall          target=claude|codex: remove only what the manifest lists, and only if unchanged
    POST /skills/all/preview        the files for every app found (or the apps ticked): new, updated, unchanged, kept
    POST /skills/all/install        install into those apps after that preview
    POST /skills/add                the one-press "Add skills": every app found, plus the Claude plugin file
    POST /skills/plugin/save        write property-helper.plugin into Downloads and show it in the file manager
    GET  /skills/property-helper.plugin   the same file as a download
    POST /skills/claude-app/open    start the Claude desktop app where possible

Skill files are plain text. The manifest (``skills-manifest.json`` in the data folder) records the path and SHA-256
of every file we wrote, so Uninstall can tell our file from one someone edited or replaced.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import Response

from . import paths
from .deps import get_store, is_htmx, redirect, render

router = APIRouter()

SKILL_NAME = "property-helper"
MANIFEST_NAME = "skills-manifest.json"


# --------------------------------------------------------------------------- where things live
def skills_source_dir() -> Path:
    """The folder holding the bundled skill files: inside the package when installed or frozen, else the repo's skills/."""
    for candidate in (paths.resource_dir() / "skills", Path(__file__).resolve().parents[2] / "skills"):
        if candidate.is_dir():
            return candidate
    return paths.resource_dir() / "skills"


def _claude_dest() -> Path:
    return Path.home() / ".claude" / "skills" / SKILL_NAME / "SKILL.md"


def _codex_dest() -> Path:
    home = os.environ.get("CODEX_HOME")  # Codex itself honours this, like the Connect page does
    return (Path(home) if home else Path.home() / ".codex") / "skills" / SKILL_NAME / "SKILL.md"


TARGETS: dict[str, dict[str, Any]] = {
    "claude": {"name": "Claude", "dest": _claude_dest, "source": "claude/property-helper/SKILL.md"},
    "codex": {"name": "Codex", "dest": _codex_dest, "source": "codex/property-helper/SKILL.md"},
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _manifest_path() -> Path:
    return paths.data_dir() / MANIFEST_NAME


def read_manifest() -> list[dict[str, str]]:
    """The files we wrote: [{"target", "path", "sha256"}]. A missing or damaged manifest means none."""
    try:
        data = json.loads(_manifest_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for e in data.get("files", []) if isinstance(data, dict) else []:
        if isinstance(e, dict) and all(isinstance(e.get(k), str) and e.get(k) for k in ("target", "path", "sha256")):
            out.append({"target": e["target"], "path": e["path"], "sha256": e["sha256"]})
    return out


def _write_manifest(entries: list[dict[str, str]]) -> None:
    target = _manifest_path()
    if not entries:
        try:
            target.unlink()
        except FileNotFoundError:
            pass
        return
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=".skills-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"version": 1, "files": entries}, fh, indent=2)
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _read_bytes(path: Path) -> bytes | None:
    try:
        if path.is_symlink() or not path.is_file():
            return None
        return path.read_bytes()
    except OSError:
        return None


def _bundled(key: str) -> bytes | None:
    return _read_bytes(skills_source_dir() / TARGETS[key]["source"])


def plan(key: str) -> dict[str, Any]:
    """What installing ``key`` would do. ``state``: new (file will be created), installed (ours and current), update
    (ours, unchanged, a newer version is bundled), foreign (a file is there that we did not write: we leave it),
    unavailable (the bundled file is missing)."""
    info = TARGETS[key]
    dest: Path = info["dest"]()
    data = _bundled(key)
    entry = next((e for e in read_manifest() if e["target"] == key and e["path"] == str(dest)), None)
    out: dict[str, Any] = {"key": key, "name": info["name"], "dest": str(dest), "text": "", "state": "unavailable",
                           "size": 0, "detail": "", "ours": False}
    if data is None:
        out["detail"] = "The skill file is missing from this copy of the app."
        return out
    out["text"] = data.decode("utf-8", "replace")
    out["size"] = len(data)
    parent_link = dest.parent.is_symlink()
    if not os.path.lexists(dest):
        out["state"] = "foreign" if parent_link else "new"
        out["detail"] = ("The folder is a shortcut, so we leave it alone." if parent_link else "This file will be created.")
        return out
    current = _read_bytes(dest)
    if entry and current is not None and _sha(current) == entry["sha256"] and not parent_link:
        out["ours"] = True
        out["state"] = "installed" if _sha(data) == entry["sha256"] else "update"
        out["detail"] = ("Installed." if out["state"] == "installed" else "Installed. A newer version is bundled and can replace it.")
        return out
    out["state"] = "foreign"
    out["detail"] = ("A file is already there that Property Helper did not write (or it was changed since), so it was left alone. "
                     "Rename or delete it, then install again, if you want this one.")
    return out


def install(key: str) -> str:
    """Write the skill file for ``key``. Returns a one-line message; raises ValueError with a plain message when it
    can't. Never overwrites a file we did not write."""
    if key not in TARGETS:
        raise ValueError("That isn't an app we have a skill for.")
    p = plan(key)
    if p["state"] == "unavailable":
        raise ValueError(p["detail"])
    if p["state"] == "foreign":
        raise ValueError(f"There is already a file at {p['dest']} that Property Helper didn't write, so nothing was changed. "
                         "Rename or delete it, then install again, if you want this skill installed.")
    if p["state"] == "installed":
        return f"The {p['name']} skill is already installed."
    dest = Path(p["dest"])
    data = _bundled(key)
    assert data is not None
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if p["state"] == "new":
            with open(dest, "xb") as fh:  # exclusive: never replaces something that appeared since we looked
                fh.write(data)
        else:
            fd, tmp = tempfile.mkstemp(dir=str(dest.parent), prefix=".skill-", suffix=".tmp")
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            os.replace(tmp, dest)
    except FileExistsError:
        raise ValueError(f"A file appeared at {dest} just now, so nothing was changed.") from None
    except OSError as exc:
        raise ValueError(f"Couldn't write {dest} ({exc.strerror or 'file error'}). Nothing was changed.") from None
    entries = [e for e in read_manifest() if not (e["target"] == key and e["path"] == str(dest))]
    entries.append({"target": key, "path": str(dest), "sha256": _sha(data)})
    _write_manifest(entries)
    return f"Installed the {p['name']} skill at {dest}."


def _ours_to_remove(entry: dict[str, str]) -> bool:
    """Only a skill file with our name, in a skills folder, and exactly as we wrote it."""
    p = Path(entry["path"])
    if p.name != "SKILL.md" or p.parent.name != SKILL_NAME or p.parent.parent.name != "skills":
        return False
    data = _read_bytes(p)
    return data is not None and _sha(data) == entry["sha256"] and not p.parent.is_symlink()


def uninstall(key: str) -> str:
    """Remove the files the manifest lists for ``key`` that still match what we wrote. Leaves anything else."""
    if key not in TARGETS:
        raise ValueError("That isn't an app we have a skill for.")
    name = TARGETS[key]["name"]
    entries = read_manifest()
    mine = [e for e in entries if e["target"] == key]
    if not mine:
        return f"The {name} skill wasn't installed by this app, so there is nothing to remove."
    keep = [e for e in entries if e["target"] != key]
    removed, left = [], []
    for e in mine:
        p = Path(e["path"])
        if not os.path.lexists(p):
            continue  # already gone
        if _ours_to_remove(e):
            try:
                p.unlink()
                removed.append(str(p))
                try:
                    p.parent.rmdir()  # only if now empty: never someone else's files
                except OSError:
                    pass
            except OSError:
                left.append(str(p))
                keep.append(e)
        else:
            left.append(str(p))  # changed or replaced since: not ours any more, so we don't touch it
    _write_manifest(keep)
    if left:
        return (f"Removed {len(removed)} file(s). Left {', '.join(left)} alone because it was changed after Property Helper wrote it "
                "or couldn't be removed.")
    return f"Removed the {name} skill." if removed else f"The {name} skill file was already gone."


# --------------------------------------------------------------------------- the Skills page
def _si():
    from . import skills_install  # imported late: skills_install builds on this module

    return skills_install


@router.get("/skills", include_in_schema=False)
def skills_page(request: Request):
    return render(request, "skills.html", plans=[plan(k) for k in TARGETS], **_si().page_context())


def _chosen(targets: list[str]) -> list[str] | None:
    """The ticked apps (only known ones), or None for "every app found"."""
    picked = [t for t in targets if t in TARGETS]
    return picked or None


@router.post("/skills/all/preview", include_in_schema=False)
def skills_all_preview(request: Request, targets: list[str] = Form(default=[])):
    si = _si()
    chosen = _chosen(targets)
    return render(request, "_skills_preview.html", preview=si.plan_all(chosen), anyway=chosen is not None,
                  **si.page_context())


@router.post("/skills/all/install", include_in_schema=False)
def skills_all_install(request: Request, targets: list[str] = Form(default=[])):
    si = _si()
    chosen = _chosen(targets)
    result = si.install_all(chosen if chosen is not None else si.detected_targets())
    if not is_htmx(request):
        done = [r["message"] for r in result["results"]]
        return redirect("/connect#skills-panel", notice=" ".join(done) or "No AI app was found, so nothing was installed.")
    return render(request, "_skills_installed.html", result=result, **si.page_context())


@router.post("/skills/add", include_in_schema=False)
def skills_add(request: Request):
    """One press: skills into every app found here, the Claude plugin saved and shown, Claude opened. POST only."""
    si = _si()
    try:
        result = si.add_everywhere()
    except Exception as exc:  # never a 500 or a traceback in the window
        from . import integrations

        integrations.log_failure(exc)
        return render(request, "_skills_add_result.html", error=integrations.friendly_error(exc), r=None,
                      **si.page_context())
    if not is_htmx(request):
        return redirect("/connect#skills-panel", notice=result["line"])
    return render(request, "_skills_add_result.html", r=result, error="", **si.page_context())


@router.post("/skills/plugin/save", include_in_schema=False)
def skills_plugin_save(request: Request):
    si = _si()
    try:
        path = si.write_plugin()
    except OSError as exc:
        return render(request, "_skills_plugin_result.html", saved=None, shown=False, error=exc.strerror or "file error",
                      **si.page_context())
    shown = si.reveal(path)
    return render(request, "_skills_plugin_result.html", saved=str(path), shown=shown, error="", **si.page_context())


@router.get("/skills/property-helper.plugin", include_in_schema=False)
def skills_plugin_download():
    si = _si()
    return Response(si.build_plugin(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{si.PLUGIN_FILE}"'})


@router.post("/skills/claude-app/open", include_in_schema=False)
def skills_open_claude(request: Request):
    ok = _si().open_claude_app()
    text = ("Opening Claude. If it was already open, it is in front now." if ok else
            "We couldn't start the Claude app from here. Open it yourself from your Applications or Start menu.")
    return Response(f'<span class="fine" role="status">{text}</span>', media_type="text/html")


@router.post("/skills/install", include_in_schema=False)
def skills_install(request: Request, target: str = Form("")):
    if target not in TARGETS:
        raise HTTPException(404, "That isn't an app we have a skill for.")
    try:
        return redirect("/skills", notice=install(target))
    except ValueError as exc:
        return redirect("/skills", error=str(exc))


@router.post("/skills/uninstall", include_in_schema=False)
def skills_uninstall(request: Request, target: str = Form("")):
    if target not in TARGETS:
        raise HTTPException(404, "That isn't an app we have a skill for.")
    try:
        return redirect("/skills", notice=uninstall(target))
    except ValueError as exc:
        return redirect("/skills", error=str(exc))
