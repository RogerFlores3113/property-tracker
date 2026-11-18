"""Opt-in address lookup through OpenStreetMap Nominatim.

Off unless the person turns on "Find map locations for addresses" in Settings, and then only when they press a Find
button. What one lookup sends, exactly:

* the address text (street, city, state, ZIP, joined with commas) as the ``q`` parameter, ``format=json`` and ``limit=1``;
* a generic ``User-Agent`` that names this app and its version, never the person's name, computer or details;
* and, as for any web request, the person's network address.

It sends no place name, notes, listing text, rating or anything else. At most one request goes out per second (Nominatim's
usage policy), with a timeout, and problems come back in plain words. Tests put an ``httpx.MockTransport`` in ``TRANSPORT``.
"""
from __future__ import annotations

import threading
import time
from typing import Any

import httpx

from . import __version__

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = f"PropertyHelper/{__version__} (desktop app for apartment hunting)"
MIN_INTERVAL_SECONDS = 1.0
TIMEOUT_SECONDS = 10.0
TRANSPORT: httpx.BaseTransport | None = None  # tests put an httpx.MockTransport here

_now = time.monotonic  # tests replace these two so they never wait
_sleep = time.sleep
_lock = threading.Lock()
_last_start: list[float] = []  # monotonic time the last request started (empty: none yet)


class GeocodeError(Exception):
    """A problem to show the person in plain words."""


def address_text(parts: dict[str, Any]) -> str:
    """The text that is sent: street, city, state and ZIP of a place or an anchor, joined with commas. No unit, name or notes."""
    bits = [" ".join(str(parts.get(k) or "").split()) for k in ("address", "city", "state", "zip")]
    return ", ".join(b for b in bits if b)


def _wait_turn() -> None:
    """Block until at least ``MIN_INTERVAL_SECONDS`` have passed since the last request started (callers queue on a lock)."""
    if _last_start:
        gap = MIN_INTERVAL_SECONDS - (_now() - _last_start[0])
        if gap > 0:
            _sleep(gap)
    _last_start[:] = [_now()]


def lookup(query: str) -> tuple[float, float, str]:
    """Look one address up. Returns ``(lat, lng, name found)``. Raises :class:`GeocodeError`."""
    query = " ".join((query or "").split())
    if len(query) < 4:
        raise GeocodeError("There is no address to look up yet. Save a street address first.")
    params = {"q": query[:300], "format": "json", "limit": "1"}
    with _lock:
        _wait_turn()
        try:
            with httpx.Client(timeout=TIMEOUT_SECONDS, transport=TRANSPORT, follow_redirects=False) as client:
                resp = client.get(NOMINATIM_URL, params=params, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        except httpx.TimeoutException:
            raise GeocodeError("OpenStreetMap took too long to answer. Try again in a minute, or type the latitude and longitude yourself.") from None
        except httpx.HTTPError:
            raise GeocodeError("Couldn't reach OpenStreetMap. Check your internet connection, or type the latitude and longitude yourself.") from None
    if resp.status_code == 429:
        raise GeocodeError("OpenStreetMap says there have been too many lookups just now. Wait a minute and try again.")
    if resp.status_code in (401, 403):
        raise GeocodeError("OpenStreetMap refused the lookup (a work or school network may block it). Type the latitude and longitude yourself.")
    if resp.status_code >= 500:
        raise GeocodeError("OpenStreetMap is busy right now. Try again in a minute.")
    if resp.status_code != 200:
        raise GeocodeError(f"OpenStreetMap sent back an error ({resp.status_code}). Try again in a minute.")
    try:
        data = resp.json()
        if not isinstance(data, list):
            raise ValueError("not a list")
        first = data[0] if data else None
        if first is None:
            raise GeocodeError("OpenStreetMap doesn't know that address. Check the spelling, or type the latitude and longitude yourself.")
        lat, lng = float(first["lat"]), float(first["lon"])
        name = str(first.get("display_name") or "")[:200]
    except GeocodeError:
        raise
    except (ValueError, KeyError, TypeError, IndexError):
        raise GeocodeError("OpenStreetMap's answer couldn't be read. Try again, or type the latitude and longitude yourself.") from None
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise GeocodeError("OpenStreetMap sent back a point that isn't on the map. Type the latitude and longitude yourself.")
    return round(lat, 6), round(lng, 6), name
