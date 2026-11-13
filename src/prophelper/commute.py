"""Commute estimates from two map points. Pure: no database, no web.

An estimate is straight-line miles times 1.3 (roads are not straight), then a speed per mode:
walk 3 mph, bike 10 mph, transit 12 mph plus 8 minutes, drive 25 mph plus 4 minutes.
A value the user or the AI typed always wins over an estimate.
"""
from __future__ import annotations

import math
from typing import Any, Iterable

MODES: tuple[str, ...] = ("walk", "bike", "transit", "drive")
MODE_LABELS = {"walk": "walk", "bike": "bike", "transit": "transit", "drive": "drive"}
ROAD_FACTOR = 1.3
SPEED_MPH = {"walk": 3.0, "bike": 10.0, "transit": 12.0, "drive": 25.0}
EXTRA_MINUTES = {"walk": 0, "bike": 0, "transit": 8, "drive": 4}
EARTH_RADIUS_MILES = 3958.8
SOURCES = ("estimate", "you", "ai")
NO_LOCATION_MESSAGE = ("{name} has no location yet, so there is no commute to work out. "
                       "On the Search page, press Find on map next to it, or enter its coordinates yourself.")
MODE_VERBS = {"walk": "Walk", "bike": "Bike", "transit": "Transit", "drive": "Drive"}


def commute_label(mode: str, minutes: int | float | None, anchor_name: str) -> str:
    """'Drive to Office, 15 min or less'. Always names the important place."""
    way = MODE_VERBS.get(mode, str(mode).capitalize())
    mins = f", {int(round(minutes))} min or less" if minutes else ""
    return f"{way} to {anchor_name}{mins}"


def haversine_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Straight-line distance between two points on Earth, in miles."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dlmb = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(min(1.0, math.sqrt(a)))


def estimate_minutes(miles: float, mode: str) -> int:
    """Minutes for a straight-line distance by one mode (see the module note). At least 1."""
    if mode not in SPEED_MPH:
        raise ValueError(f"Unknown way to travel: {mode}. Use one of: {', '.join(MODES)}.")
    road = miles * ROAD_FACTOR
    return max(1, round(road / SPEED_MPH[mode] * 60 + EXTRA_MINUTES[mode]))


def label(minutes: int | float | None, source: str = "you", mode: str = "") -> str:
    """'about 12 min (estimate)' or '15 min (you)'."""
    if minutes is None:
        return ""
    n = int(round(minutes))
    way = f" {MODE_LABELS.get(mode, mode)}" if mode else ""
    if source == "estimate":
        return f"about {n} min{way} (estimate)"
    return f"{n} min{way}" + (" (you)" if source == "you" else " (added by Claude)" if source == "ai" else "")


def has_point(thing: dict[str, Any] | None) -> bool:
    try:
        return thing is not None and thing.get("lat") is not None and thing.get("lng") is not None \
            and -90 <= float(thing["lat"]) <= 90 and -180 <= float(thing["lng"]) <= 180
    except (TypeError, ValueError):
        return False


def miles_between(place: dict[str, Any] | None, anchor: dict[str, Any] | None) -> float | None:
    """Straight-line miles between a place and an anchor, or None when either has no location."""
    if not (has_point(place) and has_point(anchor)):
        return None
    return haversine_miles(float(place["lat"]), float(place["lng"]), float(anchor["lat"]), float(anchor["lng"]))


def estimate(place: dict[str, Any] | None, anchor: dict[str, Any] | None, mode: str) -> dict[str, Any] | None:
    """``{"minutes", "miles", "source": "estimate", "mode", "label"}`` or None when a location is missing."""
    miles = miles_between(place, anchor)
    if miles is None:
        return None
    minutes = estimate_minutes(miles, mode)
    return {"minutes": minutes, "miles": round(miles, 2), "source": "estimate", "mode": mode,
            "label": label(minutes, "estimate", mode)}


def resolve(place: dict[str, Any] | None, anchor: dict[str, Any] | None, mode: str,
            stored: Iterable[dict[str, Any]] = ()) -> dict[str, Any] | None:
    """The commute to show for one place, anchor and mode. A stored value from you or the AI wins; otherwise the
    estimate; otherwise None. ``stored`` is the rows of the commutes table (any of them: this picks the match)."""
    if anchor is None:
        return None
    for row in stored:
        if row.get("anchor_id") == anchor.get("id") and row.get("mode") == mode and row.get("source") in ("you", "ai") \
                and row.get("minutes") is not None:
            miles = miles_between(place, anchor)
            return {"minutes": row["minutes"], "miles": round(miles, 2) if miles is not None else None,
                    "source": row["source"], "mode": mode, "label": label(row["minutes"], row["source"], mode)}
    return estimate(place, anchor, mode)


def resolve_all(place: dict[str, Any], anchors: Iterable[dict[str, Any]], stored: Iterable[dict[str, Any]] = (),
                modes: Iterable[str] = MODES) -> list[dict[str, Any]]:
    """Every anchor by every mode that has an answer: ``[{"anchor", "anchor_id", "mode", ...resolve()}]``."""
    stored = list(stored)
    out = []
    for a in anchors:
        for m in modes:
            r = resolve(place, a, m, stored)
            if r:
                out.append({"anchor": a.get("name", ""), "anchor_id": a.get("id"), **r})
    return out


def _fastest(place: dict[str, Any], anchor: dict[str, Any], stored: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The fastest known way to one important place: walk, bike or drive (typed or estimated), plus any way someone
    typed (transit too), so a typed commute shows even when the important place has no map point."""
    options = [r for m in ("walk", "bike", "drive") if (r := resolve(place, anchor, m, stored))]
    options += [r for m in MODES if m not in ("walk", "bike", "drive") and (r := resolve(place, anchor, m, stored))
                and r["source"] in ("you", "ai")]
    return min(options, key=lambda r: r["minutes"]) if options else None


def top_commute(place: dict[str, Any], anchors: Iterable[dict[str, Any]], stored: Iterable[dict[str, Any]] = (),
                prefer_mode: str | None = None) -> dict[str, Any] | None:
    """The one commute a card shows: the first anchor's best answer. ``prefer_mode`` (a criterion's mode) first,
    else the fastest of walk, bike and drive."""
    anchors = list(anchors)
    stored = list(stored)
    for a in anchors:
        if prefer_mode:
            r = resolve(place, a, prefer_mode, stored)
            if r:
                return {"anchor": a.get("name", ""), "anchor_id": a.get("id"), **r}
        best = _fastest(place, a, stored)
        if best:
            return {"anchor": a.get("name", ""), "anchor_id": a.get("id"), **best}
    return None


def criterion_modes(criteria: Iterable[dict[str, Any]], anchors: Iterable[dict[str, Any]]) -> dict[Any, str]:
    """{anchor id: mode} from the commute criteria (a criterion with no place means the first important place)."""
    anchors = list(anchors)
    first = anchors[0]["id"] if anchors else None
    out: dict[Any, str] = {}
    for c in criteria:
        if c.get("kind") == "commute":
            out.setdefault(c["target"].get("anchor_id") or first, c["target"].get("mode") or "bike")
    return out


def pick_for_anchor(place: dict[str, Any], anchor: dict[str, Any], stored: Iterable[dict[str, Any]] = (),
                    mode: str | None = None) -> tuple[str | None, dict[str, Any] | None]:
    """(mode, answer) shown for one important place: the criterion's ``mode`` when it has an answer, else the fastest
    known way (walk, bike or drive). ``(mode, None)`` when nothing is known."""
    stored = list(stored)
    if mode:
        found = resolve(place, anchor, mode, stored)
        if found:
            return mode, found
    options = [(m, r) for m in MODES if (r := resolve(place, anchor, m, stored))
               and (m != "transit" or r["source"] in ("you", "ai"))]
    if options:
        return min(options, key=lambda o: o[1]["minutes"])
    return mode, None


def place_rows(place: dict[str, Any], anchors: Iterable[dict[str, Any]], stored: Iterable[dict[str, Any]] = (),
               criteria: Iterable[dict[str, Any]] = ()) -> list[dict[str, Any]]:
    """One row per important place for the place page: ``{"anchor", "mode", "found", "others", "anchor_has_point",
    "place_has_point"}``. ``mode`` is the way of that place's commute criterion (fastest known when there is none) and
    ``others`` are the remaining ways, each ``{"mode", "found"}``, to fold under "Other ways"."""
    stored = list(stored)
    anchors = list(anchors)
    crit = criterion_modes(criteria, anchors)
    rows = []
    for a in anchors:
        mode, found = pick_for_anchor(place, a, stored, crit.get(a["id"]))
        mode = mode or "bike"
        others = [{"mode": m, "found": resolve(place, a, m, stored)} for m in MODES if m != mode]
        rows.append({"anchor": a, "mode": mode, "found": found, "others": others,
                     "anchor_has_point": has_point(a), "place_has_point": has_point(place)})
    return rows
