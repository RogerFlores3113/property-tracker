"""What the Today page shows: the best fits right now, what is coming up (with a short prep line), new places worth a look,
and who still owes a reply. Reads the store and ``enrich``; writes nothing.

Rules (see the product decisions): a place counts as a fit when it has a score, passes every deal-breaker and has no
high-severity red flag. A place that doesn't fit, or that may be a scam, stays on the Board but never shows under
"Best fits" or "New places".
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from . import enrich, helpers, redflags, scoring, stages
from .store import PLACE_DATE_LABELS, Store

COMING_UP_DAYS = 14
TOP_FITS = 3
LATE_AVAILABLE_DAYS = 7  # available_from more than this many days after the move-in date is a warning
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def possible_scam(place: dict[str, Any], high_messages: Any = None) -> bool:
    """True when the place is a possible scam. One rule, ``redflags.is_serious`` (enrich stores the answer on the place)."""
    if "possible_scam" in place:
        return bool(place["possible_scam"])
    return redflags.is_serious(place)


def fails_dealbreakers(place: dict[str, Any]) -> bool:
    score = place.get("score") or {}
    if score.get("passes") is False or score.get("dealbroken"):
        return True
    return bool(score.get("fails_dealbreaker") or place.get("hidden_by_dealbreaker"))


MIN_FIT_SCORE = 60  # "Best fits" needs a reasonable score as well as every must-have


def fits(place: dict[str, Any], high_messages: Any = None) -> bool:
    return place.get("score_total") is not None and not fails_dealbreakers(place) and not possible_scam(place)


def is_near(place: dict[str, Any]) -> bool:
    """A must-have is missed by a little (only because of a guess): a near miss, so not a best fit."""
    score = place.get("score") or {}
    return bool(score.get("near")) or score.get("fit") == "near_miss"


def is_best_fit(place: dict[str, Any]) -> bool:
    return fits(place) and place["score_total"] >= MIN_FIT_SCORE and not is_near(place)


def best_fits(rows: list[dict[str, Any]], limit: int = TOP_FITS) -> list[dict[str, Any]]:
    """The top places by score that fit. ``rows`` are enriched places. Passed, won and hidden places are skipped."""
    open_rows = [p for p in rows if not p["hidden"] and p["stage"] not in ("Passed", "Lease signed", "Closed") and is_best_fit(p)
                 and not no_price(p)]
    open_rows.sort(key=lambda p: ((p.get("score") or {}).get("sort_group", 0), -p["score_total"], p["title"].lower()))
    top = open_rows[:limit]
    for p in top:
        p["caution"] = caution(p)
    return top


AI_TEXT_CAUTION = "Check first: text aimed at AI tools in the listing. Read it yourself before you rely on this score."


def no_price(place: dict[str, Any]) -> bool:
    """True when a place has no rent (or, buying, no price), so it can't be ranked as a best fit. Rows made by hand
    without a ``cost_total`` are treated as priced."""
    return "cost_total" in place and place["cost_total"] is None


def needs_price(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Open places that would be best fits but have no rent or price yet: listed after the priced fits as "no price yet"."""
    return [p for p in rows if not p["hidden"] and p["stage"] not in ("Passed", "Lease signed", "Closed") and is_best_fit(p) and no_price(p)]


CHECK_FIRST_TEXT = "Possible scam signs in the listing. Tour it and read the lease before you pay anything."


def check_first(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Open places flagged as a possible scam: [{"place", "text"}]. They are not best fits or new places, but never hidden."""
    return [{"place": p, "text": CHECK_FIRST_TEXT} for p in rows
            if not p["hidden"] and p["stage"] not in ("Passed", "Lease signed", "Closed") and possible_scam(p)]


def caution(place: dict[str, Any]) -> str:
    """A short caution for a place shown as a best fit: its listing has text aimed at AI tools ('' otherwise).
    A possible scam never gets here (it is not a best fit at all)."""
    return AI_TEXT_CAUTION if any("aimed at AI tools" in str(f) for f in place.get("flags") or []) else ""


NEAR_MISS_PCT = scoring.NEAR_MISS_PCT  # over the budget by less than this share counts as a near miss


def near_miss_text(place: dict[str, Any]) -> str:
    """'$5 over because pet rent counts' when the place misses a must-have by a little (under 3 percent, or a price
    rule over only because of a guess) and fails nothing else (no other deal-breaker, no scam sign), else ''.
    The same rule as the place's shared fit state (``score.fit == "near_miss"``)."""
    score = place.get("score") or {}
    if place.get("score_total") is None or possible_scam(place):
        return ""
    return "; ".join(p["text"] for p in scoring.near_parts(score, place.get("cost")))


def near_misses(rows: list[dict[str, Any]], limit: int = TOP_FITS) -> list[dict[str, Any]]:
    """Open places that fail only on cost, by under 3 percent: [{"place", "text"}], best score first."""
    out = []
    for p in rows:
        if p["hidden"] or p["stage"] in ("Passed", "Lease signed", "Closed"):
            continue
        text = near_miss_text(p)
        if text:
            out.append({"place": p, "text": text})
    out.sort(key=lambda r: (-((r["place"].get("score") or {}).get("raw_total") or 0), r["place"]["title"].lower()))
    return out[:limit]


def month_day(value: str | date) -> str:
    d = value if isinstance(value, date) else date.fromisoformat(str(value)[:10])
    return f"{_MONTHS[d.month - 1]} {d.day}" + (f", {d.year}" if d.year != helpers.today().year else "")


def _span(days: int) -> str:
    if days < 14:
        return f"{days} day{'s' if days != 1 else ''}"
    weeks = round(days / 7)
    return f"{weeks} weeks"


def availability_warning(place: dict[str, Any], search: dict[str, Any]) -> str:
    """'Available Aug 15, 2 weeks after your move-in date' when a rental opens more than 7 days after the move-in
    date of the search. Earlier or close is fine, so it returns ''. Buy searches have no such warning."""
    if search.get("mode") == "buy":
        return ""
    try:
        avail = date.fromisoformat(place.get("available_from") or "")
        move_in = date.fromisoformat(search.get("move_in") or "")
    except ValueError:
        return ""
    gap = (avail - move_in).days
    if gap <= LATE_AVAILABLE_DAYS:
        return ""
    return f"Available {month_day(avail)}, {_span(gap)} after your move-in date"


def target_date(search: dict[str, Any]) -> tuple[str, str] | None:
    """(kind, date) of the search's own target: the move-in date (rent) or the target close date (buy)."""
    if search["mode"] == "buy":
        return ("target_close", search["target_close"]) if search.get("target_close") else None
    return ("move_in_target", search["move_in"]) if search.get("move_in") else None


TARGET_LABELS = {"target_close": "Your target close date", "move_in_target": "Your move-in date"}


def apply_by_text(day: str) -> str:
    """'Apply by Fri Nov 20, in 3 days' for an application deadline."""
    return f"Apply by {helpers.day_text(day)}, {helpers.until(day)}"


def items_left_text(left: int, total: int) -> str:
    """How much of the application checklist is still to do for one place."""
    if not total:
        return ""
    if not left:
        return "Everything on your application checklist is ticked for this place."
    return f"{left} application item{'s' if left != 1 else ''} still to do for this place."


def close_tour_notes(tours: list[dict[str, Any]]) -> dict[int, str]:
    """For tours that start within 60 minutes of the one before on the same day: {tour id: note}, such as
    '10:00 AM and 10:15 AM are 15 minutes apart; check the drive'."""
    stamped = []
    for t in tours:
        local = helpers.to_local(t["starts_at"])
        if local:
            stamped.append((local, t))
    stamped.sort(key=lambda x: x[0])
    notes: dict[int, str] = {}
    for (a, ta), (b, tb) in zip(stamped, stamped[1:]):
        gap = round((b - a).total_seconds() / 60)
        if a.date() != b.date() or gap > 60:
            continue
        first, second = helpers.clock_text(ta["starts_at"]), helpers.clock_text(tb["starts_at"])
        try:
            length = int(ta.get("duration_minutes") or 30)  # a tour with no length counts as the usual 30 minutes
        except (TypeError, ValueError):
            length = 30
        if gap <= 0:
            notes[tb["id"]] = f"{first} and {second} start at the same time; check the drive"
        elif length > gap:
            notes[tb["id"]] = (f"{first} and {second} are {gap} minutes apart; check the drive. The {first} tour lasts {length} minutes, "
                               f"so the two overlap")
        else:
            notes[tb["id"]] = f"{first} and {second} are {gap} minutes apart; check the drive"
    return notes


def prep_line(tour: dict[str, Any]) -> str:
    """The tour checklist items not answered yet, as one short line ('Check water pressure, hot water and 9 more')."""
    left = [name for name, v in (tour.get("checklist") or {}).items() if not (v or {}).get("state")]
    if not left:
        return "Every checklist item is answered."
    shown = left[:3]
    more = len(left) - len(shown)
    if more > 0:
        text = ", ".join(shown) + f" and {more} more"
    elif len(shown) > 1:
        text = ", ".join(shown[:-1]) + " and " + shown[-1]
    else:
        text = shown[0]
    return f"Before you go: check {text}. The checklist is on the place page."


def checklist_applies(stage: str, mode: str) -> bool:
    """The application checklist only helps before you apply: renters at stages before Applied, buyers before an offer
    (buyers have no application checklist, so this is False for them today)."""
    order = stages.stages_for(mode)
    first_done = "Offer drafted" if mode == "buy" else "Applied"
    return stage in order and first_done in order and order.index(stage) < order.index(first_done)


def coming_up(store: Store, search: dict[str, Any], rows: list[dict[str, Any]], days: int = COMING_UP_DAYS) -> list[dict[str, Any]]:
    """Tours and key dates in the next ``days`` days, soonest first. Each: ``when`` (sort key), ``kind``, ``label``,
    ``title``, ``href``, ``date`` (YYYY-MM-DD), ``time`` (text), ``note`` and ``prep``."""
    sid = search["id"]
    out: list[dict[str, Any]] = []
    tours = store.upcoming_tours(days, search_id=sid)
    close = close_tour_notes(tours)
    for t in tours:
        d = helpers.local_date(t["starts_at"])
        local = helpers.to_local(t["starts_at"])
        out.append({"when": (d, local.strftime("%H:%M") if local else ""), "kind": "tour", "label": "Tour", "title": t["title"],
                    "href": f"/places/{t['place_id']}#tours", "date": d, "time": helpers.clock_text(t["starts_at"]),
                    "note": ("with " + t["with_whom"]) if t["with_whom"] else "", "prep": prep_line(t),
                    "warn": close.get(t["id"], "")})
    total_items = len(store.visible_checklist(search)) if search["mode"] != "buy" else 0
    by_id = {p["id"]: p["stage"] for p in rows}
    for r in store.upcoming_place_dates(days, search_id=sid):
        row = {"when": (r["date"], r["time"] or "00:00"), "kind": "key_date", "label": PLACE_DATE_LABELS.get(r["kind"], "Date"),
               "title": r["title"], "href": f"/places/{r['place_id']}#applying" if r["kind"] == "application_deadline" else f"/places/{r['place_id']}#dates",
               "date": r["date"], "time": _clock(r["time"]), "note": r["note"], "prep": ""}
        if r["kind"] == "application_deadline" and search["mode"] != "buy":
            row["text"] = apply_by_text(r["date"])
            stage = by_id.get(r["place_id"])
            if stage is None:
                try:
                    stage = store.get_place(r["place_id"])["stage"]
                except Exception:  # a place that is gone has no stage to gate on
                    stage = ""
            if checklist_applies(stage, search["mode"]):
                row["prep"] = items_left_text(store.place_checklist_left(r["place_id"]), total_items)
        out.append(row)
    for r in store.upcoming_dates(days, search_id=sid):
        out.append({"when": (r["date"], "00:00"), "kind": "place_date", "label": r["label"], "title": r["place"]["title"],
                    "href": f"/places/{r['place']['id']}", "date": r["date"], "time": "", "note": "", "prep": ""})
    target = target_date(search)
    if target:
        try:
            d = date.fromisoformat(target[1])
        except ValueError:
            d = None
        if d and helpers.today() <= d <= helpers.today() + timedelta(days=days):
            out.append({"when": (target[1], "00:00"), "kind": "target", "label": TARGET_LABELS[target[0]], "title": search["name"],
                        "href": f"/search?id={sid}", "date": target[1], "time": "", "note": "", "prep": ""})
    out.sort(key=lambda r: (r["when"], r["title"].lower()))
    return out


def _clock(value: str) -> str:
    try:
        return helpers._clock(datetime.strptime(value, "%H:%M")) if value else ""
    except ValueError:
        return ""


def waiting_rows(store: Store, search: dict[str, Any]) -> list[dict[str, Any]]:
    """Who owes a reply, in this search. Each row has ``contact`` and ``place`` (the place the last message was about,
    else the first place the person is linked to in this search; None if neither) and ``days`` (the shared count)."""
    sid = search["id"]
    out = []
    for w in store.waiting_on_reply():
        place = w["place"]
        if place is not None and place["search_id"] != sid:
            continue
        if place is None:
            linked = [p for p in store.places_for_contact(w["contact"]["id"]) if p["search_id"] == sid]
            place = linked[0] if linked else None
        out.append({**w, "place": place})
    return out


def new_places(store: Store, search: dict[str, Any]) -> list[dict[str, Any]]:
    """Places not opened yet, minus possible scams and places that don't fit (they stay on the Board)."""
    unseen = store.new_places(search["id"])
    if not unseen:
        return []
    rows = enrich.enrich_places(store, search, unseen)
    return [p for p in rows if not fails_dealbreakers(p) and not possible_scam(p)]


def late_availability(rows: list[dict[str, Any]], search: dict[str, Any], limit: int = 5) -> list[dict[str, Any]]:
    out = []
    for p in rows:
        if p["hidden"] or p["stage"] in ("Passed", "Lease signed", "Closed") or fails_dealbreakers(p) or possible_scam(p):
            continue
        msg = availability_warning(p, search)
        if msg:
            out.append({"place": p, "text": msg})
    return out[:limit]


def build(store: Store, search: dict[str, Any]) -> dict[str, Any]:
    """Everything the Today template needs for one search."""
    rows = enrich.enrich_places(store, search)
    return {"fits": best_fits(rows), "needs_price": needs_price(rows), "check_first": check_first(rows), "near_miss": near_misses(rows), "coming": coming_up(store, search, rows), "waiting": waiting_rows(store, search),
            "new": new_places(store, search), "late": late_availability(rows, search)}
