"""Cycle 20 no-silent-drop guard over the reviewers' saved listings (panel/r*-l*.txt; files that fail to read are skipped).

Every dollar figure must be placed in a field, explained by a note, a known non-cost, or the rent. ``reader_drops()`` runs the readers with the
final guard switched off to list what they leave out on their own; ``guard_leaks()`` runs the full parse and must find nothing."""
from __future__ import annotations

import os
import re

from prophelper import dropguard
from prophelper import parsers as P

PANEL = os.environ.get("PH_PANEL", "/tmp/claude-0/-home-user-property-helper/be454331-cd61-59ba-9ebc-8cb8b7ec6a12/scratchpad/panel")
_NAME = re.compile(r"r\d+-[a-z]+-(?:l|listing|L|paste|p)\d+[a-z]?\.txt$")


def listings() -> list[tuple[str, str]]:
    out = []
    try:
        names = sorted(f for f in os.listdir(PANEL) if _NAME.match(f) and "buyer" not in f)
    except OSError:
        return out
    for f in names:
        try:
            out.append((f, open(os.path.join(PANEL, f), encoding="utf-8").read()))
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


def run_all(guard: bool) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for f, text in listings():
        try:
            bad = unaccounted(text, guard)
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
