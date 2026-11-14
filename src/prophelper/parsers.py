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
from datetime import date, timedelta
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
    r"(?:(?:\d{1,3}(?:st|nd|rd|th)|[A-Za-z][A-Za-z.'-]*)\s+){0,4}?" + _STREET + r"\b\.?"
    r"(?:[ \t]+(?:NE|NW|SE|SW|N|S|E|W)\b\.?(?=[ \t]*(?:[,\n#\d]|$|(?:apt|apartment|unit|suite|ste|near|with|and|\$)\b|\$|(?-i:[A-Z][A-Za-z.'-]+(?: [A-Z][A-Za-z.'-]+){0,3},?[ \t]+[A-Z]{2}\b))))?)"
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
_LEASE_CONDITION = re.compile(r"\s*(?:/\s*mo\w*\s*)?(?:with|for|on|if you sign|when you sign)\s+(?:a\s+|an\s+)?(\d{1,2})[- ]?(?:month|mo)s?\b", re.I)


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
        if fee and re.search(r"\b(?:no\s+pets?|pets?\s+(?:are\s+)?(?:not\s+)?(?:allowed|permitted|ok)|service\s+animals?|except)\b", clause, re.I) \
                and not re.search(r"\b(?:deposit|fees?|rent|monthly)\b", clause, re.I) and not _FEE_AFTER_STRICT.match(after):
            fee = False  # "NO PETS ALLOWED EXCEPT SERVICE ANIMALS - $2,100": a pet rule, and the amount is the rent
        new_price = bool(re.search(r"(?:reduced|dropped|lowered|cut|now|marked down)\s+(?:price\s+)?to\s*$", clause, re.I))
        if _BR_MARK.match(tail):
            fee = bool(re.search(r"\b(?:deposit|fee|pet|hoa|tax)\s*[:\-]?\s*$", clause, re.I))
        elif marker == "monthly":
            fee = bool(_FEE_BEFORE.search(clause[-22:])) and not _RENT_LABEL.search(clause[-14:]) or bool(_FEE_AFTER_MONTHLY.match(tail))
        elif not fee:
            fee = bool(_FEE_AFTER_STRICT.match(tail)) and not re.match(r"\s*\+\s*(?:all\s+)?(?:the\s+)?utilit", tail, re.I)  # "$1,150 + utilities" is the rent
        if fee and value >= 20000 and marker == "" and re.match(r"^\s*(?:hoa|assoc\w*|dues|condo fee)", tail, re.I):
            fee = False  # "$250,000 HOA $310 per month": the HOA label belongs to the next amount, no HOA fee is that big
        if re.match(r"\s*(?:total\s+)?(?:(?:is\s+)?(?:due\s+)?to\s+move[- ]?in\b|(?:is\s+)?due\s+(?:at|before|on)\s+(?:lease\s+)?(?:signing|move[- ]?in)\b|total\s+move[- ]?in\b)", tail, re.I):
            fee = True  # "$2,100 total to move in" is what you pay to get in, never the rent
        if new_price:  # "reduced to $318,500" is the new asking price, "reduced $6,500" is the size of the cut
            fee = False
        conditional = bool(re.search(r"(?:reduced|dropped|lowered|cut|drops?|now|as low as|marked down)\s+(?:price\s+)?(?:down\s+)?to\s*$", clause, re.I)
                           and _LEASE_CONDITION.match(after))
        out.append({"value": value, "start": m.start(), "end": m.end(), "marker": marker, "range": is_range, "fee": fee,
                    "labelled": (new_price or bool(_RENT_LABEL.search(clause[-24:]))) and not conditional, "clause": clause.lower(),
                    "conditional": conditional})
    return out


_BUY_PRICE_LABEL = re.compile(r"(?:\blist(?:ed|ing)?(?:[ \t]+price)?(?:[ \t]+(?:at|for))?|\bprice|\basking(?:[ \t]+price)?|\boffered[ \t]+at|\bfor[ \t]+sale(?:[ \t]+at|[ \t]+for)?|\bnow|\bsale[ \t]+price|\bpurchase[ \t]+price|\breduced[ \t]+to)[ \t:\-=(]*$", re.I)
_BUY_PRICE_NOT = re.compile(r"closing|credit|concession|assess|down[ \t]*payment|seller|reduced[ \t]+from|\bwas\b|tax|hoa|zestimate|estimated|apprais|payment|loan|mortgage|earnest|deposit|commission|\bfee|dues|rent", re.I)


def _buy_price(text: str) -> float | None:
    """The asking price of a home for sale: the largest clearly stated sale amount (in the title line, or after "listed at",
    "price", "asking"), never a fee, tax, HOA, rent or a seller credit. None when no amount is clearly a sale price."""
    first = next((ln for ln in text.split("\n") if ln.strip()), "")
    first_start = text.find(first) if first else -1
    best: float | None = None
    for a in _amounts(text):
        if a["value"] < 20000 or a["fee"] or a.get("conditional") or a["marker"]:
            continue
        line_start = text.rfind("\n", 0, a["start"]) + 1
        before = text[line_start:a["start"]]
        after = text[a["end"]:a["end"] + 30].split("\n")[0]
        if re.match(r"\s*(?:/\s*(?:mo|month|yr|year)\b|per\s+(?:mo|month|yr|year)\b|a\s+(?:month|year)\b|monthly|annual)", after, re.I):
            continue
        near = before[-30:] + " " + after[:20]
        label = bool(_BUY_PRICE_LABEL.search(before))
        in_title = first_start >= 0 and first_start <= a["start"] <= first_start + len(first)
        if not (label or in_title):
            continue
        if _BUY_PRICE_NOT.search(near) and not label:
            continue
        if _BUY_PRICE_NOT.search(before[-12:]) and not _BUY_PRICE_LABEL.search(before):
            continue
        if best is None or a["value"] > best:
            best = a["value"]
    return best


_DASH_PRICE_LINE = re.compile(r"^[ \t*#|]*(?P<head>[^\n$]*?\b(?:studio|\d\s*(?:br|bd|bed(?:room)?s?)|(?:one|two|three|four)[- ]bed(?:room)?s?|starting[ \t]+at|starts[ \t]+at)\b[^\n$]*?)"
                              r"[ \t]*[-|\u2013\u2014:][ \t]*(?P<start>(?:starting[ \t]+at|starts[ \t]+at|from)[ \t]*)?\$[ \t]?(?P<n>\d{1,3}(?:,\d{3})+|\d{3,5})(?:\.\d\d)?[ \t]*(?:/[ \t]*(?:mo|month)\b|per[ \t]+month|a[ \t]+month|monthly)?[ \t.]*$"
                              r"|^[ \t*#|]*[^\n$]*?[-|\u2013\u2014][ \t]*(?P<start2>starting[ \t]+at|starts[ \t]+at)[ \t]*\$[ \t]?(?P<n2>\d{1,3}(?:,\d{3})+|\d{3,5})(?:\.\d\d)?[ \t]*(?:/[ \t]*(?:mo|month)\b|per[ \t]+month|a[ \t]+month|monthly)?[ \t.]*$",
                              re.I | re.M)


def _dash_title_price(text: str) -> tuple[float, bool] | None:
    """"Foundry Row - 1 Bedroom - $1,575" or "Foundry Row - Starting at $1,575": the one price on a dash-separated title line.
    Returns (price, starting_at). None when the text has more than one such line with different prices (a floor plan list)."""
    found: dict[float, bool] = {}
    for m in _DASH_PRICE_LINE.finditer(text):
        n = m.group("n") or m.group("n2")
        value = _num(n)
        if not 300 <= value <= 30000:
            continue
        found[value] = found.get(value, False) or bool(m.group("start") or m.group("start2"))
    if len(found) != 1:
        return None
    value, starting = next(iter(found.items()))
    return value, starting


def _price(text: str) -> float | None:
    """The monthly rent if the text gives one, else the asking price of a home for sale."""
    amounts = [a for a in _amounts(text) if not a["fee"] and a["marker"] != "per bed" and not a.get("conditional")]
    for a in amounts:  # "$1,495/mo", "$1500 / 1br"
        if a["marker"] == "monthly" and 200 <= a["value"] <= 30000:
            return a["value"]
    sale_text = bool(_SALE_WORDS.search(text))
    for a in amounts:  # "Rent: $1,495", "Monthly rent" on the line above
        if a["labelled"] and 200 <= a["value"] <= 30000 and not (sale_text and a["value"] >= 20000):
            return a["value"]
    dash = _dash_title_price(text)
    if dash and not sale_text and not any(a["value"] >= 20000 for a in amounts):
        return dash[0]
    big = [a for a in amounts if a["value"] >= 20000]
    if big and (sale_text or not _RENT_WORDS.search(text)):
        for a in big:
            if a["labelled"]:
                return a["value"]
        return big[0]["value"]
    if big and not any(300 <= a["value"] <= 20000 for a in amounts):
        return big[0]["value"]
    m = re.search(r"(?<![\d.,$#/-])\b(\d{1,2},\d{3}|\d{3,5})\s*(?:dollars|bucks|usd)\s*(?:a|per|/|each|every)\s*(?:month|mo)\b", text, re.I)
    if m and 200 <= _num(m.group(1)) <= 30000:  # "1400 dollars a month"
        return _num(m.group(1))
    m = re.search(r"\b(?:rent|price|asking)\b[^$\d\n]{0,20}?(\d{1,2},\d{3}|\d{3,5})\b(?!\s*(?:sq|sf|ft|bed|\d))", text, re.I)
    if m and 200 <= _num(m.group(1)) <= 30000:  # a rent written without a dollar sign
        return _num(m.group(1))
    if _RENT_WORDS.search(text) and not sale_text:
        for a in amounts:
            if 300 <= a["value"] <= 20000:
                return a["value"]
    m = re.search(r"^[ \t*#]*no[ \t]+(?:pets?|smoking|dogs?|cats?|animals?)\b[^\n$]*?[-|][ \t]*\$\s?(\d{1,2},\d{3}|\d{3,5})(?:\.\d\d)?[ \t]*$", text, re.I | re.M)
    if m and not sale_text and 300 <= _num(m.group(1)) <= 20000:  # "NO PETS ALLOWED EXCEPT SERVICE ANIMALS - $2,100"
        return _num(m.group(1))
    return None


_DISCOUNTS = (
    re.compile(r"\$\s?\d[\d,]*(?:\.\d\d)?[ \t]+off\b[^.\n;!]{0,40}?\b(?:first|1st|last|month|rent|move[- ]?in|lease|signing)[^.\n;!]{0,25}", re.I),
    re.compile(r"\b\d{1,2}[ \t]*%[ \t]+off\b[^.\n;!]{0,40}?\b(?:first|1st|last|month|rent|move[- ]?in|lease|signing)[^.\n;!]{0,25}", re.I),
    re.compile(r"\b(?:first|1st|last)[ \t]+month(?:'s)?(?:[ \t]+rent)?[ \t]+(?:is[ \t]+)?(?:half|\d{1,2}[ \t]*%)[ \t-]*off\b[^.\n;!]{0,40}", re.I),
    re.compile(r"\b(?:half|\d{1,2}[ \t]*%)[ \t-]*off[ \t]+(?:the[ \t]+)?(?:first|1st|last)[ \t]+month[^.\n;!]{0,40}", re.I),
)
_REDUCED_FROM = re.compile(r"\b(?:reduced|dropped|lowered|cut|marked down|price drop(?:ped)?)[ \t]+(?:to[ \t]+\$\s?\d[\d,]*(?:\.\d\d)?[ \t]+)?from[ \t]+\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?", re.I)


_WAS_PRICE = re.compile(r"\b(?:was|previously|formerly|originally)[ \t:]+\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?", re.I)


def _discount_notes(text: str, price: float | None) -> list[str]:
    """One-time discounts ("$500 off first month's rent", "50% off first month") and a price cut ("Reduced from $2,750"). They are
    notes only: a one-time deal is not taken off the monthly rent, and an old price is never the rent."""
    notes: list[str] = []
    seen: list[tuple[int, int]] = []
    for pat in _DISCOUNTS:
        for m in pat.finditer(text):
            if any(m.start() < e and s < m.end() for s, e in seen):
                continue
            seen.append((m.start(), m.end()))
            phrase = " ".join(m.group(0).split()).rstrip(" ,:-").replace('"', "'")
            notes.append(f'The listing offers a discount ("{phrase}"). It is a one-time deal, so it is not taken off the monthly rent. Ask what you have to do to get it.')
            break
        if len(notes) >= 2:
            break
    m = _REDUCED_FROM.search(text)
    if not m and price is not None:
        wm = _WAS_PRICE.search(text)  # "Rent: $3,200 (was $3,400)"
        if wm and _num(wm.group(1)) > price:
            m = wm
    if m:
        old = f"${_num(m.group(1)):,.0f}"
        if price is not None:
            notes.append(f"The listing says the price was cut from {old}. The old price is not used, only the current rent that was read.")
        else:
            notes.append(f"The listing says the price was cut from {old}. That is the old price, so it is not used as the rent. Ask what the rent is now.")
    return notes


def _price_notes(text: str, price: float | None = None) -> list[str]:
    """Plain notes about a rent that depends on something: "Reduced to $3,250 with 12 month lease", "1 month free". They never change the price."""
    notes: list[str] = _discount_notes(text, price)
    for a in _amounts(text):
        if a.get("conditional"):
            months = _LEASE_CONDITION.match(text[a["end"]:text.find("\n", a["end"]) if text.find("\n", a["end"]) >= 0 else len(text)])
            if months:
                notes.append(f"The listing says the rent drops to ${a['value']:,.0f} with a {months.group(1)} month lease. Ask if that applies to you.")
    m = re.search(r"\b(?:(first|last|one|two|three|\d{1,2})(?:st|nd|rd|th)?[ \t-]+months?(?:'s)?[ \t]+(?:of[ \t]+rent[ \t]+)?(?:rent[ \t]+)?free|(?:up to[ \t]+)?(?:one|two|three|\d{1,2})[ \t]+weeks?[ \t]+free|free[ \t]+(?:first|1st|one|two|\d{1,2})[ \t-]*months?)\b", text, re.I)
    if m:
        notes.append(f"The listing offers a rent concession (\"{' '.join(m.group(0).split())}\"). It is a one-time deal, so it is not taken off the rent. Ask what you have to do to get it.")
    return notes


_ONES = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
         "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_NUM_WORD_PHRASE = r"(?:(?:" + "|".join(list(_ONES) + list(_TENS) + ["hundred", "thousand", "and"]) + r")(?:[ \t]+|-))+"


def _words_to_number(phrase: str) -> int | None:
    """"three thousand two hundred fifty" -> 3250. None when the words are not a plain number."""
    total, current, seen = 0, 0, False
    for w in re.split(r"[ \t-]+", phrase.lower().strip()):
        if not w or w == "and":
            continue
        if w in _ONES:
            current += _ONES[w]
        elif w in _TENS:
            current += _TENS[w]
        elif w == "hundred":
            current = max(current, 1) * 100
        elif w == "thousand":
            total += max(current, 1) * 1000
            current = 0
        else:
            return None
        seen = True
    return total + current if seen else None


def _worded_price(text: str) -> tuple[float | None, str]:
    """A rent written in words: "three thousand two hundred fifty dollars a month" or "dollars a month: 2,380".
    Returns (rent or None, a plain note when something looked like a rent but was not clear)."""
    m = re.search(r"\b(" + _NUM_WORD_PHRASE + r")dollars?[ \t]+(?:a|per|each|/)[ \t]*(?:month|mo)\b", text, re.I)
    if m:
        n = _words_to_number(m.group(1))
        if n and 200 <= n <= 30000:
            return float(n), ""
        return None, f'The listing gives a rent in words ("{" ".join(m.group(0).split())}"), but I could not read it as an amount. Ask what the rent is.'
    m = re.search(r"\b(?:rent|asking(?:[ \t]+(?:rent|price))?|price)\b[ \t]*(?:is|of|:|=)?[ \t]*(" + _NUM_WORD_PHRASE + r")(?:dollars?[ \t]+)?(?:a|per|each|/)[ \t]*(?:month|mo)\b", text, re.I)
    if m:  # "Rent is eleven hundred a month"
        n = _words_to_number(m.group(1).replace(" and ", " "))
        if n and 200 <= n <= 30000:
            return float(n), ""
        return None, f'The listing gives a rent in words ("{" ".join(m.group(0).split())}"), but I could not read it as an amount. Ask what the rent is.'
    m = re.search(r"\bdollars?[ \t]+(?:a|per|each)[ \t]+(?:month|mo)\b[ \t]*[:=\-][ \t]*\$?[ \t]*(\d{1,2},\d{3}|\d{3,5})(?:\.\d\d)?(?![\d,]|[ \t]*(?:sq|sf|ft|bed|br))", text, re.I)
    if m and 200 <= _num(m.group(1)) <= 30000:
        return _num(m.group(1)), ""
    return None, ""


def _rent_range(text: str, price: float | None) -> tuple[float, float] | None:
    """(low, high) when the rent that was read is only the low end of a written range ("$1,299 - $1,650 / mo")."""
    if price is None:
        return None
    for a in _amounts(text):
        if not a["range"] or a["fee"] or a["value"] != price:
            continue
        m = re.match(r"\s*\+?\s*(?:-|to)\s*\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?", text[a["end"]:], re.I)
        if m and _num(m.group(1)) > price:
            return price, _num(m.group(1))
    return None


_MOVE_IN_TOTAL = (
    re.compile(r"\bmove[- ]?in[ \t]+(?:cost|costs|total|price|charges?|money|amount)(?:[ \t]+(?:is|are|of))?[ \t]*[:=\-]?[ \t]*(?:about |around |approx\.? |~)?\$?[ \t]*(\d{1,3}(?:,\d{3})+|\d{3,5})(?:\.\d\d)?\b(?![ \t]*(?:/|per)[ \t]*(?:mo|month))", re.I),
    re.compile(r"\$[ \t]*(\d{1,3}(?:,\d{3})+|\d{3,5})(?:\.\d\d)?[ \t]+(?:total[ \t]+)?(?:to[ \t]+move[- ]?in|due[ \t]+(?:at|before)[ \t]+(?:lease[ \t]+)?(?:signing|move[- ]?in)|move[- ]?in[ \t]+total)\b", re.I),
)


def _move_in_total_notes(text: str) -> list[str]:
    """"Move-in cost 2200 total", "$2,100 total to move in": the all-in cash to get in. It is not the rent and it is not split into
    deposit and fees, so it only gets a note."""
    for pat in _MOVE_IN_TOTAL:
        m = pat.search(text)
        if m:
            return [f"The listing says it costs ${_num(m.group(1)):,.0f} in total to move in. That is not the monthly rent and it is not split into deposit and fees, "
                    "so it is not counted. Ask what it includes."]
    return []


def _holding_fee_notes(text: str) -> list[str]:
    """"Holding fee equal to one week's rent": a fee with no dollar amount, so it is a note, not a number."""
    m = re.search(r"\b(?:holding|reservation)[ \t]+(?:fee|deposit)\b[ \t]*(?:is[ \t]+)?(?:equal(?:s)?[ \t]+to|=|of)[ \t]+((?:one|two|a|1|2|half(?: a)?)[ \t]+(?:week|month)s?'?s?(?:'s)?[ \t]+(?:of[ \t]+)?rent)", text, re.I)
    if m:
        return [f"The listing asks for a holding fee equal to {' '.join(m.group(1).split())}. It is not counted in the cost, because no dollar amount is given. Ask if it is taken off what you owe at move-in."]
    return []


def _without_pet_one_time(text: str) -> str:
    """The text with "one time" hidden in lines about pets, so "Pets: Cats ok, $300 one time fee" stays a pet fee and is
    never read again as a move-in fee."""
    def fix(m: re.Match[str]) -> str:
        sentence = m.group(0)
        if re.search(r"\b(?:pets?|cats?|dogs?|animals?|kittens?|puppies)\b", sentence, re.I):
            return re.sub(r"\bone[- ]time\b", "pet-only", sentence, flags=re.I)
        return sentence
    # "Pets ok. One time fee $200.": a bare one-time fee in the sentence right after a pet sentence is the pet fee
    text = re.sub(_PET_THEN_ONE_TIME, lambda m: m.group(1) + "pet-only", text)
    return re.sub(r"[^.\n;]+", fix, text)


_PET_THEN_ONE_TIME = re.compile(r"(\b(?:pets?|cats?|dogs?|animals?)\b[^.\n;$]{0,40}[.;][ \t]*)(one[- ]time)(?=[ \t]+fee[ \t:\-]*\$)", re.I)


def _periodic_fee_notes(text: str) -> list[str]:
    """"Quarterly amenity fee $90", "Annual pet-friendly fee $120": a fee that is not charged every month. It has no field of its
    own, so it gets a note with the monthly share worked out, and it is not counted. HOA dues have their own reading."""
    notes: list[str] = []
    seen: set[float] = set()
    per_word = {"quarterly": ("quarter", 3), "annual": ("year", 12), "annually": ("year", 12), "yearly": ("year", 12)}
    for m in re.finditer(r"\b(quarterly|annual(?:ly)?|yearly)[ \t]+((?:[A-Za-z-]+[ \t]+){0,3}?)(?:fees?|charges?|assessments?)\b[ \t:\-=]*\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?(?![\d,])(?![ \t]*(?:/|per|a|each)[ \t]*(?:mo|month))", text, re.I):
        if re.search(r"hoa|association|tax|insurance|rent\b", m.group(2), re.I):
            continue
        n, label = _num(m.group(3)), " ".join(m.group(2).split())
        word, divisor = per_word[m.group(1).lower()]
        if n in seen or not 1 <= n <= 5000:
            continue
        seen.add(n)
        notes.append(f"The listing has a {m.group(1).lower() if m.group(1).lower() == 'quarterly' else 'yearly'} {label + ' ' if label else ''}fee of ${n:,.0f} (about ${n / divisor:,.0f} a month). "
                     f"It is not counted in the monthly cost. Ask if you have to pay it.")
    return notes


def _holding_fee_amount_notes(text: str) -> list[str]:
    """"Holding fee $200 to reserve": a one-time amount paid to hold the place. It is kept as a note, not counted."""
    m = re.search(r"\b(?:holding|reservation)[ \t]+(?:fee|deposit)\b[ \t:\-=]*(?:of[ \t]+)?\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?(?![\d,])|\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?[ \t]+(?:holding|reservation)[ \t]+(?:fee|deposit)\b", text, re.I)
    if not m:
        return []
    n = _num(m.group(1) or m.group(2))
    return [f"The listing asks for a ${n:,.0f} holding fee to reserve the place. It is one-time money and is not counted in the monthly cost. "
            "Ask if it comes off what you owe at move-in or if you lose it."]


def _credit_check_fee(text: str) -> tuple[float, str] | None:
    """"Credit check fee $35 each adult", "Credit check $38 per adult": (amount, who pays it), or None."""
    m = re.search(r"\bcredit[ \t]+(?:check|report)(?:[ \t]+fees?)?[ \t:\-=]*\$\s?(\d{1,4})(?:\.\d\d)?(?![\d,])[ \t]*(?:/|per|each|for[ \t]+(?:each|every))[ \t]*(adult|applicant|person|occupant|tenant|resident|roommate)s?\b", text, re.I) \
        or re.search(r"\$\s?(\d{1,4})(?:\.\d\d)?[ \t]*(?:credit[ \t]+(?:check|report))(?:[ \t]+fees?)?[ \t]*(?:/|per|each|for[ \t]+(?:each|every))[ \t]*(adult|applicant|person|occupant|tenant|resident|roommate)s?\b", text, re.I) \
        or re.search(r"\bcredit[ \t]+(?:check|report)(?:[ \t]+fees?)?[ \t:\-=]*\$\s?(\d{1,4})(?:\.\d\d)?(?![\d,])[ \t]*,?[ \t]*(?:charged[ \t]+)?(?:to[ \t]+)?(?:each|every)[ \t]+(adult|applicant|person|occupant|tenant|resident|roommate)\b", text, re.I)
    return (float(m.group(1)), m.group(2).lower()) if m else None


def _credit_check_plain(text: str) -> float | None:
    """"Credit check $25" with no word about who pays it: the application fee. None when the per-person form applies or nothing is said."""
    if _credit_check_fee(text):
        return None
    m = re.search(r"\bcredit[ \t]+(?:check|report)(?:[ \t]+fees?)?[ \t:\-=]*\$\s?(\d{1,4})(?:\.\d\d)?(?![\d,])(?![ \t]*(?:/|per|each|every|a[ \t]+(?:month|mo)|monthly))", text, re.I) \
        or re.search(r"(?<![\d,])\$\s?(\d{1,4})(?:\.\d\d)?[ \t]+(?:for[ \t]+(?:a[ \t]+)?)?credit[ \t]+(?:check|report)(?:[ \t]+fees?)?\b(?![ \t]*(?:/|per|each|every))", text, re.I)
    return float(m.group(1)) if m else None


def _renters_insurance_note(text: str) -> list[str]:
    """"Renter's insurance required": a cost that has no amount, so it is a note."""
    if re.search(r"\b(?:renter'?s?|tenant'?s?|renters)[ \t]+insurance\b[^.\n;]{0,30}\b(?:required|mandatory|is[ \t]+a[ \t]+must|needed|must[ \t]+(?:be|have))\b|\b(?:requires?|required|must[ \t]+(?:have|carry|show))\b[^.\n;]{0,20}\b(?:renter'?s?|tenant'?s?|renters)[ \t]+insurance\b", text, re.I) \
            and not re.search(r"\b(?:renter'?s?|tenant'?s?|renters)[ \t]+insurance\b[^.\n;]{0,20}\b(?:not|isn'?t|optional)\b", text, re.I):
        amt = re.search(r"\b(?:renter'?s?|tenant'?s?|renters)[ \t]+insurance\b[^.\n;$]{0,40}\$[ \t]?(\d[\d,]*(?:\.\d+)?)[ \t]*(?:/[ \t]*(?:mo|month)\b|per[ \t]+month|a[ \t]+month|monthly)", text, re.I)
        said = f" (${float(amt.group(1).replace(',', '')):,.0f}/month)" if amt else ""  # said once here, so the amount is not quoted again as a second note
        return [f"The listing says renter's insurance is required{said}. No cost is counted for it. Ask what coverage you need and what it costs."]
    return []


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
_BED_WORDS = {"one": 1.0, "two": 2.0, "three": 3.0, "four": 4.0, "studio": 0.0}
_BEDS_CONVERTED = re.compile(r"\b(\d{1,2})[ \t]*(?:bed(?:room)?s?|bds?|brs?)\b[^.\n;]{0,25}?\b(?:converted|conversion|reconfigured|changed|turned|made)[ \t]+(?:to|into)[ \t]+(?:a[ \t]+|an[ \t]+)?"
                            r"(\d{1,2}|one|two|three|four|studio)(?:[ \t]*(?:bed(?:room)?s?|bds?|brs?))?\b", re.I)


def _beds_converted(text: str) -> tuple[float, float] | None:
    """("2BR converted to 1 bed") -> (2, 1): the bedroom count the listing started with and the one it ends with."""
    m = _BEDS_CONVERTED.search(text)
    if not m:
        return None
    new = m.group(2).lower()
    now = _BED_WORDS[new] if new in _BED_WORDS else float(new)
    return float(m.group(1)), now


# "3/2 single family home": beds then baths, read only when a home word follows (a bare "3/2" could be a date)
_SLASH_HOME = re.compile(r"(?<![\d.,$/:-])\b(\d{1,2})[ \t]*/[ \t]*(\d(?:\.\d)?)(?![\d/.])(?=[ \t]*(?:br|ba|bd)?[ \t,-]*(?:single|house|home|condo|townhome|townhouse|duplex|apartment|apt|bungalow|ranch|villa|cottage|loft|flat)\b)")


_BED_NUM = r"(\d{1,2}|one|two|three|four|five|six|studio)"
_BEDS_CORRECTED = re.compile(r"\b" + _BED_NUM + r"[- ]?(?:bed(?:room)?s?|bdrms?|bds?|brs?)[ \t]*\?[ \t]*(?:no|nope|actually|wait|sorry)\b[ \t,.:;-]*(?:it'?s[ \t]+|its[ \t]+|a[ \t]+)?(?:[a-z]+[ \t]+)?" + _BED_NUM + r"[- ]?(?:bed(?:room)?s?|bdrms?|bds?|brs?)\b", re.I)


# "Updated 3 bedroom (actually 2 bed plus den)": a correction written in brackets or after a comma, with no question mark
_BEDS_CORRECTED_PAREN = re.compile(r"\b" + _BED_NUM + r"[- ]?(?:bed(?:room)?s?|bdrms?|bds?|brs?)\b[ \t]*[(,;:.\-\u2013\u2014]?[ \t]*(?:actually|correction|corrected(?:[ \t]+to)?|really|in fact|sorry[, ]+(?:it'?s)?)[ \t,:\-]*"
                                   r"(?:it'?s[ \t]+|its[ \t]+|a[ \t]+|an[ \t]+|only[ \t]+|just[ \t]+)?" + _BED_NUM + r"[- ]?(?:bed(?:room)?s?|bdrms?|bds?|brs?)\b", re.I)


def _beds_corrected(text: str) -> tuple[float, float] | None:
    """("One-bedroom? no, THREE bedroom duplex") -> (1, 3): the listing corrects itself, so the later count is the one it means.
    It can go down too: "Updated 3 bedroom (actually 2 bed plus den)" -> (3, 2)."""
    m = _BEDS_CORRECTED.search(text) or _BEDS_CORRECTED_PAREN.search(text)
    if not m:
        return None
    nums = []
    for g in (m.group(1), m.group(2)):
        g = g.lower()
        nums.append(_BED_WORDS[g] if g in _BED_WORDS else float({"five": 5, "six": 6}.get(g, g if g.isdigit() else 0)))
    return nums[0], nums[1]


def _beds(text: str) -> float | None:
    conv = _beds_converted(text)
    if conv:
        return conv[1]
    corrected = _beds_corrected(text)
    if corrected:
        return corrected[1]
    low = text.lower()
    hits: list[tuple[int, float]] = []
    for m in re.finditer(r"(?<![\d.,$/])\b(\d{1,2}(?:\.\d)?)[ \t]*(?:-[ \t]*\d{1,2}(?:\.\d)?[ \t]*)?(?:bed(?:room)?s?|bds?|brs?|bdrms?)\b(?!\s*(?:and breakfast|room only))", low):
        hits.append((m.start(), float(m.group(1))))
    for m in re.finditer(r"\b(?:bed(?:room)?s?|bds?)\s*[:\-]\s*(\d{1,2}(?:\.\d)?)\b", low):
        hits.append((m.start(), float(m.group(1))))
    for m in re.finditer(r"\b(\d)\s*(?:bd|br|bed)\s*[/|]\s*\d(?:\.\d)?\s*(?:ba|bth|bath)", low):
        hits.append((m.start(), float(m.group(1))))
    for m in _SLASH_HOME.finditer(low):  # "3/2 single family home"
        hits.append((m.start(), float(m.group(1))))
    for m in re.finditer(r"\b(one|two|three|four|five|six)[- ](?:bed(?:room)?s?|bdrms?|brs?)\b(?!\s*(?:and breakfast|room only))", low):
        hits.append((m.start(), float({"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}[m.group(1)])))
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
        if re.search(r"\b(?:bed(?:room)?s?|bds?|brs?)[ \t]*[:\-][ \t]*$", low[max(0, m.start() - 14):m.start()]):
            continue  # "Beds: 3 Baths: 1.5": the 3 belongs to the beds label
        hits.append((m.start(), float(m.group(1))))
    for m in re.finditer(r"\b(?:bed(?:room)?s?|bds?|brs?)[ \t]*/[ \t]*(\d{1,2}(?:\.\d)?)[ \t]*(?:bath(?:room)?s?|bths?|ba)\b", low):
        hits.append((m.start(), float(m.group(1))))  # "3 bedrooms/2 baths"
    for m in _SLASH_HOME.finditer(low):
        hits.append((m.start(), float(m.group(2))))
    for m in re.finditer(r"\bbath(?:room)?s?\s*[:\-]\s*(\d{1,2}(?:\.\d)?)\b", low):
        hits.append((m.start(), float(m.group(1))))
    for m in re.finditer(r"\b(one|two|three|four|five)[- ](?:bath(?:room)?s?|bths?)\b", low):
        hits.append((m.start(), float({"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}[m.group(1)])))  # "two bath"
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
            r"\b(?:sq\.?\s?ft\.?|square (?:feet|footage)|living area|floor area|size)\s*[:\-]\s*" + num,
            r"\b(?:sq\.?\s?ft\.?|sqft)[ \t]+" + num + r"\b(?![ \t]*(?:[/$%]|min|mi\b|ft\b|feet|blocks?|away))"]
    best: tuple[int, int] | None = None
    for pat in pats:
        for m in re.finditer(pat, low):
            if re.search(r"\blot\b|\blot size\b|acre", low[max(0, m.start() - 22):m.start()]):
                continue
            v = int(m.group(1).replace(",", ""))
            if 150 <= v <= 20000 and (best is None or m.start() < best[0]):
                best = (m.start(), v)
    return best[1] if best else None


_WASH = r"(?:w/?d|washers?|dryers?|washer\s*(?:/|and|&|\+)\s*dryer|laundry)"
_SHARED_LAUNDRY = re.compile(
    r"\b" + _WASH + r"\b[^.\n;|]{0,30}?\b(?:shared|communal|coin|common|per load|in (?:the )?(?:basement|building|bldg|complex|laundry room)|(?:in|on) (?:each|every) floor|on[- ]?site)\b"
    r"|\b(?:shared|communal|coin[- ]?op\w*|coin|common|community|building|bldg|basement|on[- ]?site)\s+" + _WASH + r"\b"
    r"|\$\s?\d+(?:\.\d\d)?\s*(?:per|/|a)\s*(?:load|wash)\b", re.I)


def _laundry(text: str) -> str:
    low = re.sub(r"\bw\s?&(?:amp;)?\s?d\b", "w/d", text.lower())  # "W&D in unit" is the same as "W/D in unit"
    low = re.sub(r"w/?d\s*(?:hook-?ups?|connections?)|washer\s*(?:/|and|&)?\s*dryer\s*(?:hook-?ups?|connections?)|laundry hook-?ups?", " hookups ", low)
    m = re.search(r"\blaundry(?: type| features?| facilit\w+)?\s*[:\-]\s*([^\n.;,]{0,40})", low)
    if m:
        v = m.group(1)
        if _SHARED_LAUNDRY.search(v) or re.search(r"shared|common|communal|building|bldg|basement|on[- ]?site|community|facilit|room|coin|center|laundromat|per load", v):
            return "in_building"  # "Laundry: Shared basement W/D, $2 per load" is never in the unit
        if re.search(r"in[- ]?(?:unit|home|suite)|inside|private|washer|w/d|full[- ]size", v):
            return "in_unit"
        if re.match(r"\s*(?:none|no\b|n/a)", v):
            return "none"
    in_unit = r"(?:in[- ]?(?:unit|home|suite|apartment|residence)\s*(?:washer|laundry|w/?d)|(?:washer\s*(?:/|and|&|\+)\s*dryer|w/\s?d|laundry(?:[ \t]+room)?|washer|dryer)\s*(?:is\s*)?(?:in[- ]?(?:the[- ])?(?:unit|home|suite|apartment|residence)|inside (?:the )?(?:unit|apartment))|in[- ]?(?:unit|home|suite)\s*(?:laundry|washers?|dryers?|w/?d|washer\s*(?:/|and|&)\s*dryer)|(?:full[- ]size|stackable|front[- ]load\w*)\s*(?:washer|w/?d)|washer\s*(?:/|and|&|\+)\s*dryer\s*(?:included|provided|in)|w/\s?d\s*(?:included|provided)|\bw/d\b(?!\s*hook))"
    negated = r"\bno\s+(?:in[- ]?(?:unit|home|suite)\s+)?(?:washers?|laundry|w/?d|washer\s*(?:/|and|&)\s*dryer)\b|\bwithout\s+(?:a\s+)?(?:washer|laundry)\b|\bno in[- ]?unit\b"
    building = (r"\blaundry\s*(?:room|rooms|facilit\w+|center|area|on[- ]?(?:site|each floor|every floor|premises)|in (?:the )?(?:building|bldg|basement|complex)|in bldg|available on)"
                r"|\b(?:on[- ]?site|shared|community|common|coin[- ]?op\w*|building|bldg)\s*laundry|\blaundry\s*(?:is\s*)?(?:available\s*)?(?:on[- ]?site|in bldg|in building)"
                r"|\bwasher\s*(?:/|and|&)\s*dryer\s*(?:in|on)\s*(?:the\s*)?(?:building|bldg|floor|site)")
    positive = _SHARED_LAUNDRY.sub(" ", re.sub(negated, " ", low))  # shared machines never count as in the unit
    if re.search(in_unit, positive):
        return "in_unit"
    if re.search(building, low) or _SHARED_LAUNDRY.search(low):
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


_PARKING_PRICE_RES = (
    re.compile(r"(?:garage|carport|covered parking|reserved parking|parking(?: fee| rate| cost)?|parking space|parking spot)s?[ \t]*(?:space|spot|stall|fee|rental|rent)?s?[ \t:\-=(,]{0,6}(?:(?:is|are|from|starting at|for|at|only|available|offered)[ \t,]+)*\$\s?(\d{2,4})(?:\.\d\d)?\b(?!\s*(?:deposit|one[- ]time|setup|set-up|/\s*\d\s*(?:br|bd|bed)))"),
    # "Parking: assigned covered spot $60/mo", "garage parking available for $110 a month": a few describing words in between
    re.compile(r"\b(?:garage|carport|parking)s?\b[ \t:\-=(]{0,4}(?:(?:assigned|reserved|covered|private|underground|heated|attached|detached|surface|lot|street|"
               r"spots?|spaces?|stalls?|available|offered|for|at|is|are|from|only|each|per|one|a|an|the|rental|rate|fee|cost|\d-car|off[- ]?street|on[- ]?site|garage|carport|parking|required|mandatory|optional|-)[ \t:,]+){1,6}"
               r"\$\s?(\d{2,4})(?:\.\d\d)?(?=[ \t]*(?:/[ \t]*mo|per[ \t]+month|a[ \t]+month|monthly|each[ \t]+month))(?!\s*(?:deposit|one[- ]time|setup|set-up|/\s*\d\s*(?:br|bd|bed)))"),
    re.compile(r"\$\s?(\d{2,4})\s*(?:/\s*mo(?:nth)?|per month|a month|monthly)?\s*(?:for |per )?(?:a |the )?(?:reserved |covered |garage |private )?(?:parking|garage|carport)\b(?!\s*deposit)"),
    # "1 spot $50/mo", "Parking: 1 spot, $50/month", "2 spaces at $40 a month"
    re.compile(r"\b\d\s*(?:parking\s+)?(?:spots?|spaces?|stalls?)\s*[,:\-]?\s*(?:for |at |is |are |only )?\$\s?(\d{2,4})(?:\.\d\d)?(?=[ \t]*(?:/[ \t]*mo|per[ \t]+month|a[ \t]+month|monthly|each[ \t]+month|\b))(?!\s*(?:deposit|one[- ]time|setup|set-up))"),
)
_PARKING_OPTIONAL = re.compile(r"\boptional\b|\bavailable\b|\badditional\b|\bextra (?:parking|spaces?|spots?|cars?|vehicles?|garage)\b|\bupgrade\b|\bif (?:you )?(?:need|want)\b|\bwaitlist\b|\bon request\b|\bfor an? fee\b", re.I)
_PARKING_REQUIRED = re.compile(r"\brequired\b|\bmandatory\b|\bmust\b", re.I)
# "Parking $100 per month optional", "Heated garage, $130 a month, optional": the word comes after the amount, past the clause end
_PARKING_OPTIONAL_AFTER = re.compile(r"^[ \t]*(?:(?:/[ \t]*mo\w*|per[ \t]+month|a[ \t]+month|monthly|each[ \t]+month|extra|additional)[ \t,;:()\-]*){0,3}"
                                     r"(?:optional\b|if[ \t]+(?:you[ \t]+)?(?:need|want)\b|on[ \t]+request\b|upgrade\b|waitlist\b|for[ \t]+an[ \t]+extra\b)", re.I)
_PARKING_FREE = re.compile(r"\bfree (?:off[- ]?street |on[- ]?site |surface |assigned |resident |tenant )?(?:parking|lot|spots?|spaces?)\b|\bparking\s*(?:is\s*)?(?:included|free|at no (?:extra )?charge)\b|"
                           r"\bparking\s*[:\-]\s*(?:free|included)\b|\b(?:lot|surface|street|off[- ]?street)[^.\n;$]{0,20}\bfree\b|\bfree\b[^.\n;$]{0,12}\b(?:lot|surface)\b|"
                           r"\b(?:\d+|one|two|three|four)\s+(?:[a-z]+\s+){0,2}(?:spaces?|spots?|stalls?)\s+(?:is\s+|are\s+)?(?:included|free)\b|\b(?:includes?|including)\s+(?:\w+[- ]?){0,2}parking\b|"
                           r"\bparking\b[^.\n;$]{0,30}\b(?:at|for|with)\s+no\s+(?:extra\s+|additional\s+)?(?:charge|cost|fee)\b|\bno\s+(?:extra\s+|additional\s+)?(?:charge|cost|fee)\s+for\s+(?:\w+\s+){0,2}parking\b", re.I)


def _parking_prices(low: str) -> list[tuple[float, bool, str]]:
    """Every parking price in the text as (amount, optional, clause). A price that is only offered ("available", "additional",
    "optional", or a different spot than the free one) is optional and never counts toward the monthly cost."""
    seen: set[int] = set()
    out: list[tuple[float, bool, str]] = []
    free_anywhere = bool(_PARKING_FREE.search(low))
    for rx in _PARKING_PRICE_RES:
        for m in rx.finditer(low):
            at = m.start(1)
            if any(abs(at - x) < 2 for x in seen):
                continue
            seen.add(at)
            a = max(low.rfind(x, 0, m.start()) for x in (".", "\n", ";", ",")) + 1  # from the start of the match: "garage available, $90" is one clause
            b = min([x for x in (low.find(". ", at), low.find("\n", at), low.find(";", at), low.find(",", at), m.end() + 14) if x != -1])
            clause = low[a:b + 1]
            required = bool(_PARKING_REQUIRED.search(clause))
            optional = bool(_PARKING_OPTIONAL.search(clause)) and not required
            after_amount = low[m.end(1):].split("\n")[0][:60]
            if not required and _PARKING_OPTIONAL_AFTER.match(re.sub(r"^(?:\.\d\d)", "", after_amount)) and not _PARKING_REQUIRED.search(after_amount[:40]):
                optional = True
                clause = low[a:m.end(1) + len(after_amount)]
            if not optional and not required and free_anywhere and not _PARKING_FREE.search(clause):
                optional = True  # free parking is listed elsewhere, so this priced one is a different, extra choice
            out.append((float(m.group(1)), optional, clause))
    return out


_GARAGE_INCLUDED = re.compile(r"\b(?:garage|carport)(?:[ \t]+(?:parking|spaces?|spots?|stalls?))?s?\b[^.\n;$]{0,20}\b(?:included|free|at no (?:extra )?charge)\b|"
                              r"\b(?:free|included)\b[^.\n;$]{0,10}\b(?:garage|carport)\b|\b(?:attached|detached)\b[ \t]+(?:\d[- ]?car[ \t]+)?garage\b|\b\d[- ]car[ \t]+garage\b", re.I)
_GARAGE_SAYS_INCLUDED = re.compile(r"\b(?:garage|carport)(?:[ \t]+(?:parking|spaces?|spots?|stalls?))?s?\b[^.\n;$]{0,20}\b(?:included|free|at no (?:extra )?charge)\b|\b(?:free|included)\b[^.\n;$]{0,10}\b(?:garage|carport)\b", re.I)
_OPTIONAL_GARAGE_CLAUSE = re.compile(r"[^.\n;,$]*\b(?:garage|carport)\b[^.\n;,$]*")


def _a(w: str) -> str:
    return ("An " if w[0] in "aeiou" else "A ") + w


def _parking_what(clause: str) -> str:
    if re.search(r"\bgarage\b", clause):
        return "garage"
    if re.search(r"\bcarports?\b", clause):
        return "carport"
    if re.search(r"\b(?:additional|extra)\b", clause):
        return "extra parking space"
    return "parking space"


def _parking_detail(text: str) -> tuple[str, float | None, list[str]]:
    low = text.lower()
    prices = _parking_prices(low)
    notes: list[str] = []
    rest = low
    for value, optional, clause in prices:
        if optional:
            what = _parking_what(clause)
            notes.append(f"{_a(what)} is available for ${value:,.0f} a month. It looks optional, so it is not counted in the monthly cost. Ask if it is required.")
            rest = rest.replace(clause, " ")
    for m in list(_OPTIONAL_GARAGE_CLAUSE.finditer(rest)):  # "Garage space available": offered, so not the place's parking
        clause = m.group(0)
        if _PARKING_OPTIONAL.search(clause) and not _PARKING_REQUIRED.search(clause) and not _GARAGE_SAYS_INCLUDED.search(clause) \
                and not re.search(r"\bno\s+garage\b|garage door|\bavailable\s+(?:now|immediately|\d|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)", clause):
            what = _parking_what(clause)
            if not any(what in n for n in notes):
                notes.append(f"{_a(what)} is available but the listing gives no price. It looks optional, so it is not counted as the place's parking. Ask if it costs extra.")
            rest = rest.replace(clause, " ")
    required = [v for v, o, _c in prices if not o]
    kind, cost = _parking_kind_cost(rest, required[0] if required else None)
    if cost is None and required:
        cost = required[0]
    if cost is None and any(o for _v, o, _c in prices) and _PARKING_FREE.search(low):
        cost = 0.0
    return kind, cost, notes


def _parking(text: str) -> tuple[str, float | None]:
    kind, cost, _notes = _parking_detail(text)
    return kind, cost


def _parking_kind_cost(text: str, priced: float | None) -> tuple[str, float | None]:
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
    elif re.search(r"\b(?:off[- ]?street|surface|free|assigned|reserved|on[- ]?site|private|ample|plenty of|paved|resident)\s+parking\b|\b(?:surface|gravel|paved|resident|tenant)?\s*lot\s+parking\b|\bparking\s+(?:lot|included|available|space|spot|provided|on[- ]?site)|\bdriveway\b|\bparking\s*[:\-]\s*(?:lot|yes|included|free|assigned|surface)|\b\d\s*parking (?:spaces?|spots?)\b|\b(?:surface|gravel|paved)\s+lot\b", low):
        kind = "lot"
    elif re.search(r"\b(?:street|on[- ]street)\s+parking\b|\bparking\s*[:\-]\s*street\b", low):
        kind = "street"
    elif re.search(r"\bno\s+(?:off[- ]?street\s+|on[- ]?site\s+)?parking\b|\bparking\s*[:\-]\s*none\b", low):
        kind = "none"
    cost: float | None = priced
    if cost is not None and not kind:
        kind = _parking_kind_words(low)
    if cost is None and re.search(r"\b(?:includes?|including)\s+(?:\w+[- ]?){0,2}parking\b|\bparking\s*[:\-][^.\n;]{0,30}\b(?:included|free)\b", low) and kind and kind != "none":
        cost = 0.0
    if cost is None and re.search(r"\bfree (?:off[- ]?street |on[- ]?site |surface |assigned |resident |tenant )?parking\b|\bparking\s*(?:is\s*)?(?:included|free|at no (?:extra )?charge)\b|\bparking\s*[:\-]\s*(?:free|included)\b|\b(?:\d+|one|two|three|four)\s+(?:[a-z]+\s+){0,2}(?:spaces?|spots?|stalls?)\s+(?:is\s+|are\s+)?(?:included|free)\b", low):
        cost = 0.0
    if cost is None and kind and kind != "none" and re.search(r"\bparking\b[^.\n;$]{0,30}\b(?:at|for|with)\s+no\s+(?:extra\s+|additional\s+)?(?:charge|cost|fee)\b|\bno\s+(?:extra\s+|additional\s+)?(?:charge|cost|fee)\s+for\s+(?:\w+\s+){0,2}parking\b", low):
        cost = 0.0  # "Off-street parking for 2 cars at no charge"
    if cost is None and kind in ("garage", "covered") and _GARAGE_INCLUDED.search(low):
        cost = 0.0  # "Attached garage included in rent", "Attached 1-car garage"
    return kind, cost


# "Pets: no pets over 25 lbs", "Dogs: no pets over 70 lbs", "Dogs: no dogs over 70 lbs": a weight rule, so what it names is allowed
_PET_NO_OVER = r"no[ \t]+(?:(?:cats?|dogs?|pets?|animals?)[ \t]+)?(?:over|above|exceeding|larger than|bigger than|heavier than|more than|weighing over)[ \t]*\d{1,3}[ \t]*(?:lbs?\b|pounds?\b)"
_PET_LABEL_NO_OVER = re.compile(r"\b(?:pets?|animals?|cats?|dogs?)[ \t]*[:\-][ \t]*" + _PET_NO_OVER + r"\.?", re.I)
_LABELLED_OK = re.compile(r"\b(cats?|dogs?)[ \t]*[:\-][ \t]*(?:(?:ok|okay|yes|allowed|welcome|accepted|fine|permitted)\b|(?:up to|under|max(?:imum)?(?: of)?|less than|below|no more than|at most|<)?[ \t]*\d{1,3}[ \t]*(?:lbs?\b|pounds?\b)|" + _PET_NO_OVER + ")", re.I)
_LABELLED_NO = re.compile(r"\b(cats?|dogs?)[ \t]*[:\-][ \t]*(?:no|none|not allowed|not permitted)\b(?![ \t]+(?:(?:cats?|dogs?|pets?|animals?)[ \t]+)?(?:over|above|exceeding|larger|bigger|heavier|more|under|breeds?|fee|deposit))", re.I)


def _charge_for(animal: str) -> str:
    kind = r"(?:fees?|rent|deposit|charge)s?"
    return (rf"\b{animal}\s+{kind}\b[ \t:\-=]{{0,3}}(?:of[ \t]+)?\$\s?\d"
            rf"|\$\s?\d[\d,]*(?:\.\d\d)?[ \t]*(?:/[ \t]*mo(?:nth)?|per month|monthly|a month|one[- ]time|non[- ]?refundable|refundable)?[ \t]*{animal}\s+{kind}\b")


_CAT_CHARGE = _charge_for("cat")
_DOG_CHARGE = _charge_for("dog")


def _pets(text: str) -> str:
    low = text.lower()
    low = _PET_LABEL_NO_OVER.sub(" ", low)  # "Pets: no pets over 25 lbs" and "Dogs: no pets over 70 lbs" are weight rules, not a no
    if re.search(r"\bno pets\b(?!\s+(?:restrictions?|limits?|problem|fee|(?:over|above|exceeding|larger|bigger|heavier|greater|more than|weighing|under)\b))|\bpets (?:are )?not (?:allowed|permitted|accepted)\b|\bnot pet[- ]friendly\b|\bpets\s*[:\-]\s*(?:no\b(?!\s+(?:cats?|dogs?)\b)|none|not allowed)|\bpet policy\s*[:\-]\s*no\b|\bno animals\b|\bpets?\s+no\s*(?:[.;,!\n|]|$)", low):
        return "none"
    work = low
    cats = dogs = False
    no_cats = re.search(r"\bno cats?\b(?!\s+(?:over|above|under|larger|bigger|heavier|exceeding|more))|\bcats? (?:are )?not (?:allowed|permitted|accepted)|\bno cats? allowed", work)
    no_dogs = re.search(r"\bno dogs?\b(?!\s+(?:over|above|under|larger|bigger|heavier|exceeding|more))|\bdogs? (?:are )?not (?:allowed|permitted|accepted)|\bno dogs? allowed", work)
    if re.search(r"\bcats? and dogs?\b|\bdogs? and cats?\b|\bcats?\s*(?:&|/|,)\s*dogs?\b|\bdogs?\s*(?:&|/|,)\s*cats?\b|\bcats?\s+(?:and|&)\s+(?:(?:small|medium|large|big|little|tiny|young|well[- ]behaved)\s+)*dogs?\b|\bdogs?\s+(?:and|&)\s+(?:(?:small|medium|large|big|little|tiny|young)\s+)*cats?\b|\ball pets\b|\bdogs? (?:are )?ok.{0,40}cats? (?:are )?ok|\bcats? (?:are )?ok.{0,40}dogs? (?:are )?ok", work):
        cats = dogs = True
    for gm in re.finditer(r"\bpet[- ]friendly\b|\bpets (?:ok|okay|allowed|welcome|accepted)\b(?!\s+(?:with|by|on|upon|subject to)\s+(?:landlord\s+|owner\s+|management\s+)?(?:approval|permission))|\bpets\s*[:\-]\s*(?:yes|ok|okay|allowed|welcome)\b", work):
        seg = work[max(work.rfind(c, 0, gm.start()) for c in ".;\n|!?") + 1:]
        seg = re.split(r"[.;\n|!?]", seg)[0]
        named = re.sub(r"\bno\s+(?:cats?|dogs?)\b|\b(?:cats?|dogs?)\s+(?:are\s+)?not\s+(?:allowed|permitted|accepted)", " ", seg)
        if not re.search(r"\b(?:cats?|dogs?)\b", named):  # "Pet friendly: cats ok" names the pets, so the general words add nothing
            cats = dogs = True
    if re.search(r"\bcats?\b(?:\s*(?:are|is))?\s*(?:ok|okay|fine|allowed|welcome|accepted|friendly|permitted)|\bcats? only\b|\bcat[- ]friendly\b|\bpurrr|\bcats?\s*[:\-]?\s*\$\s?\d", work):
        cats = True  # "Cats $200 deposit": a fee for cats means cats are taken
    if re.search(r"\bdogs?\b(?:\s*(?:are|is))?\s*(?:ok|okay|fine|allowed|welcome|accepted|friendly|permitted)|\bdogs? only\b|\bdog[- ]friendly\b|\bwoof|\bsmall dogs?\b|\bdogs? under\b|\bdogs?\s*[:\-]?\s*\$\s?\d|\bdogs?\s+(?:up to|under|less than|weighing|max(?:imum)?(?: of)?)\s+\d{1,3}\s*(?:lbs?|pounds?)\b", work):
        dogs = True
    if re.search(_CAT_CHARGE, work):
        cats = True  # "Cat fee $150": a charge for cats means cats are taken
    if re.search(_DOG_CHARGE, work):
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
    for lm in _LABELLED_OK.finditer(text):  # "Cats: ok. Dogs: up to 40 lbs." names each animal on its own line
        if lm.group(1).lower().startswith("cat"):
            cats = True
        else:
            dogs = True
    for lm in _LABELLED_NO.finditer(text):  # "Dogs: no"
        if lm.group(1).lower().startswith("cat"):
            no_cats = lm
        else:
            no_dogs = lm
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


_NO_PETS_CLAUSE = re.compile(r"\bno pets\b(?!\s+(?:restrictions?|limits?|problem|fee|(?:over|above|exceeding|larger|bigger|heavier|greater|more than|weighing|under)\b))[^.\n;]*|\bpets (?:are )?not (?:allowed|permitted|accepted)[^.\n;]*|"
                             r"\bnot pet[- ]friendly\b|\bpets\s*[:\-]\s*(?:no\b(?!\s+(?:cats?|dogs?)\b)|none|not allowed)[^.\n;]*|\bpet policy\s*[:\-]\s*no\b[^.\n;]*|\bno animals\b[^.\n;]*|\bpets?\s+no\s*(?=[.;,!\n|]|$)", re.I)
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
    for sentence in re.split(r"[.;\n?!|]+", text):
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
            for m in _LABELLED_NO.finditer(piece):  # "Dogs: no"
                says[m.group(1).lower().rstrip("s") + "s"] = "no"
            for m in _LABELLED_OK.finditer(piece):  # "Dogs: up to 40 lbs", "Dogs: no pets over 70 lbs"
                says[m.group(1).lower().rstrip("s") + "s"] = "yes"
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
    negotiable = False
    if not (clash or approval) and not _pets(text) and not any("no" in v or "yes" in v for v in stances.values()):
        negotiable = any("maybe" in v for v in stances.values())  # "Pets negotiable": not a yes, not a no
    if not (clash or approval or negotiable):
        return ""
    said = _quoted_pieces(quoted)
    who = _ask_who(text)
    if negotiable:
        return f"The listing says pets are negotiable ({said}). Pets is left empty, so ask {who} which pets are allowed and what they cost."
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


def _sentence_break(text: str, pos: int, ch: str) -> int:
    """Last ``ch`` before ``pos``; a full stop right after "lb", "lbs", "max" or inside a number ("55 lbs., $300") is not a break."""
    at = text.rfind(ch, 0, pos)
    while ch == "." and at > 0 and (re.search(r"(?:\blbs?|\bmax|\bapprox|\bno|\bapt|\bst)$", text[max(0, at - 6):at], re.I) or text[at - 1].isdigit() and text[at + 1:at + 2].isdigit()) \
            and not re.match(r"\s+(?:security\s+|damage\s+)?deposit\s*:", text[at + 1:at + 24], re.I):  # "55 lbs. Deposit: $1,000" starts a new sentence
        at = text.rfind(ch, 0, at)
    return at


def _in_pet_sentence(text: str, pos: int) -> bool:
    """True when position ``pos`` sits in a sentence that starts with a pet word ("Pet friendly (cats only, $40/month, deposit $250)")
    or inside a bracket that follows one, and that sentence does not talk about the lease or the security deposit."""
    start = max(_sentence_break(text, pos, c) for c in ".!?;\n|") + 1
    sent = text[start:pos]
    line_start = text.rfind("\n", 0, pos) + 1
    if start > 0 and text[start - 1] == "|":  # the pet line may sit mid-paragraph: it starts at the last sentence break before the pipe
        line_start = max(line_start, max(_sentence_break(text, start - 1, c) for c in ".!?;") + 1)
    if start > line_start and text[start - 1] == "|" and _PET_LEAD.match(text[line_start:pos]) \
            and not re.search(r"\bsecurity\b|\bdamage\b|\blease\b|\brent\b(?!\s*:)", text[line_start:pos], re.I) \
            and not sent.strip() and text[pos:pos + 1] == "$":
        return True  # "Pets: 1 pet, max 55 lbs., $300 deposit | $25 monthly": a pipe goes on with the same pet line
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
        if m.start() in used:
            continue  # "$35 per pet per month" was read as pet rent above, so it is not also a pet fee
        if not m.group(3) and re.search(r"\bper pet\b", m.group(0), re.I) \
                and (re.search(r"\bdeposits?\W{0,4}$", text[max(0, m.start() - 14):m.start()], re.I)
                     or re.search(r"\bpet\s+(?:rent|fees?|deposit|charge)s?\W{0,6}$", text[max(0, m.start() - 22):m.start()], re.I)
                     or re.match(r"\s*deposit", text[m.end():m.end() + 12], re.I)):
            continue  # "deposit $250 per pet" and "Monthly pet rent $35 per pet": the label owns the amount, not a pet fee
        used.add(m.start())
        rent = bool(m.group(2)) or (m.group(3) or "").lower() in ("rent", "charge")
        out.setdefault("pet_rent" if rent else "pet_fee", float(m.group(1)))
    labels = [lm for lm in re.finditer(r"\bpet\s+(rent|fees?|deposit|charge)s?\b", text, re.I)
              if not re.search(r"\b(?:no|zero|without|waived)\W{0,3}$", text[max(0, lm.start() - 10):lm.start()], re.I)]  # "No pet fee"
    for i, m in enumerate(labels):
        stop = min([m.end() + 60, text.find("\n", m.end()) if text.find("\n", m.end()) >= 0 else len(text)]
                   + ([labels[i + 1].start()] if i + 1 < len(labels) else []))
        rest = re.split(r"[.;!?](?:\s|$)", text[m.end():stop])[0]  # the next sentence's amount ("Pet fee n/a. Application $40") is not a pet amount
        am = re.match(r"[^$\n]{0,25}?(\$\s?(\d{1,4})(?:\.\d\d)?)(?!\d)(.{0,24})", rest)
        if not am or (m.end() + am.start(1)) in used or re.search(r"\bpet\b", rest[:am.start(1)], re.I):
            continue
        if re.match(r"[\s:\-=]*(?:n/?a|none|no|not|waived|free)\b", rest, re.I):
            continue  # "Pet fee n/a, application $40": no pet fee, and the amount after it belongs to something else
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
    if "pet_fee" not in out and "pet_rent" not in out:  # "Cat fee $150" / "Dog fee: $200": a fee named for one animal is the pet fee
        m = re.search(r"\b(?:cat|dog)s?[ \t]+fee[ \t:\-=]*\$[ \t]?(\d{1,4})(?:\.\d\d)?(?![\d,])([ \t]*(?:/[ \t]*mo(?:nth)?|per month|monthly|a month))?", text, re.I)
        if m:
            out["pet_rent" if m.group(2) else "pet_fee"] = float(m.group(1))
    if "pet_fee" not in out:  # "Pets ok. One time fee $200.": the fee sentence right after the pet sentence
        m = re.search(_PET_THEN_ONE_TIME.pattern + r"[ \t]+fee[ \t:\-]*\$[ \t]?(\d{1,4})(?:\.\d\d)?(?![\d,])", text, re.I)
        if m:
            out["pet_fee"] = float(m.group(3))
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
    if "pet_rent" not in out:  # "$35 each pet rent", "Pets welcome, $35 each, max 2 pets": an amount for each pet in a pet sentence
        for sent in re.split(r"[.;\n|]", text):
            em = re.search(r"\$[ \t]?(\d{1,4})(?:\.\d\d)?[ \t]*(?:(?:/[ \t]*mo(?:nth)?|per month|monthly|a month)[ \t]*)?(?:each|apiece)\b(?:[ \t]+(?:for[ \t]+)?pets?)?(?:[ \t]*(?:/[ \t]*mo(?:nth)?|per month|monthly|a month)\b)?(?![ \t]+(?:adult|applicant|person|occupant|tenant|resident|roommate|app|screen|background|credit|admin))", sent, re.I)
            if em and _PET_WORD.search(sent) and not re.search(r"\b(?:one[- ]time|deposit|non[- ]?refundable|fee)\b", sent[em.end():em.end() + 25], re.I) \
                    and not re.search(r"parking|garage|storage|utilit|application|admin", sent[:em.start()], re.I):
                out["pet_rent"] = float(em.group(1))
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
            r"\bpet[ \t]+deposit[ \t]*(?:[:\-]|of)?[ \t]*\$\s?(\d{1,4})(?:\.\d\d)?\b(?!/)")
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


def _pet_deposit_then_monthly(text: str) -> float | None:
    """"Pet deposit $300, $40 monthly": the amount after the deposit that says monthly is the pet rent."""
    m = re.search(r"\bpet[ \t]+(?:deposit|fee)[ \t:\-]*(?:of[ \t]+)?\$\s?\d{1,4}(?:\.\d\d)?[ \t]*(?:,|and|plus|\+)[ \t]*\$\s?(\d{1,4})(?:\.\d\d)?[ \t]*(?:/[ \t]*mo(?:nth)?|per month|monthly|a month)\b(?![ \t]*(?:deposit|fee|parking|garage|storage))", text, re.I)
    return float(m.group(1)) if m else None


def _no_pet_rent(text: str) -> bool:
    """"No pet rent", "Pet rent: none", "Pet rent $0": the listing says there is no monthly pet charge."""
    return bool(re.search(r"\b(?:no|zero|without|waived|free of)[ \t]+(?:monthly[ \t]+)?pet[ \t]+(?:rent|charges?)\b|\bpet[ \t]+rent[ \t]*[:\-=]?[ \t]*(?:none|n/?a|waived|free|\$\s?0(?:\.00)?(?![\d.,]))", text, re.I)) \
        and not re.search(r"\bno[ \t]+pet[ \t]+rent[ \t]+(?:for|on|if|unless|over|above|with)\b", text, re.I)


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
            pet = bool(_PET_WORD.search(re.split(r"[|]", before)[-1]) or _PET_WORD.search(re.split(r"[.!?;\n|]", after)[0]))
        else:
            near_before = re.split(r"[,.!?;\n|]", before)[-1]
            near_after = re.split(r"[,.!?;\n|]", after)[0]
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
        elif ch in ".;\n|" and depth == 0:
            out.append(text[start:i])
            start = i + 1
    out.append(text[start:])
    return out


_UNIT_LB = r"(?:lbs?\b\.?|pounds?\b|#)"
_LOOSE_WEIGHT = (
    r"\b(?:max(?:imum)?|up to|under|less than|below|at most|no more than|not (?:to )?exceed(?:ing)?)\s*(?:weight\s*)?(?:of\s*|:\s*)?(\d{1,3})\s*" + _UNIT_LB,
    r"\b(\d{1,3})\s*" + _UNIT_LB + r"\s*(?:or\s+(?:less|under|smaller)|and\s+under|max(?:imum)?|limit)",
    r"\b(?:weight\s+(?:limit|max(?:imum)?)|max(?:imum)?\s+weight)\s*(?:of|is|:|-)?\s*(?:under|up to|max(?:imum)?(?: of)?|less than|<)?\s*(\d{1,3})\s*" + _UNIT_LB + "?",
)
_NOT_PET_WEIGHT = re.compile(r"elevator|balcon|storage|bike|furniture|capacity|floor|appliance|truck|vehicle|occupan|person|people|waterbed|safe\b|trailer|luggage", re.I)


def _weight_clauses(text: str) -> list[str]:
    return [c for c in re.split(r"[.;\n|]", text) if c.strip()]


def _loose_weight(text: str) -> int | None:
    """A weight with no pet word right beside it ("Pets welcome. Maximum 55 lbs.", "Weight limit: under 70 lbs"): read only when the
    clause or the one before it is about pets, or the clause is just a short weight phrase with no other subject. Else None."""
    clauses = _weight_clauses(text)
    for i, c in enumerate(clauses):
        if _NOT_PET_WEIGHT.search(c):
            continue
        m = next((x for x in (re.search(pat, c, re.I) for pat in _LOOSE_WEIGHT) if x), None)
        if not m:
            continue
        petty = bool(_PET_WORD.search(c)) or (i > 0 and bool(_PET_WORD.search(clauses[i - 1]))) \
            or len(c.split()) <= 8
        if petty and 3 <= int(m.group(1)) <= 300:
            return int(m.group(1))
    return None


def _pet_weight_unclear(text: str) -> str:
    """A note when a number of pounds sits in a pet clause but no weight limit could be read from it, else ""."""
    if _pet_limit_fields(text).get("pet_weight_limit") is not None:
        return ""
    for c in _weight_clauses(text):
        if _PET_WORD.search(c) and re.search(r"\b\d{1,3}\s*" + _UNIT_LB, c, re.I) and not re.search(r"\$", c) and not _NOT_PET_WEIGHT.search(c):
            said = " ".join(c.split())[:80]
            return (f"The listing gives a weight near the pets (\"{said}\") but it is not clear if it is a limit, so the weight limit is left empty. "
                    f"Ask {_ask_who(text)} the heaviest pet allowed.")
    return ""


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
    elif not w:
        loose = _loose_weight(text)
        if loose:
            out["pet_weight_limit"] = float(loose)
    n = re.search(r"\b(?:max(?:imum)?(?: of)?|limit(?: of)?|up to|no more than|at most)\s+(\d|one|two|three|four)\s+(?:pets?|animals?|cats?|dogs?)\b", text, re.I) \
        or re.search(r"\b(\d|one|two|three|four)\s+(?:pets?|animals?|cats?|dogs?)\s+(?:max(?:imum)?|limit|per (?:unit|apartment|home|household))", text, re.I)
    if not n:  # "Cats up to 2", "Dogs max 2"
        n = re.search(r"\b(?:pets?|animals?|cats?|dogs?)\s+(?:up to|max(?:imum)?(?: of)?|limit(?: of)?)\s+(\d|one|two|three|four)\b(?!\d|\s*(?:lbs?|pounds?|years?|yrs?|in\b|inch))", text, re.I)
    if not n:  # "Pets: 1 pet", "Pets: 2 dogs"
        n = re.search(r"\b(?:pets?|animals?)[ \t]*[:\-][ \t]*(\d|one|two|three|four)[ \t]+(?:pets?|animals?|cats?|dogs?)\b(?![ \t]*(?:not|prohibited|banned))", text, re.I)
    if not n:  # "Two dogs ok", "2 cats allowed"
        n = re.search(r"(?<![\w$.])(\d|one|two|three|four)\s+(?:pets?|animals?|cats?|dogs?)\s+(?:are\s+)?(?:ok|okay|allowed|welcome|accepted|permitted)\b", text, re.I)
    if not n:  # "Cats only, 1 pet, maximum 55 lbs"
        for sentence in re.split(r"[.\n;]", text):
            if _PET_WORD.search(sentence):
                n = re.search(r"(?<![\w$.])(\d|one|two|three|four)[ \t]+(?:pets?|animals?)[ \t]*(?:,|$)", sentence, re.I)
                if n:
                    break
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
    if re.search(r"\b(?:no|not a|without a)\s+(?:\w+\s+)?fenc(?:ed|e|ing)\b|\bunfenced\b|\bnot fenced\b", text, re.I):
        out["fenced_yard"] = 0
    elif re.search(r"\bfenced[- ](?:in[- ])?(?:(?:back|front|private)[ ]?(?:yard|garden|lot|patio)?|yard|garden|lot|patio)\b|\b(?:yard|backyard)\s+(?:is\s+)?(?:fully\s+)?fenced|\bfully fenced\b"
                   r"|\b(?:gated|walled)[- ](?:in[- ])?(?:back|front|private )?(?:yard|garden|lot|patio)\b"
                   r"|\b(?:back|front)?[ ]?yard\b[^.\n;]{0,30}?\b(?:fence|fenced|fencing)\b", text, re.I):
        out["fenced_yard"] = 1
    return out


_PET_FILLER = re.compile(r"\b(?:deposits?|monthly|fees?|rent|ok|okay|allowed|permitted|accepted|welcomed?|fine|friendly|policy|rules?|with|and|or|per|a|an|the|is|are|we|love|both|each|every|total|combined|in|of|on|at|to|for|your|any|all|up|unit|apartment|home|place|building|month|mo|pet|pets|non|refundable|nonrefundable|one[- ]time|plus|extra|only|have|has|can|may)\b", re.I)


def _pet_limit_is_in_fields(clause: str, out: dict[str, Any]) -> bool:
    """True when a pet clause only says things the fields already hold, so a note would repeat it: every weight, count and
    dollar amount in the line is the value of its own field (weight limit, count limit, pet rent, fee or deposit), the kinds
    of pet it names agree with the pets field, and nothing else is in it (no breed, size or approval rule)."""
    if all(out.get(k) is None for k in ("pet_weight_limit", "pet_count_limit", "pet_rent", "pet_fee", "pet_deposit")):
        return False
    low = clause
    pets = out.get("pets")
    if pets in ("cats", "dogs"):
        low = re.sub(r"\b" + pets[:-1] + r"s? only\b", " ", low, flags=re.I)  # "Cats only" is what the pets field says
    low = re.sub(r"\bno\s+(?:pets?|dogs?|cats?|animals?)\s+(?=(?:over|above|heavier than|more than)\b)", " ", low, flags=re.I)  # "no pets over 70 lbs" is the weight limit
    if re.search(r"\b\d{1,3}\s*-?\s*(?:lbs?\b|pounds?\b)", low, re.I):
        low = re.sub(r"\b(?:small|medium|large|big|little)\b", " ", low, flags=re.I)  # "small dogs (35 lb limit)": the weight is the size
    if re.search(r"breed|restrict|approv|\bsize\b|case[- ]by[- ]case|negotiab|consider|\bonly\b|aggress|spay|neuter|vaccin|licen[sc]e|not allowed|prohibit|except|service animal|emotional|depend|unless|\bif\b|\bnot\b|\bno\b(?! more than)", low, re.I):
        return False
    low = re.sub(r"\bweight[ \t]+(?:limit|max(?:imum)?)\b", "limit", low, flags=re.I)
    # kinds of pet: the pets field must agree
    kinds = {k.lower().rstrip("s") for k in re.findall(r"\b(cats?|dogs?)\b", low, re.I)}
    if kinds:
        allowed = {"cats": {"cat"}, "dogs": {"dog"}, "both": {"cat", "dog"}}.get(str(pets))
        if allowed is None or not kinds <= allowed:
            return False
    # weights
    for w in re.findall(r"\b(\d{1,3})\s*-?\s*(?:lbs?\b|pounds?\b)", low, re.I):
        if out.get("pet_weight_limit") is None or float(w) != float(out["pet_weight_limit"]):
            return False
    low = re.sub(r"\b\d{1,3}\s*-?\s*(?:lbs?\b\.?|pounds?\b)", " ", low, flags=re.I)
    # counts: "2 pets", "two pet", "max 2", "limit: 2"
    for m in re.finditer(r"\b(\d|one|two|three|four)\b(?!\s*(?:/|%))", low, re.I):
        v = m.group(1).lower()
        n = int(v) if v.isdigit() else _NUM_WORDS[v]
        if out.get("pet_count_limit") is None or float(n) != float(out["pet_count_limit"]):
            return False
    low = re.sub(r"\b(?:\d|one|two|three|four)\b", " ", low, flags=re.I)
    # money
    money_fields = [out.get(k) for k in ("pet_rent", "pet_fee", "pet_deposit") if out.get(k) is not None]
    for m in re.finditer(r"\$\s?(\d[\d,]*)(?:\.\d\d)?", low):
        if float(m.group(1).replace(",", "")) not in [float(x) for x in money_fields]:
            return False
    low = re.sub(r"\$\s?\d[\d,]*(?:\.\d\d)?(?:\s*/\s*(?:mo|month)\b)?", " ", low)
    low = _PET_FILLER.sub(" ", low)
    low = re.sub(r"\b(?:cats?|dogs?|animals?|max(?:imum)?|limit|weight|up|under|over|more|than|pets?|lbs?|pounds?)\b", " ", low, flags=re.I)
    return not re.search(r"[A-Za-z]{2,}", low)


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
        if re.search(r"credit[ \t]+(?:check|report)(?:[ \t]+fees?)?[ \t:\-=]*$", text[max(line_start, m.start() - 30):m.start()], re.I):
            return ""  # a credit check fee has its own reading
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
        m2 = re.search(r"\blast[ \t]+month(?:'?s)?(?:[ \t]+rent)?[ \t]+(?:is[ \t]+|are[ \t]+)?(?:due|required|payable|collected)[ \t]+(?:at|before|on|upon|with)[ \t]+(?:lease[ \t]+)?(?:signing|move[- ]?in)\b"
                       r"|\b(?:due|required|payable)[ \t]+(?:at|before|on|upon)[ \t]+(?:lease[ \t]+)?(?:signing|move[- ]?in)[^.\n;]{0,25}\blast[ \t]+month", text, re.I)
        # last month's rent is due at signing, so the first month is due too: two months of rent up front
        return (2, False) if m2 else (0, False)
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
    text = re.sub(r"\b(one|two|1|2)[ \t]+and[ \t]+(?:a|one)[- ]half\b|\b(1|2)[ \t]+1/2\b", lambda mm: f"{(mm.group(1) or mm.group(2)).lower().replace('one', '1').replace('two', '2')}.5", text, flags=re.I)
    m = re.search(r"\b(?:security |damage )?deposits?\b[ \t:\-]{0,4}(?:is |of |equal to |equals |=)?[ \t]*(\d(?:\.\d{1,2})?)[ \t]*(?:x|times|months?(?:'s?)?(?:[ \t]+(?:of[ \t]+)?rent)?)(?:[ \t]+(?:the[ \t]+|of[ \t]+|monthly[ \t]+)*rent)?\b", text, re.I)
    if m and 0 < float(m.group(1)) <= 6:
        return float(m.group(1))
    for pat in (r"\b(?:security |damage )?deposits?\b[ \t:\-]{0,4}(?:is |of |equal to |equals |equivalent to |=)?[ \t]*(one|two|a|1|2)[- ]months?(?:'s?)?(?:[ \t]+(?:of[ \t]+)?rent)?\b",
                r"\b(one|two|1|2)[- ]months?(?:'s?)?[ \t]+(?:security |damage )deposit\b",
                r"\b(one|two|1|2)[- ]months?(?:'s?)?[ \t]+(?:security|damage)\b(?![ \t]+(?:camera|cameras|cam|system|guard|gate|door|lock|patrol|alarm|building))"):
        m = re.search(pat, text, re.I)
        if m:
            return _WORD_NUM[m.group(1).lower()]
    return 0


def _three_months_up_front(text: str) -> bool:
    return bool(re.search(r"\b(?:three|3)[- ]months?(?:'s?)?(?:[ \t]+(?:of[ \t]+)?rent)?[^.\n]{0,30}\b(?:up[- ]?front|due (?:at|before|on|by)|at (?:signing|move[- ]?in|lease signing))", text, re.I)
                or re.search(r"\b(?:up[- ]?front|due (?:at|before)|at (?:signing|move[- ]?in))[^.\n]{0,30}\b(?:three|3)[- ]months?", text, re.I))


_CAP_WORDS = re.compile(r"\b(?:up[ \t]+to|max(?:imum)?|as much as|not to exceed|capped|cap of|limit(?:ed)?(?: to| of)?)\b", re.I)


def _seller_cap(text: str) -> tuple[float, str] | None:
    """"Seller will pay up to $8,000 in closing costs": a cap on what the seller gives, not a sure credit and not the closing
    costs. Returns (the capped amount, the quoted phrase), or None."""
    for m in re.finditer(r"[^.\n]*\bseller\b[^.\n]*?\b(?:up[ \t]+to|max(?:imum)?(?:[ \t]+of)?|as much as|not to exceed|capped at)[ \t]*\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?!\d)[^.\n]*", text, re.I):
        if re.search(r"closing|credit|concession|contribut", m.group(0), re.I) and not re.search(r"assessment", m.group(0), re.I):
            return _num(m.group(1)), " ".join(m.group(0).split())[:120]
    return None


def _closing_costs(text: str) -> float | None:
    """"Estimated closing costs $9,800" -> 9800. A seller's cap ("seller will pay up to $8,000 in closing costs") is not the closing costs."""
    m = re.search(r"\bclosing costs?(?:\s+(?:(?:are|is)\s+)?(?:est\w*\.?|estimate[d]?)(?:\s+(?:at|to be|of|around|about))?)?[ \t:\-=]{0,6}(?:of |about |around |approx\.? |~)?\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?(?!\d)", text, re.I) \
        or re.search(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?[ \t]*(?:in |for )?(?:est\w*\.?[ \t]+)?closing costs?\b", text, re.I)
    if not m:
        return None
    if _CAP_WORDS.search(text[max(0, m.start() - 40):m.start(1)]) and re.search(r"\bseller\b", text[max(0, m.start() - 80):m.end() + 40], re.I):
        return None
    value = _num(m.group(1))
    return value if 100 <= value <= 5_000_000 else None


def _seller_credit(text: str) -> float | None:
    """What the seller gives the buyer toward closing: "Seller will contribute up to $5,000 toward closing costs", "seller
    concessions of $8,000", "$3,000 seller credit". None when the text gives no amount."""
    amt = r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?!\d)"
    pats = (r"\bseller(?:'s)?[ \t]+(?:will[ \t]+|to[ \t]+|is[ \t]+(?:willing[ \t]+)?to[ \t]+)?(?:contribut\w*|credit|concessions?|assist\w*|offer\w*|give[sn]?)\b[^$\n.]{0,40}?" + amt,
            r"\bseller(?:'s)?[ \t]+(?:will[ \t]+|to[ \t]+)?(?:pay|pays|cover|covers)\b[^$\n.]{0,30}?" + amt + r"[^\n.]{0,30}\bclosing",
            r"\bseller[ \t]+(?:concessions?|credits?|contributions?)\b[^$\n.]{0,20}?" + amt,
            amt + r"[ \t]+(?:in[ \t]+|of[ \t]+)?seller[ \t]+(?:concessions?|credits?|contributions?|paid closing)",
            r"\bclosing[ \t]+costs?\b[^$\n.]{0,30}?\b(?:paid|covered|contributed)[ \t]+by[ \t]+(?:the[ \t]+)?seller\b[^$\n.]{0,25}?" + amt,
            r"\bseller[ \t]+(?:paid|covered)[ \t]+closing[ \t]+costs?\b[^$\n.]{0,25}?" + amt,
            # "Seller is offering a concession of $4,000", "Closing cost credit of $6,000 from seller with accepted offer"
            r"\bseller(?:'s)?[ \t]+(?:is[ \t]+|will[ \t]+be[ \t]+)?(?:offering|giving|providing|contributing|paying|covering)\b[^$\n.]{0,40}?" + amt,
            r"\bclosing[ \t]+costs?[ \t]+(?:credits?|concessions?|contributions?|assistance)\b[^$\n.]{0,30}?" + amt + r"(?=[^\n.]{0,40}\bseller\b)")
    for pat in pats:
        for m in re.finditer(pat, text, re.I):
            if re.search(r"assessment", m.group(0), re.I):
                continue
            if _CAP_WORDS.search(m.group(0)[:m.start(1) - m.start(0)]):
                continue  # "up to $8,000" is a limit, never a sure credit
            value = _num(m.group(1))
            if 100 <= value <= 5_000_000:
                return value
    return None


def _seller_credit_percent(text: str) -> tuple[float | None, bool]:
    """(percent of the price the seller gives toward closing, "up to" flag) from "Seller concessions up to 3% toward closing costs"."""
    pats = (r"\bseller(?:'s)?[ \t]+(?:is[ \t]+|will[ \t]+(?:be[ \t]+)?)?(?:contribut\w*|credits?|concessions?|assist\w*|offer\w*|give[sn]?|giving|providing|pays?|paying|paid|cover\w*)\b[^$\n.%]{0,40}?(\d{1,2}(?:\.\d+)?)[ \t]*%",
            r"(\d{1,2}(?:\.\d+)?)[ \t]*%[ \t]*(?:in[ \t]+|of[ \t]+)?seller[ \t]+(?:concessions?|credits?|contributions?|paid)")
    for pat in pats:
        m = re.search(pat, text, re.I)
        if m and 0 < float(m.group(1)) <= 20:
            return float(m.group(1)), bool(re.search(r"\bup[ \t]+to\b|\bmax", m.group(0), re.I))
    return None, False


def _seller_credit_detail(text: str, price: float | None) -> tuple[float | None, list[str]]:
    """(the seller credit in dollars or None, plain notes). Only a dollar amount is used, as written. A percent
    is a maximum, not a promise, so the credit stays empty and the note says to ask."""
    dollars = _seller_credit(text)
    if dollars:
        return dollars, []
    cap = _seller_cap(text)
    if cap:
        return None, [f'The listing says the seller will give up to ${cap[0]:,.0f} toward closing ("{cap[1]}"). That is a limit, not a promise, so the closing costs and the seller credit are left empty. Ask what the seller will really give.']
    pct, up_to = _seller_credit_percent(text)
    if pct is not None:  # a percent, and above all an "up to", is a maximum and not a promise, so no dollar amount is worked out
        words = f"{'up to ' if up_to else ''}{pct:g}%"
        pm = re.search(r"[^.\n]*\b" + re.escape(f"{pct:g}") + r"[ \t]*%[ \t]*\(\s*(?:about |approx\.? |~)?\$\s?(\d{1,3}(?:,\d{3})+|\d+)\s*\)", text)
        if pm:
            words += f" (${_num(pm.group(1)):,.0f})"
        return None, [f"The listing offers seller concessions of {words}. Ask what the seller will really give."]
    if re.search(r"\bseller(?:'s)?[ \t]+(?:will[ \t]+)?(?:pays?|paid|covers?|contribut\w*|concessions?|credits?)\b[^.\n]{0,40}\bclosing[ \t]+costs?\b|\bclosing[ \t]+costs?\b[^.\n]{0,30}\b(?:paid|covered)[ \t]+by[ \t]+(?:the[ \t]+)?seller\b", text, re.I):
        return None, ["The listing says the seller helps with closing costs but gives no amount, so the seller credit is blank. Ask how much."]
    return None, []


def _buyer_only_fees(text: str, out: dict[str, Any]) -> list[str]:
    """For a buy search. Parking cost and move-in fees are rent-side money: the buy cost and the cash to close do not count
    them, so they are not filled in (the reader never says "filled in" for money that is not counted). Each becomes a plain
    note instead. Also a broker percent and a transfer fee, which have no field. Takes the two fields out of ``out``."""
    notes: list[str] = []
    cost = out.pop("parking_cost", None)
    if cost is not None:
        required = re.search(r"\bparking\b[^.\n]{0,60}\b(?:required|mandatory|must)\b|\b(?:required|mandatory)\b[^.\n]{0,25}\bparking\b", text, re.I) \
            and not re.search(r"\b(?:not|isn't|optional)\b[^.\n]{0,15}\b(?:required|mandatory)\b|\bparking\b[^.\n]{0,40}\boptional\b", text, re.I)
        if required:
            notes.append(f"The listing says parking is ${cost:,.0f}/month and required. The cost of buying does not count it, so it is required but not counted. Add it to your own budget.")
        else:
            notes.append(f"The listing says parking is ${cost:,.0f}/month. The cost of buying does not count parking, so it is not counted anywhere. "
                         "Ask whether it is required, and add it to your own budget if it is.")
    fee = out.pop("move_in_fees", None)
    if fee is not None:
        notes.append(f"The listing mentions a ${fee:,.0f} move-in fee. The cash to close does not count it, so it is not counted anywhere. Ask who pays it.")
    m = re.search(r"\bbrokerage[ \t]+fee\b[^.\n;$%]{0,25}?(\d{1,2}(?:\.\d+)?)[ \t]*%([^.\n;]{0,30})", text, re.I) \
        or re.search(r"\b(\d{1,2}(?:\.\d+)?)[ \t]*%[ \t]+(?:brokerage|broker|agent)[ \t]+fee\b([^.\n;]{0,30})", text, re.I)
    if m:
        who = re.search(r"\b(?:paid[ \t]+by|by)[ \t]+(?:the[ \t]+)?(buyer|seller)\b|\b(buyer|seller)[ \t]+pays?\b", m.group(0), re.I)
        by = (who.group(1) or who.group(2)).lower() if who else ""
        notes.append(f"The listing mentions a brokerage fee of {float(m.group(1)):g}%" + (f", paid by the {by}" if by else "")
                     + ". No amount is saved and it is not counted anywhere. Ask what it comes to" + ("." if by else " and who pays it."))
    cm = re.search(r"\b(?:buyer'?s?|buying)[ \t]+agent'?s?[ \t]+(?:commission|fee|compensation)\b[^.\n;$%]{0,25}?(\d{1,2}(?:\.\d+)?)[ \t]*%", text, re.I) \
        or re.search(r"\b(\d{1,2}(?:\.\d+)?)[ \t]*%[ \t]+(?:buyer'?s?|buying)[ \t]+agent'?s?[ \t]+(?:commission|fee|compensation)\b", text, re.I)
    if cm:
        notes.append(f"The listing mentions a buyer agent commission of {float(cm.group(1)):g}%. No amount is saved and it is not counted anywhere. Ask who pays it and whether it changes what you owe.")
    for pat in (r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?[ \t]+(?:\w+[ \t]+)?transfer[ \t]+fee\b", r"\btransfer[ \t]+fee\b[ \t:\-=]{0,4}(?:of[ \t]+)?\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?!\d)"):
        t = re.search(pat, text, re.I)
        if t:
            notes.append(f"The listing mentions a ${_num(t.group(1)):,.0f} transfer fee. It is not counted anywhere. Ask what it is for and who pays it.")
            break
    return notes


def _free_rent_match(text: str) -> re.Match[str] | None:
    """The first free-rent wording in the text. A bare "concession" next to seller, buyer or closing words is a seller
    concession (money toward a buyer's closing costs), never a free-rent offer."""
    for m in _NET_FREE_RENT.finditer(text):
        if m.group(0).lower().startswith("concession"):
            around = text[max(0, m.start() - 60):m.end() + 60]
            if re.search(r"\b(?:seller|buyer|closing|offer|credit)\b", around, re.I):
                continue
        return m
    return None


def _price_cut(text: str) -> float | None:
    """The size of a price cut ("Price reduced $10,000", "reduced by $10,000"), never the new price ("reduced to $...")."""
    m = re.search(r"\b(?:price[ \t]+(?:reduced|cut|drop(?:ped)?|reduction)|reduced|price[ \t]+change)[ \t:\-]*(?:by[ \t]+)?\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?!\d)", text, re.I)
    if not m or re.search(r"\bto\s*$", text[max(0, m.start(1) - 8):m.start(1)], re.I):
        return None
    if re.match(r"(?:\.\d\d)?[ \t]*(?:off|from|on)\b[^.\n;)]{0,20}\b(?:deposit|fees?|application|admin)\b", text[m.end():], re.I):
        return None  # "REDUCED $1,950 off the deposit": a smaller deposit, not a lower price
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


def _assessment_amount(sentence: str, *, skip_monthly: bool = False) -> float | None:
    """The dollar amount written next to the assessment words ("special assessment of $4,000", "$4,000 special assessment"). A price
    or any other number in the same sentence is never taken as the assessment."""
    num = r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?!\d)(?!,\d)"
    tail = r"(?!\s*(?:/\s*mo|per month|monthly|a month|/\s*y(?:ea)?r|per year|a year|yearly|annual|each year|for\s+\d+\s+(?:years?|yrs?)))" if skip_monthly else ""
    m = re.search(r"\bassessments?(?:\s*\([^)\n]{0,20}\))?[ \t]*(?:of|is|was|are|totaling|totals?|estimated at|approx\.?|about|around|for|at|[:=\-])?[ \t]*(?:of |approx\.? |about |around )?" + num + tail, sentence, re.I) \
        or re.search(num + r"(?:[ \t]*(?:one[- ]time|new|pending|upcoming|current))?[ \t]*(?:special[ \t]+)?assessments?\b", sentence, re.I)
    return _num(m.group(1)) if m else None


_PAYER_SELLER = re.compile(r"\b(?:seller|owner)\b[^.\n]{0,25}\b(?:pays?|paid|to pay|responsib\w*|covers?|credit)\b|\bpaid (?:in full )?by (?:the )?(?:seller|owner)\b|\b(?:seller|owner)[- ]paid|\bpayable (?:in full )?by (?:the )?(?:seller|owner)\b|\bdue from (?:the )?(?:seller|owner)\b|\bresponsibility of (?:the )?(?:seller|owner)\b", re.I)
_PAYER_BUYER = re.compile(r"\bbuyer\b[^.\n]{0,25}\b(?:pays?|assumes?|to pay|responsib\w*|takes?|inherits?|covers?)\b|\bresponsibility of (?:the )?buyer\b|\bpaid by (?:the )?buyer|\bassumed by (?:the )?buyer|\bbuyer[- ]paid|\bpayable (?:in full )?by (?:the )?buyer|\bdue from (?:the )?buyer", re.I)


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
    amount = _assessment_amount(sentence, skip_monthly=True)
    payer = ""
    if _PAYER_SELLER.search(sentence):
        payer = "seller"
    elif _PAYER_BUYER.search(sentence):
        payer = "buyer"
    return amount, payer, sentence


def _assessment_monthly(text: str) -> tuple[float, int | None] | None:
    """("Assessment for windows: $150/month for 24 months") -> (150, 24). Months is None when the listing gives no length."""
    m = re.search(r"\bassessments?\b[^.\n$]{0,40}?\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?[ \t]*(?:/[ \t]*mo(?:nth)?\b|per[ \t]+month|a[ \t]+month|monthly|each[ \t]+month)"
                  r"(?:[^.\n]{0,15}?\b(?:for|x|over)[ \t]+(\d{1,3})[ \t]*(?:months?|mos?\b))?", text, re.I)
    if not m:
        return None
    return _num(m.group(1)), int(m.group(2)) if m.group(2) else None


def _assessment_yearly(text: str) -> tuple[float, int | None] | None:
    """"Annual assessment $1,200 for 3 years" -> (1200, 3). Years is None when the listing gives no length."""
    m = re.search(r"\b(?:(?:annual|yearly)[ \t]+(?:special[ \t]+)?assessments?|assessments?)\b[^.\n$]{0,30}?\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?(?!\d)[ \t]*(?:(?:/[ \t]*y(?:ea)?r|per[ \t]+year|a[ \t]+year|yearly|annually|each[ \t]+year)\b)?"
                  r"(?:[^.\n]{0,15}?\b(?:for|x|over)[ \t]+(\d{1,2})[ \t]*(?:years?|yrs?)\b)?", text, re.I)
    if not m:
        return None
    annual_word = re.search(r"annual|yearly|/[ \t]*y(?:ea)?r|per[ \t]+year|a[ \t]+year|annually|each[ \t]+year", m.group(0), re.I)
    if not annual_word:
        return None
    return _num(m.group(1)), int(m.group(2)) if m.group(2) else None


def _assessment_yearly_note(text: str) -> str:
    got = _assessment_yearly(text)
    if not got:
        return ""
    amount, years = got
    length = f" for {years} years (${amount * years:,.0f} in all)" if years else ""
    return (f"The listing mentions an assessment of ${amount:,.0f} a year{length}. It is not saved as the one-time special assessment, "
            f"because that field holds one one-time amount. Ask who pays it and how much is still owed.")


def _assessment_none(text: str) -> bool:
    """"Assessments: none", "No special assessments": the listing says there are none."""
    return bool(re.search(r"\bassessments?[ \t]*[:=\-][ \t]*(?:none|no|n/a|\$0)\b|\bno (?:known |pending |current |special )*assessments?\b", text, re.I)) \
        and not re.search(r"\bassessments?\b[^.\n]{0,40}\$\s?[1-9]|\$\s?[1-9][\d,]*[^.\n]{0,20}\bassessments?\b", text, re.I)


def _assessment_monthly_note(text: str) -> str:
    got = _assessment_monthly(text)
    if not got:
        return ""
    amount, months = got
    length = f" for {months} months (${amount * months:,.0f} in all)" if months else ""
    return (f"The listing mentions an assessment of ${amount:,.0f} a month{length}. It is not saved as the "
            f"one-time special assessment. Add it to other monthly fees if you will pay it, and ask who pays.")


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
    am = _assessment_amount(sentence, skip_monthly=True)
    if not am and (_assessment_monthly(sentence) or _assessment_yearly(sentence)):
        return ""  # a monthly or yearly assessment gets its own note
    if _PAYER_SELLER.search(sentence):
        who = "the seller pays it"
    elif _PAYER_BUYER.search(sentence):
        who = "the buyer pays it"
    else:
        who = ""
    if am:
        return f"Special assessment ${am:,.0f}: {who or 'the listing doesn' + chr(39) + 't say who pays it, so ask'}."
    if not who:
        return "A special assessment is mentioned but no amount is given, and the listing doesn't say who pays it. Ask what it is and who pays it, then set Who pays on this page."
    return f"A special assessment is mentioned but no amount is given: {who}. Ask what it is for and how much it is."


def _days_on_market(text: str) -> int | None:
    """"41 days on Zillow", "Days on market: 41", "Time on Redfin 41 days"."""
    site = r"(?:zillow|redfin|realtor(?:\.com)?|trulia|homes\.com|the market|market|site)"
    for pat in (r"\b(\d{1,4})\s+days?\s+on\s+" + site, r"\bdays?\s+on\s+(?:market|" + site + r")\s*[:\-]?\s*(\d{1,4})\b",
                r"\btime\s+on\s+" + site + r"\s*[:\-]?\s*(\d{1,4})\s+days?", r"(?<![\w$])(\d{1,4})\s*DOM\b", r"\bDOM\s*[:\-]?\s*(\d{1,4})\b",
                r"\b(?:listed|on the market|on market|posted)\s+(\d{1,4})\s+days?\s+ago\b"):
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
                        r"your own|set up (?:in|with)|not available|(?:you|tenants?|residents?|renters?)\s+(?:will\s+)?(?:sets?|opens?)\s+(?:it\s+|them\s+)?up|set up by (?:you|the (?:tenants?|residents?|renters?)))\b", re.I)
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
        if re.search(r"\b(?:included|paid|covered|provided)\b", m.group(2), re.I):
            continue  # "All utilities except cable included": the landlord covers all but those, the reverse of what this reads
        out += [w for w in re.findall(_ROLE_WORD, m.group(2).lower())]
    return out


def _tenant_pays(text: str) -> str:
    """"Tenant pays gas, electric" from "Tenant pays gas and electric" (utilities the listing says the renter pays), or ''."""
    low = text.lower()
    words = "|".join(re.escape(w) for w in _UTILITY_WORDS) + "|electricity|garbage|trash removal|sewage"
    found: list[str] = []
    for clause in re.split(r"\n|;|\.(?=\s|$)", low):
        m = re.search(r"\b(?:tenants?|residents?|renters?|lessees?|you)\s*(?:pays?|are responsible for|is responsible for|responsible for|will pay|must pay|to pay|(?:sets?|opens?|arranges?) up|(?:sets?|opens?) (?:their|your) own)\b\s*(?:for\s+)?(?:all\b\s*)?(?:the\s+)?(.*)", clause)
        if not m:
            continue
        rest = re.split(r"[,;]\s*(?:and\s+)?(?:i|we|the\s+landlord|landlord|owner|management)\s+(?:will\s+)?(?:pay|pays|cover|covers|provide|provides|handle|handles)\b", m.group(1))[0]
        found += re.findall(r"\b(?:" + words + r")\b", rest)
        bare_all = not rest.strip() and re.search(r"\ball\s*$", clause[:m.start(1)])  # "Tenant pays all."
        if bare_all or (re.match(r"\s*utilities\b", rest) and not re.match(r"\s*utilities[^.\n]{0,20}\b(?:except|other than|besides)\b", rest)):
            # "Tenant responsible for all utilities", "Tenant pays all": every utility the listing doesn't say is included
            said_included = set(_utility_roles(low)["landlord"])
            found += [w for w in _ALL_UTILITIES if w not in said_included]
    left_out = {"trash" if w in ("garbage", "trash removal") else "electric" if w == "electricity" else "sewer" if w == "sewage" else w for w in _all_except(low)}
    if left_out:
        found = [w for w in found if w not in left_out] + [w for w in _ALL_UTILITIES if w not in left_out]
    return _ordered_utilities(found) if found else ""


_ALL_UTILITIES = ("electric", "gas", "water", "sewer", "trash", "heat")  # what "all utilities" means for a renter who pays them


_UTILITY_ALIASES = ((r"\b(?:valet[ -]trash|trash[ -]valet|valet[ -]waste|doorstep (?:trash|garbage))\b", "valet-waste"), (r"\bpg\s*(?:&|and)\s*e\b", "electric and gas"), (r"\bameren\b", "electric and gas"),
                    (r"\bcomed\b", "electric"), (r"\bnicor\b", "gas"), (r"\bhydro\b(?!\s*-?\s*(?:flask|jug))", "electric"),
                    (r"\brubbish\b", "trash"), (r"\brefuse\b(?!\s+to\b)", "trash"),
                    # cable is TV: it is internet only when the text pairs it with internet ("cable/internet"), never alone
                    (r"\bcable\s*(?:/|&|,|\band\b|\+|-)?\s*(?:internet|wi-?fi|broadband)\b|\b(?:internet|wi-?fi|broadband)\s*(?:/|&|,|\band\b|\+|-)\s*cable\b", "internet"),
                    (r"\bgas[ -]heat(?:ing)?\b(?!\s*(?:is|are)\b)", "gas"))


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
    text = re.sub(r"[!?]+(?=[ \t]+\S)", ".", text)  # "except electric! Heat + water included" is two sentences
    text = _INCL_ABBREV[0].sub("all utilities included", text)
    text = _INCL_ABBREV[1].sub("utilities included", text)
    text = _INCL_ABBREV[2].sub(lambda m: "includes " + m.group(1), text)
    for pat, word in _UTILITY_ALIASES:
        if word in ("electric and gas", "electric", "gas"):
            pat = r"(?<!through )(?<!via )(?<!thru )(?<!from )(?<!with )" + pat  # "Electric through Ameren" names who the bill is with, not a second utility
        text = re.sub(pat, word, text, flags=re.I)
    # "Tenant pays PG&E, water and trash included": the last comma part is the included one, so it is its own sentence
    text = _PAYS_THEN_INCLUDED.sub(r"\1. \2", text)
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
            return _flat_util_fee(low, words) or _billed_back_loose(low, words) or _billed_back_unnamed(low)
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
    # "Gas average $90 billed back by landlord monthly": the amount has no unit, the word monthly comes after billed back
    m = re.search(lst + r"[:\-]?\s*(?:avg\.?|average|about|approx\.?|approximately|around|roughly|~)?\s*\$\s?(\d{1,4})(?:\.\d\d)?(?![\d,])\s*(?:" + monthly + r")?" + back
                  + r"[^.\n;$]{0,30}?(?:" + monthly + r"|each month|every month)", low)
    if m:
        found = re.findall(words, m.group(1))
        return (_ordered_utilities(found), float(m.group(2))) if found else None
    return None


_NOT_UTILITY_LINE = re.compile(r"\b(?:parking|garages?|carports?|storage|lockers?|pets?|cats?|dogs?|animals?|applications?|app fee|screening|deposit|amenity|bike|valet|trash valet|hoa|association|rent)\b", re.I)


def _billed_back_unnamed(low: str) -> tuple[str, float] | None:
    """"Utilities billed back via RUBS, avg $120/mo": a monthly amount with no utility named. Returns ("", 120)."""
    monthly = r"(?:/\s*mo(?:nth)?|per month|monthly|a month)"
    if not re.search(r"\brubs\b|\bbilled[ -]back\b|\bratio utility billing\b|\butilities? (?:are )?billed\b|\bsubmetered\b", low):
        return None
    # The amount must sit in a line that talks about utilities: a garage, parking, storage, pet or application line
    # next to a "billed back" line is not the utilities bill.
    for m in re.finditer(r"\b(?:avg\.?|average|averages|about|approx\.?|approximately|around|~|roughly|typically|usually)?\s*\$\s?(\d{1,4})(?:\.\d\d)?\s*" + monthly, low):
        if re.search(r"deposit|fee|one[- ]time|set[- ]?up", low[max(0, m.start() - 25):m.end() + 25]):
            continue
        start = max(low.rfind("\n", 0, m.start()), low.rfind(";", 0, m.start()), *(i.start() for i in re.finditer(r"\.(?=\s)", low[:m.start()])))
        ends = [e for e in (low.find("\n", m.end()), low.find(";", m.end())) if e >= 0] + [i.start() + m.end() for i in re.finditer(r"\.(?=\s|$)", low[m.end():])]
        clause = low[start + 1:min(ends) if ends else len(low)]
        if _NOT_UTILITY_LINE.search(clause):
            continue
        if re.search(_ROLE_ITEM, clause) and not re.search(r"\bbilled|\brubs\b|\butilit|\bcharged|\bpassed", clause):
            continue  # "Water/sewer billed back by usage. Trash $15/mo.": the $15 is the trash fee, not the utilities bill
        return ("", float(m.group(1)))
    return None


def _flat_util_fee(low: str, words: str | None = None) -> tuple[str, float] | None:
    """"Water, sewer & trash flat fee $60/mo", "Water, sewer and trash: flat $55 monthly", "Flat fee $85/mo covers water,
    sewer and trash" -> (utilities, monthly amount). The tenant pays that fee every month, so it is counted like a
    billed-back amount. None when the text has no such line."""
    words = words or ("|".join(re.escape(w) for w in _UTILITY_WORDS) + "|garbage|sewage|electricity")
    low = low.lower()
    monthly = r"(?:/\s*mo(?:nth)?|per month|monthly|a month)"
    lst = r"((?:(?:" + words + r")[ \t]*(?:,|/|&|and|\+)?[ \t]*(?:and[ \t]+)?){1,6})"
    flat = r"flat(?:[ -]?(?:fee|rate|charge))?"
    m = re.search(lst + r"[:\-]?[ \t]*(?:utilit\w*[ \t]+)?" + flat + r"[ \t:\-]*\$\s?(\d{1,4})(?:\.\d\d)?\s*" + monthly, low)
    if m:
        found = re.findall(words, m.group(1))
        return (_ordered_utilities(found), float(m.group(2))) if found else None
    m = re.search(lst + r"[:\-]?[ \t]*\$\s?(\d{1,4})(?:\.\d\d)?\s*" + monthly + r"[ \t,]*(?:is[ \t]+)?" + flat + r"\b", low)
    if m:  # "Water/sewer/trash $65/mo flat"
        found = re.findall(words, m.group(1))
        return (_ordered_utilities(found), float(m.group(2))) if found else None
    m = re.search(lst + r"[:\-]?[ \t]*\$\s?(\d{1,4})(?:\.\d\d)?[ \t]*flat(?:[ -]?(?:fee|rate|charge))?[ \t]*" + monthly + r"\b", low)
    if m:  # "water $60 flat monthly"
        found = re.findall(words, m.group(1))
        return (_ordered_utilities(found), float(m.group(2))) if found else None
    m = re.search(r"\b" + flat + r"[ \t:\-]*\$\s?(\d{1,4})(?:\.\d\d)?\s*" + monthly + r"[ \t,]*(?:\(?(?:which[ \t]+)?(?:covers?|includes?|for)\)?)[ \t:]*" + lst, low)
    if m:
        found = re.findall(words, m.group(2))
        return (_ordered_utilities(found), float(m.group(1))) if found else None
    return None


_PROVIDERS = (r"ameren|pg\s*(?:&|and)\s*e|pge|comed|nicor|xcel|duke energy|con ?ed(?:ison)?|national grid|dte|peco|pseg|eversource|entergy|"
              r"sdg\s*&\s*e|socal (?:edison|gas)|the (?:electric|gas|power|utility) (?:company|co\.?)|(?:the )?local (?:electric|gas|power|utility)(?: company)?")


def _through_provider(text: str) -> list[str]:
    """Utilities the renter sets up with a named provider: "Electric and gas through PG&E", "Electric through Ameren, you set
    up". Read from the raw words before the provider, so "Electric through Ameren" is electric only."""
    words = "|".join(re.escape(w) for w in _UTILITY_WORDS) + "|electricity|garbage|trash removal|sewage"
    out: list[str] = []
    for clause in re.split(r"\n|;|\.(?=\s|$)", text.lower()):
        for m in re.finditer(r"((?:(?:" + words + r")[ \t]*(?:,|/|&|and|\+)?[ \t]*(?:and[ \t]+)?){1,6})[ \t]*(?:\(\s*)?(?:through|via|thru|with|from|:)[ \t]+(?:" + _PROVIDERS + r")\b", clause):
            if re.search(r"\b(?:landlord|owner|management)\s*(?:pays?|covers?)\b|\bincluded\b", clause[:m.start()] + clause[m.end():m.end() + 25]):
                continue
            out += re.findall(words, m.group(1))
    return [w for w in _ordered_utilities(out).split(", ") if w]


_ISPS = r"xfinity|comcast|spectrum|at&t|att|verizon|fios|cox|frontier|centurylink|google fiber|optimum|altice|wow|astound|starlink|t-mobile"


def _internet_by_provider(text: str) -> list[str]:
    """"Internet by Xfinity, tenant sets up": the renter arranges and pays the internet. ["internet"] only when the same line
    says the tenant sets it up or pays for it, or []."""
    for clause in re.split(r"\n|;|\.(?=\s|$)", text.lower()):
        if re.search(r"\b(?:internet|wi-?fi)\b[^.\n;]{0,15}\b(?:by|through|via|thru|with|from)\s+(?:" + _ISPS + r")\b", clause) \
                and re.search(r"\b(?:tenants?|you|residents?|renters?)\b[^.\n;]{0,20}\b(?:sets?|pays?|arranges?|opens?|responsible|handles?|own)\b|\bset up by (?:you|the (?:tenants?|residents?|renters?))\b", clause) \
                and not re.search(r"\b(?:landlord|owner|management)\s+(?:pays?|covers?|provides?)\b|\bincluded\b", clause):
            return ["internet"]
    return []


def _everything_except(text: str) -> list[str] | None:
    """The utilities left out of "Everything included except cable" (cable and wifi count as internet). None when the
    text has no such phrase, or names something that is not a utility."""
    for clause in re.split(r"\n|;|\.(?=\s|$)", text.lower()):
        m = re.search(r"\b(?:everything|all bills|all utilities and (?:internet|cable|wifi))\s+(?:is\s+|are\s+)?(?:included|paid|covered)\s+(?:except(?:\s+for)?|other than|besides|but not)\s+([^.\n;]{0,60})", clause)
        if not m:
            # "All utilities except cable included": the same meaning with the words the other way round
            m = re.search(r"\ball\s+(?:the\s+)?utilities\s+(?:except(?:\s+for)?|other than|besides)\s+([^.\n;]{0,60}?)\s*(?:are\s+|is\s+)?(?:all\s+)?(?:included|paid|covered|provided)\b", clause)
        if not m:
            continue
        rest = m.group(1)
        found = re.findall(_ROLE_WORD, rest)
        left = re.sub(_ROLE_WORD, " ", rest)
        if found and not re.search(r"[a-z]{3,}", re.sub(r"\b(?:and|or|the|a|for|only|service|services|tv|plan|your|own)\b", " ", left)):
            return [w for w in _ordered_utilities(found).split(", ") if w]
    return None


def _join_names(words: list[str]) -> str:
    """["electric", "gas"] -> "electric and gas"; three or more -> "a, b and c"."""
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1] if words else ""


def _util_verb(names: str) -> str:
    """"is" for one utility, "are" for several ("Water is", "Water, sewer, trash are")."""
    return "is" if names and "," not in names else "are"


def _plus_utilities_unknown(text: str) -> bool:
    """"Rent: $1,150 + utilities": the renter pays utilities, but the listing does not say which ones."""
    return bool(re.search(r"\+\s*(?:all\s+)?(?:the\s+)?utilit(?:y|ies)\b|\bplus\s+(?:all\s+)?(?:the\s+)?utilit(?:y|ies)\b|\butilit(?:y|ies)\s+(?:are\s+)?(?:extra|separate|not included)\b", text, re.I))


def listing_billed_names(text: str) -> list[str]:
    """Public: the utilities a listing's billed-back amount covers ("trash" for "$25/mo billed back for trash"), or []."""
    try:
        billed = _billed_back(_util_text(_tidy(text or "")))
        if billed:
            names = [w.strip() for w in billed[0].split(",") if w.strip()]
            if not names:
                # an amount that names no utility: assume water, sewer and trash, minus anything named as tenant-paid elsewhere
                utext = _util_text(_tidy(text or ""))
                paid = set(_utility_roles(utext)["tenant"]) | set(w.strip() for w in _tenant_pays(utext).split(",")) | set(_util_sections(utext)["pays"])
                names = [w for w in ("water", "sewer", "trash") if w not in paid]
            return names
        return [w.strip() for w in _ordered_utilities(list(_utility_roles(_util_text(_tidy(text or "")))["billed"])).split(",") if w.strip()]
    except Exception:
        return []


_ROLE_WORD = (r"hot water|water|sewer|sewage|trash removal|trash|garbage|gas|electricity|electric|heat|internet|wi-?fi|cable")
_ROLE_ITEM = r"\b(?:" + _ROLE_WORD + r")\b(?!\s+(?:stove|range|oven|fireplace|cooktop|grill|appliances?|water heater|pump|bill\b|meter))"
_ROLE_LIST_RAW = _ROLE_ITEM + r"(?:\s*(?:,|/|&|\+|\band\b)\s*" + _ROLE_ITEM + r")*"
_PAYS_THEN_INCLUDED = re.compile(
    r"(\b(?:tenants?|residents?|renters?|you)\s+(?:pays?|are\s+responsible\s+for|is\s+responsible\s+for|responsible\s+for|will\s+pay|must\s+pay)\s+(?:for\s+)?" + _ROLE_LIST_RAW + r")"
    r"[ \t]*,[ \t]*(" + _ROLE_LIST_RAW + r"[ \t]+(?:(?:is|are)[ \t]+)?(?:all[ \t]+)?(?:included|covered|provided)\b)", re.I)
_ROLE_LIST = re.compile(_ROLE_ITEM + r"(?:\s*(?:,|/|&|\+|\band\b|\bor\b)\s*" + _ROLE_ITEM + r")*", re.I)
_TENANT_SUFFIX = re.compile(
    r"^(?:\s*(?:[:\-]|through|via|thru|from|with)\s*[a-z][\w&'.]*(?:\s+[a-z][\w&'.]*){0,2}\s*,)?[\s,\-]*(?:(?:is|are)\s+)?(?:(?:the\s+)?(?:tenants?|residents?|renters?)\s+(?:pays?|sets?\s+up|signs?\s+up|arranges?|opens?\s+(?:the|an?)\s+account)\b|(?:you|(?:the\s+)?(?:tenants?|residents?|renters?))\s+(?:will\s+)?(?:sets?|opens?)\s+(?:it\s+|them\s+)?up\b|set\s+up\s+by\s+(?:you|(?:the\s+)?(?:tenants?|residents?|renters?))\b|paid\s+(?:for\s+)?by\s+(?:the\s+)?(?:tenants?|residents?|renters?)\b|(?:tenants?|residents?|renters?)[- ]paid\b|(?:the\s+)?(?:tenants?|residents?|renters?)'?s?\s+(?:responsibility|expense)\b|"
    r"extra\b|not\s+(?:included|covered|provided)\b|(?:paid\s+|billed\s+|metered\s+)?separate(?:ly)?\b|billed\b|charged\b|passed\s+through\b|"
    r"your\s+own\b|additional\b|excluded\b|at\s+(?:the\s+)?(?:tenant|resident)'?s?\s+expense\b)", re.I)
_LANDLORD_SUFFIX = re.compile(
    r"^\s*(?:(?:is|are)\s+)?(?:paid\s+(?:for\s+)?by\s+(?:the\s+)?(?:landlord|owner|management)\b|included\b|covered\b|provided\b|paid\b|free\b)", re.I)
_TENANT_PREFIX = re.compile(
    r"(?:\b(?:tenants?|residents?|renters?|lessees?|you)\s*(?:pays?|are responsible for|is responsible for|responsible for|will pay|must pay|to pay|covers?|handles?)\b"
    r"|\b(?:tenant|resident|renter)[- ]paid\s*[:\-]|\bplus\b|\bextra\b|\bnot included\s*[:\-]?|\bexcluding\b)", re.I)
_LANDLORD_PREFIX = re.compile(
    r"(?:\b(?:landlord|owner|management|property manager|lessor)\s*(?:pays?|covers?|provides?)\b|\b(?:i|we)\s+(?:will\s+)?(?:pay|cover|provide)s?\b|\b(?:rent |lease )?includes?\b|\bincluded\s*[:\-]|\bincluding\b)", re.I)
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
    per: tuple[float, str] | None = None
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
                    if amount is None:
                        raw = float(bm.group(1).replace(",", ""))
                        div = _period_divisor(tail[bm.end():bm.end() + 20], sentence)
                        amount = round(raw / div, 2)
                        if div != 1:
                            per = (raw, "quarter" if div == 3 else "year")
            elif ls:
                role, used = "landlord", ls.end()
            else:
                role = _last_role(sentence[cursor:m.start()])
            cursor = m.end() + used
            if role == "tenant":
                tenant += words
            elif role == "landlord":
                landlord += words
    return {"tenant": tenant, "landlord": landlord, "billed": billed, "amount": amount, "per": per}


def _period_divisor(after: str, sentence: str = "") -> int:
    """How many months an amount covers: 3 for "$180 per quarter" or a "quarterly" sentence, 12 for a year, else 1."""
    m = re.match(r"[ \t]*(?:/|per|a|each|every)?[ \t]*(?:(quarter(?:ly)?|qtr)|(year(?:ly)?|yr|annual(?:ly)?)|(?:month(?:ly)?|mo)\b)", after, re.I)
    if m:
        return 3 if m.group(1) else 12 if m.group(2) else 1
    if re.search(r"\bquarterly\b|\bper quarter\b|\bevery (?:three|3) months\b", sentence, re.I):
        return 3
    if re.search(r"\bannual(?:ly)?\b|\byearly\b|\bper year\b|/\s*yr\b", sentence, re.I):
        return 12
    return 1


_APPROX_ANY = r"(?:est\.?|estimated|approx\.?|approximately|about|around|roughly|~|avg\.?|averages?|average)"
_ROLE_LST = r"((?:" + _ROLE_ITEM + r"[ \t]*(?:,|/|&|and|\+)?[ \t]*(?:and[ \t]+)?){1,6})"
_NOT_MONTHLY_AFTER = r"(?![ \t]*(?:/[ \t]*(?:yr|year|qtr|quarter)|per[ \t]+(?:yr|year|quarter)|a[ \t]+(?:year|quarter)|quarterly|annual|yearly|deposit|fee|one[- ]time))"
_NAMED_ESTIMATE = (
    re.compile(_ROLE_LST + r"[ \t]*[:\-]?[ \t]*(?:is[ \t]+|are[ \t]+|runs[ \t]+)?" + _APPROX_ANY + r"[ \t]*\$[ \t]*(\d{2,4})(?:\.\d\d)?(?![\d,])" + _NOT_MONTHLY_AFTER, re.I),
    re.compile(r"\b(?:avg\.?|average|typical)[ \t]+" + _ROLE_LST + r"[ \t]*(?:is[ \t]+|are[ \t]+|of[ \t]+)?(?:" + _APPROX_ANY + r"[ \t]*)?\$[ \t]*(\d{2,4})(?:\.\d\d)?(?![\d,])" + _NOT_MONTHLY_AFTER, re.I),
)


def _named_estimate(text: str) -> tuple[str, float] | None:
    """"water/sewer/trash approximately $60 a month", "Resident pays electric ~$90 average", "Avg electric around $55": the
    listing's own rough monthly figure for named utilities, as (utilities, amount). The utility words must come right before
    an approximate figure, and the line must not say they are included or be a parking, pet or fee line."""
    for clause in re.split(r"\n|;|\.(?=\s|$)", text.lower()):
        if re.search(r"\b(?:included|covered|provided|landlord pays|owner pays|billed|flat|rubs)\b", clause) or _NOT_UTILITY_LINE.search(clause):
            continue
        for pat in _NAMED_ESTIMATE:
            m = pat.search(clause)
            if m and 10 <= float(m.group(2)) <= 2000:
                names = _ordered_utilities(re.findall(_ROLE_WORD, m.group(1)))
                names = ", ".join(w for w in names.split(", ") if w and w != "cable")
                if names:
                    return names, float(m.group(2))
    return None


_PERIODIC_UTIL = (
    re.compile(r"\b(quarterly|annual|yearly)[ \t]+utilit(?:y|ies)(?:[ \t]+(?:bill|bills|cost|costs|charge|estimate|average|total))?[ \t]*(?:is|are|of|:|-)?[ \t]*(?:" + _APPROX_ANY + r"[ \t]*)?\$[ \t]*(\d[\d,]{1,5})(?:\.\d\d)?(?![\d,])", re.I),
    re.compile(r"\butilit(?:y|ies)(?:[ \t]+(?:bill|bills|cost|costs|charge|estimate|average|total))?[ \t]*(?:is|are|of|:|-)?[ \t]*(?:" + _APPROX_ANY + r"[ \t]*)?\$[ \t]*(\d[\d,]{1,5})(?:\.\d\d)?[ \t]*(?:/|per|a|each)[ \t]*(quarter|qtr|year|yr)\b", re.I),
)


def _periodic_utility_amount(text: str) -> tuple[float, float, str] | None:
    """"Quarterly utility bill about $210" -> (70.0, 210.0, "quarter"): a utilities bill that covers more than a month,
    as the monthly share, the amount in the listing and the period. None when the text has no such line."""
    for clause in re.split(r"\n|;|\.(?=\s|$)", text):
        if re.search(r"deposit|one[- ]time|set[- ]?up", clause, re.I):
            continue
        for i, pat in enumerate(_PERIODIC_UTIL):
            m = pat.search(clause)
            if not m:
                continue
            word = (m.group(1) if i == 0 else m.group(2)).lower()
            div, unit = (3, "quarter") if word.startswith(("quarter", "qtr")) else (12, "year")
            raw = float(m.group(2 if i == 0 else 1).replace(",", ""))
            if 10 <= raw / div <= 2000:
                return round(raw / div, 2), raw, unit
    return None


def _billed_unknown(low: str) -> bool:
    """"Utilities billed back via RUBS" with no amount and no utility named."""
    return bool(re.search(r"\brubs\b|\bratio utility billing\b|\butilit(?:y|ies)\b[^.\n;]{0,20}\bbilled[ -]back\b|\bbilled[ -]back\b[^.\n;]{0,25}\butilit", low))


_UTIL_EXTRA_AMOUNT = (
    re.compile(r"\butilit(?:y|ies)\b[ \t]*(?:are[ \t]+|is[ \t]+)?(?:extra|additional|separate|not included|on top|billed separately)?[ \t,:\-]*(?:est\.?|estimated|approx\.?|approximately|about|around|roughly|~|avg\.?|average)[ \t]*\$?[ \t]*(\d{2,4})(?:\.\d\d)?[ \t]*(?:/|per|a|each)[ \t]*(?:mo|month)\b", re.I),
    re.compile(r"\butilit(?:y|ies)\b[ \t]*(?:are[ \t]+|is[ \t]+)?(?:extra|additional|separate|not included|on top)\b[ \t,:\-]*(?:(?:est\.?|estimated|approx\.?|approximately|about|around|roughly|~|avg\.?|average)[ \t]*)?\$[ \t]*(\d{2,4})(?:\.\d\d)?[ \t]*(?:/|per|a|each)[ \t]*(?:mo|month)\b", re.I),
)


_UTIL_APPROX_WORD = r"(?:est\.?|estimated|approx\.?|approximately|about|around|roughly|~|avg\.?|average)"
_UTIL_APPROX_NOUNIT = re.compile(r"\butilit(?:y|ies)\b[ \t]*(?:are[ \t]+|is[ \t]+)?(?:extra|additional|separate|not included|on top)?[ \t,:\-]*" + _UTIL_APPROX_WORD
                                 + r"[ \t]*\$?[ \t]*(\d{2,4})(?:\.\d\d)?(?![\d,])(?![ \t]*(?:/[ \t]*(?:yr|year|qtr|quarter)|per[ \t]+(?:yr|year|quarter)|a[ \t]+(?:year|quarter)|quarterly|annual|yearly|deposit|fee))", re.I)
_UTIL_SAYS_PAYS = re.compile(r"\b(?:tenants?|residents?|renters?|you)\b[^.\n;]{0,25}\b(?:pays?|responsible|covers?)\b[^.\n;]{0,20}\butilit(?:y|ies)\b|\butilit(?:y|ies)\b[^.\n;]{0,25}\b(?:extra|additional|separate|not included|on top|tenant|resident)\b", re.I)
_UTIL_NEXT_AMOUNT = re.compile(r"^[ \t]*(?:about|approx\.?|approximately|around|roughly|est\.?|estimated|~|avg\.?|average|typically|usually)[ \t]*\$[ \t]*(\d{2,4})(?:\.\d\d)?[ \t]*(?:/[ \t]*mo(?:nth)?|per[ \t]+month|a[ \t]+month|monthly|each[ \t]+month)\b", re.I)


def _utilities_extra_amount(text: str) -> float | None:
    """"Utilities extra approx $150 per month": the listing's own monthly figure for utilities, or None. Also the sentence that
    follows a utilities line ("Tenant pays all utilities. Approx $180/month") and an approximate amount with no unit
    ("Utilities extra approx $150"). The amount must sit in a line about utilities, never a parking, pet or fee line."""
    for pat in _UTIL_EXTRA_AMOUNT + (_UTIL_APPROX_NOUNIT,):
        m = pat.search(text)
        if m and 10 <= float(m.group(1)) <= 2000:
            return float(m.group(1))
    parts = re.split(r"(?<=[.!\n;])[ \t]*", text)
    for i in range(len(parts) - 1):
        if _UTIL_SAYS_PAYS.search(parts[i]) and not re.search(r"\$\s?\d", parts[i]) and not _NOT_UTILITY_LINE.search(parts[i]):
            m = _UTIL_NEXT_AMOUNT.match(parts[i + 1])
            if m and 10 <= float(m.group(1)) <= 2000:
                return float(m.group(1))
    return None


def listing_utilities_flat_fee(text: str) -> bool:
    """Public: True when the listing's utilities amount is a flat monthly fee ("Water/sewer/trash $65/mo flat"), not a bill passed back."""
    try:
        text = _util_text(_tidy(text or ""))
        billed = _billed_back(text)
        return bool(billed) and _flat_util_fee(text) == billed
    except Exception:
        return False


def listing_hoa_in_rent(text: str) -> bool:
    """Public: True when the listing says the HOA dues are already part of the rent ("HOA dues of $120 per quarter included in your rent")."""
    try:
        low = _tidy(text or "").lower()
        return bool(re.search(r"\b(?:hoa|h\.o\.a\.|association|homeowners'? association)\b[^.\n;]{0,60}\b(?:included|covered|paid by (?:the )?(?:landlord|owner|management))\b[^.\n;]{0,25}\b(?:in|with|by)\b[^.\n;]{0,12}\b(?:rent|lease|landlord|owner|management)\b"
                               r"|\b(?:rent|lease)\s+(?:includes?|covers?)\b[^.\n;]{0,40}\b(?:hoa|association)\b|\b(?:landlord|owner|management)\s+(?:pays?|covers?)\b[^.\n;]{0,25}\b(?:hoa|association)\b", low))
    except Exception:
        return False


def listing_billed_amount(text: str) -> float | None:
    """Public: the monthly utilities bill a listing's text gives ("billed back at $85/month", "billed back monthly (avg $55)"), or None."""
    try:
        text = _util_text(_tidy(text or ""))
        billed = _billed_back(text)
        if billed:
            return billed[1]
        named = _named_estimate(text)
        periodic = _periodic_utility_amount(text)
        return _utility_roles(text)["amount"] or _utilities_extra_amount(text) or (named[1] if named else None) or (periodic[0] if periodic else None)
    except Exception:
        return None


_UTIL_HDR = re.compile(
    r"(?P<incl_a>\b(?:utilities\s+included|included\s+utilities|utilities\s+incl\w*|included)(?:[ \t]*[:\-]|[ \t]*(?=\n)))"
    r"|(?P<incl_b>\b(?:rent\s+includes?|includes|landlord\s+(?:pays|covers)|owner\s+(?:pays|covers))\b)"
    r"|(?P<pay_a>\b(?:(?:tenants?|residents?|renters?)\s+(?:pays?|responsib\w+|sets?\s+up)(?:\s+for)?|not\s+included|excluded|paid\s+by\s+(?:the\s+)?(?:tenants?|residents?|renters?))(?:[ \t]*[:\-]|[ \t]*(?=\n)))"
    r"|(?P<pay_b>\b(?:(?:tenants?|residents?|renters?|you)\s+(?:pays?|will\s+pay|must\s+pay|are\s+responsible\s+for|is\s+responsible\s+for|responsible\s+for|sets?\s+up)|tenant\s+responsib\w+)\b)"
    r"|(?P<full>\butilities[ \t]*:)", re.I)
_UTIL_ITEM = re.compile(_ROLE_ITEM, re.I)
_UTIL_OTHER = re.compile(r"(?:all\s+(?:the\s+)?(?:other|remaining)\s+utilit(?:y|ies)|any\s+other\s+utilit(?:y|ies)|other\s+utilit(?:y|ies)|everything\s+else)\b", re.I)
_UTIL_NONE = re.compile(r"(?:none|n/?a|nothing|no)\b", re.I)
_UTIL_UNPLACED = re.compile(r"(?:recycling|pest\s+control|snow\s+removal|lawn\s+care|landscaping|propane|heating\s+oil|oil|steam|fuel)\b", re.I)
_UTIL_EXCEPT = re.compile(r"(?:except(?:\s+for)?|excluding|other\s+than|but\s+not)\b", re.I)
_UTIL_SEP = re.compile(r"(?:[\s,/&+*•·]+|\band\b|\bor\b|\balso\b|[:\-]+(?=\s))+", re.I)
_COMMON_UTILITIES = ("electric", "gas", "water", "sewer", "trash", "internet")


def _read_util_items(text: str, pos: int) -> tuple[dict[str, Any], int]:
    """Read one list that follows a header like "Utilities included:" or "Tenant pays": one per line, or with commas, slashes,
    bullets, "+" or "and". Stops at the first thing that is not a utility word (or at a period). Returns the items, a
    "none" flag, an "other" flag ("all other utilities"), words it can't place, the words after an "except", and where it stopped."""
    got: dict[str, Any] = {"items": [], "none": False, "other": False, "unplaced": [], "exc": []}
    into = "items"
    first = True
    while pos < len(text):
        m = _UTIL_SEP.match(text, pos)
        if m:
            pos = m.end()
        if pos >= len(text):
            break
        if _UTIL_OTHER.match(text, pos):
            got["other"] = True
            pos = _UTIL_OTHER.match(text, pos).end()
        elif _UTIL_EXCEPT.match(text, pos) and into == "items" and got["items"]:
            into = "exc"
            pos = _UTIL_EXCEPT.match(text, pos).end()
        elif _UTIL_ITEM.match(text, pos):
            m = _UTIL_ITEM.match(text, pos)
            got[into] += re.findall(_ROLE_WORD, m.group(0).lower())
            pos = m.end()
        elif _UTIL_UNPLACED.match(text, pos):
            m = _UTIL_UNPLACED.match(text, pos)
            got["unplaced"].append(m.group(0).lower())
            pos = m.end()
        elif first and _UTIL_NONE.match(text, pos):
            m = _UTIL_NONE.match(text, pos)
            got["none"] = True
            pos = m.end()
        else:
            break
        first = False
    return got, pos


def _util_sections(text: str) -> dict[str, Any]:
    """The lists under headers such as "Utilities included", "Tenant pays" and "Utilities:" (a full list), read from the
    listing text. Keys: incl, pays, full, exc (moved out of included), other, none, unplaced, found (True when any header
    list was read)."""
    low = text.lower()
    res: dict[str, Any] = {"incl": [], "pays": [], "full": [], "exc": [], "other": False, "none": False, "unplaced": [], "found": False}
    pos = 0
    while True:
        h = _UTIL_HDR.search(low, pos)
        if not h:
            break
        got, end = _read_util_items(low, h.end())
        kind = h.lastgroup
        if kind in ("incl_a", "incl_b"):
            res["incl"] += got["items"]
            res["exc"] += got["exc"]
            res["none"] = res["none"] or got["none"]
        elif kind in ("pay_a", "pay_b"):
            res["pays"] += got["items"] + got["exc"]
            res["other"] = res["other"] or got["other"]
        else:
            res["full"] += got["items"]
        if got["items"] or got["none"] or got["other"]:
            res["found"] = True
        res["unplaced"] += got["unplaced"]
        pos = max(end, h.end())
    if re.search(r"\bno\s+utilities\s+(?:are\s+)?(?:included|covered|paid)\b|\bnone\s+included\b", low):
        res["none"] = True
    return res


def _apply_util_sections(text: str, included: str, pays: str, facts: list[str]) -> tuple[str, str]:
    """Fold the header lists into what the older readers found. "All" survives only when the listing says all utilities
    are included. A list under "Utilities included" is the included list, "Tenant pays" is what the tenant pays, a full
    "Utilities:" list with a shorter included list leaves the rest to the tenant, "None" means nothing is included."""
    sec = _util_sections(text)
    if sec["unplaced"]:
        names = ", ".join(dict.fromkeys(sec["unplaced"]))
        facts.append(f"The listing mentions {names} but doesn't say who pays for it. Ask the landlord.")
    low = text.lower()
    inc = [w for w in (included.split(", ") if included and included != "all" else []) if w]
    said_all = bool(re.search(r"\ball[- ]utilities[- ](?:are[- ])?(?:included|paid|covered)|\ball[- ]inclusive|\bincludes all utilities|\bincluded utilities\s*[:\-]\s*all\b", low))
    pay = [w for w in pays.split(", ") if w]
    if sec["none"] and not sec["incl"]:
        inc, included = [], ""
    elif sec["incl"]:
        if included == "all" and said_all:
            pass
        else:
            if sec["full"]:
                # a full "Utilities: gas, water" list is not the included list; only the "Included:" list is
                inc = [w for w in inc if w not in sec["full"] or w in sec["incl"]]
            included = _ordered_utilities(inc + sec["incl"])
    norm = {"garbage": "trash", "trash removal": "trash", "sewage": "sewer", "electricity": "electric"}
    sec_incl = [norm.get(w, w) for w in sec["incl"]]
    sec_full = [norm.get(w, w) for w in sec["full"]]
    if sec_full and sec_incl:
        pay += [w for w in sec_full if w not in sec_incl and w != "hot water"]
    pay += sec["pays"] + sec["exc"]
    if re.search(r"\bheat(?:ing)?\s+(?:is|are)\s+(?:by\s+)?gas\b", low) and "gas" in [norm.get(w, w) for w in pay]:
        pay.append("heat")
    if sec["exc"]:
        keep = [w for w in (included.split(", ") if included and included != "all" else []) if w not in [norm.get(x, x) for x in sec["exc"]]]
        included = _ordered_utilities(keep)
    if sec["other"]:
        have = {w for w in (included.split(", ") if included and included != "all" else [])}
        if included != "all":
            pay += [w for w in _COMMON_UTILITIES if w not in have]
    return included, _ordered_utilities(pay)


def _reconcile_utilities(included: str, pays: str, facts: list[str]) -> tuple[str, str]:
    """A utility goes in one list only. When the listing says a utility is both included and paid by the renter, it is kept
    as something the renter pays (the safer reading for the cost) and a note says the listing is unclear."""
    if not included or not pays:
        return included, pays
    if included == "all":
        # "All utilities included" can't hold when the listing also names something the tenant pays. Nothing is called
        # included then, and the note says what to ask.
        facts.append(f"The listing says utilities are included, but it also says you pay {pays}. Ask the landlord what the rent really covers.")
        return "", pays
    norm = {"wifi": "internet", "hot water": "water"}
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
    words = {"internet" if w == "wifi" else "water" if w == "hot water" else w for w in words}  # cable is TV, not internet
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
         r"(?P<day>\d{1,2})(?![\d])(?:st|nd|rd|th)?(?:,?\s*(?P<year>\d{4}))?)")


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


_MONTH_NAME = (r"(?P<mon>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)")
_AVAIL_LABEL = (r"\b(?:date available|availability|available(?: from| on| starting| beginning)?|avail\.?|move[- ]?in(?: date)?|lease start(?:s| date)?)\b[ \t:\-]{0,6}"
                r"(?:on |for |by |starting |beginning |in )?")


def _available_month_only(text: str) -> str:
    """"Move in Aug 2027": a month and year with no day. Returns the words as written ("Aug 2027"), or "" when there is none."""
    m = re.search(_AVAIL_LABEL + _MONTH_NAME + r"\.?[ \t,]+(?P<year>\d{4})\b(?![ \t]*[-/])", text.lower())
    if not m:
        return ""
    return f"{m.group('mon')[:1].upper()}{m.group('mon')[1:]} {m.group('year')}"


_LEASE_RANGE = re.compile(r"(?P<a>" + _DATE.replace("(?P<", "(?P<a_") + r")[ \t]*(?:to|through|thru|until|till|-|\u2013|\u2014)[ \t]*(?P<b>" + _DATE.replace("(?P<", "(?P<b_") + r")", re.I)


def _lease_dates(text: str) -> tuple[str | None, int | None, str]:
    """A lease written as dates: "Lease: Aug 1 2027 to Jul 31 2028" -> ("2027-08-01", 12, ""). Both ends need a year. When the
    span is not a whole number of months the length is left out and a note says so."""
    for line in text.lower().splitlines():
        m = _LEASE_RANGE.search(line)
        if not m or not (re.search(r"\b(?:lease|term|move|avail|from|start|begin|through|dates?)", line) or not line[:m.start()].strip()):
            continue
        def grab(prefix: str) -> str | None:
            keys = {k[len(prefix) + 1:]: v for k, v in m.groupdict().items() if k.startswith(prefix + "_") and v}
            if "year" not in keys and "iso" not in keys and not (keys.get("mdy") and re.search(r"[/.-]\d{2,4}$", keys["mdy"])):
                return None
            class _M:
                def group(self, name: str) -> str | None:
                    return keys.get(name)
            return _read_date(_M(), _today())  # type: ignore[arg-type]
        start, end = grab("a"), grab("b")
        if not start or not end:
            continue
        d1, d2 = date.fromisoformat(start), date.fromisoformat(end)
        if d2 <= d1:
            continue
        nxt = d2 + timedelta(days=1)
        months = (nxt.year - d1.year) * 12 + nxt.month - d1.month
        if months >= 1 and nxt.day == d1.day and 1 <= months <= 36:
            return start, months, ""
        return start, None, (f"The listing gives lease dates ({start} to {end}) that are not a whole number of months, so the lease length is left empty. "
                             "Ask how long the lease is.")
    return None, None, ""


def _lease_months(text: str) -> int | None:
    low = text.lower()
    found: list[tuple[int, int]] = []  # (where it is written, months): the one stated first wins
    for pat in (r"(?<![\d,-])(\d{1,2})[- ](?:month|mo\b)[- ]?(?:minimum |min\.? )?(?:lease|term|contract)",
                r"\b(?:lease|term|contract)s?(?: terms?| length| duration| options?)?\s*[:\-]?\s*(?:of |is |are )?(?<![-,\d] )(\d{1,2})\s*(?:months?|mos?\b)(?!\s*(?:,|and|or|/|to|-)\s*\d)",
                r"\b(\d{1,2})\s*months?\s+(?:lease|minimum|min\b)", r"(?<![\d,-])(\d{1,2})[- ]months?[- ](?:minimum|min\b)", r"\b(one|1)[- ]year (?:lease|term|contract)"):
        for m in re.finditer(pat, low):
            if _OFFER_LEASE.search(low[max(0, m.start() - 45):m.start()]):
                continue  # "One month free on a 13-month lease" is the length the deal needs, not the lease on offer
            if re.search(r"\b(?:or|instead)[ \t]+(?:sign|choose|take|pick|get|go)\w*[ \t]+(?:a[ \t]+|an[ \t]+)?$", low[max(0, m.start() - 20):m.start()]):
                continue  # "Lease 12 months, or sign a 18 month lease and get $100 off": the longer lease is a deal, not the lease on offer
            g = m.group(1)
            n = 12 if g in ("one", "1") and "year" in m.group(0) else int(g)
            if 1 <= n <= 60 and not re.search(r"\d\s*(?:,|-|to|or)\s*$", low[max(0, m.start() - 6):m.start()]):
                found.append((m.start(), n))
    return min(found)[1] if found else None


_LEASE_LIST = (r"\d{1,2}(?:[ \t]*(?:months?|mos?))?(?:[ \t]*(?:,|/|or|and|to|-)[ \t]*(?:or[ \t]+|and[ \t]+)?\d{1,2}(?:[ \t]*(?:months?|mos?))?)+")
_LEASE_CHOICES = (
    re.compile(r"\b(?:lease|term|contract)s?(?:[ \t]+(?:terms?|lengths?|options?|durations?))?[ \t]*(?:of|is|are|:|-)?[ \t]*(" + _LEASE_LIST + r")[ \t]*(?:months?|mos?\b)", re.I),
    re.compile(r"(?<![\d,$/-])(" + _LEASE_LIST + r")[ \t]*[- ]?(?:months?|mos?)\b[- ]*(?:leases?|terms?|contracts?|options?)", re.I),
)


def _lease_choices(text: str) -> str:
    """The lease lengths when the listing gives several ("12 or 15 month lease", "Lease terms 6, 12 or 15 months"), written for a note
    ("12 or 15 months"). Empty when there is one length or the numbers are a deal ("12 months, 1 month free")."""
    for rx in _LEASE_CHOICES:
        for m in rx.finditer(text):
            nums = [int(x) for x in re.findall(r"\d{1,2}", m.group(1))]
            if len(set(nums)) < 2 or not all(3 <= n <= 60 for n in nums):
                continue
            if re.match(r"[ \t]*(?:free|off|discount|concession|rent[ \t]+free)\b", text[m.end():], re.I):
                continue
            if re.search(r"\b(?:free|off|discount|concession)\b[^.\n;]{0,25}$", text[max(0, m.start() - 30):m.start()], re.I):
                continue
            seps = re.findall(r"\b(?:to)\b|[-]", re.sub(r"\d", "", m.group(1)))
            if len(nums) == 2 and seps:
                return f"{nums[0]} to {nums[1]} months"
            ordered = [str(n) for n in nums]
            return ", ".join(ordered[:-1]) + (" or " if len(ordered) > 1 else "") + ordered[-1] + " months"
    return ""


_OFFER_LEASE = re.compile(r"\b(?:free|off|discount|concession|special|incentive|promo\w*)\b[^.\n;!]{0,25}\b(?:on|with|for|if you sign|when you sign)\s+(?:a\s+|an\s+)?$", re.I)
_OFFER_LEASE_AFTER = re.compile(r"\b(?:free|off|discount|concession|special|incentive|promo\w*)\b[^.\n;!]{0,25}\b(?:on|with|for|if you sign|when you sign)\s+(?:a\s+|an\s+)?(\d{1,2})[- ]?(?:month|mo)s?\b", re.I)


def _lease_offer_note(text: str, lease: int | None) -> list[str]:
    """A deal that needs a different lease length than the one saved ("One month free on a 13-month lease")."""
    m = _OFFER_LEASE_AFTER.search(text)
    if not m:
        # "Lease 12 months, or sign a 18 month lease and get $100 off a month"
        m = re.search(r"\b(?:or|instead)[ \t]+(?:sign|choose|take|pick|get|go)\w*[ \t]+(?:a[ \t]+|an[ \t]+)?(\d{1,2})[- ]?(?:month|mo)s?\b[^.\n;!]{0,40}", text, re.I)
        if m and lease is not None and int(m.group(1)) != lease:
            return [f"The listing also offers a deal for a {m.group(1)} month lease. The {lease} month lease is what is saved, and the deal is not counted. Ask what you have to sign to get it."]
    if not m or (lease is not None and int(m.group(1)) == lease):
        return []
    if lease is None:
        return [f"The listing ties a deal to a {m.group(1)} month lease. That is not saved as the lease length, because it only says what the deal needs. Ask how long the lease is."]
    return [f"The listing ties a deal to a {m.group(1)} month lease, which is longer than the {lease} month lease that is saved. Ask what you have to sign to get the deal."]


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
    if re.search(r"\bno[ \t]+(?:hoa|h\.o\.a\.|homeowners'?[ \t]+association)(?:[ \t]+(?:fees?|dues))?\b|\bhoa(?:[ \t]+(?:fees?|dues))?[ \t]*[:\-=][ \t]*(?:none|no|n/a|\$0)\b|\bwithout[ \t]+(?:an?[ \t]+)?hoa\b|\b(?:hoa|association)[ \t]+(?:fees?|dues)?[ \t]*(?:\(none\)|not required)", text, re.I) \
            and not re.search(r"\$\s?[1-9]\d*(?:,\d{3})*(?:\.\d\d)?\s*(?:/\s*\w+|per\s+\w+|\w+ly)\s*(?:hoa|association)|\b(?:hoa|association)(?:[ \t]+(?:fees?|dues))?[ \t:\-=(]{0,6}\$\s?[1-9]", text, re.I):
        return 0.0
    m = re.search(r"(?:\bhoa|association|homeowners'? association|\b(?:monthly|building|unit owners?)[ \t]+dues(?![ \t]+(?:to|for)\b)|\bcondo(?=\s*(?:fee|fees|dues|payment|assessment))|\bcommon (?:area )?(?:charges?|fees?))(?:\s*(?:fee|fees|dues|payment|assessment))*[ \t:\-=(]{0,6}\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?\s*(/\s*\w+|per\s+\w+|\w+ly|annual\w*)?", text, re.I)
    if not m:
        m = re.search(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?\s*(/\s*\w+|per\s+\w+|\w+ly|annual\w*)?\s*(?:hoa|association) (?:fee|dues)?", text, re.I)
    if not m:
        return None
    value, per = _num(m.group(1)), (m.group(2) or "").lower()
    if not per:
        # "Quarterly HOA $240": the period comes before the label
        lead = re.search(r"\b(quarterly|annual(?:ly)?|yearly|semi-?annual(?:ly)?)[ \t]+$", text[max(0, m.start() - 16):m.start()], re.I)
        if lead:
            per = lead.group(1).lower()
            if per.startswith("semi"):
                return None  # twice a year: not a period this reader converts
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
        name, end = m.group(2), m.end()
        um = re.search(r"[ \t]+(?:apt|apartment|unit|suite|ste)\.?$", name, re.I)
        if um:  # "4620 N BROADWAY APT 402": the unit word belongs to the unit, not to the street name
            name, end = name[:um.start()], m.start(2) + um.start()
        words = [w.strip(".,").lower() for w in name.split()]
        if set(words) & _NOSUFFIX_BAD:
            continue
        if len(words) == 1 and len(words[0]) <= 1:
            continue
        line_start = text.rfind("\n", 0, m.start()) + 1
        if _NOSUFFIX_AFTER.match(text, end) or _NOSUFFIX_BEFORE.search(text[line_start:m.start()]):
            return " ".join((m.group(1) + " " + name).split()), end
    return None


# --------------------------------------------------------------------------- address
def _unit_ok(value: str | None) -> bool:
    """A lone N, S, E, W (or NE, NW, SE, SW) is a street direction, never a unit ("710 W Clark St, W")."""
    return bool(value) and not re.fullmatch(r"[NS][EW]?|[EW]", value.strip(". "), re.I)


_DIRECTIONS = {"N", "S", "E", "W", "NE", "NW", "SE", "SW"}


def _normal_case(value: str) -> str:
    """"720 S DEARBORN ST" -> "720 S Dearborn St", "CHICAGO" -> "Chicago". Only an all-caps value is changed; N, S, E, W, NE and
    so on stay upper case."""
    letters = [c for c in value if c.isalpha()]
    if len(letters) < 2 or value.upper() != value:
        return value

    def fix(m: re.Match[str]) -> str:
        w = m.group(0)
        if w in _DIRECTIONS:
            return w
        if re.fullmatch(r"\d+(?:ST|ND|RD|TH)", w):
            return w.lower()
        return w[:1] + w[1:].lower()

    return re.sub(r"[A-Za-z0-9][A-Za-z0-9']*", fix, value)


def street_with_unit(address: Any, unit: Any) -> str:
    """The street line to show: "210 Beck St" + unit "2" -> "210 Beck St #2", but "210 Beck St Apt 2" + unit "2" stays as it is."""
    street, u = str(address or "").strip(), str(unit or "").strip().lstrip("#").strip()
    if not u:
        return street
    if re.search(r"(?:\b(?:apt|apartment|unit|suite|ste|no)\b\.?[ \t]*#?[ \t]*|#[ \t]*)" + re.escape(u) + r"(?![\w-])", street, re.I):
        return street
    return f"{street} #{u}".strip()


_TRAILING_UNIT = re.compile(r"[ \t]*(?:[|,][ \t]*)?\b(?:apt|apartment|unit|suite|ste)\b\.?[ \t]*#?[ \t]*([A-Za-z]?\d{1,5}[A-Za-z]?(?:-\d{1,3})?|[A-Za-z])[ \t]*$", re.I)


def split_address_unit(address: Any, unit: Any = None) -> tuple[str, str]:
    """An address passed with its unit in it ("12 SPRUCE LANE | APT B", "210 Beck St Apt 2") gives (street, unit): the unit moves to its own
    field, and when the unit field already holds it, it is not said twice. A unit that differs from the one in the line is left alone."""
    street, u = str(address or "").strip(), str(unit or "").strip().lstrip("#").strip()
    m = _TRAILING_UNIT.search(street)
    if not m or not _unit_ok(m.group(1)) or len(street[:m.start()].strip()) < 4:
        return street, str(unit or "").strip()
    inside = m.group(1)
    if u and u.lower() != inside.lower():
        return street, str(unit or "").strip()
    return street[:m.start()].strip(" ,|"), u or inside


def _address(text: str) -> dict[str, str]:
    out = _address_raw(text)
    for key in ("address", "city"):
        if out.get(key):
            out[key] = _normal_case(out[key])
    return out


def _address_raw(text: str) -> dict[str, str]:
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
        tail = text[end:end + 120].replace("|", ",")  # "APT 402 | CHICAGO, IL": a pipe is a comma here
        cm = re.match(r"[ \t]*(?:,|\n)?[ \t]*(?:(?i:" + _UNIT + r")[ \t]*(?:,|\n)?[ \t]*)?([A-Z][A-Za-z.'-]+(?: [A-Z][A-Za-z.'-]+){0,3}),?[ \t]+([A-Z]{2})(?:[ \t]+(\d{5})(?:-\d{4})?)?\b", tail)
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
    if "unit" not in out and "address" in out:
        hm = re.search(r"(?<![\w&-])#[ \t]*([A-Za-z]?\d{1,5}[A-Za-z]?(?:-\d{1,3})?)(?![\w-])", text)
        if hm and _unit_ok(hm.group(1)):
            out["unit"] = hm.group(1)  # "#1204, 500 Main St"
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


_LABEL_PREFIX = re.compile(r"^(?:fb marketplace|facebook marketplace|fb|facebook|marketplace|craigslist|zillow|trulia|redfin|hotpads|zumper|apartments\.com|realtor\.com|"
                           r"rentals?|rental listing|for rent|for lease|listing|new listing|just listed)[ \t]*(?::|[-|\u2013\u2014])[ \t]+(?=\S)", re.I)
_SITE_LINE = re.compile(r"^(?:fb marketplace|zillow|realtor\.com|apartments\.com|trulia|redfin|craigslist|facebook(?: marketplace)?|hotpads|zumper|rent\.com|"
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


def _word_cut(text: str, limit: int) -> str:
    """Cut at a word boundary, never in the middle of a word."""
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    if text[limit] != " " and " " in cut:
        cut = cut[:cut.rfind(" ")]
    return cut.strip(" ,;:-|")


_STATUS_LINE = re.compile(r"^(?:listed|posted|updated|last updated|published|price (?:reduced|cut|drop)|days on|\d+\s+days?\b|new listing|just listed)\b", re.I)
_SENTENCE_LINE = re.compile(
    r"\b(?:rent|utilities|water|heat|gas|electric\w*|trash|sewer|internet|parking|pets?|deposit|lease|taxes)\b[^.\n]{0,25}\b(?:includes?|included|is|are|pays?|due|required|allowed|extra)\b|"
    r"\b(?:includes?|including)\s+(?:water|sewer|trash|heat|gas|electric\w*|utilities|internet)\b|\bbuilt\s+(?:in\s+)?(?:19|20)\d\d\b|\b(?:19|20)\d\d\s+(?:build|built)\b", re.I)
_FACT_LABEL_LINE = re.compile(r"^(?:facts?\s*(?:&|and)\s*features|key features|property details|home facts|interior details|what's special)\b|"
                              r"\b(?:bedrooms?|bathrooms?|beds|baths|sqft|square feet|year built|lot size|heating|cooling|appliances|flooring)\s*:", re.I)
_PRICE_IN_TITLE = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?[kK]?(?:\s*(?:/\s*mo\w*|per\s+month|a\s+month|monthly))?", re.I)


_PROMO_BANNER = re.compile(r"\*{2,}[^*\n]{0,40}\b(?:FREE|SPECIAL|OFF|DEALS?|MONTHS?|MOVE|NO FEE|LOOK|CONCESSIONS?|PRICE|WOW|NEW|HOT)\b[^*\n]{0,30}\*{2,}")


def _headline_clean(line: str) -> str:
    """A listing headline as a short name: no *** banners, no price (and nothing after it), no "!!!", no dangling word."""
    line = _PROMO_BANNER.sub(" ", line)
    line = line.replace("*", " ")
    line = re.sub(r"!+", " ", line)
    m = _PRICE_IN_TITLE.search(line)
    if m:
        before = line[:m.start()]
        if len(re.findall(r"[A-Za-z]", before)) >= 3:
            line = before
        else:
            line = line[:m.start()] + " " + line[m.end():]
    line = " ".join(line.split()).strip(" ,;:-|/\u2013\u2014")
    line = re.sub(r"[ \t]*(?:[-|:,\u2013\u2014][ \t]*)?\b(?:starting(?:[ \t]+at)?|starts?[ \t]+at|from|only|just|asking)[ \t]*$", "", line, flags=re.I)
    line = re.sub(r"\s+for\s+(?:rent|lease)$", "", line, flags=re.I)
    line = re.sub(r"(?:\s+(?:a|an|the|and|with|of|in|at|for|to|incl|inc))+\.?$", "", line, flags=re.I)
    return _word_cut(line.strip(" ,;:-|/\u2013\u2014"), 70)


def _craigslist_headline(text: str) -> tuple[str, str]:
    """"$1,375 / 1br - 640ft2 - Newer 1BR near campus (Urbana)" -> ("Newer 1BR near campus", "Urbana")."""
    for raw in text.splitlines()[:6]:
        line = " ".join(raw.strip(" \t|*#").split())
        if not re.match(r"^\$\s?[\d,]+\s*(?:/\s*)?(?:\d+\s*br\b|studio\b)", line, re.I):
            continue
        parts = [x.strip() for x in re.split(r"\s+[-\u2013\u2014]\s+", line)]
        keep = [x for x in parts if x and not _is_fact_line(x) and not re.match(r"^\$", x)]
        if not keep:
            return "", ""
        name = keep[0]
        city = ""
        cm = re.search(r"\(([A-Z][A-Za-z .'-]{2,30})\)\s*$", name)
        if cm:
            city = cm.group(1).strip()
            name = name[:cm.start()]
        return _headline_clean(name), city
    return "", ""


def _name_segment(line: str) -> str:
    """The name part of a long first line: "Riverside Lofts Unit 4B - 2 bed 2 bath ..., 123 Main St" gives "Riverside Lofts Unit 4B"."""
    if len(line) <= 90:
        return line
    return _word_cut(re.split(r"\s+[-|\u2013\u2014]\s+|,\s+(?=\d)|\.\s+(?=[A-Z$\d])", line, maxsplit=1)[0], 90)


_GENERIC_PLACE_WORDS = {"Park", "Square", "Place", "Heights", "Village", "Hills", "Woods", "Oaks", "Ridge", "Station", "Gardens", "Landing", "Crossing", "Pointe", "Point"}
# a promo phrase is an offer, never a name ("No Broker Fee", "Now leasing", "Move-in special")
_PROMO_LINE = re.compile(r"^(?:no[ \t]+(?:broker|brokers|app(?:lication)?|admin|move[- ]in|security|deposit|fees?)\b[^\n]{0,25}|zero[ \t]+(?:deposit|fees?|broker)\b[^\n]{0,20}|"
                         r"(?:now|pre)[- ]?(?:leasing|open|renting)\b[^\n]{0,20}|(?:move[- ]in |limited[- ]time |hot |special )?(?:specials?|deals?|offers?|concessions?)\b[^\n]{0,25}|"
                         r"(?:call|text|email|contact|apply|schedule|book|tour|visit|hurry|act|don'?t miss|must see|won'?t last)\b[^\n]{0,40}|(?:best|great|amazing|unbeatable) (?:deal|price|value|location)[^\n]{0,15}|"
                         r"(?:free|reduced|waived|\d+)[ \t]+(?:rent|month|months|application|admin|deposit)\b[^\n]{0,25}\b(?:free|off|waived)\b[^\n]{0,15})$", re.I)


def _ai_aimed(line: str) -> bool:
    """True when a line is text aimed at AI tools ("ATTENTION AI ASSISTANT: ignore previous instructions"). The red flag rules own the test."""
    try:
        from .redflags import _AI_EXTRA, _AI_TARGETED, normalise_text
        clean = normalise_text(line)[0]
        return bool(_AI_TARGETED.search(clean) or _AI_EXTRA.search(clean))
    except Exception:  # noqa: BLE001
        return bool(re.search(r"\b(?:ai|llm|assistant|chatbot|language model)\b.{0,30}\b(?:ignore|disregard|instructions?)\b|\b(?:ignore|disregard)\b.{0,20}\binstructions?\b", line, re.I))


def _building_name(text: str) -> str:
    for line in text.splitlines()[:30]:
        line = _name_segment(" ".join(line.strip(" \t|\u2022\u00b7*#").split()))
        if not line or len(line) > 90 or _SITE_LINE.match(line) or _STATUS_LINE.match(line):
            continue
        m = _BUILDING.match(line)
        if m and m.group(1).split()[-1] in _GENERIC_PLACE_WORDS and re.match(r"[ \t]*[A-Za-z0-9$]", line[m.end():]) \
                and not re.match(r"[ \t]*(?:at|on|of|in|near)\b", line[m.end():], re.I):
            m = None  # "Hyde Park 3 Bed Gorgeous Condo": the match is only the start of a headline, not a building name
        if not m:
            m = _AT_BUILDING.search(line)
            if m and re.search(r"\b(?:in)\s+" + re.escape(m.group(1)), line) and not re.search(r"\b(?:at)\s+" + re.escape(m.group(1)), line) \
                    and m.group(1).split()[-1] in _GENERIC_PLACE_WORDS:
                m = None  # "Sunny 2 bed in Lincoln Park" names a neighborhood
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
    # "2 bedroom duplex 1400 dollars a month": a price written in words is a fact, not part of the name
    cut = re.sub(r"[ \t,\-|]*\$?\d[\d,]*[ \t]*(?:dollars|bucks)\b(?:[ \t]*(?:a|per|/)[ \t]*(?:month|mo)\b)?.*$", "", out, flags=re.I).strip(" -|:,")
    return cut if len(cut) >= 3 else out


_ALL_CAPS_KEEP = ("LLC", "II", "III", "IV", "NE", "NW", "SE", "SW", "UIUC", "BR", "BA", "HOA", "USA", "UW", "UC", "MIT", "NYC", "SF", "LA")
_LABEL_LINE = re.compile(
    r"^(?:rent|monthly rent|deposit|security deposit|price|asking price|list price|taxes|tax|property tax(?:es)?|hoa(?: fees?| dues)?|pets?|pet policy|"
    r"pet rent|pet fee|utilities|utils|fees?|application fee|admin fee|parking|lease|lease term|term|available|availability|laundry|sq\.? ?ft|"
    r"square feet|beds?|baths?|contact|phone|year built|move[- ]in|cost|total|amenities|features|description|location|address|city|"
    r"neighborhood|heat|cooling|appliances|rates?)\b[ \t]*(?::|=|\$|-[ \t])", re.I)
_LABEL_NUMBER = re.compile(r"^(?:rent|deposit|security deposit|price|taxes|hoa|fees?)\b[ \t]+[\d$]", re.I)
_MONEY_LINE = re.compile(r"^(?:\$|\u20ac|\u00a3|\d[\d,.]*[ \t]*(?:/|per|a)[ \t]*(?:mo|month)|\d[\d,.]*[ \t]*(?:dollars|bucks)\b)", re.I)
_RULE_LINE = re.compile(r"^seller(?:'s)?[ \t]+(?:to|will|pays?|concessions?|credits?|contribut\w*)\b|^no[ \t]+(?:smoking|pets?|dogs?|cats?|animals?|section[ \t]*8|vouchers?|students?|roommates?|co-?signers?|evictions?|felon\w*)\b|"
                        r"^(?:first|last|one|two|three|\d{1,2})(?:st)?[ \t]+(?:month|week)s?\b[^.\n]{0,15}\bfree\b", re.I)
_PET_LINE = re.compile(r"^(?:no[ \t]+)?(?:pets?|dogs?|cats?|animals?)\b", re.I)


_HEDGE_END = re.compile(r"\b(?:about|around|approx\.?|approximately|roughly|avg\.?|average|estimated|est\.?|costs?|totals?|due|is|are|of)[ \t:=~]*$|[:=~][ \t]*$", re.I)
_HEDGE_ONLY_END = re.compile(r"\b(?:about|around|approx\.?|approximately|roughly|avg\.?|average|estimated|est\.?)[ \t:=~]*$", re.I)


def _money_line_cut(line: str) -> bool:
    """A money line with its amount cut off ("Quarterly utility bill about", "Quarterly utility bill about $210"): never a title."""
    m = _PRICE_IN_TITLE.search(line)
    if m:
        return bool(_HEDGE_END.search(line[:m.start()].rstrip()) or _HEDGE_END.search(line[:m.start()]))
    return bool(_HEDGE_ONLY_END.search(line.strip()))


_DATE_ONLY = re.compile(r"^(?:(?:lease|term|dates?|available|move[- ]?in)[ \t:]*)?(?:" + re.sub(r"\(\?P<\w+>", "(?:", _DATE) + r")(?:[ \t]*(?:to|through|thru|until|-|\u2013|\u2014)[ \t]*(?:" + re.sub(r"\(\?P<\w+>", "(?:", _DATE) + r"))?[ \t.]*$", re.I)


def _date_only_line(line: str) -> bool:
    """A line that is only a date or a date range ("Aug 1 2027 to Jul 31 2028"): never a title."""
    return bool(_DATE_ONLY.match(line.strip()))


def _title(text: str, found: dict[str, Any]) -> str:
    title = _clean_title(_title_raw(text, found)).strip(" ,;:-|\u2013\u2014")
    letters = [c for c in title if c.isalpha()]
    if len(letters) >= 4 and title.upper() == title:
        title = re.sub(r"\d*[A-Za-z][A-Za-z']*", lambda m: m.group(0) if m.group(0) in _ALL_CAPS_KEEP or re.fullmatch(r"\d+(?:BR|BA|BD)", m.group(0)) else m.group(0).capitalize(), title)
        title = re.sub(r"^The\b", "The", title)
    return _finish_title(title, text)


_FEATURE_WORD = re.compile(r"\b(?:garage|carport|laundry|w/d|w&d|washer|dryer|dishwasher|renovated|remodeled|updated|stainless|hardwood|balcony|patio|a/c|central air|parking|in[- ]unit|coin|fireplace|granite|appliances?)\b|w/d|w&d", re.I)
_PROPERTY_NOUN = re.compile(r"(?:\b|(?<=\d))(?:apartments?|apts?|house|home|condo|townhome|townhouse|duplex|studio|loft|flat|cottage|bungalow|villa|bed(?:room)?s?|br|bd|bdrm|rooms?|suite|unit [a-z0-9]+|place|lofts|residences?|community)\b", re.I)


def _feature_line(line: str) -> bool:
    """A line that only lists what the place has ("Attached 1-car garage included in rent", "Shared coin laundry in the building",
    "Newly renovated, W&D in unit, dishwasher, garage"): a feature, never the name of the place."""
    return bool(_FEATURE_WORD.search(line)) and not _PROPERTY_NOUN.search(line) and not _ADDRESS.match(line)


def _not_a_name(line: str) -> bool:
    """A line that is a field ("Rent $2", "Deposit: 1.5x rent", "Pets: dogs ok"), a money amount or a pet rule, never a title."""
    return bool(_RULE_LINE.match(line) or _PROMO_LINE.match(line) or _SITE_LINE.match(line) or _ai_aimed(line) or _LABEL_LINE.match(line) or _LABEL_NUMBER.match(line) or _MONEY_LINE.match(line) or _PET_LINE.match(line)
                or _FACT_LABEL_LINE.search(line) or _STATUS_LINE.match(line) or _SENTENCE_LINE.search(line) or _feature_line(line))


def _only_address_left(line: str, found: dict[str, Any]) -> bool:
    """True when a line is just the street address plus its unit, city, state and ZIP (and bed/bath words)."""
    addr = str(found.get("address") or "")
    if not addr or addr.lower() not in line.lower():
        return False
    rest = re.sub(re.escape(addr), " ", line, flags=re.I)
    rest = re.sub(r"\b(?:unit|apt\.?|apartment|suite|ste\.?)[ \t]*#?[ \t]*[A-Za-z]?\d{1,5}[A-Za-z]?\b|#[ \t]*\w+", " ", rest, flags=re.I)
    for key in ("city", "state", "zip", "unit"):
        if found.get(key):
            rest = re.sub(r"\b" + re.escape(str(found[key])) + r"\b", " ", rest, flags=re.I)
    rest = re.sub(r"[,.;:|\-]", " ", rest).strip()
    return not rest or _is_fact_line(rest)


_DANGLING_END = re.compile(r"(?:[\s,;:|/\u2013\u2014-]+|\b(?:only|in|near|and|with|for|a|an|the|of|at|to|by|or|on)\b[\s.]*)+$", re.I)


def _finish_title(title: str, text: str) -> str:
    """A title never ends in the middle of a word or on a dangling word ("near", "only", "-")."""
    title = title.strip()
    at = text.find(title) if title else -1
    if at >= 0 and at + len(title) < len(text) and text[at + len(title)].isalnum() and title[-1].isalnum() and " " in title:
        title = title[:title.rfind(" ")]  # the pasted line goes on past the last letters, so they are half a word
    for _ in range(4):
        cut = _DANGLING_END.sub("", title).strip()
        if cut == title or len(cut) < 3:
            break
        title = cut
    return title


def _title_raw(text: str, found: dict[str, Any]) -> str:
    """A short title: the building name, else the first line of the paste that reads like a name or heading, else the street
    address. A site name (Zillow, Realtor.com) is never the title."""
    named = re.search(r"^[ \t*#|]*(?:property|community|building|listing|apartment)(?: name)?[ \t]*[:\-][ \t]*([A-Z][^\n]{2,60})$", text, re.M | re.I)
    if named and not re.search(r"\d", named.group(1)[:3]):
        return named.group(1).strip()
    headline, _city = _craigslist_headline(text)
    if headline:
        return headline
    building = _building_name(text)
    if building:
        return building
    lines = [" ".join(x.strip(" \t|\u2022\u00b7*#").split()) for x in text.splitlines()[:25]]
    lines = [x for x in lines if x]
    if len(lines) >= 2 and re.fullmatch(r"[A-Z][A-Za-z'&-]{3,25}", lines[0]) and lines[0].lower() not in _UI_WORDS and not _SITE_LINE.match(lines[0]) \
            and _ADDRESS.match(lines[1]):
        return lines[0]  # a one-word name on its own line above the address
    for raw_line in text.splitlines()[:25]:
        line = " ".join(_PROMO_BANNER.sub(" ", raw_line).strip(" \t|\u2022\u00b7*#").split())
        if _ai_aimed(raw_line) or _ai_aimed(line):
            continue
        if " | " in line:  # "LAKESHORE VILLAS | Sunny 3BR/2BA house, fenced yard": the first part that is not a fact is the name
            parts = [x.strip() for x in line.split(" | ")]
            line = next((x for x in parts if len(x) >= 3 and not _not_a_name(x) and not _is_fact_line(x)), "")
        for _ in range(2):  # "FB Marketplace - 2 bedroom ...", "Rental: 3 Bedroom Home in Belmont": the label is not the title
            line = _LABEL_PREFIX.sub("", line, count=1)
        line = _name_segment(line)
        if not line or _not_a_name(line) or _money_line_cut(line) or _date_only_line(line):
            continue
        line = _headline_clean(line)
        if not line:
            continue
        low = line.lower().rstrip(":")
        if not 4 <= len(line) <= 90 or low in _UI_WORDS or line.startswith(("http", "$", "www.", "Skip to")) or _SITE_LINE.match(line):
            continue
        am = _ADDRESS.match(line)
        if am and found.get("address"):
            return found["address"]
        head = re.split(r"\s+[-|\u2013\u2014]\s+", line, maxsplit=1)
        if len(head) == 2 and found.get("address") and found["address"] in head[1] and re.fullmatch(r"[A-Za-z][A-Za-z '&.]{1,40}", head[0]):
            return head[0].strip()  # "Name - Unit 4C, 3329 N Broadway": the name is the title, the street is the address
        if found.get("address") and _only_address_left(line, found):
            return found["address"]  # "Unit 3B, 500 Main St, Austin TX 78701": the street is the title, the unit has its own field
        if re.fullmatch(r"[\d\s$,./\-+:()]+", line) or (_is_fact_line(line) and not re.search(r"\b(?:apartment|condo|house|townhome|townhouse|duplex|loft)\b", line, re.I)):
            continue
        if re.search(r"\b(?:call|text|email|contact|apply|posted|updated|listed|published)\b.*(?:\d{3}|ago|on\b)", low):
            continue
        if re.fullmatch(r"[A-Za-z .'-]+,\s*[A-Z]{2}(?:\s+\d{5})?", line):  # just "Champaign, IL"
            continue
        if len(line.split()) >= 6 and line.endswith((".", "?")):
            continue  # a sentence, not a name
        return re.split(r"(?<=[a-z])(?<!\bincl)(?<!\bapt)(?<!\bbldg)[.!]\s", line)[0]
    addr = found.get("address", "")
    return addr.split(",")[0] if addr else ""


# --------------------------------------------------------------------------- the entry point
def _try(fn: Callable[[], Any]) -> Any:
    try:
        return fn()
    except Exception:  # a field it can't read is simply left out
        return None


def parse_listing(text: str = "", url: str = "", current: dict[str, Any] | None = None, buying: bool = False) -> dict[str, Any]:
    """Pull what a pasted listing says. Returns only the fields found. ``current`` (a saved place's fields) is for
    refreshing the reader notes: what is filled there counts as placed, so the notes only hold what is still open.
    ``buying`` is True for a buy search: the listing is then a home for sale, never a rental, and the rent-only readings
    are not used."""
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

    price_read = (_try(lambda: _buy_price(text)) if buying else None) or _try(lambda: _price(text))
    facts: list[str] = []
    price_range = _try(lambda: _rent_range(text, price_read)) if price_read and not buying else None
    if price_range:
        # "Rent from $1,299 - $1,650 / mo": the listing gives a range, so no single rent is saved (unknown beats wrong).
        price_read = None
        facts.append(f"The listing gives a rent range of ${price_range[0]:,.0f} to ${price_range[1]:,.0f} a month, so the rent is left empty. "
                     "Ask which rent applies to the unit you want, then fill it in.")
    if price_read is None and not price_range:
        worded, worded_note = _try(lambda: _worded_price(text)) or (None, "")
        if worded:
            price_read = worded
        elif worded_note:
            facts.append(worded_note)
    if buying and isinstance(price_read, (int, float)) and price_read < 20000:
        # A monthly figure ("monthly cost about $1,988") is not the asking price of a home for sale.
        if not (current or {}).get("price"):  # a price the caller already has needs no "check the asking price" note
            facts.append(
                f'The listing has ${price_read:,.0f} that looks like a monthly amount, not an asking price, so it is not used as the asking price. Check the asking price.')
        price_read = None
    dash_price = _try(lambda: _dash_title_price(text)) if price_read is not None and not buying else None
    if dash_price and dash_price[1] and dash_price[0] == price_read:
        facts.append(f"The listing says \"starting at\" ${price_read:,.0f}, so that is the lowest unit price. Ask what the rent is for the unit you want.")
    put("price", price_read)
    put("beds", _try(lambda: _beds(text)))
    conv = _try(lambda: _beds_converted(text))
    if conv:
        was = "studio" if conv[0] == 0 else f"{conv[0]:g} bedroom"
        now = "studio" if conv[1] == 0 else f"{conv[1]:g} bedroom"
        facts.append(f"The listing says this was a {was} that was converted to a {now}, so it is saved as {now}. Ask how the rooms are laid out.")
    corrected = None if conv else _try(lambda: _beds_corrected(text))
    if corrected:
        was = "studio" if corrected[0] == 0 else f"{corrected[0]:g} bedroom"
        now = "studio" if corrected[1] == 0 else f"{corrected[1]:g} bedroom"
        facts.append("The listing gives two different bedroom counts and corrects itself. The later count is saved, so check the bedroom count.")
    facts += _try(lambda: _price_notes(text, price_read)) or []
    put("baths", _try(lambda: _baths(text)))
    put("sqft", _try(lambda: _sqft(text)))
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
    kind_cost = _try(lambda: _parking_detail(text)) or ("", None, [])
    put("parking", kind_cost[0])
    put("parking_cost", kind_cost[1])
    facts += kind_cost[2]
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
    if "pet_rent" not in out:
        monthly_after_deposit = _try(lambda: _pet_deposit_then_monthly(text))
        if monthly_after_deposit:
            put("pet_rent", monthly_after_deposit)
        elif out.get("pets") != "none" and _try(lambda: _no_pet_rent(text)):
            out["pet_rent"] = 0  # the listing says there is no pet rent: zero, not unknown
    side, dep_text = _try(lambda: _pet_side_deposits(fee_text, out.get("price") if isinstance(out.get("price"), (int, float)) else None)) or ({}, fee_text)
    for key, value in side.items():
        if key not in out and not (key == "pet_fee" and "pet_fee" in out):
            put(key, value)
    if out.get("pet_rent") and re.search(r"\$\s?\d{1,4}(?:\.\d\d)?\s*(?:(?:/\s*mo(?:nth)?|per month|monthly|a month)\s*)?(?:per|each|/)\s*(?:pet|dog|cat|animal)\b", text, re.I):
        facts.append(f"Pet rent is ${out['pet_rent']:,.0f} for each pet, so with more than one pet it adds up.")
    elif out.get("pet_rent") and re.search(r"\$\s?\d{1,4}(?:\.\d\d)?\s*(?:each|apiece)\b", text, re.I) and re.search(r"\bpet\s+rent\b", text, re.I):
        facts.append(f"Pet rent is ${out['pet_rent']:,.0f} for each pet, so with more than one pet it adds up.")
    elif out.get("pet_rent") and re.search(r"\$\s?\d{1,4}(?:\.\d\d)?\s*(?:(?:/\s*mo(?:nth)?|per month|monthly|a month)\s*(?:each|apiece)|(?:each|apiece)\s*(?:/\s*mo(?:nth)?|per month|monthly|a month))\b", text, re.I):
        facts.append(f"Pet rent is ${out['pet_rent']:,.0f} a month for each pet, so with more than one pet it adds up.")
    elif out.get("pet_rent") and re.search(r"\$\s?\d{1,4}(?:\.\d\d)?\s*(?:each|apiece)\b", text, re.I):
        facts.append(f"The listing says ${out['pet_rent']:,.0f} each for pets, saved as monthly pet rent for each pet, so with more than one pet it adds up. "
                     "If it is a one time fee instead, move it to the pet fee.")
    nr = re.search(r"\$\s?(\d{1,4}(?:,\d{3})?)(?:\.\d\d)?[ \t]*(?:non[- ]?refundable[ \t]+)?pet[ \t]+deposit\b[^.\n;]{0,25}?non[- ]?refundable|\bnon[- ]?refundable[ \t]+\$\s?(\d{1,4}(?:,\d{3})?)[ \t]*pet[ \t]+deposit", text, re.I)
    if nr and out.get("pet_fee") and not out.get("pet_deposit"):
        facts.append(f"The ${float((nr.group(1) or nr.group(2)).replace(",", "")):,.0f} pet deposit is non-refundable, so it is counted as a pet fee, not as money you get back.")
    for key, value in (_try(lambda: _pet_limit_fields(text)) or {}).items():
        put(key, value)
    if out.get("pet_weight_limit") is not None and not out.get("pets") and not doubt and _PET_LABEL_NO_OVER.search(text):
        facts.append("The listing sets a pet weight limit but does not say which pets are allowed, so pets is left empty. "
                     f"Ask {_ask_who(text)} whether cats and dogs are both allowed.")
    weight_note = _try(lambda: _pet_weight_unclear(text)) or ""
    if weight_note:
        facts.append(weight_note)
    utext = _util_text(text)
    included = _try(lambda: _utilities(utext)) or ""
    pays = _try(lambda: _tenant_pays(utext)) or ""
    roles = _try(lambda: _utility_roles(utext)) or {"tenant": [], "landlord": [], "billed": [], "amount": None, "per": None}
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
        named = [w for w in roles["landlord"] if w not in gone]
        # when the listing names what is included ("Heat + water + trash included"), only those are included
        included = _ordered_utilities(named if roles["landlord"] else [w for w in _ALL_UTILITIES if w not in gone])
        pays = _ordered_utilities([w.strip() for w in (pays + ", " + kept_out).split(",") if w.strip()])
    included, pays = _try(lambda: _apply_util_sections(utext, included, pays, facts)) or (included, pays)
    through = (_try(lambda: _through_provider(text)) or []) + (_try(lambda: _internet_by_provider(utext)) or [])
    if through:
        # "Electric and gas through PG&E": set up and paid by the renter, and a billed-back or flat-fee line must not erase it.
        pays = _ordered_utilities([w.strip() for w in (pays + ", " + ", ".join(through)).split(",") if w.strip()])
    billed = _try(lambda: _billed_back(utext))
    flat = _try(lambda: _flat_util_fee(utext))

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
        moved = take_out_of_included(billed[0]) if billed[0] else ""
        pays = _ordered_utilities([w.strip() for w in (pays + ", " + billed[0]).split(",") if w.strip()])
        put("utilities_estimate", billed[1])  # their own monthly figure, so it is counted in the cost
        if billed[0] and flat == billed:
            facts.append(f"{billed[0].capitalize()} {_util_verb(billed[0])} covered by a flat fee of ${billed[1]:,.0f}/month from the listing, counted as your utilities estimate. You pay it, so it is not free.")
        elif billed[0]:
            facts.append(f"{billed[0].capitalize()} {_util_verb(billed[0])} billed back at ${billed[1]:,.0f}/month, counted as your utilities estimate.")
        else:
            facts.append(f"The listing gives a billed-back average of ${billed[1]:,.0f} a month but doesn't say which utilities it covers. Ask the landlord.")
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
            if roles.get("per"):
                facts.append(f"{names.capitalize()} {_util_verb(names)} billed back at ${roles['per'][0]:,.0f} per {roles['per'][1]}, which is about ${roles['amount']:,.0f} a month, counted as your utilities estimate.")
            else:
                facts.append(f"{names.capitalize()} {_util_verb(names)} billed back at about ${roles['amount']:,.0f}/month, counted as your utilities estimate.")
        else:
            facts.append(f"{names.capitalize()} {_util_verb(names)} billed back to you, but the listing gives no amount. Add a utilities estimate once you know it.")
    elif _try(lambda: _billed_unknown(utext.lower())):
        if included or re.search(r"\b(?:landlord|owner|management)\s+(?:pays?|covers?)\s+all\b|\ball\s+utilities\s+(?:are\s+)?(?:included|paid|covered)", utext.lower()):
            facts.append("The listing says the landlord pays the utilities, but it also says utilities are billed back to you (RUBS). "
                         "Ask the landlord which utilities you really pay and how much. None are counted as included.")
            included = ""
        else:
            facts.append("The listing says utilities are billed back to you (RUBS), but it gives no amount and doesn't say which utilities. "
                         "Ask the landlord which ones and about how much, then add a utilities estimate.")
    if "utilities_estimate" not in out:
        named = _try(lambda: _named_estimate(utext))
        if named:
            # "water/sewer/trash approximately $60 a month": the renter's own rough bill, not something included
            moved = take_out_of_included(named[0])
            pays = _ordered_utilities([w.strip() for w in (pays + ", " + named[0]).split(",") if w.strip()])
            put("utilities_estimate", named[1])
            facts.append(f"{named[0].capitalize()} {_util_verb(named[0])} about ${named[1]:,.0f} a month from the listing, counted as your utilities estimate.")
            if moved:
                facts.append(f"The listing also says {moved} is included, but it gives you a monthly amount for it, so it is not counted as included.")
    n_facts = len(facts)
    pays_before = pays
    included, pays = _reconcile_utilities(included, pays, facts)
    every = _try(lambda: _everything_except(utext))
    if every is not None:
        # "Everything included except cable": the listing says everything, so "all" is right; what it leaves out the renter pays.
        del facts[n_facts:]
        raw_every = _try(lambda: _everything_except(text)) or every
        gone = ["internet" if w in ("wifi", "wi-fi") else w for w in raw_every if w != "cable"]
        if "cable" in raw_every:
            facts.append("Cable is not included. Cable is TV, not internet, so internet is left blank. Ask whether internet is included.")
        extra = [w for w in gone if w != "internet"]
        clash = [w for w in (pays_before.split(", ") if pays_before else []) if w not in gone]
        if extra:
            included = _ordered_utilities([w for w in _ALL_UTILITIES if w not in extra])
        elif clash:
            # "Everything included except cable ... Electric is separate": the two lines disagree about electric, so it is
            # not called included; the renter pays it and the amount is unknown.
            included = _ordered_utilities([w for w in _ALL_UTILITIES if w not in clash and w not in gone])
            facts.append(f"The listing says everything is included except cable, but it also says {_join_names(clash)} {'is' if len(clash) == 1 else 'are'} extra. "
                         f"{_join_names(clash).capitalize()} {'is' if len(clash) == 1 else 'are'} left as something you pay, with no amount. Ask the landlord what the rent really covers.")
        else:
            included = "all"
        pays = _ordered_utilities([w.strip() for w in (pays + ", " + ", ".join(gone)).split(",") if w.strip()])
    elif included != "all" and "utilities_estimate" not in out and _try(lambda: _periodic_utility_amount(utext)):
        monthly, raw, unit = _try(lambda: _periodic_utility_amount(utext))
        put("utilities_estimate", monthly)
        facts.append(f"The listing gives a utilities bill of about ${raw:,.0f} per {unit}, which is about ${monthly:,.0f} a month, counted as your utilities estimate. "
                     "It does not say which utilities it covers, so ask.")
    elif not included and not pays and (_try(lambda: _utilities_extra_amount(text)) or None):
        approx = _try(lambda: _utilities_extra_amount(text))
        put("utilities_estimate", approx)  # the listing's own monthly figure, so it is counted and shown as from the listing
        facts.append(f"The listing says utilities are extra, about ${approx:,.0f}/month, counted as your utilities estimate. It does not say which utilities you pay, so ask.")
    elif pays and included != "all" and "utilities_estimate" not in out and (_try(lambda: _utilities_extra_amount(text)) or None):
        approx = _try(lambda: _utilities_extra_amount(text))
        put("utilities_estimate", approx)  # "Tenant pays all utilities. Approx $180/month": the listing's own figure
        facts.append(f"The listing gives about ${approx:,.0f}/month for utilities, counted as your utilities estimate.")
    elif not included and not pays and _try(lambda: _plus_utilities_unknown(text)):
        facts.append("The listing says utilities are extra (rent plus utilities) but doesn't say which ones. Ask the landlord which utilities you pay.")
    if every is None and re.search(r"\bcable\b", utext, re.I) and not any("Cable is" in f for f in facts):
        if re.search(r"\bcable\b[^.\n;]{0,25}\b(?:extra|separate|not included|tenant|resident|you|paid|additional)\b|\b(?:extra|separate|not included|tenant|resident|you pay|excluding|except|plus)\b[^.\n;]{0,25}\bcable\b", utext, re.I):
            facts.append("Cable is not included. Cable is TV, not internet, so internet is left blank. Ask whether internet is included.")
    put("utilities_included", included)
    if pays:
        # Nothing is included for these, so the monthly cost keeps its own estimate line (a guess), and the listing's words are kept.
        facts.append(f"Tenant pays {pays}.")
        mapped = _tenant_pays_choices(pays)
        if mapped:
            put("tenant_pays", mapped)
    avail_read = _try(lambda: _available(text))
    lease_read = _try(lambda: _lease_months(text))
    range_start, range_months, range_note = _try(lambda: _lease_dates(text)) or (None, None, "")
    if avail_read is None and range_start:
        avail_read = range_start  # "Lease: Aug 1 2027 to Jul 31 2028" starts on the first date
    if lease_read is None and range_months:
        lease_read = range_months
    if range_note:
        facts.append(range_note)
    if avail_read is None:
        month_only = _try(lambda: _available_month_only(text))
        if month_only:  # "Move in Aug 2027": no day is given, so none is made up
            facts.append(f"The listing says move in {month_only} but gives no day, so the available date is left empty. Ask which day the place is ready.")
    put("available_from", avail_read)
    put("lease_months", lease_read)
    if lease_read is None:
        choices = _try(lambda: _lease_choices(text))
        if choices:
            facts.append(f"The listing gives more than one lease length ({choices}), so the lease length is left empty. Ask which one you would get.")
    facts.extend(_try(lambda: _lease_offer_note(text, lease_read)) or [])
    put("year_built", _try(lambda: _year_built(text)))
    facts += [f"{line.rstrip('.')}." for line in (_try(lambda: _pet_limits(text)) or [])
              if not _pet_limit_is_in_fields(line, out)]

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
        mi_text = text
        per_applicant = _try(lambda: _admin_fee_per_applicant(text))
        if per_applicant:
            # "$55 admin fee per applicant" is charged to each adult who applies: an application fee, not a move-in fee.
            mi_text = per_applicant[1]
            if not out.get("application_fee"):
                put("application_fee", per_applicant[0])
                out["application_fee_per_adult"] = 1
                if not _try(lambda: _app_fee_per_person(text)):
                    facts.append(f"The ${per_applicant[0]:,.0f} admin fee is charged per applicant, so it is counted as the application fee for each adult who applies.")
            elif float(out["application_fee"]) != per_applicant[0]:
                facts.append(f"The listing also has a ${per_applicant[0]:,.0f} admin fee per applicant. It is not counted, because an application fee is already filled in. Ask whether they are two fees.")
        mi = _money_after(_without_pet_one_time(mi_text), r"(?:admin(?:istrative|istration)?|move[- ]in|lease[- ](?:signing|initiation|admin)|processing|community|one[- ]time) fees?", hi=5000)
        clean_in, clean_notes = _try(lambda: _cleaning_fee(text)) or (None, [])
        facts.extend(clean_notes)
        if mi or clean_in:
            base = (sum(dict.fromkeys(mi).keys()) if len(mi) > 1 else mi[0]) if mi else 0.0
            put("move_in_fees", base + (clean_in or 0.0))
        br = _money_after(text, r"broker(?:'?s)? fee|agent(?:'?s)? fee|finder'?s fee", hi=20000)
        if br:
            put("broker_fee", br[0])
        else:
            broker_months = _try(lambda: _broker_fee_months(text))
            if broker_months:
                rent_b = out.get("price")
                if isinstance(rent_b, (int, float)) and 200 <= rent_b <= 30000 and not _SALE_WORDS.search(text):
                    put("broker_fee", broker_months * float(rent_b))
                    facts.append(f"The broker fee is {broker_months:g} month{'s' if broker_months != 1 else ''} of rent (${broker_months * float(rent_b):,.0f}), worked out from the rent.")
                else:
                    facts.append(f"The listing says the broker fee is {broker_months:g} month{'s' if broker_months != 1 else ''} of rent, but the rent was not read, so the broker fee is left empty. Fill it in once you know the rent.")
        monthly = 0.0
        for v in dict.fromkeys(_money_monthly_fees(text)):
            monthly += v
        counted, listed = _try(lambda: _extra_monthly(text)) or ([], [])
        for label, v in counted:
            monthly += v
            facts.append(f"${v:,.0f}/month extra for {label} is counted in other monthly fees. If it is optional, take it out.")
        for label, v in _try(lambda: _mandatory_monthly_fees(text)) or []:
            monthly += v
            facts.append(f"The {label} is ${v:,.0f}/month and the listing says it is required, so it is counted in other monthly fees.")
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
        facts.extend(_try(lambda: _move_in_total_notes(text)) or [])
        facts.extend(_try(lambda: _holding_fee_notes(text)) or [])
        if not buying:
            facts.extend(_try(lambda: _holding_fee_amount_notes(text)) or [])
            facts.extend(_try(lambda: _periodic_fee_notes(text)) or [])
            facts.extend(_try(lambda: _renters_insurance_note(text)) or [])
            credit_fee = _try(lambda: _credit_check_fee(text))
            if credit_fee:
                cf, who = credit_fee
                if not out.get("application_fee"):
                    put("application_fee", cf)
                    out["application_fee_per_adult"] = 1
                    facts.append(f"The ${cf:,.0f} credit check fee is charged per {who}, so it is counted as the application fee for each adult who applies.")
                elif float(out["application_fee"]) != cf:
                    facts.append(f"The listing also has a ${cf:,.0f} credit check fee per {who}. It is not counted, because an application fee is already filled in. Ask whether they are two fees.")
            plain_credit = _try(lambda: _credit_check_plain(text))
            if plain_credit:
                if not out.get("application_fee"):
                    put("application_fee", plain_credit)
                    facts.append(f"The ${plain_credit:,.0f} credit check fee is saved as the application fee. Ask if each adult who applies pays it.")
                elif float(out["application_fee"]) != plain_credit:
                    facts.append(f"The listing also has a ${plain_credit:,.0f} credit check fee. It is not counted, because an application fee is already filled in. Ask whether they are two fees.")
        per_person = _try(lambda: _app_fee_per_person(text))
        if per_person:
            facts.append(per_person)
            if out.get("application_fee"):
                out["application_fee_per_adult"] = 1  # the cost multiplies the fee by the adults who apply
        credit, credit_notes = _try(lambda: _seller_credit_detail(text, out.get("price") if isinstance(out.get("price"), (int, float)) else None)) or (None, [])
        if credit:
            put("seller_credit", credit)
        facts.extend(credit_notes)
        insurance = _try(lambda: _insurance(text))
        if insurance is not None:
            put("insurance", insurance)
        assessment = _try(lambda: _special_assessment(text))
        if assessment:
            facts.append(assessment)
        monthly_assessment = _try(lambda: _assessment_monthly_note(text))
        if monthly_assessment:
            facts.append(monthly_assessment)
        yearly_assessment = _try(lambda: _assessment_yearly_note(text))
        if yearly_assessment:
            facts.append(yearly_assessment)
        amount, payer, _sentence = _try(lambda: _special_assessment_facts(text)) or (None, "", "")
        if amount:
            put("special_assessment", amount)
            if payer:
                put("special_assessment_payer", payer)
        elif buying and _try(lambda: _assessment_none(text)):
            put("special_assessment", 0)
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
        if not buying and _try(lambda: listing_hoa_in_rent(text)):
            # HOA dues that are part of the rent are already in the rent: nothing is saved or added on top
            hoa = None
            hm = re.search(r"[^.\n;]*\b(?:hoa|association)\b[^.\n;]*\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?[^.\n;]*|[^.\n;]*\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?[^.\n;]*\b(?:hoa|association)\b[^.\n;]*", text, re.I)
            amt = (hm.group(1) or hm.group(2)) if hm else ""
            facts.append(f"The listing says the HOA dues{f' (${amt})' if amt else ''} are included in the rent, so nothing is added for them.")
        if hoa is not None:
            put("hoa", hoa)
        tax = _try(lambda: _tax(text))
        if tax is not None:
            rent_price = out.get("price")
            rental = (not buying and isinstance(rent_price, (int, float)) and rent_price < 20000 and not _SALE_WORDS.search(text)) \
                or bool(re.search(r"\b(?:taxes?|tax)\b[^.\n;]{0,60}\b(?:included in|part of|covered by|paid (?:by|in))\s+(?:the\s+)?(?:rent|lease)\b|\brent includes?\b[^.\n;]{0,40}\btax", text, re.I))
            if rental:
                facts.append(f"The listing mentions property taxes of ${tax:,.0f} a year, but this looks like a rental, so property tax is not filled in.")
            else:
                put("property_tax", tax)
        if buying:
            facts.extend(_try(lambda: _buyer_only_fees(text, out)) or [])

    _try(fees)
    for key, value in (_try(lambda: _address(text)) or {}).items():
        put(key, value)
    if "city" not in out:
        hint = _try(lambda: _craigslist_headline(text)) or ("", "")
        if hint[1]:
            put("city", hint[1])
    title = _try(lambda: _title(text, out))
    if title:
        out["title"] = title
    if current:
        _apply_current(out, current)
    facts = _drop_placed_facts(facts, out, follow=bool(current))
    facts += _try(lambda: _safety_net(text, out, facts)) or []
    facts = _drop_placed_facts(facts, out, follow=bool(current))  # the safety net's lines follow the fields too
    facts = _try(lambda: _fix_quotes(facts, text, out)) or facts
    if facts:
        out["found_in_listing"] = " ".join(facts)
    return out


def reader_notes_for(place: dict[str, Any], buying: bool = False) -> str:
    """The "Also in the listing" notes for a saved place: its listing text read again, with what is filled on the place
    counted as placed. One rule for add, edit and update: a note about something that is filled in now is not kept."""
    found = parse_listing(str(place.get("listing_text") or ""), str(place.get("url") or ""), current=place, buying=buying)
    return str(found.get("found_in_listing") or "")


# --------------------------------------------------------------------------- notes that agree with the fields (cycle 11)
_CURRENT_EXTRA = ("parking", "laundry", "pets", "utilities_included", "tenant_pays", "pet_count_limit", "pet_breed_note", "special_assessment_payer")


def _apply_current(out: dict[str, Any], current: dict[str, Any]) -> None:
    """What is filled on the saved place counts as placed (only for the notes pass; ``out`` is not returned as fields to save)."""
    for key in _NET_REAL_FIELDS + _CURRENT_EXTRA:
        v = current.get(key)
        if v is not None and v != "" and not isinstance(v, bool):
            out[key] = v


def _drop_placed_facts(facts: list[str], out: dict[str, Any], follow: bool = False) -> list[str]:
    """Notes only hold what was not placed: a line that repeats what a field now says is dropped, and a line that says a
    field is left blank is fixed when that field is filled."""
    kept: list[str] = []
    deposit = out.get("deposit") is not None
    broker = out.get("broker_fee") is not None
    for f in facts:
        if _restates_field(f, out):
            continue  # a note that only says again what a filled field holds
        if re.fullmatch(r"Tenant pays [a-z, ]+\.", f) and out.get("tenant_pays"):
            continue  # the "Utilities you pay" field holds exactly this
        if re.search(r"parking", f) and re.search(r"gives no price\. It looks optional", f) and out.get("parking_cost") is not None:
            continue  # the amount was read as the parking cost
        if re.search(r"deposit|broker fee", f):
            if deposit:
                f = f.replace(", so the deposit is left blank.", ".").replace(" The deposit is not saved, because it may be more for you, so ask what the deposit will be.", " Ask what your deposit will be.")
                if re.search(r"deposit is left empty|Fill it in once you know the rent", f) and "security deposit" in f:
                    continue
            if broker and re.search(r"broker fee is left empty", f):
                continue
        if re.match(r"(?=[A-Z])[^.]*?\b(?:cats?|dogs?|pets?|animals?)", f, re.I) and _pet_line_placed(f, out):
            continue
        if follow:  # a saved place: every note follows what is filled on it now
            f = _follow_fields(f, out)
            if not f:
                continue
        kept.append(_one_time_wording(f))
    return kept


def _restates_field(note: str, out: dict[str, Any]) -> bool:
    """True when the note only repeats what a filled field holds: the assessment amount and payer, the renter's insurance
    that the insurance or other monthly fees field now counts, or a quoted amount that a money field now carries."""
    if re.fullmatch(r"Special assessment \$[\d,]+: the (?:buyer|seller) pays it\.", note):
        return _filled(out, "special_assessment") and _filled(out, "special_assessment_payer")
    if re.match(r"The listing says renter's insurance is required", note):
        return _filled(out, "insurance") or _filled(out, "other_monthly_fees")
    m = re.fullmatch(r'The listing also says "([^"]*)"\. (?:It is not counted anywhere\. Check what it is for\.|It is a one-time cost, so it is not in the monthly cost\. Check what it is for\.|It is a monthly fee and it is not counted anywhere\. Check what it is for\.)', note)
    if m:
        amounts = _dollar_values(m.group(1))
        return bool(amounts) and amounts <= _net_used_numbers(out, [])
    return False


def _filled(out: dict[str, Any], key: str) -> bool:
    v = out.get(key)
    return v is not None and v != "" and not isinstance(v, bool)


# A note that is about one field goes away (or is rewritten) once that field is filled. (pattern, field or fields that settle it)
_FIELD_NOTES: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = tuple((re.compile(pat, re.I), keys) for pat, keys in (
    (r"so the rent is left empty|rent range of \$|that looks like a monthly amount, not an asking price|Check the asking price", ("price",)),
    (r"billed-back average of \$|billed back to you, but the listing gives no amount|Add a utilities estimate once you know", ("utilities_estimate",)),
    (r"seller credit is blank", ("seller_credit",)),
    (r"broker fee is left empty|so no amount is saved\. Ask what it comes to", ("broker_fee",)),
    (r"\bPets is left empty", ("pets",)),
    (r"Washer and dryer hookups only", ("laundry",)),
    (r"property tax is not filled in", ("property_tax",)),
    (r"(?:parking|garage|carport)[^.]*\b(?:gives no price|no price)\b", ("parking_cost",)),
    (r"\binternet is left blank", ("utilities_included",)),
))


def _follow_fields(note: str, out: dict[str, Any]) -> str:
    """The note made again so it agrees with the fields: "" when everything it is about is filled, else the note (reworded when
    only part of it is settled). Special assessment notes depend on both the amount and who pays."""
    if _restates_field(note, out):
        return ""
    for pat, keys in _FIELD_NOTES:
        if pat.search(note) and all(_filled(out, k) for k in keys):
            if keys == ("utilities_estimate",) and "internet" in note.lower():
                continue
            return ""
    if re.search(r"special assessment", note, re.I) and not re.search(r"paid by the seller|monthly", note, re.I):
        amount = out.get("special_assessment")
        has_amount = isinstance(amount, (int, float)) and not isinstance(amount, bool) and amount > 0
        has_payer = _filled(out, "special_assessment_payer")
        if re.match(r"A special assessment is mentioned but no amount is given", note):
            if has_amount and has_payer:
                return ""
            if has_amount:
                return f"Special assessment ${float(amount):,.0f}: the listing doesn't say who pays it, so ask."
            if has_payer:
                return "A special assessment is mentioned but no amount is given. Ask what it is for and how much it is."
        elif re.match(r"Special assessment \$[\d,]+: the listing doesn't say who pays", note) and has_payer:
            return ""
    return note


_ONE_TIME_ITEM = re.compile(r"in total to move in|holding fee|reservation (?:fee|deposit)", re.I)


def _one_time_wording(note: str) -> str:
    """A one-time amount (a move-in total, a holding fee) is not in the monthly cost, and it says so in those words."""
    if re.search(r"in total to move in", note):
        return note.replace("so it is not counted. Ask what it includes.",
                            "so it is not in the monthly cost, and the cash due at move-in may be more than shown. Ask what it includes.")
    if re.search(r"holding fee equal to", note):
        return note.replace("It is not counted in the cost, because", "It is not in the monthly cost, because")
    return note


def _fix_quotes(facts: list[str], text: str, out: dict[str, Any]) -> list[str]:
    """Quotes in a note end on a whole word: a quote the reader cut in the middle of a word loses that piece and ends with "..."."""
    flat = " ".join(text.split())
    fixed: list[str] = []
    for f in facts:
        def cut(m: re.Match[str]) -> str:
            q = m.group(2)
            if q.endswith("..."):
                return m.group(0)
            at = flat.find(q)
            if at < 0:
                return m.group(0)
            nxt = flat[at + len(q):at + len(q) + 1]
            if nxt.isalnum() and q[-1:].isalnum():
                head = q.rsplit(" ", 1)[0] if " " in q else ""
                if head:
                    return f"{m.group(1)}{head.rstrip(' ,;:-')}...{m.group(3)}"
            return m.group(0)
        f = re.sub(r'(\(?")([^"]{3,240})("\)?)', cut, f)
        fixed.append(f)
    return fixed


def drop_filled_notes(notes: str, place: dict[str, Any]) -> str:
    """Saved "Also in the listing" notes with every note dropped (or reworded) that is about a field the place has filled in now.
    For a place that has notes but no listing text to read again."""
    from .money import note_units
    out = {k: v for k, v in place.items() if k in _NET_REAL_FIELDS + _CURRENT_EXTRA}
    kept = []
    for unit in note_units(notes):
        unit = _follow_fields(unit, out)
        if unit:
            kept.append(unit)
    return " ".join(kept)


_PET_LINE_WORDS = frozenset("""pets pet cats cat dogs dog allowed allow ok okay welcome accepted max maximum limit limits lbs lb pound pounds per mo month
monthly non refundable nonrefundable fee rent deposit only and no weight a the one two three each up to under""".split())


def _pet_line_placed(line: str, out: dict[str, Any]) -> bool:
    """True for a pet-rule line such as "Pets: cats and dogs allowed, max 2 pets, 50 lb limit." or "Pets allowed, 2 pet max, $350
    non-refundable pet fee, $30/mo pet rent." when the fields hold everything it says: every word is a plain pet word (no breed,
    size or approval rule), every number is the count, weight, fee, rent or deposit field it sits beside, and the pets field
    agrees with the kinds of pet it names. "no weight limit" is only dropped when no weight limit is filled."""
    if not out.get("pets"):
        return False
    body = re.sub(r"^\s*pets?\s*:\s*", "", line.strip()).rstrip(". ")
    if not body or re.search(r"\b(?:breed|restrict|size|approv|case|negotiab|except|service|emotional|depend|unless|if)", body, re.I):
        return False
    if re.search(r"\bno\b|\bnot\b", body, re.I) and not re.search(r"\bno\s+(?:weight\s+)?limit\b", body, re.I):
        return False
    if re.search(r"\bno\s+(?:weight\s+)?limit\b", body, re.I) and (_filled(out, "pet_weight_limit")):
        return False
    pets = str(out.get("pets"))
    kinds = set(re.findall(r"\b(cats?|dogs?)\b", body, re.I))
    kinds = {k.lower().rstrip("s") for k in kinds}
    if kinds == {"cat"} and pets != "cats" or kinds == {"dog"} and pets != "dogs" or kinds == {"cat", "dog"} and pets != "both":
        return False
    if not kinds and not re.search(r"\bpets?\b", body, re.I):
        return False
    pieces = [x for x in re.split(r"[,;]", body) if x.strip()]
    seen_number = False
    for piece in pieces:
        words = re.findall(r"[A-Za-z]+", piece)
        if any(w.lower() not in _PET_LINE_WORDS for w in words):
            return False
        for m in re.finditer(r"(\$)?\s?(\d+(?:,\d{3})*(?:\.\d+)?)", piece):
            seen_number = True
            n = float(m.group(2).replace(",", ""))
            if m.group(1):
                key = "pet_rent" if re.search(r"rent|/\s*mo|per month|monthly", piece, re.I) else "pet_deposit" if re.search(r"deposit", piece, re.I) else "pet_fee"
            elif re.search(r"\blbs?\b|pounds?", piece[m.end():m.end() + 8], re.I):
                key = "pet_weight_limit"
            else:
                key = "pet_count_limit"
            held = out.get(key)
            if not isinstance(held, (int, float)) or isinstance(held, bool) or float(held) != n:
                return False
    return (seen_number or bool(re.search(r"\bno\s+(?:weight\s+)?limit\b|\ballowed\b|\bok(?:ay)?\b|\bonly\b", body, re.I))) and len(line) <= 160


# --------------------------------------------------------------------------- safety net (cycle 10)
# A last pass over the pasted text. Whatever money amount, weight limit, free-rent offer, laundry, parking or utility
# wording no reader placed in a field or a note gets one short plain line, so nothing is silently dropped.
_NET_DOLLARS = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(\.\d{1,2})?(\s?[kK]\b)?|\b(\d{1,3}(?:,\d{3})+|\d+)\s*(?:dollars?|bucks)\b", re.I)
_NET_WEIGHT = re.compile(r"\b(\d{1,3})\s*[- ]?(?:lbs?\b\.?|pounds?\b)", re.I)
_NET_SKIP_NEAR = re.compile(
    r"assessed (?:value|at)|assessment value|zestimate|apprais|estimated value|home value|sold for|last sold|price history|"
    r"original price|list(?:ing|ed)? price|asking|reduced from|income|earn|salary|\b\d(?:\.\d)?\s*x\b|times (?:the )?(?:monthly )?rent|"
    r"per sq|/\s*sq|psf|price per|mortgage|(?:monthly|est\.?|estimated) payment|/\s*bed\b|per bed\b", re.I)
_NET_UNIT_BEFORE = re.compile(r"(?:studio|\b\d\s*(?:br|bd|bed(?:room)?s?)\b|\b(?:one|two|three)[- ]bed(?:room)?s?)[^.\n;$]{0,12}$", re.I)
_NET_FREE_RENT = re.compile(r"\b(?:(?:\d+|one|two|three|a|1\.5)\s+(?:months?|weeks?)(?:'s)?(?:\s+of\s+rent)?\s+free|free\s+rent|(?:months?|weeks?)\s+free|rent[- ]free\s+(?:month|period)|concessions?)\b", re.I)
_NET_BROKER_MONTH = re.compile(r"\b(?:broker|agent|finder|realtor|leasing)(?:'s|s')?\s+fee\b[^.\n;$]{0,30}?\b(?:(?:one|two|a|\d+(?:\.\d+)?)\s*(?:months?|mo)\b|\d+\s*%)|\b(?:one|two|\d+)\s+months?\s+(?:broker|agent|finder)(?:'s)?\s+fee", re.I)
_NET_UTIL_WORD = re.compile(r"\b(?:water|sewer|trash|garbage|electric(?:ity)?|gas|heat(?:ing)?|internet|wifi|cable|utilit(?:y|ies))\b", re.I)
_NET_UTIL_CUE = re.compile(r"\b(?:utilit(?:y|ies)|included|tenant|resident|renter|you pay|pay for|paid by|owner pays|landlord|extra|separate|billed|flat|metered|submeter|responsible|set up)\b", re.I)
_NET_UTIL_NOT = re.compile(r"\b(?:gas|electric)\s+(?:stove|range|oven|fireplace|grill|cooktop|appliances?|logs?)\b|\bheat\s*pump\b|\bgas station\b", re.I)
_NET_REAL_FIELDS = ("price", "parking_cost", "pet_rent", "pet_fee", "utilities_estimate", "pet_weight_limit", "pet_deposit", "deposit",
                    "application_fee", "other_monthly_fees", "move_in_fees", "broker_fee", "hoa", "property_tax", "insurance",
                    "special_assessment", "closing_costs", "seller_credit")
_NET_ENDS = ".;!?\n|•"


_ONE_TIME_WORDS = re.compile(r"move[- ]out|one[- ]time|non[- ]?refundable", re.I)
_MONTHLY_WORDS = re.compile(r"/\s*(?:mo|month)\b|\bper month\b|\ba month\b|\bmonthly\b|\bmo\.", re.I)


def _uncounted_kind_sentence(phrase: str) -> str:
    """What the safety-net note says about a quoted amount that no field holds: a one-time cost is not in the monthly cost, a
    monthly fee is not counted, and when the line does not say, the generic sentence."""
    one, monthly = bool(_ONE_TIME_WORDS.search(phrase)), bool(_MONTHLY_WORDS.search(phrase))
    if one and not monthly:
        return "It is a one-time cost, so it is not in the monthly cost."
    if monthly and not one:
        return "It is a monthly fee and it is not counted anywhere."
    return "It is not counted anywhere."


def _net_clause(text: str, start: int, end: int, limit: int = 160) -> str:
    """The short phrase around text[start:end]: the clause it sits in. A clause that fits ``limit`` is quoted whole, never
    cut in the middle; a longer one is narrowed to the comma-separated piece that holds the match, and only a piece that is
    still too long is cut at a word edge."""
    left = max(text.rfind(c, 0, start) for c in _NET_ENDS) + 1
    rights = [i for i in (text.find(c, end) for c in _NET_ENDS) if i >= 0]
    right = min(rights) if rights else len(text)
    lo, hi = left, right
    if hi - lo > limit:
        lo = max(lo, text.rfind(",", lo, start) + 1)
        comma = text.find(",", end, hi)
        if comma >= 0:
            hi = comma
    if hi - lo > limit:
        lo = max(lo, start - 28)
        hi = min(hi, max(end + 45, lo + limit))
        if lo > left:
            nxt = text.find(" ", lo, start)
            lo = nxt + 1 if nxt >= 0 else lo
        if hi < right:
            prev = text.rfind(" ", end, hi)
            hi = prev if prev > end else hi
    phrase = " ".join(text[lo:hi].split()).strip(" ,:-–—")
    return phrase.replace('"', "'")


def _quotes_title(phrase: str, title: Any) -> bool:
    """True when a quoted phrase is just the listing's title (or a piece of it)."""
    if not title or not isinstance(title, str):
        return False
    a = " ".join(phrase.replace("...", " ").split()).lower().strip(" ()")
    b = " ".join(title.replace("...", " ").split()).lower().strip(" ()")
    if len(a) >= 8 and len(b) >= 8 and (a.startswith(b) or b.startswith(a) or a in b):
        return True
    a0 = a.split("$")[0].strip(" (-:")
    return len(a0) >= 6 and len(b) >= 8 and a0 in b  # the words in front of the amount are the title's own words


def _dollar_values(text: str) -> set[float]:
    """Every dollar amount written in ``text``."""
    vals: set[float] = set()
    for m in _NET_DOLLARS.finditer(text):
        raw = m.group(1) if m.group(1) is not None else m.group(4)
        try:
            vals.add(float(raw.replace(",", "") + (m.group(2) or "" if m.group(1) is not None else "")))
        except ValueError:
            pass
    return vals


def _net_component_numbers(text: str) -> set[float]:
    """The single amounts the readers added up or converted into fields (each monthly fee inside other monthly fees, a
    required storage fee, a per-applicant fee, a cleaning fee), so a sum in a field never leaves its parts "not counted"."""
    nums: set[float] = set()
    for v in _try(lambda: _money_monthly_fees(text)) or []:
        nums.add(float(v))
    counted, _listed = _try(lambda: _extra_monthly(text)) or ([], [])
    nums.update(float(v) for _l, v in counted)
    for _l, v, required in _try(lambda: _storage_fees(text)) or []:
        if required:
            nums.add(float(v))
    pa = _try(lambda: _admin_fee_per_applicant(text))
    if pa:
        nums.add(float(pa[0]))
    fee = _try(lambda: app_fee_per_adult(text))
    if fee:
        nums.add(float(fee))
    clean, _n = _try(lambda: _cleaning_fee(text)) or (None, [])
    if clean:
        nums.add(float(clean))
    for _l, v in _try(lambda: _mandatory_monthly_fees(text)) or []:
        nums.add(float(v))
    for v in _try(lambda: _money_after(text, r"(?:admin(?:istrative|istration)?|move[- ]in|lease[- ](?:signing|initiation|admin)|processing|community|one[- ]time) fees?", hi=5000)) or []:
        nums.add(float(v))  # "Move-in fee $400 | Admin fee $200" are added into move-in fees
    return nums


def _net_used_numbers(out: dict[str, Any], facts: list[str], text: str = "") -> set[float]:
    """Every number a field or a note already carries, and the parts and conversions behind a field."""
    used: set[float] = _net_component_numbers(text) if text else set()
    for key in _NET_REAL_FIELDS:
        v = out.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v:
            used.add(float(v))
            if key in ("hoa", "property_tax", "insurance", "other_monthly_fees", "parking_cost", "utilities_estimate", "pet_rent"):
                used.update({round(float(v) * 12, 2), round(float(v) / 12, 2), round(float(v) * 3, 2), round(float(v) * 6, 2)})  # a yearly, quarterly or half-year figure written beside the monthly one
                used.update({float(round(float(v) / 12)), float(int(float(v) / 12)), float(round(float(v) / 4)), float(round(float(v) / 2))})  # "$3,100 a year ($258/mo)": the rounded share is the same figure
    price = out.get("price")
    if isinstance(price, (int, float)) and price:
        used.update({float(price) * 2, float(price) * 3})  # first and last month, three months up front
    for line in facts:
        for m in re.finditer(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?", line):
            try:
                used.add(float(m.group(0).replace(",", "")))
            except ValueError:
                pass
    return used


def _safety_net(text: str, out: dict[str, Any], facts: list[str]) -> list[str]:
    """Plain lines for what the reader saw but did not place anywhere. Never changes a field."""
    notes: list[str] = []
    used = _net_used_numbers(out, facts, text)
    done: set[float] = set()
    # two or more "1 bed $1,200" style amounts is a floor plan list: those are rents, not extra costs
    floor_plans = len(re.findall(r"(?:studio|\b\d\s*(?:br|bd|bed(?:room)?s?)\b|\b(?:one|two|three)[- ]bed(?:room)?s?)[^.\n;$]{0,12}\$\s?\d", text, re.I)) >= 2
    for m in _NET_DOLLARS.finditer(text):
        raw, dec, kay = (m.group(1), m.group(2), m.group(3)) if m.group(1) is not None else (m.group(4), None, None)
        try:
            amount = float(raw.replace(",", "") + (dec or "")) * (1000 if kay else 1)
        except ValueError:
            continue
        if amount <= 0 or amount >= 20000 or amount in used or amount in done:
            continue
        before = text[max(0, m.start() - 45):m.start()]
        after = text[m.end():m.end() + 45]
        near = before[-30:] + " " + after[:25]
        rent_read = isinstance(out.get("price"), (int, float))  # with no rent read, a rent-looking amount is still worth a line
        if _NET_SKIP_NEAR.search(near):
            continue
        if rent_read and amount >= 500 and ((floor_plans and _NET_UNIT_BEFORE.search(before)) or re.search(r"\$\s?[\d,]+\s*(?:-|–|to)\s*$", before)
                              or re.match(r"\s*(?:-|–|to)\s*\$\s?\d", after)):
            continue  # a floor plan or a rent range, not an extra cost
        phrase = _net_clause(text, m.start(), m.end())
        if not phrase:
            continue
        if _quotes_title(phrase, out.get("title")):
            continue  # the title line itself is not a note
        n_adults = re.search(r"\bfor\s+(\d|two|three|four)\s+(?:adults?|applicants?|people|persons?)\b[^.]{0,30}\b(?:together|total|combined|in all|altogether)\b", phrase, re.I)
        if n_adults:
            k = {"two": 2, "three": 3, "four": 4}.get(n_adults.group(1).lower()) or int(n_adults.group(1))
            if any(abs(c * k - amount) < 0.01 for c in used if c):
                continue  # "For 2 adults that is $110 together": the sum of a per-adult fee that is already placed
        done.add(amount)
        if any(f'"{phrase}"' in n for n in notes):
            continue  # a second amount in the same quoted line: the line is already there
        if re.search(r"\b(?:per|a|each)\s+load\b|/\s*load\b", near, re.I):
            notes.append(f'The listing says laundry costs "{phrase}". It is not counted anywhere.')
        elif re.search(r"\bincluded\s+in\s+(?:your|the)\s+(?:monthly\s+)?rent\b", phrase, re.I) and not re.search(r"\bnot\s+included\b", phrase, re.I):
            notes.append(f'The listing says "{phrase}". It is included in the rent, so it is not added on top.')
        elif re.search(r"\b(?:holding|reservation|reserve|move[- ]in total|total to move)\b", phrase, re.I):
            notes.append(f'The listing says "{phrase}". It is a one-time amount, so it is not in the monthly cost. Ask if it is taken off what you owe at move-in.')
        else:
            notes.append(f'The listing also says "{phrase}". {_uncounted_kind_sentence(phrase)} Check what it is for.')
    low_facts = " ".join(facts).lower()
    limit = out.get("pet_weight_limit")
    seen_w: set[int] = set()
    for m in _NET_WEIGHT.finditer(text):
        w = int(m.group(1))
        if w in seen_w or (isinstance(limit, (int, float)) and float(limit) == w) or re.search(rf"\b{w}\s*[- ]?(?:lbs?|pounds?)\b", low_facts):
            continue
        seen_w.add(w)
        notes.append(f'The listing says "{_net_clause(text, m.start(), m.end())}". I could not tell what this limit is for, so it is not used anywhere. Check it.')
    m = _free_rent_match(text)
    if m and not re.search(r"free rent|months? free|weeks? free|concession", low_facts):
        notes.append(f'The listing mentions a free-rent offer ("{_net_clause(text, m.start(), m.end())}"). It is not counted anywhere. Check the terms.')
    m = _NET_BROKER_MONTH.search(text)
    if m and not out.get("broker_fee") and not re.search(r"broker|agent fee|finder", low_facts):
        notes.append(f'The listing says "{_net_clause(text, m.start(), m.end())}". The fee is given in months of rent, so no amount is saved. Ask what it comes to.')
    m = re.search(r"\b(?:laundry|washer|dryer|w\s*/\s*d|washing machines?|coin[- ]op)\b", text, re.I)
    if m and not out.get("laundry") and not re.search(r"laundry|washer|dryer|hookup", low_facts) and not any("laundry" in n for n in notes):
        notes.append(f'The listing mentions laundry ("{_net_clause(text, m.start(), m.end())}"), but I could not tell what kind. Ask if it is in the unit, in the building or off site.')
    m = re.search(r"\b(?:parking|garage|carport|driveway|off[- ]street)\b", text, re.I)
    if m and not out.get("parking") and out.get("parking_cost") is None and not re.search(r"parking|garage|carport|driveway", low_facts) \
            and not any(re.search(r"parking|garage", n, re.I) for n in notes):
        notes.append(f'The listing mentions parking ("{_net_clause(text, m.start(), m.end())}"), but I could not tell what it is or what it costs. Ask.')
    counted_here = _net_component_numbers(text) | {float(out[k]) for k in ("utilities_estimate", "other_monthly_fees", "parking_cost") if isinstance(out.get(k), (int, float)) and out[k]}
    if not (out.get("utilities_included") or out.get("tenant_pays") or out.get("utilities_estimate") is not None) and "utilit" not in low_facts:
        for u in _NET_UTIL_WORD.finditer(text):
            clause = _net_clause(text, u.start(), u.end(), 400)
            if _NET_UTIL_NOT.search(clause) or re.search(r"\bnot\s+(?:included|incl)|\bexcluded\b", clause, re.I) or not _NET_UTIL_CUE.search(clause) or u.group(0).lower() in low_facts:
                continue
            if counted_here and any(_dollar_values(clause) & counted_here):
                continue  # "Water & trash $60/mo flat" is already counted in a field
            if any(_net_clause(text, u.start(), u.end()) in n for n in notes):
                break  # an amount line already quotes this very phrase
            notes.append(f'The listing mentions utilities ("{_net_clause(text, u.start(), u.end())}"), but I could not tell who pays. Ask which ones you pay for.')
            break
    if len(notes) > 6:
        notes = notes[:5] + [f"The listing has {len(notes) - 5} more things that are not counted. Read it again for the rest."]
    return notes


_PER_APPLICANT = r"(?:per|each|/)[ \t]*(?:applicant|adult|person|occupant|tenant|resident|roommate)s?\b"


def _admin_fee_per_applicant(text: str) -> tuple[float, str] | None:
    """("$55 admin fee per applicant" -> (55, the text with that phrase taken out)). None when there is no such phrase."""
    pats = (r"\$\s?(\d{1,4})(?:\.\d\d)?[ \t]*(?:admin(?:istrative|istration)?|processing)[ \t]+fees?[ \t]*" + _PER_APPLICANT,
            r"\b(?:admin(?:istrative|istration)?|processing)[ \t]+fees?[ \t:\-]*\$\s?(\d{1,4})(?:\.\d\d)?[ \t]*" + _PER_APPLICANT)
    for pat in pats:
        m = re.search(pat, text, re.I)
        if m:
            return float(m.group(1)), text[:m.start()] + " " + text[m.end():]
    return None


def _cleaning_fee(text: str) -> tuple[float | None, list[str]]:
    """(amount due at move-in or None, notes). "a $200 cleaning fee at move-in" is a move-in fee. A cleaning fee that is not
    said to be due at move-in is not counted, and a note says so."""
    notes: list[str] = []
    for clause in re.split(r"\n|;|\.(?=\s|$)", text):
        m = re.search(r"\$\s?(\d{1,3}(?:,\d{3})+|\d{1,4})(?:\.\d\d)?[ \t]*(?:one[- ]time[ \t]+|move[- ]in[ \t]+)*cleaning[ \t]+fees?\b|\bcleaning[ \t]+fees?[ \t:\-=(]{0,4}\$\s?(\d{1,3}(?:,\d{3})+|\d{1,4})(?:\.\d\d)?", clause, re.I)
        if not m:
            continue
        amount = _num(m.group(1) or m.group(2))
        non_refundable = bool(re.search(r"\bnon[- ]?refundable", clause, re.I))
        if re.search(r"move[- ]?out|moving out|\brefund|\bdeducted|\bfrom the deposit|\bpet\b|\bper[ \t]+(?:month|mo)\b|/\s*mo\b", re.sub(r"\bnon[- ]?refundable", " ", clause, flags=re.I), re.I):
            continue
        if non_refundable or re.search(r"move[- ]?in\b|moving in|\bat signing|\bupon (?:move|signing)|\bdue at (?:lease|signing)", clause, re.I):  # a non-refundable cleaning fee is paid up front
            return amount, notes
        notes.append(f"The listing mentions a ${amount:,.0f} cleaning fee but not when it is due, so it is not counted. Ask if it is due at move-in.")
    return None, notes


def _broker_fee_months(text: str) -> float | None:
    """Months of rent a broker fee is worth: "Broker fee one month", "broker fee: one month's rent", "one month broker fee"."""
    nums = {"one": 1.0, "1": 1.0, "two": 2.0, "2": 2.0, "half": 0.5, "1/2": 0.5}
    m = re.search(r"\b(?:broker|agent|finder)(?:'?s)?[ \t]+fee\b[ \t:\-=(]{0,4}(?:is |of |equal to |equals |=)?[ \t]*(?:(one|two|1|2)|(half)(?: a)?)[ \t-]*month", text, re.I) \
        or re.search(r"\b(?:(one|two|1|2)|(half)(?: a)?)[ \t-]*month(?:'?s)?(?: of rent| rent)?[ \t]+(?:broker|agent|finder)(?:'?s)?[ \t]+fee\b", text, re.I)
    if not m:
        return None
    return nums[(m.group(1) or m.group(2)).lower()]


def _money_monthly_fees(text: str) -> list[float]:
    """Required extras charged every month ("amenity fee $25/mo", "$10/month trash")."""
    found: list[float] = []
    label = r"(?:amenity|trash|valet trash|trash valet|valet waste|pest(?: control)?|package|technology|tech|community|convenience|internet|cable|smart home)(?:\s*(?:fee|fees|charge|package|service))?"
    back = re.compile(r"^[^.\n;$]{0,14}?\b(?:billed|charged|passed)\s*(?:back|through|on)\b", re.I)
    for m in re.finditer(r"\b" + label + r"[ \t:\-=]{0,4}\$\s?(\d{1,4})(?:\.\d\d)?\s*(?:/\s*mo(?:nth)?|per month|monthly|a month)", text, re.I):
        if re.match(r"(?:trash|internet|cable)", m.group(0), re.I) and (back.match(text[m.end():]) or re.match(r"[ \t,]*(?:is[ \t]+)?flat\b", text[m.end():], re.I)):
            continue  # a billed-back or flat-fee utility is the utilities estimate, never another monthly fee
        found.append(float(m.group(1)))
    for m in re.finditer(r"\b(?:valet[ -]trash|trash[ -]valet|valet[ -]waste)(?:\s*(?:fee|service|charge))?[ \t:\-=]{0,4}\$\s?(\d{1,4})(?:\.\d\d)?(?![\d,]|\s*(?:/\s*mo|per month|monthly|a month|one[- ]time|deposit))", text, re.I):
        found.append(float(m.group(1)))  # "Valet trash $30": valet trash is always a monthly service
    for m in re.finditer(r"\$\s?(\d{1,4})(?:\.\d\d)?\s*(?:/\s*mo(?:nth)?|per month|monthly|a month)\s*(?:for\s+)?" + label + r"\b", text, re.I):
        if re.search(r"(?:trash|internet|cable)", m.group(0), re.I) and back.match(text[m.end():]):
            continue
        found.append(float(m.group(1)))
    return found


_MONTHLY_RE = r"(?:/\s*mo(?:nth)?\b|per\s+month|monthly|a\s+month|each\s+month)"


def _mandatory_monthly_fees(text: str) -> list[tuple[str, float]]:
    """A monthly fee the same line calls mandatory or required ("Gym access fee $30/mo mandatory", "Required amenity fee $40/month").
    Fees that have their own reading (pets, parking, storage, utilities, trash, internet) and the ones _money_monthly_fees already
    counts are left out."""
    found: list[tuple[str, float]] = []
    own = re.compile(r"pet|dog|cat|parking|garage|carport|storage|locker|utilit|water|sewer|gas|electric|heat|trash|internet|cable|hoa|rent|deposit|application|admin|move|broker|insurance|amenity|community|technology|tech|package|pest|convenience|smart", re.I)
    for line in re.split(r"\n|;|\.(?=\s|$)", text):
        if not re.search(r"\b(?:mandatory|required|must|compulsory)\b", line, re.I) or re.search(r"\bnot (?:mandatory|required)\b|\boptional\b|\bif required\b", line, re.I):
            continue
        for m in re.finditer(r"\b((?:[A-Za-z]+[ \t]+){1,3}?fees?)\b[ \t:\-=]{0,3}(?:of[ \t]+)?\$\s?(\d{1,4})(?:\.\d\d)?[ \t]*" + _MONTHLY_RE, line, re.I):
            label = " ".join(m.group(1).split()).lower()
            label = re.sub(r"^(?:the|a|an|our|mandatory|required)\s+", "", label)
            if own.search(label) or not label.endswith(("fee", "fees")):
                continue
            found.append((label, float(m.group(2))))
    return found


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
