"""No silent drops (cycle 20): a last check that every dollar figure a rental listing gives is placed in a field, explained by a note,
a known non-cost (a late fee, an old price, a seasonal pair), or the rent itself. ``find_unplaced`` returns the figures that are none of
these, and the readers' safety net turns each into a plain note that quotes its phrase. It never changes a field.

The check reads the item the figure sits in ("Application $35", "Parking permit $120/yr", "gas - tenant, $35/mo"), decides what kind of
cost the item names, and then asks whether the field for that kind holds the figure (or the figure over the period the item names).
Utility figures are placed only when some of them add up to the saved utilities estimate, so one the reader left out of the sum is caught."""
from __future__ import annotations

import re
from typing import Any

ENABLED = True  # tests switch it off to see what the readers alone leave out

_NON_COST = re.compile(
    r"\blate (?:fee|charge|rent|payment)|\bpenalt|\bbounced|\breturned check|\bNSF\b|\bwas \$|\bformerly\b|\bnow \$|\breduced from\b|\bdown from\b|\bprice (?:drop|cut|reduction)\b|"
    r"\binstead of\b|\bnot \$|\bnot the \$|\bsuperseded\b|\bcorrection\b|\bvs\.?\b|\bcompared to\b|"
    r"\bincome\b|\bearn|\bsalary|\bcomps?\b|\bassessed\b|\bzestimate\b|\bappraise|\bsold for\b|\blast sold\b|\bper sq|/\s*sq|\bpsf\b|\bmortgage\b|\bdown payment\b|"
    r"\btogether\b|\bin total\b|\bpre-?approv|\bbuyer.{0,30}budget|\bor (?:street|a street)\b", re.I)


_SEASON = re.compile(r"\b(?:summer|winter|spring|fall|autumn|peak|off-?season|cooling season|heating season)\b", re.I)


def _after_address(before: str) -> bool:
    """True when the words in front of a figure end with a street address and a comma or dash ("Studio 5 Elm Ave," / "12 Oak St -")."""
    m = re.search(r"[ \t]*[,\-:|][ \t]*$|[ \t]+$", before)
    head = before[:m.start()] if m else before
    if not m or not head.strip():
        return False
    pm = _P()._ADDRESS.search(head)
    return bool(pm and pm.end() >= len(head.rstrip()) - 0 and head[pm.end():].strip(" ,") == "")


def is_non_cost(text: str, start: int, end: int, amount: float) -> bool:
    """True when the figure at text[start:end] is one the cost never counts: a late fee or other penalty, the old price in a price drop, a
    figure the listing replaces ("not $1,380"), an option named in a parking note, a buyer figure the listing compares, or the lower of a
    seasonal pair ("$140 in winter, $80 summer": the peak is counted, the low is not a second cost)."""
    item, line = _item(text, start, end, back=False)
    ls = text.rfind("\n", 0, start) + 1
    near = line[max(0, start - 60 - ls):end + 60 - ls]
    if _NON_COST.search(item) or _NON_COST.search(near):
        return True
    if amount >= 500 and _after_address(line[:start - ls]):
        return True  # cycle 24: "Studio 5 Elm Ave, $1,500": the price a headline gives right after the address is the rent of that place, not a cost left out
    figures = list(_P()._NET_DOLLARS.finditer(line))
    ls = text.rfind("\n", 0, start) + 1

    def season_of(i: int) -> bool:
        lo = figures[i - 1].end() if i > 0 else 0
        hi = figures[i + 1].start() if i + 1 < len(figures) else len(line)
        window = line[max(lo, figures[i].start() - 18):min(hi, figures[i].end() + 30)]
        return bool(_SEASON.search(window))

    mine = next((i for i, f in enumerate(figures) if f.start() == start - ls), None)
    if mine is not None and season_of(mine):
        for i, f in enumerate(figures):
            if i != mine and season_of(i) and any(v > amount for v in _P()._dollar_values(f.group(0))):
                return True
    return False


def _P():
    from . import parsers
    return parsers


_PLAN_WORDS = re.compile(r"\bstudio\b|\b\d(?:\.\d)?[ \t]*(?:br|bd|bed(?:room)?s?|ba|bath)\b|\b(?:one|two|three|four)[- ]bed|\bsf\b|sq\.?[ \t]?ft|square f|floor[- ]?plans?|\bplan[ \t]+[A-Z]?\d|\bunit type", re.I)
_START_AT = re.compile(r"\b(?:starting|starts|begins?|beginning|as low as|from|priced from|rents? from)[ \t]*(?:at|from)?[ \t:]*[\"']?[ \t]*$", re.I)
_CORRECTION_CUE = re.compile(r"\bcorrection\b|\bcorrected\b|\bignore (?:the |my )?(?:earlier|old|previous|first|above|original|prior) (?:price|rent|figure|number)|\b(?:rent|price) is now\b|\bupdated (?:price|rent)\b|\bnew (?:rent|price) is\b", re.I)
_COST_ITEM = re.compile(r"deposit|\bfees?\b|dues|\btax|insurance|\bhoa\b|parking|garage|utilit|electric|water|trash|pet|cleaning|application|admin", re.I)

NOT_A_COST_MARK = "not a cost on top of the rent"
_NOT_COST_SENTENCES = {
    "plan": f"It looks like the price of another floor plan or a starting price, {NOT_A_COST_MARK}. Ask which plan the rent is for.",
    "old_price": f"It looks like an older price that the listing replaces, {NOT_A_COST_MARK}. Ask if the rent saved is the right one.",
    "deposit_alternative": f"It looks like an alternative to the deposit, {NOT_A_COST_MARK}. Ask which one you would pick and what it costs.",
    "lease_option": f"It looks like the rent for another lease length, {NOT_A_COST_MARK}. Ask which lease length you want.",
}


def not_cost_kind(text: str, start: int, end: int, amount: float, price: Any = None) -> str:
    """Cycle 24: the figure is one the listing explains as not a cost on top of the rent: the price of another floor plan or a "starting at" price
    ("plan"), a rent the listing takes back ("old_price"), a surety bond offered instead of a deposit ("deposit_alternative"), or the rent for another
    lease length ("lease_option"). "" when it is none of these. The note keeps the figure; the missing list does not name it."""
    item, line = _item(text, start, end, back=False)
    ls = text.rfind("\n", 0, start) + 1
    before = line[max(0, start - ls - 60):start - ls]
    after = line[end - ls:end - ls + 50]
    rent = float(price) if isinstance(price, (int, float)) and not isinstance(price, bool) and price else None
    if amount >= 500 and rent and abs(amount - rent) >= 1 and (re.search(r"\b\d{1,2}[- ]?(?:months?|mo)\b[^$\n;.]{0,12}$", before, re.I)
                                                              or re.match(r"\s*(?:/\s*mo\w*\s*)?(?:for|on|with)\s+(?:a\s+)?\d{1,2}[- ]?(?:months?|mo)\b", after, re.I)) \
            and not _COST_ITEM.search(item):
        return "lease_option"
    if re.search(r"\bor\b[^$\n;.]{0,60}\b(?:surety|bond|waiver|guarantor|alternative)\b[^$\n;.]{0,12}$", before, re.I) and re.search(r"deposit", line, re.I):
        return "deposit_alternative"
    if amount >= 500 and rent and abs(amount - rent) >= 1 and not _COST_ITEM.search(item) and (_START_AT.search(before) or _PLAN_WORDS.search(item)):
        return "plan"
    if amount >= 500 and rent and abs(amount - rent) >= 1 and 0.5 * rent <= amount <= 2 * rent and not _COST_ITEM.search(item) and not re.search(r"concession|credit|free|\boff\b|discount|bonus|rebate", item, re.I) and (cue := _CORRECTION_CUE.search(text)) and start < cue.start():
        return "old_price"  # only a figure written before the correction: the new rent after it is never called old
    return ""


def not_cost_sentence(kind: str) -> str:
    return _NOT_COST_SENTENCES.get(kind, "")




_ITEM_SEP = re.compile(r"(?:(?<!\d),|,(?!\d{3}(?!\d)))|[;|\n]|[ \t]\+[ \t]|[ \t]~[ \t]|\.(?=\s|$)|\bplus\b|\band\b|[ \t][-\u2013\u2014][ \t]|[ \t]\*[ \t]|[✔✓✅☑]️?|\([^)]*\)")
_SUMMED = ("other_monthly_fees", "move_in_fees")
_CATS = (
    ("app", re.compile(r"application|\bapp\.? fee|applicants?\b|screening|credit check|background", re.I), ("application_fee",)),
    ("pet", re.compile(r"\bpets?\b|\bcats?\b|\bdogs?\b|\bpet\b", re.I), ("pet_rent", "pet_fee", "pet_deposit")),
    ("deposit", re.compile(r"deposit|\bsec\.?\s*dep\b|\bsecurity\b(?!\s+(?:cameras?|system|guard|gate|patrol|alarm|door|doors|entry|cams?|lights?|lighting|monitoring|service|staff|features?))", re.I), ("deposit",)),
    ("hoa", re.compile(r"\bhoa\b|dues|association|condo fee", re.I), ("hoa",)),
    ("insurance", re.compile(r"insurance|\bHO6\b", re.I), ("insurance",)),
    ("tax", re.compile(r"\btaxes\b|\btax\b", re.I), ("property_tax",)),
    ("parking", re.compile(r"parking|garage|carport|\bcar\b|\bspace\b|permit|valet|\bvehicle", re.I), ("parking_cost", "other_monthly_fees")),
    ("util", re.compile(r"electric|pg&e|\bpge\b|sdg&e|con ?ed\b|comed\b|duke energy|xcel|ameren|\bnicor\b|eversource|national grid|\bgas\b|water|sewer|trash|garbage|\bheat|internet|wi-?fi|cable|utilit", re.I), ("utilities_estimate", "other_monthly_fees")),
    ("fee", re.compile(r"\bfees?\b|admin|move-?in|lease|cleaning|processing|amenity|package|pest|locker|storage", re.I), ("move_in_fees", "other_monthly_fees", "application_fee", "deposit")),
)


def _item(text: str, start: int, end: int, back: bool = False) -> tuple[str, str]:
    """The item holding the figure and its line. With ``back`` an item that names no kind of cost is joined with the item in front of it
    ("2 assigned parking spaces, $35/mo each")."""
    ls = text.rfind("\n", 0, start) + 1
    le = text.find("\n", end)
    line = text[ls:(le if le >= 0 else len(text))]
    s0, e0 = start - ls, end - ls
    seps = [m for m in _ITEM_SEP.finditer(line)]
    lo = max([0] + [m.end() for m in seps if m.end() <= s0])
    hi = min([len(line)] + [m.start() for m in seps if m.start() >= e0])
    inside = next((m for m in seps if m.group(0).startswith("(") and m.start() <= s0 and m.end() >= e0), None)
    if inside is not None:  # cycle 23: a figure in its own brackets ("Heated garage ✔ ($135/mo)") belongs to the words in front of the bracket, not to the items after it
        before = [m for m in seps if m.end() <= inside.start()]
        lo = 0
        for m in reversed(before):
            if re.search(r"[A-Za-z]", line[m.end():inside.start()]):
                lo = m.end()
                break
        item_text = line[lo:inside.start()] + " " + line[inside.start():inside.end()]
        return (item_text if re.search(r"[A-Za-z]", line[lo:inside.start()]) else line[inside.start():inside.end()]), line
    item = line[lo:hi]
    if back and not any(c[1].search(item) for c in _CATS):
        prev = [m for m in seps if m.end() <= lo]
        for _ in range(2):
            plo = max([0] + [m.end() for m in prev if m.end() <= lo - 1])
            prev_item = line[plo:lo]
            lo = plo
            item = prev_item + " " + item
            if any(c[1].search(prev_item) for c in _CATS):
                break
            prev = [m for m in seps if m.end() <= lo]
            if lo == 0:
                break
    return item, line


def _matches(amount: float, v: float, item: str = "") -> bool:
    """The amount is the field's value, or the field's value over the period the item names (yearly, quarterly) or per space or pet."""
    mult = {1.0}
    low = item.lower()
    if re.search(r"year|annual|/\s*yr|\byr\b", low):
        mult |= {12.0}
    if re.search(r"quarter|qtr", low):
        mult |= {3.0}
    if re.search(r"semi|half|6 months|six months", low):
        mult |= {6.0}
    if re.search(r"\beach\b|\bper\b|/\s*(?:space|pet|car)", low):
        mult |= {0.5, 1 / 3, 0.25}
    # cycle 24: a figure written with cents is placed only by a field that holds those cents ("Trash $8.50" is not placed by an $8); the loose
    # half-dollar is only for a share worked out over a period (a yearly figure over 12 is rounded)
    return any(abs(amount - v * k) < (0.011 if k == 1.0 else 0.51) for k in mult)


_STOP = frozenset("the and for per mo month monthly each about approx avg roughly all fee fees extra paid pay pays tenant only one two".split())


def _quoted_clean(amount: float, notes: str, line: str, pos: int) -> bool:
    """A note quotes this very figure (the one at offset ``pos`` of its line) in words taken from the listing: a quote cut down to the figure and
    the clean words beside it. Another figure with the same amount elsewhere on the line is not covered by it."""
    for q in re.findall(r'"([^"]{2,200})"', notes):
        for part in (x.strip() for x in q.split("...") if x.strip()):
            if amount not in _P()._dollar_values(part):
                continue
            pat = r"\s+".join(re.escape(w) for w in part.split())
            if any(m.start() <= pos < m.end() for m in re.finditer(pat, line, re.I)):
                return True
    return False


def _noted(amount: float, item: str, notes: str) -> bool:
    """A note explains the figure when it holds the same amount and shares a word with the item the figure sits in."""
    words = {w for w in re.findall(r"[a-z0-9]{3,}", re.sub(r"\$\s?[\d,.]+", " ", item.lower())) if w not in _STOP}
    mine = next((c[0] for c in _CATS if c[1].search(item)), None)
    for unit in notes.split("\n"):
        if amount in _P()._dollar_values(unit) and "was corrected to" in unit and "saved on this place" in unit:
            return True  # cycle 31: the saved-versus-corrected note names the listing's new figure, so it is explained
        if amount in _P()._dollar_values(unit) and (not words or any(w in unit.lower() for w in words) or (mine and next((c[0] for c in _CATS if c[1].search(unit)), None) == mine)):
            return True
    return False


def _util_placed(text: str, est: float | None, loose: bool = False) -> set[float]:
    """Utility figures (of the listing's utility items) that some reading of them adds up to the saved estimate."""
    if est is None:
        return set()
    amts: list[tuple[float, tuple[float, ...]]] = []
    util_starts: set[int] = set()
    total_figs: set[float] = set()
    for m in _P()._NET_DOLLARS.finditer(text):
        item, line = _item(text, m.start(), m.end(), back=True)
        first = next((c for c in _CATS if c[1].search(item)), None)
        if (first is not None and first[0] == "util") or (first is None and _CATS[7][1].search(line) and re.search(r"pays?|tenant|resident|utilit|responsible", line, re.I)) \
                or (first is None and re.search(r"\b(?:typical|average|avg\.?|usual(?:ly)?)\b[^$]{0,30}\bbills?\b", item, re.I)):  # cycle 32: "Typical bills for the unit about $140" on a line of its own
            low = item.lower()
            divs = [1.0]
            if re.search(r"bi-?monthly|two months|2 months|every other month", low):
                divs += [2.0]
            if re.search(r"quarter|qtr|3 months", low):
                divs += [3.0]
            if re.search(r"year|annual|/\s*yr", low):
                divs += [12.0]
            amts.extend((a, tuple(divs)) for a in _P()._dollar_values(m.group(0)))
            util_starts.add(m.start())
            if re.search(r"\b(?:typical|average|avg\.?|usual(?:ly)?)\b[^$]{0,30}\b(?:bills?|total|utilit\w*)\b|\btotal\b|\bfor[ \t]+the[ \t]+unit\b|\ball[ \t]+(?:the[ \t]+)?utilit", line, re.I):
                total_figs.update(_P()._dollar_values(m.group(0)))  # cycle 32: a figure the listing calls the whole bill
    try:
        for b in _P()._internet_bills(_P()._tidy(text)):  # cycle 24: "Internet: Comcast, you set up (about $55)": the figure is the internet's bill, a part of the estimate, whatever the item cut says
            if not any(abs(b["amount_at"][0] - st) <= 2 for st in util_starts):
                amts.append((float(b["amount"]), (1.0,)))
    except Exception:
        pass
    amts = sorted(amts)[:8]
    opts = [[a / d for d in ds] for a, ds in amts]
    amts = [a for a, _d in amts]
    ok: set[float] = set()
    def rec(i: int, total: float, chosen: list[int]) -> None:
        if abs(total - est) < 0.7 and chosen:
            ok.update(amts[j] for j in chosen)
        if i >= len(amts) or total > est + 0.7:
            return
        rec(i + 1, total, chosen)
        for o in opts[i]:
            rec(i + 1, total + o, chosen + [i])
    rec(0, 0.0, [])
    # cycle 32: "tenant pays electric ($65); typical bills for the unit about $140": the saved $140 is the whole bill, so the $65 is a part of it
    for i, a in enumerate(amts):
        if loose and abs(a - est) < 0.01 and a in total_figs:
            parts = [b for j, b in enumerate(amts) if j != i and b < est]
            if parts and sum(parts) <= est + 0.7:
                ok.update(parts)
    return ok



def clause_placed(text: str, r: dict[str, Any], start: int, end: int, amount: float) -> bool:
    """Cycle 22: decided from the FINAL field values. The figure is placed when, taken with the other figures of the clause it sits in, a saved
    field holds it, holds its monthly share, or holds a sum it is a part of ("PG&E avg $140, water/sewer/trash flat $75 and internet ~$65" is the
    $280 estimate; "Background check $25 each applicant. Security $1,480" is the per-adult application fee and the deposit)."""
    P = _P()
    phrase = P._net_clause(text, start, end)
    if not phrase:
        return False
    vals = P._dollar_values(phrase)
    if amount not in vals:
        return False
    used = P._net_used_numbers(r, [], text)
    return amount in P.placed_amounts(vals, used, P._field_sums(r), phrase, r)


def sum_members(text: str, value: float, price: float | None = None) -> set[int] | None:
    """Cycle 22: where the figures behind a summed field are. The listing's dollar figures (not the rent-sized or sale-sized ones) are tried in
    every combination of up to six, each over the period its item names; the figures of every combination that adds up to ``value`` are the
    field's parts ({start offsets}). None when no combination does (the field was worked out some other way: it is not checked)."""
    P = _P()
    cands: list[tuple[int, tuple[float, ...]]] = []
    raw_by_start: dict[int, float] = {}
    for m in P._NET_DOLLARS.finditer(text):
        raw = m.group(1) if m.group(1) is not None else m.group(4)
        try:
            amount = float(raw.replace(",", "") + (m.group(2) or "" if m.group(1) is not None else "")) * (1000 if m.group(3) else 1)
        except ValueError:
            continue
        if amount <= 0:
            continue
        item, _line = _item(text, m.start(), m.end(), back=False)
        if _NON_COST.search(item):
            continue
        low = item.lower()
        opts = {round(amount, 2)}
        if re.search(r"year|annual|/\s*yr|\byr\b", low):
            opts.add(round(amount / 12, 2))
        if re.search(r"quarter|qtr", low):
            opts.add(round(amount / 3, 2))
        if re.search(r"semi|half|6 months|six months", low):
            opts.add(round(amount / 6, 2))
        if re.search(r"bi-?monthly|every other month|two months|2 months", low):
            opts.add(round(amount / 2, 2))
        if re.search(r"\beach\b|\bper\b|/\s*(?:space|pet|car|adult|person|applicant)", low):
            opts |= {round(amount * 2, 2), round(amount * 3, 2)}
        if min(opts) > value + 0.51:
            continue
        cands.append((m.start(), tuple(sorted(opts))))
        raw_by_start[m.start()] = round(amount, 2)
    if price:  # fees worked out from the rent: "landlord fee half a month", "broker fee 8% of annual rent"
        derived = {price * k for k in (0.5, 1, 1.5, 2)}
        for pm in _PCT.finditer(text):
            derived |= {price * float(pm.group(1)) / 100, price * 12 * float(pm.group(1)) / 100}
        cands += [(-1 - i, (round(d, 2),)) for i, d in enumerate(sorted(derived)) if d < value * 1.01 + 0.51]
    cands = cands[:22]
    amounts_raw = {j: raw_by_start.get(c[0], -1.0) for j, c in enumerate(cands)}  # a figure worked out from the rent (negative start) may be rounded
    found: set[int] = set()
    hit = False

    def close(total: float, chosen: tuple[tuple[int, float], ...]) -> bool:
        # cycle 24: figures added as written must add up to the cents; a share worked out over a period (a yearly figure over 12) may be a rounded half-dollar off
        exact = all(abs(o - round(amounts_raw.get(j, o), 2)) < 0.005 for j, o in chosen)
        return abs(total - value) < (0.011 if exact else 0.51)

    def rec(i: int, total: float, chosen: tuple[tuple[int, float], ...]) -> None:
        nonlocal hit
        if chosen and close(total, chosen):
            hit = True
            found.update(cands[j][0] for j, _o in chosen)
        if i >= len(cands) or len(chosen) >= 6 or total > value + 0.51:
            return
        rec(i + 1, total, chosen)
        for o in cands[i][1]:
            rec(i + 1, total + o, (*chosen, (i, o)))
    rec(0, 0.0, ())
    return found if hit else None


def _num_or_none(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v else None


def overcounted(text: str, r: dict[str, Any]) -> list[str]:
    """Cycle 22: a summed field (move-in fees, other monthly fees) whose value no combination of the listing's figures adds up to: a figure
    was read twice (or invented). One line per field: "move_in_fees 150: no combination of the listing's figures adds up to it"."""
    text = _P().normalize_money(text)
    out = []
    for k in _SUMMED:
        v = r.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v and sum_members(text, float(v), _num_or_none(r.get("price"))) is None:
            out.append(f"{k} {float(v):g}: no combination of the listing's figures adds up to it")
    return out


_CONCESSION_ITEM = re.compile(r"\bconcessions?\b|\b(?:months?|weeks?) free\b|\bfree (?:rent|month)|\bmove-?in special", re.I)
_CONCESSION_NOTE = re.compile(r"\b(?:rent )?concession\b|\bfree[- ]rent\b|\bmonths? free\b|\bone-time deal\b", re.I)
_MONTHS_AFTER = re.compile(r"[ \t]*(?:months?|mos?\b|month's)", re.I)


def _months_count_explained(text: str, end: int, amount: float, r: dict[str, Any]) -> bool:
    """Cycle 25: a small figure written with a dollar sign but followed by "months" ("$1.5 months rent") is a number of months of rent, not dollars. It is
    explained when a saved field holds that many months of the saved rent (a deposit of 1.5 x the rent)."""
    if amount >= 12 or not _MONTHS_AFTER.match(text, end):
        return False
    price = r.get("price")
    if not isinstance(price, (int, float)) or isinstance(price, bool) or not price:
        return False
    want = float(price) * amount
    return any(isinstance(v, (int, float)) and not isinstance(v, bool) and abs(float(v) - want) < 1.0
               for k, v in r.items() if k in ("deposit", "move_in_fees", "pet_deposit", "broker_fee", "application_fee"))


_STALE_UTIL_ESTIMATE = re.compile(r"\b(?:est(?:imate[ds]?|\.)?|about|approx\w*|roughly|typical)\b[^$]{0,12}\$[ \t]?[\d,.]+[ \t]+(?:for[ \t]+)?(?:all[ \t]+of[ \t]+(?:it|them)|everything|in[ \t]+total|total|combined|together|all[ \t]+(?:the[ \t]+)?utilities)\b", re.I)


def find_unplaced(text: str, r: dict[str, Any], notes: str) -> list[dict[str, Any]]:
    """Every dollar figure of a rental listing that no field holds and no note explains: [{"amount", "start", "end", "item", "kind"}]."""
    text = _P().normalize_money(text)
    price = r.get("price")
    est = r.get("utilities_estimate")
    util_ok = _util_placed(text, float(est) if isinstance(est, (int, float)) and not isinstance(est, bool) else None, loose=True)
    bad: list[dict[str, Any]] = []
    seen: set[tuple[float, str]] = set()
    members = {k: sum_members(text, float(r[k]), _num_or_none(r.get("price"))) for k in _SUMMED if isinstance(r.get(k), (int, float)) and not isinstance(r.get(k), bool) and r.get(k)}
    for m in _P()._NET_DOLLARS.finditer(text):
        raw = m.group(1) if m.group(1) is not None else m.group(4)
        try:
            amount = float(raw.replace(",", "") + (m.group(2) or "" if m.group(1) is not None else "")) * (1000 if m.group(3) else 1)
        except ValueError:
            continue
        if amount <= 0:
            continue
        if _months_count_explained(text, m.end(), amount, r):
            continue  # cycle 25: "$1.5 months rent deposit hold": a count of months with a stray dollar sign; the deposit field holds that many months of rent
        item, line = _item(text, m.start(), m.end(), back=True)
        ls = text.rfind("\n", 0, m.start()) + 1
        near = line[max(0, m.start() - 60 - ls):m.end() + 60 - ls]
        if (amount, item.strip()) in seen:
            continue
        seen.add((amount, item.strip()))
        if _noted(amount, item, notes) or _quoted_clean(amount, notes, line, m.start() - (text.rfind(chr(10), 0, m.start()) + 1)) or (isinstance(price, (int, float)) and amount == price):
            continue
        if is_non_cost(text, m.start(), m.end(), amount):
            continue
        if _P()._total_of_counted(text, m.start(), m.end(), amount, r):
            continue  # cycle 33: "= total $4,800" is the sum of the rent, deposit and fees that are counted, not an amount left out
        if _STALE_UTIL_ESTIMATE.search(item) and "corrects the utilities" in notes and isinstance(est, (int, float)) and not isinstance(est, bool) and abs(amount - float(est)) >= 0.5:
            continue  # cycle 29: "Estimate $100 for all of it" next to a correction that says the tenant now pays all utilities (est. $130): the old estimate is not used and is no missing amount
        if _CONCESSION_ITEM.search(item) and any(_CONCESSION_NOTE.search(u) for u in notes.split("\n")):
            continue  # cycle 25: "$6,000 in concessions, 1 month free on 13-month lease": the concession note already says it is a one-time deal that is not counted
        own = next((c for c in _CATS if c[1].search(item)), None)
        if (own is None or own[0] in ("app", "deposit")) and clause_placed(text, r, m.start(), m.end(), amount):
            continue  # only the clause of an application fee or deposit item: a utility is placed by the estimate (util_ok), a fee by the sums of its field; a bare $25 beside a $25 fee is a coincidence
        rng = re.match(r"[ \t]*(?:-|\u2013|\u2014|to)[ \t]*\$?[ \t]?(\d[\d,]*(?:\.\d\d)?)", text[m.end():m.end() + 16])
        if rng:  # cycle 31: "water ($70-$90/mo)": the low end of a range whose high end is placed is the range the reader counted at its higher figure
            try:
                hi = float(rng.group(1).replace(",", ""))
            except ValueError:
                hi = 0.0
            if hi > amount and (hi in util_ok or hi == (float(est) if isinstance(est, (int, float)) and not isinstance(est, bool) else None)
                                or any(isinstance(r.get(k), (int, float)) and not isinstance(r.get(k), bool) and abs(float(r[k]) - hi) < 0.5 for k in ("parking_cost", "pet_rent", "pet_fee", "other_monthly_fees", "hoa", "deposit", "pet_deposit", "move_in_fees", "application_fee"))):
                continue
        if amount >= 500 and re.search(r"\$\s?[\d,]+\s*(?:-|\u2013|to)\s*$|^\s*(?:-|\u2013|to)\s*\$", text[max(0, m.start() - 12):m.start()] + "|" + text[m.end():m.end() + 8]):
            continue  # a rent range
        if amount >= 1000 and "deposit" in item.lower() and re.search(rf"(?:rent|/\s*mo|per month|\bmonth)\W{{0,4}}[^.\n]{{0,25}}\${amount:,.0f}|\${amount:,.0f}\s*(?:/\s*mo|per month|a month|monthly)", text, re.I):
            continue  # one place of several: its deposit is the rent of the same place
        if amount >= 1000 and re.search(r"\brent\b|\b\d(?:\.\d)?\s*(?:br|bd|bed(?:room)?s?|ba)\b|\bper month\b|/\s*mo\b", item + " " + line[:60], re.I) and not re.search(r"deposit|fee|dues|tax|insurance", item, re.I):
            continue  # a rent (a paste of several places has several)
        cat = next((c for c in _CATS if c[1].search(item)), None) or next((c for c in _CATS if c[1].search(line)), None)
        if cat is None:
            if amount >= 20000 or isinstance(price, (int, float)) and amount > price * 0.7:
                continue  # a sale price, a comparison or a rent-sized figure
            bad.append({"amount": amount, "start": m.start(), "end": m.end(), "item": item.strip(), "kind": ""})
            continue
        if cat[0] == "util" and amount in util_ok:
            continue
        if cat[0] == "deposit" and re.search(r"\bpets?\b|\bcats?\b|\bdogs?\b", line, re.I):
            cat = ("pet", cat[1], ("pet_deposit", "pet_fee", "pet_rent", "deposit"))
        if re.search(r"\bpets?\b|\bcats?\b|\bdogs?\b", line, re.I) and any(isinstance(r.get(k), (int, float)) and not isinstance(r.get(k), bool) and abs(float(r[k]) - amount) < 0.5
                                                                                for k in ("pet_deposit", "pet_fee", "pet_rent")):
            continue  # cycle 21: "Pet policy: Cats only, $35 monthly rent, $200 fee": the pet fields hold both figures
        fieldkv = [(k, r.get(k)) for k in cat[2] if isinstance(r.get(k), (int, float)) and not isinstance(r.get(k), bool) and r.get(k) not in (0,)]
        if cat[0] != "util" and any(_matches(amount, float(v), item) or (k in _SUMMED and (m.start() in members[k] if members.get(k) is not None else amount <= float(v) + 0.011)) for k, v in fieldkv):
            continue
        if cat[0] == "util" and any(amount <= float(r[k]) + 0.011 for k in ("other_monthly_fees",) if isinstance(r.get(k), (int, float)) and r.get(k)):
            continue
        bad.append({"amount": amount, "start": m.start(), "end": m.end(), "item": item.strip(), "kind": cat[0]})
    return bad


_PCT = re.compile(r"(?<![\w.])(\d{1,3}(?:\.\d{1,2})?)[ \t]*(?:%|percent\b)")
_PCT_MONEY = re.compile(r"credit|concession|contribut|toward|towards|closing|commission|compensation|brokerage|broker|agent|finder|listing fee|\bfees?\b|\bpay(?:s|ing)?\b|\boffer", re.I)
_PCT_NOT = re.compile(r"\bdown\b|\bPMI\b|\binterest\b|\bAPR\b|\brate\b|\bltv\b|\bappreciat|\bincrease|\bescalat|\bof income|\boff\b|\bdiscount|\bdeposit\b|\boccupan|\bhumidity|\bcapacity|\bcomplete|\bsatisf|\bscore|\bmatch|\bwalk|\bgrowth|\bsunlight|\bcredit (?:score|check)|\bvacan", re.I)


def find_unplaced_percent(text: str, r: dict[str, Any], notes: str) -> list[dict[str, Any]]:
    """Cycle 22: a percent the listing gives for money (a seller credit "2% toward closing costs", a broker fee "5% of annual rent", an agent
    commission) that no field holds as dollars and no note quotes: [{"pct", "start", "end", "item"}]. A late fee, a down payment, a rate or an
    "x% off" deal is not one (the first is a penalty, the others have their own notes or are about the buyer's own loan)."""
    text = _P().normalize_money(text)
    price = r.get("price")
    bases = [float(price) * k for k in (1, 12) if isinstance(price, (int, float)) and not isinstance(price, bool) and price]
    held = [float(r[k]) for k in ("seller_credit", "closing_costs", "broker_fee", "move_in_fees", "other_monthly_fees", "hoa", "insurance") if isinstance(r.get(k), (int, float)) and not isinstance(r.get(k), bool) and r.get(k)]
    out: list[dict[str, Any]] = []
    for m in _PCT.finditer(text):
        pct = float(m.group(1))
        if pct <= 0 or pct > 100:
            continue
        item, line = _item(text, m.start(), m.end(), back=False)
        ls = text.rfind("\n", 0, m.start()) + 1
        item_all = line[max(0, m.start() - ls - 70):m.end() - ls + 60]
        if not _PCT_MONEY.search(item) and not _PCT_MONEY.search(item_all[40:]):
            continue
        if _PCT_NOT.search(item) or _NON_COST.search(item) or re.search(r"\blate\b", item_all, re.I) or re.search(r"[?]", text[m.end():m.end() + 25]):
            continue
        low = re.escape(f"{pct:g}") + r"\s*(?:%|percent)"
        if re.search(low, notes, re.I):
            continue
        if any(abs(v - pct / 100 * b) <= max(2.0, 0.004 * v) for v in held for b in bases):
            continue
        out.append({"pct": pct, "start": m.start(), "end": m.end(), "item": item.strip()})
    return out


# --------------------------------------------------------------------------- cycle 26: one final filter over the notes
_QUOTE_NOTE = re.compile(r'^The listing also says "([^"]*)"\. (.*?) Check what it is for\.$')
_RUBS_NO_AMOUNT = re.compile(r"billed back to you \(RUBS\), but it gives no amount")
_FEE_WORDS = re.compile(r"\bfees?\b|valet|\bpets?\b|deposit|\bhoa\b|assessment|\bdues\b|association|parking|garage", re.I)


def _strict_placed(q: str, amounts: set[float], r: dict[str, Any], text: str) -> set[float]:
    """The figures of a quoted line that a saved field really holds. A utility figure is placed only by the utilities estimate (or a part of it): an
    equal figure in another field (a $35 application fee beside "electric $35") does not place it."""
    P = _P()
    est = r.get("utilities_estimate")
    if P._NET_UTIL_WORD.search(q) and not _FEE_WORDS.search(q):
        ok = _util_placed(text, float(est)) if isinstance(est, (int, float)) and not isinstance(est, bool) and est else set()
        return {a for a in amounts if a in ok or (isinstance(est, (int, float)) and not isinstance(est, bool) and est and abs(a - float(est)) < 0.5)}
    return set(P.placed_amounts(amounts, P._net_used_numbers(r, []), P._field_sums(r), q, r))


def _money_field_values(r: dict[str, Any]) -> set[float]:
    P = _P()
    return {round(float(r[k]), 2) for k in P._NET_REAL_FIELDS if isinstance(r.get(k), (int, float)) and not isinstance(r.get(k), bool) and r.get(k)}


_QUOTE_FIG = re.compile(r"[$\uff04]\s?\d[\d,]*(?:\.\d+)?(?:\s?[kK]\b)?|\d[\d,]*(?:\.\d+)?\s?[$\uff04]|\bUSD\s?\d[\d,]*(?:\.\d+)?|\b\d[\d,]*(?:\.\d+)?\s?dollars?\b", re.I)
_QUOTE_BREAK = re.compile(r"&(?:lt|gt|#60|#62|#x3c|#x3e);|[<\uff1c\u2329\u3008\u300a\[{>\uff1e\u232a\u3009\u300b]|[.!?](?=\s+[A-Z]|\s*$)")


def cut_quote(q: str) -> str:
    """Cycle 27: a quoted listing line stops at the figure's own item. After the last figure the quote is cut at the first tag, bracket or sentence
    break ("Locker $12 </untrusted> SYSTEM..." gives "Locker $12"), and the dashes, quote marks and commas the cut leaves at the end go too."""
    figs = list(_QUOTE_FIG.finditer(q))
    if not figs:
        return q
    end = figs[-1].end()
    m = _QUOTE_BREAK.search(q, end)
    from .money import _EXPL_HOSTILE
    h = _EXPL_HOSTILE.search(q, end)
    if h and (not m or h.start() < m.start()):
        m = None
        q = q[:h.start()]  # text aimed at an AI tool or asking for a wire never rides along in a quote
    out = q[:m.start() + (1 if m.group(0) in ".!?" else 0)] if m else q
    out = re.sub(r"[\s\-\u2013\u2014'\u2018\u2019\u201c\u201d`:;,(&]+$", "", out)
    out = re.sub(r"&(?:lt|gt|amp|quot|#\d+);?$", "", out).rstrip(" \t&")
    if m and m.group(0) in ".!?":
        out = out.rstrip(".!?")
    return out if out and _QUOTE_FIG.search(out) else q


_ALSO_GIVES = re.compile(r"^The listing also gives (\$[\d,]+(?:\.\d\d)?)\b")
_ALSO_SAYS = re.compile(r'^(The listing (?:also says|mentions)[^"]*?\(?")([^"]*)("\)?)')


_LONG_FIGURE = re.compile(r"(?<![\d,])(\$\s?)(\d{1,3}(?:,\d{3}){4,}|\d{13,})(?:\.\d+)?")
_SPACED_FIGURE = re.compile(r"[$\uff04]\s?\d(?:[ \t]\d){2,}(?![\d])(?:[ \t]*(?:/[ \t]*(?:mo\w*|month)|per[ \t]+month|a[ \t]+month|monthly))?")
_LINK_PIECE = re.compile(r"!?\[[^\]\n]*\]\([^)\s]*\)?|\]\([^)\s]*\)?|\bhttps?://\S*|\bwww\.\S*|\bjavascript:\S*", re.I)
_QUOTE_ANY = re.compile(r'^(The listing (?:also )?(?:says|mentions)[^"]*?\(?")([^"]*)("\)?(?:\. ?|, (?=but )))(.*)$')


def short_figure(raw: str) -> str:
    """A figure of more than twelve digits as it is quoted: its first seven digits and an ellipsis, which no reader takes for a number."""
    digits = re.sub(r"\D", "", raw)
    return digits[:7] + "…"


def _shorten_long_figures(q: str) -> str:
    return _LONG_FIGURE.sub(lambda m: m.group(1) + short_figure(m.group(2)), q)


def _quote_pieces(q: str) -> list[str]:
    """The figures of one quoted line as plain words, one piece per figure that cannot share its words: a link or markdown image is cut out (a
    figure inside it is quoted alone), and two figures with no words between them ("$8 $99") are two pieces."""
    hidden = [m.group(0) for p in _LINK_PIECE.finditer(q) for m in _QUOTE_FIG.finditer(p.group(0))]
    plain = _LINK_PIECE.sub(" ", q)
    plain = re.sub(r"(?:\s*\.\.\.)+\s*$|^\s*(?:\.\.\.\s*)+", "", " ".join(plain.split())).strip(" ,;:-")
    parts = [x.strip(" ,;:-") for x in re.split(r"(?<=\d)[ \t]+(?=[$\uff04]\d)", plain)] if re.search(r"[$\uff04]\s?[\d,.]+[ \t]+[$\uff04]\s?\d", plain) else [plain]
    out = [x for x in parts if x and _QUOTE_FIG.search(x)]
    out += [h.strip() for h in hidden if not any(h in x for x in out)]
    if not out and _LINK_PIECE.search(q):
        bare = re.sub(r"[\s(\[{'\"=]+$", "", plain)  # cycle 31: a quote with a link and no figure keeps its words and never the link
        if len(bare) >= 3 and not _LINK_PIECE.search(bare):
            return [bare]
    return list(dict.fromkeys(out)) or [q]


def _title_line_figure(q: str, text: str) -> str:
    """A quote that is the whole first line of the listing (its title: "Trulia: 2 Bed Apartment at Brewery District Lofts - $1,490/mo ($1,525 now)") is
    cut down to the item that holds the figure ("$1,490/mo ($1,525 now)"): the title is the name of the place, never a note."""
    first = " ".join(text.split("\n", 1)[0].split()) if text else ""
    flat = " ".join(q.split())
    if len(flat) < 50 or not first or flat not in first or len(flat) < 0.8 * len(first):
        return q
    fig = _QUOTE_FIG.search(flat)
    if not fig:
        return q
    seps = [m.end() for m in re.finditer(r"\s[-|\u2013\u2014]\s|\s\|\s|:\s|,\s(?!\d{3}\b)", flat) if m.end() <= fig.start()]
    return flat[max(seps):] if seps else q


_STALE_QUOTE = re.compile(r'^The listing also says "([^"]*)"\. ')


def clean_quote_notes(r: dict[str, Any], facts: list[str], text: str = "") -> list[str]:
    """Cycle 29: the last look at every quoted line. (a) No link, markdown or URL is quoted and no figure shares a quote it does not belong to. (b) A
    figure written with spaces between its digits ("$2 9 5 0 / mo") is quoted as the whole run and no amount is read from it. (c) A figure of more
    than twelve digits is shortened. (d) A credit is never called a cost. (e) A stale utilities estimate that a "corrects the utilities" note replaced is
    not a note. (f) A note is said once."""
    out: list[str] = []
    est = r.get("utilities_estimate")
    corrected = any("corrects the utilities" in f for f in facts)
    for f in facts:
        m = _QUOTE_ANY.match(f)
        if not m:
            out.append(f)
            continue
        head, q, mid, said = m.group(1), m.group(2), m.group(3), m.group(4)
        if corrected and isinstance(est, (int, float)) and not isinstance(est, bool) and _STALE_UTIL_ESTIMATE.search(q) and all(abs(v - float(est)) >= 0.5 for v in _P()._dollar_values(q)):
            continue
        q = _title_line_figure(q, text)
        sp = _SPACED_FIGURE.search(q)
        if sp:
            out.append(f'{head}{q}{mid}The figure is written with spaces between its digits, so no amount is read from it. Ask what it is.')
            continue
        pieces = _quote_pieces(q) if (_LINK_PIECE.search(q) or re.search(r"[$\uff04]\s?[\d,.]+[ \t]+[$\uff04]\s?\d", q)) else [q]
        for piece in pieces:
            piece = _shorten_long_figures(piece)
            sentence = said
            if _P()._CREDIT_WORDS.search(_P()._CREDIT_NOT.sub(" ", piece)) and re.search(r"one-time cost", said) and not re.search(r"\bfees?\b|\bdeposit|\bcharge", piece, re.I):
                sentence = said.replace("It is a one-time cost, so it is not in the monthly cost.", _P().CREDIT_SENTENCE)
            out.append(f"{head}{piece}{mid}{sentence}")
    seen: set[str] = set()
    final: list[str] = []
    for f in out:
        key = " ".join(f.split()).lower()
        if key in seen:
            continue
        seen.add(key)
        final.append(f)
    return final


def finalize_notes(text: str, r: dict[str, Any], facts: list[str], buying: bool = False) -> list[str]:
    """Cycle 26: the last filter over the notes, decided from the FINAL saved fields.
    1. A "not counted" note for a quoted line says what is true: "the other amounts in that line are counted" only when every one of them is in a
       field (a utility figure only when the utilities estimate holds it), and a figure that another note already explains as optional is not
       named again.
    2. A "gives no amount" note about billed-back utilities goes when a field holds a figure for them.
    3. Two notes that quote the same figures for the same reason become one."""
    from . import money as M
    P = _P()
    facts = clean_quote_notes(r, facts, text)
    out: list[str] = []
    optional_cache: dict[int, set[float]] = {}
    for i, f in enumerate(facts):
        am = _ALSO_SAYS.match(f)
        if am:
            cut = cut_quote(am.group(2))
            if cut != am.group(2):
                f = am.group(1) + cut + f[am.start(3):]
                facts = [*facts[:i], f, *facts[i + 1:]]
        qm = _QUOTE_NOTE.match(f)
        if qm and re.search(r"not counted anywhere|not in the monthly cost", qm.group(2)):
            q, said = qm.group(1), qm.group(2)
            amounts = P._dollar_values(q)
            others = [g for j, g in enumerate(facts) if j != i]
            opt = M.optional_amounts(others)
            claim = "the other amounts in that line are counted" in said
            if claim:
                placed = _strict_placed(q, amounts, r, text)
                if amounts and amounts <= placed:
                    continue  # every figure of the line is in a field: the note only repeats what was counted
                left = amounts - placed
                named = P._dollar_values(said)
                if left == amounts:
                    f = f'The listing also says "{q}". {P._uncounted_kind_sentence(q)} Check what it is for.'  # nothing in the line is counted
                elif not (named and named <= left and (amounts - left) <= placed):
                    # the others are not all in fields: say only what is true about the figures that are left out
                    shown = [(f"${a:,.0f}" if float(a).is_integer() else f"${a:,.2f}") for a in sorted(left)]
                    names = shown[0] if len(shown) == 1 else ", ".join(shown[:-1]) + " and " + shown[-1]
                    kind = P._uncounted_kind_sentence(q)
                    sentence = P._only_sentence(names, kind, len(left) > 1)
                    f = f'The listing also says "{q}". {sentence} Check what it is for.'
        if _RUBS_NO_AMOUNT.search(f) and "doesn't say which utilities" in f:
            billed = any(re.search(r"billed back[^.]*\$[\d,.]+|(?:water|sewer|trash|utilit)[^.]*\$[\d,.]+[^.]*counted (?:once )?in other monthly fees", g, re.I) for g in facts if g is not f)
            est = r.get("utilities_estimate")
            if billed or (isinstance(est, (int, float)) and not isinstance(est, bool) and est and re.search(r"\bbilled[- ]back\b|\bRUBS\b|submeter", text, re.I) and re.search(r"billed[- ]back[^.\n]*\$\s?\d|\bRUBS\b[^.\n]*\$\s?\d", text, re.I)):
                continue  # a field now holds a figure for those items: "gives no amount" is no longer true
        out.append(f)
    # two notes that quote the same figures for the same reason are one note
    seen: list[tuple[frozenset[float], str, str]] = []
    final: list[str] = []
    for f in out:
        qm = _QUOTE_NOTE.match(f)
        if qm:
            words = re.sub(r"[^a-z0-9$.]+", " ", qm.group(1).lower()).strip()
            key = (frozenset(P._dollar_values(qm.group(1))), re.sub(r"\bOnly .{1,80} of that\b", "It", qm.group(2)), words)
            # the same figure for the same reason AND the same listing words (one quote contained in the other): "Pet rent $35" and "Applicants: $35" stay two notes
            if key[0] and any(k[0] == key[0] and k[1] == key[1] and (k[2] in words or words in k[2]) for k in seen):
                continue
            seen.append(key)
        final.append(f)
    # cycle 28: one figure, one note. A note whose quote and figures sit inside another note's quote ("Locker $9" beside "Locker $9 ... Gym $20") is that note again
    keys = []
    for f in final:
        qm = _QUOTE_NOTE.match(f)
        keys.append((frozenset(P._dollar_values(qm.group(1))), re.sub(r"\bOnly .{1,80} of that\b", "It", qm.group(2)), re.sub(r"[^a-z0-9$.]+", " ", qm.group(1).lower()).strip()) if qm else None)
    keep = []
    for i, f in enumerate(final):
        k = keys[i]
        if k and k[0] and any(o is not None and j != i and k[0] < o[0] and k[1] == o[1] and k[2] in o[2] for j, o in enumerate(keys)):
            continue
        keep.append(f)
    # cycle 28: two notes that both begin "The listing also gives $3,195 ..." are about one price: one note survives (the lease length reading, which names the months, beats the generic "depends on the condition")
    gives = {}
    for i, f in enumerate(keep):
        gm = _ALSO_GIVES.match(f)
        if gm:
            gives.setdefault(gm.group(1), []).append(i)
    drop: set[int] = set()
    for idxs in gives.values():
        if len(idxs) > 1:
            best = next((i for i in idxs if re.search(r"lease length", keep[i], re.I)), idxs[0])
            drop.update(i for i in idxs if i != best)
    return [f for i, f in enumerate(keep) if i not in drop]
