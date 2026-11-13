"""What every router needs, so routers never import ``web.py``.

    from fastapi import APIRouter, Request
    from .deps import get_store, render, redirect

    router = APIRouter()

    @router.get("/example")
    def example(request: Request):
        store = get_store(request)
        return render(request, "example.html", search=store.current_search())

* ``get_store(request)``: the app's :class:`~prophelper.store.Store`. Works as a plain call or as a FastAPI dependency.
* ``render(request, "page.html", **ctx)``: an HTML response from ``templates/``. Jinja autoescape is on, so user
  and AI text is always escaped. ``request`` is added to the context for you.
* ``redirect(url, notice="", error="")``: a 303 redirect that can carry a one-line message, shown once by
  ``base.html`` (the message travels in a short-lived signed cookie, never the address).
* ``back(request, default, notice, error)``: redirect to the page the form was on (same server only).
* ``is_htmx(request)``: True for HTMX requests (return a fragment instead of a whole page).
* ``make_templates(store)``: builds the Jinja environment (used by ``create_app`` only).

Template filters: ``local`` (Fri Nov 6, 2:30 PM), ``clock`` (2:30 PM), ``day`` (Fri Nov 6), ``date`` (2026-11-06),
``ago`` (3 days ago), ``until`` (in 3 days), ``money`` ($1,450), ``num`` (1,234), ``stage_slug``, ``beds``, ``host``.
Globals: ``STAGES_BY_MODE``, ``stages_for(mode)``, ``CLOSED_STAGES``, ``WON_STAGES``, ``CONTACT_ROLES``,
``EVENT_KINDS``, ``DOCUMENT_KINDS``, ``DRAFT_KINDS``, ``COMMUTE_MODES``, ``CRITERION_KINDS``, ``KIND_LABELS``,
``version``, ``today()``, ``has_sample()``, ``setting(key)``, ``current_search()``, ``searches()``.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import __version__, helpers, stages
from .paths import resource_dir
from .scoring import KIND_LABELS
from .store import (COMMUTE_MODES, CONTACT_LOG_KINDS, CONTACT_ROLES, CRITERION_KINDS, DOCUMENT_KINDS, DRAFT_KINDS,
                    EVENT_KINDS, Store)

ONE_SHOT_PARAMS = {"notice", "flash_error", "error"}  # messages, not page state


def get_store(request: Request) -> Store:
    """The app's Store (also usable as a FastAPI dependency)."""
    return request.app.state.store


def make_templates(store: Store) -> Jinja2Templates:
    """The Jinja environment: autoescape on for every .html template, plus the shared filters and globals."""
    env = Environment(loader=FileSystemLoader(str(resource_dir() / "templates")),
                      autoescape=select_autoescape(["html", "xml"], default_for_string=True), trim_blocks=False)
    env.filters.update({
        "local": helpers.local_time, "clock": helpers.clock_text, "day": helpers.day_text, "date": helpers.local_date,
        "num": helpers.number_text, "ago": helpers.ago, "until": helpers.until, "money": helpers.money,
        "stage_slug": helpers.stage_slug, "beds": helpers.beds_text, "host": helpers.host_of,
        "dt_input": helpers.input_datetime,
    })
    env.globals.update({
        "STAGES_BY_MODE": stages.STAGES_BY_MODE, "stages_for": stages.stages_for, "CLOSED_STAGES": stages.CLOSED_STAGES,
        "WON_STAGES": stages.WON_STAGES, "CONTACT_ROLES": CONTACT_ROLES, "CONTACT_LOG_KINDS": CONTACT_LOG_KINDS,
        "EVENT_KINDS": EVENT_KINDS, "DOCUMENT_KINDS": DOCUMENT_KINDS, "DRAFT_KINDS": DRAFT_KINDS,
        "COMMUTE_MODES": COMMUTE_MODES, "CRITERION_KINDS": CRITERION_KINDS, "KIND_LABELS": KIND_LABELS,
        "version": __version__, "today": lambda: helpers.today().isoformat(), "has_sample": store.has_sample_data,
        "setting": lambda key, default="": store.get_setting(key, default),
        "current_search": store.current_search, "searches": store.list_searches,
    })
    return Jinja2Templates(env=env)


def render(request: Request, name: str, status_code: int = 200, **ctx) -> HTMLResponse:
    """Render ``templates/<name>`` with ``ctx`` (``request`` is added)."""
    return request.app.state.templates.TemplateResponse(request, name, ctx, status_code=status_code)


def is_htmx(request: Request) -> bool:
    return bool(request.headers.get("HX-Request"))


def safe_local_path(path: str) -> bool:
    """A path on this server: not '//host', '/\\host' or anything a browser could read as another site."""
    return (path.startswith("/") and not path.startswith(("//", "/\\")) and "\\" not in path
            and not any(ch.isspace() or ord(ch) < 32 for ch in path))


def redirect(url: str, notice: str = "", error: str = "", status_code: int = 303) -> RedirectResponse:
    """Redirect to a path on this server, optionally with a one-line message (``notice``, or ``error`` for a
    problem). The app moves the message into a signed cookie, so it never sits in the address."""
    if not safe_local_path(url):
        url = "/"
    parts = urlsplit(url)
    params = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k not in ONE_SHOT_PARAMS]
    params += [(k, v) for k, v in (("notice", notice), ("flash_error", error)) if v]
    return RedirectResponse(parts.path + ("?" + urlencode(params) if params else ""), status_code=status_code)


def back(request: Request, default: str = "/", notice: str = "", error: str = "") -> RedirectResponse:
    """Redirect to the page the form was on (only a page of this very server), with an optional message."""
    ref = request.headers.get("referer") or ""
    host = (request.headers.get("host") or "").lower()
    try:
        target = urlsplit(ref)
        ours = target.scheme in ("http", "https") and target.netloc.lower() == host and safe_local_path(target.path)
    except ValueError:
        ours = False
    url = target.path + ("?" + target.query if target.query else "") if ours else default
    return redirect(url, notice=notice, error=error)


def slug_ok(text: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9-]+", text or ""))
