"""Small pure functions the templates and routers share: dates on this computer's clock, "N days ago", money and
numbers as plain words. No database access here."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from .stages import stage_slug  # noqa: F401  (re-exported for templates)
from .store import parse_iso

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def today() -> date:
    return date.today()


def to_local(value: str | datetime | None) -> datetime | None:
    """A stored timestamp as a datetime on this computer's clock, or None."""
    dt = value if isinstance(value, datetime) else parse_iso(value)
    return dt.astimezone() if dt else None


def local_date(value: str | datetime | None) -> str:
    """'2026-11-06': the day on this computer's clock (a plain stored date stays as it is)."""
    if isinstance(value, str) and len(value) == 10:
        return value
    dt = to_local(value)
    return dt.date().isoformat() if dt else ""


def _clock(dt: datetime) -> str:
    hour = dt.hour % 12 or 12
    return f"{hour}:{dt.minute:02d} {'AM' if dt.hour < 12 else 'PM'}"


def day_text(value: str | date | datetime | None, year: bool | None = None) -> str:
    """'Fri Nov 6' for a date or timestamp (the year is added when it is not this year)."""
    if isinstance(value, str) and len(value) == 10:
        try:
            d = date.fromisoformat(value)
        except ValueError:
            return value
    elif isinstance(value, datetime):
        d = (value.astimezone() if value.tzinfo else value).date()
    elif isinstance(value, date):
        d = value
    else:
        dt = to_local(value)
        if not dt:
            return ""
        d = dt.date()
    show_year = year if year is not None else d.year != today().year
    return f"{_DAYS[d.weekday()]} {_MONTHS[d.month - 1]} {d.day}" + (f", {d.year}" if show_year else "")


def local_time(value: str | datetime | None) -> str:
    """'Fri Nov 6, 2:30 PM' on this computer's clock; blank for nothing."""
    dt = to_local(value)
    return f"{day_text(dt)}, {_clock(dt)}" if dt else ""


def clock_text(value: str | datetime | None) -> str:
    dt = to_local(value)
    return _clock(dt) if dt else ""


def input_datetime(value: str | None) -> str:
    """A stored UTC time as the value of an <input type=datetime-local> (local, no zone)."""
    dt = to_local(value)
    return dt.strftime("%Y-%m-%dT%H:%M") if dt else ""


def days_since(value: str | datetime | None, now: datetime | None = None) -> int | None:
    dt = to_local(value)
    if not dt:
        return None
    ref = (now or datetime.now(timezone.utc)).astimezone().date()
    return (ref - dt.date()).days


def ago(value: str | datetime | None, now: datetime | None = None) -> str:
    """'today', 'yesterday', '3 days ago', '2 months ago'; 'upcoming' for the future; 'never' for blank."""
    n = days_since(value, now)
    if n is None:
        return "never"
    if n < 0:
        return "upcoming"
    if n == 0:
        return "today"
    if n == 1:
        return "yesterday"
    if n < 60:
        return f"{n} days ago"
    if n < 730:
        return f"{n // 30} months ago"
    return f"{n // 365} years ago"


def until(value: str | date | None, today_: date | None = None) -> str:
    """For a date: 'today', 'tomorrow', 'in 3 days', '2 days ago', 'yesterday'. Blank for nothing."""
    if not value:
        return ""
    try:
        d = value if isinstance(value, date) and not isinstance(value, datetime) else date.fromisoformat(str(value)[:10])
    except ValueError:
        return ""
    n = (d - (today_ or today())).days
    if n == 0:
        return "today"
    if n == 1:
        return "tomorrow"
    if n == -1:
        return "yesterday"
    return f"in {n} days" if n > 0 else f"{-n} days ago"


def days_in_stage(place: dict[str, Any]) -> int:
    n = days_since(place.get("stage_changed_at") or place.get("created_at"))
    return max(0, n or 0)


def number_text(value: Any) -> str:
    """1,234 for a whole number; 1,234.5 otherwise; blank for nothing."""
    if value is None or value == "":
        return ""
    try:
        n = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{n:,.0f}" if abs(n - round(n)) < 1e-9 else f"{n:,.1f}"


def money(amount: int | float | None, cents: bool = False) -> str:
    """$1,450 (or $1,450.25 when cents); blank for nothing."""
    if amount is None or amount == "":
        return ""
    try:
        n = float(amount)
    except (TypeError, ValueError):
        return str(amount)
    return f"${n:,.2f}" if cents else f"${n:,.0f}"


def beds_text(beds: Any) -> str:
    if beds is None or beds == "":
        return ""
    return "Studio" if float(beds) == 0 else f"{number_text(beds)} bed"


def place_line(place: dict[str, Any]) -> str:
    """'1 bed, 1 bath, 650 sq ft' from whatever is filled in."""
    bits = []
    if place.get("beds") is not None:
        bits.append(beds_text(place["beds"]))
    if place.get("baths") is not None:
        bits.append(f"{number_text(place['baths'])} bath")
    if place.get("sqft"):
        bits.append(f"{number_text(place['sqft'])} sq ft")
    return ", ".join(bits)


def month_start(d: date) -> date:
    return d.replace(day=1)


def add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    return date(d.year + m // 12, m % 12 + 1, 1)


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def write_new_file(target, data: bytes):
    """Write ``data`` to ``target`` without ever replacing anything: if the name is taken (even by a dangling link),
    a number is added ("name-2.ext"). The file is created exclusively, so nothing is followed or overwritten.
    Returns the path written. The folder is made if needed."""
    from pathlib import Path

    first = Path(target)
    first.parent.mkdir(parents=True, exist_ok=True)
    path, n = first, 2
    while True:
        try:
            with open(path, "xb") as fh:
                fh.write(data)
            return path
        except FileExistsError:
            path = first.with_name(f"{first.stem}-{n}{first.suffix}")
            n += 1
            if n > 10_000:
                raise OSError("Too many files with that name") from None


def host_of(url: str) -> str:
    from urllib.parse import urlsplit

    try:
        host = urlsplit(url or "").hostname or ""
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host
