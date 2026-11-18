"""A small iCalendar (RFC 5545) writer for the calendar export. Pure: no database, no web.

Items are plain dicts (see :func:`build_calendar`). Text is escaped, lines end in CRLF and long lines are folded at
75 bytes. Notes, ratings and contact details are never written: only the title, the place, who the tour is with and
the time, so the file is safe to open in another calendar app.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from .store import parse_iso

CAL_NAME = "Property Helper"
LEFT_OUT = "Notes, ratings and contact details are left out of this file."


def escape_text(value: Any) -> str:
    """Escape a TEXT value: backslash, semicolon, comma and newlines."""
    return (str(value or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\r", "\\n").replace("\n", "\\n"))


def fold(line: str) -> list[str]:
    """Split one content line into physical lines of at most 75 bytes; continuations start with one space.
    Never cuts a multi-byte character in half."""
    out: list[str] = []
    cur, size = "", 0
    for ch in line:
        n = len(ch.encode("utf-8"))
        if size + n > 75:
            out.append(cur)
            cur, size = " ", 1
        cur += ch
        size += n
    out.append(cur)
    return out


def _date_or_none(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def _utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _floating(dt: datetime) -> str:
    """Local wall-clock time with no zone and no Z, so a 10:00 tour shows at 10:00 in any calendar app."""
    return dt.astimezone().strftime("%Y%m%dT%H%M%S")


def _day(d: date) -> str:
    return d.strftime("%Y%m%d")


def build_calendar(items: list[dict[str, Any]], now: datetime | None = None) -> str:
    """The .ics text for a list of items.

    Each item: ``uid`` (a stable text such as ``tour-4``), ``summary``, optional ``description`` and ``location``,
    optional ``updated`` (the row's own saved time, used for DTSTAMP so the same data gives the same file), and
    either ``starts_at`` (a stored UTC timestamp) with optional ``duration_minutes`` for a timed event, or ``date``
    (``YYYY-MM-DD``) for an all-day event. Timed events are written as floating local time (no trailing Z, the
    wall-clock time on this computer), all-day ones as DATE values. Only DTSTAMP is UTC, as the format requires. An item that can't be read is skipped, so one bad row never breaks the file.
    """
    now = now or datetime.now(timezone.utc)
    lines: list[str] = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Property Helper//EN", "CALSCALE:GREGORIAN",
                        f"X-WR-CALNAME:{CAL_NAME}", "X-WR-CALDESC:" + escape_text(LEFT_OUT)]
    for it in items:
        uid = str(it.get("uid") or "").strip()
        if not uid:
            continue
        stamp = parse_iso(it.get("updated")) or now
        if it.get("starts_at"):
            start = parse_iso(it["starts_at"])
            if start is None:
                continue
            end = start + timedelta(minutes=int(it.get("duration_minutes") or 30))
            when = [f"DTSTART:{_floating(start)}", f"DTEND:{_floating(end)}"]
        else:
            d = _date_or_none(it.get("date"))
            if d is None:
                continue
            when = [f"DTSTART;VALUE=DATE:{_day(d)}", f"DTEND;VALUE=DATE:{_day(d + timedelta(days=1))}"]
        props = [f"UID:{uid}@property-helper.local", f"DTSTAMP:{_utc(stamp)}", *when,
                 f"SUMMARY:{escape_text(it.get('summary', ''))}"]
        if it.get("description"):
            props.append(f"DESCRIPTION:{escape_text(it['description'])}")
        if it.get("location"):
            props.append(f"LOCATION:{escape_text(it['location'])}")
        if not it.get("starts_at"):
            props.append("TRANSP:TRANSPARENT")
        lines.extend(["BEGIN:VEVENT", *props, "END:VEVENT"])
    lines.append("END:VCALENDAR")
    return "".join(piece + "\r\n" for line in lines for piece in fold(line))
