"""Entry point.

Double-clicking the app runs with no arguments: start the local server and open
the browser. AI apps launch it with `mcp` to talk over stdio.
"""
from __future__ import annotations

import argparse
import hmac
import logging
import os
import secrets
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

import httpx

from .paths import DEFAULT_PORT, app_key, data_dir, db_path, health_proof, is_frozen, launch_url, port_file


def _private(path: Path) -> Path:
    """Create the file readable by this user only (0600), and tighten an existing one. Not on Windows."""
    if os.name != "nt":
        try:
            os.close(os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600))
            os.chmod(path, 0o600)
        except OSError:
            pass
    return path


def _write_port_file(port: int) -> None:
    try:  # so the AI app's "Open in Property Helper" links point at the right port
        _private(port_file()).write_text(str(port))
    except OSError:
        pass


def _quiet(flag: bool = False) -> bool:
    """Plain console lines only (the start files pass PROPHELPER_QUIET=1). Logs still go to app.log."""
    return bool(flag or os.environ.get("PROPHELPER_QUIET"))


def _tell(quiet: bool, text: str) -> None:
    """One plain line for the person at the start window (only when quiet; otherwise the log says it)."""
    if quiet and sys.stdout is not None:
        print(text, flush=True)


def _setup_logging(to_stderr: bool) -> None:
    handlers: list[logging.Handler] = [logging.FileHandler(_private(data_dir() / "app.log"), encoding="utf-8")]
    if to_stderr and sys.stderr is not None:
        handlers.append(logging.StreamHandler(sys.stderr))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=handlers)


def _probe(port: int) -> str:
    """Who answers on this port: "ours" (this install's app, proven with an HMAC of a fresh nonce under the
    app key), "other" (something else is listening there) or "free"."""
    nonce = secrets.token_urlsafe(24)
    try:
        r = httpx.get(f"http://127.0.0.1:{port}/api/health", params={"nonce": nonce}, timeout=0.5)
        body = r.json()
    except (httpx.HTTPError, ValueError):
        return "free" if _port_free(port) else "other"
    proof = body.get("proof") if isinstance(body, dict) else None
    # Bound to the port dialed here: a program on this port that passes the nonce on to the real app
    # elsewhere gets back a proof for the real app's port, which doesn't match.
    if r.status_code == 200 and isinstance(proof, str) and hmac.compare_digest(proof, health_proof(app_key(), nonce, port)):
        return "ours"
    return "other"


def _already_running(port: int) -> bool:
    """This install's app answers on the port. Only then does a launcher send it a launch code."""
    return _probe(port) == "ours"


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def _pick_port(preferred: int) -> int:
    if _port_free(preferred):
        return preferred
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _recorded_port() -> int | None:
    try:
        return int(port_file().read_text().strip())
    except (OSError, ValueError):
        return None


PORT_GRACE = 30  # seconds a just-written port file is trusted while its app is still starting


def _forget_port(port: int) -> None:
    """The recorded port didn't answer as this app (a killed run, or another program there now): drop it, so
    the AI app's links stop pointing at it. A file written in the last few seconds stays (that app may still
    be starting)."""
    path = port_file()
    try:
        if _recorded_port() == port and time.time() - path.stat().st_mtime > PORT_GRACE:
            path.unlink()
    except OSError:
        pass


def _find_running(*ports: int) -> int | None:
    """The port this install's app answers on: the recorded one first, then these. A recorded port that
    doesn't answer as ours isn't trusted: it's rewritten when the app is found elsewhere, else dropped."""
    recorded = _recorded_port()
    for port in dict.fromkeys(p for p in (recorded, *ports) if p):
        if _already_running(port):
            if port != recorded:
                _write_port_file(port)
            return port
    if recorded:
        _forget_port(recorded)
    return None


def open_window() -> bool:
    """Open (and unlock) the app window of the running app. False when it isn't running. Prints what happened."""
    port = _find_running(DEFAULT_PORT)
    if port is None:
        return False
    url = launch_url(port)  # a one-time code, never the key itself
    try:
        opened = bool(webbrowser.open(url))
    except Exception:
        opened = False
    if opened:
        print(f"Opened http://127.0.0.1:{port}")
    else:
        print(f"I couldn't start a browser. Open this address by hand within a minute (it works once):\n{url}")
    return True


def run_app(port: int = DEFAULT_PORT, open_browser: bool = True, quiet: bool = False) -> None:
    import uvicorn

    from .store import Store
    from .web import create_app

    say = logging.getLogger(__name__)
    quiet = _quiet(quiet)
    running = _find_running(port, DEFAULT_PORT)  # the recorded port first: the app may be on another one
    if running is not None:
        port = running
        # Second double-click: just bring the window back.
        opened = True
        if open_browser:
            fresh = launch_url(port)  # a new one-time code each double-click
            try:
                opened = bool(webbrowser.open(fresh))
            except Exception:
                opened = False
            if not opened and quiet:  # no browser could start: the one place a fresh link is printed, single use
                _tell(quiet, f"I couldn't start a browser. Open this address by hand within a minute (it works once):\n{fresh}")
        say.info("Property Helper is already running at http://127.0.0.1:%s/, so this copy didn't start another. %s",
                 port, "Opened its window." if open_browser else "Run prophelper open to open its window.")
        # No address is printed: the plain address only leads to the locked page, and a launch link in a console
        # (scrollback, screenshots) would be a sign-in lying around. Double-clicking again always makes a fresh one.
        _tell(quiet, "Property Helper is already running. I opened its window again. If it didn't open, "
                     "double-click Start Property Helper once more.")
        return
    wanted = port
    port = _pick_port(port)
    if port != wanted:
        say.warning("Port %s is in use by another program that isn't this Property Helper, so no launch code was sent "
                    "to it. Starting on port %s instead.", wanted, port)
    app = create_app(Store(db_path()))
    try:  # packaged app only: an AI app's entry that points at a moved copy is pointed at this one
        from . import integrations

        for fixed in integrations.repair_if_packaged():
            say.info("Pointed %s at this copy of Property Helper.", fixed)
    except Exception:  # starting the app must never fail because of this
        pass
    _write_port_file(port)
    url = f"http://127.0.0.1:{port}/"
    if open_browser:
        threading.Timer(1.2, lambda: webbrowser.open(launch_url(port))).start()
    logging.getLogger(__name__).info("Property Helper running at %s (data: %s)", url, data_dir())
    logging.getLogger(__name__).info("If the window says it's locked, double-click Start Property Helper again "
                                     "(or run: prophelper open)")
    _tell(quiet, "Property Helper is running. Your browser will open in a moment. Keep this window open while you use it. Close it to stop.")
    _tell(quiet, "If it doesn't open, double-click Start Property Helper again (it opens a fresh, unlocked window).")
    _tell(quiet, f"Your places are kept in: {data_dir()}")
    if quiet:  # no uvicorn lines on the console; the log file still has them
        logging.getLogger("uvicorn").handlers.clear()
    # log_config=None: the frozen windowed build has no console for uvicorn's default handlers.
    try:
        uvicorn.run(app, host="127.0.0.1", port=port, log_config=None, access_log=False)
    finally:  # stopped: the port file no longer says where the app is (a killed run is caught on the next start)
        if _recorded_port() == port:
            try:
                port_file().unlink()
            except OSError:
                pass


def _install_skills(args: argparse.Namespace) -> None:
    """Add the skills to every AI app found here (or the ones named), after listing the files and asking."""
    from . import skills_install as si

    picked = [t for t, on in (("claude", args.claude), ("codex", args.codex)) if on]
    plugin = args.plugin
    if picked:
        targets = picked  # named on purpose: installs even when the app wasn't found
    elif plugin is not None:
        targets = []  # only the plugin file was asked for
    else:
        targets = si.detected_targets()
    if plugin is None and not targets:
        print("We didn't find Claude Code or Codex on this computer, so nothing was installed.\n"
              "Use --claude or --codex to install anyway, or --plugin to get the file for the Claude app.")
        return
    plan = si.plan_all(targets)
    for p in plan["plans"]:
        print(f"{p['name']}: {p['label']}  {p['shown']}" + (f"  ({p['reason']})" if p["reason"] else ""))
    if plan["plans"]:
        c = plan["counts"]
        print(f"{c['new']} new, {c['updated']} updated, {c['unchanged']} unchanged, {c['kept']} kept as they are. "
              "A file you edited, or one we didn't write, is never replaced.")
    if plan["plans"] and plan["writes"] and not args.yes:
        interactive = sys.stdin is not None and sys.stdin.isatty()
        if not interactive:  # an agent or a script has no one to ask: say nothing happened, and how to say yes
            print("Nothing installed yet, because there is no one to ask. Run again with --yes to install.")
            sys.exit(1)
        if input("Install these? Type yes to go ahead: ").strip().lower() not in ("y", "yes"):
            sys.exit("Nothing installed.")
    if plan["plans"]:
        result = si.install_all(targets)
        for r in result["results"]:
            print(f"{r['name']}: {r['label']}. {r['message']}")
        if result["written"]:
            print("Start a new chat (or restart Claude Code or Codex) so it picks up the skills.")
    if plugin is not None:
        path = si.write_plugin(Path(plugin) if plugin else None)
        print(f"Wrote {path}. In the Claude app: Customize > Plugins > Add > Upload plugin, then pick that file.")
        print("The plugin adds skills only. The Claude app still needs the connection: run prophelper connect-claude.")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="prophelper", description="Property Helper")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("app", help="start the app and open it in your browser (default)")
    serve = sub.add_parser("serve", help="start the web server and open the app window")
    serve.add_argument("--port", type=int, default=DEFAULT_PORT)
    serve.add_argument("--no-browser", action="store_true", help="don't open the window (run prophelper open later)")
    serve.add_argument("--quiet", action="store_true", help="print plain lines only (logs still go to app.log)")
    parser.add_argument("--quiet", action="store_true", help="print plain lines only (logs still go to app.log)")
    sub.add_parser("open", help="open the window of the running app (unlocks it in this browser)")
    sub.add_parser("mcp", help="run the MCP server over stdio (AI apps start this)")
    sub.add_parser("sample-data", help="load a made-up search with places to try the app")
    sub.add_parser("connect-claude", help="add Property Helper to Claude Desktop")
    sub.add_parser("connect-codex", help="add Property Helper to Codex")
    sub.add_parser("connect-lmstudio", help="add Property Helper to LM Studio")
    sub.add_parser("check-claude", help="check that Claude Desktop can start Property Helper")
    inst = sub.add_parser("install-skills", help="add the skills to every AI app found here (lists the files first), "
                                                 "or write the Claude plugin file")
    inst.add_argument("--claude", action="store_true", help="install for Claude Code (~/.claude/skills), even if not found")
    inst.add_argument("--codex", action="store_true", help="install for Codex (~/.codex/skills), even if not found")
    inst.add_argument("--yes", action="store_true", help="don't ask first (needed when no one can be asked)")
    inst.add_argument("--plugin", nargs="?", const="", default=None, metavar="PATH",
                      help="write property-helper.plugin for the Claude app (default: your Downloads folder)")
    backup = sub.add_parser("backup", help="write a copy of your data to a file")
    backup.add_argument("file", nargs="?", help="where to write it (default: your data folder's backups)")
    args = parser.parse_args(argv)
    cmd = args.cmd or "app"

    # stdout belongs to the MCP protocol; never log there.
    quiet = _quiet(getattr(args, "quiet", False)) and cmd in ("app", "serve")
    _setup_logging(to_stderr=(cmd != "app" or not is_frozen()) and not quiet)

    if cmd == "mcp":
        try:
            from .mcp_server import run_stdio
        except ImportError:
            sys.exit("The AI connection (MCP server) could not start, so there is nothing for an AI app to use. "
                     "Property Helper needs its 'mcp' package for it; reinstall the app. "
                     "The app itself works without it: run prophelper serve.")
        from .store import Store

        run_stdio(Store(db_path()))
    elif cmd == "app":
        run_app(quiet=quiet)
    elif cmd == "serve":
        run_app(port=args.port, open_browser=not args.no_browser, quiet=quiet)
    elif cmd == "open":
        if not open_window():
            sys.exit("Property Helper isn't running. Double-click Start Property Helper, or run: prophelper serve")
    elif cmd == "sample-data":
        from .sample_data import load_sample_data
        from .store import Store

        print(f"Added {load_sample_data(Store(db_path()))} sample places.")
    elif cmd == "install-skills":
        _install_skills(args)
    elif cmd == "backup":
        from .store import Store

        store = Store(db_path())
        target = Path(args.file) if args.file else data_dir() / "backups" / "property-helper-backup.db"
        target.parent.mkdir(parents=True, exist_ok=True)
        store.backup_to(target)
        print(f"Wrote a backup copy to {target}")
    elif cmd in ("connect-claude", "connect-codex", "connect-lmstudio"):
        from . import integrations

        fn = {"connect-claude": integrations.connect_claude, "connect-codex": integrations.connect_codex,
              "connect-lmstudio": integrations.connect_lmstudio}[cmd]
        try:
            result = fn()
        except Exception as exc:
            integrations.log_failure(exc)
            sys.exit(integrations.friendly_error(exc))
        if not result.get("installed", True):
            sys.exit(result["message"])
        if result.get("ok") is False:
            sys.exit(result["problem"])
        if result.get("already_connected"):
            print(f"Already set up. Property Helper's entry in {result['path']} is correct, so nothing was rewritten.")
        else:
            print(f"Updated {result['path']}.")
        print("Read it back and it matches what we meant to write.")
        target = cmd.removeprefix("connect-")
        if target == "claude":
            print(integrations.REOPEN_LINE)
        print(result.get("next_step") or "Restart the app to load Property Helper.")
        if result.get("running"):
            print("Claude Desktop is open right now, so it won't see the change until you quit it completely.")
        if result.get("quarantine"):
            print(result["quarantine"])
        if target in ("claude", "lmstudio") and result.get("entry"):
            try:
                test = integrations.check_launch(result["entry"], timeout=45)
            except Exception as exc:
                integrations.log_failure(exc)
                sys.exit(integrations.friendly_error(exc))
            print(integrations.result_line(test))
            if test["ok"]:
                if target == "claude":
                    print(integrations.HEALTHY_LINE)
            else:
                for line in test["stderr_tail"][-5:]:
                    print(f"  {line}")
                sys.exit(1)
    elif cmd == "check-claude":
        from . import integrations

        try:
            status = integrations.claude_status()
            test = integrations.check_launch(status["entry"]) if status["entry"] else None
            text = integrations.claude_report(status, test)
            ok = status["connected"] and bool(test and test["ok"])
        except Exception as exc:
            integrations.log_failure(exc)
            sys.exit(integrations.friendly_error(exc))
        if sys.stdout is None:  # a windowed Windows app has no console to print to
            (data_dir() / "connect-report.txt").write_text(text + "\n", encoding="utf-8")
        else:
            print(text)
            if not status["entry"]:
                print("Run: prophelper connect-claude")
        sys.exit(0 if ok else 1)
