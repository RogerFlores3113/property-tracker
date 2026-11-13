"""The app window: a local web UI on 127.0.0.1 opened in the user's browser.

This module owns only the security layer (Host, Origin and app-key checks, the launch-code unlock, response
headers, one-line flash messages), the shared Jinja environment and ``/api/health``. Every page lives in a router
module (``routes_pages``, ``routes_connect``, ``routes_ai``, ``routes_data``) that gets the store and templates
through ``deps.py``, so routers never import this file.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import importlib
import json
import logging
import secrets
import sqlite3
import time
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__, paths
from .deps import make_templates, render
from .paths import resource_dir
from .store import Store

LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
DOWNLOADS = {"/backup", "/backup/files.zip", "/export.csv", "/export.json", "/places.csv", "/calendar.ics", "/skills/property-helper.plugin", "/compare/share.html", "/search/export.json"}  # whole-database or personal downloads: never for another site's page
DOWNLOAD_PREFIXES = ("/files/",)  # a place's documents
OPEN_PATHS = {"/launch", "/api/health"}  # everything else needs the app window's key
KEY_HEADER = "x-prophelper-key"
SESSION_MAX_AGE = 12 * 3600  # a browser window stays unlocked this long after its last page; every page renews it
SESSIONS_KEPT = 20  # sessions remembered at once (one per launch); the oldest are forgotten first
TILES = "https://tile.openstreetmap.org"  # map tiles: allowed in img-src on /map only, and only when map pictures are on
CSP_TEMPLATE = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src {img}; "
                "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
CSP = CSP_TEMPLATE.format(img="'self' data:")  # no outside picture source on any page
CSP_MAP = CSP_TEMPLATE.format(img=f"'self' data: {TILES}")  # only the Map page, and only while map pictures are on
# Only when the user turns on "Show listing photos" in Settings, and only on a place's own page, photo links the user
# or the AI saved may load (the app never downloads them; the browser does, and only then).
CSP_PHOTOS = CSP_TEMPLATE.format(img="'self' data: https:")
# Page modules that other parts of the app add. A missing one is skipped, so the app runs while they are being built.
OPTIONAL_ROUTERS = ("routes_map", "routes_calendar", "routes_compare", "routes_contacts", "routes_documents",
                    "routes_checklist", "routes_ai", "routes_csv", "routes_geocode", "routes_extra")
LOCKED = "Double-click Start Property Helper again (or open the app icon, or run: prophelper open) to unlock this window."
LOCKED_LOG = ("A browser window asked for a page while locked. To unlock it, double-click Start Property Helper again "
              "(or open the app icon, or run: prophelper open)")
# One-line messages after a form (notice, flash_error, error) travel in a short-lived cookie, not the address,
# so names never land in browser history or logs. The cookie is signed with the app key.
FLASH_KEYS = ("notice", "flash_error", "error")
FLASH_MAX_AGE = 120  # seconds
FLASH_CHARS = 700
FLASH_COOKIE_CHARS = 3000  # a browser drops a cookie over about 4 KB
REDIRECTS = {301, 302, 303, 307, 308}
log = logging.getLogger(__name__)


def key_cookie_name(key: str) -> str:
    """Cookies are shared by every port on 127.0.0.1, so each install's cookie gets its own name. The cookie's
    value is a random session token (never the app key itself)."""
    return "prophelper_key_" + hashlib.sha256(key.encode()).hexdigest()[:10]


def flash_cookie_name(key: str) -> str:
    return "prophelper_flash_" + hashlib.sha256(key.encode()).hexdigest()[:10]


def _flash_sig(key: str, raw: str) -> str:
    return hmac.new(paths.subkey(key, "flash"), raw.encode(), hashlib.sha256).hexdigest()[:32]


def encode_flash(key: str, messages: dict[str, str]) -> str:
    limit = FLASH_CHARS
    while True:  # names in other scripts take several bytes each: shorten until the cookie surely fits
        kept = {k: (v if len(v) <= limit else v[:limit - 3].rstrip() + "...") for k, v in messages.items()}
        raw = base64.urlsafe_b64encode(json.dumps(kept).encode()).decode().rstrip("=")
        if len(raw) <= FLASH_COOKIE_CHARS or limit <= 80:
            return raw + "." + _flash_sig(key, raw)
        limit = limit * 2 // 3


def decode_flash(value: str, key: str | None = None) -> dict[str, str]:
    """The messages in a flash cookie. With key, only when the signature is ours; {} otherwise."""
    raw, _, sig = (value or "").strip('"').partition(".")
    if key is not None and not (sig and hmac.compare_digest(sig.encode(), _flash_sig(key, raw).encode())):
        return {}
    try:
        data = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    except (ValueError, TypeError):
        return {}
    return {k: str(v) for k, v in data.items() if k in FLASH_KEYS and v} if isinstance(data, dict) else {}


def _hostname(host_header: str) -> str:
    """'127.0.0.1:8766' -> '127.0.0.1', '[::1]:8766' -> '[::1]', 'localhost' -> 'localhost'."""
    if host_header.startswith("["):
        return host_header.split("]", 1)[0] + "]"
    return host_header.rsplit(":", 1)[0] if host_header.count(":") == 1 else host_header


def create_app(store: Store, key: str | None = None) -> FastAPI:
    """The FastAPI app for one Store. ``key`` is the app-window key (default: this install's ``app.key``)."""
    key = key or paths.app_key()
    cookie_name = key_cookie_name(key)
    flash_name = flash_cookie_name(key)
    locked_logged = [float("-inf")]  # monotonic time can be under 60s on a just-booted computer
    # Browser sessions: random tokens made when the launch code is used, kept in memory only (restarting the
    # app signs every window out), valid for SESSION_MAX_AGE after their last use.
    sessions: dict[str, float] = {}
    app = FastAPI(title="Property Helper", version=__version__, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = store
    app.state.templates = templates = make_templates(store)
    app.mount("/static", StaticFiles(directory=str(resource_dir() / "static")), name="static")

    def _cross_site_page() -> HTMLResponse:
        return HTMLResponse("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><title>Blocked</title></head><body>"
                            "<p>This request came from another site, so it was blocked. Go back to Property Helper and try again.</p>"
                            "</body></html>", status_code=403)

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        # The server only listens on 127.0.0.1, but a web page in the same browser could still try to reach it.
        # Block DNS-rebinding (foreign Host header) and cross-site requests (CSRF) before any handler runs.
        request.state.session_token = ""
        host_header = (request.headers.get("host") or "").strip().lower()
        if _hostname(host_header) not in LOCAL_HOSTS:
            return PlainTextResponse("Forbidden", status_code=403)
        request.state.unlocked = has_key(request)
        path = request.url.path
        if not request.state.unlocked and path not in OPEN_PATHS and not path.startswith("/static/"):
            return locked(request)
        request.state.flash = decode_flash(request.cookies.get(flash_name, ""), key)
        fetch_site = (request.headers.get("sec-fetch-site") or "").lower()
        if request.method in UNSAFE_METHODS:
            origin = request.headers.get("origin")
            if origin is not None:
                # Sandboxed frames, file:// pages and some redirects send "null": never ours.
                # Otherwise the origin must be exactly this server, port included.
                if origin.strip().lower() == "null" or urlsplit(origin.strip().lower()).netloc != host_header:
                    return _cross_site_page()
            elif fetch_site and fetch_site not in ("same-origin", "none"):
                return _cross_site_page()
            # With neither header (curl, scripts, very old browsers) we allow it: browsers always send at
            # least one of them on a cross-site request, so this can't be CSRF.
        elif request.url.path in DOWNLOADS or request.url.path.startswith(DOWNLOAD_PREFIXES):
            origin = request.headers.get("origin")
            if fetch_site in ("cross-site", "same-site") or (
                    origin is not None and (origin.strip().lower() == "null" or urlsplit(origin.strip().lower()).netloc != host_header)):
                return PlainTextResponse("Blocked: this file can only be downloaded from inside Property Helper, not from another website's page.",
                                         status_code=403)
        response = await call_next(request)
        if request.state.session_token and not path.startswith("/static/") and path != "/launch":
            response.set_cookie(cookie_name, request.state.session_token, max_age=SESSION_MAX_AGE, httponly=True,
                                samesite="strict", path="/")  # renewed on use
        flash_to_cookie(request, response)
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Content-Security-Policy", csp_for(path))
        if not path.startswith("/static/"):  # pages, the API, exports and backups: never kept in the browser cache
            response.headers["Cache-Control"] = "no-store"
        return response

    def csp_for(path: str) -> str:
        try:
            if path.startswith("/places/") and store.get_setting_bool("show_photos"):
                return CSP_PHOTOS
            if path == "/map" and store.get_setting_bool("map_tiles"):
                return CSP_MAP
        except Exception:
            pass
        return CSP

    def flash_to_cookie(request: Request, response: Response) -> None:
        """A redirect's ?notice= (or flash_error) moves into the flash cookie; a page that showed it clears it."""
        if response.status_code in REDIRECTS and "location" in response.headers:
            target = urlsplit(response.headers["location"])
            pairs = parse_qsl(target.query, keep_blank_values=True)
            messages = {k: v for k, v in pairs if k in FLASH_KEYS and v}
            if messages or any(k in FLASH_KEYS for k, _ in pairs):
                rest = urlencode([(k, v) for k, v in pairs if k not in FLASH_KEYS])
                response.headers["location"] = target._replace(query=rest).geturl()
            if messages:
                response.set_cookie(flash_name, encode_flash(key, messages), max_age=FLASH_MAX_AGE, httponly=True,
                                    samesite="strict", path="/")
                return
        shown = (request.method == "GET" and not request.headers.get("HX-Request") and response.status_code not in REDIRECTS
                 and response.headers.get("content-type", "").startswith("text/html"))
        if request.cookies.get(flash_name) and shown:
            response.delete_cookie(flash_name, path="/", httponly=True, samesite="strict")

    def new_session() -> str:
        now = time.time()
        for t in [t for t, seen in sessions.items() if now - seen > SESSION_MAX_AGE]:
            del sessions[t]
        while len(sessions) >= SESSIONS_KEPT:
            del sessions[min(sessions, key=sessions.get)]
        token = secrets.token_urlsafe(32)
        sessions[token] = now
        return token

    def session_token(request: Request) -> str:
        """The browser's session token when it is one of ours and not idle for too long (and marks it used), else ''."""
        given = request.cookies.get(cookie_name) or ""
        for token, seen in list(sessions.items()):
            if hmac.compare_digest(given.encode(), token.encode()):
                if time.time() - seen > SESSION_MAX_AGE:
                    del sessions[token]
                    return ""
                sessions[token] = time.time()
                return token
        return ""

    def has_key(request: Request) -> bool:
        """Unlocked by a live browser session (cookie) or by the app key in the x-prophelper-key header (CLI, MCP links)."""
        request.state.session_token = session_token(request)
        if request.state.session_token:
            return True
        given = request.headers.get(KEY_HEADER) or ""
        return hmac.compare_digest(given.encode(), key.encode())

    def locked(request: Request) -> Response:
        if request.url.path.startswith("/api/"):
            resp: Response = JSONResponse({"detail": LOCKED}, status_code=401)
        else:  # only the way to unlock: every other link would land on this page again
            resp = templates.TemplateResponse(request, "locked.html", {"message": LOCKED, "frozen": paths.is_frozen()}, status_code=401)
            if time.monotonic() - locked_logged[0] > 60:  # the same hint in the serve log, once a minute at most
                locked_logged[0] = time.monotonic()
                log.info(LOCKED_LOG)
        for k, v in (("X-Frame-Options", "DENY"), ("X-Content-Type-Options", "nosniff"),
                     ("Referrer-Policy", "same-origin"), ("Content-Security-Policy", CSP), ("Cache-Control", "no-store")):
            resp.headers[k] = v
        return resp

    @app.get("/launch")
    def launch(request: Request, code: str = ""):
        """The app icon and `prophelper open` come here with a one-time code; it leaves a cookie that unlocks the window."""
        if not (request.state.unlocked or paths.use_launch_code(code)):
            return locked(request)
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie(cookie_name, new_session(), max_age=SESSION_MAX_AGE, httponly=True, samesite="strict", path="/")
        return resp

    @app.get("/")
    def home():
        return RedirectResponse("/today", status_code=303)

    @app.get("/api/health")
    def health(request: Request, nonce: str = "") -> dict[str, Any]:
        """Open without the key so a second launch can find the running app. Says nothing about the data.
        With a nonce it also answers `proof` (paths.health_proof), so the launcher can tell this app from
        another program on the port before it sends a launch code. The proof is bound to the port this request
        really arrived on (the socket's, not a header), so a relay on another port can't use it."""
        out: dict[str, Any] = {"ok": True, "version": __version__}
        server = request.scope.get("server") or ()
        if len(server) == 2 and isinstance(server[1], int) and server[1] > 0:
            paths.record_port(server[1])  # a probe of the live app repairs a missing or stale port file
        if nonce and len(nonce) <= 128 and len(server) == 2 and isinstance(server[1], int):
            out["proof"] = paths.health_proof(key, nonce, server[1])
        if request.state.unlocked:
            out["places"] = store.count_places(include_archived=True)
        return out

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        if exc.status_code == 404:
            detail = exc.detail if exc.detail and exc.detail != "Not Found" else "That page doesn't exist."
            return render(request, "message.html", status_code=404, title="Not found", message=detail)
        return PlainTextResponse(str(exc.detail), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def bad_request(request: Request, exc: RequestValidationError):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": "Invalid request."}, status_code=422)
        if any((e.get("loc") or ("",))[0] == "path" for e in exc.errors()):
            return render(request, "message.html", status_code=404, title="Not found", message="That page doesn't exist.")
        return render(request, "message.html", status_code=400, title="That link isn't right",
                      message="Something in that address isn't right. Go back and try again.")

    @app.exception_handler(sqlite3.DatabaseError)  # includes OperationalError (a missing column, a damaged file)
    async def data_file_wrong(request: Request, exc: sqlite3.DatabaseError):
        log.error("Database error on %s: %s", request.url.path, exc)
        text = ("Something is wrong with your data file. You can restore the backup taken before your last restore "
                "on the Backups page.")
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": text}, status_code=500)
        page = ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
                "<title>Data file problem · Property Helper</title>"
                '<link rel="stylesheet" href="/static/style.css"></head><body><main style="max-width:36rem;margin:3rem auto;padding:0 1rem">'
                f"<h1>Something is wrong with your data file</h1><p>{text.split('. ', 1)[1]}</p>"
                '<p><a class="btn primary" href="/backups">Open Backups</a> &nbsp; <a href="/settings">Settings</a></p>'
                "</main></body></html>")
        return HTMLResponse(page, status_code=500)

    # The page routers. Each is a module of its own so several people can work on them at once. To add a page, write
    # ``routes_<name>.py`` with ``router = APIRouter()`` and add its name to OPTIONAL_ROUTERS (or to the core list).
    from . import routes_connect, routes_data, routes_pages, routes_skills

    for module in (routes_pages, routes_data, routes_connect, routes_skills):
        app.include_router(module.router)
    for name in OPTIONAL_ROUTERS:
        try:
            module = importlib.import_module(f"{__package__}.{name}")
        except ModuleNotFoundError as exc:
            if exc.name != f"{__package__}.{name}":
                raise  # the module exists but one of its imports is missing: that is a bug to see
            continue
        app.include_router(module.router)

    for route in app.routes:  # HEAD works wherever GET does (link checkers, curl -I)
        if isinstance(route, APIRoute) and "GET" in route.methods and route.path != "/launch":  # HEAD never spends a code
            route.methods.add("HEAD")
    return app
