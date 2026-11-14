"""The gap between when a rental opens and the search's move-in date, in plain words, both ways.

``today.availability_warning`` only speaks when a place opens late. This helper also speaks when it opens early (you
would pay rent for weeks before you move in), so the Place page and Claude's tools say the same thing.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from . import today

GAP_DAYS = today.LATE_AVAILABLE_DAYS  # more than this many days either way is worth saying


def gap_warning(place: dict[str, Any], search: dict[str, Any]) -> str:
    """'Available Jul 1, 6 weeks before your move-in date' or '..., 4 weeks after your move-in date'; '' when the dates
    are within a week of each other, missing, or the search is a purchase."""
    late = today.availability_warning(place, search)
    if late or search.get("mode") == "buy":
        return late
    try:
        avail = date.fromisoformat(place.get("available_from") or "")
        move_in = date.fromisoformat(search.get("move_in") or "")
    except ValueError:
        return ""
    early = (move_in - avail).days
    if early <= GAP_DAYS:
        return ""
    return f"Available {today.month_day(avail)}, {today._span(early)} before your move-in date"
