"""What the Today page shows: the best fits right now, what is coming up (with a short prep line), new places worth a look,
and who still owes a reply. Reads the store and ``enrich``; writes nothing.

Rules (see the product decisions): a place counts as a fit when it has a score, passes every deal-breaker and has no
high-severity red flag. A place that doesn't fit, or that may be a scam, stays on the Board but never shows under
"Best fits" or "New places".
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

from . import compare, enrich, helpers, redflags, scoring, stages
from . import money as money_mod
from .store import PLACE_DATE_LABELS, Store

COMING_UP_DAYS = 14
TOP_FITS = 3
CHECK_FIRST_SHOWN = 5  # the Check first section is capped like the others; the shared advice is said once
LATE_AVAILABLE_DAYS = 7  # available_from more than this many days after the move-in date is a warning
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def possible_scam(place: dict[str, Any], high_messages: Any = None) -> bool:
    """True when the place is a possible scam. One rule, ``redflags.is_serious`` (enrich stores the answer on the place)."""
    if "possible_scam" in place:
        return bool(place["possible_scam"])
    return redflags.is_serious(place)


def scam_hint_or_low_rent(place: dict[str, Any]) -> bool:
    """True when a place has any scam hint (a "check first" sign, serious or not) or the very-low-rent warning. Such a place is
    never listed as a "fit so far" under a cost check: it shows under Check first or New places instead."""
    if possible_scam(place) or redflags.scam_sign_flags(place.get("flags") or []):
        return True
    return bool(low_rent(place))


def fails_dealbreakers(place: dict[str, Any]) -> bool:
    score = place.get("score") or {}
    if score.get("passes") is False or score.get("dealbroken"):
        return True
    return bool(score.get("fails_dealbreaker") or place.get("hidden_by_dealbreaker"))


# A place that is passed, won or already under contract is not a pick any more: Today never suggests it.
OFF_THE_MARKET = ("Passed", "Lease signed", "Closed", "Under contract", "Inspection", "Closing")
MIN_FIT_SCORE = 60  # "Best fits" needs a reasonable score as well as every must-have


def fits(place: dict[str, Any], high_messages: Any = None) -> bool:
    return place.get("score_total") is not None and not fails_dealbreakers(place) and not possible_scam(place)


def hard_limit_failed(place: dict[str, Any]) -> bool:
    """True when a hard limit (a commute the searcher set as hard) is failed: list_places and Compare say FAILS for it."""
    return any(i.get("hard") and i.get("dealbreaker_status") == "fail" for i in (place.get("score") or {}).get("items") or [])


def is_near(place: dict[str, Any]) -> bool:
    """A must-have is missed by a little (only because of a guess): a near miss, so not a best fit."""
    score = place.get("score") or {}
    return bool(score.get("near")) or score.get("fit") == "near_miss"


def ai_text_only(place: dict[str, Any]) -> bool:
    """True when the only thing to check in the listing is text aimed at AI tools (no scam sign)."""
    return compare.ai_text_only(place)


_UTILITY_CONFLICT = re.compile(r"(?:utilit|electric|heat|water|gas)[\s\S]{0,300}\b(?:(?:do|does)(?: not|n'?t) agree|conflict\w*|contradict\w*|disagree\w*)|"
                               r"\b(?:(?:do|does)(?: not|n'?t) agree|conflict\w*|contradict\w*|disagree\w*)\b[\s\S]{0,300}(?:utilit|electric|heat|water|gas)", re.I)


_TENANT_PAYS_UTILITIES = re.compile(r"\b(?:tenants?|renters?|residents?|you)\s+(?:will\s+)?(?:pays?|are responsible for|is responsible for)\s+(?:for\s+)?(?:all\s+|the\s+|your\s+|own\s+)*(?:utilit|electric|gas\b|water|bills)|"
                                    r"\butilities\s+(?:are\s+)?(?:extra|not included|separate|paid by (?:the )?(?:tenant|renter|resident))\b|\b(?:plus|\+)\s+utilities\b", re.I)


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _utility_names(entry: str) -> list[str]:
    """'utilities (electric, gas and water)' -> ['electric', 'gas', 'water']; a bare 'utilities' gives []."""
    m = re.match(r"utilities \((.*)\)\s*$", entry, re.I)
    return [n.strip() for n in re.split(r",|\band\b", m.group(1)) if n.strip()] if m else []


def over_budget(place: dict[str, Any]) -> float:
    """How many dollars the place is over the search's price limit (0 when it is within it or the price rule can't tell).
    Read from the score, so it holds whether or not price is a must-have."""
    for item in (place.get("score") or {}).get("items") or []:
        if item.get("kind") == "price" and (item.get("over_amount") or 0) > 0 and item.get("passes") is False:
            return float(item["over_amount"])
    return 0.0


LOW_INSURANCE_YEARLY = 300  # a house is never insured for less than about this much a year


def low_insurance(place: dict[str, Any]) -> str:
    """'' or a plain check note when a bought place's yearly insurance is far below normal (under about $300 for a house)."""
    cost = place.get("cost") or {}
    if cost.get("mode") != "buy":
        return ""
    try:
        ins = float(place.get("insurance"))
    except (TypeError, ValueError):
        return ""
    if ins <= 0 or ins >= LOW_INSURANCE_YEARLY:
        return ""
    return (f"the insurance of ${ins:,.0f} a year is far below normal for a house, so the monthly cost looks too low. "
            "Confirm the real quote before you count on it")


LOW_RENT_MONTHLY = 200  # a rental is never listed for less than about this much a month


def low_rent(place: dict[str, Any], mode: str | None = None) -> str:
    """'' or a plain check note when a rental's monthly rent is implausibly low (under about $200, or low for its bed count, the
    search's limit or the place's other monthly costs): a typo, a misread or a placeholder. The same rule as the score's ``rent_check``."""
    mode = mode or (place.get("cost") or {}).get("mode") or "rent"
    if mode == "buy":
        return ""
    return str((place.get("score") or {}).get("rent_check") or "") or scoring.rent_looks_low(place, place.get("cost"), None, mode)


def cost_unsettled(place: dict[str, Any]) -> str:
    """Why a place's monthly cost can't be trusted for a ranking, in plain words ('' when it can). Rent: the listing's utilities
    lines disagree (so none are counted), a utility the tenant pays has no amount, or two or more parts of the monthly cost
    are unknown (utilities, parking, pet rent for a search with pets). Buy: two or more of property tax, insurance and HOA
    are unknown. A place with only one unknown part still ranks, after the complete ones."""
    cost = place.get("cost") or {}
    if not cost:
        return ""
    unc = [str(u).lower() for u in cost.get("uncounted") or []]
    if cost.get("mode") == "buy":
        left = [n for n, keys in (("property tax", ("property tax", "tax")), ("insurance", ("insurance",)), ("HOA", ("hoa",)))
                if any(u in keys for u in unc)]
        low = low_insurance(place)
        if low:
            return low
        return f"{_join(left)} are not counted yet" if len(left) >= 2 else ""
    if (low := low_rent(place)):
        return low
    notes = " ".join(str(place.get(k) or "") for k in ("reader_notes", "ai_notes"))
    utilities = [u for u in unc if u.startswith("utilities")]
    if utilities and _UTILITY_CONFLICT.search(notes):
        return "the listing's utilities lines don't agree, so no utilities are counted"
    named = [n for u in utilities for n in _utility_names(u)]
    gives_amounts = bool(compare.cost_may_be_higher(place))  # the listing states amounts that the reader did not place
    if named:
        if gives_amounts:
            return f"you pay {_join(named)} and the listing gives amounts that were not read"
        return f"you pay {_join(named)} but no amount is counted yet"
    if utilities and _TENANT_PAYS_UTILITIES.search(" ".join(str(place.get(k) or "") for k in ("listing_text", "reader_notes", "ai_notes", "notes"))):
        if gives_amounts:
            return "you pay the utilities and the listing gives amounts that were not read"
        return "you pay the utilities but no amount is counted yet"  # the whole utilities bill is unknown
    parts = []
    if utilities:
        parts.append("utilities")
    if any(u.startswith("parking") for u in unc):
        parts.append("parking")
    if compare.pet_rent_unset(place):
        parts.append("pet rent")
    if len(parts) >= 2:
        return f"{_join(parts)} are not counted yet"
    return ""


INSURANCE_NOT_FILLED = "insurance not filled in yet"


def insurance_only_unknown(place: dict[str, Any]) -> bool:
    """Cycle 28: a buy place whose only unknown cost part is home insurance. A buyer rarely has a quote at the first look, so such a
    place may show under Best fits, marked "insurance not filled in yet", and its monthly cost stays marked not complete."""
    return (place.get("cost") or {}).get("mode") == "buy" and unknown_cost_parts(place) == ["insurance"]


def is_best_fit(place: dict[str, Any]) -> bool:
    return (fits(place) and place["score_total"] >= MIN_FIT_SCORE and not is_near(place) and not ai_text_only(place) and not cost_unsettled(place)
            and not over_budget(place) and (not unknown_cost_parts(place) or insurance_only_unknown(place)) and not compare.cash_left_out(place)
            and not (place.get("score") or {}).get("lease_gap"))  # one rule: an unknown cost part is never a best fit


def best_fits(rows: list[dict[str, Any]], limit: int = TOP_FITS) -> list[dict[str, Any]]:
    """The top places by score that fit. ``rows`` are enriched places. Passed, won and hidden places are skipped."""
    open_rows = [p for p in rows if not p["hidden"] and p["stage"] not in OFF_THE_MARKET and is_best_fit(p)
                 and not no_price(p)]
    # a place whose cost leaves listed amounts out never ranks above a complete place (its price is only as low as what was read)
    open_rows.sort(key=lambda p: ((p.get("score") or {}).get("sort_group", 0), bool(compare.cost_may_be_higher(p)), insurance_only_unknown(p), -p["score_total"], _cost_key(p), p["title"].lower()))
    if open_rows and _no_address(open_rows[0]):  # a place with no address is never the top pick when another full fit has one
        i = next((i for i, p in enumerate(open_rows) if not _no_address(p)), None)
        if i is not None:
            open_rows.insert(0, open_rows.pop(i))
    top = open_rows[:limit]
    for p in top:
        p["caution"] = caution(p)
    return top


def _cost_key(place: dict[str, Any]) -> tuple[bool, float]:
    """Tie-break for places with the same score: a complete cost before one with unknown parts, then the lowest monthly cost
    first; a place with no cost sorts last."""
    try:
        total = float(place.get("cost_total"))
    except (TypeError, ValueError):
        total = float("inf")
    return (bool((place.get("cost") or {}).get("uncounted")), total)


def _no_address(place: dict[str, Any]) -> bool:
    return not str(place.get("address") or "").strip()


AI_TEXT_CAUTION = "Check first: text aimed at AI tools in the listing. Read it yourself before you rely on this score."


def no_price(place: dict[str, Any]) -> bool:
    """True when a place has no rent (or, buying, no price), so it can't be ranked as a best fit. Rows made by hand
    without a ``cost_total`` are treated as priced."""
    return "cost_total" in place and place["cost_total"] is None


def _open(p: dict[str, Any]) -> bool:
    return not p["hidden"] and p["stage"] not in OFF_THE_MARKET


def needs_price(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Open places with no rent or price yet that fit so far (a score, no failed must-have, no scam or AI-text sign).
    A no-price place always lands here, whatever else is still unknown about it, so it never drops out of Today."""
    return [p for p in rows if _open(p) and fits(p) and not ai_text_only(p) and no_price(p)]


CHECK_FIRST_TEXT = "Possible scam signs in the listing. Tour it and read the lease before you pay anything."
CHECK_FIRST_BUY_TEXT = "Possible scam signs in the listing. See it in person and read the contract, and use escrow, before you send any money."
AI_TEXT_CHECK_TEXT = "Text aimed at AI tools in the listing. Read it yourself before you rely on this score."


def check_first(rows: list[dict[str, Any]], mode: str = "rent") -> list[dict[str, Any]]:
    """Open places flagged as a possible scam, or whose only flag is text aimed at AI tools: [{"place", "text"}].
    They are not best fits or new places, but never hidden."""
    scam_text = CHECK_FIRST_BUY_TEXT if mode == "buy" else CHECK_FIRST_TEXT
    out = []
    for p in rows:
        if not _open(p):
            continue
        if possible_scam(p):
            out.append({"place": p, "text": _own_reason(p, scam_text), "own": own_reason_only(p), "scam": True})
        elif ai_text_only(p):
            first = next((str(f) for f in p.get("flags") or [] if f), "")
            generic = "Read it yourself before you rely on this score." if "aimed at AI tools" in first else AI_TEXT_CHECK_TEXT
            out.append({"place": p, "text": _own_reason(p, generic), "own": own_reason_only(p), "scam": False})
        elif not fails_dealbreakers(p) and scam_hint_or_low_rent(p):
            # cycle 26: a place left out of every other list for a scam hint or a rent that looks too low must still show somewhere
            low = low_rent(p)
            text = (("Check the rent first: " + low[0].upper() + low[1:] + ".") if low
                    else _own_reason(p, "Read it yourself and ask for the exact address before you pay anything."))
            out.append({"place": p, "text": text, "own": text, "scam": False})
    out.sort(key=lambda r: (not r["scam"], r["place"]["title"].lower()))  # possible scams first, then by name
    return out


def own_reason_only(place: dict[str, Any]) -> str:
    """Cycle 27: just this place's own reason (its one or two flag sentences), with no shared advice sentence, so a list of many
    check-first places does not repeat the same advice on every row. '' when the place has no flag sentence of its own."""
    reasons: list[str] = []
    for f in [str(f) for f in redflags.scam_sign_flags(place.get("flags") or []) if f]:
        r = redflags.short_reason(f)
        if r not in reasons:
            reasons.append(r)
    return " ".join(reasons[:2])


def _own_reason(place: dict[str, Any], generic: str, first: str = "") -> str:
    """A short reason for this place: the first sentence of its one or two own flags (the full text stays on the place page),
    so check-first places can be told apart. With no flag, the plain advice."""
    if first:
        return f"{first} {generic}"
    flags = [str(f) for f in redflags.scam_sign_flags(place.get("flags") or []) if f]
    reasons: list[str] = []
    for f in flags:
        r = redflags.short_reason(f)
        if r not in reasons:
            reasons.append(r)
    if not reasons:
        return generic
    advice = generic.split(". ", 1)[1] if generic.startswith("Possible scam signs in the listing. ") else generic
    return " ".join(reasons[:2]) + " " + advice


def caution(place: dict[str, Any]) -> str:
    """A short caution for a place shown as a best fit: its listing has text aimed at AI tools ('' otherwise).
    A possible scam never gets here (it is not a best fit at all)."""
    parts = [AI_TEXT_CAUTION] if any("aimed at AI tools" in str(f) for f in place.get("flags") or []) else []
    higher = compare.cost_may_be_higher(place)
    if higher:
        parts.append(higher)
    if insurance_only_unknown(place):
        parts.append("Home " + INSURANCE_NOT_FILLED + ", so the monthly cost is not complete.")
    return " ".join(parts)


NEAR_MISS_PCT = scoring.NEAR_MISS_PCT  # over the budget by less than this share counts as a near miss


def near_miss_text(place: dict[str, Any]) -> str:
    """'$5 over because pet rent counts' when the place misses a must-have by a little (under 3 percent, or a price
    rule over only because of a guess) and fails nothing else (no other deal-breaker, no scam sign), else ''.
    The same rule as the place's shared fit state (``score.fit == "near_miss"``)."""
    score = place.get("score") or {}
    if place.get("score_total") is None or possible_scam(place):
        return ""
    text = "; ".join(p["text"] for p in scoring.near_parts(score, place.get("cost")))
    if not text and not fails_dealbreakers(place) and (over := over_budget(place)):
        cost = place.get("cost") or {}
        lead = "at least " if cost.get("uncounted") or cost.get("missing") else ""
        text = f"{lead}${over:,.0f} over your budget{scoring._still_unknown(cost) if lead else ''} (price is not a must-have for you)"  # a place over budget is never a best fit
    return text


def near_misses(rows: list[dict[str, Any]], limit: int = TOP_FITS) -> list[dict[str, Any]]:
    """Open places that fail only on cost, by under 3 percent: [{"place", "text"}], best score first."""
    out = []
    for p in rows:
        if p["hidden"] or p["stage"] in OFF_THE_MARKET:
            continue
        text = near_miss_text(p)
        if text:
            out.append({"place": p, "text": text})
    out.sort(key=lambda r: (-((r["place"].get("score") or {}).get("raw_total") or 0), r["place"]["title"].lower()))
    return out[:limit]


def closest(rows: list[dict[str, Any]], limit: int = TOP_FITS) -> list[dict[str, Any]]:
    """When no place is a best fit: the open places that come closest, up to ``limit``: [{"place", "text"}]. Each missed
    a must-have (by a little or a lot) but is no possible scam and has no text aimed at AI tools; they are ranked by the
    shared score (which already falls the further a place misses) and ``text`` is the plain one-line reason."""
    out = []
    for p in rows:
        score = p.get("score") or {}
        if not _open(p) or p.get("score_total") is None or possible_scam(p) or ai_text_only(p):
            continue
        if score.get("fit") not in ("near_miss", "doesnt_fit"):
            continue
        if hard_limit_failed(p):
            continue  # a hard limit is a fail at any minute over, never a near miss
        reasons = [str(r) for r in score.get("fit_reasons") or [] if r]
        out.append({"place": p, "text": "; ".join(reasons) or "Misses a must-have."})
    out.sort(key=lambda r: (-r["place"]["score_total"], _cost_key(r["place"]), r["place"]["title"].lower()))
    return out[:limit]


UNCONFIRMED_TEXT = "Nothing is confirmed yet. These fit if the unknowns check out:"


def unconfirmed(rows: list[dict[str, Any]], limit: int = TOP_FITS) -> list[dict[str, Any]]:
    """When no place is a best fit: open places that fit so far ("Fits" or "Fits, but check") but have unknowns or things
    to check, so they are not confirmed: [{"place", "text"}], best score first. Not scams, not text aimed at AI tools,
    not unpriced (those are under "Needs a price")."""
    out = []
    for p in rows:
        score = p.get("score") or {}
        if (not _open(p) or not fits(p) or score.get("fit") != "fits" or ai_text_only(p) or scam_hint_or_low_rent(p) or no_price(p) or is_best_fit(p) or over_budget(p)
                or (p["score_total"] >= MIN_FIT_SCORE and not is_near(p) and (cost_unsettled(p) or unknown_cost_parts(p)))):  # these show under "Needs a cost check"
            continue
        bits = [f"{n} not known yet" for n in score.get("unknown") or []] + [str(c) for c in score.get("concerns") or []]
        if (why := cost_unsettled(p)):
            bits.append("monthly cost not settled: " + why)
        out.append({"place": p, "text": "; ".join(bits) or "Check the details on its page."})
    out.sort(key=lambda r: (-r["place"]["score_total"], _cost_key(r["place"]), r["place"]["title"].lower()))
    return out[:limit]


def cost_check(rows: list[dict[str, Any]], also: Any = ()) -> list[dict[str, Any]]:
    """Open places with an unknown or conflicting part in their monthly cost: [{"place", "text"}], best score first.
    One rule: such a place is never in "Best fits" and always here, whatever other list it is in (Closest, Near miss).
    ``also`` holds ids of places shown under "Closest", which count even when they miss a must-have by a lot."""
    out = []
    also = set(also)
    for p in rows:
        if not _open(p) or p.get("score_total") is None or possible_scam(p) or ai_text_only(p) or no_price(p) or scam_hint_or_low_rent(p):
            continue
        if fails_dealbreakers(p) or over_budget(p) or hard_limit_failed(p):
            continue  # a place that already fails a must-have or the budget is no "fit so far": it can only be a near miss
        fit = (p.get("score") or {}).get("fit")
        if not (fit in ("fits", "near_miss") or is_near(p) or over_budget(p) or p.get("id") in also):
            continue
        why = cost_unsettled(p) if (fit == "fits" and not is_near(p) and p["score_total"] >= MIN_FIT_SCORE and not over_budget(p)) else ""
        parts = unknown_cost_parts(p)
        if not why and not parts:
            continue
        if not why and insurance_only_unknown(p) and is_best_fit(p):
            continue  # cycle 28: shown under Best fits, marked "insurance not filled in yet"
        ask = "Ask the listing agent before you count on this cost." if (p.get("cost") or {}).get("mode") == "buy" \
            else "Ask the landlord before you count on the rent."
        if why:
            text = why[0].upper() + why[1:] + ". " + ask
        else:
            text = _join(parts)[0].upper() + _join(parts)[1:] + _verb(parts) + " not counted yet. " + ask
        out.append({"place": p, "text": text})
    out.sort(key=lambda r: (-r["place"]["score_total"], _cost_key(r["place"]), r["place"]["title"].lower()))
    return out


_CLOSING_HELP = re.compile(r"\b(?:closing|seller|credit|concessions?|help|assist\w*|incentive|offer\w*)\b", re.I)
_REAL_COST_WORD = re.compile(r"\b(?:hoa|tax|insurance|assessment|parking fee|deposit|fee|dues)\b", re.I)


def _closing_help_only(place: dict[str, Any]) -> bool:
    """True when every open money note in a buyer's listing notes is a closing-help offer (not a cost the buyer pays monthly)."""
    notes = money_mod.open_listing_notes(place.get("reader_notes"), place)
    return bool(notes) and all(_CLOSING_HELP.search(n) and not _REAL_COST_WORD.search(n) for n in notes)


def _verb(parts: list[str]) -> str:
    """" is" for one thing ("parking"), " are" for several or for a plural name ("some amounts in the listing notes", "utilities")."""
    return " is" if len(parts) == 1 and not re.search(r"\bamounts\b|(?:ies|charges|costs|fees|notes)$| and ", parts[0]) else " are"


def unknown_cost_parts(place: dict[str, Any]) -> list[str]:
    """Plain names of the parts of the monthly cost that are unknown ('utilities', 'parking', 'pet rent', 'HOA'...), whatever
    their number. A part the listing gave amounts for that were not read counts as unknown too."""
    cost = place.get("cost") or {}
    out: list[str] = []
    for u in cost.get("uncounted") or []:
        u = str(u)
        if u == money_mod.LISTING_NOTES_UNCOUNTED:
            if cost.get("mode") == "buy" and _closing_help_only(place):
                continue  # a closing-help offer is about cash to close, not a monthly cost part
            out.append("some amounts in the listing notes")
            continue
        name = re.sub(r"\s*\(.*\)\s*$", "", u).strip()
        if cost.get("mode") == "buy" and name.lower().startswith("parking"):
            continue  # parking is no part of a buyer's monthly cost here
        if name.lower() == "utilities" and (cost.get("mode") == "buy" or u.lower() == "utilities" and not _TENANT_PAYS_UTILITIES.search(
                " ".join(str(place.get(k) or "") for k in ("listing_text", "reader_notes", "ai_notes", "notes")))):
            continue  # a bare "utilities" nobody said the tenant pays is no cost part to ask about
        if name and name not in out:
            out.append(name)
    if cost.get("mode") != "buy" and compare.pet_rent_unset(place) and not any(x.startswith("pet") for x in out):
        out.append("pet rent")
    return out


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
    # cycle 30: a place that already shows under Check first because of a scam hint (not only a low rent) is not listed here too
    out = [p for p in rows if not fails_dealbreakers(p) and not possible_scam(p) and not ai_text_only(p)
           and not redflags.scam_sign_flags(p.get("flags") or [])]
    for p in out:
        p["low_rent_note"] = low_rent(p)  # a very low rent stays visible here now that cost check leaves such places out
    return out


def late_availability(rows: list[dict[str, Any]], search: dict[str, Any], limit: int = 5) -> list[dict[str, Any]]:
    out = []
    for p in rows:
        if p["hidden"] or p["stage"] in OFF_THE_MARKET or fails_dealbreakers(p) or possible_scam(p):
            continue
        msg = availability_warning(p, search)
        gap = (p.get("score") or {}).get("lease_gap")
        if gap:
            msg = f"{msg}. {gap}" if msg else gap
        if msg:
            out.append({"place": p, "text": msg})
    return out[:limit]


def _cap(items: list[Any], limit: int) -> tuple[list[Any], int]:
    return items[:limit], max(0, len(items) - limit)


def build(store: Store, search: dict[str, Any], days: int = COMING_UP_DAYS) -> dict[str, Any]:
    """Everything the Today page and the MCP todays_list need for one search: the one place both read from, so every
    section holds the same places on the page and in Claude's list."""
    rows = enrich.enrich_places(store, search)
    all_top = best_fits(rows, 10 ** 6)
    top, more_fits = _cap(all_top, TOP_FITS)
    needs = needs_price(rows)
    priceless = {p["id"] for p in needs}  # a place with no price shows under "Needs a price" only
    near_closest, more_closest = _cap([] if all_top else closest(rows, 10 ** 6), TOP_FITS)
    unconf, more_unconf = _cap([] if all_top else unconfirmed(rows, 10 ** 6), TOP_FITS)
    shown_closest = {c["place"]["id"] for c in near_closest}
    near, more_near = _cap([n for n in near_misses(rows, 10 ** 6) if n["place"]["id"] not in shown_closest], TOP_FITS)
    late, more_late = _cap(late_availability(rows, search, 10 ** 6), 5)
    all_checks = check_first(rows, search.get("mode", "rent"))
    checks, more_checks = _cap(all_checks, CHECK_FIRST_SHOWN)
    shared = (CHECK_FIRST_BUY_TEXT if search.get("mode") == "buy" else CHECK_FIRST_TEXT) if any(c["scam"] for c in all_checks) else ""
    return {"fits": top, "unconfirmed": unconf, "needs_price": needs, "cost_check": cost_check(rows, shown_closest), "closest": near_closest, "check_first": checks, "check_first_total": len(all_checks), "check_first_shared": shared,
            "near_miss": near, "coming": coming_up(store, search, rows, days), "waiting": waiting_rows(store, search),
            "new": [p for p in new_places(store, search) if p["id"] not in priceless], "late": late,
            "tours": store.upcoming_tours(days, search_id=search["id"]),
            "more": {"fits": more_fits, "closest": more_closest, "unconfirmed": more_unconf, "near_miss": more_near, "late": more_late, "check_first": more_checks}}
