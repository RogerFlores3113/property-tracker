"""The Connect an AI app page: one button to connect Claude Desktop, Codex (and so ChatGPT desktop) or LM Studio.

``GET /connect`` shows, for each app, whether it is installed and whether Property Helper is connected.
``POST /connect/{target}`` (claude, codex, lmstudio) writes only our own ``property-helper`` entry into that app's
settings (see ``prophelper.integrations``), after saving a backup of the file, reads it back, and (Claude and LM Studio)
starts the server the way the app would and does a real MCP handshake. For Claude Desktop on Mac and Windows, when
that test passes, it then quits Claude gracefully (never forced) and opens it again so it loads the new entry. With HTMX it answers a small result
fragment; without it, it redirects back to the page with a one-line message.
``POST /connect/{target}/test`` runs only that handshake check and writes nothing.
``POST /connect/claude/report`` gives a plain-text report to paste into a bug report.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from . import integrations, skills_install
from .deps import is_htmx, redirect, render

router = APIRouter()

def _late(name: str):
    """Look the function up when it is used, so the page always follows the module (and tests can swap it)."""
    return lambda *a, **k: getattr(integrations, name)(*a, **k)


# key -> (name, what it is for, config path, is connected, connect)
TARGETS = {
    "claude": ("the Claude app", "Adds Property Helper to the Claude app on your computer. Places and boards show up right in the chat.",
               _late("claude_config_path"), _late("claude_connected"), _late("connect_claude")),
    "codex": ("Codex", "Works for the Codex app and the codex command. The ChatGPT desktop app may share its settings file, but that is not tested yet.",
              _late("codex_config_path"), _late("codex_connected"), _late("connect_codex")),
    "lmstudio": ("LM Studio", "For models that run on your own computer. Pick one that supports tools, like Qwen 3 or Llama 3.1.",
                 _late("lmstudio_config_path"), _late("lmstudio_connected"), _late("connect_lmstudio")),
}

DISCONNECT = {
    "claude": "Open the Claude app, go to Settings, then Developer, press Edit Config, delete the \"property-helper\" block and "
              "save. Quit and reopen Claude.",
    "codex": "Open Codex's config.toml and delete the [mcp_servers.property-helper] section. Restart Codex.",
    "lmstudio": "In LM Studio open the Program tab, press Install, then Edit mcp.json, and delete the \"property-helper\" "
                "block. Restart LM Studio.",
}

EXAMPLE_PROMPTS = [
    "Add this listing to Property Helper. Here is the text: [paste the listing here]",
    "What should I do today?",
    "Show me my board and tell me which places fit best.",
    "Move Maple Row to Tour booked and add a tour on Thursday at 2pm.",
    "What does Maple Row really cost per month, with all the fees?",
    "Compare my top three places side by side.",
    "Draft a message to the Maple Row leasing office asking about parking and pets.",
    "Which places are close to campus and have in-unit laundry?",
]


def _texts() -> dict:
    return {"quit_text": integrations.quit_instruction(), "look_text": integrations.claude_where_to_look(),
            "healthy_line": integrations.TESTED_LINE, "set_up_line": integrations.SET_UP_LINE,
            "restarts": integrations.restart_supported(), "open_line": integrations.CLAUDE_OPEN_LINE}


def _status() -> list[dict]:
    rows = []
    for key, (name, blurb, path_fn, connected_fn, _connect) in TARGETS.items():
        path = path_fn()
        rows.append({"key": key, "name": name, "blurb": blurb, "path": str(path), "installed": path.parent.is_dir(),
                     "connected": connected_fn(), "disconnect": DISCONNECT[key]})
    return rows


@router.get("/connect", include_in_schema=False)
def connect_page(request: Request):
    try:
        status = integrations.claude_status()
    except Exception as exc:  # the page must always open
        integrations.log_failure(exc)
        status = {"launch_problem": None, "store_version": False, "config_error": None, "entry_problems": [],
                  "entry": None}
    claude_code = {"installed": skills_install.detect("claude"), "connected": integrations.claude_code_connected(),
                   "command": integrations.claude_code_command()}
    spec = integrations.mcp_launch_spec()
    return render(request, "connect.html", apps=_status(), prompts=EXAMPLE_PROMPTS, status=status,
                  stdio_command=spec.command, stdio_args=" ".join(spec.args),
                  stdio_data_dir=spec.env.get("PROPHELPER_DATA_DIR", ""),
                  json_snippet=integrations.generic_json_snippet(), codex_snippet=integrations.codex_snippet(),
                  claude_code=claude_code, **skills_install.page_context(), **_texts())


@router.post("/connect/claude/report", include_in_schema=False)
def connect_report(request: Request):
    """Everything we know about the Claude hookup, with a fresh test, as text to paste into a bug report."""
    try:
        text = integrations.claude_report()
    except Exception as exc:
        integrations.log_failure(exc)
        text = "We couldn't put the report together: " + integrations.friendly_error(exc)
    return render(request, "_connect_report.html", report=text)


@router.post("/connect/{target}/test", include_in_schema=False)
def connect_test(request: Request, target: str):
    """Start the saved entry the way the app would and say whether it answers. Writes nothing."""
    if target not in TARGETS:
        raise HTTPException(404, "That isn't an app we can connect.")
    name = TARGETS[target][0]
    try:
        state = integrations.config_state(target)
        entry = integrations.entry_for(target) if state["kind"] == "found" else None
        check = None
        if entry is not None:
            check = integrations.check_launch(entry)
            check["line"] = integrations.result_line(check)
        problems = integrations.check_entry(entry) if entry else []
        path = str(TARGETS[target][2]())
    except Exception as exc:  # never a 500 or a traceback in the window
        integrations.log_failure(exc)
        return render(request, "_connect_result.html", ok=False, app_name=name, app_key=target, result={},
                      error=integrations.friendly_error(exc), check=None, **_texts())
    return render(request, "_connect_test.html", app_name=name, app_key=target, entry=entry, check=check,
                  problems=problems, path=path, state=state, **_texts())


@router.post("/connect/{target}", include_in_schema=False)
def connect(request: Request, target: str):
    if target not in TARGETS:
        raise HTTPException(404, "That isn't an app we can connect.")
    name, _blurb, _path, _connected, fn = TARGETS[target]
    check = None
    restart = None
    try:
        result = fn()
        ok, error = True, ""
        if result.get("ok") and target in ("claude", "lmstudio", "codex") and result.get("entry"):
            check = integrations.check_launch(result["entry"], timeout=45)
            check["line"] = integrations.result_line(check)
        if (target == "claude" and check and check["ok"] and result.get("installed", True)
                and result.get("ok") is not False and not result.get("already_connected")
                and integrations.restart_supported()):
            restart = integrations.restart_claude()  # one click: quit Claude if open (never forced), open it again
    except Exception as exc:  # never a 500 or a traceback in the window
        integrations.log_failure(exc)
        result, ok, error = {}, False, integrations.friendly_error(exc)
        detail = getattr(exc, "detail", "")
    else:
        detail = ""
    if is_htmx(request):
        return render(request, "_connect_result.html", ok=ok, app_name=name, app_key=target, result=result, error=error,
                      detail=detail, check=check, restart=restart, **_texts())
    if not ok:
        return redirect("/connect", error=error)
    if result.get("ok") is False:
        return redirect("/connect", error=result["problem"])
    if check is not None and not check["ok"]:
        return redirect("/connect", error=f"Added to {name}'s settings, but the test failed. {check['line']}")
    if result.get("installed") is False:
        if target == "claude":
            return redirect("/connect", error="We don't see the Claude app on this computer. Get the Claude app "
                                              "at claude.ai/download, then come back and press Connect.")
        return redirect("/connect", error=result["message"])
    if restart is not None:
        return redirect("/connect", notice=restart["message"])
    return redirect("/connect", notice=f"Connected to {name}. {result.get('next_step', '')}".strip())
