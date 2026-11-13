"""CSV export of a search's places, and CSV import with a preview first.

Import is a plan: ``plan_import`` reads the rows and says, for each, what would happen (new, already saved, repeat in the
file, skipped, with the reason). It never writes to the database. ``apply_plan`` then does exactly that plan, so what
the preview showed is what happens. Cells that start with = + - @ are treated as text on the way out (no spreadsheet
formulas) and a row holding a formula on the way in is skipped. Nothing here uses the network.
"""
from __future__ import annotations

import csv
import io
import re
import secrets
import threading
import time
from typing import Any

from . import stages as st
from .store import PLACE_FIELDS, Store, normalize_address, normalize_unit, normalize_url

MAX_ROWS = 2000
MAX_COLUMNS = 80
HOLD_SECONDS = 30 * 60

# (heading in the file, place field). The first heading of each field is the one written on export.
EXPORT_COLUMNS: list[tuple[str, str]] = [
    ("Title", "title"), ("Address", "address"), ("Unit", "unit"), ("City", "city"), ("State", "state"), ("ZIP", "zip"),
    ("Link", "url"), ("Source", "source"), ("Stage", "stage"), ("Price", "price"), ("Beds", "beds"), ("Baths", "baths"),
    ("Square feet", "sqft"), ("Laundry", "laundry"), ("Parking", "parking"), ("Pets", "pets"), ("Dishwasher", "dishwasher"),
    ("Utilities included", "utilities_included"), ("Available from", "available_from"), ("Lease months", "lease_months"),
    ("Deposit", "deposit"), ("Application fee", "application_fee"), ("Parking cost", "parking_cost"), ("Pet rent", "pet_rent"),
    ("Pet fee", "pet_fee"), ("Utilities estimate", "utilities_estimate"), ("Other monthly fees", "other_monthly_fees"),
    ("Move in fees", "move_in_fees"), ("Broker fee", "broker_fee"), ("HOA", "hoa"), ("Property tax", "property_tax"),
    ("Insurance", "insurance"), ("Year built", "year_built"),
    ("Heaviest pet allowed (lb)", "pet_weight_limit"), ("Pet count limit", "pet_count_limit"), ("Breed rules", "pet_breed_note"),
    ("Pet deposit (refundable)", "pet_deposit"), ("Months of rent due before move-in", "months_up_front"),
    ("Utilities you pay", "tenant_pays"), ("Fenced yard", "fenced_yard"), ("Days on market", "days_on_market"),
    ("Special assessment", "special_assessment"), ("Who pays the special assessment", "special_assessment_payer"),
    ("Closing costs", "closing_costs"), ("Seller credit", "seller_credit"),
    ("Application fee charged per adult", "application_fee_per_adult"), ("Listing agent", "listing_agent"), ("Latitude", "lat"), ("Longitude", "lng"),
    ("Rating", "rating"), ("Fit score", "fit_score"), ("Red flags", "red_flags"), ("Notes", "notes"),
]
EXPORT_ONLY = {"fit_score", "red_flags"}  # written on export, never read back (the AI and the local check own them)

_COMPUTED_HEADS = {"true monthly cost", "cost per person per month", "score out of 100"}


def is_computed_header(heading: Any) -> bool:
    """A column our own export adds that the app works out itself (fit score, red flags, costs, commutes, each person's
    rating). Reading it back would only copy stale numbers, so import ignores it, quietly."""
    n = _norm_header(heading)
    return (n in _COMPUTED_HEADS or SYNONYMS.get(n) in EXPORT_ONLY or n in ("fit score", "red flags")
            or bool(re.match(r"^commute to .+ (minutes|way)( fastest way)?$", n)) or bool(re.search(r" s rating$", n)))


_EXTRA_NAMES: dict[str, tuple[str, ...]] = {
    "title": ("name", "property", "property name", "listing", "place", "building"),
    "address": ("street address", "street", "addr", "location", "address line 1"),
    "unit": ("apt", "apartment", "unit number", "unit no", "suite"),
    "city": ("town",), "state": ("st", "province"), "zip": ("zip code", "postal code", "postcode", "zipcode"),
    "url": ("url", "listing url", "website", "web address", "href", "listing link"),
    "source": ("site", "found on", "listing site"),
    "stage": ("status", "step"),
    "price": ("rent", "monthly rent", "asking price", "list price", "price per month", "cost", "rent per month", "asking rent"),
    "beds": ("bedrooms", "bed", "bd", "br", "bedroom"), "baths": ("bathrooms", "bath", "ba", "bathroom"),
    "sqft": ("sq ft", "squarefeet", "square footage", "size", "sf", "area"),
    "laundry": ("washer dryer", "w d", "laundry type"), "parking": ("parking type",),
    "pets": ("pet policy", "pets allowed", "pet friendly"), "dishwasher": ("has dishwasher",),
    "utilities_included": ("utilities", "included utilities", "utilities incl"),
    "available_from": ("available", "availability", "move in date", "movein", "available date", "date available"),
    "lease_months": ("lease length", "lease term", "term", "lease months"),
    "deposit": ("security deposit",), "application_fee": ("app fee", "application"),
    "parking_cost": ("parking fee", "parking rent"), "pet_rent": ("monthly pet rent", "pet fee monthly", "pet rent per month", "pet rent monthly", "pet rent mo", "pet monthly"),
    "pet_fee": ("one time pet fee", "pet fee one time", "pet fee onetime", "pet charge", "pet deposit fee"), "utilities_estimate": ("estimated utilities", "utility estimate", "utilities cost"),
    "months_up_front": ("months up front", "months due up front", "months rent up front", "months of rent up front"),
    "tenant_pays": ("tenant pays", "utilities tenant pays", "utilities you pay", "tenant utilities"),
    "other_monthly_fees": ("monthly fees", "other fees", "fees per month"),
    "hoa": ("hoa fee", "hoa dues", "hoa monthly"), "property_tax": ("tax", "taxes", "property taxes"),
    "year_built": ("built", "year"), "pet_weight_limit": ("pet weight limit", "weight limit", "pet weight", "max pet weight"),
    "pet_count_limit": ("pet limit", "max pets", "number of pets"), "pet_breed_note": ("breed restrictions", "breed rules", "breeds"),
    "fenced_yard": ("fenced", "fence", "fenced in yard"), "days_on_market": ("dom", "days listed"),
    "special_assessment_payer": ("special assessment paid by", "assessment payer"), "listing_agent": ("agent", "realtor"), "lat": ("latitude",), "lng": ("lon", "long", "longitude"),
    "rating": ("stars", "my rating"), "notes": ("note", "comments", "comment", "my notes"),
}


def _norm_header(text: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def _build_synonyms() -> dict[str, str]:
    table: dict[str, str] = {}
    for field, names in _EXTRA_NAMES.items():
        for name in names:
            table.setdefault(_norm_header(name), field)
    for heading, field in EXPORT_COLUMNS:
        table[_norm_header(heading)] = field
    for field in PLACE_FIELDS:
        table.setdefault(_norm_header(field), field)
    for dropped in ("listing_text", "photo_urls", "hidden", "is_sample", "ai_notes", "fit_notes", "lease_start", "lease_end"):
        table.pop(_norm_header(dropped), None)
    table["pet deposit"] = "pet_deposit"  # a plain "Pet deposit" is money that comes back, like the listing reader reads it ("Pet fee" is the one-time fee)
    return table


SYNONYMS = _build_synonyms()
# What a column may be matched to (a field you can fill from a spreadsheet), with the words shown in the picker.
FIELD_LABELS: dict[str, str] = {f: h for h, f in EXPORT_COLUMNS if f not in EXPORT_ONLY}


# ----------------------------------------------------------------------------- plain words for codes
# The file says "In the unit", not in_unit. Import takes these words and the old codes (the store knows the codes).
PLAIN_WORDS: dict[str, dict[str, str]] = {
    "laundry": {"in_unit": "In the unit", "in_building": "In the building", "hookups": "Hookups only", "none": "None"},
    "parking": {"garage": "Garage", "covered": "Covered", "lot": "Lot", "street": "Street", "none": "None"},
    "pets": {"cats": "Cats", "dogs": "Dogs", "both": "Cats and dogs", "none": "No pets"},
}
_FROM_PLAIN: dict[str, dict[str, str]] = {f: {_norm_header(w): code for code, w in words.items()} for f, words in PLAIN_WORDS.items()}


def _code_for(field: str, text: str) -> str:
    """The stored code for a plain word from our own export ("Hookups only" becomes hookups); anything else is passed on."""
    return _FROM_PLAIN.get(field, {}).get(_norm_header(text), text)


# ----------------------------------------------------------------------------- export
def _safe_cell(value: Any) -> Any:
    """Text that starts with = + - @ gets a leading apostrophe so a spreadsheet shows it as text, never runs it."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def _plain(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, float):
        return int(value) if value == int(value) else value
    return value


def _commute_for(place: dict[str, Any], anchor_id: Any) -> dict[str, Any] | None:
    """The commute the place page shows for this important place: the way of its commute criterion (your typed time wins),
    else the fastest known way. ``enrich.enrich_place`` works it out as ``commute_all``."""
    for c in place.get("commute_all") or []:
        if c.get("anchor_id") == anchor_id and c.get("minutes") is not None:
            return c
    times = [c for c in place.get("commutes") or [] if c.get("anchor_id") == anchor_id and c.get("minutes") is not None]
    return min(times, key=lambda c: c["minutes"]) if times else None


def _red_flags_text(place: dict[str, Any]) -> str:
    """The things to check the place page lists (the local check), then anything the AI wrote down."""
    bits = [str(f) for f in place.get("flags") or []]
    ai = str(place.get("red_flags") or "").strip()
    if ai and ai not in bits:
        bits.append(ai)
    return "; ".join(bits)


def _combined_rating(place: dict[str, Any], opinions: dict[str, Any]) -> Any:
    """Your own rating when you gave one, else the average of each person's rating."""
    if place.get("rating") is not None:
        return place["rating"]
    rated = [v for v in opinions.values() if v is not None]
    return round(sum(rated) / len(rated), 1) if rated else ""


def export_csv(places: list[dict[str, Any]], anchors: list[dict[str, Any]] | None = None, people: Any = 1,
               people_names: list[str] | None = None, opinions: dict[Any, dict[str, Any]] | None = None) -> str:
    """The places as CSV. Pass places from ``enrich.enrich_places`` (and the anchors) to add the true monthly cost, the cost per
    person (``people`` people share it), the score and each anchor's commute (the same minutes and way the place page shows).
    Fit score, Red flags and the per-person ratings come from the same checks the place page uses; ``people_names`` adds one
    "Name's rating" column each, filled from ``opinions`` ({place id: {name: rating}}). Places that are not enriched leave
    those cells empty. The computed columns are for reading in a spreadsheet and are never matched on import."""
    try:
        people = max(1, int(people or 1))
    except (TypeError, ValueError):
        people = 1
    anchors = anchors or []
    names = [str(n) for n in (people_names or [])]
    opinions = opinions or {}
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow([h for h, _ in EXPORT_COLUMNS] + [_safe_cell(f"{n}'s rating") for n in names]
                    + ["True monthly cost", "Cost per person per month", "Score out of 100"]
                    + [_safe_cell(h) for a in anchors for h in (f"Commute to {a.get('name', '')} (minutes)", f"Commute to {a.get('name', '')} (way)")])
    for p in places:
        mine = opinions.get(p.get("id")) or {}
        row = []
        for _, field in EXPORT_COLUMNS:
            v = p.get(field)
            if field in ("dishwasher", "fenced_yard", "application_fee_per_adult"):
                v = "" if v is None else ("yes" if v else "no")
            elif field in PLAIN_WORDS:
                v = PLAIN_WORDS[field].get(str(v), v) if v else ""
            elif field == "fit_score":
                v = p.get("score_total") if p.get("score_total") is not None else v
            elif field == "red_flags":
                v = _red_flags_text(p)
            elif field == "rating":
                v = _combined_rating(p, mine)
            row.append(_safe_cell(_plain(v)))
        row += [_plain(mine.get(n)) for n in names]
        total = p.get("cost_total")
        row.append(_plain(total))
        split = max(1, int(p.get("people") or people)) if p.get("cost") else people  # the adults, when the search names them
        row.append("" if total is None else round(float(total) / split, 2))
        row.append(_plain(p.get("score_total")))
        for a in anchors:
            c = _commute_for(p, a.get("id"))
            row.append(round(c["minutes"]) if c else "")
            row.append(_safe_cell(_way_text(c)) if c else "")
        writer.writerow(row)
    return out.getvalue()


def _way_text(c: dict[str, Any]) -> str:
    mode = str(c.get("mode") or "")
    return mode + (" (your time)" if c.get("source") == "you" else " (estimate)" if c.get("source") == "estimate" else "")


# ----------------------------------------------------------------------------- reading a file
class CsvProblem(ValueError):
    """A file that can't be used, in plain words."""


def read_table(data: bytes) -> tuple[list[str], list[list[str]]]:
    """``(headings, rows)`` from the bytes of a CSV file (comma, semicolon or tab separated; UTF-8 or Windows text)."""
    if not data.strip():
        raise CsvProblem("That file is empty.")
    if data[:2] == b"PK":
        raise CsvProblem("That looks like an Excel file. In Excel or Numbers choose Save As or Export, then CSV (a spreadsheet file), and upload that.")
    if b"\x00" in data[:4096]:
        raise CsvProblem("That doesn't look like a spreadsheet (CSV) file. Save your spreadsheet as CSV and try again.")
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("cp1252", errors="replace")
    sample = text[:4000]
    first_line = sample.splitlines()[0] if sample.splitlines() else ""
    delimiter = max((",", ";", "\t"), key=lambda d: first_line.count(d))
    if first_line.count(delimiter) == 0:
        delimiter = ","
    try:
        rows = [r for r in csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)]
    except csv.Error as exc:
        raise CsvProblem(f"That file couldn't be read as a spreadsheet (CSV) ({exc}).") from None
    if len(rows) < 2:
        raise CsvProblem("The file needs a heading row and at least one place under it.")
    headers = [h.strip() for h in rows[0]]
    if len(headers) > MAX_COLUMNS:
        raise CsvProblem(f"That file has {len(headers)} columns. The most I read is {MAX_COLUMNS}.")
    body = rows[1:]
    if len(body) > MAX_ROWS:
        raise CsvProblem(f"That file has {len(body):,} rows. The most I import at once is {MAX_ROWS:,}. Split it and import in parts.")
    return headers, body


def match_columns(headers: list[str]) -> dict[int, str]:
    """Guess which place field each column holds: ``{column index: field}``. Each field is used once."""
    mapping: dict[int, str] = {}
    used: set[str] = set()
    for i, head in enumerate(headers):
        field = SYNONYMS.get(_norm_header(head))
        if field and field not in used and field not in EXPORT_ONLY and (field in PLACE_FIELDS or field == "stage"):
            mapping[i] = field
            used.add(field)
    return mapping


# ----------------------------------------------------------------------------- the plan
_TOTAL = re.compile(r"^\s*(total|totals|average|avg|sum|mean|median|count)\b", re.I)
_UNSET = {"", "n/a", "na", "none given", "-", "--", "tbd", "?"}


def _cell(row: list[str], i: int) -> str:
    return row[i].strip() if i < len(row) else ""


_NUMBER_EXAMPLES = {"price": "1450", "beds": "2", "baths": "1.5", "sqft": "850", "deposit": "1450", "application_fee": "50",
                    "parking_cost": "75", "pet_rent": "35", "pet_fee": "300", "utilities_estimate": "90", "other_monthly_fees": "25",
                    "move_in_fees": "150", "broker_fee": "1450", "hoa": "250", "property_tax": "3600", "insurance": "1200",
                    "year_built": "1998", "lease_months": "12", "rating": "4", "lat": "40.11", "lng": "-88.24"}


def _cell_problem(field: str, exc: Exception) -> str:
    """A plain note for one bad cell, naming the column by its label ("Price needs to be a number, like 1450")."""
    label = FIELD_LABELS.get(field, field)
    if "needs to be a number" in str(exc):
        return f"{label} needs to be a number, like {_NUMBER_EXAMPLES.get(field, '12')}. It is left empty."
    return f"{label}: {str(exc).rstrip('.')}. It is left empty."


def plan_import(store: Store, search_id: int, headers: list[str], rows: list[list[str]], mapping: dict[int, str]) -> list[dict[str, Any]]:
    """What importing would do, row by row. Writes nothing.

    Each item: ``row`` (the row number as a spreadsheet shows it, heading = 1), ``status`` (new, match, repeat, skip),
    ``reason`` (plain words, for skip and repeat), ``values`` (cleaned fields), ``stage``, ``warnings``, ``label``,
    ``existing`` (the place a match would fill in)."""
    mode = store.get_search(search_id)["mode"]
    plan: list[dict[str, Any]] = []
    seen: dict[tuple, int] = {}
    for n, row in enumerate(rows, start=2):
        item: dict[str, Any] = {"row": n, "status": "new", "reason": "", "values": {}, "stage": None, "warnings": [], "label": "", "existing": None}
        plan.append(item)
        if not any(c.strip() for c in row):
            item.update(status="skip", reason="The row is blank.", blank=True)
            continue
        raw = {field: _cell(row, i) for i, field in mapping.items()}
        mapped_cells = [c for c in raw.values() if c]
        if not mapped_cells:
            item.update(status="skip", reason="None of the matched columns has anything in this row.")
            continue
        first = next((c for c in (raw.get("title"), raw.get("address"), mapped_cells[0]) if c), "")
        if _TOTAL.match(first) and not raw.get("url") and not raw.get("address"):
            item.update(status="skip", reason="It looks like a totals or average row.")
            continue
        if any(c[:1] == "=" for c in mapped_cells):
            item.update(status="skip", reason="A cell holds a spreadsheet formula, not a value. Save the sheet with values (not formulas) and import again.")
            continue
        values: dict[str, Any] = {}
        for field, text in raw.items():
            if field == "stage" or text.lower() in _UNSET:
                continue
            try:
                values.update(store._clean_place({field: _code_for(field, text)}, partial=True))  # checks one cell; touches no data
            except ValueError as exc:
                item["warnings"].append(_cell_problem(field, exc))
        if raw.get("stage"):
            norm = st.normalize_stage(mode, raw["stage"])
            if norm is None:
                item["warnings"].append(f"Stage \"{raw['stage'][:40]}\" isn't one of this search's stages, so it starts at {st.FIRST_STAGE}.")
            else:
                item["stage"] = norm
        bad_price = raw.get("price", "") and raw["price"].lower() not in _UNSET and "price" not in values
        if bad_price and not (values.get("title") or values.get("address")):
            item.update(status="skip", reason=f"It has no title or address, and its price (\"{raw['price'][:30]}\") isn't a number.")
            continue
        if not (values.get("title") or values.get("address") or values.get("url")):
            item.update(status="skip", reason="It has no title, address or link, and a place needs at least one.")
            continue
        item["values"] = {k: v for k, v in values.items() if v not in ("", None)}
        item["label"] = item["values"].get("title") or item["values"].get("address") or item["values"].get("url") or ""
        keys = []
        if values.get("url"):
            keys.append(("u", normalize_url(values["url"])))
        if normalize_address(values.get("address")):
            keys.append(("a", normalize_address(values["address"]), normalize_unit(values.get("unit"))))
        earlier = next((seen[k] for k in keys if k in seen), None)
        if earlier is not None:
            item.update(status="repeat", reason=f"It repeats row {earlier} in this file, so it is left out.")
            continue
        for k in keys:
            seen[k] = n
        dup = store.find_duplicate(search_id, url=values.get("url"), address=values.get("address"), unit=values.get("unit"))
        if dup is not None:
            item.update(status="match", existing={"id": dup["id"], "title": dup["title"]})
    return plan


def summarize(plan: list[dict[str, Any]]) -> dict[str, int]:
    """Counts of places, not lines: blank rows are not counted at all. ``places`` is every row that holds a place
    (new, already saved, repeated or skipped for a reason); ``blank`` is the empty rows left out silently."""
    counts = {"new": 0, "match": 0, "repeat": 0, "skip": 0, "blank": 0}
    for item in plan:
        if item.get("blank"):
            counts["blank"] += 1
        else:
            counts[item["status"]] += 1
    counts["places"] = counts["new"] + counts["match"] + counts["repeat"] + counts["skip"]
    return counts


def left_out_text(plan: list[dict[str, Any]], limit: int = 3) -> str:
    """Why rows were left out, in plain words ("Row 4: It repeats row 2 in this file"), for the summary after an import."""
    why = [f"row {i['row']}: {i['reason'].rstrip('.')}" for i in plan if i["status"] in ("repeat", "skip") and not i.get("blank")]
    if not why:
        return ""
    shown = "; ".join(why[:limit]) + (f"; and {len(why) - limit} more" if len(why) > limit else "")
    return f"{len(why)} row{'s' if len(why) != 1 else ''} left out ({shown})."


def apply_plan(store: Store, search_id: int, plan: list[dict[str, Any]]) -> dict[str, Any]:
    """Do the plan. New rows are added, matches only fill in empty fields (the store's rule), the rest are left out."""
    added = filled = 0
    failed: list[str] = []
    for item in plan:
        if item["status"] not in ("new", "match"):
            continue
        try:
            _, created = store.add_place(by="you", search_id=search_id, stage=item["stage"], **item["values"])
        except ValueError as exc:
            failed.append(f"Row {item['row']}: {exc}")
            continue
        if created:
            added += 1
        else:
            filled += 1
    return {"added": added, "filled": filled, "failed": failed}


# ----------------------------------------------------------------------------- the held upload
_held: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()
_now = time.monotonic


def hold(search_id: int, filename: str, headers: list[str], rows: list[list[str]]) -> str:
    """Keep an uploaded file in memory (never on disk) for 30 minutes so the preview can be changed and then applied."""
    token = secrets.token_urlsafe(16)
    with _lock:
        for key in [k for k, v in _held.items() if v["until"] < _now()]:
            del _held[key]
        while len(_held) >= 5:
            del _held[min(_held, key=lambda k: _held[k]["until"])]
        _held[token] = {"until": _now() + HOLD_SECONDS, "search_id": search_id, "filename": filename, "headers": headers, "rows": rows}
    return token


def held(token: str) -> dict[str, Any] | None:
    with _lock:
        item = _held.get(token)
        if item is None or item["until"] < _now():
            _held.pop(token, None)
            return None
        return item


def release(token: str) -> None:
    with _lock:
        _held.pop(token, None)
