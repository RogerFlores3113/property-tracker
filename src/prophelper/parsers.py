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

import contextvars
import functools
import itertools
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
_STATE_NAMES = {"alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA", "colorado": "CO", "connecticut": "CT",
                "delaware": "DE", "district of columbia": "DC", "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID", "illinois": "IL",
                "indiana": "IN", "iowa": "IA", "kansas": "KS", "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
                "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS", "missouri": "MO", "montana": "MT",
                "nebraska": "NE", "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
                "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA",
                "rhode island": "RI", "south carolina": "SC", "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
                "vermont": "VT", "virginia": "VA", "washington": "WA", "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY"}
_STATE_NAME_RE = "|".join(sorted((n.replace(" ", r"[ \t]+") for n in _STATE_NAMES), key=len, reverse=True))


def state_code(value: Any) -> str:
    """"Ohio" or "OH" or "oh" gives "OH"; anything that is not a US state gives an empty string."""
    v = " ".join(str(value or "").replace(".", " ").split())
    if v.upper() in _STATES:
        return v.upper()
    return _STATE_NAMES.get(v.lower(), "")


_STREET = (r"(?:st|street|ave|avenue|rd|road|dr|drive|blvd|boulevard|ln|lane|ct|court|pl|place|way|cir|circle|pkwy|parkway|"
           r"ter|terrace|trl|trail|hwy|highway|loop|plaza|pike|(?:row|walk|alley|path|mews)(?![ \t]+(?:ln|lane|st|street|ave|avenue|rd|road|dr|drive|blvd|boulevard|ct|court|pl|place|way|cir|circle|ter|terrace|trl|trail|pkwy|parkway)\b)|sq(?=\.?,|\.?[ \t]+(?:unit|apt|apartment|suite|ste|#))|square(?=\b,))")
_NOT_STREET_WORDS = {"bed", "beds", "bedroom", "bedrooms", "bath", "baths", "bathroom", "bathrooms", "br", "ba", "bd", "bds", "sq",
                     "ft", "sqft", "month", "mo", "year", "years", "min", "minute", "minutes", "mile", "miles", "unit", "units",
                     "floor", "floors", "car", "cars", "pet", "pets", "story", "stories", "block", "blocks", "min."}
# words that make "2 driveway spots OR street" or "1 car garage or street" a parking phrase, never a street address
_PARKING_ADDRESS_WORDS = frozenset("driveway driveways spot spots garage garages parking permit permits or and covered stall stalls space spaces either free included carport carports".split())
_ADDRESS_NOT_NAME = frozenset("near next with by off behind beside across".split())  # "1 ... near High St": a place described, not a street name
_UNIT = r"(?:#|apt\.?|apartment|unit|suite|ste\.?)\s*#?\s*([A-Za-z]?\d{1,5}[A-Za-z]?(?:-\d{1,3})?|[NS][EW]\b|[A-Z])\b"
_ADDRESS = re.compile(
    r"(?<![\w$.,/-])(\d{1,6}(?:-\d{1,6})?[ \t]+(?:[NSEW]\.?[ \t]+|(?:North|South|East|West)[ \t]+)?"
    r"(?:(?:\d{1,3}(?:st|nd|rd|th)|[A-Za-z][A-Za-z.'-]*)[ \t]+){0,4}?" + _STREET + r"\b\.?"
    r"(?:(?<=[Cc][Tt])[ \t]+(?:dr|drive|ln|lane|way|rd|road|st|street|ave|avenue|pl|place|blvd)\b\.?|(?<=[Cc]ourt)[ \t]+(?:dr|drive|ln|lane|way|rd|road|st|street|ave|avenue|pl|place|blvd)\b\.?|"
    r"(?<=[Cc][Ii][Rr])[ \t]+(?:dr|drive|ln|lane|way|rd|road|st|street|ave|avenue|pl|place|blvd)\b\.?|(?<=[Pp][Ll])[ \t]+(?:dr|drive|ln|lane|way|rd|road|st|street|ave|avenue|blvd)\b\.?)?"
    r"(?:[ \t]+(?:NE|NW|SE|SW|N|S|E|W)\b\.?(?=[ \t]*(?:[,\n#\d]|$|(?:apt|apartment|unit|suite|ste|near|with|and|\$)\b|\$|(?-i:[A-Z][A-Za-z.'-]+(?: [A-Z][A-Za-z.'-]+){0,3},?[ \t]+[A-Z]{2}\b))))?)"
    r"(?:,?\s+" + _UNIT + r")?", re.I)
_CITY_LINE = re.compile(r"([A-Z][A-Za-z.'-]+(?: [A-Z][A-Za-z.'-]+){0,3}),?\s+([A-Z]{2}),?\s+(\d{5})(?:-\d{4})?\b")
_CITY_LINE_NAME = re.compile(r"([A-Z][A-Za-z.'-]+(?: [A-Z][A-Za-z.'-]+){0,3}),?[ \t]+(" + _STATE_NAME_RE + r"),?[ \t]+(\d{5})(?:-\d{4})?\b", re.I)
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
_UTIL_WORD = re.compile(r"\b(?:utilit\w*|electric\w*|power|gas|water|sewer|trash|garbage|internet|wi-?fi|cable|heat\w*)\b", re.I)
_EST_CUE_END = re.compile(r"(?:\babout|\bapprox\.?|\bapproximately|\baround|\broughly|\best\.?|\bestimated|\bavg\.?|\baverage|\btypically|\busually|\bbetween|~|\btotal|\bcosts?|\bis|\bare|[:=-])[ \t]*$", re.I)
_UTIL_AFTER = re.compile(r"^[ \t]*(?:\(?(?:all[- ]in|total|combined|each)\)?[ \t,]*)?(?:(?:/|per|a)[ \t]*(?:mo\w*|month\w*)[ \t]*)?(?:total[ \t]+)?(?:(?:for|on|toward|towards|covers?|covering|to[ \t]+cover|in)[ \t]+)?(?:all[ \t]+)?(?:the[ \t]+)?(?:your[ \t]+)?(?:electric\w*|power|gas|water|sewer|trash|garbage|internet|wi-?fi|cable|heat\w*|utilit\w*)\b(?![ \t,]*(?:and[ \t]+\w+[ \t]+)?(?:is[ \t]+|are[ \t]+)?(?:not|no|incl\w*|extra|separate|excluded|additional|plus|paid[ \t]+by[ \t]+(?:the[ \t]+)?(?:landlord|owner))\b)", re.I)


def _utility_clause_amount(text: str, start: int, end: int) -> bool:
    """Cycle 21: a figure inside a clause about utilities ("Tenant pays utilities, about $230 per month", "$230 a month for electric, gas and
    water") is what the utilities cost, never the rent."""
    seg_start = max(text.rfind("\n", 0, start) + 1, 0)
    seg = text[seg_start:start]  # the last sentence only: cut at the final sentence break
    cuts = [m.end() for m in re.finditer(r"(?<!approx)(?<!Approx)(?<!est)(?<!Est)(?<!avg)(?<!Avg)[.!?;][ \t]+", seg)]
    if cuts:
        seg = seg[cuts[-1]:]
    after = text[end:end + 90].split("\n")[0]
    if _UTIL_AFTER.match(after) and not _RENT_LABEL.search(seg[-12:]):
        return True
    if _UTIL_WORD.search(seg) and _EST_CUE_END.search(seg) and not re.search(r"\b(?:rent|price|asking)\b[ \t]*[:=-]?[ \t]*(?:is[ \t]*)?(?:about|approx\.?|~)?[ \t]*$", seg, re.I) \
            and re.search(r"\b(?:you|tenant|tenants|resident|residents|renter|renters)\b[^.\n]{0,25}\b(?:pays?|responsible|covers?)\b|\b(?:utilit\w*|electric\w*|power|gas|water|sewer|trash|internet)\b[^.\n$]{0,40}$", seg, re.I):
        return True
    return False


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
    if "\u202e" in text:
        from . import guards as _guards  # cycle 28: text under a right-to-left override is read in the order it shows on screen
        text = _guards.bidi_visual(text)
    for a, b in (("\u00a0", " "), ("\u2009", " "), ("\u202f", " "), ("\u200b", ""), ("\ufeff", ""), ("\r\n", "\n"), ("\r", "\n"),
                 ("\u2019", "'"), ("\u2018", "'"), ("\u201c", '"'), ("\u201d", '"'), ("\u2212", "-")):
        text = text.replace(a, b)
    text = re.sub(r"[\u2013\u2014]", "-", text)
    return normalize_money(text)


_FULLWIDTH = {**{0xFF10 + i: 0x30 + i for i in range(10)}, 0xFF04: 0x24, 0xFE69: 0x24}
_MONEY_K_WORD = re.compile(r"concession|credit|closing|seller|toward|reserve|assessment|\bfees?\b|dues|deposit|\brent\b|\bcash\b|\bpay|\bcost|\bprice|\boffer|\bhoa\b|\btax|insurance|\bbudget|\bcommission|\bgrant|\bhelp", re.I)
_K_NOT_MONEY = re.compile(r"^\s*(?:sq|sf|ft|run|tv|video|mi\b|miles?|steps|lbs|pounds|resolution|display|monitor)", re.I)


def normalize_money(text: str) -> str:
    """Cycle 23: one spelling of money for every reader and the guard. A fullwidth dollar or digits, "USD 30", "US$30", "30 USD", "30 dollars" or
    "30 bucks" become "$30", and "$6k", "$1.5k" or a "6k" beside a money word ("$6k in concessions", "6k credit") become "$6,000" and
    "$1,500". Nothing else in the text changes."""
    if not text:
        return text
    if any(0xFF00 <= ord(c) <= 0xFFEF or ord(c) == 0xFE69 for c in text):
        text = text.translate(_FULLWIDTH)
        text = re.sub(r"(?<=\d)\uFF0C(?=\d)", ",", text)
        text = re.sub(r"(?<=\d)\uFF0E(?=\d)", ".", text)
    if "$" in text or re.search(r"usd|dollar|bucks|\d\s?k\b", text, re.I):
        text = re.sub(r"\bUS\s?\$\s?(?=\d)", "$", text, flags=re.I)
        text = re.sub(r"\bUSD\s?\$?\s?(?=\d)", "$", text, flags=re.I)
        text = re.sub(r"(?<![\w$.,])(\d{1,3}(?:,\d{3})+|\d+)(\.\d{1,2})?\s?(?:USD|US dollars?|dollars?|bucks)\b", lambda m: "$" + m.group(1) + (m.group(2) or ""), text, flags=re.I)

        # cycle 25: the dollar sign after the number ("парковка 50$", "50 $/mo", "1,200$") is money too; "$50" is left as it is
        text = re.sub(r"(?<![\w$.,])(\d{1,3}(?:\.\d{3})+)[ \t]?\$(?![ \t]?\d)", lambda m: "$" + m.group(1).replace(".", ","), text)
        text = re.sub(r"(?<![\w$.,])(\d{1,3}(?:,\d{3})+|\d+)(\.\d{1,2})?[ \t]?\$(?![ \t]?\d)", lambda m: "$" + m.group(1) + (m.group(2) or ""), text)

        # cycle 24: a European thousands dot ("$1.700", "$1.700,50", "$12.500") is $1,700 / $1,700.50 / $12,500, never $1.70 (a dot with exactly three digits after it
        # and no more is a thousands mark: nobody writes a thousandth of a dollar)
        text = re.sub(r"\$\s?(\d{1,3}(?:\.\d{3})+),(\d{2})(?!\d)", lambda m: "$" + m.group(1).replace(".", ",") + "." + m.group(2), text)
        text = re.sub(r"\$\s?(\d{1,3}(?:\.\d{3})+)(?![\d.]|,\d)", lambda m: "$" + m.group(1).replace(".", ","), text)

        def _k(m: re.Match[str]) -> str:
            n = float(m.group(1).replace(",", "")) * 1000
            return "$" + (f"{n:,.0f}" if n == int(n) else f"{n:,.2f}")
        text = re.sub(r"\$\s?(\d+(?:\.\d+)?)\s?[kK]\b(?![\w-]*\w)", _k, text)

        def _bare_k(m: re.Match[str]) -> str:
            ls = text.rfind("\n", 0, m.start()) + 1
            le = text.find("\n", m.end())
            near = text[max(ls, m.start() - 40):min(le if le >= 0 else len(text), m.end() + 40)]
            if _K_NOT_MONEY.search(text[m.end():m.end() + 12]) or not _MONEY_K_WORD.search(near):
                return m.group(0)
            return _k(m)
        text = re.sub(r"(?<![\w$.,])(\d+(?:\.\d+)?)[kK]\b(?![-\w])", lambda m: _bare_k(m), text)
    return text


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def _tidy_number(x: float) -> int | float:
    return int(x) if float(x).is_integer() else round(x, 2)


def _usd(x: float) -> str:
    """Cycle 24: "$42.50" and "$1,200": cents are kept when the amount has them (never "$42" for "$42.50")."""
    x = float(x)
    return f"${x:,.2f}" if abs(x - round(x)) > 0.004 else f"${x:,.0f}"


# --------------------------------------------------------------------------- money
_LEASE_CONDITION = re.compile(r"\s*(?:/\s*mo\w*\s*)?(?:with|for|on|if you sign|when you sign)\s+(?:a\s+|an\s+)?(\d{1,2})[- ]?(?:month|mo)s?\b", re.I)


_NOT_RENT_EXTRA = re.compile(r"\b(?:second|2nd|third|3rd|extra|additional|add'?l\.?|another|optional|guest)[ \t]+(?:[a-z-]+[ \t]+)?(?:space|spot|car|vehicle|storage|locker|parking|garage|carport|bike|person|occupant|adult|pet|resident|tenant|key|fob|unit|room)s?\b[^$\n]{0,15}$"
                            r"|\b(?:storage|locker|parking|garage|carport|bike[ \t]+room)[ \t]+(?:space|spot|unit|rental|rent|cost|fee)[ \t]*[:=-]?[ \t]*(?:is|are|at|for)?[ \t]*$", re.I)


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
            fee = bool(_FEE_BEFORE.search(clause[-22:])) and not _RENT_LABEL.search(clause[-14:]) or bool(_FEE_AFTER_MONTHLY.match(tail)) \
                or _utility_clause_amount(text, m.start(), m.end())
        elif not fee:
            fee = bool(_FEE_AFTER_STRICT.match(tail)) and not re.match(r"\s*\+\s*(?:all\s+)?(?:the\s+)?utilit", tail, re.I)  # "$1,150 + utilities" is the rent
        if not fee and _NOT_RENT_EXTRA.search(clause):
            fee = True  # cycle 26: "Second space $200/mo", "extra storage $50/mo", "additional occupant $75": never a rent candidate
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


_CORRECTION_CUE = (r"(?:\?+[ \t]*no\b[ \t,:;.!-]*(?:(?:sorry|wait|actually|it'?s)\b[ \t,:;.!-]*)?|\bno[ \t,]+(?:sorry|wait|actually)\b[ \t,:;.!-]*|"
                   r"\b(?:sorry|actually|oops|correction|my[ \t]+bad)\b[ \t,:;.!-]*(?:(?:no|sorry|actually)\b[ \t,:;.!-]*)?)")
_CORRECTED_RENT = re.compile(r"(?P<first>(?<![\w.,$#/-])(?:\$[ \t]?)?(?:\d{1,2},\d{3}|\d{3,5}|\d(?:\.\d{1,2})?[ \t]?k)\b[ \t]*(?:a[ \t]+month|per[ \t]+month|/[ \t]*mo(?:nth)?|monthly)?[ \t]*[?!]*)[ \t,;:.-]*"
                             + _CORRECTION_CUE + r"(?:rent[ \t]+(?:is[ \t]+)?|it'?s[ \t]+|its[ \t]+)?\$?[ \t]?(?P<n>\d{1,2},\d{3}|\d{3,5})(?![\d,]*\d)(?!\.\d)(?![ \t]*(?:sq|sf|ft|bed|br|bd|bath|ba\b|%|deposit|fee|pet|/[ \t]*(?:bed|room)|per[ \t]+(?:bed|room|person)))", re.I)


_UNIT_LABEL = r"(studio\b|\d(?:\.\d)?(?=[ \t-]*(?:br|bd|bds|bed|beds|bedroom|bedrooms)\b))(?:[ \t-]*(?:br|bd|bds|bed|beds|bedroom|bedrooms)\b)?"


def _unit_price_hits(text: str) -> list[tuple[int, int, float, float]]:
    """Cycle 20: rents given for different bedroom counts in one listing: "3BR is $2,295/mo", "2 bed: $1,290", "$1,290, that is the 2BR",
    "$1,500 for the 1 bedroom". Returns (start, end, bedrooms, monthly amount) for each, in order. Only amounts in the rent range count."""
    found: list[tuple[int, int, float, float]] = []
    for m in re.finditer(r"(?<![\w$])" + _UNIT_LABEL + r"[ \t]*(?:is|are|:|=|@|at|for|-|\u2013|\u2014|rent(?:s)?(?:[ \t]+(?:is|are|at))?)?[ \t]*(?:only[ \t]+|now[ \t]+|just[ \t]+)?\$\s?(\d{1,2},\d{3}|\d{3,5})(?!\d|,\d)(?:\.\d\d)?(?![ \t]*(?:deposit|fee|pet|/[ \t]*(?:bed|room)|per[ \t]+(?:bed|room|person)))", text, re.I):
        found.append((m.start(), m.end(), 0.0 if m.group(1).lower() == "studio" else float(m.group(1)), _num(m.group(2))))
    for m in re.finditer(r"\$\s?(\d{1,2},\d{3}|\d{3,5})(?!\d|,\d)(?:\.\d\d)?[^$.\n;]{0,30}?\b(?:that|this|it)(?:'s|[ \t]+is)[ \t]+(?:only[ \t]+)?(?:the[ \t]+|for[ \t]+the[ \t]+)?" + _UNIT_LABEL
                         + r"|\$\s?(\d{1,2},\d{3}|\d{3,5})(?!\d|,\d)(?:\.\d\d)?[ \t]*(?:/[ \t]*mo(?:nth)?|per[ \t]+month|a[ \t]+month|monthly)?[ \t]*(?:for|on|is for|is|are)[ \t]+(?:only[ \t]+)?(?:the[ \t]+)?" + _UNIT_LABEL, text, re.I):
        amt, lab = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        found.append((m.start(), m.end(), 0.0 if lab.lower() == "studio" else float(lab), _num(amt)))
    found.sort()
    return [h for h in found if 300 <= h[3] <= 30000]


def _unit_prices(text: str) -> list[tuple[float, float]]:
    return [(b, a) for _s, _e, b, a in _unit_price_hits(text)]


def _unit_price_beds(text: str) -> float | None:
    """The bedroom count the listing is about, read with the unit price lines taken out (a bedroom count that only appears in the
    price list is not the count the listing is about)."""
    hits = _unit_price_hits(text)
    blank = text
    for s0, e0, _b, _a in sorted(hits, reverse=True):
        blank = blank[:s0] + " " * (e0 - s0) + blank[e0:]
    return _beds(blank)


def _unit_price_pick(text: str, beds: float | None) -> tuple[float | None, str, bool] | None:
    """When the listing gives rents for two or more different bedroom counts: (rent for the listing's own bedroom count or None, a plain
    note, True when a rent was picked). None when the listing does not give prices for different bedroom counts."""
    pairs = _unit_prices(text)
    kinds = {b for b, _a in pairs}
    if len(kinds) < 2:
        return None

    def name(b: float) -> str:
        return "studio" if b == 0 else f"{b:g} bedroom"

    def shown(b: float, a: float) -> str:
        was = re.search(r"\$\s?(\d{1,2},\d{3}|\d{3,5})(?:\.\d\d)?[ \t]*(?:->|=>|-->|\u2192|to)[ \t]*(?:now[ \t]+)?\$\s?" + re.escape(f"{a:,.0f}") + r"(?![\d,])", text, re.I)
        return f"the {name(b)} is ${a:,.0f}" + (f", it was ${_num(was.group(1)):,.0f}" if was else "")

    listed = "; ".join(dict.fromkeys(shown(b, a) for b, a in pairs))
    mine = [a for b, a in pairs if beds is not None and b == beds]
    if beds is not None and len(set(mine)) == 1:
        others = "; ".join(dict.fromkeys(shown(b, a) for b, a in pairs if b != beds))
        return mine[0], f"The listing gives rents for more than one size ({others}). The rent saved is the one for the {name(beds)} this listing is about. Check it.", True
    if not re.search(r"\b(?:sorry|oops|actually|correction|corrected|mistake|typo|my bad|that(?:'s| is) the|not the|wrong)\b", text, re.I):
        return None  # a plain floor plan list ("Studio $950 ... 1 bed $1,200, 2 bed $1,500") keeps the old reading: its first unit
    return None, f"The listing gives rents for more than one size ({listed}) and I could not tell which one this place is, so the rent is left empty. Ask which size it is and what it costs.", False


_SUPERSEDED_RENT = (
    r"\(?\bnot[ \t]+\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?(?!\d)[^.\n)]{0,30}?\b(?:earlier|previously|before|posted|listed|advertised|typo|mistake|error|wrong|incorrect|anymore|any[ \t]+more|as[ \t]+stated)\b",
    r"\b(?:earlier|previously|originally|first)[ \t]+(?:posted|listed|advertised|stated)(?:[ \t]+(?:as|at))?[ \t]+\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?(?!\d)[^.\n]{0,40}?\b(?:typo|mistake|error|wrong|incorrect)\b",
    r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?(?!\d)[^.\n$]{0,30}?\b(?:was|is)[ \t]+(?:a[ \t]+|an[ \t]+)?(?:typo|mistake|error|wrong|incorrect)\b",
    r"\b(?:ignore|disregard|correction)[ \t:,-]+(?:the[ \t]+)?(?:earlier[ \t]+|old[ \t]+|previous[ \t]+)?\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?(?!\d)",
)


_SUPERSEDED_SAID = re.compile(r"\b(?:earlier|previous(?:ly)?|old|prior|original(?:ly)?)[ \t]+(?:ad|listing|post(?:ing)?|price|rent|figure|number|version)?[ \t]*(?:said|was|showed|had|listed|read|stated|gave)[ \t]+(?:a[ \t]+(?:rent|price)[ \t]+of[ \t]+)?\$[ \t]?(\d{1,2},\d{3}|\d{3,5})(?!\d|,\d)(?:\.\d\d)?", re.I)


def _superseded_amounts(text: str) -> list[float]:
    """Cycle 20: a figure the listing itself takes back ("rent is $1,440 (not $1,380 as earlier posted)", "$1,380 was a typo"). It is not an
    amount to count, so one short note names it and nothing calls it missing."""
    out: list[float] = []
    for pat in _SUPERSEDED_RENT:
        for m in re.finditer(pat, text, re.I):
            v = _num(m.group(1))
            if v not in out:
                out.append(v)
    for m in _SUPERSEDED_SAID.finditer(text):  # cycle 26: "rent is now $3,250 (earlier ad said $3,400)", "(was $3,400)" next to a correction word
        line = text[text.rfind("\n", 0, m.start()) + 1:(text.find("\n", m.end()) if text.find("\n", m.end()) >= 0 else len(text))]
        if re.search(r"\b(?:correct\w*|updated?|now|revised|changed|new[ \t]+(?:rent|price))\b", line, re.I):
            v = _num(m.group(1))
            if 300 <= v <= 30000 and v not in out:
                out.append(v)
    return out


def _corrected_rent(text: str) -> tuple[float, str] | None:
    """Cycle 19: "1.5k a month, no sorry 2,350", "$1,500/mo? actually $1,650/mo": a rent the listing takes back and replaces. Returns
    (the new rent, the first figure as written) or None. The first figure must itself look like a rent, so "no 1,000 deposit" is no correction."""
    for m in _CORRECTED_RENT.finditer(text):
        new = _num(m.group("n"))
        if not 300 <= new <= 30000:
            continue
        first = m.group("first").strip(" ?!")
        if not re.search(r"\$|k\b|month|/\s*mo|monthly", first, re.I) and not re.search(r"\brent\b[^.\n]{0,15}$", text[max(0, m.start("first") - 20):m.start("first")], re.I):
            continue
        return new, first
    return None


_RENT_FIX_CUE = re.compile(r"\b(?:correction|corrected|corrects?|updated?|edit(?:ed)?|revised?|new[ \t]+(?:rent|price)|(?:rent|price)[ \t]+(?:is[ \t]+)?now|changed[ \t]+to)\b", re.I)
_RENT_FIX_AMT = re.compile(r"\b(?:rent|price)\b[^$\n]{0,30}?\$[ \t]?(\d{1,2},\d{3}(?:\.\d\d)?|\d{3,5}(?:\.\d\d)?)(?!\d|,\d)|\$[ \t]?(\d{1,2},\d{3}(?:\.\d\d)?|\d{3,5}(?:\.\d\d)?)(?!\d|,\d)[ \t]*(?:/[ \t]*mo\w*|a[ \t]+month|per[ \t]+month|monthly)?[ \t]*(?:is[ \t]+the[ \t]+)?(?:new|correct|current)[ \t]+(?:rent|price)", re.I)
_RENT_FIX_TAKEN_BACK = re.compile(r"\b(?:ignore|disregard|replaces?|replacing|supersedes?|instead[ \t]+of|not[ \t]+the)\b[^.\n]{0,25}\b(?:earlier|old|previous|prior|original|first|above|posted|last)\b[^.\n]{0,15}\b(?:price|rent|figure|number|amount|listing)\b"
                                  r"|\b(?:earlier|old|previous|prior|original)[ \t]+(?:price|rent)\b[^.\n]{0,20}\b(?:wrong|incorrect|outdated|void|no[ \t]+longer|is[ \t]+a[ \t]+typo|was[ \t]+a[ \t]+typo)\b", re.I)


def _rent_correction(text: str) -> tuple[float, float | None, str] | None:
    """Cycle 24: "CORRECTION: rent is now $3,100, ignore earlier price.", "Edit: new rent $1,495. Ignore previous price.", "UPDATE: price corrected to $1,750,
    disregard the old price": a sentence that gives a new rent and takes the earlier one back. Returns (new rent, the earlier rent read from the rest of the
    listing or None, the sentence) or None. Only a sentence with a correction word AND a word that takes the old price back counts, so "now $1,450 if you
    sign by Dec 15" and "was $X now $Y" stay as they were."""
    if _SALE_WORDS.search(text):
        return None
    for sm in re.finditer(r"[^\n]+", text):
        line = sm.group(0)
        for part in re.finditer(r"(?:[^.!?]|(?<=\d)\.(?=\d))+[.!?]?", line):
            sent = part.group(0)
            if not sent.strip() or not _RENT_FIX_CUE.search(sent):
                continue
            am = _RENT_FIX_AMT.search(sent)
            if not am:
                continue
            new = _num(am.group(1) or am.group(2))
            if not 300 <= new <= 30000:
                continue
            scope = text[sm.start() + part.start():sm.start() + part.end() + 60]
            if not _RENT_FIX_TAKEN_BACK.search(scope):
                continue
            if _COND_AFTER.match(text[sm.start() + part.start() + am.end():sm.start() + part.start() + am.end() + 60]):
                continue
            a0, b0 = sm.start() + part.start(), sm.start() + part.end()
            rest = text[:a0] + " " * (b0 - a0) + text[b0:]
            old = _price(rest)
            if old is None:  # "$3,000" alone in a title line: the only rent-sized figure left is the earlier rent
                bare = {a["value"] for a in _amounts(rest) if not a["fee"] and a["marker"] != "per bed" and 300 <= a["value"] <= 30000}
                old = next(iter(bare)) if len(bare) == 1 else None
            return new, (old if old is not None and old != new else None), " ".join(sent.split())
    return None


_FIX_CUE = re.compile(r"\b(?:corrected?|corrections?|updated?|edit(?:ed)?|revised?|actually|changed[ \t]+to|should[ \t]+(?:be|read)|(?:is|are|it'?s|now)[ \t]+now|now[ \t]+(?:is|are|it'?s)|now[ \t]*[:=])\b|\bnow[ \t]*[:=]|\b(?:is|are|it'?s)[ \t]+now\b", re.I)
_FIX_OLD_BEFORE = re.compile(r"(?:earlier|earlier[ \t]+(?:ad|listing|post)|previous(?:ly)?|before|old|original(?:ly)?|first|was|were|said|says|showed|listed|not|instead[ \t]+of|rather[ \t]+than|from|than)[ \t:,(-]*(?:it[ \t]+)?(?:was[ \t]+|said[ \t]+|had[ \t]+)?(?:(?:a|an|the|only|just)[ \t]+)?$", re.I)
_FIX_BATH = re.compile(r"(?<![\d.,$/])\b(\d{1,2}(?:\.\d)?)[ \t-]*(?:full[ \t]+)?(?:ba\b|baths?\b|bathrooms?\b|bth?s?\b)", re.I)
_FIX_BED = re.compile(r"(?<![\d.,$/])\b(\d{1,2}|studio|one|two|three|four|five)[ \t-]*(?:bed(?:room)?s?\b|br\b|bds?\b|bdrms?\b)", re.I)
_FIX_DEP = re.compile(r"\bdeposit[ \t]*(?:is|of|was|:|=|-|now|to)?[ \t]*(?:is[ \t]+|now[ \t]+|to[ \t]+)*\$[ \t]?(\d{1,2},\d{3}(?:\.\d\d)?|\d{2,5}(?:\.\d\d)?)(?![\d,])|\$[ \t]?(\d{1,2},\d{3}(?:\.\d\d)?|\d{2,5}(?:\.\d\d)?)(?![\d,])[ \t]*(?:security[ \t]+)?deposit\b", re.I)


def _fix_sentences(text: str) -> list[str]:
    """Sentences and pipe or line pieces ("1.5 BA" keeps its decimal point)."""
    return [x.strip() for x in re.split(r"[|\n]|[.!?;](?=\s|$)", text) if x and x.strip()]


def _fix_pick(sent: str, rx: re.Pattern[str]) -> tuple[str | None, str | None]:
    """(the value the sentence gives as the new one, the old value it names). New = the last match that is not written as the old figure."""
    new = old = None
    for m in rx.finditer(sent):
        g = next((x for x in m.groups() if x), None)
        if g is None:
            continue
        if _FIX_OLD_BEFORE.search(sent[max(0, m.start() - 28):m.start()]):
            old = g
        else:
            new = g
    return new, old


def _corrected_facts(text: str) -> dict[str, tuple[Any, Any]]:
    """Cycle 26: a "Corrected:", "Update:" or "now" line that names a fact replaces the earlier value for that fact: "Corrected: earlier listing said
    2 BA, it is 1.5 BA", "UPDATE: now 1.5 bath (was 2)", "Edit: deposit is now $800". Returns {fact: (new value, old value or None)} for facts
    "baths", "beds" and "deposit"; the rent has its own reader (_rent_correction)."""
    out: dict[str, tuple[Any, Any]] = {}
    if _SALE_WORDS.search(text):
        return out
    for sent in _fix_sentences(text):
        if not _FIX_CUE.search(sent):
            continue
        new, old = _fix_pick(sent, _FIX_BATH)
        if new is not None:
            out["baths"] = (float(new), float(old) if old else None)
        new, old = _fix_pick(sent, _FIX_BED)
        if new is not None:
            nums = {"studio": 0.0, "one": 1.0, "two": 2.0, "three": 3.0, "four": 4.0, "five": 5.0}
            val = lambda g: nums[g.lower()] if g.lower() in nums else float(g)  # noqa: E731
            out["beds"] = (val(new), val(old) if old else None)
        new, old = _fix_pick(sent, _FIX_DEP)
        if new is not None and not re.search(r"\b(?:pet|parking|key|garage|holding|application)[ \t]+deposit", sent, re.I):
            out["deposit"] = (_num(new), _num(old) if old else None)
    return out


def _nice_date(iso: str) -> str:
    try:
        d = date.fromisoformat(iso)
        return f"{d.strftime('%b')} {d.day}, {d.year}"
    except (TypeError, ValueError):
        return str(iso)


def _corrected_date(text: str) -> str | None:
    """A date a correction line gives for when the place is available ("Update: available date is now Feb 1 2027 (was Jan 15)", "Corrected: move-in is 2/1/27").
    The date after the cue words in that sentence; None when there is none."""
    for sent in _fix_sentences(text):
        if not _FIX_CUE.search(sent) or not re.search(r"\b(?:avail\w*|move[- ]?in|ready|date)\b", sent, re.I):
            continue
        tail = sent
        for m in re.finditer(r"\b(?:now|is|to|corrected|correction|update|updated|actually)\b[ \t:,-]*", sent, re.I):
            tail = sent[m.end():]
        for cand in (tail, "Available " + tail):
            got = _try(lambda c=cand: _available(c))
            if got:
                return got
    return None


def _corrected_fact_note(label: str, new_text: str, old_text: str | None) -> str:
    was = f" It first said {old_text}." if old_text else ""
    return f"The listing corrects itself about the {label}.{was} The later value is saved and the earlier one is not used. Check it with the landlord."


# ----------------------------------------------------------------- cycle 27: one general correction step
_GC_KW = re.compile(
    r"(?P<named>\b(?:pet|parking|key|garage|holding|reservation|storage|fob|cleaning|move[- ]in|admin\w*|lease|late|utility|utilities|amenity|trash|internet)[ \t]+(?:rent|deposit|dep|fees?)\b)"
    r"|(?P<dep>\b(?:(?:security|sec\.?|refundable|damage)[ \t]+)?(?:deposit|dep)\b)"
    r"|(?P<hoa>\bhoa\b|\b(?:condo|association|assoc\.?)[ \t]+(?:fees?|dues)\b)"
    r"|(?P<tax>\b(?:property[ \t]+)?tax(?:es)?\b)"
    r"|(?P<app>\b(?:application|app)(?:[ \t]+fee)?\b)"
    r"|(?P<park>\b(?:parking|garage|carport)\b)"
    r"|(?P<rent>\b(?:monthly[ \t]+)?rent\b|\bprice\b|\basking\b)", re.I)
_GC_FIELD = {"dep": "deposit", "hoa": "hoa", "tax": "property_tax", "app": "application_fee", "park": "parking_cost", "rent": "price"}
_GC_LABEL = {"deposit": "deposit", "hoa": "HOA", "property_tax": "property tax", "application_fee": "application fee", "parking_cost": "parking cost", "price": "rent"}
_GC_MONEY = re.compile(r"\$[ \t]?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d\d))?(?!\d|,\d)")
_GC_LEAD = re.compile(r"^[ \t\"'(\[*#-]*(?:(?:corrected?|corrections?|actually)\b|(?:update[ds]?|revised|edit(?:ed)?)[ \t]*[:,\-\u2013\u2014])", re.I)
_GC_HARD = r"corrected?|corrections?|updated?|revised|edit(?:ed)?|actually|changed[ \t]+to|should[ \t]+(?:be|read)"
_GC_CUE = re.compile(r"\b(?P<w>now|" + _GC_HARD + r"|new)\b", re.I)
_GC_OLD = re.compile(r"\b(?:was|were|from|earlier|previously|before|originally|not|instead[ \t]+of|used[ \t]+to[ \t]+be|old|formerly|prior|said|listed[ \t]+as|posted[ \t]+as|ignore|disregard|than)\b", re.I)
_GC_FILL = (r"(?:rent|price|asking|deposit|dep|security|sec|hoa|dues|fees?|tax(?:es)?|property|monthly|(?:condo|association)[ \t]+(?:fees?|dues)|application|app|parking|garage|carport|is|are|of|at|only|just|now|the|a|an|total|to|be|should|will|"
            r"it'?s|its|this|unit|payment|charge|cost|costs|per|month|ad|listing|post|figure|number|version|as|had|showed|read|stated|gave|it|refundable|amount|for)")
_GC_TAIL = re.compile(r"^[ \t:=\-–—(]*(?:" + _GC_FILL + r"\b[ \t:=\-–—(]*)*$", re.I)
_GC_OLD_AFTER = re.compile(r"^[ \t]*(?:/[ \t]*\w+|per[ \t]+\w+|a[ \t]+(?:month|year)|monthly|yearly|annual\w*)?[ \t]*\)?[ \t]*[,;]?[ \t]*\(?[ \t]*(?:but[ \t]+)?(?:now|updated?|corrected|changed|->|=>|→|is[ \t]+now)\b", re.I)
_GC_NEW_AFTER = re.compile(r"^[ \t]*(?:/[ \t]*\w+|per[ \t]+\w+|a[ \t]+(?:month|year)|monthly|yearly)?[ \t]*(?:is|are)?[ \t]*(?:the[ \t]+)?(?:new|correct|current|updated)[ \t]+(?:rent|price|deposit|hoa|tax)", re.I)
_GC_SPECIAL = re.compile(r"\b(?:special|promo\w*|concession|if[ \t]+you|when[ \t]+you|sign(?:ed|ing)?[ \t]+by|move[- ]?in[ \t]+by|first[ \t]+(?:\d+|one|two|three|six|twelve)[ \t]+months?|limited[ \t]+time|discount\w*|off\b|waive[ds]?|free[ \t]+rent|reduced[ \t]+from|price[ \t]+(?:cut|drop))", re.I)
_GC_AFTER_KW = re.compile(r"^[ \t]*(?:/[ \t]*\w+[ \t]*)?(?:" + _GC_KW.pattern + r")", re.I)


def _gc_tail_state(window: str) -> str | None:
    """"old", "hard" (a correction word), "soft" (a bare "now") or None for the words just before an amount, looking only at what touches the amount."""
    last_old = last_cue = None
    for m in _GC_OLD.finditer(window):
        if _GC_TAIL.match(window[m.end():]):
            last_old = m
    for m in _GC_CUE.finditer(window):
        if _GC_TAIL.match(window[m.end():]):
            last_cue = m
    if last_old and (not last_cue or last_old.start() > last_cue.start()):
        return "old"
    if last_cue:
        return "soft" if last_cue.group("w").lower() in ("now", "new") else "hard"
    return None


def _gc_unit_value(field: str, value: float, after: str) -> float:
    """HOA is kept per month and property tax per year, so a figure written the other way is converted."""
    a = after[:28]
    monthly = bool(re.match(r"[ \t]*(?:/[ \t]*(?:mo|month)\b|per[ \t]+month|monthly|a[ \t]+month)", a, re.I))
    yearly = bool(re.match(r"[ \t]*(?:/[ \t]*(?:yr|year)\b|per[ \t]+(?:year|annum)|annual\w*|yearly|a[ \t]+year)", a, re.I))
    quarterly = bool(re.match(r"[ \t]*(?:/[ \t]*(?:qtr|quarter)\b|per[ \t]+quarter|quarterly)", a, re.I))
    if field == "hoa":
        if yearly:
            return round(value / 12, 2)
        if quarterly:
            return round(value / 3, 2)
    if field == "property_tax":
        if monthly:
            return round(value * 12, 2)
        if quarterly:
            return round(value * 4, 2)
    return value


def _general_corrections(text: str, buying: bool = False) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Cycle 27: one step for every named fact a "Corrected:", "Update:", "now" or "updated:" wording replaces: rent, deposit, HOA, property tax,
    application fee and parking cost. Layouts: "Corrected: rent is now $1,360", "Rent $1,275. Corrected: now $1,325 per month.", "HOA was $340/mo, now $385/mo",
    "Deposit is $1,275 (now $1,325)", "Property tax was $4,200, updated: $4,800/yr", "$2,300/mo. Corrected: rent now $2,250". Returns
    ({field: {"new", "olds" (the figures the listing takes back), "sentence"}}, quoted sentences it could not place)."""
    found: dict[str, dict[str, Any]] = {}
    unplaced: list[str] = []
    if not text or (_SALE_WORDS.search(text) and not buying):
        return found, unplaced
    sents = [(m.start(), m.group(0)) for m in re.finditer(r"(?:[^|\n.!?;]|(?<=\d)\.(?=\d))+", text) if m.group(0).strip()]
    prev_fields: list[set[str]] = []  # the named fields of each earlier sentence that had an amount
    for _off, s in sents:
        amts = list(_GC_MONEY.finditer(s))
        lead = bool(_GC_LEAD.match(s))
        prev_end, chain = 0, None
        sent_fields: set[str] = set()
        for a in amts:
            window = s[prev_end:a.start()]
            after = s[a.end():a.end() + 40]
            value = _num(a.group(1) + ("." + a.group(2) if a.group(2) else ""))
            if _GC_OLD_AFTER.match(after):
                role: str | None = "old"
            else:
                role = _gc_tail_state(window)
                if role is None and lead:
                    role = "hard"
                if role is None and _GC_NEW_AFTER.match(after):
                    role = "soft"
            field: str | None = None
            inherited = False
            kws = list(_GC_KW.finditer(window))
            if kws:
                k = kws[-1]
                field = "named" if k.lastgroup == "named" else _GC_FIELD[k.lastgroup]
            elif chain is not None:
                field = chain
            else:
                kk = _GC_AFTER_KW.match(after)
                if kk and kk.lastgroup:
                    field = "named" if kk.lastgroup == "named" else _GC_FIELD[kk.lastgroup]
            hard = role == "hard" or lead
            if field is None and role in ("hard", "soft") and hard:
                for pf in reversed(prev_fields):  # "Corrected: now $1,325 per month": the fact is the one the sentence before it was about
                    if len(pf) == 1:
                        field = next(iter(pf))
                        inherited = True
                    break
            if field is not None:
                chain = field
            prev_end = a.end()
            if field and field != "named":
                sent_fields.add(field)
            if role is None or field == "named":
                continue
            if role == "soft" and _GC_SPECIAL.search(s):
                continue  # "now $1,450 if you sign by Dec 15", "was $1,600, now $1,450 special": a special, never a correction
            if _COND_AFTER.match(after) and role != "old":
                continue
            if field is None:
                if hard and role != "old" and value >= 100 and re.search(r"\b(?:now|corrected?|corrections?|updated?|revised)\b", s, re.I) \
                        and not re.search(r"\d[ \t]?[xX\u00d7][ \t]?\d|\b(?:bed(?:room)?s?|br|bd|bds)\b", s, re.I):
                    q = " ".join(s.split())
                    if q not in unplaced:
                        unplaced.append(q)
                continue
            if buying and field in ("price", "deposit"):
                continue
            if inherited and field in ("deposit", "application_fee", "property_tax") and re.match(r"[ \t]*(?:/[ \t]*(?:mo|month)\b|per[ \t]+month|a[ \t]+month|monthly)", after, re.I):
                if hard and role != "old":  # "Corrected: now $1,450 per month" after a deposit line: a monthly figure is not a deposit, so it cannot be placed
                    q = " ".join(s.split())
                    if q not in unplaced:
                        unplaced.append(q)
                continue
            value = _gc_unit_value(field, value, after)
            ent = found.setdefault(field, {"new": None, "olds": [], "sentence": "", "spans": []})
            ent["spans"].append((_off + a.start(), _off + a.end()))
            if role == "old":
                if value not in ent["olds"]:
                    ent["olds"].append(value)
            else:
                if ent["new"] is not None and ent["new"] != value and ent["new"] not in ent["olds"]:
                    ent["olds"].append(ent["new"])
                ent["new"] = value
                ent["sentence"] = " ".join(s.split())
        if amts:
            prev_fields.append(sent_fields)
    ranges = {"price": (300, 30000), "deposit": (0, 50000), "hoa": (1, 6000), "property_tax": (50, 200000), "application_fee": (0, 1000), "parking_cost": (0, 1000)}
    for fld in list(found):
        ent = found[fld]
        if ent["new"] is None or not ranges[fld][0] <= ent["new"] <= ranges[fld][1]:
            del found[fld]
            continue
        ent["olds"] = [o for o in ent["olds"] if o != ent["new"]]
    return found, unplaced


def _gc_fmt(field: str, v: float) -> str:
    return _usd(v) + (" a month" if field == "hoa" else " a year" if field == "property_tax" else "")


def _gc_apply(text: str, out: dict[str, Any], facts: list[str], found: dict[str, dict[str, Any]], unplaced: list[str], buying: bool, only: set[str] | None = None) -> None:
    """Apply the corrections to the read fields. Each applied correction gets one short note that names the old value as not used; an older note about
    the old value goes. A correction that cannot be placed is quoted."""
    for fld, ent in found.items():
        if only is not None and fld not in only:
            continue
        if fld in ("hoa", "property_tax") and not buying and out.get(fld) is None and not _SALE_WORDS.search(text):
            continue
        if fld in ("application_fee", "parking_cost") and out.get(fld) is None:
            continue
        new = ent["new"]
        before = out.get(fld)
        olds = list(ent["olds"])
        if not olds and isinstance(before, (int, float)) and not isinstance(before, bool) and not _same_num(before, new):
            olds.append(float(before))
        out[fld] = _tidy_number(new)
        if not olds:
            continue
        label = _GC_LABEL[fld]
        olds_txt = [_gc_fmt(fld, o) for o in olds]
        kw = {"price": r"\b(?:rent|price)\b", "deposit": r"\bdeposit\b", "hoa": r"\b(?:hoa|condo)\b", "property_tax": r"\btax", "application_fee": r"\bapplication\b", "parking_cost": r"\bparking\b"}[fld]
        have = [f for f in facts if "correct" in f.lower() and re.search(kw, f, re.I) and any(re.search(re.escape(_usd(o)) + r"(?![\d,])", f) for o in olds)]
        facts[:] = [f for f in facts if f in have or "correct" in f.lower() or not re.search(kw, f, re.I) or not any(re.search(re.escape(_usd(o)) + r"(?![\d,])", f) for o in olds)]
        if have:
            continue
        old_list = " and ".join(olds_txt) if len(olds_txt) <= 2 else ", ".join(olds_txt)
        facts.append(f"The listing corrects the {label}: it is now {_gc_fmt(fld, new)}. The earlier {old_list} {'is' if len(olds_txt) == 1 else 'are'} not used. Ask the landlord to confirm it.")


def _gc_quote_unplaced(facts: list[str], unplaced: list[str]) -> None:
    for q in unplaced:
        if not any(q[:60] in f for f in facts):
            facts.append(f'The listing has a correction I could not match to one fact: "{q[:140]}". Nothing was changed from it, so the saved amounts may be out of date. Ask the landlord which amount is right.')


_BB_PRICE = re.compile(r"(?<![\w$#/.,-])\d(?:\.\d)?[ \t]*(?:br|bd|bds|bed|beds|bedrooms?)(?![A-Za-z])[ \t]*[/|,\u00b7x-]?[ \t]*\d(?:\.\d)?[ \t]*(?:ba|bath|baths|bathrooms?)\b[ \t]*[-|,:\u2013\u2014\u00b7]?[ \t]*"
                       r"\$[ \t]?(\d{1,2},\d{3}|\d{3,5})(?![\d,])(?!\.\d)(?![ \t]*(?:deposit|fee|pet|hoa|/[ \t]*(?:bed|room)|per[ \t]+(?:bed|room|person)|off\b))", re.I)


def _beds_baths_price(text: str) -> float | None:
    """Cycle 19: a header that gives the price right after the beds and baths: "Logan Square 3BR2BA $3,250.", "3bd/2ba - $3,250",
    "3 BR | 2 BA | $3,250/mo". The dollar sign is required, so a street number after the baths is never read. One price only."""
    found = {_num(m.group(1)) for m in _BB_PRICE.finditer(text)}
    found = {v for v in found if 300 <= v <= 30000}
    return next(iter(found)) if len(found) == 1 else None


_FLOOR_PLAN_PRICE = re.compile(r"(?<![\w.,$/#-])([0-6])[ \t]?[xX\u00d7][ \t]?([1-4](?:\.5)?)(?![\w/$%'\"-]|\.\d)(?P<mid>[^\n$0-9]{0,32}?)\$[ \t]?(?P<n>\d{1,2},\d{3}|\d{3,5})(?![\d,])(?!\.\d)"
                               r"(?![ \t]*(?:deposit|fee|pet|hoa|/[ \t]*(?:bed|room)|per[ \t]+(?:bed|room|person)|off\b|application|admin))")


def _floor_plan_prices(text: str) -> list[tuple[float, float, float, bool]]:
    """Cycle 21: a rent written after a beds-by-baths shorthand: "Floor plan 2x1: $1,425", "Cozy 1x1 near campus, $1,150!!", "1x1. from $1,199".
    Returns (beds, baths, amount, starting_at) for each; only amounts that can be a monthly rent."""
    out: list[tuple[float, float, float, bool]] = []
    for m in _FLOOR_PLAN_PRICE.finditer(text):
        mid = m.group("mid")
        if re.search(r"[.;!?]\s+\S", mid.strip() + " x") and not re.fullmatch(r"[ \t]*[.:,\-]?[ \t]*(?:from|starting at|starts at)?[ \t]*", mid, re.I) and re.search(r"[.;]\s", mid):
            continue  # the shorthand and the amount are in different sentences
        if re.search(r"\b(?:deposit|fees?|pets?|parking|utilit\w*|hoa|tax|insurance|per\s+(?:person|adult)|each)\b", mid, re.I):
            continue
        v = _num(m.group("n"))
        if 300 <= v <= 30000:
            out.append((float(m.group(1)), float(m.group(2)), v, bool(re.search(r"\b(?:from|starting|starts)\b", mid, re.I))))
    return out


_STRICT_RENT_LABEL = re.compile(r"(?<![\w-])(?:monthly[ \t]+)?rent(?:[ \t]+is|[ \t]+of)?[ \t]*(?:[:=\-\u2013\u2014][ \t]*)?(?:is[ \t]+)?(?:about[ \t]+|approx\.?[ \t]+|~)?$", re.I)
_SIDE_KIND = re.compile(r"\b(?:garage|parking|carport|covered[ \t]+parking|pets?|dogs?|cats?|storage|valet|utilit\w*|internet|wifi|cable|amenity|package|pest|trash|laundry|furnish\w*|fees?)\b", re.I)
_SIDE_CUE = re.compile(r"\b(?:optional|available|extra|additional|add[- ]?on|by[ \t]+request|if[ \t]+(?:you[ \t]+)?(?:want|desired|needed)|per[ \t]+(?:space|pet|car|vehicle)|each|fee|rent|monthly)\b|[:\-\u2013]\s*$", re.I)


def _side_clause_amount(text: str, start: int) -> bool:
    """Cycle 25: the figure sits in a parking, pet, storage or utility clause of its own ("| Garage parking optional, $200/mo",
    ". Pet rent $35/mo"): the last pipe, bullet, semicolon, line or sentence piece before it names that thing and has no rent label."""
    seg_start = max(text.rfind("\n", 0, start) + 1, 0)
    seg = text[seg_start:start]
    cuts = [m.end() for m in re.finditer(r"[|;\u2022\u00b7]|(?<!approx)(?<!Approx)(?<!est)(?<!Est)(?<!avg)(?<!Avg)(?<!no)(?<!No)[.!?][ \t]+", seg)]
    if cuts:
        seg = seg[cuts[-1]:]
    seg = seg[-70:]
    if not _SIDE_KIND.search(seg) or _STRICT_RENT_LABEL.search(seg[-22:]):
        return False
    if re.search(r"\b(?:bed(?:room)?s?|br|bd|bath|apartment|apt|unit|home|house|studio)\b", seg, re.I) and not re.search(r"\b(?:optional|extra|additional)\b", seg, re.I):
        return False  # "2 bed with garage, $1,500/mo": the garage is a feature of the place, the figure is its rent
    return bool(_SIDE_CUE.search(seg))


def _real_sale_words(text: str) -> bool:
    """Cycle 25: sale wording in the text, not counting "open house" (a rental can have an open house, "6 month lease available at $2,550. Open house Sunday")."""
    return any(m.group(0).lower() != "open house" and not (m.group(0).lower() == "offered at" and re.search(r"\b(?:leases?|terms?)[ \t]+(?:is[ \t]+|also[ \t]+)*$", text[max(0, m.start() - 20):m.start()], re.I))
               for m in _SALE_WORDS.finditer(text))


def _price(text: str) -> float | None:
    """The monthly rent if the text gives one, else the asking price of a home for sale."""
    corrected = None if _SALE_WORDS.search(text) else _corrected_rent(text)
    if corrected:
        return corrected[0]  # cycle 19: a rent the listing takes back ("1.5k a month, no sorry 2,350") never wins
    amounts = [a for a in _amounts(text) if not a["fee"] and a["marker"] != "per bed" and not a.get("conditional")]
    if not _real_sale_words(text):
        for a in amounts:  # cycle 25: "Rent: $3,200 | Garage parking optional, $200/mo": a figure labelled rent beats any other figure
            if a["labelled"] and 200 <= a["value"] < 20000 and _STRICT_RENT_LABEL.search(text[max(0, a["start"] - 22):a["start"]]) \
                    and not _side_clause_amount(text, a["start"]):
                return a["value"]
    for a in amounts:  # "$1,495/mo", "$1500 / 1br"
        if a["marker"] == "monthly" and 200 <= a["value"] <= 30000 and not _side_clause_amount(text, a["start"]):
            return a["value"]
    sale_text = bool(_SALE_WORDS.search(text))
    for a in amounts:  # "Rent: $1,495", "Monthly rent" on the line above
        if a["labelled"] and 200 <= a["value"] <= 30000 and not (sale_text and a["value"] >= 20000):
            return a["value"]
    dash = _dash_title_price(text)
    if dash and not sale_text and not any(a["value"] >= 20000 for a in amounts):
        return dash[0]
    hdr = _beds_baths_price(text)
    if hdr is not None and not sale_text and not any(a["value"] >= 20000 for a in amounts):
        return hdr  # cycle 19: "Logan Square 3BR2BA $3,250."
    fp = _floor_plan_prices(text)
    if fp and not sale_text and not any(a["value"] >= 20000 for a in amounts):
        beds_here = _beds(text)
        mine = {v for b, _bt, v, _st in fp if beds_here is not None and b == beds_here} or ({v for _b, _bt, v, _st in fp} if len({v for _b, _bt, v, _st in fp}) == 1 else set())
        if len(mine) == 1:
            return next(iter(mine))  # cycle 21: "Floor plan 2x1: $1,425", "Cozy 1x1 near campus, $1,150"
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
    m = re.search(r"(?<![\d.,$#/-])\b(\d{1,2},\d{3}|\d{3,5})[ \t]*(?:a[ \t]+month|per[ \t]+month|/[ \t]*mo(?:nth)?)\b", text, re.I)
    if m and 300 <= _num(m.group(1)) <= 30000 and not _SALE_WORDS.search(text):  # "1,299 a month": a rent written without a dollar sign
        return _num(m.group(1))
    m = re.search(r"(?<![\w.,$#/-])(\d(?:\.\d{1,2})?)[ \t]?k[ \t]*(?:a[ \t]+month|per[ \t]+month|/[ \t]*mo(?:nth)?|monthly)\b", text, re.I)
    if m and 0.3 <= float(m.group(1)) <= 30 and not _SALE_WORDS.search(text):  # cycle 18: "1.5k a month" is 1,500
        return float(m.group(1)) * 1000
    bare = _bare_labelled_rent(text)
    if bare is not None and not sale_text:
        return bare
    # cycle 16: a bare number is a rent only with an explicit period right after it (above). "HOUSE FOR RENT. 612 Mohawk St" and
    # "Rent. 4120 Indianola Ave" are street numbers, never a rent, so a number that only follows the word "rent" is not read.
    if _RENT_WORDS.search(text) and not sale_text:
        for a in amounts:
            if 300 <= a["value"] <= 20000:
                return a["value"]
    m = re.search(r"^[ \t*#]*no[ \t]+(?:pets?|smoking|dogs?|cats?|animals?)\b[^\n$]*?[-|][ \t]*\$\s?(\d{1,2},\d{3}|\d{3,5})(?:\.\d\d)?[ \t]*$", text, re.I | re.M)
    if m and not sale_text and 300 <= _num(m.group(1)) <= 20000:  # "NO PETS ALLOWED EXCEPT SERVICE ANIMALS - $2,100"
        return _num(m.group(1))
    return None


_NET_EFFECTIVE = re.compile(r"\(?\b(?:net[ \t-]+effective|effective|after[ \t-]+concessions?)(?:[ \t]+(?:rent|price|monthly(?:[ \t]+rent)?))?[ \t]*(?:is|of|:|=|about|around|approx\.?|~)?[ \t]*\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?\)?", re.I)
_NET_EFFECTIVE_AFTER = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?[ \t]*(?:/[ \t]*mo(?:nth)?[ \t]*)?(?:net[ \t-]+effective|effective(?:[ \t]+rent)?|after[ \t-]+concessions?)\b", re.I)
_AMT_G = r"\$\s?(\d{1,3}(?:,\d{3})+|\d{3,5})(?:\.\d\d)?"
_OLD_NEW = (
    ("arrow", re.compile(_AMT_G + r"[ \t]*(?:/mo)?[ \t]*(?:-+>|=+>|\u2192|\u279c|\u2794|>>|to|now|then)[ \t]*(?:(?:now|today|currently|new[ \t]+price|only)[ \t:]*)?" + _AMT_G + r"(?![\d,])", re.I)),
    ("was", re.compile(r"\b(?:was|previously|formerly|originally|old[ \t]+price|before)[ \t:]*" + _AMT_G + r"[ \t]*[,;:()\-\u2013\u2014]*[ \t]*(?:now|today|currently|new[ \t]+price|now[ \t]+only|(?:then[ \t]+)?(?:reduced|dropped|lowered|cut|marked[ \t]+down|down|lower|discounted)[ \t]+to|then)[ \t:]*" + _AMT_G, re.I)),
    ("reduced", re.compile(r"\b(?:reduced|dropped|lowered|cut|marked[ \t]+down|price[ \t]+drop(?:ped)?)[ \t]+from[ \t]+" + _AMT_G + r"[ \t]+to[ \t]+" + _AMT_G, re.I)),
    ("struck", re.compile(r"(?:~~|<s>|<del>)[ \t]*" + _AMT_G + r"[ \t]*(?:/mo)?[ \t]*(?:~~|</s>|</del>)[ \t,:-]*" + _AMT_G, re.I)),
)


_COND_AFTER = re.compile(r"^[ \t]*(?:/[ \t]*mo\w*[ \t]*)?(?:only[ \t]+)?(?:if|when|with|for[ \t]+(?:leases?|signing|new[ \t]+(?:residents?|tenants?)|those|anyone|students?|move-?ins?|(?:a|an)[ \t]+(?:\d|one|two|twelve))|by|before|through|until|on[ \t]+(?:a|an)[ \t]+\d|provided|as[ \t]+long|should[ \t]+you|\(?if)\b", re.I)
_PROMO_THEN = re.compile(_AMT_G + r"[ \t]*(?:/[ \t]*mo\w*|a[ \t]+month|per[ \t]+month|monthly)?[ \t]*(?:for[ \t]+(?:the[ \t]+)?|during[ \t]+(?:the[ \t]+)?)?(?:first|1st)?[ \t]*(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)[ \t-]*(?:months?|mos?)\b[ \t]*(?:only)?[ \t]*[,;:.\-]*[ \t]*(?:and[ \t]+)?(?:then|after(?:wards?)?|followed[ \t]+by|thereafter)[ \t:,]*(?:it(?:'s|[ \t]+is)[ \t]+|(?:goes|rises?|increases?|steps?[ \t]+up|resets?|reverts?)[ \t]+(?:up[ \t]+)?to[ \t]+|rent[ \t]+(?:is|of)[ \t]+)?" + _AMT_G + r"(?![\d,])", re.I)
_PROMO_THEN2 = re.compile(r"\b(?:first|1st)[ \t]+(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)[ \t-]*(?:months?|mos?)[ \t:,\-]*(?:is|are|at|only)?[ \t]*" + _AMT_G + r"[ \t]*(?:/[ \t]*mo\w*|a[ \t]+month|per[ \t]+month)?[ \t]*[,;:.\-]*[ \t]*(?:and[ \t]+)?(?:then|after(?:wards?)?|thereafter)[ \t:,]*(?:it(?:'s|[ \t]+is)[ \t]+|(?:goes|rises?|increases?)[ \t]+to[ \t]+)?" + _AMT_G + r"(?![\d,])", re.I)


def _promo_then_rent(text: str) -> tuple[float, str, float] | None:
    """Cycle 21: "$2,100 first 6 months then $2,350", "$2,100 for the first 6 months, then $2,350": a lower rent for a while and a higher ongoing rent.
    Returns (promo rent, months as written, ongoing rent). The ongoing rent is the one that lasts, so it is the one saved."""
    for m in _PROMO_THEN.finditer(text):
        a, mo, b = _num(m.group(1)), m.group(2), _num(m.group(3))
        if 300 <= a < b <= 30000:
            return a, mo, b
    for m in _PROMO_THEN2.finditer(text):
        mo, a, b = m.group(1), _num(m.group(2)), _num(m.group(3))
        if 300 <= a < b <= 30000:
            return a, mo, b
    return None


_NOW_IF = re.compile(r"\b(?:now|just|only|special|promo(?:tional)?(?:[ \t]+(?:rent|price))?|discounted|reduced[ \t]+to)[ \t:]*" + _AMT_G + r"(?![\d,])[ \t]*(?:/[ \t]*mo\w*|a[ \t]+month|per[ \t]+month)?[ \t]*"
                     r"(?P<cond>(?:if|when|with|for[ \t]+(?:leases?|signing|new[ \t]+(?:residents?|tenants?)|(?:a|an)[ \t]+(?:\d|one|two|twelve))|by|before|through|until|provided|as[ \t]+long)\b[^.\n;]{0,60})", re.I)


def _conditional_now_price(text: str, rent: float | None) -> tuple[float, str] | None:
    """Cycle 21: "$1,490/mo, now $1,450 if you sign by Dec 15": a lower price that depends on a condition. The listed rent stays the rent and the
    conditional figure is a note. Returns (the conditional amount, the condition as written)."""
    for m in _NOW_IF.finditer(text):
        v = _num(m.group(1))
        if 300 <= v <= 30000 and (rent is None or v != rent):
            return v, " ".join(m.group("cond").split()).rstrip(" ,:-")
    return None


_SPECIAL_AFTER = re.compile(r"^[ \t]*(?:/[ \t]*mo\w*[ \t]*|a[ \t]+month[ \t]*|per[ \t]+month[ \t]*|monthly[ \t]*)?(?:[-\u2013,:(][ \t]*)?(?:only[ \t]+)?"
                            r"(?P<cond>(?:if|when)[ \t]+(?:you[ \t]+|u[ \t]+|signed[ \t]+)?(?:sign|lease|move|apply|book|tour|rent|commit)\w*[^.\n;|]{0,50}|signing[ \t]+by[^.\n;|]{0,40}|sign[ \t]+by[^.\n;|]{0,40}|"
                            r"\(?(?:special(?![ \t]+assess)|promo\w*|limited[ \t-]+time)\b[^.\n;|]{0,40})", re.I)
_SPECIAL_BEFORE = re.compile(r"\b(?:specials?(?![ \t]+assess)|promo\w*|limited[ \t-]+time(?:[ \t]+offer)?)[ \t]*(?:price|rent|offer|rate)?[ \t]*[:=-]?[ \t]*(?:only[ \t]+)?$", re.I)
_SPECIAL_DEADLINE = re.compile(r"\b(?:by|before|through|until|ends?|expires?)[ \t]+((?:[A-Za-z]{3,9}\.?[ \t]+\d{1,2}(?:st|nd|rd|th)?(?:,?[ \t]+\d{4})?)|\d{1,2}/\d{1,2}(?:/\d{2,4})?)", re.I)
_REGULAR_AMT = re.compile(r"\b(?:regular(?:ly)?|normally|usually|reg\.|standard|otherwise|after(?:wards)?|then)[ \t:]*(?:rent|price|rate)?[ \t]*(?:is|of|at|returns?[ \t]+to)?[ \t]*\$[ \t]?(\d{1,2},\d{3}|\d{3,5})(?!\d|,\d)(?:\.\d\d)?", re.I)


def _special_price(text: str, rent: float | None) -> tuple[float, str, float | None] | None:
    """Cycle 26: "$3,600/MO $3,000 IF YOU SIGN BY DEC 1 (SPECIAL)", "Special: $2,950 if you sign by 12/1, regularly $3,100": a price tied to "if you sign by",
    "special", "promo" or "limited time" is a special, never the rent. Returns (the special amount, a short phrase naming it and its deadline, the regular rent when
    the listing states it and it is not the rent that was read, else None) or None."""
    if _SALE_WORDS.search(text) or (rent is not None and rent > 30000):
        return None
    for m in _AMOUNT.finditer(text):
        v = _num(m.group(1) + (m.group(2) or ""))
        if not 300 <= v <= 30000 or (rent is not None and v == rent):
            continue
        after = text[m.end():m.end() + 120]
        before = text[max(0, m.start() - 40):m.start()]
        if re.match(r"[ \t]*(?:off|discount|credit|bonus|rebate|gift|cash|back|reward)\b", after, re.I) or (rent is not None and v < 0.5 * rent):
            continue  # "Rent specials: $500 off first month" is a discount, not a price for the rent
        am = _SPECIAL_AFTER.match(after)
        if not am and not _SPECIAL_BEFORE.search(before):
            continue
        if re.search(r"\b(?:deposit|fees?|parking|garage|pet|utilit\w*|application|admin\w*|hoa)\b[^$]{0,20}$", before, re.I) and not _SPECIAL_BEFORE.search(before):
            continue
        scope = after[:am.end()] + after[am.end():am.end() + 40] if am else after[:60]
        scope = re.split(r"[.\n;|]", scope)[0]
        dm = _SPECIAL_DEADLINE.search(scope)
        reg = _REGULAR_AMT.search(text[m.end():m.end() + 160])
        reg_v = _num(reg.group(1)) if reg else None
        if dm:
            date_txt = dm.group(1).title() if re.match(r"[A-Za-z]", dm.group(1)) else dm.group(1)
            phrase = f"if you sign by {date_txt}" if re.search(r"\bsign|lease|move|apply|book", scope, re.I) else f"until {date_txt}"
        else:
            phrase = " ".join((am.group("cond") if am else "").split()).strip(" ,:-()!").lower()
            phrase = "" if re.fullmatch(r"special|promo\w*|limited[ \t-]+time", phrase) else phrase
        if rent is not None and v > rent and reg_v is None:
            continue  # a higher figure is not a special on the rent that was read
        if reg_v is not None and reg_v > v and (rent is None or rent == v):
            return v, phrase, reg_v
        if rent is not None and v < rent:
            return v, phrase, None
    return None


def _special_note(special: tuple[float, str, float | None], rent: float) -> str:  # the regular rent is in its field, so the note does not repeat it
    amt, phrase, _reg = special
    when = f" {phrase}" if phrase else ""
    return (f"The listing has a special: {_usd(amt)} a month{when}. The regular rent is saved. Ask if you can still get the special and what the rent is after it.")


def _rent_two_prices(text: str) -> tuple[float, float, str] | None:
    """A listing that gives two rents. Returns (the rent to save, the other figure, kind) or None.
    kind "net" = "Starting at $3,400 ... (net effective $3,138)": the quoted rent is saved and the net effective figure is a note.
    kind "drop" = "$3,350 -> $3,200 price drop", "was $X now $Y", "reduced from $X to $Y", "~~$X~~ $Y": the current (lower) price is
    saved and the old one is a note. Only a lower new figure counts as a drop (a higher one could be a rise or a different unit)."""
    if _SALE_WORDS.search(text):
        return None
    for kind, pat in _OLD_NEW:
        for m in pat.finditer(text):
            old, new = _num(m.group(1)), _num(m.group(2))
            if _COND_AFTER.match(text[m.end():m.end() + 60]):
                continue  # cycle 21: "$1,490, now $1,450 if you sign by Dec 15" is a condition, not the new rent
            if 300 <= new < old <= 30000:
                return new, old, kind
    m = _NET_EFFECTIVE.search(text) or _NET_EFFECTIVE_AFTER.search(text)
    if m:
        net = _num(m.group(1))
        rest = text[:m.start()] + " " * (m.end() - m.start()) + text[m.end():]
        base = _price(rest)
        if base is None:
            base = _bare_starting_rent(rest)
        if base is not None and base > net and 300 <= base <= 30000:
            return base, net, "net"
    return None


def _rent_two_prices_note(price: float, other: float, kind: str) -> str:
    if kind == "net":
        return (f"The listing gives ${price:,.0f} a month as the rent and a net effective rent of ${other:,.0f}. The net effective figure only spreads a free-rent deal over the lease, "
                f"so ${price:,.0f} is saved as the rent. Ask what you pay each month.")
    return f"The listing says the rent dropped from ${other:,.0f} to ${price:,.0f}. The current ${price:,.0f} is saved as the rent and the old ${other:,.0f} is not used."


_LO_AMT = r"\$[ \t]?(\d{1,2},\d{3}|\d{3,5})(?!\d|,\d)(?:\.\d\d)?"
_LO_LEN = r"(\d{1,2})[ \t-]?(?:months?|mos?)\b"
_LO_RENT_FIRST = re.compile(_LO_AMT + r"[ \t]*(?:/[ \t]*mo\w*|a[ \t]+month|per[ \t]+month|monthly)?[ \t]*(?:\(?[ \t]*(?:for|with|on)[ \t]+(?:a[ \t]+|an[ \t]+)?|\([ \t]*)" + _LO_LEN + r"(?![ \t]*(?:free|off|discount))", re.I)
_LO_LEN_FIRST = re.compile(r"(?<![\d,$/-])" + _LO_LEN + r"[ \t]*(?:leases?|terms?|contracts?)?[ \t]*(?:(?:is[ \t]+)?(?:also[ \t]+)?(?:available|offered)[ \t]+)?(?:rent|price)?[ \t]*(?:is|at|for|:|=|-|–|—)?[ \t]*" + _LO_AMT, re.I)
_LO_SHOWN = re.compile(r"\b(?:rent|price)[ \t]+(?:shown|listed|quoted|above|advertised|here)?[ \t]*(?:is|are)?[ \t]*(?:for|based[ \t]+on)[ \t]+(?:a[ \t]+|an[ \t]+)?" + _LO_LEN + r"(?![ \t]*(?:free|off|discount))", re.I)
_LO_FEEDY = re.compile(r"\b(?:deposit|fees?|application|admin\w*|pets?|parking|garage|utilit\w*|hoa|key|cleaning|move[- ]?in)\b", re.I)


def _lease_rent_options(text: str, raw: bool = False) -> list[tuple[float, int, int]] | None:
    """Cycle 23: the rent written for each lease length ("$1,490 for 13 month lease; 12 month lease $1,540", "12 mo: $1,540 / 13 mo: $1,490",
    "$1,540 (12-month) or $1,490 (13-month)", "Rent shown is for a 13 month lease; 12 month lease $1,540" with the shown rent in the title).
    Returns [(rent, lease months, position)] in the order written, or None unless two different lengths are each tied to a rent."""
    if _real_sale_words(text):
        return None
    found: dict[int, tuple[float, int, int, int]] = {}  # position of the match -> (rent, months, position, end)

    def add(rent: float, months: int, a: int, b: int) -> None:
        if not (300 <= rent <= 30000 and 3 <= months <= 60):
            return
        if _FEE_AFTER_STRICT.match(text[b:b + 30]) or _LO_FEEDY.search(text[max(0, a - 14):a]):
            return
        found.setdefault(a, (rent, months, a, b))

    for m in _LO_RENT_FIRST.finditer(text):
        add(_num(m.group(1)), int(m.group(2)), m.start(), m.end())
    for m in _LO_LEN_FIRST.finditer(text):
        add(_num(m.group(2)), int(m.group(1)), m.start(), m.end())
    opts = sorted(found.values(), key=lambda o: o[2])
    if raw:
        return [(o[0], o[1], o[2]) for o in opts]
    if len(opts) == 1:
        sm = _LO_SHOWN.search(text)
        if sm and int(sm.group(1)) != opts[0][1] and 3 <= int(sm.group(1)) <= 60:
            blank = text[:opts[0][2]] + " " * (opts[0][3] - opts[0][2]) + text[opts[0][3]:]
            shown = _price(blank)
            if shown is not None and shown != opts[0][0]:
                return [(shown, int(sm.group(1)), -1), (opts[0][0], opts[0][1], opts[0][2])]
        return None
    if len(opts) >= 2 and len({o[1] for o in opts}) == len(opts):
        return [(o[0], o[1], o[2]) for o in opts]
    return None


def _lease_rent_options_note(opts: list[tuple[float, int, int]], first_saved: bool = True) -> str:
    """The rents the listing gives for each lease length. Cycle 24: the note never names the rent that is saved, because the rent can be
    changed later (update_place) and the note would then be wrong: it lists the options as the listing gave them."""
    listed = "; ".join(f"{_usd(r)} for {mo} months" for r, mo, _p in opts)
    if first_saved:
        return (f"The listing gives a different rent for each lease length: {listed}. The 12 month one, or the one closest to 12 months, is used for the rent and the lease length, "
                "and each of the others is another lease length option, so it is not added to the cost. Ask which lease length you would get.")
    return (f"The listing gives a different rent for each lease length: {listed}. These are lease length options, and each one is another lease length option, "
            "so it is not added to the cost. Ask which lease length you would get.")


def _lease_plan_lowest(text: str, opts: list[tuple[float, int, int]]) -> tuple[float, str] | None:
    """Cycle 24: "2BR Standard $1,380 | 2BR Deluxe $1,520 (12 mo) | 2BR Deluxe $1,480 (15 mo)": the listing gives lease lengths for some plans and a
    cheaper plan with the same bedroom count has none. The lowest plan for the listing's own bedroom count is the rent. Returns (rent, note) or None.
    The note lists the plans and never names the rent that is saved."""
    plans = _plan_line_prices(text, None)
    if not plans:
        return None
    own = _beds(_text_without_plans(text, None))
    kinds = {b for b, _v in plans}
    want = own if own is not None else (next(iter(kinds)) if len(kinds) == 1 else None)
    if want is None:
        return None
    mine = [v for b, v in plans if b == want]
    if not mine or min(mine) >= min(o[0] for o in opts):
        return None
    name = "studio" if want == 0 else f"{want:g} bedroom"
    return min(mine), (f"The listing gives {name} plans at {'; '.join(dict.fromkeys(_usd(v) for v in mine))}. "
                       f"The lowest {name} plan was used for the rent and it names no lease length, so the lease length is left empty. Ask which plan you want.")


def _lease_extra_option(text: str, price: float | None) -> tuple[float, int] | None:
    """Cycle 24: "Rent: $3,200 per month. Lease: 12 months (or 15 months at $3,100)": a rent for another lease length next to the rent the
    listing gives. It is an option, never an amount that is "not counted". Returns (rent, lease months) or None."""
    if price is None or _real_sale_words(text):
        return None
    opts = _lease_rent_options(text, raw=True) or []
    if len(opts) != 1 or opts[0][0] == price:
        return None
    a = opts[0][2]
    seg = text[max(text.rfind("\n", 0, a) + 1, text.rfind(";", 0, a) + 1, text.rfind("|", 0, a) + 1, a - 45):a]
    prev = list(re.finditer(r"\$[ \t]?\d[\d,]*(?:\.\d\d)?", seg))
    if prev:
        seg = seg[prev[-1].end():]  # "2.5 bath, 1,380 sqft. $2,360/mo, or $2,310 with 14-month lease": only what sits between the two rents
    if re.search(r"\b(?:sq\.?[ \t]?ft|sqft|sf)\b|\b\d[ \t]?(?:ba|bath)\b", seg, re.I):
        return None  # "3BR/2BA 1,250 sf $2,380 (12 month lease)" is another floor plan, not another lease length of this one
    return opts[0][0], opts[0][1]


def _blank_lease_option(text: str, months: int, rent: float) -> str:
    """The text with the one "$rent ... N months" lease option blanked (used to read the lease length of the rent that is saved)."""
    for rx in (_LO_RENT_FIRST, _LO_LEN_FIRST):
        for m in rx.finditer(text):
            r, mo = (_num(m.group(1)), int(m.group(2))) if rx is _LO_RENT_FIRST else (_num(m.group(2)), int(m.group(1)))
            if r == rent and mo == months:
                return text[:m.start()] + " " * (m.end() - m.start()) + text[m.end():]
    return text


def lease_months_only_from_plans(listing_text: str, lease_months: Any) -> bool:
    """Cycle 25 (correction path): True when the saved lease length is the length of one of the rent-for-each-lease-length options in the listing and
    nothing else in the listing states that length. A rent corrected by hand makes that length unknown ("$1,100 for a 10-month lease" stops being the
    lease once the rent is $1,260)."""
    try:
        months = int(float(lease_months))
    except (TypeError, ValueError):
        return False
    text = str(listing_text or "")
    if not text.strip() or _real_sale_words(text):
        return False
    opts = _lease_rent_options(text, raw=True) or []
    if not any(o[1] == months for o in opts):
        return False
    rest = text
    for rent, mo, _pos in opts:
        rest = _blank_lease_option(rest, mo, rent)
    return _lease_months(rest) != months


def _lease_extra_option_note(rent: float, months: int) -> str:
    return (f"The listing also gives {_usd(rent)} for a {months} month lease. That is another lease length option, so it is not added to the cost. "
            "Ask which lease length you would get.")


_PLAN_BEDS = re.compile(r"(?<![\w$#/.,-])(?:(\d)[ \t]?(?:br|bd|bds|bed|beds|bedroom|bedrooms)\b|(studio|efficiency)\b)", re.I)


def _text_without_plans(text: str, skip: float | None) -> str:
    """The text with each floor-plan piece blanked, so a bedroom count that only appears in the plan list is not read as the listing's own."""
    out, pos = text, 0
    for seg in re.split(r"([\n;|])", text):
        if seg not in "\n;|" and _plan_line_prices(seg, skip):
            out = out[:pos] + " " * len(seg) + out[pos + len(seg):]
        pos += len(seg)
    return out


def _plan_line_prices(text: str, skip: float | None) -> list[tuple[float, float]]:
    """Cycle 23: prices per floor plan, one plan per line or per ";" item ("A1 1BR/1BA 640 sf $1,395; A2 1BR/1BA 702 sf $1,445"): (bedrooms, rent).
    A piece needs one bedroom count and one amount, no fee word, and no "starting at"."""
    out: list[tuple[float, float]] = []
    for seg in re.split(r"[\n;|]", text):
        if re.search(r"\b(?:starting|starts?|from)\b|" + _LO_FEEDY.pattern, seg, re.I):
            continue
        amts = [_num(m.group(1)) for m in re.finditer(_LO_AMT, seg)]
        beds = {0.0 if m.group(2) else float(m.group(1)) for m in _PLAN_BEDS.finditer(seg)}
        if len(amts) != 1 or len(beds) != 1 or not 300 <= amts[0] <= 30000 or amts[0] == skip:
            continue
        if re.search(_LO_AMT + r"[ \t]*(?:/[ \t]*(?:bed|room)|per[ \t]+(?:bed|room|person))", seg, re.I):
            continue
        out.append((next(iter(beds)), amts[0]))
    return out


_SAME_PLAN_NAME = re.compile(r"\b(?:plan|floor[ \t]*plan|unit|type|model)[ \t]+[A-Za-z]?\d?[A-Za-z]?\b", re.I)


def _same_bed_plans(text: str, beds: float | None) -> list[tuple[str, float]]:
    """Cycle 25: "Plan A 3BR/2BA 1,180 sqft $3,390. Plan B 3BR/2.5BA $3,640." Returns (plan name, rent) for each named plan piece (one per sentence,
    line, pipe or semicolon item) with the listing's own bedroom count and one rent-sized amount. A piece with a fee word or a per-bed amount is no plan."""
    out: list[tuple[str, float]] = []
    if beds is None:
        return out
    for seg in re.split(r"[\n;|]|(?<=[A-Za-z0-9)])\.[ \t]+(?=[A-Z0-9])|,[ \t]+(?=(?:\d[ \t]?(?:br|bd|bed)\w*[ \t]+)?(?:plan|floor[ \t]*plan)\b)", text, flags=re.I):
        nm = _SAME_PLAN_NAME.search(seg)
        if not nm or re.search(r"\b(?:starting|starts?|from)\b|" + _LO_FEEDY.pattern, seg, re.I):
            continue
        amts = [_num(m.group(1)) for m in re.finditer(_LO_AMT, seg)]
        pb = {0.0 if m.group(2) else float(m.group(1)) for m in _PLAN_BEDS.finditer(seg)}
        if len(amts) != 1 or pb != {beds} or not 300 <= amts[0] <= 30000:
            continue
        if re.search(_LO_AMT + r"[ \t]*(?:/[ \t]*(?:bed|room)|per[ \t]+(?:bed|room|person))", seg, re.I):
            continue
        out.append((" ".join(nm.group(0).split()).title().replace("Floor Plan", "Floor plan"), amts[0]))
    return out


def _starting_plan_pick(text: str, price: float, beds: float | None) -> tuple[float | None, str] | None:
    """Cycle 23: the rent read is a "starting at" price and the listing also gives a price for each floor plan. Returns (rent to save or None, note), or
    None when this does not apply. The lowest price of a plan with the listing's bedroom count is saved, never the lower "starting at" price; when the
    bedroom count cannot be matched to one kind of plan the rent is left empty."""
    dash = _dash_title_price(text)
    if not (_starting_at(text, price) or (dash and dash[1] and dash[0] == price)):
        return None
    plans = _plan_line_prices(text, price)
    if not plans:
        return None

    def name(b: float) -> str:
        return "studio" if b == 0 else f"{b:g} bedroom"

    def listed(items: list[tuple[float, float]]) -> str:
        return "; ".join(dict.fromkeys(f"{name(b)} ${v:,.0f}" for b, v in items))

    kinds = {b for b, _v in plans}
    want = beds if beds is not None else (next(iter(kinds)) if len(kinds) == 1 else None)
    if want is None:
        return None, (f"The listing says \"starting at\" ${price:,.0f} and gives prices by floor plan ({listed(plans)}), and I could not tell which size this place is, "
                      "so the rent is left empty. Ask which plan you want and what it costs.")
    mine = [v for b, v in plans if b == want]
    if not mine or min(mine) < price:
        return None
    best = min(mine)
    rest = [(b, v) for b, v in plans if not (b == want and v == best)]
    other = f" The other plans are {listed(rest)}." if rest else ""
    return best, (f"The listing says \"starting at\" ${price:,.0f}, which is the lowest price of any size, and also gives prices by floor plan. "
                  f"The rent saved is the lowest {name(want)} plan, ${best:,.0f}, not the \"starting at\" price.{other} Ask which plan you want.")


_STREET_WORD = re.compile(r"(?:st|street|ave|avenue|rd|road|dr|drive|blvd|boulevard|ln|lane|ct|court|pl|place|way|cir|circle|pkwy|parkway|hwy|highway|terrace|ter|trail)\b\.?", re.I)


def _bare_labelled_rent(text: str) -> float | None:
    """Cycle 18: "Rent 1,480 plus parking", "Rent: 1480", "monthly rent 1,250": a rent written without a dollar sign right after the word
    rent. A number followed by a street word or a capitalised word is a street number ("For rent 612 Mohawk St"), never a rent.
    Cycle 19: a figure followed by "per bedroom" or "per person" is one share, never the whole rent, and a figure labelled rent after
    "No:", "sorry" or "actually" replaces an earlier one ("Rent 1,480 per bedroom? No: Pilsen 3bd/2ba rent 3,240")."""
    found: list[tuple[float, bool]] = []
    for m in re.finditer(r"(?<![\w$])(?:monthly[ \t]+)?rent(?:[ \t]*(?:is|of|:|=|-))?[ \t]*(\d{1,2},\d{3}|\d{3,5})(?![\d,.]*\d)(?:\.\d\d)?", text, re.I):
        value = _num(m.group(1))
        if not 300 <= value <= 30000:
            continue
        after = text[m.end():m.end() + 40]
        if re.match(r"[ \t]*(?:sq|sf|ft|bed|br|bd|bath)", after, re.I):
            continue
        if re.match(r"[ \t]*(?:/|per|a|each)[ \t]*(?:bed(?:room)?|br|bd|room|person|tenant|resident|student)s?\b", after, re.I):
            continue  # one share of the rent, not the whole place
        if re.match(r"[ \t]+\d", after):
            continue  # "FOR RENT 4120 4120 Indianola St": a number that another number follows is part of an address
        nxt = re.match(r"[ \t]+([A-Za-z]+)(?:[ \t]+([A-Za-z]+))?", after)
        if nxt:
            w1, w2 = nxt.group(1), nxt.group(2) or ""
            if w1[0].isupper() or _STREET_WORD.fullmatch(w1) or (w2 and _STREET_WORD.fullmatch(w2)):
                continue
        before = text[max(0, m.start() - 70):m.start()]
        fixed = bool(re.search(r"(?:\?[ \t]*no\b|\bno[ \t,]+(?:sorry|wait|actually)\b|\b(?:sorry|actually|oops|correction)\b)[^.\n]{0,50}$", before, re.I))
        found.append((value, fixed))
    for value, fixed in found:
        if fixed:
            return value
    return found[0][0] if found else None


def _bare_per_room_rent(text: str) -> float | None:
    """Cycle 19: "Rent 1,480 per bedroom" with no dollar sign: the one share a listing gives when no whole rent is read."""
    m = re.search(r"(?<![\w$])(?:monthly[ \t]+)?rent(?:[ \t]*(?:is|of|:|=|-))?[ \t]*(\d{1,2},\d{3}|\d{3,5})(?![\d,.]*\d)(?:\.\d\d)?[ \t]*(?:/|per|a|each)[ \t]*(?:bed(?:room)?|br|bd|room|person|tenant|resident|student)s?\b", text, re.I)
    return _num(m.group(1)) if m and 200 <= _num(m.group(1)) <= 30000 else None


_PER_ROOM_RENT = re.compile(r"(?<![\d.,#/-])(\$?)(\d{1,2},\d{3}|\d{3,5})[ \t]*(?:/[ \t]*mo(?:nth)?\b|a[ \t]+month|per[ \t]+month|monthly)?[ \t]*(?:/|per|a|each)[ \t]*(?:bed(?:room)?|room|person|tenant|resident|student)s?\b", re.I)
_UNIT_RENT = re.compile(r"\b(total|unit|whole[- ]unit|entire[- ]unit|combined|full)[ \t]+(?:monthly[ \t]+)?(?:rent|price)\b[^\d$\n]{0,15}?\$?[ \t]?(\d{1,2},\d{3}|\d{3,5})(?![\d,])", re.I)


def _two_rents(text: str) -> tuple[str, str, float, str] | None:
    """"1,299 a month per bedroom... total rent 2,975": a per-room rent and a unit or total rent in the same listing. Returns
    (per-room text, unit text, unit value, "unit" or "total") or None. The unit or total figure is the rent of the place."""
    pm = _PER_ROOM_RENT.search(text)
    if not pm:
        return None
    per = _num(pm.group(2))
    for um in _UNIT_RENT.finditer(text):
        unit = _num(um.group(2))
        if unit > per and 300 <= unit <= 30000 and 200 <= per <= 30000:
            kind = "total" if um.group(1).lower() in ("total", "combined", "full") else "unit"
            return f"${per:,.0f}", f"${unit:,.0f}", unit, kind
    return None


_OTHER_UNIT_RENT = re.compile(r"(?<![\w$])(studio|\d{1,2}[ \t-]*(?:br|bd|bds|beds?|bedrooms?))\b[ \t:,\-]*(?:from[ \t]+|at[ \t]+)?\$\s?(\d{1,2},\d{3}|\d{3,5})(?![\d,])(?![ \t]*(?:/[ \t]*(?:bed|room)|per[ \t]+(?:bed|room)))", re.I)


def _per_room_split_note(text: str, price: float | None) -> str:
    """Cycle 17: "$1,425 ($712 per room)", "$3,225 per month; $1,075 per room", "2 BR $1,900 total ($950 per room) / 1 BR $1,325". The
    rent read is the whole place. A per-room figure below it is a share of it, so it is named in one plain note, and a
    separate unit at another price ("1 BR $1,325") is named as a different unit. "" when there is no such split."""
    if price is None:
        return ""
    pm = None
    for m in _PER_ROOM_RENT.finditer(text):
        v = _num(m.group(2))
        if 200 <= v < price:
            pm = m
            break
    if not pm:
        return ""
    per = _num(pm.group(2))
    rooms = round(price / per)
    if rooms >= 2 and abs(per * rooms - price) <= max(5.0, 0.01 * price):
        note = f"The listing gives ${price:,.0f} a month for the whole place and ${per:,.0f} per room. The per-room figure is part of the total, so ${price:,.0f} is saved as the rent."
    else:  # the two figures do not add up (a self-correcting listing): say so, claim nothing
        note = (f"The listing gives ${price:,.0f} a month and also ${per:,.0f} per room, which do not add up to the same rent. "
                f"${price:,.0f} is saved as the rent. Ask what the whole place costs and what each person pays.")
    others = []
    for om in _OTHER_UNIT_RENT.finditer(text):
        v = _num(om.group(2))
        label = " ".join(om.group(1).upper().split())
        if v != price and v != per and 200 <= v <= 30000 and not any(label == o[0] for o in others):
            others.append((label, v))
    if others:
        note += " " + " ".join(f"A separate {l} option at ${v:,.0f} is a different unit, so it is not used as the rent." for l, v in others[:2])
    return note


_DISCOUNTS = (
    re.compile(r"\$\s?\d[\d,]*(?:\.\d\d)?[ \t]+off\b[^.\n;!]{0,40}?\b(?:first|1st|last|month|rent|move[- ]?in|lease|signing)[^.\n;!]{0,25}", re.I),
    re.compile(r"\b\d{1,2}[ \t]*%[ \t]+off\b[^.\n;!]{0,40}?\b(?:first|1st|last|month|rent|move[- ]?in|lease|signing)[^.\n;!]{0,25}", re.I),
    re.compile(r"\b(?:first|1st|last)[ \t]+month(?:'s)?(?:[ \t]+rent)?[ \t]+(?:is[ \t]+)?(?:half|\d{1,2}[ \t]*%)[ \t-]*off\b[^.\n;!]{0,40}", re.I),
    re.compile(r"\b(?:half|\d{1,2}[ \t]*%)[ \t-]*off[ \t]+(?:the[ \t]+)?(?:first|1st|last)[ \t]+month[^.\n;!]{0,40}", re.I),
)
_REDUCED_FROM = re.compile(r"\b(?:reduced|dropped|lowered|cut|marked down|price drop(?:ped)?)[ \t]+(?:to[ \t]+\$\s?\d[\d,]*(?:\.\d\d)?[ \t]+)?from[ \t]+\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?", re.I)


_WAS_PRICE = re.compile(r"\b(?:was|previously|formerly|originally)[ \t:]+\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?", re.I)


def _discount_notes(text: str, price: float | None, buying: bool = False) -> list[str]:
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
            notes.append(f"The listing says the price was cut from {old}. The old price is not used, only the current {'price' if buying else 'rent'} that was read.")
        else:
            notes.append(f"The listing says the price was cut from {old}. That is the old price, so it is not used as the {'asking price' if buying else 'rent'}. Ask what the {'price' if buying else 'rent'} is now.")
    return notes


def _price_notes(text: str, price: float | None = None, buying: bool = False) -> list[str]:
    """Plain notes about a rent that depends on something: "Reduced to $3,250 with 12 month lease", "1 month free". They never change the price."""
    notes: list[str] = _discount_notes(text, price, buying)
    for a in _amounts(text):
        if a.get("conditional"):
            months = _LEASE_CONDITION.match(text[a["end"]:text.find("\n", a["end"]) if text.find("\n", a["end"]) >= 0 else len(text)])
            if months:
                notes.append(f"The listing says the rent drops to ${a['value']:,.0f} with a {months.group(1)} month lease. Ask if that applies to you.")
    m = re.search(r"(?<![\w/.])(?:(first|last|one|two|three|half|\d{1,2}/\d{1,2}|\d{1,2})(?:st|nd|rd|th)?[ \t-]+months?(?:'s)?[ \t]+(?:of[ \t]+rent[ \t]+)?(?:rent[ \t]+)?free|(?:up to[ \t]+)?(?:one|two|three|\d{1,2})[ \t]+weeks?[ \t]+free|free[ \t]+(?:first|1st|one|two|\d{1,2})[ \t-]*months?)\b", text, re.I)
    if m:
        notes.append(f"The listing offers a rent concession (\"{' '.join(m.group(0).split())}\"). It is a one-time deal, so it is not taken off the rent. Ask what you have to do to get it.")
    fm = re.search(r"\bfree[ \t]+for[ \t]+(?:the[ \t]+)?(?:first|1st)[ \t]+(?:\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)[ \t]+(?:months?|weeks?)\b", text, re.I)
    if fm:  # cycle 22: "garage $140 per month, free for first 6 months": a promo that ends, named so the full price is not forgotten
        bounds = [b.end() for b in re.finditer(r"\.\s|\n|\||;", text[:fm.start()])]
        line = " ".join(text[(bounds[-1] if bounds else 0):fm.end()].split())[-90:]
        notes.append(f"The listing says \"{line}\". The free months are a one-time deal and are not taken off any monthly figure. Ask what you pay after the free months end.")
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


_STARTING_AT = re.compile(r"(?<![\w$])(?:starting|starts|beginning|begins)[ \t]+(?:at|from|around)[ \t]+(?:only[ \t]+)?\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?|"
                          r"(?<![\w$])as[ \t]+low[ \t]+as[ \t]+\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?|"
                          r"(?<!reduced )(?<!dropped )(?<!lowered )(?<!cut )(?<!price )(?<!was )(?<!down )(?<!\w)from[ \t]+\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?(?![\d,])(?![ \t]*(?:-|\u2013|to)[ \t]*\$)", re.I)


def _starting_at(text: str, price: float | None) -> bool:
    """True when the rent that was read is a "starting at $X" or "from $X" price, so it is the lowest unit and not the rent of the unit wanted."""
    if price is None:
        return False
    return any(_num(g) == price for m in _STARTING_AT.finditer(text) for g in m.groups() if g)


def _bare_starting_rent(text: str) -> float | None:
    """"Starting at $3,250" with no other rent in the text: the lowest unit's rent. Small amounts and fee lines are not rents."""
    for m in _STARTING_AT.finditer(text):
        if m.group(0).lower().startswith("from"):
            continue
        g = next((x for x in m.groups() if x), None)
        value = _num(g) if g else 0
        if not 500 <= value <= 30000:
            continue
        before = text[max(0, m.start() - 40):m.start()]
        after = text[m.end():m.end() + 30]
        if _FEE_AFTER_STRICT.match(after) or _FEE_AFTER_MONTHLY.match(after) or re.search(_FEE, before[-25:], re.I):
            continue
        if re.match(r"[ \t]*(?:/[ \t]*)?(?:sq|sf|ft|acres?)", after, re.I):
            continue
        return value
    return None


def _range_line(text: str, rng: tuple[float, float]) -> str:
    """The line (and the one above it) that holds the written range "$1,475 - $1,525", to read the words around it."""
    m = re.search(r"\$\s?" + re.escape(f"{rng[0]:,.0f}") + r"(?:\.\d\d)?\s*\+?\s*(?:-|\u2013|to)\s*\$\s?" + re.escape(f"{rng[1]:,.0f}"), text)
    if not m:
        return ""
    a = text.rfind("\n", 0, max(0, text.rfind("\n", 0, m.start()))) + 1
    b = text.find("\n", m.end())
    return text[a:len(text) if b < 0 else b]


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
    re.compile(r"\bmove[- ]?in[ \t]+(?:cost|costs|total|price|charges?|money|amount)(?:[ \t]+(?:is|are|of))?[ \t]*[:=\-]?[ \t]*(?:about |around |approx\.? |~)?\$?[ \t]*(\d{1,3}(?:,\d{3})+|\d{3,5})(?:\.\d\d)?\b(?![ \t]*(?:/|per|a)[ \t]*(?:mo|month))", re.I),
    re.compile(r"\$[ \t]*(\d{1,3}(?:,\d{3})+|\d{3,5})(?:\.\d\d)?[ \t]+(?:total[ \t]+)?(?:to[ \t]+move[- ]?in|due[ \t]+(?:at|before)[ \t]+(?:lease[ \t]+)?(?:signing|move[- ]?in)|move[- ]?in[ \t]+total)\b", re.I),
)


def _move_in_total_notes(text: str) -> list[str]:
    """"Move-in cost 2200 total", "$2,100 total to move in": the all-in cash to get in. It is not the rent and it is not split into
    deposit and fees, so it only gets a note."""
    for pat in _MOVE_IN_TOTAL:
        m = pat.search(text)
        if m and pat is _MOVE_IN_TOTAL[1] and re.search(r"\b(?:fees?|deposits?|dep|charges?|cost|admin\w*|application|lease\w*|processing|amenity|key|cleaning|security|sec|pet)\.?[ \t:\-=]*$", text[max(0, m.start() - 20):m.start()], re.I):
            continue  # "Cleaning fee $200 due at move-in": that is one fee, not the total to move in
        if m:
            return [f"The listing says it costs {_usd(_num(m.group(1)))} in total to move in. That is not the monthly rent and it is not split into deposit and fees, "
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
    m = re.search(r"\bcredit[ \t]+(?:check|report)(?:[ \t]+fees?)?[ \t:\-=]*\$\s?(\d{1,4}(?:\.\d\d)?)(?![\d,])[ \t]*(?:/|per|each|for[ \t]+(?:each|every))[ \t]*(adult|applicant|person|occupant|tenant|resident|roommate)s?\b", text, re.I) \
        or re.search(r"\$\s?(\d{1,4}(?:\.\d\d)?)[ \t]*(?:credit[ \t]+(?:check|report))(?:[ \t]+fees?)?[ \t]*(?:/|per|each|for[ \t]+(?:each|every))[ \t]*(adult|applicant|person|occupant|tenant|resident|roommate)s?\b", text, re.I) \
        or re.search(r"\bcredit[ \t]+(?:check|report)(?:[ \t]+fees?)?[ \t:\-=]*\$\s?(\d{1,4}(?:\.\d\d)?)(?![\d,])[ \t]*,?[ \t]*(?:charged[ \t]+)?(?:to[ \t]+)?(?:each|every)[ \t]+(adult|applicant|person|occupant|tenant|resident|roommate)\b", text, re.I)
    return (float(m.group(1)), m.group(2).lower()) if m else None


def _credit_in_app_fee(facts: list[str], out: dict[str, Any], cf: float, text: str = "") -> bool:
    """Cycle 24: the credit check was already added into the saved application fee (a note says "the two together"),
    so a second note asking whether they are two fees would repeat a value that is already counted."""
    if any(("both charged to each adult" in f or "the two together" in f) and _usd(cf) in f for f in facts):
        return True
    app = out.get("application_fee")
    if text and isinstance(app, (int, float)) and not isinstance(app, bool):
        # "Application fee $80 per adult (includes the $30 credit check)": the credit check sits in the same sentence as the fee that holds it
        for sent in re.split(r"\n|;|(?<!\d)[.!?](?=\s|$)", text):
            if re.search(r"\bcredit[ \t]+(?:check|report)", sent, re.I) and re.search(r"\b(?:includ\w*|incl\.?|inside|within|part[ \t]+of|covers?|of[ \t]+which|built[ \t]+in)\b", sent, re.I) \
                    and re.search(r"\$\s?" + re.escape(f"{app:g}").replace(r"\.", r"\.") + r"(?:\.00?)?(?![\d,])", sent):
                facts.append(f"The {_usd(cf)} credit check is part of the {_usd(app)} application fee, so it is counted once, inside the fee.")
                return True
    return False


def _credit_check_plain(text: str) -> float | None:
    """"Credit check $25" with no word about who pays it: the application fee. None when the per-person form applies or nothing is said."""
    if _credit_check_fee(text):
        return None
    m = re.search(r"\bcredit[ \t]+(?:check|report)(?:[ \t]+fees?)?[ \t:\-=]*\$\s?(\d{1,4}(?:\.\d\d)?)(?![\d,])(?![ \t]*(?:/|per|each|every|a[ \t]+(?:month|mo)|monthly))", text, re.I) \
        or re.search(r"(?<![\d,])\$\s?(\d{1,4}(?:\.\d\d)?)[ \t]+(?:for[ \t]+(?:a[ \t]+)?)?credit[ \t]+(?:check|report)(?:[ \t]+fees?)?\b(?![ \t]*(?:/|per|each|every))", text, re.I)
    return float(m.group(1)) if m else None


_RENTERS = r"(?:renter'?s?|tenant'?s?|renters)[ \t]+insurance"


def _renters_insurance_yearly(text: str) -> tuple[float, float] | None:
    """(yearly amount, monthly amount) for a required renter's insurance with a price written per month or per year:
    "Renter's insurance required $15/mo" -> (180, 15). The insurance field is a yearly amount. A price with no period, or an
    optional insurance, gives None (it stays a note)."""
    if not _renters_insurance_required(text):
        return None
    per = r"(?:(/[ \t]*(?:mo|month)\b|per[ \t]+month|a[ \t]+month|monthly|each[ \t]+month)|(/[ \t]*(?:yr|year)\b|per[ \t]+year|a[ \t]+year|yearly|annually|annual\b))"
    m = re.search(r"\b" + _RENTERS + r"\b[^.\n;$]{0,40}\$[ \t]?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?[ \t]*" + per, text, re.I)
    if not m:
        return None
    value = _num(m.group(1))
    if m.group(2):
        monthly, yearly = value, value * 12
    else:
        monthly, yearly = value / 12, value
    return (round(yearly, 2), round(monthly, 2)) if 0 < yearly <= 5000 else None


def _renters_insurance_required(text: str) -> bool:
    return bool(re.search(r"\b" + _RENTERS + r"\b[^.\n;]{0,30}\b(?:required|mandatory|is[ \t]+a[ \t]+must|needed|must[ \t]+(?:be|have))\b|\b(?:requires?|required|must[ \t]+(?:have|carry|show))\b[^.\n;]{0,20}\b" + _RENTERS + r"\b", text, re.I)) \
        and not re.search(r"\b" + _RENTERS + r"\b[^.\n;]{0,20}\b(?:not|isn'?t|optional)\b", text, re.I)


def _renters_insurance_note(text: str) -> list[str]:
    """"Renter's insurance required": with a price per month or year it is counted (the insurance field), and the note says so.
    With no usable price it is a note only."""
    if not _renters_insurance_required(text):
        return []
    got = _renters_insurance_yearly(text)
    if got:
        return [f"Renter's insurance is required and counted in the monthly cost (${got[1]:,.0f} a month, saved as ${got[0]:,.0f} a year). Ask what coverage you need and whether a plan you already have is accepted."]
    return ["The listing says renter's insurance is required. No cost is counted for it. Ask what coverage you need and what it costs."]


def _money_after(text: str, label: str, *, lo: float = 0, hi: float = 1_000_000, gap: int = 28, skip_before: str = "", verbs: bool = False) -> list[float]:
    """Amounts written as "<label> ... $N" or "$N <label>" (labels are regex text). Several matches are all returned.
    Cycle 25: verbs=True also reads "<label> is $N", "<label> of $N", "<label> will be $N", "<label> equals $N" anywhere in a sentence."""
    found: list[float] = []
    mid = r"(?:[ \t:\-=(]|\b(?:is|are|of|equals?|will[ \t]+be|comes?[ \t]+to|totals?|set[ \t]+at|at|due|payable|required|upon|before|paid|signing|move[- ]?in|lease)\b)" if verbs else r"[ \t:\-=(]"
    for m in re.finditer(r"(?:" + label + r")" + mid + r"{0,%d}?(\n\s*)?\$\s?(\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)(?!\d)" % gap, text, re.I):
        if m.group(1) and text[text.rfind("\n", 0, m.start()) + 1:m.start()].strip():
            continue  # "$1,500 deposit" then "$50 application fee" on the next line: that $50 is not the deposit
        if skip_before and re.search(skip_before, text[max(0, m.start() - 14):m.start()], re.I):
            continue
        v = _num(m.group(2))
        if lo <= v <= hi:
            found.append(v)
    for m in re.finditer(r"\$\s?(\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)[ \t]*(?:/[ \t]*mo(?:nth)?[ \t]*)?(?:one[- ]time |non[- ]refundable |refundable )?(?:" + label + r")(?![ \t]*[:=]|[ \t]*\d(?:\.\d+)?[ \t]*(?:x|times|months?)\b)", text, re.I):
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


_SLASH_LOOSE = re.compile(r"(?<![\w.,$/:#-])([1-6])[ \t]?/[ \t]?([1-4](?:\.5)?)(?![\w/.$%:-]|,\d|[ \t]*(?:mile|miles|mi\b|bath|baths|off\b|acre|block|blocks|inch|in\b|month|mo\b|yr|year|%|am\b|pm\b|pets?\b|cats?\b|dogs?\b))")
_SLASH_DATE_BEFORE = re.compile(r"\b(?:avail\w*|date|move|moving|start\w*|begin\w*|by|on|until|till|thru|through|ready|lease|due|from|since|open house|tour|expires?|deadline|posted|updated|built|before|after|today|tomorrow|sat|sun|mon|tue|wed|thu|fri|saturday|sunday|monday|tuesday|wednesday|thursday|friday|signed|renewal|rate|dated?|as of|effective)\b[ \t:]*$", re.I)


_RETRACTED = re.compile(r"[ \t]*[?.,;!]*[ \t]*(?:no|nope|actually|wait|sorry|correction)\b", re.I)


def _shorthand_retracted(text: str, end: int) -> bool:
    """Cycle 22: "3/2? No - 2 bed 1.5 bath": a layout shorthand the listing takes back right away is never read."""
    m = _RETRACTED.match(text[end:end + 20])
    return bool(m) and bool(re.search(r"\d[ \t]*(?:bed|bd|br|ba\b|bath)|\b\d[ \t]?[/xX\u00d7][ \t]?\d|\bstudio\b|\b(?:one|two|three|four)[- ](?:bed|bath)", text[end + m.end():end + m.end() + 50], re.I))


def _slash_beds_baths(text: str) -> tuple[int, float, float] | None:
    """Cycle 21: "3/2 ranch", "Newly renovated 3/2 near Hoover Elementary": beds over baths. Not a date ("available 3/2"), not a fraction
    ("1/2 mile", "1/2 bath"). Returns (position, beds, baths) of the first one."""
    for m in _SLASH_LOOSE.finditer(text):
        if m.group(1) == "1" and m.group(2) == "2":
            continue
        if _SLASH_DATE_BEFORE.search(text[max(0, m.start() - 22):m.start()]):
            continue
        if re.match(r"[ \t]*[-/]\d", text[m.end():m.end() + 4]):
            continue
        if _shorthand_retracted(text, m.end()):
            continue
        return m.start(), float(m.group(1)), float(m.group(2))
    return None


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


def _same_num(a: Any, b: float) -> bool:
    try:
        return abs(float(a) - b) < 0.01
    except (TypeError, ValueError):
        return False


_BEDS_SLASH_PAIR = re.compile(r"(?<![\d.,$/])\b(\d)[ \t]*(?:bed(?:room)?s?|bds?|brs?)[ \t]*/[ \t]*(\d)[ \t]*(?:bed(?:room)?s?|bds?|brs?)\b", re.I)


def _explicit_beds_baths(text: str, st: re.Match[str]) -> float | None:
    """Cycle 22: "Studio-1BR ... 1 Bed 1 Bath": one plain "N bed N bath" and no other bedroom count outside the plan range wins over the range."""
    if re.search(r"\b(?:from|starting[ \t]+(?:at|from)|starts?[ \t]+at|as[ \t]+low[ \t]+as)[ \t]+\$|\$\s?\d[\d,]*[ \t]*(?:-|\u2013|to)[ \t]*\$\s?\d", text, re.I):
        return None  # a "from $X" price or a price range means the listing covers several plans, so one "1 bed 1 bath" may be only one of them
    rest = text[:st.start()] + " " + text[st.end():]
    ex = re.findall(r"(?<![\d.,$/])\b(\d{1,2})[ \t]*(?:bed(?:room)?s?|bds?|brs?|bdrms?)\b[ \t,/|&-]*(?:and[ \t]+)?\d(?:\.\d)?[ \t]*(?:bath(?:room)?s?|bths?|ba)\b", rest, re.I)
    if len(ex) != 1:
        return None
    allb = {float(x) for x in re.findall(r"(?<![\d.,$/])\b(\d{1,2})[ \t]*(?:bed(?:room)?s?|bds?|brs?|bdrms?)\b", rest, re.I)}
    return float(ex[0]) if allb == {float(ex[0])} else None


def _beds_conflict(text: str) -> str:
    """"1BR/2BR convertible" in the title and "3 bedrooms" in the body: the listing does not say how many bedrooms it has. Returns
    a plain note (and the bedroom count stays empty), or "" when there is no such pair."""
    if _beds_converted(text) or _beds_corrected(text):
        return ""
    st = re.search(r"\bstudio[ \t]*(?:-|/|to|or|&)[ \t]*\d[ \t]*(?:br|bd|bed(?:room)?s?)\b", text, re.I)
    if st and _explicit_beds_baths(text, st):
        return ""
    if st:  # "Studio-1BR Prairie Commons": a plan range, not one layout
        return f'The listing says "{st.group(0)}", which covers more than one layout, so the bedroom count is left empty. Ask which layout you would get.'
    m = _BEDS_SLASH_PAIR.search(text)
    if not m or m.group(1) == m.group(2):
        return ""
    pair = {float(m.group(1)), float(m.group(2))}
    rest = text[:m.start()] + " " + text[m.end():]
    others = sorted({float(x) for x in re.findall(r"(?<![\d.,$/])\b(\d{1,2})[ \t]*(?:bed(?:room)?s?|bds?|brs?|bdrms?)\b", rest, re.I)} - pair)
    said = f'"{m.group(0)}"' + (f' and also "{others[0]:g} bedroom{"" if others[0] == 1 else "s"}"' if others else "")
    return f"The listing says {said}, so I could not tell how many bedrooms it has. The bedroom count is left empty. Ask which layout you would get."


# "LUXE 1x1", "2x2 apartment": beds by baths. Single digits only and never a size ("2x4 beams", "3x3 ft"), a count ("2x rent") or a date.
_BEDS_X_BATHS = re.compile(r"(?<![\w.,$/#-])([0-6])[ \t]?[xX\u00d7][ \t]?([1-4](?:\.5)?)(?![\w/$%'\"-]|\.\.|\u2026|[.,][\w$]|[ \t]*(?:ft|feet|foot|in\b|inch|sq|sf|x\b|\u00d7|mm|cm|m\b|%|\(|lumber|beams?|boards?|studs?|posts?|fenc))")


# "1x1? no 2x1" and "Actually: Campustown Flats 1x1": the listing corrects its own layout, so the later one is the one it means
_XB_CORRECT = re.compile(r"(?<![\w.,$/#-])[0-6][ \t]?[xX\u00d7][ \t]?[1-4](?:\.5)?[ \t]*[?.,;!]*[ \t]*(?:no|nope|actually|wait|sorry)\b[ \t,.:;-]*(?:(?:no|wait|actually|sorry)\b[ \t,.:;-]*)?(?:it'?s[ \t]+|its[ \t]+|it[ \t]+is[ \t]+|a[ \t]+)?(?:[a-z]+[ \t]+)?"
                         r"(?P<xb>(?<![\w.,$/#-])([0-6])[ \t]?[xX\u00d7][ \t]?([1-4](?:\.5)?)(?![\w,/$%'\"-]|\.\d))", re.I)
_XB_ACTUALLY = re.compile(r"\b(?:actually|correction|corrected)[ \t]*[:,-][ \t]*(?P<head>[^\n$.]{0,50}?)(?<![\w.,$/#-])([0-6])[ \t]?[xX\u00d7][ \t]?([1-4](?:\.5)?)(?![\w,/$%'\"-]|\.\d)", re.I)


def _beds_x_corrected(text: str) -> tuple[float, float] | None:
    m = _XB_CORRECT.search(text)
    if m:
        return float(m.group(2)), float(m.group(3))
    m = _XB_ACTUALLY.search(text)
    if m:
        return float(m.group(2)), float(m.group(3))
    return None


_XB_NOT_LAYOUT = re.compile(r"(?:deposit|security|fee|fees|admin|application|pet|key)[ \t]*[:=\-]?[ \t]*$", re.I)


def _first_x_match(text: str):
    """The first "2x1" that is a layout. "Deposit: 1x1" (one month) is not."""
    for m in _BEDS_X_BATHS.finditer(text):
        if _XB_NOT_LAYOUT.search(text[max(0, m.start() - 16):m.start()]) or _shorthand_retracted(text, m.end()):
            continue
        return m
    return None


def _beds_x_baths(text: str) -> tuple[float, float] | None:
    m = _first_x_match(text)
    if not m:
        return None
    return float(m.group(1)), float(m.group(2))


# "3BR2BA", "2bd1.5ba": beds and baths written together with no space
_BEDS_GLUED = re.compile(r"(?<![\w.,$/#-])(\d)[ \t]?(?:bed(?:room)?s?|bds?|brs?|bdrms?)[ \t]?(\d(?:\.5)?)[ \t]?(?:bath(?:room)?s?|bths?|ba)\b", re.I)


def _beds(text: str) -> float | None:
    conv = _beds_converted(text)
    if conv:
        return conv[1]
    corrected = _beds_corrected(text)
    if corrected:
        return corrected[1]
    xc = _beds_x_corrected(text)
    if xc:
        return xc[0]
    st_r = re.search(r"\bstudio[ \t]*(?:-|/|to|or|&)[ \t]*\d[ \t]*(?:br|bd|bed(?:room)?s?)\b", text, re.I)
    if st_r:
        ex_b = _explicit_beds_baths(text, st_r)
        if ex_b is not None:
            return ex_b
    if _beds_conflict(text):
        return None
    low = text.lower()
    hits: list[tuple[int, float]] = []
    for m in re.finditer(r"(?<![\d.,$/])\b(\d{1,2}(?:\.\d)?)(?:[ \t]*|-)(?:-[ \t]*\d{1,2}(?:\.\d)?[ \t]*)?(?:bed(?:room)?s?|bds?|brs?|bdrms?)\b(?!\s*(?:and breakfast|room only))", low):
        hits.append((m.start(), float(m.group(1))))
    for m in _BEDS_GLUED.finditer(text):
        hits.append((m.start(), float(m.group(1))))
    for m in re.finditer(r"\b(?:bed(?:room)?s?|bds?)\s*[:\-]\s*(\d{1,2}(?:\.\d)?)\b", low):
        hits.append((m.start(), float(m.group(1))))
    for m in re.finditer(r"\b(\d)\s*(?:bd|br|bed)\s*[/|]\s*\d(?:\.\d)?\s*(?:ba|bth|bath)", low):
        hits.append((m.start(), float(m.group(1))))
    for m in _SLASH_HOME.finditer(low):  # "3/2 single family home"
        if not _shorthand_retracted(low, m.end()):
            hits.append((m.start(), float(m.group(1))))
    for m in re.finditer(r"\b(one|two|three|four|five|six)[- ](?:bed(?:room)?s?|bdrms?|brs?)\b(?!\s*(?:and breakfast|room only))", low):
        hits.append((m.start(), float({"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}[m.group(1)])))
    studio = re.search(r"\bstudio\b(?!\s*(?:apartments?\s*)?(?:are|is|also|available)\b)", low)
    if studio and not re.search(r"\bno studio\b", low) and not [h for h in hits if h[1] >= 1]:
        hits.append((studio.start(), 0.0))  # "Studio-plus ... 1 bed" is a 1 bedroom; only a plain studio is 0
    xb = _beds_x_baths(text)
    if xb:
        hits.append((_first_x_match(text).start(), xb[0]))  # type: ignore[union-attr]
    sl = _slash_beds_baths(text)
    if sl:
        hits.append((sl[0], sl[1]))
    hits = [h for h in hits if h[1] <= 20]
    return min(hits)[1] if hits else None


_BATH_NUM = r"(\d{1,2}(?:\.\d)?|one|two|three|four|five)"
_BATH_WORD = r"[- ]?(?:bath(?:room)?s?|bths?|ba)\b"
_BATHS_CORRECTED = re.compile(r"\b" + _BATH_NUM + _BATH_WORD + r"[ \t]*\?[ \t]*(?:no|nope|actually|wait|sorry)\b[ \t,.:;-]*(?:it'?s[ \t]+|its[ \t]+|a[ \t]+)?(?:[a-z]+[ \t]+)?" + _BATH_NUM + _BATH_WORD
                             + r"|\b" + _BATH_NUM + _BATH_WORD + r"[ \t]*[(,;:.\-\u2013\u2014]?[ \t]*(?:actually|correction|corrected(?:[ \t]+to)?|really|in fact)[ \t,:\-]*(?:it'?s[ \t]+|its[ \t]+|a[ \t]+|only[ \t]+|just[ \t]+)?" + _BATH_NUM + _BATH_WORD, re.I)
_BATH_WORDS = {"one": 1.0, "two": 2.0, "three": 3.0, "four": 4.0, "five": 5.0}


def _baths_corrected(text: str) -> tuple[float, float] | None:
    """("two bath? no, 1 bath") -> (2, 1): the listing corrects itself, so the later count is the one it means (up or down)."""
    m = _BATHS_CORRECTED.search(text)
    if not m:
        return None
    g = [x for x in m.groups() if x]
    vals = [_BATH_WORDS[x.lower()] if x.lower() in _BATH_WORDS else float(x) for x in g[:2]]
    return vals[0], vals[1]


def _baths(text: str) -> float | None:
    corrected = _baths_corrected(text)
    if corrected:
        return corrected[1]
    xc = _beds_x_corrected(text)
    if xc:
        return xc[1]
    low = text.lower()
    m = re.search(r"(\d{1,2})\s*full\s*(?:bath(?:room)?s?|ba)\b[^.\n]{0,25}?(\d)\s*(?:half|1/2|partial)\s*(?:bath(?:room)?s?|ba)", low)
    if m:
        return int(m.group(1)) + 0.5 * int(m.group(2))
    m = re.search(r"(\d{1,2})\s*full\W{1,3}(\d)\s*(?:half|partial)\s*(?:bath(?:room)?s?|ba)\b", low)
    if m:
        return int(m.group(1)) + 0.5 * int(m.group(2))
    hits: list[tuple[int, float]] = []
    for m in _BEDS_GLUED.finditer(text):
        hits.append((m.start(), float(m.group(2))))
    for m in re.finditer(r"(?<![\d.,$/])\b(\d{1,2}(?:\.\d)?)(?:[ \t]*|-)(?:-[ \t]*\d(?:\.\d)?[ \t]*)?(?:full[ \t]+)?(?:bath(?:room)?s?|bths?|ba)\b", low):
        if re.search(r"\b(?:bed(?:room)?s?|bds?|brs?)[ \t]*[:\-][ \t]*$", low[max(0, m.start() - 14):m.start()]):
            continue  # "Beds: 3 Baths: 1.5": the 3 belongs to the beds label
        hits.append((m.start(), float(m.group(1))))
    for m in re.finditer(r"\b(?:bed(?:room)?s?|bds?|brs?)[ \t]*/[ \t]*(\d{1,2}(?:\.\d)?)[ \t]*(?:bath(?:room)?s?|bths?|ba)\b", low):
        hits.append((m.start(), float(m.group(1))))  # "3 bedrooms/2 baths"
    for m in _SLASH_HOME.finditer(low):
        if not _shorthand_retracted(low, m.end()):
            hits.append((m.start(), float(m.group(2))))
    for m in re.finditer(r"\bbath(?:room)?s?\s*[:\-]\s*(\d{1,2}(?:\.\d)?)\b", low):
        hits.append((m.start(), float(m.group(1))))
    for m in re.finditer(r"\b(one|two|three|four|five)[- ](?:bath(?:room)?s?|bths?)\b", low):
        hits.append((m.start(), float({"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}[m.group(1)])))  # "two bath"
    for m in re.finditer(r"\b(?:bath(?:room)?s?)\b[ \t]+(\d{1,2}(?:\.\d)?)\b(?![ \t]*(?:sq|sf|ft|\$|/|%|\d|min|mi\b|blocks?|years?|yr|bed|bd|br))", low):
        hits.append((m.start(), float(m.group(1))))
    for m in re.finditer(r"\b\d\s*(?:bd|br|bed)\s*[/|]\s*(\d(?:\.\d)?)\s*(?:ba|bth|bath)", low):
        hits.append((m.start(), float(m.group(1))))
    xb = _beds_x_baths(text)
    if xb:
        hits.append((_first_x_match(text).start(), xb[1]))  # type: ignore[union-attr]
    sl = _slash_beds_baths(text)
    if sl:
        hits.append((sl[0], sl[2]))
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
    low = re.sub(r"(?<![\w/&-])(?:wd|w-d|w\.d\.?)(?![\w/&-])", "w/d", low)  # cycle 27: "WD in unit" is the same as "W/D in unit"
    low = re.sub(r"\bwash[ \t]*(?:/|&|\+|and)[ \t]*dry\b", "washer/dryer", low)  # "wash/dry in unit" is the same as "washer/dryer in unit"
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
    negated = r"\bno\s+(?:in[- ]?(?:unit|home|suite)\s+)?(?:washer\s*(?:/|and|&)\s*dryer|washers?|laundry|w/?d)\b|\bwithout\s+(?:a\s+)?(?:washer|laundry)\b|\bno in[- ]?unit\b"
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
    if re.search(r"\bno\s+dish\s?washer|\bwithout\s+(?:a\s+)?dish\s?washer|\bdish\s?washer\s*[:\-]\s*(?:no|none)\b|(?<![\w/&-])no\s+dw(?![\w/&-])", low):
        return 0
    if re.search(r"\bdish\s?washer", low) or re.search(r"(?<![\w/&-])dw(?![\w/&-])", low):  # "DW" alone, or "W/D, DW"
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


_PARKING_COUNT_PRICE_RE = re.compile(r"\b(?:\d|one|two|three|four)[ \t]+(?:(?:assigned|reserved|covered|private|surface|off[- ]?street|parking)[ \t]+)*(?:spots?|spaces?|stalls?)\b[^.\n;$]{0,30}?\$\s?(\d{2,4})(?:\.\d\d)?\b(?!\s*(?:deposit|one[- ]time|setup|set-up))")
_PARKING_NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4}
_PARKING_YEARLY_AFTER = re.compile(r"(?:\.\d\d)?[ \t]*(?:/[ \t]*(?:yr|year|annum|y)\b|per[ \t]+(?:year|yr|annum)\b|a[ \t]+year\b|annually\b|yearly\b|annual\b|each[ \t]+year\b|every[ \t]+year\b)")
_PARKING_EACH_AFTER = re.compile(r"(?:\.\d\d)?[ \t]*(?:/[ \t]*mo\w*|per[ \t]+month|a[ \t]+month|monthly)?[ \t,]*(?:each|apiece|per[ \t]+(?:parking[ \t]+)?(?:spot|space|stall)s?)\b")
_PARKING_PRICE_RES = (
    re.compile(r"(?:garage|carport|covered parking|reserved parking|parking(?: fee| rate| cost)?|parking space|parking spot|parking permit|street permit)s?[ \t]*(?:space|spot|stall|fee|rental|rent|permit)?s?[ \t:\-=(,]{0,6}(?:(?:is|are|from|starting at|for|at|only|available|offered)[ \t,]+)*\$\s?(\d{2,4})(?:\.\d\d)?\b(?!\s*(?:deposit|one[- ]time|setup|set-up|/\s*\d\s*(?:br|bd|bed)))"),
    # "Parking: assigned covered spot $60/mo", "garage parking available for $110 a month": a few describing words in between
    re.compile(r"\b(?:garage|carport|parking)s?\b[ \t:\-=(]{0,4}(?:(?:assigned|reserved|covered|private|underground|heated|attached|detached|surface|lot|street|"
               r"spots?|spaces?|stalls?|permits?|available|offered|for|at|is|are|from|only|each|per|one|a|an|the|rental|rate|fee|cost|\d-car|off[- ]?street|on[- ]?site|garage|carport|parking|required|mandatory|optional|upgrade|upgraded|premium|-)[ \t:,]+){1,6}"
               r"\$\s?(\d{2,4})(?:\.\d\d)?(?=[ \t]*(?:/[ \t]*mo|per[ \t]+month|a[ \t]+month|monthly|each[ \t]+month))(?!\s*(?:deposit|one[- ]time|setup|set-up|/\s*\d\s*(?:br|bd|bed)))"),
    re.compile(r"\$\s?(\d{2,4})\s*(?:/\s*mo(?:nth)?|per month|a month|monthly)?\s*(?:for |per )?(?:a |the )?(?:reserved |covered |garage |private )?(?:parking|garage|carport)\b(?!\s*deposit)"),
    # "1 spot $50/mo", "Parking: 1 spot, $50/month", "2 spaces at $40 a month"
    # "Parking required for all residents $120/month", "Garage optional $100"
    re.compile(r"\b(?:garage|carport|parking)s?[ \t:\-]+(?:is[ \t]+|are[ \t]+)?(?:required|mandatory|optional|additional|extra)\b[^.\n;$]{0,30}?\$\s?(\d{2,4})(?:\.\d\d)?\b(?!\s*(?:deposit|one[- ]time|setup|set-up))"),
    re.compile(r"\b\d\s*(?:parking\s+)?(?:spots?|spaces?|stalls?)\s*[,:\-]?\s*(?:for |at |is |are |only )?\$\s?(\d{2,4})(?:\.\d\d)?(?=[ \t]*(?:/[ \t]*mo|per[ \t]+month|a[ \t]+month|monthly|each[ \t]+month|\b))(?!\s*(?:deposit|one[- ]time|setup|set-up))"),
    _PARKING_COUNT_PRICE_RE,
    # cycle 24: "Covered spot $75", "Reserved indoor garage space: $90": a kind word and a spot word with the price right after (the only parking when nothing else is said)
    re.compile(r"\b(?:covered|garage|carport|reserved|assigned|indoor|underground|attached|private|heated|designated)[ \t]+(?:(?:covered|indoor|garage|underground|reserved|assigned|private|heated|parking|outdoor|surface)[ \t]+)*"
               r"(?:spots?|spaces?|stalls?)[ \t]*[:\-=(,]{0,3}[ \t]*(?:(?:is|are|for|at|only|from|just|costs?|rents?[ \t]+for)[ \t]+)*\$\s?(\d{2,4})(?:\.\d\d)?\b(?!\s*(?:deposit|included|incl\b|free\b|in[ \t]+(?:the[ \t]+)?rent|one[- ]time|setup|set-up|/\s*\d\s*(?:br|bd|bed)))"),
    # "additional spaces $60": an extra space (optional, so it never counts)
    re.compile(r"\b(?:additional|extra)[ \t]+(?:parking[ \t]+)?(?:spots?|spaces?|stalls?|cars?|vehicles?)[ \t:\-=,]*(?:are[ \t]+|is[ \t]+|for[ \t]+|at[ \t]+|cost[ \t]+)*\$\s?(\d{2,4})(?:\.\d\d)?\b(?!\s*(?:deposit|one[- ]time|setup|set-up))"),
)
_PARKING_OPTIONAL = re.compile(r"\boptional\b|\bavailable\b|\badditional\b|\bextra (?:parking|spaces?|spots?|cars?|vehicles?|garage)\b|\bupgrade\b|\bif (?:you )?(?:need|want)\b|\bwaitlist\b|\b(?:on|by|upon) request\b|\bfor an? fee\b", re.I)
_PARKING_REQUIRED = re.compile(r"\brequired\b|\bmandatory\b|\bmust\b", re.I)
# "Parking $100 per month optional", "Heated garage, $130 a month, optional": the word comes after the amount, past the clause end
_PARKING_OPTIONAL_AFTER = re.compile(r"^[ \t]*(?:(?:/[ \t]*mo\w*|per[ \t]+month|a[ \t]+month|monthly|each[ \t]+month|extra|additional)[ \t,;:()\-]*){0,3}"
                                     r"(?:optional\b|if[ \t]+(?:you[ \t]+)?(?:need|want)\b|on[ \t]+request\b|upgrade\b|waitlist\b|for[ \t]+an[ \t]+extra\b)", re.I)
_PARKING_FREE = re.compile(r"\bfree (?:off[- ]?street |on[- ]?street |street |on[- ]?site |surface |assigned |resident |tenant )?(?:parking|lot|spots?|spaces?)\b|\bparking\s*(?:is\s*)?(?:included|free|at no (?:extra )?charge)\b|"
                           r"\bparking\s*[:\-]\s*(?:free|included)\b|\b(?:lot|surface|street|off[- ]?street)[^.\n;$]{0,20}\bfree\b|\bfree\b[^.\n;$]{0,12}\b(?:lot|surface)\b|"
                           r"\b(?:\d+|one|two|three|four)\s+(?:[a-z-]+\s+){0,2}(?:spaces?|spots?|stalls?)\s+(?:is\s+|are\s+)?(?:included|free)\b|\b(?:includes?|including)\s+(?:\w+[- ]?){0,2}parking\b|"
                           r"\bparking\b[^.\n;$]{0,30}\b(?:at|for|with)\s+no\s+(?:extra\s+|additional\s+)?(?:charge|cost|fee)\b|\bno\s+(?:extra\s+|additional\s+)?(?:charge|cost|fee)\s+for\s+(?:\w+\s+){0,2}parking\b", re.I)


# "Off-street parking, free.", "Parking: street - free", "Parking (free)": the word free comes after the parking words
_PARKING_FREE_AFTER = re.compile(r"\b(?:parking|garages?|carports?|(?:driveway|lot|street|off[- ]?street)[ \t]+(?:parking|spots?|spaces?))[ \t]*(?:[:,(\-\u2013\u2014][ \t]*)(?:[a-z][a-z\- ]{0,20}?[ \t]*[,\-(][ \t]*)?(?:is[ \t]+)?"
                                 r"(?:free|included|no[ \t]+(?:extra[ \t]+|additional[ \t]+)?(?:charge|cost|fee))\b(?![ \t]+(?:for|during|until|trial|first|if|with|(?:wi-?fi|internet|water|rent|cable|trash|laundry|heat|utilit\w*|storage|tours?|month|app\w*|pets?|gym|pool)\b))")


def _parking_prices(low: str) -> list[tuple[float, bool, str, str]]:
    """Every parking price in the text as (amount a month, optional, clause, unit). A price that is only offered ("available", "additional",
    "optional", or a different spot than the free one) is optional and never counts toward the monthly cost. A yearly price ("street permit
    $25/yr") comes back as its monthly share with unit "year" (the clause holds the yearly words); a price "each" for 2 required spaces comes
    back as the total with unit "each"."""
    seen: set[int] = set()
    out: list[tuple[float, bool, str, str]] = []
    free_anywhere = bool(_PARKING_FREE.search(low))
    for rx in _PARKING_PRICE_RES:
        for m in rx.finditer(low):
            at = m.start(1)
            if any(abs(at - x) < 2 for x in seen):
                continue
            if rx is _PARKING_COUNT_PRICE_RE and not re.search(r"\bparking\b|\bgarage\b|\bcarport\b|\b(?:assigned|reserved|covered|surface|off[- ]?street)\b", low[max(0, m.start() - 40):m.end()]):
                continue  # "1 space $40" with nothing saying it is parking
            seen.add(at)
            a = max(low.rfind(x, 0, m.start()) for x in (".", "\n", ";", ",", " | ")) + 1  # from the start of the match: "garage available, $90" is one clause
            b = min([x for x in (low.find(". ", at), low.find("\n", at), low.find(";", at), low.find(",", at), low.find(" | ", at), m.end() + 14) if x != -1])
            clause = low[a:b + 1]
            required = bool(_PARKING_REQUIRED.search(clause))
            optional = bool(_PARKING_OPTIONAL.search(clause)) and not required
            after_amount = re.split(r"[.;](?:\s|$)", low[m.end(1):].split("\n")[0][:60])[0]  # stop at the sentence end: the next sentence is not about this price
            if not required and _PARKING_OPTIONAL_AFTER.match(re.sub(r"^(?:\.\d\d)", "", after_amount)) and not _PARKING_REQUIRED.search(after_amount[:40]):
                optional = True
                clause = low[a:m.end(1) + len(after_amount)]
            if not optional and not required and free_anywhere and not _PARKING_FREE.search(clause):
                optional = True  # free parking is listed elsewhere, so this priced one is a different, extra choice
            value, unit = float(m.group(1)), ""
            if _PARKING_YEARLY_AFTER.match(after_amount) or (re.search(r"\b(?:yearly|annual|annually)\b", low[a:m.start(1)]) and not re.search(r"month|/[ \t]*mo", after_amount[:40])):
                value, unit = round(value / 12, 2), "year"
                clause = low[a:m.end(1) + len(after_amount)]
            elif not optional and _PARKING_EACH_AFTER.match(after_amount):
                sentence = low[max(low.rfind(x, 0, m.start(1)) for x in (".", "\n", ";")) + 1:m.end(1) + len(after_amount)]
                cm = re.search(r"\b(\d|one|two|three|four)[ \t]+(?:(?:assigned|reserved|covered|private|surface|off[- ]?street|required|parking)[ \t,]+)*(?:spots?|spaces?|stalls?|cars?|vehicles?)\b", sentence)
                n = (_PARKING_NUM_WORDS.get(cm.group(1)) or int(cm.group(1))) if cm else 1
                if n > 1:
                    value, unit = value * n, "each"
            out.append((value, optional, clause, unit))
    if not out:
        out = _parking_general_prices(low)
    return out


_PARKING_WORD = re.compile(r"\b(?:parking|garage|carport|(?:assigned|reserved|covered|private|driveway)[ \t]+(?:space|spot|stall)s?|(?:space|spot|stall)s?[ \t]+per[ \t]+unit|permit)\b")
_PARKING_NOT_THIS = re.compile(r"deposit|application|admin|one[- ]time|set-?up|move[- ]in|key|fob|per[ \t]+(?:semester|quarter)|each[ \t]+(?:semester|quarter)|\b(?:semester|quarterly|quarter)\b")


def _parking_general_prices(low: str) -> list[tuple[float, bool, str, str]]:
    """The general step for a priced parking line the narrow patterns above did not read: a clause that names parking (garage, carport,
    assigned or reserved space, permit) and a dollar amount with its period anywhere after it ("reserved garage space required, $95 per
    space per month", "Parking: yearly permit $240"). Same tuple as _parking_prices."""
    out: list[tuple[float, bool, str, str]] = []
    free_anywhere = bool(_PARKING_FREE.search(low))
    for sm in re.finditer(r"[^\n;|~\u2022]+", low):
        for sent in re.split(r"\.(?!\d)", sm.group(0)):
            if not _PARKING_WORD.search(sent) or re.search(r"\b(?:second|2nd|additional|extra|another|guest|visitors?)\b|[=@]|https?:", sent):
                continue  # a second or extra space is optional, and a formula or link in the line is not a price to read
            for m in re.finditer(r"\$\s?(\d{2,4})(?:\.\d\d)?(?![\d,])", sent):
                before, after = sent[:m.start()], sent[m.end():]
                clause_start = max(before.rfind(","), -1) + 1
                if not _PARKING_WORD.search(before) and not re.match(r"[ \t]*(?:/[ \t]*mo\w*|per[ \t]+\w+|a[ \t]+\w+)?[ \t]*(?:for[ \t]+)?(?:a[ \t]+|the[ \t]+)?(?:reserved[ \t]+|covered[ \t]+|garage[ \t]+)?(?:parking|garage|carport|permit)", after):
                    continue
                if _PARKING_NOT_THIS.search(before[-25:] + " " + after[:25]):
                    continue
                if re.search(r"\b(?:pets?|dogs?|cats?|storage|bike|trash|water|internet|utilit)\w*[ \t:]*$", before[-14:]):
                    continue
                near = after[:45]
                yearly = bool(_PARKING_YEARLY_AFTER.match(near)) or (bool(re.search(r"\b(?:yearly|annual|annually)\b", before[-40:])) and not re.search(r"month|/[ \t]*mo", near))
                monthly = bool(re.search(r"/[ \t]*mo\w*|per[ \t]+(?:[a-z]+[ \t]+){0,3}month|a[ \t]+month|monthly|each[ \t]+month", near[:40])) or bool(re.search(r"\bmonthly\b", before[-30:]))
                if not (yearly or monthly):
                    continue
                clause = sent[clause_start:m.end() + 30]
                required = bool(_PARKING_REQUIRED.search(sent))
                optional = bool(_PARKING_OPTIONAL.search(sent)) and not required
                if not required and _PARKING_OPTIONAL_AFTER.match(near):
                    optional = True
                if not optional and not required and free_anywhere and not _PARKING_FREE.search(sent):
                    optional = True
                value, unit = float(m.group(1)), ""
                if yearly:
                    value, unit = round(value / 12, 2), "year"
                elif not optional and re.search(r"\bper[ \t]+(?:parking[ \t]+)?(?:spot|space|stall)\b|\beach\b", near):
                    cm = re.search(r"\b(\d|one|two|three|four)[ \t]+(?:(?:assigned|reserved|covered|private|surface|off[- ]?street|required|parking)[ \t,]+)*(?:spots?|spaces?|stalls?|cars?|vehicles?)\b", sent)
                    n = (_PARKING_NUM_WORDS.get(cm.group(1)) or int(cm.group(1))) if cm else 1
                    if n > 1:
                        value, unit = value * n, "each"
                out.append((value, optional, clause, unit))
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
    pm = re.search(r"\b((?:(?:reserved|covered|assigned|premium|heated|underground|indoor|private|surface)[ \t]+)+(?:spots?|spaces?|stalls?|parking))\b", clause)
    if pm:
        phrase = " ".join(pm.group(1).split())
        return phrase + (" space" if phrase.endswith("parking") else "")  # cycle 26: "reserved covered spot $60" is named as the listing words it, so the note and the quoted line share words
    return "parking space"


_PARK_ITEM_BAD = re.compile(r"\b(?:optional|available|extra|additional|upgrade|waitlist|wait[- ]list|if|deposit|one[- ]time|application|fee for|no|required|mandatory)\b")
_PARK_FREE_ITEM = re.compile(r"\b(?:free|included|no[ \t]+(?:charge|cost|fee))\b")
_PARK_TYPE = r"(?:covered|garage|carport|reserved|assigned|surface|open|uncovered|underground|outdoor|indoor|street|driveway|lot|spot|space)"
_PARK_LINE_ITEM = re.compile(r"^[ \t*\u2022\-]*(" + _PARK_TYPE + r"[a-z \t]{0,20}?)[ \t]*[:\-]?[ \t]*((?:\$\s?\d|free\b)[^\n]*)$")


_PARK_RANK_WORDS = re.compile(r"\b(?:assigned|reserved)\b")
_PARK_YEARLY_WORDS = re.compile(r"/\s*y(?:ea)?r|per\s+year|a\s+year|yearly|annual")
_PARK_KIND_NAMES = {"garage": "a garage", "covered": "covered parking", "lot": "a surface lot", "street": "street parking", "": "another parking choice"}


def _choice_kind(it: str) -> str:
    """The kind of one parking choice ("assigned garage space" garage, "2 driveway spots" lot, "street permit" street, "" when no kind is named)."""
    k = _parking_kind_words(it)
    if k:
        return k
    if re.search(r"\bdriveway\b", it):
        return "lot"
    return ""


def _choice_label(kind: str, it: str) -> str:
    """Plain words for one parking choice in a note."""
    if kind == "lot" and re.search(r"\bdriveway\b", it):
        return "driveway parking"
    if kind == "street":
        return "a street permit" if re.search(r"\bpermit\b", it) else "street parking"
    if kind == "lot" and _PARK_RANK_WORDS.search(it):
        return "assigned parking"
    return _PARK_KIND_NAMES.get(kind, "another parking choice")


def _parking_choice_items(parts: list[str], strict: bool) -> list[tuple[float | None, str, str]] | None:
    """Split parking text into its choices: (monthly price or None when none is given, kind, the words). A choice has a kind word, a price or
    "free". Returns None when the text holds a word that makes it an extra rather than a choice ("optional", "available", "extra") or a price
    that is not monthly or yearly. ``strict`` (text that is not a "Parking:" list) needs a kind word in every priced choice."""
    items: list[str] = []
    for part in parts:
        # "street (free)" and "$0 (open lot)" are one choice: a bracket that only holds the price, or follows only a price, joins its neighbour
        part = re.sub(r"\(\s*((?:free|included|no[ \t]+(?:charge|cost|fee))\b[^()$\d]*|\$\s?\d[^()a-z]*(?:(?:/\s*mo\w*|per\s+\w+|a\s+\w+)[^()]*)?)\)", r" \1 ", part)
        part = re.sub(r"((?:^|[,;|])\s*\$\s?\d[^(),;|a-z]*)\(\s*([a-z][^()$\d]*)\)", r"\1 \2 ", part)
        items += [x.strip() for x in re.split(r"\s*[;|]\s*|,(?!\d{3})\s*|\s+/\s+|\s*/(?=\s*(?:covered|garage|carport|reserved|assigned|surface|open|uncovered|street|driveway)\b)|\s+or\s+|\s+-\s+|[()]", part) if x.strip()]
    raw: list[list[Any]] = []  # [price or None, kind words or "", words]
    for it in items:
        if not re.search(_PARK_TYPE + r"|free|included|\$\s?0\b|^\$|\bpermit\b", it) and not _PARK_FREE_ITEM.search(it):
            continue  # not a parking choice (a stray word between two choices)
        if re.search(r"\bfree[ \t]+(?:wi-?fi|internet|water|rent|cable|trash|laundry|heat|utilit\w*|storage|month|tours?)", it):
            continue  # "free wifi" is not a free parking choice
        if _PARK_ITEM_BAD.search(it):
            return None
        pm = re.search(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?(?!\d)", it)
        kind = _choice_kind(it)
        price: float | None = None
        if pm:
            price = float(pm.group(1).replace(",", ""))
            if _PARK_YEARLY_WORDS.search(it):
                price = round(price / 12, 2)
            elif re.search(r"per\s+(?:semester|quarter)|quarterly|semester", it):
                return None
        elif _PARK_FREE_ITEM.search(it):
            price = 0.0
        elif not kind or re.search(r"\bno\b|\bnone\b", it):
            continue
        # "2-car garage, included" and "$75/mo per vehicle, covered": a price with no kind and a kind with no price next to each other are one choice
        if raw and not kind and price is not None and raw[-1][0] is None and raw[-1][1]:
            raw[-1][0] = price
            raw[-1][2] += " " + it
            continue
        if raw and kind and price is None and raw[-1][0] is not None and not raw[-1][1]:
            raw[-1][1] = kind
            raw[-1][2] += " " + it
            continue
        raw.append([price, kind, it])
    got: list[tuple[float | None, str, str]] = []
    for price, kind, it in raw:
        if price is not None and strict and not kind:
            return None
        got.append((price, kind or ("lot" if price == 0 else ""), it))
    return got


def _parking_decide(got: list[tuple[float | None, str, str]]) -> tuple[str, float | None, list[str]] | None:
    """The one parking choice to save from several: the best kind offered (garage > covered or carport > assigned or reserved > surface lot or
    street) with that choice's own price, and one note naming the others. The same kind at different prices keeps the cheapest."""
    priced_kinds = {k for v, k, _it in got if v is not None}
    got = [g for g in got if g[0] is not None or g[1] not in priced_kinds]  # "garage" then "garage $150": the priced mention is the choice
    seen: set[tuple[Any, str]] = set()
    uniq = []
    for g in got:
        if (g[0], g[1]) not in seen:
            seen.add((g[0], g[1]))
            uniq.append(g)
    got = uniq
    if len(got) < 2 or (len({g[1] for g in got}) < 2 and len({g[0] for g in got}) < 2):
        return None

    def _rank(g):
        if g[1] == "garage":
            return 4
        if g[1] == "covered":
            return 3
        return 2 if _PARK_RANK_WORDS.search(g[2]) else 1
    top = max(_rank(g) for g in got)
    cands = [g for g in got if _rank(g) == top]
    best = min(cands, key=lambda g: (g[0] is None, g[0] if g[0] is not None else 0))  # the best kind offered, at its cheapest price
    others = []
    for v, k, it in got:
        if (v, k, it) == best:
            continue
        yearly = bool(_PARK_YEARLY_WORDS.search(it))
        price = "" if v is None else (" for free" if v == 0 else f" for ${v * 12:,.0f} a year" if yearly else f" for ${v:,.0f} a month")
        others.append(_choice_label(k, it) + price)
    kind_best = best[1] or "lot"
    nm = _choice_label(kind_best, best[2])
    if best[0] is None:
        saved = f"{nm[0].upper() + nm[1:]} is saved, but the listing gives no price for it."
    else:
        cost_words = "free" if best[0] == 0 else f"${best[0]:,.0f} a month"
        saved = f"{nm[0].upper() + nm[1:]} ({cost_words}) is saved."
    note = (f"The listing gives more than one parking choice. {saved} It also offers {' and '.join(others)}. "
            "They are alternatives, so the others are not in the monthly cost. Ask which one you would get"
            + (" and what it costs." if best[0] is None or any(g[0] is None for g in got) else "."))
    return kind_best, (None if best[0] is None else round(best[0], 2)), [note]


def _parking_options(low: str) -> tuple[str, float | None, list[str]] | None:
    """Cycle 19 and 20: several parking choices in one list ("Parking: $0 (open lot), Covered $45", "Parking: garage OR 2 driveway spots OR street
    permit", "free parking in a surface lot (garage spaces also offered for $75)"). They are options, not extra charges. The best kind offered
    is saved with its own price (never another choice's price) and one plain note names the others. Returns (kind, monthly cost or None, notes)
    or None when the text is not such a list."""
    for m in re.finditer(r"\bparking(?:[ \t]+(?:options?|types?|rates?|fees?|costs?|choices?))?[ \t]*[:\-][ \t]*([^\n]*)", low):
        parts = [re.split(r"\.(?:\s|$)|\s\|\s", m.group(1))[0]]
        rest = low[m.end():].split("\n")
        for line in rest[1:5]:
            if not _PARK_LINE_ITEM.match(line):
                break
            parts.append(line)
        if "$" not in " ".join(parts):
            parts = [re.sub(r"\bavailable\b", " ", x) for x in parts]  # "garage, carport, or street permit available": a list of kinds, not an extra
        if re.search(r"\b(?:optional|available|extra|additional|upgrade|waitlist|wait[- ]list|(?:on|by|upon)[ \t]+request)\b", " ".join(parts)):
            continue  # an offered extra is handled by the optional-parking reader, not as a choice
        got = _parking_choice_items(parts, strict=False)
        if got:
            res = _parking_decide(got)
            if res:
                return res
    # the same choice written inside a sentence: "free parking in a surface lot (garage spaces also offered for $75)"
    for line in low.split("\n"):
        for sent in re.split(r"\.(?:\s|$)(?![^(]*\))", line):
            if not re.search(r"\b(?:parking|garages?|carports?|driveway|lot)\b", sent) or not re.search(r"\$\s?\d|\bfree\b|\bincluded\b", sent):
                continue
            if sent.count("(") + sent.count(",") + len(re.findall(r"\bor\b", sent)) == 0:
                continue
            if re.search(r"\b(?:optional|available|extra|additional|upgrade|waitlist|wait[- ]list|required|mandatory)\b", sent):
                continue  # an offered extra (or a required one) is the optional-parking reader's, not a choice
            got = _parking_choice_items([sent], strict=True)
            if got and all(v is not None for v, _k, _i in got) and len({g[1] for g in got}) >= 2:
                res = _parking_decide(got)
                if res:
                    return res
    return None


_CAR_FIRST = r"(?:1st|first|one|1)[ \t]+(?:car|vehicle|spot|space|stall)s?"
_CAR_SECOND = r"(?:2nd|second|additional|extra|each[ \t]+additional|another)[ \t]+(?:car|vehicle|spot|space|stall)s?"
_CAR_AMT = r"\$\s?(\d{2,4})(?:\.\d\d)?(?!\d)(?!,\d)(?![ \t]*(?:/[ \t]*y|per[ \t]+y|a[ \t]+y|yearly|annual))"


def _parking_per_car(low: str) -> tuple[float, float | None, str] | None:
    """Cycle 20: "Parking: 1st car $100, 2nd car $120", "$100 for the first car, $120 for a second", "first car $100 / additional car $120".
    Returns (the first car's monthly price, the second car's price or None, the matched text with the prices blanked) or None."""
    first = re.search(r"\b" + _CAR_FIRST + r"[ \t:\-=]*(?:is[ \t]+|are[ \t]+|at[ \t]+|for[ \t]+)?" + _CAR_AMT, low) \
        or re.search(_CAR_AMT + r"[ \t]*(?:/[ \t]*mo\w*|per[ \t]+month|a[ \t]+month|monthly)?[ \t]*(?:for[ \t]+)?(?:the[ \t]+|your[ \t]+)?" + _CAR_FIRST + r"\b", low)
    if not first:
        return None
    second = re.search(r"\b" + _CAR_SECOND + r"[ \t:\-=]*(?:is[ \t]+|are[ \t]+|at[ \t]+|for[ \t]+)?" + _CAR_AMT, low) \
        or re.search(_CAR_AMT + r"[ \t]*(?:/[ \t]*mo\w*|per[ \t]+month|a[ \t]+month|monthly)?[ \t]*(?:for[ \t]+)?(?:a[ \t]+|the[ \t]+|each[ \t]+)?" + _CAR_SECOND + r"\b", low)
    blanked = low
    for m in [first] + ([second] if second else []):
        blanked = blanked[:m.start()] + " " * (m.end() - m.start()) + blanked[m.end():]
    return float(first.group(1)), (float(second.group(1)) if second else None), blanked


_PARK_ONE_INCLUDED = re.compile(r"\b(?:1|one|a|single)[ \t]+(?:(?:assigned|reserved|covered|private|surface|off[- ]?street|deeded|garage|parking|lot)[ \t]+){0,3}(?:spaces?|spots?|stalls?|cars?)[ \t]+(?:is[ \t]+|are[ \t]+)?(?:included|free)\b"
                                r"|\bincluded[ \t]*[:\-]?[ \t]*(?:1|one)[ \t]+(?:spaces?|spots?|stalls?)\b")
_PARK_SECOND_PRICE = re.compile(r"\b(?:2nd|second|another)(?:[ \t]+(?:car|vehicle|space|spot|stall|parking))*[ \t:\-=]*(?:is[ \t]+|are[ \t]+|at[ \t]+|for[ \t]+|costs?[ \t]+|rents?[ \t]+|rented[ \t]+|rental[ \t]+|leases?[ \t]+|extra[ \t]+)*\$\s?(\d{2,4})(?:\.\d\d)?(?!\d)(?!,\d)"
                                r"(?![ \t]*(?:/[ \t]*y|per[ \t]+y|a[ \t]+y|yearly|annual))")


def _parking_promo_note(text: str, cost: float) -> str:
    """Cycle 22: "Underground garage: $140 per month, free for first 6 months". The full price is the parking cost (the deal ends), and a
    note says the first months are free, so the first months cost less than the saved figure."""
    for sent in re.split(r"[.\n;|]", text):
        if not re.search(r"\b(?:parking|garage|carport|covered|space|spot|stall)\b", sent, re.I):
            continue
        m = re.search(r"\b(?:free|waived|no[ \t]+(?:charge|cost|fee))[ \t]+(?:for[ \t]+)?(?:the[ \t]+)?(?:first|1st|initial)[ \t]+((?:\d{1,2}|one|two|three|four|five|six|twelve)[ \t]+(?:months?|weeks?|mos?\b))"
                      r"|\b(?:first|1st)[ \t]+((?:\d{1,2}|one|two|three|four|five|six|twelve)[ \t]+(?:months?|weeks?))[ \t]+(?:are[ \t]+|is[ \t]+)?(?:free|waived)\b"
                      r"|\b((?:\d{1,2}|one|two|three|four|five|six|twelve)[ \t]+months?)[ \t]+free\b", sent, re.I)
        if m:
            span = next(g for g in m.groups() if g)
            span = " ".join(span.split())
            span = "month" if re.fullmatch(r"(?:one|1)[ \t]+months?", span, re.I) else span
            return (f"The listing says parking is free for the first {span}. The full ${cost:,.0f} a month is the parking cost saved, because the offer ends. "
                    "The first months cost less. Check with the landlord when the offer ends.")
    return ""


def _parking_included_plus_second(low: str) -> tuple[str, float | None, list[str]] | None:
    """Cycle 21: "Parking: 1 space included, 2nd $90", "1 spot included; second space $110/mo". One space is in the rent, so the parking cost is $0
    and the second space is an optional extra named in a note. Only what the listing said is named."""
    for line in low.split("\n"):
        inc, sec = _PARK_ONE_INCLUDED.search(line), _PARK_SECOND_PRICE.search(line)
        if not inc or not sec or not re.search(r"\b(?:parking|space|spot|garage|stall|lot)", line):
            continue
        # cycle 22: only the sentence about the included space says its kind ("Detached garage available at $165/mo" next to it is another offer)
        s_start = max(line.rfind(". ", 0, inc.start()), line.rfind("; ", 0, inc.start())) + 1
        ends = [i for i in (line.find(". ", sec.end()), line.find("; ", sec.end())) if i != -1]
        s_end = min(ends) if ends else len(line)
        rest = line[s_start:sec.start()] + " " + line[sec.end():s_end]
        kind, cost = _parking_kind_cost(rest, None)
        if cost != 0:
            continue
        kind = kind or "lot"  # one space is included, so the parking is known ($0) even when the listing does not name its type
        price = float(sec.group(1))
        return kind, 0.0, [f"The listing says one parking space is included and a second space is ${price:,.0f}. The second space is optional, so it is not counted in the monthly cost. "
                           "Ask the price if you will have two cars."]
    return None


_PX_WORD = r"(?:2nd|3rd|second|third|another|additional|extra|add'l|each[ \t]+additional)"
_PX_NOUNS = frozenset("space spaces spot spots stall stalls car cars vehicle vehicles parking garage carport garages".split())
_PX_FILL = _PX_NOUNS | frozenset("is are at for cost costs a an the each per one of only price priced rate fee fees monthly month mo available rent rents rented rental lease leases add adds".split())
_PX_RENT_FILL = _PX_FILL | frozenset("from building us landlord management office owner to on request directly with rental it".split())
_PX_PERIOD = r"((?:[ \t]*/[ \t]*(?:mo\w*|yr|year)|[ \t]+per[ \t]+(?:month|mo|year|yr)|[ \t]+a[ \t]+(?:month|year)|[ \t]+monthly|[ \t]+yearly|[ \t]+annually)?)"
_PX_AMT = r"\$\s?(\d{1,4}(?:,\d{3})*)(?:\.\d\d)?(?![\d,])"
_PX_RES = (
    ("extra", re.compile(r"\b(" + _PX_WORD + r")\b([^$\n|;.]{0,40}?)" + _PX_AMT + _PX_PERIOD, re.I)),
    ("rent", re.compile(r"\b(?:rent|lease|add)[ \t]+(?:an?[ \t]+)?(?:extra[ \t]+|second[ \t]+|additional[ \t]+)?(?:parking[ \t]+)?(?:space|spot|stall)\b()([^$\n|;.]{0,40}?)" + _PX_AMT + _PX_PERIOD, re.I)),
    ("after", re.compile(_PX_AMT + _PX_PERIOD + r"[ \t]*(?:for|per|each)[ \t]+(?:an?[ \t]+|each[ \t]+)?(" + _PX_WORD + r")\b(?:[ \t]+(?:car|vehicle|space|spot|stall|parking)s?)?", re.I)),
)
_PX_CONTEXT = re.compile(r"\b(?:parking|garages?|carports?|driveway|spaces?|spots?|stalls?)\b", re.I)
_PX_TOPIC = re.compile(r"\b(?:pets?|dogs?|cats?|deposit|application|admin|utilit\w*|storage|trash|internet|cable|laundry|amenity|fees?)\b", re.I)


def _px_has_parking_context(text: str, pos: int) -> bool:
    """A parking word shortly before pos in the same line (or the line above, for a bullet list) with no other topic in between."""
    ls = text.rfind("\n", 0, pos) + 1
    prev = text[max(ls, pos - 110):pos]
    if not _PX_CONTEXT.search(prev) and ls > 0:
        pls = text.rfind("\n", 0, ls - 1) + 1
        prev = text[max(pls, ls - 110):ls - 1] + " " + text[ls:pos]
    hits = list(_PX_CONTEXT.finditer(prev))
    if not hits:
        return False
    tail = prev[hits[-1].end():]
    tail = re.sub(r"\b(?:2nd|second|extra|additional)\b", " ", tail)
    return not _PX_TOPIC.search(tail)


def _parking_extras(text: str) -> tuple[str, list[tuple[str, float, str]]]:
    """Cycle 23: the one general step for an extra parking space with its own price: "1 space included, 2nd $90", "extra $50", "Additional $175/mo",
    "or rent a space from the building for $120", "$90 for a second space", whatever the layout (pipes, bullets, one line, next to other
    sentences). Such a price is optional: it never counts in the monthly cost and never makes the parking cost missing. Returns (the text with those
    phrases blanked out, [(the extra word, the amount, the period words)])."""
    found: list[tuple[int, int, str, float, str]] = []
    for kind, rx in _PX_RES:
        for m in rx.finditer(text):
            if kind == "extra":
                word, middle, amt, period = m.group(1), m.group(2), m.group(3), m.group(4)
            elif kind == "rent":
                word, middle, amt, period = "extra", m.group(2), m.group(3), m.group(4)
            else:
                amt, period, word, middle = m.group(1), m.group(2), m.group(3), ""
            tokens = re.findall(r"[a-z']+", middle.lower())
            if not all(t in (_PX_RENT_FILL if kind == "rent" else _PX_FILL) for t in tokens):
                continue
            if kind == "after" and re.search(r"\b(?:car|vehicle|space|spot|stall|parking)", text[m.start():m.end()], re.I):
                pass
            elif not (_PX_NOUNS & set(tokens)) or kind == "extra" and set(tokens) <= {"space", "spaces"} - {"parking"}:
                if not _px_has_parking_context(text, m.start()):
                    continue
            elif not _px_has_parking_context(text, m.start()) and not (_PX_NOUNS - {"space", "spaces"}) & set(tokens):
                continue
            if any(m.start() < e and s < m.end() for s, e, *_r in found):
                continue
            found.append((m.start(), m.end(), word.lower(), float(amt.replace(",", "")), " ".join(period.split()).lower()))
    if not found:
        return text, []
    blanked = text
    for s, e, *_r in found:
        blanked = blanked[:s] + " " * (e - s) + blanked[e:]
    found.sort()
    return blanked, [(w, a, per) for _s, _e, w, a, per in found]


def _parking_extras_note(extras: list[tuple[str, float, str]], kind: str, cost: float | None, low: str) -> str:
    """One short note for the optional extra space prices that _parking_extras took out."""
    def money(a: float, per: str) -> str:
        yearly = bool(re.search(r"y", per))
        return f"${a:,.0f}" + (" a year" if yearly else " a month" if per else "")
    prices = " and ".join(dict.fromkeys(money(a, per) for _w, a, per in extras))
    second = all(w in ("2nd", "second", "another") for w, _a, _p in extras)
    many = len(set(a for _w, a, _p in extras)) > 1
    if cost == 0 and kind not in ("", "none") and (_PARKING_FREE.search(low) or _PARK_ONE_INCLUDED.search(low) or _GARAGE_SAYS_INCLUDED.search(low) or _PARKING_FREE_AFTER.search(low)):
        who = "a second space is" if second and not many else ("more spaces are" if many else "an extra space is")
        what = "The second space is" if second and not many else ("The extra spaces are" if many else "The extra space is")
        return (f"The listing says one parking space is included and {who} {prices}. {what} optional, so it is not counted in the monthly cost. "
                "Ask the price if you will have two cars.")
    who = "extra parking spaces cost" if many else "an extra parking space costs"
    return (f"The listing says {who} {prices}. It is optional, so it is not counted in the monthly cost. Ask the price if you will have more than one car.")


_PARKING_PROMO = re.compile(r"\(?[ \t]*(?:\b(?:free|waived)[ \t]+(?:for[ \t]+)?(?:the[ \t]+)?(?:first|1st|initial)[ \t]+(?:\d{1,2}|one|two|three|four|five|six|twelve)[ \t]+(?:months?|weeks?|mos?\b)"
                            r"|\b(?:first|1st)[ \t]+(?:\d{1,2}|one|two|three|four|five|six|twelve)[ \t]+(?:months?|weeks?)[ \t]+(?:are[ \t]+|is[ \t]+)?(?:free|waived)\b"
                            r"|\b(?:\d{1,2}|one|two|three|four|five|six|twelve)[ \t]+months?[ \t]+free\b)[ \t]*\)?", re.I)


_RW_PER = r"(?:[ \t]*(?:/[ \t]*mo\w*|per[ \t]+month|a[ \t]+month|monthly))?"
_RW_GARAGE = r"(?:an?[ \t]+|the[ \t]+)?(?:(?:attached|detached|covered|private|\d[- ]car|1[- ]car|2[- ]car)[ \t]+)*(?:garage|carport|covered parking|parking)"
_RENT_WITH_GARAGE = (
    re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+|\d{3,5})(?:\.\d\d)?" + _RW_PER + r"[ \t]*(?:,|/|\(?[ \t]*or)[ \t]*\$\s?(\d{1,3}(?:,\d{3})+|\d{3,5})(?:\.\d\d)?" + _RW_PER
               + r"[ \t]*(?:rent[ \t]*)?(?:with|w/|including|plus)[ \t]+" + _RW_GARAGE + r"\)?", re.I),
    re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+|\d{3,5})(?:\.\d\d)?" + _RW_PER + r"[ \t]*(?:rent[ \t]*)?(?:without|w/o|no)[ \t]+" + _RW_GARAGE
               + r"[ \t,;/]*(?:or[ \t]+|and[ \t]+)?\$\s?(\d{1,3}(?:,\d{3})+|\d{3,5})(?:\.\d\d)?" + _RW_PER + r"[ \t]*(?:rent[ \t]*)?(?:with|w/|including)[ \t]+" + _RW_GARAGE + r"\)?", re.I),
)


def _rent_with_garage(text: str) -> tuple[str, str] | None:
    """Cycle 23: "Rent $2,100 or $2,350 with garage": the second figure is the rent with a garage, never a garage cost. Returns (the text with that
    phrase blanked so no parking is read from it, a plain note) or None."""
    for rx in _RENT_WITH_GARAGE:
        m = rx.search(text)
        if not m:
            continue
        a, b = (float(g.replace(",", "")) for g in m.groups())
        if b <= a:
            continue
        note = (f"The listing gives the rent as ${a:,.0f}, or ${b:,.0f} with a garage. The ${b:,.0f} is the rent with the garage, not a separate garage cost, "
                f"and the garage is optional, so it is not added to the monthly cost. Ask if the garage is the extra ${b - a:,.0f} a month.")
        return text[:m.start()] + " " * (m.end() - m.start()) + text[m.end():], note
    return None


_PARKING_ZERO_THEN = re.compile(r"\$\s?0(?:\.00)?(?![\d.])[ \t]*(?:for|during|in)[ \t]+(?:the[ \t]+)?(?:first|1st|initial)[ \t]+(year|\d{1,2}[ \t]+months?|(?:one|two|three|four|five|six|twelve)[ \t]+months?)[ \t]*[,;(\-]?[ \t]*"
                                r"(?:then|after(?:wards?)?|and[ \t]+then|and[ \t]+after(?:wards?)?)[ \t,:]*(?:it(?:'s|[ \t]+is)?[ \t]+|is[ \t]+)?\$\s?(\d{2,4})(?:\.\d\d)?(?![\d,])"
                                r"(?![ \t]*(?:/[ \t]*y|per[ \t]+y|a[ \t]+y|yearly|annual))", re.I)
_PARKING_SECOND_ONLY = re.compile(r"(?:\b(?:required|mandatory|needed|only[ \t]+required|only[ \t]+needed)\b[^.\n;|$]{0,20}?\b(?:for|if)\b[^.\n;|$]{0,25}?\b(?:2nd|second|third|additional|extra|another)[ \t]+(?:car|vehicle|space|spot|stall)s?(?:[ \t]+only)?"
                                  r"|\bonly[ \t]+(?:required[ \t]+)?(?:for|if)\b[^.\n;|$]{0,25}?\b(?:2nd|second|third|additional|extra|another)[ \t]+(?:car|vehicle|space|spot|stall)s?"
                                  r"|\b(?:2nd|second|third|additional|extra|another)[ \t]+(?:car|vehicle)s?[ \t]+only\b)", re.I)
_PX_MONEY_PERIOD = re.compile(r"\$\s?(\d{1,4})(?:\.\d\d)?(?![\d,])((?:[ \t]*/[ \t]*(?:mo\w*|yr|year)|[ \t]+per[ \t]+(?:month|mo|year|yr)|[ \t]+a[ \t]+(?:month|year)|[ \t]+monthly|[ \t]+yearly)?)", re.I)


def _parking_second_only(text: str) -> tuple[str, str] | None:
    """Cycle 24: "Parking in the garage is $85/month (required for 2nd car only)": the price is owed only with a second car, so for a one-car household it
    is optional. The price may sit in the sentence before ("Garage: $85/month. Only required if you have a second vehicle."). Returns (the text with
    that price and phrase blanked, one short note) or None."""
    clauses: list[tuple[int, str]] = []
    for sm in re.finditer(r"[^\n|;]+", text):
        for part in re.finditer(r"(?:[^.]|\.(?=\d))+", sm.group(0)):
            clauses.append((sm.start() + part.start(), part.group(0)))
    for i, (base, clause) in enumerate(clauses):
        pm = _PARKING_SECOND_ONLY.search(clause)
        if not pm:
            continue
        at, src = base, clause
        am = _PX_MONEY_PERIOD.search(clause)
        if am and am.start() < pm.end() and am.end() > pm.start():
            continue
        if not am or not _PX_CONTEXT.search(clause):
            if i == 0:
                continue
            at, src = clauses[i - 1]
            am = _PX_MONEY_PERIOD.search(src)
            if not am or not _PX_CONTEXT.search(src):
                continue
        value, per = float(am.group(1)), " ".join(am.group(2).split()).lower()
        amount = f"${value:,.2f}" if value != int(value) else f"${value:,.0f}"
        when = " a year" if re.search(r"y", per) else " a month" if per else ""
        blank = text[:at + am.start()] + " " * (am.end() - am.start()) + text[at + am.end():]
        blank = blank[:base + pm.start()] + " " * (pm.end() - pm.start()) + blank[base + pm.end():]
        what = "garage" if re.search(r"\bgarage\b", src, re.I) else "carport" if re.search(r"\bcarport\b", src, re.I) else "parking"
        return blank, (f"The listing says the {what} is {amount}{when} but required for a second car only. It is optional for one car, so it is not counted in the monthly cost. "
                       "Ask what parking costs if you have one car.")
    return None


_Q_TOPIC = re.compile(r"\b(?:park(?:ing)?|garage|carport|driveway|pets?|dogs?|cats?|animals?|yard)\b", re.I)
_Q_SENTENCE = re.compile(r"[^.!?\n|;]*\?(?=[ \t]*(?:$|\n|\||(?-i:[A-Z])|[\"'\u201c\u2018\-*\u2022]|(?:please|pls|ask|call|contact|inquire|enquire|email|e-mail|text|reach|check|varies|depends|tbd|see)\b))|[^.!?\n|;]*\b(?:please\s+ask|ask\s+us\s+(?:about|if|whether))\b[^.!?\n|;]*[.!]?", re.I)


def _drop_question_sentences(text: str) -> tuple[str, list[str]]:
    """Cycle 25: a sentence that ends in "?" or says "please ask" about parking, pets or a yard is a question, not a fact. It is
    blanked before the parking, pet and yard readers run, so it sets nothing. Returns (the text, one short note per topic)."""
    topics: list[str] = []
    quoted: list[str] = []

    def blank(m: re.Match[str]) -> str:
        sentence = m.group(0)
        found = {("parking" if re.match(r"park|garage|carport|driveway", w, re.I) else "yard" if w.lower() == "yard" else "pets")
                 for w in (x.group(0) for x in _Q_TOPIC.finditer(sentence))}
        if not found:
            return sentence
        for t in ("parking", "pets", "yard"):
            if t in found and t not in topics:
                topics.append(t)
        q = " ".join(sentence.split()).strip(" -*\u2022:")
        if q and len(q) <= 90 and q not in quoted:
            quoted.append(q)
        return " " * len(sentence)

    cleaned = _Q_SENTENCE.sub(blank, text)
    if not topics:
        return text, []
    names = " and ".join(topics) if len(topics) < 3 else "parking, pets and yard"
    said = (" (" + ", ".join(f'"{q}"' for q in quoted[:3]) + ")") if quoted else ""
    return cleaned, [f"The listing only asks about {names}{said}, a question and not an answer, so nothing is saved for {'it' if len(topics) == 1 else 'them'}. Ask the landlord."]


_UPGRADE_WORDS = re.compile(r"\b(?:reserved|covered|garage|carport|premium|heated|underground|indoor|upgrade|private|assigned|attached)\b", re.I)
_FREE_ITEM = re.compile(r"\$\s?0(?:\.00)?(?![\d,]|\.\d)|\bfree\b|\bno[ \t]+(?:extra[ \t]+)?(?:charge|cost|fee)\b|\bincluded\b", re.I)
_PLAIN_SPOT = re.compile(r"\b(?:surface|lot|street|open|off[- ]?street|outdoor|uncovered|on[- ]?site|driveway|parking)\b", re.I)
_ITEM_PRICE = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d\d))?(?!\d)\s*(/\s*(?:yr|year)|per\s+year|a\s+year|annually|yearly)?", re.I)


def _parking_free_plus_upgrade(text: str) -> tuple[str, float, list[str]] | None:
    """Cycle 25: "Surface lot $0. Reserved covered spot $65/mo", "Free lot parking | Garage $150/mo". A free spot offered beside a priced
    upgrade (reserved, covered, garage, premium) is the parking (cost $0) and the upgrade is optional: one note names it, it is never counted."""
    free: list[str] = []
    upgrades: list[tuple[str, float, bool]] = []
    text = re.sub(r"\(\s*(?:free|included|no[ \t]+(?:extra[ \t]+)?(?:charge|cost|fee))\b[^()\n]*\)", " free ", text, flags=re.I)  # "surface lot (free)"
    text = re.sub(r"(?<![\w$])\$0(?:\.00)?(?![\d.,])[ \t]*\(([^()\n$]{2,30})\)", r"free \1", text)  # "$0 (open lot)" is a free open lot
    for raw in re.split(r"[()]|\s+or\s+|\n|\s\|\s|;|\.(?=\s|$)|,(?!\d{3})(?=[^,;|\n.]*(?:\$|\b(?:reserved|covered|garage|carport|premium|heated|underground|indoor|upgrade|private|assigned|attached|free|included|surface|street|open[ \t]+lot)\b))|\s+-\s+|\s+/\s+|[•*][ \t]*", text):
        item = re.sub(r"^[\s\-*\u2022]*(?:parking(?:\s+(?:options?|types?))?\s*[:\-]\s*)?", "", raw.strip(), flags=re.I)
        if not item or not re.search(r"\bparking\b|\bspots?\b|\bspaces?\b|\blot\b|\bgarage\b|\bcarport\b|\bstreet\b|\bdriveway\b|\b(?:covered|reserved|premium|heated|underground|indoor|upgrade)\b[^\n]{0,12}\$|\$[^\n]{0,12}\b(?:covered|reserved|premium|heated|underground|indoor|upgrade)\b", item, re.I) \
                and not re.search(r"\bparking\b[^\n]{0,6}\$0\b", raw, re.I):
            continue
        pm = _ITEM_PRICE.search(item)
        price = float(pm.group(1).replace(",", "") + ("." + pm.group(2) if pm.group(2) else "")) if pm else None
        if price is not None and price > 0 and _UPGRADE_WORDS.search(item) and not _PARKING_REQUIRED.search(item):
            yearly = bool(pm.group(3))
            upgrades.append((re.sub(r"\s*[:\-=(]*\s*\$.*$", "", item).strip(" :-(") or "an upgraded spot", price, yearly))
        elif (price == 0 or (price is None and _FREE_ITEM.search(item))) and (_PLAIN_SPOT.search(item) or re.search(r"\bspots?\b|\bspaces?\b", item, re.I) or re.search(r"\bparking\b", raw, re.I)) and not _UPGRADE_WORDS.search(item):
            free.append(item)
        elif price is not None and price > 0:
            return None  # another priced spot that is not an upgrade: leave it to the other readers
    if not free or not upgrades:
        return None
    parts = []
    for name, price, yearly in upgrades:
        name = re.sub(r"^(?:an?|the)\s+", "", name.lower()) or "upgraded spot"
        name = re.sub(r"^[a-z][a-z ]{0,24}:\s*(?=\S)", "", name) or name  # "amenities: garage" names the garage
        if re.fullmatch(r"(?:covered|reserved|premium|heated|underground|indoor|private|assigned)", name):
            name += " parking"
        parts.append(f"{name} (${price:,.2f}".replace(".00", "") + (" a year)" if yearly else " a month)"))
    kind = _parking_kind_words(free[0].lower()) or ("lot" if _PLAIN_SPOT_KIND.search(free[0]) else "")  # "Parking $0 first spot": no kind is named, so none is saved
    note = (f"The listing also offers an upgrade: {' and '.join(parts)}. It is optional, so it is not counted in the monthly cost, and the free parking is the one saved. "
            "If you want the upgrade, ask the landlord what it includes.")
    return kind, 0.0, [note]


_PARK_RANGE = re.compile(r"\bparking\b[^\n.;|$]{0,25}?\$\s?(\d{1,4}(?:\.\d\d)?)[ \t]*(?:/[ \t]*mo\w*|per[ \t]+month|a[ \t]+month|monthly)?[ \t]*(?:-|\u2013|\u2014|to)[ \t]*\$\s?(\d{1,4}(?:\.\d\d)?)(?![\d,])", re.I)


def _parking_range(text: str) -> tuple[str, float | None, list[str]] | None:
    """Cycle 25: "Parking $0 - $250 depending on spot". The spot decides the price, so a range that starts at $0 leaves the parking cost unknown with
    one note that quotes both figures. A range that starts above $0 counts the higher figure (the most you could pay)."""
    m = _PARK_RANGE.search(text)
    if not m:
        return None
    low_v, high_v = float(m.group(1)), float(m.group(2))
    if high_v <= low_v:
        return None
    a, b = f"${low_v:,.2f}".replace(".00", ""), f"${high_v:,.2f}".replace(".00", "")
    kind = _parking_kind_words(text.lower())
    if low_v == 0:
        return kind, None, [f"The listing gives parking as {a} to {b} a month depending on the spot, so no single parking cost is filled in. Check which spot you would get."]
    return kind or "lot", high_v, [f"The listing gives parking as {a} to {b} a month. The higher {b} is counted in the monthly cost. Ask which price you would pay."]


_PLAIN_SPOT_KIND = re.compile(r"\b(?:surface|lot|street|open|off[- ]?street|outdoor|uncovered|on[- ]?site|driveway)\b", re.I)
_PARKING_NO_DOLLAR = re.compile(r"\b((?:garage |covered |reserved )?parking(?: fee| rate| cost)?[ \t]*[:\-]?[ \t]*)(\d{2,4}(?:\.\d\d)?)(?=[ \t]*(?:/[ \t]*mo\w*|per[ \t]+month|a[ \t]+month|monthly)\b)", re.I)


_PFF_SECOND = re.compile(r"\b(?:2nd|second|3rd|third|another|additional|extra|add'l|guest|visitor)\b", re.I)
_PFF_NOUN = re.compile(r"\b(?:parking|spots?|spaces?|stalls?|garages?|carports?|driveways?|lot|street)\b", re.I)
_PFF_FREE = re.compile(r"\bfree\b|\bincluded\b|(?<![\w$])\$\s?0(?:\.00)?(?![\d,.])|\bno[ \t]+(?:extra[ \t]+)?(?:charge|cost|fee)\b", re.I)
_PFF_FREE_NOT = re.compile(r"\bfree[ \t]+(?:wi-?fi|internet|water|rent|cable|trash|laundry|heat|utilit\w*|storage|month|tours?)|\b(?:first|1st)[ \t]+(?:\d+[ \t]+)?(?:months?|year|weeks?)\b|\btrial\b|\bif\b|\bwaitlist\b|\boptional\b|\bavailable\b|\b(?:on|by|upon)[ \t]+request\b", re.I)
_PFF_TOPIC = re.compile(r"\b(?:pets?|dogs?|cats?|deposit|application|admin|utilit\w*|storage|trash|internet|cable|laundry|amenity|bike|key|fob|move)\b", re.I)
_PFF_AMT = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d\d))?(?!\d)")


def _parking_free_with_priced(text: str) -> tuple[str, float, list[str]] | None:
    """Cycle 27: a free (or included) spot, or a free first or assigned spot, beside a second, guest or covered spot with a price
    ("Parking: 1 free assigned spot, second spot $75, covered $100", "Attached 2-car garage included, uncovered guest spot $50/mo",
    "garage, driveway free"). The free spot is the parking at $0. Each priced extra is optional and named in one note; an extra with
    no price is named too. Nothing is counted for the extras. Returns None when any parking price in the line is not clearly an extra."""
    if re.search(r"\bparking\b[^\n.]{0,40}\$\s?[1-9]\d*[^\n.]{0,25}\b(?:required|mandatory)\b|\b(?:required|mandatory)\b[^\n.]{0,25}\bparking\b[^\n.]{0,30}\$\s?[1-9]", text, re.I):
        return None  # a required parking price beside a free spot: the listing disagrees with itself, so the other readers decide
    blocks: list[str] = []
    for ln in text.split("\n"):
        if blocks and re.match(r"\s*[-*\u2022]\s", ln):
            blocks[-1] += " ; " + ln  # a bullet list under "Parking:" is one block
        else:
            blocks.append(ln)
    for line in blocks:
        if not _PFF_NOUN.search(line):
            continue
        line = re.sub(r"\(([^()$\n]{1,30})\)", lambda m: " " + m.group(1) + " " if not _PFF_SECOND.search(m.group(1)) else m.group(0), line)  # "1 included space (covered)" is one item
        items = [x.strip(" \t-*\u2022:") for x in re.split(r"\||;|\.(?=\s|$)|,(?!\d{3})|\s+-\s+|[()]|\s+(?:and|but|plus)\s+(?=\$|(?:a[ \t]+)?(?:second|2nd|covered|garage|reserved|additional|extra|free|driveway|street|lot|surface|carport)\b)", line) if x.strip(" \t-*\u2022:")]
        free: list[str] = []
        extras: list[tuple[str, float]] = []
        unpriced: list[str] = []
        ok = True
        off = False  # after a pet, storage or fee item, a bare "second $15" belongs to that topic, not to parking
        for it in items:
            il = it.lower()
            il = re.sub(r"^(?:parking(?:[ \t]+(?:options?|types?))?[ \t]*[:\-][ \t]*)", "", il)
            if _PFF_TOPIC.search(il) and not _PFF_NOUN.search(il):
                off = True
                continue
            if _PFF_NOUN.search(il):
                off = False
            elif off:
                continue
            pm = _PFF_AMT.search(il)
            if pm:
                amount = float((pm.group(1)).replace(",", "") + ("." + pm.group(2) if pm.group(2) else ""))
                if re.search(r"/\s*(?:yr|year)|per\s+year|a\s+year|annual|yearly|/\s*\d\s*(?:br|bd|bed)|deposit|one[- ]time|setup", il[pm.end():pm.end() + 20]) or _PFF_TOPIC.search(il):
                    if _PFF_NOUN.search(il):
                        ok = False
                    continue
                if amount == 0:
                    if _PFF_NOUN.search(il) and not _PFF_FREE_NOT.search(il):
                        free.append(il)
                    continue
                if (_PFF_SECOND.search(il) or _UPGRADE_WORDS.search(il)) and not _PARKING_REQUIRED.search(il) and not _PFF_FREE_NOT.search(il):
                    label = re.sub(r"\s*[:\-=]*\s*(?:for\s+|at\s+|is\s+)?\$.*$", "", il).strip(" :-,") or "a second spot"
                    label = re.sub(r"^(?:an?|the)\s+", "", label)
                    extras.append((label, amount))
                elif _PFF_NOUN.search(il):
                    ok = False  # a priced spot that is not clearly an extra
                continue
            if _PFF_FREE.search(il) and _PFF_NOUN.search(il) and not _PFF_FREE_NOT.search(il) and not _PFF_SECOND.search(il):
                if re.search(r"\bnot\s+included\b|\bno\s+(?:free\s+)?parking\b|\bnot\s+free\b", il):
                    ok = False
                else:
                    free.append(il)
            elif re.search(r"\b(?:garages?|carports?|covered)\b", il) and not _PFF_FREE_NOT.search(il) and not re.search(r"\b(?:no|not|without|none)\b", il):
                unpriced.append(il)
        if not ok or not free or not (extras or unpriced):
            continue
        if any(re.search(r"\b(?:garages?|carports?)\b", f) for f in free):
            pass
        elif unpriced and not extras and not any(re.search(r"\b(?:driveway|street|lot|surface|open|uncovered|assigned|spots?|spaces?)\b", f) for f in free):
            continue
        kind = _parking_kind_words(" ".join(free)) or "lot"
        if kind in ("garage", "covered") and not any(re.search(r"\b(?:garages?|carports?|covered)\b", f) for f in free):
            kind = "lot"
        notes = []
        if extras:
            parts = " and ".join(f"{lb} (${v:,.2f} a month)".replace(".00", "") for lb, v in extras)
            notes.append(f"The listing gives free parking (saved at $0) and also offers {parts}. These are optional, so they are not counted in the monthly cost. Ask the price if you want one.")
        if unpriced and not any(re.search(r"\b(?:garages?|carports?)\b", f) for f in free):
            names = " and ".join(sorted({("garage" if re.search(r"garage", u) else "carport" if re.search(r"carport", u) else "covered parking") for u in unpriced}))
            notes.append(f"The listing also mentions {names} but gives no price for it. The free parking is the one saved at $0. Ask if the {names} costs extra.")
        return kind, 0.0, notes
    return None


def _parking_detail(text: str) -> tuple[str, float | None, list[str]]:
    text = _PARKING_NO_DOLLAR.sub(lambda m: m.group(1) + "$" + m.group(2), text)  # cycle 26: "Parking 85/mo" has no dollar sign but is a price a month
    text = _PARKING_PROMO.sub(" ", text)  # cycle 22: a short free offer ("free for first 6 months") never makes the parking free
    zero_notes: list[str] = []
    zm = _PARKING_ZERO_THEN.search(text)
    if zm and _PX_CONTEXT.search(text[max(0, zm.start() - 80):zm.start()]):  # cycle 24: "$0 for first year, then $90": the ongoing $90 is the parking cost
        text = text[:zm.start()] + f"${float(zm.group(2)):.0f}/month" + text[zm.end():]
        zero_notes.append(f"The listing says the parking is $0 for the first {zm.group(1).lower()}, then ${float(zm.group(2)):,.0f}. The ongoing ${float(zm.group(2)):,.0f} a month is counted in the monthly cost, "
                          "not the first-period $0. Ask if the $" + f"{float(zm.group(2)):,.0f} is a monthly price.")
    second_only = _parking_second_only(text)
    if second_only:
        text = second_only[0]
        zero_notes.append(second_only[1])
    kind, cost, notes = _parking_detail_inner(text)
    if kind == "lot" and re.search(r"\bdeeded\b", text, re.I) and not _parking_kind_words(re.sub(r"\bdeeded\b", " ", text.lower())) \
            and not re.search(r"\b(?:driveway|off[- ]?street|lot|surface|street)\b", text, re.I):
        kind = ""  # cycle 24: "1 deeded parking space" is its own thing: the schema has no deeded kind, so the kind is left empty and named in a note
        notes = notes + ["The listing says the parking is a deeded space" + (" that comes with the home, so there is no monthly parking charge" if cost == 0 else "") + ". "
                         "It does not say if the space is a garage, covered or outdoor, so check which one."]  # cycle 25: no "left empty / ask" words: an included deeded space is not a missing parking cost
    return kind, cost, zero_notes + notes


def _parking_detail_inner(text: str) -> tuple[str, float | None, list[str]]:
    low = text.lower()
    per_car = _parking_per_car(low)
    if per_car:
        first, second, rest_low = per_car
        kind, cost = _parking_kind_cost(rest_low, first)
        notes = []
        if second is not None:
            notes.append(f"The listing gives a second car as ${second:,.0f}. A second car costs ${second:,.0f} a month more, and it is not counted in the monthly cost, "
                         f"which holds the first car's ${first:,.0f}. Ask the price if you will have two cars.")
        else:
            others = sorted({v for v, _o, _c, _u in (_try(lambda: _parking_prices(low)) or []) if abs(v - first) > 0.5})
            if others:  # cycle 21: "garage parking $110/mo (1st car $100 if on a 12 mo lease)": the first car's price is counted, the other price is named
                notes.append(f"The listing gives parking as ${others[0]:,.0f} a month and the first car as ${first:,.0f}. The first car's ${first:,.0f} is counted in the monthly cost "
                             f"and the ${others[0]:,.0f} is not. Ask which price you would pay and what the condition is.")
        return kind, (cost if cost is not None else first), notes
    inc = _parking_included_plus_second(low)
    if inc:
        return inc
    fwp = _parking_free_with_priced(text)
    if fwp:
        return fwp
    rng = _parking_range(text)
    if rng:
        return rng
    upg = _parking_free_plus_upgrade(text)
    rent_garage = _rent_with_garage(text)
    if rent_garage:
        text = rent_garage[0]
    text, extras = _parking_extras(text)  # cycle 23: an extra, second or "or rent a space" price is optional in every layout; it is taken out before the rest is read
    low = text.lower()
    kind, cost, notes = _parking_detail_core(text, low)
    if upg and not (cost == 0 and kind in ("lot", "street")):
        return upg  # cycle 25: the free spot is the parking and the priced upgrade is optional (an older reading that already ended at the free spot is kept)
    if extras:
        notes = [n for n in notes if "gives no price" not in n] + [_parking_extras_note(extras, kind, cost, low)]  # the price that note missed is in the extras note
    if rent_garage:
        notes = notes + [rent_garage[1]]
    return kind, cost, notes


def _parking_detail_core(text: str, low: str) -> tuple[str, float | None, list[str]]:
    opts = _parking_options(low)
    if opts:
        return opts
    prices = _parking_prices(low)
    notes: list[str] = []
    rest = low
    for value, optional, clause, unit in prices:
        if optional:
            what = _parking_what(clause)
            if unit == "year":
                notes.append(f"{_a(what)} is available for ${value * 12:,.0f} a year. It looks optional, so it is not counted in the monthly cost. Ask if it is required.")
            else:
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
    required = [v for v, o, _c, _u in prices if not o]
    kind, cost = _parking_kind_cost(rest, required[0] if required else None)
    if cost is None and required:
        cost = required[0]
    for value, optional, _clause, unit in prices:
        if not optional and value == required[0] and unit == "year":
            notes.append(f"The listing gives the parking as ${value * 12:,.0f} a year, so ${value:,.2f} a month is counted. Check that the yearly amount is right.")
        elif not optional and value == required[0] and unit == "each":
            notes.append(f"The listing says the parking is required at that price for each space, so ${value:,.0f} a month (all the spaces) is counted.")
    if cost is None and any(o for _v, o, _c, _u in prices) and _PARKING_FREE.search(low):
        cost = 0.0
    if not kind and cost == 0 and _PARKING_FREE.search(low):
        kind = "lot"  # "Parking included (garage $90 optional)": the included spot, whose type the listing does not give, is a plain lot spot; the garage is the extra
    if cost is None and kind == "lot" and not prices and re.search(r"\bdriveway\b", low) and not re.search(r"\bdriveway\b[^.\n;]{0,40}\$", low):
        notes.append("The listing mentions driveway parking but gives no price. The parking cost is left empty. Ask if it costs extra.")
    if kind == "none" and re.search(r"\bparking\s*(?:is\s*)?(?:not\s+available|unavailable)\b(?!\s+(?:on|along|at)\s+(?:the\s+)?(?:street|curb|road))|\bno\s+parking\s+available\b", low):
        notes.append("The listing says there is no parking.")
    return kind, cost, notes


def _parking(text: str) -> tuple[str, float | None]:
    kind, cost, _notes = _parking_detail(text)
    return kind, cost


def _parking_kind_cost(text: str, priced: float | None) -> tuple[str, float | None]:
    low = text.lower()
    kind = ""
    if re.search(r"\bparking\s*(?:is\s*)?(?:not\s+available|unavailable)\b(?!\s+(?:on|along|at)\s+(?:the\s+)?(?:street|curb|road))|\bno\s+parking\s+available\b", low) and not re.search(r"\bgarage\b", low):
        return "none", None
    label = re.search(r"\bparking(?: features?| type)?\s*[:\-]\s*([^\n.;]{0,40})", low)
    if label and not re.search(r"\bgarage\b", low):
        v = label.group(1)
        segs = re.split(r"[,/]|\bor\b|\band\b", v)
        if len(segs) > 1 and re.search(r"\b(?:surface|lot|street|off[- ]?street|driveway)\b", segs[0]):
            # "Parking: surface lot included, covered $35": the first part is the parking, a later priced or optional part is an extra
            keep = [segs[0]] + [x for x in segs[1:] if not re.search(r"\$|\b(?:optional|available|extra|additional|upgrade)\b", x)]
            v = ",".join(keep)
        if re.search(r"\bcarport|\bcovered", v):
            kind = "covered"
        elif re.search(r"\bstreet\b", v) and not re.search(r"off[- ]?street", v):
            kind = "street"
        elif re.search(r"\blot\b|off[- ]?street|surface|assigned|reserved|driveway|included|free|yes|on[- ]?site", v):
            kind = "lot"
        elif re.match(r"\s*(?:none|no)\b(?!\s+(?:extra\s+|additional\s+)?(?:charge|cost|fee))", v):
            kind = "none"
    if kind:
        pass
    elif re.search(r"\b(?:attached |detached |private |heated |\d[- ]car |reserved |covered )?garage\b(?! door| apartment)", low) \
            and not re.search(r"\bno\s+garage\b|\bgarage\s*[:\-]\s*(?:no|none)\b", low):
        kind = "garage"
    elif re.search(r"\bcarports?\b|\bcovered\s+(?:parking|spaces?|spots?)\b", low):
        kind = "covered"
    elif re.search(r"\bparking\s+(?:is\s+)?(?:only\s+)?on\s+the\s+street\b", low) and not re.search(r"off[- ]?street", low):
        kind = "street"  # "Free parking on the street"
    elif re.search(r"\b(?:off[- ]?street|surface|free|assigned|reserved|on[- ]?site|private|ample|plenty of|paved|resident)\s+parking\b|\b(?:surface|gravel|paved|resident|tenant)?\s*lot\s+parking\b|\bparking\s+(?:lot|included|available|space|spot|provided|on[- ]?site)|\bdriveway\b|\bparking\s*[:\-]\s*(?:lot|yes|included|free|assigned|surface)|\b\d\s*parking (?:spaces?|spots?)\b|\b(?:surface|gravel|paved)\s+lot\b|\blot\s+(?:spots?|spaces?)\b", low):
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
    if cost is None and kind and kind != "none" and re.search(r"\b(?:off[- ]?street|on[- ]?site)\s+parking\s+(?:for|fits)\s+(?:up to\s+)?(?:\d|one|two|three|four)\s+(?:cars?|vehicles?)\b", low) \
            and not re.search(r"\bparking\b[^.\n;]{0,40}(?:\$|\b(?:fee|permit|extra|additional|optional|available|charge|cost)\b)|\b(?:fee|permit|extra|additional|optional|charge|cost)\b[^.\n;]{0,20}\bparking\b", low):
        cost = 0.0  # "Off-street parking for two cars": a plain statement with no charge named
    if cost is None and re.search(r"\bfree (?:off[- ]?street |on[- ]?street |street |on[- ]?site |surface |assigned |resident |tenant )?parking\b|\bparking\s*(?:is\s*)?(?:included|free|at no (?:extra )?charge)\b|\bparking\s*[:\-]\s*(?:free|included)\b|\b(?:\d+|one|two|three|four)\s+(?:[a-z-]+\s+){0,2}(?:spaces?|spots?|stalls?)\s+(?:is\s+|are\s+)?(?:included|free)\b", low):
        cost = 0.0
    if cost is None and kind and kind != "none" and re.search(r"\bparking\b(?:(?![,&]|\band\b|\bwater\b|\bheat\b|\btrash\b|\bgas\b|\belectric|\butilit|\bsewer\b|\binternet\b|\bwifi\b)[^.\n;$]){0,30}\bincluded\b(?![^.\n;]{0,12}\b(?:for|at|with)\s+\$)(?<!not included)", re.sub(r"\bnot\s+included\b|\bincluded\s+in\s+(?:the\s+)?(?:app|application)", " ", low)):
        cost = 0.0  # "Off-street parking for 2 cars included"
    if cost is None and re.search(r"\bparking[ \t]*[:\-][ \t]*(?:(?:on[- ]?)?street|(?:surface[ \t]+)?lot|driveway|off[- ]?street|covered|garage)[ \t]*[,;(\-][ \t]*\$\s?0(?:\.00)?(?!\d|\.\d|,\d)", low):
        kind = kind or _parking_kind_words(low) or "lot"
        cost = 0.0  # "Parking: street, $0"
    if cost is None and re.search(r"\b(?:street|lot|surface|driveway|off[- ]?street|covered|garage)[ \t]+parking[ \t:\-]*\$\s?0(?:\.00)?(?!\d|\.\d|,\d)", low):
        cost = 0.0  # "Street parking $0"
    if cost is None and re.search(r"\bparking\b[ \t:,\-]*(?:(?:required|mandatory|fees?|costs?|rates?|rent|is|for[ \t]+(?:all[ \t]+)?residents|per[ \t]+month)[ \t:,\-]*){0,3}\$\s?0(?:\.00)?(?!\d|\.\d|,\d)", low):
        cost = 0.0  # "Parking $0 included": the listing says it is free; cycle 23: "Parking required: $0 (street)" too
        if not kind:  # cycle 21: "Parking $0, street" names its kind right after the price
            zm = re.search(r"\bparking\b(?:[ \t]+[a-z]+){0,3}[ \t:,\-]*\$\s?0(?:\.00)?[ \t]*[,;(\-]?[ \t]*([^\n.;|]{0,30})", low)
            kind = (_parking_kind_words(zm.group(1)) if zm else "") or "lot"
    if cost is None and kind != "none" and re.search(r"(?:\bparking\b|\b(?:\d|one|two|three|four)[ \t]+(?:[a-z-]+[ \t]+){0,3}(?:spots?|spaces?|stalls?)\b)[^\n.;|$]{0,40}?[,:\-(]?[ \t]*\$\s?0(?:\.00)?(?!\d|\.\d|,\d)(?![ \t]*(?:[-\u2013\u2014]|to\b))", low):
        cost = 0.0  # cycle 25: "Parking: 1 off-street spot, $0" and "1 off-street parking space, $0": the listing gives $0
        kind = kind or _parking_kind_words(low) or "lot"
    if cost is None and kind and kind != "none" and re.search(r"\bparking\b[^.\n;$]{0,30}\b(?:at|for|with)\s+no\s+(?:extra\s+|additional\s+)?(?:charge|cost|fee)\b|\bno\s+(?:extra\s+|additional\s+)?(?:charge|cost|fee)\s+for\s+(?:\w+\s+){0,2}parking\b", low):
        cost = 0.0  # "Off-street parking for 2 cars at no charge"
    if cost is None and kind and kind != "none" and re.search(r"\bfree\b[ \t]*(?:\w+[ \t]+){0,2}?(?:lot|spots?|spaces?|stalls?|driveway|garage|carport)\b|\b(?:lot|spots?|spaces?|stalls?|driveway|garage|carport)\b[ \t]*[,:\-]?[ \t]*(?:is[ \t]+)?free\b(?![ \t]+(?:for|during|until|trial|first|if))", low):
        cost = 0.0  # cycle 19: "Surface lot, free" / "free off-street parking": stated free
    if cost is None and kind == "lot" and re.search(r"\bfree\s+(?:\w+\s+)?driveway\b|\bdriveway(?:\s+parking)?\s+(?:is\s+)?(?:free|included)\b", low):
        cost = 0.0  # "Free driveway parking"
    if cost is None and kind != "none" and _PARKING_FREE_AFTER.search(low):
        cost = 0.0  # cycle 20: "Off-street parking, free." / "Parking: off-street, no charge"
        kind = kind or "lot"
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


def _pets(text: str, weight_rules: bool = True) -> str:
    low = text.lower()
    low = _PET_LABEL_NO_OVER.sub(" ", low)  # "Pets: no pets over 25 lbs" and "Dogs: no pets over 70 lbs" are weight rules, not a no
    if re.search(r"\bno pets\b(?!\s+(?:restrictions?|limits?|problem|fee|(?:over|above|exceeding|larger|bigger|heavier|greater|more than|weighing|under)\b))|\bpets?\s*[:\-]?\s*(?:are\s+)?(?:not|never)\s+(?:allowed|permitted|accepted|welcome|ok|okay)\b|\bpets? (?:are )?(?:prohibited|banned|forbidden)\b|\bnot pet[- ]friendly\b|\bpets\s*[:\-]\s*(?:no\b(?!\s+(?:cats?|dogs?)\b)|none|not allowed)|\bpet policy\s*[:\-]\s*(?:no\b(?!\s+(?:cats?|dogs?)\b)|none|not allowed|not permitted)|\bno animals\b|\bpets?\s+no\s*(?:[.;,!\n|]|$)|(?<![\w-])(?<!not )(?<!not a )(?<!not an )(?<!isn.t )(?<!isn.t a )pet[- ]free\b(?![ \t]*(?:cats?|dogs?|rooms?|floors?|units?|wings?|zones?|areas?|section|buildings?[ \t]+(?:available|options?)))", low):
        return "none"
    work = low
    cats = dogs = False
    no_cats = re.search(r"\bno cats?\b(?!\s+(?:over|above|under|larger|bigger|heavier|exceeding|more))|\bcats? (?:are )?not (?:allowed|permitted|accepted)|\bno cats? allowed|\bcats?\s*[:\-]?\s*no\b(?![-\w])(?!\s*(?:over|above|under|larger|bigger|heavier|exceeding|more|breeds?|fee|deposit|rent|\w+\s+fee))|\bcats? (?:are )?(?:prohibited|banned|forbidden|not welcome)\b|\bcat[- ]free\b", work)
    no_dogs = re.search(r"\bno dogs?\b(?!\s+(?:over|above|under|larger|bigger|heavier|exceeding|more))|\bdogs? (?:are )?not (?:allowed|permitted|accepted)|\bno dogs? allowed|\bdogs?\s*[:\-]?\s*no\b(?![-\w])(?!\s*(?:over|above|under|larger|bigger|heavier|exceeding|more|breeds?|fee|deposit|rent|\w+\s+fee))|\bdogs? (?:are )?(?:prohibited|banned|forbidden|not welcome)\b|\bdog[- ]free\b", work)
    if re.search(r"\bcats? and dogs?\b|\bdogs? and cats?\b|\bcats?\s*(?:&|/|,)\s*dogs?\b|\bdogs?\s*(?:&|/|,)\s*cats?\b|\bcats?\s+(?:and|&)\s+(?:(?:small|medium|large|big|little|tiny|young|well[- ]behaved)\s+)*dogs?\b|\bdogs?\s+(?:and|&)\s+(?:(?:small|medium|large|big|little|tiny|young)\s+)*cats?\b|\ball pets\b|\bdogs? (?:are )?ok.{0,40}cats? (?:are )?ok|\bcats? (?:are )?ok.{0,40}dogs? (?:are )?ok", work):
        cats = dogs = True
    if re.search(r"(?<!\bno )(?<!\bnot )(?<!\bwithout )\b(?:one |a |1 )?(?:cats?|dogs?) or (?:one |a |1 )?(?:(?:small|medium|large|big|little|tiny|young|well[- ]behaved)\s+)*(?:dogs?|cats?)\b(?!\s+(?:is |are )?(?:not|prohibited|banned))", work) \
            and not re.search(r"\b(?:no|not|without)\s+(?:\w+\s+)?(?:cats?|dogs?) or\b", work):
        cats = dogs = True  # "We allow one cat or small dog": both kinds are taken (one animal of either kind)
    for gm in re.finditer(r"\bpet[- ]friendly\b|\bpets (?:ok|okay|allowed|welcome|accepted)\b(?!\s+(?:with|by|on|upon|subject to)\s+(?:landlord\s+|owner\s+|management\s+)?(?:approval|permission))|\bpets\s*[:\-]\s*(?:yes|ok|okay|allowed|welcome)\b", work):
        seg = work[max(work.rfind(c, 0, gm.start()) for c in ".;\n|!?") + 1:]
        seg = re.split(r"[.;\n|!?]", seg)[0]
        named = re.sub(r"\bno\s+(?:cats?|dogs?)\b|\b(?:cats?|dogs?)\s+(?:are\s+)?not\s+(?:allowed|permitted|accepted)", " ", seg)
        if not re.search(r"\b(?:cats?|dogs?)\b", named):  # "Pet friendly: cats ok" names the pets, so the general words add nothing
            cats = dogs = True
    if re.search(r"\bcats?\b(?:\s*(?:are|is))?\s*[:\-]?\s*(?:ok|okay|yes|fine|allowed|welcome|accepted|friendly|permitted)\b|\bcats? only\b|\bcat[- ]friendly\b|\bpurrr|\bcats?\s*[:\-]?\s*\$\s?\d", work):
        cats = True  # "Cats $200 deposit": a fee for cats means cats are taken
    if re.search(r"\bdogs?\b(?:\s*(?:are|is))?\s*[:\-]?\s*(?:ok|okay|yes|fine|allowed|welcome|accepted|friendly|permitted)\b|\bdogs? only\b|\bdog[- ]friendly\b|\bwoof|\bsmall dogs?\b|\bdogs? under\b|\bdogs?\s*[:\-]?\s*\$\s?\d|\bdogs?\s+(?:up to|under|less than|weighing|max(?:imum)?(?: of)?)\s+\d{1,3}\s*(?:lbs?|pounds?)\b", work):
        dogs = True
    if weight_rules and not _MAYBE_PETS.search(work) and re.search(r"\bno\s+dogs?[ \t]+(?:over|above|exceeding|larger than|bigger than|heavier than|more than|weighing over)[ \t]*\d{1,3}[ \t]*(?:lbs?\b|pounds?\b)", work):
        dogs = True  # cycle 19: "No dogs over 35 lbs" means dogs under 35 lb are taken
    if weight_rules and not _MAYBE_PETS.search(work) and re.search(r"\bno\s+cats?[ \t]+(?:over|above|exceeding|larger than|bigger than|heavier than|more than|weighing over)[ \t]*\d{1,3}[ \t]*(?:lbs?\b|pounds?\b)", work):
        cats = True
    if re.search(r"\bcats?\s+(?:up to|under|less than|below|weighing|max(?:imum)?(?: of)?)\s+\d{1,3}\s*(?:lbs?|pounds?)\b|\bcats?\b[^.\n;]{0,12}\b(?:ok|okay|allowed|welcome)\b[^.\n;]{0,10}\b\d{1,3}\s*(?:lbs?|pounds?)\b", work):
        cats = True  # "cats under 15 lbs", "cats ok 12 lb"
    if re.search(r"(?<![\w$.])(?:\d|one|two|three|four)\s+(?:dogs?)\s+(?:max(?:imum)?|only|limit|per\s+(?:unit|apartment|home|household))\b|\b(?:max(?:imum)?(?: of)?|limit(?: of)?|up to|no more than|at most)\s+(?:\d|one|two|three|four)\s+dogs?\b", work) \
            and not re.search(r"\bno\s+dogs?\b", work):
        dogs = True  # "1 dog max", "max 2 dogs"
    if re.search(r"(?<![\w$.])(?:\d|one|two|three|four)\s+(?:cats?)\s+(?:max(?:imum)?|only|limit|per\s+(?:unit|apartment|home|household))\b|\b(?:max(?:imum)?(?: of)?|limit(?: of)?|up to|no more than|at most)\s+(?:\d|one|two|three|four)\s+cats?\b", work) \
            and not re.search(r"\bno\s+cats?\b", work):
        cats = True  # "1 cat max", "max 2 cats"
    if re.search(_CAT_CHARGE, work):
        cats = True  # "Cat fee $150": a charge for cats means cats are taken
    if re.search(_DOG_CHARGE, work):
        dogs = True
    if re.search(r"\bcats?\s+(?:up to|max(?:imum)?(?: of)?|limit(?: of)?)\s+(?:\d|one|two|three|four)\b(?!\d|\s*(?:lbs?|pounds?|years?|yrs?|in\b|inch))", work):
        cats = True  # "Cats up to 2"
    if re.search(r"\bdogs?\s+(?:up to|max(?:imum)?(?: of)?|limit(?: of)?)\s+(?:\d|one|two|three|four)\b(?!\d|\s*(?:lbs?|pounds?|years?|yrs?|in\b|inch))", work):
        dogs = True
    if re.search(r"\bcats?\s*[:\-]\s*(?:up to\s+|max(?:imum)?(?: of)?\s+)?(?:\d|one|two|three|four)\b(?!\d|\s*(?:lbs?|pounds?|years?|yrs?|in\b|inch|%|/))(?![ \t]+(?:not|no)\b)", work):
        cats = True  # "Cats: 2 allowed"
    if re.search(r"\bdogs?\s*[:\-]\s*(?:up to\s+|max(?:imum)?(?: of)?\s+)?(?:\d|one|two|three|four)\b(?!\d|\s*(?:lbs?|pounds?|years?|yrs?|in\b|inch|%|/))(?![ \t]+(?:not|no)\b)", work):
        dogs = True  # "Dogs: 2 allowed, max 60 lbs each"
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
    if re.search(r"\bno\s+(?:cats?|dogs?)\s+(?:or|nor|and)\s+(?:cats?|dogs?)\b(?!\s+(?:over|above|under|larger|bigger|heavier|exceeding|more))", work):
        cats = dogs = False  # "No cats or dogs": neither is taken, and never "dogs only"
        if not re.search(r"\b(?:fish|birds?|caged|small animals?|reptiles?|hamsters?|rabbits?|other (?:pets|animals)|aquarium)\b", work):
            return "none"  # cycle 23: no dogs and no cats is no pets
    if not cats and not dogs and no_cats and no_dogs and not re.search(r"\b(?:fish|birds?|caged|small animals?|reptiles?|hamsters?|rabbits?|other (?:pets|animals)|aquarium)\b", work):
        return "none"  # cycle 23: "No cats. No dogs."
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
            base = _pets(piece, False)
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
    if not (clash or approval) and not _pets(text, False) and not any("no" in v or "yes" in v for v in stances.values()):
        negotiable = any("maybe" in v for v in stances.values())  # "Pets negotiable": not a yes, not a no
    if not (clash or approval or negotiable):
        return ""
    said = _quoted_pieces(quoted)
    who = _ask_who(text)
    if negotiable:
        if re.search(r"\bsmall\b", said, re.I):
            return f"The listing says small pets may be allowed ({said}), but that is not a yes. Pets is left empty, so ask {who} which pets are allowed and what they cost."
        return f"The listing says pets are negotiable ({said}). Pets is left empty, so ask {who} which pets are allowed and what they cost."
    if clash:
        return f"The listing is not clear about pets. It says {said}. Pets is left empty, so ask {who} which pets are allowed before you count on it."
    return f"The listing says pets depend on approval ({said}). Pets is left empty, so ask {who} which pets are allowed."


def _pets_soft_note(text: str) -> str:
    """"Cats welcome. Dogs considered case by case": cats is saved, and this says dogs are not a yes. "" when there is nothing to say."""
    stances, quoted = _pet_stances(text)
    soft = [sp for sp, v in stances.items() if "maybe" in v and "yes" not in v and "no" not in v
            and re.search(r"\b" + sp[:-1] + r"s?\b", text, re.I)]  # cycle 20: a species the listing never names ("Pets considered, one dog ok") is not talked about
    if not soft or not any("yes" in v for v in stances.values()):
        return ""
    names = " and ".join(sp for sp in soft)
    said = _quoted_pieces([q for q in quoted if _MAYBE_PETS.search(q)])
    return (f"The listing says {names} are considered case by case ({said}). Only the pets it clearly allows are saved, "
            f"so ask {_ask_who(text)} about {names}.")


_NO_SPECIES_MORE = re.compile(r"\b(cats?|dogs?)\s+(?:are\s+)?(?:prohibited|banned|forbidden|not\s+welcome)\b|\b(cat|dog)[- ]free\b", re.I)


def _pets_refused_kinds(text: str) -> list[str]:
    """Cycle 23: the kinds of pet the listing says no to ("Pets: no cats", "Dogs not permitted", "cats are prohibited"), as "cats" and "dogs"."""
    low = _PET_LABEL_NO_OVER.sub(" ", text)
    found: list[str] = []
    for m in [*_NO_SPECIES.finditer(low), *_LABELLED_NO.finditer(low), *_NO_SPECIES_MORE.finditer(low)]:
        word = next(g for g in m.groups() if g).lower().rstrip("s") + "s"
        if word not in found:
            found.append(word)
    return found


def _pets_no_species_note(text: str) -> str:
    """"Pets: no cats" with nothing said about dogs: pets stays empty (dogs are not mentioned), and this says what the listing refused so a renter
    with that pet is not left guessing. "" when both kinds or none are refused."""
    refused = _pets_refused_kinds(text)
    if len(refused) != 1:
        return ""
    sp = refused[0]
    other = "dogs" if sp == "cats" else "cats"
    return (f"The listing says no {sp}. It does not say if {other} are allowed, so pets is left empty. "
            f"If you have {'a cat' if sp == 'cats' else 'a dog'}, this place is not an option. Ask {_ask_who(text)} about {other}.")


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


_PC_SKIP = re.compile(r"\b(?:parking|garage|storage|utilit\w*|trash|hoa|internet|cable|application|admin\w*|security|lease|first month|last month|screening|background|move[- ]in)\b", re.I)
_PC_MONTHLY = re.compile(r"^[ \t]*(?:/[ \t]*mo\w*|per[ \t]+month|a[ \t]+month|each[ \t]+month|monthly|(?:pet[ \t]+)?rent\b|(?:pet[ \t]+)?(?:fee|charge)[ \t]+(?:per|a|each|/)[ \t]*(?:month|mo)\b)", re.I)
_PC_ONE_TIME = re.compile(r"^[ \t]*(?:one[- ]time[ \t]+|non[- ]?refundable[ \t]+)?(?:pet[ \t]+)?fee\b(?![ \t]*(?:/|per[ \t]+month|monthly|a[ \t]+month))", re.I)


def _pet_clause_charges(text: str) -> dict[str, float]:
    """Cycle 23: the charge words next to an amount in a sentence about cats, dogs or pets that never says "pet" before the amount:
    "Cats allowed with $300 deposit and $35 monthly fee" ($35 is the pet rent), "Pets: cats only, $20 rent", "Cats ok. $250 deposit, $30/mo.".
    Only a monthly amount (pet rent) or a plain one-time fee is read here; deposits have their own readers."""
    out: dict[str, float] = {}
    for sm in re.finditer(r"[^\n|;]+", text):
        for part in re.finditer(r"(?:[^.]|\.(?=\d))+", sm.group(0)):
            sent = part.group(0)
            start = sm.start() + part.start()
            if not (_PET_WORD.search(sent) or (re.match(r"\s*\$", sent) and _after_pet_sentence(text, start))) or _PC_SKIP.search(sent):
                continue
            for am in re.finditer(r"(?<![\w$])\$[ \t]?(\d{1,4})(?:\.\d\d)?(?![\d,])", sent):
                value = float(am.group(1))
                right = re.split(r"\$|,|\band\b|\bplus\b|\+", sent[am.end():am.end() + 40])[0]
                left = re.split(r",|\band\b|\bplus\b|\+|\$", sent[:am.start()])[-1]
                if re.match(r"[ \t]*(?:one[- ]time[ \t]+|non[- ]?refundable[ \t]+|refundable[ \t]+)?(?:pet[ \t]+)?deposits?\b", right, re.I) or re.search(r"deposits?\W{0,4}$", left, re.I):
                    continue
                if re.search(r"\b(?:unless|waiv\w*|except\w*|if approved)\b", sent[am.end():am.end() + 60], re.I):
                    continue  # a charge the listing says can be waived stays a quoted note
                if _PC_MONTHLY.match(right) and value <= 300:
                    out.setdefault("pet_rent", value)
                elif re.search(r"\b(?:monthly|per month|a month)\W*(?:pet[ \t]+)?(?:rent|fee|charge)?\W{0,4}$", left, re.I) and value <= 300 and not _PC_ONE_TIME.match(right):
                    out.setdefault("pet_rent", value)
                elif _PC_ONE_TIME.match(right) or re.search(r"\bfee\W{0,4}$", left, re.I) and not re.search(r"\b(?:monthly|per month)\b", left, re.I):
                    out.setdefault("pet_fee", value)
    return out


def _pet_fees(text: str) -> dict[str, float]:
    """Pet rent (monthly) and pet fee or deposit (one time), kept apart."""
    out: dict[str, float] = {}
    used: set[int] = set()
    for m in re.finditer(r"\$[ \t]?(\d{1,4})(?:\.\d\d)?[ \t]*(?:(?:/[ \t]*mo(?:nth)?|per month|monthly|a month)[ \t]*(?:per|each|/)[ \t]*(?:pet|dog|cat|animal)s?\b"
                         r"|(?:per|each|/)[ \t]*(?:pet|dog|cat|animal)s?[ \t]*(?:/[ \t]*mo(?:nth)?|per month|monthly|a month)\b)", text, re.I):
        used.add(m.start())
        out.setdefault("pet_rent", float(m.group(1)))
    for m in re.finditer(r"\$[ \t]?(\d{1,4})(?:\.\d\d)?[ \t]*(/[ \t]*mo(?:nth)?|per month|monthly|a month)?[ \t]*(?:per pet[ \t]*)?"
                         r"(?:(?:one[- ]?time|non[- ]?refundable|refundable|up[- ]?front|flat)(?:[ \t]+|,[ \t]*(?=(?:one[- ]?time|non[- ]?refundable|refundable|up[- ]?front|flat)))){0,3}(?:pet\s+(rent|fees?|deposit|charge)\b|per pet\b)", text, re.I):
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
                   or "monthly" in re.split(r"[.;!?\n](?:\s|$)|\n", text[max(0, m.start() - 10):m.start()])[-1].lower())  # cycle 18: only the same sentence ("$35 per cat monthly. Pet fee $250" is not a monthly fee)
        out.setdefault("pet_rent" if monthly else "pet_fee", float(am.group(2)))
    m = re.search(r"\bmonthly\s+pet\s+(?:fee|rent|charge)\s*[:\-]?\s*\$\s?(\d{1,4})", text, re.I)
    if m:
        out["pet_rent"] = float(m.group(1))
    if "pet_fee" not in out:  # "Cats up to 2, $250 fee, $30 pet rent": a bare "$250 fee" in a pet sentence is the one-time pet fee
        for m in re.finditer(r"\b(?:cats?|dogs?|pets?|animals?)\b[^.\n;$]{0,45}?\$[ \t]?(\d{1,4})(?:\.\d\d)?[ \t]*(?:(?:one[- ]?time|non[- ]?refundable|refundable)[ \t,]+){0,3}fee\b"
                             r"(?![ \t]+(?:for|to)[ \t]+(?:app|apply|screen|background|credit|admin|move|tour))([ \t]*(?:/[ \t]*mo(?:nth)?|per month|monthly|a month)?)", text, re.I):
            if text[max(0, m.start(1) - 12):m.start(1)].lower().rstrip().endswith(("application", "app", "admin")):
                continue
            out.setdefault("pet_rent" if m.group(2).strip() else "pet_fee", float(m.group(1)))
            break
    if "pet_fee" not in out and "pet_rent" not in out:  # "Cat fee $150" / "Dog fee: $200": a fee named for one animal is the pet fee
        m = re.search(r"\b(?:cat|dog)s?[ \t]+fee[ \t:\-=]*\$[ \t]?(\d{1,4})(?:\.\d\d)?(?![\d,])([ \t]*(?:/[ \t]*mo(?:nth)?|per month|monthly|a month))?", text, re.I)
        if m:
            out["pet_rent" if m.group(2) else "pet_fee"] = float(m.group(1))
    if "pet_rent" not in out:  # "cat rent $25", "Dog rent $40": rent named for one animal is the monthly pet rent
        m = re.search(r"\b(?:cat|dog)s?[ \t]+rent[ \t:\-=]*\$[ \t]?(\d{1,4})(?:\.\d\d)?(?![\d,])(?![ \t]*(?:one[- ]time|deposit|fee))", text, re.I)
        if m:
            out["pet_rent"] = float(m.group(1))
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
    if "pet_fee" not in out:  # cycle 20: "Pet policy: Cats only, 1 max, $35 monthly rent, $200 fee.": a bare "$N fee" inside a line that starts with a pet word
        for sent in re.split(r"[.;\n|](?=\s|$)|\n", text):
            if not _PET_LEAD.match(sent.strip()):
                continue
            fm = re.search(r"(?<![\w$])\$[ \t]?(\d{1,4})(?:\.\d\d)?(?![\d,])[ \t]*(?:one[- ]time[ \t]+|non[- ]?refundable[ \t]+)?fee\b(?![ \t]*(?:/|per[ \t]+month|monthly|a[ \t]+month|each[ \t]+month))(?![ \t]+(?:for|to)[ \t]+(?:app|apply|screen|background|credit|admin|move|tour|lease|parking))", sent, re.I)
            if fm and not re.search(r"(?:application|app|admin|move[- ]in|credit|screening|background|parking|key|lease|holding)\W{0,3}$", sent[:fm.start()].rstrip(), re.I):
                out["pet_fee"] = float(fm.group(1))
                break
    for key, value in _pet_clause_charges(text).items():
        out.setdefault(key, value)
    if not out:  # "cats negotiable, $50 extra": an extra charge for the pet, taken as monthly pet rent
        m = re.search(r"\b(?:cats?|dogs?|pets?)\b[^.\n$]{0,40}\$\s?(\d{1,4})(?:\.\d\d)?\s*(?:extra|more|additional)\b([^.\n]{0,25})", text, re.I)
        if m:
            one_time = re.search(r"one[- ]time|deposit|non[- ]?refundable|once", m.group(2), re.I)
            out["pet_fee" if one_time else "pet_rent"] = float(m.group(1))
    return out

_NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4}


def _pet_deposit_says_refundable(text: str, amount: float) -> bool:
    """True when the sentence that gives this pet deposit amount (or the one next to it) says it comes back ("refundable", "returned",
    "comes back"). "Non-refundable" is the opposite and never counts."""
    amt = f"{amount:,.0f}"
    plain = f"{amount:.0f}"
    for m in re.finditer(r"\$\s?(?:" + re.escape(amt) + "|" + re.escape(plain) + r")(?!\d)", text):
        a = max(text.rfind(x, 0, m.start()) for x in (".", "\n", ";", "|")) + 1
        b = min([x for x in (text.find(". ", m.end()), text.find("\n", m.end()), text.find(";", m.end()), text.find("|", m.end())) if x != -1] or [len(text)])
        around = re.sub(r"non[- ]?refundable", " ", text[a:b], flags=re.I)
        if re.search(r"\brefundable\b|\b(?:comes?|come|given|paid|sent|get|gets)[ \t]+back\b|\breturn(?:ed|able)\b|\brefunded\b", around, re.I):
            return True
    return False


def _no_pet_deposit(text: str) -> bool:
    """The listing says there is no pet deposit ("no pet deposit", "pet deposit: none", "no deposit for pets")."""
    return bool(re.search(r"\bno[ \t]+pet[ \t]+deposits?\b|\bpet[ \t]+deposits?[ \t]*[:\-=]?[ \t]*(?:none|n/?a|\$0(?:\.00)?|waived|no)\b|"
                          r"\bno[ \t]+deposits?[ \t]+(?:is[ \t]+)?(?:for|on|needed[ \t]+for|required[ \t]+for)[ \t]+(?:pets?|cats?|dogs?|animals?)\b|"
                          r"\b(?:pets?|cats?|dogs?)\b[^.\n;$]{0,30}\bno[ \t]+(?:pet[ \t]+)?deposits?\b", text, re.I))


def _pet_deposit(text: str) -> tuple[float | None, str]:
    """A refundable pet deposit ("$400 refundable pet deposit"), kept apart from the one-time pet fee: it comes back,
    so it counts only as cash needed at move-in. Returns (amount, text with that phrase blanked so _pet_fees skips it)."""
    pats = (r"\$\s?(\d{1,4})(?:\.\d\d)?[ \t]*(?:one[- ]time[ \t]+)?(?:refundable[ \t]+)?pet[ \t]+deposit\b",
            r"\bpet[ \t]+deposit[ \t]*(?:[(\[][ \t]*(?:fully[ \t]+)?refundable[ \t]*[)\]]|(?:fully[ \t]+)?refundable)?[ \t]*(?:[:\-=]|of|is)?[ \t]*\$\s?(\d{1,4})(?:\.\d\d)?\b(?!/)",
            # "$250 per pet deposit", "$250 each pet deposit", "deposit: $250 per pet"
            r"\$\s?(\d{1,4})(?:\.\d\d)?[ \t]*(?:per|each|/)[ \t]*(?:pet|dog|cat|animal)s?[ \t]+(?:refundable[ \t]+)?deposit\b",
            r"\b(?:pets?|dogs?|cats?|animals?)[ \t]+deposit[ \t]*(?:[:\-]|of)?[ \t]*\$\s?(\d{1,4})(?:\.\d\d)?[ \t]*(?:per|each|/)[ \t]*(?:pet|dog|cat|animal)s?\b",
            r"(?<!pet )\bdeposit[ \t]*(?:[:\-]|of)?[ \t]*\$\s?(\d{1,4})(?:\.\d\d)?(?=[ \t]*(?:per|each|/)[ \t]*(?:pet|dog|cat|animal)s?\b)")
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


_PAIR_TAG = re.compile(r"(non[- ]?)?refundable\b", re.I)


def _pet_conditional_deposit(text: str) -> tuple[float, str, str] | None:
    """Cycle 23: "Dogs up to 25 lbs only; larger dogs with approval and an additional $500 deposit": the $500 is owed only by the larger dogs, so it is
    never the flat pet deposit. Returns (amount, the text with that phrase blanked, a plain note) or None."""
    for sm in re.finditer(r"[^\n|;]+", text):
        for part in re.finditer(r"(?:[^.]|\.(?=\d))+", sm.group(0)):
            clause = part.group(0)
            base = sm.start() + part.start()
            for m in re.finditer(r"\$\s?(\d{1,4}(?:,\d{3})?)(?:\.\d\d)?[ \t]*(?:(?:pet|extra|additional)[ \t]+)?(?:deposit|fee)s?\b|\b(?:deposit|fee)[ \t:\-]*\$\s?(\d{1,4}(?:,\d{3})?)(?:\.\d\d)?", clause, re.I):
                before = re.split(r"[,]", clause[:m.start()])[-1]
                before = re.sub(r"\bno[ \t]+(?:\w+[ \t]+)?(?:over|above|exceeding|more than|larger|bigger|heavier)\b", " ", before, flags=re.I)  # "no pets over 25 pounds" is the weight rule
                if not (re.search(r"\b(?:larger|bigger|heavier|big|over|above|exceeding|more than)\b", before, re.I) and re.search(r"\b(?:dogs?|pets?|animals?|cats?)\b", before, re.I)
                        and re.search(r"\b(?:additional|extra|another|plus|approval|approved|requires?|needs?)\b", before, re.I)):
                    continue
                if re.search(r"\b(?:each|every|per)[ \t]+(?:pet|dog|cat)\b|\bper[ \t]+(?:pet|dog|cat)\b", clause[m.end():m.end() + 14], re.I):
                    continue  # "$300 deposit per pet" is the general one
                amount = float((m.group(1) or m.group(2)).replace(",", ""))
                wm = re.search(r"\b(?:up to|under|max(?:imum)?(?: of)?|less than|below|over|above|exceeding|than)[ \t]*(\d{1,3})[ \t]*(?:lbs?\b|pounds?\b)", text[max(0, base - 150):base + m.start()], re.I) \
                    or re.search(r"\b(\d{1,3})[ \t]*(?:lbs?\b|pounds?\b)", text[max(0, base - 150):base + m.start()], re.I)
                over = f" (over {wm.group(1)} lbs)" if wm else ""
                a, b = base + m.start(), base + m.end()
                note = (f"The listing gives an additional ${amount:,.0f} deposit only for larger pets{over} with approval. It only applies on that condition, "
                        f"so it is not saved as the pet deposit. Ask what it would cost for your pet.")
                return amount, text[:a] + " " * (b - a) + text[b:], note
    return None


def _pet_deposit_pair(text: str) -> tuple[float | None, float | None, str, str] | None:
    """"Pet deposit: $300 refundable + $150 non-refundable", "$150 non-refundable pet fee and $300 refundable deposit": two amounts in one
    pet sentence, one tagged refundable and the other non-refundable, in any order. The refundable one is the pet deposit (it comes back)
    and the non-refundable one is the pet fee. Same return shape as _pet_deposit_split."""
    for sm in re.finditer(r"[^\n;|]+", text):
        sent = sm.group(0)
        for part in re.split(r"\.(?!\d)", sent):
            if not (_PET_WORD.search(part) or _after_pet_sentence(text, sm.start() + sent.find(part))):
                continue
            amts = list(re.finditer(_AMT_NUM, part))
            if len(amts) != 2:
                continue
            tags: list[bool | None] = []
            for i, a in enumerate(amts):
                before = part[(amts[i - 1].end() if i else 0):a.start()]
                after = part[a.end():(amts[i + 1].start() if i + 1 < len(amts) else len(part))]
                tag = None
                mb = re.search(r"(non[- ]?)?refundable[ \t:\-]*(?:pet[ \t]+)?(?:deposit|fee)?[ \t:\-]*$", before, re.I)
                if mb and len(before) - mb.start() <= 40:
                    tag = not mb.group(1)
                else:
                    ma = re.match(r"[ \t]*(?:(?:pet[ \t]+)?(?:deposit|fee)[ \t]*)?(?:\(|-|:)?[ \t]*" + _PAIR_TAG.pattern, after, re.I)
                    if ma:
                        tag = not ma.group(1)
                tags.append(tag)
            if sorted(t is True for t in tags) != [False, True] or None in tags:
                continue
            lead = re.search(r"(?:pet[ \t]+)?(?:deposits?|fees?)[ \t]*[:\-]?[ \t]*$", part[:amts[0].start()], re.I)
            start = lead.start() if lead else amts[0].start()
            last_tag = _PAIR_TAG.search(part, amts[1].end())
            end = amts[1].end()
            if tags[1] is not None and last_tag and last_tag.start() >= end and last_tag.start() - end <= 20:
                end = last_tag.end()
            tail = re.match(r"[ \t]*(?:(?:pet[ \t]+)?(?:deposit|fee)s?\b)?", part[end:])
            end += tail.end() if tail else 0
            base = sm.start() + sent.find(part)
            blanked = text[:base + start] + " " * (end - start) + text[base + end:]
            ref = _num(amts[tags.index(True)].group(1))
            non = _num(amts[tags.index(False)].group(1))
            each = " Both amounts are for each pet, so with more than one pet they add up." if re.search(r"\b(?:per|each|/)[ \t]*(?:pet|animal|dog|cat)", part, re.I) else ""
            return (ref, non, blanked,
                    f"The listing gives ${ref:,.0f} that comes back (saved as the pet deposit) and ${non:,.0f} that does not (saved as the pet fee).{each}")
    return None


def _pet_deposit_split(text: str) -> tuple[float | None, float | None, str, str] | None:
    """"$350 pet deposit (non-refundable $150 of it)": part of the deposit comes back and part does not. Returns (refundable
    deposit, non-refundable fee, text with that phrase blanked, plain note), or None. When the non-refundable part is not smaller
    than the whole, both are None and the note says to ask."""
    pair = _pet_deposit_pair(text)
    if pair:
        return pair
    m = re.search(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?[ \t]*pet[ \t]+deposit\b[ \t,:;\-]*\(?[ \t]*(?:of[ \t]+which[ \t]+)?"
                  r"(?:(?:non[- ]?refundable)[ \t:\-]*\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?|\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?[ \t]*(?:of[ \t]+(?:it|that|this|which)[ \t]+)?(?:is[ \t]+|are[ \t]+)?non[- ]?refundable)"
                  r"(?:[ \t]*(?:of[ \t]+(?:it|that|this|which)|portion))?[ \t]*\)?(?![ \t]*(?:pet[ \t]+)?(?:fee|deposit|rent)\b)", text, re.I)
    if not m:
        return _pet_deposit_refundable_split(text) or _pet_deposit_nonrefundable_split(text)
    whole, part = _num(m.group(1)), _num(m.group(2) or m.group(3))
    blanked = text[:m.start()] + " " * (m.end() - m.start()) + text[m.end():]
    if 0 < part < whole:
        return (whole - part, part, blanked,
                f"The ${whole:,.0f} pet deposit is partly non-refundable: ${whole - part:,.0f} comes back (saved as the pet deposit) and ${part:,.0f} does not (saved as the pet fee).")
    return (None, None, blanked,
            f"The listing says a ${whole:,.0f} pet deposit with ${part:,.0f} non-refundable, which does not add up, so the pet deposit and pet fee are left empty. Ask how much comes back.")


_AMT_NUM = r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?"
_REFUNDABLE_PART = (r"[ \t,:;\-]*\(?[ \t]*(?:of[ \t]+which[ \t]+)?" + _AMT_NUM +
                    r"[ \t]*(?:of[ \t]+(?:it|that|this|which)[ \t]+)?(?:is[ \t]+|are[ \t]+)?(?<!non)(?<!non-)(?<!non )refundable\b[ \t]*\)?")


def _after_pet_sentence(text: str, pos: int) -> bool:
    """True when the sentence just before ``pos`` is a pet sentence ("Cats allowed. $250 deposit ...") and neither talks about the lease."""
    parts = [x for x in re.split(r"[.!?;\n|]", text[max(0, pos - 90):pos]) if x.strip()]
    last = parts[-2] if len(parts) >= 2 and not parts[-1].strip() else (parts[-1] if parts else "")
    here = parts[-1] if parts else ""
    return bool(_PET_WORD.search(here) or _PET_LEAD.match(last.strip())) and not re.search(r"\bsecurity\b|\bdamage\b|\blease\b", here + " " + last, re.I)


def _pet_deposit_refundable_split(text: str) -> tuple[float | None, float | None, str, str] | None:
    """"Pet deposit $400 ($250 refundable)", "$350 deposit ($150 refundable)" in a pet sentence: only part of the deposit comes
    back. The refundable part is the pet deposit and the rest is the pet fee. Same return shape as _pet_deposit_split."""
    pats = (r"\bpet[ \t]+deposit[ \t]*(?:[:\-]|of)?[ \t]*" + _AMT_NUM + _REFUNDABLE_PART,
            _AMT_NUM + r"[ \t]*(?:pet[ \t]+)?deposit\b" + _REFUNDABLE_PART,
            _AMT_NUM + r"[ \t]*(?:,|\()" + _REFUNDABLE_PART)
    for i, pat in enumerate(pats):
        for m in re.finditer(pat, text, re.I):
            if i >= 1 and not (re.search(r"\bpet[ \t]+$", text[max(0, m.start() - 6):m.start()], re.I) or "pet" in m.group(0).lower()[:30]
                               or _in_pet_sentence(text, m.start()) or _after_pet_sentence(text, m.start())):
                continue  # a "$1,500 deposit ($1,000 refundable)" with no pet word is the security deposit
            if i == 2 and not (_in_pet_sentence(text, m.start()) and not re.search(r"\brent\b|\bsecurity\b|\blease\b", text[max(0, m.start() - 20):m.start()], re.I)):
                continue  # a bare "$500, $300 refundable" is read only inside a pet sentence
            if re.match(r"[ \t]*(?:pet[ \t]+)?(?:fee|deposit|rent)\b", text[m.end():m.end() + 12], re.I):
                continue
            whole, part = _num(m.group(1)), _num(m.group(2))
            blanked = text[:m.start()] + " " * (m.end() - m.start()) + text[m.end():]
            if 0 < part < whole:
                return (part, whole - part, blanked,
                        f"The pet deposit is ${whole:,.0f} and only part of it comes back, so it is split into a pet deposit (comes back) and a pet fee (does not).")
            return (None, None, blanked,
                    f"The listing gives a ${whole:,.0f} pet deposit and a refundable part that does not add up, so the pet deposit and pet fee are left empty. Ask how much comes back.")
    return None


_NONREF_PART = (r"[ \t,:;\-]*\(?[ \t]*(?:of[ \t]+which[ \t]+)?"
                r"(?:non[- ]?refundable[ \t:\-]*" + _AMT_NUM + r"|" + _AMT_NUM + r"[ \t]*(?:of[ \t]+(?:it|that|this|which)[ \t]+)?(?:is[ \t]+|are[ \t]+)?non[- ]?refundable\b)"
                r"(?:[ \t]*(?:of[ \t]+(?:it|that|this|which)|portion))?[ \t]*\)?")
_PER_PET_TAIL = r"(?:[ \t]*(?:per|each|/)[ \t]*(?:pet|animal|dog|cat)s?\b)?"


def _pet_deposit_nonrefundable_split(text: str) -> tuple[float | None, float | None, str, str] | None:
    """"$300 deposit per pet, non-refundable $100", "Pet deposit $300 (non-refundable $150)", "$300 (non-refundable $150)" in a pet
    sentence: the deposit is the whole amount and the non-refundable part of it is a fee. The rest comes back, so it is the pet
    deposit and the non-refundable part is the pet fee. Same return shape as _pet_deposit_split."""
    pats = (r"\bpet[ \t]+deposit[ \t]*(?:[:\-]|of)?[ \t]*" + _AMT_NUM + _PER_PET_TAIL + _NONREF_PART,
            _AMT_NUM + r"[ \t]*(?:pet[ \t]+)?deposit\b" + _PER_PET_TAIL + _NONREF_PART,
            _AMT_NUM + _PER_PET_TAIL + r"[ \t]*(?:,|\()" + _NONREF_PART)
    for i, pat in enumerate(pats):
        for m in re.finditer(pat, text, re.I):
            per_pet = bool(re.search(r"\b(?:per|each|/)[ \t]*(?:pet|animal|dog|cat)", m.group(0), re.I))
            if i >= 1 and not (re.search(r"\bpet[ \t]+$", text[max(0, m.start() - 6):m.start()], re.I) or "pet" in m.group(0).lower()[:30]
                               or _in_pet_sentence(text, m.start()) or _after_pet_sentence(text, m.start()) or per_pet):
                continue  # a "$1,500 deposit (non-refundable $500)" with no pet word is not a pet charge
            if i == 2 and not (per_pet or ((_in_pet_sentence(text, m.start()) or _after_pet_sentence(text, m.start()))
                                           and not re.search(r"\brent\b|\bsecurity\b|\blease\b", text[max(0, m.start() - 20):m.start()], re.I))):
                continue
            if re.match(r"[ \t]*(?:pet[ \t]+)?(?:fee|deposit|rent)\b", text[m.end():m.end() + 12], re.I):
                continue
            whole = _num(m.group(1))
            part = _num(m.group(2) or m.group(3))
            blanked = text[:m.start()] + " " * (m.end() - m.start()) + text[m.end():]
            each = " Both amounts are for each pet, so with more than one pet they add up." if per_pet else ""
            if 0 < part < whole:
                return (whole - part, part, blanked,
                        f"The pet deposit is ${whole:,.0f} and ${part:,.0f} of it is non-refundable, so ${whole - part:,.0f} is saved as the pet deposit (comes back) "
                        f"and ${part:,.0f} as the pet fee (does not).{each}")
            return (None, None, blanked,
                    f"The listing gives a ${whole:,.0f} pet deposit with ${part:,.0f} non-refundable, which does not add up, so the pet deposit and pet fee are left empty. Ask how much comes back.")
    return None


def _pet_application(text: str) -> tuple[float, bool, str] | None:
    """"Pet application $40 per pet", "$40 pet application fee": a screening charge for the pet, not the pet fee. Returns
    (amount, charged per pet, text with that phrase blanked), or None."""
    m = re.search(r"\bpet[ \t]+(?:application|screening|app)(?:[ \t]+fee)?[ \t:\-=]*\$[ \t]?(\d{1,4})(?:\.\d\d)?(?![\d,])(" + _PER_PET_TAIL + r")"
                  r"|\$[ \t]?(\d{1,4})(?:\.\d\d)?(?![\d,])(" + _PER_PET_TAIL + r")[ \t]*pet[ \t]+(?:application|screening|app)\b(?:[ \t]+fee)?", text, re.I)
    if not m:
        return None
    return float(m.group(1) or m.group(3)), bool((m.group(2) or m.group(4) or "").strip()), text[:m.start()] + " " * (m.end() - m.start()) + text[m.end():]


def _per_animal_charges(text: str) -> tuple[str, dict[str, float], str] | None:
    """"Pet fee $250 cat, $400 dog", "Cat fee $250, dog fee $400": one kind of charge with a price for each animal. Returns
    (kind "fee" / "rent" / "deposit", {"cat": amount, "dog": amount}, text with those phrases blanked), or None."""
    amt = r"\$\s?(\d{1,4})(?:\.\d\d)?"
    animal = r"(cat|dog)s?"
    pats = (r"\bpet[ \t]+(fee|rent|deposit)s?[ \t:\-=]*(?:" + amt + r"[ \t]*(?:for[ \t]+(?:a[ \t]+|each[ \t]+)?)?" + animal + r"|" + animal + r"[ \t]*[:\-=]?[ \t]*" + amt + r")"
            r"(?:[ \t]*(?:/[ \t]*mo(?:nth)?|per month|monthly|a month|each)?[ \t]*(?:,|/|&|;|and|\|)[ \t]*(?:and[ \t]+)?(?:" + amt + r"[ \t]*(?:for[ \t]+(?:a[ \t]+|each[ \t]+)?)?" + animal + r"|" + animal + r"[ \t]*[:\-=]?[ \t]*" + amt + r"))",
            r"\b" + animal + r"[ \t]+(fee|rent|deposit)s?[ \t:\-=]*" + amt + r"(?:[ \t]*(?:/[ \t]*mo(?:nth)?|per month|monthly|a month))?[ \t]*(?:,|/|&|;|and|\|)[ \t]*(?:and[ \t]+)?" + animal + r"[ \t]+(?:fee|rent|deposit)s?[ \t:\-=]*" + amt)
    m = re.search(pats[0], text, re.I)
    if m:
        g = m.groups()
        kind = g[0].lower()
        first = (g[2].lower(), float(g[1])) if g[1] else (g[3].lower(), float(g[4]))
        second = (g[6].lower(), float(g[5])) if g[5] else (g[7].lower(), float(g[8]))
    else:
        m = re.search(pats[1], text, re.I)
        if not m:
            return None
        g = m.groups()
        kind = g[1].lower()
        first, second = (g[0].lower(), float(g[2])), (g[3].lower(), float(g[4]))
    if first[0] == second[0]:
        return None
    return kind, {first[0]: first[1], second[0]: second[1]}, text[:m.start()] + " " * (m.end() - m.start()) + text[m.end():]


def _pet_deposit_then_monthly(text: str) -> float | None:
    """"Pet deposit $300, $40 monthly": the amount after the deposit that says monthly is the pet rent."""
    m = re.search(r"\bpet[ \t]+(?:deposit|fee)[ \t:\-]*(?:of[ \t]+)?\$\s?\d{1,4}(?:\.\d\d)?[ \t]*(?:,|and|plus|\+)[ \t]*\$\s?(\d{1,4})(?:\.\d\d)?[ \t]*(?:/[ \t]*mo(?:nth)?|per month|monthly|a month)\b(?![ \t]*(?:deposit|fee|parking|garage|storage))", text, re.I)
    return float(m.group(1)) if m else None


def _no_pet_rent(text: str) -> bool:
    """"No pet rent", "Pet rent: none", "Pet rent $0": the listing says there is no monthly pet charge."""
    return bool(re.search(r"\b(?:no|zero|without|waived|free of)[ \t]+(?:monthly[ \t]+)?pet[ \t]+(?:rent|charges?)\b|\bpet[ \t]+rent[ \t]*[:\-=]?[ \t]*(?:none|n/?a|waived|free|\$\s?0(?:\.00)?(?![\d.,]))"
                          r"|\b(?:monthly[ \t]+)?pet[ \t]+rent[ \t]*[:\-=,]?[ \t]*(?:is[ \t]+|are[ \t]+|will[ \t]+be[ \t]+)?(?:not|never)[ \t]+(?:charged|required|applicable|applied|collected|due|assessed)\b"
                          r"|\b(?:don'?t|do[ \t]+not|does(?:n'?t|[ \t]+not)|won'?t|will[ \t]+not|never)[ \t]+(?:charge|collect|require|assess)[ \t]+(?:any[ \t]+)?(?:monthly[ \t]+)?pet[ \t]+rent\b", text, re.I)) \
        and not re.search(r"\bno[ \t]+pet[ \t]+rent[ \t]+(?:for|on|if|unless|over|above|with)\b|\bpet[ \t]+rent\b[^.\n;]{0,25}\b(?:not|never)[ \t]+(?:charged|required|applicable|applied|collected|due|assessed)[ \t]+(?:for|on|if|unless|over|above|with|until|during)\b", text, re.I)


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
            ss = max(_sentence_break(text, m.start(), c) for c in ".!?;\n|") + 1
            se = min([i for i in (text.find(c, m.end()) for c in ".!?;\n|") if i >= 0] or [len(text)])
            if not pet and m.group(1) and not text[ss:m.start()].strip() and _after_pet_sentence(text, ss) and amount > 0 and (rent is None or amount < rent * 0.6) \
                    and re.search(r"/[ \t]*mo\b|\bmonthly\b|per[ \t]+month|a[ \t]+month", text[m.end():se], re.I) \
                    and not re.search(r"\b(?:credit|approv\w*|security|lease|first|last|refundable|if|else)\b", text[ss:se], re.I):
                pet = True  # cycle 23: "Cats ok. $250 deposit, $30/mo.": a sentence right after a pet sentence that starts with a deposit and lists a monthly pet charge
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


_WEIGHT_WAIVER = re.compile(r"\bwithout[ \t]+(?:prior[ \t]+|written[ \t]+|special[ \t]+)?(?:approv\w+|permission|consent)\b|\b(?:with|upon|subject to|pending|requires?|needs?|need|once)[ \t]+(?:prior[ \t]+|written[ \t]+|special[ \t]+|management[ \t]+|landlord[ \t]+)?(?:approv\w+|permission|consent)\b|"
                           r"\bunless[ \t]+(?:approved|permitted|cleared|waived|authorized|authorised)\b|\bexceptions?\b|\bcase[- ]by[- ]case\b|\bwaive[sd]?\b|\bwaivable\b|\bnegotiable\b|\bmay[ \t]+(?:be[ \t]+)?(?:made|approved|granted|considered|allowed)\b|"
                           r"\b(?:approved|permitted|allowed)[ \t]+(?:by|on)[ \t]+(?:the[ \t]+)?(?:management|landlord|owner|office)\b|\bat[ \t]+(?:the[ \t]+)?(?:management|landlord|owner)(?:'s)?[ \t]+(?:discretion|option|approval)\b", re.I)


def _pet_weight_waiver_note(text: str, out: dict[str, Any]) -> str:
    """Cycle 25: "No pets over 40 lb without approval", "Dogs up to 40 lb; larger with approval", "exceptions considered": the weight limit can be waived on
    approval, so a heavier dog is a question for the landlord, never a flat no. One short note says so (the scoring reads it as "ask")."""
    w = out.get("pet_weight_limit")
    if w is None:
        return ""
    sentences = [x for x in re.split(r"(?<=[.!?])\s+|\n+|\s\|\s", text) if x.strip()]
    number = f"{float(w):g}"
    for i, sentence in enumerate(sentences):
        if not re.search(r"(?<![\d.])" + re.escape(number) + r"(?:\.0+)?[ \t]*(?:lbs?\b|pounds?\b)", sentence, re.I):
            continue
        nxt = sentences[i + 1] if i + 1 < len(sentences) else ""
        if _WEIGHT_WAIVER.search(sentence) or (nxt and len(nxt) < 80 and _WEIGHT_WAIVER.search(nxt) and re.search(r"\b(?:pets?|dogs?|animals?|larger|bigger|heavier|exceptions?|weight)\b", nxt, re.I)):
            return (f"The listing says the {number} lb pet weight limit can be waived with approval. A heavier pet is a question for {_ask_who(text)}, not a flat no.")
    return ""


def _pet_weight_unclear(text: str) -> str:
    """A note when a number of pounds sits in a pet clause but no weight limit could be read from it, else ""."""
    fields = _pet_limit_fields(text)
    if fields.get("pet_weight_limit") is not None or fields.get("_weight_conflict") or fields.get("_weight_combined"):
        return ""
    for c in _weight_clauses(text):
        if _PET_WORD.search(c) and re.search(r"\b\d{1,3}\s*" + _UNIT_LB, c, re.I) and not re.search(r"\$", c) and not _NOT_PET_WEIGHT.search(c):
            said = " ".join(c.split())[:80]
            return (f"The listing gives a weight near the pets (\"{said}\") but it is not clear if it is a limit, so the weight limit is left empty. "
                    f"Ask {_ask_who(text)} the heaviest pet allowed.")
    return ""


def _pet_weight_conflict(text: str, wmatch: Any) -> list[str]:
    """Cycle 22: "No dogs over 40 lbs." next to "Dogs allowed up to 80 lbs": two weight limits for the same pets that disagree. Returns the
    quoted lines (two or more) or []. Limits for different animals (cats and dogs) are not a conflict."""
    seen: dict[float, str] = {}
    kinds: list[set[str]] = []
    for part in re.split(r"[.\n;|]", text):
        m = wmatch(part)
        if not m or not 3 <= int(m.group(1)) <= 300:
            continue
        k = {w.lower().rstrip("s") for w in re.findall(r"\b(?:dogs?|cats?)\b", part, re.I)}
        value = float(m.group(1))
        if value in seen:
            continue
        seen[value] = " ".join(part.split())
        kinds.append(k)
    if len(seen) < 2:
        return []
    if any(a and b and not (a & b) for n, a in enumerate(kinds) for b in kinds[n + 1:]):
        return []
    return list(seen.values())[:3]


_BREED_NAME = re.compile(r"\b(?:pit[ \t-]?bulls?|pitbulls?|staffordshire\w*|rottweilers?|rotties|dobermans?|doberman pinschers?|german shepherds?|huskies|huskys?|akitas?|chow(?:s| chows?)?|mastiffs?|great danes?|wolf[ \t-]?(?:hybrids?|dogs?)|presa canarios?|cane corsos?|malamutes?|bully breeds?|aggressive (?:dog )?breeds?)\b", re.I)


def _pet_limit_fields(text: str) -> dict[str, Any]:
    """Structured pet limits: pet_weight_limit (lb), pet_count_limit, pet_breed_note and fenced_yard (1 or 0)."""
    out: dict[str, Any] = {}
    def _wmatch(t: str) -> re.Match[str] | None:
        return re.search(r"\b(?:dogs?|pets?|animals?)\b[^.\n;]{0,40}?(?:under|up to|less than|below|at most|no more than|not (?:to )?exceed(?:ing)?|max(?:imum)?(?: of)?|weigh(?:ing|s)?(?: up to| under)?|<)\s*(\d{1,3})\s*(?:lbs?\b|pounds?\b)", t, re.I) \
        or re.search(r"\bno\s+(?:dogs?|pets?|animals?|breeds?|cats?)?\s*(?:over|above|exceeding|larger than|heavier than|more than)\s*(\d{1,3})\s*(?:lbs?\b|pounds?\b)", t, re.I) \
        or re.search(r"\b(?:dogs?|pets?|animals?)\b[^.\n;]{0,30}?\b(?:over|above|exceeding)\s*(\d{1,3})\s*(?:lbs?\b|pounds?\b)\s*(?:are\s+)?(?:not\s+(?:allowed|permitted|accepted)|prohibited)", t, re.I) \
        or re.search(r"\b(\d{1,3})\s*(?:lbs?\b|pounds?\b)\s*(?:weight\s*)?(?:limit|cap|max(?:imum)?)", t, re.I) \
        or re.search(r"\b(?:dogs?|pets?|animals?)\b[^.\n;]{0,40}?\b(\d{1,3})\s*(?:lbs?\b|pounds?\b)\s*(?:each|apiece|max(?:imum)?|per (?:pet|dog|animal))", t, re.I) \
        or re.search(r"\bweight (?:limit|cap|max(?:imum)?)\s*(?:of|is|:)?\s*(\d{1,3})\s*(?:lbs?\b|pounds?\b)?", t, re.I) \
        or re.search(r"\b(?:dogs?|pets?|animals?)\b[ \t]+(?:max(?:imum)?|only|limit(?:ed)?)[ \t]*[,(:\-]?[ \t]*(?:to[ \t]+|of[ \t]+)?(\d{1,3})[ \t]*(?:lbs?\b|pounds?\b)(?![^.\n;]{0,40}\b(?:waiv\w*|negotiable|case[- ]by[- ]case|exceptions? (?:may|can|are|possible)|flexible|approval))", t, re.I) \
        or re.search(r"\b(?:dogs?|pets?)\b[ \t]*(?:are[ \t]+)?(?:ok|okay|allowed|welcome|accepted|permitted)[ \t]*[:,\-(]?[ \t]*(?:up to|under|max(?:imum)?(?: of)?|to)?[ \t]*(\d{1,3})[ \t]*(?:lbs?\b|pounds?\b)", t, re.I)
    w = _wmatch(text)
    conflict = _pet_weight_conflict(text, _wmatch)
    if conflict:
        out["_weight_conflict"] = conflict  # cycle 22: two limits that disagree, so no limit is saved
        w = None
    if w and 3 <= int(w.group(1)) <= 300:
        out["pet_weight_limit"] = float(w.group(1))
    elif not w and not conflict:
        loose = _loose_weight(text)
        if loose:
            out["pet_weight_limit"] = float(loose)
    if out.get("pet_weight_limit") is not None:
        wn = f"{out['pet_weight_limit']:.0f}"
        for c in _weight_clauses(text):
            if re.search(r"\b" + wn + r"[ \t]*(?:lbs?\b|pounds?\b|#)", c, re.I) and re.search(r"\b(?:combined|in total|total weight|all pets|altogether|together|in all|total)\b", c, re.I) \
                    and not re.search(r"\b(?:each|per[ \t]+(?:pet|dog|animal)|apiece)\b", c, re.I):
                out["_weight_combined"] = (out.pop("pet_weight_limit"), " ".join(c.split()))  # cycle 23: a limit for all the pets together is not the per-pet weight
                break
    n = re.search(r"\b(?:max(?:imum)?(?: of)?|limit(?: of)?|up to|no more than|at most)\s+(\d|one|two|three|four)\s+(?:pets?|animals?|cats?|dogs?)\b", text, re.I) \
        or re.search(r"\b(?<![\w$.])(\d|one|two|three|four)\s+(?:pets?|animals?|cats?|dogs?)\s+(?:max(?:imum)?|limit|only|per (?:unit|apartment|home|household))", text, re.I)
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
    if "pet_count_limit" not in out:  # "2 allowed, max 60 lbs each": a count with "allowed" in a pet sentence
        for sentence in re.split(r"[.\n;]", text):
            if _PET_WORD.search(sentence) or re.search(r"\d\s*(?:lbs?|pounds?)\s+(?:each|apiece|max)", sentence, re.I):
                n = re.search(r"(?<![\w$.\-/])(\d|one|two|three|four)[ \t]+(?:pets?[ \t]+|animals?[ \t]+)?allowed\b", sentence, re.I)
                if n:
                    v = n.group(1).lower()
                    count = int(v) if v.isdigit() else _NUM_WORDS[v]
                    if count >= 1:
                        out["pet_count_limit"] = count
                        break
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
    if "pet_count_limit" not in out:  # cycle 20: "one dog under 75 lb ok", "1 dog OK": the listing allows that many
        for sentence in re.split(r"[.\n;]", text):
            if not _PET_WORD.search(sentence) or re.search(r"\bno[ \t]+(?:pets?|dogs?|cats?|animals?)\b|\bnot[ \t]+allowed|\b(?:per|each|every)[ \t]+(?:pets?|dogs?|cats?|animals?)\b", sentence, re.I):
                continue
            if not re.search(r"\b(?:ok|okay|allowed|welcome\w*|accepted|permitted|considered|fine|only)\b", sentence, re.I):
                continue
            n = re.search(r"(?<![\w$.\-/#])(\d|one|two|three|four)[ \t]+(?:(?:small|medium|large|big|friendly|well[- ]behaved|house[- ]trained)[ \t]+)?(?:dogs?|cats?|pets?|animals?)\b(?![ \t]*(?:fee|deposit|rent|policy|limit|charges?|per\b|each\b|/))", sentence, re.I)
            if n:
                v = n.group(1).lower()
                count = int(v) if v.isdigit() else _NUM_WORDS[v]
                if count >= 1:
                    out["pet_count_limit"] = count
                    break
    b = next((c for c in _clauses(text) if re.search(r"\b(?:breed|breeds|breed restrictions?)\b", c, re.I)), None)
    if b:
        clause = " ".join(b.split()).strip(" -:,")
        if "," in clause and "(" not in clause and not re.search(r"\bbreeds?[ \t]*[:\-]", clause, re.I):  # "Dogs OK, 1 dog max, breed restrictions apply": keep the pieces that are about breeds
            other = re.compile(r"\b\d{1,3}\s*(?:lbs?|pounds?)|\bmax(?:imum)?\b|\b(?:dogs?|cats?|pets?|animals?)\b[^,]{0,12}\b(?:ok|okay|allowed|welcome|accepted)\b|\bconsidered\b|case[- ]by[- ]case|\bno more than\b|\bup to\b|\bunder\b|approval|\bfees?\b|\$", re.I)
            pieces = [x.strip() for x in clause.split(",") if re.search(r"\bbreeds?\b", x, re.I) and not other.search(x)]
            if pieces:
                clause = ", ".join(pieces)
        if 0 < len(clause) <= 140:
            out["pet_breed_note"] = clause[0].upper() + clause[1:]
    if "pet_breed_note" not in out:  # cycle 23: "no pit bulls", "Rottweilers not allowed": the breed rule with no word "breed" in it
        pieces = []
        for c in _clauses(text):
            for piece in re.split(r",|\band\b(?=\s+no\b)", c):
                if _BREED_NAME.search(piece) and re.search(r"\bno\b|\bnot\s+(?:allowed|permitted|accepted)|\bprohibited\b|\bbanned\b|\brestricted\b|\bexcluded\b", piece, re.I) \
                        and not re.search(r"\bno\s+(?:\w+\s+)?(?:weight|size)\b", piece, re.I):
                    cleaned = " ".join(piece.split()).strip(" -:,")
                    if cleaned and cleaned.lower() not in [x.lower() for x in pieces]:
                        pieces.append(cleaned)
        if pieces and len(", ".join(pieces[:3])) <= 140:
            note = ", ".join(pieces[:3])
            out["pet_breed_note"] = note[0].upper() + note[1:]
    # a fenced patio, balcony, courtyard, deck, porch, terrace or dog run is not a fenced yard
    ytext = re.sub(r"\b(?:fenced|fence|fencing|gated|walled)[- ]?(?:in\b)?[ \t]*(?:around[ \t]+)?(?:the[ \t]+|a[ \t]+|an[ \t]+)?(?:(?:back|front|private|small|shared|tiny|little|outdoor)[ \t]+)*(?:patio|balcon\w*|courtyard|deck|porch|terrace|dog[- ]?run|dog[- ]?park)s?\b(?![ \t]*(?:yard|garden|lot)\b)"
                   r"|\b(?:patio|balcon\w*|courtyard|deck|porch|terrace|dog[- ]?run)s?\b[^.\n;,]{0,15}?\b(?:fenced|fence|fencing)\b", " ", text, flags=re.I)
    if re.search(r"\b(?:no|not a|without a)\s+(?:\w+\s+)?fenc(?:ed|e|ing)\b|\bunfenced\b|\bnot fenced\b|\b(?:no|not an?|without an?)\s+(?:fully\s+)?enclosed\s+(?:\w+\s+)?(?:yard|backyard|garden)\b", text, re.I):
        out["fenced_yard"] = 0
    elif re.search(r"\bfenced[- ](?:in[- ])?(?:(?:back|front|private)[ ]?(?:yard|garden|lot|patio)?|yard|garden|lot|patio|(?:single[- ]family[ ]|detached[ ])?(?:house|home|property|townhome|townhouse|duplex|cottage|bungalow))\b|\b(?:yard|backyard)\s+(?:is\s+)?(?:fully\s+)?fenced|\b(?:fully|completely|totally)[ -]fenced\b"
                   r"|\byard\b[ \t]*[:\-]?[ \t]*(?:is[ \t]+)?(?:fully[ \t]+|completely[ \t]+|totally[ \t]+)?(?:enclosed|fenced)\b"
                   r"|(?<!not )(?<!un)\b(?:fully[ \t]+|completely[ \t]+)?enclosed[ \t-]+(?:(?:back|front|private)[ \t]*)?(?:yard|backyard|garden)\b"
                   r"|\b(?:gated|walled)[- ](?:in[- ])?(?:back|front|private )?(?:yard|garden|lot|patio)\b"
                   r"|\b(?:back|front)?[ ]?yard\b[^.\n;]{0,30}?\b(?:fence|fenced|fencing)\b"
                   r"|\b(?:fence|fencing)\s+(?:around|surrounds?|encloses?)\s+(?:the\s+)?(?:entire\s+|whole\s+|full\s+)?(?:(?:back|front|private)\s?(?:yard|garden|lot)?|yard|garden|lot)\b"
                   r"|\b(?:fence|fencing)\s+(?:in|on|at)\s+(?:the\s+)?back\b|\bback(?:\s+of\s+the\s+(?:house|home|property))?\s+(?:is\s+)?(?:fully\s+)?fenced\b", ytext, re.I):
        out["fenced_yard"] = 1
    elif _fence_around_home(ytext):
        out["fenced_yard"] = 1
    elif _no_private_yard(text):
        out["fenced_yard"] = 0  # "No yard but shared courtyard": no private yard, so no fenced yard
    return out


_FENCE_HOME = re.compile(r"(?:^|[.!\n;,|])[ \t]*(?:fully[ \t]+|completely[ \t]+)?fenced[ \t]*(?:[.!\n;,|]|$)"
                         r"|\b(?:fully[ \t]+|completely[ \t]+)?fenced[ \t]+(?:all[ \t]+(?:around|the[ \t]+way[ \t]+around)|on[ \t]+all[ \t]+sides|in[ \t]+full)\b"
                         r"|\b(?:\d{1,2}[- ]?(?:ft|foot|feet|')\.?[- ]?(?:tall[ \t]+)?|privacy[ \t]+|wood(?:en)?[ \t]+|chain[- ]?link[ \t]+|vinyl[ \t]+|wrought[ \t]+iron[ \t]+)+fence\b"
                         r"|\b(?:lot|property|house|home|grounds)[ \t]+is[ \t]+(?:fully[ \t]+|completely[ \t]+)?fenced\b"
                         r"|\b(?:fence|fencing)[ \t]+(?:all[ \t]+(?:around|the[ \t]+way[ \t]+around)|on[ \t]+all[ \t]+sides|surrounds?[ \t]+(?:the[ \t]+)?(?:property|house|home|lot|yard))\b", re.I)
_FENCE_NOT_HOME = re.compile(r"\b(?:pool|playground|community|complex|dog[- ]?park|dog[- ]?run|courtyard|patio|balcon\w*|deck|porch|terrace|garden[- ]style|parking|lot[- ]?entrance|gate[sd]?[- ]?(?:community|access)|between|neighbou?rs?)\b|\bno[ \t]+fenc|\bnot[ \t]+fenc|\bunfenced", re.I)


def _fence_around_home(text: str) -> bool:
    """Cycle 21: "Fenced." on its own, "6-ft fence all around", "fenced all around" say the home is fenced. A fence round a pool, patio, courtyard or a
    shared area is not a fenced yard."""
    for m in _FENCE_HOME.finditer(text):
        a = max(text.rfind(x, 0, m.start()) for x in (".", "\n", ";")) + 1 if m.group(0)[0] not in ".!\n;,|" else m.start() + 1
        b_ = min([i for i in (text.find(". ", m.end()), text.find("\n", m.end()), text.find(";", m.end())) if i != -1] or [len(text)])
        clause = text[a:b_] if m.group(0)[0] not in ".!\n;,|" else text[m.start() + 1:m.end() + 1]
        if _FENCE_NOT_HOME.search(clause):
            continue
        return True
    return False


def _no_private_yard(text: str) -> bool:
    """"No yard", "No private yard but shared courtyard": the home has no yard of its own. "No yard work" is not that."""
    return bool(re.search(r"\b(?:no|without)\s+(?:private\s+|back\s*|front\s+|fenced\s+)?yard\b(?!\s*(?:work|care|maintenance|upkeep|mowing|duty|duties|sales?|waste|trimming))", text, re.I))


_PET_FILLER = re.compile(r"\b(?:deposits?|monthly|fees?|rent|ok|okay|allowed|permitted|accepted|welcomed?|fine|friendly|policy|rules?|with|and|or|per|a|an|the|is|are|we|love|both|each|every|total|combined|in|of|on|at|to|for|your|any|all|up|unit|apartment|home|place|building|month|mo|pet|pets|non|refundable|nonrefundable|one[- ]time|plus|then|extra|only|have|has|can|may)\b", re.I)


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
    low = re.sub(r"\bweight[ \t]+(?:limit|cap|max(?:imum)?)\b", "limit", low, flags=re.I)
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
    low = re.sub(r"\bone[ \t]*-?[ \t]*time\b", " ", low, flags=re.I)  # cycle 25: "one-time" is a kind of charge, not a count of one
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
    low = re.sub(r"\b(?:cats?|dogs?|animals?|max(?:imum)?|limit|cap|weight|up|under|over|more|than|pets?|lbs?|pounds?)\b", " ", low, flags=re.I)
    return not re.search(r"[A-Za-z]{2,}", low)


def _pet_limits(text: str) -> list[str]:
    """Weight, breed and count limits on pets ("dogs under 50 lbs"), as short plain lines, since the pets field only says which pets."""
    found: list[str] = []
    for raw in _clauses(text):
        if not re.search(r"\b(?:dogs?|cats?|pets?|animals?|breeds?)\b", raw, re.I):
            continue
        clause = " ".join(raw.split()).strip(" -:,")
        clause = re.split(r"[\u2714\u2713\u2705\u2611]\ufe0f?\s*(?:\([^)]*\)\s*)?", clause)[-1].strip(" -:,")  # cycle 23: "Heated garage ✔ ($135/mo) Pet friendly (dogs up to 40 lbs)": the pet rule is the part after the last tick, not the whole feature line
        if not re.search(r"\b(?:dogs?|cats?|pets?|animals?|breeds?)\b", clause, re.I):
            continue
        if re.search(r"\b\d{1,3}\s*(?:lbs?|pounds?)|\bbreed|\bweight|\brestrict\w*|\blimits?\b|\bmax(?:imum)?\b|\bunder \d|\bup to \d|\b(?:two|2) pets\b|\bsize\b", clause, re.I) \
                and len(clause) <= 140 and not any(clause.lower() in f.lower() for f in found):
            found.append(clause[0].upper() + clause[1:])
    return found[:2]


def _app_fee_per_person(text: str) -> str:
    """"Application fee $55 per adult": the fee field is one amount, so keep the per-person wording visible."""
    m0 = re.search(r"\$\s?(\d{1,4}(?:\.\d\d)?)[ \t]*(?:each|apiece|per[ \t]+(?:adult|person|applicant|occupant))[ \t]+(?:application|app|screening)(?:[ \t]+(?:processing[ \t]+)?fees?)?\b", text, re.I)
    if m0:  # cycle 21: "$40 each application fee per adult"
        return f"The application fee {_usd(float(m0.group(1)))} is charged per person, so each adult who applies pays it."
    m = re.search(r"application(?: processing)? fees?[^.\n]{0,25}?\$\s?(\d{1,4}(?:\.\d\d)?)[^.\n]{0,12}?\b(?:per|each|/)\s*(adult|applicant|person|occupant|tenant|resident|roommate)", text, re.I) \
        or re.search(r"\$\s?(\d{1,4}(?:\.\d\d)?)\s*(?:application(?: fee)?|app fee)[^.\n]{0,12}?\b(?:per|each|/)\s*(adult|applicant|person|occupant|tenant|resident|roommate)", text, re.I) \
        or re.search(r"application(?: processing)? fees?[^.\n]{0,40}?(?:\bper|\beach)\s+(adult|applicant|person|occupant|tenant|resident|roommate)", text, re.I)
    if not m:  # cycle 19: "Application $40 each", "Apply: $55 per person", "Application: $35 each adult"
        m = re.search(r"(?<![\w-])(?:application|apply|app)(?:[ \t]+(?:online|now|here|today))?[ \t]*[:\-=]?[ \t]*\$\s?(\d{1,4}(?:\.\d\d)?)[ \t]*(?:(?:per|each|/)[ \t]*(adult|applicant|person|occupant|tenant|resident|roommate)s?\b|(each)\b)", text, re.I)
        if m and not m.group(2):
            return f"The application fee {_usd(float(m.group(1)))} is charged per person, so each adult who applies pays it."
    if not m:  # cycle 20: "Application fee $40 each", "Applicants pay $50 each", "Applicant screening fee $38 each", "Each applicant pays $45"
        m = re.search(r"(?<![\w-])(?:applicants?|applications?|app)[ \t]+(?:(?:screening|processing|background|check)[ \t]+)?(?:fees?|pay|pays|charges?|cost|costs)\b[ \t:\-=(]{0,4}(?:is |are |of )?\$\s?(\d{1,4}(?:\.\d\d)?)(?!\d|,\d)[ \t)]{0,2}(?:,[ \t]*)?(each)\b", text, re.I) \
            or re.search(r"(?<![\w-])each[ \t]+(?:applicant|adult|occupant|tenant)[ \t]+(?:pays?|must[ \t]+pay|is[ \t]+charged|will[ \t]+pay)[ \t:\-=]*(?:a[ \t]+|an[ \t]+)?(?:application[ \t]+|screening[ \t]+)?(?:fees?[ \t:\-=]*(?:of[ \t]+)?)?\$\s?(\d{1,4}(?:\.\d\d)?)(?!\d|,\d)", text, re.I)
        if m:
            return f"The application fee {_usd(float(m.group(1)))} is charged per person, so each adult who applies pays it."
    if not m:  # "Screening: $50 per adult"
        m = re.search(r"\$\s?(\d{1,4}(?:\.\d\d)?)\s*(?:per|each|/)\s*(adult|applicant|person|occupant|tenant|resident|roommate)\b", text, re.I)
        line_start = text.rfind("\n", 0, m.start()) + 1 if m else 0
        if not m or not re.search(r"\bapplic|\bapp fee|\bscreening|\bbackground check", text[line_start:m.end() + 40], re.I):
            return ""
        if re.search(r"credit[ \t]+(?:check|report)(?:[ \t]+fees?)?[ \t:\-=]*$", text[max(line_start, m.start() - 30):m.start()], re.I):
            return ""  # a credit check fee has its own reading
    who = m.group(m.lastindex).lower()
    amount = f" {_usd(float(m.group(1)))}" if m.lastindex >= 2 and m.group(1).replace('.', '').isdigit() else ""
    return f"The application fee{amount} is charged per {who}, so each adult who applies pays it."


def app_fee_per_adult(text: str) -> float | None:
    """The application fee when the listing charges it per adult ("$50 per adult"), else None."""
    m = re.search(r"\$\s?(\d{1,4}(?:\.\d\d)?)", _app_fee_per_person(text) or "")
    return float(m.group(1)) if m else None


def app_fee_note_for_people(values: dict[str, Any], people: int) -> dict[str, Any]:
    """For the Add preview only: when the application fee is charged per adult and the search has several people, say what
    all of them pay together. The ``application_fee`` field itself stays the one-person amount. Returns ``values`` (changed
    in place) so a caller can chain it."""
    note = values.get("found_in_listing") or ""
    fee = values.get("application_fee")
    if people > 1 and isinstance(fee, (int, float)) and fee > 0 and ("is charged per" in note or "charged to each adult" in note) and " adults that is " not in note:
        extra = f" For {people} adults that is {_usd(fee * people)} together."
        lines = note.split("\n")
        for i, ln in enumerate(lines):  # cycle 18: only the per-adult application fee line gets the sentence, never the last note
            if ("is charged per" in ln or "charged to each adult" in ln) and re.search(r"application fee|admin fee|credit check fee", ln, re.I):
                lines[i] = ln.rstrip() + extra
                break
        else:
            return values
        values["found_in_listing"] = "\n".join(lines)
    return values


def _move_in_months(text: str) -> tuple[int, bool]:
    """(months of rent due at move-in, deposit also due) from "first and last month" or "first, last and deposit"."""
    m = re.search(r"\b(?:first|1st)\b(?:\s+month(?:'?s)?(?:\s+rent)?)?\s*(?:,|and|&|\+|/|plus)\s*(?:and\s+)?\blast\b(?:\s+month(?:'?s)?(?:\s+rent)?)?"
                  r"(?:\s*(?:,|and|&|\+|/|plus)\s*(?:a\s+)?(?:the\s+)?(?:security\s+)?(deposit))?", text, re.I)
    if not m:
        mr = re.search(r"\blast\b(?:[ \t]+month(?:'?s)?(?:[ \t]+rent)?)?[ \t]*(?:,|and|&|\+|/|plus)[ \t]*(?:and[ \t]+)?(?:the[ \t]+)?\b(?:first|1st)\b[ \t]+month", text, re.I)
        if mr:  # cycle 22: "Last month's rent plus first month required"
            return 2, bool(re.match(r"[ \t]*(?:'?s)?(?:[ \t]+rent)?[ \t]*(?:,|and|&|\+|/|plus)[ \t]*(?:a[ \t]+|the[ \t]+)?(?:security[ \t]+)?deposit", text[mr.end():mr.end() + 40], re.I))
    if not m:
        m2 = re.search(r"\blast[ \t]+month(?:'?s)?(?:[ \t]+rent)?[ \t]+(?:is[ \t]+|are[ \t]+)?(?:due|required|payable|collected)[ \t]+(?:at|before|on|upon|with)[ \t]+(?:lease[ \t]+)?(?:signing|move[- ]?in)\b"
                       r"|\b(?:due|required|payable)[ \t]+(?:at|before|on|upon)[ \t]+(?:lease[ \t]+)?(?:signing|move[- ]?in)[^.\n;]{0,25}\blast[ \t]+month", text, re.I)
        # last month's rent is due at signing, so the first month is due too: two months of rent up front
        return (2, False) if m2 else (0, False)
    return 2, bool(m.group(1))


def _deposit_each(text: str) -> float | None:
    """Cycle 17: a deposit given once for several items: "First, last and security deposit required ($2,800 each)", "first month,
    last month and deposit, $1,500 each", "$2,800 each for first, last and security deposit". The amount is what each item
    costs, so it is the security deposit. None when the line gives no per-item amount."""
    amt = r"\$\s?(\d{1,3}(?:,\d{3})+(?:\.\d\d)?|\d+(?:\.\d\d)?)(?![\d,])"
    items = r"(?:first|1st)\b(?:[ \t]+month(?:'?s)?(?:[ \t]+rent)?)?[ \t]*(?:,|and|&|\+|/|plus)[ \t]*(?:and[ \t]+)?(?:last)\b(?:[ \t]+month(?:'?s)?(?:[ \t]+rent)?)?[ \t]*(?:,|and|&|\+|/|plus)[ \t]*(?:and[ \t]+)?(?:a[ \t]+|the[ \t]+)?(?:security[ \t]+)?deposit\b"
    for pat in (items + r"[^.\n;$]{0,40}?[ \t(,:\-]*" + amt + r"[ \t]*(?:each|apiece|per[ \t]+item|for[ \t]+each)\b",
                amt + r"[ \t]*(?:each|apiece)\b[ \t]*(?:for|toward|on)?[ \t]*(?:the[ \t]+)?" + items):
        m = re.search(pat, text, re.I)
        if m:
            v = _num(m.group(1))
            return v if 100 <= v <= 50000 else None
    return None


_WORD_NUM = {"one": 1, "a": 1, "1": 1, "two": 2, "2": 2}


_DEP_WHICHEVER = re.compile(r"\$[ \t]?(?P<amt>\d{1,2},\d{3}|\d{2,5})(?:\.\d\d)?[ \t]*(?:or|/)[ \t]*(?P<pct>\d{1,3}(?:\.\d)?)[ \t]*%[ \t]*(?:of[ \t]+)?(?:the[ \t]+)?(?:monthly[ \t]+|one[ \t]+month'?s?[ \t]+)?(?:rent)?[ \t,;(-]*whichever[ \t]+(?:is[ \t]+)?(?P<w>greater|higher|more|larger|less|lower|smaller)", re.I)
_NAMED_DEP_WORDS = r"(?:pets?|dogs?|cats?|animals?|key|keys|fob|fobs|parking|garage|carport|storage|locker|bike|gate|remote|mailbox|pool|holding|reservation|application|cleaning|furniture|utility|utilities)"
_NAMED_DEP_KEEP = re.compile(r"\b(?:security|damage|lease|first[ \t]+month|last[ \t]+month|rental|rent[ \t]+deposit)\b", re.I)


def _blank_named_deposits(text: str) -> str:
    """Cycle 26: a "$300 refundable deposit" inside a pet, key, parking or other named clause is that thing's deposit, never the security deposit. The amount
    next to the word "deposit" is blanked when its own clause names such a thing, or when its sentence starts with a pet word ("Pets: dogs OK up to 75 lb, pet rent
    not charged, $300 refundable deposit.") and the clause does not say security, damage or lease. Same length, so positions stay."""
    out = text
    amt = r"\$[ \t]?\d{1,3}(?:,\d{3})*(?:\.\d\d)?|\$[ \t]?\d+(?:\.\d\d)?"
    pat = re.compile(r"(?:(?:security[ \t]+|refundable[ \t]+|non[- ]?refundable[ \t]+|one[- ]time[ \t]+)?deposits?\b[ \t:\-=(]{0,4}(?:of[ \t]+|is[ \t]+)?(?:" + amt + r"))|(?:(?:" + amt + r")[ \t]*(?:/[ \t]*mo\w*[ \t]*)?(?:one[- ]time[ \t]+|non[- ]?refundable[ \t]+|refundable[ \t]+)*(?:[a-z]+[ \t]+)?deposits?\b)", re.I)
    for m in pat.finditer(text):
        brk = list(re.finditer(r"[.!?](?=\s|$)|[;|\n]", text))
        a = max([x.end() for x in brk if x.end() <= m.start()] + [0])
        b = min([x.start() for x in brk if x.start() >= m.end()] + [len(text)])
        sent = text[a:b]
        cs = max(text.rfind(",", a, m.start()), text.rfind("(", a, m.start()), a - 1) + 1
        ce_c = [i for i in (text.find(c, m.end(), b) for c in ",)") if i >= 0]
        clause = text[cs:min(ce_c) if ce_c else b]
        near = text[max(cs, m.start() - 14):m.end()]
        named = re.search(r"\b" + _NAMED_DEP_WORDS + r"\b", near, re.I) and not _NAMED_DEP_KEEP.search(clause)
        pet_sentence = bool(_PET_LEAD.match(sent.strip())) and not _NAMED_DEP_KEEP.search(clause) and not re.search(r"\bsecurity[ \t]+deposit|\blease\b", sent, re.I)
        if named or pet_sentence:
            out = out[:m.start()] + " " * (m.end() - m.start()) + out[m.end():]
    return out


def _deposit_or_fee(text: str) -> tuple[float, float, str, str, str] | None:
    """Cycle 26: "Security deposit $1,000 or one-time fee $450 non-refundable": two ways to pay, not two charges. Returns (deposit, fee, text with the fee
    phrase blanked, the note, the fee phrase) or None. The deposit is saved (the larger cash) and the fee is a note, so the cost is not both."""
    amt = r"\$[ \t]?(\d{1,2},\d{3}(?:\.\d\d)?|\d{2,5}(?:\.\d\d)?)(?![\d,])"
    fee_words = r"(?:one[- ]time[ \t]+|non[- ]?refundable[ \t]+|flat[ \t]+)*(?:[a-z]+[ \t]+){0,2}fee"
    pats = (r"(?:security[ \t]+|refundable[ \t]+)?deposits?[ \t]*(?:is|of|:|=|-)?[ \t]*" + amt + r"[ \t]*[,;(]?[ \t]*(?:or|/|OR)[ \t]*(?:a[ \t]+|an[ \t]+)?(?P<fee>" + fee_words + r"[ \t]*(?:of|is|:|=)?[ \t]*" + amt + r"(?:[ \t]*\(?(?:non[- ]?refundable|one[- ]time)\)?)?)",
            r"(?:security[ \t]+|refundable[ \t]+)?deposits?[ \t]*(?:is|of|:|=|-)?[ \t]*" + amt + r"[ \t]*[,;(]?[ \t]*(?:or|/|OR)[ \t]*(?:a[ \t]+|an[ \t]+)?(?P<fee2>" + amt + r"[ \t]*(?:one[- ]time[ \t]+|non[- ]?refundable[ \t]+)*(?:[a-z]+[ \t]+)?fee\b(?:[ \t]*\(?(?:non[- ]?refundable|one[- ]time)\)?)?)")
    for pat in pats:
        m = re.search(pat, text, re.I)
        if not m:
            continue
        dep = _num(m.group(1))
        fee_txt = m.group("fee") if "fee" in m.groupdict() and m.groupdict().get("fee") else m.group("fee2")
        fm = re.search(amt, fee_txt)
        fee = _num(fm.group(1)) if fm else 0.0
        if not (dep and fee):
            continue
        phrase = " ".join(fee_txt.split())
        note = (f"The listing gives a {_usd(dep)} security deposit or a one-time fee ({phrase}). They are two ways to pay, so the {_usd(dep)} deposit is saved "
                f"and the {_usd(fee)} fee is not added. Ask which one you would pick and what it costs.")
        return dep, fee, text[:m.start("fee") if m.groupdict().get("fee") else m.start("fee2")] + " " * len(fee_txt) + text[m.end():], note, fee_txt
    return None


_BEST_CASE_DEPOSIT = (
    r"\$\s?(\d{1,3}(?:,\d{3})+(?:\.\d\d)?|\d+(?:\.\d\d)?)[ \t]*(?:security[ \t]+)?deposit[ \t]*,?[ \t]*(?:(?:with|upon|on|w/)[ \t]+(?:approved|good|qualifying|excellent)[ \t]+credit|o\.?a\.?c\.?\b|(?:with|subject to)[ \t]+credit[ \t]+approval)",
    r"\b(?:security[ \t]+)?deposits?[ \t]*(?:is[ \t]+|of[ \t]+|[:\-][ \t]*)?(?:as low as|as little as|low as|starting (?:at|from)|starts? (?:at|from)|beginning at|from only)[ \t]*\$\s?(\d{1,3}(?:,\d{3})+(?:\.\d\d)?|\d+(?:\.\d\d)?)",
    r"\b(?:security[ \t]+)?deposits?[ \t]*(?:is[ \t]+|of[ \t]+|[:\-][ \t]*)?\$\s?(\d{1,3}(?:,\d{3})+(?:\.\d\d)?|\d+(?:\.\d\d)?)[ \t]*(?:(?:with|upon|on|w/)[ \t]+(?:approved|good|qualifying|excellent)[ \t]+credit|o\.?a\.?c\.?\b)",
)


def _best_case_deposit(text: str) -> tuple[float | None, str]:
    """A deposit that is only the best case ("$500 deposit with approved credit", "deposit as low as $500"): not what every renter
    pays, so it is not saved as the deposit. Returns (amount, text with that phrase blanked)."""
    for pat in _BEST_CASE_DEPOSIT:
        m = re.search(pat, text, re.I)
        if m:
            return _num(m.group(1)), text[:m.start()] + " " * (m.end() - m.start()) + text[m.end():]
    return None, text


_NONREF = r"(?:non[- ]?refundable|not[ \t]+refundable|isn'?t[ \t]+refundable|is[ \t]+not[ \t]+refundable|no[ \t]+refunds?|will[ \t]+not[ \t]+be[ \t]+refunded|not[ \t]+returned|non[- ]?returnable)"
_NOT_THIS_DEPOSIT = re.compile(r"\b(?:pet|pets|parking|holding|reservation|key|keys|application|garage|fob|remote|gate|access|mailbox|storage|bike|locker|lock|card|pool|admin\w*)[ \t]+$", re.I)


def _nonrefundable_deposit(text: str) -> tuple[float, str] | None:
    """Cycle 23: a deposit the listing says is not refundable ("Security deposit is $400 (not refundable, it is a cleaning fee)", "Deposit $400 non-refundable",
    "$400 non-refundable cleaning deposit", "Non-refundable deposit: $400"). Money you never get back is a move-in fee, not a deposit. The "not refundable" words
    must sit right against that deposit's own amount ("deposit $2,980 + $400 non-refundable pet fee" is a refundable deposit). Returns (amount, the clause) or None.
    A pet, parking, key or application deposit has its own reading."""
    amt = r"\$[ \t]?(\d{2,5}(?:\.\d\d)?|\d{1,2},\d{3}(?:\.\d\d)?)(?!\d|,\d)"
    pats = (r"\b(?P<w>\w+[ \t]+)?deposits?\b[ \t]*(?:is|are|of|:|=|-)?[ \t]*(?:only[ \t]+)?" + amt + r"[ \t]*[,(\-]?[ \t]*" + _NONREF,
            amt + r"[ \t]*[,(\-]?[ \t]*" + _NONREF + r"[ \t]+(?:[a-z]+[ \t]+)?(?:security[ \t]+)?deposits?\b",
            _NONREF + r"[ \t]+(?:(?P<w2>[a-z]+)[ \t]+)?deposits?\b[ \t]*(?:is|are|of|:|=|-)?[ \t]*" + amt)
    for clause in re.split(r"\n|;|\.(?=\s|$)", text):
        for i, pat in enumerate(pats):
            for m in re.finditer(pat, clause, re.I):
                word = (m.groupdict().get("w") or m.groupdict().get("w2") or "")
                before = clause[max(0, m.start() - 14):m.start()] + (word if i != 1 else "")
                if i == 1:
                    mid = re.search(r"deposits?", clause[m.start():], re.I)
                    pre = clause[m.start():m.start() + (mid.start() if mid else 0)]
                    if re.search(r"\b(?:pet|pets|parking|holding|reservation|key|keys|application|garage|fob|remote|gate|access|mailbox|storage|bike|locker|lock|card|pool|admin\w*)\b", pre, re.I):
                        continue
                elif _NOT_THIS_DEPOSIT.search((word + " ") if word else clause[max(0, m.start() - 14):m.start()]) or (word and re.fullmatch(r"(?:pet|pets|parking|holding|reservation|key|keys|application|garage|fob|remote|gate|access|mailbox|storage|bike|locker|lock|card|pool|admin\w*)", word.strip(), re.I)):
                    continue
                v = _num(next(g for g in m.groups() if g and re.fullmatch(r"[\d,]+(?:\.\d\d)?", g)))
                if 50 <= v <= 5000:
                    return v, " ".join(clause.split())
    return None


_COND_DEPOSIT = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+(?:\.\d\d)?|\d+(?:\.\d\d)?)[ \t]*(?:security[ \t]+|refundable[ \t]+|damage[ \t]+)?deposit\b[ \t,]*"
                           r"((?:if|when|for|with|should|unless|depending|based[ \t]+on|subject[ \t]+to|only[ \t]+if)\b[^.\n;]{0,50}?(?:credit|income|score|co-?signer|guarantor|history|references?|background)[^.\n;]{0,20})"
                           r"|\b(?:security[ \t]+)?deposit[ \t]*(?:of|is|:|-)?[ \t]*\$\s?(\d{1,3}(?:,\d{3})+(?:\.\d\d)?|\d+(?:\.\d\d)?)[ \t,]*"
                           r"((?:if|when|for|with|should|unless|depending|based[ \t]+on|subject[ \t]+to|only[ \t]+if)\b[^.\n;]{0,50}?(?:credit|income|score|co-?signer|guarantor|history|references?|background)[^.\n;]{0,20})", re.I)


def _conditional_deposit(text: str) -> tuple[float, str, str] | None:
    """Cycle 18: "$1,200 security deposit if credit is poor", "Deposit $500 for tenants with no cosigner". A deposit that only applies on a condition is not
    the deposit for everyone. Returns (amount, the condition, text with that phrase blanked) or None. A condition that is the best case
    (approved or good credit) is left to _best_case_deposit."""
    for m in _COND_DEPOSIT.finditer(text):
        cond = m.group(2) or m.group(4)
        if re.search(r"(?:approved|good|qualifying|excellent|great)[ \t]+credit|credit[ \t]+approval", cond, re.I):
            continue
        amount = _num(m.group(1) or m.group(3))
        return amount, " ".join(cond.split()).rstrip(" ,"), text[:m.start()] + " " * (m.end() - m.start()) + text[m.end():]
    return None


def _bare_security_amount(text: str) -> float | None:
    """Cycle 20: "$3,100 security" with no word "deposit" ("first month + $3,100 security + $200 move-in fee", "$1,500 sec dep"): the security deposit.
    Not "$50 security fee", a security system or a security camera."""
    m = re.search(r"(?<![\w$])\$\s?(\d{1,3}(?:,\d{3})+(?:\.\d\d)?|\d+(?:\.\d\d)?)(?!\d)[ \t]*(?:/[ \t]*mo\w*)?[ \t]*(?:security|sec\.?[ \t]*dep\.?)(?![ \t]*(?:deposit|fees?|system|camera|cameras|cam|guard|gate|door|lock|patrol|alarm|building|service|charge|/|per|monthly|a[ \t]+month))\b", text, re.I)
    if not m:  # cycle 21: "Security $1,260", "Security: $1,260" (the label comes first)
        m = re.search(r"(?<![\w$-])(?:security|sec\.?[ \t]*dep\.?)[ \t]*[:=\-]?[ \t]*\$\s?(\d{1,3}(?:,\d{3})+(?:\.\d\d)?|\d+(?:\.\d\d)?)(?![\d,])(?![ \t]*(?:/|per|monthly|a[ \t]+month|each[ \t]+month|fees?|deposit))", text, re.I)
    if not m:
        return None
    v = _num(m.group(1))
    return v if 100 <= v <= 50000 else None


def _deposit_in_months(text: str) -> float:
    """The security deposit written as a number of months of rent ("security deposit one month", "deposit equal to one month's
    rent"), as that number of months. 0 when the text gives none."""
    text = re.sub(r"\b(1|2)\u00bd", r"\1.5", text)
    text = re.sub(r"\b(one|two|1|2)[ \t]+and[ \t]+(?:a|one)[- ]half\b|\b(1|2)[ \t]+1/2\b", lambda mm: f"{(mm.group(1) or mm.group(2)).lower().replace('one', '1').replace('two', '2')}.5", text, flags=re.I)
    m = re.search(r"\b(?:security |damage )?deposits?\b[ \t:\-]{0,4}(?:is |of |equal to |equals |=)?[ \t]*(\d(?:\.\d{1,2})?)[ \t]*(?:x|times|months?(?:'s?)?(?:[ \t]+(?:of[ \t]+)?rent)?)(?:[ \t]+(?:the[ \t]+|of[ \t]+|monthly[ \t]+)*rent)?\b", text, re.I)
    if m and 0 < float(m.group(1)) <= 6:
        return float(m.group(1))
    if re.search(r"\b(?:security |damage )?deposits?\b[ \t:\-]{0,4}(?:is |are |will be )?(?:the )?(?:same as|same amount as|equal to|equals|equivalent to|matches|=)[ \t]+(?:the |your |one |1 )?(?:monthly |first month'?s? )?rent\b", text, re.I):
        return 1  # cycle 18: "deposit same as rent"
    for pat in (r"\b(?:security |damage )?deposits?\b[ \t:\-]{0,4}(?:is |of |equal to |equals |equivalent to |=)?[ \t]*(one|two|a|1|2)[- ]months?(?:'s?)?(?:[ \t]+(?:of[ \t]+)?rent)?\b",
                r"(?<![\d.])(one|two|1|2|1\.5|2\.5|1\.25)[- ]months?(?:'s?)?(?:[ \t]+(?:of[ \t]+)?rent)?[ \t]+(?:(?:security |damage )deposit|deposit)\b",
                r"\b(one|two|1|2)[- ]months?(?:'s?)?[ \t]+(?:security|damage)\b(?![ \t]+(?:camera|cameras|cam|system|guard|gate|door|lock|patrol|alarm|building))"):
        m = re.search(pat, text, re.I)
        if m:
            g = m.group(1).lower()
            return _WORD_NUM[g] if g in _WORD_NUM else float(g)
    return 0


_DEP_PRE = r"(?:\b(?:(?:security|damage|refundable)[ \t]+)?deposits?\b|\bsec\.?[ \t]*dep\.?(?![a-z]))"
_DEP_DUE = r"(?:[ \t]*(?:is[ \t]+|are[ \t]+)?(?:due|payable|required|collected)[ \t]+(?:at|on|before|by|upon)[ \t]+(?:lease[ \t]+)?(?:signing|move[- ]?in)?)?"
_DEP_EQ = r"(?:(?:is|are|will[ \t]+be|of|equal[ \t]+to|equals|equivalent[ \t]+to|same[ \t]+as|about|approx\.?|=)[ \t]+)*(?:(?:the|a|an|your)[ \t]+)?"
_DEP_NUM = r"(one[- ]and[- ]a[- ]half|one[- ]half|half(?:[ \t]+a)?|1/2|0?\.5|one|two|1\.25|1\.5|2\.5|\u00bd|1|2|a)"
_DEP_MONTH = r"[- ]?(?:month|mo)s?(?:'s?)?(?:[ \t]+(?:of[ \t]+)?(?:the[ \t]+)?(?:monthly[ \t]+)?rent)?(?![a-z])"
_DEP_WORDS = {"one": 1.0, "a": 1.0, "1": 1.0, "two": 2.0, "2": 2.0, "half": 0.5, "half a": 0.5, "1/2": 0.5, ".5": 0.5, "0.5": 0.5, "\u00bd": 0.5, "one-half": 0.5, "one half": 0.5,
              "1.5": 1.5, "2.5": 2.5, "1.25": 1.25, "one and a half": 1.5, "one-and-a-half": 1.5}


def _deposit_months_general(text: str) -> tuple[float, str] | None:
    """Cycle 27: the security deposit written as months of rent in any of the usual layouts: "Security deposit: half month", "Security deposit half month's rent",
    "Half month security deposit", "Sec dep 1.5 months", "Security deposit due at signing: one month", "Deposit due at signing equal to one month". Returns
    (months, the phrase) or None. Only a deposit with no kind word before it (pet, parking, key and so on) is the security deposit."""
    for pat in (_DEP_PRE + _DEP_DUE + r"[ \t:\-=,]{0,4}" + _DEP_EQ + _DEP_NUM + _DEP_MONTH,
                r"(?<![\d.$])" + _DEP_NUM + _DEP_MONTH + r"[ \t]+(?:(?:security|damage)[ \t]+)?deposit\b"):
        for m in re.finditer(pat, text, re.I):
            if _NOT_THIS_DEPOSIT.search(text[max(0, m.start() - 16):m.start()]):
                continue
            g = re.sub(r"[ \t]+", " ", m.group(1).lower())
            if re.match(r"\s*(?:/|per\b)", text[m.end():]) or re.match(r"[ \t]*(?:old|lease|term|minimum|min\b)", text[m.end():], re.I):
                continue  # "deposit one month lease", "1 month minimum": a lease length, not months of rent
            if g in _DEP_WORDS:
                return _DEP_WORDS[g], " ".join(m.group(0).split())
    return None


def _blank_named_month_deposits(text: str) -> str:
    """Cycle 27: a deposit written in months inside a pet, parking, key or other named clause ("Pet deposit: one month", "Key deposit 1.5 months") is that thing's deposit, never the
    security deposit. The clause is blanked (same length) before the months are read."""
    pat = re.compile(r"\b" + _NAMED_DEP_WORDS + r"[ \t]+(?:refundable[ \t]+)?deposits?\b[ \t:\-=]{0,4}(?:(?:is|of|equal to|equals|=)[ \t]+)?(?:\d(?:\.\d+)?|one|two|a|half(?:[ \t]+a)?|1/2)[- ]?months?\b(?:'s?)?(?:[ \t]+(?:of[ \t]+)?rent)?", re.I)
    return pat.sub(lambda m: " " * len(m.group(0)), text)


def _deposit_or_fee_refundable(text: str) -> tuple[float, str] | None:
    """Cycle 27: "Deposit or fee: $1,000 refundable", "Deposit/fee $800 (refundable)": one amount under a "deposit or fee" label that the listing says comes back,
    so it is the security deposit. Without the word refundable it stays unread (a fee is not a deposit)."""
    m = re.search(r"\bdeposit[ \t]*(?:or|/|and/or)[ \t]*(?:move[- ]in[ \t]+)?fee\b[ \t]*[:\-=]?[ \t]*\$[ \t]?(\d{1,2},\d{3}(?:\.\d\d)?|\d{2,5}(?:\.\d\d)?)(?![\d,])[ \t]*[,(\-]?[ \t]*(?:fully[ \t]+)?(?<!non-)(?<!non )(?<!not )refundable\b", text, re.I)
    if not m or re.search(r"\bnon[- ]?refundable|\bnot[ \t]+refundable", m.group(0), re.I):
        return None
    return _num(m.group(1)), " ".join(m.group(0).split())


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


_CLOSE_NOUN = r"(?:(?:settlement|closing)[ \t]+(?:costs?|charges?|fees?)|(?:costs?|charges?)[ \t]+at[ \t]+(?:closing|settlement|close))"
_CLOSE_FILL = (r"(?:[ \t:\-=(,~]|approx\.?|est\.?|\b(?:about|around|approximately|estimated|roughly|is|are|of|at|run|runs|total|totals|come|comes|to|be|will|should|near|close)\b)*")
_CLOSE_AMT = r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?(?!\d)"
_CLOSE_NOUN_FOR_BUYER = (r"\b" + _CLOSE_NOUN + r"(?:[ \t]+(?:for|to|paid[ \t]+by|due[ \t]+from|payable[ \t]+by)[ \t]+(?:the[ \t]+)?buyer(?:'?s)?|[ \t]*\((?:buyer'?s?|est\w*\.?)\))"
                         + _CLOSE_FILL + _CLOSE_AMT)
_CLOSE_BUYER_NOUN = (r"\bbuyer(?:'?s)?[ \t]+(?:(?:est\w*\.?|expected|total)[ \t]+)*" + _CLOSE_NOUN + _CLOSE_FILL + _CLOSE_AMT)


def _closing_costs(text: str) -> float | None:
    """"Estimated closing costs $9,800" -> 9800. What the seller pays ("Seller will pay $7,000 in closing costs", "seller-paid closing
    costs $5,000", "closing costs paid by seller") is a credit and never the buyer's closing costs, and neither is a seller's cap."""
    pats = (r"\bclosing costs?(?:[ \t]*\((?:buyer'?s?|est\w*\.?)\)|[ \t]+for[ \t]+(?:the[ \t]+)?buyer(?:'?s)?|[ \t]+(?:runs?|totals?|comes?[ \t]+to)|[ \t]+(?:paid|due|payable|covered|owed)[ \t]+(?:by|from)[ \t]+(?:the[ \t]+)?buyer(?:'?s?)?|\s+(?:(?:are|is)\s+)?(?:est\w*\.?|estimate[d]?)(?:\s+(?:at|to be|of|around|about))?)?[ \t:\-=]{0,6}(?:(?:of|about|around|approx\.?|approximately|roughly|est\.?|at)[ \t]+|~[ \t]*)*\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?(?!\d)",
            r"\bclosing[ \t]*(?::|is\b|runs?\b|around\b|about\b|approx\b\.?|roughly\b|~)[ \t]*(?:(?:around|about|approx\.?|roughly|is)[ \t]+|~[ \t]*)*\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?(?!\d)",
            r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?[ \t]*(?:in |for )?(?:est\w*\.?[ \t]+)?closing costs?\b",
            # cycle 22: "Buyer will need about $7,000 for closing"
            r"\bbuyer(?:'?s)?[ \t]+(?:(?:will[ \t]+)?(?:needs?|pays?)|should[ \t]+(?:plan[ \t]+for|budget))[ \t]+(?:about|around|approx\.?|roughly|~)?[ \t]*\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?(?!\d)[ \t]+(?:for|in|toward|towards)[ \t]+(?:the[ \t]+)?closing\b(?![ \t]+(?:help|assistance|credit))",
            # cycle 25: "Estimated settlement costs for buyer: $7,800", "Buyer's settlement costs about $8,300", "Settlement costs (buyer): $7,800", "Buyer costs at closing: $8,300"
            _CLOSE_NOUN_FOR_BUYER, _CLOSE_BUYER_NOUN)
    for pat_no, pat in enumerate(pats):
        for m in re.finditer(pat, text, re.I):
            clause_start = max(text.rfind(".", 0, m.start()), text.rfind("\n", 0, m.start()), text.rfind(";", 0, m.start())) + 1
            before = text[clause_start:m.start()]
            if re.search(r"\b(?:seller|owner)(?:'s)?\b", before, re.I) and not re.search(r"\bbuyer(?:'s)?[ \t]+(?:own[ \t]+)?closing\b", before, re.I):
                continue  # what the seller pays is a credit, not the buyer's closing costs
            if re.match(r"closing(?![ \t]+costs?)", m.group(0), re.I) and re.search(r"\b(?:at|by|before|on|of|upon|due|until|after)[ \t]+$", before, re.I):
                continue  # "due at closing: $1,000" is not the closing costs
            if re.match(r"[^.\n;]{0,40}\b(?:paid|covered|credited|funded|contributed|provided)[ \t]+by[ \t]+(?:the[ \t]+)?(?:seller|owner)\b|[ \t,]*(?:from|by)[ \t]+(?:the[ \t]+)?(?:seller|owner)\b", text[m.end():m.end() + 70], re.I):
                continue
            clause_tail = [i for i in (text.find(".", m.end()), text.find("\n", m.end()), text.find(";", m.end())) if i != -1]
            clause = text[clause_start:min(clause_tail) if clause_tail else len(text)]  # cycle 25: only this sentence, never the one before it
            if pat_no < 3 and _CAP_WORDS.search(clause[max(0, m.start() - 40 - clause_start):m.start(1) - clause_start]) and re.search(r"\bseller\b", clause, re.I):
                continue
            value = _num(m.group(1))
            if 100 <= value <= 5_000_000:
                return value
    return None


_CLOSING_ITEM = re.compile(r"\b((?:title(?:[ \t]+(?:and|&)[ \t]+escrow)?|escrow|lender|loan|origination|appraisal|recording|attorney|settlement|survey|prepaids?)(?:[ \t]+(?:fees?|costs?|charges?))?)"
                           r"[ \t:\-=(]{0,4}(?:(?:of|about|around|approx\.?|approximately|roughly|est\.?|estimated|at)[ \t]+|~[ \t]*)*\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?(?!\d|,\d|[ \t]*(?:/|per[ \t]+(?:mo|month|yr|year)|a[ \t]+(?:month|year)|monthly|annual))", re.I)


def _closing_items(text: str) -> tuple[float, str] | None:
    """Cycle 23: closing costs the listing gives in parts ("title and escrow about $2,100 plus lender fees about $3,200"): two or more named
    parts in one sentence are added up. Returns (the total, a plain phrase naming each part) or None. A sentence about the seller is skipped."""
    parts: list[tuple[str, float]] = []
    for sent in re.split(r"[.\n;](?!\d)", text):
        if re.search(r"\bseller|\bcredit|\bconcession|\bcash[ \t]+(?:needed|to[ \t]+close)", sent, re.I):
            continue
        for m in _CLOSING_ITEM.finditer(sent):
            name, amount = " ".join(m.group(1).lower().split()), _num(m.group(2))
            if amount >= 50 and name not in [n for n, _a in parts]:
                parts.append((name, amount))
    if len(parts) >= 2:
        total = round(sum(a for _n, a in parts), 2)
        return total, " plus ".join(f"{n} ${a:,.0f}" for n, a in parts)
    return None


_EXTRA_MONTHLY_LABEL = (r"(?:capital[ \t]+(?:reserves?|improvements?)|reserves?|amenit(?:y|ies)|club[ \t]?house|master[ \t]+association|master[ \t]+assoc\.?|sinking[ \t]+fund|"
                        r"storage|elevator|doorman|security|shuttle)")
_EXTRA_MONTHLY_PER = r"(?:/[ \t]*mo(?:nth)?\b|per[ \t]+month|a[ \t]+month|each[ \t]+month|monthly\b)"
_EXTRA_AMT = r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d\d))?(?!\d)"


def _hoa_extra_monthly(text: str) -> list[tuple[float, str]]:
    """Cycle 24: a second monthly charge next to the HOA on a sale listing ("HOA $475/month plus a $75 monthly capital reserve fee",
    "Amenity fee: $40/month"). Returns (monthly amount, plain label) for each. A one-time, yearly, seller-paid, optional or included charge,
    and an assessment (read by the assessment readers), is not here."""
    out: list[tuple[float, str]] = []
    for seg in re.split(r"[.\n;](?!\d)", text):
        if re.search(r"\bone[- ]time\b|\bat[ \t]+closing\b|\bseller|\bspecial\b|\bassessments?\b|\boptional\b|\bavailable\b|\bincluded\b|\bif[ \t]+(?:you|desired|wanted)\b|\bby[ \t]+request\b|\bwaived?\b|\bper[ \t]+(?:year|quarter)\b|\bannual|\byearly\b|\bno[ \t]+\w+[ \t]+fee", seg, re.I):
            continue
        for pat_no, pat in enumerate((rf"{_EXTRA_AMT}[ \t]*(?:{_EXTRA_MONTHLY_PER}[ \t]*)?(?:a[ \t]+)?({_EXTRA_MONTHLY_LABEL})(?:[ \t]+(?:fees?|charges?|dues|payments?))?",
                    rf"\b({_EXTRA_MONTHLY_LABEL})(?:[ \t]+(?:fees?|charges?|dues|payments?))?[ \t:\-=(]{{0,4}}(?:(?:about|around|approx\.?|roughly|~)[ \t]*)?{_EXTRA_AMT}")):
            for m in re.finditer(pat, seg, re.I):
                whole = seg[max(0, m.start() - 12):m.end() + 25]
                if not re.search(_EXTRA_MONTHLY_PER, whole, re.I):
                    continue
                if re.search(r"\bper[ \t]+(?:year|quarter)|/[ \t]*(?:yr|year)|\bannual", seg[m.start():m.end() + 20], re.I):
                    continue
                groups = m.groups()
                if pat_no == 0:
                    amount, cents, label = groups[0], groups[1], groups[2]
                else:
                    label, amount, cents = groups[0], groups[1], groups[2]
                value = _num(amount) + (int(cents) / 100 if cents else 0)
                label = " ".join(label.lower().split())
                if 5 <= value < 2000 and (value, label) not in out:
                    out.append((value, label))
    return out


def _money_c(v: float) -> str:
    """$7,400 or $42.50: cents only when there are some."""
    return f"${v:,.0f}" if abs(v - round(v)) < 0.005 else f"${v:,.2f}"


_SINGLE_CLOSING = re.compile(
    r"\b((?:lender|title|settlement|escrow)(?:[ \t]*(?:,|and|&)[ \t]*(?:lender|title|settlement|escrow))*[ \t]+(?:fees?|costs?|charges?))"
    r"(?:[ \t]+(?:are|is|run|runs|total|totals|come|comes|will[ \t]+(?:run|be|total)|should[ \t]+(?:run|be)))*(?:[ \t]+(?:to|at|of))?[ \t:\-=]{0,4}"
    r"(?:(?:about|around|approx\.?|approximately|roughly|est\.?|estimated|close[ \t]+to|nearly|~)[ \t]*)*" + _EXTRA_AMT + r"(?!\d|,\d)(?![ \t]*(?:/|per[ \t]+(?:mo|month|yr|year)|a[ \t]+(?:month|year)|monthly|annual))", re.I)
_SINGLE_CLOSING_AFTER = re.compile(
    r"\bexpect[ \t]+(?:about|around|approx\.?|roughly|~)?[ \t]*" + _EXTRA_AMT + r"[ \t]+(?:in|for)[ \t]+((?:lender|title|settlement|escrow)(?:[ \t]*(?:,|and|&)[ \t]*(?:lender|title|settlement|escrow))*[ \t]+(?:fees?|costs?|charges?))", re.I)


def _closing_single(text: str) -> tuple[float, str] | None:
    """Cycle 24: closing costs given in one line as lender and title fees ("Lender and title fees run roughly $7,400", "expect around $7,400 in
    lender and title fees"). Returns (amount, the quoted phrase) or None. What the seller pays is never read here."""
    for pat in (_SINGLE_CLOSING, _SINGLE_CLOSING_AFTER):
        for m in pat.finditer(text):
            start = max(text.rfind(".", 0, m.start()), text.rfind("\n", 0, m.start()), text.rfind(";", 0, m.start())) + 1
            end_candidates = [i for i in (text.find(".", m.end()), text.find("\n", m.end()), text.find(";", m.end())) if i != -1]
            sent = text[start:min(end_candidates) if end_candidates else len(text)]
            if re.search(r"\bseller|\bcredit|\bconcession|\bowner\b", sent, re.I):
                continue
            amt_g, cents_g = (2, 3) if pat is _SINGLE_CLOSING else (1, 2)
            amount = _num(m.group(amt_g)) + (int(m.group(cents_g)) / 100 if m.group(cents_g) else 0)
            if 100 <= amount <= 5_000_000:
                return amount, " ".join(sent.split())[:100]
    return None



def _closing_costs_percent(text: str, price: float | None) -> tuple[float | None, str] | None:
    """Cycle 20: "title and closing costs approx. 2.5% of price" is worked out from the price (with a note). With no price only a note is
    given. What the seller gives ("Seller pays 3% toward closing") and a percent of the loan or down payment are never read here."""
    for m in re.finditer(r"\b(?:closing|settlement)(?:[ \t]+(?:costs?|charges?|fees?)\b|(?=[ \t]*[:=]))(?:[^.\n$%;]|\b(?:approx|est)\.){0,30}?(\d{1,2}(?:\.\d+)?)[ \t]*%([^.\n;]{0,40})", text, re.I):
        clause_start = max(text.rfind(".", 0, m.start()), text.rfind("\n", 0, m.start()), text.rfind(";", 0, m.start())) + 1
        before = text[clause_start:m.start()]
        if re.search(r"\b(?:seller|owner)(?:'s)?\b|\bconcession|\bcredit", before + " " + m.group(0)[:m.start(1) - m.start()], re.I):
            continue
        tail = m.group(2)
        if re.match(r"[ \t]*(?:of|on)[ \t]+(?:the[ \t]+)?(?:buyer'?s?[ \t]+)?(?:loan|mortgage|down|financed|financing|rent)\b", tail, re.I):
            continue
        if not re.match(r"[ \t]*(?:of|on)[ \t]+(?:the[ \t]+)?(?:purchase[ \t]+|sale[ \t]+|sales[ \t]+|list[ \t]+|listing[ \t]+|asking[ \t]+|home[ \t]+)?price\b|[ \t]*(?:\)|,|$)", tail, re.I):
            continue
        pct = float(m.group(1))
        if not 0 < pct <= 10:
            continue
        said = re.sub(r"\s+", " ", text[clause_start:m.end()].strip())
        if isinstance(price, (int, float)) and price > 0:
            dollars = round(float(price) * pct / 100, 2)
            return dollars, (f"The listing says the closing costs are about {pct:g}% of the price. At a price of ${float(price):,.0f} that is ${dollars:,.0f} "
                             f"({pct:g}% x ${float(price):,.0f}), saved as the closing costs. The percent comes from the listing, not from a guess, but it is still an estimate, so ask for a real figure.")
        return None, f'The listing says the closing costs are about {pct:g}% of the price ("{said}"), but there is no price to work it out from, so the closing costs are left empty.'
    return None


_OFFER_AFTER = re.compile(r"[ \t]*(?:\(|,|-)?[ \t]*(?:is[ \t]+|are[ \t]+)?(?:available|negotiable|possible|on[ \t]+request|upon[ \t]+request|if[ \t]+requested)\b", re.I)


def _credit_words(text: str) -> str:
    """Cycle 23: "$6k" is $6,000 and "Sellers are" is "Seller is", so every seller credit pattern sees one form."""
    text = re.sub(r"(?<![\w])[$＄]\s?(\d{1,3}(?:\.\d+)?)[ \t]?k\b", lambda m: f"${round(float(m.group(1)) * 1000):,}", text, flags=re.I)
    text = re.sub(r"\b(sellers?)(?:[ \t]+are\b)", lambda m: m.group(1).rstrip("sS") + " is" if m.group(1).lower() == "sellers" else m.group(0), text, flags=re.I)
    return re.sub(r"\b[Ss]ellers\b(?!')", lambda m: m.group(0)[:-1], text)


def _seller_credit(text: str, offers: list[str] | None = None) -> float | None:
    """What the seller gives the buyer toward closing: "Seller will contribute up to $5,000 toward closing costs", "seller
    concessions of $8,000", "$3,000 seller credit". None when the text gives no amount. An "available" amount goes to ``offers``."""
    text = _credit_words(text)
    amt = r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?!\d)"
    pats = (r"\b(?:seller|owner)(?:'s)?[ \t]+(?:will[ \t]+|to[ \t]+|is[ \t]+(?:willing[ \t]+)?to[ \t]+)?(?:contribut\w*|credit|concessions?|assist\w*|offer\w*|give[sn]?)\b[^$\n.]{0,40}?" + amt,
            r"\bseller(?:'s)?[ \t]+(?:will[ \t]+|to[ \t]+)?(?:pay|pays|cover|covers)\b[^$\n.]{0,30}?" + amt + r"[^\n.]{0,30}\bclosing",
            r"\bseller[ \t]+(?:concessions?|credits?|contributions?)\b[^$\n.]{0,20}?" + amt,
            amt + r"[ \t]+(?:in[ \t]+|of[ \t]+)?seller[ \t]+(?:concessions?|credits?|contributions?|paid closing)",
            r"\bclosing[ \t]+costs?\b[^$\n.]{0,30}?\b(?:paid|covered|contributed)[ \t]+by[ \t]+(?:the[ \t]+)?seller\b[^$\n.]{0,25}?" + amt,
            r"\bseller[ \t]+(?:paid|covered)[ \t]+closing[ \t]+costs?\b[^$\n.]{0,25}?" + amt,
            # "Seller is offering a concession of $4,000", "Closing cost credit of $6,000 from seller with accepted offer"
            r"\bseller(?:'s)?[ \t]+(?:is[ \t]+|will[ \t]+be[ \t]+)?(?:offering|giving|providing|contributing|paying|covering)\b[^$\n.]{0,40}?" + amt,
            r"\bclosing[ \t]+costs?[ \t]+(?:credits?|concessions?|contributions?|assistance)\b[^$\n.]{0,30}?" + amt + r"(?=[^\n.]{0,40}\bseller\b)",
            # "Closing cost help from seller: $3,000", "Closing cost assistance from the seller $3,000"
            r"\bclosing[ \t]+costs?[ \t]+(?:help|assistance|credits?|concessions?|contributions?|money|support)[ \t]+(?:from|by|paid by)[ \t]+(?:the[ \t]+)?seller\b[ \t:\-=]{0,4}(?:of[ \t]+|about[ \t]+)?" + amt,
            # "Seller closing help: $4,500", "Seller help with closing $4,500", "Seller-paid closing costs: $3,500"
            r"\bseller(?:'s)?[ \t]+(?:closing(?:[ \t]+costs?)?[ \t]+)?(?:help|assistance|aid|support|allowance)\b[ \t:\-=]{0,4}(?:of[ \t]+|about[ \t]+)?" + amt,
            r"\bseller(?:'s)?[ \t]+(?:help|assistance|aid|support)(?:[ \t]+(?:with|toward|towards|for))?[ \t]+closing(?:[ \t]+costs?)?\b[ \t:\-=]{0,4}(?:of[ \t]+|about[ \t]+)?" + amt,
            r"\bseller[- ]paid[ \t]+closing(?:[ \t]+costs?)?\b[ \t:\-=]{0,4}(?:of[ \t]+|about[ \t]+)?" + amt,
            # cycle 23: "Seller to provide a $4,000 closing credit", "$4,000 closing credit from the seller", "Closing credit of $4,000 from seller"
            r"\bseller(?:'s)?[ \t]+(?:to|will|shall)[ \t]+(?:provide|give|offer|grant|issue|extend)[ \t]+(?:an?[ \t]+|the[ \t]+)?" + amt,
            amt + r"[ \t]+(?:closing[ \t]+(?:cost[ \t]+)?)?(?:credits?|concessions?)\b(?=[^\n.]{0,60}\bseller\b)",
            r"\bclosing[ \t]+credits?\b[ \t:\-=]{0,4}(?:of[ \t]+|about[ \t]+)?" + amt + r"(?=[^\n.]{0,40}\bseller\b)",
            # cycle 26: "Seller closing contribution $5,000", "Seller closing credit: $5,000", "Closing contribution from seller: $5,000"
            r"\bseller(?:'s)?[ \t]+closing(?:[ \t]+costs?)?[ \t]+(?:contributions?|credits?|concessions?)\b[ \t:\-=]{0,4}(?:of[ \t]+|about[ \t]+|approx\.?[ \t]+)?" + amt,
            r"\bclosing(?:[ \t]+costs?)?[ \t]+(?:contributions?|credits?|concessions?)[ \t]+(?:from|by|paid[ \t]+by)[ \t]+(?:the[ \t]+)?seller\b[ \t:\-=]{0,4}(?:of[ \t]+|about[ \t]+)?" + amt,
            r"\bseller(?:'s)?[ \t]+(?:will[ \t]+)?(?:pays?|covers?|contributes?|credits?|gives?)[ \t]+(?:the[ \t]+buyer[ \t]+)?(?:about[ \t]+|approx\.?[ \t]+)?" + amt
            + r"(?=[ \t]*(?:toward|towards|for|to|on|in)[ \t]+(?:the[ \t]+)?(?:buyer'?s?[ \t]+)?closing\b)")
    for pat in pats:
        for m in re.finditer(pat, text, re.I):
            if re.search(r"assessment", m.group(0), re.I):
                continue
            if _CAP_WORDS.search(m.group(0)[:m.start(1) - m.start(0)]):
                continue  # "up to $8,000" is a limit, never a sure credit
            if _OFFER_AFTER.match(text, m.end()):
                if offers is not None:
                    offers.append(" ".join(text[max(text.rfind(".", 0, m.start()), text.rfind("\n", 0, m.start())) + 1:m.end() + 20].split())[:120])
                continue  # "Seller contribution of $9,000 available" is an offer, not a promised credit
            value = _num(m.group(1))
            if 100 <= value <= 5_000_000:
                return value
    # cycle 26: "Seller pays $6,000." with nothing after the amount, in a listing that talks about the buyer's closing costs
    if re.search(r"\bclosing\b", text, re.I):
        for m in re.finditer(r"\bseller(?:'s)?[ \t]+(?:will[ \t]+)?(?:pays?|contributes?|credits?|gives?)[ \t:\-=]{0,3}(?:about[ \t]+|approx\.?[ \t]+)?" + amt + r"(?!\.?\d)[ \t]*(?:[.;,\n]|$)", text, re.I):
            if _CAP_WORDS.search(text[max(0, m.start() - 25):m.start()]):
                continue
            value = _num(m.group(1))
            if 100 <= value <= 5_000_000:
                return value
    return None


def _seller_credit_percent(text: str) -> tuple[float | None, bool]:
    """(percent of the price the seller gives toward closing, "up to" flag) from "Seller concessions up to 3% toward closing costs"."""
    pats = (r"\b(?:seller|owner)(?:'s)?[ \t]+(?:is[ \t]+|will[ \t]+(?:be[ \t]+)?|to[ \t]+)?(?:contribut\w*|credits?|concessions?|assist\w*|offer\w*|give[sn]?|giving|providing|pays?|paying|paid|cover\w*)\b[^$\n.%]{0,40}?(\d{1,2}(?:\.\d+)?)[ \t]*%",
            r"(\d{1,2}(?:\.\d+)?)[ \t]*%[ \t]*(?:in[ \t]+|of[ \t]+)?seller[ \t]+(?:concessions?|credits?|contributions?|paid)")
    for pat in pats:
        m = re.search(pat, text, re.I)
        if m and 0 < float(m.group(1)) <= 20:
            return float(m.group(1)), bool(re.search(r"\bup[ \t]+to\b|\bmax", m.group(0), re.I) or _OFFER_AFTER.match(text, m.end())
                                           or re.search(r"\b(?:available|negotiable|possible)\b[ \t:]*$", text[max(0, m.start() - 20):m.start(1)], re.I))
    return None, False


_EITHER_AMT = r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?(?!\d)"
_EITHER_PCT = r"(\d{1,2}(?:\.\d+)?)[ \t]*%"
_EITHER_WORD = r"(?:whichever|whatever)[ \t]+(?:is|one[ \t]+is)?[ \t]*(?:the[ \t]+)?(greater|higher|more|larger|bigger|lesser|lower|less|smaller)"


def _seller_credit_either(text: str, price: float | None) -> tuple[float | None, list[str]] | None:
    """Cycle 25: "Seller closing contribution: $2,000 or 1%, whichever is greater". A dollar figure and a percent of the price joined by "or" with
    "whichever is greater" (or less, or "the greater of ... and ..."): the choice is worked out against the price. Returns (credit, notes) or None.
    With no price the credit stays empty and a note quotes the line."""
    for sent in re.split(r"[.\n;](?!\d)", text):
        if not re.search(r"\b(?:seller|owner)\b", sent, re.I) or not re.search(r"closing|credit|concession|contribut|assist|help", sent, re.I):
            continue
        if re.search(r"\bassessment", sent, re.I) or re.search(r"\bup[ \t]+to\b|\bmax", sent, re.I):
            continue
        am = re.search(_EITHER_AMT, sent)
        pm = re.search(_EITHER_PCT, sent)
        if not am or not pm or len(re.findall(r"\$\s?\d", sent)) != 1 or len(re.findall(r"\d[ \t]*%", sent)) != 1:
            continue
        w = re.search(_EITHER_WORD, sent, re.I) or re.search(r"\b(?:the[ \t]+)?(greater|higher|larger|lesser|lower|smaller)[ \t]+of\b", sent, re.I)
        if not w:
            continue
        if re.match(r"[ \t]*(?:of|on)[ \t]+(?:the[ \t]+)?(?:buyer'?s?[ \t]+)?(?:loan|mortgage|down|financed|financing)\b", sent[pm.end():], re.I):
            continue
        fixed, pct = _num(am.group(1)), float(pm.group(1))
        if not 0 < pct <= 20 or not 100 <= fixed <= 5_000_000:
            continue
        quote = " ".join(sent.split())[:120]
        greater = w.group(1).lower() in ("greater", "higher", "more", "larger", "bigger")
        if not isinstance(price, (int, float)) or price < 20000:  # no price, or a figure too small to be a sale price (a monthly amount read wrongly)
            return None, [f'The listing says the seller gives ${fixed:,.0f} or {pct:g}% of the price, "{quote}", but there is no price to work the percent out from, so no seller credit is saved. Ask what the seller will really give.']
        by_pct = round(float(price) * pct / 100, 2)
        pick = max(fixed, by_pct) if greater else min(fixed, by_pct)
        word = "greater" if greater else "lesser"
        which = "the percent" if pick == by_pct and by_pct != fixed else "the dollar amount"
        return pick, [f"The listing says the seller gives ${fixed:,.0f} or {pct:g}% of the price, whichever is {word}. {pct:g}% of ${float(price):,.0f} is ${by_pct:,.0f}, "
                      f"so the {word} is {which}, ${pick:,.0f}, saved as the seller credit. It can only pay closing costs. Ask the seller's agent to confirm."]
    return None


def _seller_credit_detail(text: str, price: float | None) -> tuple[float | None, list[str]]:
    """(the seller credit in dollars or None, plain notes). Only a dollar amount is used, as written. A percent
    is a maximum, not a promise, so the credit stays empty and the note says to ask."""
    text = _credit_words(text)
    either = _seller_credit_either(text, price)
    if either:
        return either
    offers: list[str] = []
    dollars = _seller_credit(text, offers)
    if dollars:
        return dollars, []
    if offers:
        return None, [f'The listing offers a seller contribution ("{offers[0]}"). That is an offer, not a promise, so no seller credit is saved. Ask what the seller will really give.']
    cap = _seller_cap(text)
    if cap:
        return None, [f'The listing says the seller will give up to ${cap[0]:,.0f} toward closing ("{cap[1]}"). That is a limit, not a promise, so no seller credit is saved. Ask what the seller will really give.']
    pct, up_to = _seller_credit_percent(text)
    if pct is not None and not up_to and isinstance(price, (int, float)) and price > 0:
        # cycle 19: a plain percent of the price ("Seller will contribute 2% of the price toward closing") is worked out in dollars
        pm = re.search(r"[^.\n]*\b" + re.escape(f"{pct:g}") + r"[ \t]*%[ \t]*(?:\(\s*(?:about |approx\.? |~)?\$\s?(\d{1,3}(?:,\d{3})+|\d+)\s*\))?([^.\n]{0,40})", text)
        tail = pm.group(2) if pm else ""
        if not re.match(r"[ \t]*(?:of|on)[ \t]+(?:the[ \t]+)?(?:buyer'?s?[ \t]+)?(?:closing|loan|mortgage|down|financed|financing)\b", tail, re.I):
            if pm and pm.group(1):
                dollars_pct = _num(pm.group(1))
                return dollars_pct, [f"The listing says the seller gives {pct:g}% toward closing and states it as ${dollars_pct:,.0f}, so the seller credit is saved as ${dollars_pct:,.0f}."]
            dollars_pct = round(float(price) * pct / 100, 2)
            return dollars_pct, [f"The listing says the seller gives {pct:g}% of the price toward closing. At a price of ${float(price):,.0f} that is ${dollars_pct:,.0f} ({pct:g}% x ${float(price):,.0f}), saved as the seller credit. Ask the seller's agent to confirm."]
    if pct is not None:  # a percent, and above all an "up to", is a maximum and not a promise, so no dollar amount is worked out
        words = f"{'up to ' if up_to and re.search(r'up[ \t]+to[ \t]+' + re.escape(f'{pct:g}'), text, re.I) else ''}{pct:g}%"
        pm = re.search(r"[^.\n]*\b" + re.escape(f"{pct:g}") + r"[ \t]*%[ \t]*\(\s*(?:about |approx\.? |~)?\$\s?(\d{1,3}(?:,\d{3})+|\d+)\s*\)", text)
        if pm:
            words += f" (${_num(pm.group(1)):,.0f})"
        return None, [f"The listing offers seller concessions of {words}. Ask what the seller will really give."]
    if re.search(r"\bseller(?:'s)?[ \t]+(?:will[ \t]+)?(?:pays?|paid|covers?|contribut\w*|concessions?|credits?)\b[^.\n]{0,40}\bclosing[ \t]+costs?\b|\bclosing[ \t]+costs?\b[^.\n]{0,30}\b(?:paid|covered)[ \t]+by[ \t]+(?:the[ \t]+)?seller\b", text, re.I):
        return None, ["The listing says the seller helps with closing costs but gives no amount, so the seller credit is blank. Ask how much."]
    return None, []


_LC_AMT = r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?(?![\d,])"
_LC_PATS = (
    # "Lender credit of $2,000 applied at closing", "Lender credit: $2,000", "Closing credit $2,000", "Credit at closing of $2,000"
    r"\b(lender|closing|settlement)[ \t]+(?:cost[ \t]+)?credits?\b[ \t:\-=(]{0,4}(?:of[ \t]+|about[ \t]+|approx\.?[ \t]+|worth[ \t]+)?" + _LC_AMT,
    r"\bcredits?[ \t]+(?:at|toward|towards|applied[ \t]+(?:at|to|toward))[ \t]+(?:the[ \t]+)?(?:closing|settlement|close)\b[ \t:\-=(]{0,4}(?:of[ \t]+|about[ \t]+|approx\.?[ \t]+)?" + _LC_AMT,
    # "$2,000 lender credit", "$2,000 closing credit", "$2,000 credit at closing", "$2,000 credit applied at closing"
    _LC_AMT + r"[ \t]+(?:(lender|closing|settlement)[ \t]+(?:cost[ \t]+)?credits?|credit[ \t]+(?:at|toward|towards|applied[ \t]+(?:at|to|toward))[ \t]+(?:the[ \t]+)?(?:closing|settlement|close)\b)",
    # "Lender is giving a $2,000 credit", "Lender will credit $2,000 at closing"
    r"\blender[ \t]+(?:is[ \t]+|will[ \t]+)?(?:giving|providing|offering|crediting|credit|gives|credits)\b[^$\n.]{0,25}?" + _LC_AMT)


def _lender_credits(text: str) -> list[tuple[float, str, str]]:
    """Cycle 27: credits to the buyer at closing that are not the seller's: "Lender credit of $2,000 applied at closing", "$1,500 closing credit",
    "Credit at closing: $1,000". Returns (amount, "lender" or "closing", sentence). A sentence that names the seller or owner is the seller credit reader's,
    a limit ("up to"), an offer ("may", "available", "can"), a question and a credit check or score are never read."""
    got: list[tuple[float, str, str]] = []
    for sent in re.split(r"[.\n;](?!\d)", _credit_words(text)):
        if not re.search(r"\b(?:lender|closing|settlement|close)\b", sent, re.I) or re.search(r"\bcredit[ \t]+(?:check|score|report|history)|\b(?:seller|owner|sellers)\b|\bup[ \t]+to\b|\bmax\b|\bassessment|\bmay\b|\bcould\b|\bavailable\b|\bif\b|\bnegotiab|\bpossible\b|\?\s*$", sent, re.I):
            continue
        for pat in _LC_PATS:
            m = re.search(pat, sent, re.I)
            if not m:
                continue
            amount = _num(next(g for g in m.groups() if g and g[0].isdigit()))
            kind = "lender" if re.search(r"\blender\b", m.group(0), re.I) else "closing"
            if 100 <= amount <= 5_000_000 and all(abs(amount - g[0]) > 0.005 for g in got):
                got.append((amount, kind, sent))
            break
    return got


def lender_credits(text: str) -> list[tuple[float, str]]:
    """(amount, "lender" or "closing") for each credit _lender_credits reads."""
    return [(a, k) for a, k, _s in _lender_credits(text or "")]


def _lender_credit_notes(text: str) -> list[str]:
    notes = []
    for amount, kind, _sent in _lender_credits(text):
        who = "a lender credit" if kind == "lender" else "a closing credit"
        tail = "" if kind == "lender" else " The listing does not say who gives it."
        notes.append(f"The listing says {who} of ${amount:,.0f} is applied at closing.{tail} It lowers the cash to close, so it is counted there as a credit, together with any seller credit "
                     "and never below the down payment. It is not a cost. Ask the lender or the seller's agent to confirm it.")
    return notes


def seller_paid_fees(text: str) -> list[tuple[str, float]]:
    """Cycle 27: one-time fees the listing says the seller pays ("Transfer fee $350 paid by seller", "Seller pays the $800 move-in fee"). Not a cost to the buyer."""
    got: list[tuple[str, float]] = []
    for sent in re.split(r"[.\n;]", text or ""):
        if not _PAYER_SELLER.search(sent) or _PAYER_BUYER.search(sent):
            continue
        for m in _BUYER_FEE.finditer(sent):
            label = " ".join((m.group("n1") or m.group("n2")).lower().split())
            amount = _num(m.group(1) if m.group("n1") else m.group(m.lastindex))
            if not re.fullmatch(r"(?:working[ \t]+)?capital[ \t]+contributions?", label) and 50 <= amount <= 100000 and (label, amount) not in got:
                got.append((label, amount))
    return got


def _seller_gives_toward_closing(text: str) -> bool:
    """True when the listing has the seller paying or crediting something toward the buyer's closing costs."""
    return bool(_seller_credit(text) or _seller_cap(text) or _seller_credit_percent(text)[0] is not None
                or re.search(r"\bseller(?:'s)?[ \t]+(?:will[ \t]+)?(?:pays?|paid|covers?|contribut\w*|concessions?|credits?)\b[^.\n]{0,40}\bclosing[ \t]+costs?\b", text, re.I))


def _closing_help_offer(text: str) -> list[str]:
    """Cycle 22: "Buyer's agent: closing cost help up to $8,000 available" is an offer of help, not a cost and not a promised credit.
    The note quotes the amount, so it is named and never silently dropped, and it holds nothing that reads as a missing cost part.
    What the seller gives ("Seller covers closing costs up to $6,000") has its own seller-cap note and is skipped here."""
    notes: list[str] = []
    for sent in re.split(r"[.\n;]", text):
        if re.search(r"\b(?:seller|owner)\b", sent, re.I) or not re.search(r"\bclosing\b", sent, re.I):
            continue
        m = re.search(r"\b(?:help|assistance|credits?|allowance|concessions?|contributions?|grants?|incentive)\b[^$\n]{0,40}?" + _CAP_WORDS.pattern + r"[ \t]*\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?!\d)"
                      r"|" + _CAP_WORDS.pattern + r"[ \t]*\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?!\d)[ \t]*(?:in[ \t]+|of[ \t]+|toward[s]?[ \t]+)?(?:closing\b[^\n]{0,20}?)?(?:help|assistance|credits?|allowance)", sent, re.I)
        if m:
            amount = _num(next(g for g in m.groups() if g and re.fullmatch(r"[\d,]+", g)))
            notes.append(f'The listing offers closing cost help of up to ${amount:,.0f} ("{" ".join(sent.split())[:120]}"). That is an offer, not a cost and not a promised credit, '
                         "so nothing is added for it. The details are for the buyer's agent to confirm.")
    return notes[:1]


def _buyer_only_fees(text: str, out: dict[str, Any]) -> list[str]:
    """For a buy search. Parking cost and move-in fees are rent-side money: the buy cost and the cash to close do not count
    them, so they are not filled in (the reader never says "filled in" for money that is not counted). Each becomes a plain
    note instead. Also a broker percent and a transfer fee, which have no field. Takes the two fields out of ``out``."""
    notes: list[str] = []
    cost = out.pop("parking_cost", None)
    if cost == 0:
        cost = None  # cycle 21: $0 parking is free, so there is nothing to add or ask about ("$0 not counted" is noise)
    yearly = None
    if cost:
        yearly = next((round(v * 12) for v, _o, _c, u in (_try(lambda: _parking_prices(text.lower())) or []) if u == "year" and abs(v - cost) < 0.01), None)
    if cost is not None and yearly:
        notes.append(f"The listing says parking is ${yearly:,.0f} a year (about ${cost:,.0f} a month). The cost of buying does not count parking, so it is not counted anywhere. "
                     "Ask whether it is required, and add it to your own budget if it is.")
    elif cost is not None:
        required = re.search(r"\bparking\b[^.\n]{0,60}\b(?:required|mandatory|must)\b|\b(?:required|mandatory)\b[^.\n]{0,25}\bparking\b", text, re.I) \
            and not re.search(r"\b(?:not|isn't|optional)\b[^.\n]{0,15}\b(?:required|mandatory)\b|\bparking\b[^.\n]{0,40}\boptional\b", text, re.I)
        if required:
            notes.append(f"The listing says parking is ${cost:,.0f}/month and required. The cost of buying does not count it, so it is required but not counted. Add it to your own budget.")
        else:
            notes.append(f"The listing says parking is ${cost:,.0f}/month. The cost of buying does not count parking, so it is not counted anywhere. "
                         "Ask whether it is required, and add it to your own budget if it is.")
    fee = out.pop("move_in_fees", None)
    counted_fees, unclear_fees = _try(lambda: buyer_one_time_fees(text)) or ([], [])
    for label, amount in counted_fees:
        notes.append(f"The listing says the buyer pays the ${amount:,.0f} {label} at closing. It is counted in the cash to close as a one-time fee, not in the monthly cost. "
                     "Ask the seller's agent to confirm it.")
    seller_fees = _try(lambda: seller_paid_fees(text)) or []
    for label, amount in seller_fees:
        notes.append(f"The listing says the seller pays the ${amount:,.0f} {label}. It is not a cost to you, so it is not counted in the cash to close.")
    for label, amount in unclear_fees:
        if fee is not None and abs(fee - amount) < 0.01:
            continue  # a move-in fee with no payer keeps its own note below
        notes.append(f"The listing mentions a ${amount:,.0f} {label} but does not say who pays it, so it is not counted in the cash to close. Ask who pays it.")
    if fee is not None and any(abs(a - fee) < 0.01 for _l, a in counted_fees):
        fee = None  # the move-in fee has its own note above
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
    for pat in (r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?[ \t]+(?:\w+[ \t]+)?transfer[ \t]+fee\b", r"\btransfer[ \t]+(?:fee|tax)\b[ \t:\-=]{0,4}(?:of[ \t]+)?\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?!\d)",
                r"\btransfer[ \t]+fees?[ \t]+(?:is[ \t]+|are[ \t]+)?(?:paid|due|payable|covered|owed)[ \t]+by[ \t]+(?:the[ \t]+)?(?:buyer|seller)\b[ \t:\-=,]{0,4}(?:of[ \t]+)?\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?!\d)",
                r"\b(?:buyer|seller)[ \t]+(?:pays|will[ \t]+pay|to[ \t]+pay|covers|is[ \t]+responsible[ \t]+for)[ \t]+(?:the[ \t]+)?transfer[ \t]+fees?\b[ \t:\-=,]{0,4}(?:of[ \t]+)?\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?!\d)",
                r"\btransfer[ \t]+fee\b[^.\n;$]{0,30}?\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?!\d)"):
        t = re.search(pat, text, re.I)
        if t:
            amount = _num(t.group(1))
            sent = next((x for x in re.split(r"[.\n;]", text) if t.group(0) in x), "")
            buyer_pays = bool(_PAYER_BUYER.search(sent) or re.search(r"\bbuyer'?s?\b[^.\n]{0,30}\btransfer[ \t]+fee", sent, re.I)) and not _PAYER_SELLER.search(sent)
            next_payer = "" if (_PAYER_BUYER.search(sent) or _PAYER_SELLER.search(sent)) else (_try(lambda: _assessment_payer(text, sent)) or "")  # cycle 27: "- Transfer fee $350\n- Paid in full by the seller"
            buyer_pays = buyer_pays or next_payer == "buyer"
            if buyer_pays:  # cycle 17: a transfer fee the buyer pays is a closing cost, with or without the word "closing"
                prior = out.get("closing_costs")
                if prior in (None, "") and _seller_gives_toward_closing(text):
                    notes.append(f"The listing says the buyer pays a ${amount:,.0f} transfer fee at closing. It is not saved as the closing costs, because the seller is also paying toward closing "
                                 "and the fee alone would make the cash to close look too low. The cash to close uses an estimate of the closing costs. Ask for the full closing cost estimate.")
                elif prior in (None, ""):
                    out["closing_costs"] = _tidy_number(float(amount))
                    notes.append(f"The listing says the buyer pays a ${amount:,.0f} transfer fee at closing. It is counted in the closing costs, so it is in the cash to close. "
                                 "That is the only closing cost the listing gives, so the real total is likely higher. Ask for the full closing cost estimate.")
                else:
                    notes.append(f"The listing says the buyer pays a ${amount:,.0f} transfer fee at closing. The closing costs were already read from the listing, so it is not added again. "
                                 "Ask whether the closing costs already include it.")
            elif next_payer == "seller" or (_PAYER_SELLER.search(sent) and not _PAYER_BUYER.search(sent)):  # cycle 27: the listing says the seller pays it
                notes.append(f"The listing says the seller pays the ${amount:,.0f} transfer fee. It is not a cost to you, so it is not counted in the cash to close.")
            else:
                notes.append(f"The listing mentions a ${amount:,.0f} transfer fee. It is not counted anywhere. Ask what it is for and who pays it.")
            break
    return notes


_BUYER_FEE_NAME = (r"capital[ \t]+improvements?(?:[ \t]+(?:fee|assessment|contribution|charge))?|reserve(?:s)?(?:[ \t]+fund)?(?:[ \t]+(?:contribution|fee|deposit|payment))|"
                   r"reserve[ \t]+fund|move[- ]in[ \t]+fee|initiation[ \t]+fee|working[ \t]+capital(?:[ \t]+(?:contribution|fee))?|capital[ \t]+contribution")
_BUYER_FEE = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?(?![\d,]|[ \t]*(?:/|per[ \t]+(?:mo|month|yr|year)|a[ \t]+(?:month|year)|monthly|annual))[ \t]*(?:one[- ]time[ \t]+|new[ \t]+)?(?P<n1>" + _BUYER_FEE_NAME + r")\b"
                        r"|\b(?P<n2>" + _BUYER_FEE_NAME + r")\b[ \t:\-=(]{0,4}(?:of[ \t]+|due[ \t]+|payable[ \t]+)?(?:(?:due|payable|paid)?[ \t]*at[ \t]+closing[ \t:\-=,]*)?\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?(?![\d,]|[ \t]*(?:/|per[ \t]+(?:mo|month|yr|year)|a[ \t]+(?:month|year)|monthly|annual))", re.I)


def buyer_one_time_fees(text: str) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
    """Cycle 18: one-time fees on a home for sale that the buyer pays at closing ("Buyer to pay $2,400 capital improvement fee at closing",
    "$1,800 reserve fund contribution at closing", "Buyer pays $800 move-in fee to the association"). Returns (counted, unclear): counted
    when the sentence says the buyer pays or says at closing (and not the seller), unclear when no payer is named. A fee the seller pays,
    a monthly or yearly amount and a plain "capital contribution" (read with the special assessment) are left out of counted."""
    counted: list[tuple[str, float]] = []
    unclear: list[tuple[str, float]] = []
    seen: set[tuple[str, float]] = set()
    for sent in re.split(r"[.\n;]", text):
        for m in _BUYER_FEE.finditer(sent):
            label = " ".join((m.group("n1") or m.group("n2")).lower().split())
            amount = _num(m.group(1) if m.group("n1") else m.group(m.lastindex))
            if re.fullmatch(r"(?:working[ \t]+)?capital[ \t]+contributions?", label):
                continue  # read with the special assessment (it is already in the cash to close)
            if (label, amount) in seen or not 50 <= amount <= 100000:
                continue
            seen.add((label, amount))
            if _PAYER_SELLER.search(sent) and not _PAYER_BUYER.search(sent):
                continue
            if _PAYER_BUYER.search(sent) or re.search(r"\bat[ \t]+closing\b|\bat[ \t]+settlement\b|\bdue[ \t]+at[ \t]+(?:closing|signing)\b", sent, re.I):
                counted.append((label, amount))
            else:
                unclear.append((label, amount))
    return counted, unclear


_MASTER_DUES = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?[ \t]*(/[ \t]*\w+|per[ \t]+\w+)?[ \t]*(annual(?:ly)?|yearly|monthly|quarterly)?[ \t]*(?:master|umbrella|master[- ]association|master[- ]hoa|sub[- ]?association)[ \t]+(?:association[ \t]+|hoa[ \t]+)?(?:dues|fees?)"
                          r"|\b(?:master|umbrella)[ \t]+(?:association[ \t]+|hoa[ \t]+)(?:dues|fees?)[ \t:\-=]{0,4}\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?[ \t]*(/[ \t]*\w+|per[ \t]+\w+|annual(?:ly)?|yearly|monthly|quarterly)?", re.I)


def _master_dues(text: str) -> tuple[float, str, float, str] | None:
    """Cycle 18: "HOA fee $210/month plus $600 annual master association dues". Returns (monthly amount, the phrase, the amount as written, text with the
    phrase blanked) or None when the period is not clear."""
    m = _MASTER_DUES.search(text)
    if not m:
        return None
    if m.group(1) is not None:
        value, per = _num(m.group(1)), " ".join(((m.group(2) or "") + " " + (m.group(3) or "")).lower().split())
    else:
        value, per = _num(m.group(4)), (m.group(5) or "").lower()
    if re.search(r"annual|yearly|/\s*y|per\s+y", per):
        monthly = value / 12
    elif re.search(r"quarter", per):
        monthly = value / 3
    elif re.search(r"mo", per):
        monthly = value
    else:
        return None
    phrase = " ".join(m.group(0).split())
    return round(monthly, 2), phrase, value, text[:m.start()] + " " * (m.end() - m.start()) + text[m.end():]


_LISTING_CASH_TO_CLOSE = re.compile(r"\bcash[ \t]+(?:needed[ \t]+)?to[ \t]+close(?:[ \t]+estimate)?[ \t]*(?:(?:is|of|:|=|-|about|around|approx\.?)[ \t]*)*\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?", re.I)


def listing_cash_to_close(text: str) -> float | None:
    """The cash to close figure the listing quotes itself ("Cash to close estimate: $55,000"), or None."""
    m = _LISTING_CASH_TO_CLOSE.search(text or "")
    return _num(m.group(1)) if m else None


def _free_rent_match(text: str) -> re.Match[str] | None:
    """The first free-rent wording in the text. A bare "concession" next to seller, buyer or closing words is a seller
    concession (money toward a buyer's closing costs), never a free-rent offer."""
    for m in _NET_FREE_RENT.finditer(text):
        if m.group(0).lower().startswith("concession"):
            around = text[max(0, m.start() - 60):m.end() + 60]
            if re.search(r"\b(?:sellers?|buyer|closing|offer|credit)\b", around, re.I):
                continue
        return m
    return None


def _price_cut(text: str) -> float | None:
    """The size of a price cut ("Price reduced $10,000", "reduced by $10,000"), never the new price ("reduced to $...")."""
    m = re.search(r"\b(?:price[ \t]+(?:reduced|cut|drop(?:ped)?|reduction)|reduced|price[ \t]+change)[ \t:\-]*(?:by[ \t]+)?\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?!\d)", text, re.I)
    if not m or re.search(r"\bto\s*$", text[max(0, m.start(1) - 8):m.start(1)], re.I):
        return None
    if re.match(r"(?:\.\d\d)?[ \t]*(?:->|=>|-->|\u2192|\u2794|to\b|now\b)", text[m.end():], re.I):
        return None  # cycle 20: "RENT REDUCED $2,450 -> $2,375": the $2,450 is the old price, not the size of the cut
    if re.match(r"(?:\.\d\d)?[ \t]*(?:off|from|on)\b[^.\n;)]{0,20}\b(?:deposit|fees?|application|admin)\b", text[m.end():], re.I):
        return None  # "REDUCED $1,950 off the deposit": a smaller deposit, not a lower price
    return _num(m.group(1))


def _insurance(text: str) -> float | None:
    """Home insurance as a yearly amount (the field is per year). "est $1,100/yr" -> 1100; "$90/mo" -> 1080."""
    m = re.search(r"\b(?:(?:ho-?[36](?:\s+(?:insurance|policy|coverage|premium))?|(?:condo(?:minium)?|unit[- ]owner'?s?)\s+(?:insurance|policy|coverage|premium))|(?:home(?:owner'?s?)?|hazard|property|dwelling)\s+(?:policy|coverage|premium)|(?:home(?:owner'?s?)?\s+|hazard\s+)?insurance)(?:\s+(?:est\w*\.?|estimate[d]?|quote[d]?|premium|policy|cost))*(?:[ \t]+(?:at|of|is))?[ \t:\-=]{0,6}(?:about |around |approx\.? |~)?"
                  r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?\s*(/\s*\w+|per\s+\w+|a\s+(?:year|month)|annual\w*|monthly)?", text, re.I)
    if not m:  # "$55/mo HO6 insurance", "$660 a year condo insurance"
        m = re.search(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?\s*(/\s*\w+|per\s+\w+|a\s+(?:year|month)|annual\w*|monthly)?[ \t]+(?:for[ \t]+)?(?:ho-?[36]|condo|home(?:owner'?s?)?)[ \t]+insurance\b", text, re.I)
    if not m:
        # cycle 20: "Homeowner's insurance (HO6) about $70 per month", "HO6 insurance (about $70/mo)": filler words between the name and the amount
        m = re.search(r"\b(?:ho-?[36]|(?:home(?:owner'?s?)?|hazard|condo(?:minium)?|unit[- ]owner'?s?|property)[ \t]+insurance|insurance)\b"
                      r"(?:[ \t:\-=(),~]|\b(?:ho-?[36]|about|around|approx\w*\.?|est\w*\.?|roughly|of|at|is|cost|costs|premium|policy|coverage|insurance|condo|home\w*|hazard|owner'?s?|typically|runs|for)\b)*"
                      r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?\s*(/\s*\w+|per\s+\w+|a\s+(?:year|month)|annual\w*|monthly|yearly)?", text, re.I)
    if not m:
        # cycle 22: "insurance included in your loan escrow $70 per month" (the escrow word ties the amount to the insurance)
        m = re.search(r"\binsurance\b[^.\n$]{0,50}?\bescrow\b[ \t:\-=(),]{0,4}(?:about |around |approx\.? |~)?"
                      r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?\s*(/\s*\w+|per\s+\w+|a\s+(?:year|month)|annual\w*|monthly|yearly)?", text, re.I)
    if not m:
        return None
    value, per = _num(m.group(1)), (m.group(2) or "").lower()
    if re.search(r"\b(?:optional|recommended|not required|if you want)\b", text[m.end():m.end() + 30], re.I):
        return None  # an insurance the listing calls optional is not a cost
    if re.search(r"mo", per):
        value *= 12
    return round(value, 2) if 100 <= value <= 100000 else None


def _assessment_amount(sentence: str, *, skip_monthly: bool = False) -> float | None:
    """The dollar amount written next to the assessment words ("special assessment of $4,000", "$4,000 special assessment"). A price
    or any other number in the same sentence is never taken as the assessment."""
    num = r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?!\d)(?!,\d)"
    if skip_monthly and re.search(r"\b(?:monthly|per[ \t]+month|each[ \t]+month|a[ \t]+month)[ \t]+(?:special[ \t]+)?assessments?\b", sentence, re.I):
        return None  # "Monthly special assessment of $150" is not a one-time amount
    tail = r"(?!\s*(?:/\s*mo|per month|monthly|a month|/\s*y(?:ea)?r|per year|a year|yearly|annual|each year|for\s+\d+\s+(?:years?|yrs?)))" if skip_monthly else ""
    m = re.search(r"\bassessments?(?:\s*\([^)\n$]{0,20}\))?[ \t]*(?:of|is|was|are|totaling|totals?|estimated at|approx\.?|about|around|for|at|[:=\-])?[ \t]*\(?[ \t]*(?:of |approx\.? |about |around )?" + num + tail, sentence, re.I) \
        or re.search(num + r"(?:[ \t]*(?:one[- ]time|new|pending|upcoming|current))?[ \t]*(?:(?:condo|hoa|association|building)[ \t]+)?(?:special[ \t]+)?assessments?\b", sentence, re.I)
    return _num(m.group(1)) if m else None


# Cycle 26: payer words. Buyer: buyer, purchaser, new owner. Seller: seller, current owner (a bare "owner" that is not the "new owner").
_PW_S = r"(?:sellers?|(?:current|present|existing|previous|prior|outgoing)[ \t]+owner|(?<!new[ \t])(?<!incoming[ \t])(?<!next[ \t])owner)"
_PW_B = r"(?:buyers?|purchasers?|(?:new|incoming|next)[ \t]+owner)"
_PW_THE_S, _PW_THE_B = r"(?:the[ \t]+)?" + _PW_S, r"(?:the[ \t]+)?" + _PW_B
_PAYER_SELLER = re.compile(r"\b" + _PW_S + r"\b[^.\n]{0,25}\b(?:pay(?:s|ing)?|paid|to pay|responsib\w*|cover(?:s|ing)?|credit)\b|\bpaid (?:in full )?(?:at (?:closing|close) )?by " + _PW_THE_S + r"|\b(?:seller|owner)[- ]paid|\bpayable (?:in full )?by " + _PW_THE_S
                           + r"|\bdue from " + _PW_THE_S + r"|\bresponsibility of " + _PW_THE_S + r"|\bowed by " + _PW_THE_S + r"|\b" + _PW_S + r"[ \t]+(?:will |would |shall )?owes?\b"
                           + r"|\bcharged to " + _PW_THE_S + r"|\b" + _PW_S + r"'?s?[ \t]+(?:responsibility|expense|cost)\b|\bat[ \t]+(?:closing|close|settlement)[ \t]+by[ \t]+" + _PW_THE_S, re.I)
_PAYER_BUYER = re.compile(r"\b" + _PW_B + r"\b[^.\n]{0,25}\b(?:pay(?:s|ing)?|assumes?|to pay|responsib\w*|takes?|inherits?|cover(?:s|ing)?|(?:will |would |shall )?owes?)\b|\bowed by " + _PW_THE_B + r"|\bresponsibility of " + _PW_THE_B
                          + r"|\bpaid (?:in full )?(?:at (?:closing|close) )?by " + _PW_THE_B + r"|\bassumed by " + _PW_THE_B + r"|\bbuyer[- ]paid|\bpayable (?:in full )?by " + _PW_THE_B + r"|\bdue from " + _PW_THE_B
                          + r"|\bcharged to " + _PW_THE_B + r"|\b" + _PW_B + r"'?s?[ \t]+(?:responsibility|expense|cost)\b|\bat[ \t]+(?:closing|close|settlement)[ \t]+by[ \t]+" + _PW_THE_B, re.I)


def _buyer_closing_charges(text: str):
    """A one-time charge the buyer pays at closing that is not called a "special assessment": "Condo assessment of $2,400 payable
    by buyer at closing", "$1,000 one-time capital contribution at closing". Returns (amount, kind words, sentence) or None.
    A charge per month or per year is not one-time and is left out."""
    for sent in re.split(r"[.\n;]", text):
        if re.search(r"\bspecial assessments?\b|\bno\b[^.\n]{0,15}\bassessments?\b", sent, re.I):
            continue
        if re.search(r"/\s*(?:mo|yr)|per[ \t]+(?:month|year)|monthly|yearly|annual|quarterly|each[ \t]+(?:month|year)|seller|owner", sent, re.I) and not _PAYER_BUYER.search(sent):
            continue
        contrib = re.search(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?!\d)(?:\.\d\d)?[ \t]*(?:one[- ]time[ \t]+|new[ \t]+)?((?:working[ \t]+)?capital[ \t]+contributions?)\b"
                            r"|\b((?:working[ \t]+)?capital[ \t]+contributions?)\b[ \t:\-=(]{0,4}(?:of[ \t]+)?(?:(?:due[ \t]+|payable[ \t]+|paid[ \t]+)?at[ \t]+closing[ \t:\-=,]*)?\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?!\d)", sent, re.I)
        if contrib and re.search(r"\bat closing\b|\bone[- ]time\b|\b(?:buyer|due at|paid at)\b", sent, re.I):
            amount = _num(contrib.group(1) or contrib.group(4))
            yield amount, (contrib.group(2) or contrib.group(3)).lower(), sent
        if re.search(r"\b(?:condo|hoa|association|building)[ \t]+assessments?\b", sent, re.I) and _PAYER_BUYER.search(sent) and not _PAYER_SELLER.search(sent):
            amount = _assessment_amount(sent, skip_monthly=True)
            if amount:
                yield amount, "condo assessment", sent
                continue
        if re.search(r"\bone[- ]time[ \t]+assessments?\b", sent, re.I) and _PAYER_BUYER.search(sent):
            amount = _assessment_amount(sent, skip_monthly=True)  # "Buyer to pay one-time assessment of $1,800 at closing"
            if amount:
                yield amount, "one-time assessment", sent


def _buyer_closing_charge(text: str) -> tuple[float, str, str] | None:
    """The first one-time buyer charge at closing (see _buyer_closing_charges), or None."""
    return next(iter(_buyer_closing_charges(text)), None)


def _buyer_closing_note(text: str) -> str:
    got = _buyer_closing_charge(text)
    if not got:
        return ""
    _amount, kind, _sent = got
    return (f"The {kind} is a one-time cost for the buyer at closing, so it is saved as a special assessment paid by the buyer "
            "and counted in the cash to close. Ask the seller's agent to confirm it.")


# A sentence about a special assessment, or about "seller-paid assessments" (the seller pays it: not a credit to the buyer).
_SPECIAL_SENTENCE = r"[^.\n]*\b(?:special assessments?|(?:seller|owner)[- ]paid[ \t]+(?:(?:condo|hoa|association|building)[ \t]+)?assessments?)\b[^.\n]*"


_PAYER_NEXT = re.compile(r"^[ \t\-*\u2022]*(?:(?:it|this|that|the[ \t]+assessment)[ \t]+(?:is[ \t]+|will[ \t]+be[ \t]+)?)?(?:due|payable|owed|to[ \t]+be[ \t]+paid|paid|payment[ \t]+due)[^$]{0,30}?\b(?:from|by)[ \t]+(?:the[ \t]+)?(buyer|purchaser|new[ \t]+owner|seller|current[ \t]+owner)\b"
                         r"|^[ \t\-*\u2022]*(buyer|purchaser|new[ \t]+owner|seller|current[ \t]+owner)[ \t]+(?:pays|is[ \t]+paying|will[ \t]+be[ \t]+paying|to[ \t]+pay|will[ \t]+pay|covers|is[ \t]+covering|will[ \t]+cover|is[ \t]+responsible|responsible)[ \t]+(?:for[ \t]+)?(?:it|this|that|the[ \t]+assessment)\b", re.I)


def _assessment_payer(text: str, sentence: str) -> str:
    """"seller" / "buyer" / "" for the special assessment sentence. The sentence itself decides ("Buyer to pay special assessment of $3,000 at
    closing", "due from buyer at close"); with no payer word in it, the very next line or sentence may say it on its own ("- Due from buyer at close")."""
    is_seller, is_buyer = bool(_PAYER_SELLER.search(sentence)), bool(_PAYER_BUYER.search(sentence))
    if re.search(r"\b(?:seller|buyer|purchaser)[ \t]*(?:or|and|/|&)[ \t]*(?:the[ \t]+)?(?:buyer|seller|purchaser)\b|\beither\b|\bsplit\b(?![ \t]+(?:evenly[ \t]+|equally[ \t]+)?(?:between|among|across|by)[ \t]+(?:all[ \t]+|the[ \t]+)?(?:unit[ \t]+)?owners)|\bshared?\b(?![ \t]+(?:by|among|between)[ \t]+(?:all[ \t]+|the[ \t]+)?(?:unit[ \t]+)?owners)|\bnegotiabl\w*|\bto[ \t]+be[ \t]+(?:determined|negotiated)\b|\bTBD\b", sentence, re.I):
        return ""  # cycle 26: "seller or buyer", "split", "negotiable": the payer is not settled
    if is_seller and is_buyer:
        return ""  # cycle 26: both sides named in one sentence: unknown beats a wrong payer
    if is_seller:
        return "seller"
    if is_buyer:
        return "buyer"
    at = text.find(sentence) if sentence else -1
    if at >= 0:
        rest = text[at + len(sentence):]
        nxt = re.match(r"[ \t]*[.;]?[ \t]*\n?([^.\n;]*)", rest)
        seg = nxt.group(1) if nxt else ""
        if not seg.strip():  # a blank piece: look at the next one
            nxt = re.match(r"[ \t]*[.;]?[ \t]*\n?[ \t]*[.;]?[ \t]*\n?([^.\n;]*)", rest)
            seg = nxt.group(1) if nxt else ""
        m = _PAYER_NEXT.match(seg)
        if m:
            return "buyer" if re.match(r"buyer|purchaser|new", (m.group(1) or m.group(2)).lower()) else "seller"
    return ""


_PLAIN_ASSESS_RECURRING = re.compile(r"/\s*(?:mo|month|yr|year)|\bper[ \t]+(?:month|year|quarter)|\b(?:monthly|yearly|annual\w*|quarterly|each[ \t]+(?:month|year)|a[ \t]+(?:month|year))\b|\bfor[ \t]+\d+[ \t]+(?:months?|years?|yrs?)\b", re.I)


def _plain_assessment(text: str) -> tuple[float, str, str] | None:
    """Cycle 26: an assessment due at closing that is not called "special": "Assessment due from buyer at closing: $2,200", "Assessment $2,200,
    payable by purchaser at closing", "Condo assessment of $1,500 paid by seller". One sentence with the word assessment, one dollar amount, and
    either a payer word or "at closing". Returns (amount, payer "buyer" / "seller" / "", sentence), or None. A monthly, yearly or time-limited
    assessment, "no assessment" and a sentence with two competing amounts are left to the other readers."""
    for sent in re.split(r"[.\n;](?!\d)", text):
        if not re.search(r"\bassessments?\b", sent, re.I) or re.search(r"\bspecial[ \t]+assessments?\b|\bno\b[^.\n]{0,15}\bassessments?\b|\bnone\b", sent, re.I):
            continue
        amounts = re.findall(r"\$\s?\d", sent)
        if len(amounts) != 1 or _PLAIN_ASSESS_RECURRING.search(sent) or re.search(r"\?\s*$", sent):
            continue
        payer = _assessment_payer(text, sent)
        at_closing = re.search(r"\bat[ \t]+(?:closing|close|settlement)\b|\bdue[ \t]+(?:at|on)[ \t]+(?:closing|close|settlement)\b|\bclosing[ \t]+(?:statement|table)\b", sent, re.I)
        if not payer and not at_closing and not re.search(r"\b(?:seller|buyer|purchaser)\b", sent, re.I):
            continue
        amount = _assessment_amount(sent, skip_monthly=True)
        if amount is None:
            m = re.search(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?!\d)(?!,\d)", sent)
            tail = sent[m.end():] if m else ""
            amount = _num(m.group(1)) if m and not re.match(r"\s*(?:/|per\b|a\b|each\b)", tail, re.I) else None
        if amount:
            return amount, payer, sent
    return None


def _plain_assessment_note(amount: float, payer: str) -> str:
    if payer == "buyer":
        return (f"The listing says an assessment of ${amount:,.0f} is paid by the buyer at closing, so it is saved as a one-time assessment paid by the buyer "
                "and counted in the cash to close. Ask the seller's agent to confirm it.")
    if payer == "seller":
        return f"The listing says the seller pays an assessment of ${amount:,.0f}. It is not a cost to you, so it is not counted in the cash to close."
    return (f"The listing has an assessment of ${amount:,.0f} due at closing but does not say who pays it, so it is not counted in the cash to close. "
            "Ask the seller's agent who pays it, then set Who pays on this page.")


def _special_assessment_facts(text: str, buying: bool = False) -> tuple[float | None, str, str]:
    """(one-time amount or None, payer "seller" / "buyer" / "", the matching sentence) for a special assessment.
    An amount quoted per month is left out of the amount (it is not one-time), but the sentence still comes back."""
    if re.search(r"\bno (?:known |pending |current )?special assessments?\b", text, re.I):
        return None, "", ""
    sentence = None
    for m in re.finditer(_SPECIAL_SENTENCE, text, re.I):
        sentence = m.group(0)
        if re.search(r"\$\s?\d", sentence):
            break
    if sentence is None:
        got = _buyer_closing_charge(text) if buying else None
        if got:
            return got[0], "buyer", got[2]
        plain = _plain_assessment(text) if buying else None  # cycle 26: "Assessment due from buyer at closing: $2,200" (no word "special")
        return (plain[0], plain[1], plain[2]) if plain else (None, "", "")
    amount = _assessment_amount(sentence, skip_monthly=True)
    payer = _assessment_payer(text, sentence)
    return amount, payer, sentence


def _assessment_monthly(text: str) -> tuple[float, int | None] | None:
    """("Assessment for windows: $150/month for 24 months") -> (150, 24). Months is None when the listing gives no length."""
    m = re.search(r"\bassessments?\b[^.\n$]{0,40}?\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?[ \t]*(?:/[ \t]*mo(?:nth)?\b|per[ \t]+month|a[ \t]+month|monthly|each[ \t]+month)"
                  r"(?:[^.\n]{0,15}?\b(?:for|x|over)[ \t]+(\d{1,3})[ \t]*(?:months?|mos?\b))?", text, re.I)
    if not m:  # "Monthly special assessment of $150", "$150/mo special assessment"
        m = re.search(r"\bmonthly[ \t]+special[ \t]+assessments?\b[^.\n$]{0,25}?\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?(?!\d)"
                      r"(?:[^.\n]{0,15}?\b(?:for|x|over)[ \t]+(\d{1,3})[ \t]*(?:months?|mos?\b))?"
                      r"|\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?[ \t]*(?:/[ \t]*mo(?:nth)?\b|per[ \t]+month|a[ \t]+month|monthly)[ \t]+(?:special[ \t]+)?assessments?\b"
                      r"(?:[^.\n]{0,15}?\b(?:for|x|over)[ \t]+(\d{1,3})[ \t]*(?:months?|mos?\b))?", text, re.I)
        if m:
            return _num(m.group(1) or m.group(3)), (int(m.group(2) or m.group(4)) if (m.group(2) or m.group(4)) else None)
    if not m:
        return None
    return _num(m.group(1)), int(m.group(2)) if m.group(2) else None


def _assessment_monthly_end(text: str) -> str:
    """The year a monthly assessment ends ("through 2029", "until 2029", "ends 2029"), or ""."""
    for m in re.finditer(r"[^.\n]*\bassessments?\b[^.\n]*", text, re.I):
        e = re.search(r"\b(?:through|thru|until|till|to|ending(?:[ \t]+in)?|ends?(?:[ \t]+in)?|expires?(?:[ \t]+in)?)[ \t]+(?:the[ \t]+end[ \t]+of[ \t]+)?(?:[A-Za-z]+\.?[ \t]+)?(20\d\d)\b", m.group(0), re.I)
        if e:
            return e.group(1)
    return ""


def _monthly_assessment_items(text: str) -> list[dict[str, Any]]:
    """Cycle 23: every assessment the listing gives per month, one item each, told apart by its own words. "Monthly assessment $415" and
    "Assessment: $280/month" are the regular monthly HOA ("regular"); "Special assessment: $250 a month through 2028" is a "special" one.
    Each item: kind, amount, months (or None), end (a year or ""), quote. A yearly, quarterly, one-time or seller-paid assessment is not here."""
    items: list[dict[str, Any]] = []
    prev_ok = False
    for seg in re.split(r"\.(?!\d)|[\n;]|,(?!\d{3})|\bplus\b|\+", text):
        word = re.search(r"\bassessments?\b", seg, re.I)
        ok = bool(word) or (prev_ok and re.match(r"[ \t]*(?:a[ \t]+)?special\b", seg, re.I) is not None)
        prev_ok = ok
        if not ok or re.search(r"\bno\b[^$]{0,25}\bassessments?\b|\bnone\b", seg, re.I):
            continue
        if _PAYER_SELLER.search(seg) or re.search(r"\bone[- ]time\b|\bat[ \t]+closing\b", seg, re.I):
            continue
        if re.search(r"/[ \t]*y(?:ea)?r|per[ \t]+year|a[ \t]+year|yearly|annual|quarter|each[ \t]+(?:year|quarter)", seg, re.I):
            continue
        if not re.search(r"/[ \t]*mo(?:nth)?\b|per[ \t]+month|a[ \t]+month|each[ \t]+month|\bmonthly\b|\bmo\b", seg, re.I):
            continue
        amts = list(re.finditer(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?(?!\d)", seg))
        if not amts:
            continue
        after = [a for a in amts if word and a.start() >= word.start()] or ([a for a in amts if a.end() <= (word.start() if word else 0)] if word else amts)
        a = (after or amts)[0]
        mm = re.search(r"\b(?:for|x|over)[ \t]+(\d{1,3})[ \t]*(?:months?|mos?\b)", seg, re.I)
        end = _assessment_monthly_end("assessment " + seg)
        # a time-limited or purpose-named assessment ("for windows", "for 24 months", "through 2028") is a special one, never the regular HOA
        special = bool(re.search(r"\bspecial\b|\bcapital\b|\bpending\b|\bupcoming\b|\bassessments?[ \t]+for\b", seg, re.I)) or bool(mm) or bool(end)
        items.append({"kind": "special" if special else "regular", "amount": _num(a.group(1)), "months": int(mm.group(1)) if mm else None,
                      "end": end, "quote": " ".join(seg.split())})
    return items


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
    for m in re.finditer(_SPECIAL_SENTENCE, text, re.I):
        sentence = m.group(0)
        if re.search(r"\$\s?\d", sentence):
            break
    if sentence is None:
        return ""
    am = _assessment_amount(sentence, skip_monthly=True)
    if not am and (_assessment_monthly(sentence) or _assessment_yearly(sentence)):
        return ""  # a monthly or yearly assessment gets its own note
    payer_now = _assessment_payer(text, sentence)
    who = {"seller": "the seller pays it", "buyer": "the buyer pays it"}.get(payer_now, "")
    if am and payer_now == "seller" and re.search(r"\b(?:has|have|had|was|were)[ \t]+(?:already[ \t]+)?(?:been[ \t]+)?paid\b|\balready[ \t]+(?:been[ \t]+)?paid\b|\b(?:seller|owner)[ \t]+paid\b|\bpaid[ \t]+(?:in[ \t]+20\d\d|last[ \t]+year|previously)\b", sentence, re.I) \
            and not re.search(r"\b(?:to[ \t]+be|will[ \t]+be|at[ \t]+(?:closing|close|settlement)|due|upcoming|pending)\b", sentence, re.I):
        return (f"A special assessment of ${am:,.0f} was already paid by the seller. It is not a cost to you, so it is not counted in the cash to close.")
    if am:
        return f"Special assessment ${am:,.0f}: {who or 'the listing doesn' + chr(39) + 't say who pays it, so ask'}."
    if not who:
        return "A special assessment is mentioned but no amount is given, and the listing doesn't say who pays it. Ask what it is and who pays it, then set Who pays on this page."
    return f"A special assessment is mentioned but no amount is given: {who}. Ask what it is for and how much it is."


def _days_on_market(text: str) -> int | None:
    """"41 days on Zillow", "Days on market: 41", "Time on Redfin 41 days"."""
    site = r"(?:zillow|redfin|realtor(?:\.com)?|trulia|homes\.com|the market|market|site)"
    for pat in (r"\bDOM\s*[:\-]?\s*(\d{1,4})\b", r"\b(\d{1,4})\s+days?\s+on\s+" + site, r"\bdays?\s+on\s+(?:market|" + site + r")\s*[:\-]?\s*(\d{1,4})\b",
                r"\btime\s+on\s+" + site + r"\s*[:\-]?\s*(\d{1,4})\s+days?", r"(?<![\w$])(\d{1,4})\s*DOM\b(?!\s*[:\-=]\s*\d)",
                r"\b(?:listed|on the market|on market|posted)\s+(\d{1,4})\s+days?\s+ago\b"):
        m = re.search(pat, text, re.I)
        if m:
            return int(m.group(1))
    # "Listed 2 weeks ago", "3 weeks ago" alone on a line: weeks and days ago
    for m in re.finditer(r"^[ \t*#|-]*(?:(?:listed|posted|on[ \t]+(?:the[ \t]+)?market|new[ \t]+listing)[ \t:]*)?(\d{1,3})[ \t]+(days?|weeks?)[ \t]+ago[ \t.]*$|"
                         r"\b(?:listed|posted|on[ \t]+(?:the[ \t]+)?market)[ \t:]+(\d{1,3})[ \t]+(weeks?)[ \t]+ago\b", text, re.I | re.M):
        n, unit = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        days = int(n) * (7 if unit.lower().startswith("week") else 1)
        if 0 < days <= 3650:
            return days
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
    if line.endswith(".") and not re.search(r"\b(?:Inc|Co|Jr|Sr|Ltd|Corp|LLC|[A-Z])\.$", line):
        line = line[:-1].rstrip(" ,;:-")  # "Priya Natarajan, Buckeye Realty." has no trailing period
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


_LANDLORD_PAYS_ALL = re.compile(r"\b(?:landlord|owner|management|property manager)\s+(?:pays?|covers?)\s+(?:for\s+)?all\s+(?:the\s+)?utilit(?:y|ies)\b(?![^.\n;]{0,12}\b(?:except|other than|besides|but|excluding|rubs|billed)\b)")
_PLUS_UTILITIES_WORDS = re.compile(r"(?:\+|\bplus)\s*(?:all\s+)?utilit(?:y|ies)\b|\butilit(?:y|ies)\s*(?:are\s*)?(?:not included|extra|separate|not covered|excluded)\b|\brubs\b|\bbilled[ -]back\b")


_LABEL_NOT_INCLUDED = re.compile(r"\$|\b(?:avg|average|about|around|approx\w*|roughly|estimate\w*|est|budget|typically|usually|billed|metered|bill)\b")


def _utilities(text: str) -> str:
    low = text.lower()
    if re.search(r"\b(?:no|not|excluding|plus|\+)\s*(?:all\s+)?utilities\b|\butilities\s*(?:are\s*)?(?:not included|extra|separate|not covered|excluded)|\btenant pays (?:all )?(?:the )?utilities|\bresident pays (?:all )?utilities", low) \
            and not re.search(r"\ball utilities (?:are )?(?:included|paid)", low):
        low = re.sub(r"\b(?:no|not|excluding|plus|\+)\s*(?:all\s+)?utilities\b", " ", low)
    low = _drop_not_included(low)
    lab = re.search(r"\b(?:utilities included(?:[ \t]+in(?:[ \t]+the)?[ \t]+(?:rent|lease|price))?|included utilities|included in(?:[ \t]+the)?[ \t]+(?:rent|lease)|rent includes|includes)[ \t]*[:\-][ \t]*([^\n.;]{0,60})", low)
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
    if _LANDLORD_PAYS_ALL.search(low) and not _PLUS_UTILITIES_WORDS.search(low) and not re.search(r"\b(?:tenants?|residents?|renters?|you)\s+(?:pays?|are responsible for|is responsible for|will pay|must pay)\s+(?:for\s+)?(?:all\b|the\s+utilit)", low):
        return "all"  # a plain "Landlord pays all utilities." with no "except", no RUBS and no line that says the opposite
    found: list[str] = []
    words = "|".join(re.escape(w) for w in _UTILITY_WORDS) + "|hot water|trash removal|garbage|sewage|electricity"
    for m in re.finditer(r"\b(?:rent |lease |monthly rent )?includes?\s+((?:(?:" + words + r")[ \t]*(?:,|/|&|and|\+)?[ \t]*(?:and[ \t]+)?){1,6})(?!\s*(?:fee|charge|deposit|\$))", low):
        found += re.findall(words, m.group(1))
    for m in re.finditer(r"((?:(?:" + words + r")[ \t]*(?:,|/|&|and|\+)?[ \t]*(?:and[ \t]+)?){1,6})\s*(?:(?:is|are)\s*)?(?:all\s*)?(?:included|paid|covered|provided)\b", low):
        found += re.findall(words, m.group(1))
    for m in re.finditer(r"(?<![\w/])((?:(?:" + words + r")[ \t]*(?:,|/|&|and|\+)?[ \t]*(?:and[ \t]+)?){1,6})[ \t]*:[ \t]*(?:all[ \t]+)?(?:included|provided|covered)\b(?![ \t]*(?:in|with|for|if|only|at|by|extra|but|except|\$))", low):
        found += re.findall(words, m.group(1))  # "Water/Sewer/Trash: Included"
    for m in re.finditer(r"\b(?:utilities included(?:[ \t]+in(?:[ \t]+the)?[ \t]+(?:rent|lease|price))?|included utilities|included in(?:[ \t]+the)?[ \t]+(?:rent|lease)|rent includes|includes|utilities)[ \t]*[:\-][ \t]*([^\n.;]{0,60})", low):
        if _LABEL_NOT_INCLUDED.search(m.group(1)):
            continue  # "Utilities: avg $70 for electric" is a price, not a list of what the rent covers
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
        listed_after = re.match(r"\s*utilities\s*[:(\-]\s*\(?\s*(?:" + words + r")\b(?![^)\n]*\b(?:etc|and more|e\.g|such as|for example|including)\b)", rest)  # "all utilities (electric, gas, water, trash)": the list is what is meant, not every utility
        if bare_all or (re.match(r"\s*utilities\b", rest) and not listed_after and not re.match(r"\s*utilities[^.\n]{0,20}\b(?:except|other than|besides)\b", rest)):
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
_UTIL_PAREN = re.compile(r"\b(electricity|electric|gas|water|sewer|trash|internet|heat|cable)\s*\((?![^)]*(?:\d|\$|\b(?:incl\w*|included|not|extra|paid|billed|tenant|resident|landlord|owner|plus|excluded|separate\w*|bi-?monthly|quarterly|annual\w*|yearly|monthly|optional|seasonal)\b))[^)]{1,25}\)", re.I)
# "incl. utilities", "utilities incl.", "incl. water and sewer" (not "not incl.")
_INCL_ABBREV = (re.compile(r"(?<!not )(?<!n't )\bincl(?:uding|uded|\.)?[ \t]+(?:all[ \t]+)?(?:the[ \t]+)?utilit(?:y|ies)\b(?![ \t]*(?:not|extra|separate))", re.I),
                re.compile(r"\butilit(?:y|ies)[ \t]+incl\b\.?", re.I),
                re.compile(r"(?<!not )(?<!n't )\bincl\.[ \t]+((?:water|sewer|trash|gas|electric|heat|internet|wifi|hot water)\b)", re.I))


_UTIL_INCL_AFTER = re.compile(r"(?<!not )(?<!no )(?<!n't )(?<![\w/-])((?:(?:hot water|water|sewer|trash|garbage|gas|electric|heat|internet|wi-?fi)[ \t]*(?:,|/|&|\+|and)?[ \t]*){1,5}?)[ \t]+incl\b(\.?)(?![ \t]*(?:in|with|for|\())(?![ \t]+(?:hot water|water|sewer|trash|gas|electric|heat|internet|wi-?fi)\b(?![ \t]+(?:tenant|resident|renter|pays?|extra|separate|not|is|are)\b))", re.I)


def _both_or_electric(m: re.Match[str], word: str) -> str:
    """A provider that sells electric and gas ("PG&E") means both, unless its own sentence also gives gas a figure of its own: then the provider's figure is the electric."""
    full = m.string
    a = max(full.rfind("\n", 0, m.start()), full.rfind(". ", 0, m.start()), full.rfind(";", 0, m.start()))
    b_candidates = [i for i in (full.find("\n", m.end()), full.find(". ", m.end()), full.find(";", m.end())) if i != -1]
    sent = full[a + 1:min(b_candidates) if b_candidates else len(full)]
    rest = sent.replace(m.group(0), " ")
    if re.search(r"\bgas\b[^.\n;$]{0,25}\$\s?\d|\$\s?\d[^.\n;$]{0,25}\bgas\b", rest, re.I) and not re.search(r"\belectric\w*\b", rest, re.I):
        return "electric"
    return word


# cycle 22: internet the listing calls optional ("internet optional (Comcast ~$70)", "your choice", "if you want it") or never says the
# renter has to pay ("Internet (Comcast ~$70)" in a plain list) is a choice, not a utility bill: it is never part of the utilities estimate.
_NET_WORD_RE = re.compile(r"\b(?:internet|wi-?fi|broadband)\b", re.I)
_NET_OPTIONAL_RE = re.compile(r"\b(?:optional|your choice|if you (?:want|need|choose|like|prefer)(?: it)?|if desired|at your option|up to you|not (?:required|mandatory)|(?:by|on|upon) request)\b|\bextra if\b", re.I)
_NET_AVAILABLE_RE = re.compile(r"\bavailable\b", re.I)
_NET_PAYER_RE = re.compile(r"\b(?:tenants?|residents?|renters?|you|lessees?)\b[^.\n;]{0,30}\b(?:pays?|responsible|handles?|sets? up|arranges?|will pay|must pay)\b|\b(?:required|mandatory|must|billed back|resident responsibility|tenant responsibility|responsibility of)\b|\b(?:paid|billed|covered|handled|arranged|set[ \t]+up)[ \t]+by[ \t]+(?:the[ \t]+)?(?:tenants?|residents?|renters?|you)\b|\b(?:tenants?|residents?|renters?)[- ]paid\b|\bon[ \t]+(?:the[ \t]+)?(?:tenants?|residents?|renters?|you)\b", re.I)
_NET_BRAND_RE = re.compile(r"\b(?:comcast|xfinity|spectrum|verizon|fios|cox|centurylink|frontier|google fiber|at&t|att|optimum|rcn|wow|astound|mediacom|windstream)\b", re.I)
_NET_AMOUNT_RE = re.compile(r"\$[ \t]?((?:\d{1,3}(?:,\d{3})+|\d{1,5})(?:\.\d{1,2})?)(?![\d])")


def _internet_clauses(text: str, bills: bool = False) -> list[dict[str, Any]]:
    """Every clause that gives internet a dollar figure and is a choice or never said to be the renter's bill:
    [{"start", "end", "amount", "kind": "optional" | "unstated", "quote"}]. A clause is the word and what follows it up to a comma, "and", dot,
    semicolon or line end that comes after the figure (brackets stay whole). A figure the same sentence puts on the renter ("Tenant pays ... internet ~$65",
    "internet required $55") is a bill and is left alone."""
    out: list[dict[str, Any]] = []
    for m in _NET_WORD_RE.finditer(text):
        i, depth, seen_money = m.end(), 0, False
        while i < len(text):
            c = text[i]
            if c == "(":
                depth += 1
            elif c == ")":
                depth = max(0, depth - 1)
            elif c == "\n" or (depth == 0 and (c in ";|" or (c == "." and (i + 1 >= len(text) or text[i + 1] in " \t\n") and not re.search(r"\b(?:approx|avg|est)$", text[m.end():i], re.I)))):
                break
            elif depth == 0 and c == "$":
                seen_money = True
            elif depth == 0 and c == "," and seen_money and not re.match(r"[ \t]*(?:optional|your choice|if you|not required|available)", text[i + 1:i + 25], re.I):
                break
            elif depth == 0 and seen_money and re.match(r"[ \t]+(?:and|plus|&)[ \t]+(?:" + _ROLE_WORD + r"|pets?|parking|garage|rent|deposit)", text[i:i + 24], re.I) and not re.match(r"[ \t]+and[ \t]+optional", text[i:i + 24], re.I):
                break
            i += 1
        clause = text[m.start():i]
        am = _NET_AMOUNT_RE.search(clause)
        if not am:
            continue
        before = text[max(0, m.start() - 16):m.start()]
        line_start = text.rfind("\n", 0, m.start()) + 1
        prefix = text[line_start:m.start()]
        cut = list(re.finditer(r"(?<!approx)(?<!avg)(?<!est)(?<!incl)\.[ \t]+(?=[A-Z])", prefix + text[m.start():m.start() + 1]))
        sentence = (prefix[cut[-1].end():] if cut else prefix) + text[m.start():i]  # "Resident pays: Electric ~$40; Internet (Xfinity) approx. $60": the ";" does not end the payer's list
        after_pay = re.match(r"[ \t]*,[ \t]*[^.\n;|]{0,40}", text[i:])
        if after_pay:
            sentence += after_pay.group(0)  # cycle 24: "Internet (Xfinity) $50/mo, you set up": the payer words come after the figure
        flat = " " + clause.lower()
        if _NET_OPTIONAL_RE.search(clause) or re.search(r"\boptional[ \t:]*$", before, re.I) \
                or (_NET_AVAILABLE_RE.search(clause) and not _NET_PAYER_RE.search(sentence)):  # "available" alone is weak: "available, tenant pays Comcast ~$70" is a bill
            kind = "optional"
        elif _NET_BRAND_RE.search(clause) and not _NET_PAYER_RE.search(sentence) and not re.search(r"\b(?:included|incl)\b", flat):
            kind = "unstated"
        elif re.search(r"\b(?:from|starting[ \t]+(?:at|from)|starts[ \t]+at|as[ \t]+low[ \t]+as)[ \t]*\$", clause, re.I):
            kind = "starting"  # "(Spectrum from $50)": a starting price, never the bill
        else:
            if bills and _NET_PAYER_RE.search(sentence):
                out.append({"start": m.start(), "end": i, "amount": float(am.group(1).replace(",", "")), "kind": "bill", "quote": " ".join(clause.split()).strip(" ,;"), "word_end": m.end(), "amount_at": (m.start() + am.start(1), m.start() + am.end(1))})
            continue
        if re.search(r"\b(?:required|mandatory|must)\b", clause, re.I) and not re.search(r"\bnot (?:required|mandatory)\b", clause, re.I):
            if bills:
                out.append({"start": m.start(), "end": i, "amount": float(am.group(1).replace(",", "")), "kind": "bill", "quote": " ".join(clause.split()).strip(" ,;"), "word_end": m.end(), "amount_at": (m.start() + am.start(1), m.start() + am.end(1))})
            continue  # "Internet required $55": a bill (the fee readers own it)
        start = m.start()
        if kind == "starting":
            br = re.search(r"\([^()]*\$[^()]*\)", clause)
            if br:  # only the bracket goes: "Electric & internet resident responsibility (Spectrum from $50)" still says the renter pays internet
                out.append({"start": m.start() + br.start(), "end": m.start() + br.end(), "amount": float(am.group(1).replace(",", "")), "kind": kind, "quote": " ".join(clause.split()).strip(" ,;")})
                continue
            fm = re.search(r"(?:from|starting[ \t]+(?:at|from)|starts[ \t]+at|as[ \t]+low[ \t]+as)[ \t]*\$[ \t]?\d[\d,]*(?:\.\d\d)?(?:[ \t]*(?:/[ \t]*mo(?:nth)?|per[ \t]+month|a[ \t]+month|monthly))?", clause, re.I)
            if not fm:
                continue
            out.append({"start": m.start() + fm.start(), "end": m.start() + fm.end(), "amount": float(am.group(1).replace(",", "")), "kind": kind, "quote": " ".join(clause.split()).strip(" ,;")})
            continue
        lead = re.search(r"(?:(?:,|\band\b|&|\+)[ \t]*|optional[ \t:]*)$", text[:start])
        if lead:
            start = lead.start()
        out.append({"start": start, "end": i, "amount": float(am.group(1).replace(",", "")), "kind": kind, "quote": " ".join(clause.split()).strip(" ,;")})
    return out


_NET_NOT_OWNED_AFTER = re.compile(r"^[ \t]*(?:/[ \t]*mo(?:nth)?\b|per[ \t]+month|a[ \t]+month|monthly|each[ \t]+month)?[ \t)]*[,;]?[ \t]*(?:total|combined|together|altogether|for[ \t]+both|between|each\b|per[ \t]+(?:year|quarter)|/[ \t]*(?:yr|year)|a[ \t]+year|annual)", re.I)
_NET_UTIL_NAME = re.compile(r"\b(?:electric\w*|gas|water|sewer|trash|garbage|heat\w*|utilit\w*|parking|garage|rent|pets?|deposit)\b", re.I)


def _internet_bills(text: str) -> list[dict[str, Any]]:
    """Cycle 24: internet the renter has to set up or pay, with its own monthly price, in any layout: "Internet: you set up your own with Spectrum, about
    $55/mo", "Internet: Comcast, you set up (about $55)", "Internet $70 required through provider", "Internet $65 (Xfinity, required)". Optional,
    "available" and price-only internet are the choice notes' business. A figure that sits in a list of utilities or is a total for several of them
    ("Tenant pays electric and internet, about $120 total") is not the internet's own and is left alone. [{"start", "end", "amount", "quote"}]"""
    out: list[dict[str, Any]] = []
    for h in _internet_clauses(text, bills=True):
        if h["kind"] != "bill":
            continue
        clause = text[h["start"]:h["end"]]
        a0, a1 = h["amount_at"]
        before = text[max(0, text.rfind("\n", 0, h["start"]) + 1):h["start"]]
        before_sent = re.split(r"\.[ \t]+(?=[A-Z])|[;|][ \t]+", before)[-1]
        gap = text[h["word_end"]:a0]
        if _NET_UTIL_NAME.search(gap) or re.search(r"\b(?:total|combined|together|both|each)\b", gap, re.I):
            continue  # another bill sits between the word and the figure ("Internet and electric $120")
        if re.search(r"(?:electric\w*|gas|water|sewer|trash|garbage|heat\w*)[ \t]*(?:,|&|\+|/|\band\b)[ \t]*(?:the[ \t]+)?$", before_sent, re.I):
            continue  # the last name of a list ("electric, gas and internet $120"): the figure is the list's
        if re.search(r"\b(?:fees?|charges|monthly(?:[ \t]+extras)?)[ \t]*:", before_sent, re.I):
            continue  # "Monthly fees: Pest control $5, valet trash $25, internet $60 required": a list of fees, the fee readers count each once
        if _NET_NOT_OWNED_AFTER.match(text[a1:a1 + 40]) or re.search(r"\b(?:deposit|one[- ]time|set-?up fee|install\w*|activation)\b", clause, re.I):
            continue
        if re.search(r"\b(?:included|incl\.?|free|no charge|not required|optional)\b", clause, re.I) or h["amount"] <= 0:
            continue
        line_txt = text[text.rfind("\n", 0, h["start"]) + 1:(text.find("\n", h["end"]) if text.find("\n", h["end"]) != -1 else len(text))]
        if h["amount"] in (_internet_amenity_fees(line_txt) + _money_monthly_fees(line_txt)):
            continue  # "Internet required, $60/mo": the fee readers already count it once in other monthly fees (cycle 15), it stays there
        out.append(h)
    return out


def _strip_internet_bills(text: str, bills: list[dict[str, Any]]) -> str:
    """The text with the internet clauses the utilities estimate counted taken out, so no fee reader counts them a second time."""
    for h in sorted(bills, key=lambda x: -x["start"]):
        text = text[:h["start"]] + " " + text[h["end"]:]
    return text


_PROVIDER_NOUN = (r"(?:the[ \t]+|their[ \t]+|your[ \t]+|a[ \t]+|an[ \t]+|our[ \t]+)?(?:(?:property|building|complex|community|local|city|county|approved|preferred)(?:'s|s')?[ \t]+)?"
                  r"(?:provider|providers|utility[ \t]+(?:company|companies|provider|providers)|utilities[ \t]+(?:company|provider)|company|companies)")


def _provider_unpriced(text: str) -> list[str]:
    """Cycle 24: utilities a listing sends "through provider" ("electric and internet through provider") with no price and no word that the landlord
    pays: the renter's own bills with no amount, so they are unknown, never dropped. A named provider ("through ComEd") is the older reader's job."""
    words = "|".join(re.escape(w) for w in _UTILITY_WORDS if w != "hot water") + "|electricity|wi-?fi"
    out: list[str] = []
    for clause in re.split(r"\n|;|\.(?=\s|$)", text.lower()):
        if "$" in clause or re.search(r"\b(?:landlord|owner|management)[ \t]+(?:pays?|covers?|provides?)\b|\b(?:included|incl)\b|\boptional\b|\bnot\s+(?:required|needed)\b", clause):
            continue
        for m in re.finditer(r"((?:\b(?:" + words + r")\b[ \t]*(?:,|/|&|and|\+)?[ \t]*(?:and[ \t]+)?){1,6})[ \t]*(?:\(\s*)?(?:through|via|thru|with|from|by)[ \t]+" + _PROVIDER_NOUN + r"\b", clause):
            out += [("electric" if w == "electricity" else "internet" if w.startswith("wi") else w) for w in re.findall(r"\b(?:" + words + r")\b", m.group(1))]
    return [w for w in _ordered_utilities(out).split(", ") if w and w != "cable"]


_ASKED_INCLUDED = re.compile(r"\b((?:(?:hot water|water|sewer|trash|garbage|gas|electric\w*|heat\w*|internet|wi-?fi)[ \t]*(?:,|/|&|and|\+)?[ \t]*){1,4})[ \t]*(?:incl(?:uded|\.)?|is[ \t]+included|are[ \t]+included)(?![A-Za-z])[^.?\n;()]{0,25}\?"
                             r"|\b(?:is|are)[ \t]+((?:(?:hot water|water|sewer|trash|garbage|gas|electric\w*|heat\w*|internet|wi-?fi)[ \t]*(?:,|/|&|and|\+)?[ \t]*){1,4})[ \t]*(?:incl(?:uded|\.)?)(?![A-Za-z])[^.?\n;()]{0,25}\?", re.I)


def _asked_included(text: str) -> list[tuple[str, list[str]]]:
    """Cycle 24: "gas incl. in rent?" or "Is gas included?" is a question, not a statement: [(the question, ["gas"])]."""
    out: list[tuple[str, list[str]]] = []
    for m in _ASKED_INCLUDED.finditer(text):
        names = re.findall(r"hot water|water|sewer|trash|garbage|gas|electric\w*|heat\w*|internet|wi-?fi", (m.group(1) or m.group(2)).lower())
        q = m.group(0)
        if len(names) > 1 and re.search(r"\$[ \t]?[\d.,]+[ \t]*(?:/[ \t]*mo(?:nth)?|per[ \t]+month|a[ \t]+month|monthly)?[ \t]*$", text[max(0, m.start() - 30):m.start()]):
            names = names[-1:]  # "$140/mo electric, gas incl. in rent?": the figure is the electric's, only the last name is asked about
            q = q[q.lower().rfind(names[0][:4]):]
        names = [("trash" if w == "garbage" else "electric" if w.startswith("electric") else "heat" if w.startswith("heat") else "internet" if w.startswith("wi") else "water" if w == "hot water" else w) for w in names]
        if names:
            out.append((q, list(dict.fromkeys(names))))
    return out


def _except_priced_re() -> re.Pattern[str]:
    return re.compile(r"\b(?:tenants?|residents?|renters?|you)[ \t]+(?:pays?|(?:is|are)[ \t]+responsible[ \t]+for)[ \t]+(?:for[ \t]+)?(?:all|everything)(?:[ \t]+(?:the[ \t]+)?utilit\w+)?[ \t]+"
                      r"(?:except(?:[ \t]+for)?|other[ \t]+than|besides|but(?![ \t]+not))[ \t]+(?P<names>" + _ROLE_LIST_RAW + r")[ \t]*(?P<br>\([^)\n]*\$[ \t]?\d[^)\n]*\))", re.I)


def _except_priced(text: str) -> dict[str, Any] | None:
    """Cycle 24: "tenant pays all except internet and electric (electric avg $40... actually, ask)": the line says the renter does NOT pay the left-out
    ones, then puts a price on one of them. The two readings compete, so the left-out ones stay unknown and the figure is not counted; the rest are
    the renter's bills with no amount. {"left": [...], "rest": [...], "quote": "...", "amount": 40.0} or None."""
    for clause in re.split(r"\n|;", text):
        m = _except_priced_re().search(clause)
        if not m:
            continue
        left = [w for w in _ordered_utilities(re.findall(_ROLE_WORD, m.group("names").lower())).split(", ") if w]
        am = re.search(r"\$[ \t]?(\d[\d,]*(?:\.\d\d)?)", m.group("br"))
        if not left or not am:
            continue
        if not re.search(_ROLE_WORD, m.group("br").lower()):
            continue  # cycle 27: "all utilities except trash (estimated $110/mo)": the figure names no utility, it is the estimate for the rest
        left_set = set(left)
        rest = [w for w in _ALL_UTILITIES if w not in left_set]
        return {"left": left, "rest": rest, "quote": " ".join(m.group(0).split()), "amount": float(am.group(1).replace(",", ""))}
    return None


def _util_tail(text: str, est: Any, pays: str, included: str, counted: set[str], facts_now: list[str]) -> dict[str, Any]:
    """Cycle 24: the last utility checks, decided after every utility reader has run. Returns {"est": ("keep",) | ("set", v) | ("pop",), "pays", "included",
    "facts": [...], "counted": set, "text": the listing text with the internet clauses the estimate counted taken out}."""
    pay_l = [w.strip() for w in pays.split(",") if w.strip()]
    inc_l = [] if included == "all" else [w.strip() for w in included.split(",") if w.strip()]
    all_inc = included == "all"
    notes: list[str] = []
    new_counted: set[str] = set()
    est_op: tuple = ("keep",)
    cur = float(est) if isinstance(est, (int, float)) and not isinstance(est, bool) else None
    out_text = text

    def add_pay(*names: str) -> None:
        for w in names:
            if w not in pay_l:
                pay_l.append(w)

    ep = _except_priced(text)
    if ep:
        left, rest = ep["left"], ep["rest"]
        add_pay(*rest)
        pay_l = [w for w in pay_l if w not in left]  # cycle 25: "all except internet and electric": those two are unknown, not something the renter pays
        inc_l = [w for w in (list(_ALL_UTILITIES) if all_inc else inc_l) if w not in left and w not in rest]
        all_inc = False
        if cur is not None and abs(cur - ep["amount"]) < 0.01:
            est_op, cur = ("pop",), None
        priced = [w for w in left if re.search(r"\b" + w + r"\b", ep["quote"][ep["quote"].find("("):].lower())] or left
        notes.append(f"The listing says you pay all the utilities except {_join_names(left)}, and then gives a price for {_join_names(priced)}: \"{ep['quote'][:100]}\". "
                     f"Those two lines don't agree, so {_join_names(left)} {'is' if len(left) == 1 else 'are'} left unknown and the price is not counted. "
                     f"{_join_names(rest).capitalize()} {'is' if len(rest) == 1 else 'are'} listed as something you pay, with no amount. Ask the landlord who pays {_join_names(left)} and what {'it costs' if len(rest) == 1 else 'they cost'}.")
    seen_amounts: list[float] = []
    bills = [] if ep else _internet_bills(text)
    said_net = any(re.search(r"\binternet\b[^.]*(?:counted as your utilities estimate|added to your utilities|counted in other monthly fees)|(?:counted as your utilities estimate|counted in other monthly fees)[^.]*\binternet\b", f, re.I) for f in facts_now)
    if bills and "internet" not in counted and not said_net and "internet" not in inc_l and not all_inc:
        amounts = sorted({round(b["amount"], 2) for b in bills})
        if len(amounts) == 1:
            amt = amounts[0]
            cur = round((cur or 0.0) + amt, 2)
            est_op = ("set", cur)
            add_pay("internet")
            new_counted.add("internet")
            out_text = _strip_internet_bills(text, bills)
            seen_amounts.append(amt)
            how = "the listing says it is required" if re.search(r"\b(?:required|mandatory|must)\b", bills[0]["quote"], re.I) else "the listing says you set it up and pay it"
            notes.append(f"Internet is {_money_cents(amt)} a month and {how}, counted as your utilities estimate.")
    unpriced = [w for w in _provider_unpriced(text) if w not in counted and w not in new_counted and w not in inc_l and not (all_inc and w != "internet")]
    if unpriced and not ep:
        add_pay(*unpriced)
        notes.append(f"{_join_names(unpriced).capitalize()} {'is' if len(unpriced) == 1 else 'are'} listed as something you pay, with no amount. "
                     f"The listing says {'it goes' if len(unpriced) == 1 else 'they go'} through the provider. Ask what {'it costs' if len(unpriced) == 1 else 'they cost'}.")
    for _q, names in _asked_included(text):
        gone = [w for w in names if w in inc_l]
        inc_l = [w for w in inc_l if w not in names]
        add_pay(*[w for w in names if w != "internet" or w in pay_l])
        notes.append(f"The listing asks whether {_join_names(names)} {'is' if len(names) == 1 else 'are'} included in the rent. That is a question, not an answer, so "
                     f"{_join_names(names)} {'is' if len(names) == 1 else 'are'} not counted as included. Ask the landlord.")
    return {"drop_counted": bool(ep), "est": est_op, "pays": _ordered_utilities(pay_l), "included": "all" if all_inc else _ordered_utilities(inc_l), "facts": notes, "counted": new_counted, "text": out_text}


_NO_AMOUNT_SENTENCE = re.compile(r"((?:[A-Z][a-z]+(?:, | and )?)+) (?:is|are) listed as something you pay, with no amount\. Ask what (?:it costs|they cost)\.")


def _drop_internet_unpriced(note: str) -> str:
    """"Electric and internet are listed as something you pay, with no amount. Ask what they cost." once the internet is priced and counted: the sentence
    keeps only the names that still have no amount (and goes when none is left)."""
    def one(m: re.Match[str]) -> str:
        names = [w.lower() for w in re.findall(r"[A-Z][a-z]+", m.group(1))]
        if "internet" not in names:
            return m.group(0)
        left = [w for w in names if w != "internet"]
        if not left:
            return ""
        return f"{_join_names(left).capitalize()} {'is' if len(left) == 1 else 'are'} listed as something you pay, with no amount. Ask what {'it costs' if len(left) == 1 else 'they cost'}."
    return re.sub(r"\s{2,}", " ", _NO_AMOUNT_SENTENCE.sub(one, note)).strip()


def _strip_choice_internet(text: str) -> str:
    """The text with each optional or unstated internet clause taken out, so no utility reader counts it."""
    hits = _internet_clauses(text)
    for h in sorted(hits, key=lambda x: -x["start"]):
        text = text[:h["start"]] + " " + text[h["end"]:]
    return text


def _internet_choice_notes(text: str, facts: list[str]) -> list[str]:
    """One short note for each internet figure that is not counted because it is optional or never said to be the renter's bill."""
    notes: list[str] = []
    for h in _internet_clauses(_tidy(text or "")):
        amt = f"${h['amount']:,.0f}"
        if any("nternet" in f and amt in f and re.search(r"optional|not counted|does not say|starting price", f) for f in [*facts, *notes]):
            continue
        if h["kind"] == "optional":
            notes.append(f"Internet is listed as optional at {amt} a month, so it is not counted. Ask if you need it.")
        elif h["kind"] == "starting":
            notes.append(f"The listing gives internet from {amt} a month, which is only a starting price, so it is not counted. Ask what you would really pay.")
        else:
            notes.append(f"The listing gives internet at about {amt} a month but does not say you must pay it, so it is not counted. Ask if it is required. The listing says \"{h['quote'][:80]}\".")
    return notes


_HOA_COVERS_RE = re.compile(r"[^.\n;]*\b(?:hoa|h\.o\.a|association|assoc)\b[^.\n;]{0,40}\b(?:covers?|includes?|pays?|paid)\b[^.\n;]*[.;]?"
                            r"|[^.\n;]*\b(?:covered|included|paid)[ \t]+(?:for[ \t]+)?by[ \t]+(?:the[ \t]+)?(?:hoa|h\.o\.a|association|assoc)\b[^.\n;]*[.;]?", re.I)


_HOA_COMMA_AND = re.compile(r"(\b(?:hoa|h\.o\.a|association|assoc)\b[^.\n;$]{0,40}\b(?:covers?|includes?|pays?|paid)\b[^.\n;,$]*?)[ \t]*,[ \t]*(?:and|but|plus|also)[ \t]+(?=[^.\n;]*\$)", re.I)


def _hoa_clause_split(text: str) -> str:
    """Cycle 25: "HOA covers water, and there is also a $25 water charge each month" is two statements: the HOA part ends at the comma, so the
    figure after it is read as its own sentence and can be compared with what the HOA covers."""
    return _HOA_COMMA_AND.sub(r"\1. ", text)


def _strip_hoa_covers(text: str) -> str:
    """"HOA covers trash and water" next to "Tenant pays all utilities" (a rental): what a building fee covers is not a bill the renter pays and not a
    second answer about who pays it, so the utility readers do not see it. A home for sale, or a listing with no renter-pays line, keeps it."""
    if not _HOA_COVERS_RE.search(text) or _is_sale_text(text):
        return text
    text = _hoa_clause_split(text)
    conflicts = _hoa_price_conflicts(text)
    if conflicts:
        # cycle 23: "water $25 | HOA covers water": the two lines disagree. The HOA line goes (a building fee is not a bill), and so does the
        # figure for that utility: nothing counts it, and the reader adds a note and leaves it unknown.
        rest = _HOA_COVERS_RE.sub(" ", _PIPE_SPLIT.sub(". ", text))
        for name, _amt in conflicts:
            rest = _UTIL_PRICE_SEG(name).sub(" ", rest)
        return rest
    rest = _HOA_COVERS_RE.sub(" ", text)
    named = {w for m in _HOA_COVERS_RE.finditer(text) for w in re.findall(_ROLE_WORD, m.group(0).lower())}
    pays_all = re.search(r"\b(?:tenants?|residents?|renters?|you)\b[^.\n;]{0,20}\b(?:pays?|responsible)\b[^.\n;]{0,12}\ball\b[^.\n;]{0,12}\butilit", rest, re.I)
    priced = any(re.search(r"\b" + w + r"\b[^.\n;$]{0,25}\$[ \t]?\d|\$[ \t]?\d[^.\n;]{0,25}\b" + w + r"\b", rest, re.I) for w in named)
    if not (pays_all or priced):
        return text  # "HOA covers water and trash. Tenant pays electric and gas": nothing in the renter's lines disagrees, so the HOA line stands
    return rest


_PIPE_SPLIT = re.compile(r"[ \t]+[|*\u2022\u00b7][ \t]+")


def _UTIL_PRICE_SEG(name: str) -> re.Pattern[str]:
    """"water $25 (water is $25 flat)" / "Water: $25/mo": a utility word with its own figure, so the figure can be taken out."""
    return re.compile(r"\b" + name + r"\b(?:[ \t]+(?:charges?|fees?|bills?|costs?|rates?))?[ \t]*[:\-]?[ \t]*\(?[ \t]*(?:(?:is|are|about|around|approx\w*|roughly|est\w*|avg\.?|average|~)[ \t]*)*\$[ \t]?\d[\d,]*(?:\.\d\d)?"
                      r"(?:[ \t]*(?:/[ \t]*mo(?:nth)?\b|per[ \t]+month\b|a[ \t]+month\b|monthly\b|flat\b))*[ \t]*\)?(?:[ \t]*\([^)\n]{0,30}\$[ \t]?\d[^)\n]{0,20}\))?"
                      # cycle 25: the figure first, "a $25 water charge each month", "$25/mo water fee"
                      r"|(?:\b(?:an?|the)[ \t]+)?\$[ \t]?\d[\d,]*(?:\.\d\d)?(?:[ \t]*(?:/[ \t]*mo(?:nth)?\b|per[ \t]+month\b|a[ \t]+month\b|monthly\b))?[ \t]+(?:(?:flat|extra|separate|additional)[ \t]+)?" + name
                      + r"\b(?:[ \t]+(?:charges?|fees?|bills?|costs?|rates?))?(?:[ \t]+(?:each|per|every|a)[ \t]+month\b|[ \t]*/[ \t]*mo(?:nth)?\b|[ \t]+monthly\b)?", re.I)


def _money_cents(v: float) -> str:
    """$55, $8.50, $1,425: whole dollars stay whole, cents are kept."""
    return f"${v:,.0f}" if abs(v - round(v)) < 0.005 else f"${v:,.2f}"


def _hoa_price_conflicts(text: str) -> list[tuple[str, float]]:
    """Rental text where "HOA covers water" and "water $25" both appear: [("water", 25.0)]. Two lines that disagree about the same utility."""
    if not _HOA_COVERS_RE.search(text) or _is_sale_text(text):
        return []
    text = _hoa_clause_split(text)
    text = _PIPE_SPLIT.sub(". ", text)
    rest = _HOA_COVERS_RE.sub(" ", text)
    out: list[tuple[str, float]] = []
    for m in _HOA_COVERS_RE.finditer(text):
        for w in re.findall(_ROLE_WORD, m.group(0).lower()):
            if w in dict(out) or w in ("internet", "cable", "wifi", "wi-fi"):
                continue
            pm = _UTIL_PRICE_SEG(w).search(rest)
            if pm:
                am = re.search(r"\$[ \t]?(\d[\d,]*(?:\.\d\d)?)", pm.group(0))
                out.append((w, float(am.group(1).replace(",", "")) if am else 0.0))
    return out


def _tilde_items(text: str) -> str:
    """A listing pasted as "~ Heat is gas ~ Electric typically $55 ~ Water included" uses the tilde as a bullet: each part is its own sentence.
    Only a line with two or more spaced tildes followed by a word is cut. "Electric ~ $55" and "Electric ~ about $55" are figures, not bullets."""
    bullet = r"[ \t]~[ \t]+(?=(?!(?:about|around|approx\w*|roughly|est\w*|avg|average|maybe|up[ \t]+to)\b)[A-Za-z])"
    out = []
    for line in text.split("\n"):
        n = len(re.findall(bullet, line))
        if n >= 2 or (n >= 1 and re.match(r"^[ \t]*~[ \t]+[A-Za-z]", line)):
            line = re.sub(bullet, ". ", line)
            line = re.sub(r"^[ \t]*~[ \t]+", "", line)
        out.append(line)
    return "\n".join(out)


_HEAT_GAS_STATED = re.compile(r"\bgas\b[^.\n;$]{0,30}\([ \t]*heat(?:ing)?[ \t]*\)|\bheat(?:ing)?[ \t]*\([ \t]*gas[ \t]*\)|\bgas[ \t]+heat(?:ing)?\b|\bgas\b[^.\n;]{0,30}\$[ \t]*\d[^.\n;(]{0,12}\([ \t]*heat", re.I)


def _heat_is_gas_stated(text: str) -> bool:
    """True when the listing says the heat is gas ("Heat is gas", "gas about $95 (heat)", "Heat (gas)", "gas heat")."""
    return bool(_HEAT_IS_GAS.search(text) or _HEAT_GAS_STATED.search(text))


def _heat_is_gas_words(facts: list[str], text: str) -> list[str]:
    """A utility note that names gas AND heat as two bills ("Gas, heat and electric are about $130") says it once when the listing says the heat is
    gas: "Heat (gas) and electric are about $130". Later mentions in that note say just "heat". Words inside the quoted listing text are left alone,
    and a note that names only one of the two is not touched."""
    if not _heat_is_gas_stated(text):
        return facts
    pair = re.compile(r"\b(?:([Gg])as,?[ \t]+(?:and[ \t]+)?[Hh]eat|([Hh])eat,?[ \t]+(?:and[ \t]+)?[Gg]as)\b")
    done: list[str] = []
    for f in facts:
        if not re.search(r"utilities estimate|billed back|flat fee", f):
            done.append(f)
            continue
        parts = re.split(r'("[^"]*")', f)
        if not any(pair.search(parts[i]) for i in range(0, len(parts), 2)):
            done.append(f)
            continue
        seen = False

        def one(m: re.Match[str]) -> str:
            nonlocal seen
            word = "Heat" if m.group(0)[0].isupper() else "heat"
            if not seen:
                seen = True
                return word + " (gas)"
            return word
        for i in range(0, len(parts), 2):
            seg = pair.sub(lambda m: "Heat" if (m.group(1) or m.group(2)).isupper() else "heat", parts[i])
            parts[i] = re.sub(r"\b(?:[Hh]eat|[Gg]as)\b", one, seg)
        g = "".join(parts)
        g = re.sub(r"^(Heat \(gas\)) are about\b", r"\1 is about", g)
        done.append(g)
    return done


def _util_text(text: str) -> str:
    """The listing text with provider and everyday names turned into the utility words the readers know: "PG&E" is
    electric and gas, ComEd and hydro are electric, Nicor is gas, refuse and rubbish are trash, cable is internet.
    "Valet trash" is a service fee, not a utility, so it is hidden from the utility readers."""
    for _q, _n in _asked_included(text):
        text = text.replace(_q, " ")  # cycle 24: "gas incl. in rent?" is a question, not a statement
    text = _strip_choice_internet(text)  # cycle 22: optional internet is a choice, never a utility the estimate counts
    text = _strip_hoa_covers(text)
    text = _tilde_items(text)
    text = re.sub(r"(\bgas\b[^.\n;]{0,30}\$[ \t]?\d[\d,]*(?:\.\d\d)?[^.\n;()]{0,12})\([ \t]*heat(?:ing)?[ \t]*\)", r"\1", text, flags=re.I)  # "gas about $95 (heat)": the bracket says what the gas is for, it is not a second utility
    _un = r"(?:electric\w*|gas|water|sewer|trash|garbage|internet|wi-?fi|heat\w*)"
    text = re.sub(r"(\b" + _un + r")[ \t]+[|\u2022\u00b7][ \t]+(?=" + _un + r"\b)", r"\1, ", text, flags=re.I)  # cycle 20: "Electric | Gas | Internet - about $140 combined" is one list of names, not three sentences
    text = re.sub(r"[ \t]+[|*\u2022\u00b7][ \t]+", ". ", text)  # "Heat + water included | Gas cooking, electric tenant" and "Water included * Electric not included, budget about $75 * pets": a pipe or bullet ends the sentence
    text = _ONLY_SCOPE.sub(lambda m: "/".join(_only_scope_split(m)[0]) if _only_scope_split(m) else m.group(0), text)  # cycle 25: "Water/sewer/trash (water and trash only) $60" is "water/trash $60"
    text = _flat_forms(text)  # cycle 27: "Water, sewer and trash (flat $75)", "Water and trash only $60 flat"
    text = _say_all_utilities(text)  # cycle 26: "Resident pays all except trash" is "all utilities except trash"
    text = _scope_only_brackets(text)
    text = _PAYER_AFTER.sub(lambda m: m.group(0) if re.search(r"\bgas[ \t]+(?:cooking|stove|range|oven|fireplace)[ \t]*$", m.string[max(0, m.start() - 20):m.start()] + m.group("lead").split(",")[0], re.I)
                            else f"{m.group('lead')}Tenant pays {m.group('names')}", text)  # cycle 26: "Electric and gas tenant", "Gas: resident", "Electric - renter"
    text = _UTIL_PAREN.sub(lambda m: m.group(1), text)  # "Electric (PG&E), gas" -> "Electric, gas"
    text = re.sub(r"\(\s*(?:comcast|xfinity|spectrum|verizon|fios|cox|centurylink|frontier|google fiber|at&t|att)\b[ \t,:-]*(?=[~$]|about|approx|around|roughly|est|avg|\d)", "(", text, flags=re.I)  # "internet (Comcast ~$70)": the company name is not a utility
    text = re.sub(r"(\b(?:internet|wi-?fi|broadband)[ \t]*[:\-][ \t]*)(?:comcast|xfinity|spectrum|verizon|fios|cox|centurylink|frontier|google fiber|at&t|att|optimum)\b[ \t,:-]*(?=[~$]|about|approx|around|roughly|est|avg|\d)", r"\1", text, flags=re.I)  # cycle 25: "Internet: Spectrum, approx $65": the company name between the word and its figure is not a utility
    text = re.sub(r"\belec\b(?=[ \t]*(?:[+/&,:(]|and\b|\$|~|about|avg|approx|around|\d|incl|paid|tenant|extra))", "electric", text, flags=re.I)  # "elec + gas (avg $155 total)"
    text = re.sub(r"\bpower\b(?:[ \t]+bills?)?(?=[ \t]*(?:\(?[ \t]*(?:~|about|around|approx\w*|roughly|est\w*|avg\.?|average)?[ \t]*\$|[,/&+][ \t]*(?:gas|water|sewer|trash|internet)\b|and[ \t]+(?:gas|water|sewer|trash|internet)\b|(?:is|are)[ \t]+(?:not[ \t]+)?(?:incl|paid|extra|tenant)))", "electric", text, flags=re.I)  # "you pay power ($90ish)"
    text = re.sub(r"(?<=\bpays )(?:the[ \t]+)?power\b|(?<=\bpay )(?:the[ \t]+)?power\b|(?<=\btenant pays )power\b|(?<=\bresponsible for )power\b", "electric", text, flags=re.I)
    text = re.sub(r"\b(avg|approx|est)\.(?=[ \t]*[$~\d])", r"\1", text, flags=re.I)  # "water avg. $70/mo" is not two sentences
    text = re.sub(r"[!?]+(?=[ \t]+\S)", ".", text)  # "except electric! Heat + water included" is two sentences
    # "Landlord pays everything but electric" and "Utilities included except electric" mean "all utilities ... except electric"
    text = re.sub(r"\b((?:landlord|owner|management|property manager)[ \t]+(?:pays?|covers?)[ \t]+(?:for[ \t]+)?)(?:everything|all(?:[ \t]+(?:the[ \t]+)?utilit(?:y|ies))?)[ \t]+(?:but(?![ \t]+not)|except(?:[ \t]+for)?|other than|besides)\b", r"\1all utilities except", text, flags=re.I)
    # "Landlord pays all utilities, tenant electric only total $110" / "(tenant pays electric only)": the landlord pays all but that one, and the figure is the renter's
    def _only_pays(m: re.Match[str]) -> str:
        if not (m.group("o1") or m.group("o2")):
            return m.group(0)
        names = re.sub(r"\s+", " ", m.group("names").strip())
        tail = re.sub(r"\btotal\b[ \t]*", "", m.group("tail") or "", flags=re.I).strip(" \t,;-")
        return f"all utilities included except {names}. Tenant pays {names}{(' ' + tail) if tail else ''}"
    text = re.sub(r"\b(?P<lead>(?:landlord|owner|management|property manager)[ \t]+(?:pays?|covers?)[ \t]+(?:for[ \t]+)?all[ \t]+(?:the[ \t]+)?utilit(?:y|ies))[ \t]*[,;:\-(]*[ \t]*(?:but[ \t]+)?(?:the[ \t]+)?"
                  r"(?:tenants?|residents?|renters?|you)[ \t]+(?:(?:pays?|is[ \t]+responsible[ \t]+for|are[ \t]+responsible[ \t]+for)[ \t]+)?(?P<o1>only[ \t]+)?(?P<names>" + _ROLE_LIST_RAW + r")(?P<o2>[ \t]+only\b)?\)?"
                  r"(?P<tail>[ \t]*[,;\-]?[ \t]*(?:total|about|around|approx\w*|avg\.?|average|roughly|est\w*|~)?[ \t]*\$[ \t]*\d{2,4}(?:\.\d\d)?(?![\d,]))?", _only_pays, text, flags=re.I)
    text = re.sub(r"(?<!all )(?<!the )(?<!all the )\butilit(?:y|ies)[ \t]+(?:are[ \t]+)?included[ \t]+(?:but(?![ \t]+not)|except(?:[ \t]+for)?|other than|besides)\b", "all utilities included except", text, flags=re.I)
    text = _INCL_ABBREV[0].sub("all utilities included", text)
    text = _INCL_ABBREV[1].sub("utilities included", text)
    text = _UTIL_INCL_AFTER.sub(lambda m: m.group(1) + " included" + m.group(2), text)  # "HEAT INCL.", "Water/sewer incl" -> "... included"
    text = _INCL_ABBREV[2].sub(lambda m: "includes " + m.group(1), text)
    for pat, word in _UTILITY_ALIASES:
        if word in ("electric and gas", "electric", "gas"):
            pat = r"(?<!through )(?<!via )(?<!thru )(?<!from )(?<!with )" + pat  # "Electric through Ameren" names who the bill is with, not a second utility
        if word == "electric and gas":
            text = re.sub(pat, lambda m, w=word: _both_or_electric(m, w), text, flags=re.I)  # cycle 19: "PG&E (about $80), gas about $30" names gas again with its own figure
        else:
            text = re.sub(pat, word, text, flags=re.I)
    text = _except_price_split(text)
    text = re.sub(r"\b(trash|garbage|waste)[ \t]+(?:pick-?ups?|collection|removal|disposal|services?)\b(?![ \t]+(?:fee|charge))", "trash", text, flags=re.I)  # "Trash pickup included" is the trash being included
    # "Tenant pays PG&E, water and trash included": the last comma part is the included one, so it is its own sentence
    text = _PAYS_THEN_INCLUDED.sub(r"\1. \2", text)
    text = _scope_util_figures(text)
    return text


_ONLY_NAME = r"(?:hot water|water|sewer|trash|garbage|gas|electric|heat|internet)"
_ONLY_LIST = r"(?:" + _ONLY_NAME + r"[ \t]*(?:,|/|&|\+|\band\b)?[ \t]*(?:and[ \t]+)?)"
_ONLY_SCOPE = re.compile(r"(?P<grp>\b" + _ONLY_LIST + r"{2,6}?)[ \t]*[(\[][ \t]*(?P<br>[^()\[\]\n$]{3,50}?)[ \t]*[)\]]", re.I)


def _only_scope_split(m: re.Match[str]) -> tuple[list[str], list[str]] | None:
    """"Water/sewer/trash (water and trash only) $60/mo flat": the bracket narrows the group to the names it lists. (kept, left out) or None
    when the bracket is not a narrowing ("only" or "just" must be in it and every name in it must be in the group)."""
    br = m.group("br").lower()
    if not re.search(r"\b(?:only|just)\b", br):
        return None
    kept = [w for w in re.findall(_ONLY_NAME, br)]
    grp = [w for w in re.findall(_ONLY_NAME, m.group("grp").lower())]
    if not kept or not set(kept) < set(grp) or re.search(r"\$|\d", br):
        return None
    kept = list(dict.fromkeys("trash" if w == "garbage" else w for w in kept))
    grp = list(dict.fromkeys("trash" if w == "garbage" else w for w in grp))
    return kept, [w for w in grp if w not in kept]


def _only_scope_notes(text: str) -> list[str]:
    """Cycle 25: the left-out part of "Water/sewer/trash (water and trash only) $60/mo flat" is unknown: one note says so."""
    out: list[str] = []
    for m in _ONLY_SCOPE.finditer(text):
        got = _only_scope_split(m)
        if got and got[1]:
            kept, left = got
            out.append(f"The listing says its figure covers {_join_names(kept)} only, so {_join_names(left)} {'is' if len(left) == 1 else 'are'} left unknown. "
                       f"Ask who pays {'it' if len(left) == 1 else 'them'} and what {'it costs' if len(left) == 1 else 'they cost'}.")
    return out


# cycle 25: a flat or estimated figure covers only the utilities in its own item (the words touching it, its slash group, its brackets), never the
# other utilities that sit in the same sentence. "Tenant pays gas, electric, water flat $40/mo" is a $40 for the water; "gas, electric and water
# about $40" (one list joined by "and") and "Water, sewer, trash $65/month" (a label list with no payer words) still cover the whole list.
_SCOPE_NAME = re.compile(r"\b(?:hot water|water|sewer|sewage|trash removal|trash|garbage|gas|electricity|electric|heat|internet|wi-?fi|cable)\b(?!\s+(?:stove|range|oven|fireplace|cooktop|grill|appliances?|water heater|pump|bill\b|meter))", re.I)
_SCOPE_PAYER = re.compile(r"\b(?:tenants?|residents?|renters?|lessees?|you)\b[^.\n;$]{0,14}\b(?:pays?|responsible|will pay|must pay|handles?|covers?)\b|\bpay[ \t]+for\b|\bpays?\b", re.I)
_SCOPE_TOTAL = re.compile(r"\b(?:total|combined|altogether|all[ \t-]*in|together|bundle[ds]?|package|per[ \t]+person|each[ \t]+person|between)\b|\bboth\b|\ball[ \t]+(?:the[ \t]+)?utilit", re.I)
_SCOPE_MONEY = re.compile(r"(?<![\w$])[$\uff04][ \t]?\d")
_SCOPE_FEE = re.compile(r"deposit|one[- ]time|set[- ]?up|application|activation|move[- ]in|\bpets?\b|parking|insurance|\bfee\b(?<!flat fee)", re.I)


def _scope_top_commas(clause: str) -> list[str]:
    """The clause cut at its top-level commas (not inside brackets, not inside a number like 1,200)."""
    parts, depth, prev = [], 0, 0
    for i, ch in enumerate(clause):
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        elif ch == "," and depth == 0 and not (i > 0 and clause[i - 1].isdigit() and i + 1 < len(clause) and clause[i + 1].isdigit()):
            parts.append(clause[prev:i])
            prev = i + 1
    parts.append(clause[prev:])
    return parts


def _scope_names(seg: str) -> list[str]:
    seg = re.sub(r"\([^)]*\)", " ", seg)
    return sorted({m.group(0).lower() for m in _SCOPE_NAME.finditer(seg)})


def _scope_util_figures(text: str) -> str:
    """Cut a clause between the plain list of utilities before a figure and the item the figure belongs to, so the readers see "tenant pays gas,
    electric. water flat $40/mo". Only done when the figure's own item names fewer utilities than the list before it and either a payer
    word leads the list or an earlier part is already a joined group ("electric and gas, water ... $30"). A serial list closed by "and"
    ("gas, electric and water $40") and a label list without payer words ("Water, sewer, trash $65/month") are left alone."""
    out: list[str] = []
    for part in re.split(r"(\n|;|\.(?=\s|$))", text):
        if not part or part in ("\n", ";", ".") or not _SCOPE_MONEY.search(part) or not _SCOPE_NAME.search(part) or _SCOPE_TOTAL.search(part):
            out.append(part)
            continue
        segs = _scope_top_commas(part)
        if len(segs) < 2:
            out.append(part)
            continue
        cut_before: set[int] = set()
        for i, seg in enumerate(segs):
            if not _SCOPE_MONEY.search(seg) or _SCOPE_FEE.search(seg):
                continue
            start = i
            if not _scope_names(seg) and i > 0 and _scope_names(segs[i - 1]) and not _SCOPE_MONEY.search(segs[i - 1]):
                start = i - 1  # "water is split with the other half, usually around $30": the figure's own words are the part before it
            own = ",".join(segs[start:i + 1])
            own_names = _scope_names(own)
            if not own_names or start == 0 or own_names == ["trash"]:
                continue  # a lone trash figure after a payer list ("Resident pays: Electric, Gas, Trash $18") is read as it was
            if re.fullmatch(r"\s*(?:" + _SCOPE_NAME.pattern + r")\s*\([^)]*\)\s*", own, re.I):
                continue  # "..., internet ($60)": the bracket right after one name is that name's, read by the partial rule
            back = []
            j = start - 1
            while j >= 0 and _scope_names(segs[j]) and not _SCOPE_MONEY.search(segs[j]):
                back.append(j)
                j -= 1
            if not back:
                continue
            serial = len(own_names) >= 2 and all(len(_scope_names(segs[k])) == 1 for k in back)
            if serial:
                continue
            payer = bool(_SCOPE_PAYER.search(",".join(segs[:start])))
            prev_group = any(len(_scope_names(segs[k])) >= 2 for k in back)
            if payer or prev_group:
                cut_before.add(start)
        if not cut_before:
            out.append(part)
            continue
        built = segs[0]
        for k in range(1, len(segs)):
            built += (". " if k in cut_before else ",") + segs[k].lstrip() if k in cut_before else "," + segs[k]
        out.append(built)
    return "".join(out)


def _except_price_split(text: str) -> str:
    """"All utilities included except internet and electric (electric avg $40)": the figure in the brackets (or after "which averages") is the
    price of the utility it sits next to, so it becomes its own sentence, "Tenant pays electric about $40/month", and the readers see the
    except list and the renter's price apart. A clause with no single utility the figure can belong to is left as it was."""
    def fix(clause: str) -> str:
        if not re.search(r"\b(?:all|every)[ \t]+(?:the[ \t]+)?utilit|\beverything\b|\bpays?[ \t]+all\b", clause, re.I):
            return clause
        m = re.search(r"\b(?:except(?:[ \t]+for)?|other[ \t]+than|besides)[ \t]+", clause, re.I)
        if not m:
            return clause
        tail = clause[m.end():]
        lst = _ROLE_LIST.match(tail)
        if not lst:
            return clause
        rest = tail[lst.end():]
        fm = _GEN_MONEY.search(rest)
        if not fm or len(rest[:fm.start()]) > 45 or re.search(r"quarter|annual|year|yr\b|every|bi-?monthly|deposit|fee|one[ \t-]time", rest, re.I):
            return clause
        _noise = r"(?:is|are|runs?|avg\.?|averages?|average|about|around|approx\w*|roughly|est\w*|typically|usually|typical|~)"
        if not re.fullmatch(r"[ \t,:(\-]*(?:which|that|it)?[ \t]*(?:" + _noise + r"[ \t]*)*(?:" + _ROLE_WORD + r")?[ \t]*(?:" + _noise + r"[ \t]*)*", rest[:fm.start()], re.I):
            return clause  # "all utilities except electric included, electric about $65": the words before the figure are not just its label
        raw_amt = fm.group(0)
        near = [w for w in re.findall(_ROLE_WORD, rest[:fm.start()].lower())]
        listed = [w for w in re.findall(_ROLE_WORD, lst.group(0).lower())]
        target = near[-1:] or (listed if len(listed) == 1 else [])
        if not target or (near and near[-1] not in listed):
            return clause
        return f"{clause[:m.end()]}{lst.group(0)}. Tenant pays {target[0]} about {raw_amt}/month"
    out = []
    for part in re.split(r"(\n|;|\.(?=\s|$))", text):
        out.append(fix(part) if part and part not in ("\n", ";", ".") else part)
    return "".join(out)


_INCL_EXCEPT = (re.compile(r"\ball\s+(?:the\s+)?utilities\s+(?:are\s+)?(?:included|paid|covered|provided)\b[^.\n;]{0,20}?\b(?:except(?:\s+for)?|other than|besides|but(?!\s+not))\s+([^.\n;]{0,60})", re.I),
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


_NON_UTILITY_SERVICE = re.compile(r"\b(?:lawn|landscap\w*|yard|snow|pest|cleaning|housekeeping|valet|amenit\w*|parking|garage|pets?|hoa)\b", re.I)


def _billed_back(text: str) -> tuple[str, float] | None:
    """A billed-back or flat amount for utilities, unless the same line also covers something that is not a utility ("flat $30
    per month for trash and lawn" is a service fee, counted once as a fee, so it is not also the utilities estimate)."""
    got = _billed_back_raw(text)
    if got:
        amount = re.escape(f"{got[1]:g}")
        for clause in re.split(r"\n|;|\.(?=\s|$)", text):
            if re.search(r"\$\s?" + amount + r"(?![\d,])", clause) and _NON_UTILITY_SERVICE.search(clause):
                return None
    return got


def _billed_back_raw(text: str) -> tuple[str, float] | None:
    """"Water, sewer and trash billed back at $85/month" -> ("water, sewer, trash", 85). The amount is the monthly bill the
    tenant pays for those utilities. None when the text has no such line."""
    low = text.lower()
    words = "|".join(re.escape(w) for w in _UTILITY_WORDS) + "|garbage|sewage|electricity"
    m = re.search(r"((?:(?:" + words + r")[ \t]*(?:,|/|&|and|\+)?[ \t]*(?:and[ \t]+)?){1,6})\s*(?:(?:is|are)\s+)?(?:billed|charged|passed)\b[^$\n.]{0,30}?"
                  r"\$\s?(\d{1,4}(?:\.\d\d)?)\s*(?:/\s*mo(?:nth)?|per month|monthly|a month)", low)
    if not m:
        # "$25/mo billed back for trash" (the amount first)
        m2 = re.search(r"\$\s?(\d{1,4}(?:\.\d\d)?)\s*(?:/\s*mo(?:nth)?|per month|monthly|a month)\s*(?:is\s+|are\s+)?(?:billed|charged|passed)\s*(?:back|through)?\s*(?:for|on|to cover)\s+"
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
    m = re.search(r"\$\s?(\d{1,4}(?:\.\d\d)?)\s*" + monthly + r"\s*(?:for\s+)?" + lst + back, low)
    if m:
        found = re.findall(words, m.group(2))
        return (_ordered_utilities(found), float(m.group(1))) if found else None
    m = re.search(lst + r"[:\-]?\s*\$\s?(\d{1,4}(?:\.\d\d)?)\s*" + monthly + back, low)
    if m:
        found = re.findall(words, m.group(1))
        return (_ordered_utilities(found), float(m.group(2))) if found else None
    # "Gas average $90 billed back by landlord monthly": the amount has no unit, the word monthly comes after billed back
    m = re.search(lst + r"[:\-]?\s*(?:avg\.?|average|about|approx\.?|approximately|around|roughly|~)?\s*\$\s?(\d{1,4}(?:\.\d\d)?)(?![\d,])\s*(?:" + monthly + r")?" + back
                  + r"[^.\n;$]{0,30}?(?:" + monthly + r"|each month|every month)", low)
    if m:
        found = re.findall(words, m.group(1))
        return (_ordered_utilities(found), float(m.group(2))) if found else None
    return None


_NOT_UTILITY_LINE = re.compile(r"\b(?:insurance|parking|garages?|carports?|storage|lockers?|pets?|cats?|dogs?|animals?|applications?|app fee|screening|deposit|amenity|bike|valet|trash valet|hoa|association|rent)\b", re.I)


def _billed_back_unnamed(low: str) -> tuple[str, float] | None:
    """"Utilities billed back via RUBS, avg $120/mo": a monthly amount with no utility named. Returns ("", 120)."""
    monthly = r"(?:/\s*mo(?:nth)?|per month|monthly|a month)"
    if not re.search(r"\brubs\b|\bbilled[ -]back\b|\bratio utility billing\b|\butilities? (?:are )?billed\b|\bsubmetered\b", low):
        return None
    # The amount must sit in a line that talks about utilities: a garage, parking, storage, pet or application line
    # next to a "billed back" line is not the utilities bill.
    for m in re.finditer(r"\b(?:avg\.?|average|averages|about|approx\.?|approximately|around|~|roughly|typically|usually)?\s*\$\s?(\d{1,4}(?:\.\d\d)?)\s*" + monthly, low):
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
    m = re.search(lst + r"[:\-]?[ \t]*(?:(?:is|are)[ \t]+)?(?:an?[ \t]+)?(?:utilit\w*[ \t]+)?" + flat + r"[ \t:\-]*(?:of[ \t]+)?\$\s?(\d{1,4}(?:\.\d\d)?)\s*" + monthly, low)
    if m:
        found = re.findall(words, m.group(1))
        return (_ordered_utilities(found), float(m.group(2))) if found else None
    m = re.search(lst + r"[:\-]?[ \t]*\$\s?(\d{1,4}(?:\.\d\d)?)\s*" + monthly + r"[ \t,]*(?:is[ \t]+)?" + flat + r"\b", low)
    if m:  # "Water/sewer/trash $65/mo flat"
        found = re.findall(words, m.group(1))
        return (_ordered_utilities(found), float(m.group(2))) if found else None
    m = re.search(lst + r"[:\-]?[ \t]*\$\s?(\d{1,4}(?:\.\d\d)?)[ \t]*flat(?:[ -]?(?:fee|rate|charge))?[ \t]*" + monthly + r"\b", low)
    if m:  # "water $60 flat monthly"
        found = re.findall(words, m.group(1))
        return (_ordered_utilities(found), float(m.group(2))) if found else None
    m = re.search(r"\b" + flat + r"[ \t:\-]*\$\s?(\d{1,4}(?:\.\d\d)?)\s*" + monthly + r"[ \t,]*(?:\(?(?:which[ \t]+)?(?:covers?|includes?|for)\)?)[ \t:]*" + lst, low)
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
        roles_b = _utility_roles(_util_text(_tidy(text or "")))
        if not roles_b["amount"]:
            return []  # "Water is passed through" with no amount prices nothing: the cost still says the water is not counted yet
        return [w.strip() for w in _ordered_utilities(list(roles_b["billed"])).split(",") if w.strip()]
    except Exception:
        return []


_ROLE_WORD = (r"hot water|water|sewer|sewage|trash removal|trash|garbage|gas|electricity|electric|heat|internet|wi-?fi|cable")
_ROLE_ITEM = r"\b(?:" + _ROLE_WORD + r")\b(?!\s+(?:stove|range|oven|fireplace|cooktop|grill|appliances?|water heater|pump|bill\b|meter))"
_ROLE_LIST_RAW = _ROLE_ITEM + r"(?:\s*(?:,|/|&|\+|\band\b)\s*" + _ROLE_ITEM + r")*"
_PAYS_THEN_INCLUDED = re.compile(
    r"(\b(?:tenants?|residents?|renters?|you)\s+(?:pays?|are\s+responsible\s+for|is\s+responsible\s+for|responsible\s+for|will\s+pay|must\s+pay)\s+(?:for\s+)?" + _ROLE_LIST_RAW + r")"
    r"[ \t]*,[ \t]*(" + _ROLE_LIST_RAW + r"[ \t]+(?:(?:is|are)[ \t]+)?(?:all[ \t]+)?(?:included|covered|provided)\b)", re.I)
_ROLE_LIST = re.compile(_ROLE_ITEM + r"(?:\s*(?:,|/|&|\+|\band\b|\bor\b)\s*" + _ROLE_ITEM + r")*", re.I)

# cycle 26: a payer word written after the utilities ("Electric and gas tenant", "Gas, electric: resident", "Electric - renter") says who pays them.
_PAYER_AFTER = re.compile(r"(?P<lead>(?:^|[.;\n(][ \t]*|\butilities[ \t]*:[ \t]*|,[ \t]+))(?P<names>" + _ROLE_ITEM + r"(?:[ \t]*(?:,|/|&|\+|\band\b)[ \t]*" + _ROLE_ITEM + r")*)"
                          r"(?:[ \t]*[:\-\u2013\u2014][ \t]*|[ \t]+)(?:(?:paid[ \t]+)?by[ \t]+(?:the[ \t]+)?)?(?:tenants?|residents?|renters?|lessees?)\b(?![ \t]+(?:pays?|paid|is|are|responsible|must|will|can|may|should|has|have|to)\b)(?![ \t]*[:\-\u2013\u2014][ \t]*(?:\$|\d))", re.I | re.M)
_TENANT_SUFFIX = re.compile(
    r"^(?:\s*(?:[:\-]|through|via|thru|from|with)\s*[a-z][\w&'.]*(?:\s+[a-z][\w&'.]*){0,2}\s*,)?[\s,\-]*(?:(?:is|are)\s+)?(?:[:\-]\s*(?:the\s+)?(?:tenants?|residents?|renters?|you)(?:'?s?\s+(?:responsibility|expense|cost))?\b(?!\s+(?:pays?|is|are)\b[^,.;]{0,12}\b(?:included|landlord)\b)|(?:the\s+)?(?:tenants?|residents?|renters?)\s+(?:pays?|sets?\s+up|signs?\s+up|arranges?|opens?\s+(?:the|an?)\s+account)\b|(?:you|(?:the\s+)?(?:tenants?|residents?|renters?))\s+(?:will\s+)?(?:sets?|opens?)\s+(?:it\s+|them\s+)?up\b|set\s+up\s+by\s+(?:you|(?:the\s+)?(?:tenants?|residents?|renters?))\b|paid\s+(?:for\s+)?by\s+(?:the\s+)?(?:tenants?|residents?|renters?)\b|(?:tenants?|residents?|renters?)[- ]paid\b|(?:the\s+)?(?:tenants?|residents?|renters?)'?s?\s+(?:responsibility|expense)\b|"
    r"on\s+(?:you|(?:the\s+)?(?:tenants?|residents?|renters?))\b|on\s+rubs\b|"
    r"(?:also\s+)?(?:the\s+)?(?:tenants?|residents?|renters?)\.?[ \t]*(?=,|$)|"
    r"extra\b|not\s+(?:included|covered|provided)\b|(?:paid\s+|billed\s+|metered\s+)?separate(?:ly)?\b|billed\b|charged\b|passed\s+through\b|"
    r"your\s+own\b|additional\b|excluded\b|at\s+(?:the\s+)?(?:tenant|resident)'?s?\s+expense\b)", re.I)
_LANDLORD_SUFFIX = re.compile(
    r"^\s*(?:(?:is|are)\s+)?(?:paid\s+(?:for\s+)?by\s+(?:the\s+)?(?:landlord|owner|management)\b|included\b|covered\b|provided\b|paid\b|free\b)", re.I)
_TENANT_PREFIX = re.compile(
    r"(?:\b(?:tenants?|residents?|renters?|lessees?|you)\s*(?:pays?|are responsible for|is responsible for|responsible for|will pay|must pay|to pay|covers?|handles?)\b"
    r"|\b(?:tenant|resident|renter)[- ]paid\s*[:\-]|\bplus\b|\bextra\b|\bnot included\s*[:\-]?|\bexcluding\b)", re.I)
_LANDLORD_PREFIX = re.compile(
    r"(?:\b(?:landlord|owner|management|property manager|lessor)\s*(?:pays?|covers?|provides?)\b|\b(?:i|we)\s+(?:will\s+)?(?:pay|cover|provide)s?\b|\b(?:rent |lease )?includes?\b|(?<!not )(?<!n't )\bincluded\s*[:\-]|\bincluding\b)", re.I)
_EXCEPT = re.compile(r"\b(?:except|other than|besides)\b", re.I)
_BILLED_WORDS = re.compile(r"\b(?:billed|charged|passed through|rubs)\b", re.I)

_BRACKET_ONLY_FIG = re.compile(r"\([ \t]*(?P<names>" + _ROLE_LIST_RAW + r")[ \t]*(?:only|just)[ \t]*\)[ \t]*[:\-\u2013]?[ \t]*(?P<fig>(?:~|about[ \t]+|around[ \t]+|approx\w*[ \t]+)?\$[ \t]?\d[\d,]*(?:\.\d\d)?(?:[ \t]*(?:/[ \t]*mo\w*|per[ \t]+month|a[ \t]+month|monthly|flat))*)", re.I)


_PAIR_BRACKET = re.compile(r"(?P<names>" + _ROLE_ITEM + r"(?:[ \t]*(?:,|/|&|\+|\band\b)[ \t]*" + _ROLE_ITEM + r")*)[ \t]*\([ \t]*(?P<a>(?:~|about[ \t]+|around[ \t]+|approx\w*[ \t]+)?[$\uff04][ \t]?\d[\d,]*(?:\.\d\d)?)"
                           r"[ \t]*(?:,|&|/|\band\b|\bor\b|\+)[ \t]*(?P<b>(?:~|about[ \t]+|around[ \t]+|approx\w*[ \t]+)?[$\uff04][ \t]?\d[\d,]*(?:\.\d\d)?)"
                           r"(?P<tail>(?:[ \t,]*(?:typical(?:ly)?|usually|each|avg\.?|average|approx\w*|estimated|est\.?|roughly|respectively|/[ \t]*mo\w*|per[ \t]+month|a[ \t]+month|monthly))*)[ \t]*\)", re.I)


def _pair_bracket_figures(text: str) -> tuple[str, list[str]]:
    """"you pay electric and water ($40 and $35 typical)": two figures in one bracket go to the two utilities named right before it, in order
    ("electric about $40/mo, water about $35/mo"). With any other number of names the figures cannot be paired, so they are taken out of the
    text the readers see, both stay unknown, and a note quotes them."""
    notes: list[str] = []

    def one(m: re.Match[str]) -> str:
        names = list(dict.fromkeys("trash" if w == "garbage" else "internet" if w in ("wifi", "wi-fi") else "water" if w == "hot water" else w
                                   for w in re.findall(_ROLE_WORD, m.group("names").lower())))
        a, b = m.group("a").replace("\uff04", "$"), m.group("b").replace("\uff04", "$")
        if len(names) == 2 and not re.search(r"respectively|each", m.group("tail"), re.I) or len(names) == 2:
            return f"{names[0]} about {re.sub(r'^(?:~|about |around |approx\w* )', '', a, flags=re.I)}/mo, {names[1]} about {re.sub(r'^(?:~|about |around |approx\w* )', '', b, flags=re.I)}/mo"
        quote = re.sub(r"\s+", " ", m.group(0)).strip()
        notes.append(f'The listing also says "{quote}". It is not counted anywhere. It gives two figures for {_join_names(names)} and does not say which is for which, '
                     f"so {_join_names(names)} stay unknown. Ask what each one costs.")
        return m.group("names")
    return _PAIR_BRACKET.sub(one, text), notes


def _scope_only_brackets(text: str) -> str:
    """"Tenant pays (water and trash only) $60 flat": the bracket names the utilities the figure covers, so it reads "water/trash $60 flat"."""
    def one(m: re.Match[str]) -> str:
        if re.search(_ROLE_ITEM + r"[ \t]*$", m.string[max(0, m.start() - 40):m.start()], re.I):
            return m.group(0)  # "Water/sewer/trash (water and trash only) $60": the group before the bracket is narrowed by the older step
        return "/".join(dict.fromkeys(re.findall(_ROLE_WORD, m.group("names").lower()))) + " " + m.group("fig")
    return _BRACKET_ONLY_FIG.sub(one, text)



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
                bm = re.search(r"\$\s?((?:\d{1,3}(?:,\d{3})+|\d{1,4})(?:\.\d\d)?)", tail[:80])
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
    re.compile(_ROLE_LST + r"[ \t]*[:\-]?[ \t]*(?:is[ \t]+|are[ \t]+|runs[ \t]+)?" + _APPROX_ANY + r"[ \t]*\$[ \t]*(\d{2,4}(?:\.\d\d)?)(?![\d,])" + _NOT_MONTHLY_AFTER, re.I),
    re.compile(r"\b(?:avg\.?|average|typical)[ \t]+" + _ROLE_LST + r"[ \t]*(?:is[ \t]+|are[ \t]+|of[ \t]+)?(?:" + _APPROX_ANY + r"[ \t]*)?\$[ \t]*(\d{2,4}(?:\.\d\d)?)(?![\d,])" + _NOT_MONTHLY_AFTER, re.I),
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


_EST_WORD = r"(?:est(?:imated?)?\.?|approx(?:imate(?:ly)?)?\.?|about|around|roughly|~|avg\.?|averag(?:e|es|ing)|typically|typical|usually|runs?|budget(?:ed|ing)?(?:[ \t]+(?:of|is))?)"
_EST_MONEY = r"\$[ \t]*(\d{1,4}(?:\.\d\d)?)(?![\d,])" + _NOT_MONTHLY_AFTER
_EST_PER = r"(?:[ \t]*(?:/[ \t]*mo(?:nth)?\b|per[ \t]+month|a[ \t]+month|monthly|each[ \t]+month))?"
_EST_FILL = r"(?:(?!" + _ROLE_ITEM + r")[^$.\n;]){0,30}?"
_EST_NAMED = (
    # "Water/sewer approximate $60 per month", "Water is by meter, typically around $55/month", "Electric averages $110"
    re.compile(_ROLE_LST + _EST_FILL + r"(?:" + _EST_WORD + r"[ \t]*)+" + _EST_MONEY, re.I),
    # "approximately $120/month average for heat", "$140 electric and gas average"
    re.compile(_EST_MONEY + _EST_PER + r"(?:[ \t]*(?:on[ \t]+average|average|avg\.?|combined|total))?[ \t,]*(?:for|on|of)?[ \t]*" + _ROLE_LST, re.I),
    # "Water/sewer $55/mo": a plain monthly figure written right after the utilities it is for (the unit is required)
    re.compile(_ROLE_LST + r"[ \t]*[:\-]?[ \t]*\$[ \t]*(\d{1,4}(?:\.\d\d)?)[ \t]*(?:/[ \t]*mo(?:nth)?\b|per[ \t]+month\b|a[ \t]+month\b|monthly\b)", re.I),
)
_EST_TOTAL = (
    # "roughly $150 a month total in the winter", "$180 combined"
    re.compile(r"(?:" + _EST_WORD + r"[ \t]*)*" + _EST_MONEY + _EST_PER + r"[ \t]*(?:in[ \t]+)?(?:total|combined|all[ \t-]*in)\b", re.I),
    # "Utilities estimate $120 total", "utilities run about $150"
    re.compile(r"\butilit(?:y|ies)[ \t]+(?:estimate|average|avg\.?|cost|costs|bill|bills|total)s?[ \t]*(?:is|are|of|:|-)?[ \t]*(?:" + _EST_WORD + r"[ \t]*)*" + _EST_MONEY, re.I),
    re.compile(r"\butilit(?:y|ies)\b[^$.\n;]{0,15}?(?:" + _EST_WORD + r"[ \t]*)+" + _EST_MONEY, re.I),
    # cycle 24: "Utilities: tenant pays all, estimate $220/mo" (the figure is the whole bill, the payer words sit between the label and the figure)
    re.compile(r"\butilit(?:y|ies)\b[ \t]*[:\-][ \t]*(?:tenants?|residents?|renters?|you)[ \t]+(?:pays?|are[ \t]+responsible[ \t]+for)[ \t]+(?:for[ \t]+)?(?:all|everything)(?:[ \t]+(?:the[ \t]+)?utilit\w+)?[ \t]*[,;:\-(]*[ \t]*(?:" + _EST_WORD + r"[ \t]*)+" + _EST_MONEY, re.I),
)


_TOTAL_FOR = re.compile(r"(?:" + _EST_WORD + r"[ \t]*)*" + _EST_MONEY + _EST_PER + r"[ \t]*(?:in[ \t]+)?(?:total|combined|altogether|all[ \t-]*in)\b[ \t]*(?:for|on|of)?[ \t]*(?P<rest>[^$.\n;]{0,40})", re.I)
_FOR_BOTH = re.compile(_EST_MONEY + _EST_PER + r"[ \t]*(?:for|on|of)[ \t]+(?:both|the[ \t]+two|the[ \t]+pair)\b", re.I)
_HEAT_IS_GAS = re.compile(r"\bheat(?:ing)?\b[ \t]*(?:is|are|=|:|\()[ \t]*(?:by[ \t]+)?gas\b|\bgas[ \t]+(?:is[ \t]+)?(?:the[ \t]+)?heat(?:ing)?\b", re.I)
_PLAIN_NAMED = (
    re.compile(r"(?P<names>(?:" + _ROLE_ITEM + r"[ \t]*(?:,|/|&|and|\+)?[ \t]*(?:and[ \t]+)?){1,6})[ \t]*[:\-]?[ \t]*\$[ \t]*(?P<amt>\d{1,4}(?:\.\d\d)?)(?![\d,])" + _NOT_MONTHLY_AFTER, re.I),
    re.compile(r"\$[ \t]*(?P<amt>\d{1,4}(?:\.\d\d)?)(?![\d,])" + _NOT_MONTHLY_AFTER + _EST_PER + r"[ \t]*(?:for[ \t]+)?(?P<names>(?:" + _ROLE_ITEM + r"[ \t]*(?:,|/|&|and|\+)?[ \t]*(?:and[ \t]+)?){1,6})", re.I),
)
_EXCEPT_EST = re.compile(
    r"(?:\b(?:landlord|owner|management)[ \t]+(?:pays?|covers?)[ \t]+(?:for[ \t]+)?(?:all|everything)(?:[ \t]+(?:the[ \t]+)?utilit(?:y|ies))?|\b(?:all[ \t]+)?utilit(?:y|ies)[ \t]+(?:are[ \t]+)?included)"
    r"[ \t]+(?:except(?:[ \t]+for)?|but|other[ \t]+than|besides)\b(?P<rest>[^$.\n;]*?)(?:" + _EST_WORD + r"|probably|likely|maybe)[ \t]*\$[ \t]*(?P<amt>\d{2,4}(?:\.\d\d)?)(?![\d,])" + _NOT_MONTHLY_AFTER, re.I)
_ALL_WORDS = re.compile(r"^[ \t]*(?:everything|(?:all|any)(?:[ \t]+of)?(?:[ \t]+(?:the|your|these|those))?[ \t]*(?:utilit(?:y|ies)|bills?|of[ \t]+it|of[ \t]+them)?|it[ \t]+all|the[ \t]+utilit(?:y|ies))[ \t)]*$", re.I)


def _estimate_segments(clause: str) -> list[str]:
    """Cut a clause that holds several dollar figures at the last comma between two of them, so each figure is read with its own
    words ("around $55 electric, avg $70 gas" is two figures, never "electric avg $70")."""
    cuts: list[int] = []
    amounts = [m.start() for m in re.finditer(r"\$", clause)]
    for a, b in zip(amounts, amounts[1:]):
        commas = [i for i in range(a, b) if clause[i] == ","]
        if commas:
            cuts.append(commas[-1])
        else:
            ands = [a + m.start() for m in re.finditer(r"[ \t](?:and|plus|\+)[ \t]", clause[a:b])]
            if ands:
                lead = re.match(r"\$[ \t]*[\d.,]+[ \t]*(?:/[ \t]*mo(?:nth)?|per[ \t]+month|a[ \t]+month|monthly)?[ \t]*(?:and|plus|\+)[ \t]", clause[a:b])
                cuts.append(a + lead.end() - 5 if lead else ands[-1])  # "electric $55 and gas avg $70": two figures
    out, prev = [], 0
    for c in cuts:
        out.append(clause[prev:c])
        prev = c + 1
    out.append(clause[prev:])
    return out


def _est_names(raw: str, clause: str) -> list[str]:
    names = [w for w in _ordered_utilities(re.findall(_ROLE_WORD, raw)).split(", ") if w and w != "cable"]
    if names and _HEAT_IS_GAS.search(clause) and ("gas" in names or "heat" in names):
        names = [w for w in _ordered_utilities(names + ["gas", "heat"]).split(", ") if w]  # "Heat is gas ... about $110": one bill for both
    return names


_EST_SKIP = r"\b(?:included|covered|provided|landlord pays|owner pays|billed|flat|rubs|deposit|fee|one[- ]time|set[- ]?up|quarterly|annual|annually|yearly|quarter|year|yr|qtr)\b"


def _prune_skipped(whole: str) -> str:
    """"utilities: electric ~$65/mo, gas ~$40/mo, water/sewer/trash included" -> "utilities: electric ~$65/mo, gas ~$40/mo": the comma
    parts that say included or are about a fee or pet go, the figures in the others stay. "" when a dropped part holds a dollar
    figure of its own (then the whole line is left to the fee readers) or nothing is left."""
    parts = re.split(r",(?!\d)", whole)
    if len(parts) < 2:
        return ""
    keep = []
    for part in parts:
        if re.search(_EST_SKIP, part) or _NOT_UTILITY_LINE.search(part):
            if "$" in part:
                return ""
            continue
        keep.append(part)
    return ",".join(keep) if keep and any("$" in k for k in keep) else ""


_PLAIN_ONLY = re.compile(r"^\W*(?:(?:tenants?|residents?|renters?|you)[ \t]+pays?[ \t]*[:\-]?[ \t]*|utilities[ \t]*[:\-][ \t]*|extra[ \t]*[:\-]?[ \t]*)?(?P<names>(?:" + _ROLE_ITEM + r"[ \t]*(?:,|/|&|and|\+)?[ \t]*(?:and[ \t]+)?){1,4})[ \t]*[:\-]?[ \t]*(?:total[ \t]*)?\$[ \t]*(?P<amt>\d{2,4})(?:\.\d\d)?(?![\d,])" + _EST_PER + r"[ \t]*\W*$", re.I)


def _estimate_items(text: str) -> list[dict[str, Any]]:
    """Every rough monthly figure the listing gives for utilities: {"names": [...], "amount": 60.0, "total": False}. A figure for
    named utilities ("Water/sewer approximate $60", "$140 electric and gas average") has names; a figure for the whole
    bill ("roughly $150 a month total", "Gas: roughly $150 a month total for all utilities") has total True and no names. Lines about
    included utilities, fees, parking, pets and renter's insurance are never read."""
    items: list[dict[str, Any]] = []
    prev_whole = ""
    for whole in re.split(r"\n|;|\.(?=\s|$)", text.lower()):
        before_whole, prev_whole = prev_whole, whole
        mx = _EXCEPT_EST.search(whole)
        if mx and 10 <= float(mx.group("amt")) <= 2000:
            # "Landlord pays all utilities except they said electric is on you, about $60": the figure is for what is left out
            names_x = [w for w in _est_names(mx.group("rest"), whole) if w != "trash"]
            if names_x:
                items.append({"names": names_x, "amount": float(mx.group("amt")), "total": False})
            continue
        whole = re.sub(r"\b(?:(?:is|are)[ \t]+)?(?:not|n't)[ \t]+(?:included|covered|provided)\b[ \t]*,?", " ", whole)  # "Electric not included, budget about $75": the figure is for the electric
        if re.search(_EST_SKIP, whole) or _NOT_UTILITY_LINE.search(whole):
            whole = _prune_skipped(whole)  # (a figure per quarter or year is the periodic reader's, not a monthly figure)
            if not whole:
                continue
        segs = _estimate_segments(whole)
        several = len(segs) > 1 and bool(re.search(_EST_WORD, whole))
        for clause in segs:
            m = _TOTAL_FOR.search(clause)
            if m and 10 <= float(m.group(1)) <= 2000:
                rest = m.group("rest").strip(" \t)(,")
                if rest.strip() == "":
                    # "electric and gas roughly $90 total": the utilities written right before the figure are what it covers
                    lead = clause[:m.start()]
                    bl = list(_ROLE_LIST.finditer(lead))
                    if bl and not re.sub(r"[ \t,:\-(]|\b(?:is|are|about|around|approx\.?|approximately|roughly|est\.?|estimated|avg\.?|average|runs?)\b", "", lead[bl[-1].end():]):
                        lead_names = _est_names(bl[-1].group(0), clause)
                        if lead_names and re.search(r"\ball[ \t]+(?:the[ \t]+)?utilit", whole):
                            # "Tenant responsible for all utilities (gas, electric, water, approx $320 per month combined)": the figure is for the whole bill
                            items.append({"names": [], "amount": float(m.group(1)), "total": True})
                            continue
                        if lead_names:
                            items.append({"names": lead_names, "amount": float(m.group(1)), "total": False})
                            continue
                if rest.strip() == "" or _ALL_WORDS.match(rest):
                    items.append({"names": [], "amount": float(m.group(1)), "total": True})
                    continue
                names_l = _est_names(rest, clause)
                if names_l:
                    items.append({"names": names_l, "amount": float(m.group(1)), "total": False})
                    continue
            m = _FOR_BOTH.search(clause)
            if m and 10 <= float(m.group(1)) <= 2000:
                before = list(_ROLE_LIST.finditer(clause[:m.start()]))
                names_l = _est_names(before[-1].group(0), clause) if before else []
                if len(names_l) < 2:
                    after = _ROLE_LIST.match(clause[m.end():].lstrip())  # "$90/mo for both gas and electric"
                    names_l = _est_names(after.group(0), clause) if after else []
                if len(names_l) < 2 and not clause[m.end():].strip(" \t,") \
                        and re.search(r"\b(?:tenant|resident|renter|you pay|your responsibility|on you)\b", before_whole) \
                        and not re.search(r"\b(?:included|landlord pays|owner pays|covered)\b", before_whole):
                    # cycle 16 join: "Gas cooking, electric tenant. Budget around $90/mo for both.": the two named just before
                    names_l = [w for w in _est_names(" ".join(x.group(0) for x in _ROLE_LIST.finditer(before_whole)), before_whole) if w != "trash"]
                if len(names_l) >= 2:
                    items.append({"names": names_l, "amount": float(m.group(1)), "total": False})
                    continue
            got = False
            for k, pat in enumerate(_EST_NAMED):
                for m in pat.finditer(clause):
                    amount = float(m.group(1) if k == 1 else m.group(2))
                    names_l = _est_names(m.group(2 if k == 1 else 1), clause)
                    if k == 0 and (m.group(1).rstrip().endswith((",", ":")) or re.search(r"[,:(]", clause[m.end(1):m.start(2)])):
                        # "Tenant pays: electric and gas, avg $65 electric": the list before the figure is a lead-in and the
                        # utility written right after the figure is the one it is for
                        trail = _ROLE_LIST.match(re.sub(r"^[ \t/]*(?:(?:mo(?:nth)?|per[ \t]+month|a[ \t]+month|monthly)[ \t]+)?(?:for[ \t]+)?", "", clause[m.end():]))  # cycle 24: "(about $55/mo water)"
                        if trail and not re.match(r"[ \t]*(?:combined|total)", clause[m.end():]):
                            trail_names = _est_names(trail.group(0), clause)
                            if trail_names:
                                names_l = trail_names
                    if k == 2 and set(names_l) <= {"trash"}:
                        continue  # "Trash $15/mo" is a service fee, not a utility bill
                    if names_l and 10 <= amount <= 2000 and (k != 1 or re.search(_EST_WORD, clause)):
                        if not any(i["amount"] == amount and set(i["names"]) & set(names_l) for i in items):
                            items.append({"names": names_l, "amount": amount, "total": False})
                        got = True
            if got:
                continue
            pm1 = _PLAIN_ONLY.match(clause.strip())
            if pm1:
                # a line that is only a utility and a figure ("electric $60", "Tenant pays electric $55"): the listing's own monthly figure
                plain1 = [w for w in _est_names(pm1.group("names"), clause) if w in ("electric", "gas", "water", "sewer", "heat")]
                amt1 = float(pm1.group("amt"))
                if plain1 and 10 <= amt1 <= 2000:
                    if not any(i["amount"] == amt1 and set(i["names"]) & set(plain1) for i in items):
                        items.append({"names": plain1, "amount": amt1, "total": False})
                    continue
            if several:
                # "Tenant pays $55 electric, avg $70 gas": the plain figure sits next to one with an estimate word, so it is an estimate too
                pm = _PLAIN_NAMED[0].search(clause) or _PLAIN_NAMED[1].search(clause)
                if pm:
                    plain_names = [w for w in _est_names(pm.group("names"), clause) if w != "trash"]
                    plain_amt = float(pm.group("amt"))
                    if plain_names and 10 <= plain_amt <= 2000:
                        if not any(i["amount"] == plain_amt and set(i["names"]) & set(plain_names) for i in items):
                            items.append({"names": plain_names, "amount": plain_amt, "total": False})
                        continue
            for pat in _EST_TOTAL:
                m = pat.search(clause)
                if m and 10 <= float(m.group(1)) <= 2000:
                    items.append({"names": [], "amount": float(m.group(1)), "total": True})
                    break
    return items


# ---- cycle 18: one general utility-line reader ---------------------------------------------------------------------
_GEN_MONEY = re.compile(r"(?<![\w$])\$[ \t]?((?:\d{1,3}(?:,\d{3})+|\d{1,5})(?:\.\d{1,2})?)(?![\d])")
_GEN_GENERIC = re.compile(r"\b(?:all[ \t]+(?:the[ \t]+)?)?utilit(?:y|ies)\b", re.I)
_GEN_SKIP_AROUND = re.compile(r"deposit|one[- ]time|set[- ]?up|application|activation|move[- ]in|late|\bpets?\b|parking|insurance|\bfee\b(?<!flat fee)", re.I)
_GEN_NOISE = r"(?:all(?=[ \t]+(?:paid|billed|charged))|budget[ \t]+billing|budget(?=[ \t~]*(?:about|around|approx\w*|roughly|est\w*)?[ \t~]*(?:\$|$))|(?:utility[ \t]+)?(?:providers?|compan(?:y|ies)|city)|service|up[ \t]+to|as[ \t]+much[ \t]+as|quarterly|annual(?:ly)?|yearly|via|through|thru|passed|rubs|billing|ratio|tenants?|residents?|renters?|pays?|paid|is|are|runs?|about|around|approx\w*|avg\.?|averages?|average|typical(?:ly)?|est\w*|roughly|usually|flat|fee|rate|billed|back|charged|at|only|total|combined|of|bills?|costs?|per[ \t]+month|monthly|submeter\w*|metered|capped|plus|for|on|to[ \t]+cover|toward|covers?|covering|a[ \t]+month|/[ \t]*mo|bundled|which|seasonal(?:ly)?|you)"
# cycle 19: period wording that may sit between a name and its figure ("Electric every 3 months about $90", "water-sewer ($70 bi-monthly)")
_GEN_NUMWORD = r"(?:\d{1,2}|two|three|four|six|twelve)"
_GEN_PERIOD_PHRASE = r"(?:(?:billed[ \t]+|charged[ \t]+|paid[ \t]+)?(?:every|each)[ \t]+(?:other[ \t]+)?(?:" + _GEN_NUMWORD + r"[ \t]+)?(?:months?|quarters?|years?)|bi-?monthly|semi-?annual(?:ly)?|annual(?:ly)?|yearly|quarterly|monthly|separately|by|in[ \t]+addition)"
_GEN_SEASON_WORD = r"(?:in[ \t]+)?(?:winter|summer|spring|fall|autumn|peak|off-?peak)(?:[ \t]+(?:months?|season|bills?))?"  # cycle 20: "gas winter avg $70, summer avg $15"
_GEN_GAP = re.compile(r"^(?:[\s:=~(),.\-/]|" + _GEN_PERIOD_PHRASE + r"\b|" + _GEN_SEASON_WORD + r"\b|" + _GEN_NOISE + r"\b)*$", re.I)


def _gen_months(phrase: str) -> int | None:
    """How many months one bill covers, from period wording ("every 3 months", "bi-monthly", "per quarter", "annually"); None when it says none."""
    p = phrase.lower()
    nums = {"two": 2, "three": 3, "four": 4, "six": 6, "twelve": 12}
    m = re.search(r"every[ \t]+(?:other[ \t]+)?(?:(\d{1,2}|two|three|four|six|twelve)[ \t]+)?(month|quarter|year)s?\b", p)
    if m:
        n = m.group(1)
        n = int(n) if n and n.isdigit() else nums.get(n or "", 1)
        unit = {"month": 1, "quarter": 3, "year": 12}[m.group(2)]
        if re.search(r"every[ \t]+other[ \t]+month", p):
            return 2
        return n * unit if n * unit in (1, 2, 3, 4, 6, 12) else None
    if re.search(r"\b(?:each|per|a)[ \t]+quarter\b|\bquarterly\b|\bqtr\b", p):
        return 3
    if re.search(r"\bbi-?monthly\b", p):
        return 2
    if re.search(r"\bsemi-?annual", p):
        return 6
    if re.search(r"\b(?:each|per|a)[ \t]+year\b|\bannual(?:ly)?\b|\byearly\b|/[ \t]*yr\b", p):
        return 12
    return None
_GEN_AFTER_PERIOD = re.compile(r"^[ \t]*(?:(?:/|per|a|each|every)[ \t]*)?(?:(?P<b>(?:2|two)[ \t]*mo(?:nth)?s?\b|(?:every[ \t]+)?other[ \t]+month\b)|(?P<mo>mo(?:nth)?\b|month\b|monthly\b|every[ \t]+month)|(?P<q>quarter(?:ly)?\b|qtr\b|every[ \t]+(?:3|three)[ \t]+months\b)|(?P<h>every[ \t]+(?:6|six)[ \t]+months\b|semi-?annual(?:ly)?\b)|(?P<y>year(?:ly)?\b|yr\b|annual(?:ly)?\b))", re.I)
_GEN_TENANT = re.compile(r"\b(?:tenants?|residents?|renters?|lessees?)\b|\b(?:billed|charged|invoiced)[ \t]+(?:by|from)[ \t]+(?:the[ \t]+)?(?:landlord|owner|management|property[ \t]+manager)\b|\byou[ \t]+(?:pay|are[ \t]+responsible|handle)\b|\bon[ \t]+you\b|\b(?:billed|charged)[ \t]+(?:back|through|to)\b|\brubs\b|\bsub-?meter\w*|\bpassed[ \t]+through\b|\bextra\b|\bseparate\b|(?:\bnot|n't)[ \t]+included\b|\bexcluded\b|\bplus\b", re.I)
_GEN_LANDLORD = re.compile(r"(?<!billed by )(?<!charged by )(?<!invoiced by )(?<!billed from )(?<!billed by the )(?<!charged by the )\b(?:landlord|owners?|management|property[ \t]+manager)\b|(?<!not )(?<!n't )\b(?:included|covered|provided)\b", re.I)


_GEN_PERIOD_AFTER_LIST = re.compile(r"^[ \t,]*(?:(?:billed|charged|paid|due)[ \t]+)?(?:every|each|per|a|/)[ \t]*(?:(?P<q>quarter\b|(?:3|three)[ \t]+months\b)|(?P<y>year\b|12[ \t]+months\b)|(?P<h>(?:6|six)[ \t]+months\b))", re.I)


# cycle 19: a dash that is followed by a payer word, "flat", "about" or a dollar figure joins a name to its details ("Electric - tenant (about $45)"),
# it does not start a new item. A dash followed by a utility name still starts one ("Electric $60 - Gas $55").
_GEN_DASH_ATTR = r"(?:\$|~|all[ \t]+(?:paid|billed|charged|tenant|resident|on|by|payable)\b|tenants?\b|residents?\b|renters?\b|you\b|flat\b|about\b|around\b|approx\w*|avg\b|averages?\b|est\b|est\.|roughly\b|usually\b|typically\b|paid\b|pays?\b|billed\b|charged\b|metered\b|submeter\w*|separate\w*|extra\b|rubs\b)"


def _gen_period(seg: str, start: int, end: int, nxt: int, single: bool, after_list: str = "", gap: str = "", head: str = "") -> int:
    """How many months the figure at seg[start:end] covers: read after the figure, else between its name and it, else just before its names,
    else (one figure only) anywhere in the line."""
    m = _GEN_AFTER_PERIOD.match(seg[end:nxt])
    if m:
        return 2 if m.group("b") else 3 if m.group("q") else 6 if m.group("h") else 12 if m.group("y") else 1
    m = re.match(r"^[ \t]*[)(,]*[ \t]*((?:every[ \t]+(?:other[ \t]+)?(?:\d{1,2}|two|three|four|six|twelve)?[ \t]*(?:months?|quarters?|years?)|bi-?monthly|quarterly))\b", seg[end:nxt], re.I)
    if m and _gen_months(m.group(1)) and not re.match(r"[ \t:]*(?:~|about|around|approx\w*|roughly|est\w*)?[ \t]*\$", seg[end + m.end():], re.I):
        return _gen_months(m.group(1)) or 1  # "($70 bi-monthly)" and "$90 (quarterly)"; not "$55 (bi-monthly $110)": there the period word labels the next figure, which restates this one
    if gap:
        g = re.search(_GEN_PERIOD_PHRASE, gap, re.I)
        if g and _gen_months(g.group(0)):
            return _gen_months(g.group(0)) or 1  # "Electric every 3 months about $90"
    if head:
        h = re.search(r"(?:every[ \t]+(?:other[ \t]+)?(?:\d{1,2}|two|three|four|six|twelve)?[ \t]*(?:months?|quarters?|years?)|bi-?monthly|quarterly|annual(?:ly)?)[ \t,:]*(?:(?:the|a|your|our)[ \t]+)?$", head, re.I)
        if h and _gen_months(h.group(0)):
            return _gen_months(h.group(0)) or 1  # "Every 3 months the water bill averages $210"
    m = _GEN_PERIOD_AFTER_LIST.match(after_list)  # "$210 for water and sewer every quarter"
    if m:
        return 3 if m.group("q") else 6 if m.group("h") else 12
    if single:
        if re.search(r"\bquarterly\b|\bper[ \t]+quarter\b|\bevery[ \t]+(?:3|three)[ \t]+months\b|/[ \t]*qtr", seg, re.I):
            return 3
        if re.search(r"\bannual(?:ly)?\b|\byearly\b|\bper[ \t]+year\b|/[ \t]*yr\b", seg, re.I):
            return 12
    else:
        head = seg[max(0, start - 30):start]
        if re.search(r"quarterly[ \t~,:]*(?:(?:about|around|approx\w*|avg|average|est\w*|roughly|is|of)[ \t~]*)*$", head, re.I):
            return 3
        if re.search(r"(?:annual(?:ly)?|yearly)[ \t~,:]*(?:(?:about|around|approx\w*|avg|average|est\w*|roughly|is|of)[ \t~]*)*$", head, re.I):
            return 12
    return 1


_GEN_ROLE_ITEM = r"\b(?:" + _ROLE_WORD + r")\b(?!\s+(?:stove|range|oven|fireplace|cooktop|grill|appliances?|water heater|pump|meter))"
_GEN_ROLE_LIST = re.compile(_GEN_ROLE_ITEM + r"(?:(?:\s*(?:,|/|&|\+|\band\b|\bor\b)\s*|(?<=\w)-(?=\w))" + _GEN_ROLE_ITEM + r")*", re.I)
_GEN_SEASON = r"(?:winter|summer|spring|fall|autumn|peak|off-?peak|cold|hot|heating|cooling|high|low)(?:[ \t]+(?:months?|season|bills?))?"
_GEN_UPTO = re.compile(r"\b(?:up[ \t]+to|as[ \t]+(?:much|high)[ \t]+as|max(?:imum)?(?:[ \t]+of)?|peaks?[ \t]+(?:at|of)|tops?[ \t]+out[ \t]+at|can[ \t]+(?:reach|hit))[ \t~]*$", re.I)
_GEN_TOTAL_WORD = re.compile(r"\b(?:total|combined|altogether|all[ -]in|together|bundle\w*|package|each|split|per[ \t]+person)\b", re.I)


def _util_general(text: str, pipes: bool = False) -> dict[str, Any] | None:
    """The one general utility-line step (cycle 18). Cut the text into items (lines, sentences, bullets, dashes), pair every named
    utility with the dollar figure written next to it and the period it covers (month, quarter, every 3 months, year), decide who
    pays from the words around it (tenant, resident, billed back, RUBS, owner, included), and add the tenant-paid figures once.
    pipes=True when the pasted text used pipes or dots between items ("Gas: $60 | Electric: $55 | Internet: $65"), so a lone internet or trash
    figure next to priced utilities is part of that list. Returns {"amount", "tenant", "landlord", "items", "conflict", "only", "all_landlord", "partials", "seasonal"} or None when the text has no priced
    utility the reader is sure about (the older readers then decide)."""
    low = text.lower()
    items: list[dict[str, Any]] = []
    landlord_names: list[str] = []
    tenant_names: list[str] = []
    generic_priced: list[float] = []
    only = False
    all_landlord = False
    prev_priced = False  # the segment right before this one held a priced tenant utility (a bullet list of utilities)
    partials: list[dict[str, Any]] = []  # one figure after several names: counted for the name it sits next to, the rest unknown
    seasonal: list[dict[str, Any]] = []  # two figures for one utility ("$110 winter, $30 summer"): the higher counts
    optional: list[dict[str, Any]] = []  # "Internet $55 (optional)": named in a note, never counted
    restated: list[float] = []  # "$130 combined (billed quarterly: ~$390)": the same bill said again for the whole period
    stated_totals: list[float] = []  # "-- budget roughly $170 a month total" after a priced list
    variable: list[dict[str, Any]] = []  # "Electric $45 seasonal (more in summer)": the figure is a floor, not the high bill
    peaks: list[dict[str, Any]] = []  # "winter higher up to $260", "up to $200 a month": the highest figure the listing admits to, which is the one counted
    deferred: list[tuple[int, dict[str, Any]]] = []  # a lone internet or trash figure, kept only when a neighbouring sentence is a priced utility (a pipe list)
    priced_sents: set[int] = set()
    carry_group: tuple[list[str], int] | None = None  # tenant-paid names with no figure in sentence N; a total in sentence N+1 is theirs ("Tenant pays electric, gas and internet. Typical total is $175/mo")
    sent_line: dict[int, int] = {}  # sentence number -> physical line, so a ";" list on one line is told from separate lines
    sentences: list[str] = []
    chain = 0  # one number for every sentence joined by ";" on one line; a period or a new line starts the next
    for line_txt in low.split("\n"):
        chain += 1
        for part in re.split(r"(;|\.(?=\s|$))", line_txt):
            if part == ";":
                continue
            if part == ".":
                chain += 1
                continue
            if not part.strip():
                continue
            sent_line[len(sentences)] = chain
            sentences.append(part)
    for si, sentence in enumerate(sentences):
        pieces = re.split(r"[ \t]+(?:-{2,}|[-–—•*])[ \t]+(?=\S)(?!" + _GEN_DASH_ATTR + r")|^[ \t]*[-–—•*][ \t]+", sentence)
        bullets = len(pieces) > 1 or bool(re.match(r"^[ \t]*[-–—•*][ \t]+", sentence))
        for seg in pieces:
            seg = seg.strip()
            if not seg:
                continue
            if re.search(r"\b(?:hoa|dues|association|assessments?|condo(?:minium)? fees?)\b", seg):
                continue  # what a building fee covers is not a utility bill the renter pays
            in_list = bullets and prev_priced
            prev_priced = False
            if _LANDLORD_PAYS_ALL.search(seg) and not re.search(r"\b(?:except|other than|besides|but|rubs|billed)\b", seg):
                all_landlord = True
            toks: list[tuple[int, int, str, Any]] = []  # (start, end, kind, names)
            for m in _GEN_ROLE_LIST.finditer(seg):
                names = [w for w in _ordered_utilities(re.findall(_ROLE_WORD, m.group(0))).split(", ") if w and w != "cable"]
                if names:
                    toks.append((m.start(), m.end(), "L", names))
            for m in _GEN_GENERIC.finditer(seg):
                if not any(t[0] <= m.start() < t[1] for t in toks):
                    toks.append((m.start(), m.end(), "G", []))
            for m in _GEN_MONEY.finditer(seg):
                if _GEN_SKIP_AROUND.search(seg[max(0, m.start() - 22):m.end() + 22]):
                    continue
                raw = float(m.group(1).replace(",", ""))
                if raw >= 900 and not re.search(r"\b(?:" + _ROLE_WORD + r"|utilit\w*|tenants?|residents?|renters?|landlord|owners?|total|combined)\b", seg[:m.start()]):
                    continue  # "Pine Valley Rental $2,260 bi-monthly water about $64": a rent-sized figure before any utility word is the rent, not a bill
                toks.append((m.start(), m.end(), "M", raw))
            toks.sort(key=lambda t: t[0])
            lists = [t for t in toks if t[2] in "LG"]
            moneys = [t for t in toks if t[2] == "M"]
            if moneys and not lists and len(moneys) == 1 and carry_group and si - carry_group[1] == 1 and _GEN_GROUP_TOTAL.search(seg) \
                    and not re.search(r"\b(?:rent|deposit|fees?|move-?in|everything|all[ \t]+(?:the[ \t]+)?utilit\w*)\b", seg) and not _GEN_FEE_WORDS.search(seg):
                gm = moneys[0]
                g_raw = gm[3]
                g_div = _gen_period(seg, gm[0], gm[1], len(seg), True)
                g_monthly = round(g_raw / g_div, 2)
                if 1 <= g_monthly <= 3000:
                    items.append({"names": list(carry_group[0]), "raw": g_raw, "div": g_div, "monthly": g_monthly, "group": True})
                    priced_sents.add(si)
                    prev_priced = True
                    carry_group = None
                    continue
            pairs: list[tuple[tuple, tuple]] = []
            if moneys and lists:
                def ok(a: tuple, b: tuple) -> bool:
                    return bool(_GEN_GAP.match(seg[a[1]:b[0]])) and not any(a[1] <= t[0] and t[1] <= b[0] for t in toks if t is not a and t is not b)
                name_first, used = [], set()
                for lt in lists:
                    mt = next((m for m in moneys if m[0] >= lt[1] and id(m) not in used), None)
                    if mt and ok(lt, mt):
                        name_first.append((lt, mt))
                        used.add(id(mt))
                amount_first, used = [], set()
                for mt in moneys:
                    lt = next((l for l in lists if l[0] >= mt[1] and id(l) not in used), None)
                    if lt and ok(mt, lt):
                        amount_first.append((lt, mt))
                        used.add(id(lt))
                def tight(ps: list[tuple[tuple, tuple]]) -> int:
                    return sum(abs(max(a[0], b[0]) - min(a[1], b[1])) for a, b in ps)
                pairs = amount_first if (len(amount_first), -tight(amount_first)) > (len(name_first), -tight(name_first)) else name_first
                other_pairs = name_first if pairs is amount_first else amount_first
                for op in other_pairs:  # "elec + gas (avg $155 total) + $22 sewer": the figure before a name still belongs to it
                    if not any(op[0] is p[0] or op[1] is p[1] for p in pairs):
                        pairs = pairs + [op]
            paired_l = {id(p[0]) for p in pairs}
            paired_m = {id(p[1]) for p in pairs}
            alts: dict[int, list[tuple]] = {}
            chain_end: dict[int, int] = {}
            season_ids: set[int] = set()
            for mt in moneys:
                if id(mt) in paired_m:
                    continue
                before_m = [p[1] for p in pairs if p[1][1] <= mt[0]]
                if not before_m:
                    continue
                base_m = max(before_m, key=lambda x: x[1])
                between = seg[chain_end.get(id(base_m), base_m[1]):mt[0]]  # "$80-$120 winter, $25 summer": the third figure follows the second one
                if re.match(r"^[ \t,/;&(]*(?:(?:mo(?:nth)?\b|per[ \t]+month|a[ \t]+month|monthly)[ \t,;]*)?(?:in[ \t]+)?(?:the[ \t]+)?(?:" + _GEN_SEASON + r")?[ \t,/;&)(]*(?:(?:and|or|then|but)[ \t]*)?(?:(?:in|the|~|about|around|approx\w*|avg\.?|average|est\w*|roughly|up[ \t]+to)[ \t]*)*$", between, re.I) \
                        and re.search(_GEN_SEASON, between + " " + seg[mt[1]:mt[1] + 16], re.I):
                    alts.setdefault(id(base_m), []).append(mt)  # "gas (~$110 winter, $30 summer)"
                    season_ids.add(id(mt))
                    chain_end[id(base_m)] = mt[1]
                elif re.match(r"^[ \t]*(?:\([ \t]*(?:in[ \t]+)?" + _GEN_SEASON + r"[ \t]*\)|(?:in[ \t]+)?" + _GEN_SEASON + r")?[ \t]*(?:-|\u2013|\u2014|to|up[ \t]+to)[ \t]*$", between, re.I) and mt[3] > base_m[3] and id(base_m) not in alts:
                    alts.setdefault(id(base_m), []).append(mt)  # "$85-$95 (seasonal)": a range, the higher end counts
                    season_ids.add(id(mt))
                    chain_end[id(base_m)] = mt[1]
            restate_ids: set[int] = set()
            total_ids: set[int] = set()
            peak_ids: set[int] = set()
            for mt in moneys:
                if id(mt) in paired_m or id(mt) in season_ids:
                    continue
                before_m = [p[1] for p in pairs if p[1][1] <= mt[0]]
                if before_m:
                    base_m = max(before_m, key=lambda x: x[1])
                    between = seg[base_m[1]:mt[0]]
                    if re.search(r"quarter|bi-?monthly|annual|yearly|every|months|\bper[ \t]+year\b|\bbilled\b", between) and base_m[3] > 0 \
                            and any(abs(mt[3] - k * base_m[3]) <= max(2.0, 0.02 * mt[3]) for k in (2, 3, 4, 6, 12)) and len(between) <= 60:
                        restate_ids.add(id(mt))  # "$130 combined (billed quarterly by the city: ~$390)"
                        restated.append(mt[3])
                        continue
                    if re.search(r"quarter|bi-?monthly|annual|yearly|every|months|\bper[ \t]+year\b", between) and mt[3] > 0 and len(between) <= 40 \
                            and re.match(r"[ \t]*(?:/[ \t]*mo(?:nth)?\b|per[ \t]+month|a[ \t]+month|monthly|each[ \t]+month)", seg[mt[1]:]) \
                            and any(abs(base_m[3] - k * mt[3]) <= max(2.0, 0.02 * base_m[3]) for k in (2, 3, 4, 6, 12)):
                        restate_ids.add(id(mt))  # "Electric ~$110 bi-monthly ($55/mo)": the bracket says the same bill per month
                        restated.append(mt[3])
                        continue
                near_t = seg[max(0, mt[0] - 30):mt[1] + 25]
                if _GEN_UPTO.search(seg[max(0, mt[0] - 24):mt[0]]) and (pairs or si in priced_sents or stated_totals) and not _gen_fee_owned(seg, mt):
                    peak_ids.add(id(mt))
                    peaks.append({"amount": round(mt[3] / _gen_period(seg, mt[0], mt[1], len(seg), True), 2), "names": []})  # "approx $215 total, winter higher up to $260"
                    continue
                if re.search(r"\b(?:total|combined|altogether|budget|overall|all[ -]in)\b", near_t) and not re.search(r"\b(?:rent|deposit|fees?|move-?in|parking|pets?)\b", near_t) \
                        and not re.search(r"\b(?:everything|all[ \t]+(?:the[ \t]+)?utilit|other|else|remaining|including|both)\b|\bfor\b", seg[mt[1]:mt[1] + 40]) \
                        and (pairs or si in priced_sents or (si - 1 in priced_sents and sent_line.get(si, 0) - sent_line.get(si - 1, 0) <= 1)):
                    total_ids.add(id(mt))  # "-- budget roughly $170 a month total": checked against the items once they are all read
                    stated_totals.append(round(mt[3] / _gen_period(seg, mt[0], mt[1], len(seg), True), 2))
            if any(id(m) not in paired_m and id(m) not in season_ids and id(m) not in restate_ids and id(m) not in total_ids and id(m) not in peak_ids and not _gen_fee_owned(seg, m) and _util_money_context(seg, m) for m in moneys):
                return None  # a figure next to utility words that no utility owns: leave it to the older readers
            # items in text order
            elems: list[dict[str, Any]] = []
            for lt in lists:
                mt = next((p[1] for p in pairs if p[0] is lt), None)
                elems.append({"start": lt[0], "end": max(lt[1], mt[1] if mt else 0), "list": lt, "money": mt, "names": list(lt[3]), "kind": lt[2]})
            # "$110 total for electric and gas": a list written right after a figure that already has names joins them
            for i, e in enumerate(elems):
                if e["money"] is not None and e["kind"] == "L":
                    nxt_e = elems[i + 1] if i + 1 < len(elems) else None
                    if nxt_e and nxt_e["money"] is None and nxt_e["kind"] == "L" and re.match(r"^[ \t]*(?:/[ \t]*mo|per[ \t]+month|monthly|a[ \t]+month)?[ \t]*(?:total|combined|in[ \t]+all)?[ \t]*(?:for|on|of)[ \t]+(?:both[ \t]+)?$", seg[e["end"]:nxt_e["start"]]):
                        e["names"] += [w for w in nxt_e["names"] if w not in e["names"]]
                        e["end"] = nxt_e["end"]
                        nxt_e["skip"] = True
            elems = [e for e in elems if not e.get("skip")]
            for e in elems:
                if e["money"] is not None and e["kind"] == "L" and re.match(r"^[ \t]*(?:/[ \t]*mo|per[ \t]+month|monthly|a[ \t]+month)?[ \t]*(?:in[ \t]+)?(?:total|combined|altogether)?[ \t]*(?:for|on|of)[ \t]+(?:all|the|your)[ \t]+(?:the[ \t]+)?utilit", seg[e["money"][1]:]):
                    e["kind"] = "G"  # "Gas: roughly $150 a month total for all utilities": the figure is the whole bill
            cues = [(m.start(), "tenant") for m in _GEN_TENANT.finditer(seg)] + [(m.start(), "landlord") for m in _GEN_LANDLORD.finditer(seg)]
            cues.sort()
            group_role = ""
            for i, e in enumerate(elems):
                nxt_start = elems[i + 1]["start"] if i + 1 < len(elems) else len(seg)
                tail = [c for c in cues if e["list"][1] <= c[0] < nxt_start and not (e["money"] is not None and e["money"][0] < e["list"][0] and c[0] < e["money"][1])]
                e["own"] = tail[0][1] if tail else ""
                if i + 1 == len(elems) and tail and (re.match(r"^[ \t,]*\(|^[ \t,]*(?:all|both|each)\b", seg[e["end"]:]) or len(elems) > 1 and re.search(r"\((?:[^)]*\b(?:all|both|each|three|two)\b)[^)]*\)", seg[e["end"]:])):
                    group_role = tail[0][1]
                lead = [c for c in cues if c[0] < e["start"]]
                e["lead"] = lead[-1][1] if lead else ""
                e["only"] = bool(re.search(r"\bonly\b", seg[max(0, e["start"] - 6):e["start"]] + seg[e["end"]:e["end"] + 12] + seg[e["list"][1]:e["list"][1] + 8], re.I))
            for e in elems:
                role = e["own"] or e["lead"] or group_role
                e["role"] = role
                if e["kind"] == "G":
                    if e["money"] is not None:
                        generic_priced.append(e["money"][3])
                    continue
                if e["money"] is None:
                    if re.search(r"\b(?:no|without|zero|none|n/a)[ \t]*$", seg[max(0, e["start"] - 8):e["start"]]):
                        continue  # "no gas (all electric)": a utility the listing says does not exist is nobody's bill
                    if re.search(r"\b(?:except(?:[ \t]+for)?|other[ \t]+than|besides|excluding|but(?![ \t]+not)|aside[ \t]+from)[ \t]*$", seg[max(0, e["start"] - 25):e["start"]]):
                        return None  # "pays everything but electric": the names are what the line leaves OUT, so the older readers (who know "except") decide
                    if role == "landlord":
                        landlord_names += e["names"]
                    elif role == "tenant":
                        tenant_names += e["names"]
                        if e["kind"] == "L" and len(e["names"]) >= 2 and _gen_last_elem(elems, e):
                            carry_group = (list(e["names"]), si)
                    continue
                if re.search(r"\boptional\b", seg[e["list"][1]:e["money"][0]] if e["money"][0] >= e["list"][1] else "") \
                        or re.match(r"^[ \t]*(?:/[ \t]*mo\w*|per[ \t]+month|a[ \t]+month)?[ \t]*\(?[ \t]*optional\b", seg[e["money"][1]:e["money"][1] + 30]) \
                        or re.search(r"\boptional[ \t]+$", seg[max(0, e["list"][0] - 12):e["list"][0]]):
                    optional.append({"names": list(e["names"]), "amount": e["money"][3]})  # "Internet $55 (optional)": a choice, so it is not a cost the renter has to pay
                    continue
                if role == "landlord":
                    return None  # a priced utility that the same line says is included: two readings, the older readers note it
                if not role and in_list:
                    role = "tenant"  # a bullet under other priced utilities
                n_priced = sum(1 for x in elems if x["money"] is not None)
                deferrable = False
                if not role and set(e["names"]) <= {"trash", "internet"} and not (in_list or n_priced > 1):
                    deferrable = True  # "Trash $15/mo" and "Internet $65" alone are service fees, left to the fee readers (unless a pipe list sits around it)
                after_win = seg[e["end"]:e["end"] + 30]
                cut_win = re.search(r"(?:,|[ \t]and\b|[ \t]plus\b)[^$]{0,25}\$", after_win)  # "Trash $18, Pest $6": the next priced item is its own fee, not a word about this one
                if cut_win:
                    after_win = after_win[:cut_win.start()]
                if _NON_UTILITY_SERVICE.search(seg[max(0, e["start"] - 25):e["end"]] + after_win):
                    continue  # "$85/mo flat fee for water, sewer, trash and pest control": a service fee, counted by the fee readers
                if re.search(r"\bflat\b", seg[e["list"][1]:e["money"][1] + 14]) and not n_priced > 1 and not in_list \
                        and not re.search(r"/[ \t]*mo|per[ \t]+month|monthly|a[ \t]+month|each[ \t]+month", seg[e["list"][1]:e["money"][1] + 26]):
                    continue  # "Water/trash flat $65" with no period is a flat fee the fee readers count once
                nxt_pos = next((m[0] for m in moneys if m[0] > e["money"][0] and id(m) not in season_ids), len(seg))
                ei = elems.index(e)
                name_first_e = e["money"][0] >= e["list"][1]
                gap_txt = seg[e["list"][1]:e["money"][0]] if name_first_e else seg[e["money"][1]:e["list"][0]]
                head_txt = seg[(elems[ei - 1]["end"] if ei else 0):min(e["list"][0], e["money"][0])][-40:] if not (ei and elems[ei - 1]["money"] is not None) else ""  # "water $70 bi-monthly, internet $60": the period words belong to the figure before them
                div = _gen_period(seg, e["money"][0], e["money"][1], min(nxt_pos, len(seg)), len(moneys) - len(season_ids) == 1,
                                  seg[e["end"]:e["end"] + 30] if e["money"][0] < e["list"][0] else "", gap_txt, head_txt)
                raw_amt = e["money"][3]
                names_here = list(e["names"])
                unknown_here: list[str] = []
                if id(e["money"]) in alts and div == 1:
                    figs = [e["money"][3]] + [a[3] for a in alts[id(e["money"])]]
                    raw_amt = max(figs)
                    last_end = max(a[1] for a in alts[id(e["money"])])
                    tail_m = re.match(r"[ \t]*\(?[ \t]*(?:in[ \t]+)?(?:the[ \t]+)?" + _GEN_SEASON + r"\)?", seg[last_end:], re.I)
                    q_start = e["money"][0]
                    if e["money"][0] >= e["list"][1]:
                        sw = re.search(r"(?:\bin[ \t]+)?\b(?:" + _GEN_SEASON + r")", seg[e["list"][1]:e["money"][0]], re.I)
                        if sw:
                            q_start = e["list"][1] + sw.start()  # "winter avg $70, summer avg $15": the season words before the first figure belong in the quote
                    quote = re.sub(r"\s+", " ", seg[q_start:last_end + (tail_m.end() if tail_m else 0)]).strip(" ,.;)")
                    if quote.count("(") > quote.count(")"):
                        quote += ")"
                    seasonal.append({"names": names_here, "figures": sorted(figs, reverse=True), "quote": quote})
                elif id(e["money"]) in alts:
                    return None  # two figures and a quarterly or yearly period: too unclear to count
                if e["kind"] == "L" and _gen_partial_list(seg, e):
                    unknown_here = names_here[:-1]
                    names_here = names_here[-1:]
                    partials.append({"all": list(e["names"]), "last": names_here[0], "unknown": unknown_here, "amount": raw_amt})
                monthly = round(raw_amt / div, 2)
                if not 1 <= monthly <= 3000:
                    return None
                item = {"names": names_here, "raw": raw_amt, "div": div, "monthly": monthly}
                if id(e["money"]) not in alts and _GEN_UPTO.search(seg[max(0, e["money"][0] - 24):e["money"][0]]):
                    peaks.append({"amount": monthly, "names": list(names_here)})  # "Electric and gas up to $200 a month": the top figure is the one counted
                if id(e["money"]) not in alts and e["money"][0] >= e["list"][1] and re.match(r"^[ \t]*(?:seasonal(?:ly)?[ \t]*)?\(?[ \t]*(?:(?:more|higher|up|goes[ \t]+up)[ \t]+(?:in|during)[ \t]+\w+|(?:winter|summer)[ \t]+(?:is[ \t]+)?(?:higher|more)|higher[ \t]+in[ \t]+\w+|varies)", seg[e["money"][1]:e["money"][1] + 40]):
                    variable.append({"names": list(names_here), "amount": monthly})
                if len(names_here) > 1 and _GEN_GROUP_TOTAL.search(seg[min(e["list"][0], e["money"][0]):max(e["list"][1], e["money"][1]) + 16]):
                    item["group"] = True  # "electric | gas | water | internet - about $210 total": one figure for all the names
                if deferrable:
                    deferred.append((si, item, list(e["names"]), e["only"]))
                    continue
                items.append(item)
                priced_sents.add(si)
                tenant_names += e["names"]
                prev_priced = True
                only = only or e["only"]
    for dsi, ditem, dnames, donly in deferred:
        same_line_nb = any(n in priced_sents and sent_line.get(n) == sent_line.get(dsi) for n in (dsi - 1, dsi + 1))  # "Electric ~$40; Internet $60; Water $45": a ";" list
        run_before = dsi - 1 in priced_sents and len(items) >= 3  # "Trash $18, Water $40, Electric ~$55, Gas ~$70. Internet $55.": the lone figure ends a list of priced utilities
        if (pipes or same_line_nb or (run_before and sent_line.get(dsi) == sent_line.get(dsi - 1) + 1)) and (dsi - 1 in priced_sents or dsi + 1 in priced_sents) and any(not set(i["names"]) <= {"trash", "internet"} for i in items):
            items.append(ditem)  # "Gas: $60 | Electric: $55 | Internet: $65": the pipes made each part its own sentence
            tenant_names += dnames
            only = only or donly
            priced_sents.add(dsi)
    if generic_priced:
        if all_landlord and not items:
            return {"conflict": generic_priced[0], "amount": None, "tenant": [], "landlord": [], "items": [], "only": False, "all_landlord": True}
        return None
    if not items:
        return None
    optional = [o for o in optional if not any(set(o["names"]) & set(i["names"]) for i in items)]
    seen: list[dict[str, Any]] = []
    for it in items:
        same = [s for s in seen if set(s["names"]) & set(it["names"])]
        if any(set(s["names"]) != set(it["names"]) or s["monthly"] != it["monthly"] for s in same):
            return None  # overlapping figures for the same utility: the older readers keep the higher one and say so
        if not same:
            seen.append(it)
    if all_landlord and not only:
        return None
    amount = round(sum(s["monthly"] for s in seen), 2)
    stated_total = None
    base_amount = amount
    if stated_totals and not partials:
        stated_total = max(stated_totals)
        if stated_total > amount:
            amount = stated_total  # the listing's own total is higher than the items it lists: the higher one is the cost it admits to
            base_amount = amount
    peaks = [pk for pk in peaks if pk["names"] or items]
    top = max((pk["amount"] for pk in peaks if not pk["names"]), default=0)
    if top and top > amount:
        amount = top  # "approx $215 total, winter higher up to $260": the winter figure is what a high month costs
    elif top:
        peaks = [pk for pk in peaks if pk["names"]]
    return {"amount": amount, "stated_total": stated_total, "peaks": peaks, "base_amount": base_amount, "restated": restated, "optional": optional, "variable": [v for v in variable if any(set(v["names"]) == set(i["names"]) for i in seen)], "tenant": [w for w in _ordered_utilities(tenant_names).split(", ") if w],
            "landlord": [w for w in _ordered_utilities(landlord_names).split(", ") if w and w not in tenant_names],
            "items": seen, "conflict": None, "only": only, "all_landlord": all_landlord,
            "partials": [pt for pt in partials if any(pt["last"] in it["names"] for it in seen)], "seasonal": [sz for sz in seasonal if any(set(sz["names"]) == set(it["names"]) for it in seen)]}


def _pipe_list(text: str) -> bool:
    """True when one line of the pasted text has a utility word, a dollar figure and two or more pipes or dots between items
    ("Gas: $60 | Electric: $55 | Internet: $65"). One address pipe ("... Apt 204 | URBANA") is not a list."""
    label_lines = [ln for ln in text.split("\n") if re.match(r"^[ \t]*(?:[-*\u2022][ \t]+)?(?:utilit\w*[ \t]*:[ \t]*)?(?:electric\w*|gas|water|sewer|trash|internet|heat\w*|garbage)[a-z /&]{0,20}[:\-]?[ \t]*(?:~|about[ \t]+|around[ \t]+)?\$\d+[^\n]{0,30}$", ln, re.I)]
    if len(label_lines) >= 3 and sum(1 for ln in label_lines if re.match(r"^[ \t]*(?:[-*\u2022][ \t]+)?(?:utilit\w*[ \t]*:[ \t]*)?(?:electric|gas|water|sewer|heat)", ln, re.I)) >= 2:
        return True  # "Gas: $60" / "Electric: $55" / "Internet: $65" on separate lines
    for line in text.split("\n"):
        if len(re.findall(r"[ \t][|\u2022\u00b7][ \t]", line)) >= 2 and "$" in line and re.search(r"\b(?:electric|gas|water|sewer|trash|internet|heat)\w*", line, re.I):
            return True
    return False


def _gen_partial_list(seg: str, e: dict[str, Any]) -> bool:
    """One figure written right after a comma list of three or more utilities ("Tenant: electric, gas, water, internet ($60)") with
    no word that makes it a total: it belongs to the name it sits next to, the others have no amount."""
    names = e["names"]
    if len(names) < 2 or set(names) <= {"water", "sewer", "trash"} or e["money"] is None or e["money"][0] < e["list"][1]:
        return False
    in_paren = "(" in seg[e["list"][1]:e["money"][0]]  # "you pay electric and gas and internet (~$70)": the bracket belongs to the last name
    dashed = bool(re.match(r"^[ \t]*(?:-{1,2}|\u2013|\u2014)[ \t]*", seg[e["list"][1]:e["money"][0]]))  # cycle 26: "electric and internet - approx $60/mo": the figure touches the last name only
    if len(names) < 3 and not (in_paren or dashed):
        return False
    if "," not in seg[e["list"][0]:e["list"][1]] and not in_paren and not dashed:
        return False
    if not re.match(r"^[ \t]*[(:=\-\u2013]?[ \t]*(?:~|about|around|approx\w*|avg\.?|average|est\w*|roughly)?[ \t]*[(~]?[ \t]*$", seg[e["list"][1]:e["money"][0]], re.I):
        return False
    if re.search(r"\b(?:total|combined|altogether|all[ -]in|together|bundle\w*|package)\b", seg, re.I):
        return False
    return not re.search(r"\b(?:each|split|per[ \t]+person|for[ \t]+all|for[ \t]+both|total|combined)\b", seg[e["money"][1]:e["money"][1] + 40], re.I)


_GEN_GROUP_TOTAL = re.compile(r"\b(?:total|combined|altogether|in[ \t]+all|all[ -]in|together)\b", re.I)
_GEN_FEE_WORDS = re.compile(r"\b(?:pets?|parking|garage|application|admin\w*|hoa)\b", re.I)


def _gen_last_elem(elems: list[dict[str, Any]], e: dict[str, Any]) -> bool:
    """True when this item is the last one of its sentence (a total in the next sentence can then belong to its names)."""
    return elems[-1] is e


def _gen_fee_owned(seg: str, m: tuple) -> bool:
    """True when a figure sits right after a service-fee name ("Trash $18, Pest $6"): the fee readers own it, it is not a utility figure."""
    return bool(re.search(r"\b(?:pest|valet|package|amenity|lawn|landscap\w*|snow|cleaning|housekeeping|parking|garage|pet)\w*(?:[ \t]+\w+)?[ \t:=~-]*(?:about[ \t]*|approx\w*[ \t]*)?$", seg[max(0, m[0] - 24):m[0]]))


def _util_money_context(seg: str, m: tuple) -> bool:
    """True when an unowned dollar figure sits in a line that is about utilities (so it must not be dropped silently)."""
    if re.match(r"^[ \t]*(?:/[ \t]*mo(?:nth)?|per[ \t]+month|a[ \t]+month|monthly)?[ \t,]*(?:in[ \t]+)?(?:total|combined|altogether|for[ \t]+both|all[ \t-]*in)\b", seg[m[1]:]) or re.search(r"\bbudget\b[^$]{0,25}$", seg[:m[0]]):
        return True  # "Budget around $90/mo for both": a figure for utilities named in another sentence, left to the older readers
    near = seg[max(0, m[0] - 60):m[1] + 40]
    return bool(re.search(r"\b(?:water|sewer|sewage|trash|garbage|gas|electric\w*|heat|internet|wi-?fi|utilit\w*)\b", near)) and not re.search(r"\brent\b", near)


def _util_general_differs(gen: dict[str, Any], est: Any, pays: str, included: str, old_names: set[str] | None = None) -> bool:
    """True when the general reader's figure, payers or included list are not what the older readers ended with."""
    if gen["conflict"]:
        return included == "all"
    if gen.get("partials") or gen.get("seasonal") or gen.get("peaks") or gen.get("optional") or gen.get("variable") or gen.get("restated") or gen.get("stated_total") or any(it.get("group") for it in gen["items"]):
        return True  # one figure for several names, or two seasonal figures: the older readers' note would claim more than the listing says
    have_pays = {w.strip() for w in pays.split(",") if w.strip()}
    inc = set(_ALL_UTILITIES) if included == "all" else {w.strip() for w in included.split(",") if w.strip()}
    if not isinstance(est, (int, float)) or abs(float(est) - gen["amount"]) > 0.01:
        return True
    priced_here = {w for it in gen["items"] for w in it["names"]}
    unpriced_old = set(old_names or ()) - priced_here
    if priced_here & {"gas", "heat"}:
        unpriced_old -= {"gas", "heat"}  # a gas figure is the heat's figure too
    if unpriced_old and priced_here and not gen.get("stated_total"):
        return True  # cycle 24: "pays gas, electric and water (about $55/mo water)": the figure is the water's, the older note said it was all three
    return bool(set(gen["tenant"]) - have_pays) or bool(set(gen["tenant"]) & inc) or bool(have_pays & set(gen["landlord"]))


def _util_general_note(gen: dict[str, Any]) -> str:
    groups = [it for it in gen["items"] if it.get("group")]
    if len(groups) == 1 and len(gen["items"]) == 1:
        g = groups[0]
        text = (f"The listing gives about {_money_cents(g['monthly'])} a month as the total for {_join_names(g['names'])}, counted as your utilities estimate."
                if g["div"] == 1 else
                f"The listing gives {_money_cents(g['raw'])} for {_join_names(g['names'])} as one total for {g['div']} months, about {_money_cents(g['monthly'])} a month, counted as your utilities estimate.")
    elif all(it["div"] == 1 for it in gen["items"]) and not groups:
        names = _ordered_utilities([w for it in gen["items"] for w in it["names"]]).split(", ")
        text = f"{_join_names(names).capitalize()} {_util_verb(', '.join(names))} about {_money_cents(gen.get('base_amount', gen['amount']))} a month from the listing, counted as your utilities estimate."
    else:
        parts = []
        for it in gen["items"]:
            names = _join_names(it["names"])
            if it["div"] == 1 and it.get("group"):
                parts.append(f"{names} about {_money_cents(it['monthly'])} a month in total")
            elif it["div"] == 1:
                parts.append(f"{names} about {_money_cents(it['monthly'])} a month")
            else:
                unit = {2: "two months", 3: "quarter", 6: "six months", 12: "year"}.get(it["div"], f"{it['div']} months")
                parts.append(f"{names} {_money_cents(it['raw'])} per {unit}, about ${it['monthly']:,.2f} a month".replace(".00 a month", " a month"))
        text = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
        text = text[:1].upper() + text[1:] + " from the listing, counted as your utilities estimate."
    for pt in gen.get("partials") or []:
        unk = pt["unknown"]
        text += (f" The listing gives one figure, {_money_cents(pt['amount'])}, after {_join_names(pt['all'])}, and does not say it is the total for all of them. "
                 f"It is counted for {pt['last']} only. {_join_names(unk).capitalize()} {'is' if len(unk) == 1 else 'are'} listed as something you pay, with no amount. "
                 f"Ask what {'it costs' if len(unk) == 1 else 'they cost'}.")
    left_unpriced = list(gen.get("scoped_unknown") or [])
    if left_unpriced and not gen.get("partials") and not gen.get("stated_total") and not any(it.get("group") for it in gen["items"]) and not gen.get("optional"):
        text += (f" {_join_names(left_unpriced).capitalize()} {'is' if len(left_unpriced) == 1 else 'are'} listed as something you pay, with no amount. "
                 f"Ask what {'it costs' if len(left_unpriced) == 1 else 'they cost'}.")
    for vr in gen.get("variable") or []:
        text += f" The listing says {_join_names(vr['names'])} costs more in some months, so {_money_cents(vr['amount'])} may be low. Ask what a high month costs."
    for rs in gen.get("restated") or []:
        mine = next((it for it in gen["items"] if abs(it["monthly"] - rs) < 0.51 or any(abs(it["monthly"] * k - rs) <= max(2.0, 0.02 * rs) for k in (2, 3, 4, 6, 12)) or abs(it["raw"] - rs) < 0.51), None)
        if mine is not None:
            text += f" The {_money_cents(rs)} in the listing is the same {_join_names(mine['names'])} bill said another way, so it is not added again."
    for op in gen.get("optional") or []:
        text += f" {_join_names(op['names']).capitalize()} is listed as optional at {_money_cents(op['amount'])}, so it is not counted. Ask if you need it."
    # cycle 23: a stated total that is the counted figure needs no sentence of its own (it was said twice: "about $148 a month ... also gives $148 as the total")
    for pk in gen.get("peaks") or []:
        if pk["names"]:
            text += f" The listing says up to {_money_cents(pk['amount'])} for {_join_names(pk['names'])} in a high month, so the higher figure, {_money_cents(pk['amount'])}, is counted. Ask what a typical month costs."
        else:
            text += f" The listing also says up to {_money_cents(pk['amount'])} in a high month, so the higher figure, {_money_cents(pk['amount'])}, is counted instead. Ask what a typical month costs."
    for sz in gen.get("seasonal") or []:
        shown = f": {sz['quote']}" if "(" in sz["quote"] else f" ({sz['quote']})"  # a bracket inside the quote would nest
        how_many = {2: "two", 3: "three"}.get(len(sz["figures"]), "several")
        text += (f" The listing gives {_join_names(sz['names'])} {how_many} figures{shown}. The higher one, {_money_cents(sz['figures'][0])}, is counted. "
                 "Ask what a typical month costs.")
    return text


_RANGE_FIG = re.compile(r"\$[ \t]?(\d[\d,]*(?:\.\d\d)?)[ \t]*(?:-|\u2013|\u2014|to|or)[ \t]*\$?[ \t]?(\d[\d,]*(?:\.\d\d)?)(?![\d,])", re.I)
_TOTAL_FIG = re.compile(r"\b(?:typical|average|avg\.?|estimated|est\.?|approx\w*|about|around|roughly|usually|monthly)?[ \t]*(?:utilit\w*[ \t]+)?\btotal\b[ \t]*(?:is|of|:|-|=|runs)?[ \t]*(?:(?:about|around|approx\w*|roughly|est\w*|avg\.?|average|typically|~)[ \t]*)*\$[ \t]?(\d[\d,]*(?:\.\d\d)?)(?![\d,])", re.I)
_RANGE_SKIP = re.compile(r"deposit|one[- ]time|set[- ]?up|application|move[- ]in|\blate\b|\bpets?\b|parking|insurance|\brent\b|\bfees?\b|quarter|annual|yearly|\byear\b|every|bi-?monthly|\bflat\b|included|covered|provided|landlord pays|owner pays", re.I)


def _util_range(utext: str) -> dict[str, Any] | None:
    """Cycle 23: a utilities figure written as a range ("Typical total $135-$160 per month", "Utilities average $135 to $160 a month") or as a plain
    "total" line under a renter-pays line ("Tenant pays all utilities. Typical total $135"). The higher figure is the one counted.
    Returns {"amount": high, "low": low or None, "names": [...], "quote": "..."} or None."""
    prev = ""
    for clause in re.split(r"\n|;|\.(?=\s|$)", utext.lower()):
        before, prev = prev, clause
        if not clause.strip() or _RANGE_SKIP.search(clause) or _NOT_UTILITY_LINE.search(clause):
            continue
        names = [w for w in _ordered_utilities(re.findall(_ROLE_WORD, clause)).split(", ") if w and w != "cable"]
        has_util = bool(re.search(r"\butilit(?:y|ies)\b", clause)) or bool(names)
        rm = _RANGE_FIG.search(clause)
        if rm:
            lo, hi = float(rm.group(1).replace(",", "")), float(rm.group(2).replace(",", ""))
            if not (has_util or _TOTAL_FIG.search(clause[:rm.end()] + "$0")) and not re.search(r"\btotal\b", clause):
                continue
            if 10 <= lo < hi <= 3000 and hi <= 4 * lo:
                return {"amount": hi, "low": lo, "names": names if not re.search(r"\ball\b[^.\n]{0,12}utilit", clause) else [], "quote": " ".join(clause.split())}
            continue
        tm = _TOTAL_FIG.search(clause)
        if tm and not has_util and re.search(r"\b(?:tenants?|residents?|renters?|you)\b[^.\n]{0,40}\b(?:pays?|responsible)\b[^.\n]{0,40}\butilit|\butilit\w*[^.\n]{0,30}\b(?:tenants?|residents?|renters?|you)\b", before):
            amt = float(tm.group(1).replace(",", ""))
            if 10 <= amt <= 3000 and not _RANGE_SKIP.search(before.split("utilit")[0] if False else ""):
                return {"amount": amt, "low": None, "names": [], "quote": " ".join(clause.split())}
    return None


def _utility_component_numbers(text: str, skip_internet: bool = False) -> set[float]:
    """The single utility figures a utilities estimate was built from (each rough figure, a quarterly bill and its monthly share).
    With ``skip_internet`` an internet-only figure is left out (the fee readers own a required internet fee)."""
    utext = _util_text(_tidy(text or ""))
    nums = {float(i["amount"]) for i in _estimate_items(utext) if not (skip_internet and set(i.get("names") or []) == {"internet"})}
    rng = _util_range(utext)
    if rng:
        nums |= {rng["amount"]} | ({rng["low"]} if rng["low"] else set())
    if not skip_internet:
        nums |= {float(b["amount"]) for b in _internet_bills(_tidy(text or ""))}  # cycle 24: a priced internet bill the renter pays is part of the estimate
    per = _periodic_named(utext)
    if per:
        nums |= {per["raw"], per["monthly"]}
    for c in _periodic_components(utext):
        nums |= {c["raw"], c["monthly"]}
    gen = _util_general(utext, _pipe_list(text or ""))  # cycle 19: every figure the general reader counted is a part of the estimate, never "not counted"
    if gen and not gen["conflict"]:
        for it in gen["items"]:
            if skip_internet and set(it["names"]) == {"internet"}:
                continue
            nums |= {float(it["raw"]), float(it["monthly"])}
        nums |= {float(f) for f in gen.get("restated") or []}
        if gen.get("stated_total"):
            nums.add(float(gen["stated_total"]))
        nums |= {float(pk["amount"]) for pk in gen.get("peaks") or []}
        for sz in gen.get("seasonal") or []:
            nums |= {float(f) for f in sz["figures"]}  # both seasonal figures are quoted in the estimate's note, so neither is "not counted"
    return nums


_PERIODIC_NAMED = re.compile(r"\b(quarterly|annual|yearly)[ \t]+((?:\b(?:" + _ROLE_WORD + r")\b[ \t]*(?:,|/|&|and|\+)?[ \t]*){1,4})[ \t]*(?:bill|bills|charge|charges|cost|costs|fee)s?[ \t]*(?:is|are|of|:|-)?[ \t]*(?:" + _APPROX_ANY + r"[ \t]*)?\$[ \t]*(\d[\d,]{1,5}(?:\.\d\d)?)(?![\d,])", re.I)
_PAYER_CUE = re.compile(r"\b(?:billed|charged|passed)[ \t]+(?:back|through|to)\b|\bbilled\b|\b(?:tenants?|residents?|renters?|you)\b[^.\n;]{0,20}\b(?:pays?|responsible)\b|\bpaid[ \t]+by[ \t]+(?:the[ \t]+)?(?:tenants?|residents?|renters?)\b", re.I)


_PERIODIC_BILL = re.compile(r"\b((?:\b(?:" + _ROLE_WORD + r")\b[ \t]*(?:,|/|&|and|\+)?[ \t]*){1,4})[ \t]*bills?\b[^$.\n;]{0,40}?\$[ \t]*(\d[\d,]{1,5}(?:\.\d\d)?)[ \t]*(?:a|per|/|each|every)[ \t]*(quarter|qtr|year|yr)\b", re.I)
_PASSED_THROUGH = re.compile(r"\b(?:(?:quarterly|monthly|annual\w*|yearly)[ \t]+)?((?:\b(?:" + _ROLE_WORD + r")\b[ \t]*(?:,|/|&|and|\+)?[ \t]*){1,4})[ \t]*bills?\b[^$.\n;]{0,30}?\b(?:passed[ \t]+(?:through|on|along)|billed[ \t]+back|charged[ \t]+back|billed[ \t]+to|charged[ \t]+to)\b", re.I)


def _passed_through(text: str) -> list[str]:
    """Utilities whose bill the listing says is passed through to the renter with no amount ("Quarterly water bill passed through")."""
    out: list[str] = []
    for clause in re.split(r"\n|;|\.(?=\s|$)", text.lower()):
        if "$" in clause or re.search(r"\b(?:landlord|owner)\s+pays\b|\bincluded\b", clause):
            continue
        m = _PASSED_THROUGH.search(clause)
        if m:
            out += [w for w in _ordered_utilities(re.findall(_ROLE_WORD, m.group(1))).split(", ") if w and w != "cable"]
    return [w for w in _ordered_utilities(out).split(", ") if w]


def _periodic_named(text: str) -> dict[str, Any] | None:
    """"Quarterly water bill of $135 billed back" -> {"names": ["water"], "monthly": 45.0, "raw": 135.0, "unit": "quarter"}: a bill for named
    utilities that covers more than a month, only when the same line says the renter pays it. None otherwise."""
    for clause in re.split(r"\n|;|\.(?=\s|$)", text):
        if re.search(r"deposit|one[- ]time|set[- ]?up|\b(?:included|landlord pays|owner pays)\b", clause, re.I):
            continue
        m = _PERIODIC_NAMED.search(clause)
        if not m:
            # "Water bill is quarterly, usually $120 a quarter": a bill with an amount the listing gives for the renter's costs
            mb = _PERIODIC_BILL.search(clause)
            if mb:
                div, unit = (12, "year") if mb.group(3).lower() in ("year", "yr") else (3, "quarter")
                raw = float(mb.group(2).replace(",", ""))
                names = [w for w in _ordered_utilities(re.findall(_ROLE_WORD, mb.group(1).lower())).split(", ") if w and w != "cable"]
                if names and 10 <= raw / div <= 2000:
                    return {"names": names, "monthly": round(raw / div, 2), "raw": raw, "unit": unit}
            continue
        if not _PAYER_CUE.search(clause):
            continue
        div, unit = (12, "year") if m.group(1).lower() in ("annual", "yearly") else (3, "quarter")
        raw = float(m.group(3).replace(",", ""))
        names = [w for w in _ordered_utilities(re.findall(_ROLE_WORD, m.group(2).lower())).split(", ") if w and w != "cable"]
        if names and 10 <= raw / div <= 2000:
            return {"names": names, "monthly": round(raw / div, 2), "raw": raw, "unit": unit}
    return None


_PERIOD_WORD = re.compile(r"\bquarterly\b|\bper[ \t]+quarter\b|\ba[ \t]+quarter\b|\bevery[ \t]+(?:three|3)[ \t]+months\b|\bannual(?:ly)?\b|\byearly\b|\bper[ \t]+year\b|\ba[ \t]+year\b|/[ \t]*(?:qtr|quarter|yr)\b", re.I)
_PERIOD_LEAD = re.compile(r"\b(?:quarterly|annual|yearly)[ \t]+$", re.I)
_PERIOD_TAIL = re.compile(r"[ \t,:]*(?:bills?[ \t]*)?(?:(?:is|are)[ \t]+)?(?:(?:billed|charged|paid|passed|due|comes?)[ \t]*(?:through|back|on|along|to[ \t]+(?:you|tenants?|the[ \t]+tenants?))?[ \t,]*)?(?:quarterly|every|per[ \t]+quarter|annual|yearly)", re.I)


_ROLE_BILL_LIST = re.compile(r"\b(?:" + _ROLE_WORD + r")\b(?:[ \t]*(?:,|/|&|\+|\band\b)[ \t]*\b(?:" + _ROLE_WORD + r")\b)*", re.I)


def _periodic_components(text: str) -> list[dict[str, Any]]:
    """Every bill for named utilities that covers more than a month and that the listing says the renter pays, with its amount:
    "Water billed quarterly, about $96 per quarter" and "Quarterly water bill passed through, around $150" ->
    {"names": ["water"], "monthly": 32.0, "raw": 96.0, "unit": "quarter"}. A sentence that says the landlord pays it, or that
    it is included, is not read."""
    out: list[dict[str, Any]] = []
    for sent in re.split(r"\n|;|\.(?=\s|$)", text.lower()):
        if re.search(r"deposit|one[- ]time|set[- ]?up|\b(?:landlord|owner|management)[ \t]+pays?\b|\bincluded\b|\bfees?\b", sent) or not _PERIOD_WORD.search(sent):
            continue
        if not (_PAYER_CUE.search(sent) or re.search(r"\bbills?\b", sent)):
            continue
        for lm in _ROLE_BILL_LIST.finditer(sent):
            if not (_PERIOD_TAIL.match(sent[lm.end():lm.end() + 45]) or _PERIOD_LEAD.search(sent[max(0, lm.start() - 12):lm.start()])):
                continue
            am = re.search(r"\$[ \t]*(\d[\d,]{1,5}(?:\.\d\d)?)(?![\d,])", sent[lm.end():])
            if not am:
                continue
            raw = float(am.group(1).replace(",", ""))
            tail = sent[lm.end() + am.end():lm.end() + am.end() + 25]
            div = _period_divisor(tail, sent)
            names = [w for w in _ordered_utilities(re.findall(_ROLE_WORD, lm.group(0))).split(", ") if w and w not in ("cable", "internet", "wifi", "wi-fi")]
            if names and div > 1 and 10 <= raw / div <= 2000 and not any(set(names) & set(c["names"]) for c in out):
                out.append({"names": names, "monthly": round(raw / div, 2), "raw": raw, "unit": "quarter" if div == 3 else "year"})
            break
    return out


_UTIL_TRACE: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar("util_trace", default=None)


@functools.lru_cache(maxsize=256)
def _util_read(text: str) -> tuple[float | None, tuple[str, ...]]:
    """What parse_listing counted for utilities in this listing text: (monthly amount or None, the utilities that amount covers).
    The saved-place checks use it so "from the listing" always means what the reader itself counted."""
    token = _UTIL_TRACE.set(None)
    try:
        got = parse_listing(text, "")
        trace = _UTIL_TRACE.get() or {}
        amt = got.get("utilities_estimate")
        return (float(amt) if isinstance(amt, (int, float)) and not isinstance(amt, bool) else None), tuple(trace.get("names") or ())
    finally:
        _UTIL_TRACE.reset(token)


_FEE_PAID_TO_LANDLORD = (
    re.compile(r"\$[ \t]*(\d{2,4}(?:\.\d\d)?)(?![\d,])[ \t]*(?:/[ \t]*mo(?:nth)?\b|per[ \t]+month|a[ \t]+month|monthly|each[ \t]+month)?[^.\n;$]{0,30}\b(?:paid|billed|charged|due|payable|owed|collected|passed[ \t]+on)[ \t]+(?:by|to)[ \t]+(?:the[ \t]+)?(?:tenants?|renters?|residents?|you|landlord|owner|management)\b", re.I),
    re.compile(r"\b(?:tenants?|renters?|residents?|you)[ \t]+(?:pays?|reimburse\w*|owes?)[ \t]+(?:the[ \t]+)?(?:landlord|owner|management)[^.\n;$]{0,25}\$[ \t]*(\d{2,4}(?:\.\d\d)?)(?![\d,])", re.I),
)


def _util_fee_conflict(text: str) -> float | None:
    """"All utilities included, total $180 per month paid by tenant to landlord": the same line says everything is included and
    that the renter pays a monthly amount for the utilities. The amount, or None when no line says that."""
    for sent in re.split(r"\n|;|\.(?=\s|$)", text.lower()):
        if "utilit" not in sent or re.search(r"deposit|one[- ]time|set[- ]?up|\bparking\b|\bpets?\b", sent):
            continue
        for pat in _FEE_PAID_TO_LANDLORD:
            m = pat.search(sent)
            if m and 10 <= float(m.group(1)) <= 2000:
                return float(m.group(1))
    return None


def _estimate_plan(items: list[dict[str, Any]], skip: set[str] | None = None) -> dict[str, Any] | None:
    """The one monthly figure to count from the listing's rough figures, never the lower of two that conflict. A figure for the
    whole bill that covers more wins over figures for single utilities (unless those add up to more); figures for different
    utilities add up; figures for the same utility keep the higher. Returns {"amount", "names", "total", "dropped"} or None.
    ``skip``: utilities another amount already prices (figures for those are left out)."""
    skip = skip or set()
    named = [i for i in items if not i["total"] and not (set(i["names"]) & skip)]
    totals = [] if skip else [i for i in items if i["total"]]
    kept: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i in sorted(named, key=lambda i: (-len(i["names"]), -i["amount"])):
        if seen & set(i["names"]):
            continue
        kept.append(i)
        seen |= set(i["names"])
    named_sum = sum(i["amount"] for i in kept)
    best_total = max(totals, key=lambda i: i["amount"]) if totals else None
    if best_total and best_total["amount"] >= named_sum:
        return {"amount": best_total["amount"], "names": [], "total": True, "dropped": [i for i in items if i is not best_total], "kept": []}
    if not kept:
        return None
    names = [w for i in kept for w in i["names"]]
    return {"amount": round(named_sum, 2), "names": names, "total": False, "dropped": [i for i in items if i not in kept], "kept": kept}


def _estimate_plan_for(utext: str, skip: set[str] | None = None) -> dict[str, Any] | None:
    items = _estimate_items(utext)
    return _estimate_plan(items, skip) if items else None


def listing_estimate_names(text: str) -> list[str]:
    """Public: the utilities a listing's own figures cover, besides what a billed-back or flat amount covers (see _listing_estimate_names),
    plus the ones the reader added in from other figures (quarterly bills and figures for other utilities)."""
    base = _listing_estimate_names(text)
    try:
        traced = list(_util_read(_tidy(text or ""))[1])
    except Exception:
        traced = []
    more = [w for w in traced if w not in base]
    names = base + more
    if "gas" in names and "heat" not in names and _HEAT_IS_GAS.search(_tidy(text or "")):
        names.append("heat")  # "Heat is gas": the gas bill is the heating bill
    return names


def _listing_estimate_names(text: str) -> list[str]:
    """Public: the utilities that a rough monthly figure in the listing covers ("water, sewer" for "Water/sewer approximate $60"),
    besides any a billed-back or flat amount covers. Empty when the figure covers the whole bill or there is none. Never raises."""
    try:
        utext = _util_text(_tidy(text or ""))
        billed = _billed_back(utext)
        if billed:
            skip = {w.strip() for w in billed[0].split(",") if w.strip()}
            plan = _estimate_plan_for(utext, skip) if skip else None
        else:
            roles = _utility_roles(utext)
            plan = None if roles["amount"] or roles["billed"] else _estimate_plan_for(utext)
        if not plan and not billed:
            named_periodic = _periodic_named(utext)
            if named_periodic and not roles["amount"] and not roles["billed"]:
                return list(named_periodic["names"])
        return list(plan["names"]) if plan else []
    except Exception:
        return []


_PERIODIC_UTIL = (
    re.compile(r"\b(quarterly|annual|yearly)[ \t]+utilit(?:y|ies)(?:[ \t]+(?:bill|bills|cost|costs|charge|estimate|average|total))?[ \t]*(?:is|are|of|:|-)?[ \t]*(?:" + _APPROX_ANY + r"[ \t]*)?\$[ \t]*(\d[\d,]{1,5}(?:\.\d\d)?)(?![\d,])", re.I),
    re.compile(r"\butilit(?:y|ies)(?:[ \t]+(?:bill|bills|cost|costs|charge|estimate|average|total))?[ \t]*(?:is|are|of|:|-)?[ \t]*(?:" + _APPROX_ANY + r"[ \t]*)?\$[ \t]*(\d[\d,]{1,5}(?:\.\d\d)?)[ \t]*(?:/|per|a|each)[ \t]*(quarter|qtr|year|yr)\b", re.I),
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
    re.compile(r"\butilit(?:y|ies)\b[ \t]*(?:are[ \t]+|is[ \t]+)?(?:extra|additional|separate|not included|on top|billed separately)?[ \t,:\-]*(?:est\.?|estimated|approx\.?|approximately|about|around|roughly|~|avg\.?|average)[ \t]*\$?[ \t]*(\d{2,4}(?:\.\d\d)?)[ \t]*(?:/|per|a|each)[ \t]*(?:mo|month)\b", re.I),
    re.compile(r"\butilit(?:y|ies)\b[ \t]*(?:are[ \t]+|is[ \t]+)?(?:extra|additional|separate|not included|on top)\b[ \t,:\-]*(?:(?:est\.?|estimated|approx\.?|approximately|about|around|roughly|~|avg\.?|average)[ \t]*)?\$[ \t]*(\d{2,4}(?:\.\d\d)?)[ \t]*(?:/|per|a|each)[ \t]*(?:mo|month)\b", re.I),
)


_UTIL_APPROX_WORD = r"(?:est\.?|estimated|approx\.?|approximately|about|around|roughly|~|avg\.?|average)"
_UTIL_AMOUNT_FIRST = re.compile(r"(?<![\w$])(?:" + _UTIL_APPROX_WORD + r"[ \t]*)?\$[ \t]*(\d{2,4}(?:\.\d\d)?)[ \t]*(?:/[ \t]*mo(?:nth)?|per[ \t]+month|a[ \t]+month|monthly|each[ \t]+month)?[ \t]*(?:(?:total|combined|in[ \t]+all|for)[ \t]+)?(?:all[ \t]+(?:the[ \t]+)?|the[ \t]+|your[ \t]+)?utilities\b(?![ \t]*(?:deposit|fees?|included|package|plan|bundle|charge|program|account|allowance|\())", re.I)
_UTIL_APPROX_NOUNIT = re.compile(r"\butilit(?:y|ies)\b[ \t]*(?:are[ \t]+|is[ \t]+)?(?:extra|additional|separate|not included|on top|billed[ \t]+back|billed[ \t]+separately|passed[ \t]+through)?[ \t,:\-(]*(?:(?:total|combined|overall)[ \t]+)?" + _UTIL_APPROX_WORD
                                 + r"[ \t]*(?:(?:total|combined|overall)[ \t]+)?\$?[ \t]*(\d{2,4}(?:\.\d\d)?)(?![\d,])(?![ \t]*(?:/[ \t]*(?:yr|year|qtr|quarter)|per[ \t]+(?:yr|year|quarter)|a[ \t]+(?:year|quarter)|quarterly|annual|yearly|deposit|fee))", re.I)
_UTIL_SAYS_PAYS = re.compile(r"\b(?:tenants?|residents?|renters?|you)\b[^.\n;]{0,25}\b(?:pays?|responsible|covers?)\b[^.\n;]{0,20}\butilit(?:y|ies)\b|\butilit(?:y|ies)\b[^.\n;]{0,25}\b(?:extra|additional|separate|not included|on top|tenant|resident)\b", re.I)
_UTIL_NEXT_AMOUNT = re.compile(r"^[ \t]*(?:about|approx\.?|approximately|around|roughly|est\.?|estimated|~|avg\.?|average|typically|usually)[ \t]*\$[ \t]*(\d{2,4}(?:\.\d\d)?)[ \t]*(?:/[ \t]*mo(?:nth)?|per[ \t]+month|a[ \t]+month|monthly|each[ \t]+month)\b", re.I)


_TENANT_WORD_U = r"(?:tenants?|residents?|renters?|lessees?|you)"
_ALL_UTIL_PAID_BY = re.compile(
    r"\b(?:all|every)[ \t]+(?:the[ \t]+)?utilit(?:y|ies)(?P<br>[ \t]*\([^()\n]{0,50}\))?(?:[ \t]+(?:are[ \t]+|is[ \t]+|to[ \t]+be[ \t]+|will[ \t]+be[ \t]+)?(?:paid|covered|billed|handled|arranged|set[ \t]+up|provided|the[ \t]+responsibility|responsibility|expense|cost)(?:[ \t]+(?:of|by|to|for|on))?[ \t]+(?:the[ \t]+)?" + _TENANT_WORD_U + r"\b"
    r"|[ \t]+(?:are|is)[ \t]+(?:the[ \t]+)?(?:tenants?|residents?|renters?|lessees?)(?:'s|s')?[ \t]+(?:responsibility|expense|cost|bill|account)\b"
    r"|[ \t]+on[ \t]+(?:the[ \t]+)?" + _TENANT_WORD_U + r"\b"
    r"|[ \t]*[:\-\u2013][ \t]*(?:the[ \t]+)?(?:tenants?|residents?|renters?|lessees?)\b(?![ \t]+(?:pays?|paid)\b[^.\n;]{0,12}\b(?:none|nothing)\b))"
    r"|\b(?:tenants?|residents?|renters?)(?:'s|s')?[- ](?:paid|responsible)[ \t]+(?:for[ \t]+)?(?:all|every)[ \t]+(?:the[ \t]+)?utilit(?:y|ies)\b"
    r"|\butilit(?:y|ies)[ \t]*:?[ \t]*(?:all|every)[ \t]+(?:are[ \t]+)?paid[ \t]+(?:of|by)[ \t]+(?:the[ \t]+)?" + _TENANT_WORD_U + r"\b", re.I)


_UTIL_PACKAGE = re.compile(r"\butilit(?:y|ies)[ \t]+(?:package|bundle|plan|program|fee|charge)s?[^.\n;|]*?\$[ \t]?\d[^.\n;|]*", re.I)
_FLAT_NAMES = r"(?:(?:hot[ \t]+water|water|sewer|sewage|trash(?:[ \t]+removal)?|garbage|gas|electric(?:ity)?|heat(?:ing)?)(?:[ \t]*(?:,|/|&|\+|\band\b)[ \t]*(?:hot[ \t]+water|water|sewer|sewage|trash(?:[ \t]+removal)?|garbage|gas|electric(?:ity)?|heat(?:ing)?))*)"
_FLAT_AMT = r"\$[ \t]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?"
_PERIOD_U = r"(?:[ \t]*(?:/[ \t]*mo(?:nth)?\b|per[ \t]+month|a[ \t]+month|monthly|each[ \t]+month))"
_FLAT_FORMS = (
    # "Water, sewer and trash (flat $75)" / "(flat fee $75/mo)" / "(about $75 flat)"
    re.compile(r"(?<![\w/])(?P<n>" + _FLAT_NAMES + r")[ \t]*\([ \t]*(?:a[ \t]+)?(?:flat(?:[ \t]+(?:fee|rate|charge))?[ \t]*[:\-]?[ \t]*(?P<a>" + _FLAT_AMT + r")|(?P<b>" + _FLAT_AMT + r")[ \t]*flat)" + _PERIOD_U + r"?[ \t]*\)", re.I),
    # "Water and trash only $60 flat" / "Water and trash only: $60/mo" / "Water and trash: $60 flat" (the names are the only ones the figure covers)
    re.compile(r"(?<![\w/])(?P<n>" + _FLAT_NAMES + r")[ \t]+only[ \t]*[:\-]?[ \t]*(?:is[ \t]+)?(?:flat[ \t]+)?(?P<a>" + _FLAT_AMT + r")(?:" + _PERIOD_U + r"|[ \t]*flat\b(?:[ \t]+(?:fee|rate))?)", re.I),
    re.compile(r"(?<![\w/])(?P<n>" + _FLAT_NAMES + r")[ \t]*:[ \t]*(?P<a>" + _FLAT_AMT + r")[ \t]*flat\b(?:[ \t]+(?:fee|rate))?", re.I),
)


def _flat_forms(text: str) -> str:
    """Cycle 27: one written form for a flat figure that covers named utilities: "Water, sewer and trash (flat $75)", "Water and trash only $60 flat" and
    "Water and trash: $60 flat" all become "Water, sewer and trash flat $75/month", which every reader already understands. Items with a figure that
    names a payer or says included are left alone."""
    for pat in _FLAT_FORMS:
        def fix(m: re.Match[str]) -> str:
            if re.search(r"\b(?:included|incl|free|no charge)\b", m.string[m.end():m.end() + 14], re.I):
                return m.group(0)
            amt = (m.group("a") or m.group("b")).replace(" ", "")
            return f"{m.group('n')} flat {amt}/month"
        text = pat.sub(fix, text)
    return text


_HEAT_GAS_GROUP = re.compile(r"\b(?:heat(?:ing)?[ \t]*(?:&|and|/|\+)[ \t]*gas|gas[ \t]*(?:&|and|/|\+)[ \t]*heat(?:ing)?|gas[ \t]+heat(?:ing)?)\b", re.I)
_TRASH_FEE_RE = re.compile(r"\b(?:valet[ \t-]*(?:trash|waste)|trash[ \t-]*valet|trash[ \t]+removal|trash[ \t]+(?:pick-?up|service|fee|charge)|garbage[ \t]+(?:removal|pick-?up|service|fee|charge)|waste[ \t]+(?:removal|service))(?:[ \t]+(?:fee|service|charge))?[ \t]*[:\-=]?[ \t]*\$[ \t]?(\d{1,4}(?:\.\d\d)?)", re.I)


_IN_TRASH_CHECK: contextvars.ContextVar[bool] = contextvars.ContextVar("in_trash_check", default=False)


def _trash_fee_covers_trash(text: str, out: dict[str, Any]) -> None:
    """Cycle 27: a trash, valet trash or trash removal fee that is counted in other monthly fees is the trash bill: trash is not also an unknown utility."""
    if _IN_TRASH_CHECK.get():
        return  # cycle 27 join: the estimate lookup below re-reads the listing; that inner read must not start this check again (it recursed to the limit)
    token = _IN_TRASH_CHECK.set(True)
    try:
        _trash_fee_covers_trash_inner(text, out)
    finally:
        _IN_TRASH_CHECK.reset(token)


def _trash_fee_covers_trash_inner(text: str, out: dict[str, Any]) -> None:
    pays = [w.strip() for w in str(out.get("tenant_pays") or "").split(",") if w.strip()]
    fees = out.get("other_monthly_fees")
    if "trash" not in pays or not isinstance(fees, (int, float)) or isinstance(fees, bool):
        return
    covered = set(_try(lambda: listing_billed_names(text)) or []) | set(_try(lambda: listing_estimate_names(text)) or [])
    if "trash" in covered or re.search(r"\b(?:rubs|billed[ \t]+back|passed[ \t]+through)\b", text, re.I):
        return  # a utility bill for the trash exists too: the fee is a service, the bill stays in the estimate
    for m in _TRASH_FEE_RE.finditer(text):
        amt = float(m.group(1))
        if 0 < amt <= float(fees) + 0.01 and not re.search(r"\b(?:optional|available|if you|on request)\b", text[max(0, m.start() - 20):m.end() + 25], re.I):
            rest = [w for w in pays if w != "trash"]
            if rest:
                out["tenant_pays"] = ", ".join(rest)
            else:
                out.pop("tenant_pays", None)
            return


_STD_FIVE = ("electric", "gas", "water", "sewer", "trash")
_EST_WORDS = r"(?:(?:est(?:imated|imate)?|approx(?:imately|imate)?|about|around|roughly|avg|average|approximately|~)\.?[ \t]*:?[ \t]*)"
_MONEY_U = r"\$[ \t]?\d[\d,]*(?:\.\d\d)?(?:[ \t]*(?:/[ \t]*mo(?:nth)?|per[ \t]+month|a[ \t]+month|monthly|total|combined))*"
_EXCEPT_W = r"(?:except(?:[ \t]+for)?|other[ \t]+than|besides)"
_ALL_EXCEPT_EST = re.compile(
    r"(?P<head>\b(?:all|everything)[ \t]+(?:(?:the[ \t]+)?utilit(?:y|ies)[ \t]+)?" + _EXCEPT_W + r"[ \t]+(?P<names>" + _ROLE_LIST_RAW + r"))"
    r"(?P<sep>[ \t]*[,;(\-\u2013:]?[ \t]*)(?P<est>" + _EST_WORDS + r"?" + _MONEY_U + r")(?P<close>[ \t]*\))?(?![ \t]*(?:for|covering|covers)\b)", re.I)
_EST_FOR_ALL_EXCEPT = re.compile(
    r"(?P<est>" + _EST_WORDS + r"?" + _MONEY_U + r")[ \t]*(?:for|covering|on)[ \t]+(?P<head>(?:all|everything)[ \t]+(?:(?:the[ \t]+)?utilit(?:y|ies)[ \t]+)?" + _EXCEPT_W + r"[ \t]+(?P<names>" + _ROLE_LIST_RAW + r"))", re.I)


def _canon_util(w: str) -> str:
    return {"garbage": "trash", "trash removal": "trash", "sewage": "sewer", "electricity": "electric", "hot water": "water"}.get(w, w)


def _all_except_estimate(text: str) -> str:
    """Cycle 27: "All utilities except trash, estimated $140" (payer words or none) is an estimate for everything BUT the trash: it is written out
    as "...except trash. Estimated $140/month for electric, gas, water, sewer." so no reader gives the figure to the left-out utility.
    A line that says the landlord or "included" is the other way round and is left alone."""
    def build(names_raw: str, est: str) -> tuple[list[str], str]:
        left = [_canon_util(w) for w in re.findall(_ROLE_WORD, names_raw.lower())]
        rest = [w for w in _STD_FIVE if w not in left]
        amount = re.search(r"\$[ \t]?\d[\d,]*(?:\.\d\d)?", est)
        return rest, (amount.group(0).replace(" ", "") if amount else est)

    def bad_before(m: re.Match[str]) -> bool:
        line_start = max(m.string.rfind("\n", 0, m.start()) + 1, m.string.rfind(". ", 0, m.start()) + 2, 0)
        before = m.string[line_start:m.start("head")]
        return bool(re.search(r"\b(?:landlord|owner|management|included|include|includes|covered|covers|provided|provides|pays?[ \t]+all[ \t]+utilit)\b", before[-60:], re.I)
                    and not re.search(r"\b(?:tenants?|residents?|renters?|you)[ \t]+(?:pays?|(?:is|are)[ \t]+responsible|responsible)\b[^.\n]*$", before, re.I)) \
            or bool(re.search(r"\b(?:included|covered|provided)\b", m.group("names") + m.string[m.end("names"):m.end("names") + 12], re.I))

    def done(m: re.Match[str], rest: list[str], est: str, pre: str) -> str:
        dot = "" if m.string[m.end():m.end() + 1] == "." else "."
        return f"{pre}{m.group('head')}. Estimated {est}/month for {', '.join(rest)}{dot}"

    def one(m: re.Match[str]) -> str:
        if bad_before(m):
            return m.group(0)
        rest, est = build(m.group("names"), m.group("est"))
        if not rest:
            return m.group(0)
        pre = "" if re.search(r"\b(?:tenants?|residents?|renters?|lessees?|you)\b[^.\n]*$", m.string[max(0, m.start("head") - 60):m.start("head")], re.I) else "Tenant pays "
        return done(m, rest, est, pre)

    def two(m: re.Match[str]) -> str:
        if bad_before(m):
            return m.group(0)
        rest, est = build(m.group("names"), m.group("est"))
        return m.group(0) if not rest else done(m, rest, est, "Tenant pays ")

    before_rewrite = text
    text = _EST_FOR_ALL_EXCEPT.sub(two, text)
    text = _ALL_EXCEPT_EST.sub(one, text)
    if text != before_rewrite:
        # "...except trash, estimated $120. Trash $15.": the left-out utility's own figure is a flat monthly bill, counted for that utility
        left_all = {_canon_util(w) for m in re.finditer(r"\b(?:except(?:[ \t]+for)?|other[ \t]+than|besides)[ \t]+(" + _ROLE_LIST_RAW + r")", text, re.I) for w in re.findall(_ROLE_WORD, m.group(1).lower())}
        for name in sorted(left_all):
            word = r"(?:trash(?:[ \t]+removal)?|garbage)" if name == "trash" else name
            text = re.sub(r"(?<!fees: )(?<!fee: )(?<!charges: )(?<![\w$/])(?P<n>" + word + r")(?:[ \t]+(?:is|are|costs?|fee))?[ \t]*[:\-]?[ \t]*(?P<amt>\$(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?)(?![\d/]|\.\d|[ \t]*(?:/|per\b|a[ \t]+month|monthly|flat|total|each|one|once|deposit|set))",
                          r"\g<n> \g<amt>/month flat", text, flags=re.I)
    # "Tenant pays: electric, gas, water (approx $80 total, all except trash)": the bracket repeats which one is left out, it is not a utility the figure covers
    text = re.sub(r"(\b(?:electric|gas|water|sewer|heat)\b[^.\n;()]{0,40}\([^()\n]*\$[^()\n]*?)[ \t]*[,;\-\u2013][ \t]*(?:all|everything)[ \t]+(?:(?:the[ \t]+)?utilit(?:y|ies)[ \t]+)?" + _EXCEPT_W + r"[ \t]+(?:" + _ROLE_LIST_RAW + r")[ \t]*\)", r"\1)", text, flags=re.I)
    return text


def _say_all_utilities(text: str) -> str:
    """"Resident pays all except trash" -> "Resident pays all utilities except trash" so every reader sees the same words.
    Cycle 27: "all utilities paid by tenant", "all utilities: tenant", "tenant-paid all utilities" are "Tenant pays all utilities" in every word order."""
    def keep_net(listed: str) -> str:
        net = [w for w in re.findall(_ROLE_WORD, listed.lower()) if w in ("internet", "wifi", "wi-fi", "cable")]
        return (" and " + ", ".join(dict.fromkeys(net))) if net else ""

    def paid_by(m: re.Match[str]) -> str:
        br = m.groupdict().get("br") or ""
        if re.search(r"\b(?:including|incl\.?|inc\.|such as|like)\b", br, re.I) or not br:
            return "Tenant pays all utilities" + keep_net(br)
        return "Tenant pays all utilities" + br  # "All utilities (electric, gas, water) paid by tenant": a plain list is what is meant
    text = _ALL_UTIL_PAID_BY.sub(paid_by, text)
    # "Tenant pays all utilities including heat and trash, about $200": the names are examples inside "all", never the only ones the figure covers
    text = re.sub(r"(\b(?:tenants?|residents?|renters?|lessees?|you)[ \t]+(?:pays?|(?:is|are)[ \t]+responsible[ \t]+for|responsible[ \t]+for|will[ \t]+pay)[ \t]+(?:for[ \t]+)?all[ \t]+(?:the[ \t]+)?utilit(?:y|ies))[ \t]*,?[ \t]*\(?[ \t]*(?:including|incl\.?|inc\.)[ \t]+(" + _ROLE_LIST_RAW + r")[ \t]*\)?", lambda m: m.group(1) + keep_net(m.group(2)), text, flags=re.I)
    text = _all_except_estimate(text)
    return re.sub(r"\b((?:tenants?|residents?|renters?|lessees?|you)[ \t]+(?:pays?|are[ \t]+responsible[ \t]+for|is[ \t]+responsible[ \t]+for|responsible[ \t]+for|will[ \t]+pay|must[ \t]+pay)[ \t]+(?:for[ \t]+)?)(?:everything|all)(?=[ \t]+(?:except(?:[ \t]+for)?|other[ \t]+than|besides)\b)", r"\1all utilities", text, flags=re.I)


def _utilities_extra_amount(text: str) -> float | None:
    """"Utilities extra approx $150 per month": the listing's own monthly figure for utilities, or None. Also the sentence that
    follows a utilities line ("Tenant pays all utilities. Approx $180/month") and an approximate amount with no unit
    ("Utilities extra approx $150"). The amount must sit in a line about utilities, never a parking, pet or fee line."""
    text = _say_all_utilities(text)
    for pat in _UTIL_EXTRA_AMOUNT + (_UTIL_APPROX_NOUNIT,):
        m = pat.search(text)
        if m and 10 <= float(m.group(1)) <= 2000:
            return float(m.group(1))
    for clause in re.split(r"\n|;|\.(?=\s|$)", text):
        m = _UTIL_AMOUNT_FIRST.search(clause)  # cycle 22: "Approx $175/mo all utilities"
        if not m or not 10 <= float(m.group(1)) <= 2000 or _NOT_UTILITY_LINE.search(clause) or re.search(r"\b(?:\d[ \t]*(?:bed|br|bd|ba|bath)\w*|studio|sq[ \t]*ft|sqft)\b", clause, re.I):
            continue
        approx = m.group(0).lower().lstrip().startswith(("approx", "about", "around", "roughly", "~", "est", "avg", "average"))
        if approx or (float(m.group(1)) <= 600 and re.search(r"/[ \t]*mo|per[ \t]+month|a[ \t]+month|monthly", m.group(0), re.I)):  # a rent-sized figure with no "about" is not a utilities total
            return float(m.group(1))
    parts = re.split(r"(?<=[.!\n;])[ \t]*", text)
    for i in range(len(parts) - 1):
        if _UTIL_SAYS_PAYS.search(parts[i]) and not re.search(r"\$\s?\d", parts[i]) and not _NOT_UTILITY_LINE.search(parts[i]):
            m = _UTIL_NEXT_AMOUNT.match(re.sub(r"^[-*\u2022\u2013\u2014][ \t]+", "", parts[i + 1]))
            if m and 10 <= float(m.group(1)) <= 2000:
                return float(m.group(1))
    return None


def listing_utilities_flat_fee(text: str) -> bool:
    """Public: True when the listing's utilities amount is a flat monthly fee ("Water/sewer/trash $65/mo flat"), not a bill passed back."""
    try:
        text = _util_text(_tidy(text or ""))
        billed = _billed_back(text)
        if billed and billed[0] and (_estimate_plan_for(text, {w.strip() for w in billed[0].split(",") if w.strip()}) or {}).get("names"):
            return False  # the amount also holds a rough figure for other utilities, so it is not only a flat fee
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


_HOA_LABEL = r"(?:hoa|h\.o\.a\.|association|condo[ \t]+(?:fees?|dues|assessments?)|(?:monthly|building)[ \t]+dues|dues|common[ \t]+(?:area[ \t]+)?(?:charges?|fees?))"
_HOA_OWNER_PAYS = re.compile(r"\b(?:paid|billed|covered|handled|included)[ \t]+by[ \t]+(?:the[ \t]+)?(?:owner|landlord|management|seller)\b|\b(?:owner|landlord|management)[ \t]+(?:pays?|covers?|handles?|is[ \t]+responsible)\b|\b(?:owner|landlord)[- ]paid\b", re.I)
_HOA_TENANT_PAYS = re.compile(r"\b(?:tenant|renter|resident|lessee)'?s?[ \t]+(?:pays?|is[ \t]+responsible|are[ \t]+responsible|covers?|must[ \t]+pay|will[ \t]+pay)\b|\b(?:paid|billed|charged|passed[ \t]+(?:through|on|along))[ \t]+(?:by|to)[ \t]+(?:the[ \t]+)?(?:tenant|renter|resident|lessee)s?\b|\b(?:tenant|renter)[- ]paid\b|\bpassed[ \t]+(?:through|on|along)[ \t]+to[ \t]+(?:the[ \t]+)?(?:tenant|renter)"
                              r"|\bpass[- ]?through\b|\bpass(?:ed)?[ \t]+through\b(?![ \t]+to[ \t]+(?:the[ \t]+)?owner)|\b(?:mandatory|compulsory)\b|(?<!not )(?<!n't )\brequired\b|\bbilled[ \t]+monthly\b", re.I)  # cycle 26: a required or passed-through HOA fee on a rental is the renter's


def _hoa_clauses(text: str) -> list[str]:
    """The pieces of the text (sentences, lines, bullets) that name an HOA or condo fee."""
    return [c for c in re.split(r"[.](?!\d)|[\n;|]|\s[-\u2013\u2014]\s", text) if re.search(r"\b" + _HOA_LABEL, c, re.I)]


def _hoa_payer(text: str) -> str:
    """Who pays the HOA or condo fee on a rental: "tenant", "owner", or "" when the listing does not say (or says both)."""
    owner = tenant = False
    for c in _hoa_clauses(text):
        owner = owner or bool(_HOA_OWNER_PAYS.search(c))
        tenant = tenant or bool(_HOA_TENANT_PAYS.search(c))
    if owner and tenant:
        return ""
    return "owner" if owner else ("tenant" if tenant else "")


def _hoa_paid_by_owner(text: str) -> str:
    """For a rental: "Quarterly HOA $240 paid by owner", "Monthly condo fee 385 (paid by owner)" -> the amount words ("$240 quarterly"),
    "" when the owner paying the HOA is not said. The tenant pays nothing for it, so nothing is counted."""
    for sent in _hoa_clauses(text):
        if _HOA_OWNER_PAYS.search(sent):
            amt = re.search(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)|\b(\d{2,4})\b", sent)
            per = re.search(r"\b(quarterly|annual(?:ly)?|yearly|monthly|per[ \t]+(?:month|quarter|year)|/[ \t]*(?:mo|yr))", sent, re.I)
            figure = (amt.group(1) or amt.group(2)) if amt else ""
            return (f"${figure}" if figure else "") + (f" {per.group(1).lower()}" if per and figure else "")
    return ""


def listing_billed_amount(text: str) -> float | None:
    """Public: the monthly utilities bill a listing's text gives ("billed back at $85/month", "billed back monthly (avg $55)"), or None.
    It is the amount the reader counts when it reads the whole text (figures for other utilities and quarterly bills added up)."""
    try:
        counted_now = _util_read(_tidy(text or ""))[0]
        if counted_now is not None:
            return counted_now
    except Exception:
        pass
    try:
        text = _util_text(_tidy(text or ""))
        billed = _billed_back(text)
        if billed:
            extra = _estimate_plan_for(text, {w.strip() for w in billed[0].split(",") if w.strip()}) if billed[0] else None
            return billed[1] + (extra["amount"] if extra and not extra["total"] else 0)
        roles = _utility_roles(text)
        plan = None if roles["amount"] or roles["billed"] else _estimate_plan_for(text)
        periodic = _periodic_utility_amount(text)
        named_periodic = _periodic_named(text)
        return roles["amount"] or (plan["amount"] if plan else None) or _utilities_extra_amount(text) or (periodic[0] if periodic else None) or (named_periodic["monthly"] if named_periodic else None)
    except Exception:
        return None


_UTIL_HDR = re.compile(
    r"(?P<incl_a>\b(?:utilities\s+included|included\s+utilities|utilities\s+incl\w*|included)(?:[ \t]*[:\-]|[ \t]*(?=\n)))"
    r"|(?P<incl_b>\b(?:rent\s+includes?|includes|landlord\s+(?:pays|covers)|owner\s+(?:pays|covers)|(?:hoa|association|hoa\s+fees?|condo\s+fees?|management)\s+(?:pays|covers))\b)"
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
        if kind in ("full", "incl_a"):  # a list that names who covers it (HOA includes, landlord pays, tenant pays) places its own extras
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
            mentions_net = bool(re.search(r"\b(?:internet|wi-?fi|broadband|cable)\b", low))
            pay += [w for w in _COMMON_UTILITIES if w not in have and (w != "internet" or mentions_net)]
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
    many = len(clash) > 1
    facts.append(f"The listing is unclear about {names}: one line says {'they are' if many else 'it is'} included and another says you pay {'them' if many else 'it'}. "
                 f"{'They are' if many else 'It is'} left as something you pay with no amount, so the cost is not complete. Ask the landlord what the rent really covers.")
    return (_ordered_utilities(left) if left else ""), pays


def _really_included(text: str, amount: float, names: str) -> list[str]:
    """Which of ``names`` the listing calls included in a sentence OTHER than the one that gives the billed or flat amount.
    "Water, sewer, trash $70/month flat, paid with rent" is one sentence about the fee: it is no claim that water is included."""
    gone = {w.strip() for w in names.split(",") if w.strip()}
    rest = [c for c in re.split(r"\n|;|\.(?=\s|$)", text) if not re.search(r"\$\s?" + re.escape(f"{amount:g}") + r"(?![\d,])", c)]
    inc = _utilities("\n".join(rest))
    have = set(_ALL_UTILITIES) if inc == "all" else {w.strip() for w in inc.split(",") if w.strip()}
    return [w for w in sorted(gone) if w in have]


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
        if m.group("dmd"):  # "15-Jan-2027", "15 January 2027"
            return date(int(m.group("dmy")), _MONTHS[m.group("dmm")[:3].lower()], int(m.group("dmd"))).isoformat()
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
         r"(?P<day>\d{1,2})(?![\d])(?:st|nd|rd|th)?(?:,?\s*(?P<year>\d{4}))?|"
         r"(?P<dmd>\d{1,2})(?:st|nd|rd|th)?[- ]+(?P<dmm>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?,?[- ]+(?P<dmy>\d{4})\b)")


_NOT_A_DATE_TAIL = re.compile(r"[ \t]*(?:x\b|\u00d7|times\b|months?\b|month'?s\b|mos?\b|%|dollars?\b|usd\b|bucks\b|k\b|weeks?\b|days?\b|years?\b|yrs?\b|\$|per\b|"
                              r"(?:of[ \t]+)?(?:rent|rents|deposit|security|pay|payment|fee|fees)\b|(?:bed|bd|br|ba|bath|sq|sf)\w*)", re.I)


def _is_amount_not_date(low: str, m: re.Match[str]) -> bool:
    """Cycle 24: "Move-in: 1.5 months deposit", "Move in 1/2 month", "move-in 2.5x rent", "Move-in: 1.5 rent": a number that is followed by months, mo,
    x rent or a money word is a count of months or an amount, never a date. A dotted number that is followed by rent or deposit words is not a date either."""
    tail = low[m.end():m.end() + 24]
    if _NOT_A_DATE_TAIL.match(tail):
        mdy = m.groupdict().get("mdy")
        if mdy and "/" in mdy and re.match(r"[ \t]*(?:rent|rents|deposit|security|pay|payment|fee|fees|per|bed|bd|br|ba|bath|sq|sf)", tail, re.I) and not re.match(r"[ \t]*(?:months?|mos?|x|times)\b", tail, re.I):
            return False  # "Available 6/1 rent $1,800": a slash date, then the rent
        if m.groupdict().get("iso") or m.groupdict().get("dmd") or m.groupdict().get("mon"):
            return bool(re.match(r"[ \t]*(?:x\b|\u00d7|times\b|months?\b|mos?\b|%|dollars?\b|usd\b)", tail, re.I))
        return True
    return False


def _first_real_date(rx: re.Pattern[str], low: str) -> re.Match[str] | None:
    for m in rx.finditer(low):
        if not _is_amount_not_date(low, m):
            return m
    return None


_DEADLINE_CUE = re.compile(r"\b(?:move[- ]?in|move[- ]?ins|sign(?:ing|s)?|apply|applying|applications?|lease|deposit|book|reserve|tour|submit|commit|order)\b(?:[ \t]+(?:up|a[ \t]+lease|your[ \t]+lease|the[ \t]+lease|it|now|today))?[ \t]*(?:by|before|through|until|no[ \t]+later[ \t]+than|within)\b[ \t:]*", re.I)
_DEADLINE_DEAL_WORDS = re.compile(r"\b(?:free|off|concessions?|specials?|discounts?|waived?|incentives?|bonus|credit|promo\w*|deal|offer)\b", re.I)


def _blank_deal_dates(text: str) -> str:
    """Cycle 25: a date in a deal or deadline clause ("1 month free if you move in by 2/1", "sign by 1/15", "apply by Dec 1") is when the deal
    ends, never when the place is available: the clause is blanked before the availability date is read."""
    out = text
    sentences = [(sm.start(), sm.end()) for sm in re.finditer(r"[^.!?\n;|]+(?:[.!?](?!\s|$)[^.!?\n;|]*)*", text)]
    for m in _DEADLINE_CUE.finditer(text):
        dm = re.compile(_DATE, re.I).match(text, m.end())
        if dm and re.match(r"move", m.group(0), re.I):
            # a bare "Move in by 3/15/2027." can be the day the place is ready: it is a deadline only next to a deal ("1 month free", "$300 off")
            i = next((k for k, (a, b) in enumerate(sentences) if a <= m.start() < b), None)
            near = " ".join(text[sentences[k][0]:sentences[k][1]] for k in (i - 1, i, i + 1) if i is not None and 0 <= k < len(sentences))
            if not _DEADLINE_DEAL_WORDS.search(near):
                continue
        if dm:
            out = out[:m.start()] + " " * (dm.end() - m.start()) + out[dm.end():]
    for sm in re.finditer(r"[^.!?\n;|]+", text):
        seg = sm.group(0)
        if not _DEADLINE_DEAL_WORDS.search(seg):
            continue
        for m in re.finditer(r"\bmove[- ]?in[ \t]+(?:on[ \t]+)?(?=" + _DATE + r")", seg, re.I):
            dm = re.compile(_DATE, re.I).match(text, sm.start() + m.end())
            if dm:
                a = sm.start() + m.start()
                out = out[:a] + " " * (dm.end() - a) + out[dm.end():]
    return out


def _available(text: str) -> str | None:
    today = _today()
    low = _blank_deal_dates(text).lower()
    m = _first_real_date(re.compile(r"\b(?:date available|availability|available(?: from| on| starting| beginning)?|avail\.?|move[- ]?in(?: date)?|(?:move[- ]?in[- ])?ready(?:[ ]for[ ]move[- ]?in)?(?:[ ]on|[ ]by)?|lease start(?:s| date)?)\b[ \t:\-]{0,6}(?:on |for |by |starting |beginning )?" + _DATE), low)
    if m:
        return _read_date(m, today)
    m = re.search(r"\b(?:available|avail\.?)\s*(?:for\s+)?" + _DATE + r"\s*(?:move[- ]?in|lease)", low)
    if m:
        return _read_date(m, today)
    m = _first_real_date(re.compile(r"(?<![\d/.-])" + _DATE + r"[ \t]*[-:(]?[ \t]*(?:move[- ]?in|lease start)\b"), low)
    if m and not re.search(r"(?:to|through|thru|until|-)[ \t]*$", low[max(0, m.start() - 4):m.start()]):  # "15-JAN-2027 MOVE IN"
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
            if "year" not in keys and "iso" not in keys and "dmy" not in keys and not (keys.get("mdy") and re.search(r"[/.-]\d{2,4}$", keys["mdy"])):
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
        if d1.day == 1 and d2.month == 2 and d2.day == 28 and nxt.day == 29:
            m2 = (d2.year - d1.year) * 12 + d2.month - d1.month + 1  # "3/1/2027 - 2/28/2028": the Feb 28 end is month-end (leap year typo or not)
            if 1 <= m2 <= 36:
                return start, m2, ""
        return start, None, (f"The listing gives lease dates ({start} to {end}) that are not a whole number of months, so the lease length is left empty. "
                             "Ask how long the lease is.")
    return None, None, ""


_LEASE_START_PHRASE = re.compile(r"\blease[ \t]+(?:starting|starts?|begins?|beginning|commenc\w+|start[ \t]+date)[ \t]*(?:on|:|-|=)?[ \t]*" + _DATE.replace("(?P<", "(?P<s_"), re.I)
_LEASE_END_PHRASE = re.compile(r"\blease[ \t]+(?:through|thru|ends?|ending|expires?|until|end[ \t]+date)[ \t]*(?:on|:|-|=)?[ \t]*" + _DATE.replace("(?P<", "(?P<e_"), re.I)


_LEASE_START_PHRASE2 = re.compile(
    r"\b(?:lease|\d{1,2}[- ]?(?:months?|mos?)(?:[- ]lease)?)\b[^.\n;]{0,60}?\b(?:starting|starts?|begins?|beginning|commenc\w+|from)[ \t]*(?:on|:|-|=)?[ \t]*" + _DATE.replace("(?P<", "(?P<s_"), re.I)
_LEASE_MONTHS_AFTER_DATE = re.compile(
    r"\blease\b[^.\n;]{0,40}?(?:\d{4}|\d{1,2}/\d{1,2}/\d{2})[ \t]*,[ \t]*(?:for[ \t]+)?(\d{1,2})[ \t]*[- ]?months?\b(?![ \t]*(?:free|off|rent|of|discount|concession|,[ \t]*\d|/|or\b|and\b))", re.I)


def _dated_with_year(m: re.Match[str], prefix: str) -> str | None:
    """The date a prefixed _DATE match holds, only when it names its year ("Feb 28, 2027"): a lease date with no year is not guessed."""
    keys = {k[len(prefix):]: v for k, v in m.groupdict().items() if k.startswith(prefix) and v}
    if not ("iso" in keys or "dmy" in keys or "year" in keys or (keys.get("mdy") and re.search(r"[/.-]\d{2,4}$", keys["mdy"]))):
        return None
    class _M:
        def group(self, name: str) -> str | None:
            return keys.get(name)
    return _read_date(_M(), _today())  # type: ignore[arg-type]


def _whole_months(start: str, end: str) -> int | None:
    """The lease months between a first day and a last day ("2027-03-01" to "2028-02-28" is 12), or None when it is not whole months."""
    d1, d2 = date.fromisoformat(start), date.fromisoformat(end)
    if d2 <= d1:
        return None
    nxt = d2 + timedelta(days=1)
    months = (nxt.year - d1.year) * 12 + nxt.month - d1.month
    if months >= 1 and nxt.day == d1.day and 1 <= months <= 36:
        return months
    if d1.day == 1 and d2.month == 2 and d2.day == 28 and nxt.day == 29:
        m2 = (d2.year - d1.year) * 12 + d2.month - d1.month + 1  # a Feb 28 end is month-end
        return m2 if 1 <= m2 <= 36 else None
    return None


_ORDINALS = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9,
             "tenth": 10, "fifteenth": 15, "twentieth": 20, "thirtieth": 30}
_MONTH_WORD = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_ORDINAL_DATE = re.compile(r"\b(?:the[ \t]+)?(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|fifteenth|twentieth|thirtieth|\d{1,2}(?:st|nd|rd|th))"
                           r"(?:[ \t]+day)?[ \t]+of[ \t]+(" + _MONTH_WORD + r")\b(\.?,?[ \t]*\d{4}\b)?", re.I)


def _ordinal_dates(text: str) -> str:
    """"starts the first of April 2027" -> "starts April 1 2027" (same length-free rewrite), so the date readers see a plain date."""
    def fix(m: re.Match[str]) -> str:
        w = m.group(1).lower()
        day = _ORDINALS.get(w) or int(re.sub(r"\D", "", w))
        return f"{m.group(2)} {day}" + (f" {re.sub(r'[^0-9]', '', m.group(3))}" if m.group(3) else "")
    return _ORDINAL_DATE.sub(fix, text)


# "Lease begins 12/1 ends 11/30/2027": a start with no year and an end with a year. The start is the day that makes whole months.
_LEASE_BEGIN_END = re.compile(r"\blease[ \t]+(?:starting|starts?|begins?|beginning|commenc\w+)[ \t]*(?:on|:|-|=)?[ \t]*" + _DATE.replace("(?P<", "(?P<s_") + r"[ \t]*[,;.-]?\s*(?:and[ \t]+)?"
                              r"(?:lease[ \t]+)?(?:ends?|ending|expires?|through|thru|until)[ \t]*(?:on|:|-|=)?[ \t]*" + _DATE.replace("(?P<", "(?P<e_"), re.I)


def _lease_begin_end(text: str) -> tuple[str, str] | None:
    m = _LEASE_BEGIN_END.search(text)
    if not m:
        return None
    end = _dated_with_year(m, "e_")
    if not end:
        return None
    start = _dated_with_year(m, "s_")
    if not start:
        keys = {k[2:]: v for k, v in m.groupdict().items() if k.startswith("s_") and v}
        if "mdy" not in keys:
            return None
        parts = re.split(r"[/.-]", keys["mdy"])
        if len(parts) != 2:
            return None
        e = date.fromisoformat(end)
        try:
            cand = date(e.year, int(parts[0]), int(parts[1]))
        except ValueError:
            return None
        if cand >= e:
            cand = date(e.year - 1, cand.month, cand.day)
        start = cand.isoformat()
    return (start, end) if _whole_months(start, end) else None


def _lease_phrases(text: str) -> tuple[str | None, str | None]:
    """"12 month lease starting 3/1/2027" -> start; "Lease through 2/28/2028", "Lease ends Feb 28, 2027" -> end. Each needs a year."""
    start = end = None
    text = _ordinal_dates(text)
    both = _lease_begin_end(text)
    if both:
        return both
    m = _LEASE_START_PHRASE.search(text)
    if m:
        start = _dated_with_year(m, "s_")
    if not start:
        for m in _LEASE_START_PHRASE2.finditer(text):  # "Lease through 2/28/2028, starting 3/1/2027", "13 months lease from 15-Jan-2027"
            start = _dated_with_year(m, "s_")
            if start:
                break
    m = _LEASE_END_PHRASE.search(text)
    if m:
        end = _dated_with_year(m, "e_")
    return start, end


_TWO_LENGTHS = (
    re.compile(r"\b(\d{1,2})[ \t]*months?\b\)?[^.\n;]{0,12}?[ \t,]+or[ \t]+(?:a[ \t]+)?(?:full|whole)[- ]?(?:year|12)\b", re.I),
    re.compile(r"\b(?:full|whole)[- ]year[ \t]*\)?[ \t,]+or[ \t]+(?:a[ \t]+)?(\d{1,2})[ \t]*months?\b", re.I),
)


def _lease_two_lengths(text: str) -> str:
    """"Aug 1 2027 - Feb 28 2028 (7 months), or full year": two lengths are offered. Written for a note ("7 months or a full year"); "" when not."""
    for rx in _TWO_LENGTHS:
        m = rx.search(text)
        if m and 1 <= int(m.group(1)) <= 60 and int(m.group(1)) != 12:
            return f"{int(m.group(1))} months or a full year"
    return ""


def _lease_bare_months(text: str, other: bool) -> int | None:
    """A line or comma piece that is only "13 months": the lease length, when it is the one length in the paste. 6 to 36 only."""
    if other:
        return None
    found = [int(m.group(1)) for seg in re.split(r"[\n|;,]|\.[ \t]+", text)
             for m in [re.fullmatch(r"[ \t\u2022*\-]*(?:(?:lease|term)[ \t]*(?:length)?[ \t]*[:\-]?[ \t]*)?(\d{1,2})[- ]?months?[ \t.]*", seg, re.I)] if m]
    if len(found) == 1 and 6 <= found[0] <= 36 and len(re.findall(r"\b\d{1,2}[- ]?months?\b", text, re.I)) == 1:
        return found[0]
    return None


# "Starts 3-1-27", "Begins March 1, 2027": a bare start word with a date. The date needs a year or a month name, so "starts 3.5" is no date.
_BARE_START = re.compile(r"(?<![\w$])(?:starts?|starting|begins?|beginning)(?:[ \t]+date)?[ \t]*(?:on|at|:|-|=)?[ \t]*" + _DATE.replace("(?P<", "(?P<b_"), re.I)


def _bare_start_date(text: str) -> str | None:
    for m in _BARE_START.finditer(_ordinal_dates(text)):
        if re.search(r"\b(?:rent|payments?|billing|interest)[ \t]*$", text[max(0, m.start() - 12):m.start()], re.I):
            continue
        d = _dated_with_year(m, "b_")
        if d:
            return d
        keys = {k[2:]: v for k, v in m.groupdict().items() if k.startswith("b_") and v}
        if keys.get("mon") and not keys.get("year"):
            class _M:
                def group(self, name: str) -> str | None:
                    return keys.get(name)
            return _read_date(_M(), _today())  # type: ignore[arg-type]
    return None


_MONTH_TO_MONTH = re.compile(r"\bmonth[- ]to[- ]month\b[^.\n;)\]}|<>＜＞]{0,30}", re.I)
_M2M_PRICED = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?[ \t]*\(?[ \t]*\bmonth[- ]to[- ]month\b", re.I)


def _month_to_month_note(text: str, lease: Any = None) -> list[str]:
    m = _MONTH_TO_MONTH.search(text)
    if not m:
        return []
    if _M2M_PRICED.search(text) and re.search(r"\$\s?\d[\d,]*[^|\n;$]{0,12}\b(?:[2-9]|1\d|2[0-4])[- ]?(?:mo\b|months?\b(?![- ]to))", text, re.I):
        return []  # cycle 27: a month-to-month rent the listing prices is quoted once, by the lease-length or "also says" note for that figure
    said = " ".join(m.group(0).split()).strip(" ,-")
    keep = "" if lease else " No lease length is saved from that."
    return [f'The listing says "{said}".{keep} Ask what the month to month terms and rent are.']


_COMMUTE_CLAIM = re.compile(
    r"\b(\d{1,3})[ \t]*[- ]?(?:min(?:ute)?s?)[ \t]*(?:by[ \t]+)?(?:(?:bike|biking|bicycle|cycling|walk|walking|drive|driving|bus|transit|train)(?:[ \t]+(?:ride|trip|ride))?)[ \t]+(?:to|from)[ \t]+(?:the[ \t]+)?"
    r"[A-Z][\w'&-]*(?:[ \t]+[A-Z][\w'&-]*){0,3}")


def _commute_claims(text: str) -> list[str]:
    """"12 min bike to Siebel", "14 min bike to the Quad": the listing's own commute claim, quoted in a note. Never a commute field."""
    notes: list[str] = []
    for m in _COMMUTE_CLAIM.finditer(text):
        claim = " ".join(m.group(0).split())
        note = (f'The listing says "{claim}". That is the listing\'s own claim, so no commute is filled in from it. '
                "Your own commute settings decide the commute; check the real time before you trust it.")
        if note not in notes:
            notes.append(note)
    return notes[:3]


_LEASE_OR_LEASE = re.compile(r"\d{1,2}[- ]?(?:months?|mos?)\b[- ]?(?:leases?|terms?|contracts?)?[ \t]*(?:,|/|or|and)[ \t]*(?:or[ \t]+|and[ \t]+|a[ \t]+)?\d{1,2}[- ]?(?:months?|mos?)\b")
_LEASE_PAIR = re.compile(r"(?<![\d,$/-])(\d{1,2})[- ]?(?:months?|mos?)\b[- ]?(?:leases?|terms?|contracts?)?[ \t]*(?:,|/|or|and)[ \t]*(?:or[ \t]+|and[ \t]+|a[ \t]+)?(\d{1,2})[- ]?(?:months?|mos?)\b(?![ \t]*(?:free|off|discount|of[ \t]+rent|rent\b|concession))[- ]?(?:leases?|terms?|contracts?)?")


def _lease_pair_at(low: str, pos: int) -> bool:
    """True when the lease length written at pos is one of two lengths side by side ("9 month lease or 12 month lease")."""
    for m in _LEASE_PAIR.finditer(low):
        a, b = int(m.group(1)), int(m.group(2))
        if a != b and 3 <= a <= 60 and 3 <= b <= 60 and (m.start(1) <= pos <= m.start(2) + 3 or m.start() - 1 <= pos <= m.end()) \
                and re.search(r"leases?|terms?|contracts?", m.group(0)):
            return True
    return False


_LEASE_ALSO = re.compile(r"(?<![\d,$/-])(\d{1,2})[- ]?(?:months?|mos?)\b[- ]?(?:leases?|terms?|contracts?)?(?:[ \t]+(?:available|offered|option|possible))?[ \t]*[,;.]?[ \t]*"
                         r"(?:or[ \t]+)?(?:and[ \t]+)?(?:also|plus|as well)[ \t,:]*(?:a[ \t]+|an[ \t]+)?(\d{1,2})[- ]?(?:months?|mos?)\b(?![ \t]*(?:free|off|discount|of[ \t]+rent|rent\b|concession))", re.I)


def _lease_also(text: str) -> tuple[int, int] | None:
    """"11-month lease available, also 12-month": the two lengths the listing offers (first, second)."""
    m = _LEASE_ALSO.search(text)
    if not m:
        return None
    a, b = int(m.group(1)), int(m.group(2))
    return (a, b) if a != b and 3 <= a <= 60 and 3 <= b <= 60 else None


def _lease_months(text: str) -> int | None:
    low = text.lower()
    also = _lease_also(low)
    if also:
        return 12 if 12 in also else None  # a plain year is the one that is saved; two other lengths stay unknown (see _lease_choices)
    found: list[tuple[int, int]] = []  # (where it is written, months): the one stated first wins
    for pat in (r"(?<![\d,-])(\d{1,2})[- ](?:month|mo\b)[- ]?(?:minimum |min\.? )?(?:lease|term|contract)",
                r"\b(?:lease|term|contract)s?(?: terms?| length| duration| options?)?\s*[:\-]?\s*(?:of |is |are )?(?<![-,\d] )(\d{1,2})\s*(?:months?|mos?\b)(?!\s*(?:,|and|or|/|to|-)\s*\d)",
                r"\b(\d{1,2})\s*months?\s+(?:lease|minimum|min\b)", r"(?<![\d,-])(\d{1,2})[- ]months?[- ](?:minimum|min\b)", r"\b(one|1)[- ]year (?:lease|term|contract)"):
        for m in re.finditer(pat, low):
            if _OFFER_LEASE.search(low[max(0, m.start() - 45):m.start()]):
                continue  # "One month free on a 13-month lease" is the length the deal needs, not the lease on offer
            if re.search(r"\b(?:or|instead)[ \t]+(?:sign|choose|take|pick|get|go)\w*[ \t]+(?:a[ \t]+|an[ \t]+)?$", low[max(0, m.start() - 20):m.start()]):
                continue  # "Lease 12 months, or sign a 18 month lease and get $100 off": the longer lease is a deal, not the lease on offer
            if _LEASE_OR_LEASE.search(low[max(0, m.start() - 24):m.end() + 34].replace("\n", " ")) and not _OFFER_LEASE.search(low[max(0, m.start() - 45):m.start()]):
                if _lease_pair_at(low, m.start()):
                    continue  # "9 month lease or 12 month lease": two lengths on offer, so neither is the lease
            g = m.group(1)
            n = 12 if g in ("one", "1") and "year" in m.group(0) else int(g)
            if 1 <= n <= 60 and (not re.search(r"\d\s*(?:,|-|to|or)\s*$", low[max(0, m.start() - 6):m.start()])
                                 or re.search(r"(?:\b\d{4}|\d/\d{1,2}/\d{2})\s*,\s*$", low[max(0, m.start() - 12):m.start()])):  # "3/1/2027, 13 month lease": the date is not a lease length
                found.append((m.start(), n))
    if not found:
        m = _LEASE_MONTHS_AFTER_DATE.search(text)  # "Lease starting 3/1/2027, 13 months."
        if m and 3 <= int(m.group(1)) <= 60:
            return int(m.group(1))
    return min(found)[1] if found else None


_LEASE_LIST = (r"\d{1,2}(?:[ \t]*(?:months?|mos?))?(?:[ \t]*(?:,|/|or|and|to|-)[ \t]*(?:or[ \t]+|and[ \t]+)?\d{1,2}(?:[ \t]*(?:months?|mos?))?)+")
_LEASE_CHOICES = (
    re.compile(r"\b(?:lease|term|contract)s?(?:[ \t]+(?:terms?|lengths?|options?|durations?))?[ \t]*(?:of|is|are|:|-)?[ \t]*(" + _LEASE_LIST + r")[ \t]*(?:months?|mos?\b)", re.I),
    re.compile(r"(?<![\d,$/-])(" + _LEASE_LIST + r")[ \t]*[- ]?(?:months?|mos?)\b[- ]*(?:leases?|terms?|contracts?|options?)", re.I),
)


def _lease_choices(text: str) -> str:
    low = text.lower()
    also = _lease_also(low)
    if also:
        return f"{also[0]} or {also[1]} months"
    for m in _LEASE_PAIR.finditer(low):
        a, b = int(m.group(1)), int(m.group(2))
        if a != b and 3 <= a <= 60 and 3 <= b <= 60 and re.search(r"leases?|terms?|contracts?", m.group(0)):
            return f"{a} or {b} months"
    return _lease_choices_list(text)


def _lease_choices_list(text: str) -> str:
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
    also = _lease_also(text.lower())
    if also and lease is not None and lease in also:
        other = also[0] if also[1] == lease else also[1]
        return [f"The listing also offers {'an' if other in (8, 11, 18) else 'a'} {other} month lease. The {lease} month lease is what is saved. Ask which one you would get."]
    m = _OFFER_LEASE_AFTER.search(text)
    if not m:
        # "Lease 12 months, or sign a 18 month lease and get $100 off a month"
        m = re.search(r"\b(?:or|instead)[ \t]+(?:sign|choose|take|pick|get|go)\w*[ \t]+(?:a[ \t]+|an[ \t]+)?(\d{1,2})[- ]?(?:month|mo)s?\b[^.\n;!]{0,40}", text, re.I)
        if m and lease is not None and int(m.group(1)) != lease:
            return [f"The listing also offers a deal for a {m.group(1)} month lease. The {lease} month lease is what is saved, and the deal is not counted. Ask what you have to sign to get it."]
    if not m or (lease is not None and int(m.group(1)) == lease):
        return []
    if lease is None:
        return [f"The listing ties a deal to a {m.group(1)} month lease. That is not saved as the lease length, because it only says what the deal needs."]
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
    return _year_built_loose(text)


_YEAR_BUILT_LOOSE = re.compile(r"(?<![\w$])(?:(?:newly[ \t]+)?(?:new|completed|opened|constructed|built)(?:[ \t]+in)?|year[ \t]+of[ \t]+construction|construction[ \t]+(?:date|year))[ \t]*[:\-]?[ \t]*((?:18|19|20)\d{2})\b(?!\d|,\d)(?![ \t]*[-/]\d)", re.I)
# a year after "completed", "opened" or "new" that belongs to something else: a renovation, an amenity, a lease, a sale
_YEAR_BUILT_NOT = re.compile(r"renovat|remodel|updat|upgrad|kitchen|bath|roof|inspect|lease|leasing|sale|sold|closing|purchase|escrow|deal|work|repair|install|paint|floor|hvac|window|appliance|addition|pool|gym|fitness|lobby|office|clubhouse|rooftop|tour|application|move|availab|offer|listing|price|rent|reduced|permit|sign", re.I)


def _year_built_loose(text: str) -> int | None:
    """Cycle 25: "New in 2025.", "Completed 2024", "Opened 2022", "Constructed 2021", "Year of construction: 2019". The word must stand at the
    start of a sentence, line or item, or follow a comma, dash or bar, and the clause before it must not be about a renovation, an amenity, a lease or a sale."""
    for m in _YEAR_BUILT_LOOSE.finditer(text):
        clause_start = max(text.rfind(".", 0, m.start()), text.rfind("\n", 0, m.start()), text.rfind(";", 0, m.start()), text.rfind(",", 0, m.start()),
                           text.rfind("|", 0, m.start()), text.rfind(" - ", 0, m.start())) + 1
        lead = text[clause_start:m.start()]
        if lead.strip(" \t-*\u2022\u2013\u2014:(") and not re.fullmatch(r"[ \t]*(?:(?:a|an|the)[ \t]+)?(?:brand[ \t]+)?", lead, re.I):
            continue  # the word is in the middle of a longer phrase ("pool opened 2022", "kitchen completed 2024")
        sentence_end = [i for i in (text.find(".", m.end()), text.find("\n", m.end())) if i != -1]
        tail = text[m.end():min(sentence_end) if sentence_end else len(text)]
        if _YEAR_BUILT_NOT.search(lead) or re.match(r"[ \t]*(?:lease|leases|availab|move|tour)", tail, re.I):
            continue
        y = int(m.group(1))
        if 1800 <= y <= _today().year + 3:
            return y
    return None


_SEASON = r"(?:(?:early|late|mid)[ \t-]*)?(?:spring|summer|fall|autumn|winter|q[1-4]|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?)"
_YEAR_BUILT_DELIVERED = re.compile(r"(?<![\w$])(?:(?:newly|recently|just)[ \t]+)?(?:delivered|opened|completed|built)(?:[ \t]+(?:in|on))?[ \t]*[:\-]?[ \t]*(?:" + _SEASON + r"[ \t]*(?:of[ \t]+)?,?[ \t]*)?((?:19|20)\d{2})\b(?!\d|,\d)(?![ \t]*[-/]\d)", re.I)


def _year_built_delivered(text: str) -> int | None:
    """Cycle 27 (renters): "Delivered 2024", "Opened fall 2023", "Delivered in spring 2025". Same rules as the loose reader: the word starts a
    sentence, line or item, and the clause is not about a renovation, an amenity, a lease or a sale."""
    for m in _YEAR_BUILT_DELIVERED.finditer(text):
        clause_start = max(text.rfind(".", 0, m.start()), text.rfind("\n", 0, m.start()), text.rfind(";", 0, m.start()), text.rfind(",", 0, m.start()),
                           text.rfind("|", 0, m.start()), text.rfind(" - ", 0, m.start())) + 1
        lead = text[clause_start:m.start()]
        if lead.strip(" \t-*\u2022\u2013\u2014:(") and not re.fullmatch(r"[ \t]*(?:(?:a|an|the)[ \t]+)?(?:brand[ \t]+)?", lead, re.I):
            continue
        ends = [i for i in (text.find(".", m.end()), text.find("\n", m.end())) if i != -1]
        tail = text[m.end():min(ends) if ends else len(text)]
        if _YEAR_BUILT_NOT.search(lead) or re.match(r"[ \t]*(?:lease|leases|availab|move|tour)", tail, re.I):
            continue
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


_HOA_NO_INFO = (r"\b(?:hoa|association)(?:[ \t]+(?:fees?|dues))?[ \t]*[:\-=][ \t]*no[ \t]+(?:info\w*|details?|data|figures?)(?:[ \t]+(?:listed|available|provided|given|yet))?|"
                r"\bno[ \t]+(?:hoa|h\.o\.a\.|homeowners'?[ \t]+association)(?:[ \t]+(?:fees?|dues))?[ \t]+(?:info\w*|details?|data|yet|known|listed|available|provided|given|confirmed|figures?|amounts?|numbers?|on[ \t]+file)\b(?:[ \t]+(?:yet|available|provided|listed|given))?")


def _hoa(text: str) -> float | None:
    if re.search(r"\bno[ \t]+(?:hoa|h\.o\.a\.|homeowners'?[ \t]+association)(?:[ \t]+(?:fees?|dues))?\b(?![ \t]+(?:info\w*|details?|data|yet|known|listed|available|provided|given|confirmed|figures?|amounts?|numbers?|on[ \t]+file))|\bhoa(?:[ \t]+(?:fees?|dues))?[ \t]*[:\-=][ \t]*(?:none|no(?![ \t]+(?:info\w*|details?|data|figures?))|n/a|\$0)\b|\bwithout[ \t]+(?:an?[ \t]+)?hoa\b|\b(?:hoa|association)[ \t]+(?:fees?|dues)?[ \t]*(?:\(none\)|not required)", text, re.I) \
            and not re.search(r"\$\s?[1-9]\d*(?:,\d{3})*(?:\.\d\d)?\s*(?:/\s*\w+|per\s+\w+|\w+ly)\s*(?:hoa|association)|\b(?:hoa|association)(?:[ \t]+(?:fees?|dues))?[ \t:\-=(]{0,6}\$\s?[1-9]", text, re.I):
        return 0.0
    bm = re.search(r"\b(?:hoa|association)(?:[ \t]+(?:fees?|dues))?[ \t]+(?:is|are)?[ \t]*(?:billed|paid|due|charged|payable|collected)[ \t]+(quarterly|annually|yearly|monthly)[ \t]+(?:at|of|for|as)?[ \t]*\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?(?!\d)", text, re.I)
    if bm:  # "HOA fee is billed quarterly at $900": the period comes before the amount
        value = _num(bm.group(2))
        w = bm.group(1).lower()
        value = value / 3 if w == "quarterly" else (value / 12 if w in ("annually", "yearly") else value)
        return round(value, 2) if 0 < value < 5000 else None
    m = re.search(r"(?:\bhoa|association|\bassoc\.?(?=[ \t]*(?:fees?|dues))|homeowners'? association|\b(?:monthly|building|unit owners?)[ \t]+dues(?![ \t]+(?:to|for)\b)|\bcondo(?=\s*(?:fee|fees|dues|payment|assessment))|\bcommon (?:area )?(?:charges?|fees?))(?:\s*(?:fee|fees|dues|payment|assessments?))*(?:[ \t]+(?:is|are|was|were|run|runs|total|totals|come|comes)\b(?:[ \t]+(?:to|in[ \t]+at))?)?[ \t:\-=(]{0,6}(?:of[ \t]+)?(?:(?:about|around|approx\.?|approximately|roughly|est\.?|estimated|~)[ \t]*)?\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?\s*(/\s*\w+|per\s+\w+|\w+ly|annual\w*)?", text, re.I)
    if not m:
        m = re.search(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?\s*(/\s*\w+|per\s+\w+|\w+ly|annual\w*)?\s*(?:hoa|association) (?:fee|dues)?", text, re.I)
    if not m:
        # "Monthly condo fee 385", "Condo fee: 385/mo": a plain number with no dollar sign counts only when the listing says monthly
        nm = re.search(r"\b(monthly[ \t]+)?(?:hoa|condo|association)[ \t]+(?:fees?|dues)[ \t:\-=]{0,4}(\d{2,4})(?:\.\d\d)?(?![\d,]|\.\d|[ \t]*(?:%|sq|sf|/[ \t]*(?:br|bd|bed)))"
                       r"([ \t]*(?:/[ \t]*mo(?:nth)?\b|per[ \t]+month\b|a[ \t]+month\b|monthly\b))?", text, re.I)
        if nm and (nm.group(1) or nm.group(3)) and not re.search(r"quarter|annual|year", text[max(0, nm.start() - 12):nm.end() + 20], re.I):
            return float(nm.group(2))
        return None
    value, per = _num(m.group(1)), (m.group(2) or "").lower()
    if not per:
        # "HOA $240 billed quarterly", "HOA $240, paid annually": the period comes after the amount
        after = re.match(r"[ \t,]*(?:\(?(?:billed|paid|due|charged|payable|collected|assessed)[ \t]+)?(quarterly|annual(?:ly)?|yearly|semi-?annual(?:ly)?|monthly|every[ \t]+(?:3|three)[ \t]+months|every[ \t]+(?:quarter|year)|each[ \t]+(?:quarter|year)|a[ \t]+(?:quarter|year)|once[ \t]+a[ \t]+year)\b", text[m.end():m.end() + 40], re.I)
        if after:
            w = after.group(1).lower()
            if w.startswith("semi"):
                return None  # twice a year: not a period this reader converts
            per = "quarter" if ("quarter" in w or "three" in w or "3" in w) else ("month" if w == "monthly" else "year")
    if not per:
        # "Quarterly HOA $240": the period comes before the label
        lead = re.search(r"\b(quarterly|annual(?:ly)?|yearly|semi-?annual(?:ly)?)[ \t]+$", text[max(0, m.start() - 16):m.start()], re.I)
        if lead:
            per = lead.group(1).lower()
            if per.startswith("semi"):
                return None  # twice a year: not a period this reader converts
    if not per and re.search(r"\bmonthly[ \t]+$", text[max(0, m.start() - 12):m.start()], re.I) and re.search(r"assessments?\W*$", m.group(0).split("$")[0], re.I) \
            and not re.search(r"special|one[- ]time|capital|seller|pending|upcoming", text[max(0, m.start() - 40):m.end() + 30], re.I):
        per = "month"  # cycle 21: "Monthly HOA assessment: $310" says monthly before the label
    if re.search(r"assessments?\W*$", m.group(0).split("$")[0], re.I) and not per:
        return None  # "HOA assessment $4,000" with no period is not monthly dues
    if re.search(r"yr|year|annual", per):
        value /= 12
    elif "quarter" in per:
        value /= 3
    return round(value, 2) if 0 < value < 5000 else (0.0 if value == 0 else None)


def _hoa_plain_monthly(text: str) -> float | None:
    """A buyer listing's plain monthly dues the HOA reader does not name: "Dues $330 mo", "Assessments: $95/mo", "Condo dues 330 a month".
    The label is dues or assessments, with the amount right after it and a monthly word after the amount. A special, one-time,
    seller-paid or time-limited assessment ("for 24 months") is not the monthly dues."""
    for m in re.finditer(r"\b(?:(?:hoa|condo|association|monthly|building)[ \t]+)?(?:dues|assessments)[ \t]*[:\-=]?[ \t]*\$?[ \t]?(\d{2,4}(?:,\d{3})?)(?:\.\d\d)?(?![\d,])"
                         r"[ \t]*(?:/[ \t]*mo\w*|per[ \t]+month|a[ \t]+month|each[ \t]+month|monthly|mo\b\.?|/m\b)", text, re.I):
        lead = text[max(0, m.start() - 30):m.start()]
        tail = text[m.end():m.end() + 30]
        if re.search(r"special|one[- ]time|seller|capital|reserve|annual|yearly|quarterly|pending|upcoming|roof|window|move[- ]in|closing|initiation|\bpaid\b", lead, re.I) \
                or re.search(r"^[ \t,]*(?:for|x|over)[ \t]+\d|^[ \t,]*(?:until|through|ends?)\b", tail, re.I):
            continue
        value = _num(m.group(1))
        if 20 <= value < 5000:
            return float(value)
    return _hoa_maintenance(text)


_HOA_MAINT = re.compile(r"\bmaintenance(?:[ \t]+(?:fees?|dues|charges?|costs?))?[ \t]*(?:is|are|of|:|=|-|\u2013)*[ \t]*(?:about|around|approx\.?|approximately|roughly|est\.?|estimated|~)?[ \t]*\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?(?!\d|,\d)"
                        r"[ \t]*(/[ \t]*\w+|per[ \t]+\w+|a[ \t]+(?:month|year)|each[ \t]+(?:month|year)|monthly|annual\w*|yearly|mo\b\.?)?", re.I)


def _hoa_maintenance(text: str) -> float | None:
    """Cycle 25: a condo's "Maintenance fee: $325 a month" is its monthly HOA when the listing gives no other HOA figure. Needs a monthly or yearly marker
    after the amount; a lawn, garage or other named maintenance fee, a one-time, optional or seller-paid one, and an amount with no period are not read.
    A yearly amount is divided by 12."""
    for m in _HOA_MAINT.finditer(text):
        per = (m.group(2) or "").lower()
        if not per:  # "Monthly maintenance fee is $325", "Annual maintenance fee: $3,900"
            per = (re.search(r"\b(monthly|annual\w*|yearly)[ \t]+(?:condo[ \t]+|hoa[ \t]+)?$", text[max(0, m.start() - 20):m.start()], re.I) or [None, ""])[1].lower()
        if re.search(r"month|mo\b|/\s*m\b", per):
            divisor = 1
        elif re.search(r"year|yr|annual", per):
            divisor = 12
        else:
            continue
        before = text[max(0, m.start() - 20):m.start()]
        seg_start = max(text.rfind(".", 0, m.start()), text.rfind("\n", 0, m.start()), text.rfind(";", 0, m.start())) + 1
        seg_end = [i for i in (text.find(".", m.end()), text.find("\n", m.end()), text.find(";", m.end())) if i != -1]
        seg = text[seg_start:min(seg_end) if seg_end else len(text)]
        if re.search(r"\b(?:garage|lawn|yard|pool|parking|pest|snow|road|home|house|property|unit|pet|move[- ]in|boat|storage|equipment|vehicle|car)[ \t]+$", before, re.I) \
                or re.search(r"\boptional\b|\bone[- ]time\b|\bseller|\bspecial\b|\bassessment|\bat[ \t]+closing\b|\bif[ \t]+(?:you|desired|wanted)\b|\bby[ \t]+request\b|\bwaived?\b|\bno[ \t]+maintenance\b|\bcost[ \t]+of[ \t]+maintenance", seg, re.I):
            continue
        value = _num(m.group(1)) / divisor
        if 20 <= value < 5000:
            return round(value, 2)
    return None


def _tax(text: str) -> float | None:
    """Property tax as a yearly figure. "Taxes: $4,100 per year", "property taxes approx $4,100/yr", "$342/mo taxes"."""
    amt = r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?\s*(/\s*\w+|per\s+\w+|a\s+(?:month|year)|\w+ly|annual\w*)?"
    m = re.search(r"\b(?:(?:property|real[ \t]+estate) )?tax(?:es)?(?:[ \t]*\((?:(?:tax[ \t]+)?(?:year[ \t]+)?20\d\d|annual|yearly|per[ \t]+year|last[ \t]+year)\))?(?:\s+annual amount|\s+paid|\s+\(annual\)|\s+(?:bill|amount|payment|levy))?(?:[ \t:\-=]|approx(?:imately|\.)?|about|around|roughly|typically|usually|generally|on average|averag\w+|est(?:imated|\.)?|~|\b(?:are|is|was|were|runs?|ran|totals?|totaled|at|of)\b|\bcomes?[ \t]+(?:to|in[ \t]+at)\b){0,10}" + amt, text, re.I)
    if not m:
        m = re.search(amt + r"\s*(?:in\s+)?(?:property\s+)?tax(?:es)?\b", text, re.I)
    if not m:
        return None
    value, per = _num(m.group(1)), (m.group(2) or "").lower()
    if re.search(r"mo|month", per):
        value *= 12
    return round(value, 2) if 100 <= value <= 200000 else None


_NOSUFFIX = re.compile(r"(?<![\w$.,/#-])(\d{1,6})[ \t]+((?:(?:[NSEW]{1,2}|North|South|East|West)\.?[ \t]+)?[A-Z][A-Za-z.'-]*(?:[ \t]+[A-Z][A-Za-z.'-]*){0,2})\b")
_ADDR_NOCOMMA = re.compile(r"(?<![\w$.,/#-])(\d{1,6}[ \t]+(?:[NSEW]{1,2}\.?|North|South|East|West)[ \t]+([A-Z][A-Za-z'-]+))[ \t]+([A-Z][A-Za-z.'-]+(?:[ \t]+[A-Z][A-Za-z.'-]+)?)[ \t]+([A-Z]{2})\b(?=[ \t]*(?:[|\n,.;]|$))")
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
        if set(words) & _NOSUFFIX_BAD or set(words) & _PARKING_ADDRESS_WORDS:
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
    wm = re.match(r"(?:apt|apartment|unit|suite|ste)\b\.?[ \t]*#?[ \t]*(\S.*)$", u, re.I)
    if wm or str(unit).strip().startswith("#"):  # the unit kept its word: "Unit 12", "Apt 2", "#5"
        bare = wm.group(1) if wm else u
        if re.search(r"(?:\b(?:apt|apartment|unit|suite|ste|no)\b\.?[ \t]*#?[ \t]*|#[ \t]*)" + re.escape(bare) + r"(?![\w-])", street, re.I):
            return street
        return f"{street} {str(unit).strip()}".strip()
    if re.search(r"(?:\b(?:apt|apartment|unit|suite|ste|no)\b\.?[ \t]*#?[ \t]*|#[ \t]*)" + re.escape(u) + r"(?![\w-])", street, re.I):
        return street
    return f"{street} #{u}".strip()


_TRAILING_UNIT = re.compile(r"[ \t]*(?:[|,][ \t]*)?(?:\b(?P<word>apt|apartment|unit|suite|ste)\b\.?[ \t]*#?|(?P<hash>#))[ \t]*([A-Za-z]?\d{1,5}[A-Za-z]?(?:-\d{1,3})?|[A-Za-z])[ \t]*$", re.I)
_UNIT_WORDS = {"apt": "Apt", "apartment": "Apt", "unit": "Unit", "suite": "Suite", "ste": "Suite"}


def split_address_unit(address: Any, unit: Any = None, keep_word: bool = False) -> tuple[str, str]:
    """An address passed with its unit in it ("12 SPRUCE LANE | APT B", "210 Beck St Apt 2", "88 E Lincoln St #5") gives (street, unit): the unit moves
    to its own field, and when the unit field already holds it, it is not said twice. A unit that differs from the one in the line is left alone.
    With keep_word, a unit taken from the line keeps its word ("Unit 12", "Apt 2", "#5"); a unit the caller passed is kept as they wrote it."""
    street, u = str(address or "").strip(), str(unit or "").strip().lstrip("#").strip()
    given = str(unit or "").strip()
    if keep_word:
        u = re.sub(r"^(?:apt|apartment|unit|suite|ste)\b\.?[ \t]*#?[ \t]*", "", given, flags=re.I).lstrip("#").strip()
    m = _TRAILING_UNIT.search(street)
    if not m or not _unit_ok(m.group(3)) or len(street[:m.start()].strip()) < 4:
        return street, given
    inside = m.group(3)
    if u and u.lower() != inside.lower():
        return street, given
    if given:
        return street[:m.start()].strip(" ,|"), given if keep_word else u
    if keep_word:
        word = _UNIT_WORDS.get((m.group("word") or "").lower())
        inside = f"{word} {inside}" if word else f"#{inside}"
    return street[:m.start()].strip(" ,|"), inside


def split_full_address(address: Any, unit: Any = None, city: Any = None, state: Any = None, zip_code: Any = None) -> dict[str, str]:
    """A whole address line ("88 N Mattis Ave, Champaign, IL 61821", "88 E Lincoln St #5, Columbus, Ohio 43201") gives its parts:
    address (street only), unit (with its word when the line had one), city, state (two letters) and zip. What the caller passed
    on its own wins; a tail that names another city, state or ZIP than the caller's is left alone. Parts that are not found are
    left out."""
    street = " ".join(str(address or "").split())
    out: dict[str, str] = {}
    c0, s0, z0 = (str(x or "").strip() for x in (city, state, zip_code))
    if s0 and state_code(s0):
        out["state"] = state_code(s0)
    elif s0:
        out["state"] = s0
    if c0:
        out["city"] = c0
    if z0:
        out["zip"] = z0
    if "," in street:
        # the city, state and ZIP start after the first comma that is followed by something that is not a unit
        pieces = [x.strip() for x in street.split(",")]
        for i in range(1, len(pieces)):
            rest = ", ".join(pieces[i:])
            mt = re.fullmatch(r"(?P<city>[A-Za-z][A-Za-z.' -]*?)(?:,[ \t]*|[ \t]+)(?P<state>[A-Za-z]{2}|" + _STATE_NAME_RE + r")\.?(?:,?[ \t]*(?P<zip>\d{5})(?:-\d{4})?)?", rest, re.I)
            if not mt or not state_code(mt.group("state")) or re.match(r"(?:apt|apartment|unit|suite|ste|#)", mt.group("city"), re.I):
                continue
            tc, ts, tz = mt.group("city").strip(), state_code(mt.group("state")), mt.group("zip") or ""
            if (c0 and tc.lower() != c0.lower()) or (out.get("state") and ts != out["state"]) or (z0 and tz and tz != z0):
                break  # it names another place than the caller did: leave the line alone
            street = ", ".join(pieces[:i])
            out.setdefault("city", tc)
            out["state"] = ts
            if tz:
                out.setdefault("zip", tz)
            break
    street, u = split_address_unit(street, unit, keep_word=True)
    out["address"] = street
    if u:
        out["unit"] = u
    return out


def _city_after_street(text: str, street: str) -> str:
    """"FOR RENT - 2207 Philo Rd, Urbana - 1BR": a city right after the street, ended by a dash, a bar, a comma or the line end, with no state."""
    at = text.find(street)
    if at < 0:
        return ""
    m = re.match(r"(?:[ \t]+(?:" + _UNIT + r"))?[ \t]*,[ \t]*(?P<city>[A-Z][A-Za-z.'-]+(?: [A-Z][A-Za-z.'-]+){0,2})[ \t]*(?=$|\n|[|,.\u2013\u2014]|[ \t]-[ \t])", text[at + len(street):at + len(street) + 80], re.M)
    if not m:
        return ""
    city = m.group("city").strip()
    if _NOT_A_PLACE_WORD.search(city) or _FEATURE_WORD.search(city) or _PROPERTY_NOUN.search(city) or city.lower() in _UI_WORDS \
            or {w.lower().strip(".") for w in city.split()} & (_NOT_STREET_WORDS | _CITY_STOP):
        return ""
    return city


_CITY_STOP = {"unit", "apt", "apartment", "suite", "call", "text", "email", "contact", "near", "walk", "close", "washer", "dryer", "garage",
              "parking", "heat", "water", "gas", "electric", "deposit", "rent", "lease", "tour", "showing", "view", "built", "pool", "gym"}


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
        parts = street.split()
        words = {w.lower().strip(".,") for w in parts[1:-1]}
        if "sq" in words and re.fullmatch(_STREET, parts[-1].strip(".,"), re.I) and parts[-2].lower().strip(".,") == "sq":
            words.discard("sq")  # cycle 24: "4100 Easton Sq Pl": Sq is part of the street name when a suffix follows it
        if words & _NOT_STREET_WORDS or words & _PARKING_ADDRESS_WORDS or words & _ADDRESS_NOT_NAME:
            continue
        candidates.append((street, m.group(2) if _unit_ok(m.group(2)) else None, m.end()))
        break
    if not candidates:
        bare = _address_no_suffix(text)
        if bare:
            candidates.append((bare[0], None, bare[1]))
    if not candidates and "address" not in out:
        nm = _ADDR_NOCOMMA.search(text)  # "| 4600 N Broadway Chicago IL |": a direction, one street word, then the city and the state
        if nm and nm.group(4) in _STATES and not ({w.lower() for w in nm.group(2).split()} & (_NOSUFFIX_BAD | _PARKING_ADDRESS_WORDS)):
            out["address"] = " ".join(nm.group(1).split())
            out["city"], out["state"] = nm.group(3), nm.group(4)
    for street, unit_in, end in candidates:
        out["address"] = street
        if unit_in:
            out["unit"] = unit_in
        tail = text[end:end + 120].replace("|", ",")  # "APT 402 | CHICAGO, IL": a pipe is a comma here
        cm = re.match(r"[ \t]*(?:,|\n)?[ \t]*(?:(?i:" + _UNIT + r")[ \t]*(?:,|\n)?[ \t]*)?([A-Z][A-Za-z.'-]+(?: [A-Z][A-Za-z.'-]+){0,3}),?[ \t]+([A-Z]{2})(?:,?[ \t]+(\d{5})(?:-\d{4})?)?\b", tail)
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
                lead = re.search(r"(?<![\w$.,/#-])(\d{1,6}[ \t]+(?:[NSEW]{1,2}\.?[ \t]+)?)$", text[:m.start()])
                if lead:  # "4700 N Broadway Chicago IL 60640": the first word of the "city" is the street name
                    words = m.group(1).split()
                    if len(words) == 2:
                        out.setdefault("address", " ".join((lead.group(1) + words[0]).split()))
                        out["city"] = words[1]
                    else:
                        out.pop("city")  # which words are the street and which the city is not clear, so the city is left empty
                break
    if "city" not in out:
        for m in _CITY_LINE_NAME.finditer(text):  # "Columbus, Ohio 43201"
            if m.group(1)[:1].isupper() and m.group(1) not in ("Ohio",):
                out["city"], out["state"], out["zip"] = m.group(1), state_code(m.group(2)), m.group(3)
                break
    if "city" not in out:
        label = re.search(r"\b(?:location|city|area|neighborhood)\s*[:\-]\s*", text, re.I)
        scan = text[label.end():label.end() + 80] if label else text
        for m in _CITY_STATE.finditer(scan):
            if m.group(2) in _STATES and not re.match(r"(?:Rent|Price|Beds?|Baths?|Bed|Bath|Sq|Unit|Apt)$", m.group(1)):
                out["city"], out["state"] = m.group(1), m.group(2)
                break
    if "city" not in out and "address" in out:
        bare = _city_after_street(text, out["address"])
        if bare:
            out["city"] = bare
            same = re.search(r"\b" + re.escape(bare) + r",?[ \t]+([A-Z]{2})\b", text)
            if same and same.group(1) in _STATES:
                out["state"] = same.group(1)  # the same city is written with its state somewhere else in the listing
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
                           r"rentals?|rental listing|for rent|for lease|listing|new listing|just listed)(?:[ \t]+(?:style|listing|post|ad))?[ \t]*(?::|[-|\u2013\u2014])[ \t]+(?=\S)", re.I)
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
    line = " ".join(line.split()).strip(" ,;:-|/\\\u2013\u2014")
    line = re.sub(r"[ \t]*(?:[-|:,\u2013\u2014][ \t]*)?\b(?:starting(?:[ \t]+at)?|starts?[ \t]+at|from|only|just|asking(?:[ \t]+price)?|(?:monthly[ \t]+)?rent(?:al)?(?:[ \t]+(?:is|of))?[ \t]*[:=]?|priced?(?:[ \t]+at)?|price[ \t]+is|for[ \t]+only)[ \t]*$", "", line, flags=re.I)
    line = re.sub(r"\s+for\s+(?:rent|lease)$", "", line, flags=re.I)
    line = re.sub(r"(?:\s+(?:a|an|the|and|with|of|in|at|for|to|incl|inc))+\.?$", "", line, flags=re.I)
    return _word_cut(line.strip(" ,;:-|/\\\u2013\u2014"), 70)


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


_NOT_A_PLACE_WORD = re.compile(r"\b(?:ok|okay|call|text|now|obo|firm|negotiable|pets?|no|available|utilities|incl\w*|free|off|deal|only|furnished|sublease|new|great|nice|cute)\b", re.I)


def _paren_area(text: str) -> str:
    """"Craigslist - 2br - $1,200 (Linden)": the area in brackets at the end of a priced headline line."""
    for raw in text.splitlines()[:3]:
        line = " ".join(raw.strip(" \t|*#").split())
        if "$" not in line:
            continue
        m = re.search(r"\(([A-Z][A-Za-z .'-]{2,30})\)\s*$", line)
        if m and not _NOT_A_PLACE_WORD.search(m.group(1)) and not _is_fact_line(m.group(1)) or (m and m.group(1).count(" ") == 0 and not _NOT_A_PLACE_WORD.search(m.group(1))):
            return m.group(1).strip()
    return ""


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
        line = _LABEL_PREFIX.sub("", line, count=1)  # "Apartments.com style: Maple Court Apartments": the site label is not the name
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
    # "Studio-1BR Prairie Commons from $1,299 - $1,420": a plan range in front of the name and a "from" price after it are facts, not the name
    lead = re.match(r"(?:studio|\d{1,2}[ \t]*(?:br|bd|bed(?:room)?s?))[ \t]*[-/\u2013][ \t]*(?:studio|\d{1,2}[ \t]*(?:br|bd|bed(?:room)?s?))[ \t]+(?=[A-Z])", out, re.I)
    if lead:
        rest = re.sub(r"[ \t]+(?:from|starting[ \t]+at|starts[ \t]+at|as[ \t]+low[ \t]+as)[ \t]*\$[^\n]*$", "", out[lead.end():], flags=re.I).strip(" -|:,")
        if len(rest) >= 3 and re.search(r"[A-Za-z]{3}", rest) and not _is_fact_line(rest):
            out = rest
    for _ in range(3):
        cut = _TITLE_SUFFIX.sub("", out).strip(" -|:,")
        if cut == out or len(cut) < 3:
            break
        out = cut
    # "2 bedroom duplex 1400 dollars a month": a price written in words is a fact, not part of the name
    cut = re.sub(r"[ \t,\-|]*\$?\d[\d,]*[ \t]*(?:dollars|bucks)\b(?:[ \t]*(?:a|per|/)[ \t]*(?:month|mo)\b)?.*$", "", out, flags=re.I).strip(" -|:,")
    cut = cut if len(cut) >= 3 else out
    # cycle 24: "Hilltop 2BR Condo 2 bed 1 bath": the beds and baths said a second time at the end are facts the name already has
    again = _TITLE_BEDBATH_AGAIN.search(cut)
    if again and _TITLE_BED_CUE.search(cut[:again.start()]) and len(cut[:again.start()].strip(" -|:,")) >= 3:
        cut = cut[:again.start()].strip(" -|:,")
    return cut


_TITLE_BED_CUE = re.compile(r"\b\d(?:\.\d)?[ \t]*(?:br|bd|bdrm|bed(?:room)?s?)\b|\b[1-4][xX][1-3]\b|\b(?:one|two|three|four)[- ]bed", re.I)
_TITLE_BEDBATH_AGAIN = re.compile(r"[ \t,/|]+(?:\d(?:\.\d)?[ \t]*(?:bed(?:room)?s?|bdrms?|bds?|brs?)|studio)(?:[ \t,/|]+\d(?:\.\d)?[ \t]*(?:bath(?:room)?s?|bths?|ba)\b)?[ \t]*$"
                                  r"|[ \t,/|]+\d(?:\.\d)?[ \t]*(?:bath(?:room)?s?|bths?|ba)[ \t]*$", re.I)
_ALL_CAPS_KEEP = ("LLC", "II", "III", "IV", "NE", "NW", "SE", "SW", "UIUC", "BR", "BA", "HOA", "USA", "UW", "UC", "MIT", "NYC", "SF", "LA")
_LABEL_LINE = re.compile(
    r"^(?:rent|monthly rent|deposit|security deposit|price|asking price|list price|taxes|tax|property tax(?:es)?|hoa(?: fees?| dues)?|pets?|pet policy|"
    r"pet rent|pet fee|utilities|utils|fees?|application fee|admin fee|parking|lease|lease term|term|available|availability|laundry|sq\.? ?ft|"
    r"square feet|beds?|baths?|contact|phone|year built|move[- ]in|cost|total|amenities|features|description|location|address|city|"
    r"neighborhood|heat|cooling|appliances|rates?|pricing|prices|details|overview|summary|info|information|about|highlights)\b[ \t]*(?::|=|\$|-[ \t])", re.I)
_LABEL_NUMBER = re.compile(r"^(?:rent|deposit|security deposit|price|taxes|hoa|fees?)\b[ \t]+[\d$]", re.I)
_MONEY_LINE = re.compile(r"^(?:\$|\u20ac|\u00a3|\d[\d,.]*[ \t]*(?:/|per|a)[ \t]*(?:mo|month)|\d[\d,.]*[ \t]*(?:dollars|bucks)\b)", re.I)
_RULE_LINE = re.compile(r"^seller(?:'s)?[ \t]+(?:to|will|pays?|concessions?|credits?|contribut\w*)\b|^no[ \t]+(?:smoking|pets?|dogs?|cats?|animals?|section[ \t]*8|vouchers?|students?|roommates?|co-?signers?|evictions?|felon\w*)\b|"
                        r"^(?:first|last|one|two|three|\d{1,2})(?:st)?[ \t]+(?:month|week)s?\b[^.\n]{0,15}\bfree\b", re.I)
_PET_LINE = re.compile(r"^(?:no[ \t]+)?(?:pets?|dogs?|cats?|animals?)\b", re.I)
# a policy or money sentence is never the name of a place ("Landlord pays all utilities", "Deposit one month", "Tenant pays electric", "Utilities included")
_POLICY_LINE = re.compile(r"^(?:(?:landlord|owner|owners|tenant|tenants|renter|renters|resident|residents)(?:'s)?[ \t]+(?:pays?|paying|covers?|is|are|responsible|provides?|total)\b"
                          r"|(?:security[ \t]+|refundable[ \t]+)?deposits?\b|(?:all[ \t]+)?utilit(?:y|ies)\b|(?:application|admin|move[- ]in|pet|parking|lease|rent)[ \t]+(?:fees?|terms?|total|due|cost|is|are)\b|lease[ \t]+(?:begins?|starts?|runs?|ends?|length|period)\b"
                          r"|(?:water|sewer|trash|gas|electric(?:ity)?|heat|internet|wifi|cable)\b[^.\n]{0,40}\b(?:included|extra|separate|not included|paid|billed)\b"
                          r"|available[ \t]+(?:now|immediately|today|\d|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*)", re.I)


_HEDGE_END = re.compile(r"\b(?:about|around|approx\.?|approximately|roughly|avg\.?|average|estimated|est\.?|costs?|totals?|due|is|are|of)[ \t:=~]*$|[:=~][ \t]*$", re.I)
_HEDGE_ONLY_END = re.compile(r"\b(?:about|around|approx\.?|approximately|roughly|avg\.?|average|estimated|est\.?)[ \t:=~]*$", re.I)


def _money_line_cut(line: str) -> bool:
    """A money line with its amount cut off ("Quarterly utility bill about", "Quarterly utility bill about $210"): never a title."""
    m = _PRICE_IN_TITLE.search(line)
    if m:
        before = line[:m.start()]
        if len(before.split()) >= 5 and re.search(r"[,|\u2013\u2014-][ \t]*(?:monthly[ \t]+)?(?:rent|price|asking)[ \t]*[:=]?[ \t]*$", before, re.I):
            return False  # "Hazel Lane 3bd townhouse in Menlo Park - rent: $2,390": a headline that ends in its rent, not a cut-off money line
        return bool(_HEDGE_END.search(line[:m.start()].rstrip()) or _HEDGE_END.search(line[:m.start()]))
    return bool(_HEDGE_ONLY_END.search(line.strip()))


_DATE_ONLY = re.compile(r"^(?:(?:lease|term|dates?|available|move[- ]?in)[ \t:]*)?(?:" + re.sub(r"\(\?P<\w+>", "(?:", _DATE) + r")(?:[ \t]*(?:to|through|thru|until|-|\u2013|\u2014)[ \t]*(?:" + re.sub(r"\(\?P<\w+>", "(?:", _DATE) + r"))?[ \t.]*$", re.I)


def _date_only_line(line: str) -> bool:
    """A line that is only a date or a date range ("Aug 1 2027 to Jul 31 2028"): never a title."""
    return bool(_DATE_ONLY.match(line.strip()))


# a section label is never the name of a place ("Rent. 4120 Indianola Ave", "Pricing: 2BR Plan A ...")
_SECTION_LABELS = frozenset("""rent rental rentals pricing price prices rates rate details description overview summary info information about amenities features
contact location availability lease terms pets parking fees utilities floor plans floorplans highlights""".split())
_GREETING_TITLE = re.compile(r"^(?:hi|hello|hey|hiya|howdy|dear|greetings|good (?:morning|afternoon|evening)|welcome|attention)\b", re.I)


_NAME_STOP_WORDS = re.compile(r"\b(?:beautiful|charming|spacious|sunny|cozy|newly|new|renovated|large|lovely|gorgeous|brand|luxury|nice|great|huge|amazing|updated|modern)\b", re.I)


_BED_CUE = re.compile(r"\b\d(?:\.\d)?[ \t]*(?:br|bd|bdrm|bed(?:room)?s?)\b|\bstudio\b|\b[1-4][xX][1-3]\b|\b(?:one|two|three|four)[- ]bed", re.I)
_FEE_HEAD = re.compile(r"\b(?:fees?|deposits?|dues|control|permits?|net effective|billed|late|locker|valet|assessments?|utilities|concession|free)\b", re.I)


def _fee_or_policy_head(line: str) -> bool:
    """True when a line reads like a fee, a money rule or a policy ("Pest control $8, locker $10", "Net effective rent $1,380", "Condo fee $240
    paid by owner"), whatever follows: such a line is never the name of a place. A line that names its beds ("2BR Rent Special") is a headline."""
    if _BED_CUE.search(line):
        return False
    head = re.split(r"\$|[:;]|[ \t]+[-\u2013\u2014][ \t]+|[ \t]\|[ \t]", line, maxsplit=1)[0]
    return (bool(_FEE_HEAD.search(head)) or bool(re.match(r"(?:monthly[ \t]+)?rent\b|(?:just[ \t]+)?(?:reduced|price[ \t]+(?:reduced|drop|cut)|new[ \t]+price)\b", head, re.I))) and len(head.split()) <= 6


def _chatty_title(title: str, found: dict[str, Any]) -> str:
    """A greeting or a long sentence that holds the street address ("Hi Beautiful newly built 1 bed 1 bath at 88 Prospect Ave Champaign")
    is not a name: the street address is the title. A real name in front of the address ("Pilsen Courtyard 3BR/2BA 1700 S Racine Ave") stays."""
    addr = str(found.get("address") or "")
    if not addr:
        return title
    if _GREETING_TITLE.match(title):
        return addr
    at = title.lower().find(addr.lower())
    if at >= 0:
        others = title[:at].split() + title[at + len(addr):].split()
        if len(others) >= 7:
            return addr
    return title


def fallback_title(found: dict[str, Any]) -> str:
    """No name and no street address in the paste: "2 bed in Linden", else "2 bed place", else "Rental in Linden". Used when a pasted listing is saved and the reader found no name and no street address."""
    city = str(found.get("city") or "").strip()
    beds = found.get("beds")
    if isinstance(beds, (int, float)) and not isinstance(beds, bool) and 0 <= beds <= 20:
        what = "Studio" if beds == 0 else f"{beds:g} bed"
        return f"{what} in {city}" if city else (what if beds == 0 else f"{what} place")
    return f"Rental in {city}" if city else ""


_PLAN_CUE = re.compile(r"\b\d(?:\.\d)?[ \t]*(?:br|bd|bdrm|bed(?:room)?s?|ba|bath(?:room)?s?)\b|\bstudio\b|\b\d[xX]\d\b|\b\d[ \t]*/[ \t]*\d(?:\.\d)?\b|\b(?:one|two|three|four)[- ]bed", re.I)
_LEAD_STOP_WORDS = frozenset("rent rental price beds bedroom bedrooms bath baths bathroom bathrooms for the and with near ago available now apartment unit asking from first month months only".split())
_LEAD_BAD_START = re.compile(r"^(?:rent|rental|price|asking|pets?|parking|deposit|utilities|available|beds?|baths?|unit|apt|for|contact|call|text|email|posted|updated|fees?|year built|dom|sqft|sq)\b", re.I)
_LEAD_SITE_PREFIX = re.compile(r"^(?:zillow|craigslist|trulia|redfin|hotpads|zumper|facebook marketplace|fb marketplace|facebook|marketplace|apartments\.com|realtor\.com)(?:[ \t]*[-:|\u2013\u2014][ \t]*|[ \t]+)", re.I)
_LEAD_PRICE_PREFIX = re.compile(r"^\$[\d,.]+[kK]?(?:/mo(?:nth)?)?[ \t]*[-|\u2013\u2014:,][ \t]*")
_LEAD_CORRECTION_PREFIX = re.compile(r"^[^?]{1,30}\?[ \t]*(?:no|nope)\b[ \t]*[-:,\u2013\u2014]?[ \t]*", re.I)
_LEAD_SEG_END = re.compile(r"[ \t]*(?:\.(?=\s|$)|!+|;|\||\u2022|\u00b7|[ \t]~[ \t]|[ \t][-\u2013\u2014][ \t]+(?=\$|\d|(?:was|now|reduced|asking|from)\b)|,[ \t]*(?=\$)|[ \t]+(?=\$))")


def _lead_title(text: str, found: dict[str, Any], current: str) -> str:
    """Cycle 22: a descriptive name for a place whose title is missing, is only its street address, or is a line about utilities or fees: the
    first line's lead words that hold a plan and a neighbourhood or kind of place ("Avondale 3BR 2BA", "2 BR / 2 BA Condo in Victorian Village",
    "3 bd / 2 ba ranch", "Single family home, 3 beds, 2 baths"). Every title in a search is then built the same way. '' keeps the title as it is."""
    addr = str(found.get("address") or "").split(",")[0].strip()
    cur = (current or "").strip()
    if cur and not (addr and cur.lower() == addr.lower()) and not _POLICY_TITLE_WEAK.match(cur):
        return ""
    only_address = bool(cur) and bool(addr) and cur.lower() == addr.lower()
    for raw in [x for x in text.splitlines() if x.strip()][:1]:  # the headline: the first line of the paste
        if _ai_aimed(raw):
            from .redflags import trim_at_injection
            raw = trim_at_injection(raw)  # the words in front of text aimed at an AI tool can still be a name
            if _ai_aimed(raw):
                continue
        line = " ".join(raw.strip(" \t|\u2022\u00b7*#>").split())
        line0 = line
        priced_first = bool(_LEAD_PRICE_PREFIX.match(line))
        line = _LEAD_PRICE_PREFIX.sub("", line)
        line = _LEAD_SITE_PREFIX.sub("", line)
        line = _LEAD_CORRECTION_PREFIX.sub("", line)
        line = re.sub(r"^(?:\*\*|__)|(?:\*\*|__)$", "", line)
        line = _HYPE_LEAD.sub("", line)
        parts = [x for x in _LEAD_SEG_END.split(line) if x and x.strip()]
        if not parts:
            continue
        head = parts[0].strip(" ,:-")
        if re.match(r"^(?:rent|price|asking)\b", head, re.I) or _LEAD_BAD_START.match(head) or head.startswith(("$", "http", "www.")) \
                or re.match(r"^[A-Za-z][A-Za-z ]{0,15}:[ \t]", head) or re.search(r"\b(?:a|per)[ \t]+month\b|/mo\b|\$|\bk[ \t]+a[ \t]+month", head, re.I):
            continue
        rest = [x.strip(" ,:-") for x in re.split(r",[ \t]+", head)]
        title = rest[0]
        for extra in rest[1:3]:
            if _PLAN_CUE.search(title) and not re.fullmatch(r"\d(?:\.\d)?[ \t]*(?:ba|bath(?:room)?s?)", extra, re.I):
                break
            if len(title) + len(extra) > 56:
                break
            title += ", " + extra
        title = re.sub(r"[ \t]+for[ \t]+(?:rent|lease)\b", "", title, flags=re.I).strip(" ,:-")
        title = re.sub(r"[ \t]*[-\u2013\u2014]?[ \t]*\b(?:was|now|reduced|asking|from|rent|rent[ \t]+\d[\d,.]*|for[ \t]+\d[\d,.]*)$", "", title, flags=re.I).strip(" ,:-")
        if addr and addr.lower() in title.lower():
            continue
        if _ADDRESS.match(title) or not 8 <= len(title) <= 60 or not _PLAN_CUE.search(title):
            continue
        words = [w for w in re.findall(r"[A-Za-z]{4,}", _PLAN_CUE.sub(" ", title)) if w.lower() not in _LEAD_STOP_WORDS]
        if not words or _policy_title_line(title) or _fee_or_policy_head(title) or (_not_a_name(title) and not _PROPERTY_NOUN.search(title) and not _NAMED_PLAN.match(title) and not re.search(r"\b(?:near|in|at|by)[ \t]+[A-Z]", title)):
            continue
        if re.search(r"\b(?:call|text|email|contact)\b", title, re.I):
            continue
        if only_address and not _NEIGHBOURHOOD_PLAN.match(title) and not priced_first and " | " not in line0:
            continue  # over a street address only a neighbourhood and plan, or a headline that came after its price, wins
        if title.upper() == title and len([c for c in title if c.isalpha()]) >= 4:
            title = title.title()
        return _finish_title(title, text)
    return ""


_NEIGHBOURHOOD_PLAN = re.compile(r"^(?!(?:Beautiful|Cozy|Charming|Spacious|Sunny|Lovely|Gorgeous|Newly|Large|Updated|Modern|Quiet|Bright|Luxury|Amazing|Stunning|Nice|Great|Huge|Renovated|Brand|New|Cute|Clean|Big|Small|Light|Open|Lovely|Pet|Perfect|Rare|Wow|Hot|Just|Single|Tri|Two|One|Three|Studio|Corner)\b)"
                                 r"[A-Z][A-Za-z'.-]+(?:[ \t]+[A-Z][A-Za-z'.-]+){0,2}[ \t]+(?:\d(?:\.\d)?[ \t]*(?i:br|bd|bdrm|bed(?:room)?s?|ba|bath)|\d[xX]\d|\d/\d)")
_POLICY_TITLE_WEAK = re.compile(r"^(?:electric(?:ity)?|gas|water|sewer|trash|garbage|internet|wi-?fi|heat(?:ing)?|hoa|utilities|fees?|pets?|parking|deposit)\b|\bcovers?\b", re.I)


_STREET_NAME_ONLY = re.compile(r"\b(?:on|at|off|near)[ \t]+((?:[A-Z][A-Za-z.'-]+[ \t]+){1,3}(?:Dr|Drive|St|Street|Ave|Avenue|Rd|Road|Ln|Lane|Ct|Court|Blvd|Boulevard|Way|Pl|Place|Ter|Terrace|Cir|Circle)\b\.?)")


def _street_name_title(text: str, found: dict[str, Any]) -> str:
    """No name and no numbered address, but the paste names a street ("3BR/2BA SFH on Oak Knoll Dr, Menlo Park"): "3 bed on Oak Knoll Dr". '' when none."""
    m = _STREET_NAME_ONLY.search(text)
    beds = found.get("beds")
    if not m or not isinstance(beds, (int, float)) or isinstance(beds, bool) or not 0 <= beds <= 20:
        return ""
    street = m.group(1).rstrip(".").strip()
    return f"{'Studio' if beds == 0 else f'{beds:g} bed'} on {street}"


_CORRECTION_CUT = re.compile(r"[ \t.!?,;]+(?:no|nope|oops|sorry|correction|actually|wait)\b[:,!.]?(?:[ \t].*)?$|[ \t]+--.*$|[ \t]+\u2014[ \t]+.*$", re.I)
# a policy, amenity, parking or correction line is never the name of a place, even when it comes first and a street address is in the paste
_POLICY_TITLE = re.compile(
    r"\b(?:month[- ]to[- ]month|lease|leases|leasing|doorman|concierge|rooftop|fenced|fence|yard|driveway|street permit|street parking|garage|carport|parking|"
    r"pets?|dogs?|cats?|utilit\w*|deposits?|laundry|washer|dryer|dishwasher|included|allowed|tours?|appointment|tenant|landlord|owner|"
    r"credit|application|available|rent[:=]|no:|sorry|oops|correction|breeds?|restrictions?|restricted|smok\w*|weight|limits?|apply|applies|not incl\w*|prohibited|required|mandatory|"
    r"hoa|covers?|covered by|water|sewer|trash|garbage|electric(?:ity)?|internet|wi-?fi|typically|landscaping)\b", re.I)
_REAL_PLACE_NOUN = re.compile(r"\b(?:apartments?|apts?|house|home|condo|townhome|townhouse|duplex|lofts?|flats?|cottages?|bungalows?|villas?|residences?|estates?|commons|court|manor|terrace|towers?)\b", re.I)


def _policy_title_line(line: str) -> bool:
    """True for a policy, amenity, parking or correction phrase ("Month to month possible after first year", "Doorman building, rooftop", "Yard fenced on
    all sides"). A line that names its beds or a kind of place ("Cozy 2 bed with garage", "Oak Court Apartments") is a headline."""
    return bool(_POLICY_TITLE.search(line)) and not _BED_CUE.search(line) and not _REAL_PLACE_NOUN.search(line)


_HYPE_LEAD = re.compile(r"^(?:wow|omg|hurry|look|must[ \t]+see|don'?t[ \t]+miss(?:[ \t]+this)?|won'?t[ \t]+last|amazing[ \t]+deal|great[ \t]+deal|rare[ \t]+find|a[ \t]+must[ \t]+see|act[ \t]+fast|available[ \t]+now|just[ \t]+listed|new[ \t]+listing)\b[ \t!:,.\u2013\u2014-]*", re.I)


_TITLE_DECOR = re.compile(r"[*#~=_\u2022\u00b7\u2605\u2606\u2726\u2727\u2756\u25cf\u25a0\u25c6\u25ba\u25b6]+")


def strip_title_decoration(title: str) -> str:
    """Cycle 23: stars, hashes, bullets and emoji around a name are decoration ("*** Edgewater 3 bed 2 bath ***"), never part of the title. Only
    the edges lose them (a "#5" unit number inside the title stays); emoji and star symbols go from anywhere."""
    import unicodedata
    t = "".join(" " if unicodedata.category(c) in ("So", "Sk") else c for c in (title or ""))
    t = re.sub(r"[\u2605\u2606\u2726\u2727\u2756\u25cf\u25a0\u25c6\u25ba\u25b6]+", " ", t)
    t = re.sub(r"^[\s*#~=_\u2022\u00b7]+|[\s*#~=_\u2022\u00b7]+$", "", t)
    t = re.sub(r"(?:\s[*~=_]+)+(?=\s|$)", " ", t)  # a run of stars standing alone between words
    return " ".join(t.split()).strip(" ,;:-|\u2013\u2014")


def _title(text: str, found: dict[str, Any]) -> str:
    title = _clean_title(_title_raw(text, found)).strip(" ,;:-|\u2013\u2014")
    lead = _HYPE_LEAD.sub("", title)
    if lead != title and len(lead) >= 8:
        title = lead[:1].upper() + lead[1:]  # "Wow Newly renovated 2 bedroom": the shout is not part of the name
    cut = _CORRECTION_CUT.sub("", title).strip(" ,;:-|\u2013\u2014")
    if cut != title:  # "Albany Park 1x1? no 3x2": the size before the correction is the wrong one, so it goes too
        cut = re.sub(r"\s+\d+\s*x\s*\d+\s*\??$", "", cut).strip(" ,;:-|?\u2013\u2014")
    if len(cut) >= 8:
        title = cut  # "Gorgeous 3 bedroom house near Lincoln Elementary! No: rent 3,240 -- no wait": the correction is not part of the name
    if re.search(r"[a-z]", title):  # "Uptown 3 BEDROOM 2 BATH": a shouted kind-of-place word beside normal words is written normally
        title = re.sub(r"\b(?:BEDROOMS?|BATHROOMS?|BATHS?|BEDS?|APARTMENT|HOUSE|DUPLEX|TOWNHOUSE|CONDO|STUDIO)\b", lambda m: m.group(0).capitalize(), title)
    letters = [c for c in title if c.isalpha()]
    if len(letters) >= 4 and title.upper() == title:
        title = re.sub(r"\d*[A-Za-z][A-Za-z']*", lambda m: m.group(0) if m.group(0) in _ALL_CAPS_KEEP or re.fullmatch(r"\d+(?:BR|BA|BD)", m.group(0)) else m.group(0).capitalize(), title)
        title = re.sub(r"^The\b", "The", title)
    title = re.sub(r"[ \t]*[-\u2013\u2014][ \t]*(?:was|now|reduced|asking|from|starting)$", "", title, flags=re.I)  # "Pilsen 3/2 - was $3,600": the price words are not part of the name
    title = _finish_title(title, text)
    if title and _policy_title_line(title) and not _ADDRESS.match(title):
        addr = str(found.get("address") or "")
        return addr.split(",")[0] if addr else ""  # a policy, amenity or parking phrase is never the name
    if title and _fee_or_policy_head(title) and not _ADDRESS.match(title):
        addr = str(found.get("address") or "")
        return addr.split(",")[0] if addr else ""  # a fee or policy phrase is never the name: the street address, else no title
    return _chatty_title(title, found)


_FEATURE_WORD = re.compile(r"\b(?:garage|carport|laundry|w/d|w&d|washer|dryer|dishwasher|renovated|remodeled|updated|stainless|hardwood|balcony|patio|a/c|central air|parking|in[- ]unit|coin|fireplace|granite|appliances?)\b|w/d|w&d", re.I)
_PROPERTY_NOUN = re.compile(r"(?:\b|(?<=\d))(?:apartments?|apts?|house|home|condo|townhome|townhouse|duplex|studio|loft|flat|cottage|bungalow|villa|bed(?:room)?s?|br|bd|bdrm|rooms?|suite|unit [a-z0-9]+|place|lofts|residences?|community)\b", re.I)


# a brand with a plan after it ("LUXE 1x1", "Aspen 2BR") is a name, even though the rest is a bed/bath word
_PLAN_HEAD = re.compile(r"^[A-Z][A-Za-z'&.-]+(?:[ \t]+[A-Z][A-Za-z'&.-]+){0,2}[ \t]+(?:\d{1,2}[ \t]?(?i:br|bd|bed)|\d[xX]\d|(?i:studio)\b)")
_PLAN_NAME = re.compile(r"^[A-Z][A-Za-z'&.-]{2,}(?:[ \t]+[A-Za-z'&.-]+){0,2}[ \t]+(?:\d[xX]\d(?:\.\d)?|\d[ \t]?(?:br|bd|bed)\w*)$")


# a pipe part that is a bed count and a kind of place ("3 Bed Duplex Half") or a neighbourhood with its plan ("Uptown 3 BEDROOM 2 BATH") is a name
_NAMED_PLAN = re.compile(
    r"^[A-Z][A-Za-z'&-]{2,}(?:[ \t]+[A-Za-z'&-]+){0,2}[ \t]+\d(?:\.\d)?[ \t]*(?:bed(?:room)?s?|br|bd)(?:[ \t]*/?[ \t]*\d(?:\.\d)?[ \t]*(?:bath(?:room)?s?|ba))?(?:[ \t]+\$[\d,]+(?:/mo)?)?$", re.I)
_BED_NOUN_PART = re.compile(r"^\d(?:\.\d)?[ \t]*(?:bed(?:room)?s?|br|bd)[ \t]+(?:[A-Za-z]+[ \t]+)?(?:duplex|house|townhouse|townhome|condo|apartment|flat|loft|studio|cottage|bungalow)(?:[ \t]+[A-Za-z]+)?$", re.I)


def _plain_address_part(part: str, found: dict[str, Any]) -> bool:
    """A pipe part that is only the street address (with its city and state): it is the address, not the name."""
    addr = str(found.get("address") or "")
    return bool(addr) and part.lower().startswith(addr.lower()) and len(part) <= len(addr) + 40


def _feature_line(line: str) -> bool:
    """A line that only lists what the place has ("Attached 1-car garage included in rent", "Shared coin laundry in the building",
    "Newly renovated, W&D in unit, dishwasher, garage"): a feature, never the name of the place."""
    return bool(_FEATURE_WORD.search(line)) and not _PROPERTY_NOUN.search(line) and not _ADDRESS.match(line)


def _not_a_name(line: str) -> bool:
    """A line that is a field ("Rent $2", "Deposit: 1.5x rent", "Pets: dogs ok"), a money amount or a pet rule, never a title."""
    return bool(_RULE_LINE.match(line) or _PROMO_LINE.match(line) or _SITE_LINE.match(line) or _ai_aimed(line) or _LABEL_LINE.match(line) or _POLICY_LINE.match(line) or _LABEL_NUMBER.match(line) or _MONEY_LINE.match(line) or _PET_LINE.match(line)
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
    raw_lines: list[str] = []
    for one in text.splitlines()[:25]:
        if _ai_aimed(one) and not found.get("address"):
            # an instruction aimed at AI tools in front of a real heading ("Ignore previous instructions... Cedar Rise 3BR 2BA $2,200 ..."):
            # keep only a sentence that reads as a name with a plan, never the instruction
            raw_lines += [x for x in re.split(r"(?<=[.!?])[ \t]+", one) if _PLAN_HEAD.match(x.strip()) and not _ai_aimed(x)]
        else:
            raw_lines.append(one)
    for raw_line in raw_lines:
        named_part = False
        line = " ".join(_PROMO_BANNER.sub(" ", raw_line).strip(" \t|\u2022\u00b7*#").split())
        marked = bool(re.match(r"[ \t>]*(?:#{1,6}[ \t]|\*\*|__)", raw_line))  # a bold or heading line is a title, even when it ends in a full stop
        line = re.sub(r"^(?:>[ \t]*|[-+][ \t]+|\d{1,2}[.)][ \t]+)+", "", line).strip(" \t*#_") if not line.startswith("$") else line
        line = re.sub(r"^(?:actually|update|updated|correction|edit|edited|note|ps|p\.s\.)[ \t]*[:,][ \t]*(?=\S)", "", line, flags=re.I)  # "Actually: Campustown Flats 1x1"
        if _ai_aimed(raw_line) or _ai_aimed(line):
            continue
        if " | " in line or len(re.findall(r"[ \t]~[ \t]", line)) >= 2:  # "LAKESHORE VILLAS | Sunny 3BR/2BA house, fenced yard": the first part that is not a fact is the name
            parts = [x.strip() for x in (re.split(r"[ \t]\|[ \t]", line) if " | " in line else re.split(r"[ \t]~[ \t]", line))]
            ok = [x for x in parts if len(x) >= 3 and not _not_a_name(x) and (not _is_fact_line(x) or _PLAN_NAME.match(x) or _NAMED_PLAN.match(x) or _BED_NOUN_PART.match(x))]
            line = next((x for x in ok if not _ADDRESS.match(x) and not _plain_address_part(x, found)), "") or (ok[0] if ok else "")
            named_part = bool(_NAMED_PLAN.match(line) or _BED_NOUN_PART.match(line))
        for _ in range(2):  # "FB Marketplace - 2 bedroom ...", "Rental: 3 Bedroom Home in Belmont": the label is not the title
            line = _LABEL_PREFIX.sub("", line, count=1)
        line = _name_segment(line)
        if not line or _not_a_name(line) or _money_line_cut(line) or _date_only_line(line) or (len(line.split()) <= 8 and _policy_title_line(line)) or (_fee_or_policy_head(line) and not (found.get("address") and found["address"].lower() in line.lower())):
            continue
        shout = line
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
        if found.get("address") and found["address"].lower() in line.lower() and _is_fact_line(line) and not _PLAN_NAME.match(line):
            return found["address"]  # "Beautiful updated 2 bed 1 bath in Beechwold, 4410 Indianola Ave, Columbus": a headline with an address
        if re.fullmatch(r"[\d\s$,./\-+:()]+", line) or (_is_fact_line(line) and not _PLAN_NAME.match(line) and not named_part and not re.search(r"\b(?:apartment|condo|house|townhome|townhouse|duplex|loft)\b", line, re.I)):
            continue
        if re.search(r"\b(?:call|text|email|contact|apply|posted|updated|listed|published)\b.*(?:\d{3}|ago|on\b)", low) \
                or re.search(r"\b(?:call|text|email|message|msg|dm|reach|contact)\s+(?:me|us)\b|\bwhatsapp\b", low):
            continue  # "Nice place, text me" is a contact line, not a name
        if re.fullmatch(r"[A-Za-z .'-]+,\s*[A-Z]{2}(?:\s+\d{5})?", line):  # just "Champaign, IL"
            continue
        if len(line.split()) >= 6 and line.endswith((".", "?")) and not marked:
            lead = re.split(r"(?<=[a-z])!+[ \t]", shout, maxsplit=1)[0]
            if lead != shout and 2 <= len(lead.split()) <= 8 and not re.search(r"\d", lead) and _PROPERTY_NOUN.search(lead) and not _fee_or_policy_head(lead) and not _not_a_name(lead):
                return lead  # "Cozy duplex in Hilltop! 2 bedrooms, 1 bath. ...": the shout in front is the headline
            continue  # a sentence, not a name
        if marked and line.endswith("."):
            line = line[:-1].rstrip()
        head = re.split(r"(?<=[a-z])(?<!\bincl)(?<!\bapt)(?<!\bbldg)[.!]\s", line)[0]
        if head.lower().strip(" .:") in _SECTION_LABELS:
            if found.get("address") and found["address"] in line:
                return found["address"]  # "Rent. 4120 Indianola Ave, Call for price": the label is not the name
            continue
        return head
    addr = found.get("address", "")
    return addr.split(",")[0] if addr else ""


# --------------------------------------------------------------------------- the entry point
def _try(fn: Callable[[], Any]) -> Any:
    try:
        return fn()
    except Exception:  # a field it can't read is simply left out
        return None


def _one_pet_household(pet_kind: Any, pet_count: Any) -> bool:
    """True when the search says the household has exactly one pet (a cat or a dog, count 1). An unknown count is not one pet."""
    try:
        n = int(float(pet_count)) if pet_count not in (None, "") and not isinstance(pet_count, bool) else None
    except (TypeError, ValueError):
        n = None
    return n == 1 and str(pet_kind or "").strip().lower() in ("cat", "dog")


_FIRST_PET_FREE = re.compile(r"(?:\b(?:not|never|isn'?t|is[ \t]+not|aren'?t|are[ \t]+not|won'?t[ \t]+be)[ \t]+(?:charged|applied|collected|assessed|due|required)|\b(?:waived|free|exempt|no[ \t]+(?:charge|cost|fee))|\bwe[ \t]+(?:waive|don'?t[ \t]+charge)|\bwaiv\w+)"
                            r"[^.;\n|$]{0,25}?\b(?:for|on|the|with)[ \t]+(?:the[ \t]+|your[ \t]+)?(?:1st|first|one)[ \t]+(?:pet|dog|cat|animal)\b"
                            r"|\b(?:1st|first)[ \t]+(?:pet|dog|cat|animal)[ \t]+(?:is[ \t]+|are[ \t]+|rides[ \t]+)?(?:free|waived|exempt|no[ \t]+(?:charge|cost|fee)|not[ \t]+charged|without[ \t]+(?:a[ \t]+)?(?:charge|pet[ \t]+rent|fee))", re.I)


def _pet_rent_first_free(text: str, amount: float) -> bool:
    """Cycle 26: "$40/mo pet rent not charged for first pet", "pet rent $40, first pet free": the amount is a pet rent the listing waives for the
    first pet only. True when the sentence that gives this pet rent says so."""
    amt = f"{amount:.0f}"
    for sent in re.split(r"(?<!\d)[.;!?](?:\s|$)|\n|\|", text):
        if re.search(r"\$\s?" + amt + r"(?!\d)", sent) and re.search(r"\bpets?\b|\bdogs?\b|\bcats?\b", sent, re.I) and _FIRST_PET_FREE.search(sent):
            return True
    return False


def _pet_count_for_rent(pet_kind: Any, pet_count: Any) -> int | None:
    """How many pets the search has: its count, 2 for "both", 1 for a cat or a dog with no count, None when the search says nothing."""
    try:
        n = int(float(pet_count)) if pet_count not in (None, "") and not isinstance(pet_count, bool) else None
    except (TypeError, ValueError):
        n = None
    if n is not None and n >= 0:
        return n
    kind = str(pet_kind or "").strip().lower()
    return {"cat": 1, "dog": 1, "both": 2}.get(kind)


_REQ_FEE_MARK = re.compile(r"\b(?:mandatory|required|compulsory|pass[- ]?through|passed[ \t]+through|billed[ \t]+monthly|must[ \t]+pay|non[- ]?optional)\b", re.I)
_REQ_FEE_LABEL = re.compile(r"\b(?:fees?|charges?|dues|surcharge|assessment|levy|hoa|pass[- ]?through|passthrough|pest|package|amenity|amenities|community|technology|tech|convenience|admin(?:istrative)?[ \t]+service|service)\b", re.I)
_REQ_FEE_SKIP = re.compile(r"\b(?:parking|garage|carport|pets?|dogs?|cats?|animals?|storage|locker|utilit\w*|electric\w*|gas|water|sewer|(?<!valet )trash(?![ \t]+valet)|garbage|internet|cable|wi-?fi|application|app|admin|deposit|move[- ]?(?:in|out)|one[- ]time|set-?up|broker|holding|key|fob|insurance|taxes|tax|closing|credit|background|screening|lease|termination|late|penalty|cleaning|reservation|processing|transfer|renewal|rent)\b", re.I)
_REQ_FEE_NOT = re.compile(r"\b(?:optional|not (?:required|mandatory)|if (?:you )?(?:want|need|choose|required)|available|waived|unless|may be|can be|upon request|per (?:use|load|visit)|per[ \t]+(?:semester|quarter|year))\b|/[ \t]*(?:yr|year)\b|\b(?:yearly|annual|annually|quarterly|semester)\b", re.I)
_REQ_FEE_PERIOD = re.compile(r"/[ \t]*mo(?:nth)?\b|\bper[ \t]+month\b|\ba[ \t]+month\b|\bmonthly\b|\beach[ \t]+month\b", re.I)


def _required_monthly_fees(text: str) -> list[tuple[str, float, bool, str]]:
    """Cycle 26: a monthly fee the listing calls mandatory, required, a pass-through or "billed monthly", by any name ("$30 mandatory pest and
    package fee", "$75 monthly HOA passthrough", "HOA pass-through $75/mo", "Technology fee $50, required"). Returns (label, amount, says_monthly,
    the clause). Fees that have their own readers (pets, parking, storage, utilities, application, deposits, one-time fees) are left out,
    and so is anything optional, yearly or per use."""
    found: list[tuple[str, float, bool, str]] = []
    for sent in re.split(r"\.(?=\s+[A-Z0-9$\"'(\-]|\s*$)|\n|;|\|", text):
        clauses = re.split(r",(?!\d{3})|\bplus\b|\band\b(?=[ \t]+\$)|\+", sent, flags=re.I)
        for i, clause in enumerate(clauses):
            ms = list(re.finditer(r"(?<![\w$])\$[ \t]?(\d{1,4}(?:\.\d\d)?)(?![\d,])", clause))
            if len(ms) != 1:
                continue
            marker_text = clause
            if not _REQ_FEE_MARK.search(marker_text) and i + 1 < len(clauses) and re.match(r"[ \t]*\(?[ \t]*(?:mandatory|required|compulsory)\b", clauses[i + 1], re.I):
                marker_text = clause + " " + clauses[i + 1]  # "Technology fee $50, required"
            if not _REQ_FEE_MARK.search(marker_text) or not _REQ_FEE_LABEL.search(clause) or _REQ_FEE_SKIP.search(re.sub(r"\bhoa\b", " ", clause, flags=re.I)) or _REQ_FEE_NOT.search(clause):
                continue
            m = ms[0]
            if re.search(r"\b(?:rent|deposit)\b[ \t:\-=]*(?:is[ \t]+)?$", clause[:m.start()], re.I):
                continue
            label = re.sub(r"[^a-z\- ]+", " ", _REQ_FEE_MARK.sub(" ", _REQ_FEE_PERIOD.sub(" ", clause[:m.start()] + " " + clause[m.end():])).lower())
            label = " ".join(label.split())
            label = re.sub(r"^(?:the|a|an|our|plus|and|also|of|is|are|monthly|per month)\s+", "", label).strip(" -")
            label = re.sub(r"\b(?:monthly|per month|mo)\b", " ", label)
            label = " ".join(label.split()) or "required fee"
            found.append((label, float(m.group(1)), bool(_REQ_FEE_PERIOD.search(marker_text)), " ".join(clause.split())))
    return found


def _money_words(v: float) -> str:
    return f"${v:,.2f}".replace(".00", "")


def _per_animal_notes(kind: str, prices: dict[str, float], pet_kind: str, out: dict[str, Any]) -> list[str]:
    """A pet charge with a price for each animal. The search's pet ("cat" or "dog") picks the one that is saved; with both pets,
    no pet or an unknown pet nothing is saved and the note names both prices."""
    key = {"fee": "pet_fee", "rent": "pet_rent", "deposit": "pet_deposit"}[kind]
    label = {"fee": "pet fee", "rent": "pet rent", "deposit": "pet deposit"}[kind]
    per = " a month" if kind == "rent" else ""
    both = f"${prices['cat']:,.0f}{per} for a cat and ${prices['dog']:,.0f}{per} for a dog"
    want = str(pet_kind or "").strip().lower()
    if want in ("cat", "dog") and want in prices:
        out[key] = _tidy_number(prices[want])
        return [f"The listing has a {label} of {both}. Your search has a {want}, so the {want} amount is saved."]
    if want == "both":
        return [f"The listing has a {label} of {both}. Your search has both, so no {label} is saved. Fill it in once you know what you will pay."]
    return [f"The listing has a {label} of {both}. The {label} is left empty because it depends on the pet. Fill in the one that applies to you."]


def parse_listing(text: str = "", url: str = "", current: dict[str, Any] | None = None, buying: bool = False, pet_kind: str = "", pet_count: Any = None) -> dict[str, Any]:
    """Pull what a pasted listing says. Returns only the fields found. ``current`` (a saved place's fields) is for
    refreshing the reader notes: what is filled there counts as placed, so the notes only hold what is still open.
    ``buying`` is True for a buy search: the listing is then a home for sale, never a rental, and the rent-only readings
    are not used. ``pet_kind`` is the search's pet ("cat", "dog", "both" or none), used to pick a pet charge priced per animal."""
    text = _scope_only_brackets(_tidy(text or ""))  # cycle 26: "(water and trash only) $60 flat" -> "water/trash $60 flat" for every reader
    text, pair_notes = _pair_bracket_figures(text)  # cycle 26: "electric and water ($40 and $35 typical)" -> each figure to its own utility
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
    gc_found, gc_unplaced = _try(lambda: _general_corrections(text, buying)) or ({}, [])  # cycle 27: one general correction step, rent here and the rest after the fee readers
    text_all = text
    other_vals = {v for f, e in gc_found.items() if f != "price" for v in (e["new"], *e["olds"])}
    if other_vals:
        # "Security deposit was $1,500, now $1,400" or "HOA was $340/mo, now $385/mo": a figure in another fact's correction is never the rent or the price,
        # so the rent readers below see the text without those figures (the other readers get the whole text back after the rent is saved)
        for f, e in gc_found.items():
            if f != "price":
                for a0, b0 in e["spans"]:
                    text = text[:a0] + " " * (b0 - a0) + text[b0:]
        price_read = (_try(lambda: _buy_price(text)) if buying else None) or _try(lambda: _price(text))
    facts: list[str] = list(pair_notes)
    price_range = _try(lambda: _rent_range(text, price_read)) if price_read and not buying else None
    saved_price = (current or {}).get("price")
    if price_range and isinstance(saved_price, (int, float)) and not isinstance(saved_price, bool) and saved_price > 0 and float(saved_price) != price_range[1]:
        # a rent the caller already saved: keep it, but say the listing gives a range (it must not look like the whole story)
        facts.append(f"The listing shows a rent from ${price_range[0]:,.0f} up to ${price_range[1]:,.0f} a month, so the saved rent may be the low end. "
                     "Ask which rent applies to the unit you want.")
        price_range = None
    fp_all = _try(lambda: _floor_plan_prices(text)) or [] if not buying else []
    fp_beds = _try(lambda: _beds(text)) if fp_all else None
    if price_range:
        fp_in = {v for b, _bt, v, st in fp_all if fp_beds is not None and b == fp_beds and not st and price_range[0] <= v <= price_range[1]}
        if len(fp_in) == 1 and price_read in fp_in:
            # cycle 21: "$1,425 - $1,610 | 2 Beds ... Floor plan 2x1: $1,425": the floor plan for the listing's own size is the rent
            facts.append(f"The listing gives a rent range of ${price_range[0]:,.0f} to ${price_range[1]:,.0f} a month. The rent saved is the {fp_beds:g} bed floor plan, "
                         f"${price_read:,.0f}. Ask if the unit you want is a different size.")
            price_range = None
    if price_range:
        # "Rent from $1,299 - $1,650 / mo": the listing gives a range, so no single rent is saved (unknown beats wrong).
        # cycle 26: a narrow range (the high figure at most 10 percent above the low) saves the higher figure whatever the words around it ("from", "starting at", "depending on floor")
        narrow = price_range[1] <= price_range[0] * 1.10
        wide = not narrow and (price_range[1] > price_range[0] * 1.15 or re.search(r"\b(?:from|starting|starts|ranges?|ranging|depending|depends|varies|vary|as[ \t]+low[ \t]+as|up[ \t]+to)\b", _range_line(text, price_range), re.I))
        if wide or re.search(r"\b\d(?:\.\d)?[ \t]*(?:-|\u2013|to)[ \t]*\d(?:\.\d)?[ \t]*(?:bd|bds|br|brs|bed|beds|bedrooms?)\b|\b(?:studio|efficiency)[ \t]*(?:-|\u2013|to|/)[ \t]*\d", text, re.I):
            # the range spans different sizes ("1 - 2 bd"): the higher figure is the bigger unit, so no single rent is saved
            price_read = None
            facts.append(f"The listing gives a rent range of ${price_range[0]:,.0f} to ${price_range[1]:,.0f} a month, so the rent is left empty. "
                         "Ask which rent applies to the unit you want, then fill it in.")
        else:
            price_read = price_range[1]  # cycle 25: a range counts the higher number (cycle 23 rule), so the cost is never understated
            facts.append(f"The listing gives a rent range of ${price_range[0]:,.0f} to ${price_range[1]:,.0f} a month. The higher figure, ${price_range[1]:,.0f}, is saved as the rent "
                         "so the cost is not understated, and the lower figure is not a cost on top of the rent. Ask which rent applies to the unit you want.")
    if price_read is None and not price_range:
        worded, worded_note = _try(lambda: _worded_price(text)) or (None, "")
        if worded:
            price_read = worded
        elif worded_note:
            facts.append(worded_note)
    if price_read is None and not price_range and not buying:
        price_read = _try(lambda: _bare_starting_rent(text))  # "Starting at $3,250": the lowest unit, read with a note below
    unit_pick = None if buying or price_range or _try(lambda: _two_rents(text)) or _try(lambda: _per_room_split_note(text, price_read)) else _try(lambda: _unit_price_pick(text, _unit_price_beds(text)))
    if unit_pick:  # cycle 20: prices for different bedroom counts: the one for this listing's own bedroom count, never the lower one
        price_read = unit_pick[0]
        facts.append(unit_pick[1])
    if price_read is not None and fp_all and not unit_pick:
        other_fp = [(b, bt, v, st) for b, bt, v, st in fp_all if v != price_read and fp_beds is not None and b != fp_beds]
        for b, bt, v, st in dict.fromkeys(other_fp):
            facts.append(f"The listing also gives a {b:g} bed floor plan ({b:g}x{bt:g}) {'from ' if st else 'at '}${v:,.0f}. The rent saved is for the {fp_beds:g} bed. "
                         f"Ask the price of the {b:g} bed if you want that one.")
    two_prices = None if buying or price_range or unit_pick else _try(lambda: _rent_two_prices(text))
    if two_prices:  # cycle 18: two rents in one listing: the quoted or current one is saved, the other is named in a note
        price_read = two_prices[0]
        if two_prices[2] == "net" or not (_REDUCED_FROM.search(text) or _WAS_PRICE.search(text)):  # those two already get a "price was cut" note
            facts.append(_rent_two_prices_note(*two_prices))
    promo = None if buying or price_range or unit_pick or two_prices else _try(lambda: _promo_then_rent(text))
    if promo:  # cycle 21: "$2,100 first 6 months then $2,350": the rent that lasts is saved, the promo rent is a note
        price_read = promo[2]
        mo = promo[1]
        facts.append(f"The listing gives ${promo[0]:,.0f} a month for the first {mo} month{'' if mo in ('1', 'one') else 's'}, then ${promo[2]:,.0f}. "
                     f"The ongoing ${promo[2]:,.0f} is saved as the rent, so the first months cost less than the saved rent. Ask what you pay after the special ends.")
    cond_now = None if buying or promo else _try(lambda: _conditional_now_price(text, price_read))
    if cond_now and price_read is not None:
        facts.append(f"The listing also gives ${cond_now[0]:,.0f} a month {cond_now[1]}. That price depends on the condition, so the saved rent stays ${price_read:,.0f}. Ask if the lower price applies to you.")
    elif not (buying or promo or price_range or unit_pick or two_prices):
        special = _try(lambda: _special_price(text, price_read))
        if special:  # cycle 26: "$3,600/MO $3,000 IF YOU SIGN BY DEC 1 (SPECIAL)": the regular rent stays, one short note names the special and its deadline
            if special[2] is not None:
                price_read = special[2]
            if price_read is not None:
                facts.append(_special_note(special, price_read))
    if not buying:
        for old_amt in _try(lambda: _superseded_amounts(text)) or []:
            if old_amt != price_read:
                facts.append(f"The listing says ${old_amt:,.0f} was a mistake or an old figure, so it is not used. Check the rent with the landlord.")
    if not buying and not price_range:
        corr = _try(lambda: _corrected_rent(text))
        if corr and price_read == corr[0]:
            facts.append(f"The listing corrects itself: it first says {corr[1]} and then ${corr[0]:,.0f}. The later ${corr[0]:,.0f} is saved as the rent. Check it with the landlord.")
        elif price_read is None:
            bare_room = _try(lambda: _bare_per_room_rent(text))
            if bare_room:
                facts.append(f"The listing gives {bare_room:,.0f} per bedroom or person but not the rent for the whole place, so the rent is left empty. Ask what the whole place costs.")
    if not buying and not price_range:
        rent_fix = _try(lambda: _rent_correction(text))
        if rent_fix:  # cycle 24: the later rent wins; the superseded one is noted as the old price, never as an uncounted amount
            price_read = rent_fix[0]
            if rent_fix[1] is not None and not any(_usd(rent_fix[1]) in f for f in facts):
                facts.append(f"The listing corrects the rent. It first said {_usd(rent_fix[1])} and then says {_usd(rent_fix[0])}, so the {_usd(rent_fix[1])} is the old price and is not used. "
                             "Check the rent with the landlord.")
    if buying and isinstance(price_read, (int, float)) and price_read < 20000:
        # A monthly figure ("monthly cost about $1,988") is not the asking price of a home for sale.
        if not (current or {}).get("price"):  # a price the caller already has needs no "check the asking price" note
            facts.append(
                f'The listing has ${price_read:,.0f} that looks like a monthly amount, not an asking price, so it is not used as the asking price. Check the asking price.')
        price_read = None
    plan_fix = None
    if price_read is not None and not buying and not unit_pick:
        own_beds = _try(lambda: _beds(_text_without_plans(text, price_read)))
        if own_beds is None and isinstance((current or {}).get("beds"), (int, float)) and not isinstance((current or {}).get("beds"), bool):
            own_beds = float((current or {}).get("beds"))
        plan_fix = _try(lambda: _starting_plan_pick(text, price_read, own_beds))
    if plan_fix:  # cycle 23: "Starting at $1,250" plus "A1 1BR $1,395; A2 1BR $1,445": the 1 bed plan, never the lower starting price
        price_read = plan_fix[0]
        facts.append(plan_fix[1])
    dash_price = _try(lambda: _dash_title_price(text)) if price_read is not None and not buying else None
    if dash_price and dash_price[1] and dash_price[0] == price_read:
        facts.append(f"The listing says \"starting at\" ${price_read:,.0f}, so that is the lowest unit price. Ask what the rent is for the unit you want.")
    elif price_read is not None and not buying and _try(lambda: _starting_at(text, price_read)):
        facts.append(f"The listing says \"starting at\" ${price_read:,.0f}, so that is the lowest unit price. Ask what the rent is for the unit you want.")
    if price_read is None and not buying:
        cfp = re.search(r"\b(?:call|contact|inquire|inquiries|ask|email|text|message)\b[^.\n;]{0,20}\b(?:for|about)\b[^.\n;]{0,12}\b(?:price|pricing|rent|rates?|details)\b", text, re.I)
        if cfp:  # cycle 16: "Call for price" is no price, and a street number beside it is not one
            facts.append(f'The listing gives no price (it says "{" ".join(cfp.group(0).split())}"), so the rent is left empty. Ask what the rent is.')
    two = None if buying else _try(lambda: _two_rents(text))
    if two:
        per_txt, unit_txt, unit_val, unit_kind = two
        price_read = unit_val
        facts.append(f"The listing gives two rents: {per_txt} a month per bedroom or room, and {unit_txt} as the {unit_kind} rent. "
                     f"The {unit_kind} rent of {unit_txt} is saved as the rent, not the {per_txt} figure. Ask which one you pay.")
    if not two and not buying:
        split_note = _try(lambda: _per_room_split_note(text, price_read))
        if split_note:
            facts.append(split_note)
    lease_opts = None if buying or price_range or plan_fix else _try(lambda: _lease_rent_options(text))
    lease_plan_pick = None
    lease_chosen = None
    extra_lease_opt = None
    if lease_opts:  # cycle 25: the rent and the lease length come from the same option: the one closest to 12 months (the first written on a tie)
        lease_chosen = min(lease_opts, key=lambda o: abs(o[1] - 12))
        if price_read != lease_chosen[0]:  # the "starting at" note was about the first rent read, which is no longer the rent saved
            facts[:] = [f for f in facts if not f.startswith('The listing says "starting at"')]
        price_read = lease_chosen[0]
        lease_plan_pick = _try(lambda: _lease_plan_lowest(text, lease_opts))
        if lease_plan_pick:  # cycle 24: a cheaper plan for the same bedroom count exists: it is the rent, the lease options are a note
            price_read = lease_plan_pick[0]
            facts.append(lease_plan_pick[1])
            facts.append(_lease_rent_options_note(lease_opts, first_saved=False))
        else:
            facts.append(_lease_rent_options_note(lease_opts))
    elif not (buying or price_range or plan_fix):
        extra_lease_opt = _try(lambda: _lease_extra_option(text, price_read))
        if extra_lease_opt:
            facts.append(_lease_extra_option_note(*extra_lease_opt))
    if (price_read is not None or price_range) and not (buying or plan_fix or unit_pick or lease_opts or two):
        same_plans = _try(lambda: _same_bed_plans(text, _try(lambda: _beds(text)))) or []
        if len({v for _n, v in same_plans}) >= 2 and (price_read in {v for _n, v in same_plans} or (price_range and price_read is None)) \
                and (not price_range or {price_range[0], price_range[1]} <= {v for _n, v in same_plans}):
            if price_range:
                facts[:] = [f for f in facts if "gives a rent range of" not in f]  # the plan note below names both ends of the range
            low_name, low_val = min(same_plans, key=lambda x: x[1])
            others = "; ".join(f"{n} {_usd(v)}" for n, v in same_plans if v != low_val)
            price_read = low_val
            facts.append(f"The listing gives more than one plan with the same number of bedrooms ({low_name} {_usd(low_val)}; {others}). The lowest one is saved as the rent. "
                         "Ask which plan you want and what it costs.")
    if price_read is not None and not buying and price_read < 1500 and not (price_range or two or unit_pick or plan_fix or lease_opts):
        # cycle 25: a rent far below another rent-sized figure the reader did not explain is a reading error (an optional parking figure read as the rent)
        big = [a for a in (_try(lambda: _amounts(text)) or []) if 1000 <= a["value"] <= 30000 and a["value"] >= 3 * price_read and not a["fee"]
               and not a.get("conditional") and a["marker"] != "per bed" and not any(_usd(a["value"]) in f for f in facts)]
        if big:
            lab = [a for a in big if a["labelled"] and not _side_clause_amount(text, a["start"])]
            if lab:
                price_read = lab[0]["value"]
            else:
                facts.append(f"The listing gives {_usd(price_read)} and also {_usd(big[0]['value'])}, and I could not tell which one is the monthly rent, so the rent is left empty. Ask what the rent is.")
                price_read = None
    if "price" in gc_found and not buying and not price_range:
        gc_tmp = {"price": price_read}
        _gc_apply(text, gc_tmp, facts, gc_found, [], buying, only={"price"})
        price_read = gc_tmp["price"]
    put("price", price_read)
    text = text_all
    if plan_fix and plan_fix[0] is None:
        put("beds", _try(lambda: _beds(_text_without_plans(text, None))))  # cycle 23: a bedroom count that only appears in the plan list is not the listing's own
    elif unit_pick and unit_pick[0] is None and _unit_price_beds(text) is None:
        pass  # cycle 20: the only bedroom counts are in a price list, so none of them is "the" count of this listing
    else:
        put("beds", _try(lambda: _beds(text)))
    conv = _try(lambda: _beds_converted(text))
    if conv:
        was = "studio" if conv[0] == 0 else f"{conv[0]:g} bedroom"
        now = "studio" if conv[1] == 0 else f"{conv[1]:g} bedroom"
        facts.append(f"The listing says this was a {was} that was converted to a {now}, so it is saved as {now}. Ask how the rooms are laid out.")
    corrected = None if conv else _try(lambda: _beds_corrected(text))
    caller_beds = (current or {}).get("beds")
    caller_baths = (current or {}).get("baths")
    if corrected:
        was = "studio" if corrected[0] == 0 else f"{corrected[0]:g} bedroom"
        now = "studio" if corrected[1] == 0 else f"{corrected[1]:g} bedroom"
        if caller_beds not in (None, "") and not _same_num(caller_beds, corrected[1]):
            facts.append(f"The listing gives two different bedroom counts ({was}, then {now}) and corrects itself. The bedroom count that was already saved was kept, so check it.")
        else:
            facts.append("The listing gives two different bedroom counts and corrects itself. The later count is saved, so check the bedroom count.")
    xb_fix = None if (conv or corrected or not _XB_CORRECT.search(text)) else _try(lambda: _beds_x_corrected(text))
    if xb_fix:
        facts.append(f"The listing gives two different layouts and corrects itself. The later one ({xb_fix[0]:g} bed, {xb_fix[1]:g} bath) is saved, so check the layout.")
    beds_conflict = _try(lambda: _beds_conflict(text)) or ""
    if beds_conflict:
        facts.append(beds_conflict)
    bath_fix = _try(lambda: _baths_corrected(text))
    if bath_fix:
        if caller_baths not in (None, "") and not _same_num(caller_baths, bath_fix[1]):
            facts.append(f"The listing gives two different bathroom counts ({bath_fix[0]:g}, then {bath_fix[1]:g}) and corrects itself. The bathroom count that was already saved was kept, so check it.")
        else:
            facts.append("The listing gives two different bathroom counts and corrects itself. The later count is saved, so check the bathroom count.")
    facts += _try(lambda: _price_notes(text, price_read, buying)) or []
    put("baths", _try(lambda: _baths(text)))
    fixed_facts = {} if buying else (_try(lambda: _corrected_facts(text)) or {})
    if "baths" in fixed_facts and not bath_fix:
        nb, ob = fixed_facts["baths"]
        base_b = out.get("baths")
        if ob is not None or (base_b is not None and not _same_num(base_b, nb)):
            facts.append(_corrected_fact_note("bathroom count", f"{nb:g} bath", f"{(ob if ob is not None else base_b):g} bath"))
        out["baths"] = _tidy_number(nb)
    if "beds" in fixed_facts and not (corrected or conv or xb_fix):
        nb, ob = fixed_facts["beds"]
        base_b = out.get("beds")
        if ob is not None or (base_b is not None and not _same_num(base_b, nb)):
            wb = lambda v: "studio" if v == 0 else f"{v:g} bedroom"  # noqa: E731
            facts.append(_corrected_fact_note("bedroom count", wb(nb), wb(ob if ob is not None else base_b)))
        out["beds"] = _tidy_number(nb)
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
    ptext, question_notes = _drop_question_sentences(text)  # cycle 25: a sentence that asks ("Is parking included?") sets no parking or pet fact
    facts += question_notes
    kind_cost = _try(lambda: _parking_detail(ptext)) or ("", None, [])
    put("parking", kind_cost[0])
    put("parking_cost", kind_cost[1])
    facts += [n for n in kind_cost[2] if not (buying and re.search(r"is counted\.|are counted\.|counted in the monthly cost\.? Check|, so .{1,40} is counted", n) and "not counted" not in n)]
    if kind_cost[1] and not kind_cost[2] and re.search(r"\bparking\b[^.\n;$]{0,40}\$\s?" + f"{kind_cost[1]:.0f}" + r"(?!\d)(?:\.\d\d)?[^.\n;$]{0,25}\b(?:per|each|a|/)\s*(?:vehicle|car|space|spot)\b"
                                                    r"|\bparking\b[^.\n;$]{0,40}\b(?:per|each)\s+(?:vehicle|car)\b[^.\n;$]{0,15}\$\s?" + f"{kind_cost[1]:.0f}" + r"(?!\d)", ptext, re.I) \
            and not re.search(r"\b(?:optional|available)\b", ptext[max(0, ptext.lower().find("parking") - 20):ptext.lower().find("parking") + 80], re.I):
        facts.append("Parking is charged for each vehicle (or space) and the cost is counted once. With more than one car it costs more.")
    if kind_cost[1]:
        promo = _try(lambda: _parking_promo_note(ptext, float(kind_cost[1])))
        if promo:
            facts.append(promo)
    doubt = _try(lambda: _pets_doubt(ptext)) or ""
    if doubt:
        facts.append(doubt)  # pets stays empty (unknown), so a pet owner sees "Fits, but check"
    else:
        put("pets", _try(lambda: _pets(ptext)))
        soft = _try(lambda: _pets_soft_note(ptext)) or ""
        if soft:
            facts.append(soft)
        if not out.get("pets"):
            no_kind = _try(lambda: _pets_no_species_note(ptext)) or ""
            if no_kind:
                facts.append(no_kind)  # cycle 23: "Pets: no cats" is never dropped silently
    pet_text = ptext
    pet_app = _try(lambda: _pet_application(ptext))
    if pet_app:
        pet_text = pet_app[2]
        facts.append(f"The listing also charges a ${pet_app[0]:,.0f} pet application" + (" for each pet" if pet_app[1] else "") + ". It is a separate one-time charge and is not the pet fee, so ask when it is paid.")
    cond_dep = _try(lambda: _pet_conditional_deposit(pet_text))
    if cond_dep:
        pet_text = cond_dep[1]
        facts.append(cond_dep[2])
    split = _try(lambda: _pet_deposit_split(pet_text))
    if split:
        pet_text = split[2]
        put("pet_deposit", split[0])
        put("pet_fee", split[1])
        facts.append(split[3])
    animals = _try(lambda: _per_animal_charges(pet_text))
    if animals:
        pet_text = animals[2]
        facts.extend(_per_animal_notes(animals[0], animals[1], pet_kind, out))
    deposit_amount, fee_text = _try(lambda: _pet_deposit(pet_text)) or (None, pet_text)
    if deposit_amount is not None and "pet_deposit" in out:
        deposit_amount = None
    if deposit_amount is None and "pet_deposit" not in out and out.get("pets") in ("cats", "dogs"):
        # cycle 24: "Cats allowed with $200 cat deposit": when only one kind of animal is allowed, a deposit named for that animal is the pet deposit
        an = "cat" if out.get("pets") == "cats" else "dog"
        dm = re.search(rf"\$\s?(\d{{1,4}})(?:\.\d\d)?[ \t]*(?:(?:one[- ]time|non[- ]?refundable|refundable)[ \t]+)?{an}s?[ \t]+deposit\b(?![ \t]*(?:/|per[ \t]+month))"
                       rf"|\b{an}s?[ \t]+deposit[ \t]*(?:[:\-=]|of|is)?[ \t]*\$\s?(\d{{1,4}})(?:\.\d\d)?(?![\d,/])", fee_text, re.I)
        if dm and not re.search(r"non[- ]?refundable", fee_text[max(0, dm.start() - 20):dm.end() + 20], re.I):
            deposit_amount = float(dm.group(1) or dm.group(2))
            fee_text = fee_text[:dm.start()] + " " * (dm.end() - dm.start()) + fee_text[dm.end():]
    put("pet_deposit", deposit_amount)
    if deposit_amount is None and "pet_deposit" not in out and out.get("pets") != "none" and _try(lambda: _no_pet_deposit(ptext)):
        out["pet_deposit"] = 0  # the listing says there is no pet deposit: zero, not unknown
    for key, value in (_try(lambda: _pet_fees(fee_text)) or {}).items():
        if key not in out:
            put(key, value)
    if "pet_rent" not in out:
        monthly_after_deposit = _try(lambda: _pet_deposit_then_monthly(ptext))
        if monthly_after_deposit:
            put("pet_rent", monthly_after_deposit)
        elif out.get("pets") != "none" and _try(lambda: _no_pet_rent(ptext)):
            out["pet_rent"] = 0  # the listing says there is no pet rent: zero, not unknown
    if out.get("pet_rent"):
        bare = re.search(r"(?<![\w-])pets?[ \t]*[:\-]?[ \t]*\$\s?" + f"{float(out['pet_rent']):.0f}" + r"(?!\d)(?:\.\d\d)?[ \t]*(?:/[ \t]*mo(?:nth)?\b|per[ \t]+month|a[ \t]+month|monthly|mo\b)", ptext, re.I)
        if bare:
            facts.append(f'The listing\'s line "{" ".join(bare.group(0).split())}" is saved as monthly pet rent (${float(out["pet_rent"]):,.0f} a month). '
                         "It only matters if you have a pet. Ask if it is for each pet.")
    side, dep_text = _try(lambda: _pet_side_deposits(fee_text, out.get("price") if isinstance(out.get("price"), (int, float)) else None)) or ({}, fee_text)
    for key, value in side.items():
        if key not in out and not (key == "pet_fee" and "pet_fee" in out):
            put(key, value)
    unsure_at: int | None = None
    if out.get("pet_deposit") and not split and not _try(lambda: _pet_deposit_says_refundable(ptext, float(out["pet_deposit"]))):
        # cycle 20: the field has no "unknown" state, so the amount stays (cash at move-in) and a note says refundability is unknown
        unsure = float(out["pet_deposit"])
        unsure_at = len(facts)
        facts.append(f"The listing gives a ${unsure:,.0f} pet deposit but does not say if it comes back. It is saved in the pet deposit field so the cash at move-in "
                     "includes it, but do not count on getting it back. Ask if it is refundable.")
    if out.get("pet_rent") and _try(lambda: _pet_rent_first_free(ptext, float(out["pet_rent"]))):
        # cycle 26: "pet rent $40 not charged for first pet": $0 for one pet; with more pets only the pets after the first are charged
        rent_amt = float(out["pet_rent"])
        n_pets = _pet_count_for_rent(pet_kind, pet_count)
        if n_pets is not None and n_pets >= 2:
            out["pet_rent"] = _tidy_number(rent_amt * (n_pets - 1))
            facts.append(f"The listing says the ${rent_amt:,.0f} pet rent is not charged for the first pet. Your search has {n_pets} pets, so it is counted for the other "
                         + ("pet" if n_pets == 2 else f"{n_pets - 1} pets") + f" only (${float(out['pet_rent']):,.0f} a month).")
        else:
            out["pet_rent"] = 0
            facts.append(f"The listing says the ${rent_amt:,.0f} pet rent is not charged for the first pet, so pet rent is $0 for one pet. "
                         f"A second pet would add ${rent_amt:,.0f} a month.")
    if out.get("pet_rent") and not any(f"${float(out['pet_rent']):,.0f}" in f and "second pet" in f for f in facts):
        # cycle 27: "pet rent $35/mo for first pet, second pet $25": the second pet's rent is named so the $25 is never an unexplained figure
        sm = re.search(r"\b(?:second|2nd|additional|extra)[ \t]+(?:pet|dog|cat|animal)s?\b[ \t:\-=]*(?:is[ \t]+|rent[ \t]+|fee[ \t]+)?\$[ \t]?(\d{1,4}(?:\.\d\d)?)(?!\d)(?![ \t]*(?:deposit|one[- ]time))", ptext, re.I)
        if sm and float(sm.group(1)) != float(out["pet_rent"]) and re.search(r"\b(?:first|1st|one)[ \t]+(?:pet|dog|cat|animal)\b|/[ \t]*mo|per[ \t]+month|monthly", ptext[max(0, sm.start() - 60):sm.end() + 20], re.I):
            second = float(sm.group(1))
            facts.append(f"The listing gives pet rent of ${float(out['pet_rent']):,.0f} a month and ${second:,.0f} a month for a second pet. "
                         f"The ${float(out['pet_rent']):,.0f} is saved. A second pet would add ${second:,.0f} a month, so ask what you would pay if you have two pets.")
    one_pet = _one_pet_household(pet_kind, pet_count)  # cycle 24: "with more than one pet it adds up" only when the search has more than one pet or the count is unknown
    if out.get("pet_rent") and re.search(r"\$\s?\d{1,4}(?:\.\d\d)?\s*(?:(?:/\s*mo(?:nth)?|per month|monthly|a month)\s*)?(?:per|each|/)\s*(?:pet|dog|cat|animal)\b", fee_text, re.I):
        if not one_pet:
            facts.append(f"Pet rent is ${out['pet_rent']:,.0f} for each pet, so with more than one pet it adds up.")
    elif out.get("pet_rent") and re.search(r"\$\s?\d{1,4}(?:\.\d\d)?\s*(?:(?:/\s*mo(?:nth)?|per month|monthly|a month)\s*)?pet\s+rent\s+(?:per|each|for each|a|/)\s*(?:pet|animal|dog|cat)\b", fee_text, re.I):
        if not one_pet:
            facts.append(f"Pet rent is ${out['pet_rent']:,.0f} a month for each pet, so with more than one pet it adds up.")
    elif out.get("pet_rent") and re.search(r"\$\s?\d{1,4}(?:\.\d\d)?\s*(?:each|apiece)\b", fee_text, re.I) and re.search(r"\bpet\s+rent\b", fee_text, re.I):
        if not one_pet:
            facts.append(f"Pet rent is ${out['pet_rent']:,.0f} for each pet, so with more than one pet it adds up.")
    elif out.get("pet_rent") and re.search(r"\$\s?\d{1,4}(?:\.\d\d)?\s*(?:(?:/\s*mo(?:nth)?|per month|monthly|a month)\s*(?:each|apiece)|(?:each|apiece)\s*(?:/\s*mo(?:nth)?|per month|monthly|a month))\b", fee_text, re.I):
        if not one_pet:
            facts.append(f"Pet rent is ${out['pet_rent']:,.0f} a month for each pet, so with more than one pet it adds up.")
    elif out.get("pet_rent") and re.search(r"\$\s?\d{1,4}(?:\.\d\d)?\s*(?:each|apiece)\b", fee_text, re.I):
        facts.append(f"The listing says ${out['pet_rent']:,.0f} each for pets, saved as monthly pet rent for each pet" + ("" if one_pet else ", so with more than one pet it adds up") + ". "
                     "If it is a one time fee instead, move it to the pet fee.")
    if out.get("pet_deposit") and re.search(r"\$\s?" + f"{out['pet_deposit']:.0f}" + r"(?!\d)(?:\.\d\d)?[ \t]*(?:per|each|/)[ \t]*(?:pet|dog|cat|animal)s?[ \t]+(?:refundable[ \t]+)?deposit\b"
                                            r"|\bdeposit[ \t]*[:\-]?[ \t]*\$\s?" + f"{out['pet_deposit']:.0f}" + r"(?!\d)(?:\.\d\d)?[ \t]*(?:per|each|/)[ \t]*(?:pet|dog|cat|animal)s?\b", ptext, re.I):
        if unsure_at is not None:
            # cycle 27: one pet deposit gets one note, and it must not say the deposit comes back when the listing does not
            if not one_pet:
                facts[unsure_at] = facts[unsure_at] + " The deposit is for each pet, so with more than one pet it adds up."
        elif _try(lambda: _pet_deposit_says_refundable(ptext, float(out["pet_deposit"]))):
            facts.append(f"The pet deposit is ${out['pet_deposit']:,.0f}" + ("" if one_pet else " for each pet, so with more than one pet it adds up") + ". It comes back, so it counts only as cash at move-in.")
        else:
            facts.append(f"The pet deposit is ${out['pet_deposit']:,.0f}" + ("" if one_pet else " for each pet, so with more than one pet it adds up") + ".")
    nr = re.search(r"\$\s?(\d{1,4}(?:,\d{3})?)(?:\.\d\d)?[ \t]*(?:non[- ]?refundable[ \t]+)?pet[ \t]+deposit\b[^.\n;]{0,25}?non[- ]?refundable|\bnon[- ]?refundable[ \t]+\$\s?(\d{1,4}(?:,\d{3})?)[ \t]*pet[ \t]+deposit", ptext, re.I)
    if nr and out.get("pet_fee") and not out.get("pet_deposit"):
        facts.append(f"The ${float((nr.group(1) or nr.group(2)).replace(",", "")):,.0f} pet deposit is non-refundable, so it is counted as a pet fee, not as money you get back.")
    for key, value in (_try(lambda: _pet_limit_fields(ptext)) or {}).items():
        if key == "_weight_combined":
            amount, quoted = value
            facts.append(f"The listing gives {amount:,.0f} lb as a combined limit for all the pets together (\"{quoted[:80]}\"), not for each pet. "
                         f"The weight limit here is for one pet, so it is left empty. Ask {_ask_who(ptext)} the heaviest single pet allowed.")
            continue
        if key == "_weight_conflict":
            quoted = " and ".join(f'"{q}"' for q in value)
            facts.append(f"The listing gives two pet weight limits that do not match: {quoted}. The weight limit is left empty. Ask {_ask_who(ptext)} which one applies.")
            continue
        put(key, value)
    if out.get("pet_weight_limit") is not None and not out.get("pets") and not doubt and _PET_LABEL_NO_OVER.search(ptext):
        facts.append("The listing sets a pet weight limit but does not say which pets are allowed, so pets is left empty. "
                     f"Ask {_ask_who(ptext)} whether cats and dogs are both allowed.")
    if out.get("fenced_yard") == 0 and re.search(r"\bshared\s+(?:courtyard|yard|garden|patio)\b", ptext, re.I) and _no_private_yard(ptext):
        facts.append("There is no private yard, only a shared courtyard.")
    if out.get("fenced_yard") == 1 and re.search(r"\b(?:shared|common|communal)[ \t]+(?:fenced[ \t-]+)?(?:back[ \t]*|front[ \t]*)?yard\b|\bfenced[ \t-]+(?:back[ \t]*|front[ \t]*)?yard\b[ \t]*[\(,:\-\u2013]?[ \t]*(?:is[ \t]+)?(?:shared|common|communal|shared[ \t]+with)\b", ptext, re.I):
        facts.append("The fenced yard is shared, not private. Ask when your pet can use it.")
    weight_note = _try(lambda: _pet_weight_unclear(ptext)) or ""
    if weight_note:
        facts.append(weight_note)
    utext = _util_text(text)
    facts.extend(_try(lambda: _only_scope_notes(text)) or [])
    included = _try(lambda: _utilities(utext)) or ""
    pays = _try(lambda: _tenant_pays(utext)) or ""
    roles = _try(lambda: _utility_roles(utext)) or {"tenant": [], "landlord": [], "billed": [], "amount": None, "per": None}
    roles["landlord"] = [w.strip() for w in _ordered_utilities(list(roles["landlord"])).split(",") if w.strip()]
    left_out = _try(lambda: _ordered_utilities(_all_except(utext.lower()))) or ""
    except_priced: set[str] = set()
    if left_out:
        # cycle 27: "all utilities except trash" never says the trash is free: when the listing gives the left-out utility its own figure ("Trash $15"
        # or "trash $15" in a fee list) it is a bill the renter pays, not something the landlord includes
        priced_out = {w for w, _a in (_try(lambda: _fee_list_utilities(text)) or [])} | {
            _canon_util(w) for w in left_out.split(", ")
            if re.search(r"(?<![\w$])" + ("(?:trash|garbage)" if w == "trash" else w) + r"(?:[ \t]+(?:is|are|costs?|fee))?[ \t]*[:\-]?[ \t]*\$[ \t]?\d", utext, re.I)}
        left_out = _ordered_utilities([w for w in left_out.split(", ") if w and w not in priced_out])
        except_priced = set(priced_out)
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
    pays_pre, included_pre, n_facts_pre = pays, included, len(facts)  # cycle 18: what the words alone said, before any figure moved a utility
    billed = _try(lambda: _billed_back(utext))
    flat = _try(lambda: _flat_util_fee(utext))
    counted: set[str] = set()  # the utilities the estimate counted so far (cycle 17: the figures for the others are added after)
    base_kind = ""

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
        base_kind = "billed" if billed[0] else "billed_unnamed"
        counted |= {w.strip() for w in billed[0].split(",") if w.strip()}
        if billed[0] and flat == billed:
            facts.append(f"{billed[0].capitalize()} {_util_verb(billed[0])} covered by a flat fee of {_money_cents(billed[1])}/month from the listing, counted as your utilities estimate. You pay it, so it is not free.")
        elif billed[0]:
            facts.append(f"{billed[0].capitalize()} {_util_verb(billed[0])} billed back at {_money_cents(billed[1])}/month, counted as your utilities estimate.")
        else:
            facts.append(f"The listing gives a billed-back average of {_money_cents(billed[1])} a month but doesn't say which utilities it covers. Ask the landlord.")
        really = _try(lambda: _really_included(utext, billed[1], moved)) if moved else []
        if really:
            facts.append(f"The listing also says {_join_names(really)} {_util_verb(', '.join(really))} included, but a billed-back amount means you pay it, so it is not counted as included.")
        extra = _try(lambda: _estimate_plan_for(utext, {w.strip() for w in billed[0].split(",") if w.strip()})) if billed[0] else None
        if extra and not extra["total"]:
            # "Electric and gas about $140 combined. Water, sewer, trash $70/month flat": the two figures cover different utilities, so they add up
            put("utilities_estimate", billed[1] + extra["amount"])
            more = _ordered_utilities(list(extra["names"]))
            counted |= set(more.split(", "))
            pays = _ordered_utilities([w.strip() for w in (pays + ", " + more).split(",") if w.strip()])
            facts.append(f"{_join_names(more.split(', ')).capitalize()} {_util_verb(more)} about {_money_cents(extra['amount'])} a month from the listing, added to the {_money_cents(billed[1])} above. "
                         f"The utilities estimate is the two together, {_money_cents(billed[1] + extra['amount'])} a month.")
    elif roles["billed"]:
        names = _ordered_utilities(list(roles["billed"]))
        moved = take_out_of_included(names)
        if moved:
            facts.append(f"The listing also says {moved} is included, but it is billed back to you, so it is not counted as included.")
        pays = _ordered_utilities([w.strip() for w in (pays + ", " + names).split(",") if w.strip()])
        if roles["amount"]:
            put("utilities_estimate", roles["amount"])
            base_kind = "roles"
            counted |= set(names.split(", "))
            if roles.get("per"):
                facts.append(f"{names.capitalize()} {_util_verb(names)} billed back at {_money_cents(roles['per'][0])} per {roles['per'][1]}, which is about {_money_cents(roles['amount'])} a month, counted as your utilities estimate.")
            else:
                facts.append(f"{names.capitalize()} {_util_verb(names)} billed back at about {_money_cents(roles['amount'])}/month, counted as your utilities estimate.")
        else:
            facts.append(f"{names.capitalize()} {_util_verb(names)} billed back to you, but the listing gives no amount. Add a utilities estimate once you know it.")
    elif _try(lambda: _billed_unknown(utext.lower())):
        if included == "all" or re.search(r"\b(?:landlord|owner|management)\s+(?:pays?|covers?)\s+all\b|\ball\s+utilities\s+(?:are\s+)?(?:included|paid|covered)", utext.lower()):  # a named list ("Rent includes: internet") is not "the landlord pays the utilities"
            facts.append("The listing says the landlord pays the utilities, but it also says utilities are billed back to you (RUBS). "
                         "Ask the landlord which utilities you really pay and how much. None are counted as included.")
            included = ""
        else:
            facts.append("The listing says utilities are billed back to you (RUBS), but it gives no amount and doesn't say which utilities. "
                         "Ask the landlord which ones and about how much, then add a utilities estimate.")
    if "utilities_estimate" not in out:
        plan = _try(lambda: _estimate_plan_for(utext))
        if plan and plan["total"] and included == "all" and not pays:
            # "Landlord pays all utilities" next to "roughly $150 total for everything": the two lines disagree, so nothing is called included
            facts.append(f"The listing says the landlord pays all the utilities, but it also gives about {_money_cents(plan['amount'])} a month in total for them. "
                         "Those two lines don't agree, so none are counted as included and no amount is counted. Ask the landlord which utilities you really pay and how much.")
            included = ""
            plan = None
        if plan and (not plan["total"] or ((pays or not included) and included != "all")):
            # "water/sewer/trash approximately $60 a month", "roughly $150 a month total": the renter's own rough bill, not something included
            if plan["total"]:
                base_kind = "plan_total"
                put("utilities_estimate", plan["amount"])
                facts.append(f"The listing gives about {_money_cents(plan['amount'])} a month for all the utilities you pay, counted as your utilities estimate.")
                dropped_names = _ordered_utilities([w for d in plan["dropped"] for w in d["names"]])
                if dropped_names:  # "$55 for water/sewer" next to a total: those are utilities the renter pays, covered by the total
                    pays = _ordered_utilities([w.strip() for w in (pays + ", " + dropped_names).split(",") if w.strip()])
            else:
                names = _ordered_utilities(list(plan["names"]))
                moved = take_out_of_included(names)
                pays = _ordered_utilities([w.strip() for w in (pays + ", " + names).split(",") if w.strip()])
                base_kind = "plan"
                counted |= set(names.split(", "))
                put("utilities_estimate", plan["amount"])
                facts.append(f"{_join_names(names.split(', ')).capitalize()} {_util_verb(names)} about {_money_cents(plan['amount'])} a month from the listing, counted as your utilities estimate.")
                really = _try(lambda: _really_included(utext, plan["amount"], moved)) if moved else []
                if really:
                    facts.append(f"The listing also says {_join_names(really)} {_util_verb(', '.join(really))} included, but it gives you a monthly amount for it, so it is not counted as included.")
            for d in plan["dropped"]:
                what = _join_names(d["names"]) if d["names"] else "utilities"
                facts.append(f"The listing also gives {what} at about {_money_cents(d['amount'])} a month. Only the figure that covers more or is higher, {_money_cents(plan['amount'])}, is counted.")
    if "utilities_estimate" not in out:
        per = _try(lambda: _periodic_named(utext))
        if per:
            # "Quarterly water bill of $135 billed back": the monthly share of the bill is the estimate for those utilities
            names = _ordered_utilities(list(per["names"]))
            was_included = take_out_of_included(names)
            if was_included:
                facts.append(f"The listing also says {_join_names(was_included.split(', '))} {_util_verb(was_included)} included, but it also gives a {per['unit']}ly bill for it, so it is not counted as included.")
            pays = _ordered_utilities([w.strip() for w in (pays + ", " + names).split(",") if w.strip()])
            base_kind = "per"
            counted |= set(names.split(", "))
            put("utilities_estimate", per["monthly"])
            facts.append(f"{_join_names(names.split(', ')).capitalize()} {_util_verb(names)} a {per['unit']}ly bill of {_money_cents(per['raw'])}, so about {_money_cents(per['monthly'])} a month, counted as your utilities estimate.")
    passed = [w for w in (_try(lambda: _passed_through(utext)) or []) if w not in set(roles["billed"]) and not (billed and w in billed[0])]
    if passed and not (_try(lambda: _periodic_named(utext)) or {}).get("names"):
        have_now = [w.strip() for w in included.split(",") if w.strip()] if included != "all" else list(_ALL_UTILITIES)
        clash_p = [w for w in passed if w in have_now]
        rest_p = [w for w in passed if w not in clash_p]
        if clash_p:
            included = _ordered_utilities([w for w in have_now if w not in clash_p])
            facts.append(f"The listing says the landlord pays {_join_names(clash_p)}, but it also says the {_join_names(clash_p)} bill is passed through to you. "
                         f"{_join_names(clash_p).capitalize()} {_util_verb(', '.join(clash_p))} left unknown, so ask the landlord who pays {'it' if len(clash_p) == 1 else 'them'} and how much.")
        if rest_p:
            pays = _ordered_utilities([w.strip() for w in (pays + ", " + ", ".join(rest_p)).split(",") if w.strip()])
            facts.append(f"The {_join_names(rest_p)} bill is passed through to you, but the listing gives no amount. Add a utilities estimate once you know it.")
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
        facts.append(f"The listing gives a utilities bill of about {_money_cents(raw)} per {unit}, which is about {_money_cents(monthly)} a month, counted as your utilities estimate. "
                     "It does not say which utilities it covers, so ask.")
    elif not included and not pays and "utilities_estimate" not in out and (_try(lambda: _utilities_extra_amount(text)) or None):
        approx = _try(lambda: _utilities_extra_amount(text))
        put("utilities_estimate", approx)  # the listing's own monthly figure, so it is counted and shown as from the listing
        facts.append(f"The listing says utilities are extra, about {_money_cents(approx)}/month, counted as your utilities estimate. It does not say which utilities you pay, so ask.")
    elif pays and included != "all" and "utilities_estimate" not in out and (_try(lambda: _utilities_extra_amount(text)) or None):
        approx = _try(lambda: _utilities_extra_amount(text))
        put("utilities_estimate", approx)  # "Tenant pays all utilities. Approx $180/month": the listing's own figure
        facts.append(f"The listing gives about {_money_cents(approx)}/month for utilities, counted as your utilities estimate.")
    elif not included and not pays and _try(lambda: _plus_utilities_unknown(text)):
        facts.append("The listing says utilities are extra (rent plus utilities) but doesn't say which ones. Ask the landlord which utilities you pay.")
    rubs_i = next((i for i, f in enumerate(facts) if f.startswith("The listing says utilities are billed back to you (RUBS), but it gives no amount")), None)
    if rubs_i is not None and isinstance(out.get("utilities_estimate"), (int, float)):
        dup_i = next((i for i, f in enumerate(facts) if i > rubs_i and f.endswith(("counted as your utilities estimate.", "so ask.")) and re.match(r"The listing (?:gives about|says utilities are extra, about) \$", f)), None)
        if dup_i is not None:
            facts[rubs_i:rubs_i + 1] = []  # one note, not two: the figure the listing gives answers the "no amount" note
            facts[dup_i - 1] = (f"The listing says utilities are billed back to you (RUBS), about {_money_cents(out['utilities_estimate'])}/month, counted as your utilities estimate. "
                                "It does not say which utilities you pay, so ask.")
    if every is None and re.search(r"\bcable\b", utext, re.I) and not any("Cable is" in f for f in facts):
        if re.search(r"\bcable\b[^.\n;]{0,25}\b(?:extra|separate|not included|tenant|resident|you|paid|additional)\b|\b(?:extra|separate|not included|tenant|resident|you pay|excluding|except|plus)\b[^.\n;]{0,25}\bcable\b", utext, re.I):
            facts.append("Cable is not included. Cable is TV, not internet, so internet is left blank. Ask whether internet is included.")
    lpa = re.search(r"\b(?:landlord|owner|management|property manager)\s+(?:pays?|covers?)\s+(?:for\s+)?all\b(?:\s+(?:the\s+)?utilit\w*)?(?P<exc>\s+(?:except(?:\s+for)?|other\s+than|besides)\s+[^.\n;]{0,40})?", utext, re.I)
    tpa = re.search(r"\b(?:tenants?|residents?|renters?|you)\s+(?:pays?|are\s+responsible\s+for|is\s+responsible\s+for|responsible\s+for|will\s+pay|must\s+pay)\s+(?:for\s+)?all\b(?!\s+(?:the\s+)?(?:utilit\w*\s+)?(?:except|other\s+than|besides))", utext, re.I)
    if lpa and tpa and not any(("landlord pays" in f or "unclear about" in f or "(RUBS)" in f) for f in facts):
        # "Tenant pays all" next to "landlord pays all": the listing contradicts itself, so nothing is called included
        tail = (lpa.group("exc") or "").strip()
        facts.append(f"The listing says you pay all the utilities, but it also says the landlord pays all{(' ' + tail) if tail else ''}. "
                     "Those two lines don't agree, so none are counted as included and no amount is counted. Ask the landlord which utilities you really pay and how much.")
        included = ""
    fee_conflict = _try(lambda: _util_fee_conflict(utext)) if included == "all" and not out.get("utilities_estimate") else None
    if fee_conflict:
        # "All utilities included ... $180 per month paid by tenant to landlord": two readings, so nothing is counted and nothing is called included
        facts.append(f"The listing says the landlord pays all the utilities, but it also says {_money_cents(fee_conflict)} a month for them is paid by the tenant to the landlord. "
                     "Those two lines don't agree, so none are counted as included and no amount is counted. Ask the landlord which utilities you really pay and how much.")
        included = ""
        base_kind = "conflict"
    add_names_seen: list[str] = []
    if base_kind in ("billed", "roles", "plan", "per", "billed_unnamed", "") and (base_kind or "utilities_estimate" not in out):
        # cycle 17: figures for other utilities are added, never dropped ("Electric $60. Gas $75. Water billed quarterly $150")
        more_items = _try(lambda: _estimate_items(utext)) or []
        named_more = [i for i in more_items if not i["total"] and not (set(i["names"]) & counted)] if base_kind in ("roles", "billed_unnamed", "") else []
        plan_more = _estimate_plan(named_more) if named_more else None
        per_more = [c for c in (_try(lambda: _periodic_components(utext)) or []) if not (set(c["names"]) & counted)
                    and not (plan_more and set(c["names"]) & set(plan_more["names"]))]
        if base_kind == "billed_unnamed" and (plan_more or per_more):
            # "Utilities billed back via RUBS, avg $120" next to "electric $55": the RUBS amount may already cover them, so nothing is counted
            pieces = [f"{_money_cents(out['utilities_estimate'])} a month billed back" if isinstance(out.get("utilities_estimate"), (int, float)) else "a billed-back amount"]
            pieces += [f"{_join_names(i['names'])} {_money_cents(i['amount'])} a month" for i in (plan_more["kept"] if plan_more else [])]
            pieces += [f"{_join_names(c['names'])} {_money_cents(c['raw'])} per {c['unit']}" for c in per_more]
            out.pop("utilities_estimate", None)
            facts[:] = [f for f in facts if "billed-back average" not in f]
            facts.append("The listing gives these utility figures: " + "; ".join(pieces) + ". It doesn't say which utilities the billed-back amount covers, so they may overlap and no amount is counted. Ask the landlord for the real monthly total.")
            plan_more = None
            per_more = []
        added = 0.0
        add_names: list[str] = []
        into = "added to" if isinstance(out.get("utilities_estimate"), (int, float)) else "counted as"
        if plan_more and not plan_more["total"]:
            more = _ordered_utilities(list(plan_more["names"]))
            added += plan_more["amount"]
            add_names += more.split(", ")
            each = ", ".join(f"{_join_names(i['names'])} about {_money_cents(i['amount'])} a month" for i in plan_more["kept"])
            facts.append(f"From the listing: {each}, {into} your utilities estimate.")
            for d in plan_more["dropped"]:
                facts.append(f"The listing also gives {_join_names(d['names']) if d['names'] else 'utilities'} at about {_money_cents(d['amount'])} a month. Only the higher figure for the same utility, {_money_cents(plan_more['amount'])}, is counted.")
        for c in per_more:
            cn = _ordered_utilities(list(c["names"]))
            added += c["monthly"]
            add_names += cn.split(", ")
            facts.append(f"{_join_names(cn.split(', ')).capitalize()} {_util_verb(cn)} billed at {_money_cents(c['raw'])} per {c['unit']}, which is about {_money_cents(c['monthly'])} a month, {into} your utilities estimate.")
        add_names_seen += add_names
        if add_names:
            have_inc = [w.strip() for w in included.split(",") if w.strip()] if included != "all" else list(_ALL_UTILITIES)
            gone_inc = [w for w in add_names if w in have_inc]
            if gone_inc:
                included = _ordered_utilities([w for w in have_inc if w not in gone_inc])
                facts.append(f"The listing also says {_join_names(gone_inc)} {_util_verb(', '.join(gone_inc))} included, but it gives you a bill for it, so it is not counted as included.")
            pays = _ordered_utilities([w.strip() for w in (pays + ", " + ", ".join(add_names)).split(",") if w.strip()])
            base_now = out.get("utilities_estimate")
            total_now = round((float(base_now) if isinstance(base_now, (int, float)) else 0.0) + added, 2)
            put("utilities_estimate", total_now)
            if isinstance(base_now, (int, float)):
                facts.append(f"The utilities estimate adds all the figures the listing gives, {_money_cents(total_now)} a month.")
    gen = _try(lambda: _util_general(utext, _pipe_list(text)))
    util_taken: list[float] = []  # figures the general reader counted as utilities: never also other monthly fees
    flat_trash_note = ""
    if gen and not gen["conflict"] and len(gen["items"]) > 1:
        flat_trash = [(lab, v) for lab, v, per in (_try(lambda: _flat_service_fees(text)) or []) if per and re.search(r"\btrash\b", lab)]
        trash_item = next((it for it in gen["items"] if it["names"] == ["trash"]), None)
        if flat_trash and trash_item and trash_item["monthly"] != flat_trash[0][1]:
            # "Trash passed through at $12/mo" next to "Flat $75/mo fee covers trash, pest and valet": the flat fee is counted once as a fee, so the $12 is left out
            gen = {**gen, "items": [it for it in gen["items"] if it is not trash_item]}
            gen["amount"] = round(sum(it["monthly"] for it in gen["items"]), 2)
            flat_trash_note = (f"The listing also says trash is {_money_cents(trash_item['monthly'])}/month, but a {_money_cents(flat_trash[0][1])}/month flat fee already covers trash. "
                               f"Only the flat fee is counted, so the {_money_cents(trash_item['monthly'])} is not. Ask which one applies.")
    if gen and not gen["conflict"] and any(re.search(r"don't agree|unclear about", f) for f in facts[n_facts_pre:]):
        gen = None  # the older readers found the listing contradicting itself: nothing is called included or counted
    old_est_names = {w for i in (_try(lambda: _estimate_items(utext)) or []) for w in i["names"]}
    if gen and old_est_names:
        gen = {**gen, "scoped_unknown": [w for w in gen.get("tenant") or [] if w in old_est_names and not any(w in it["names"] or (w in ("gas", "heat") and {"gas", "heat"} & set(it["names"])) for it in gen["items"])]}  # cycle 24: the older reader gave these a figure the line did not
    if gen and (_util_general_differs(gen, out.get("utilities_estimate"), pays, included, old_est_names)
                or sum("utilities estimate" in f for f in facts[n_facts_pre:]) >= 2 or flat_trash_note):
        # cycle 18: the general line reader disagrees with the older readers, so its figures, payers and notes replace theirs
        priced_names = {w for it in gen["items"] for w in it["names"]}
        keep_notes = [f for f in facts[n_facts_pre:] if f.startswith("Cable is")
                      or (re.search(r"(?:billed back to you|passed through to you), but the listing gives no amount", f) and not any(re.search(r"\b" + w + r"\b", f.lower()) for w in priced_names))]  # "Water is billed back to you, but the listing gives no amount" still stands
        del facts[n_facts_pre:]
        facts.extend(keep_notes)
        out.pop("utilities_estimate", None)
        counted, add_names_seen = set(), []
        if gen["conflict"]:
            facts.append(f"The listing says the landlord pays all the utilities, but it also says {_money_cents(gen['conflict'])} a month for utilities is paid by the tenant. "
                         "Those two lines don't agree, so none are counted as included and no amount is counted. Ask the landlord which utilities you really pay and how much.")
            included, pays = "", pays_pre if included_pre != "all" else ""
        else:
            tenant = gen["tenant"]
            base_pays = [w.strip() for w in pays.split(",") if w.strip() and w.strip() not in gen["landlord"]]
            pays = _ordered_utilities(base_pays + tenant)
            have = list(_ALL_UTILITIES) if included == "all" else [w.strip() for w in included.split(",") if w.strip()]
            included = _ordered_utilities([w for w in have + gen["landlord"] if w not in tenant and w not in pays.split(", ")]) if (have or gen["landlord"]) else ""
            put("utilities_estimate", gen["amount"])
            facts.append(_util_general_note(gen))
            if flat_trash_note:
                facts.append(flat_trash_note)
            counted = {w for it in gen["items"] for w in it["names"]}
    if gen and not gen["conflict"] and isinstance(out.get("utilities_estimate"), (int, float)) and abs(float(out["utilities_estimate"]) - gen["amount"]) < 0.01:
        util_taken = [v for it in gen["items"] if set(it["names"]) != {"internet"} for v in (it["raw"], it["monthly"])]
    rng = None if buying or included == "all" else _try(lambda: _util_range(utext))
    if rng and not (pays or not included):
        rng = None
    if rng:
        cur_est = out.get("utilities_estimate")
        lo_hit = isinstance(cur_est, (int, float)) and rng["low"] is not None and abs(float(cur_est) - rng["low"]) < 0.01
        if cur_est is None or lo_hit or (isinstance(cur_est, (int, float)) and abs(float(cur_est) - rng["amount"]) < 0.01):
            if cur_est is None or lo_hit:
                if lo_hit:
                    facts[n_facts_pre:] = [f for f in facts[n_facts_pre:] if "utilities estimate" not in f and "of that" not in f]
                put("utilities_estimate", rng["amount"])
                if rng["names"]:
                    pays = _ordered_utilities([w.strip() for w in (pays + ", " + ", ".join(rng["names"])).split(",") if w.strip()])
                    counted |= set(rng["names"])
            said_already = any(f"{_money_cents(rng['amount'])}" in f and re.search(r"higher|range|up to|total", f) for f in facts[n_facts_pre:])
            if said_already:
                pass  # an older reader already said it ("two figures ($40-$60). The higher one, $60, is counted")
            elif rng["low"] is not None:
                facts.append(f"The listing gives {_join_names(rng['names']) if rng['names'] else 'the utilities'} "
                             f"as a range, {_money_cents(rng['low'])} to {_money_cents(rng['amount'])} a month. The higher figure, {_money_cents(rng['amount'])}, is counted as your utilities estimate. Ask what a typical month costs.")
            elif not any(f"{_money_cents(rng['amount'])}" in f and "utilities estimate" in f for f in facts[n_facts_pre:]):
                facts.append(f"The listing gives about {_money_cents(rng['amount'])} a month in total for the utilities you pay, counted as your utilities estimate.")
    if not util_taken and not buying and isinstance(out.get("utilities_estimate"), (int, float)) and not isinstance(out.get("utilities_estimate"), bool):
        # cycle 22: whichever reader built the estimate, its figures are counted once: never also in other monthly fees ("Water/sewer/trash $35" next to "electric & gas (budget $80)")
        util_taken = [v for v in (_try(lambda: _utility_component_numbers(text, True)) or set()) if 0 < v <= float(out["utilities_estimate"]) + 0.5]
    text_full = text
    tail = None if buying else _try(lambda: _util_tail(text, out.get("utilities_estimate"), pays, included, counted | set(add_names_seen), facts[n_facts_pre:]))
    if tail:
        pays, included = tail["pays"], tail["included"]
        text_full, text = text, tail["text"]  # the fee readers below must not count an internet bill the estimate already holds; the last guard sees the whole text
        if tail["est"][0] == "set":
            put("utilities_estimate", tail["est"][1])
        elif tail["est"][0] == "pop":
            out.pop("utilities_estimate", None)
        counted |= tail["counted"]
        if tail["drop_counted"]:
            facts[n_facts_pre:] = [f for f in facts[n_facts_pre:] if "counted as your utilities estimate" not in f]  # the figure the line contradicts is not counted, so no note says it is
        if "internet" in tail["counted"]:
            facts[n_facts_pre:] = [f for f in (_drop_internet_unpriced(x) for x in facts[n_facts_pre:]) if f]
        facts.extend(tail["facts"])
    if not buying and isinstance(out.get("utilities_estimate"), (int, float)) and not isinstance(out.get("utilities_estimate"), bool):
        # cycle 27: "Utility package $175/mo flat (heat, water, electric, trash) billed back" is the utilities, counted once: the fee readers must not see it
        text = _UTIL_PACKAGE.sub(lambda m: " " if any(abs(float(a.replace(",", "")) - float(out["utilities_estimate"])) < 0.5 for a in re.findall(r"\$[ \t]?(\d[\d,]*(?:\.\d\d)?)", m.group(0))) else m.group(0), text)
    _UTIL_TRACE.set({"amount": out.get("utilities_estimate"), "names": sorted(counted | set(add_names_seen))})
    if buying and included and included != "all":
        hm = re.search(r"\b(?:hoa|assessment|association|condo[ \t]+fees?|dues)\b[^.\n]{0,60}?\b(?:includes?|covers?)\b([^.\n]{0,80})", utext, re.I)
        covered = [w for w in included.split(", ") if hm and re.search(r"\b" + re.escape(w) + r"\b", hm.group(1), re.I)]
        if covered:
            facts.append(f"The HOA fee covers {_join_names(covered)}, so {'it is' if len(covered) == 1 else 'they are'} marked as included. {'It is' if len(covered) == 1 else 'They are'} paid out of the HOA fee, not a separate bill, so no utility amount is counted.")
    inc_set = set(_ALL_UTILITIES) if included == "all" else {w.strip() for w in included.split(",") if w.strip()}
    if "electric" in pays.split(", ") and "gas" not in pays.split(", ") and "gas" not in inc_set and re.search(r"\bgas\s+cooking\b", utext, re.I):
        # "Gas cooking, electric tenant": the renter pays the electric, and a gas range means a gas bill too, with no amount given
        pays = _ordered_utilities([w.strip() for w in (pays + ", gas").split(",") if w.strip()])
        facts.append("The listing says gas cooking and that you pay electric. Gas is counted as something you pay, with no amount. Ask whether the gas bill is yours.")
    if included and included != "all" and (_HEAT_IS_GAS.search(utext) or _HEAT_IS_GAS.search(text)):
        # "Heat is gas, included": the gas that heats the home is the heat, so both words are included (unless the renter pays one of them)
        inc_now = [w.strip() for w in included.split(",") if w.strip()]
        pay_now = {w.strip() for w in pays.split(",") if w.strip()}
        if ("heat" in inc_now) != ("gas" in inc_now):
            other = "gas" if "heat" in inc_now else "heat"
            if other not in pay_now and not (other == "gas" and re.search(r"\bgas[ \t]+(?:cooking|stove|range|oven)\b", utext, re.I)):
                included = _ordered_utilities(inc_now + [other])
    priced_now = counted | set(add_names_seen)
    if "gas" in priced_now and "heat" in {w.strip() for w in pays.split(",")} and "heat" not in priced_now \
            and not re.search(r"\bheat", utext, re.I):
        # cycle 20: "Tenant pays all utilities ... Nicor $95 winter": the gas bill is the heat, so heat is not a second unknown
        pays = _ordered_utilities([w.strip() for w in pays.split(",") if w.strip() and w.strip() != "heat"])
    pay_words_now = {w.strip() for w in pays.split(",") if w.strip()}
    if {"gas", "heat"} <= pay_words_now and "heat" not in priced_now and not re.search(r"\bheat", text, re.I):
        # cycle 25: the listing never says heat, so it does not separate the two: one unknown (the gas), not gas and heat
        # cycle 26: also when "gas" only comes from "tenant responsible for all utilities"
        pays = _ordered_utilities([w for w in (x.strip() for x in pays.split(",")) if w and w != "heat"])
    for hw, hamt in (_try(lambda: _hoa_price_conflicts(text)) or []):
        # cycle 23: "HOA covers water" and "water $25" disagree: water is neither counted nor called included, it stays unknown
        inc_left = [w.strip() for w in included.split(",") if w.strip() and w.strip() != hw] if included != "all" else [w for w in _ALL_UTILITIES if w != hw]
        included = _ordered_utilities(inc_left) if inc_left else ""
        pays = _ordered_utilities([w.strip() for w in (pays + ", " + hw).split(",") if w.strip()])
        facts.append(f"The listing says the HOA covers {hw} and also lists a {hw} charge of {_money_cents(hamt)} a month. Ask which is right. "
                     f"{hw.capitalize()} is not counted and not marked included.")
    if "heat" in {w.strip() for w in pays.split(",")} and (_HEAT_IS_GAS.search(utext) or _HEAT_IS_GAS.search(text)):
        # cycle 23: "Heat is gas. Tenant pays gas, electric": the gas is the heat, so heat is not a second utility the renter pays
        keep_pay = [w.strip() for w in pays.split(",") if w.strip() and w.strip() != "heat"]
        inc_words = set(_ALL_UTILITIES) if included == "all" else {w.strip() for w in included.split(",") if w.strip()}
        if "gas" not in keep_pay and "gas" not in inc_words:
            keep_pay.append("gas")
        pays = _ordered_utilities(keep_pay)
    if {"heat", "gas"} <= {w.strip() for w in pays.split(",")} and _HEAT_GAS_GROUP.search(utext):
        # cycle 27: "Heat & gas: tenant" is one bill for the same thing, not two unknowns
        pays = _ordered_utilities([w.strip() for w in pays.split(",") if w.strip() and w.strip() != "heat"])
    facts[:] = _try(lambda: _heat_is_gas_words(facts, text)) or facts
    if except_priced and included and included != "all":
        included = _ordered_utilities([w.strip() for w in included.split(",") if w.strip() and w.strip() not in except_priced])  # "all except trash" never made a priced trash free
    put("utilities_included", included)
    if pays:
        # Nothing is included for these, so the monthly cost keeps its own estimate line (a guess), and the listing's words are kept.
        facts.append(f"Tenant pays {pays}.")
        mapped = _tenant_pays_choices(pays)
        if mapped:
            put("tenant_pays", mapped)
    avail_read = _try(lambda: _available(_ordinal_dates(text)))
    lease_read = _try(lambda: _lease_months(text))
    range_start, range_months, range_note = _try(lambda: _lease_dates(text)) or (None, None, "")
    if avail_read is None and range_start:
        avail_read = range_start  # "Lease: Aug 1 2027 to Jul 31 2028" starts on the first date
    if lease_read is None and range_months:
        lease_read = range_months
    if range_note:
        facts.append(range_note)
    phrase_start, phrase_end = _try(lambda: _lease_phrases(text)) or (None, None)
    two_lengths = _try(lambda: _lease_two_lengths(text)) or ""
    if extra_lease_opt and lease_read == extra_lease_opt[1]:
        # cycle 25: "$2,360/mo, or $2,310 with 14-month lease": the 14 months belong to the other price, so it is not the lease length of the rent saved
        lease_read = _try(lambda: _lease_months(_blank_lease_option(text, extra_lease_opt[1], extra_lease_opt[0])))
    if lease_opts and lease_plan_pick:
        lease_read, two_lengths = None, ""  # cycle 24: the plan picked names no lease length, so none is saved
    elif lease_opts:
        lease_read, two_lengths = lease_chosen[1], ""  # cycle 23: the lease length of the option whose rent is saved
    if lease_read is None and not two_lengths:
        lease_read = _try(lambda: _lease_bare_months(text, bool(_lease_choices(text)) or bool(range_start)))
    lease_start_read = phrase_start or range_start
    lease_end_read = phrase_end
    if lease_end_read and lease_read is None and not two_lengths:
        known = lease_start_read or avail_read
        if known:
            lease_read = _try(lambda: _whole_months(known, lease_end_read))  # type: ignore[arg-type]
        if lease_read is None and not known:
            facts.append("The listing gives a lease end date but no start date, so the lease length is left empty. Ask when the lease starts.")
    if two_lengths:
        lease_read = None
        lease_end_read = None
        facts.append(f"The listing offers two lease lengths ({two_lengths}), so the lease length is left empty. Ask which one you would get.")

    if avail_read is None and lease_start_read:
        avail_read = lease_start_read  # "12 month lease starting 1/1/27": the lease start is the date it is available
    if avail_read is None:
        avail_read = _try(lambda: _bare_start_date(text))  # "Starts 3-1-27"
    if avail_read is None:
        month_only = _try(lambda: _available_month_only(text))
        if month_only:  # "Move in Aug 2027": no day is given, so none is made up
            facts.append(f"The listing says move in {month_only} but gives no day, so the available date is left empty. Ask which day the place is ready.")
    fix_date = None if buying else _try(lambda: _corrected_date(text))
    if fix_date and fix_date != avail_read:  # cycle 26: "Update: available date is now Feb 1" replaces the earlier date
        if avail_read:
            facts.append(_corrected_fact_note("available date", _nice_date(fix_date), _nice_date(avail_read)))
        avail_read = fix_date
    put("available_from", avail_read)
    put("lease_months", lease_read)
    put("lease_start", lease_start_read)
    put("lease_end", lease_end_read)
    if lease_read is None and not two_lengths:
        choices = _try(lambda: _lease_choices(text))
        if choices:
            facts.append(f"The listing gives more than one lease length ({choices}), so the lease length is left empty. Ask which one you would get.")
    facts.extend(_try(lambda: _lease_offer_note(text, lease_read)) or [])
    facts.extend(_try(lambda: _month_to_month_note(text, lease_read)) or [])
    facts.extend(_try(lambda: _commute_claims(text)) or [])
    put("year_built", _try(lambda: _year_built(text) or _year_built_delivered(text)))
    kept_limits = [f"{line.rstrip('.')}." for line in (_try(lambda: _pet_limits(ptext)) or [])
                   if not _pet_limit_is_in_fields(line, out)]
    facts += kept_limits
    if not any(_WEIGHT_WAIVER.search(k) for k in kept_limits):  # cycle 25: the weight limit can be waived on approval, said once (a kept line that says it already is enough)
        waiver_note = _try(lambda: _pet_weight_waiver_note(ptext, out)) or ""
        if waiver_note:
            facts.append(waiver_note)

    def fees() -> None:
        dep_src, wired = _split_wired_deposit(dep_text)
        cond_dep = _try(lambda: _conditional_deposit(dep_src))
        if cond_dep:
            dep_src = cond_dep[2]
            facts.append(f'The listing gives a {_usd(cond_dep[0])} security deposit "{cond_dep[1]}". It only applies on that condition, so it is not saved as the deposit. Ask what your deposit will be.')
        best_case, dep_src = _try(lambda: _best_case_deposit(dep_src)) or (None, dep_src)
        if best_case is not None:
            facts.append(f"The listing gives a best-case deposit of {_usd(best_case)} with approved credit. The deposit is not saved, because it may be more for you, so ask what the deposit will be.")
        if wired:
            facts.append("The listing asks for a deposit by wire. A wire can't be taken back, so the deposit is left blank. Don't send money before you have toured the place.")
        nonref_dep = None if _SALE_WORDS.search(text) else _try(lambda: _nonrefundable_deposit(dep_src))
        if nonref_dep:  # cycle 23: "Security deposit is $400 (not refundable, it is a cleaning fee)" is money you do not get back: a move-in fee
            dep_src = dep_src.replace(nonref_dep[1], " ") if nonref_dep[1] in dep_src else re.sub(r"\$\s?" + re.escape(f"{nonref_dep[0]:,.0f}") + r"(?![\d,])", " ", dep_src, count=1)
        dep_src = _try(lambda: _blank_named_deposits(dep_src)) or dep_src  # cycle 26: a deposit inside a pet, key, parking or other named clause is never the security deposit
        either = None if _SALE_WORDS.search(text) else _try(lambda: _deposit_or_fee(dep_src))
        if either:
            dep_src = either[2]
            facts.append(either[3])
        dep = _money_after(dep_src, r"(?:security |refundable |damage |rental )?deposits?|sec\.?[ \t]*dep\.?", hi=50000, skip_before=r"(?:pet|parking|holding|reservation|key|application|garage|fob|remote|gate|access|mailbox|storage|bike|locker|lock|card|pool|cleaning|venmo|zelle|paypal|cash\s?app|wire|wired|crypto|bitcoin|gift)\s*$", verbs=True)
        dep = [v for v in dep if v is not None]
        rent_now = out.get("price")
        wm = _DEP_WHICHEVER.search(dep_src) if dep else None
        if wm and not _SALE_WORDS.search(text):  # cycle 26: "$1,000 or 75% of rent, whichever is greater": the rule decides, so the figure alone is not the deposit
            pct = float(wm.group("pct")) / 100.0
            word = wm.group("w").lower()
            if isinstance(rent_now, (int, float)) and 200 <= rent_now <= 30000:
                pick = max(dep[0], pct * float(rent_now)) if word in ("greater", "higher", "more", "larger") else min(dep[0], pct * float(rent_now))
                dep = [pick]
                facts.append(f"The listing says the deposit is {_usd(float(wm.group('amt').replace(',', '')))} or {wm.group('pct')}% of rent, whichever is {word}. The {word} one, worked out from the rent, "
                             "is saved. Ask the landlord to confirm the deposit.")
            else:
                dep = []
                facts.append(f"The listing says the deposit is {_usd(float(wm.group('amt').replace(',', '')))} or {wm.group('pct')}% of rent, whichever is {word}, but the rent was not read, "
                             "so the deposit is left empty. Fill it in once you know the rent.")
        by_months = _deposit_in_months(_blank_named_month_deposits(text))  # cycle 27: "Pet deposit: one month" is not the security deposit
        by_phrase = ""
        if not by_months and not _is_sale_text(text):  # cycle 27: "half month", "Sec dep 1.5 months", "due at signing: one month"
            gm = _try(lambda: _deposit_months_general(dep_src))
            if gm:
                by_months, by_phrase = gm
        each_dep = _try(lambda: _deposit_each(text))
        dep_mult = None if dep else _try(lambda: _deposit_multiple(dep_src))
        if dep:
            put("deposit", dep[0])
        elif each_dep and not _SALE_WORDS.search(text):
            put("deposit", each_dep)  # cycle 17: "first, last and security deposit ($2,800 each)"
        elif (or_fee_ref := (None if _SALE_WORDS.search(text) else _try(lambda: _deposit_or_fee_refundable(dep_src)))):
            put("deposit", or_fee_ref[0])  # cycle 27: "Deposit or fee: $1,000 refundable": a refundable amount is a deposit
            facts.append(f'The listing says "{or_fee_ref[1]}". It is refundable, so it is read as the security deposit, {_usd(or_fee_ref[0])}. Ask the landlord to confirm it.')
        elif dep_mult and isinstance(rent_now, (int, float)) and 200 <= rent_now <= 30000 and not _is_sale_text(text):
            put("deposit", dep_mult[0] * float(rent_now))  # cycle 21: "Security 1.5x rent", "Deposit: 1x1"
            facts.append(f"The listing gives the deposit as \"{dep_mult[1]}\", {dep_mult[0]:g} month{'s' if dep_mult[0] != 1 else ''} of rent. Worked out from the {_usd(float(rent_now))} rent that is "
                         f"{_usd(dep_mult[0] * float(rent_now))}. Ask the landlord to confirm the deposit.")
        elif dep_mult and not _is_sale_text(text):
            facts.append(f"The listing gives the deposit as \"{dep_mult[1]}\", {dep_mult[0]:g} month{'s' if dep_mult[0] != 1 else ''} of rent, but the rent was not read, so the deposit is left empty. Fill it in once you know the rent.")
        elif by_months and isinstance(rent_now, (int, float)) and 200 <= rent_now <= 30000 and not _is_sale_text(text):
            put("deposit", by_months * float(rent_now))  # "security deposit one month", "deposit equal to one month's rent"
            hm = re.search(r"\$[ \t]?\d(?:\.\d+)?[ \t]*months?\b[^.\n;|]{0,30}?\bdeposit\b[^.\n;|]{0,12}", dep_src, re.I)
            if not hm and _SALE_WORDS.search(re.sub(r"\bnew[ \t]+construction\b", " ", text, flags=re.I)):  # cycle 26: "Deposit 1.5 months" in a rental that says "open house": filled from the rent, and the note says it was worked out
                facts.append(f"The listing gives the deposit as {by_months:g} month{'s' if by_months != 1 else ''} of rent, so the deposit is worked out from the rent. Ask the landlord to confirm it.")
            if hm:  # cycle 25: "$1.5 months rent deposit hold": the dollar sign is a typo for the months, so the figure is explained here and no note repeats it
                facts.append(f'The listing says "{" ".join(hm.group(0).split())}". It is read as a deposit of {by_months:g} months of rent, '
                             f"{_usd(by_months * float(rent_now))} from the {_usd(float(rent_now))} rent. Ask what the deposit is and whether it is a hold.")
            elif by_phrase:  # cycle 27: months in a new wording turned into dollars from the rent, with one note that says so (the older readings keep their old behavior)
                facts.append(f'The listing gives the deposit as "{by_phrase}", {_months_words(by_months)} of rent. Worked out from the {_usd(float(rent_now))} rent that is '
                             f"{_usd(by_months * float(rent_now))}. Ask the landlord to confirm the deposit.")
        elif by_months and not _is_sale_text(text):
            facts.append(f"The listing says the security deposit is {_months_words(by_months)} of rent, but the rent was not read, so the deposit is left empty. Fill it in once you know the rent.")
        elif (bare_sec := _try(lambda: _bare_security_amount(dep_src))) and not _SALE_WORDS.search(text):
            put("deposit", bare_sec)  # cycle 20: "first month + $3,100 security + $200 move-in fee"
        elif best_case is None and re.search(r"\b(?:no|zero|\$0) (?:security )?deposit|\bdeposit\s*[:\-]?\s*(?:\$0|none|waived|zero)\b", text, re.I):
            put("deposit", 0.0)
        elif nonref_dep and best_case is None and not cond_dep and not wired:
            put("deposit", 0.0)  # the only deposit the listing names is the one that is not refundable, so no refundable deposit is stated
        fx_dep = fixed_facts.get("deposit")
        if fx_dep and not buying and not _is_sale_text(text):  # cycle 26: a "Corrected:" or "now" line that names the deposit replaces the earlier one
            old_dep = fx_dep[1] if fx_dep[1] is not None else out.get("deposit")
            if fx_dep[1] is not None or (old_dep is not None and not _same_num(old_dep, fx_dep[0])):
                facts.append(_corrected_fact_note("deposit", _usd(fx_dep[0]), _usd(float(old_dep)) if old_dep is not None else None))
            put("deposit", fx_dep[0])
        dcn = _try(lambda: _deposit_credit_note(text, out.get("deposit")))
        if dcn:
            facts.append(dcn)
        pen = _try(lambda: _penalty_fee_note(text))
        if pen:
            facts.append(pen)
        app = _money_after(text, r"application(?: processing)? fees?|app(?:lication)? fee|screening fee|background check fee", hi=1000)
        per_adult_fee = _try(lambda: app_fee_per_adult(text))
        if app:
            put("application_fee", app[0])
        elif per_adult_fee:
            put("application_fee", per_adult_fee)
        elif (bare_app := re.search(r"\$\s?(\d{1,4}(?:\.\d\d)?)[ \t]+application\b(?![ \t]*(?:fee|each|per|/))", text, re.I)) and float(bare_app.group(1)) > 0:
            put("application_fee", float(bare_app.group(1)))  # "Fees: $65 application, $175 amenity fee monthly"
        elif (bare_app2 := re.search(r"(?<![\w-])application[ \t]*[:\-=][ \t]*\$\s?(\d{1,4}(?:\.\d\d)?)(?!\d|,\d)(?![ \t]*(?:/[ \t]*(?:adult|person|applicant|occupant|tenant|resident|mo|month|each)|per|each))|(?<![\w-])application[ \t]+\$\s?(\d{1,4}(?:\.\d\d)?)(?!\d|,\d)(?![ \t]*(?:/[ \t]*(?:adult|person|applicant|occupant|tenant|resident|mo|month|each)|per|each))", text, re.I)) and float(bare_app2.group(1) or bare_app2.group(2)) > 0:
            put("application_fee", float(bare_app2.group(1) or bare_app2.group(2)))  # cycle 18: "Application $40", "Application: $40"
        elif (bare_app3 := re.search(r"(?<![\w-])app[ \t]*[:\-=]?[ \t]*\$\s?(\d{1,4}(?:\.\d\d)?)(?!\d|,\d)(?![ \t]*(?:/|per\b|each\b|off\b|waived|credit|background|screening))", text, re.I)) and float(bare_app3.group(1)) > 0 \
                and not re.search(r"\b(?:no|free|zero|waived?)[ \t]*$", text[max(0, bare_app3.start() - 8):bare_app3.start()], re.I):
            put("application_fee", float(bare_app3.group(1)))  # cycle 22: "Fees: App $55, admin $200"
        elif (bare_app4 := re.search(r"(?<![\w.,$-])\$\s?(\d{1,4}(?:\.\d\d)?)(?!\d|,\d)[ \t]+(?:online[ \t]+)?app\b(?![ \t]*(?:store|download|\-?based|login|portal))(?![ \t]*(?:/[ \t]*(?:mo|month|adult|person|applicant|occupant|tenant|resident|yr|year|each)|per\b|each\b|credit|background|screening))", text, re.I)) and float(bare_app4.group(1)) > 0 \
                and not re.search(r"\b(?:no|free|zero|waived?)[ \t]*$", text[max(0, bare_app4.start() - 8):bare_app4.start()], re.I):
            put("application_fee", float(bare_app4.group(1)))  # cycle 25: "Fees: $50 app, $150 admin": "app" is the application fee
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
                    facts.append(f"The {_usd(per_applicant[0])} admin fee is charged per applicant, so it is counted as the application fee for each adult who applies.")
            elif float(out["application_fee"]) != per_applicant[0]:
                facts.append(f"The listing also has a {_usd(per_applicant[0])} admin fee per applicant. It is not counted, because an application fee is already filled in. Ask whether they are two fees.")
        bg_each = _try(lambda: _background_check_each(text))
        bg_single = bool(bg_each) and per_adult_fee == bg_each and len(re.findall(r"\$\s?" + re.escape(f"{bg_each:g}") + r"(?![\d,])", text)) == 1  # cycle 22: one figure, so the per-adult phrase IS the background check
        if bg_each and not bg_single and out.get("application_fee") and per_adult_fee and float(out["application_fee"]) == per_adult_fee:
            # cycle 21: "$35 per adult plus $25 background check each": both are charged to every adult, so the fee per adult is the two together
            out["application_fee"] = _tidy_number(float(out["application_fee"]) + bg_each)
            facts.append(f"The {_usd(per_adult_fee)} application fee and the {_usd(bg_each)} background check are both charged to each adult who applies, "
                         f"so the application fee saved is the two together, {_usd(per_adult_fee + bg_each)} per adult.")
        if bg_each and re.search(r"\b(?:background|screening)[ \t]+(?:check|report)", text, re.I) and not (not bg_single and per_adult_fee and out.get("application_fee") is not None and float(out["application_fee"]) == per_adult_fee + bg_each):
            same_fig = re.search(r"\bapp(?:lication)?(?:[ \t]+(?:processing[ \t]+)?fees?)?[ \t:\-=]*\$\s?" + re.escape(f"{bg_each:g}") + r"(?:\.\d\d)?[ \t]*(?:background|screening|credit)\b", text, re.I)
            have_app = out.get("application_fee")
            if have_app in (None, "", 0, 0.0) or ((same_fig or bg_single) and float(have_app) == bg_each):
                # cycle 22: "Background check $25 each", "Application $25 background check each": every adult pays it, so it is the per-adult application cost
                put("application_fee", bg_each)
                out["application_fee_per_adult"] = 1
                facts.append(f"The {_usd(bg_each)} background check is charged to each adult who applies, so it is saved as the application fee per adult. "
                             "The listing gives no other application fee. Ask if there is one.")
            elif float(have_app) != bg_each:
                facts.append(f"The listing also says the background check is {_usd(bg_each)} for each adult. It is not added to the {_usd(float(have_app))} application fee, "
                             "because the listing does not say if that fee is per adult too. Ask what each adult pays in total.")
        if either and either[4] in mi_text:
            mi_text = mi_text.replace(either[4], " " * len(either[4]), 1)  # the one-time fee the listing offers instead of the deposit is not also a move-in fee
        mi_text = re.sub(r"\$\s?\d[\d,]*(?:\.\d\d)?[ \t]*(?:/[ \t]*mo(?:nth)?\b|per[ \t]+month|a[ \t]+month|monthly|each[ \t]+month)(?=[ \t]+(?:[\w\"\u201c\u201d'-]+[ \t]+){0,2}fees?\b)", " ", mi_text)  # cycle 17: "$100/month community fee" is monthly, never a one-time move-in fee
        mi = _money_after(_without_pet_one_time(mi_text), r"(?:admin(?:istrative|istration)?|move[- ]in|lease[- ](?:signing|initiation|admin)|processing|community|one[- ]time|key) fees?", hi=5000)
        if not mi:
            bare_admin = _try(lambda: _bare_admin_fee(mi_text))
            if bare_admin:
                mi = [bare_admin]
                facts.append(f"The {_usd(bare_admin)} admin amount is counted as a one-time admin fee in move-in fees. If it is a discounted price, ask what the usual fee is.")
        extra_one_time = 0.0
        if not buying and not _is_sale_text(text) and not (isinstance(out.get("price"), (int, float)) and out["price"] >= 20000):
            counted_mi = list(mi)
            for label_x, v_x, kind_x in _try(lambda: _one_time_fee_items(mi_text)) or []:
                if v_x in counted_mi:
                    counted_mi.remove(v_x)
                    continue
                if label_x.startswith(("admin", "processing")) and per_applicant and v_x == per_applicant[0]:
                    continue
                extra_one_time += v_x  # cycle 21: "Fees: application $50, admin $120, lease processing $60", "$250 amenity fee one-time"
                if kind_x == "key" and isinstance(out.get("deposit"), (int, float)) and not isinstance(out.get("deposit"), bool) and out["deposit"] > 0 and label_x.startswith("key deposit"):
                    # cycle 23: a key deposit is money you get back, so it is added once to the deposit (not spread over the lease like a fee)
                    extra_one_time -= v_x
                    sec_x = float(out["deposit"])
                    out["deposit"] = _tidy_number(sec_x + v_x)
                    facts.append(f"The security deposit is {_usd(sec_x)} and the key deposit is {_usd(v_x)}, so the deposit saved is both together, {_usd(sec_x + v_x)}. "
                                 "The key deposit is counted once in the cash at move-in and not spread over the lease. Ask when you get it back.")
                elif kind_x == "key":
                    facts.append(f"The {_usd(v_x)} {label_x} is counted in the cash at move-in. The listing may say it comes back, so ask when you get it back.")
        if nonref_dep and not buying and not _is_sale_text(text):
            extra_one_time += nonref_dep[0]
            _dep_read = out.get("deposit")
            facts.append(f"The {_usd(nonref_dep[0])} deposit is not refundable, so it is counted as a one-time move-in fee in the cash at move-in, not as a deposit you get back."
                         + ("" if isinstance(_dep_read, (int, float)) and not isinstance(_dep_read, bool) and _dep_read > 0 else " Ask if there is also a refundable security deposit."))  # cycle 27: a deposit that was read leaves no such question
        clean_in, clean_notes = _try(lambda: _cleaning_fee(text)) or (None, [])
        facts.extend(clean_notes)
        landlord_months = _try(lambda: _landlord_fee_months(text))
        landlord_fee = 0.0
        if landlord_months:
            rent_l = out.get("price")
            if isinstance(rent_l, (int, float)) and 200 <= rent_l <= 30000 and not _is_sale_text(text):
                landlord_fee = landlord_months * float(rent_l)
                facts.append(f"The landlord fee is {_months_words(landlord_months)} of rent ({_usd(landlord_fee)}), worked out from the rent. "
                             "It is counted as a one-time move-in fee.")
            else:
                facts.append(f"The listing says the landlord fee is {_months_words(landlord_months)} of rent, but the rent was not read, so no amount is saved. Fill it in once you know the rent.")
        if mi or clean_in or landlord_fee or extra_one_time:
            base = (sum(dict.fromkeys(mi).keys()) if len(mi) > 1 else mi[0]) if mi else 0.0
            put("move_in_fees", base + (clean_in or 0.0) + landlord_fee + extra_one_time)
        facts.extend(_try(lambda: _conditional_fee_notes(text, bool(mi) or out.get("application_fee") is not None)) or [])
        br = _money_after(text, r"broker(?:'?s)? fee|agent(?:'?s)? fee|finder'?s fee", hi=20000)
        if br:
            put("broker_fee", br[0])
        elif (broker_pct := _try(lambda: _broker_fee_percent(text))):
            pct, of_what, months_mult = broker_pct
            rent_b = out.get("price")
            if isinstance(rent_b, (int, float)) and 200 <= rent_b <= 30000 and not _is_sale_text(text):
                amount_b = round(pct / 100 * months_mult * float(rent_b))
                put("broker_fee", amount_b)
                cond_b = re.search(r"\b(?:broker|agent|finder)(?:'?s)?[ \t]+fee\b[^.\n]{0,60}?\b((?:for|if|when|only[ \t]+(?:if|for|when))[ \t]+[^.\n;]{3,40})", text, re.I)
                facts.append(f"The broker fee is {pct:g}% of {of_what}. Worked out from the ${float(rent_b):,.0f} rent that is ${amount_b:,.0f}. Ask the broker to confirm the amount."
                             + (f" The listing says it applies {' '.join(cond_b.group(1).split())}." if cond_b else ""))
            else:
                facts.append(f"The listing says the broker fee is {pct:g}% of {of_what}, but the rent was not read, so the broker fee is left empty. Fill it in once you know the rent.")
        else:
            broker_months = _try(lambda: _broker_fee_months(text))
            if broker_months:
                rent_b = out.get("price")
                if isinstance(rent_b, (int, float)) and 200 <= rent_b <= 30000 and not _is_sale_text(text):
                    put("broker_fee", broker_months * float(rent_b))
                    facts.append(f"The broker fee is {broker_months:g} month{'s' if broker_months != 1 else ''} of rent (${broker_months * float(rent_b):,.0f}), worked out from the rent.")
                else:
                    facts.append(f"The listing says the broker fee is {broker_months:g} month{'s' if broker_months != 1 else ''} of rent, but the rent was not read, so the broker fee is left empty. Fill it in once you know the rent.")
        for fl_name, fl_amt in _try(lambda: _fee_list_utilities(text)) or []:
            # cycle 26: "Fees: admin $175 | Trash $12 | lease processing $125": a utility inside a fee list is a utility, counted once in the utilities estimate
            said = any(re.search(rf"\b{fl_name}\b", f, re.I) and re.search(r"counted|flat fee|billed back", f, re.I) for f in facts)
            est_f = out.get("utilities_estimate")
            if said or (isinstance(est_f, (int, float)) and not isinstance(est_f, bool) and abs(float(est_f) - fl_amt) < 0.01):
                continue
            have_f = [w.strip() for w in str(out.get("tenant_pays") or "").split(",") if w.strip()]
            if fl_name in str(out.get("utilities_included") or "").split(", "):
                if fl_name not in except_priced:
                    continue
                rest_inc = [w for w in str(out.get("utilities_included") or "").split(", ") if w and w != fl_name]  # "all except trash" never made the trash free
                if rest_inc:
                    put("utilities_included", ", ".join(rest_inc))
                else:
                    out.pop("utilities_included", None)
            put("utilities_estimate", round((float(est_f) if isinstance(est_f, (int, float)) and not isinstance(est_f, bool) else 0.0) + fl_amt, 2))
            util_taken.append(fl_amt)
            if not isinstance(est_f, (int, float)) and have_f:
                left_f = [w for w in have_f if w != fl_name]
                if left_f:  # the estimate now holds only this item, so what else the renter pays must still show as having no amount
                    facts.append(f"{_join_names(left_f).capitalize()} {'is' if len(left_f) == 1 else 'are'} listed as something you pay, with no amount. Ask what {'it costs' if len(left_f) == 1 else 'they cost'}.")
            facts.append(f"{fl_name.capitalize()} is {_money_cents(fl_amt)}, listed among the fees. The listing does not say how often, so it is counted as monthly in your utilities estimate. Ask if that is right.")
        monthly = 0.0
        added: list[float] = []
        pool = [v for v in dict.fromkeys(_money_monthly_fees(text)) if v not in util_taken]  # cycle 18: a utility figure is counted once, in the utilities estimate
        for v in pool:
            monthly += v; added.append(v)
        for v in _try(lambda: _monthly_list_fees(text)) or []:  # cycle 17: each item of a "Monthly:" list counts, equal amounts too
            if v in pool:
                pool.remove(v)  # already counted by the reader above
            else:
                monthly += v; added.append(v)
        counted, listed = _try(lambda: _extra_monthly(text)) or ([], [])
        for label, v in counted:
            if buying and re.search(r"parking|space|spot|garage|stall|carport|\bcar\b", label):
                continue  # cycle 21: the cost of buying does not count parking, so it is not in other monthly fees (one note says so)
            monthly += v; added.append(v)
            facts.append(f"${v:,.0f}/month extra for {label} is counted in other monthly fees. If it is optional, take it out.")
        for label, v in _try(lambda: _mandatory_monthly_fees(text)) or []:
            monthly += v; added.append(v)
            facts.append(f"The {label} is ${v:,.0f}/month and the listing says it is required, so it is counted in other monthly fees.")
        storage = _try(lambda: _storage_fees(text)) or []
        listed = [(l, v) for l, v in listed if not re.search(r"storage|locker", l)]
        svc_locker = {v for l, v in (_try(lambda: _service_fee_items(text)) or []) if re.search(r"locker", l) and not re.search(r"package|parcel|mail", l)}
        for label, v, required in storage:
            if v in svc_locker and not required:
                continue  # cycle 19: a locker priced in a list of monthly services is counted below, so it is not also called optional
            if required:
                monthly += v; added.append(v)
                facts.append(f"{label[:1].upper() + label[1:]} is ${v:,.0f}/month and the listing says it is required, so it is counted in other monthly fees.")
            else:
                facts.append(f"{label[:1].upper() + label[1:]} is ${v:,.0f}/month. It is not counted in the cost because it looks optional. Add it to other monthly fees if you need it.")
        for label, v in listed:
            facts.append(f"{label[:1].upper() + label[1:]} is ${v:,.0f}/month extra. It looks optional, so it is not counted in the cost. Add it to other monthly fees if you need it.")
        already_monthly = set(_try(lambda: _money_monthly_fees(text)) or [])
        for label, v, has_period in _try(lambda: _flat_service_fees(text)) or []:
            if v in util_taken:
                continue  # cycle 18: the general utility reader already counted this figure in the utilities estimate
            if isinstance(out.get("utilities_estimate"), (int, float)) and abs(float(out["utilities_estimate"]) - v) < 0.01:
                continue  # already the utilities estimate: never counted twice
            if v in already_monthly:
                continue  # cycle 17: "flat $30 per month for trash and lawn" is already counted above, never twice
            monthly += v; added.append(v)
            facts.append(f"The {label} flat fee is ${v:,.0f}" + ("/month" if has_period else "") + ", counted once in other monthly fees."
                         + ("" if has_period else " The listing does not say how often, so it is counted as monthly. Ask if that is right."))
            covered_utils = [w for w in re.findall(r"hot water|water|sewer|sewage|trash|garbage|waste", label) if w not in ("garbage", "waste", "sewage")]
            tenant_list = [w.strip() for w in str(out.get("tenant_pays") or "").split(",")]
            paid_here = [w for w in dict.fromkeys("water" if u == "hot water" else u for u in covered_utils) if w in tenant_list]
            if paid_here:
                # cycle 25: a utility whose flat figure is counted in other monthly fees is no longer "not counted yet" in the utilities line
                left_pay = [w for w in tenant_list if w and w not in paid_here]
                if left_pay:
                    out["tenant_pays"] = ", ".join(left_pay)
                else:
                    out.pop("tenant_pays", None)
                facts.append(f"{', '.join(paid_here).capitalize()} {'is' if len(paid_here) == 1 else 'are'} paid through that flat fee, so {'it is' if len(paid_here) == 1 else 'they are'} not counted again in your utilities estimate.")
            covered_set = {"water" if u == "hot water" else u for u in covered_utils}
            if covered_set and any(f.startswith("The listing says utilities are billed back to you (RUBS), but it gives no amount") for f in facts):
                # cycle 26: "Utilities billed back: water/sewer/trash $75 flat" gave the billed-back items a figure, so "no amount" is no longer true
                for cl in re.split(r"\n|;|\.(?=\s|$)", utext.lower()):
                    if re.search(r"\bbilled\b|\brubs\b", cl) and set(re.findall(_ROLE_WORD, cl)) and {("water" if w == "hot water" else "trash" if w == "garbage" else "sewer" if w == "sewage" else w) for w in re.findall(_ROLE_WORD, cl)} <= covered_set:
                        facts[:] = [f for f in facts if not f.startswith("The listing says utilities are billed back to you (RUBS), but it gives no amount")]
                        break
            dups = _try(lambda: _flat_overlap(utext, covered_set)) or []
            est_o = out.get("utilities_estimate")
            if dups and isinstance(est_o, (int, float)) and not isinstance(est_o, bool) and not any("already covers" in f for f in facts):
                # cycle 26: "(water and trash only) $60 flat" next to "Trash is $12/mo extra": the flat fee already covers trash, so the $12 is never counted twice
                gone_amt = round(sum(d["amount"] for d in dups), 2)
                left_est = round(float(est_o) - gone_amt, 2)
                if left_est >= 0 and gone_amt > 0:
                    if left_est > 0.01:
                        put("utilities_estimate", left_est)
                    else:
                        out.pop("utilities_estimate", None)
                    dn = {w for d in dups for w in d["names"]}
                    kept_facts: list[str] = []
                    for f in facts:
                        mf = re.match(r"^((?:[A-Z][a-z]+)(?:, [a-z]+)*(?: and [a-z]+)?) (?:is|are) about \$[\d,.]+ a month from the listing, counted as your utilities estimate\.$", f)
                        listed_names = [w.lower() for w in re.findall(r"[A-Za-z]+", mf.group(1)) if w.lower() != "and"] if mf else []
                        if mf and listed_names and set(listed_names) & dn:
                            rest_names = [w for w in listed_names if w not in dn]
                            if rest_names and left_est > 0.01:
                                kept_facts.append(f"{_join_names(rest_names).capitalize()} {'is' if len(rest_names) == 1 else 'are'} about {_money_cents(left_est)} a month from the listing, counted as your utilities estimate.")
                            continue
                        kept_facts.append(f)
                    facts[:] = kept_facts
                    named = _join_names(sorted(dn, key=lambda w: _ALL_UTILITIES.index(w) if w in _ALL_UTILITIES else 9))
                    facts.append(f"The listing also gives {named} at {', '.join(_money_cents(d['amount']) for d in dups)} a month, but the {_money_cents(v)} flat fee already covers "
                                 f"{'it' if len(dn) == 1 else 'them'}. Only the flat fee is counted, so that figure is not. Ask which one applies.")
            elif covered_utils and has_period and not any(w in tenant_list or (w == "hot water" and "water" in tenant_list) for w in covered_utils):  # cycle 17: those utilities are paid through the flat fee, so they are not counted again
                facts.append(f"{', '.join(dict.fromkeys(covered_utils)).capitalize()} {'is' if len(set(covered_utils)) == 1 else 'are'} paid through that flat fee, so {'it is' if len(set(covered_utils)) == 1 else 'they are'} not counted again in your utilities estimate.")
        if not buying:
            known_fee_values = {round(float(x), 2) for x in (_try(lambda: _money_monthly_fees(text)) or [])} | {round(float(x), 2) for x in (_try(lambda: _monthly_list_fees(text)) or [])} \
                | {round(float(v2), 2) for _l, v2 in (_try(lambda: _mandatory_monthly_fees(text)) or [])} | {round(float(v2), 2) for _l, v2, _p in (_try(lambda: _flat_service_fees(text)) or [])} \
                | {round(float(v2), 2) for _l, v2 in (_try(lambda: _service_fee_items(text)) or [])} | {round(float(v2), 2) for _l, v2 in counted} | set(round(float(a), 2) for a in added)
            for label, v, says_monthly, clause in _try(lambda: _required_monthly_fees(text)) or []:  # cycle 26: a required monthly fee by any name counts once
                if round(v, 2) in known_fee_values or any(isinstance(out.get(k), (int, float)) and abs(float(out[k]) - v) < 0.01 for k in ("hoa", "utilities_estimate", "parking_cost", "pet_rent")):
                    continue  # already counted by another reader: never twice
                if re.search(r"\bhoa\b", clause, re.I) and _try(lambda: _hoa_payer(text)) == "tenant" and abs(float(_try(lambda: _hoa(text)) or 0) - v) < 0.01:
                    continue  # the HOA reader counts this one in the HOA line
                monthly += v; added.append(v)
                known_fee_values.add(round(v, 2))
                facts.append(f'The listing says "{clause[:90]}". It is a required fee, so {_money_words(v)}{" a month" if says_monthly else ""} is counted once in other monthly fees.'
                             + ("" if says_monthly else " The listing does not say how often, so it is counted as monthly. Ask if that is right."))
        for label, v in _try(lambda: _service_fee_items(text)) or []:  # cycle 18: every named fee of a list counts once, whatever the layout
            if v in added:
                added.remove(v)  # a reader above already counted this one
            else:
                monthly += v
                facts.append(f"{label[:1].upper() + label[1:]} is ${v:,.0f}/month, counted in other monthly fees. If it is optional, take it out.")
        if monthly:
            put("other_monthly_fees", monthly)
            est = out.get("utilities_estimate")
            pays = [w.strip() for w in str(out.get("tenant_pays") or "").split(",") if w.strip()]
            no_net_in_est = bool(gen and not gen["conflict"] and not any("internet" in it["names"] for it in gen["items"]) and isinstance(est, (int, float)) and abs(float(est) - gen["amount"]) < 0.01)  # cycle 18: that estimate never counted internet, so none comes out of it
            if isinstance(est, (int, float)) and "internet" in pays:
                for nm in re.finditer(r"\b(?:internet|wi-?fi)\b(?:[ \t]*\([^)\n$]{1,25}\))?[ \t:\-=]{0,4}\$\s?(\d{1,4})(?![\d,])", text, re.I):
                    v = float(nm.group(1))
                    if no_net_in_est and v in _money_monthly_fees(text):
                        facts.append(f"Internet is ${v:,.0f}/month and the listing says you pay it, so it is counted once in other monthly fees.")
                        break
                    if v in _money_monthly_fees(text) and float(est) >= v:
                        # cycle 15 join: a required internet fee is counted once, as a monthly fee, not again in utilities
                        rest = float(est) - v
                        facts[:] = [f for f in facts if not re.search(r"\binternet\b[^.]*\$[\d,]+ a month from the listing, counted as your utilities estimate", f, re.I)]
                        if rest > 0:
                            out["utilities_estimate"] = int(rest) if rest == int(rest) else rest
                            others = [w for w in pays if w != "internet"]
                            names = ", ".join(others[:-1]) + " and " + others[-1] if len(others) > 1 else (others[0] if others else "utilities")
                            facts.append(f"{names[:1].upper() + names[1:]} {'are' if len(others) > 1 else 'is'} about ${rest:,.0f} a month from the listing, counted as your utilities estimate.")
                        else:
                            out.pop("utilities_estimate", None)
                        facts.append(f"Internet is ${v:,.0f}/month and the listing says you pay it, so it is counted once in other monthly fees.")
                        break
        est_now = out.get("utilities_estimate")
        if isinstance(est_now, (int, float)) and "internet" in [w.strip() for w in str(out.get("tenant_pays") or "").split(",")] \
                and any(re.search(r"\binternet\b", f, re.I) and re.search(r"counted as your utilities estimate|added to your utilities estimate", f, re.I) for f in facts) \
                and not any(re.search(r"\binternet is \$", f, re.I) for f in facts):
            # cycle 19: "* Internet $50" that the utilities estimate already holds is named as counted there, never also "not counted anywhere"
            for nm in re.finditer(r"^[ \t]*[*\u2022\-][ \t]*(?:internet|wi-?fi)\b(?:[ \t]*\([^)\n$]{1,25}\))?[ \t:\-=]{0,4}\$\s?(\d{1,4})(?![\d,])", text, re.I | re.M):
                v = float(nm.group(1))
                if 0 < v <= float(est_now) and v not in _net_component_numbers(text):
                    facts.append(f"Internet is ${v:,.0f}/month and the listing says you pay it, so it is counted in your utilities estimate.")
                    break
        months, with_deposit = _try(lambda: _move_in_months(text)) or (0, False)
        rent = out.get("price")
        first_last = months
        if _three_months_up_front(text):
            months = 3  # only when the listing really says three months of rent are due before move-in
        if months and not _SALE_WORDS.search(text):
            put("months_up_front", months)
        if first_last and isinstance(rent, (int, float)) and 200 <= rent <= 30000 and not _SALE_WORDS.search(text):
            # First and last month are cash due at move-in, not a fee: money.cash_at_move_in shows them apart.
            each = _try(lambda: _deposit_each(text)) if months == 2 and first_last == 2 else None
            if each and abs(each - float(rent)) >= 1:  # cycle 18: "first, last and security deposit ($2,800 each)" with a rent of $2,700
                line = (f"The listing says first month, last month and the deposit are {_usd(each)} each, so first and last month are counted as {_usd(each * 2)} "
                        f"(not {_usd(first_last * float(rent))} worked out from the {_usd(float(rent))} rent) and the deposit is {_usd(each)}. First and last month are due at move-in")
                with_deposit = False
            else:
                line = f"First and last month's rent ({_usd(first_last * float(rent))}) are due at move-in"
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
            renters_ins = _try(lambda: _renters_insurance_yearly(text))
            if renters_ins:
                put("insurance", renters_ins[0])  # a yearly amount: "$15/mo" is 180
            credit_fee = _try(lambda: _credit_check_fee(text))
            if credit_fee:
                cf, who = credit_fee
                if not out.get("application_fee"):
                    put("application_fee", cf)
                    out["application_fee_per_adult"] = 1
                    facts.append(f"The {_usd(cf)} credit check fee is charged per {who}, so it is counted as the application fee for each adult who applies.")
                elif float(out["application_fee"]) != cf and not _credit_in_app_fee(facts, out, cf, text):
                    facts.append(f"The listing also has a {_usd(cf)} credit check fee per {who}. It is not counted, because an application fee is already filled in. Ask whether they are two fees.")
            plain_credit = _try(lambda: _credit_check_plain(text))
            if plain_credit:
                if not out.get("application_fee"):
                    put("application_fee", plain_credit)
                    facts.append(f"The {_usd(plain_credit)} credit check fee is saved as the application fee. Ask if each adult who applies pays it.")
                elif float(out["application_fee"]) != plain_credit and not _credit_in_app_fee(facts, out, plain_credit, text):
                    facts.append(f"The listing also has a {_usd(plain_credit)} credit check fee. It is not counted, because an application fee is already filled in. Ask whether they are two fees.")
        per_person = _try(lambda: _app_fee_per_person(text))
        if per_person:
            if not any("charged to each adult" in f and "application fee" in f for f in facts):  # cycle 23: the combined note already says it, once is enough
                facts.append(per_person)
            if out.get("application_fee"):
                out["application_fee_per_adult"] = 1  # the cost multiplies the fee by the adults who apply
        credit, credit_notes = _try(lambda: _seller_credit_detail(text, out.get("price") if isinstance(out.get("price"), (int, float)) else None)) or (None, [])
        if credit:
            put("seller_credit", credit)
        have_credit = current.get("seller_credit") if current else None
        if have_credit not in (None, "") and not isinstance(have_credit, bool):
            credit_notes = [re.sub(r"so no seller credit is saved\. Ask what the seller will really give\.|so the seller credit is blank\. Ask how much\.",
                                   f"so check that the seller credit of ${float(have_credit):,.0f} on this place is what the seller agreed to.", n) for n in credit_notes]
            credit_notes = [n.replace("gives no amount, so the seller credit is blank", "gives no amount") for n in credit_notes]
        facts.extend(credit_notes)
        facts.extend(_try(lambda: _lender_credit_notes(text)) or [])
        if not credit_notes:
            facts.extend(_try(lambda: _closing_help_offer(text)) or [])
        insurance = _try(lambda: _insurance(text))
        if insurance is not None:
            put("insurance", insurance)
        assessment = _try(lambda: _special_assessment(text))
        if assessment:
            facts.append(assessment)
        monthly_assessment = _try(lambda: _assessment_monthly_note(text))
        m_items = _try(lambda: _monthly_assessment_items(text)) or []
        reg_items = [i for i in m_items if i["kind"] == "regular"]
        if reg_items and (buying or _SALE_WORDS.search(text) or (isinstance(out.get("price"), (int, float)) and out["price"] >= 20000)):
            monthly_assessment = ""  # cycle 23: a regular monthly assessment is the HOA and has its own note below
        if monthly_assessment and _try(lambda: _hoa(text)) is None and _try(lambda: _hoa_plain_monthly(text)) == (_try(lambda: _assessment_monthly(text)) or (0,))[0]:
            monthly_assessment = ""  # these monthly dues were saved as the HOA, so no note says they are left out
        if monthly_assessment:
            facts.append(monthly_assessment)
        yearly_assessment = _try(lambda: _assessment_yearly_note(text))
        if yearly_assessment:
            facts.append(yearly_assessment)
        amount, payer, _sentence = _try(lambda: _special_assessment_facts(text, buying)) or (None, "", "")
        has_special = bool(re.search(r"\bspecial assessments?\b", _sentence, re.I))
        all_charges = (_try(lambda: list(_buyer_closing_charges(text))) or []) if buying and amount else []
        first_kind = "special assessment" if has_special else (all_charges[0][1] if all_charges else "condo assessment")
        if has_special:
            extra_charges = [c for c in all_charges if c[2] != _sentence and c[1] == "capital contribution"]
        else:
            extra_charges = all_charges[1:]  # the first charge is the one read as the amount; the others are added in
        if extra_charges and (payer == "buyer" or (not payer and first_kind != "special assessment")):
            # a second one-time buyer charge at closing ("$1,000 one-time capital contribution" next to a $2,400 assessment): added in, and the note names both
            first = amount
            for c in extra_charges:
                amount += c[0]
            parts = ", ".join(f"${v:,.0f} ({k})" for v, k in [(first, first_kind)] + [(c[0], c[1]) for c in extra_charges])
            facts.append(f"The listing has more than one one-time charge for the buyer at closing: {parts}. They are added together as the special assessment "
                         f"(${amount:,.0f} in all, paid by the buyer) and counted in the cash to close. Ask the seller's agent to confirm each one.")
            payer = "buyer"
        elif extra_charges:
            c = extra_charges[0]
            facts.append(f"The listing also has a ${c[0]:,.0f} {c[1]} at closing. It is not added to the special assessment because the listing does not say the buyer pays "
                         "both. Ask the seller's agent who pays it.")
        elif buying and amount and not re.search(r"\bspecial assessments?\b", _sentence, re.I):
            closing_note = _try(lambda: _buyer_closing_note(text))
            if closing_note:
                facts.append(closing_note)
            elif _sentence:
                facts.append(_plain_assessment_note(amount, payer))
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
        elif (buying or _SALE_WORDS.search(text) or (isinstance(out.get("price"), (int, float)) and out["price"] >= 20000)) and (items := _try(lambda: _closing_items(text))):
            put("closing_costs", items[0])
            facts.append(f"The listing gives the closing costs in parts ({items[1]}). They are added up and saved as ${items[0]:,.0f} closing costs, used instead of a guess. "
                         "Ask the lender for the full estimate, because other fees may be missing.")
        elif (buying or _SALE_WORDS.search(text) or (isinstance(out.get("price"), (int, float)) and out["price"] >= 20000)) and (single := _try(lambda: _closing_single(text))):
            put("closing_costs", single[0])
            facts.append(f"The listing says \"{single[1]}\". It is read as the closing costs and saved as {_money_c(single[0])}, used instead of a guess. Ask the lender for the full estimate.")
        else:
            pct_note = _try(lambda: _closing_costs_percent(text, out.get("price") if isinstance(out.get("price"), (int, float)) else None))
            if pct_note:
                if pct_note[0]:
                    put("closing_costs", pct_note[0])
                facts.append(pct_note[1])
        cut = _try(lambda: _price_cut(text))
        if cut:
            facts.append(f"Price reduced ${cut:,.0f}.")
        hoa = _try(lambda: _hoa(text))
        if hoa is None and (buying or _SALE_WORDS.search(text) or (isinstance(out.get("price"), (int, float)) and out["price"] >= 20000)):
            plain_hoa = _try(lambda: _hoa_plain_monthly(text))
            if plain_hoa:
                hoa = plain_hoa
                maint = _try(lambda: _hoa_maintenance(text))
                if maint is not None and abs(maint - plain_hoa) < 0.01:
                    facts.append(f"The listing gives a maintenance fee that comes to {_money_c(plain_hoa)} a month and no other HOA figure, so it is read as the HOA and saved as "
                                 f"{_money_c(plain_hoa)} a month. Ask what the fee covers and whether there are other association fees.")
        master = _try(lambda: _master_dues(text))
        if master:  # cycle 18: "$600 annual master association dues" next to "HOA fee $210/month": the monthly share is added to the HOA
            base_hoa = _try(lambda: _hoa(master[3]))
            if base_hoa is not None and base_hoa > 0:
                hoa = round(base_hoa + master[0], 2)
                facts.append(f"The listing gives an HOA fee of ${base_hoa:,.0f}/month and also master association dues ({master[1]}). The dues are ${master[0]:,.0f}/month, "
                             f"so the HOA is saved as ${hoa:,.0f}/month. Ask whether the dues are already part of the HOA fee.")
            elif base_hoa is None:
                hoa = master[0]
                facts.append(f"The listing gives master association dues ({master[1]}), saved as ${master[0]:,.0f}/month in the HOA. Ask whether there are other association fees.")
        sale_ctx = bool(buying or _SALE_WORDS.search(text) or (isinstance(out.get("price"), (int, float)) and out["price"] >= 20000))
        extras = (_try(lambda: _hoa_extra_monthly(text)) or []) if sale_ctx else []
        if extras:
            names = " and ".join(f"{_money_c(v)} monthly {lab}" for v, lab in extras)
            if hoa is not None and hoa > 0:
                base = hoa
                hoa = round(base + sum(v for v, _l in extras), 2)
                facts.append(f"The listing gives HOA dues of {_money_c(base)} a month and also a {names} fee. Both are added, so the HOA is saved as "
                             f"{_money_c(hoa)} a month. Ask whether the fee is part of the HOA.")
            else:
                facts.append(f"The listing gives a {names} fee but no HOA amount, so it is not counted and the HOA is left empty. Ask the seller's agent for the total monthly HOA.")
        added = _try(lambda: _assessment_monthly(text)) if sale_ctx else None
        if reg_items and sale_ctx and payer != "seller" and not _try(lambda: _assessment_none(text)):
            # cycle 23: a regular monthly assessment is the HOA; a monthly special assessment is its own amount added on top, never the whole HOA
            spec_items = [i for i in m_items if i["kind"] == "special"]
            reg_amts = sorted({i["amount"] for i in reg_items})
            spec_words = "; ".join(
                f"${i['amount']:,.0f} a month" + (f" through {i['end']}" if i["end"] else (f" for {i['months']} months (${i['amount'] * i['months']:,.0f} in all)" if i["months"] else ""))
                for i in spec_items)
            if len(reg_amts) > 1 or (hoa is not None and abs(hoa - reg_amts[0]) > 0.01):
                had = f"HOA dues of ${hoa:,.0f} a month and " if hoa is not None else ""
                facts.append(f"The listing gives {had}a regular monthly assessment of {' and '.join(f'${a:,.0f}' for a in reg_amts)}. It is unclear whether those are two charges or the same one, "
                             "so the HOA is left empty." + (f" The special assessment of {spec_words} is not counted either." if spec_items else "")
                             + " Ask what the total monthly HOA and assessment is.")
                hoa = None
            elif spec_items:
                base = reg_amts[0]
                hoa = round(base + sum(i["amount"] for i in spec_items), 2)
                facts.append(f"The listing has a regular monthly assessment of ${base:,.0f} (the HOA) and a special assessment of {spec_words}. Both are added, so the HOA is saved as "
                             f"${hoa:,.0f} a month. The special assessment is not forever: ask who pays it and when it ends.")
            elif hoa is None:
                hoa = reg_amts[0]
                facts.append(f"The listing gives a monthly assessment of ${hoa:,.0f}, read as the regular monthly HOA.")
        elif added and payer != "seller" and not _try(lambda: _assessment_none(text)):
            # cycle 19: a monthly special assessment is money the buyer pays every month, so it goes into the monthly HOA figure
            amt_m, months_m = added
            plain = _try(lambda: _hoa_plain_monthly(text))
            if not (hoa is not None and plain == amt_m and _try(lambda: _hoa(text)) is None):  # not when it was already read as the HOA itself
                end_year = _try(lambda: _assessment_monthly_end(text)) or ""
                length = f" through {end_year}" if end_year else (f" for {months_m} months (${amt_m * months_m:,.0f} in all)" if months_m else "")
                base = hoa
                hoa = round((base or 0) + amt_m, 2)
                how = f"on top of the ${base:,.0f} HOA, so the HOA is saved as ${hoa:,.0f} a month" if base else f"so the HOA is saved as ${hoa:,.0f} a month"
                facts[:] = [f for f in facts if not f.startswith("The listing mentions an assessment of")]
                facts.append(f"The listing has a special assessment of ${amt_m:,.0f} a month{length}. It is added to the monthly cost, {how}. "
                             f"It is not a one-time cost. Ask who pays it and when it ends.")
        if not buying and _try(lambda: listing_hoa_in_rent(text)):
            # HOA dues that are part of the rent are already in the rent: nothing is saved or added on top
            hoa = None
            hm = re.search(r"[^.\n;]*\b(?:hoa|association)\b[^.\n;]*\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?[^.\n;]*|[^.\n;]*\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d\d)?[^.\n;]*\b(?:hoa|association)\b[^.\n;]*", text, re.I)
            amt = (hm.group(1) or hm.group(2)) if hm else ""
            facts.append(f"The listing says the HOA dues{f' (${amt})' if amt else ''} are included in the rent, so nothing is added for them.")
        if not buying and hoa is not None and not listing_hoa_in_rent(text):
            owner_hoa = _try(lambda: _hoa_paid_by_owner(text))
            hoa_rental = not _SALE_WORDS.search(text) and not (isinstance(out.get("price"), (int, float)) and out["price"] >= 20000)
            payer = _try(lambda: _hoa_payer(text)) or ""
            if owner_hoa or (payer == "owner"):
                hoa = None
                facts.append(f"The listing says the owner pays the HOA{f' ({owner_hoa})' if owner_hoa else ''}, so nothing is counted for you. Ask whether any HOA charge is passed on to the tenant.")
            elif hoa_rental and payer != "tenant" and hoa:
                # On a rental the HOA or condo fee is the owner's bill unless the listing says it is passed on to the tenant.
                facts.append(f"The listing mentions an HOA or condo fee of ${hoa:,.0f} a month but does not say the tenant pays it, so it is not counted. Ask whether it is passed on to the tenant.")
                hoa = None
        if hoa is not None:
            put("hoa", hoa)
        elif (buying or _SALE_WORDS.search(text)) and (hm_unknown := re.search(_HOA_NO_INFO, text, re.I)):
            facts.append(f'The listing says "{" ".join(hm_unknown.group(0).split())}", so the HOA is left empty (not $0). Ask the seller\'s agent what the monthly HOA fee is.')
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
    _try(lambda: _gc_apply(text, out, facts, gc_found, gc_unplaced, buying, only=set(gc_found) - {"price"}))
    _try(lambda: _gc_quote_unplaced(facts, gc_unplaced))
    if "price" in gc_found:  # one note for the old rent: a price-cut or old-figure note that already names it stays, and ours goes
        _olds = [_usd(o) for o in gc_found["price"]["olds"]]
        _mine = [f for f in facts if f.startswith("The listing corrects the rent:")]
        _legacy = [f for f in facts if f not in _mine and re.search(r"price was cut from|rent dropped from|was a mistake or an old figure|is the old price|old price is not used|first said", f)
                   and any(o in f for o in _olds)]
        if _mine and _legacy and all(any(o in f for f in _legacy) for o in _olds):
            facts[:] = [f for f in facts if f not in _mine]
    facts += _try(lambda: _internet_choice_notes(text, facts)) or [] if not buying else []  # cycle 22: optional internet is named, never counted
    for key, value in (_try(lambda: _address(text)) or {}).items():
        put(key, value)
    if "city" not in out:
        hint = _try(lambda: _craigslist_headline(text)) or ("", "")
        if hint[1]:
            put("city", hint[1])
        elif _try(lambda: _paren_area(text)):
            put("city", _paren_area(text))
    title = _try(lambda: _title(text, out))
    title = _try(lambda: _lead_title(text, out, title or "")) or title  # cycle 22: a descriptive name instead of the street address or a policy line
    title = title or _try(lambda: _street_name_title(text, out))
    title = strip_title_decoration(title or "")
    if title:
        out["title"] = title
    reader_estimate = out.get("utilities_estimate")
    est_replaced = False
    if current:
        facts = _drop_old_rent_notes(facts, out.get("price"), current.get("price"), buying)  # cycle 26: a rent the user changed leaves no note about the old rent
        _apply_current(out, current)
        facts = _reword_replaced_estimate(facts, reader_estimate, out.get("utilities_estimate"))
        saved_est = out.get("utilities_estimate")
        est_replaced = isinstance(saved_est, (int, float)) and not isinstance(saved_est, bool) and (
            not isinstance(reader_estimate, (int, float)) or abs(float(saved_est) - float(reader_estimate)) >= 0.5)
    if not buying:
        _trash_fee_covers_trash(text_full, out)
    facts = _drop_placed_facts(facts, out, follow=bool(current))
    facts += _try(lambda: _safety_net(text, out, facts)) or []
    facts = _drop_placed_facts(facts, out, follow=bool(current))  # the safety net's lines follow the fields too
    if not buying:
        facts += [n for n in (_try(lambda: _no_silent_drop(text_full, out, facts, est_replaced)) or []) if not _pet_quote_placed(n, out)]  # cycle 20: the last net, every figure is placed, explained or quoted
    facts += _try(lambda: _no_silent_percent(text, out, facts)) or []
    facts = _try(lambda: _quote_hostile_facts(text, facts, out)) or facts
    facts = _try(lambda: _settle_notes(text, out, facts, buying)) or facts
    if est_replaced:
        facts = _answer_utility_notes(facts, out)
    facts = _try(lambda: _fix_quotes(facts, text, out)) or facts
    if not buying:
        from . import dropguard as _dg
        facts = _try(lambda: _dg.finalize_notes(text, out, facts, buying)) or facts  # cycle 26: the last filter, decided from the final fields
    if facts:
        out["found_in_listing"] = "\n".join(" ".join(f.split()) for f in facts if f.strip())  # one note per line
        if buying:  # a note for a home for sale says seller or listing agent, never landlord (the quoted listing words are left alone)
            out["found_in_listing"] = re.sub(r"\b([Aa]sk|[Cc]heck with) the landlord\b", r"\1 the seller or listing agent", out["found_in_listing"])
    return out


def _pet_quote_placed(note: str, out: dict[str, Any]) -> bool:
    """Cycle 21: 'The listing also says "Pet policy: Cats only, 1 max, $35 monthly rent, $200 fee". It is a monthly fee ...' when the pet fields hold all of that line."""
    qm = re.match(r'The listing also says "([^"]+)"\. ', note)
    return bool(qm and re.match(r"\s*pets?\b", qm.group(1), re.I) and _pet_line_placed(qm.group(1), out))


def _reword_replaced_estimate(facts: list[str], read: Any, saved: Any) -> list[str]:
    """The reader's utilities note says what it counted. When the place holds a different estimate (Claude or the user set it after the
    listing was read), the saved estimate is what the cost uses, so the note says that instead of the reader's figure."""
    try:
        if read is None or saved is None or isinstance(saved, bool) or abs(float(saved) - float(read)) < 0.5:
            return facts
        mine = float(saved)
    except (TypeError, ValueError):
        return facts
    return [re.sub(r"counted as your utilities estimate", f"but the utilities estimate saved on this place is ${mine:,.0f}, so ${mine:,.0f} is what is counted", f) for f in facts]


def reader_notes_for(place: dict[str, Any], buying: bool = False, pet_kind: str = "", pet_count: Any = None) -> str:
    """The "Also in the listing" notes for a saved place: its listing text read again, with what is filled on the place
    counted as placed. One rule for add, edit and update: a note about something that is filled in now is not kept."""
    found = parse_listing(str(place.get("listing_text") or ""), str(place.get("url") or ""), current=place, buying=buying, pet_kind=pet_kind, pet_count=pet_count)
    return reconcile_seller_credit_note(reconcile_insurance_note(str(found.get("found_in_listing") or ""), place.get("insurance")), place.get("seller_credit"))


def reconcile_seller_credit_note(notes: str, saved: Any) -> str:
    """When the place holds a seller credit that differs from the percent the listing states (Claude or the user sent one, even 0), that
    saved value is what counts, so a note must not say the listing's amount was 'saved as the seller credit'. It says what was kept."""
    if saved is None or saved == "" or isinstance(saved, bool):
        return notes
    try:
        mine = float(str(saved).replace("$", "").replace(",", ""))
    except (TypeError, ValueError):
        return notes
    kept = f"${mine:,.0f}"

    def fix(m: re.Match[str], shown: str) -> str:
        if abs(float(m.group(2).replace(",", "")) - mine) <= 1.0:
            return m.group(0)  # the listing's own figure is what is saved: the note is right
        return (f"The listing mentions a {m.group(1)}% seller credit ({shown}${m.group(2)}) that was not saved because the value given was {kept}. "
                f"The seller credit stays {kept}." + (" Ask the seller's agent to confirm." if "Ask the seller's agent" in m.group(0) else ""))
    notes = re.sub(r"The listing says the seller gives ([\d.]+)% of the price toward closing\.\s+At a price of \$[\d,]+ that is \$([\d,]+) \([^)]*\), saved as the seller credit\.(?: Ask the seller's agent to confirm\.)?",
                   lambda m: fix(m, "about "), notes)
    return re.sub(r"The listing says the seller gives ([\d.]+)% toward closing and states it as \$([\d,]+), so the seller credit is saved as \$[\d,]+\.",
                  lambda m: fix(m, ""), notes)


_INSURANCE_COUNTED = re.compile(r"Renter's insurance is required and counted in the monthly cost \(\$([\d,]+) a month, saved as \$([\d,]+) a year\)\.")


def reconcile_insurance_note(notes: str, saved: Any) -> str:
    """The renter's insurance note says what the reader counted. When the place holds a different yearly amount (Claude or the
    user sent it), the saved amount is what the cost uses, so the note says that instead of the reader's numbers."""
    m = _INSURANCE_COUNTED.search(notes or "")
    try:
        mine = float(saved)
    except (TypeError, ValueError):
        return notes
    if not m or abs(mine - float(m.group(2).replace(",", ""))) < 0.5:
        return notes
    return _INSURANCE_COUNTED.sub(
        f"Renter's insurance is required. The listing says ${m.group(1)} a month (${m.group(2)} a year), but the insurance saved on this place "
        f"is ${mine:,.0f} a year, so ${mine / 12:,.0f} a month is what is counted.", notes, count=1)


# --------------------------------------------------------------------------- notes that agree with the fields (cycle 11)
_CURRENT_EXTRA = ("parking", "laundry", "pets", "utilities_included", "tenant_pays", "pet_count_limit", "pet_breed_note", "special_assessment_payer")


_OLD_RENT_NOTE = re.compile(
    r"price was cut from|rent dropped from|corrects the rent|is the old price|old price is not used|\bstarting at\b|rent range of|different rent for each lease length|"
    r"another lease length option|more than one plan with the same number|floor plan|net effective|rent saved is|saved as the rent|is saved as the rent|"
    r"The listing has a special|special of \$|was a mistake or an old figure|rent is now|first said \$", re.I)


def _drop_old_rent_notes(facts: list[str], read: Any, saved: Any, buying: bool = False) -> list[str]:
    """Cycle 26: the place holds a rent that differs from the one the listing text gives (the user or Claude corrected it). A note that explains
    which listing figure is the rent, or says an older price is not used, is about the old rent and goes."""
    def num(v: Any) -> float | None:
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None
    r, sv = num(read), num(saved)
    if buying or r is None or sv is None or abs(r - sv) < 0.5:
        return facts
    return [f for f in facts if not _OLD_RENT_NOTE.search(f)]


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
        if re.search(r"parking", f) and re.search(r"gives no price\. It looks optional", f) and out.get("parking_cost"):  # cycle 21: a $0 included lot does not place an optional garage that has no price
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
        if _pet_quote_placed(f, out):
            continue
        if follow:  # a saved place: every note follows what is filled on it now
            f = _follow_fields(f, out)
            if not f:
                continue
        kept.append(_one_time_wording(f))
    return _dedupe_totals([f for f in kept if not _quote_repeat(f, kept, out)])


_SUBTOTAL_NOTE = re.compile(r"The utilities estimate is the two together, \$[\d,]+ a month\.")
_TOTAL_NOTE = re.compile(r"The utilities estimate adds all the figures the listing gives, \$[\d,]+ a month\.")


def _dedupe_totals(notes: list[str]) -> list[str]:
    """A total that is already summed is said once: when the notes give both a running subtotal ("the two together, $137") and the
    total of all the figures ("adds all the figures, $169"), only the total stays."""
    if any(_TOTAL_NOTE.search(n) for n in notes):
        return [x for x in (" ".join(_SUBTOTAL_NOTE.sub("", n).split()) for n in notes) if x]
    return notes


_BARE_PET_QUOTE = re.compile(r"(?=[A-Z])(?!(?:The|A|An|It|This|That|Ask|Pets? is|Check|No amount)\b)[^.]*?\b(?:cats?|dogs?|pets?|animals?)", re.I)


def _quote_repeat(f: str, notes: list[str], out: dict[str, Any]) -> bool:
    """True when a note only says again what the notes or the fields already hold: a bare copy of the listing line that another note
    already quotes ("Pet limit 25 lbs, can be waived." beside the note that says ("Pet limit 25 lbs, can be waived")), a pet line the pet
    breed note field already holds, or a pet line whose quoted part another note gives and whose numbers are all in fields."""
    core = f.strip().rstrip(".!").strip(' "').lower()
    if len(core) < 8:
        return False
    quoted = [q.strip(" .").lower() for g in notes if g is not f for q in re.findall(r'"([^"]{6,})"', g)]
    if core in quoted:
        return True
    if not _BARE_PET_QUOTE.match(f):
        return False
    amounts = _dollar_values(f)
    if amounts and not amounts_all_placed(amounts, _net_used_numbers(out, []), _field_sums(out)):
        return False
    held = out.get("pet_weight_limit")
    for w in re.findall(r"(\d{1,3})[ \t]*[- ]?(?:lbs?\b|pounds?\b)", f, re.I):
        if not isinstance(held, (int, float)) or float(held) != float(w):
            return False
    breed = str(out.get("pet_breed_note") or "").strip().rstrip(".").strip().lower()
    if breed and core == breed:
        return True
    return any(len(q) >= 12 and q in core for q in quoted)


def _restates_field(note: str, out: dict[str, Any]) -> bool:
    """True when the note only repeats what a filled field holds: the assessment amount and payer, the renter's insurance
    that the insurance or other monthly fees field now counts, or a quoted amount that a money field now carries."""
    if re.fullmatch(r"Special assessment \$[\d,]+: the (?:buyer|seller) pays it\.", note):
        return _filled(out, "special_assessment") and _filled(out, "special_assessment_payer")
    if re.match(r"The listing says renter's insurance is required", note):
        return _filled(out, "insurance") or _filled(out, "other_monthly_fees")
    m = re.fullmatch(r'The listing also says "([^"]*)"\. (?:It|Only [^"]{1,80} of that) (?:is|are|looks?) [^"]{0,80}(?:\. The rest is already counted\.|; the other amounts in that line are counted\.|\.) Check what it is for\.', note)
    if m and re.search(r"not counted anywhere|not in the monthly cost", note):
        return amounts_all_placed(_dollar_values(m.group(1)), _net_used_numbers(out, []), _field_sums(out), m.group(1), out)
    return False


_SUM_FIELDS = ("utilities_estimate", "other_monthly_fees", "parking_cost", "pet_rent", "hoa", "insurance")


def _field_sums(out: dict[str, Any]) -> set[float]:
    """Sums of any two or three monthly fields ("$55 + $70 + $48 flat" with utilities $125 and other fees $48 is $173)."""
    vals = [float(out[k]) for k in _SUM_FIELDS if isinstance(out.get(k), (int, float)) and not isinstance(out.get(k), bool) and out[k]]
    return {round(sum(c), 2) for size in (2, 3) for c in itertools.combinations(vals, size)}


_PERIOD_AFTER = ((re.compile(r"semi-?annual|twice a year|every (?:6|six) months|per half"), 6),
                 (re.compile(r"annual|yearly|per year|a year|each year|/\s*(?:yr|year)\b|per annum"), 12),
                 (re.compile(r"quarter|qtr|every (?:3|three) months|per (?:3|three) months"), 3))
_NOTE_MONTHLY_WORDS = re.compile(r"/\s*(?:mo|month)\b|\bper month\b|\ba month\b|\bmonthly\b|\bmo\b", re.I)


def _period_divisors(phrase: str) -> dict[float, int]:
    """For each dollar amount in ``phrase``, how many months it covers when the words next to it say so ("$600 annual master dues" is 12,
    "$210 every 3 months" is 3). Amounts with no such words are left out (they are monthly)."""
    out: dict[float, int] = {}
    for m in _NET_DOLLARS.finditer(phrase):
        raw = m.group(1) if m.group(1) is not None else m.group(4)
        try:
            amount = round(float(raw.replace(",", "") + ((m.group(2) or "") if m.group(1) is not None else "")), 2)
        except ValueError:
            continue
        after = phrase[m.end():m.end() + 28].lower()
        after = after.split("$")[0]
        after = re.split(r"[,;]|\band\b", after)[0]
        before = re.split(r"[,;.:(]|\bplus\b|\band\b", phrase[max(0, m.start() - 24):m.start()].lower())[-1]  # "every 3 months $90", "annual dues $600"
        if _NOTE_MONTHLY_WORDS.search(after):
            continue
        for pat, div in _PERIOD_AFTER:
            if pat.search(after) or pat.search(before):
                out[amount] = div
                break
    return out


_UTIL_NAME_MAP = (("electric", re.compile(r"\b(?:electric(?:ity)?|power)\b", re.I)), ("gas", re.compile(r"\bgas\b", re.I)),
                  ("water", re.compile(r"\bwater\b", re.I)), ("sewer", re.compile(r"\bsewer\b", re.I)),
                  ("trash", re.compile(r"\b(?:trash|garbage)\b", re.I)), ("heat", re.compile(r"\bheat(?:ing)?\b", re.I)),
                  ("internet", re.compile(r"\b(?:internet|wi-?fi|cable)\b", re.I)))
_ITEM_SPLIT = re.compile(r"[,;|\n]|:::|\bplus\b|\band\b(?![ \t]*(?:sewer|trash|garbage))|[ \t][-\u2013\u2014][ \t]|[ \t]\*[ \t]")
_ITEM_FIELD_WORDS = (
    ("hoa", re.compile(r"\b(?:hoa|dues|association|condo fee)\b", re.I)),
    ("parking_cost", re.compile(r"\b(?:parking|garage|carport|covered space|assigned space)\b", re.I)),
    ("pet_rent", re.compile(r"\bpet rent\b", re.I)),
    ("other_monthly_fees", re.compile(r"\b(?:flat fee|amenity|valet|pest|trash fee|package|locker|storage|permit|technology|internet|wifi|cable)\b", re.I)),
)


def _tenant_names(out: dict[str, Any]) -> set[str]:
    text = str(out.get("tenant_pays") or "")
    return {name for name, pat in _UTIL_NAME_MAP if pat.search(text)}


def _semantic_placed(amount: float, phrase: str, out: dict[str, Any]) -> bool:
    """True when ``amount`` sits in an item of ``phrase`` that names a cost a field already carries: a utility the place says the tenant
    pays (with a utilities estimate that holds at least the utility amounts of the line), or a fee, dues, parking or pet rent item
    with its own field that holds at least that amount. The field is what is counted, so the amount is not "not counted"."""
    items = [x for x in _ITEM_SPLIT.split(phrase) if x and x.strip()]
    tenant = _tenant_names(out)
    est = out.get("utilities_estimate")
    est = float(est) if isinstance(est, (int, float)) and not isinstance(est, bool) else None
    util_sum, mine_util = 0.0, False
    field_sum: dict[str, float] = {}
    mine_field: set[str] = set()
    for item in items:
        vals = _dollar_values(item)
        if not vals:
            continue
        named = {name for name, pat in _UTIL_NAME_MAP if pat.search(item)}
        if named & tenant and est is not None:
            util_sum += sum(vals)
            if amount in vals:
                mine_util = True
            continue
        for key, pat in _ITEM_FIELD_WORDS:
            if pat.search(item):
                field_sum[key] = field_sum.get(key, 0.0) + sum(vals)
                if amount in vals:
                    mine_field.add(key)
                break
    for key in mine_field:  # the field must hold all the amounts of that kind in the line, or one of them was left out of it
        held = out.get(key)
        if isinstance(held, (int, float)) and not isinstance(held, bool) and held and field_sum[key] <= float(held) + 0.5:
            return True
    return bool(mine_util and est is not None and est + 0.5 >= util_sum)


def placed_amounts(amounts: set[float], used: set[float], extra: set[float] | None = None, phrase: str = "", out: dict[str, Any] | None = None, semantic: bool = True) -> set[float]:
    """The amounts (of ``amounts``) that a field already counts. An amount is placed when a field holds it, when its monthly share does
    ("$600 annual" is $50 a month), when some of the amounts add up to a field ("$210 plus $600 annual" is the $260 HOA), or, given the
    place's fields (``out``), when the item it sits in names a cost a field carries (electric $60, gas $35 with a $125 utilities estimate)."""
    used_r = {round(u, 2) for u in used}
    targets = used_r | {round(e, 2) for e in (extra or set())}
    divs = _period_divisors(phrase) if phrase else {}
    monthly = {a: round(a / divs.get(round(a, 2), 1), 2) for a in amounts}
    placed = {a for a in amounts if round(a, 2) in used_r or monthly[a] in used_r}
    if not amounts:
        return placed
    pool = sorted(amounts)
    for size in range(len(pool), 1, -1):
        for combo in itertools.combinations(pool, size):
            total = round(sum(monthly[c] for c in combo), 2)
            if any(abs(total - t) < (0.51 if any(c in divs or round(c, 2) in divs for c in combo) else 0.005) for t in targets):
                placed |= set(combo)
    if out:
        for a in pool:
            if semantic and a not in placed and _semantic_placed(a, phrase or "", out):
                placed.add(a)
        # an amount that repeats the monthly share of a placed periodic amount ("$600 annual ... $50/month") is placed with it
        for a in pool:
            if a not in placed and any(monthly[b] == a for b in placed if b != a):
                placed.add(a)
        placed = _util_strict(placed, phrase or "", out)
    return placed


def _util_strict(placed: set[float], phrase: str, out: dict[str, Any]) -> set[float]:
    """Cycle 22: with the listing text at hand (``out["_text"]``), a figure in a utility item ("water is $25") is placed only by the
    utilities estimate (some of the listing's utility figures add up to it) or by other monthly fees, never by another $25 elsewhere in the
    listing (a background check). Without the text nothing changes."""
    text = out.get("_text")
    if not text or not placed or not phrase:
        return placed
    from . import dropguard
    est = out.get("utilities_estimate")
    est = float(est) if isinstance(est, (int, float)) and not isinstance(est, bool) else None
    util_ok = dropguard._util_placed(text, est) if est is not None else set()
    other = out.get("other_monthly_fees")
    other = float(other) if isinstance(other, (int, float)) and not isinstance(other, bool) else 0.0
    keep = set(placed)
    for item in (x for x in _ITEM_SPLIT.split(phrase) if x and x.strip()):
        vals = _dollar_values(item)
        if not vals or not any(pat.search(item) for _n, pat in _UTIL_NAME_MAP) or _NON_UTIL_COST_WORD.search(item):
            continue
        for a in vals:
            if a in keep and a not in util_ok and not (est is not None and abs(a - est) < 0.5) and not (other and a <= other + 0.5):
                keep.discard(a)
    return keep


def amounts_all_placed(amounts: set[float], used: set[float], extra: set[float] | None = None, phrase: str = "", out: dict[str, Any] | None = None) -> bool:
    """True when every dollar amount in a note is a value a field holds, or part of a sum a field holds ("electric avg $60, gas avg
    $45" with a utilities estimate of $105). The one test behind dropping a stale "not counted anywhere" note."""
    if not amounts:
        return False
    return placed_amounts(amounts, used, extra, phrase, out) >= set(amounts)


_NET_NOTE = re.compile(r"The listing also says \"[^\"]+\"\. (?:It is not counted anywhere|It is a monthly fee and it is not counted anywhere|It looks like a utility cost and it is not counted anywhere|It is a one-time cost, so it is not in the monthly cost|Only .{1,80} of that )")


def note_amounts_placed(note: str, place: dict[str, Any]) -> bool:
    """For a saved note that says an amount is not counted: True when every dollar amount in it is already in a field of the place
    (or is part of a sum a field holds), so the note is stale."""
    amounts = _dollar_values(note)
    if not amounts:
        return False
    out = {k: v for k, v in place.items() if k in _NET_REAL_FIELDS + _CURRENT_EXTRA}
    if place.get("listing_text"):
        out["_text"] = str(place["listing_text"])
    used = _net_used_numbers(out, [], str(place.get("listing_text") or ""))
    # cycle 23: a note the last check wrote was decided from the final fields, so only a field that holds the figure itself settles it
    # ("Locker $12" is not placed by a $65 other fees that does not hold it)
    return placed_amounts(amounts, used, _field_sums(out), note, out, semantic=not _NET_NOTE.match(note)) >= set(amounts)


def _filled(out: dict[str, Any], key: str) -> bool:
    v = out.get(key)
    return v is not None and v != "" and not isinstance(v, bool)


# A note that is about one field goes away (or is rewritten) once that field is filled. (pattern, field or fields that settle it)
_FIELD_NOTES: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = tuple((re.compile(pat, re.I), keys) for pat, keys in (
    (r"so the rent is left empty|rent range of \$(?![\s\S]*higher figure)|that looks like a monthly amount, not an asking price|Check the asking price", ("price",)),
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
    from .money import without_stale_estimate
    note = without_stale_estimate(note, out)  # "The cash to close uses an estimate of the closing costs" is false once they are filled in
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


def _fix_quote_end(done: str, flat: str, q: str, at: int, m: re.Match[str]) -> str:
    nxt = flat[at + len(q):at + len(q) + 1]
    if nxt.isalnum() and q[-1:].isalnum() and " " in q:
        return f"{m.group(1)}{q.rsplit(' ', 1)[0].rstrip(' ,;:-')}...{m.group(3)}"
    return done


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
            if at > 0 and q[:1].isalnum() and not flat[at - 1].isspace() and flat[at - 1] not in "\"'([{":
                lead = flat[flat.rfind(" ", 0, at) + 1:at]  # cycle 22: a quote starts on a whole token ("1/2 month free", not "2 month free")
                if lead and len(lead) <= 12 and '"' not in lead:
                    q = lead + q
                    at -= len(lead)
                    return _fix_quote_end(f"{m.group(1)}{q}{m.group(3)}", flat, q, at, m)
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
    from .money import without_stale_estimate
    notes = without_stale_estimate(notes, out)
    kept = []
    for unit in note_units(notes):
        unit = _follow_fields(unit, out)
        if unit:
            kept.append(unit)
    if not any("counted as your utilities estimate" in k for k in kept):
        kept = _answer_utility_notes(kept, out)  # the estimate was set after the notes were made (by the user or Claude)
    return "\n".join(kept)


_PET_LINE_WORDS = frozenset("""pets pet cats cat dogs dog allowed allow ok okay welcome accepted max maximum limit limits lbs lb pound pounds per mo month
monthly non refundable nonrefundable fee rent deposit only and no weight a the one two three each up to under""".split())


def _pet_line_placed(line: str, out: dict[str, Any]) -> bool:
    """True for a pet-rule line such as "Pets: cats and dogs allowed, max 2 pets, 50 lb limit." or "Pets allowed, 2 pet max, $350
    non-refundable pet fee, $30/mo pet rent." when the fields hold everything it says: every word is a plain pet word (no breed,
    size or approval rule), every number is the count, weight, fee, rent or deposit field it sits beside, and the pets field
    agrees with the kinds of pet it names. "no weight limit" is only dropped when no weight limit is filled."""
    if not out.get("pets"):
        return False
    body = re.sub(r"^\s*pets?(?:[ \t]+(?:policy|rules?|terms))?\s*:\s*", "", line.strip(), flags=re.I).rstrip(". ")
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
    def _split_held(m: re.Match[str]) -> str:  # "$350 deposit ($150 refundable)": the deposit and fee fields hold the two parts
        whole, part = _num(m.group(1)), _num(m.group(2))
        dep, fee = out.get("pet_deposit"), out.get("pet_fee")
        return " allowed " if isinstance(dep, (int, float)) and isinstance(fee, (int, float)) and float(dep) == part and float(fee) == whole - part else m.group(0)
    body = re.sub(_AMT_NUM + r"[ \t]*(?:pet[ \t]+)?deposit\b" + _REFUNDABLE_PART, _split_held, body, flags=re.I)
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
_NET_FREE_RENT = re.compile(r"(?<![\w/.])(?:(?:\d+/\d+|\d+(?:\.\d+)?|one|two|three|a|half(?:\s+a)?|one[- ]half)\s+(?:months?|weeks?)(?:'s)?(?:\s+of\s+rent)?\s+free|free\s+rent|(?:months?|weeks?)\s+free|rent[- ]free\s+(?:month|period)|concessions?)\b", re.I)
_NET_BROKER_MONTH = re.compile(r"\b(?:broker|agent|finder|realtor|leasing)(?:'s|s')?\s+fee\b[^.\n;$]{0,30}?\b(?:(?:one|two|a|\d+(?:\.\d+)?)\s*(?:months?|mo)\b|\d+\s*%)|\b(?:one|two|\d+)\s+months?\s+(?:broker|agent|finder)(?:'s)?\s+fee", re.I)
_NET_UTIL_WORD = re.compile(r"\b(?:water|sewer|trash|garbage|electric(?:ity)?|gas|heat(?:ing)?|internet|wifi|cable|utilit(?:y|ies))\b", re.I)
_NET_UTIL_CUE = re.compile(r"\b(?:utilit(?:y|ies)|included|tenant|resident|renter|you pay|pay for|paid by|owner pays|landlord|extra|separate|billed|flat|metered|submeter|responsible|set up)\b", re.I)
_NET_UTIL_NOT = re.compile(r"\b(?:gas|electric)\s+(?:stove|range|oven|fireplace|grill|cooktop|appliances?|logs?)\b|\bheat\s*pump\b|\bgas station\b", re.I)
_NET_REAL_FIELDS = ("price", "parking_cost", "pet_rent", "pet_fee", "utilities_estimate", "pet_weight_limit", "pet_deposit", "deposit",
                    "application_fee", "other_monthly_fees", "move_in_fees", "broker_fee", "hoa", "property_tax", "insurance",
                    "special_assessment", "closing_costs", "seller_credit")
_NET_ENDS = ".;!?\n|•"


_ONE_TIME_WORDS = re.compile(r"move[- ]out|one[- ]time|non[- ]?refundable|\bclosing\b|\blender\b|\btitle (?:fees?|insurance|company)\b|\bescrow (?:fee|deposit)|\borigination\b|\brecording fees?\b|transfer tax", re.I)
_SELLER_PAID_WORDS = re.compile(r"\bpaid by (?:the )?seller\b|\bseller[- ]paid\b|\bseller (?:will )?(?:pay|cover)s?\b|\bby the seller\b", re.I)
_DEAL_WORDS = re.compile(r"\blimited[- ]time\b|\bfor a limited\b|\bconcessions?\b|\bfree rent\b|\bmonths? free\b|\bweeks? free\b|\bmove-in special\b|\brent credit\b", re.I)
_MONTHLY_WORDS = re.compile(r"/\s*(?:mo|month)\b|\bper month\b|\ba month\b|\bmonthly\b|\bmo\.", re.I)


def _uncounted_kind_sentence(phrase: str) -> str:
    """What the safety-net note says about a quoted amount that no field holds: a one-time cost is not in the monthly cost, a
    monthly fee is not counted, and when the line does not say, the generic sentence."""
    one, monthly = bool(_ONE_TIME_WORDS.search(phrase)), bool(_MONTHLY_WORDS.search(phrase))
    if _SELLER_PAID_WORDS.search(phrase):
        return "The seller pays it, so it is not your cost and it is not in the monthly cost."  # cycle 27: a seller-paid figure is never "who pays?"
    pieces_ = [x for x in re.split(r"[,;\n]|\bplus\b|\band\b|\*|\s~\s", phrase) if _dollar_values(x)]
    from .money import _EXPL_SECOND
    if pieces_ and all(_EXPL_SECOND.search(x) and not re.search(r"\b(?:required|mandatory)\b", x, re.I) for x in pieces_):
        return "It looks like an optional extra, so it is not counted in the monthly cost."  # cycle 27: a second item or a storage add-on
    if _DEAL_WORDS.search(phrase) and not monthly:
        return "It is a one-time deal, so it is not in the monthly cost."  # cycle 24: a concession is a deal, never a missing monthly cost
    if monthly and not one:
        pieces = [x for x in re.split(r"[,;\n]|\bplus\b|\band\b|\*|\s~\s", phrase) if _dollar_values(x)]
        if len(pieces) > 1 and not all(_MONTHLY_WORDS.search(x) for x in pieces):
            return "It is not counted anywhere."  # cycle 22: "$35/mo, $200 fee": only some of the amounts are monthly, so the line is not called monthly
    if one and not monthly:
        return "It is a one-time cost, so it is not in the monthly cost."
    if monthly and not one:
        if _NET_UTIL_WORD.search(phrase) and not re.search(r"\bfees?\b|valet|\bpets?\b|deposit|\binternet\b|\bwifi\b|\bcable\b|\bhoa\b|assessment|\bdues\b|association", phrase, re.I):
            return "It looks like a utility cost and it is not counted anywhere."  # cycle 17: a utility amount is never called "a monthly fee"
        return "It is a monthly fee and it is not counted anywhere."
    return "It is not counted anywhere."


_PLURAL_KIND = (("The seller pays it, so it is not your cost and it is not in the monthly cost.", "are paid by the seller, so they are not your cost and they are not in the monthly cost."),
                ("It looks like an optional extra, so it is not counted in the monthly cost.", "are optional extras, so they are not counted in the monthly cost."),
                ("It is a one-time cost, so it is not in the monthly cost.", "are one-time costs, so they are not in the monthly cost."),
                ("It looks like a utility cost and it is not counted anywhere.", "look like utility costs and they are not counted anywhere."),
                ("It is a monthly fee and it is not counted anywhere.", "are monthly fees and they are not counted anywhere."),
                ("It is not counted anywhere.", "are not counted anywhere."))


def _with_rest_counted(sentence: str) -> str:
    """A "not counted" sentence that names only some of the amounts in a line says the rest of the line is counted."""
    return sentence[:-1] + "; the other amounts in that line are counted." if sentence.startswith("Only ") and sentence.endswith(".") else sentence


def _only_unplaced(sentence: str, phrase: str, used: set[float], out: dict[str, Any] | None = None, extra_placed: set[float] | frozenset[float] = frozenset()) -> str:
    """When a quoted line holds some amounts a field already counts and some it does not, the "not counted" sentence names only the
    amounts that are not placed ("Only $4 of that is a monthly fee and it is not counted anywhere."), never the whole line. The kind
    (monthly, one-time) is read from the words around the unplaced amounts, not from the placed ones."""
    amounts = sorted(_dollar_values(phrase))
    placed = placed_amounts(set(amounts), used, _field_sums(out or {}), phrase, out) | (set(amounts) & set(extra_placed))
    left = [a for a in amounts if a not in placed]
    if len(amounts) < 2 or not left or len(left) == len(amounts):
        return sentence
    shown = [f"${a:,.0f}" if float(a).is_integer() else f"${a:,.2f}" for a in left]
    names = shown[0] if len(shown) == 1 else ", ".join(shown[:-1]) + " and " + shown[-1]
    pieces = [x for x in re.split(r"[,;\n]|\bplus\b|\band\b|\*", phrase) if x.strip()]
    mine = " ".join(x for x in pieces if any(a in _dollar_values(x) for a in left))
    kind = _uncounted_kind_sentence(mine) if mine else "It is not counted anywhere."
    if kind == "It is not counted anywhere." and _ONE_TIME_WORDS.search(phrase) and not _MONTHLY_WORDS.search(mine):
        kind = "It is a one-time cost, so it is not in the monthly cost."
    if len(left) > 1:
        for single, plural in _PLURAL_KIND:
            if kind == single:
                return f"Only {names} of that {plural}"
    return re.sub(r"^It (?:is|looks)", lambda m: f"Only {names} of that " + ("is" if m.group(0) == "It is" else "looks"), kind, count=1)


_ABBREV_BEFORE = re.compile(r"(?:\b(?:est|approx|avg|incl|apt|ca|ave|inc|bldg|ste)|\b[a-z])$", re.I)


def _real_end(text: str, i: int) -> bool:
    """A sentence end: a full stop after "est" or "approx" (or inside a number such as 1.45k) is not one."""
    if text[i] != ".":
        return True
    nxt = text[i + 1:i + 2]
    if nxt and not nxt.isspace():
        return False
    return not _ABBREV_BEFORE.search(text[max(0, i - 8):i])


def _end_before(text: str, c: str, start: int) -> int:
    at = start
    while True:
        at = text.rfind(c, 0, at)
        if at < 0 or _real_end(text, at):
            return at


def _end_after(text: str, c: str, end: int) -> int:
    at = end - 1
    while True:
        at = text.find(c, at + 1)
        if at < 0 or _real_end(text, at):
            return at


_FORMAT_CHARS = re.compile("[\u00ad\u200b-\u200f\u202a-\u202e\u2060-\u2069\ufeff\U000e0000-\U000e007f]")
_QUOTE_WORD = re.compile(r"[A-Za-z](?:[A-Za-z'\-]*[A-Za-z])?[,:]?")
_QUOTE_NUM = re.compile(r"[~\u2248]?\$?\d[\d,]*(?:\.\d+)?(?:/[A-Za-z]+|[A-Za-z]+\d*)?[,:)]?")
_QUOTE_JUNK_PHRASE = re.compile(r"[<>\[\]{}=@\\_`^\uff1d]|<!|\|")


def _quote_token_ok(tok: str) -> bool:
    return bool(_QUOTE_WORD.fullmatch(tok) or _QUOTE_NUM.fullmatch(tok))


def _tidy_quote(phrase: str, text: str, start: int, end: int) -> str:
    """A quote of an open figure that reads as plain words. A clean phrase is returned as it is. A phrase that holds markup, a formula, a
    hidden character or text aimed at an AI tool is cut down to the figure with the clean words next to it ("Concierge ... $25 monthly",
    "$14"): it never starts in the middle of a word or number and never carries the junk."""
    from .redflags import _AI_C17, _AI_EXTRA, _AI_TARGETED
    folded = _FORMAT_CHARS.sub("", phrase)
    before = re.split(r"[.!?]\s|\n", text[max(0, start - 70):start])[-1]
    around = _FORMAT_CHARS.search(before) or re.search(r"[=\uff1d+@]\s?[A-Za-z]{2,10}\||<!--|</?[A-Za-z]|-->", before)  # junk just in front of the clause
    aimed = any(pat.search(phrase) for pat in (_AI_TARGETED, _AI_EXTRA, _AI_C17))  # cycle 22: text aimed at an AI tool is never quoted whole
    if folded == phrase and not around and not aimed and not _QUOTE_JUNK_PHRASE.search(phrase) and all(_quote_token_ok(t.rstrip(".;!?")) or not re.search(r"^[A-Za-z]{1,2}\d+$|[A-Za-z]!|!\w", t) for t in phrase.split()):
        return phrase
    ls = text.rfind("\n", 0, start) + 1
    le = text.find("\n", end)
    line = text[ls:(le if le >= 0 else len(text))]
    line = _FORMAT_CHARS.sub("", line)
    line = re.sub(r"<!--.*?-->|<[^>]{0,80}>", " \x00 ", line)
    line = re.sub(r"[=\uff1d+@]\s?[A-Za-z]{2,10}\|\S*(?:\s+'?[/\w]+'?!?\w*)?", " \u00a7 ", line)  # a spreadsheet formula ("=cmd|calc", "+cmd|' /C calc'!A0")
    for pat in (_AI_TARGETED, _AI_EXTRA, _AI_C17):
        line = pat.sub(" \x00 ", line)
    amount_text = text[start:end].replace(" ", "")
    toks = line.split()
    idx = next((i for i, t in enumerate(toks) if amount_text in t.replace(" ", "")), None)
    if idx is None:
        return phrase
    left: list[str] = []
    skipped = 0
    i = idx - 1
    while i >= 0 and len(left) < 5:
        t = toks[i]
        if "\x00" in t or re.search(r"[.;!?]$", t):
            break
        if _quote_token_ok(t):
            left.insert(0, t)
            skipped = 0
        else:
            skipped += 1
            if skipped > 3:
                break
            if not left or left[0] != "...":
                left.insert(0, "...")
        i -= 1
    while left and left[0] == "...":
        left.pop(0)
    cut_at = max((i for i, w in enumerate(left) if w.lower() in ("and", "to", "or", "but", "then")), default=-1)
    if 0 <= cut_at < len(left) - 1:
        left = left[cut_at + 1:]  # "the city and to send $500" is quoted from the last "to": "send $500"
    words = [w for w in left if w != "..."]
    if not any(len(re.sub(r"[^A-Za-z]", "", w)) >= 3 for w in words):
        left = []
    amt_tok = toks[idx].rstrip(".;!?,)")
    right: list[str] = []
    for t in toks[idx + 1:idx + 4]:
        if "\x00" in t or not re.fullmatch(r"(?:per|a|each|month|monthly|mo|year|yearly|annually|/mo|/month|/yr|flat|extra|deposit|fees?|charge|rent|payment|holding|reservation|application)[.;!?]?", t, re.I):
            break
        right.append(t.rstrip(".;!?"))
        if re.search(r"[.;!?]$", t):
            break
    if right and right[0].lower() in ("and", "or", "plus", "the", "a"):
        right = []
    out = " ".join([*left, amt_tok, *right]).strip(" ,:-")
    out = re.sub(r"^(?:and|or|but|then|to)[ \t]+", "", out, flags=re.I)
    return out.replace('"', "'")


def _comma_before(text: str, lo: int, start: int) -> int:
    """Where a quote may start after the last comma before ``start``: never inside a number ("$1,380"). ``lo`` when there is none."""
    at = start
    while True:
        at = text.rfind(",", lo, at)
        if at < 0:
            return lo
        if not (text[at - 1:at].isdigit() and text[at + 1:at + 2].isdigit()):
            return at + 1


def _comma_after(text: str, end: int, hi: int) -> int:
    """The first comma at or after ``end`` that is not inside a number, else -1."""
    at = end
    while True:
        at = text.find(",", at, hi)
        if at < 0:
            return -1
        if not (text[at - 1:at].isdigit() and text[at + 1:at + 2].isdigit()):
            return at
        at += 1


_NET_SEGMENT_SEPS = (" * ", " ~ ")


def _net_clause(text: str, start: int, end: int, limit: int = 160) -> str:
    """The short phrase around text[start:end]: the clause it sits in. A clause that fits ``limit`` is quoted whole, never
    cut in the middle; a longer one is narrowed to the comma-separated piece that holds the match, and only a piece that is
    still too long is cut at a word edge."""
    left = max(_end_before(text, c, start) for c in _NET_ENDS) + 1
    for sep in _NET_SEGMENT_SEPS:  # cycle 22: " * " and " ~ " separate bullets or segments: each is its own clause
        at = text.rfind(sep, 0, start)
        if at >= 0:
            left = max(left, at + len(sep))
    rights = [i for i in (_end_after(text, c, end) for c in (*_NET_ENDS, *_NET_SEGMENT_SEPS)) if i >= 0]
    right = min(rights) if rights else len(text)
    lo, hi = left, right
    if hi - lo > limit:
        lo = max(lo, _comma_before(text, lo, start))
        comma = _comma_after(text, end, hi)
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
    phrase = re.sub(r"\.{2,}$", "", " ".join(text[lo:hi].split()).strip(" ,:-–—")).strip(" ,:-–—")
    phrase = re.sub(r"^~\s+|\s+~$", "", phrase)  # a segment mark, not an "about" sign
    return phrase.replace('"', "'")


def _quotes_title(phrase: str, title: Any) -> bool:
    """True when a quoted phrase is just the listing's title (or a piece of it)."""
    if not title or not isinstance(title, str):
        return False
    if re.search(r"[$\uff04]\s?\d", phrase) and not re.search(r"[$\uff04]\s?\d", title) and (lambda v: bool(v) and max(v) < 500)(_dollar_values(phrase)):
        return False  # cycle 27: the title has no dollar figure, so a phrase that holds one is more than the title ("Storage unit $30" is not the title "Storage unit")
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
    nums |= _try(lambda: _utility_component_numbers(text)) or set()  # the figures a utilities estimate was added up from
    nums.update(float(v) for _l, v, _k in _try(lambda: _one_time_fee_items(text)) or [])  # cycle 21: the items of a "Fees:" list that are added into move-in fees
    bg = _try(lambda: _background_check_each(text))
    if bg:
        nums.add(float(bg))  # cycle 21: added to the per-adult application fee
    return nums


def _net_used_numbers(out: dict[str, Any], facts: list[str], text: str = "") -> set[float]:
    """Every number a field or a note already carries, and the parts and conversions behind a field."""
    comps: set[float] = _net_component_numbers(text) if text else set()
    used: set[float] = set(comps)
    for key in _NET_REAL_FIELDS:
        v = out.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v:
            used.add(float(v))
            if key in ("hoa", "property_tax", "insurance", "other_monthly_fees", "parking_cost", "utilities_estimate", "pet_rent"):
                if key in ("hoa", "property_tax", "insurance"):  # cycle 20: a bare multiple is a coincidence ($120 against parking $40), so only the fields that are billed by period keep it
                    used.update({round(float(v) * 12, 2), round(float(v) * 3, 2), round(float(v) * 6, 2)})  # a yearly, quarterly or half-year figure written beside the monthly one
                    used.update({float(round(float(v) * k)) for k in (3, 6, 12)})  # "$425 a quarter" saved as 141.67 a month: 141.67 x 3 is 425.01
                if key == "parking_cost":
                    used.update({round(float(v) / 2, 2)})  # "$175 each, 2 required" saved as $350
                if key in ("property_tax", "insurance"):  # saved per year: the monthly share is the same figure ("$3,100 a year ($258/mo)")
                    used.update({round(float(v) / 12, 2), float(round(float(v) / 12)), float(int(float(v) / 12)), float(round(float(v) / 4)), float(round(float(v) / 2))})
    # cycle 24 join: a part read with cents ("Application fee $42.50") is not placed by a field that holds only its whole dollars ($42): the cents were lost
    fields = {float(out[k]) for k in _NET_REAL_FIELDS if isinstance(out.get(k), (int, float)) and not isinstance(out.get(k), bool) and out.get(k)}
    used -= {c for c in comps if c != int(c) and c not in fields and any(f == int(f) and 0 < abs(c - f) < 1 for f in fields)}
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
    used_fields = _net_used_numbers(out, [], text)  # cycle 22: "the other amounts in that line are counted" is decided by the fields, never by a figure that another note quotes
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
        from .dropguard import _months_count_explained
        if _months_count_explained(text, m.end(), amount, out):
            continue  # cycle 25: "$1.5 months rent deposit hold": the deposit field holds 1.5 months of rent
        before = text[max(0, m.start() - 45):m.start()]
        after = text[m.end():m.end() + 45]
        near = before[-30:] + " " + after[:25]
        rent_read = isinstance(out.get("price"), (int, float))  # with no rent read, a rent-looking amount is still worth a line
        if _NET_SKIP_NEAR.search(near):
            continue
        from . import dropguard
        from .dropguard import is_non_cost
        if is_non_cost(text, m.start(), m.end(), amount):
            continue  # cycle 20: a penalty, a replaced figure, an old price, the low of a seasonal pair: never a cost "not counted"
        if rent_read and amount >= 500 and ((floor_plans and _NET_UNIT_BEFORE.search(before)) or re.search(r"\$\s?[\d,]+\s*(?:-|–|to)\s*$", before)
                              or re.match(r"\s*(?:-|–|to)\s*\$\s?\d", after)):
            continue  # a floor plan or a rent range, not an extra cost
        phrase = _net_clause(text, m.start(), m.end())
        if phrase:
            from .redflags import trim_at_injection
            phrase = trim_at_injection(phrase)  # a line that runs on into text aimed at an AI is quoted only up to the fee itself
            phrase = _tidy_quote(phrase, text, m.start(), m.end())  # markup, a formula or a hidden character in the line never goes into the quote
        if not phrase:
            continue
        if _quotes_title(phrase, out.get("title")):
            continue  # the title line itself is not a note
        if dropguard._CONCESSION_ITEM.search(phrase) and any(dropguard._CONCESSION_NOTE.search(f) for f in facts):
            continue  # cycle 25: "$6,000 in concessions, 1 month free": the concession note already says it is a one-time deal that is not counted
        n_adults = re.search(r"\bfor\s+(\d|two|three|four)\s+(?:adults?|applicants?|people|persons?)\b[^.]{0,30}\b(?:together|total|combined|in all|altogether)\b", phrase, re.I)
        if n_adults:
            k = {"two": 2, "three": 3, "four": 4}.get(n_adults.group(1).lower()) or int(n_adults.group(1))
            if any(abs(c * k - amount) < 0.01 for c in used if c):
                continue  # "For 2 adults that is $110 together": the sum of a per-adult fee that is already placed
        if any(re.search(r"\boptional\b", f, re.I) and not re.search(r"\b(?:required|mandatory)\b", f, re.I) and amount in _dollar_values(f) for f in facts):
            done.add(amount)
            continue  # cycle 26: a figure an earlier note already explains as optional is that one note, never also "not counted anywhere" or missing
        if amount in placed_amounts(_dollar_values(phrase), used, _field_sums(out), phrase, out):
            done.add(amount)
            continue  # a field counts it (a yearly figure's monthly share, part of a sum, a utility the tenant pays with an estimate): never "not counted"
        done.add(amount)
        if any(f'"{phrase}"' in n for n in notes):
            continue  # a second amount in the same quoted line: the line is already there
        if re.search(r"\b(?:per|a|each)\s+load\b|/\s*load\b", near, re.I):
            notes.append(f'The listing says laundry costs "{phrase}". It is not counted anywhere.')
        elif re.search(r"\bincluded\s+in\s+(?:your|the)\s+(?:monthly\s+)?rent\b", phrase, re.I) and not re.search(r"\bnot\s+included\b", phrase, re.I):
            notes.append(f'The listing says "{phrase}". It is included in the rent, so it is not added on top.')
        elif re.search(r"\b(?:holding|reservation|reserve|move[- ]in total|total to move)\b", phrase, re.I):
            notes.append(f'The listing says "{phrase}". It is a one-time amount, so it is not in the monthly cost. Ask if it is taken off what you owe at move-in.')
        elif re.search(r"\b(?:second|2nd|additional|extra)[ \t]+(?:vehicle|car|auto)s?\b", phrase, re.I) and not re.search(r"\b(?:required|mandatory|must)\b", phrase, re.I):
            notes.append(f'The listing says "{phrase}". A second vehicle is optional, so it is not counted in the monthly cost. Ask the price if you will have two cars.')
        elif re.search(r"\boptional\b|\balso (?:offered|available)\b|\b(?:garage|carport|covered|reserved)\b[^.\n]{0,25}\b(?:offered|available) (?:for|at)\b", near, re.I) and not re.search(r"\b(?:required|mandatory|must)\b", phrase, re.I):
            notes.append(f'The listing says "{phrase}". It looks optional, so it is not counted in the monthly cost. Ask if it is required.')
        elif (nk := dropguard.not_cost_kind(text, m.start(), m.end(), amount, out.get("price"))):
            notes.append(f'The listing also says "{phrase}". {dropguard.not_cost_sentence(nk)}')  # cycle 24: another plan, an older price, a deposit alternative, another lease length: kept as a note, never "missing"
        else:
            notes.append(f'The listing also says "{phrase}". {_with_rest_counted(_only_unplaced(_uncounted_kind_sentence(phrase), phrase, used_fields, out))} Check what it is for.')
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
    if m and not re.search(r"free rent|months? free|weeks? free|concession|net effective", low_facts):
        notes.append(f'The listing mentions a free-rent offer ("{_net_clause(text, m.start(), m.end())}"). It is not counted anywhere. Check the terms.')
    m = _NET_BROKER_MONTH.search(text)
    if m and not out.get("broker_fee") and not re.search(r"broker|agent fee|finder", low_facts):
        notes.append(f'The listing says "{_net_clause(text, m.start(), m.end())}". The fee is given as {"a share" if "%" in _net_clause(text, m.start(), m.end()) else "months"} of the rent, so no amount is saved. Ask what it comes to.')
    m = re.search(r"\b(?:laundry|washer|dryer|w\s*/\s*d|washing machines?|coin[- ]op)\b", text, re.I)
    if m and not out.get("laundry") and not re.search(r"laundry|washer|dryer|hookup", low_facts) and not any("laundry" in n for n in notes):
        notes.append(f'The listing mentions laundry ("{_net_clause(text, m.start(), m.end())}"), but I could not tell what kind. Ask if it is in the unit, in the building or off site.')
    m = next((pm for pm in re.finditer(r"\b(?:parking|garage|carport|driveway|off[- ]street)\b", text, re.I)
              if not re.search(r"\bassessments?\b|\brepair|\breplacement|\bresurfac|\bsealcoat", _net_clause(text, pm.start(), pm.end()), re.I)), None)  # "assessment for the parking deck repair" is a cost, not parking
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


_UTIL_QUOTE_NOTE = re.compile(r'The listing also says "([^"]*)"\. ')
_NON_UTIL_COST_WORD = re.compile(r"\b(?:fees?|parking|garage|carport|deposit|pets?|hoa|dues|insurance|application|admin|permit|locker|storage|valet|pest|lawn|amenity)\b", re.I)


def _answer_utility_notes(facts: list[str], out: dict[str, Any]) -> list[str]:
    """When the place holds a utilities estimate that the user or Claude set (not the reader's own), every note that only quotes utility
    amounts ("Electric $45 seasonal, gas $20-$60", "Only $15 of that", "I could not tell who pays") is answered by that estimate: the whole
    utility note family says so in one plain sentence, so none of it is left reading as "not counted"."""
    est = out.get("utilities_estimate")
    if not isinstance(est, (int, float)) or isinstance(est, bool):
        return facts
    done: list[str] = []
    for f in facts:
        m = _UTIL_QUOTE_NOTE.match(f)
        if m and _NET_UTIL_WORD.search(m.group(1)) and not _NON_UTIL_COST_WORD.search(m.group(1)):
            f = f'The listing also says "{m.group(1)}". The utilities estimate saved on this place is ${float(est):,.0f} a month, so the utility amounts in that line are answered by it.'
        elif re.match(r'The listing mentions utilities \("[^"]*"\), but I could not tell who pays', f):
            continue
        done.append(f)
    return done


_QUOTE_NOTE = re.compile(r'^The listing also says "([^"]*)"\. (.*) Check what it is for\.$')
_PARTS_NOTE = re.compile(r"^The listing also gives .+? at about \$([\d,]+(?:\.\d+)?) a month\. Only the figure that covers more or is higher, \$([\d,]+(?:\.\d+)?), is counted\.$")
_COUNTED_OTHER_FEES = re.compile(r"\bcounted in other monthly fees\b|\bis counted in other monthly fees\b", re.I)


def _settle_notes(text: str, out: dict[str, Any], facts: list[str], buying: bool = False) -> list[str]:
    """Cycle 21: the notes made agree with the final fields, one truthful note each. A figure that is part of a counted total (electric $50,
    gas $25, internet $55 and trash $18 inside "about $148 total") is placed, so it is never "not counted anywhere" and its parts are not
    repeated. "The other amounts in that line are counted" is said only when every other amount in the line is in a saved field. For a
    home for sale, a note that says an amount is "counted in other monthly fees" (the cost of buying does not use that field) is dropped
    when another note already says the same figure is not counted, and otherwise says it is not counted."""
    from . import dropguard
    est = out.get("utilities_estimate")
    util_ok: set[float] = set()
    if not buying and isinstance(est, (int, float)) and not isinstance(est, bool) and est:
        util_ok = dropguard._util_placed(text, float(est))
    used = _net_used_numbers(out, [], text)
    done: list[str] = []
    for f in facts:
        if buying and _COUNTED_OTHER_FEES.search(f):
            amt = next(iter(sorted(_dollar_values(f))), None)
            if amt is not None and any(g is not f and "not counted" in g and amt in _dollar_values(g) for g in facts):
                continue  # the same figure has a note that says it is not counted: one truthful note
            f = re.sub(r"\bis counted in other monthly fees\.(?: If it is optional, take it out\.)?|, counted in other monthly fees\.(?: If it is optional, take it out\.)?|so it is counted in other monthly fees\.",
                       "but the cost of buying does not use other monthly fees, so it is not counted anywhere. Add it to your own budget if you pay it.", f)
        pm = _PARTS_NOTE.match(f)
        if pm and util_ok and float(pm.group(1).replace(",", "")) in util_ok and abs(float(pm.group(2).replace(",", "")) - float(est or 0)) < 0.5:
            continue  # "electric about $50" is one of the parts that add up to the counted $148
        qm = _QUOTE_NOTE.match(f)
        if qm and re.search(r"not counted anywhere|not in the monthly cost", qm.group(2)):
            q = qm.group(1)
            amounts = _dollar_values(q)
            extra = {a for a in amounts & util_ok} if (util_ok and _NET_UTIL_WORD.search(q)) else set()
            if extra:
                placed = placed_amounts(amounts, used, _field_sums(out), q, out) | extra
                if amounts <= placed:
                    continue  # every figure in the line is in a field or is a part of a counted total: nothing is left out
                kind = _uncounted_kind_sentence(q)
                new = _with_rest_counted(_only_unplaced(kind, q, used, out, extra))
                f = f'The listing also says "{q}". {new} Check what it is for.'
            elif "the other amounts in that line are counted" in qm.group(2):
                named = _dollar_values(qm.group(2))
                sums = _field_sums(out)
                strict = {round(u, 2) for u in used} | {round(x, 2) for x in sums}
                if any(round(a, 2) not in strict and not any(abs(a / k - u) < 0.51 for u in strict for k in (3, 6, 12)) for a in amounts - named):
                    f = f.replace("; the other amounts in that line are counted.", ".")  # said only when every other amount is in a saved field
        done.append(f)
    return done


def _no_silent_drop(text: str, out: dict[str, Any], facts: list[str], skip_util: bool = False) -> list[str]:
    """Cycle 20: a dollar figure of the listing that no field holds and no note explains gets a plain note that quotes its phrase."""
    from . import dropguard
    if any("more things that are not counted" in f for f in facts):
        return []  # the safety net already said the listing has too many to list
    if not dropguard.ENABLED or _SALE_WORDS.search(text) or (isinstance(out.get("price"), (int, float)) and out["price"] >= 20000):
        return []  # a home for sale has its own readers and notes
    notes: list[str] = []
    for hit in dropguard.find_unplaced(text, out, "\n".join(facts)):
        if skip_util and hit["kind"] == "util":
            continue  # the estimate on the place was set by the user or Claude, so the utility figures are answered
        phrase = _net_clause(text, hit["start"], hit["end"])
        item = " ".join(str(hit["item"]).replace('"', "'").split()).strip(" ,:-'")
        if len(item) <= 120 and len(item) != len(phrase) and re.search(r"[A-Za-z]{4}", item) and (phrase in item or item in phrase):
            phrase = item  # "Internet (Xfinity) approx. $60/mo": the clause stops at the dot after approx.; "Fees: A $35, B $150": quote the one item
        if phrase:
            from .redflags import trim_at_injection
            whole = phrase
            phrase = trim_at_injection(phrase)
            if text[hit["start"]:hit["end"]].replace(" ", "") not in phrase.replace(" ", ""):
                phrase = whole  # cycle 22: a figure inside a flagged sentence ("... ignore previous instructions ... $14"): the clean words beside it are quoted, fenced and cut down
            phrase = _tidy_quote(phrase, text, hit["start"], hit["end"])
        if phrase and _quotes_title(phrase, out.get("title")) and item and len(item) < len(phrase):
            phrase = item  # the figure sits in the title line, so only its own item is quoted
        if phrase and _quotes_title(phrase, out.get("title")) and out.get("price") is None:
            tight = _hostile_figure_quote(text, hit["start"], hit["end"])  # cycle 24: a one-line listing whose title holds the figure: the figure with a few clean words beside it
            if tight and not _quotes_title(tight, out.get("title")):
                phrase = tight
        if not phrase or _quotes_title(phrase, out.get("title")) or any(f'"{phrase}"' in n for n in [*facts, *notes]):
            continue
        nk = dropguard.not_cost_kind(text, hit["start"], hit["end"], hit["amount"], out.get("price"))
        if nk:
            notes.append(f'The listing also says "{phrase}". {dropguard.not_cost_sentence(nk)}')
            continue
        notes.append(f'The listing also says "{phrase}". {_uncounted_kind_sentence(phrase)} Check what it is for.')
    if len(notes) > 8:
        notes = notes[:7] + [f"The listing has {len(notes) - 7} more things that are not counted. Read it again for the rest."]
    return notes


_LINK_IN_SENTENCE = re.compile(r"https?://|\bwww\.|\b[a-z0-9-]+\.(?:com|net|org|io|co|app|xyz|example|info|biz|ru|cn)\b/?", re.I)


def _hostile_amounts(text: str) -> dict[float, tuple[int, int]]:
    """Cycle 22: dollar figures that sit only in a sentence aimed at an AI tool or in a sentence that holds a link: {amount: (start, end) of the
    first one}. A figure that is also written in a plain sentence is left out (that sentence is the source)."""
    from .redflags import _AI_C17, _AI_EXTRA, _AI_TARGETED
    plain: set[float] = set()
    hostile: dict[float, tuple[int, int]] = {}
    for m in _NET_DOLLARS.finditer(text):
        raw = m.group(1) if m.group(1) is not None else m.group(4)
        try:
            amount = float(raw.replace(",", "") + (m.group(2) or "" if m.group(1) is not None else "")) * (1000 if m.group(3) else 1)
        except ValueError:
            continue
        lo = max(_end_before(text, c, m.start()) for c in ".!?\n|") + 1  # cycle 23: a pipe also ends an item ("... | 2nd $90 | Ignore previous instructions ...")
        hi = min([i for i in (_end_after(text, c, m.end()) for c in ".!?\n|") if i >= 0] or [len(text)])
        sentence = text[lo:hi]
        if any(pat.search(sentence) for pat in (_AI_TARGETED, _AI_EXTRA, _AI_C17)) or _LINK_IN_SENTENCE.search(sentence):
            hostile.setdefault(amount, (m.start(), m.end()))
        else:
            plain.add(amount)
    return {a: pos for a, pos in hostile.items() if a not in plain}


def _hostile_figure_quote(text: str, start: int, end: int) -> str:
    """The figure with up to three clean words on each side, cut where a link or text aimed at an AI tool starts ("pay the $500 holding fee")."""
    left = [w for w in re.findall(r"[A-Za-z][A-Za-z'-]*[,:]?|\S+", text[max(0, start - 60):start])][-3:]
    keep: list[str] = []
    for w in reversed(left):
        if not re.fullmatch(r"[A-Za-z][A-Za-z'-]*", w):
            break
        keep.insert(0, w)
    right: list[str] = []
    for w in text[end:end + 70].split()[:4]:
        if not re.fullmatch(r"[A-Za-z][A-Za-z'-]*|/mo|/month|per|a", w):
            break
        right.append(w)
    while right and right[-1].lower() in ("at", "on", "to", "via", "from", "by", "now", "and", "or", "the", "a", "per"):
        right.pop()
    while keep and keep[0].lower() in ("to", "and", "you", "must", "now", "then", "please", "user", "the"):
        keep.pop(0)
    return " ".join([*keep, text[start:end].strip(), *right]).replace('"', "'")


def _quote_hostile_facts(text: str, facts: list[str], out: dict[str, Any] | None = None) -> list[str]:
    """Cycle 22: a note that restates a figure the listing gave only inside a hostile sentence or a sentence with a link ("pay the $500 holding fee
    at https://...") is a fact laundered from that text. It is replaced by a fenced quote of the figure and the clean words beside it."""
    hostile = _hostile_amounts(text)
    if not hostile:
        return facts
    held = {round(u, 2) for u in _net_used_numbers(out or {}, [], text)}  # a figure a field counts stays as the reader said it
    done: list[str] = []
    for f in facts:
        vals = _dollar_values(re.sub(r'"[^"]*"', " ", f))
        if vals and all(v in hostile and round(v, 2) not in held for v in vals) and not re.search(r'^The listing (?:also )?says "', f):
            phrase = _hostile_figure_quote(text, *hostile[sorted(vals)[0]])
            new = f'The listing also says "{phrase}". It is not counted anywhere. Check what it is for.'
            if new not in done:
                done.append(new)
            continue
        done.append(f)
    return done


def _no_silent_percent(text: str, out: dict[str, Any], facts: list[str]) -> list[str]:
    """Cycle 22: a percent the listing gives for money ("Seller to credit 2% toward closing costs", "Broker fee: 5% of annual rent") that no field
    holds as dollars and no note quotes gets a plain note that quotes it. Never changes a field."""
    from . import dropguard
    if not dropguard.ENABLED:
        return []
    notes: list[str] = []
    for hit in dropguard.find_unplaced_percent(text, out, "\n".join(facts)):
        phrase = _net_clause(text, hit["start"], hit["end"])
        if phrase:
            from .redflags import trim_at_injection
            whole = phrase
            phrase = trim_at_injection(phrase)
            if text[hit["start"]:hit["end"]].replace(" ", "") not in phrase.replace(" ", ""):
                phrase = whole
            phrase = _tidy_quote(phrase, text, hit["start"], hit["end"])
        if not phrase or any(f'"{phrase}"' in n for n in [*facts, *notes]):
            continue
        notes.append(f'The listing also says "{phrase}". It is a percent, so no dollar amount is saved and it is not counted anywhere. Ask what it comes to.')
    return notes[:4]


_PER_APPLICANT = r"(?:per|each|/)[ \t]*(?:applicant|adult|person|occupant|tenant|resident|roommate)s?\b"


def _admin_fee_per_applicant(text: str) -> tuple[float, str] | None:
    """("$55 admin fee per applicant" -> (55, the text with that phrase taken out)). None when there is no such phrase."""
    pats = (r"\$\s?(\d{1,4}(?:\.\d\d)?)[ \t]*(?:admin(?:istrative|istration)?|processing)[ \t]+fees?[ \t]*" + _PER_APPLICANT,
            r"\b(?:admin(?:istrative|istration)?|processing)[ \t]+fees?[ \t:\-]*\$\s?(\d{1,4}(?:\.\d\d)?)[ \t]*" + _PER_APPLICANT)
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
        m = re.search(r"\$\s?(\d{1,3}(?:,\d{3})+(?:\.\d\d)?|\d{1,4}(?:\.\d\d)?)[ \t]*(?:one[- ]time[ \t]+|move[- ]in[ \t]+|non[- ]?refundable[ \t]+)*cleaning[ \t]+fees?\b|\bcleaning[ \t]+fees?(?:[ \t]+(?:at|due[ \t]+at|due|upon)[ \t]+(?:move[- ]?in|signing|lease[ \t]+signing))?[ \t:\-=(]{0,4}\$\s?(\d{1,3}(?:,\d{3})+(?:\.\d\d)?|\d{1,4}(?:\.\d\d)?)", clause, re.I)
        if not m:
            continue
        amount = _num(m.group(1) or m.group(2))
        non_refundable = bool(re.search(r"\bnon[- ]?refundable", clause, re.I))
        if re.search(r"move[- ]?out|moving out|\bwhen you (?:leave|move out)|\bat checkout\b", clause, re.I) and not re.search(r"move[- ]?in\b|moving in|\bat signing|\bpet\b|\brefund|\bdeducted|\bfrom the deposit", re.sub(r"\bnon[- ]?refundable", " ", clause, flags=re.I), re.I):
            notes.append(f"The listing has a {_usd(amount)} cleaning fee when you move out. It is a one-time cost at the end of the lease, so it is not counted in the monthly cost.")
            continue
        if re.search(r"move[- ]?out|moving out|\brefund|\bdeducted|\bfrom the deposit|\bpet\b|\bper[ \t]+(?:month|mo)\b|/\s*mo\b", re.sub(r"\bnon[- ]?refundable", " ", clause, flags=re.I), re.I):
            continue
        if non_refundable or re.search(r"move[- ]?in\b|moving in|\bat signing|\bupon (?:move|signing)|\bdue at (?:lease|signing)", clause, re.I):  # a non-refundable cleaning fee is paid up front
            if not re.search(r"move[- ]?in\b|moving in|\bat signing|\bupon (?:move|signing)|\bdue at (?:lease|signing)", clause, re.I):
                notes.append(f"The {_usd(amount)} non-refundable cleaning fee is counted as a one-time move-in fee. Ask if it is due at move-in.")
            return amount, notes
        notes.append(f"The listing mentions a {_usd(amount)} cleaning fee but not when it is due, so it is not counted. Ask if it is due at move-in.")
    return None, notes


_FLAT_WORDS = r"(?:hot water|water|sewer|sewage|trash|garbage|waste|lawn(?: care)?|landscaping|yard(?: work)?|snow(?: removal)?|pest(?: control)?)"
_FLAT_LIST = _FLAT_WORDS + r"(?:[ \t]*(?:,|/|&|\+|\band\b)[ \t]*(?:and[ \t]+)?" + _FLAT_WORDS + r")*"
_FLAT_PERIOD = r"(?:[ \t]*(?:/[ \t]*mo(?:nth)?\b|per[ \t]+month|a[ \t]+month|monthly|each[ \t]+month))"
_FLAT_UTILITY_ONLY = re.compile(r"^(?:(?:hot water|water|sewer|sewage|trash|garbage|waste)(?:[ \t]*(?:,|/|&|\+|\band\b)[ \t]*)?)+$", re.I)


_FEE_LABEL = re.compile(r"^[ \t]*(?:(?:monthly|move-?in|one-?time|other|additional|required|mandatory|pass-?through)[ \t]+)*(?:fees?|charges|costs)[ \t]*:[ \t]*", re.I)
_FEE_UTIL_ITEM = re.compile(r"^[ \t]*(?:and[ \t]+)?(?:[-*\u2022][ \t]*)?(?P<n>trash|garbage|water[ \t]*/[ \t]*sewer|water|sewer)(?:[ \t]+(?:fee|charge|service))?[ \t]*[:\-=]?[ \t]*(?:~|about[ \t]+|approx\w*[ \t]+)?\$[ \t]?(?P<a>\d{1,3}(?:\.\d\d)?)[ \t]*\.?[ \t]*$", re.I)


def _fee_list_utilities(text: str) -> list[tuple[str, float]]:
    """A water, sewer or trash item with a figure and no period inside a fee list ("Fees: admin $175, trash $12" or one pipe item among fee
    items). Returns [(name, amount)]. Items with a period ("trash $12/mo") are read by the monthly readers, never here."""
    out: list[tuple[str, float]] = []
    lines = text.split("\n")
    in_bullets = False
    for line in lines:
        segs = [x for x in re.split(r"[ \t]+[|\u2022\u00b7][ \t]+|(?<=[a-z\d\)])\.[ \t]+(?=[A-Z])", line)]
        region = False
        for seg in segs:
            if _FEE_LABEL.match(seg):
                region = True
                seg = _FEE_LABEL.sub("", seg)
                in_bullets = not seg.strip()
            elif re.match(r"^[ \t]*[A-Za-z][A-Za-z /&-]{1,25}:", seg) and not _FEE_UTIL_ITEM.match(seg):
                region = False
                if not re.match(r"^[ \t]*[-*\u2022]", seg):
                    in_bullets = False
            elif in_bullets and not re.match(r"^[ \t]*[-*\u2022]", seg):
                in_bullets = False
            if not (region or in_bullets):
                continue
            for part in _scope_top_commas(seg):
                m = _FEE_UTIL_ITEM.match(part)
                if m:
                    name = m.group("n").lower().replace(" ", "")
                    for w in (["water", "sewer"] if "/" in name else ["trash" if name == "garbage" else name]):
                        out.append((w, float(m.group("a"))))
    return list(dict.fromkeys(out))


def _flat_overlap(utext: str, covered: set[str]) -> list[dict[str, Any]]:
    """Figures the utility readers gave to utilities that a flat fee already covers ("Trash is $12/mo extra" beside "water/trash $60 flat"):
    [{"names": [...], "amount": 12.0}]. Only figures whose names are all inside the flat fee count."""
    found: list[dict[str, Any]] = []
    for it in _estimate_items(utext) or []:
        if not it["total"] and it["names"] and set(it["names"]) <= covered:
            found.append({"names": list(it["names"]), "amount": float(it["amount"])})
    gen = _util_general(utext, False)
    if gen and not gen["conflict"]:
        for it in gen["items"]:
            if it["names"] and set(it["names"]) <= covered and not any(abs(f["amount"] - it["monthly"]) < 0.01 for f in found):
                found.append({"names": list(it["names"]), "amount": float(it["monthly"])})
    return found


def _flat_service_fees(text: str) -> list[tuple[str, float, bool]]:
    """A flat fee for services that come with the unit ("Trash and lawn $30 flat fee", "Water/trash flat $65", "Water, trash
    and lawn: flat $75/mo fee"). Returns (label, amount, period given). A flat fee for water, sewer or trash that says "a
    month" is the utilities estimate (another reader counts it), so it is left out here."""
    found: list[tuple[str, float, bool]] = []
    pats = (r"\b(" + _FLAT_LIST + r")[ \t]*[:\-]?[ \t]*flat(?:[ \t-]?(?:fee|rate|charge))?[ \t:\-]*\$\s?(\d{1,3})(?:\.\d\d)?(?![\d,])(" + _FLAT_PERIOD + r")?",
            r"\b(" + _FLAT_LIST + r")[ \t]*[:\-]?[ \t]*\$\s?(\d{1,3})(?:\.\d\d)?(?![\d,])(" + _FLAT_PERIOD + r")?[ \t,]*(?:is[ \t]+)?flat(?:[ \t-]?(?:fee|rate|charge))?(" + _FLAT_PERIOD + r")?")
    # cycle 16: "Flat $75/mo fee for amenities", "Flat $75/mo fee covers trash and amenity", "... covers trash, pest and valet"
    # cycle 17: "Flat fee $85/mo covers water, sewer, trash and pest control", "$20/mo flat fee for lawn care", "Flat $20/mo for lawn care".
    # A flat fee that covers only water, sewer or trash is the utilities estimate (another reader); one that also covers a
    # service that is not a utility (pest control, lawn, snow, amenities) is a monthly fee, counted here.
    _cov = (_FLAT_WORDS + r"|amenit(?:y|ies)|valet(?:[ \t]+trash)?|package|technology|convenience")
    for m in re.finditer(r"(?:\bflat(?:[ \t-]?(?:fee|rate|charge))?[ \t:\-]*\$\s?(\d{1,3})(?:\.\d\d)?(?![\d,])(" + _FLAT_PERIOD + r")|(?<![\w$])\$\s?(\d{1,3})(?:\.\d\d)?(?![\d,])(" + _FLAT_PERIOD + r")[ \t]*flat(?:[ \t-]?(?:fee|rate|charge))?)"
                         r"[ \t,]*(?:fee|rate|charge)?[ \t,:\-]*(?:for|covers?|covering|includes?|including|pays?[ \t]+for)[ \t]+(?:the[ \t]+)?"
                         r"((?:" + _cov + r")(?:[ \t]*(?:,|/|&|\+|\band\b)[ \t]*(?:and[ \t]+)?(?:" + _cov + r"))*)", text, re.I):
        label = " ".join(m.group(5).lower().split())
        amount = float(m.group(1) or m.group(3))
        utility_only = bool(_FLAT_UTILITY_ONLY.match(label))
        if amount > 0 and not utility_only and not any(abs(amount - a) < 0.01 for _l, a, _p in found):
            found.append((label, amount, True))
    for pat in pats:
        for m in re.finditer(pat, text, re.I):
            label = " ".join(m.group(1).lower().split())
            period = bool(m.group(3) or (m.lastindex and m.lastindex >= 4 and m.group(4)))
            amount = float(m.group(2))
            if amount <= 0 or any(abs(amount - a) < 0.01 for _l, a, _p in found):
                continue
            if period and _FLAT_UTILITY_ONLY.match(label):
                continue
            found.append((label, amount, period))
    return found


def _months_words(n: float) -> str:
    return "half a month" if n == 0.5 else f"{n:g} month{'s' if n != 1 else ''}"


def _landlord_fee_months(text: str) -> float | None:
    """Months of rent a landlord fee is worth: "Landlord fee: 1 month's rent paid to Lakeshore Realty"."""
    nums = {"one": 1.0, "1": 1.0, "two": 2.0, "2": 2.0, "half": 0.5, "1/2": 0.5, "\u00bd": 0.5, "0.5": 0.5, "one-half": 0.5, "one half": 0.5, ".5": 0.5}
    m = re.search(r"\blandlord(?:'?s)?[ \t]+fee\b[ \t:\-=(]{0,4}(?:is |of |equal to |equals |=)?[ \t]*(one[- ]half|1/2|\u00bd|0?\.5|one|two|1|2|half)(?: a)?[ \t-]*month", text, re.I)
    return nums[m.group(1).lower()] if m else None


def _conditional_fee_notes(text: str, saved: bool) -> list[str]:
    """"Admin fee $75 due at signing, reduced to $0 if you apply this week": the full fee is what the listing states, and a note
    says the condition. Nothing is lowered, because the condition may not apply."""
    notes: list[str] = []
    for clause in re.split(r"\n|;|\.(?=\s|$)", text):
        m = re.search(r"\b(admin(?:istrative|istration)?|application|move[- ]in|lease[- ]signing|processing)[ \t]+fees?\b[^$\n]{0,12}\$\s?(\d{1,4}(?:\.\d\d)?)[^\n]{0,60}?\b(?:reduced|waived|discounted|dropped|cut)\b[^\n]{0,25}?\b((?:if|when|with|for|by)\b[^\n]{0,60})", clause, re.I)
        if not m:
            continue
        cond = m.group(3).strip(" ,")
        amount = float(m.group(2))
        kind = " ".join(m.group(1).lower().split())
        tail = f" The full ${amount:,.0f} is what is counted, because the condition may not apply to you." if saved else ""
        notes.append(f'The listing says the {kind} fee of {_usd(amount)} can be lower: "{cond}".{tail} Ask what you would really pay.')
    return notes


def _broker_fee_percent(text: str) -> tuple[float, str, float] | None:
    """Cycle 20: a broker fee given as a share of the rent: "Broker fee: 50% of one month's rent", "broker fee is half of a month's rent",
    "15% broker fee of annual rent". Returns (percent, words for what it is a share of, months of rent that share is taken from) or None."""
    head = r"\b(?:broker|agent|finder)(?:'?s)?[ \t]+fee\b[ \t:\-=(]{0,4}(?:is |of |equal to |equals |=)?[ \t]*"
    month = r"(?:(?:one|1|a|the|first|1st)[ \t]+)?month(?:'?s)?(?:[ \t]+(?:of[ \t]+)?(?:the[ \t]+)?rent)?"
    m = re.search(head + r"(\d{1,3}(?:\.\d)?)[ \t]*%[ \t]*(?:of[ \t]+)?(?:(?:the|a|one|1|first|1st)[ \t]+)?(?:(annual|yearly|12[- ]month)[ \t]+rent|month(?:'?s)?(?:[ \t]+(?:of[ \t]+)?(?:the[ \t]+)?rent)?|monthly[ \t]+rent)", text, re.I)
    if m:
        pct = float(m.group(1))
        if 0 < pct <= 100:
            return (pct, "a year of rent", 12.0) if m.group(2) else (pct, "one month's rent", 1.0)
    m = re.search(head + r"(\d{1,3}(?:\.\d)?)[ \t]*%[ \t]*of[ \t]+(?:(?:a|one|1|the)[ \t]+)?(?:full[ \t]+)?(?:year(?:'?s)?|12[ \t]+months'?)[ \t]+(?:of[ \t]+)?rent", text, re.I)
    if m and 0 < float(m.group(1)) <= 100 and not re.match(r"[ \t]*\?", text[m.end():]):  # cycle 21: "Broker fee is 8% of a year of rent"; "5% of one year's rent? No, ask" stays unread
        return float(m.group(1)), "a year of rent", 12.0
    m = re.search(head + r"(half)[ \t]+(?:of[ \t]+)?(?:(?:a|one|1)[ \t]+)?month(?:'?s)?(?:[ \t]+(?:of[ \t]+)?rent)?", text, re.I)
    if m:
        return 50.0, "one month's rent", 1.0
    m = re.search(r"\b(\d{1,3}(?:\.\d)?)[ \t]*%[ \t]+(?:broker|agent|finder)(?:'?s)?[ \t]+fee\b[ \t]*(?:of|on)[ \t]+(?:the[ \t]+)?(?:(annual|yearly)[ \t]+rent|" + month + r")", text, re.I)
    if m:
        pct = float(m.group(1))
        if 0 < pct <= 100:
            return (pct, "a year of rent", 12.0) if m.group(2) else (pct, "one month's rent", 1.0)
    return None


def _broker_fee_months(text: str) -> float | None:
    """Months of rent a broker fee is worth: "Broker fee one month", "broker fee: one month's rent", "one month broker fee"."""
    nums = {"one": 1.0, "1": 1.0, "two": 2.0, "2": 2.0, "half": 0.5, "1/2": 0.5}
    m = re.search(r"\b(?:broker|agent|finder)(?:'?s)?[ \t]+fee\b[ \t:\-=(]{0,4}(?:is |of |equal to |equals |=)?[ \t]*(?:(one|two|1|2)|(half)(?: a)?)[ \t-]*month", text, re.I) \
        or re.search(r"\b(?:(one|two|1|2)|(half)(?: a)?)[ \t-]*month(?:'?s)?(?: of rent| rent)?[ \t]+(?:broker|agent|finder)(?:'?s)?[ \t]+fee\b", text, re.I)
    if not m:
        return None
    return nums[(m.group(1) or m.group(2)).lower()]


_SVC_STRONG = (r"pest(?:[ \t]+control)?|package(?:[ \t]+(?:locker|lockers|service|room))?|parcel(?:[ \t]+locker)?|valet(?:[ \t]+(?:trash|waste))?|trash[ \t]+valet|"
               r"lawn(?:[ \t]+(?:care|maintenance|mowing|service))?|landscaping|snow(?:[ \t]+(?:removal|plowing))?")
_SVC_WEAK = r"amenit(?:y|ies)|community|technology|convenience|smart[ \t]+home"
_SVC_FEE_WORD = r"(?:[ \t]+(?:fees?|charges?|service|package))"
_SVC_PERIOD = r"(?:/[ \t]*mo(?:nth)?\b|[ \t]+per[ \t]+month|[ \t]+a[ \t]+month|[ \t]*monthly\b|[ \t]+each[ \t]+month)"
_SVC_BAD_TAIL = re.compile(r"\b(?:optional|billed|passed|deposit|one[- ]time|once|set[- ]?up|install|per[ \t]+(?:use|load|visit|quarter|year|week)|/[ \t]*(?:yr|year|qtr|quarter|wk|week)|annual|annually|yearly|quarterly|semi-?annual|weekly|biweekly|every[ \t]+(?:3|three|6|six)[ \t]+months|if[ \t]+(?:you|needed|wanted))", re.I)


def _service_fee_items(text: str) -> list[tuple[str, float]]:
    """Cycle 18: the general step for a list of named monthly services, in any layout: "Monthly pest control $6, package locker $4, valet trash
    $20", "Fees: $25 amenity fee monthly, $10 monthly package locker fee", "$35/month for lawn care and snow removal", "flat $10/mo package
    for trash valet". Returns (label, amount) for each named service with an amount that is monthly (a period beside it, a "monthly" word
    in the same sentence or list, or valet trash, which is always monthly). Optional, one-time, per-use and yearly items are left out."""
    found: list[tuple[str, float]] = []
    strong, weak = _SVC_STRONG, _SVC_WEAK
    more = r"(?:[ \t]*(?:,|/|&|\band\b)[ \t]*(?:" + strong + r")(?:" + _SVC_FEE_WORD + r")?)*"
    amt = r"\$\s?(?P<a>\d{1,3})(?:\.\d\d)?(?!,?\d)"
    lead = r"(?:(?:" + strong + r")(?:" + _SVC_FEE_WORD + r")?[ \t]*(?:,|/|&|\band\b)[ \t]*)*"
    p_name = re.compile(r"(?<![\w$])(?P<n>" + lead + r"(?:" + strong + r")(?:" + _SVC_FEE_WORD + r")?|(?:" + weak + r")" + _SVC_FEE_WORD + r")(?:[ \t]*\([^)\n$]{1,25}\))?[ \t:\-=]{0,4}(?:of[ \t]+)?" + amt + r"(?P<p>" + _SVC_PERIOD + r")?", re.I)
    p_amt = re.compile(amt + r"(?P<p>" + _SVC_PERIOD + r")?[ \t]*(?:flat[ \t]+)?(?:for[ \t]+)?(?:the[ \t]+)?(?:flat[ \t]+)?(?P<m>monthly[ \t]+)?(?P<n>(?:" + strong + r")(?:" + _SVC_FEE_WORD + r")?" + more + r"|(?:" + weak + r")" + _SVC_FEE_WORD + r")(?P<q>[ \t]*monthly\b|[ \t]+per[ \t]+month|/[ \t]*mo\b)?", re.I)
    p_locker = re.compile(r"(?<![\w$])(?P<n>(?:storage[ \t]+)?lockers?(?:[ \t]+fees?)?)[ \t:\-=]{0,4}" + amt + r"(?P<p>" + _SVC_PERIOD + r")?", re.I)
    clause_info: list[tuple[str, list[tuple[int, int]], bool]] = []
    for clause in re.split(r"\n|;|(?<=[a-z\)\d])\.(?=\s|$)", text):
        clause_start = len(found)
        clause_monthly = bool(re.search(r"\bmonthly\b|\bper[ \t]+month\b|/[ \t]*mo\b|\ba[ \t]+month\b", re.sub(r"\((?:about|approx\.?|roughly|around|~)[^)]*\)", " ", clause), re.I))
        spans: list[tuple[int, int]] = []
        for pat in (p_name, p_amt):
            for m in pat.finditer(clause):
                if any(m.start() < e and s0 < m.end() for s0, e in spans):
                    continue
                if re.search(r"\b(?:pets?|dogs?|cats?|parking|garage|storage|deposit|application|move[- ]in)[ \t]*[:\-]?[ \t]*$", clause[max(0, m.start() - 14):m.start()], re.I):
                    continue
                tail = clause[m.end():m.end() + 30]
                tail = re.split(r"[,]|\$", tail)[0]
                if _SVC_BAD_TAIL.search(tail) or _SVC_BAD_TAIL.search(clause[max(0, m.start() - 22):m.end()]):
                    continue  # "quarterly pest control fee of $30", "$30 per quarter", "optional"
                label = " ".join(m.group("n").lower().split())
                amount = float(m.group("a"))
                has_period = bool(m.groupdict().get("p") or m.groupdict().get("m") or m.groupdict().get("q"))
                always = not re.match(r"amenit|community|technology|convenience|smart", label)  # pest, package, valet, lawn and snow services are monthly unless the item says otherwise
                if amount <= 0 or not (has_period or clause_monthly or always):
                    continue
                spans.append((m.start(), m.end()))
                found.append((label, amount))
        clause_info.append((clause, spans, len(found) > clause_start and any(not re.search(r"locker", lb) for lb, _a in found[clause_start:])))
    # cycle 19: "Pest control $8, locker $10, valet trash $15" or a bullet "* Locker $10" among bullets of monthly services: a locker priced
    # inside a list of monthly services is one of them. A lone locker line is storage and keeps its own reading.
    for i, (clause, spans, hit) in enumerate(clause_info):
        near_bullets = False
        if re.match(r"[ \t]*[*\u2022\-][ \t]", clause):
            for step in (-1, 1):
                k = i + step
                while 0 <= k < len(clause_info) and re.match(r"[ \t]*[*\u2022\-][ \t]", clause_info[k][0]):
                    if clause_info[k][2]:
                        near_bullets = True
                    k += step
        if not (hit or near_bullets):
            continue
        for m in p_locker.finditer(clause):
            if any(m.start() < e and s0 < m.end() for s0, e in spans):
                continue
            tail = re.split(r"[,]|\$", clause[m.end():m.end() + 30])[0]
            if _SVC_BAD_TAIL.search(tail) or re.search(r"\b(?:pets?|dogs?|cats?|parking|garage|deposit|application|move[- ]in)[ \t]*[:\-]?[ \t]*$", clause[max(0, m.start() - 14):m.start()], re.I):
                continue
            found.append((" ".join(m.group("n").lower().split()), float(m.group("a"))))
    return found


_PENALTY_FEE = re.compile(r"(?<![\w$])(?P<l>late(?:[ \t]+(?:rent|payment))?|returned[ \t-]+(?:check|cheque|payment|item)s?|bounced[ \t-]+(?:check|cheque)s?|nsf|insufficient[ \t]+funds)(?:[ \t]+(?:fees?|charges?|penalty))?[ \t:\-=(]{0,4}(?:of[ \t]+)?\$\s?(?P<a>\d{1,4})(?:\.\d\d)?(?![\d,])"
                          r"|\$\s?(?P<a2>\d{1,4})(?:\.\d\d)?[ \t]*(?P<l2>late|returned[ \t-]+(?:check|cheque|payment|item)|bounced[ \t-]+(?:check|cheque)|nsf)(?:[ \t]+(?:fees?|charges?|penalty))", re.I)


def _penalty_fees(text: str) -> list[tuple[str, float]]:
    """Cycle 19: fees that only apply when you pay late or a payment bounces ("$75 late fee", "Returned check fee $35"). Returns (name, amount)."""
    found: list[tuple[str, float]] = []
    for m in _PENALTY_FEE.finditer(text):
        label = " ".join((m.group("l") or m.group("l2")).lower().split())
        label = {"nsf": "returned payment", "insufficient funds": "returned payment"}.get(label, label)
        if re.match(r"late", label):
            label = "late"
        label = re.sub(r"s$", "", label)
        if not label.startswith(("late", "returned", "bounced")):
            label = "returned payment"
        amount = float(m.group("a") or m.group("a2"))
        if amount > 0 and (label, amount) not in found:
            found.append((label, amount))
    return found


def _penalty_fee_note(text: str) -> str:
    """One plain note for late, returned-check and similar penalty fees: they are not a cost of living there, so they are named once
    (with their amounts) and never listed as an unexplained or missing cost."""
    items = _penalty_fees(text)
    if not items:
        return ""
    names = [f"a ${a:,.0f} {l} fee" for l, a in items[:3]]
    named = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    return f"The listing mentions {named}. A fee like this only applies if you pay late or a payment bounces, so it is not in the monthly cost."


def _is_sale_text(text: str) -> bool:
    """Sale words, with "new construction" ignored: a new-construction apartment building is still a rental."""
    text = re.sub(r"\bnew[ \t]+construction\b", " ", text, flags=re.I)
    if re.search(r"\b(?:tenants?|landlord|for[ \t]+rent|security[ \t]+deposit|application[ \t]+fee|lease[ \t]+terms?)\b", text, re.I):
        text = re.sub(r"\bopen[ \t]+house\b", " ", text, flags=re.I)  # cycle 26: "Open house Saturday" in a rental is a showing, not a sale
    return bool(_SALE_WORDS.search(text))


_ONE_TIME_LABELS = (
    r"admin(?:istrative|istration)?(?:[ \t]+fees?)?", r"lease[- ](?:processing|up|initiation|signing|admin\w*|set-?up|start-?up)(?:[ \t]+fees?)?",
    r"lease[ \t]+fees?", r"processing[ \t]+fees?", r"move[- ]?in[ \t]+fees?", r"key[ \t]+(?:deposit|fees?)", r"keys?(?=[ \t]*[:=]?[ \t]*\$)", r"(?:set-?up|start-?up|onboarding)[ \t]+fees?",
    r"(?:amenity|community|technology|tech)[ \t]+fees?",
    r"(?:one[- ]?time|non[- ]?refundable)[ \t]+(?:amenity|community|technology|tech)(?:[ \t]+fees?)?",  # cycle 22: "one-time amenity $200"
    r"move[- ]?in(?![ \t]*(?:fees?|total|costs?|specials?|date|day|ready|cash|charges?|money|price|amount|incentive|offer|-)\b)",
)
_ONE_TIME_CUE = re.compile(r"\b(?:one[- ]?time|once|up[- ]?front|due[ \t]+(?:at|before|on)[ \t]+(?:lease[ \t]+)?(?:signing|move[- ]?in)|at[ \t]+(?:lease[ \t]+)?(?:signing|move[- ]?in)|non[- ]?refundable|paid[ \t]+once)\b", re.I)
_MONTHLY_CUE = re.compile(r"(?:/[ \t]*(?:mo\w*|month\w*|yr|year)|\bper[ \t]+(?:month|mo|year|yr|pet|cat|dog|adult|person|applicant|bed|room)|\ba[ \t]+(?:month|year)|\bmonthly|\bannual(?:ly)?|\byearly|\bevery[ \t]+month|\beach[ \t]+month)", re.I)


def _one_time_fee_items(text: str) -> list[tuple[str, float, str]]:
    """Cycle 21: every named one-time fee of the listing, whatever the layout ("Fees: application $50, admin $120, lease processing $60",
    "$250 amenity fee one-time", "Admin $125 due at signing", "$50 lease fee", "Key deposit $50 refundable"). Returns (label, amount, kind) where kind is
    "fee" or "key". Monthly and per-person amounts are skipped. An amenity or community fee counts only when the listing says it is one time."""
    out: list[tuple[str, float, str]] = []
    out_pos: list[int] = []  # cycle 22: where each amount sits in the text, so one figure matched by two labels is counted once
    amt = r"\$[ \t]?(\d{1,2},\d{3}(?:\.\d\d)?|\d{1,4}(?:\.\d\d)?)(?!\d|,\d)"
    for lab in _ONE_TIME_LABELS:
        pats = (r"(?<![\w-])(" + lab + r")[ \t]*(?:is|are|of)?[ \t]*[:=\-]?[ \t]*(?:only[ \t]+)?" + amt,
                amt + r"[ \t]*(?:one[- ]?time[ \t]+|non[- ]?refundable[ \t]+)?(" + lab + r")(?![\w-])")
        for i, pat in enumerate(pats):
            for m in re.finditer(pat, text, re.I):
                label = " ".join(m.group(1 if i == 0 else 2).lower().split())
                n = m.group(2 if i == 0 else 1)
                v = _num(n)
                if not 0 < v <= 5000:
                    continue
                tail = text[m.end():m.end() + 40].split("\n")[0]
                tail = re.split(r"[;,]|\.(?:\s|$)|\$", tail)[0]
                head = text[max(0, m.start() - 24):m.start()]
                if _MONTHLY_CUE.search(tail) or re.search(r"\b(?:pet|application|app|credit|background|holding|reservation)[ \t]*$", head, re.I):
                    continue
                if i == 1 and re.search(r"(?:per|each|/)[ \t]*$", text[max(0, m.start() - 6):m.start()], re.I):
                    continue
                if i == 1 and re.search(r"\b(?:application|app|admin\w*|lease|pet|security|key|parking|processing|holding|credit|background|screening|cleaning|storage|move[- ]?in|damage)[ \t]+(?:fees?|deposits?|rent|costs?|charges?)[ \t]*[:=\-]?[ \t]*$|\brent[ \t]*[:=\-][ \t]*$", text[max(0, m.start() - 24):m.start()], re.I):
                    continue  # "Application fee: $50   Admin fee: $100": the $50 belongs to the label in front of it
                if re.search(r"(?:waive[ds]?|no|free|zero|off|reduced?|save|saving)[ \t]*$", head, re.I):
                    continue
                if re.match(r"move[- ]?in$", label):
                    line_before = text[text.rfind("\n", 0, m.start()) + 1:m.start()]
                    if v > 1000 or not re.search(r"\bfees?[ \t]*:|[;,|][ \t]*$", line_before, re.I):
                        continue  # a bare "Move-in $2,500" may be the whole cost to move in, so only an item of a fee list counts
                if re.match(r"(?:amenity|community|technology|tech)", label):
                    around = text[max(0, m.start() - 20):m.end() + 40].split("\n")[0]
                    if not _ONE_TIME_CUE.search(around):
                        continue
                apos = m.start(2 if i == 0 else 1)
                item = (label, v, "key" if label.startswith("key") else "fee")
                if apos in out_pos:  # the same amount again under a second label: keep the longer label, count it once
                    j = out_pos.index(apos)
                    if len(label) > len(out[j][0]):
                        out[j] = item
                    continue
                if any(o[0].split()[0] == label.split()[0] and o[1] == v for o in out):
                    continue  # the same fee quoted twice in the listing ("Admin $150 ... admin fee $150") is one fee
                out.append(item)
                out_pos.append(apos)
    return out


_DEPOSIT_MULT = re.compile(r"(?<![\w-])(?:security(?:[ \t]+deposit)?|(?:damage[ \t]+)?deposit)[ \t]*[:=\-]?[ \t]*(?:is[ \t]+|of[ \t]+)?(\d(?:\.\d{1,2})?)[ \t]*(?:x|\u00d7|times)(?:[ \t]*(?:the[ \t]+)?(?:monthly[ \t]+)?rent\b|[ \t]*1(?!\d|\.\d)(?![ \t]*(?:ba|bath))|(?![\w]))", re.I)


def _deposit_multiple(text: str) -> tuple[float, str] | None:
    """Cycle 21: a deposit given as a multiple of the rent: "Security 1.5x rent", "Deposit: 1x1" (one month), "deposit 2x rent". Returns (months, the phrase)."""
    m = _DEPOSIT_MULT.search(text)
    if not m:
        return None
    months = float(m.group(1))
    if not 0 < months <= 6:
        return None
    return months, " ".join(m.group(0).split())


def _background_check_each(text: str) -> float | None:
    """Cycle 21: "$25 background check each", "background check $25 per adult": a screening charge every adult pays besides the application fee."""
    m = re.search(r"\$\s?(\d{1,3}(?:\.\d\d)?)[ \t]*(?:background|screening|credit)[ \t]+(?:check|report)s?(?:[ \t]+fees?)?[ \t]*(?:each|apiece|per[ \t]+(?:adult|person|applicant|occupant))\b"
                  r"|\b(?:background|screening|credit)[ \t]+(?:check|report)s?(?:[ \t]+fees?)?[ \t:\-=]*\$\s?(\d{1,3}(?:\.\d\d)?)[ \t]*(?:each|apiece|per[ \t]+(?:adult|person|applicant|occupant))\b", text, re.I)
    if not m:
        return None
    v = float(m.group(1) or m.group(2))
    return v if v > 0 else None


def _bare_admin_fee(text: str) -> float | None:
    """Cycle 19: "Move-in specials: $99 admin", "Admin: $99": an admin amount with no word "fee" after it, a one-time move-in cost."""
    for m in re.finditer(r"(?<![\w$])\$\s?(\d{1,4}(?:\.\d\d)?)[ \t]+(?:lease[ \t]+)?admin(?:istrative|istration)?\b(?![ \t]*(?:fees?|/|per|each|off|waived|credit))"
                         r"|(?<![\w$])admin(?:istrative|istration)?[ \t]*[:\-=][ \t]*\$\s?(\d{1,4}(?:\.\d\d)?)(?![\d,])(?![ \t]*(?:/|per|each|off))", text, re.I):
        before = text[max(0, m.start() - 12):m.start()]
        if re.search(r"(?:waive[ds]?|no|free|zero|off|reduced?|save)[ \t]*$", before, re.I):
            continue
        v = float(m.group(1) or m.group(2))
        if v > 0:
            return v
    return None


def _deposit_credit_note(text: str, deposit: Any) -> str:
    """Cycle 19: "Deposit $2,350 conditional on credit approval", "Deposit: one month rent (conditional on credit approval)": the value is kept and
    one plain note says it depends on credit approval."""
    if not re.search(r"\bdeposits?\b[^.\n;]{0,70}?\b(?:conditional|contingent|dependent|depends?)[ \t]+(?:up)?on[ \t]+(?:your[ \t]+)?(?:credit|approval|screening)", text, re.I) \
            and not re.search(r"\bdeposits?\b[^.\n;]{0,70}?\b(?:may|might|could|can|will)[ \t]+(?:be[ \t]+|go[ \t]+)?(?:higher|more|up|increase\w*|vary|differ|change)\b[^.\n;]{0,40}\bcredit|"
                              r"\bdeposits?\b[^.\n;]{0,70}?\b(?:higher|more|varies|varying|depending|depends)[ \t]+(?:with|on|for|based[ \t]+on)[ \t]+(?:your[ \t]+)?(?:weak\w*[ \t]+|poor[ \t]+|lower[ \t]+)?credit", text, re.I):
        return ""
    if isinstance(deposit, (int, float)) and not isinstance(deposit, bool) and deposit > 0:
        return f"The {_usd(float(deposit))} deposit depends on credit approval, so it may be higher if your credit is weaker. Check with the landlord before you rely on it."
    return "The listing says the deposit depends on credit approval, so the amount you pay may differ. Check with the landlord what yours would be."


def _money_monthly_fees(text: str) -> list[float]:
    """Required extras charged every month ("amenity fee $25/mo", "$10/month trash")."""
    text = _strip_choice_internet(text)  # cycle 22: an optional internet package is a choice, never a monthly fee that counts
    found: list[float] = []
    label = r"(?:amenity|trash removal|garbage removal|trash|valet trash|trash valet|valet waste|pest(?: control)?|package|technology|tech|community|convenience|internet|cable|smart home)(?:\s*(?:fee|fees|charge|package|service))?"
    back = re.compile(r"^[^.\n;$]{0,14}?\b(?:billed|charged|passed)\s*(?:back|through|on)\b", re.I)
    for m in re.finditer(r"\b" + label + r"(?:[ \t]*\([^)\n$]{1,25}\))?(?:[ \t]+(?:is|are|costs?|runs?|will[ \t]+be)\b)?[ \t:\-=]{0,4}\$\s?(\d{1,4}(?:\.\d\d)?)\s*(?:/\s*mo(?:nth)?|per month|monthly|a month)", text, re.I):
        if re.match(r"(?:trash|internet|cable)", m.group(0), re.I) and (back.match(text[m.end():]) or re.match(r"[ \t,]*(?:is[ \t]+)?flat\b", text[m.end():], re.I)):
            continue  # a billed-back or flat-fee utility is the utilities estimate, never another monthly fee
        found.append(float(m.group(1)))
    for m in re.finditer(r"\b(?:valet[ -]trash|trash[ -]valet|valet[ -]waste)(?:\s*(?:fee|service|charge))?[ \t:\-=]{0,4}\$\s?(\d{1,4}(?:\.\d\d)?)(?![\d,]|\s*(?:/\s*mo|per month|monthly|a month|one[- ]time|deposit))", text, re.I):
        found.append(float(m.group(1)))  # "Valet trash $30": valet trash is always a monthly service
    for m in re.finditer(r"\$\s?(\d{1,4}(?:\.\d\d)?)\s*(?:/\s*mo(?:nth)?|per month|monthly|a month)\s*(?:for\s+)?[\"\u201c\u2018']?" + label + r"\b", text, re.I):
        if re.search(r"(?:trash|internet|cable)", m.group(0), re.I) and back.match(text[m.end():]):
            continue
        found.append(float(m.group(1)))
    for m in re.finditer(r"\$\s?(\d{1,4}(?:\.\d\d)?)[ \t]*" + label + r"[ \t]*(?:/\s*mo(?:nth)?\b|per month|monthly|a month|each month)", text, re.I):
        if re.match(r"\$\s?\d+(?:\.\d\d)?[ \t]*(?:trash|internet|cable)", m.group(0), re.I) and (back.match(text[m.end():]) or re.match(r"[ \t,]*(?:is[ \t]+)?flat\b", text[m.end():], re.I)):
            continue
        found.append(float(m.group(1)))  # "$175 amenity fee monthly"
    found.extend(_internet_amenity_fees(text))
    return found


_LIST_FEE_LABEL = re.compile(r"\b(?:amenit(?:y|ies)|community|trash|valet|pest|package|technology|tech|convenience|smart home|internet|wi-?fi|cable|lawn|landscap\w*|snow|pool|gym|fitness|clubhouse)\b", re.I)


def _monthly_list_fees(text: str) -> list[float]:
    """Cycle 17: a list under a "Monthly:" heading, where only some items carry the period ("Monthly: Pest control $5, Valet trash
    $25, Internet $60/mo required"). Every named fee in the list is a monthly fee. Internet counts only when the item says it is
    required; an item that says optional, billed back or per use is left to the other readers."""
    found: list[float] = []
    for m in re.finditer(r"\bmonthly(?:[ \t]+(?:fees?|charges|costs|extras))?[ \t]*[:\-][ \t]*([^\n]*)", text, re.I):
        body = re.split(r"\.(?=\s+[A-Z])|\.\s*$", m.group(1))[0]
        for item in re.split(r"[,;]|\band\b(?=[ \t]+[A-Za-z][A-Za-z \t-]*\$)", body):
            im = re.match(r"[ \t]*([A-Za-z][A-Za-z \t-]{1,30}?)[ \t]*:?[ \t]*\$\s?(\d{1,4})(?:\.\d\d)?(?![\d,])(.*)$", item)
            if not im or not _LIST_FEE_LABEL.search(im.group(1)):
                continue
            label, tail = im.group(1).lower(), im.group(3)
            if re.search(r"\b(?:optional|billed|passed|deposit|one[- ]time|set[- ]?up|install|per[ \t]+(?:use|load|visit)|/\s*(?:yr|year))", tail, re.I) \
                    or re.search(r"\b(?:parking|garage|pet|storage|locker)\b", label):
                continue
            if re.search(r"internet|wi-?fi|cable", label) and not re.search(r"\b(?:required|mandatory|must)\b", tail, re.I):
                continue
            found.append(float(im.group(2)))
    return found


_MONTHLY_AFTER = r"(?:/[ \t]*mo(?:nth)?\b|[ \t]+per[ \t]+month|[ \t]+a[ \t]+month|[ \t]*monthly\b|[ \t]+each[ \t]+month)"
_AMENITY_LABEL = r"(?:amenit(?:y|ies)|community|trash|valet[ -]trash|trash[ -]valet|pest(?: control)?|package|technology|tech|convenience|smart home)"


def _internet_amenity_fees(text: str) -> list[float]:
    """Cycle 16: mandatory internet and amenity fees in any wording. "Internet: Spectrum required, $55/mo mandatory", "Internet
    required, $60/mo", "Monthly amenity fee $25". Internet counts only when the same line says it is required or mandatory
    (an optional or tenant-arranged internet is not a fee). A "monthly ... fee" with an amount needs no other period."""
    found: list[float] = []
    for line in re.split(r"\n|;|\.(?=\s|$)|\s\|\s", text):  # cycle 25: a pipe ends an item ("INTERNET ... NOT INCLUDED | PARKING: $175/MO REQUIRED" is not an internet fee)
        if re.search(r"\b(?:internet|wi-?fi)\b", line, re.I) and re.search(r"\b(?:required|mandatory|must|compulsory)\b", line, re.I) \
                and not re.search(r"\bnot (?:mandatory|required)\b|\boptional\b|\bif (?:you )?(?:want|need|required)\b|\bavailable\b|\bset[s]? up\b|\bsets? it up\b", line, re.I):
            for m in re.finditer(r"\b(?:internet|wi-?fi)\b[^$\n]{0,45}?\$\s?(\d{1,4})(?:\.\d\d)?(?![\d,])" + _MONTHLY_AFTER, line, re.I):
                if re.search(r"\b(?:deposit|one[- ]time|set[- ]?up|install)", m.group(0), re.I):
                    continue
                found.append(float(m.group(1)))
                break
    for m in re.finditer(r"\bmonthly[ \t]+(?:" + _AMENITY_LABEL + r"(?:[ \t]*(?:fees?|charges?|package|service))?|(?:fee|charge)[ \t]+for[ \t]+(?:the[ \t]+)?" + _AMENITY_LABEL + r")[ \t:\-=]{0,4}\$\s?(\d{1,4})(?:\.\d\d)?(?![\d,]|[ \t]*(?:/[ \t]*(?:yr|year)|per[ \t]+year|one[- ]time|deposit))", text, re.I):
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
    noun = r"(?:storage(?:\s+(?:locker|unit|space|cage|room))?|(?<!package\s)(?<!parcel\s)(?<!mail\s)lockers?)"  # a package locker is a service fee, not storage
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
