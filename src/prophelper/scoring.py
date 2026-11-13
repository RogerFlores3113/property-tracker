"""Weighted scoring of a place against a search's criteria (DESIGN section 3). Pure: no database, no web.

``score_place`` returns, for one place:

* ``items``: one dict per criterion with ``score`` (0 to 1), ``known`` (False when the place has no value, which
  scores 0.5), ``dealbreaker_status`` (``""`` when the criterion is not a deal-breaker, else ``"pass"``, ``"fail"`` or
  ``"check"``), the place's ``value`` and the wanted ``target`` as plain words, and a short ``detail`` line.
* ``total``: 0 to 100, ``100 * sum(weight * score) / sum(weight)`` rounded, or None when there is nothing to score.
* ``unknown``, ``failed`` and ``check``: labels, so a page can say what to fill in.
* ``fails_dealbreaker`` / ``needs_check``: booleans for the "doesn't fit" badge and for the "check this" note.
* ``fit``: the one shared state every page and tool reads: ``"fits"``, ``"near_miss"`` (a must-have missed by a little,
  under 3 percent or only because of a guess; ``fit_reasons`` and ``near_texts`` say how much and why),
  ``"doesnt_fit"`` (a deal-breaker fails; ``fit_reasons`` says each gap, such as "Over budget by $6") or
  ``"check_first"`` (a serious red flag, ``fit_reasons`` says why). ``fit_label`` is its plain-words name
  ("Fits, but check" when a fitting place has ``concerns``). The total is capped (49 when a
  deal-breaker fails, 50 for a serious red flag) so a place that fails never looks like a great match, and
  ``raw_total`` keeps the uncapped number. ``sort_group`` is 0 for ``fits``, 1 for ``near_miss``, 2 for ``doesnt_fit`` and 3 for a
  possible scam (``check_first``, even when it also fails a deal-breaker): sort on it first.
* ``conditional``: labels of price must-haves that pass only because a cost is unknown (the score is capped at 85).
* ``unknown_count``: how many criteria rest on an unknown value (each scored at 0.5).
"""
from __future__ import annotations

from typing import Any, Iterable

from . import commute as commute_mod
from . import money, redflags

KINDS: tuple[str, ...] = ("price", "beds", "baths", "sqft", "commute", "laundry", "dishwasher", "parking", "pets",
                          "fenced_yard", "newer", "custom")
KIND_LABELS: dict[str, str] = {
    "price": "Monthly cost", "beds": "Bedrooms", "baths": "Bathrooms", "sqft": "Size", "commute": "Commute",
    "laundry": "Laundry", "dishwasher": "Dishwasher", "parking": "Parking", "pets": "Pets", "fenced_yard": "Fenced yard", "newer": "Newer building",
    "custom": "Your own score",
}
UNKNOWN_SCORE = 0.5
CAP_DEALBREAKER = 49
CAP_SCAM = 50
CAP_NEAR = 74  # a must-have missed by a little, only because of a guess
CAP_FAR_COMMUTE = 69  # someone's commute is more than a quarter over their limit: not a "good" match
CAP_MOSTLY_UNKNOWN = 59
CAP_UNKNOWN_COST = 85  # a price must-have that passes only while a cost is unknown
NEAR_MISS_PCT = 0.03  # a must-have missed by less than this share is a near miss
SORT_GROUPS = {"fits": 0, "near_miss": 1, "doesnt_fit": 2, "check_first": 3}
FIT_LABELS = {"fits": "Yes", "near_miss": "Near miss", "doesnt_fit": "Doesn't fit", "check_first": "Check first: possible scam"}
LATE_PENALTY = 10
LAUNDRY_RANK = {"in_unit": 3, "in_building": 2, "hookups": 1, "none": 0}
LAUNDRY_WORDS = {"in_unit": "in the unit", "in_building": "in the building", "hookups": "hookups only", "none": "none"}
PARKING_RANK = {"garage": 3, "covered": 2, "lot": 1, "street": 0, "none": -1}
PETS_OK = {"cats": ("cats", "both"), "dogs": ("dogs", "both"), "both": ("both",)}


def _num(v: Any) -> float | None:
    return money.num(v)


def _fmt(n: float | None, prefix: str = "", suffix: str = "") -> str:
    if n is None:
        return ""
    if prefix == "$" or abs(n - round(n)) < 1e-9:
        return f"{prefix}{n:,.0f}{suffix}"
    return f"{prefix}{n:,.1f}{suffix}"


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def default_label(kind: str, target: dict[str, Any] | None = None, mode: str = "rent", anchor_name: str = "") -> str:
    """A plain label for a criterion made without one: 'Monthly cost, at most $1,600' (or 'Price, at most $340,000'
    when buying). A commute label names its place when ``anchor_name`` is given."""
    t = target or {}
    if kind == "price":
        if mode == "buy":
            return f"Price, at most {_fmt(_num(t.get('max')), '$')}" if _num(t.get("max")) else "Price"
        return f"Monthly cost, at most {_fmt(_num(t.get('max')), '$')}" if _num(t.get("max")) else KIND_LABELS[kind]
    if kind in ("beds", "baths"):
        return f"{KIND_LABELS[kind]}, at least {_fmt(_num(t.get('min')))}" if _num(t.get("min")) is not None else KIND_LABELS[kind]
    if kind == "sqft":
        return f"Size, at least {_fmt(_num(t.get('min')), '', ' sq ft')}" if _num(t.get("min")) else KIND_LABELS[kind]
    if kind == "commute":
        mins, mode = _num(t.get("minutes")), t.get("mode") or "bike"
        where = f" to {anchor_name}" if anchor_name else ""
        return f"Commute{where} by {mode}, {_fmt(mins, '', ' min')} or less" if mins else f"Commute{where}"
    if kind == "laundry":
        return "Washer and dryer in the unit" if (t.get("want") or "in_unit") == "in_unit" else "Laundry in the building"
    if kind == "fenced_yard":
        return "Fenced yard"
    if kind == "newer":
        return f"Built {t['year']} or later" if t.get("year") else KIND_LABELS[kind]
    return KIND_LABELS.get(kind, kind.title())


def _auto_label(kind: str, target: dict[str, Any], ctx: dict[str, Any]) -> str:
    """The label for a criterion saved without one. A commute names its important place, so two never read the same."""
    if kind == "commute":
        anchors = ctx.get("anchors", {})
        a = anchors.get(target.get("anchor_id")) if target.get("anchor_id") is not None else next(iter(anchors.values()), None)
        if a:
            return commute_mod.commute_label(target.get("mode") or "bike", _num(target.get("minutes")), a["name"])
    return default_label(kind, target, ctx.get("mode", "rent"))


def _result(score: float | None, value: str, target: str, detail: str, *, known: bool, passes: bool | None,
            gap: str = "") -> dict[str, Any]:
    return {"score": UNKNOWN_SCORE if score is None else _clamp(score), "known": known, "value": value, "target": target,
            "detail": detail, "passes": passes, "gap": gap}


def _unknown(target: str, what: str) -> dict[str, Any]:
    return _result(None, "", target, f"{what} is not filled in, so it counts as a maybe.", known=False, passes=None)


NEAR_OVER = 0.05  # this far over the target scores NEAR_SCORE; the curve then falls to 0 at 25% over
NEAR_SCORE = 0.6


def over_score(over_ratio: float) -> float:
    """Score for being ``over_ratio`` (0.05 is 5 percent) above a cost target: steep at first (5 percent over scores
    0.6), then straight down to 0 at 25 percent over."""
    if over_ratio <= 0:
        return 1.0
    if over_ratio <= NEAR_OVER:
        return 1 - (1 - NEAR_SCORE) * over_ratio / NEAR_OVER
    return max(0.0, NEAR_SCORE * (1 - (over_ratio - NEAR_OVER) / (0.25 - NEAR_OVER)))


def _buyer_assessment(place: dict[str, Any]) -> float:
    """A special assessment the buyer pays (0 otherwise). It is in the cash to close, and the price score only says so."""
    sa = _num(place.get("special_assessment"))
    return sa if sa and str(place.get("special_assessment_payer") or "") == "buyer" else 0.0


NEAR_GUESS = 0.05  # over by this share or less, only because of a guess, is a near miss and not a fail
_PART_NAMES = {"utilities": "utilities", "parking": "parking", "pet_rent": "pet rent", "other": "other fees"}


def _cost_parts(cost: dict[str, Any]) -> tuple[float | None, list[str], float]:
    """(rent, ['utilities guess $180', ...], the guessed part) from a rent cost breakdown."""
    rent, parts, guess = None, [], 0.0
    for line in cost.get("lines") or []:
        amount = line.get("amount")
        if line["key"] == "price":
            rent = amount
        elif line["key"] in _PART_NAMES and amount:
            est = bool(line.get("estimated"))
            parts.append(f"{_PART_NAMES[line['key']]}{' guess' if est else ''} {_fmt(amount, '$')}")
            if est:
                guess += amount
    return rent, parts, guess


def _score_price(c: dict[str, Any], place: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Rent compares the true monthly cost to the cap (or the rent alone when the rule says "count rent only"). Buy
    compares the listed PRICE to the cap (not the monthly cost). The detail always says what was compared."""
    t = c["target"]
    limit = _num(t.get("max")) or _num(ctx.get("budget_max"))
    buying = ctx.get("mode") == "buy"
    guess = 0.0
    rent_only = False
    if buying:
        have = _num(place.get("price"))
        what, unit = "The price", ""
        target = f"at most {_fmt(limit, '$')}" if limit else "no limit set"
        shown = f"{_fmt(have, '$')}" if have is not None else ""
    else:
        cost = ctx.get("cost") or {}
        rent, parts, guess = _cost_parts(cost)
        rent_only = str(t.get("count") or "") == "rent"
        what = "The rent" if rent_only else "The monthly cost"
        if rent_only:
            have, unit, guess = rent, " a month, rent only", 0.0
            shown = f"{_fmt(have, '$')} a month, rent only" if have is not None else ""
        else:
            have, unit = cost.get("total"), " a month"
            if have is not None and parts and rent is not None:
                shown = f"{_fmt(have, '$')} a month all in (rent {_fmt(rent, '$')} + {' + '.join(parts)})"
            else:
                shown = f"{_fmt(have, '$')} a month" if have is not None else ""
        target = (f"at most {_fmt(limit, '$')} a month" + (", rent only" if rent_only else " all in")) if limit else "no limit set"
    if have is None:
        return _unknown(target, what)
    value = shown or f"{_fmt(have, '$')}{unit}"
    if not limit:
        return _result(1.0, value, target, f"{value}. No price limit set on this search.", known=True, passes=True)
    note = ""
    if buying and _buyer_assessment(place):
        note = (f" A special assessment of {_fmt(_buyer_assessment(place), '$')} that you pay is not in this score; "
                "it is in the cash to close.")
    if have <= limit:
        r = _result(1.0, value, target, f"{value}, {_fmt(limit - have, '$')} under your limit.{note}",
                    known=True, passes=True)
        unknown_costs = list((ctx.get("cost") or {}).get("uncounted") or []) if not buying and not rent_only else []
        if unknown_costs:
            names = ", ".join(unknown_costs)
            r["detail"] += f" This passes only if the unknown costs are small: {names} not counted yet."
            r["conditional"] = names
        return r
    over = have - limit
    score = over_score(over / limit)
    near = guess > 0 and have - guess <= limit + 1e-9 and over / limit <= NEAR_GUESS
    detail = f"{value}, {_fmt(over, '$')} over your limit of {_fmt(limit, '$')}."
    if near:
        detail += " It is only over because of the utilities guess, so this is a near miss."
    detail += note
    r = _result(score, value, target, detail, known=True, passes=False,
                gap=f"Over budget by {_fmt(over, '$')}" if buying else f"{value}, over {_fmt(limit, '$')} by {_fmt(over, '$')}")
    r["over_amount"], r["over_pct"], r["near"] = over, over / limit, near
    return r


_NEAR_NAMES = {"pet_rent": ("pet rent", "counts"), "utilities": ("the utilities estimate", "counts"), "parking": ("parking", "counts"),
               "other": ("the other monthly fees", "count"), "one_time": ("the one-time fees", "count")}


def _near_reason(cost: dict[str, Any] | None, over: float, guessed: bool) -> str:
    """' because pet rent counts' for the first cost line that, left out, would bring the place under the limit."""
    lines = (cost or {}).get("lines") or []
    for line in lines:
        if line["key"] in _NEAR_NAMES and (line["amount"] or 0) >= over - 1e-9 and (line["amount"] or 0) > 0:
            if guessed and line["key"] == "utilities" and line.get("estimated"):
                return " because the utilities guess counts"
            name, verb = _NEAR_NAMES[line["key"]]
            return f" because {name} {verb}"
    if guessed:
        return " because the utilities guess counts" if any(l["key"] == "utilities" and l.get("estimated") for l in lines) \
            else " because a guessed cost counts"
    return ""


def near_parts(score: dict[str, Any], cost: dict[str, Any] | None) -> list[dict[str, str]]:
    """When every missed must-have is a small miss (a guess-only overage, or under 3 percent), one ``{"label", "text"}``
    per miss: '$51 over because the utilities guess counts'. Otherwise []. The one rule for a "near miss"."""
    items = score.get("items") or []
    misses = [i for i in items if i.get("dealbreaker_status") in ("fail", "near")]
    if not misses:
        return []
    out = []
    for item in misses:
        over, pct = item.get("over_amount"), item.get("over_pct")
        if over is None or pct is None or over <= 0 or (pct >= NEAR_MISS_PCT and item.get("dealbreaker_status") != "near"):
            return []
        if item["kind"] == "price":
            text = f"${over:,.0f} over" + _near_reason(cost, over, bool(item.get("near")))
        else:
            text = item.get("gap") or f"{item.get('label', 'A must-have')} is just short"
        shown = ("Price" if (cost or {}).get("mode") == "buy" else KIND_LABELS["price"]) if item["kind"] == "price" else item.get("label") or ""
        out.append({"label": shown, "kind": item["kind"], "text": text})
    return out


def _beds_word(n: float) -> str:
    return "Studio" if n == 0 else f"{_fmt(n)} bedroom{'' if n == 1 else 's'}"


def _score_min(c: dict[str, Any], place: dict[str, Any], field: str, label: str, unit: str) -> dict[str, Any]:
    want = _num(c["target"].get("min"))
    target = f"at least {_fmt(want, '', unit)}" if want is not None else "any"
    have = _num(place.get(field))
    if have is None:
        return _unknown(target, label)
    value = "Studio" if field == "beds" and have == 0 else _fmt(have, '', unit)
    if want is None or have >= want:
        return _result(1.0, value, target, "Meets it.", known=True, passes=True)
    if field == "sqft":
        score = (have - 0.6 * want) / (0.4 * want) if want > 0 else 0.0
    else:
        score = 0.5 if have >= want - 1 else 0.0
    if field == "beds":
        gap = f"{value}, you need {_beds_word(want)}"
    else:
        gap = f"{label.replace('The ', '').capitalize()} {value}, wanted {target}"
    r = _result(score, value, target, "Below what you wanted.", known=True, passes=False, gap=gap)
    if field == "sqft" and want and want > 0:
        r["over_amount"], r["over_pct"] = want - have, (want - have) / want
    return r


def _commute_anchors(t: dict[str, Any], ctx: dict[str, Any]) -> list[dict[str, Any]]:
    """The places this commute rule checks: the one chosen; every important place when the rule says so or when
    several people share the search (each person's commute counts); else the first one."""
    anchors = ctx.get("anchors", {})
    if t.get("anchor_id") is not None:
        a = anchors.get(t["anchor_id"])
        return [a] if a else []
    if anchors and (t.get("all_anchors") or int(ctx.get("people") or 1) > 1):
        return list(anchors.values())
    first = next(iter(anchors.values()), None)
    return [first] if first else []


def _score_commute(c: dict[str, Any], place: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    t = c["target"]
    mins = _num(t.get("minutes"))
    mode = t.get("mode") or "bike"
    chosen = _commute_anchors(t, ctx)
    many = len(chosen) > 1
    anchor_name = "everyone's places" if many else (chosen[0]["name"] if chosen else "that place")
    target = f"{_fmt(mins, '', ' min')} or less by {mode} to {anchor_name}" if mins else "any"
    if not chosen:
        gone = t.get("anchor_id") is not None
        return _result(None, "", target, "The important place you wanted to reach was removed, so choose another one in What matters." if gone
                       else "There is no important place yet. Add one on the Search page, like Work or Campus.", known=False, passes=None)
    found_all, missing = [], []
    for anchor in chosen:
        found = commute_mod.resolve(place, anchor, mode, ctx.get("commutes", ()))
        if found is None:
            missing.append(anchor)
        else:
            found_all.append((anchor, found))
    if not found_all:
        anchor = missing[0]
        if not commute_mod.has_point(anchor):
            return _result(None, "", target, commute_mod.NO_LOCATION_MESSAGE.format(name=anchor["name"]), known=False, passes=None)
        return _unknown(target, f"The {mode} time to {anchor['name']}")
    if many:
        value = ", ".join(f"{a['name']} {f['minutes']:.0f} min" for a, f in found_all)
    else:
        value = found_all[0][1]["label"]
    if not mins:
        return _result(1.0, value, target, "", known=True, passes=True)
    over = [(a, f) for a, f in found_all if f["minutes"] > mins]
    worst = max(f["minutes"] for _, f in found_all)
    score = 1.0 if worst <= mins else 1 - (worst - mins) / mins
    if over:
        who = [f"{a['name']}: {f['minutes']:.0f} min, limit {mins:.0f}" for a, f in over] if many \
            else [f"Commute {over[0][1]['minutes']:.0f} min, limit {mins:.0f}"]
        detail = ("; ".join(who) + ".") if many else f"{worst - mins:.0f} min over your limit."
    else:
        detail = "Everyone is within your limit." if many else "Within your limit."
    if any(f["source"] == "estimate" for _, f in found_all):
        detail += " This is an estimate from the map, so check it."
    if missing:
        detail += " No time yet for " + ", ".join(a["name"] for a in missing) + "."
    gap = "; ".join(who) if over else ""
    if over and not many and len(ctx.get("anchors", {})) > 1:
        gap += f" ({over[0][0]['name']})"
    r = _result(score, value, target, detail, known=True, passes=not over, gap=gap)
    if over:
        r["over_amount"], r["over_pct"] = worst - mins, (worst - mins) / mins
        r["concern"] = gap
    return r


def _score_laundry(c: dict[str, Any], place: dict[str, Any]) -> dict[str, Any]:
    want = c["target"].get("want") or "in_unit"
    target = LAUNDRY_WORDS.get(want, "in the unit")
    have = str(place.get("laundry") or "")
    if have not in LAUNDRY_RANK:
        return _unknown(target, "Laundry")
    if want == "in_unit":
        score = {"in_unit": 1.0, "in_building": 0.5, "hookups": 0.25, "none": 0.0}[have]
    else:
        score = {"in_unit": 1.0, "in_building": 1.0, "hookups": 0.25, "none": 0.0}[have]
    return _result(score, LAUNDRY_WORDS[have], target, "", known=True, passes=score >= 1.0,
                   gap="" if score >= 1.0 else f"Laundry: {LAUNDRY_WORDS[have]}, wanted {target}")


def _score_yes(value_known: bool, yes: bool, target: str, value: str, what: str) -> dict[str, Any]:
    if not value_known:
        return _unknown(target, what)
    return _result(1.0 if yes else 0.0, value, target, "", known=True, passes=yes,
                   gap="" if yes else f"{what}: {value}, wanted {target}")


def _score_dishwasher(c: dict[str, Any], place: dict[str, Any]) -> dict[str, Any]:
    d = place.get("dishwasher")
    return _score_yes(d is not None, bool(d), "has one", "yes" if d else "no", "Dishwasher")


def _score_parking(c: dict[str, Any], place: dict[str, Any]) -> dict[str, Any]:
    want = c["target"].get("want") or "lot"
    have = str(place.get("parking") or "")
    target = "off-street parking" if want == "lot" else f"{want} parking"
    if have not in PARKING_RANK:
        return _unknown(target, "Parking")
    ok = PARKING_RANK[have] >= PARKING_RANK.get(want, 1)
    return _score_yes(True, ok, target, have, "Parking")


_PROFILE_WANT = {"cat": "cats", "dog": "dogs", "both": "both"}


def _score_pets(c: dict[str, Any], place: dict[str, Any], ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    """The pet policy, then (when the search says what pets you have) the place's weight and count limits."""
    profile = (ctx or {}).get("pets") or {}
    kind = profile.get("kind") or ""
    want = c["target"].get("want") or _PROFILE_WANT.get(kind, "")
    have = str(place.get("pets") or "")
    target = f"{want} allowed" if want else "pets allowed"
    if have not in ("cats", "dogs", "both", "none"):
        return _unknown(target, "The pet policy")
    ok = have in PETS_OK.get(want, ("cats", "dogs", "both"))
    value = have if have != "none" else "no pets"
    if not ok or not kind:
        return _score_yes(True, ok, target, value, "The pet policy")
    has_dog = kind in ("dog", "both")
    weight, count = _num(profile.get("weight")), _num(profile.get("count"))
    w_limit, c_limit = _num(place.get("pet_weight_limit")), _num(place.get("pet_count_limit"))
    problems: list[str] = []
    unknown: list[str] = []
    if has_dog and weight:
        if w_limit is None:
            unknown.append("weight limit")
        elif weight > w_limit:
            problems.append(f"Your dog is {_fmt(weight)} lb; limit {_fmt(w_limit)} lb")
    if count:
        if c_limit is None:
            if count > 1:  # one pet is nearly always fine, so only more than one needs the limit
                unknown.append("number of pets allowed")
        elif count > c_limit:
            problems.append(f"You have {_fmt(count)} pets; limit {_fmt(c_limit)}")
    if problems:
        return _result(0.0, value, target, "; ".join(problems) + ".", known=True, passes=False, gap="; ".join(problems))
    if unknown:
        return _result(None, value, target, "The " + " and the ".join(unknown) + " is not filled in, so it counts as a maybe.",
                       known=False, passes=None)
    limits = ([f"limit {_fmt(w_limit)} lb"] if has_dog and weight and w_limit is not None else []) \
        + ([f"up to {_fmt(c_limit)} pets"] if count and c_limit is not None else [])
    return _result(1.0, value, target, "Fits your pets" + (f" ({', '.join(limits)})." if limits else "."), known=True, passes=True)


def _score_fenced_yard(c: dict[str, Any], place: dict[str, Any]) -> dict[str, Any]:
    d = place.get("fenced_yard")
    return _score_yes(d is not None, bool(d), "a fenced yard", "yes" if d else "no", "The fenced yard")


def _score_newer(c: dict[str, Any], place: dict[str, Any]) -> dict[str, Any]:
    year = _num(c["target"].get("year")) or 2000
    have = _num(place.get("year_built"))
    target = f"built {_fmt(year)} or later"
    if have is None:
        return _unknown(target, "The year built")
    return _score_yes(True, have >= year, target, f"built {_fmt(have)}", "The year built")


def _score_custom(c: dict[str, Any], place: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    given = (ctx.get("custom_scores") or {}).get(c.get("id"))
    target = "your own score, 0 to 5"
    if given is None:
        return _unknown(target, "Your score")
    return _result(_num(given) / 5.0, f"{_fmt(_num(given))} of 5", target, "", known=True, passes=_num(given) > 0,
                   gap="" if _num(given) > 0 else "Your own score is 0")


def score_criterion(c: dict[str, Any], place: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """One criterion against one place. ``ctx``: cost, budget_max, anchors ({id: anchor}), commutes, custom_scores."""
    kind = c["kind"]
    if kind == "price":
        r = _score_price(c, place, ctx)
    elif kind == "beds":
        r = _score_min(c, place, "beds", "Bedrooms", " bed")
    elif kind == "baths":
        r = _score_min(c, place, "baths", "Bathrooms", " bath")
    elif kind == "sqft":
        r = _score_min(c, place, "sqft", "The size", " sq ft")
    elif kind == "commute":
        r = _score_commute(c, place, ctx)
    elif kind == "laundry":
        r = _score_laundry(c, place)
    elif kind == "dishwasher":
        r = _score_dishwasher(c, place)
    elif kind == "parking":
        r = _score_parking(c, place)
    elif kind == "pets":
        r = _score_pets(c, place, ctx)
    elif kind == "fenced_yard":
        r = _score_fenced_yard(c, place)
    elif kind == "newer":
        r = _score_newer(c, place)
    elif kind == "custom":
        r = _score_custom(c, place, ctx)
    else:
        r = _unknown("", kind)
    if not c.get("dealbreaker"):
        r.pop("conditional", None)  # only a must-have is held back by an unknown cost
        status = ""
    elif r["passes"] is None:
        status = "check"
    elif not r["passes"] and r.get("near"):
        status = "near"  # over only because of a guess, and by a little: not a hard fail
    else:
        status = "pass" if r["passes"] else "fail"
    return {"id": c.get("id"), "kind": kind, "label": c.get("label") or _auto_label(kind, c["target"], ctx),
            "weight": c.get("weight", 0), "dealbreaker": bool(c.get("dealbreaker")), "dealbreaker_status": status, **r}


def has_serious_flag(place: dict[str, Any], peer_prices: Iterable[float] = ()) -> bool:
    """True when the listing shows a serious scam sign. The rule lives in ``redflags.is_serious``."""
    return redflags.is_serious(place, peer_prices)


def starter_criteria(mode: str, budget_max: Any, bedrooms: Any, have_kinds: Iterable[str] = ()) -> list[dict[str, Any]]:
    """The must-haves a new search gets by itself: Bedrooms (when it names a bedroom count of 1 or more) and Monthly cost
    or Price (when it has a budget). A kind the caller already has is skipped, so nothing doubles. Each is
    ``{kind, label, weight, dealbreaker, target}`` ready for ``store.add_criterion``; the target is marked ``auto``."""
    have = set(have_kinds)
    out: list[dict[str, Any]] = []
    budget, beds = _num(budget_max), _num(bedrooms)
    if budget and budget > 0 and "price" not in have:
        t = {"max": budget, "auto": True}
        out.append({"kind": "price", "label": default_label("price", t, mode), "weight": 20, "dealbreaker": True, "target": t})
    if beds and beds >= 1 and "beds" not in have:
        t = {"min": beds, "auto": True}
        out.append({"kind": "beds", "label": default_label("beds", t, mode), "weight": 15, "dealbreaker": True, "target": t})
    return out


def _late_opening(place: dict[str, Any], search: dict[str, Any] | None, mode: str) -> str:
    """The plain reason when a rental opens well after the move-in date ('' otherwise). Early openings are only a note."""
    if not search or mode == "buy":
        return ""
    from . import movein  # late import: movein reads today, which reads enrich, which reads this module
    msg = movein.gap_warning(place, {**search, "mode": mode})
    return msg if msg and "after your move-in" in msg else ""


def score_place(place: dict[str, Any], criteria: Iterable[dict[str, Any]], *, mode: str = "rent",
                anchors: Iterable[dict[str, Any]] = (), commutes: Iterable[dict[str, Any]] = (),
                custom_scores: dict[int, float] | None = None, budget_max: float | None = None,
                settings: dict[str, Any] | None = None, cost: dict[str, Any] | None = None,
                serious_flag: bool | None = None, people: int = 1,
                pets: dict[str, Any] | None = None, search: dict[str, Any] | None = None,
                adults: Any = None) -> dict[str, Any]:
    """Score a place. ``criteria`` rows have ``kind``, ``weight``, ``dealbreaker`` and ``target`` (a dict).
    ``commutes`` are the place's stored commute rows; ``cost`` can be passed to avoid computing it twice.
    ``pets`` is the search's pet profile ({kind, weight, count}); without it only the pet policy is checked.
    ``serious_flag`` says the listing shows a serious scam sign (worked out from the text when left as None).
    ``search`` (optional) lets a place that opens well after the move-in date count against fit.
    Also returned: ``near`` (must-haves missed by a little, only because of a guess), ``concerns`` (plain reasons a
    fitting place still loses points: a person's commute over the limit, a late opening) and ``caps`` (why the total
    was held down)."""
    ctx = {"cost": cost if cost is not None else money.true_monthly_cost(place, mode, settings, people, adults=adults),
           "budget_max": budget_max, "anchors": {a["id"]: a for a in anchors}, "commutes": list(commutes),
           "custom_scores": custom_scores or {}, "mode": mode, "pets": pets or {}, "people": people}
    items = [score_criterion(c, place, ctx) for c in criteria]
    total_w = sum(max(0.0, float(i["weight"] or 0)) for i in items)
    raw = None
    if items and total_w > 0:
        raw = int(round(100 * sum(max(0.0, float(i["weight"] or 0)) * i["score"] for i in items) / total_w + 1e-9))
    failed = [i["label"] for i in items if i["dealbreaker_status"] == "fail"]
    near = [i["label"] for i in items if i["dealbreaker_status"] == "near"]
    check = [i["label"] for i in items if i["dealbreaker_status"] == "check"]
    scam = has_serious_flag(place) if serious_flag is None else bool(serious_flag)
    reasons = [i["gap"] or f"Fails: {i['label']}" for i in items if i["dealbreaker_status"] == "fail"]
    concerns = [i["gap"] for i in items if i["dealbreaker_status"] == "near" and i["gap"]]
    concerns += [i["concern"] for i in items if i.get("concern") and i["dealbreaker_status"] != "fail"]
    far_commute = any(i.get("concern") and (i.get("over_pct") or 0) > 0.25 for i in items)
    late = _late_opening(place, search, mode)
    if late:
        concerns.append(late)
        if raw is not None:
            raw = max(0, raw - LATE_PENALTY)
    conditional = [i["label"] for i in items if i.get("conditional") and i["dealbreaker_status"] == "pass"]
    for i in items:
        if i.get("conditional") and i["dealbreaker_status"] == "pass":
            concerns.append(f"{i['label']} passes only if the unknown costs are small ({i['conditional']})")
    fit = "fits"
    total = raw
    caps: list[str] = []

    def cap(n: int, why: str) -> None:
        nonlocal total
        if total is not None and total > n:
            total = n
            caps.append(why)
    parts_ = near_parts({"items": items}, ctx["cost"]) if (failed or near) else []
    if failed:
        fit = "near_miss" if parts_ else "doesnt_fit"
        cap(CAP_DEALBREAKER, "a must-have fails")
    elif near:
        fit = "near_miss"
    if near:
        cap(CAP_NEAR, "a must-have is just over")
    if far_commute:
        cap(CAP_FAR_COMMUTE, "someone's commute is well over the limit")
    if conditional:
        cap(CAP_UNKNOWN_COST, "a cost is not known yet, so the price only passes if it is small")
    if check:  # unknown must-haves: neutral-ish, but never a high score
        cap({1: 80, 2: 65}.get(len(check), 55), f"{len(check)} must-have{'s' if len(check) != 1 else ''} not known yet")
    unknown_n = sum(1 for i in items if not i["known"])
    if unknown_n >= 3 and unknown_n * 2 >= len(items):
        cap(CAP_MOSTLY_UNKNOWN, "most of what matters is not known yet")
    if scam:
        fit = "check_first"
        reasons = ["Check first: possible scam. Do not pay anything before you have toured it."] + reasons
        cap(CAP_SCAM, "possible scam")
    near_texts = [f"{p['label']} {p['text']}" if p["kind"] == "price" else p["text"] for p in parts_] if fit == "near_miss" else []
    if fit == "near_miss":
        reasons = near_texts
        concerns[:] = [c for c in concerns if c not in {i["gap"] for i in items if i["dealbreaker_status"] == "near"}]
    if late:
        concerns[:] = [c for c in concerns if c != late]
        concerns.append(f"{late}, so the score is {LATE_PENALTY} points lower")
    unknown = [i["label"] for i in items if not i["known"]]
    fit_label = "Fits, but check" if fit == "fits" and concerns else FIT_LABELS[fit] if fit != "fits" else "Fits"
    return {"total": total, "raw_total": raw, "items": items, "unknown": unknown, "unknown_count": len(unknown),
            "failed": failed, "near": near, "concerns": concerns, "caps": caps, "check": check, "fails_dealbreaker": bool(failed), "needs_check": bool(check),
            "fit": fit, "fit_label": fit_label, "fit_reasons": reasons, "near_texts": near_texts, "near_parts": parts_ if fit == "near_miss" else [], "conditional": conditional,
            "conditional_costs": [i["conditional"] for i in items if i.get("conditional") and i["dealbreaker_status"] == "pass"],
            "late_penalty": LATE_PENALTY if late else 0, "late_note": late,
            "scam": scam, "sort_group": SORT_GROUPS[fit], "cost": ctx["cost"]}


def sort_key(p: dict[str, Any]) -> tuple[int, int, str]:
    """Order for a list of enriched places: places that fit first, best score first, then by name."""
    score = p.get("score") or {}
    total = p.get("score_total")
    return (score.get("sort_group", 0), -(total if total is not None else -1), str(p.get("title", "")).lower())


def score_band(total: int | None) -> str:
    """'good' (70 and up), 'ok' (40 to 69), 'low' (under 40) or '' when there is no score."""
    if total is None:
        return ""
    return "good" if total >= 70 else "ok" if total >= 40 else "low"
