"""Read a pasted listing (and its link) into fields. Runs on this computer and never opens the link.

``parse_listing(text, url)`` returns a dict of field -> value for the fields it could find. Keys are the same as the
place fields (``price``, ``beds``, ``baths``, ``sqft``, ``address``, ``unit``, ``city``, ``state``, ``zip``, ``laundry``,
``dishwasher``, ``parking``, ``parking_cost``, ``pets``, ``pet_rent``, ``pet_fee``, ``pet_deposit`` (refundable), ``pet_weight_limit``, ``pet_count_limit``,
``pet_breed_note``, ``fenced_yard``, ``utilities_included``,
``available_from``, ``lease_months``, ``deposit``, ``application_fee``, ``move_in_fees``, ``other_monthly_fees``,
``year_built``, ``hoa``, ``property_tax``, ``insurance``, ``source``, ``title``), plus ``found_in_listing``: a short plain
summary of facts with no field of their own (pet weight limits, a special assessment, per-adult fees). A missing key means "not found", never a guess.

It is made for text copied from Zillow, Apartments.com, Craigslist, Facebook Marketplace, Realtor.com, Redfin and
property-manager sites, which all word things differently. ``price`` is the monthly rent when the text gives one
("$1,495/mo", "Rent: $1,495", "$1500 / 1br"), else the asking price of a home for sale. Fees, deposits, HOA and
payment estimates are never mistaken for the rent. The function never raises: a field it can't read is left out.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Callable
from urllib.parse import urlsplit

MAX_CHARS = 60_000  # a listing is short; this keeps a huge paste fast

KNOWN_SITES = {
    "zillow.com": "Zillow", "apartments.com": "Apartments.com", "craigslist.org": "Craigslist", "facebook.com": "Facebook",
    "trulia.com": "Trulia", "redfin.com": "Redfin", "realtor.com": "Realtor.com", "rent.com": "Rent.com",
    "hotpads.com": "HotPads", "zumper.com": "Zumper", "apartmentlist.com": "Apartment List", "padmapper.com": "PadMapper",
    "streeteasy.com": "StreetEasy", "loopnet.com": "LoopNet", "homes.com": "Homes.com", "cozy.co": "Cozy",
    "fb.com": "Facebook", "m.facebook.com": "Facebook", "forrent.com": "ForRent.com", "apartmentguide.com": "ApartmentGuide",
}
# Site names that may appear in the pasted text itself (used only when there is no link to read the site from).
_TEXT_SITES = (
    (r"\bcraigslist\b", "Craigslist"), (r"\bfacebook marketplace\b|\bmarketplace\b.{0,40}\bfacebook\b", "Facebook"),
    (r"\bapartments\.com\b", "Apartments.com"), (r"\bzillow\b", "Zillow"), (r"\bredfin\b", "Redfin"),
    (r"\brealtor\.com\b", "Realtor.com"), (r"\btrulia\b", "Trulia"), (r"\bhotpads\b", "HotPads"), (r"\bzumper\b", "Zumper"),
)
_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_STATES = frozenset("AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK "
                    "OR PA RI SC SD TN TX UT VT VA WA WV WI WY PR".split())
_STREET = (r"(?:st|street|ave|avenue|rd|road|dr|drive|blvd|boulevard|ln|lane|ct|court|pl|place|way|cir|circle|pkwy|parkway|"
           r"ter|terrace|trl|trail|hwy|highway|loop|plaza|pike|(?:row|walk|alley|path|mews)(?![ \t]+(?:ln|lane|st|street|ave|avenue|rd|road|dr|drive|blvd|boulevard|ct|court|pl|place|way|cir|circle|ter|terrace|trl|trail|pkwy|parkway)\b)|sq(?=\b\.?,)|square(?=\b,))")
_NOT_STREET_WORDS = {"bed", "beds", "bedroom", "bedrooms", "bath", "baths", "bathroom", "bathrooms", "br", "ba", "bd", "bds", "sq",
                     "ft", "sqft", "month", "mo", "year", "years", "min", "minute", "minutes", "mile", "miles", "unit", "units",
                     "floor", "floors", "car", "cars", "pet", "pets", "story", "stories", "block", "blocks", "min."}
_UNIT = r"(?:#|apt\.?|apartment|unit|suite|ste\.?)\s*#?\s*([A-Za-z]?\d{1,5}[A-Za-z]?(?:-\d{1,3})?|[A-Z])\b"
_ADDRESS = re.compile(
    r"(?<![\w$.,/-])(\d{1,6}(?:-\d{1,6})?\s+(?:[NSEW]\.?\s+|(?:North|South|East|West)\s+)?"
    r"(?:(?:\d{1,3}(?:st|nd|rd|th)|[A-Za-z][A-Za-z.'-]*)\s+){0,4}?" + _STREET + r"\b\.?)"
    r"(?:,?\s+" + _UNIT + r")?", re.I)
_CITY_LINE = re.compile(r"([A-Z][A-Za-z.'-]+(?: [A-Z][A-Za-z.'-]+){0,3}),?\s+([A-Z]{2})\s+(\d{5})(?:-\d{4})?\b")
_CITY_STATE = re.compile(r"([A-Z][A-Za-z.'-]+(?: [A-Z][A-Za-z.'-]+){0,3}),\s+([A-Z]{2})\b(?!\w)")

_AMOUNT = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(\.\d{1,2})?(\s?[kK]\b)?")
# a $ amount that is not the rent: the words around it say what it is
_FEE = (r"deposits?|fees?|pet|pets|parking|garage|carport|admin(?:istrative|istration)?|application|app\b|utilit\w*|hoa|"
        r"assoc\w*|dues|tax(?:es)?|insurance|mortgage|down payment|closing|cleaning|storage|late|move[- ]?in|amenity|trash|"
        r"water|sewer|internet|cable|reservation|holding|bike|laundry|washer|dryer|estimated?|est\.?|payment|per pet|"
        r"charge|waiver|concession|savings?|credit|income|salary|earn|reward|bonus|gift|off\b|rebate|special|"
        r"referral|broker|finder|lock|key|pest|package|valet|technology|renters?|guarantor|cosigner|prorat\w*|"
        r"lawn|snow|per bed|/bed|reduc\w*|price (?:cut|drop|change)\w*|cuts?\b|dropped|lowered|markdown|decreas\w*|"
        r"assessment\w*")
_FEE_BEFORE = re.compile(r"\b(?:" + _FEE + r")", re.I)
_MONTHLY = r"(?:/\s*|per\s+|a\s+|each\s+|every\s+)?(?:mo\b|mos\b|month\b|months\b|monthly\b|mth\b)"
_RENT_MARK = re.compile(r"^\s*\+?\s*(?:" + _MONTHLY + r"|/\s*(?:unit|apt)\b)", re.I)
_BR_MARK = re.compile(r"^\s*/\s*(?:\d\s*(?:br|bd|bed)|studio)", re.I)  # Craigslist: "$1100 / 1br - 700ft2"
_PER_BED = re.compile(r"^\s*\+?\s*(?:/|per)\s*(?:bed|bedroom|person|resident|tenant|student)", re.I)
_FEE_AFTER_STRICT = re.compile(r"^\s*\+?\s*(?:one[- ]time\s+|non[- ]refundable\s+|refundable\s+|monthly\s+|price\s+)?(?:" + _FEE + r")", re.I)
_FEE_AFTER_MONTHLY = re.compile(r"^\s*\+?\s*(?:" + _MONTHLY + r")?\s*(?:for\s+|per\s+|-\s*)?(?:pet|parking|garage|storage|utilit|hoa|trash|"
                                r"internet|cable|amenity|water|insurance|lawn|cleaning|reserved|covered)", re.I)
_RENT_LABEL = re.compile(r"\b(?:rent|monthly|price|asking|lease|per month|list(?:ed|ing)?(?: price)?|offered|cost)\b", re.I)
_SALE_WORDS = re.compile(r"\b(?:for sale|list price|listed (?:at|for)|asking price|offered at|mls|sold|est\.? ?payment|"
                         r"mortgage|down payment|home value|zestimate|redfin estimate|price cut|days on (?:zillow|market|redfin)|"
                         r"open house|new construction|sale price|purchase price|buy)\b", re.I)
_RENT_WORDS = re.compile(r"\b(?:rent|rental|lease|apartment|apt|month|monthly|studio|\d\s*br|\d\s*bed|landlord|tenant|tour)\b", re.I)


def site_name(url: str | None) -> str:
    """'Zillow' for a zillow.com link, else the host without 'www.' ('rentmaplerow.com'). '' for no usable link."""
    try:
        host = (urlsplit(str(url or "").strip()).hostname or "").lower()
    except ValueError:
        return ""
    if not host and url and "." in str(url).split("/")[0]:
        try:
            host = (urlsplit("https://" + str(url).strip()).hostname or "").lower()
        except ValueError:
            host = ""
    host = host[4:] if host.startswith("www.") else host
    if not host:
        return ""
    for domain, name in KNOWN_SITES.items():
        if host == domain or host.endswith("." + domain):
            return name
    return host


def _today() -> date:
    return date.today()


def _tidy(text: str) -> str:
    text = (text or "")[:MAX_CHARS]
    for a, b in (("\u00a0", " "), ("\u2009", " "), ("\u202f", " "), ("\u200b", ""), ("\ufeff", ""), ("\r\n", "\n"), ("\r", "\n"),
                 ("\u2019", "'"), ("\u2018", "'"), ("\u201c", '"'), ("\u201d", '"'), ("\u2212", "-")):
        text = text.replace(a, b)
    text = re.sub(r"[\u2013\u2014]", "-", text)
    return text


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def _tidy_number(x: float) -> int | float:
    return int(x) if float(x).is_integer() else round(x, 2)


# --------------------------------------------------------------------------- money
def _amounts(text: str) -> list[dict[str, Any]]:
    """Every $ amount with what it is probably for. Keys: value, start, end, marker ('monthly', 'per bed' or ''), range
    (True when it is the low end of a "$1,350 - $1,795"), fee (a deposit, fee, HOA and so on), labelled (the words just
    before say rent or price)."""
    out: list[dict[str, Any]] = []
    for m in _AMOUNT.finditer(text):
        value = _num(m.group(1) + (m.group(2) or ""))
        if m.group(3):
            value *= 1000
        line_start = text.rfind("\n", 0, m.start()) + 1
        line_end = text.find("\n", m.end())
        line_end = len(text) if line_end < 0 else line_end
        before, after = text[line_start:m.start()], text[m.end():line_end]
        if not before.strip() and line_start > 0:  # "Monthly Rent" on one line and the amount on the next
            prev_start = text.rfind("\n", 0, line_start - 1) + 1
            prev = text[prev_start:line_start - 1]
            if len(prev) <= 40:
                before = prev + " "
        clause = re.split(r"[;|\u2022\u00b7\n]|(?<!est)(?<!Est)(?<!EST)(?<!approx)[.!?]\s+|,\s|\$\s?\d[\d,]*(?:\.\d+)?[kK]?", before)[-1][-40:]
        tail, is_range = after, False
        rm = re.match(r"\s*\+?\s*(?:-|to)\s*\$\s?[\d,]+(?:\.\d{1,2})?\+?", after, re.I)
        if rm:
            tail, is_range = after[rm.end():], True
        marker = ""
        if _PER_BED.match(tail):
            marker = "per bed"
        elif _RENT_MARK.match(tail) or _BR_MARK.match(tail):
            marker = "monthly"
        fee = bool(_FEE_BEFORE.search(clause))
        new_price = bool(re.search(r"(?:reduced|dropped|lowered|cut|now|marked down)\s+(?:price\s+)?to\s*$", clause))
        if _BR_MARK.match(tail):
            fee = bool(re.search(r"\b(?:deposit|fee|pet|hoa|tax)\s*[:\-]?\s*$", clause, re.I))
        elif marker == "monthly":
            fee = bool(_FEE_BEFORE.search(clause[-22:])) and not _RENT_LABEL.search(clause[-14:]) or bool(_FEE_AFTER_MONTHLY.match(tail))
        elif not fee:
            fee = bool(_FEE_AFTER_STRICT.match(tail))
        if new_price:  # "reduced to $318,500" is the new asking price, "reduced $6,500" is the size of the cut
            fee = False
        out.append({"value": value, "start": m.start(), "end": m.end(), "marker": marker, "range": is_range, "fee": fee,
                    "labelled": new_price or bool(_RENT_LABEL.search(clause[-24:])), "clause": clause.lower()})
    return out


def _price(text: str) -> float | None:
    """The monthly rent if the text gives one, else the asking price of a home for sale."""
    amounts = [a for a in _amounts(text) if not a["fee"] and a["marker"] != "per bed"]
    for a in amounts:  # "$1,495/mo", "$1500 / 1br"
        if a["marker"] == "monthly" and 200 <= a["value"] <= 30000:
            return a["value"]
    sale_text = bool(_SALE_WORDS.search(text))
    for a in amounts:  # "Rent: $1,495", "Monthly rent" on the line above
        if a["labelled"] and 200 <= a["value"] <= 30000 and not (sale_text and a["value"] >= 20000):
            return a["value"]
    big = [a for a in amounts if a["value"] >= 20000]
    if big and (sale_text or not _RENT_WORDS.search(text)):
        for a in big:
            if a["labelled"]:
                return a["value"]
        return big[0]["value"]
    if big and not any(300 <= a["value"] <= 20000 for a in amounts):
        return big[0]["value"]
    m = re.search(r"\b(?:rent|price|asking)\b[^$\d\n]{0,20}?(\d{1,2},\d{3}|\d{3,5})\b(?!\s*(?:sq|sf|ft|bed|\d))", text, re.I)
    if m and 200 <= _num(m.group(1)) <= 30000:  # a rent written without a dollar sign
        return _num(m.group(1))
    if _RENT_WORDS.search(text) and not sale_text:
        for a in amounts:
            if 300 <= a["value"] <= 20000:
                return a["value"]
    return None


def _money_after(text: str, label: str, *, lo: float = 0, hi: float = 1_000_000, gap: int = 28, skip_before: str = "") -> list[float]:
    """Amounts written as "<label> ... $N" or "$N <label>" (labels are regex text). Several matches are all returned."""
    found: list[float] = []
    for m in re.finditer(r"(?:" + label + r")[ \t:\-=(]{0,%d}?(\n\s*)?\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?(?!\d)" % gap, text, re.I):
        if m.group(1) and text[text.rfind("\n", 0, m.start()) + 1:m.start()].strip():
            continue  # "$1,500 deposit" then "$50 application fee" on the next line: that $50 is not the deposit
        if skip_before and re.search(skip_before, text[max(0, m.start() - 14):m.start()], re.I):
            continue
        v = _num(m.group(2))
        if lo <= v <= hi:
            found.append(v)
    for m in re.finditer(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?[ \t]*(?:/[ \t]*mo(?:nth)?[ \t]*)?(?:one[- ]time |non[- ]refundable |refundable )?(?:" + label + r")", text, re.I):
        if skip_before and re.search(skip_before, text[max(0, m.start() - 14):m.start()], re.I):
            continue
        v = _num(m.group(1))
        if lo <= v <= hi:
            found.append(v)
    return found


# --------------------------------------------------------------------------- facts
def _beds(text: str) -> float | None:
    low = text.lower()
    hits: list[tuple[int, float]] = []
    for m in re.finditer(r"(?<![\d.,$/])\b(\d{1,2}(?:\.\d)?)[ \t]*(?:-[ \t]*\d{1,2}(?:\.\d)?[ \t]*)?(?:bed(?:room)?s?|bds?|brs?|bdrms?)\b(?!\s*(?:and breakfast|room only))", low):
        hits.append((m.start(), float(m.group(1))))
    for m in re.finditer(r"\b(?:bed(?:room)?s?|bds?)\s*[:\-]\s*(\d{1,2}(?:\.\d)?)\b", low):
        hits.append((m.start(), float(m.group(1))))
    for m in re.finditer(r"\b(\d)\s*(?:bd|br|bed)\s*[/|]\s*\d(?:\.\d)?\s*(?:ba|bth|bath)", low):
        hits.append((m.start(), float(m.group(1))))
    studio = re.search(r"\bstudio\b(?!\s*(?:apartments?\s*)?(?:are|is|also|available)\b)", low)
    if studio and not re.search(r"\bno studio\b", low) and not [h for h in hits if h[1] >= 1]:
        hits.append((studio.start(), 0.0))  # "Studio-plus ... 1 bed" is a 1 bedroom; only a plain studio is 0
    hits = [h for h in hits if h[1] <= 20]
    return min(hits)[1] if hits else None


def _baths(text: str) -> float | None:
    low = text.lower()
    m = re.search(r"(\d{1,2})\s*full\s*(?:bath(?:room)?s?|ba)\b[^.\n]{0,25}?(\d)\s*(?:half|1/2|partial)\s*(?:bath(?:room)?s?|ba)", low)
    if m:
        return int(m.group(1)) + 0.5 * int(m.group(2))
    m = re.search(r"(\d{1,2})\s*full\W{1,3}(\d)\s*(?:half|partial)\s*(?:bath(?:room)?s?|ba)\b", low)
    if m:
        return int(m.group(1)) + 0.5 * int(m.group(2))
    hits: list[tuple[int, float]] = []
    for m in re.finditer(r"(?<![\d.,$/])\b(\d{1,2}(?:\.\d)?)[ \t]*(?:-[ \t]*\d(?:\.\d)?[ \t]*)?(?:full[ \t]+)?(?:bath(?:room)?s?|bths?|ba)\b", low):
        hits.append((m.start(), float(m.group(1))))
    for m in re.finditer(r"\bbath(?:room)?s?\s*[:\-]\s*(\d{1,2}(?:\.\d)?)\b", low):
        hits.append((m.start(), float(m.group(1))))
    for m in re.finditer(r"\b\d\s*(?:bd|br|bed)\s*[/|]\s*(\d(?:\.\d)?)\s*(?:ba|bth|bath)", low):
        hits.append((m.start(), float(m.group(1))))
    hits = [h for h in hits if h[1] <= 15]
    return min(hits)[1] if hits else None


def _sqft(text: str) -> int | None:
    low = text.lower()
    num = r"(\d{1,2},\d{3}|\d{3,5})"
    pats = [r"(?<![\d,.])" + num + r"(?:[ \t]*-[ \t]*(?:\d{1,2},\d{3}|\d{3,5}))?[ \t]*(?:sq\.?\s?ft\.?|sqft|sq\.? ?feet|square\s*(?:feet|foot|ft)|\bsf\b|ft2|ft\u00b2|s\.f\.)",
            r"\b(?:sq\.?\s?ft\.?|square (?:feet|footage)|living area|floor area|size)\s*[:\-]\s*" + num]
    best: tuple[int, int] | None = None
    for pat in pats:
        for m in re.finditer(pat, low):
            if re.search(r"\blot\b|\blot size\b|acre", low[max(0, m.start() - 22):m.start()]):
                continue
            v = int(m.group(1).replace(",", ""))
            if 150 <= v <= 20000 and (best is None or m.start() < best[0]):
                best = (m.start(), v)
    return best[1] if best else None


def _laundry(text: str) -> str:
    low = text.lower()
    low = re.sub(r"w/?d\s*(?:hook-?ups?|connections?)|washer\s*(?:/|and|&)?\s*dryer\s*(?:hook-?ups?|connections?)|laundry hook-?ups?", " hookups ", low)
    m = re.search(r"\blaundry(?: type| features?| facilit\w+)?\s*[:\-]\s*([^\n.;,]{0,40})", low)
    if m:
        v = m.group(1)
        if re.search(r"in[- ]?(?:unit|home|suite)|inside|private|washer|w/d|full[- ]size", v):
            return "in_unit"
        if re.search(r"shared|common|building|bldg|on[- ]?site|community|facilit|room|coin|center|laundromat", v):
            return "in_building"
        if re.match(r"\s*(?:none|no\b|n/a)", v):
            return "none"
    in_unit = r"(?:in[- ]?(?:unit|home|suite|apartment|residence)\s*(?:washer|laundry|w/?d)|(?:washer\s*(?:/|and|&|\+)\s*dryer|w/\s?d|laundry|washer|dryer)\s*(?:is\s*)?(?:in[- ]?(?:the[- ])?(?:unit|home|suite|apartment|residence)|inside (?:the )?(?:unit|apartment))|in[- ]?(?:unit|home|suite)\s*(?:laundry|washers?|dryers?|w/?d|washer\s*(?:/|and|&)\s*dryer)|(?:full[- ]size|stackable|front[- ]load\w*)\s*(?:washer|w/?d)|washer\s*(?:/|and|&|\+)\s*dryer\s*(?:included|provided|in)|w/\s?d\s*(?:included|provided)|\bw/d\b(?!\s*hook))"
    negated = r"\bno\s+(?:in[- ]?(?:unit|home|suite)\s+)?(?:washers?|laundry|w/?d|washer\s*(?:/|and|&)\s*dryer)\b|\bwithout\s+(?:a\s+)?(?:washer|laundry)\b|\bno in[- ]?unit\b"
    building = (r"\blaundry\s*(?:room|rooms|facilit\w+|center|area|on[- ]?(?:site|each floor|every floor|premises)|in (?:the )?(?:building|bldg|basement|complex)|in bldg|available on)"
                r"|\b(?:on[- ]?site|shared|community|common|coin[- ]?op\w*|building|bldg)\s*laundry|\blaundry\s*(?:is\s*)?(?:available\s*)?(?:on[- ]?site|in bldg|in building)"
                r"|\bwasher\s*(?:/|and|&)\s*dryer\s*(?:in|on)\s*(?:the\s*)?(?:building|bldg|floor|site)")
    positive = re.sub(negated, " ", low)
    if re.search(in_unit, positive):
        return "in_unit"
    if re.search(building, low):
        return "in_building"
    if re.search(r"\bno\s+(?:on[- ]?site\s+|in[- ]?unit\s+)?(?:laundry|washer|w/?d)\b|\blaundry:\s*none\b", low):
        return "none"
    if " hookups " in low:
        return "hookups"
    return ""


def _dishwasher(text: str) -> int | None:
    low = text.lower()
    if re.search(r"\bno\s+dish\s?washer|\bwithout\s+(?:a\s+)?dish\s?washer|\bdish\s?washer\s*[:\-]\s*(?:no|none)\b", low):
        return 0
    if re.search(r"\bdish\s?washer", low):
        return 1
    return None


def _parking(text: str) -> tuple[str, float | None]:
    low = text.lower()
    kind = ""
    label = re.search(r"\bparking(?: features?| type)?\s*[:\-]\s*([^\n.;]{0,40})", low)
    if label and not re.search(r"\bgarage\b", low):
        v = label.group(1)
        if re.search(r"\bcarport|\bcovered", v):
            kind = "covered"
        elif re.search(r"\bstreet\b", v) and not re.search(r"off[- ]?street", v):
            kind = "street"
        elif re.search(r"\blot\b|off[- ]?street|surface|assigned|reserved|driveway|included|free|yes|on[- ]?site", v):
            kind = "lot"
        elif re.match(r"\s*(?:none|no)\b", v):
            kind = "none"
    if kind:
        pass
    elif re.search(r"\b(?:attached |detached |private |heated |\d[- ]car |reserved |covered )?garage\b(?! door| apartment)", low) \
            and not re.search(r"\bno\s+garage\b|\bgarage\s*[:\-]\s*(?:no|none)\b", low):
        kind = "garage"
    elif re.search(r"\bcarports?\b|\bcovered\s+(?:parking|spaces?|spots?)\b", low):
        kind = "covered"
    elif re.search(r"\b(?:off[- ]?street|surface|free|assigned|reserved|on[- ]?site|private|ample|plenty of|paved|resident)\s+parking\b|\bparking\s+(?:lot|included|available|space|spot|provided|on[- ]?site)|\bdriveway\b|\bparking\s*[:\-]\s*(?:lot|yes|included|free|assigned|surface)|\b\d\s*parking (?:spaces?|spots?)\b", low):
        kind = "lot"
    elif re.search(r"\b(?:street|on[- ]street)\s+parking\b|\bparking\s*[:\-]\s*street\b", low):
        kind = "street"
    elif re.search(r"\bno\s+(?:off[- ]?street\s+|on[- ]?site\s+)?parking\b|\bparking\s*[:\-]\s*none\b", low):
        kind = "none"
    cost: float | None = None
    m = re.search(r"(?:garage|carport|covered parking|reserved parking|parking(?: fee| rate| cost)?|parking space|parking spot)s?\s*(?:space|spot|stall|fee|rental|rent)?s?[ \t:\-=(]{0,6}(?:is |are |from |starting at |for |at |only )?\$\s?(\d{2,4})(?:\.\d\d)?\b(?!\s*(?:deposit|one[- ]time|setup|set-up|/\s*\d\s*(?:br|bd|bed)))", low)
    if m:
        cost = float(m.group(1))
    else:
        m = re.search(r"\$\s?(\d{2,4})\s*(?:/\s*mo(?:nth)?|per month|a month|monthly)?\s*(?:for |per )?(?:a |the )?(?:reserved |covered |garage |private )?(?:parking|garage|carport)\b(?!\s*deposit)", low)
        if m:
            cost = float(m.group(1))
    if cost is None and re.search(r"\b(?:includes?|including)\s+(?:\w+[- ]?){0,2}parking\b|\bparking\s*[:\-][^.\n;]{0,30}\b(?:included|free)\b", low) and kind and kind != "none":
        cost = 0.0
    if cost is None and re.search(r"\bfree (?:off[- ]?street |on[- ]?site |surface |assigned |resident |tenant )?parking\b|\bparking\s*(?:is\s*)?(?:included|free|at no (?:extra )?charge)\b|\bparking\s*[:\-]\s*(?:free|included)\b", low):
        cost = 0.0
    return kind, cost


def _pets(text: str) -> str:
    low = text.lower()
    if re.search(r"\bno pets\b(?!\s+(?:restrictions?|limits?|problem|fee))|\bpets (?:are )?not (?:allowed|permitted|accepted)\b|\bnot pet[- ]friendly\b|\bpets\s*[:\-]\s*(?:no\b|none|not allowed)|\bpet policy\s*[:\-]\s*no\b|\bno animals\b", low):
        return "none"
    work = low
    cats = dogs = False
    no_cats = re.search(r"\bno cats?\b|\bcats? (?:are )?not (?:allowed|permitted|accepted)|\bno cats? allowed", work)
    no_dogs = re.search(r"\bno dogs?\b|\bdogs? (?:are )?not (?:allowed|permitted|accepted)|\bno dogs? allowed|\bno (?:large|big|aggressive) dogs?|\bno breed", work)
    if re.search(r"\bcats? and dogs?\b|\bdogs? and cats?\b|\bcats?\s*(?:&|/|,)\s*dogs?\b|\bdogs?\s*(?:&|/|,)\s*cats?\b|\bpet[- ]friendly\b|\bpets (?:ok|okay|allowed|welcome|considered|accepted)\b|\bpets\s*[:\-]\s*(?:yes|ok|okay|allowed|welcome)\b|\ball pets\b|\bdogs? (?:are )?ok.{0,40}cats? (?:are )?ok|\bcats? (?:are )?ok.{0,40}dogs? (?:are )?ok", work):
        cats = dogs = True
    if re.search(r"\bcats?\b(?:\s*(?:are|is))?\s*(?:ok|okay|allowed|welcome|accepted|friendly|permitted)|\bcats? only\b|\bcat[- ]friendly\b|\bpurrr", work):
        cats = True
    if re.search(r"\bdogs?\b(?:\s*(?:are|is))?\s*(?:ok|okay|allowed|welcome|accepted|friendly|permitted)|\bdogs? only\b|\bdog[- ]friendly\b|\bwoof|\bsmall dogs?\b|\bdogs? under\b", work):
        dogs = True
    if re.search(r"\bcats?\s+(?:are\s+)?(?:negotiable|considered|case[- ]by[- ]case|by approval|with approval|on approval|upon approval)", work):
        cats = True
    if re.search(r"\bdogs?\s+(?:are\s+)?(?:negotiable|considered|case[- ]by[- ]case|by approval|with approval|on approval|upon approval)", work):
        dogs = True
    if no_cats and not re.search(r"\bcats? only\b", work):
        cats = False
    if no_dogs and not re.search(r"\bdogs? only\b", work):
        dogs = False
    if re.search(r"\bcats? only\b", work):
        dogs = False
    if re.search(r"\bdogs? only\b", work):
        cats = False
    if cats and dogs:
        return "both"
    if cats:
        return "cats"
    if dogs:
        return "dogs"
    return ""


def _pet_fees(text: str) -> dict[str, float]:
    """Pet rent (monthly) and pet fee or deposit (one time), kept apart."""
    out: dict[str, float] = {}
    used: set[int] = set()
    for m in re.finditer(r"\$[ \t]?(\d{1,4})(?:\.\d\d)?[ \t]*(/[ \t]*mo(?:nth)?|per month|monthly|a month)?[ \t]*(?:per pet[ \t]*)?"
                         r"(?:one[- ]time[ \t]+|non[- ]refundable[ \t]+|refundable[ \t]+)?(?:pet\s+(rent|fees?|deposit|charge)\b|per pet\b)", text, re.I):
        used.add(m.start())
        rent = bool(m.group(2)) or (m.group(3) or "").lower() in ("rent", "charge")
        out.setdefault("pet_rent" if rent else "pet_fee", float(m.group(1)))
    labels = list(re.finditer(r"\bpet\s+(rent|fees?|deposit|charge)s?\b", text, re.I))
    for i, m in enumerate(labels):
        stop = min([m.end() + 60, text.find("\n", m.end()) if text.find("\n", m.end()) >= 0 else len(text)]
                   + ([labels[i + 1].start()] if i + 1 < len(labels) else []))
        rest = text[m.end():stop]
        am = re.match(r"[^$\n]{0,25}?(\$\s?(\d{1,4})(?:\.\d\d)?)(?!\d)(.{0,24})", rest)
        if not am or (m.end() + am.start(1)) in used or re.search(r"\bpet\b", rest[:am.start(1)], re.I):
            continue
        trailing = re.split(r"[.;]\s", am.group(3))[0]
        monthly = (m.group(1).lower() in ("rent", "charge") or bool(re.match(r"\s*(?:/\s*mo|per month|monthly|a month)", trailing, re.I))
                   or "monthly" in text[max(0, m.start() - 10):m.start()].lower())
        out.setdefault("pet_rent" if monthly else "pet_fee", float(am.group(2)))
    m = re.search(r"\bmonthly\s+pet\s+(?:fee|rent|charge)\s*[:\-]?\s*\$\s?(\d{1,4})", text, re.I)
    if m:
        out["pet_rent"] = float(m.group(1))
    if not out:  # "cats negotiable, $50 extra": an extra charge for the pet, taken as monthly pet rent
        m = re.search(r"\b(?:cats?|dogs?|pets?)\b[^.\n$]{0,40}\$\s?(\d{1,4})(?:\.\d\d)?\s*(?:extra|more|additional)\b([^.\n]{0,25})", text, re.I)
        if m:
            one_time = re.search(r"one[- ]time|deposit|non[- ]?refundable|once", m.group(2), re.I)
            out["pet_fee" if one_time else "pet_rent"] = float(m.group(1))
    return out

_NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4}


def _pet_deposit(text: str) -> tuple[float | None, str]:
    """A refundable pet deposit ("$400 refundable pet deposit"), kept apart from the one-time pet fee: it comes back,
    so it counts only as cash needed at move-in. Returns (amount, text with that phrase blanked so _pet_fees skips it)."""
    pats = (r"\$\s?(\d{1,4})(?:\.\d\d)?[ \t]*(?:one[- ]time[ \t]+)?(?:refundable[ \t]+)?pet[ \t]+deposit\b",
            r"\bpet[ \t]+deposit[ \t]*[:\-]?[ \t]*\$\s?(\d{1,4})(?:\.\d\d)?\b(?!/)")
    for pat in pats:
        for m in re.finditer(pat, text, re.I):
            around = text[max(0, m.start() - 14):m.start()] + " " + text[m.start():m.end() + 28]
            if re.search(r"non[- ]?refundable", around, re.I):
                continue  # a non-refundable pet deposit is a fee, not money that comes back
            return float(m.group(1)), text[:m.start()] + " " * (m.end() - m.start()) + text[m.end():]
    return None, text


_PET_WORD = re.compile(r"\b(?:pets?|cats?|dogs?|animals?|kittens?|puppy|puppies)\b", re.I)


def _pet_side_deposits(text: str, rent: float | None) -> tuple[dict[str, float], str]:
    """A "$250 deposit non-refundable" written next to the pets is a pet charge, never the security deposit. Returns
    ({"pet_fee" or "pet_deposit": amount}, text with those amounts blanked so the security deposit search skips them)."""
    found: dict[str, float] = {}
    blanked = text
    pat = (r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?[ \t]*(?:/[ \t]*mo(?:nth)?[ \t]*)?(?:one[- ]time[ \t]+|non[- ]?refundable[ \t]+|refundable[ \t]+)?(security[ \t]+|damage[ \t]+|pet[ \t]+|holding[ \t]+|key[ \t]+|parking[ \t]+)?deposits?\b"
           r"|\bdeposits?\b[ \t:\-=(]{0,4}(?:of[ \t]+)?\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?")
    for m in re.finditer(pat, text, re.I):
        if m.group(2) or re.search(r"(?:security|damage|pet|holding|key|parking)[ \t]+$", text[max(0, m.start() - 12):m.start()], re.I):
            continue  # "security deposit", "pet deposit" and so on name themselves
        amount = _num(m.group(1) or m.group(3))
        if rent and amount >= rent * 0.9:
            continue  # as big as a month's rent: that is the security deposit
        nonref = bool(re.search(r"non[- ]?refundable", text[max(0, m.start() - 20):m.end() + 25], re.I))
        before = text[max(0, m.start() - 80):m.start()]
        after = text[m.end():m.end() + 40]
        if nonref:
            pet = bool(_PET_WORD.search(before) or _PET_WORD.search(re.split(r"[.!?;\n]", after)[0]))
        else:
            near_before = re.split(r"[,.!?;\n]", before)[-1]
            near_after = re.split(r"[,.!?;\n]", after)[0]
            pet = bool(_PET_WORD.search(near_before) or _PET_WORD.search(near_after))
        if not pet:
            continue
        found.setdefault("pet_fee" if nonref else "pet_deposit", amount)
        blanked = blanked[:m.start()] + " " * (m.end() - m.start()) + blanked[m.end():]
    return found, blanked


def _pet_limit_fields(text: str) -> dict[str, Any]:
    """Structured pet limits: pet_weight_limit (lb), pet_count_limit, pet_breed_note and fenced_yard (1 or 0)."""
    out: dict[str, Any] = {}
    w = re.search(r"\b(?:dogs?|pets?|animals?)\b[^.\n;]{0,40}?(?:under|up to|less than|below|at most|max(?:imum)?(?: of)?|weigh(?:ing|s)?(?: up to| under)?|<)\s*(\d{1,3})\s*(?:lbs?\b|pounds?\b)", text, re.I) \
        or re.search(r"\b(\d{1,3})\s*(?:lbs?\b|pounds?\b)\s*(?:weight\s*)?(?:limit|max(?:imum)?)", text, re.I) \
        or re.search(r"\bweight (?:limit|max(?:imum)?)\s*(?:of|is|:)?\s*(\d{1,3})\s*(?:lbs?\b|pounds?\b)?", text, re.I)
    if w and 3 <= int(w.group(1)) <= 300:
        out["pet_weight_limit"] = float(w.group(1))
    n = re.search(r"\b(?:max(?:imum)?(?: of)?|limit(?: of)?|up to|no more than|at most)\s+(\d|one|two|three|four)\s+(?:pets?|animals?)\b", text, re.I) \
        or re.search(r"\b(\d|one|two|three|four)\s+(?:pets?|animals?)\s+(?:max(?:imum)?|limit|per (?:unit|apartment|home|household))", text, re.I)
    if n:
        v = n.group(1).lower()
        count = int(v) if v.isdigit() else _NUM_WORDS[v]
        if count >= 1:
            out["pet_count_limit"] = count
    if "pet_count_limit" not in out:
        for sentence in re.split(r"[.\n;]", text):
            if _PET_WORD.search(sentence):
                cm = re.search(r"\b(\d|one|two|three|four)\s+max(?:imum)?\b(?!\s*(?:occupants?|people|residents?|adults?|tenants?))", sentence, re.I)
                if cm:
                    v = cm.group(1).lower()
                    count = int(v) if v.isdigit() else _NUM_WORDS[v]
                    if count >= 1:
                        out["pet_count_limit"] = count
                        break
    b = re.search(r"[^.\n;]*\b(?:breed|breeds|breed restrictions?)\b[^.\n;]*", text, re.I)
    if b:
        clause = " ".join(b.group(0).split()).strip(" -:,")
        if 0 < len(clause) <= 140:
            out["pet_breed_note"] = clause[0].upper() + clause[1:]
    if re.search(r"\b(?:no|not a|without a)\s+fenced\b|\bunfenced\b|\bnot fenced\b", text, re.I):
        out["fenced_yard"] = 0
    elif re.search(r"\bfenced[- ](?:in[- ])?(?:back|front|private )?(?:yard|garden|lot|patio)|\b(?:yard|backyard)\s+(?:is\s+)?(?:fully\s+)?fenced|\bfully fenced\b", text, re.I):
        out["fenced_yard"] = 1
    return out


def _pet_limits(text: str) -> list[str]:
    """Weight, breed and count limits on pets ("dogs under 50 lbs"), as short plain lines, since the pets field only says which pets."""
    found: list[str] = []
    for m in re.finditer(r"[^.\n;]*\b(?:dogs?|cats?|pets?|animals?|breeds?)\b[^.\n;]*", text, re.I):
        clause = " ".join(m.group(0).split()).strip(" -:,")
        if re.search(r"\b\d{1,3}\s*(?:lbs?|pounds?)|\bbreed|\bweight|\brestrict\w*|\blimits?\b|\bmax(?:imum)?\b|\bunder \d|\bup to \d|\b(?:two|2) pets\b|\bsize\b", clause, re.I) \
                and len(clause) <= 140 and not any(clause.lower() in f.lower() for f in found):
            found.append(clause[0].upper() + clause[1:])
    return found[:2]


def _app_fee_per_person(text: str) -> str:
    """"Application fee $55 per adult": the fee field is one amount, so keep the per-person wording visible."""
    m = re.search(r"application(?: processing)? fees?[^.\n]{0,25}?\$\s?(\d{1,4})(?:\.\d\d)?[^.\n]{0,12}?\b(?:per|each|/)\s*(adult|applicant|person|occupant|tenant|resident|roommate)", text, re.I) \
        or re.search(r"\$\s?(\d{1,4})(?:\.\d\d)?\s*(?:application fee|app fee)[^.\n]{0,12}?\b(?:per|each|/)\s*(adult|applicant|person|occupant|tenant|resident|roommate)", text, re.I) \
        or re.search(r"application(?: processing)? fees?[^.\n]{0,40}?(?:\bper|\beach)\s+(adult|applicant|person|occupant|tenant|resident|roommate)", text, re.I)
    if not m:
        return ""
    who = m.group(m.lastindex).lower()
    amount = f" ${float(m.group(1)):,.0f}" if m.lastindex >= 2 and m.group(1).replace('.', '').isdigit() else ""
    return f"The application fee{amount} is charged per {who}, so each adult who applies pays it."


def app_fee_note_for_people(values: dict[str, Any], people: int) -> dict[str, Any]:
    """For the Add preview only: when the application fee is charged per adult and the search has several people, say what
    all of them pay together. The ``application_fee`` field itself stays the one-person amount. Returns ``values`` (changed
    in place) so a caller can chain it."""
    note = values.get("found_in_listing") or ""
    fee = values.get("application_fee")
    if people > 1 and isinstance(fee, (int, float)) and fee > 0 and "is charged per" in note and "together" not in note:
        values["found_in_listing"] = note + f" For {people} people that is ${fee * people:,.0f} together."
    return values


def _move_in_months(text: str) -> tuple[int, bool]:
    """(months of rent due at move-in, deposit also due) from "first and last month" or "first, last and deposit"."""
    m = re.search(r"\b(?:first|1st)\b(?:\s+month(?:'?s)?(?:\s+rent)?)?\s*(?:,|and|&|\+|/)\s*(?:and\s+)?\blast\b(?:\s+month(?:'?s)?(?:\s+rent)?)?"
                  r"(?:\s*(?:,|and|&|\+|/|plus)\s*(?:a\s+)?(?:the\s+)?(?:security\s+)?(deposit))?", text, re.I)
    if not m:
        return 0, False
    return 2, bool(m.group(1))


_WORD_NUM = {"one": 1, "a": 1, "1": 1, "two": 2, "2": 2}


def _deposit_in_months(text: str) -> int:
    """The security deposit written as a number of months of rent ("security deposit one month", "deposit equal to one month's
    rent"), as that number of months. 0 when the text gives none."""
    for pat in (r"\b(?:security |damage )?deposits?\b[ \t:\-]{0,4}(?:is |of |equal to |equals |equivalent to |=)?[ \t]*(one|two|a|1|2)[- ]months?(?:'s?)?(?:[ \t]+(?:of[ \t]+)?rent)?\b",
                r"\b(one|two|1|2)[- ]months?(?:'s?)?[ \t]+(?:security |damage )deposit\b"):
        m = re.search(pat, text, re.I)
        if m:
            return _WORD_NUM[m.group(1).lower()]
    return 0


def _three_months_up_front(text: str) -> bool:
    return bool(re.search(r"\b(?:three|3)[- ]months?(?:'s?)?(?:[ \t]+(?:of[ \t]+)?rent)?[^.\n]{0,30}\b(?:up[- ]?front|due (?:at|before|on|by)|at (?:signing|move[- ]?in|lease signing))", text, re.I)
                or re.search(r"\b(?:up[- ]?front|due (?:at|before)|at (?:signing|move[- ]?in))[^.\n]{0,30}\b(?:three|3)[- ]months?", text, re.I))


def _closing_costs(text: str) -> float | None:
    """"Estimated closing costs $9,800" -> 9800."""
    m = re.search(r"\bclosing costs?(?:\s+(?:est\w*\.?|estimate[d]?))?[ \t:\-=]{0,6}(?:of |about |around |approx\.? |~)?\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?(?!\d)", text, re.I) \
        or re.search(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?[ \t]*(?:in |for )?(?:est\w*\.?[ \t]+)?closing costs?\b", text, re.I)
    if not m:
        return None
    value = _num(m.group(1))
    return value if 100 <= value <= 5_000_000 else None


def _price_cut(text: str) -> float | None:
    """The size of a price cut ("Price reduced $10,000", "reduced by $10,000"), never the new price ("reduced to $...")."""
    m = re.search(r"\b(?:price[ \t]+(?:reduced|cut|drop(?:ped)?|reduction)|reduced|price[ \t]+change)[ \t:\-]*(?:by[ \t]+)?\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?!\d)", text, re.I)
    if not m or re.search(r"\bto\s*$", text[max(0, m.start(1) - 8):m.start(1)], re.I):
        return None
    return _num(m.group(1))


def _insurance(text: str) -> float | None:
    """Home insurance as a yearly amount (the field is per year). "est $1,100/yr" -> 1100; "$90/mo" -> 1080."""
    m = re.search(r"\b(?:home(?:owner'?s?)?\s+|hazard\s+)?insurance(?:\s+(?:est\w*\.?|estimate[d]?|premium|cost))*[ \t:\-=]{0,6}(?:about |around |approx\.? |~)?"
                  r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?\s*(/\s*\w+|per\s+\w+|a\s+(?:year|month)|annual\w*|monthly)?", text, re.I)
    if not m:
        return None
    value, per = _num(m.group(1)), (m.group(2) or "").lower()
    if re.search(r"mo", per):
        value *= 12
    return round(value, 2) if 100 <= value <= 100000 else None


def _special_assessment_facts(text: str) -> tuple[float | None, str, str]:
    """(one-time amount or None, payer "seller" / "buyer" / "", the matching sentence) for a special assessment.
    An amount quoted per month is left out of the amount (it is not one-time), but the sentence still comes back."""
    if re.search(r"\bno (?:known |pending |current )?special assessments?\b", text, re.I):
        return None, "", ""
    sentence = None
    for m in re.finditer(r"[^.\n]*\bspecial assessments?\b[^.\n]*", text, re.I):
        sentence = m.group(0)
        if re.search(r"\$\s?\d", sentence):
            break
    if sentence is None:
        return None, "", ""
    am = re.search(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?!\d)(?!,\d)(?!\s*(?:/\s*mo|per month|monthly|a month))", sentence)
    payer = ""
    if re.search(r"\bseller\b[^.\n]{0,25}\b(?:pays?|paid|to pay|responsible|covers?|credit)\b|\bpaid (?:in full )?by (?:the )?seller|\bseller[- ]paid", sentence, re.I):
        payer = "seller"
    elif re.search(r"\bbuyer\b[^.\n]{0,25}\b(?:pays?|assumes?|to pay|responsible|takes?|inherits?|covers?)\b|\bpaid by (?:the )?buyer|\bassumed by (?:the )?buyer|\bbuyer[- ]paid", sentence, re.I):
        payer = "buyer"
    return (_num(am.group(1)) if am else None), payer, sentence


def _special_assessment(text: str) -> str:
    """A plain line about a special assessment: the amount and who pays it."""
    if re.search(r"\bno (?:known |pending |current )?special assessments?\b", text, re.I):
        return ""
    sentence = None
    for m in re.finditer(r"[^.\n]*\bspecial assessments?\b[^.\n]*", text, re.I):
        sentence = m.group(0)
        if re.search(r"\$\s?\d", sentence):
            break
    if sentence is None:
        return ""
    am = re.search(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)", sentence)
    if re.search(r"\bseller\b[^.\n]{0,25}\b(?:pays?|paid|to pay|responsible|covers?|credit)\b|\bpaid (?:in full )?by (?:the )?seller|\bseller[- ]paid", sentence, re.I):
        who = "the seller pays it"
    elif re.search(r"\bbuyer\b[^.\n]{0,25}\b(?:pays?|assumes?|to pay|responsible|takes?|inherits?|covers?)\b|\bpaid by (?:the )?buyer|\bassumed by (?:the )?buyer|\bbuyer[- ]paid", sentence, re.I):
        who = "the buyer pays it"
    else:
        who = "the listing doesn't say who pays it, so ask"
    if am:
        return f"Special assessment ${_num(am.group(1)):,.0f}: {who}."
    return f"A special assessment is mentioned but no amount is given: {who}."


def _days_on_market(text: str) -> int | None:
    """"41 days on Zillow", "Days on market: 41", "Time on Redfin 41 days"."""
    site = r"(?:zillow|redfin|realtor(?:\.com)?|trulia|homes\.com|the market|market|site)"
    for pat in (r"\b(\d{1,4})\s+days?\s+on\s+" + site, r"\bdays?\s+on\s+(?:market|" + site + r")\s*[:\-]?\s*(\d{1,4})\b",
                r"\btime\s+on\s+" + site + r"\s*[:\-]?\s*(\d{1,4})\s+days?"):
        m = re.search(pat, text, re.I)
        if m:
            return int(m.group(1))
    return None


_NOT_AN_AGENT = re.compile(r"^(?:the\s+)?(?:owner|property manage\w*|landlord|private|seller|you)\b", re.I)


def _listing_agent(text: str) -> str:
    """The listing agent and company from "Listed by Jane Q. Agent, Example Realty" (phone numbers and licence numbers dropped)."""
    m = re.search(r"\b(?:listed by|listing agent|listing provided by|listing courtesy of|presented by)\s*[:\-]?[ \t]*([^\n]{3,140})", text, re.I)
    if not m:
        return ""
    line = re.sub(r"\(?\+?\d[\d\s().-]{6,}\d\)?", " ", m.group(1))
    line = re.sub(r"\b(?:DRE|license|lic|BRE|MLS)\b[ \t#:.]*[\w-]*", " ", line, flags=re.I)
    line = re.sub(r"\s*[\u2022\u00b7|]\s*", ", ", line)
    line = " ".join(line.split()).strip(" ,;:-")
    if len(line) < 3 or _NOT_AN_AGENT.match(line) or re.search(r"https?://|@", line):
        return ""
    return line[:120]


def _estimated_payment(text: str) -> float | None:
    """What the listing itself estimates per month ("Est. payment $2,310/mo"), or None."""
    m = re.search(r"\b(?:est(?:imated|\.)?\s*(?:monthly\s*)?(?:payment|mortgage)|monthly payment|payment estimate)\s*[:\-]?\s*(?:is\s*)?(?:about |around |from )?\$\s?(\d{1,3}(?:,\d{3})+|\d+)", text, re.I)
    if not m:
        m = re.search(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)\s*(?:/\s*mo(?:nth)?|per month|a month)?\s*(?:est\.?|estimated)\s*(?:payment|mortgage)", text, re.I)
    if not m:
        return None
    value = _num(m.group(1))
    return value if 200 <= value <= 60000 else None


def listing_estimated_payment(text: str) -> float | None:
    """Public: the monthly payment a pasted listing quotes for itself, or None. Never raises."""
    try:
        return _estimated_payment(_tidy(text or ""))
    except Exception:
        return None


_UTILITY_WORDS = ("water", "sewer", "trash", "gas", "electric", "heat", "internet", "wifi", "cable", "hot water")


_PAYS_BEFORE = re.compile(r"\b(?:tenants?|residents?|renters?|lessees?|you|guests?|occupants?)\s*(?:pays?|are responsible|is responsible|responsible|will pay|must pay|to pay|covers?|handles?)\b"
                          r"|\bat (?:your|the tenant'?s?|the resident'?s?|tenant'?s?|resident'?s?) (?:own )?expense\b|\bin (?:your|the tenant'?s?|the resident'?s?) name\b", re.I)
_NOT_AFTER = re.compile(r"\b(?:not included|not covered|not paid|not provided|not part of|excluded|extra|separate(?:ly)?|billed|additional|"
                        r"your own|set up (?:in|with)|not available)\b", re.I)
_YES_MARK = re.compile(r"\b(?:included|paid|covered|provided)\b")


def _drop_not_included(low: str) -> str:
    """Remove what the listing says is NOT part of the rent ("tenant pays electric, internet", "gas not included") so only
    what it says is included is left to read."""
    out: list[str] = []
    for clause in re.split(r"\n|;|\.(?=\s|$)", low):
        m = _PAYS_BEFORE.search(clause)
        if m:
            clause = clause[:m.start()]
        else:
            m = _NOT_AFTER.search(clause)
            if m:
                head = clause[:m.start()]
                ys = list(_YES_MARK.finditer(head))
                clause = head[:ys[-1].end()] if ys else ""
        out.append(clause)
    return "\n".join(out)


def _utilities(text: str) -> str:
    low = text.lower()
    if re.search(r"\b(?:no|not|excluding|plus|\+)\s*(?:all\s+)?utilities\b|\butilities\s*(?:are\s*)?(?:not included|extra|separate|not covered|excluded)|\btenant pays (?:all )?(?:the )?utilities|\bresident pays (?:all )?utilities", low) \
            and not re.search(r"\ball utilities (?:are )?(?:included|paid)", low):
        low = re.sub(r"\b(?:no|not|excluding|plus|\+)\s*(?:all\s+)?utilities\b", " ", low)
    low = _drop_not_included(low)
    lab = re.search(r"\b(?:utilities included|included utilities|rent includes|includes)\s*[:\-]\s*([^\n.;]{0,60})", low)
    if lab and not re.match(r"\s*(?:all|yes|everything)\b", lab.group(1)):
        words_re = "|".join(re.escape(w) for w in _UTILITY_WORDS) + "|trash removal|garbage|sewage|electricity"
        listed = re.findall(words_re, lab.group(1))
        if listed:
            return _ordered_utilities(listed)
    if re.search(r"\ball[- ]utilities[- ](?:are[- ])?(?:included|paid|covered)|\butilities (?:are )?all included|\ball[- ]inclusive|\ball bills (?:paid|included)|\bincludes all utilities|\butilities (?:are )?(?:included|paid)\b(?! (?:for|in) )|\bincluded utilities\s*[:\-]\s*all", low) \
            and not re.search(r"\butilities\s*[:\-]?\s*(?:not|excluded)", low):
        return "all utilities included"
    if re.search(r"\b(?:all )?utilities\s*(?:are )?included\s+in\s+(?:the\s+)?(?:rent|lease|price|monthly)\b|\butilities\s*:\s*(?:all\s+)?(?:included|paid)\b", low):
        return "all utilities included"
    found: list[str] = []
    words = "|".join(re.escape(w) for w in _UTILITY_WORDS) + "|hot water|trash removal|garbage|sewage|electricity"
    for m in re.finditer(r"\b(?:rent |lease |monthly rent )?includes?\s+((?:(?:" + words + r")\s*(?:,|/|&|and|\+)?\s*(?:and\s+)?){1,6})(?!\s*(?:fee|charge|deposit|\$))", low):
        found += re.findall(words, m.group(1))
    for m in re.finditer(r"((?:(?:" + words + r")\s*(?:,|/|&|and|\+)?\s*(?:and\s+)?){1,6})\s*(?:(?:is|are)\s*)?(?:all\s*)?(?:included|paid|covered|provided)\b", low):
        found += re.findall(words, m.group(1))
    for m in re.finditer(r"\b(?:utilities included|included utilities|rent includes|includes|utilities)\s*[:\-]\s*([^\n.;]{0,60})", low):
        found += re.findall(words, m.group(1))
    for m in re.finditer(r"\b(?:landlord|owner|management|property manager)\s+(?:pays?|covers?)\s+(?:for\s+)?((?:(?:" + words + r")\s*(?:,|/|&|and|\+)?\s*(?:and\s+)?){1,6})", low):
        found += re.findall(words, m.group(1))
    return _ordered_utilities(found) if found else ""


def _tenant_pays(text: str) -> str:
    """"Tenant pays gas, electric" from "Tenant pays gas and electric" (utilities the listing says the renter pays), or ''."""
    low = text.lower()
    words = "|".join(re.escape(w) for w in _UTILITY_WORDS) + "|electricity|garbage|trash removal|sewage"
    found: list[str] = []
    for clause in re.split(r"\n|;|\.(?=\s|$)", low):
        m = re.search(r"\b(?:tenants?|residents?|renters?|lessees?|you)\s*(?:pays?|are responsible for|is responsible for|responsible for|will pay|must pay|to pay)\b\s*(?:for\s+)?(?:all\s+)?(?:the\s+)?(.*)", clause)
        if not m:
            continue
        rest = m.group(1)
        found += re.findall(r"\b(?:" + words + r")\b", rest)
    return _ordered_utilities(found) if found else ""


def _tenant_pays_choices(pays: str) -> str:
    """The renter-pays words as the store's fixed list (electric, gas, water, trash, internet, heat), in that order."""
    words = {w.strip() for w in pays.split(",")}
    words = {"internet" if w in ("wifi", "cable") else "water" if w in ("hot water", "sewer") else w for w in words}
    return ", ".join(w for w in ("electric", "gas", "water", "trash", "internet", "heat") if w in words)


def _ordered_utilities(found: list[str]) -> str:
    norm = {"garbage": "trash", "trash removal": "trash", "sewage": "sewer", "electricity": "electric"}
    ordered: list[str] = []
    for w in found:
        w = norm.get(w, w)
        if w == "hot water" and "water" in ordered:
            continue
        if w not in ordered:
            ordered.append(w)
    return ", ".join(ordered)


def _read_date(m: re.Match[str], today: date) -> str | None:
    try:
        if m.group("iso"):
            return date(int(m.group("iso")[:4]), int(m.group("iso")[5:7]), int(m.group("iso")[8:10])).isoformat()
        if m.group("mdy"):
            parts = re.split(r"[/.-]", m.group("mdy"))
            mo, d, y = parts[0], parts[1], (parts[2] if len(parts) > 2 else "")
            if y:
                y = int(y) + (2000 if int(y) < 100 else 0)
                return date(y, int(mo), int(d)).isoformat()
            dt = date(today.year, int(mo), int(d))
            return (dt if dt >= today else date(today.year + 1, dt.month, dt.day)).isoformat()
        month = _MONTHS[m.group("mon")[:3].lower()]
        day = int(m.group("day"))
        if m.group("year"):
            return date(int(m.group("year")), month, day).isoformat()
        dt = date(today.year, month, day)
        return (dt if dt >= today else date(today.year + 1, month, day)).isoformat()
    except (ValueError, KeyError, TypeError):
        return None


_DATE = (r"(?:(?P<iso>\d{4}-\d{2}-\d{2})|(?P<mdy>\d{1,2}[/.-]\d{1,2}(?:[/.-](?:\d{4}|\d{2}))?)|"
         r"(?P<mon>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?\s+"
         r"(?P<day>\d{1,2})(?:st|nd|rd|th)?(?:,?\s*(?P<year>\d{4}))?)")


def _available(text: str) -> str | None:
    today = _today()
    low = text.lower()
    m = re.search(r"\b(?:date available|availability|available(?: from| on| starting| beginning)?|avail\.?|move[- ]?in(?: date)?|ready (?:for move[- ]in )?(?:on|by)|lease start(?:s| date)?)\b[ \t:\-]{0,6}(?:on |for |by |starting |beginning )?" + _DATE, low)
    if m:
        return _read_date(m, today)
    m = re.search(r"\b(?:available|avail\.?)\s*(?:for\s+)?" + _DATE + r"\s*(?:move[- ]?in|lease)", low)
    if m:
        return _read_date(m, today)
    if re.search(r"\bavailable\s*(?:now|immediately|today)\b|\bavailability\s*[:\-]\s*(?:now|immediate)|\bmove[- ]in ready\b|\bimmediate(?:ly)? (?:move[- ]in|available)", low):
        return today.isoformat()
    return None


def _lease_months(text: str) -> int | None:
    low = text.lower()
    for pat in (r"(?<![\d,-])(\d{1,2})[- ](?:month|mo\b)[- ]?(?:minimum |min\.? )?(?:lease|term|contract)",
                r"\b(?:lease|term|contract)s?(?: terms?| length| duration| options?)?\s*[:\-]?\s*(?:of |is |are )?(?<![-,\d] )(\d{1,2})\s*(?:months?|mos?\b)(?!\s*(?:,|and|or|/|to|-)\s*\d)",
                r"\b(\d{1,2})\s*months?\s+(?:lease|minimum|min\b)", r"\b(one|1)[- ]year (?:lease|term|contract)"):
        m = re.search(pat, low)
        if m:
            g = m.group(1)
            n = 12 if g in ("one", "1") and "year" in m.group(0) else int(g)
            if 1 <= n <= 60 and not re.search(r"\d\s*(?:,|-|to|or)\s*$", low[max(0, m.start() - 6):m.start()]):
                return n
    return None


def _year_built(text: str) -> int | None:
    low = text.lower()
    for pat in (r"\b(?:year built|built in|built|constructed in|construction (?:year|completed)|completed in|opened in)\s*[:\-]?\s*((?:18|19|20)\d{2})\b",
                r"\b((?:18|19|20)\d{2})\s+(?:construction|built)\b"):
        m = re.search(pat, low)
        if m:
            y = int(m.group(1))
            if 1800 <= y <= _today().year + 3:
                return y
    return None


def _periodic(text: str, label: str, yearly_default: bool) -> float | None:
    """An amount like "HOA $250/mo" or "Taxes $4,200/yr" as a monthly (``yearly_default`` False) or yearly figure."""
    m = re.search(r"(?:" + label + r")(?:\s*(?:fee|fees|dues|amount|annual amount|monthly|annually))*[ \t:\-=]{0,6}\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?\s*(/\s*\w+|per\s+\w+|\w+ly|annual\w*)?", text, re.I)
    if not m:
        m2 = re.search(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?\s*(/\s*\w+|per\s+\w+|\w+ly|annual\w*)?\s*(?:" + label + r")\b", text, re.I)
        m = m2
    if not m:
        return None
    value = _num(m.group(1))
    per = (m.group(2) or "").lower()
    monthly = bool(re.search(r"mo|month", per))
    yearly = bool(re.search(r"yr|year|annual", per))
    quarterly = "quarter" in per
    value_month = value if monthly else (value / 12 if yearly else (value / 3 if quarterly else None))
    if value_month is None:
        value_month = value / 12 if yearly_default else value
    return round(value_month * 12, 2) if yearly_default else round(value_month, 2)


def _hoa(text: str) -> float | None:
    m = re.search(r"(?:hoa|association|homeowners'? association|condo)(?:\s*(?:fee|fees|dues|payment))*[ \t:\-=]{0,6}\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?\s*(/\s*\w+|per\s+\w+|\w+ly|annual\w*)?", text, re.I)
    if not m:
        m = re.search(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?\s*(/\s*\w+|per\s+\w+|\w+ly|annual\w*)?\s*(?:hoa|association) (?:fee|dues)?", text, re.I)
    if not m:
        return None
    value, per = _num(m.group(1)), (m.group(2) or "").lower()
    if re.search(r"yr|year|annual", per):
        value /= 12
    elif "quarter" in per:
        value /= 3
    return round(value, 2) if 0 < value < 5000 else (0.0 if value == 0 else None)


def _tax(text: str) -> float | None:
    m = re.search(r"\b(?:property )?tax(?:es)?(?:\s+annual amount|\s+paid|\s+\(annual\))?[ \t:\-=]{0,6}\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?\s*(/\s*\w+|per\s+\w+|\w+ly|annual\w*)?", text, re.I)
    if not m:
        return None
    value, per = _num(m.group(1)), (m.group(2) or "").lower()
    if re.search(r"mo|month", per):
        value *= 12
    return round(value, 2) if 100 <= value <= 200000 else None


# --------------------------------------------------------------------------- address
def _address(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in _ADDRESS.finditer(text):
        street = " ".join(m.group(1).split()).rstrip(",.")
        words = {w.lower().strip(".,") for w in street.split()[1:-1]}
        if words & _NOT_STREET_WORDS:
            continue
        out["address"] = street
        if m.group(2):
            out["unit"] = m.group(2)
        tail = text[m.end():m.end() + 120]
        cm = re.match(r"[ \t]*(?:,|\n)?[ \t]*(?:" + _UNIT + r"[ \t]*(?:,|\n)?[ \t]*)?([A-Z][A-Za-z.'-]+(?: [A-Z][A-Za-z.'-]+){0,3}),?[ \t]+([A-Z]{2})(?:[ \t]+(\d{5})(?:-\d{4})?)?\b", tail)
        if cm and cm.group(3) in _STATES:
            if cm.group(1) and not out.get("unit"):
                out["unit"] = cm.group(1)
            out["city"], out["state"] = cm.group(2), cm.group(3)
            if cm.group(4):
                out["zip"] = cm.group(4)
        break
    if "city" not in out:
        for m in _CITY_LINE.finditer(text):
            if m.group(2) in _STATES:
                out["city"], out["state"], out["zip"] = m.group(1), m.group(2), m.group(3)
                break
    if "city" not in out:
        label = re.search(r"\b(?:location|city|area|neighborhood)\s*[:\-]\s*", text, re.I)
        scan = text[label.end():label.end() + 80] if label else text
        for m in _CITY_STATE.finditer(scan):
            if m.group(2) in _STATES and not re.match(r"(?:Rent|Price|Beds?|Baths?|Bed|Bath|Sq|Unit|Apt)$", m.group(1)):
                out["city"], out["state"] = m.group(1), m.group(2)
                break
    if "address" in out and "unit" not in out:
        um = re.search(r"(?<![\w-])" + _UNIT, text[max(0, text.find(out["address"])):][:300], re.I)
        if um and not re.match(r"[A-Z]$", um.group(1)):
            out["unit"] = um.group(1)
    return out


# --------------------------------------------------------------------------- title
_UI_WORDS = {"save", "share", "contact", "back", "home", "menu", "photos", "show more", "request a tour", "floor plans", "overview",
             "facts and features", "description", "listed by", "apply now", "call", "email", "message", "tour", "favorite",
             "back to search", "back to results", "sign in", "log in", "skip to content", "report", "hide", "more", "close",
             "details", "map", "schedule a tour", "see more", "get directions", "nearby schools", "price history", "x", "copy link",
             "send message", "is this still available?", "marketplace", "notifications", "home / rentals", "rentals",
             "skip to main content", "skip to content", "skip to main", "advertisement", "sponsored", "view photos", "all photos"}


def _is_fact_line(line: str) -> bool:
    stripped = re.sub(r"\$\s?[\d,.]+[kK]?|\d+(?:\.\d)?\s*(?:-\s*\d+\s*)?(?:bed(?:room)?s?|bds?|brs?|bath(?:room)?s?|bths?|ba|sq\.?\s?ft\.?|sqft|sf|ft2|mo|month|/mo|studio)\b|"
                      r"[\d,.]+|/\s*mo|\bstudio\b|\bfor rent\b|\bfor sale\b|\bavailable\b|\bnow\b|\bacres?\b|\blot\b|\bfull\b|\bhalf\b|"
                      r"\bpartial\b|\bprice\b|\bsingle family\b|\bstarting at\b|\bfrom\b|\bsquare\b|\bfeet\b|\bfoot\b|\bbeds?\b|"
                      r"\bbaths?\b|\brent\b|\bdeposit\b|\bbedrooms?\b|\bbathrooms?\b|\bsize\b|\bbuilt\b|\byear\b", " ", line, flags=re.I)
    words = re.findall(r"[A-Za-z]{3,}", stripped)
    return len(words) <= 1


_SITE_LINE = re.compile(r"^(?:zillow|realtor\.com|apartments\.com|trulia|redfin|craigslist|facebook(?: marketplace)?|hotpads|zumper|rent\.com|"
                        r"apartment ?list|padmapper|streeteasy|homes\.com|loopnet|forrent|apartmentguide|marketplace|mls)\b[^a-z]{0,3}(?:\w{0,12})?[^\n]{0,40}$", re.I)
_BUILDING = re.compile(
    r"^(?:Welcome to |Introducing |Presenting )?((?:The\s+)?(?:[A-Z][\w'&.-]*\s+){0,4}?"
    r"(?:Apartments?|Apts?|Lofts?|Court|Flats|Residences|Residence|Towers?|Commons|Villas?|Terrace|Manor|Gardens|Village|Place|Square|Townhomes?|Townhouses|Condos?|Heights|Landing|Crossing|Park)\b"
    r"(?:\s+(?:Apartments?|Apts?|Homes|Flats|Residences|Townhomes?|Condos?)\b)?"
    r"(?:\s+(?:at|on|of)\s+[A-Z][\w'&.-]*(?:\s+[A-Z][\w'&.-]*){0,3})?"
    r"|The\s+[A-Z][\w'&.-]*(?:\s+(?:at|on)\s+[A-Z][\w'&.-]*(?:\s+[A-Z][\w'&.-]*){0,3}))", re.U)


_BUILDING_WORD = (r"(?:Apartments?|Apts?|Lofts?|Court|Flats|Residences?|Towers?|Commons|Villas?|Terrace|Manor|Gardens|Village|Place|Square|"
                  r"Townhomes?|Townhouses|Condos?|Heights|Landing|Crossing|Park|Pointe?|Station|Lofts|Oaks|Woods|Ridge|Hills|Reserve|Club)")
_AT_BUILDING = re.compile(r"\b(?:at|in)\s+((?:The\s+)?(?:[A-Z][\w'&.-]*\s+){0,3}" + _BUILDING_WORD + r"\b(?:\s+(?:Apartments?|Homes|Flats|Residences|Townhomes?|Condos?)\b)?)")


def _building_name(text: str) -> str:
    for line in text.splitlines()[:30]:
        line = " ".join(line.strip(" \t|\u2022\u00b7*#").split())
        if not line or len(line) > 90 or _SITE_LINE.match(line):
            continue
        m = _BUILDING.match(line) or _AT_BUILDING.search(line)
        if m:
            name = m.group(1).strip()
            if len(name) >= 6 and not re.match(r"(?:The\s+)?(?:Apartments?|Court|Place|Park|Square)$", name):
                return name
    return ""


def _title(text: str, found: dict[str, Any]) -> str:
    """A short title: the building name, else the first line of the paste that reads like a name or heading, else the street
    address. A site name (Zillow, Realtor.com) is never the title."""
    building = _building_name(text)
    if building:
        return building
    for line in text.splitlines()[:25]:
        line = " ".join(line.strip(" \t|\u2022\u00b7*#").split())
        if not line:
            continue
        low = line.lower().rstrip(":")
        if not 4 <= len(line) <= 90 or low in _UI_WORDS or line.startswith(("http", "$", "www.", "Skip to")) or _SITE_LINE.match(line):
            continue
        am = _ADDRESS.match(line)
        if am and found.get("address"):
            return found["address"]
        if re.fullmatch(r"[\d\s$,./\-+:()]+", line) or _is_fact_line(line):
            continue
        if re.search(r"\b(?:call|text|email|contact|apply|posted|updated|listed|published)\b.*(?:\d{3}|ago|on\b)", low):
            continue
        if re.fullmatch(r"[A-Za-z .'-]+,\s*[A-Z]{2}(?:\s+\d{5})?", line):  # just "Champaign, IL"
            continue
        return re.split(r"(?<=[a-z])[.!]\s", line)[0]
    addr = found.get("address", "")
    return addr.split(",")[0] if addr else ""


# --------------------------------------------------------------------------- the entry point
def _try(fn: Callable[[], Any]) -> Any:
    try:
        return fn()
    except Exception:  # a field it can't read is simply left out
        return None


def parse_listing(text: str = "", url: str = "") -> dict[str, Any]:
    """Pull what a pasted listing says. Returns only the fields found."""
    text = _tidy(text or "")
    out: dict[str, Any] = {}
    src = site_name(url)
    if not src and text:
        low = text.lower()
        for pat, name in _TEXT_SITES:
            if re.search(pat, low):
                src = name
                break
    if src:
        out["source"] = src
    if not text.strip():
        return out

    def put(key: str, value: Any, *, keep_zero: bool = True) -> None:
        if value is None or value == "" or (not keep_zero and value == 0):
            return
        out[key] = _tidy_number(value) if isinstance(value, float) else value

    put("price", _try(lambda: _price(text)))
    put("beds", _try(lambda: _beds(text)))
    put("baths", _try(lambda: _baths(text)))
    put("sqft", _try(lambda: _sqft(text)))
    facts: list[str] = []
    laundry = _try(lambda: _laundry(text))
    if laundry == "hookups":
        from .store import LAUNDRY_VALUES  # a value the store doesn't hold yet is shown as a plain line instead
        if "hookups" in LAUNDRY_VALUES:
            put("laundry", laundry)
        else:
            facts.append("Washer and dryer hookups only (you bring the machines).")
    else:
        put("laundry", laundry)
    put("dishwasher", _try(lambda: _dishwasher(text)))
    kind_cost = _try(lambda: _parking(text)) or ("", None)
    put("parking", kind_cost[0])
    put("parking_cost", kind_cost[1])
    put("pets", _try(lambda: _pets(text)))
    deposit_amount, fee_text = _try(lambda: _pet_deposit(text)) or (None, text)
    put("pet_deposit", deposit_amount)
    for key, value in (_try(lambda: _pet_fees(fee_text)) or {}).items():
        put(key, value)
    side, dep_text = _try(lambda: _pet_side_deposits(fee_text, out.get("price") if isinstance(out.get("price"), (int, float)) else None)) or ({}, fee_text)
    for key, value in side.items():
        if key not in out and not (key == "pet_fee" and "pet_fee" in out):
            put(key, value)
    for key, value in (_try(lambda: _pet_limit_fields(text)) or {}).items():
        put(key, value)
    put("utilities_included", _try(lambda: _utilities(text)))
    pays = _try(lambda: _tenant_pays(text))
    if pays:
        # Nothing is included for these, so the monthly cost keeps its own estimate line (a guess), and the listing's words are kept.
        facts.append(f"Tenant pays {pays}.")
        mapped = _tenant_pays_choices(pays)
        if mapped:
            put("tenant_pays", mapped)
    put("available_from", _try(lambda: _available(text)))
    put("lease_months", _try(lambda: _lease_months(text)))
    put("year_built", _try(lambda: _year_built(text)))
    facts += [f"{line.rstrip('.')}." for line in (_try(lambda: _pet_limits(text)) or [])]

    def fees() -> None:
        dep = _money_after(dep_text, r"(?:security |refundable |damage |rental )?deposits?", hi=50000, skip_before=r"(?:pet|parking|holding|reservation|key|application|garage)\s*$")
        dep = [v for v in dep if v is not None]
        rent_now = out.get("price")
        by_months = _deposit_in_months(text)
        if dep:
            put("deposit", dep[0])
        elif by_months and isinstance(rent_now, (int, float)) and 200 <= rent_now <= 30000 and not _SALE_WORDS.search(text):
            put("deposit", by_months * float(rent_now))  # "security deposit one month", "deposit equal to one month's rent"
        elif re.search(r"\b(?:no|zero|\$0) (?:security )?deposit|\bdeposit\s*[:\-]?\s*(?:\$0|none|waived|zero)\b", text, re.I):
            put("deposit", 0.0)
        app = _money_after(text, r"application(?: processing)? fees?|app(?:lication)? fee|screening fee|background check fee", hi=1000)
        if app:
            put("application_fee", app[0])
        elif re.search(r"\b(?:no|free|zero|\$0|waived)\s+application (?:fee|processing)|\bapplication fee\s*[:\-]?\s*(?:\$0|none|waived|free)\b", text, re.I):
            put("application_fee", 0.0)
        mi = _money_after(text, r"(?:admin(?:istrative|istration)?|move[- ]in|lease[- ](?:signing|initiation|admin)|processing|community|one[- ]time) fees?", hi=5000)
        if mi:
            put("move_in_fees", sum(dict.fromkeys(mi).keys()) if len(mi) > 1 else mi[0])
        br = _money_after(text, r"broker(?:'?s)? fee|agent(?:'?s)? fee|finder'?s fee", hi=20000)
        if br:
            put("broker_fee", br[0])
        monthly = 0.0
        for v in dict.fromkeys(_money_monthly_fees(text)):
            monthly += v
        if monthly:
            put("other_monthly_fees", monthly)
        months, with_deposit = _try(lambda: _move_in_months(text)) or (0, False)
        rent = out.get("price")
        first_last = months
        if _three_months_up_front(text):
            months = 3  # only when the listing really says three months of rent are due before move-in
        if months and not _SALE_WORDS.search(text):
            put("months_up_front", months)
        if first_last and isinstance(rent, (int, float)) and 200 <= rent <= 30000 and not _SALE_WORDS.search(text):
            # First and last month are cash due at move-in, not a fee: money.cash_at_move_in shows them apart.
            line = f"First and last month's rent (${first_last * float(rent):,.0f}) are due at move-in"
            if with_deposit:
                line += ", plus a deposit" + ("." if out.get("deposit") else " (the listing gives no amount).")
            else:
                line += "."
            facts.append(line)
        per_person = _try(lambda: _app_fee_per_person(text))
        if per_person:
            facts.append(per_person)
        insurance = _try(lambda: _insurance(text))
        if insurance is not None:
            put("insurance", insurance)
        assessment = _try(lambda: _special_assessment(text))
        if assessment:
            facts.append(assessment)
        amount, payer, _sentence = _try(lambda: _special_assessment_facts(text)) or (None, "", "")
        if amount:
            put("special_assessment", amount)
            if payer:
                put("special_assessment_payer", payer)
        dom = _try(lambda: _days_on_market(text))
        if dom is not None:
            put("days_on_market", dom)
        agent = _try(lambda: _listing_agent(text))
        if agent:
            put("listing_agent", agent)
        est = _try(lambda: _estimated_payment(text))
        if est:
            facts.append(f"The listing estimates the payment at ${est:,.0f}/mo.")
        closing = _try(lambda: _closing_costs(text))
        if closing:
            put("closing_costs", closing)
        cut = _try(lambda: _price_cut(text))
        if cut:
            facts.append(f"Price reduced ${cut:,.0f}.")
        hoa = _try(lambda: _hoa(text))
        if hoa is not None:
            put("hoa", hoa)
        tax = _try(lambda: _tax(text))
        if tax is not None:
            put("property_tax", tax)

    _try(fees)
    for key, value in (_try(lambda: _address(text)) or {}).items():
        put(key, value)
    title = _try(lambda: _title(text, out))
    if title:
        out["title"] = title
    if facts:
        out["found_in_listing"] = " ".join(facts)
    return out


def _money_monthly_fees(text: str) -> list[float]:
    """Required extras charged every month ("amenity fee $25/mo", "$10/month trash")."""
    found: list[float] = []
    label = r"(?:amenity|trash|valet trash|pest(?: control)?|package|technology|tech|community|convenience|internet|cable|smart home)(?:\s*(?:fee|fees|charge|package|service))?"
    for m in re.finditer(r"\b" + label + r"[ \t:\-=]{0,4}\$\s?(\d{1,4})(?:\.\d\d)?\s*(?:/\s*mo(?:nth)?|per month|monthly|a month)", text, re.I):
        found.append(float(m.group(1)))
    for m in re.finditer(r"\$\s?(\d{1,4})(?:\.\d\d)?\s*(?:/\s*mo(?:nth)?|per month|monthly|a month)\s*(?:for\s+)?" + label + r"\b", text, re.I):
        found.append(float(m.group(1)))
    return found
