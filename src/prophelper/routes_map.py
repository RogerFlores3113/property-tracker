"""The map.

    GET  /map                        the current search's places as pins (?anchor=ID picks the anchor for the 1, 2 and 3 mile
                                     rings, ?anchor=0 turns them off, ?show_hidden=1 includes hidden places)
    POST /places/{id}/location       save a place's latitude and longitude by hand

The page works without JavaScript as a list. ``/places/{id}/geocode`` (the "Find on map" button, shown only when
the address lookup setting is on) is built in the AI and lookup module.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from . import enrich, mapdata
from .deps import get_store, redirect, render
from .store import NotFound

router = APIRouter()


@router.get("/map", include_in_schema=False)
def map_page(request: Request, anchor: str = "", show_hidden: int = 0):
    store = get_store(request)
    search = store.current_search()
    anchors = store.list_anchors()
    tiles = store.get_setting_bool("map_tiles")
    if search is None:
        return render(request, "map.html", search=None, anchors=anchors, chosen=None, tiles=tiles, data=mapdata.build([], anchors, tiles=tiles, anchor=None)["data"],
                      located=[], unlocated=[], hidden=0, show_hidden=False, geocode=False)
    rows = enrich.enrich_places(store, search)
    shown, hidden = [], 0
    for p in rows:
        if (p["hidden"] or p["hidden_by_dealbreaker"]) and not show_hidden:
            hidden += 1
            continue
        shown.append(p)
    wanted = int(anchor) if anchor.isdigit() else None
    chosen = mapdata.pick_anchor(anchors, wanted)
    built = mapdata.build(shown, anchors, tiles=tiles, anchor=chosen)
    return render(request, "map.html", search=search, anchors=anchors, chosen=chosen, no_rings=(wanted == 0), tiles=tiles, data=built["data"],
                  located=built["located"], unlocated=built["unlocated"], hidden=hidden, show_hidden=bool(show_hidden),
                  geocode=store.get_setting_bool("geocode"))


@router.post("/map/tiles", include_in_schema=False)
def show_street_map(request: Request):
    """The one button on the plain map: turn map pictures on (same switch as Settings)."""
    get_store(request).set_setting("map_tiles", "1")
    return redirect("/map", notice="Street map is on. Your browser now loads map pictures from OpenStreetMap when you open the Map. You can turn it off in Settings.")


@router.post("/places/{place_id}/location", include_in_schema=False)
async def save_location(request: Request, place_id: int):
    store = get_store(request)
    form = await request.form()
    lat, lng = str(form.get("lat", "")).strip(), str(form.get("lng", "")).strip()
    if not lat or not lng:
        return redirect("/map", error="Type both the latitude and the longitude.")
    try:
        place = store.update_place(place_id, by="you", lat=lat, lng=lng)
    except NotFound:
        raise HTTPException(404, "That place doesn't exist (it may have been deleted).") from None
    except ValueError as exc:
        return redirect("/map", error=str(exc))
    return redirect("/map", notice=f"Saved a map point for {place['title']}.")
