"""One-click skills for every AI app on this computer, and the one plugin file for the Claude app.

A skill is a short instruction file an AI app reads to use Property Helper well. Where each app looks:

  Claude Code   ~/.claude/skills/property-helper/SKILL.md
  Codex         ~/.codex/skills/property-helper/SKILL.md   ($CODEX_HOME/skills when that is set)
  The Claude app (desktop and claude.ai) has no skills folder on disk. It takes a plugin: one .plugin file (a zip
  holding .claude-plugin/plugin.json and skills/<name>/SKILL.md), added under Customize > Plugins > Add > Upload
  plugin. ``build_plugin`` makes that file. The repository carries the same plugin and a marketplace file in its
  .claude-plugin/ folder, so ``claude plugin marketplace add rogerflores3113/property-helper`` works for people with
  access to the repository.

The safety rules live in ``routes_skills`` (the manifest of what we wrote): a file we did not write, or one the user
edited since we wrote it, is never replaced. This module adds the combined view on top: one preview of every file
(new, updated, unchanged or kept), detection of the apps that are here, and the plugin file.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

from . import helpers, paths, routes_skills

REPO = "rogerflores3113/property-helper"
PLUGIN_NAME = "property-helper"
PLUGIN_FILE = "property-helper.plugin"
MARKETPLACE_NAME = "property-helper"
PLUGIN_DESCRIPTION = ("Skills that teach your AI app to use Property Helper well: saving places from listings, moving stages, "
                      "tours, true monthly cost, comparing places and what to do today.")
PLUGIN_MANIFEST: dict[str, Any] = {
    "name": PLUGIN_NAME,
    "description": PLUGIN_DESCRIPTION,
    "author": {"name": "Property Helper"},
    "homepage": f"https://github.com/{REPO}",
    "keywords": ["apartments", "housing", "property-helper"],
}
TARGETS = ("claude", "codex")  # the keys routes_skills uses
LABELS = {"claude": "Claude Code", "codex": "Codex"}
CLAUDE_CODE_SLASH_COMMANDS = (f"/plugin marketplace add {REPO}", f"/plugin install {PLUGIN_NAME}@{MARKETPLACE_NAME}")
PLUGIN_STEPS = (
    "Open the Claude app.",
    "Go to Customize, then Plugins, then Add, then Upload plugin.",
    f"Pick {PLUGIN_FILE}.",
)
_STATE_LABEL = {"new": "new", "update": "updated", "installed": "unchanged", "foreign": "kept", "unavailable": "unavailable"}
_ZIP_TIME = (2020, 1, 1, 0, 0, 0)


def _display(path: str | Path) -> str:
    """A path with the home folder written as ~, the way people expect to read it."""
    p = Path(path)
    try:
        return "~/" + p.relative_to(Path.home()).as_posix()
    except ValueError:
        return str(p)


# ------------------------------------------------------------------ which apps are here
def detect(target: str) -> bool:
    """Is that app on this computer? Its settings folder exists or its command is on the PATH."""
    if target == "claude":
        folder = Path.home() / ".claude"
    elif target == "codex":
        home = os.environ.get("CODEX_HOME")
        folder = Path(home) if home else Path.home() / ".codex"
    else:
        raise ValueError(f"Unknown target: {target}")
    if folder.is_dir():
        return True
    return shutil.which("claude" if target == "claude" else "codex") is not None


def detected_targets() -> list[str]:
    return [t for t in TARGETS if detect(t)]


# ------------------------------------------------------------------ plan and install
def plan_target(key: str) -> dict[str, Any]:
    """One app: the file, what installing would do to it (new, updated, unchanged or kept) and why."""
    p = routes_skills.plan(key)
    label = _STATE_LABEL[p["state"]]
    reason = ""
    if p["state"] == "foreign":
        mine = any(e["target"] == key and e["path"] == p["dest"] for e in routes_skills.read_manifest())
        reason = ("edited by you, so it was kept. To get the new version, rename or delete that file, then install again" if mine
                  else "not made by Property Helper, so it was kept. To install ours, rename or delete that file, then install again")
    elif p["state"] == "unavailable":
        reason = p["detail"]
    return {"key": key, "name": LABELS[key], "dest": p["dest"], "shown": _display(p["dest"]), "label": label,
            "reason": reason, "size": p["size"], "state": p["state"]}


def plan_all(targets: list[str] | None = None) -> dict[str, Any]:
    """One combined preview of the files. ``targets`` None means every app found on this computer."""
    chosen = [t for t in TARGETS if t in (targets if targets is not None else detected_targets())]
    plans = [plan_target(t) for t in chosen]
    counts = {k: sum(1 for p in plans if p["label"] == k) for k in ("new", "updated", "unchanged", "kept")}
    return {"targets": chosen, "plans": plans, "counts": counts,
            "missing": [{"target": t, "label": LABELS[t]} for t in TARGETS if not detect(t)],
            "found": [{"target": t, "label": LABELS[t]} for t in TARGETS if detect(t)],
            "writes": any(p["label"] in ("new", "updated") for p in plans),
            "kept": [p for p in plans if p["label"] == "kept"]}


def install_all(targets: list[str]) -> dict[str, Any]:
    """Install into each app. A file that is not ours, or that the user edited, is kept and said so."""
    chosen = [t for t in TARGETS if t in targets]
    results = []
    for t in chosen:
        before = plan_target(t)
        if before["label"] in ("kept", "unavailable"):
            results.append({**before, "ok": False, "message": before["reason"] or "Nothing was changed."})
            continue
        try:
            msg = routes_skills.install(t)
            results.append({**before, "ok": True, "message": msg})
        except ValueError as exc:  # nothing changed
            results.append({**before, "label": "kept", "ok": False, "message": str(exc)})
    return {"targets": chosen, "results": results,
            "written": [r["dest"] for r in results if r["ok"] and r["label"] in ("new", "updated")]}


# ------------------------------------------------------------------ the Claude app plugin
def _skill_files() -> list[tuple[str, bytes]]:
    """(path inside the plugin, bytes) for each bundled Claude skill."""
    root = routes_skills.skills_source_dir() / "claude"
    out = []
    if root.is_dir():
        for skill in sorted(p for p in root.iterdir() if p.is_dir()):
            for f in sorted(p for p in skill.rglob("*") if p.is_file()):
                out.append((f"skills/{skill.name}/{f.relative_to(skill).as_posix()}", f.read_bytes()))
    return out


def _zip_add(z: zipfile.ZipFile, name: str, data: bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    z.writestr(info, data)


def build_plugin() -> bytes:
    """The Claude app plugin: one zip with .claude-plugin/plugin.json and skills/<name>/... The same bytes every time."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        _zip_add(z, ".claude-plugin/plugin.json", (json.dumps(PLUGIN_MANIFEST, indent=2) + "\n").encode("utf-8"))
        for name, data in _skill_files():
            _zip_add(z, name, data)
    return buf.getvalue()


def downloads_dir() -> Path:
    """The person's Downloads folder. PROPHELPER_DOWNLOADS_DIR overrides it. Falls back to the app's data folder."""
    override = paths.downloads_override()
    if override:
        return override
    try:
        from platformdirs import user_downloads_dir

        d = Path(user_downloads_dir())
        if d.is_dir():
            return d
    except Exception:
        pass
    return paths.data_dir()


def write_plugin(path: Path | str | None = None) -> Path:
    """Write the plugin file. With no path, into Downloads. A folder path gets the file name."""
    target = Path(path) if path else downloads_dir() / PLUGIN_FILE
    if target.is_dir():
        target = target / PLUGIN_FILE
    return helpers.write_new_file(target, build_plugin())  # never over a file that is already there


def reveal(path: Path, platform: str | None = None) -> bool:
    """Show the file in the system file manager. Best effort: never raises, False when it could not."""
    platform = platform or sys.platform
    try:
        if platform == "darwin":
            cmd = ["open", "-R", str(path)]
        elif platform == "win32":
            cmd = ["explorer", f"/select,{path}"]
        else:
            cmd = ["xdg-open", str(Path(path).parent)]
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def claude_app_command(platform: str | None = None, env: dict[str, str] | None = None) -> list[str] | None:
    """How to start the Claude desktop app, or None when it isn't found (Linux has none)."""
    platform = platform or sys.platform
    env = os.environ if env is None else env
    if platform == "darwin":
        for base in (Path("/Applications"), Path.home() / "Applications"):
            if (base / "Claude.app").is_dir():
                return ["open", "-a", "Claude"]
    elif platform == "win32":
        local = env.get("LOCALAPPDATA")
        if local:
            for exe in (Path(local) / "AnthropicClaude" / "Claude.exe", Path(local) / "Programs" / "Claude" / "Claude.exe"):
                if exe.is_file():
                    return [str(exe)]
    return None


def open_claude_app() -> bool:
    cmd = claude_app_command()
    if not cmd:
        return False
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def add_everywhere(*, reveal_fn=None, open_fn=None, platform: str | None = None) -> dict[str, Any]:
    """The one-press "Add skills": install into every app found here (only files we made; a file the person edited
    or did not make is kept), save property-helper.plugin to Downloads, show it, and open the Claude app.
    ``reveal_fn`` and ``open_fn`` are injectable so tests start nothing. On a repeat press (everything current and
    the plugin file already in place) nothing is opened or shown again. Returns the per-app results and ``line``,
    the one sentence to show."""
    platform = platform or sys.platform
    reveal_fn = reveal_fn or reveal
    open_fn = open_fn or open_claude_app
    found = detected_targets()
    done = install_all(found)
    apps = []
    for r in done["results"]:
        state = "kept" if r["label"] == "kept" else ("current" if r["label"] == "unchanged" else "added")
        apps.append({"target": r["key"], "label": LABELS[r["key"]], "state": state, "dest": r["shown"],
                     "message": r["message"], "ok": r["ok"]})
    path = downloads_dir() / PLUGIN_FILE
    try:
        repeat = path.is_file() and path.read_bytes() == build_plugin()
    except OSError:
        repeat = False
    error = ""
    shown = opened = False
    can_open = claude_app_command() is not None
    if not repeat:
        try:
            path = write_plugin()
            shown = bool(reveal_fn(path))
            opened = bool(open_fn()) if can_open else False
        except FileExistsError:
            error = f"A different {PLUGIN_FILE} is already in {_display(path.parent)}, so it was left alone."
        except OSError as exc:
            error = f"Couldn't save {PLUGIN_FILE} ({exc.strerror or 'file error'})."
    added = [a for a in apps if a["state"] == "added"]
    kept = [a for a in apps if a["state"] == "kept"]
    where = _display(path.parent)
    bits = []
    if added:
        bits.append("added the skills to " + " and ".join(a["label"] for a in added))
    elif apps and not kept:
        bits.append("the skills in " + " and ".join(a["label"] for a in apps) + " were already up to date")
    if kept:
        bits.append("left " + " and ".join(a["label"] for a in kept) + " alone because a file there is not ours or was edited")
    if error:
        bits.append(error.rstrip("."))
    elif repeat:
        bits.append(f"{PLUGIN_FILE} was already saved in {where}")
    else:
        bits.append(f"saved {PLUGIN_FILE} in {where} for the Claude app")
    line = bits[0][0].upper() + bits[0][1:] + ("; " + "; ".join(bits[1:]) if len(bits) > 1 else "") + "."
    return {"apps": apps, "written": done["written"], "plugin_path": str(path), "plugin_file": PLUGIN_FILE,
            "plugin_dir": _display(path.parent), "plugin_repeat": repeat, "plugin_error": error, "shown": shown,
            "opened": opened, "can_open_claude": can_open, "missing": [LABELS[t] for t in TARGETS if t not in found],
            "selected": shown and platform in ("darwin", "win32"), "line": line}


def page_context() -> dict[str, Any]:
    """What the Connect and Skills pages need for the skills panel."""
    plan = plan_all()
    return {"skill_plan": plan, "plugin_file": PLUGIN_FILE, "plugin_steps": PLUGIN_STEPS,
            "can_open_claude": claude_app_command() is not None, "marketplace_commands": CLAUDE_CODE_SLASH_COMMANDS}
