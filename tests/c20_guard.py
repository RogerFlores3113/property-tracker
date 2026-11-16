"""Cycle 20 no-silent-drop guard over the reviewers' saved listings (panel/r*-l*.txt; files that fail to read are skipped).

Every dollar figure must be placed in a field, explained by a note, a known non-cost, or the rent. ``reader_drops()`` runs the readers with the
final guard switched off to list what they leave out on their own; ``guard_leaks()`` runs the full parse and must find nothing.

Cycle 22 adds three checks, all reported by ``run_all``: a percent the listing gives for money (a seller credit "2% toward closing costs", a broker
fee "5% of annual rent") that no field holds and no note quotes; a figure inside a sentence aimed at an AI tool or with a link that is neither
placed nor quoted (the dollar check already sees it, the hostile text no longer hides it); and a summed field (move-in fees, other monthly fees)
whose value no combination of the listing's figures adds up to (a figure read twice)."""
from __future__ import annotations

import os
import re

from prophelper import dropguard
from prophelper import parsers as P

PANEL = os.environ.get("PH_PANEL", "/tmp/claude-0/-home-user-property-helper/be454331-cd61-59ba-9ebc-8cb8b7ec6a12/scratchpad/panel")
_NAME = re.compile(r"r\d+-[a-z]+-(?:l|listing|L|paste|p)\d+[a-z]?\.txt$")


def listings(include_buyer: bool = False) -> list[tuple[str, str]]:
    out = []
    try:
        names = sorted(f for f in os.listdir(PANEL) if _NAME.match(f) and (include_buyer or "buyer" not in f))
    except OSError:
        return out
    for f in names:
        try:
            text = open(os.path.join(PANEL, f), encoding="utf-8").read()
            if "\n====" not in text:  # a paste of several places is not one listing
                out.append((f, text))
        except (OSError, UnicodeDecodeError):
            continue
    return out


def unaccounted(text: str, guard: bool) -> list[str]:
    dropguard.ENABLED = guard
    try:
        r = P.parse_listing(text, "")
    finally:
        dropguard.ENABLED = True
    return [f"${h['amount']:g} [{h['kind']}] {h['item'][:100]}" for h in dropguard.find_unplaced(text, r, str(r.get("found_in_listing") or ""))]


def percent_and_double(text: str, guard: bool) -> list[str]:
    """Percent figures with no field and no note, and summed fields that count a figure twice. Buyer listings are included."""
    dropguard.ENABLED = guard
    try:
        r = P.parse_listing(text, "")
    finally:
        dropguard.ENABLED = True
    notes = str(r.get("found_in_listing") or "")
    bad = [f"{h['pct']:g}% [percent] {h['item'][:100]}" for h in dropguard.find_unplaced_percent(text, r, notes)]
    bad += [f"[double count] {x}" for x in dropguard.overcounted(text, r)] if "buyer" not in text[:0] else []
    return bad


def run_all(guard: bool) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for f, text in listings(include_buyer=True):
        try:
            bad = [] if "buyer" in f else unaccounted(text, guard)
            bad += percent_and_double(text, guard)
        except Exception as e:  # noqa: BLE001
            bad = [f"ERROR {e!r}"]
        if bad:
            out[f] = bad
    return out


if __name__ == "__main__":
    for guard in (False, True):
        res = run_all(guard)
        print("== guard", "on" if guard else "off (reader drops)")
        for f, bad in res.items():
            print(f)
            for b in bad:
                print("   ", b)
        print(len(res), "listings;", sum(len(v) for v in res.values()), "figures")
