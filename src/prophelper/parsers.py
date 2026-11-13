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
           r"ter|terrace|trl|trail|hwy|highway|loop|plaza|pike|(?:row|walk|alley|path|mews)(?![ \t]+(?:ln|lane|st|street|ave|avenue|rd|road|dr|drive|blvd|boulevard|ct|court|pl|place|way|cir|circle|ter|terrace|trl|trail|pkwy|parkway)\b)|sq(?=\.?,|\.?[ \t]+(?:unit|apt|apartment|suite|ste|#))|square(?=\b,))")
_NOT_STREET_WORDS = {"bed", "beds", "bedroom", "bedrooms", "bath", "baths", "bathroom", "bathrooms", "br", "ba", "bd", "bds", "sq",
                     "ft", "sqft", "month", "mo", "year", "years", "min", "minute", "minutes", "mile", "miles", "unit", "units",
                     "floor", "floors", "car", "cars", "pet", "pets", "story", "stories", "block", "blocks", "min."}
_UNIT = r"(?:#|apt\.?|apartment|unit|suite|ste\.?)\s*#?\s*([A-Za-z]?\d{1,5}[A-Za-z]?(?:-\d{1,3})?|[NS][EW]\b|[A-Z])\b"
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
        r"assessment\w*|contribut\w*|seller")
_FEE_BEFORE = re.compile(r"\b(?:" + _FEE + r")", re.I)
_MONTHLY = r"(?:/\s*|per\s+|a\s+|each\s+|every\s+)?(?:mo\b|mos\b|month\b|months\b|monthly\b|mth\b)"
_RENT_MARK = re.compile(r"^\s*\+?\s*(?:" + _MONTHLY + r"|/\s*(?:unit|apt)\b)", re.I)
_BR_MARK = re.compile(r"^\s*/\s*(?:\d\s*(?:br|bd|bed)|studio)", re.I)  # Craigslist: "$1100 / 1br - 700ft2"
_PER_BED = re.compile(r"^\s*\+?\s*(?:/|per)\s*(?:bed|bedroom|person|resident|tenant|student)", re.I)
_FEE_AFTER_STRICT = re.compile(r"^\s*\+?\s*(?:one[- ]time\s+|non[- ]refundable\s+|refundable\s+|monthly\s+|price\s+)?(?:" + _FEE + r")", re.I)
_FEE_AFTER_MONTHLY = re.compile(r"^\s*\+?\s*(?:" + _MONTHLY + r")?\s*(?:for\s+|per\s+|-\s*)?(?:pet|parking|garage|storage|utilit|hoa|trash|"
                                r"internet|cable|amenity|water|insurance|lawn|cleaning|reserved|covered|tax|assessment)(?![a-z]*[ \t]*(?:is[ \t]+|are[ \t]+)?(?:not[ \t]+)?(?:incl\b|included|extra\b|separate))", re.I)
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
        if fee and value >= 20000 and marker == "" and re.match(r"^\s*(?:hoa|assoc\w*|dues|condo fee)", tail, re.I):
            fee = False  # "$250,000 HOA $310 per month": the HOA label belongs to the next amount, no HOA fee is that big
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
    for m in re.finditer(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?[ \t]*(?:/[ \t]*mo(?:nth)?[ \t]*)?(?:one[- ]time |non[- ]refundable |refundable )?(?:" + label + r")(?![ \t]*[:=]|[ \t]*\d(?:\.\d+)?[ \t]*(?:x|times|months?)\b)", text, re.I):
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
    for m in re.finditer(r"\b(?:bath(?:room)?s?)\b[ \t]+(\d{1,2}(?:\.\d)?)\b(?![ \t]*(?:sq|sf|ft|\$|/|%|\d|min|mi\b|blocks?|years?|yr|bed|bd|br))", low):
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


def _parking_kind_words(low: str) -> str:
    """The parking type from the words around a parking price ("covered spot", "surface lot", "street permit")."""
    if re.search(r"\bgarage\b(?! door)", low):
        return "garage"
    if re.search(r"\bcarports?\b|\bcovered\b", low):
        return "covered"
    if re.search(r"\b(?:surface|off[- ]?street|assigned|reserved|paved|gravel|on[- ]?site)\b|\blot\b", low):
        return "lot"
    if re.search(r"\bstreet\b", low):
        return "street"
    return ""


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
    elif re.search(r"\b(?:off[- ]?street|surface|free|assigned|reserved|on[- ]?site|private|ample|plenty of|paved|resident)\s+parking\b|\b(?:surface|gravel|paved|resident|tenant)?\s*lot\s+parking\b|\bparking\s+(?:lot|included|available|space|spot|provided|on[- ]?site)|\bdriveway\b|\bparking\s*[:\-]\s*(?:lot|yes|included|free|assigned|surface)|\b\d\s*parking (?:spaces?|spots?)\b", low):
        kind = "lot"
    elif re.search(r"\b(?:street|on[- ]street)\s+parking\b|\bparking\s*[:\-]\s*street\b", low):
        kind = "street"
    elif re.search(r"\bno\s+(?:off[- ]?street\s+|on[- ]?site\s+)?parking\b|\bparking\s*[:\-]\s*none\b", low):
        kind = "none"
    cost: float | None = None
    m = re.search(r"(?:garage|carport|covered parking|reserved parking|parking(?: fee| rate| cost)?|parking space|parking spot)s?\s*(?:space|spot|stall|fee|rental|rent)?s?[ \t:\-=(]{0,6}(?:is |are |from |starting at |for |at |only )?\$\s?(\d{2,4})(?:\.\d\d)?\b(?!\s*(?:deposit|one[- ]time|setup|set-up|/\s*\d\s*(?:br|bd|bed)))", low)
    if not m:
        # "Parking: assigned covered spot $60/mo", "garage parking available for $110 a month": a few describing words in between
        m = re.search(r"\b(?:garage|carport|parking)s?\b[ \t:\-=(]{0,4}(?:(?:assigned|reserved|covered|private|underground|heated|attached|detached|surface|lot|street|"
                      r"spots?|spaces?|stalls?|available|offered|for|at|is|are|from|only|each|per|one|a|an|the|rental|rate|fee|cost|\d-car|garage|carport|parking|-)[ \t:]+){1,6}"
                      r"\$\s?(\d{2,4})(?:\.\d\d)?(?=[ \t]*(?:/[ \t]*mo|per[ \t]+month|a[ \t]+month|monthly|each[ \t]+month))(?!\s*(?:deposit|one[- ]time|setup|set-up|/\s*\d\s*(?:br|bd|bed)))", low)
    if m:
        cost = float(m.group(1))
    else:
        m = re.search(r"\$\s?(\d{2,4})\s*(?:/\s*mo(?:nth)?|per month|a month|monthly)?\s*(?:for |per )?(?:a |the )?(?:reserved |covered |garage |private )?(?:parking|garage|carport)\b(?!\s*deposit)", low)
        if m:
            cost = float(m.group(1))
    if cost is not None and not kind:
        kind = _parking_kind_words(low)
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
    no_cats = re.search(r"\bno cats?\b(?!\s+(?:over|above|under|larger|bigger|heavier|exceeding|more))|\bcats? (?:are )?not (?:allowed|permitted|accepted)|\bno cats? allowed", work)
    no_dogs = re.search(r"\bno dogs?\b(?!\s+(?:over|above|under|larger|bigger|heavier|exceeding|more))|\bdogs? (?:are )?not (?:allowed|permitted|accepted)|\bno dogs? allowed", work)
    if re.search(r"\bcats? and dogs?\b|\bdogs? and cats?\b|\bcats?\s*(?:&|/|,)\s*dogs?\b|\bdogs?\s*(?:&|/|,)\s*cats?\b|\bpet[- ]friendly\b|\bpets (?:ok|okay|allowed|welcome|accepted)\b(?!\s+(?:with|by|on|upon|subject to)\s+(?:landlord\s+|owner\s+|management\s+)?(?:approval|permission))|\bpets\s*[:\-]\s*(?:yes|ok|okay|allowed|welcome)\b|\ball pets\b|\bdogs? (?:are )?ok.{0,40}cats? (?:are )?ok|\bcats? (?:are )?ok.{0,40}dogs? (?:are )?ok", work):
        cats = dogs = True
    if re.search(r"\bcats?\b(?:\s*(?:are|is))?\s*(?:ok|okay|fine|allowed|welcome|accepted|friendly|permitted)|\bcats? only\b|\bcat[- ]friendly\b|\bpurrr|\bcats?\s*[:\-]?\s*\$\s?\d", work):
        cats = True  # "Cats $200 deposit": a fee for cats means cats are taken
    if re.search(r"\bdogs?\b(?:\s*(?:are|is))?\s*(?:ok|okay|fine|allowed|welcome|accepted|friendly|permitted)|\bdogs? only\b|\bdog[- ]friendly\b|\bwoof|\bsmall dogs?\b|\bdogs? under\b|\bdogs?\s*[:\-]?\s*\$\s?\d", work):
        dogs = True
    if re.search(r"\bcats?\s+(?:up to|max(?:imum)?(?: of)?|limit(?: of)?)\s+(?:\d|one|two|three|four)\b(?!\d|\s*(?:lbs?|pounds?|years?|yrs?|in\b|inch))", work):
        cats = True  # "Cats up to 2"
    if re.search(r"\bdogs?\s+(?:up to|max(?:imum)?(?: of)?|limit(?: of)?)\s+(?:\d|one|two|three|four)\b(?!\d|\s*(?:lbs?|pounds?|years?|yrs?|in\b|inch))", work):
        dogs = True
    pm = re.search(r"\bpets?\s*[:\-]\s*((?:up to|max(?:imum)?(?: of)?|limit(?: of)?|up to a max of)?\s*(?:\d|one|two|three|four)?\s*(?:dogs?|cats?)\b[^.\n;]{0,40})", work)
    if pm and not re.search(r"\b(?:no|not|none)\b", pm.group(1)):
        cats = cats or bool(re.search(r"\bcats?\b", pm.group(1)))
        dogs = dogs or bool(re.search(r"\bdogs?\b", pm.group(1)))
    # "considered", "case by case" and "with approval" are not a yes: _pets_doubt and _pets_soft_note say so in a note
    if re.search(r"\bcats?\s+(?:are\s+)?negotiable", work):
        cats = True
    if re.search(r"\bdogs?\s+(?:are\s+)?negotiable", work):
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


_NO_PETS_CLAUSE = re.compile(r"\bno pets\b(?!\s+(?:restrictions?|limits?|problem|fee))[^.\n;]*|\bpets (?:are )?not (?:allowed|permitted|accepted)[^.\n;]*|"
                             r"\bnot pet[- ]friendly\b|\bpets\s*[:\-]\s*(?:no\b|none|not allowed)[^.\n;]*|\bpet policy\s*[:\-]\s*no\b[^.\n;]*|\bno animals\b[^.\n;]*", re.I)
_NO_SPECIES = re.compile(r"\bno\s+(cats?|dogs?)\b(?!\s+(?:over|above|under|larger|bigger|heavier|exceeding|more|breeds?))|\b(cats?|dogs?)\s+(?:are\s+)?not\s+(?:allowed|permitted|accepted)", re.I)
_HARD_APPROVAL = (r"(?:(?:with|by|on|upon|subject to|needs?|requires?|required)\s+(?:prior\s+)?(?:written\s+)?(?:landlord\s+|owner\s+|management\s+)?(?:approval|permission)"
                  r"|(?:approval|permission)\s+(?:is\s+)?(?:required|needed))")
_SOFT_APPROVAL = r"(?:considered|negotiable|case[- ]by[- ]case)"
_MAYBE_PETS = re.compile(r"\b(cats?|dogs?|pets?|animals?)\b[^.\n;,?!]{0,25}?\b(?:" + _SOFT_APPROVAL + "|" + _HARD_APPROVAL + ")", re.I)
_HARD_ONLY = re.compile(r"\b(?:cats?|dogs?|pets?|animals?)\b[^.\n;,?!]{0,25}?\b" + _HARD_APPROVAL, re.I)
_APPROVAL_ONLY = re.compile(r"\b(?:cats?|dogs?|pets?|animals?)\b[^.\n;,?!]{0,25}?\b(?:case[- ]by[- ]case|" + _HARD_APPROVAL + ")", re.I)
_SPECIES = ("cats", "dogs")


def _pet_stances(text: str) -> tuple[dict[str, set[str]], list[str]]:
    """What each piece of the listing says about cats and dogs: {"cats": {"yes", "no", "maybe"}, "dogs": ...}, plus the
    pieces that said something about pets (for quoting). A piece is a sentence or a part of one split at a comma."""
    stances: dict[str, set[str]] = {"cats": set(), "dogs": set()}
    quoted: list[str] = []
    for sentence in re.split(r"[.;\n?!]+", text):
        for piece in re.split(r",", sentence):
            piece = " ".join(piece.split())
            if not piece or not re.search(r"\b(?:pets?|cats?|dogs?|animals?)\b", piece, re.I):
                continue
            says: dict[str, str] = {}
            base = _pets(piece)
            if base == "none":
                says = {"cats": "no", "dogs": "no"}
            elif base:
                for sp in _SPECIES:
                    if base in ("both", sp):
                        says[sp] = "yes"
            for m in _NO_SPECIES.finditer(piece):
                says[(m.group(1) or m.group(2)).lower().rstrip("s") + "s"] = "no"
            for m in _MAYBE_PETS.finditer(piece):
                word = m.group(1).lower().rstrip("s")
                hard = bool(re.search(_HARD_APPROVAL, m.group(0), re.I))
                for sp in (_SPECIES if word in ("pet", "animal") else (word + "s",)):
                    if says.get(sp) != "no":
                        says[sp] = "appr" if hard else ("maybe" if says.get(sp) != "appr" else "appr")
            if says:
                quoted.append(piece.strip(" -:"))
                for sp, v in says.items():
                    stances[sp].add(v)
    return stances, quoted


def _ask_who(text: str) -> str:
    """Who to ask about the pet rule: the landlord for a rental, the seller or listing agent for a home for sale."""
    return "the seller or listing agent" if _SALE_WORDS.search(text) else "the landlord"


def _quoted_pieces(quoted: list[str]) -> str:
    seen: list[str] = []
    for q in quoted:
        if q.lower() not in [x.lower() for x in seen]:
            seen.append(q)
    return ", then ".join(f'"{q[:60]}"' for q in seen[:4])


def _pets_doubt(text: str) -> str:
    """A plain sentence when the listing contradicts itself about pets ("Pets: dogs ok. Pets: no pets allowed.", "Dogs ok, no cats
    allowed? Cats considered with approval.") or leaves it to the landlord's approval ("Cats ok. Dogs need approval."), else "".
    Then pets is left unknown."""
    stances, quoted = _pet_stances(text)
    clash = any("no" in v and (v & {"yes", "maybe", "appr"}) for v in stances.values())
    approval = False
    if not clash and not any("no" in v for v in stances.values()):
        if any("appr" in v for v in stances.values()) or _HARD_ONLY.search(text):
            approval = True  # a pet rule that needs approval is never a plain yes
        else:
            approval = bool(_APPROVAL_ONLY.search(text)) and not any("yes" in v for v in stances.values())
    if not (clash or approval):
        return ""
    said = _quoted_pieces(quoted)
    who = _ask_who(text)
    if clash:
        return f"The listing is not clear about pets. It says {said}. Pets is left empty, so ask {who} which pets are allowed before you count on it."
    return f"The listing says pets depend on approval ({said}). Pets is left empty, so ask {who} which pets are allowed."


def _pets_soft_note(text: str) -> str:
    """"Cats welcome. Dogs considered case by case": cats is saved, and this says dogs are not a yes. "" when there is nothing to say."""
    stances, quoted = _pet_stances(text)
    soft = [sp for sp, v in stances.items() if "maybe" in v and "yes" not in v and "no" not in v]
    if not soft or not any("yes" in v for v in stances.values()):
        return ""
    names = " and ".join(sp for sp in soft)
    said = _quoted_pieces([q for q in quoted if _MAYBE_PETS.search(q)])
    return (f"The listing says {names} are considered case by case ({said}). Only the pets it clearly allows are saved, "
            f"so ask {_ask_who(text)} about {names}.")


def _pets_conflict(text: str) -> bool:
    """True when the listing says no pets in one place and that some pets are fine in another ("No pets allowed. Pets: up to 2 dogs")."""
    return bool(_pets_doubt(text)) and _pets(text) in ("none", "")


_WIRE_SENTENCE = re.compile(r"(?<!never )(?<!not )(?<!n't )(?<!no )\bwir(?:e|ed|ing)\b[^.\n;]{0,40}\bdeposit\b|\bdeposit\b[^.\n;]{0,40}\b(?:by|via|through|to be)\s+wir(?:e|ed|ing)\b", re.I)


def _split_wired_deposit(text: str) -> tuple[str, bool]:
    """The text with "Wire $500 deposit to hold unit" sentences blanked (so no deposit is read from them), and whether there was one."""
    parts = re.split(r"(?<=[.;\n])", text)
    kept = [x for x in parts if not _WIRE_SENTENCE.search(x)]
    return "".join(kept), len(kept) != len(parts)


_PET_LEAD = re.compile(r"^\W*(?:pets?|pet[- ]friendly|pet policy|cats?|dogs?|animals?)\b", re.I)


def _in_pet_sentence(text: str, pos: int) -> bool:
    """True when position ``pos`` sits in a sentence that starts with a pet word ("Pet friendly (cats only, $40/month, deposit $250)")
    or inside a bracket that follows one, and that sentence does not talk about the lease or the security deposit."""
    start = max(text.rfind(c, 0, pos) for c in ".!?;\n") + 1
    sent = text[start:pos]
    if _PET_LEAD.match(sent) and not re.search(r"\bsecurity\b|\bdamage\b|\blease\b|\brent\b(?!\s*:)", sent, re.I):
        return True
    op = text.rfind("(", 0, pos)
    return op >= 0 and text.find(")", op, pos) < 0 and bool(_PET_WORD.search(text[max(0, op - 30):op + 1]))


def _pet_fees(text: str) -> dict[str, float]:
    """Pet rent (monthly) and pet fee or deposit (one time), kept apart."""
    out: dict[str, float] = {}
    used: set[int] = set()
    for m in re.finditer(r"\$[ \t]?(\d{1,4})(?:\.\d\d)?[ \t]*(?:(?:/[ \t]*mo(?:nth)?|per month|monthly|a month)[ \t]*(?:per|each|/)[ \t]*(?:pet|dog|cat|animal)s?\b"
                         r"|(?:per|each|/)[ \t]*(?:pet|dog|cat|animal)s?[ \t]*(?:/[ \t]*mo(?:nth)?|per month|monthly|a month)\b)", text, re.I):
        used.add(m.start())
        out.setdefault("pet_rent", float(m.group(1)))
    for m in re.finditer(r"\$[ \t]?(\d{1,4})(?:\.\d\d)?[ \t]*(/[ \t]*mo(?:nth)?|per month|monthly|a month)?[ \t]*(?:per pet[ \t]*)?"
                         r"(?:one[- ]time[ \t]+|non[- ]refundable[ \t]+|refundable[ \t]+)?(?:pet\s+(rent|fees?|deposit|charge)\b|per pet\b)", text, re.I):
        if not m.group(3) and re.search(r"\bper pet\b", m.group(0), re.I) \
                and (re.search(r"\bdeposits?\W{0,4}$", text[max(0, m.start() - 14):m.start()], re.I)
                     or re.search(r"\bpet\s+(?:rent|fees?|deposit|charge)s?\W{0,6}$", text[max(0, m.start() - 22):m.start()], re.I)
                     or re.match(r"\s*deposit", text[m.end():m.end() + 12], re.I)):
            continue  # "deposit $250 per pet" and "Monthly pet rent $35 per pet": the label owns the amount, not a pet fee
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
    if "pet_fee" not in out:  # "Cats up to 2, $250 fee, $30 pet rent": a bare "$250 fee" in a pet sentence is the one-time pet fee
        for m in re.finditer(r"\b(?:cats?|dogs?|pets?|animals?)\b[^.\n;$]{0,45}?\$[ \t]?(\d{1,4})(?:\.\d\d)?[ \t]*(?:one[- ]time[ \t]+|non[- ]?refundable[ \t]+)?fee\b"
                             r"(?![ \t]+(?:for|to)[ \t]+(?:app|apply|screen|background|credit|admin|move|tour))([ \t]*(?:/[ \t]*mo(?:nth)?|per month|monthly|a month)?)", text, re.I):
            if text[max(0, m.start(1) - 12):m.start(1)].lower().rstrip().endswith(("application", "app", "admin")):
                continue
            out.setdefault("pet_rent" if m.group(2).strip() else "pet_fee", float(m.group(1)))
            break
    if "pet_fee" not in out and "pet_rent" in out:  # "Dogs max 2. $300 fee, $35 pet rent": the fee sits beside the pet rent
        m = re.search(r"\$[ \t]?(\d{1,4})(?:\.\d\d)?[ \t]*(?:one[- ]time[ \t]+|non[- ]?refundable[ \t]+)?fee\b[ \t]*,?[ \t]*(?:and[ \t]+)?\$[ \t]?\d{1,4}(?:\.\d\d)?[^.\n;$]{0,15}pet[ \t]+rent", text, re.I) \
            or re.search(r"\bpet[ \t]+rent\b[^.\n;$]{0,25}\$[ \t]?\d{1,4}(?:\.\d\d)?[^.\n;$]{0,15}?,[ \t]*(?:and[ \t]+)?\$[ \t]?(\d{1,4})(?:\.\d\d)?[ \t]*(?:one[- ]time[ \t]+|non[- ]?refundable[ \t]+)?fee\b(?![ \t]*(?:/|per month|monthly))", text, re.I)
        if m:
            out["pet_fee"] = float(m.group(1))
    if "pet_rent" not in out:  # "Pet friendly (cats only, $40/month, deposit $250)": a monthly amount inside a pet sentence is the pet rent
        for m in re.finditer(r"\$[ \t]?(\d{1,4})(?:\.\d\d)?[ \t]*(?:/[ \t]*mo(?:nth)?|per month|monthly|a month)\b(?![ \t]*(?:deposit|fee))", text, re.I):
            if _in_pet_sentence(text, m.start()) and not re.search(r"parking|garage|storage|utilit|trash|hoa|internet|cable|water|\brent\b", text[max(0, m.start() - 20):m.start()], re.I):
                out["pet_rent"] = float(m.group(1))
                break
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
            before = re.split(r"[,;.\n]", text[max(0, m.start() - 20):m.start()])[-1]
            # what follows counts only up to the next clause that is about another pet charge ("$300 pet deposit, non-refundable pet fee $150")
            after = re.split(r"[;.\n]|(?:,|\band\b)\s*(?:and\s+)?(?:[\w$]+[- ]?){0,4}\bpets?\b", text[m.end():m.end() + 40])[0]
            around = before + " " + text[m.start():m.end()] + " " + after
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
            pet = bool(_PET_WORD.search(near_before) or _PET_WORD.search(near_after)) or _in_pet_sentence(text, m.start())
        if not pet:
            continue
        found.setdefault("pet_fee" if nonref else "pet_deposit", amount)
        blanked = blanked[:m.start()] + " " * (m.end() - m.start()) + blanked[m.end():]
    return found, blanked


def _clauses(text: str) -> list[str]:
    """Split at a full stop, semicolon or new line, but not inside brackets: "Breed rules (no pit bulls; no rottweilers)" stays whole."""
    out: list[str] = []
    depth, start = 0, 0
    for i, ch in enumerate(text):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif ch in ".;\n" and depth == 0:
            out.append(text[start:i])
            start = i + 1
    out.append(text[start:])
    return out


def _pet_limit_fields(text: str) -> dict[str, Any]:
    """Structured pet limits: pet_weight_limit (lb), pet_count_limit, pet_breed_note and fenced_yard (1 or 0)."""
    out: dict[str, Any] = {}
    w = re.search(r"\b(?:dogs?|pets?|animals?)\b[^.\n;]{0,40}?(?:under|up to|less than|below|at most|no more than|not (?:to )?exceed(?:ing)?|max(?:imum)?(?: of)?|weigh(?:ing|s)?(?: up to| under)?|<)\s*(\d{1,3})\s*(?:lbs?\b|pounds?\b)", text, re.I) \
        or re.search(r"\bno\s+(?:dogs?|pets?|animals?|breeds?|cats?)?\s*(?:over|above|exceeding|larger than|heavier than|more than)\s*(\d{1,3})\s*(?:lbs?\b|pounds?\b)", text, re.I) \
        or re.search(r"\b(?:dogs?|pets?|animals?)\b[^.\n;]{0,30}?\b(?:over|above|exceeding)\s*(\d{1,3})\s*(?:lbs?\b|pounds?\b)\s*(?:are\s+)?(?:not\s+(?:allowed|permitted|accepted)|prohibited)", text, re.I) \
        or re.search(r"\b(\d{1,3})\s*(?:lbs?\b|pounds?\b)\s*(?:weight\s*)?(?:limit|max(?:imum)?)", text, re.I) \
        or re.search(r"\b(?:dogs?|pets?|animals?)\b[^.\n;]{0,40}?\b(\d{1,3})\s*(?:lbs?\b|pounds?\b)\s*(?:each|apiece|max(?:imum)?|per (?:pet|dog|animal))", text, re.I) \
        or re.search(r"\bweight (?:limit|max(?:imum)?)\s*(?:of|is|:)?\s*(\d{1,3})\s*(?:lbs?\b|pounds?\b)?", text, re.I)
    if w and 3 <= int(w.group(1)) <= 300:
        out["pet_weight_limit"] = float(w.group(1))
    n = re.search(r"\b(?:max(?:imum)?(?: of)?|limit(?: of)?|up to|no more than|at most)\s+(\d|one|two|three|four)\s+(?:pets?|animals?|cats?|dogs?)\b", text, re.I) \
        or re.search(r"\b(\d|one|two|three|four)\s+(?:pets?|animals?|cats?|dogs?)\s+(?:max(?:imum)?|limit|per (?:unit|apartment|home|household))", text, re.I)
    if not n:  # "Cats up to 2", "Dogs max 2"
        n = re.search(r"\b(?:pets?|animals?|cats?|dogs?)\s+(?:up to|max(?:imum)?(?: of)?|limit(?: of)?)\s+(\d|one|two|three|four)\b(?!\d|\s*(?:lbs?|pounds?|years?|yrs?|in\b|inch))", text, re.I)
    if not n:  # "Two dogs ok", "2 cats allowed"
        n = re.search(r"(?<![\w$.])(\d|one|two|three|four)\s+(?:pets?|animals?|cats?|dogs?)\s+(?:are\s+)?(?:ok|okay|allowed|welcome|accepted|permitted)\b", text, re.I)
    if n:
        v = n.group(1).lower()
        count = int(v) if v.isdigit() else _NUM_WORDS[v]
        if count >= 1:
            out["pet_count_limit"] = count
    if "pet_count_limit" not in out:  # "Cats ok, up to 2"
        for sentence in re.split(r"[.\n;]", text):
            if _PET_WORD.search(sentence):
                n = re.search(r"\b(?:up to|max(?:imum)?(?: of)?|limit(?: of)?|no more than|at most)\s+(\d|one|two|three|four)\b(?!\d|\s*(?:lbs?|pounds?|years?|yrs?|in\b|inch|bed|bath|sq|people|persons?|occupants?|adults?|residents?|%|months?))", sentence, re.I)
                if n:
                    v = n.group(1).lower()
                    count = int(v) if v.isdigit() else _NUM_WORDS[v]
                    if count >= 1:
                        out["pet_count_limit"] = count
                        break
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
    b = next((c for c in _clauses(text) if re.search(r"\b(?:breed|breeds|breed restrictions?)\b", c, re.I)), None)
    if b:
        clause = " ".join(b.split()).strip(" -:,")
        if "," in clause and "(" not in clause:  # "Dogs OK, 1 dog max, breed restrictions apply": keep the pieces that are about breeds
            other = re.compile(r"\b\d{1,3}\s*(?:lbs?|pounds?)|\bmax(?:imum)?\b|\b(?:dogs?|cats?|pets?|animals?)\b[^,]{0,12}\b(?:ok|okay|allowed|welcome|accepted)\b|\bconsidered\b|case[- ]by[- ]case|\bno more than\b|\bup to\b|\bunder\b|approval|\bfees?\b|\$", re.I)
            pieces = [x.strip() for x in clause.split(",") if re.search(r"\bbreeds?\b", x, re.I) and not other.search(x)]
            if pieces:
                clause = ", ".join(pieces)
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
    for raw in _clauses(text):
        if not re.search(r"\b(?:dogs?|cats?|pets?|animals?|breeds?)\b", raw, re.I):
            continue
        clause = " ".join(raw.split()).strip(" -:,")
        if re.search(r"\b\d{1,3}\s*(?:lbs?|pounds?)|\bbreed|\bweight|\brestrict\w*|\blimits?\b|\bmax(?:imum)?\b|\bunder \d|\bup to \d|\b(?:two|2) pets\b|\bsize\b", clause, re.I) \
                and len(clause) <= 140 and not any(clause.lower() in f.lower() for f in found):
            found.append(clause[0].upper() + clause[1:])
    return found[:2]


def _app_fee_per_person(text: str) -> str:
    """"Application fee $55 per adult": the fee field is one amount, so keep the per-person wording visible."""
    m = re.search(r"application(?: processing)? fees?[^.\n]{0,25}?\$\s?(\d{1,4})(?:\.\d\d)?[^.\n]{0,12}?\b(?:per|each|/)\s*(adult|applicant|person|occupant|tenant|resident|roommate)", text, re.I) \
        or re.search(r"\$\s?(\d{1,4})(?:\.\d\d)?\s*(?:application fee|app fee)[^.\n]{0,12}?\b(?:per|each|/)\s*(adult|applicant|person|occupant|tenant|resident|roommate)", text, re.I) \
        or re.search(r"application(?: processing)? fees?[^.\n]{0,40}?(?:\bper|\beach)\s+(adult|applicant|person|occupant|tenant|resident|roommate)", text, re.I)
    if not m:  # "Screening: $50 per adult"
        m = re.search(r"\$\s?(\d{1,4})(?:\.\d\d)?\s*(?:per|each|/)\s*(adult|applicant|person|occupant|tenant|resident|roommate)\b", text, re.I)
        line_start = text.rfind("\n", 0, m.start()) + 1 if m else 0
        if not m or not re.search(r"\bapplic|\bapp fee|\bscreening|\bbackground check", text[line_start:m.end() + 40], re.I):
            return ""
    who = m.group(m.lastindex).lower()
    amount = f" ${float(m.group(1)):,.0f}" if m.lastindex >= 2 and m.group(1).replace('.', '').isdigit() else ""
    return f"The application fee{amount} is charged per {who}, so each adult who applies pays it."


def app_fee_per_adult(text: str) -> float | None:
    """The application fee when the listing charges it per adult ("$50 per adult"), else None."""
    m = re.search(r"\$\s?(\d{1,4})(?:\.\d\d)?", _app_fee_per_person(text) or "")
    return float(m.group(1)) if m else None


def app_fee_note_for_people(values: dict[str, Any], people: int) -> dict[str, Any]:
    """For the Add preview only: when the application fee is charged per adult and the search has several people, say what
    all of them pay together. The ``application_fee`` field itself stays the one-person amount. Returns ``values`` (changed
    in place) so a caller can chain it."""
    note = values.get("found_in_listing") or ""
    fee = values.get("application_fee")
    if people > 1 and isinstance(fee, (int, float)) and fee > 0 and "is charged per" in note and "together" not in note:
        values["found_in_listing"] = note + f" For {people} adults that is ${fee * people:,.0f} together."
    return values


def _move_in_months(text: str) -> tuple[int, bool]:
    """(months of rent due at move-in, deposit also due) from "first and last month" or "first, last and deposit"."""
    m = re.search(r"\b(?:first|1st)\b(?:\s+month(?:'?s)?(?:\s+rent)?)?\s*(?:,|and|&|\+|/|plus)\s*(?:and\s+)?\blast\b(?:\s+month(?:'?s)?(?:\s+rent)?)?"
                  r"(?:\s*(?:,|and|&|\+|/|plus)\s*(?:a\s+)?(?:the\s+)?(?:security\s+)?(deposit))?", text, re.I)
    if not m:
        return 0, False
    return 2, bool(m.group(1))


_WORD_NUM = {"one": 1, "a": 1, "1": 1, "two": 2, "2": 2}


_BEST_CASE_DEPOSIT = (
    r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?[ \t]*(?:security[ \t]+)?deposit[ \t]*,?[ \t]*(?:(?:with|upon|on|w/)[ \t]+(?:approved|good|qualifying|excellent)[ \t]+credit|o\.?a\.?c\.?\b|(?:with|subject to)[ \t]+credit[ \t]+approval)",
    r"\b(?:security[ \t]+)?deposits?[ \t]*(?:is[ \t]+|of[ \t]+|[:\-][ \t]*)?(?:as low as|as little as|low as|starting (?:at|from)|starts? (?:at|from)|beginning at|from only)[ \t]*\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?",
    r"\b(?:security[ \t]+)?deposits?[ \t]*(?:is[ \t]+|of[ \t]+|[:\-][ \t]*)?\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?[ \t]*(?:(?:with|upon|on|w/)[ \t]+(?:approved|good|qualifying|excellent)[ \t]+credit|o\.?a\.?c\.?\b)",
)


def _best_case_deposit(text: str) -> tuple[float | None, str]:
    """A deposit that is only the best case ("$500 deposit with approved credit", "deposit as low as $500"): not what every renter
    pays, so it is not saved as the deposit. Returns (amount, text with that phrase blanked)."""
    for pat in _BEST_CASE_DEPOSIT:
        m = re.search(pat, text, re.I)
        if m:
            return _num(m.group(1)), text[:m.start()] + " " * (m.end() - m.start()) + text[m.end():]
    return None, text


def _deposit_in_months(text: str) -> float:
    """The security deposit written as a number of months of rent ("security deposit one month", "deposit equal to one month's
    rent"), as that number of months. 0 when the text gives none."""
    m = re.search(r"\b(?:security |damage )?deposits?\b[ \t:\-]{0,4}(?:is |of |equal to |equals |=)?[ \t]*(\d(?:\.\d{1,2})?)[ \t]*(?:x|times|months?(?:'s?)?(?:[ \t]+(?:of[ \t]+)?rent)?)(?:[ \t]+(?:the[ \t]+|of[ \t]+|monthly[ \t]+)*rent)?\b", text, re.I)
    if m and 0 < float(m.group(1)) <= 6:
        return float(m.group(1))
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
    m = re.search(r"\bclosing costs?(?:\s+(?:(?:are|is)\s+)?(?:est\w*\.?|estimate[d]?)(?:\s+(?:at|to be|of|around|about))?)?[ \t:\-=]{0,6}(?:of |about |around |approx\.? |~)?\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?(?!\d)", text, re.I) \
        or re.search(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?[ \t]*(?:in |for )?(?:est\w*\.?[ \t]+)?closing costs?\b", text, re.I)
    if not m:
        return None
    value = _num(m.group(1))
    return value if 100 <= value <= 5_000_000 else None


def _seller_credit(text: str) -> float | None:
    """What the seller gives the buyer toward closing: "Seller will contribute up to $5,000 toward closing costs", "seller
    concessions of $8,000", "$3,000 seller credit". None when the text gives no amount."""
    amt = r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?!\d)"
    pats = (r"\bseller(?:'s)?[ \t]+(?:will[ \t]+)?(?:contribut\w*|credit|concessions?|assist\w*|offer\w*|give[sn]?)\b[^$\n.]{0,40}?" + amt,
            r"\bseller(?:'s)?[ \t]+(?:will[ \t]+|to[ \t]+)?(?:pay|pays|cover|covers)\b[^$\n.]{0,30}?" + amt + r"[^\n.]{0,30}\bclosing",
            r"\bseller[ \t]+(?:concessions?|credits?|contributions?)\b[^$\n.]{0,20}?" + amt,
            amt + r"[ \t]+(?:in[ \t]+|of[ \t]+)?seller[ \t]+(?:concessions?|credits?|contributions?|paid closing)",
            r"\bclosing[ \t]+costs?\b[^$\n.]{0,30}?\b(?:paid|covered|contributed)[ \t]+by[ \t]+(?:the[ \t]+)?seller\b[^$\n.]{0,25}?" + amt,
            r"\bseller[ \t]+(?:paid|covered)[ \t]+closing[ \t]+costs?\b[^$\n.]{0,25}?" + amt)
    for pat in pats:
        for m in re.finditer(pat, text, re.I):
            if re.search(r"assessment", m.group(0), re.I):
                continue
            value = _num(m.group(1))
            if 100 <= value <= 5_000_000:
                return value
    return None


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
    raw = re.split(r"(?<!\b[A-Z])(?<!\bInc)(?<!\bCo)(?<!\bJr)(?<!\bSr)(?<!\bLtd)(?<!\bCorp)(?<!\bLLC)[.!?]\s+(?=[A-Z0-9$#])", m.group(1))[0]
    raw = re.split(r"[ \t,;]+(?:unit|apt\.?|apartment|suite|ste\.?|#)[ \t]*#?[ \t]*[A-Za-z]?\d{0,5}[A-Za-z]?\b(?=[ \t]*(?:[.,;]|$|\d|\$))", raw, maxsplit=1, flags=re.I)[0]
    line = re.sub(r"\(?\+?\d[\d\s().-]{6,}\d\)?", " ", raw)
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
        return "all"
    if re.search(r"\b(?:all )?utilities\s*(?:are )?included\s+in\s+(?:the\s+)?(?:rent|lease|price|monthly)\b|\butilities\s*:\s*(?:all\s+)?(?:included|paid)\b", low):
        return "all"
    found: list[str] = []
    words = "|".join(re.escape(w) for w in _UTILITY_WORDS) + "|hot water|trash removal|garbage|sewage|electricity"
    for m in re.finditer(r"\b(?:rent |lease |monthly rent )?includes?\s+((?:(?:" + words + r")[ \t]*(?:,|/|&|and|\+)?[ \t]*(?:and[ \t]+)?){1,6})(?!\s*(?:fee|charge|deposit|\$))", low):
        found += re.findall(words, m.group(1))
    for m in re.finditer(r"((?:(?:" + words + r")[ \t]*(?:,|/|&|and|\+)?[ \t]*(?:and[ \t]+)?){1,6})\s*(?:(?:is|are)\s*)?(?:all\s*)?(?:included|paid|covered|provided)\b", low):
        found += re.findall(words, m.group(1))
    for m in re.finditer(r"\b(?:utilities included|included utilities|rent includes|includes|utilities)\s*[:\-]\s*([^\n.;]{0,60})", low):
        found += re.findall(words, m.group(1))
    for m in re.finditer(r"\b(?:landlord|owner|management|property manager)\s+(?:pays?|covers?)\s+(?:for\s+)?((?:(?:" + words + r")[ \t]*(?:,|/|&|and|\+)?[ \t]*(?:and[ \t]+)?){1,6})", low):
        found += re.findall(words, m.group(1))
    return _ordered_utilities(found) if found else ""


_ALL_EXCEPT = re.compile(r"\ball\s+(?:the\s+)?utilities\b([^.\n;]{0,40}?)\b(?:except(?:\s+for)?|other than|besides)\s+([^.\n;]{0,60})", re.I)


def _all_except(text: str) -> list[str]:
    """Utilities left out of "Tenant pays all utilities except trash" / "All utilities except garbage" (so the landlord keeps
    those). Empty when the text says the opposite ("all utilities included except trash") or has no such phrase."""
    out: list[str] = []
    for clause in re.split(r"\n|;|\.(?=\s|$)", text):
        m = _ALL_EXCEPT.search(clause)
        if not m or re.search(r"\b(?:included|paid|covered|provided|landlord|owner)\b", clause[:m.end(1)], re.I):
            continue
        out += [w for w in re.findall(_ROLE_WORD, m.group(2).lower())]
    return out


def _tenant_pays(text: str) -> str:
    """"Tenant pays gas, electric" from "Tenant pays gas and electric" (utilities the listing says the renter pays), or ''."""
    low = text.lower()
    words = "|".join(re.escape(w) for w in _UTILITY_WORDS) + "|electricity|garbage|trash removal|sewage"
    found: list[str] = []
    for clause in re.split(r"\n|;|\.(?=\s|$)", low):
        m = re.search(r"\b(?:tenants?|residents?|renters?|lessees?|you)\s*(?:pays?|are responsible for|is responsible for|responsible for|will pay|must pay|to pay|(?:sets?|opens?|arranges?) up|(?:sets?|opens?) (?:their|your) own)\b\s*(?:for\s+)?(?:all\s+)?(?:the\s+)?(.*)", clause)
        if not m:
            continue
        rest = m.group(1)
        found += re.findall(r"\b(?:" + words + r")\b", rest)
        if re.match(r"\s*utilities\b", rest) and not re.match(r"\s*utilities[^.\n]{0,20}\b(?:except|other than|besides)\b", rest):
            found += list(_ALL_UTILITIES)  # "Tenant responsible for all utilities"
    left_out = {"trash" if w in ("garbage", "trash removal") else "electric" if w == "electricity" else "sewer" if w == "sewage" else w for w in _all_except(low)}
    if left_out:
        found = [w for w in found if w not in left_out] + [w for w in _ALL_UTILITIES if w not in left_out]
    return _ordered_utilities(found) if found else ""


_ALL_UTILITIES = ("electric", "gas", "water", "sewer", "trash", "heat")  # what "all utilities" means for a renter who pays them


_UTILITY_ALIASES = ((r"\b(?:valet[ -]trash|trash[ -]valet|valet[ -]waste|doorstep (?:trash|garbage))\b", "valet-waste"), (r"\bpg\s*(?:&|and)\s*e\b", "electric and gas"), (r"\bameren\b", "electric and gas"),
                    (r"\bcomed\b", "electric"), (r"\bnicor\b", "gas"), (r"\bhydro\b(?!\s*-?\s*(?:flask|jug))", "electric"),
                    (r"\brubbish\b", "trash"), (r"\brefuse\b(?!\s+to\b)", "trash"), (r"\bcable\b(?!\s+ready)", "internet"))


# a provider or short note in brackets right after a utility word: "Electric (PG&E)", "Gas (Nicor)", "Water (city)"
_UTIL_PAREN = re.compile(r"\b(electricity|electric|gas|water|sewer|trash|internet|heat|cable)\s*\((?![^)]*(?:\d|\$|\b(?:incl\w*|included|not|extra|paid|billed|tenant|resident|landlord|owner|plus|excluded|separate\w*)\b))[^)]{1,25}\)", re.I)
# "incl. utilities", "utilities incl.", "incl. water and sewer" (not "not incl.")
_INCL_ABBREV = (re.compile(r"(?<!not )(?<!n't )\bincl(?:uding|uded|\.)?[ \t]+(?:all[ \t]+)?(?:the[ \t]+)?utilit(?:y|ies)\b(?![ \t]*(?:not|extra|separate))", re.I),
                re.compile(r"\butilit(?:y|ies)[ \t]+incl\b\.?", re.I),
                re.compile(r"(?<!not )(?<!n't )\bincl\.[ \t]+((?:water|sewer|trash|gas|electric|heat|internet|wifi|hot water)\b)", re.I))


def _util_text(text: str) -> str:
    """The listing text with provider and everyday names turned into the utility words the readers know: "PG&E" is
    electric and gas, ComEd and hydro are electric, Nicor is gas, refuse and rubbish are trash, cable is internet.
    "Valet trash" is a service fee, not a utility, so it is hidden from the utility readers."""
    text = _UTIL_PAREN.sub(lambda m: m.group(1), text)  # "Electric (PG&E), gas" -> "Electric, gas"
    text = _INCL_ABBREV[0].sub("all utilities included", text)
    text = _INCL_ABBREV[1].sub("utilities included", text)
    text = _INCL_ABBREV[2].sub(lambda m: "includes " + m.group(1), text)
    for pat, word in _UTILITY_ALIASES:
        text = re.sub(pat, word, text, flags=re.I)
    return text


_INCL_EXCEPT = (re.compile(r"\ball\s+(?:the\s+)?utilities\s+(?:are\s+)?(?:included|paid|covered|provided)\b[^.\n;]{0,20}?\b(?:except(?:\s+for)?|other than|besides)\s+([^.\n;]{0,60})", re.I),
                re.compile(r"\butilities\s*[:\-]\s*all\s+(?:are\s+)?(?:included|paid|covered|provided)?\s*(?:except(?:\s+for)?|other than|besides)\s+([^.\n;]{0,60})", re.I))


def _included_except(text: str) -> list[str]:
    """Utilities the tenant still pays when the listing says "all utilities included except electric". Empty when it doesn't."""
    out: list[str] = []
    for clause in re.split(r"\n|;|\.(?=\s|$)", text):
        for pat in _INCL_EXCEPT:
            m = pat.search(clause)
            if m:
                out += re.findall(_ROLE_WORD, m.group(1).lower())
                break
    return out


def _billed_back(text: str) -> tuple[str, float] | None:
    """"Water, sewer and trash billed back at $85/month" -> ("water, sewer, trash", 85). The amount is the monthly bill the
    tenant pays for those utilities. None when the text has no such line."""
    low = text.lower()
    words = "|".join(re.escape(w) for w in _UTILITY_WORDS) + "|garbage|sewage|electricity"
    m = re.search(r"((?:(?:" + words + r")[ \t]*(?:,|/|&|and|\+)?[ \t]*(?:and[ \t]+)?){1,6})\s*(?:(?:is|are)\s+)?(?:billed|charged|passed)\b[^$\n.]{0,30}?"
                  r"\$\s?(\d{1,4})(?:\.\d\d)?\s*(?:/\s*mo(?:nth)?|per month|monthly|a month)", low)
    if not m:
        # "$25/mo billed back for trash" (the amount first)
        m2 = re.search(r"\$\s?(\d{1,4})(?:\.\d\d)?\s*(?:/\s*mo(?:nth)?|per month|monthly|a month)\s*(?:is\s+|are\s+)?(?:billed|charged|passed)\s*(?:back|through)?\s*(?:for|on|to cover)\s+"
                       r"((?:(?:" + words + r")[ \t]*(?:,|/|&|and|\+)?[ \t]*(?:and[ \t]+)?){1,6})", low)
        if not m2:
            return _billed_back_loose(low, words)
        found = re.findall(words, m2.group(2))
        return (_ordered_utilities(found), float(m2.group(1))) if found else None
    found = re.findall(words, m.group(1))
    return (_ordered_utilities(found), float(m.group(2))) if found else None


def _billed_back_loose(low: str, words: str) -> tuple[str, float] | None:
    """"$25/mo for trash, billed back" and "trash $25/mo billed back": the amount sits next to the utility and the words
    billed back or charged back follow it."""
    monthly = r"(?:/\s*mo(?:nth)?|per month|monthly|a month)"
    lst = r"((?:(?:" + words + r")[ \t]*(?:,|/|&|and|\+)?[ \t]*(?:and[ \t]+)?){1,6})"
    back = r"[^.\n;$]{0,12}?\b(?:billed|charged|passed)\s*(?:back|through|on)\b"
    m = re.search(r"\$\s?(\d{1,4})(?:\.\d\d)?\s*" + monthly + r"\s*(?:for\s+)?" + lst + back, low)
    if m:
        found = re.findall(words, m.group(2))
        return (_ordered_utilities(found), float(m.group(1))) if found else None
    m = re.search(lst + r"[:\-]?\s*\$\s?(\d{1,4})(?:\.\d\d)?\s*" + monthly + back, low)
    if m:
        found = re.findall(words, m.group(1))
        return (_ordered_utilities(found), float(m.group(2))) if found else None
    return None


def listing_billed_names(text: str) -> list[str]:
    """Public: the utilities a listing's billed-back amount covers ("trash" for "$25/mo billed back for trash"), or []."""
    try:
        billed = _billed_back(_util_text(_tidy(text or "")))
        if billed:
            return [w.strip() for w in billed[0].split(",") if w.strip()]
        return [w.strip() for w in _ordered_utilities(list(_utility_roles(_util_text(_tidy(text or "")))["billed"])).split(",") if w.strip()]
    except Exception:
        return []


_ROLE_WORD = (r"hot water|water|sewer|sewage|trash removal|trash|garbage|gas|electricity|electric|heat|internet|wi-?fi|cable")
_ROLE_ITEM = r"\b(?:" + _ROLE_WORD + r")\b(?!\s+(?:stove|range|oven|fireplace|cooktop|grill|appliances?|water heater|pump|bill\b|meter))"
_ROLE_LIST = re.compile(_ROLE_ITEM + r"(?:\s*(?:,|/|&|\+|\band\b|\bor\b)\s*" + _ROLE_ITEM + r")*", re.I)
_TENANT_SUFFIX = re.compile(
    r"^\s*(?:(?:is|are)\s+)?(?:paid\s+(?:for\s+)?by\s+(?:the\s+)?(?:tenants?|residents?|renters?)\b|(?:the\s+)?(?:tenants?|residents?|renters?)'?s?\s+(?:responsibility|expense)\b|"
    r"extra\b|not\s+(?:included|covered|provided)\b|(?:paid\s+|billed\s+|metered\s+)?separate(?:ly)?\b|billed\b|charged\b|passed\s+through\b|"
    r"your\s+own\b|additional\b|excluded\b|at\s+(?:the\s+)?(?:tenant|resident)'?s?\s+expense\b)", re.I)
_LANDLORD_SUFFIX = re.compile(
    r"^\s*(?:(?:is|are)\s+)?(?:paid\s+(?:for\s+)?by\s+(?:the\s+)?(?:landlord|owner|management)\b|included\b|covered\b|provided\b|paid\b|free\b)", re.I)
_TENANT_PREFIX = re.compile(
    r"(?:\b(?:tenants?|residents?|renters?|lessees?|you)\s*(?:pays?|are responsible for|is responsible for|responsible for|will pay|must pay|to pay|covers?|handles?)\b"
    r"|\bplus\b|\bextra\b|\bnot included\s*[:\-]?|\bexcluding\b)", re.I)
_LANDLORD_PREFIX = re.compile(
    r"(?:\b(?:landlord|owner|management|property manager|lessor)\s*(?:pays?|covers?|provides?)\b|\b(?:rent |lease )?includes?\b|\bincluded\s*[:\-]|\bincluding\b)", re.I)
_EXCEPT = re.compile(r"\b(?:except|other than|besides)\b", re.I)
_BILLED_WORDS = re.compile(r"\b(?:billed|charged|passed through|rubs)\b", re.I)


def _last_role(gap: str) -> str:
    """Which side the cue words just before a list put it on: "tenant", "landlord" or "" (no cue)."""
    role, at = "", -1
    for kind, pat in (("tenant", _TENANT_PREFIX), ("landlord", _LANDLORD_PREFIX)):
        for m in pat.finditer(gap):
            if m.start() >= at:
                role, at = kind, m.start()
    if role and _EXCEPT.search(gap[at:]):
        role = "landlord" if role == "tenant" else "tenant"
    elif not role and _EXCEPT.search(gap):
        m = _EXCEPT.search(gap)
        before = _last_role(gap[:m.start()])
        role = {"tenant": "landlord", "landlord": "tenant"}.get(before, "")
    return role


def _utility_roles(text: str) -> dict[str, Any]:
    """Who pays each utility the listing names. Each cue ("paid by tenant", "landlord pays", "included", "extra", "plus",
    "billed back") belongs to the nearest list of utilities in its own sentence: the list right before it for a cue that
    follows the list, the list right after it for a cue that leads. Returns {"tenant": [...], "landlord": [...],
    "billed": [...], "amount": monthly $ or None}."""
    tenant: list[str] = []
    landlord: list[str] = []
    billed: list[str] = []
    amount: float | None = None
    for sentence in re.split(r"\n|;|\.(?=\s|$)", text.lower()):
        lists = list(_ROLE_LIST.finditer(sentence))
        cursor = 0
        for i, m in enumerate(lists):
            words = re.findall(_ROLE_WORD, m.group(0))
            nxt = lists[i + 1].start() if i + 1 < len(lists) else len(sentence)
            tail = sentence[m.end():nxt]
            role, used = "", 0
            ts, ls = _TENANT_SUFFIX.match(tail), _LANDLORD_SUFFIX.match(tail)
            if ts:
                role, used = "tenant", ts.end()
                if _BILLED_WORDS.match(tail.lstrip()) or re.match(r"\s*(?:billed|charged)", tail):
                    billed += words
                bm = re.search(r"\$\s?(\d{1,3}(?:,\d{3})+|\d{1,4})(?:\.\d\d)?", tail[:80])
                if bm and _BILLED_WORDS.search(tail[:bm.start()]) and not re.search(r"deposit|fee|one[- ]time|set[- ]?up", tail[max(0, bm.start() - 20):bm.end() + 25]):
                    amount = amount if amount is not None else float(bm.group(1).replace(",", ""))
            elif ls:
                role, used = "landlord", ls.end()
            else:
                role = _last_role(sentence[cursor:m.start()])
            cursor = m.end() + used
            if role == "tenant":
                tenant += words
            elif role == "landlord":
                landlord += words
    return {"tenant": tenant, "landlord": landlord, "billed": billed, "amount": amount}


def listing_billed_amount(text: str) -> float | None:
    """Public: the monthly utilities bill a listing's text gives ("billed back at $85/month", "billed back monthly (avg $55)"), or None."""
    try:
        text = _util_text(_tidy(text or ""))
        billed = _billed_back(text)
        if billed:
            return billed[1]
        return _utility_roles(text)["amount"]
    except Exception:
        return None


def _reconcile_utilities(included: str, pays: str, facts: list[str]) -> tuple[str, str]:
    """A utility goes in one list only. When the listing says a utility is both included and paid by the renter, it is kept
    as something the renter pays (the safer reading for the cost) and a note says the listing is unclear."""
    if not included or not pays:
        return included, pays
    norm = {"wifi": "internet", "cable": "internet", "hot water": "water"}
    pay_set = {norm.get(w.strip(), w.strip()) for w in pays.split(",") if w.strip()}
    have = list(_ALL_UTILITIES) + ["internet"] if included == "all" else [w.strip() for w in included.split(",") if w.strip()]
    clash = [w for w in have if norm.get(w, w) in pay_set]
    if not clash:
        return included, pays
    left = [w for w in have if w not in clash]
    names = ", ".join(clash)
    facts.append(f"The listing is unclear about {names}: it says {names} is included and also that you pay for it. "
                 f"It is listed as something you pay, so check with the landlord.")
    return (_ordered_utilities(left) if left else ""), pays


def _tenant_pays_choices(pays: str) -> str:
    """The renter-pays words as the store's fixed list (electric, gas, water, trash, internet, heat), in that order."""
    words = {w.strip() for w in pays.split(",")}
    words = {"internet" if w in ("wifi", "cable") else "water" if w == "hot water" else w for w in words}
    return ", ".join(w for w in ("electric", "gas", "water", "sewer", "trash", "internet", "heat") if w in words)


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
            return (dt if dt > today else date(today.year + 1, dt.month, dt.day)).isoformat()
        month = _MONTHS[m.group("mon")[:3].lower()]
        day = int(m.group("day"))
        if m.group("year"):
            return date(int(m.group("year")), month, day).isoformat()
        dt = date(today.year, month, day)
        return (dt if dt > today else date(today.year + 1, month, day)).isoformat()  # no year: the next such date, never today
    except (ValueError, KeyError, TypeError):
        return None


_DATE = (r"(?:(?P<iso>\d{4}-\d{2}-\d{2})|(?P<mdy>\d{1,2}[/.-]\d{1,2}(?:[/.-](?:\d{4}|\d{2}))?)|"
         r"(?P<mon>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?\s+"
         r"(?P<day>\d{1,2})(?:st|nd|rd|th)?(?:,?\s*(?P<year>\d{4}))?)")


def _available(text: str) -> str | None:
    today = _today()
    low = text.lower()
    m = re.search(r"\b(?:date available|availability|available(?: from| on| starting| beginning)?|avail\.?|move[- ]?in(?: date)?|(?:move[- ]?in[- ])?ready(?:[ ]for[ ]move[- ]?in)?(?:[ ]on|[ ]by)?|lease start(?:s| date)?)\b[ \t:\-]{0,6}(?:on |for |by |starting |beginning )?" + _DATE, low)
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
                r"(?<![$\d,.])\b((?:18|19|20)\d{2})\s+(?:new\s+)?(?:construction|built|build)\b(?!-)(?!\s*(?:units?|prices?|from|begins|starting|starts))",
                r"\bnew (?:construction|build)\s*(?:\(|[:,\-]\s*)?(?:completed |delivered |ready |in )?((?:18|19|20)\d{2})\b"):
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
    m = re.search(r"(?:\bhoa|association|homeowners'? association|\bcondo(?=\s*(?:fee|fees|dues|payment|assessment))|\bcommon (?:area )?(?:charges?|fees?))(?:\s*(?:fee|fees|dues|payment|assessment))*[ \t:\-=(]{0,6}\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?\s*(/\s*\w+|per\s+\w+|\w+ly|annual\w*)?", text, re.I)
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
    """Property tax as a yearly figure. "Taxes: $4,100 per year", "property taxes approx $4,100/yr", "$342/mo taxes"."""
    amt = r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?\s*(/\s*\w+|per\s+\w+|\w+ly|annual\w*)?"
    m = re.search(r"\b(?:property )?tax(?:es)?(?:\s+annual amount|\s+paid|\s+\(annual\))?(?:[ \t:\-=]|approx(?:imately|\.)?|about|around|est(?:imated|\.)?|~){0,10}" + amt, text, re.I)
    if not m:
        m = re.search(amt + r"\s*(?:in\s+)?(?:property\s+)?tax(?:es)?\b", text, re.I)
    if not m:
        return None
    value, per = _num(m.group(1)), (m.group(2) or "").lower()
    if re.search(r"mo|month", per):
        value *= 12
    return round(value, 2) if 100 <= value <= 200000 else None


_NOSUFFIX = re.compile(r"(?<![\w$.,/#-])(\d{1,6})[ \t]+((?:(?:[NSEW]{1,2}|North|South|East|West)\.?[ \t]+)?[A-Z][A-Za-z.'-]*(?:[ \t]+[A-Z][A-Za-z.'-]*){0,2})\b")
_NOSUFFIX_AFTER = re.compile(r"[ \t]*(?:,[ \t]*[A-Z][A-Za-z.'-]+(?: [A-Z][A-Za-z.'-]+){0,3},?[ \t]+[A-Z]{2}\b|,[ \t]*\d{5}\b|,?[ \t]+(?:#|apt\b|apartment\b|unit\b|suite\b|ste\b))", re.I)
_NOSUFFIX_BEFORE = re.compile(r"(?:#|\bapt\.?|\bapartment|\bunit|\bsuite)[ \t]*#?[ \t]*[A-Za-z]?\d{1,5}[A-Za-z]?[ \t]*,[ \t]*$", re.I)
_NOSUFFIX_BAD = _NOT_STREET_WORDS | {"day", "days", "week", "weeks", "per", "plus", "and", "of", "at", "in", "for", "to", "off", "total", "rent", "pm", "am",
                                     "bedroom", "bathroom", "studio", "available", "monthly"}


def _address_no_suffix(text: str) -> tuple[str, int] | None:
    """A street with no suffix ("3329 N Broadway, Chicago, IL 60657" or "Unit 4C, 3329 N Broadway"). It must be a house number, an
    optional direction and a capitalised street name, followed by a city and state, a ZIP or a unit word, or follow a unit and a comma."""
    for m in _NOSUFFIX.finditer(text):
        words = [w.strip(".,").lower() for w in m.group(2).split()]
        if set(words) & _NOSUFFIX_BAD:
            continue
        if len(words) == 1 and len(words[0]) <= 1:
            continue
        line_start = text.rfind("\n", 0, m.start()) + 1
        if _NOSUFFIX_AFTER.match(text, m.end()) or _NOSUFFIX_BEFORE.search(text[line_start:m.start()]):
            return " ".join((m.group(1) + " " + m.group(2)).split()), m.end()
    return None


# --------------------------------------------------------------------------- address
def _unit_ok(value: str | None) -> bool:
    """A lone N, S, E, W (or NE, NW, SE, SW) is a street direction, never a unit ("710 W Clark St, W")."""
    return bool(value) and not re.fullmatch(r"[NS][EW]?|[EW]", value.strip(". "), re.I)


def _address(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    candidates: list[tuple[str, str | None, int]] = []
    for m in _ADDRESS.finditer(text):
        street = " ".join(m.group(1).split()).rstrip(",.")
        words = {w.lower().strip(".,") for w in street.split()[1:-1]}
        if words & _NOT_STREET_WORDS:
            continue
        candidates.append((street, m.group(2) if _unit_ok(m.group(2)) else None, m.end()))
        break
    if not candidates:
        bare = _address_no_suffix(text)
        if bare:
            candidates.append((bare[0], None, bare[1]))
    for street, unit_in, end in candidates:
        out["address"] = street
        if unit_in:
            out["unit"] = unit_in
        tail = text[end:end + 120]
        cm = re.match(r"[ \t]*(?:,|\n)?[ \t]*(?:" + _UNIT + r"[ \t]*(?:,|\n)?[ \t]*)?([A-Z][A-Za-z.'-]+(?: [A-Z][A-Za-z.'-]+){0,3}),?[ \t]+([A-Z]{2})(?:[ \t]+(\d{5})(?:-\d{4})?)?\b", tail)
        if cm and cm.group(3) in _STATES:
            if cm.group(1) and not out.get("unit") and _unit_ok(cm.group(1)):
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
        if um and not re.match(r"[A-Z]$", um.group(1)) and _unit_ok(um.group(1)):
            out["unit"] = um.group(1)
    if "unit" not in out:
        # "2 bed in unit 2C at 123 Main St", "Unit B." before or after the address: a word like unit or apt names it
        for um in re.finditer(r"(?<![\w-])(?:unit|apt\.?|apartment|suite|ste\.?)\s*#?\s*([A-Za-z]?\d{1,5}[A-Za-z]?(?:-\d{1,3})?|[A-Z])\b", text, re.I):
            val = um.group(1)
            if (val.isalpha() and not val.isupper()) or not _unit_ok(val):
                continue  # "unit a few" is not a unit, and a lone direction is not one either
            out["unit"] = val
            break
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


def _name_segment(line: str) -> str:
    """The name part of a long first line: "Riverside Lofts Unit 4B - 2 bed 2 bath ..., 123 Main St" gives "Riverside Lofts Unit 4B"."""
    if len(line) <= 90:
        return line
    return re.split(r"\s+[-|\u2013\u2014]\s+|,\s+(?=\d)|\.\s+(?=[A-Z$\d])", line, maxsplit=1)[0][:90].strip()


def _building_name(text: str) -> str:
    for line in text.splitlines()[:30]:
        line = _name_segment(" ".join(line.strip(" \t|\u2022\u00b7*#").split()))
        if not line or len(line) > 90 or _SITE_LINE.match(line):
            continue
        m = _BUILDING.match(line) or _AT_BUILDING.search(line)
        if m:
            name = m.group(1).strip()
            if len(name) >= 6 and not re.match(r"(?:The\s+)?(?:Apartments?|Court|Place|Park|Square)$", name):
                return name
    return ""


_TITLE_SUFFIX = re.compile(r"\s*[-|:,]\s*(?:\$\s?[\d,.]+[kK]?(?:\s*/\s*mo\w*)?|(?:studio|\d+(?:\.\d)?\s*(?:-\s*\d+\s*)?(?:bed(?:room)?s?|bds?|brs?|bath(?:room)?s?|bths?|ba|sq\.?\s?ft\.?|sqft|sf))\b)[^\n]*$", re.I)


def _clean_title(title: str) -> str:
    """Drop a trailing " - 2 bed 1 bath" or " | $1,500/mo" (facts, not part of the name). Never leaves it empty."""
    out = title
    for _ in range(3):
        cut = _TITLE_SUFFIX.sub("", out).strip(" -|:,")
        if cut == out or len(cut) < 3:
            break
        out = cut
    return out


_ALL_CAPS_KEEP = ("LLC", "II", "III", "IV", "NE", "NW", "SE", "SW", "UIUC", "BR", "BA", "HOA", "USA", "UW", "UC", "MIT", "NYC", "SF", "LA")
_LABEL_LINE = re.compile(
    r"^(?:rent|monthly rent|deposit|security deposit|price|asking price|list price|taxes|tax|property tax(?:es)?|hoa(?: fees?| dues)?|pets?|pet policy|"
    r"pet rent|pet fee|utilities|utils|fees?|application fee|admin fee|parking|lease|lease term|term|available|availability|laundry|sq\.? ?ft|"
    r"square feet|beds?|baths?|contact|phone|year built|move[- ]in|cost|total|amenities|features|description|location|address|city|"
    r"neighborhood|heat|cooling|appliances|rates?)\b[ \t]*(?::|=|\$|-[ \t])", re.I)
_LABEL_NUMBER = re.compile(r"^(?:rent|deposit|security deposit|price|taxes|hoa|fees?)\b[ \t]+[\d$]", re.I)
_MONEY_LINE = re.compile(r"^(?:\$|\u20ac|\u00a3|\d[\d,.]*[ \t]*(?:/|per|a)[ \t]*(?:mo|month))", re.I)
_PET_LINE = re.compile(r"^(?:no[ \t]+)?(?:pets?|dogs?|cats?|animals?)\b", re.I)


def _title(text: str, found: dict[str, Any]) -> str:
    title = _clean_title(_title_raw(text, found)).strip(" ,;:-|\u2013\u2014")
    letters = [c for c in title if c.isalpha()]
    if len(letters) >= 4 and title.upper() == title:
        title = re.sub(r"[A-Za-z][A-Za-z']*", lambda m: m.group(0) if m.group(0) in _ALL_CAPS_KEEP else m.group(0).capitalize(), title)
        title = re.sub(r"^The\b", "The", title)
    return title


def _not_a_name(line: str) -> bool:
    """A line that is a field ("Rent $2", "Deposit: 1.5x rent", "Pets: dogs ok"), a money amount or a pet rule, never a title."""
    return bool(_LABEL_LINE.match(line) or _LABEL_NUMBER.match(line) or _MONEY_LINE.match(line) or _PET_LINE.match(line))


def _title_raw(text: str, found: dict[str, Any]) -> str:
    """A short title: the building name, else the first line of the paste that reads like a name or heading, else the street
    address. A site name (Zillow, Realtor.com) is never the title."""
    named = re.search(r"^[ \t*#|]*(?:property|community|building|listing|apartment)(?: name)?[ \t]*[:\-][ \t]*([A-Z][^\n]{2,60})$", text, re.M | re.I)
    if named and not re.search(r"\d", named.group(1)[:3]):
        return named.group(1).strip()
    building = _building_name(text)
    if building:
        return building
    lines = [" ".join(x.strip(" \t|\u2022\u00b7*#").split()) for x in text.splitlines()[:25]]
    lines = [x for x in lines if x]
    if len(lines) >= 2 and re.fullmatch(r"[A-Z][A-Za-z'&-]{3,25}", lines[0]) and lines[0].lower() not in _UI_WORDS and not _SITE_LINE.match(lines[0]) \
            and _ADDRESS.match(lines[1]):
        return lines[0]  # a one-word name on its own line above the address
    for raw_line in text.splitlines()[:25]:
        line = " ".join(raw_line.strip(" \t|\u2022\u00b7*#").split())
        if " | " in line:  # "LAKESHORE VILLAS | Sunny 3BR/2BA house, fenced yard": the first part that is not a fact is the name
            parts = [x.strip() for x in line.split(" | ")]
            line = next((x for x in parts if len(x) >= 3 and not _not_a_name(x) and not _is_fact_line(x)), "")
        line = _name_segment(line)
        if not line:
            continue
        low = line.lower().rstrip(":")
        if _not_a_name(line):
            continue
        if not 4 <= len(line) <= 90 or low in _UI_WORDS or line.startswith(("http", "$", "www.", "Skip to")) or _SITE_LINE.match(line):
            continue
        am = _ADDRESS.match(line)
        if am and found.get("address"):
            return found["address"]
        head = re.split(r"\s+[-|\u2013\u2014]\s+", line, maxsplit=1)
        if len(head) == 2 and found.get("address") and found["address"] in head[1] and re.fullmatch(r"[A-Za-z][A-Za-z '&.]{1,40}", head[0]):
            return head[0].strip()  # "Name - Unit 4C, 3329 N Broadway": the name is the title, the street is the address
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
    doubt = _try(lambda: _pets_doubt(text)) or ""
    if doubt:
        facts.append(doubt)  # pets stays empty (unknown), so a pet owner sees "Fits, but check"
    else:
        put("pets", _try(lambda: _pets(text)))
        soft = _try(lambda: _pets_soft_note(text)) or ""
        if soft:
            facts.append(soft)
    deposit_amount, fee_text = _try(lambda: _pet_deposit(text)) or (None, text)
    put("pet_deposit", deposit_amount)
    for key, value in (_try(lambda: _pet_fees(fee_text)) or {}).items():
        put(key, value)
    side, dep_text = _try(lambda: _pet_side_deposits(fee_text, out.get("price") if isinstance(out.get("price"), (int, float)) else None)) or ({}, fee_text)
    for key, value in side.items():
        if key not in out and not (key == "pet_fee" and "pet_fee" in out):
            put(key, value)
    if out.get("pet_rent") and re.search(r"\$\s?\d{1,4}(?:\.\d\d)?\s*(?:(?:/\s*mo(?:nth)?|per month|monthly|a month)\s*)?(?:per|each|/)\s*(?:pet|dog|cat|animal)\b", text, re.I):
        facts.append(f"Pet rent is ${out['pet_rent']:,.0f} for each pet, so with more than one pet it adds up.")
    nr = re.search(r"\$\s?(\d{1,4}(?:,\d{3})?)(?:\.\d\d)?[ \t]*(?:non[- ]?refundable[ \t]+)?pet[ \t]+deposit\b[^.\n;]{0,25}?non[- ]?refundable|\bnon[- ]?refundable[ \t]+\$\s?(\d{1,4}(?:,\d{3})?)[ \t]*pet[ \t]+deposit", text, re.I)
    if nr and out.get("pet_fee") and not out.get("pet_deposit"):
        facts.append(f"The ${float((nr.group(1) or nr.group(2)).replace(",", "")):,.0f} pet deposit is non-refundable, so it is counted as a pet fee, not as money you get back.")
    for key, value in (_try(lambda: _pet_limit_fields(text)) or {}).items():
        put(key, value)
    utext = _util_text(text)
    included = _try(lambda: _utilities(utext)) or ""
    pays = _try(lambda: _tenant_pays(utext)) or ""
    roles = _try(lambda: _utility_roles(utext)) or {"tenant": [], "landlord": [], "billed": [], "amount": None}
    roles["landlord"] = [w.strip() for w in _ordered_utilities(list(roles["landlord"])).split(",") if w.strip()]
    left_out = _try(lambda: _ordered_utilities(_all_except(utext.lower()))) or ""
    if left_out:
        roles["landlord"] = roles["landlord"] + [w.strip() for w in left_out.split(",") if w.strip() and w.strip() not in roles["landlord"]]
        pays = _ordered_utilities([w for w in list(_ALL_UTILITIES) if w not in left_out.split(", ")] + [w.strip() for w in pays.split(",") if w.strip() and w.strip() not in left_out.split(", ")])
    if roles["tenant"] or roles["landlord"]:
        # The clause reading wins where the older sentence-wide reading put a tenant's utility in the included list.
        mine = _ordered_utilities(list(roles["tenant"]))
        pays = _ordered_utilities([w.strip() for w in (pays + ", " + mine).split(",") if w.strip() and w.strip() not in roles["landlord"]])
        pay_set = {w.strip() for w in pays.split(",")}
        keep = [w.strip() for w in included.split(",") if w.strip()] if included != "all" else []
        included = included if included == "all" else _ordered_utilities(
            [w for w in keep + list(roles["landlord"]) if w not in pay_set])
    kept_out = _try(lambda: _ordered_utilities(_included_except(utext.lower()))) or ""
    if kept_out:
        # "All utilities included except electric": the rest is included, and the renter pays what is left out.
        gone = [w.strip() for w in kept_out.split(",") if w.strip()]
        included = _ordered_utilities([w for w in _ALL_UTILITIES if w not in gone])
        pays = _ordered_utilities([w.strip() for w in (pays + ", " + kept_out).split(",") if w.strip()])
    billed = _try(lambda: _billed_back(utext))

    def take_out_of_included(names: str) -> str:
        """A utility the tenant pays a billed-back amount for is not included: it goes in one list only."""
        nonlocal included
        gone = {w.strip() for w in names.split(",") if w.strip()}
        have = [w.strip() for w in included.split(",") if w.strip()] if included != "all" else list(_ALL_UTILITIES)
        hit = [w for w in have if w in gone]
        if hit:
            included = _ordered_utilities([w for w in have if w not in gone])
        return ", ".join(hit)

    if billed:
        moved = take_out_of_included(billed[0])
        pays = _ordered_utilities([w.strip() for w in (pays + ", " + billed[0]).split(",") if w.strip()])
        put("utilities_estimate", billed[1])  # their own monthly figure, so it is counted in the cost
        facts.append(f"{billed[0].capitalize()} are billed back at ${billed[1]:,.0f}/month, counted as your utilities estimate.")
        if moved:
            facts.append(f"The listing also says {moved} is included, but a billed-back amount means you pay it, so it is not counted as included.")
    elif roles["billed"]:
        names = _ordered_utilities(list(roles["billed"]))
        moved = take_out_of_included(names)
        if moved:
            facts.append(f"The listing also says {moved} is included, but it is billed back to you, so it is not counted as included.")
        pays = _ordered_utilities([w.strip() for w in (pays + ", " + names).split(",") if w.strip()])
        if roles["amount"]:
            put("utilities_estimate", roles["amount"])
            facts.append(f"{names.capitalize()} are billed back at about ${roles['amount']:,.0f}/month, counted as your utilities estimate.")
        else:
            facts.append(f"{names.capitalize()} are billed back to you, but the listing gives no amount. Add a utilities estimate once you know it.")
    included, pays = _reconcile_utilities(included, pays, facts)
    put("utilities_included", included)
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
        dep_src, wired = _split_wired_deposit(dep_text)
        best_case, dep_src = _try(lambda: _best_case_deposit(dep_src)) or (None, dep_src)
        if best_case:
            facts.append(f"The listing gives a best-case deposit of ${best_case:,.0f} with approved credit. The deposit is not saved, because it may be more for you, so ask what the deposit will be.")
        if wired:
            facts.append("The listing asks for a deposit by wire. A wire can't be taken back, so the deposit is left blank. Don't send money before you have toured the place.")
        dep = _money_after(dep_src, r"(?:security |refundable |damage |rental )?deposits?", hi=50000, skip_before=r"(?:pet|parking|holding|reservation|key|application|garage)\s*$")
        dep = [v for v in dep if v is not None]
        rent_now = out.get("price")
        by_months = _deposit_in_months(text)
        if dep:
            put("deposit", dep[0])
        elif by_months and isinstance(rent_now, (int, float)) and 200 <= rent_now <= 30000 and not _SALE_WORDS.search(text):
            put("deposit", by_months * float(rent_now))  # "security deposit one month", "deposit equal to one month's rent"
        elif by_months and not _SALE_WORDS.search(text):
            facts.append(f"The listing says the security deposit is {by_months:g} month{'s' if by_months != 1 else ''} of rent, but the rent was not read, so the deposit is left empty. Fill it in once you know the rent.")
        elif re.search(r"\b(?:no|zero|\$0) (?:security )?deposit|\bdeposit\s*[:\-]?\s*(?:\$0|none|waived|zero)\b", text, re.I):
            put("deposit", 0.0)
        app = _money_after(text, r"application(?: processing)? fees?|app(?:lication)? fee|screening fee|background check fee", hi=1000)
        per_adult_fee = _try(lambda: app_fee_per_adult(text))
        if app:
            put("application_fee", app[0])
        elif per_adult_fee:
            put("application_fee", per_adult_fee)
        elif re.search(r"\b(?:no|free|zero|\$0|waived)\s+app(?:lication)?[ \t]+(?:fee|processing)|\bapp(?:lication)? fee\s*[:\-]?\s*(?:\$0|none|waived|free)\b|\bapplication fee\s*[:\-]?\s*(?:\$0|none|waived|free)\b", text, re.I):
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
        counted, listed = _try(lambda: _extra_monthly(text)) or ([], [])
        for label, v in counted:
            monthly += v
            facts.append(f"${v:,.0f}/month extra for {label} is counted in other monthly fees. If it is optional, take it out.")
        storage = _try(lambda: _storage_fees(text)) or []
        listed = [(l, v) for l, v in listed if not re.search(r"storage|locker", l)]
        for label, v, required in storage:
            if required:
                monthly += v
                facts.append(f"{label[:1].upper() + label[1:]} is ${v:,.0f}/month and the listing says it is required, so it is counted in other monthly fees.")
            else:
                facts.append(f"{label[:1].upper() + label[1:]} is ${v:,.0f}/month. It is not counted in the cost because it looks optional. Add it to other monthly fees if you need it.")
        for label, v in listed:
            facts.append(f"{label[:1].upper() + label[1:]} is ${v:,.0f}/month extra. It looks optional, so it is not counted in the cost. Add it to other monthly fees if you need it.")
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
            if out.get("application_fee"):
                out["application_fee_per_adult"] = 1  # the cost multiplies the fee by the adults who apply
        credit = _try(lambda: _seller_credit(text))
        if credit:
            put("seller_credit", credit)
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
            rent_price = out.get("price")
            rental = (isinstance(rent_price, (int, float)) and rent_price < 20000 and not _SALE_WORDS.search(text)) \
                or bool(re.search(r"\b(?:taxes?|tax)\b[^.\n;]{0,60}\b(?:included in|part of|covered by|paid (?:by|in))\s+(?:the\s+)?(?:rent|lease)\b|\brent includes?\b[^.\n;]{0,40}\btax", text, re.I))
            if rental:
                facts.append(f"The listing mentions property taxes of ${tax:,.0f} a year, but this looks like a rental, so property tax is not filled in.")
            else:
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
    label = r"(?:amenity|trash|valet trash|trash valet|valet waste|pest(?: control)?|package|technology|tech|community|convenience|internet|cable|smart home)(?:\s*(?:fee|fees|charge|package|service))?"
    back = re.compile(r"^[^.\n;$]{0,14}?\b(?:billed|charged|passed)\s*(?:back|through|on)\b", re.I)
    for m in re.finditer(r"\b" + label + r"[ \t:\-=]{0,4}\$\s?(\d{1,4})(?:\.\d\d)?\s*(?:/\s*mo(?:nth)?|per month|monthly|a month)", text, re.I):
        if re.match(r"(?:trash|internet|cable)", m.group(0), re.I) and back.match(text[m.end():]):
            continue  # a billed-back utility is the utilities estimate, never another monthly fee
        found.append(float(m.group(1)))
    for m in re.finditer(r"\b(?:valet[ -]trash|trash[ -]valet|valet[ -]waste)(?:\s*(?:fee|service|charge))?[ \t:\-=]{0,4}\$\s?(\d{1,4})(?:\.\d\d)?(?![\d,]|\s*(?:/\s*mo|per month|monthly|a month|one[- ]time|deposit))", text, re.I):
        found.append(float(m.group(1)))  # "Valet trash $30": valet trash is always a monthly service
    for m in re.finditer(r"\$\s?(\d{1,4})(?:\.\d\d)?\s*(?:/\s*mo(?:nth)?|per month|monthly|a month)\s*(?:for\s+)?" + label + r"\b", text, re.I):
        if re.search(r"(?:trash|internet|cable)", m.group(0), re.I) and back.match(text[m.end():]):
            continue
        found.append(float(m.group(1)))
    return found


_MONTHLY_RE = r"(?:/\s*mo(?:nth)?\b|per\s+month|monthly|a\s+month|each\s+month)"


def _extra_monthly(text: str) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
    """Extra monthly charges written plainly: "$150 extra monthly for lawn and trash", "Storage locker extra $40 per month".
    Returns (counted, listed). Lawn, trash and similar services come with the unit, so they are counted as a monthly fee;
    storage, a locker or a pool pass can be turned down, so they are only listed (the person decides)."""
    counted: list[tuple[str, float]] = []
    listed: list[tuple[str, float]] = []
    optional = re.compile(r"storage|locker|pool|gym|club|garage|carport|parking|bike|wine|pet|dog|cat", re.I)
    pats = (r"\$\s?(\d{1,4})(?:\.\d\d)?\s*(?:extra\s+)?" + _MONTHLY_RE + r"?\s*extra\s*(?:" + _MONTHLY_RE + r")?\s*(?:for|to cover)\s+([A-Za-z][A-Za-z ,&/-]{2,40})",
            r"\b([A-Za-z][A-Za-z -]{2,30}?)\s+(?:is\s+)?extra\s*[:\-]?\s*\$\s?(\d{1,4})(?:\.\d\d)?\s*" + _MONTHLY_RE,
            r"\$\s?(\d{1,4})(?:\.\d\d)?\s*extra\s+(?:monthly|a\s+month|per\s+month|each\s+month)\s+(?:for\s+)?([A-Za-z][A-Za-z -]{2,30})")
    seen: set[tuple[str, float]] = set()
    for i, pat in enumerate(pats):
        for m in re.finditer(pat, text, re.I):
            amount, label = (float(m.group(2)), m.group(1)) if i == 1 else (float(m.group(1)), m.group(2))
            label = re.split(r"[.;\n]", label)[0].strip(" ,-").lower()
            label = re.sub(r"^(?:the|a|an|our|each)\s+", "", label)
            if not label or amount <= 0 or (label, amount) in seen or re.search(r"\b(?:deposit|rent)\b", label):
                continue
            seen.add((label, amount))
            (listed if optional.search(label) else counted).append((label, amount))
    return counted, listed


def _storage_fees(text: str) -> list[tuple[str, float, bool]]:
    """Storage lockers and units, however the price is written ("Storage locker $30 per month", "Storage locker: $30/mo",
    "optional storage locker available for $30/month"). Returns (label, monthly amount, required). It is only required
    when the same line says so (required, mandatory, must); otherwise it looks optional."""
    out: list[tuple[str, float, bool]] = []
    noun = r"(?:storage(?:\s+(?:locker|unit|space|cage|room))?|lockers?)"
    monthly = r"(?:/\s*mo(?:nth)?\b|per\s+month|monthly|a\s+month|each\s+month)"
    for line in re.split(r"\n|;|(?<=[a-z\)])\.(?=\s|$)", text):
        found: list[tuple[str, float]] = []
        for m in re.finditer(r"\b(" + noun + r")\b[^.\n;$]{0,45}?\$\s?(\d{1,4})(?:\.\d\d)?\s*" + monthly, line, re.I):
            if not re.search(r"deposit|one[- ]time|set[- ]?up", m.group(0), re.I):
                found.append((m.group(1), float(m.group(2))))
        for m in re.finditer(r"\$\s?(\d{1,4})(?:\.\d\d)?\s*" + monthly + r"\s*(?:for\s+)?(?:a\s+|the\s+)?(" + noun + r")\b", line, re.I):
            if re.search(r"\b(?:garage|carport|parking|spot|space|stall|covered)\b[^$]{0,30}$", line[:m.start()], re.I):
                continue  # "heated garage $110/mo storage lockers ...": the $110 is the garage, not the storage
            found.append((m.group(2), float(m.group(1))))
        required = bool(re.search(r"\b(?:required|mandatory|must|included in the (?:fees|charges))\b", line, re.I)) and not re.search(r"\bnot required\b|\boptional\b", line, re.I)
        for label, amount in found:
            if amount > 0 and all(amount != a for _l, a, _r in out):
                out.append((label.lower(), amount, required))
    return out


def listing_uncounted_fees(text: str) -> list[str]:
    """Public: monthly fees the reader saw but did not count because they look optional, worded "storage locker $40/mo"."""
    try:
        text = _tidy(text or "")
        seen: dict[float, str] = {}
        for label, amount, required in _storage_fees(text):
            if not required:
                seen.setdefault(amount, label)
        for label, amount in _extra_monthly(text)[1]:
            if amount not in seen and not re.search(r"storage|locker|parking|garage|carport", label):
                seen[amount] = label
        return [f"{label} ${amount:,.0f}/mo" for amount, label in seen.items()]
    except Exception:
        return []
