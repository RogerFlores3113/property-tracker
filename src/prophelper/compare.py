"""Compare two to four places side by side. Pure: it takes enriched places (see ``enrich.py``) and returns rows.

``build_rows(places)`` returns a list of sections; each section is ``{"title", "rows"}`` and each row is
``{"key", "label", "cells", "differs", "best_note"}``. A cell is ``{"text", "value", "best", "unknown"}``:

* ``text``: what the page shows.
* ``value``: the number used to compare (None when unknown or not a number).
* ``best``: True on the best value in the row (lowest cost, highest score and so on); ``marker`` is then "(best)" or "(tied best)". A row where every known value
  is the same, or where fewer than two places have a value, marks no best.
* ``differs``: True when the known values are not all the same, so the page can highlight the row.
* ``tied``: True when two or more places share the best value (``best_note`` is then "tied best").

Which way is better is set per row: ``low`` (cost, fees, commute minutes), ``high`` (score, size, newer year built) or
``None`` (a fact where neither is better, such as bedrooms: only differences are shown). An unknown value is never
best, and a cost that leaves something out ("insurance not counted yet") is never marked best. Worst is never marked.
"""
from __future__ import annotations

import re
from typing import Any

from . import helpers
from . import money as money_mod

MIN_PLACES, MAX_PLACES = 2, 4
LAUNDRY_RANK = {"in_unit": 3, "in_building": 2, "hookups": 1, "none": 0}
LAUNDRY_TEXT = {"in_unit": "In the unit", "in_building": "In the building", "hookups": "Hookups only", "none": "None"}
PARKING_RANK = {"garage": 4, "covered": 3, "lot": 2, "street": 1, "none": 0}
PARKING_TEXT = {"garage": "Garage", "covered": "Covered", "lot": "Lot", "street": "Street", "none": "None"}
PETS_TEXT = {"cats": "Cats", "dogs": "Dogs", "both": "Cats and dogs", "none": "No pets"}
UNKNOWN = "unknown"
NONE_LISTED = "None listed"  # a buy place with no special assessment entered
NOT_COUNTED_NO_PETS = "Not counted, no pets"
NOT_KNOWN = "Not known"  # shown for money nobody has filled in (never $0)


class CompareError(ValueError):
    """A plain-words reason the comparison can't be made (too few or too many places)."""


def parse_ids(values: Any) -> list[int]:
    """Ids from '1,2,3', from a list of such strings, or from a mix; repeats dropped, order kept.
    Raises CompareError for anything that is not a whole number."""
    parts: list[str] = []
    for v in (values if isinstance(values, (list, tuple)) else [values]):
        parts.extend(str(v or "").replace(" ", ",").split(","))
    out: list[int] = []
    for p in parts:
        if not p:
            continue
        if not p.isdigit():
            raise CompareError("Those aren't place numbers. Pick the places with the boxes below.")
        n = int(p)
        if n > 0 and n not in out:
            out.append(n)
    return out


def check_count(n: int) -> None:
    if n < MIN_PLACES:
        raise CompareError(f"Pick at least {MIN_PLACES} places to compare. You picked {n}.")
    if n > MAX_PLACES:
        raise CompareError(f"Compare takes {MIN_PLACES} to {MAX_PLACES} places at a time. You picked {n}, so take {n - MAX_PLACES} off.")


def mark(cells: list[dict[str, Any]], better: str | None) -> tuple[bool, str]:
    """Set ``best`` and ``marker`` on the cells of one row, in place. Returns (differs, note): "best", "tied best" or "".
    The marker text on a cell is "(best)" or "(tied best)". Worst values are never marked."""
    known = [c["value"] for c in cells if c["value"] is not None]
    differs = len(set(round(v, 4) for v in known)) > 1
    for c in cells:
        c["best"] = False
        c["worst"] = False
        c["marker"] = ""
    if not differs or better not in ("low", "high"):
        return differs, ""
    # An incomplete number (something left out of it) can't win, and unknowns never win.
    ranked = [c["value"] for c in cells if c["value"] is not None and not c.get("incomplete")]
    if len(set(round(v, 4) for v in ranked)) < 2:
        return differs, ""
    best = min(ranked) if better == "low" else max(ranked)
    for c in cells:
        c["best"] = c["value"] is not None and not c.get("incomplete") and abs(c["value"] - best) < 1e-9
    n = sum(1 for c in cells if c["best"])
    for c in cells:
        if c["best"]:
            c["marker"] = "(tied best)" if n > 1 else "(best)"
    return differs, "tied best" if n > 1 else "best"


def _cell(text: Any, value: float | None = None, unknown_text: str = UNKNOWN) -> dict[str, Any]:
    unknown = text is None or text == ""
    return {"text": unknown_text if unknown else str(text), "value": value, "best": False, "worst": False, "marker": "",
            "unknown": unknown, "incomplete": False}


def _money(v: Any, cents: bool = False) -> dict[str, Any]:
    return _cell(helpers.money(v, cents=cents) if v is not None else None, float(v) if v is not None else None, NOT_KNOWN)


def _year(v: Any) -> dict[str, Any]:
    """A year with no thousands comma (2016, not 2,016)."""
    n = None
    try:
        n = int(float(v)) if v not in (None, "") else None
    except (TypeError, ValueError):
        n = None
    return _cell(str(n) if n else None, float(n) if n else None)


def unknown_list(p: dict[str, Any]) -> list[str]:
    """What is really unknown about an enriched place: criteria with no value and costs not filled in."""
    return list(dict.fromkeys([*p["score"]["unknown"], *p["cost"]["missing"], *guessed_list(p)]))


def guessed_list(p: dict[str, Any]) -> list[str]:
    """Costs that are only an estimate, worded "Utilities (a guess)" (their line label already says so)."""
    out = []
    for line in (p.get("cost") or {}).get("lines", []):
        if line.get("estimated") and line.get("amount") is not None:
            label = line["label"]
            out.append(label if "guess" in label.lower() else f"{label} (a guess)")
    return out


_GUESS_WORDS = re.compile(r"\s*\((?:an? )?(?:guess|estimate)\)|\s+(?:guess|estimate)$", re.IGNORECASE)


def _guessed_names(p: dict[str, Any]) -> list[str]:
    """The names of guessed costs with the word guess taken off ("Utilities (a guess)" gives "utilities")."""
    names = []
    for g in guessed_list(p):
        name = _GUESS_WORDS.sub("", g).strip()
        if name:
            names.append(name[0].lower() + name[1:] if not name[:2].isupper() else name)
    return list(dict.fromkeys(names))


def _missing_names(p: dict[str, Any]) -> list[str]:
    """Costs nobody has filled in, in plain words, with no brackets: "utilities estimate" becomes "electric and internet"
    when the listing says what the tenant pays."""
    out = []
    for m in (p.get("cost") or {}).get("missing", []):
        named = next((u for u in p["cost"].get("uncounted") or [] if u.startswith("utilities (")), "")
        if named and m == "utilities estimate":
            m = named[len("utilities ("):].rstrip(")")
        out.append(m)
    names = partial_utilities(p)
    if names:
        out.append(_join_and(names))
    return list(dict.fromkeys(out))


def cost_unknowns(p: dict[str, Any]) -> list[str]:
    """Every unknown cost part the cost math knows about, in plain words: unfilled costs, utilities the tenant pays or the
    listing does not include, and pet charges (a search with a pet, a place that allows pets, no fee or deposit). The one
    source for "Not counted yet", "Still unknown" and Claude's unknowns."""
    return list(dict.fromkeys([*_missing_names(p), *pet_charges_unknown_text(p)]))


def _join_and(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


_STANDARD_UTILITIES = (("electric", re.compile(r"electric|power", re.I)), ("gas", re.compile(r"\bgas\b", re.I)),
                       ("internet", re.compile(r"internet|wi-?fi|cable", re.I)))


def partial_utilities(p: dict[str, Any]) -> list[str]:
    """For a rental whose listing names some included utilities (such as heat and water) but not all of them, and says
    nothing about what the tenant pays: the usual ones it does not list as included (electric, gas, internet). The cost
    math counts that as $0 included, so this is the one place that says the rest is still unknown. [] otherwise."""
    if (p.get("cost") or {}).get("mode") in (None, "buy") or money_mod.num(p.get("utilities_estimate")) is not None:
        return []
    listed = str(p.get("utilities_included") or "").strip()
    if not listed or listed.lower() in money_mod.NOTHING_WORDS or _utilities_fully_included(p) or money_mod.tenant_pays_list(p):
        return []
    return [name for name, pat in _STANDARD_UTILITIES if not pat.search(listed)]


def _uncounted(p: dict[str, Any]) -> list[str]:
    """Cost parts left out of the monthly number: the money result's own list plus utilities the listing does not
    include and nobody priced. The one list behind "not counted yet" everywhere (cost cell, lowest cost, per person)."""
    out = list((p.get("cost") or {}).get("uncounted") or [])
    names = partial_utilities(p)
    if names:
        out.append(f"utilities ({_join_and(names)})")
    return out


def pet_charges_unknown_text(p: dict[str, Any]) -> list[str]:
    return ["pet charges"] if (p.get("cost") or {}).get("mode") == "rent" and _pet_charges_unknown(p) else []


def unknown_text(unknown: list[str], guessed: list[str]) -> str:
    """One plain style for the "Not counted yet" and "Still unknown" rows: "Nothing unknown", "Unknown: a, b",
    "Utilities guessed", or both joined with a semicolon. Never nested brackets."""
    bits = []
    if unknown:
        bits.append("Unknown: " + ", ".join(unknown))
    if guessed:
        text = _join_and(guessed) + " guessed"
        bits.append(text[0].upper() + text[1:])
    return "; ".join(bits) or "Nothing unknown"


def _not_counted_text(p: dict[str, Any]) -> str:
    return unknown_text(cost_unknowns(p), _guessed_names(p))


def still_unknown_text(p: dict[str, Any], label=lambda x: x) -> str:
    """Criteria with no value plus unfilled and guessed costs, in the same style as ``_not_counted_text``. ``label`` wraps
    a criterion label (Claude's server fences the user's own words)."""
    return unknown_text(list(dict.fromkeys([*[label(x) for x in p["score"]["unknown"]], *cost_unknowns(p)])), _guessed_names(p))


def unknown_names(p: dict[str, Any]) -> list[str]:
    """Short names of everything the score and cost rest on a guess or a blank for: 'guessed utilities', 'parking'."""
    out = [f"guessed {n}" for n in _guessed_names(p)]
    for item in p["score"].get("items") or []:
        if not item.get("known"):
            out.append("commute" if item.get("kind") == "commute" else str(scoring_kind_label(item)).lower())
    return list(dict.fromkeys(out))


def scoring_kind_label(item: dict[str, Any]) -> str:
    from . import scoring
    return scoring.KIND_LABELS.get(item.get("kind"), item.get("label") or "something")


def _num(v: Any, suffix: str = "") -> dict[str, Any]:
    return _cell(helpers.number_text(v) + suffix if v not in (None, "") else None, float(v) if v not in (None, "") else None)


def _yes_no(v: Any) -> dict[str, Any]:
    if v is None:
        return _cell(None)
    return _cell("Yes" if v else "No", 1.0 if v else 0.0)


def flat_cost_name(u: str) -> str:
    """'utilities (electric and gas)' becomes 'electric and gas utilities', so a name never nests brackets inside brackets."""
    m = re.fullmatch(r"utilities \((.*)\)", u.strip())
    return f"{m.group(1)} utilities" if m else u


def _cost_cell(p: dict[str, Any]) -> dict[str, Any]:
    cell = _money(p["cost_total"])
    unc = _uncounted(p)
    if cell["value"] is not None and unc:
        cell["text"] += f" ({', '.join(flat_cost_name(u) for u in unc)} not counted yet)"
        cell["incomplete"] = True
    return cell


def _cash_label(places: list[dict[str, Any]]) -> str:
    modes = {p["cost"].get("mode") for p in places}
    if modes == {"buy"}:
        return "Cash needed to close (down payment, closing costs)"
    if modes == {"rent"}:
        return "Cash needed at move-in"
    return "Cash needed up front (to close, or at move-in)"


def _deposit_unknown(p: dict[str, Any], c: dict[str, Any] | None) -> bool:
    """True when a renter's cash at move-in leaves out a deposit nobody has filled in. Uses the money result's own flag
    (``deposit_unknown``) when it has one, else works it out from the place. A deposit of 0 is a known deposit."""
    if not c or p["cost"].get("mode") == "buy":
        return False
    if "deposit_unknown" in c:
        return bool(c["deposit_unknown"])
    return p.get("deposit") in (None, "")


def cash_unknown_names(p: dict[str, Any]) -> list[str]:
    """What a renter's move-in cash leaves out because nobody filled it in, besides the deposit: 'pet charges', 'parking'."""
    if p["cost"].get("mode") == "buy" or not p["cost"].get("cash_at_move_in"):
        return []
    out = []
    if _pet_charges_unknown(p):
        out.append("pet charges")
    if str(p.get("parking") or "") in ("garage", "covered", "lot") and p.get("parking_cost") in (None, ""):
        out.append("parking")  # a kind of parking that usually costs something, with no price filled in
    return out


def _cash_cell(p: dict[str, Any]) -> dict[str, Any]:
    """Cash due up front: for a buyer, down payment + closing costs (a guess when not entered) + a special assessment the
    buyer pays; for a renter, the move-in cash (at least that much when the deposit is not known, so it can't win)."""
    buy = p["cost"].get("mode") == "buy"
    c = p["cost"].get("cash_to_close") if buy else p["cost"].get("cash_at_move_in")
    cell = _money(c["total"]) if c else _cell(None, unknown_text=NOT_KNOWN)
    if not c:
        return cell
    notes = []
    if c.get("has_estimate"):
        notes.append("closing costs are a guess")
    sa = next((x for x in c.get("parts") or [] if str(x.get("label", "")).startswith("Special assessment")), None)
    if sa:
        notes.append(f"includes a {helpers.money(sa['amount'])} special assessment you pay")
    if notes:
        cell["text"] += f" ({', '.join(notes)})"
    unknown = (["deposit"] if _deposit_unknown(p, c) else []) + cash_unknown_names(p)
    if unknown:
        cell["text"] = f"at least {helpers.money(c['total'])} ({_join_and(unknown)} not known)"
        cell["incomplete"] = True
    return cell


def _note_rank(unit: str) -> int:
    """0 for a money note (an amount or cost still open), 2 for offer boilerplate (free rent, concessions), 1 for the rest."""
    if re.search(r"free[- ]rent|concession|months? free|weeks? free|move-in special", unit, re.I) and not re.search(r"\$\s?\d", unit):
        return 2
    return 0 if (money_mod.listing_notes_uncounted(unit) or re.search(r"\$\s?\d", unit)) else 1


def listing_notes_text(p: dict[str, Any], limit: int = 110) -> str:
    """The reader's saved notes from the listing, short. Money notes come first and the offer boilerplate last. Whole notes
    only: when they do not all fit, it ends after the last whole note with "and N more on the place page"."""
    text = " ".join(str(p.get("reader_notes") or "").split())
    if not text:
        return ""
    units = sorted(money_mod.note_units(text), key=_note_rank)  # stable: the order they were written inside each group
    shown: list[str] = []
    used = 0
    for u in units:
        if used + len(u) + 1 > limit and shown:
            break
        shown.append(u)
        used += len(u) + 1
    rest = len(units) - len(shown)
    first = shown[0] if shown else ""
    if len(first) > limit and len(shown) == 1:
        sentences = re.split(r"(?<=[.!?])\s+", first)  # one long note: keep whole sentences, never cut inside one
        first = sentences[0]
        if len(first) > limit * 2:
            first = first[:limit * 2].rsplit(" ", 1)[0].rstrip(" ,;:") + "..."
        shown = [first]
        rest = len(units) - 1 + (1 if len(sentences) > 1 else 0)
    out = " ".join(shown)
    return out + (f" and {rest} more on the place page." if rest > 0 else "")


def _pet_charges_unknown(p: dict[str, Any]) -> bool:
    """True when the search has pets, the place allows them, and neither a pet fee nor a pet deposit is filled in."""
    if not p["cost"].get("pets_counted", True) or str(p.get("pets") or "") == "none":
        return False
    known_pets = str(p.get("pets") or "") in ("cats", "dogs", "both")
    if known_pets and any(p.get(k) not in (None, "") for k in ("pet_rent", "pet_fee", "pet_deposit")):
        return False  # a pet charge was read and the pets allowed are known: the pet side of the cost is not a gap
    return p.get("pet_fee") in (None, "") and p.get("pet_deposit") in (None, "")


def _utilities_fully_included(p: dict[str, Any]) -> bool:
    """True when the listing says every utility is in the rent (or the tenant pays none), so $0 is a fact, not a guess."""
    if money_mod.utilities_covered(p):
        return True
    pays = money_mod.tenant_pays_list(p)
    return bool(pays) and all(w in money_mod.NOTHING_WORDS for w in pays)


def _ineligible(p: dict[str, Any], best_of: bool = False) -> bool:
    """A place that does not fit, or is a possible scam: its values show, but it never gets a best marker. A near miss
    (a small overage, often from a guess) can still win, and its Fit cell says it is a near miss. In a best-of line
    (``best_of``: lowest cost, highest score) a place with text aimed at AI tools is left out too."""
    return (p["score"].get("fit", "fits") not in ("fits", "near_miss") or bool(p.get("possible_scam"))
            or (best_of and ai_text_only(p)))

def ai_text_only(p: dict[str, Any]) -> bool:
    """True when the only thing to check in the listing is text aimed at AI tools (no scam sign)."""
    flags = [str(f) for f in p.get("flags") or []]
    return bool(flags) and not p.get("possible_scam") and all("aimed at AI tools" in f for f in flags)


AI_TEXT_FIT = "Check first: text aimed at AI tools in the listing"


def unpriced(p: dict[str, Any]) -> bool:
    """A place with no rent (or, buying, no price): it can't win a best-of line (lowest cost, highest score)."""
    return p.get("cost_total") is None


def _fits(p: dict[str, Any]) -> bool:
    """A place that fits (not a near miss, not a possible scam)."""
    return p["score"].get("fit", "fits") == "fits" and not p.get("possible_scam")


_COMMUTE_TARGET = re.compile(r"(\d+(?:\.\d+)?) min or less by (\w+)")


def over_limit_text(p: dict[str, Any]) -> str:
    """"24 min bike vs your 20 min limit" when a commute rule (must-have or nice-to-have) says this place is over its
    limit, else "". The limit and way come from the rule's own score line; the minutes are the commute the app shows
    (``commute.show_commute``, in ``commute_all``), else the limit plus the overage."""
    for item in p["score"].get("items") or []:
        if item.get("kind") != "commute" or not item.get("over_amount"):
            continue
        m = _COMMUTE_TARGET.search(str(item.get("target") or ""))
        if not m:
            return "over your commute limit"
        limit, mode = float(m.group(1)), m.group(2)
        shown = [c["minutes"] for c in p.get("commute_all") or [] if c.get("mode") == mode and c["minutes"] > limit]
        minutes = max(shown) if shown else limit + float(item["over_amount"])
        return f"{minutes:.0f} min {mode} vs your {limit:.0f} min limit"
    return ""


def lowest_cost(places: list[dict[str, Any]]) -> dict[str, Any]:
    """THE rule for "lowest true monthly cost", used by the Compare page, the shared page and Claude's compare_places.
    Returns ``winners`` (places; several when tied), ``amount``, ``same`` (every candidate costs the same, so no lowest),
    ``all_unknown`` (every candidate leaves a cost part out, so the winner is only the lowest of what is counted),
    ``over_limit`` ([(place, "24 min bike vs your 20 min limit")] for places at or under the winner's cost that are over
    a commute limit), ``skipped_unknown`` (places that look cheaper but leave a cost part out) and ``blocked``
    ([(place, why)]: cheaper places that don't fit, are near misses beside a fitting place, or may be a scam).

    Only places that fully fit can win; a near miss never does (it is named as cheaper but not a place to pick). A place
    whose commute is over a limit is named, never silently the winner: it is skipped for "lowest" unless every
    candidate is over, and then the winner says so. A place with unknown cost parts is skipped unless every candidate
    has them."""
    priced = [p for p in places if p["cost_total"] is not None]
    eligible = [p for p in priced if not _ineligible(p, True) and _fits(p)]  # only places that fully fit; a near miss never wins
    base = [p for p in eligible if not over_limit_text(p)] or eligible
    complete = [p for p in base if not _uncounted(p)]
    pool = complete or base
    out: dict[str, Any] = {"winners": [], "amount": None, "same": False, "all_unknown": bool(pool) and not complete and len(priced) > 1,
                           "of_fit": len(eligible) < len(priced),
                           "over_limit": [], "skipped_unknown": [], "blocked": [], "no_fit": bool(priced) and not eligible}
    ref = min((p["cost_total"] for p in pool), default=None)
    if pool:
        low = min(p["cost_total"] for p in pool)
        out["amount"] = low
        out["winners"] = [p for p in pool if abs(p["cost_total"] - low) < 0.005]
        out["same"] = len(pool) > 1 and len(out["winners"]) == len(pool)
        for p in eligible:
            if p in pool or p["cost_total"] > low + 0.005:
                continue
            why = over_limit_text(p)
            if why:
                out["over_limit"].append((p, why))
            elif p not in complete:
                out["skipped_unknown"].append(p)
        if all(over_limit_text(p) for p in pool):
            out["over_limit"] += [(p, over_limit_text(p)) for p in out["winners"] if (p, over_limit_text(p)) not in out["over_limit"]]
    for p in priced:
        if p in eligible or (ref is not None and p["cost_total"] >= ref + 0.005):
            continue
        if p["score"].get("fit") == "check_first" or p.get("possible_scam"):
            out["blocked"].append((p, "check it first: possible scam"))
        elif ai_text_only(p):
            out["blocked"].append((p, "check it first: text aimed at AI tools in the listing"))
        elif p["score"].get("fit") == "near_miss":
            out["blocked"].append((p, "it is a near miss"))
        else:
            out["blocked"].append((p, "it doesn't fit what you asked for"))
    return out


def _assessment_cell(p: dict[str, Any]) -> dict[str, Any]:
    """A buyer's special assessment and who pays it. What the buyer pays is the number compared."""
    if p["cost"].get("mode") != "buy":
        return _cell(None)
    from .money import num
    sa = num(p.get("special_assessment"))
    if sa is None:
        if "assessment" in str(p.get("listing_text") or "").lower():
            cell = _cell("Mentioned in the listing, amount not entered")
            cell["incomplete"] = True
            return cell
        cell = _cell(None, 0.0, unknown_text=NONE_LISTED)  # nothing entered and the listing is silent: counts as none, for ranking only
        return cell
    if sa == 0:
        return _cell("None", 0.0)
    amount, payer = helpers.money(sa), str(p.get("special_assessment_payer") or "")
    if payer == "buyer":
        return _cell(f"{amount} (you pay it)", sa)
    if payer == "seller":
        return _cell(f"{amount} (the seller pays it)", 0.0)
    cell = _cell(f"{amount} (who pays it is not known)", sa)
    cell["incomplete"] = True
    return cell


def _per_person_cell(p: dict[str, Any]) -> dict[str, Any]:
    cell = _money(p.get("per_person"))
    if cell["value"] is not None and _uncounted(p):
        cell["incomplete"] = True
    if cell["value"] is not None:
        cell["text"] += f" ({p['people']} {p.get('split_noun') or 'people'})"
    return cell


FIT_TEXT = {"fits": "Yes", "near_miss": "Near miss", "doesnt_fit": "Doesn't fit", "check_first": "Check first: possible scam"}


def _fit_cell(p: dict[str, Any]) -> dict[str, Any]:
    fit = p["score"].get("fit", "fits")
    reasons = "; ".join(p["score"].get("fit_reasons") or [])
    if fit == "fits" and p["score"].get("fit_label") == "Fits, but check":
        concerns = "; ".join(p["score"].get("concerns") or [])
        return _cell("Fits, but check" + (f" ({concerns})" if concerns else ""))
    if fit == "fits" and ai_text_only(p):
        return _cell(AI_TEXT_FIT)
    if fit == "near_miss" and not reasons:
        reasons = "; ".join(p["score"].get("near_texts") or [])
    if fit == "fits" and p["score"].get("notes"):
        return _cell("Yes (" + "; ".join(p["score"]["notes"]) + ")")
    return _cell(FIT_TEXT.get(fit, fit) + (f" ({reasons})" if reasons and fit != "fits" else ""))


def _score_cell(p: dict[str, Any]) -> dict[str, Any]:
    cell = _num(p["score_total"])
    if cell["value"] is not None:
        fit = p["score"].get("fit", "fits")
        label = p["score"].get("fit_label") if fit == "fits" and p["score"].get("fit_label") == "Fits, but check" \
            else ({"near_miss": "near miss", "doesnt_fit": "doesn't fit", "check_first": "check first"}.get(fit) or "")
        if label:
            cell["text"] += f", {label[0].lower() + label[1:]}"
    names = unknown_names(p)
    n = p["score"].get("unknown_count") or 0
    if cell["value"] is not None and (n or names):
        n = len(names) or n
        cell["text"] += f" (based on {n} unknown{'s' if n != 1 else ''}" + (f": {', '.join(names)}" if names else "") + ")"
    return cell


def _opinion_cell(p: dict[str, Any]) -> dict[str, Any]:
    o = p.get("opinions")
    if not o:
        return _cell(None)
    return _cell(f"{o['average']:g} (average of {o['count']})", float(o["average"]))


def _person_rows(places: list[dict[str, Any]]) -> list[dict[str, Any] | None]:
    """One row per named person who rated something: "Sam's rating (1 to 5)" with each place's number. The places carry
    ``opinion_rows`` (the people's saved opinions) when the page loaded them."""
    names: list[str] = []
    for p in places:
        for o in p.get("opinion_rows") or []:
            if o["person"] not in names:
                names.append(o["person"])
    rows = []
    for name in names:
        cells = []
        for p in places:
            o = next((x for x in p.get("opinion_rows") or [] if x["person"] == name), None)
            cells.append(_num(o["rating"]) if o and o.get("rating") is not None else _cell(None))
        rows.append(_row("person-" + name, f"{name}'s rating (1 to 5)", cells, "high", only_if_any=True, places=places))
    return rows


def _plain(text: Any) -> dict[str, Any]:
    return _cell(text or None)


def _utilities_cell(p: dict[str, Any]) -> dict[str, Any]:
    """What the listing says the rent includes: 'Heat, water', 'All' or 'None listed'."""
    text = str(p.get("utilities_included") or "").strip()
    if not text:
        return _cell(None, unknown_text="None listed")
    if money_mod.utilities_covered(p):
        return _cell("All")
    if text.lower() in money_mod.NOTHING_WORDS:
        return _cell("None listed")
    return _cell(text)


_LANDLORD_PHRASES = (
    (re.compile(r"\bask the landlord\b", re.I), "ask the seller or listing agent"),
    (re.compile(r"\bcheck with the landlord\b", re.I), "check with the seller or listing agent"),
    (re.compile(r"\bthe landlord's approval\b", re.I), "the seller's approval"),
    (re.compile(r"\bthe landlord\b", re.I), "the seller"),
)


def for_buyer(text: str) -> str:
    """Wording for a buy search: a note written for renters says seller or listing agent, and the special assessment note says what to do."""
    out = str(text)
    for pat, repl in _LANDLORD_PHRASES:
        out = pat.sub(repl, out)
    return out


def _pet_limits_text(p: dict[str, Any]) -> str:
    """'Dogs, up to 50 lb, 2 pets at most', from the facts a place has. Empty when none is known."""
    bits: list[str] = []
    allowed = PETS_TEXT.get(p.get("pets") or "")
    if allowed:
        bits.append(allowed)
    w = p.get("pet_weight_limit")
    if w not in (None, ""):
        bits.append(f"up to {float(w):g} lb")
    n = p.get("pet_count_limit")
    if n not in (None, ""):
        bits.append(f"{int(n)} pet{'s' if int(n) != 1 else ''} at most")
    return ", ".join(bits)


def _pet_limits_cell(p: dict[str, Any]) -> dict[str, Any]:
    return _cell(_pet_limits_text(p) or None)


def _fenced_yard_cell(p: dict[str, Any]) -> dict[str, Any]:
    return _yes_no(p.get("fenced_yard"))


def _search_cares_about(places: list[dict[str, Any]], *kinds: str) -> bool:
    """True when the search has a rule of one of these kinds (the scored items say so)."""
    return any(i.get("kind") in kinds for p in places for i in (p.get("score") or {}).get("items") or [])


def shows_pet_limits(places: list[dict[str, Any]]) -> bool:
    return any(p.get("pet_weight_limit") not in (None, "") or p.get("pet_count_limit") not in (None, "") for p in places) \
        or _search_cares_about(places, "pets")


def shows_fenced_yard(places: list[dict[str, Any]]) -> bool:
    return any(p.get("fenced_yard") is not None for p in places) or _search_cares_about(places, "fenced_yard")


def _line_unset(p: dict[str, Any], key: str) -> bool:
    """True when a $0 cost line is really "never filled in" (pet rent with pets unknown, parking never set)."""
    if key == "pet_rent":
        return p.get("pet_rent") in (None, "") and str(p.get("pets") or "") != "none"
    if key == "parking":
        return p.get("parking_cost") in (None, "") and not p.get("parking")
    if key == "other":
        return p.get("other_monthly_fees") in (None, "")
    return False


def _one_time_unset(p: dict[str, Any]) -> bool:
    return any(l["key"] == "one_time" and l.get("unset") for l in p["cost"].get("lines", []))


def _commute_rows(places: list[dict[str, Any]], anchors: list[tuple[Any, str]], row=None) -> list[dict[str, Any] | None]:
    """One row per important place. Each cell is the commute the app shows everywhere (``commute.show_commute``: the way
    of that place's commute rule, a saved time before an estimate). Cells in another way than the row's are shown but
    never ranked, so an estimate is never ranked against a saved time of another way."""
    row = row or _row
    rows = []
    for aid, name in anchors:
        found = [next((x for x in p.get("commute_all", []) if x["anchor"] == name), None) for p in places]
        modes = {c["mode"] for c in found if c}
        mode = next(iter(modes)) if len(modes) == 1 else ""
        cells = []
        for c in found:
            cell = _cell(c["label"], float(c["minutes"])) if c else _cell(None)
            if c and not mode:
                cell["incomplete"] = True
            cells.append(cell)
        rows.append(row(f"commute-{aid}", f"To {name}" + (f" ({mode})" if mode else ""), cells, "low"))
    return rows


BEST_OF_KEYS = ("cost", "per_person", "score")


def _row(key: str, label: str, cells: list[dict[str, Any]], better: str | None = None, *, only_if_any: bool = False,
         places: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    if only_if_any and all(c["unknown"] for c in cells):
        return None
    if places and len(places) == len(cells):
        fitting_value = any(c["value"] is not None and _fits(p) for c, p in zip(cells, places))
        for c, p in zip(cells, places):
            if _ineligible(p, key in BEST_OF_KEYS) or (key == "score" and unpriced(p)):
                c["incomplete"] = True  # shown, but a place that doesn't fit, may be a scam or has no price never wins a row
            elif not _fits(p) and fitting_value:
                c["incomplete"] = True  # a near miss only wins a row when no fitting place has a value in it
            elif key in ("cost", "per_person") and over_limit_text(p):
                c["incomplete"] = True  # over a commute limit: not the lowest cost without saying so (see lowest_cost)
    differs, note = mark(cells, better)
    return {"key": key, "label": label, "cells": cells, "differs": differs, "best_note": note, "tied": note == "tied"}


def build_rows(places: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sections of rows for these enriched places (same order as ``places``)."""
    sections: list[dict[str, Any]] = []
    def row(key, label, cells, better=None, *, only_if_any=False):
        return _row(key, label, cells, better, only_if_any=only_if_any, places=places)


    def section(title: str, rows: list[dict[str, Any] | None]) -> None:
        rows = [r for r in rows if r]
        if rows:
            sections.append({"title": title, "rows": rows})

    # ---- the headline numbers
    section("The short version", [
        row("cost", "True monthly cost", [_cost_cell(p) for p in places], "low"),
        row("per_person", "Each adult each month" if all(p.get("split_noun") == "adults" for p in places if p.get("per_person") is not None) else "Per person each month", [_per_person_cell(p) for p in places], "low", only_if_any=True)
        if any(p.get("per_person") is not None for p in places) else None,
        row("fit", "Does it fit?", [_fit_cell(p) for p in places]) if any(p["score"].get("fit", "fits") != "fits" or p["score"].get("fit_label") == "Fits, but check" or ai_text_only(p) or p["score"].get("notes") for p in places) else None,
        row("score", "Fit score (out of 100)", [_score_cell(p) for p in places], "high"),
        row("stage", "Stage", [_plain(p["stage"]) for p in places]),
        row("rating", "Your rating (1 to 5)", [_num(p.get("rating")) for p in places], "high", only_if_any=True),
        row("opinions", "Average of the people's ratings (1 to 5)", [_opinion_cell(p) for p in places], "high", only_if_any=True)
        if any(p.get("opinions") for p in places) else None,
        *_person_rows(places),
    ])

    # ---- cost line by line
    line_keys: list[tuple[str, str]] = []
    for p in places:
        for line in p["cost"]["lines"]:
            if not any(k == line["key"] for k, _ in line_keys):
                line_keys.append((line["key"], line["label"]))
    cost_rows = []
    for key, label in line_keys:
        cells = []
        for p in places:
            found = next((ln for ln in p["cost"]["lines"] if ln["key"] == key), None)
            amount = found["amount"] if found else None
            if amount is not None and ((found or {}).get("unset") or _line_unset(p, key)):
                amount = None
            if key == "pet_rent" and not p["cost"].get("pets_counted", True):
                cells.append(_cell(NOT_COUNTED_NO_PETS))  # the search has no pets: not a $0, not comparable
                continue
            cell = _money(amount)
            if key == "utilities" and amount == 0 and not _utilities_fully_included(p):
                cell["incomplete"] = True  # a $0 guess for a place that only includes some utilities can't tie a fully included one
            if key == "pet_rent" and amount == 0:
                cell["text"] = "$0 (none)"
            cells.append(cell)
        cost_rows.append(row("cost-" + key, label, cells, "low", only_if_any=True))
    cost_rows.append(row("missing", "Not counted yet", [_plain(_not_counted_text(p)) for p in places]))
    section("What it really costs, line by line", cost_rows)

    # ---- the facts
    section("The place", [
        row("price", "Price" if all(p["cost"].get("mode") == "buy" for p in places) else "Listed price", [_money(p.get("price")) for p in places], "low"),
        row("down", "Down payment", [_money(p["cost"].get("down_payment")) if p["cost"].get("mode") == "buy" else _cell(None) for p in places], only_if_any=True),
        row("assessment", "Special assessment (who pays it)", [_assessment_cell(p) for p in places], "low", only_if_any=True)
        if any(p["cost"].get("mode") == "buy" for p in places) else None,
        row("seller_credit", "Seller credit toward closing (more is better)", [_money(p.get("seller_credit")) if p["cost"].get("mode") == "buy" else _cell(None) for p in places], "high", only_if_any=True)
        if any(p["cost"].get("mode") == "buy" for p in places) else None,
        row("loan", "Loan amount", [_money(p["cost"].get("loan_amount")) if p["cost"].get("mode") == "buy" else _cell(None) for p in places], "low", only_if_any=True),
        row("beds", "Bedrooms", [_num(p.get("beds")) for p in places]),
        row("baths", "Bathrooms", [_num(p.get("baths")) for p in places]),
        row("sqft", "Size (sq ft, bigger is better)", [_num(p.get("sqft")) for p in places], "high"),
        row("year_built", "Year built (newer is better)", [_year(p.get("year_built")) for p in places], "high"),
        row("laundry", "Laundry", [_cell(LAUNDRY_TEXT.get(p.get("laundry") or ""), LAUNDRY_RANK.get(p.get("laundry") or "")) for p in places], "high"),
        row("dishwasher", "Dishwasher", [_yes_no(p.get("dishwasher")) for p in places], "high"),
        row("parking", "Parking", [_cell(PARKING_TEXT.get(p.get("parking") or ""), PARKING_RANK.get(p.get("parking") or "")) for p in places], None),
        row("pets", "Pets", [_cell(PETS_TEXT.get(p.get("pets") or "")) for p in places]),
        row("pet_limits", "Pet limits (kinds, weight, how many)", [_pet_limits_cell(p) for p in places]) if shows_pet_limits(places) else None,
        row("fenced_yard", "Fenced yard", [_fenced_yard_cell(p) for p in places], "high") if shows_fenced_yard(places) else None,
        row("utilities", "Utilities included", [_utilities_cell(p) for p in places], only_if_any=True),
        row("listing_notes", "Listing notes", [_plain(listing_notes_text(p)) for p in places], only_if_any=True),
    ])
    section("Dates and money up front", [
        row("available", "Available from", [_plain(helpers.day_text(p["available_from"]) if p.get("available_from") else "") for p in places], only_if_any=True),
        row("lease_months", "Lease length (months)", [_num(p.get("lease_months")) for p in places], only_if_any=True),
        row("months_up_front", "Months of rent due before move-in",
             [_num(money_mod.months_up_front(p)) if p["cost"].get("mode") == "rent" else _cell(None) for p in places], "low", only_if_any=True)
        if any(p["cost"].get("mode") == "rent" and money_mod.months_up_front(p) > 1 for p in places) else None,
        row("cash_up_front", _cash_label(places), [_cash_cell(p) for p in places],
             "low" if len({p["cost"].get("mode") for p in places}) == 1 else None, only_if_any=True),
        row("days_on_market", "Days on the market", [_num(p.get("days_on_market")) for p in places], only_if_any=True)
        if any(p["cost"].get("mode") == "buy" for p in places) else None,
        row("deposit", "Deposit (comes back)", [_money(p.get("deposit")) for p in places], "low", only_if_any=True),
        row("upfront", "Fees paid once (application, move-in, broker, pet)", [_money(None if _one_time_unset(p) else p["cost"].get("one_time_total")) if p["cost"].get("mode") == "rent" else _cell(None) for p in places], "low", only_if_any=True),
    ])

    # ---- commutes: one row per anchor, using the mode of that anchor's commute criterion
    anchors: list[tuple[Any, str]] = []
    for p in places:
        for c in p.get("commute_all", []):
            if not any(c["anchor"] == name for _, name in anchors):
                anchors.append((c["anchor_id"], c["anchor"]))
    commute_rows = _commute_rows(places, anchors, row)
    section("Commutes", commute_rows)

    # ---- the score, criterion by criterion
    labels: list[str] = []
    for p in places:
        for item in p["score"]["items"]:
            if item["label"] not in labels:
                labels.append(item["label"])
    score_rows = []
    for label in labels:
        cells = []
        for p in places:
            item = next((i for i in p["score"]["items"] if i["label"] == label), None)
            if item is None:
                cells.append(_cell(None))
            elif not item["known"] or item["score"] is None:
                cells.append(_cell(None))
            else:
                pct = round(item["score"] * 100)
                cells.append(_cell(f"{pct}%" + (" (fails)" if item.get("dealbreaker_status") == "fail" else ""), float(pct)))
        score_rows.append(row("score-" + label, label, cells, "high"))
    score_rows.append(row("unknown", "Still unknown", [_plain(still_unknown_text(p)) for p in places]))
    section("Score, one thing at a time", score_rows)
    return sections


def summary_lines(places: list[dict[str, Any]], sections: list[dict[str, Any]]) -> list[str]:
    """A few plain sentences: who has the lowest cost (``lowest_cost``, the one rule) and who scores highest (several
    places can be tied)."""
    out = lowest_cost_sentences(places, lambda p: p["title"])
    for sec in sections:
        for row in sec["rows"]:
            if row["key"] == "score" and row["differs"]:
                winners = [p["title"] for p, c in zip(places, row["cells"]) if c["best"]]
                if len(winners) > 1:
                    out.append(f"{' and '.join(winners)} are tied for the highest fit score.")
                elif winners:
                    out.append(f"{winners[0]} has the highest fit score.")
    return out


def lowest_note(r: dict[str, Any]) -> str:
    """The plain tail of the lowest-cost sentence, never nested brackets: ' of the places that fit', and, when every place
    leaves a cost part out, ', though every place leaves a cost part out'."""
    note = " of the places that fit" if r["of_fit"] else ""
    if not r["all_unknown"]:
        return note
    w = r.get("winners") or []
    if len(w) == 1:  # name what the winner leaves out: "..., but its electric isn't counted"
        left = _join_and([("utilities" if u == "utilities estimate" else u) for u in cost_unknowns(w[0])] or [_short_parts(w[0])])
        return note + f", but {_its(left)}{left} {'aren' if _aren_t(left) == 'are' else 'isn'}'t counted"
    return note + ", though every place leaves a cost part out"


def _short_parts(p: dict[str, Any]) -> str:
    """'utilities' or 'parking and utilities': the cost parts of this place that are not counted."""
    parts = [u.split(" (")[0] for u in _uncounted(p)]
    return _join_and(list(dict.fromkeys(parts))) if parts else "costs"


def _its(parts: str) -> str:
    """"its utilities", but plain "some amounts in the listing notes" (no "its")."""
    return "" if parts.startswith("some ") else "its "


def _aren_t(text: str) -> str:
    return "are" if (" and " in text or text.endswith("s") or text == "costs") else "is"


def skipped_unknown_sentences(r: dict[str, Any], name, merged: bool = False) -> list[str]:
    """For places that look cheaper but leave a cost part out: 'Oak Row looks cheaper, but its utilities are not counted.'
    With ``merged`` the sentences are clauses to join after the winner's own ('...; Oak Row looks cheaper ...')."""
    out = []
    for p in r["skipped_unknown"]:
        parts = _short_parts(p)
        out.append(f"{name(p)} looks cheaper, but {_its(parts)}{parts} {_aren_t(parts)} not counted" + ("" if merged else "."))
    return out


def unpriced_sentences(places: list[dict[str, Any]], name) -> list[str]:
    """Places with no rent or price: named once, so nobody wonders why they are not in the lowest-cost or highest-score lines."""
    out = []
    for p in places:
        if unpriced(p):
            out.append(f"{name(p)} has no price yet, so it is not in the lowest-cost or highest-score lines.")
    return out


def lowest_cost_sentences(places: list[dict[str, Any]], name) -> list[str]:
    """The At a glance sentences for the lowest cost. ``name(place)`` is how a place is called (its title on the web)."""
    r = lowest_cost(places)
    out: list[str] = []
    w = r["winners"]
    if w and not r["same"]:
        note = lowest_note(r)
        skipped = skipped_unknown_sentences(r, name, merged=True)
        if skipped:  # the winner is complete; say so and name the cheaper-looking place that is not
            who = f"{' and '.join(name(p) for p in w)} {'are tied for' if len(w) > 1 else 'is'} the lowest complete cost{note}"
            out.append("; ".join([who, *skipped]) + ".")
        elif len(w) > 1:
            out.append(f"{' and '.join(name(p) for p in w)} are tied for the lowest true monthly cost{note}.")
        else:
            out.append(f"{name(w[0])} has the lowest true monthly cost{note}.")
    elif r["skipped_unknown"]:
        out.extend(skipped_unknown_sentences(r, name))
    for p, why in r["over_limit"]:
        out.append(f"{name(p)} is cheapest, but {why}.")
    lowest = min((p["cost_total"] for p in places if p["cost_total"] is not None), default=None)
    for p, why in r["blocked"]:
        word = "cheapest" if lowest is not None and abs(p["cost_total"] - lowest) < 0.005 else "cheaper"
        out.append(f"{name(p)} is {word}, but {why}.")
    out.extend(unpriced_sentences(places, name))
    return out
