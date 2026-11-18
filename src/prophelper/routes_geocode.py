"""Opt-in address lookup (OpenStreetMap address lookup) for places and important places.

    POST /places/{id}/geocode     look up the place's address, save lat and lng, go back to the page
    POST /anchors/{id}/geocode    the same for an important place (a saved place for commutes, like Campus or Work)

The Find button is always shown. Lookup stays opt-in: while it is off, pressing Find shows a short explanation page with
"Turn on and find" (which posts ``enable=1`` to the same address) and "Not now". See ``geocode.py`` for exactly what is sent.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from . import geocode
from .deps import back as _back, get_store, redirect, render, safe_local_path
from .store import NotFound

router = APIRouter()


def _ask_to_turn_on(request: Request, *, action: str, what: str, fields: dict[str, str], back_url: str):
    """The one-time explanation shown instead of a silent redirect while lookup is off."""
    return render(request, "geocode_ask.html", action=action, what=what, fields=fields,
                  back_url=back_url if safe_local_path(back_url) else "/today")


def back(request: Request, default: str, notice: str = "", error: str = ""):
    """Like deps.back, but never back to this POST-only address (the explanation page is shown there)."""
    if (request.headers.get("referer") or "").split("?")[0].endswith("/geocode"):
        return redirect(default, notice=notice, error=error)
    return _back(request, default, notice=notice, error=error)


def _wants_on(form) -> bool:
    return str(form.get("enable") or "") == "1"


def lookup_for_place(request: Request, store, place: dict, *, enable: bool = False):
    default = f"/places/{place['id']}"
    if not store.get_setting_bool("geocode"):
        if not enable:
            return _ask_to_turn_on(request, action=f"/places/{place['id']}/geocode", what=place.get("title") or "this place",
                                   fields={}, back_url=default)
        store.set_setting("geocode", "1")
    if not (place.get("address") or "").strip():
        return back(request, default, error="This place has no street address yet. Save one, then press Find on map.")
    try:
        lat, lng, name = geocode.lookup(geocode.address_text(place))
        store.update_place(place["id"], by="you", lat=lat, lng=lng)
    except (geocode.GeocodeError, ValueError) as exc:
        return back(request, default, error=str(exc))
    return back(request, default, notice=f"Found it and saved the map point ({lat}, {lng})." + (f" OpenStreetMap calls it: {name}" if name else ""))


def lookup_for_anchor(request: Request, store, anchor: dict, *, search_id: str = "", enable: bool = False):
    default = f"/search?id={search_id}#anchors" if str(search_id).isdigit() else "/search#anchors"
    if not store.get_setting_bool("geocode"):
        if not enable:
            return _ask_to_turn_on(request, action=f"/anchors/{anchor['id']}/geocode", what=anchor["name"],
                                   fields={"search_id": str(search_id)} if str(search_id).isdigit() else {}, back_url=default)
        store.set_setting("geocode", "1")
    if not (anchor.get("address") or "").strip():
        return back(request, default, error=f"{anchor['name']} has no address yet. Type one and press Find on map again, or enter coordinates yourself.")
    try:
        lat, lng, name = geocode.lookup(geocode.address_text(anchor))
        store.update_anchor(anchor["id"], lat=lat, lng=lng)
    except (geocode.GeocodeError, ValueError) as exc:
        return back(request, default, error=str(exc))
    return back(request, default, notice=f"Found {anchor['name']} and saved its map point ({lat}, {lng})." + (f" OpenStreetMap calls it: {name}" if name else ""))


@router.post("/places/{place_id}/geocode", include_in_schema=False)
async def geocode_place(request: Request, place_id: int):
    store = get_store(request)
    try:
        place = store.get_place(place_id)
    except NotFound:
        raise HTTPException(404, "That place doesn't exist (it may have been deleted).") from None
    form = await request.form()
    return lookup_for_place(request, store, place, enable=_wants_on(form))


@router.post("/anchors/{anchor_id}/geocode", include_in_schema=False)
async def geocode_anchor(request: Request, anchor_id: int):
    store = get_store(request)
    try:
        anchor = store.get_anchor(anchor_id)
    except NotFound:
        raise HTTPException(404, "That important place doesn't exist.") from None
    form = await request.form()
    if "address" in form and str(form.get("address")).strip() != (anchor.get("address") or ""):
        try:  # the Find button sits in the edit form, so use the address as typed
            anchor = store.update_anchor(anchor_id, address=form.get("address", ""))
        except ValueError as exc:
            return back(request, "/search#anchors", error=str(exc))
    return lookup_for_anchor(request, store, anchor, search_id=str(form.get("search_id") or ""), enable=_wants_on(form))
