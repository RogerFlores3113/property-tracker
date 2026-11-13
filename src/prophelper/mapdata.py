"""What the Map page hands to its script and its no-JavaScript list. Pure: no database, no web.

``build(places, anchors, ...)`` takes enriched places (see ``enrich.py``) and returns ``{"data", "located", "unlocated"}``:

* ``data``: the dict that goes into the page as JSON (``tiles``, ``places``, ``anchors``, ``ring``, ``center``).
* ``located``: every shown place with a map point, each with ``miles`` to the chosen anchor (or None).
* ``unlocated``: the places with no usable map point (the page lists them with a form to add one).
"""
from __future__ import annotations

from typing import Any

from . import commute, helpers

RING_MILES = (1, 2, 3)
TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
DEFAULT_CENTER = (39.8283, -98.5795)  # the middle of the United States, used when nothing has a point yet


def pick_anchor(anchors: list[dict[str, Any]], wanted: int | None) -> dict[str, Any] | None:
    """The anchor the rings go around: the one asked for, else the first with a map point, else None.
    ``wanted`` of 0 means no rings."""
    located = [a for a in anchors if commute.has_point(a)]
    if wanted == 0:
        return None
    for a in located:
        if a["id"] == wanted:
            return a
    return located[0] if located else None


def label_for(place: dict[str, Any]) -> str:
    """The text on a pin: the true monthly cost, e.g. '$1,495', or '?' when there is no price yet."""
    return helpers.money(place["cost_total"]) if place.get("cost_total") is not None else "?"


def build(places: list[dict[str, Any]], anchors: list[dict[str, Any]], *, tiles: bool, anchor: dict[str, Any] | None) -> dict[str, Any]:
    located, unlocated = [], []
    for p in places:
        if commute.has_point(p):
            row = dict(p)
            miles = commute.miles_between(p, anchor) if anchor else None
            row["miles"] = round(miles, 1) if miles is not None else None
            located.append(row)
        else:
            unlocated.append(p)
    pins = [{"id": p["id"], "title": p["title"], "label": label_for(p), "score": p["score_total"], "fit": (p.get("score") or {}).get("fit", "fits"), "band": p["band"] or "none",
             "stage": p["stage"], "lat": float(p["lat"]), "lng": float(p["lng"]), "url": f"/places/{p['id']}"} for p in located]
    pts = [{"id": a["id"], "name": a["name"], "lat": float(a["lat"]), "lng": float(a["lng"])} for a in anchors if commute.has_point(a)]
    marks = [(x["lat"], x["lng"]) for x in pins + pts]
    center = (sum(m[0] for m in marks) / len(marks), sum(m[1] for m in marks) / len(marks)) if marks else DEFAULT_CENTER
    data = {"tiles": tiles, "tileUrl": TILE_URL, "attribution": ATTRIBUTION, "places": pins, "anchors": pts,
            "ring": {"anchorId": anchor["id"], "lat": float(anchor["lat"]), "lng": float(anchor["lng"]), "miles": list(RING_MILES)} if anchor else None,
            "center": [round(center[0], 5), round(center[1], 5)]}
    located.sort(key=lambda r: (r["miles"] is None, r["miles"] or 0, r["title"].lower()))
    return {"data": data, "located": located, "unlocated": unlocated}
