"""Stage lists for rent and buy searches. Pure: no database, no web.

The order is fixed. ``Passed`` is closed (you decided against the place), ``Lease signed`` and ``Closed`` are won.
The AI may only move a place forward or to ``Passed`` (see :func:`ai_can_move`).
"""
from __future__ import annotations

MODES: tuple[str, ...] = ("rent", "buy")
RENT_STAGES: tuple[str, ...] = ("Saved", "Contacted", "Tour booked", "Toured", "Applied", "Approved", "Lease signed", "Passed")
BUY_STAGES: tuple[str, ...] = ("Saved", "Toured", "Offer drafted", "Offer made", "Under contract", "Inspection", "Closing",
                               "Closed", "Passed")
STAGES_BY_MODE: dict[str, tuple[str, ...]] = {"rent": RENT_STAGES, "buy": BUY_STAGES}
ALL_STAGES: tuple[str, ...] = tuple(dict.fromkeys(RENT_STAGES + BUY_STAGES))
FIRST_STAGE = "Saved"
PASSED = "Passed"
WON_STAGES: tuple[str, ...] = ("Lease signed", "Closed")
CLOSED_STAGES: tuple[str, ...] = (PASSED,) + WON_STAGES

_ALIASES = {
    "new": "Saved", "saved": "Saved", "bookmarked": "Saved", "shortlist": "Saved", "interested": "Saved",
    "contacted": "Contacted", "emailed": "Contacted", "reached out": "Contacted", "asked": "Contacted",
    "tour booked": "Tour booked", "tour scheduled": "Tour booked", "scheduled": "Tour booked", "booked": "Tour booked",
    "toured": "Toured", "visited": "Toured", "seen": "Toured", "saw it": "Toured",
    "applied": "Applied", "application": "Applied", "application sent": "Applied",
    "approved": "Approved", "accepted": "Approved",
    "lease signed": "Lease signed", "signed": "Lease signed", "leased": "Lease signed", "won": "Lease signed",
    "offer drafted": "Offer drafted", "offer made": "Offer made", "offered": "Offer made",
    "under contract": "Under contract", "in contract": "Under contract", "accepted offer": "Under contract",
    "inspection": "Inspection", "closing": "Closing", "closed": "Closed", "bought": "Closed",
    "passed": PASSED, "pass": PASSED, "rejected": PASSED, "no": PASSED, "dropped": PASSED, "ruled out": PASSED,
}


def stages_for(mode: str) -> tuple[str, ...]:
    """The stage list of a mode ("rent" or "buy"). Unknown modes get the rent list."""
    return STAGES_BY_MODE.get(mode, RENT_STAGES)


def normalize_stage(mode: str, text: object) -> str | None:
    """The stage a person or an AI meant ("Tour scheduled" -> "Tour booked"), valid for ``mode``, or None."""
    stages = stages_for(mode)
    raw = " ".join(str(text or "").split())
    for s in stages:
        if s.lower() == raw.lower():
            return s
    alias = _ALIASES.get(raw.lower())
    return alias if alias in stages else None


def stage_index(mode: str, stage: str) -> int:
    """Position in the mode's list; -1 for a stage that mode doesn't have."""
    stages = stages_for(mode)
    return stages.index(stage) if stage in stages else -1


def is_closed(stage: str) -> bool:
    return stage in CLOSED_STAGES


def is_won(stage: str) -> bool:
    return stage in WON_STAGES


def is_forward(mode: str, old: str, new: str) -> bool:
    """True when ``new`` is later in the list than ``old``."""
    return stage_index(mode, new) > stage_index(mode, old) >= 0


def ai_can_move(mode: str, old: str, new: str) -> bool:
    """The AI rule: forward, or to Passed. Never backward, never out of Passed."""
    if new == old:
        return True
    if old == PASSED:
        return False
    return new == PASSED or is_forward(mode, old, new)


def stage_slug(stage: str | None) -> str:
    """'Tour booked' -> 'tour-booked' (a CSS class suffix)."""
    return "-".join(str(stage or "Saved").lower().split())
