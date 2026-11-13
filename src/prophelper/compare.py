"""Compare two to four places side by side. Pure: it takes enriched places (see ``enrich.py``) and returns rows.

``build_rows(places)`` returns a list of sections; each section is ``{"title", "rows"}`` and each row is
``{"key", "label", "cells", "differs", "best_note"}``. A cell is ``{"text", "value", "best", "unknown"}``:

* ``text``: what the page shows.
* ``value``: the number used to compare (None when unknown or not a number).
* ``best``: True on the best value in the row (lowest cost, highest score and so on). A row where every known value
  is the same, or where fewer than two places have a value, marks no best.
* ``differs``: True when the known values are not all the same, so the page can highlight the row.
* ``tied``: True when two or more places share the best value (``best_note`` is then "tied", said once for the row).

Which way is better is set per row: ``low`` (cost, fees, commute minutes), ``high`` (score, size, newer year built) or
``None`` (a fact where neither is better, such as bedrooms: only differences are shown). An unknown value is never
best or worst, and a cost that leaves something out ("insurance not counted yet") is never marked lowest.
"""
from __future__ import annotations

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
    """Set ``best`` on the cells of one row, in place. Returns (differs, plain note about the best)."""
    known = [c["value"] for c in cells if c["value"] is not None]
    differs = len(set(round(v, 4) for v in known)) > 1
    for c in cells:
        c["best"] = False
        c["worst"] = False
    if not differs or better not in ("low", "high"):
        return differs, ""
    # An incomplete number (something left out of it) can't win; it also can't be called the worst.
    ranked = [c["value"] for c in cells if c["value"] is not None and not c.get("incomplete")]
    if len(set(round(v, 4) for v in ranked)) < 2:
        return differs, ""
    best, worst = (min(ranked), max(ranked)) if better == "low" else (max(ranked), min(ranked))
    for c in cells:
        ok = c["value"] is not None and not c.get("incomplete")
        c["best"] = ok and abs(c["value"] - best) < 1e-9
        c["worst"] = ok and abs(c["value"] - worst) < 1e-9
    if sum(1 for c in cells if c["best"]) > 1:
        return differs, "tied"
    return differs, "lowest" if better == "low" else "highest"


def _cell(text: Any, value: float | None = None, unknown_text: str = UNKNOWN) -> dict[str, Any]:
    unknown = text is None or text == ""
    return {"text": unknown_text if unknown else str(text), "value": value, "best": False, "worst": False,
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
    for line in p["cost"].get("lines", []):
        if line.get("estimated") and line.get("amount") is not None:
            label = line["label"]
            out.append(label if "guess" in label.lower() else f"{label} (a guess)")
    return out


def _not_counted_text(p: dict[str, Any]) -> str:
    if p["cost"]["missing"]:
        named = next((u for u in p["cost"].get("uncounted") or [] if u.startswith("utilities (")), "")  # names what the tenant pays
        return ", ".join(named if (named and m == "utilities estimate") else m for m in p["cost"]["missing"])
    guessed = guessed_list(p)
    return "nothing left out, but " + ", ".join(guessed) if guessed else "nothing, all costs are in"


def _num(v: Any, suffix: str = "") -> dict[str, Any]:
    return _cell(helpers.number_text(v) + suffix if v not in (None, "") else None, float(v) if v not in (None, "") else None)


def _yes_no(v: Any) -> dict[str, Any]:
    if v is None:
        return _cell(None)
    return _cell("Yes" if v else "No", 1.0 if v else 0.0)


def _cost_cell(p: dict[str, Any]) -> dict[str, Any]:
    cell = _money(p["cost_total"], True)
    unc = p["cost"].get("uncounted") or []
    if cell["value"] is not None and unc:
        cell["text"] += f" ({', '.join(unc)} not counted yet)"
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
    if _deposit_unknown(p, c):
        cell["text"] = f"at least {helpers.money(c['total'])} (deposit not known)"
        cell["incomplete"] = True
    return cell


def _assessment_cell(p: dict[str, Any]) -> dict[str, Any]:
    """A buyer's special assessment and who pays it. What the buyer pays is the number compared."""
    if p["cost"].get("mode") != "buy":
        return _cell(None)
    from .money import num
    sa = num(p.get("special_assessment"))
    if sa is None:
        return _cell(None, unknown_text=NOT_KNOWN)
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
    cell = _money(p.get("per_person"), True)
    if cell["value"] is not None and p["cost"].get("uncounted"):
        cell["incomplete"] = True
    if cell["value"] is not None:
        cell["text"] += f" ({p['people']} people)"
    return cell


FIT_TEXT = {"fits": "Yes", "doesnt_fit": "Doesn't fit", "check_first": "Check first: possible scam"}


def _fit_cell(p: dict[str, Any]) -> dict[str, Any]:
    fit = p["score"].get("fit", "fits")
    reasons = "; ".join(p["score"].get("fit_reasons") or [])
    return _cell(FIT_TEXT.get(fit, fit) + (f" ({reasons})" if reasons and fit != "fits" else ""))


def _score_cell(p: dict[str, Any]) -> dict[str, Any]:
    cell = _num(p["score_total"])
    n = p["score"].get("unknown_count") or 0
    if cell["value"] is not None and n:
        cell["text"] += f" (based on {n} unknown{'s' if n != 1 else ''})"
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
        rows.append(_row("person-" + name, f"{name}'s rating (1 to 5)", cells, "high", only_if_any=True))
    return rows


def _plain(text: Any) -> dict[str, Any]:
    return _cell(text or None)


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


def _row(key: str, label: str, cells: list[dict[str, Any]], better: str | None = None, *, only_if_any: bool = False) -> dict[str, Any] | None:
    if only_if_any and all(c["unknown"] for c in cells):
        return None
    differs, note = mark(cells, better)
    return {"key": key, "label": label, "cells": cells, "differs": differs, "best_note": note, "tied": note == "tied"}


def build_rows(places: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sections of rows for these enriched places (same order as ``places``)."""
    sections: list[dict[str, Any]] = []

    def section(title: str, rows: list[dict[str, Any] | None]) -> None:
        rows = [r for r in rows if r]
        if rows:
            sections.append({"title": title, "rows": rows})

    # ---- the headline numbers
    section("The short version", [
        _row("cost", "True monthly cost", [_cost_cell(p) for p in places], "low"),
        _row("per_person", "Per person each month", [_per_person_cell(p) for p in places], "low", only_if_any=True)
        if any(p.get("per_person") is not None for p in places) else None,
        _row("fit", "Does it fit?", [_fit_cell(p) for p in places]) if any(p["score"].get("fit", "fits") != "fits" for p in places) else None,
        _row("score", "Fit score (out of 100)", [_score_cell(p) for p in places], "high"),
        _row("stage", "Stage", [_plain(p["stage"]) for p in places]),
        _row("rating", "Your rating (1 to 5)", [_num(p.get("rating")) for p in places], "high", only_if_any=True),
        _row("opinions", "Average of the people's ratings (1 to 5)", [_opinion_cell(p) for p in places], "high", only_if_any=True)
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
            cells.append(_money(amount, True))
        cost_rows.append(_row("cost-" + key, label, cells, "low", only_if_any=True))
    cost_rows.append(_row("missing", "Not counted yet", [_plain(_not_counted_text(p)) for p in places]))
    section("What it really costs, line by line", cost_rows)

    # ---- the facts
    section("The place", [
        _row("price", "Price" if all(p["cost"].get("mode") == "buy" for p in places) else "Listed price", [_money(p.get("price")) for p in places], "low"),
        _row("down", "Down payment", [_money(p["cost"].get("down_payment")) if p["cost"].get("mode") == "buy" else _cell(None) for p in places], only_if_any=True),
        _row("assessment", "Special assessment (who pays it)", [_assessment_cell(p) for p in places], "low", only_if_any=True)
        if any(p["cost"].get("mode") == "buy" for p in places) else None,
        _row("loan", "Loan amount", [_money(p["cost"].get("loan_amount")) if p["cost"].get("mode") == "buy" else _cell(None) for p in places], "low", only_if_any=True),
        _row("beds", "Bedrooms", [_num(p.get("beds")) for p in places]),
        _row("baths", "Bathrooms", [_num(p.get("baths")) for p in places]),
        _row("sqft", "Size (sq ft, bigger is better)", [_num(p.get("sqft")) for p in places], "high"),
        _row("year_built", "Year built (newer is better)", [_year(p.get("year_built")) for p in places], "high"),
        _row("laundry", "Laundry", [_cell(LAUNDRY_TEXT.get(p.get("laundry") or ""), LAUNDRY_RANK.get(p.get("laundry") or "")) for p in places], "high"),
        _row("dishwasher", "Dishwasher", [_yes_no(p.get("dishwasher")) for p in places], "high"),
        _row("parking", "Parking", [_cell(PARKING_TEXT.get(p.get("parking") or ""), PARKING_RANK.get(p.get("parking") or "")) for p in places], "high"),
        _row("pets", "Pets", [_cell(PETS_TEXT.get(p.get("pets") or "")) for p in places]),
        _row("utilities", "Utilities included", [_plain(p.get("utilities_included")) for p in places], only_if_any=True),
    ])
    section("Dates and money up front", [
        _row("available", "Available from", [_plain(helpers.day_text(p["available_from"]) if p.get("available_from") else "") for p in places], only_if_any=True),
        _row("lease_months", "Lease length (months)", [_num(p.get("lease_months")) for p in places], only_if_any=True),
        _row("months_up_front", "Months of rent due before move-in",
             [_num(money_mod.months_up_front(p)) if p["cost"].get("mode") == "rent" else _cell(None) for p in places], "low", only_if_any=True)
        if any(p["cost"].get("mode") == "rent" and money_mod.months_up_front(p) > 1 for p in places) else None,
        _row("cash_up_front", _cash_label(places), [_cash_cell(p) for p in places],
             "low" if len({p["cost"].get("mode") for p in places}) == 1 else None, only_if_any=True),
        _row("days_on_market", "Days on the market", [_num(p.get("days_on_market")) for p in places], only_if_any=True)
        if any(p["cost"].get("mode") == "buy" for p in places) else None,
        _row("deposit", "Deposit (comes back)", [_money(p.get("deposit")) for p in places], "low", only_if_any=True),
        _row("upfront", "Fees paid once (application, move-in, broker, pet)", [_money(None if _one_time_unset(p) else p["cost"].get("one_time_total")) if p["cost"].get("mode") == "rent" else _cell(None) for p in places], "low", only_if_any=True),
    ])

    # ---- commutes: one row per anchor, using the mode of that anchor's commute criterion
    anchors: list[tuple[Any, str]] = []
    for p in places:
        for c in p.get("commute_all", []):
            if not any(c["anchor"] == name for _, name in anchors):
                anchors.append((c["anchor_id"], c["anchor"]))
    commute_rows = []
    for aid, name in anchors:
        cells, mode = [], ""
        for p in places:
            c = next((x for x in p.get("commute_all", []) if x["anchor"] == name), None)
            mode = mode or (c["mode"] if c else "")
            cells.append(_cell(c["label"], float(c["minutes"])) if c else _cell(None))
        commute_rows.append(_row(f"commute-{aid}", f"To {name}" + (f" ({mode})" if mode else ""), cells, "low"))
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
        score_rows.append(_row("score-" + label, label, cells, "high"))
    score_rows.append(_row("unknown", "Still unknown", [_plain(", ".join(unknown_list(p)) or "nothing, everything is filled in") for p in places]))
    section("Score, one thing at a time", score_rows)
    return sections


def summary_lines(places: list[dict[str, Any]], sections: list[dict[str, Any]]) -> list[str]:
    """A few plain sentences: who is cheapest and who scores highest (several places can be tied)."""
    out: list[str] = []
    for key, what in (("cost", "lowest true monthly cost"), ("score", "highest fit score")):
        for sec in sections:
            for row in sec["rows"]:
                if row["key"] == key and row["differs"]:
                    winners = [p["title"] for p, c in zip(places, row["cells"]) if c["best"]]
                    if len(winners) > 1:
                        out.append(f"{' and '.join(winners)} are tied for the {what}.")
                    elif winners:
                        out.append(f"{winners[0]} has the {what}.")
    return out
