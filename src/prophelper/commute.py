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


def criterion_modes(criteria: Iterable[dict[str, Any]], anchors: Iterable[dict[str, Any]], people: int = 1) -> dict[Any, str]:
    """{anchor id: mode} from the commute criteria. A criterion with no place means the first important place, and an
    "everyone's places" criterion (or any commute rule when several people share the search) covers every place that
    has no rule of its own."""
    anchors = list(anchors)
    first = anchors[0]["id"] if anchors else None
    out: dict[Any, str] = {}
    spread: str | None = None
    for c in criteria:
        if c.get("kind") != "commute":
            continue
        t = c.get("target") or {}
        mode = t.get("mode") or "bike"
        if t.get("anchor_id") is not None:
            out.setdefault(t["anchor_id"], mode)
        elif t.get("all_anchors") or (people > 1 and anchors):
            spread = spread or mode
            out.setdefault(first, mode)
        else:
            out.setdefault(first, mode)
    if spread:
        for a in anchors:
            out.setdefault(a["id"], spread)
    return out


def show_commute(place: dict[str, Any], anchor: dict[str, Any], stored: Iterable[dict[str, Any]] = (),
                 mode: str | None = None) -> dict[str, Any] | None:
    """The ONE commute to show for a place and an important place (Compare, share, CSV, cards, the place page, Claude).

    ``mode`` is the way of the commute rule for that place (None when no rule). With a rule the answer is always that
    way: the saved time (typed by the user or set by Claude) if there is one, else an estimate of the same way,
    labelled as an estimate. It never shows an estimate of another way. Only when that way has no answer at all is a
    time someone saved in another way shown, named by its way (Compare never ranks it). With no rule, a saved time wins
    (the fastest one), else the fastest estimate of walk, bike or drive. Returns ``resolve()``'s shape or None."""
    stored = list(stored)
    if mode:
        found = resolve(place, anchor, mode, stored)
        if found:
            return found
    saved = [r for m in MODES if (r := resolve(place, anchor, m, stored)) and r["source"] in ("you", "ai")]
    if saved:
        return min(saved, key=lambda r: r["minutes"])
    est = [r for m in ("walk", "bike", "drive") if (r := estimate(place, anchor, m))]
    return min(est, key=lambda r: r["minutes"]) if est else None


def pick_for_anchor(place: dict[str, Any], anchor: dict[str, Any], stored: Iterable[dict[str, Any]] = (),
                    mode: str | None = None) -> tuple[str | None, dict[str, Any] | None]:
    """(mode, answer) shown for one important place, by ``show_commute``. ``(mode, None)`` when nothing is known."""
    found = show_commute(place, anchor, stored, mode)
    return (found["mode"] if found else mode), found


def top_commute(place: dict[str, Any], anchors: Iterable[dict[str, Any]], stored: Iterable[dict[str, Any]] = (),
                prefer_mode: str | None = None, criteria: Iterable[dict[str, Any]] = (), people: int = 1) -> dict[str, Any] | None:
    """One commute to show when a single one is needed: the first important place that has an answer, in the way of its
    commute rule (``criteria``; else ``prefer_mode`` for the first place), by ``show_commute``."""
    anchors = list(anchors)
    stored = list(stored)
    modes = criterion_modes(criteria, anchors, people)
    for i, a in enumerate(anchors):
        mode = modes.get(a["id"]) or (prefer_mode if i == 0 else None)
        r = show_commute(place, a, stored, mode)
        if r:
            return {"anchor": a.get("name", ""), "anchor_id": a.get("id"), **r}
    return None


def all_commutes(place: dict[str, Any], anchors: Iterable[dict[str, Any]], stored: Iterable[dict[str, Any]] = (),
                 criteria: Iterable[dict[str, Any]] = (), people: int = 1) -> list[dict[str, Any]]:
    """Every important place's shown commute, ``[{"anchor", "anchor_id", ...}]`` (places with no answer are left out)."""
    anchors = list(anchors)
    stored = list(stored)
    modes = criterion_modes(criteria, anchors, people)
    out = []
    for a in anchors:
        r = show_commute(place, a, stored, modes.get(a["id"]))
        if r:
            out.append({"anchor": a.get("name", ""), "anchor_id": a.get("id"), **r})
    return out


def place_rows(place: dict[str, Any], anchors: Iterable[dict[str, Any]], stored: Iterable[dict[str, Any]] = (),
               criteria: Iterable[dict[str, Any]] = (), people: int = 1) -> list[dict[str, Any]]:
    """One row per important place for the place page: ``{"anchor", "mode", "found", "others", "anchor_has_point",
    "place_has_point"}``. ``mode`` is the way of that place's commute rule (the shown time's way when there is none) and
    ``others`` are the remaining ways, each ``{"mode", "found"}``, to fold under "Other ways"."""
    stored = list(stored)
    anchors = list(anchors)
    crit = criterion_modes(criteria, anchors, people)
    rows = []
    for a in anchors:
        mode, found = pick_for_anchor(place, a, stored, crit.get(a["id"]))
        mode = mode or "bike"
        others = [{"mode": m, "found": resolve(place, a, m, stored)} for m in MODES if m != mode]
        rows.append({"anchor": a, "mode": mode, "found": found, "others": others,
                     "anchor_has_point": has_point(a), "place_has_point": has_point(place)})
    return rows
