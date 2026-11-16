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


def is_non_cost(text: str, start: int, end: int, amount: float) -> bool:
    """True when the figure at text[start:end] is one the cost never counts: a late fee or other penalty, the old price in a price drop, a
    figure the listing replaces ("not $1,380"), an option named in a parking note, a buyer figure the listing compares, or the lower of a
    seasonal pair ("$140 in winter, $80 summer": the peak is counted, the low is not a second cost)."""
    item, line = _item(text, start, end, back=False)
    ls = text.rfind("\n", 0, start) + 1
    near = line[max(0, start - 60 - ls):end + 60 - ls]
    if _NON_COST.search(item) or _NON_COST.search(near):
        return True
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


_ITEM_SEP = re.compile(r"(?:(?<!\d),|,(?!\d{3}(?!\d)))|[;|\n]|[ \t]\+[ \t]|[ \t]~[ \t]|\.(?=\s|$)|\bplus\b|\band\b|[ \t][-\u2013\u2014][ \t]|[ \t]\*[ \t]|[✔✓✅☑]️?|\([^)]*\)")
_SUMMED = ("other_monthly_fees", "move_in_fees")
_CATS = (
    ("app", re.compile(r"application|\bapp\.? fee|applicants?\b|screening|credit check|background", re.I), ("application_fee",)),
    ("pet", re.compile(r"\bpets?\b|\bcats?\b|\bdogs?\b|\bpet\b", re.I), ("pet_rent", "pet_fee", "pet_deposit")),
    ("deposit", re.compile(r"deposit|\bsecurity\b(?!\s+(?:cameras?|system|guard|gate|patrol|alarm|door|doors|entry|cams?|lights?|lighting|monitoring|service|staff|features?))", re.I), ("deposit",)),
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
    return any(abs(amount - v * k) < 0.51 for k in mult)


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
        if amount in _P()._dollar_values(unit) and (not words or any(w in unit.lower() for w in words) or (mine and next((c[0] for c in _CATS if c[1].search(unit)), None) == mine)):
            return True
    return False


def _util_placed(text: str, est: float | None) -> set[float]:
    """Utility figures (of the listing's utility items) that some reading of them adds up to the saved estimate."""
    if est is None:
        return set()
    amts: list[tuple[float, tuple[float, ...]]] = []
    util_starts: set[int] = set()
    for m in _P()._NET_DOLLARS.finditer(text):
        item, line = _item(text, m.start(), m.end(), back=True)
        first = next((c for c in _CATS if c[1].search(item)), None)
        if (first is not None and first[0] == "util") or (first is None and _CATS[7][1].search(line) and re.search(r"pays?|tenant|resident|utilit|responsible", line, re.I)):
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
    if price:  # fees worked out from the rent: "landlord fee half a month", "broker fee 8% of annual rent"
        derived = {price * k for k in (0.5, 1, 1.5, 2)}
        for pm in _PCT.finditer(text):
            derived |= {price * float(pm.group(1)) / 100, price * 12 * float(pm.group(1)) / 100}
        cands += [(-1 - i, (round(d, 2),)) for i, d in enumerate(sorted(derived)) if d < value * 1.01 + 0.51]
    cands = cands[:22]
    found: set[int] = set()
    hit = False

    def rec(i: int, total: float, chosen: tuple[int, ...]) -> None:
        nonlocal hit
        if chosen and abs(total - value) < 0.51:
            hit = True
            found.update(cands[j][0] for j in chosen)
        if i >= len(cands) or len(chosen) >= 6 or total > value + 0.51:
            return
        rec(i + 1, total, chosen)
        for o in cands[i][1]:
            rec(i + 1, total + o, (*chosen, i))
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


def find_unplaced(text: str, r: dict[str, Any], notes: str) -> list[dict[str, Any]]:
    """Every dollar figure of a rental listing that no field holds and no note explains: [{"amount", "start", "end", "item", "kind"}]."""
    text = _P().normalize_money(text)
    price = r.get("price")
    est = r.get("utilities_estimate")
    util_ok = _util_placed(text, float(est) if isinstance(est, (int, float)) and not isinstance(est, bool) else None)
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
        own = next((c for c in _CATS if c[1].search(item)), None)
        if (own is None or own[0] in ("app", "deposit")) and clause_placed(text, r, m.start(), m.end(), amount):
            continue  # only the clause of an application fee or deposit item: a utility is placed by the estimate (util_ok), a fee by the sums of its field; a bare $25 beside a $25 fee is a coincidence
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
        if cat[0] != "util" and any(_matches(amount, float(v), item) or (k in _SUMMED and (m.start() in members[k] if members.get(k) is not None else amount <= float(v) + 0.5)) for k, v in fieldkv):
            continue
        if cat[0] == "util" and any(amount <= float(r[k]) + 0.5 for k in ("other_monthly_fees",) if isinstance(r.get(k), (int, float)) and r.get(k)):
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
