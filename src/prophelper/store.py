"""The database: every place you are looking at, where it stands, who you talked to and what is coming up.

One SQLite file in WAL mode, shared by the app window and the MCP server (two processes). Schema changes are
append-only migrations tracked in ``PRAGMA user_version``.

Conventions (they hold for every method):

* Timestamps are UTC ISO 8601 strings with seconds, made by :func:`now_iso`. Anything a caller passes in goes through
  :func:`to_utc_iso`, which also accepts a plain date or a time with no zone (read as this computer's local time).
  Plain dates (``move_in``, ``available_from``...) are ``YYYY-MM-DD``. Money is US dollars, distances are miles.
* Rows come back as plain ``dict``s. Text columns are never ``None`` (empty string instead); numbers and dates that
  are not set are ``None``. A place's ``photo_urls`` is a list, a criterion's ``target`` is a dict.
* Methods raise :class:`NotFound` for an id that does not exist and ``ValueError`` (plain words, fit to show the user)
  for a bad value. Only known fields are written; unknown keyword arguments are ignored.
* The AI never deletes: the ``delete_*``, ``remove_*`` and archive methods exist for the app window only. The MCP
  layer opens its Store with :meth:`Store.enable_no_delete`.
* ``by`` / ``source`` on a write says who made the change: ``"you"`` or ``"ai"``. With ``by="ai"``: the user's
  ``notes`` and ``rating`` are never touched (text meant for ``notes`` goes to ``ai_notes``), a stage moves only
  forward or to Passed, and every value the AI replaced is written to the timeline so it can be put back.
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from . import stages as st

# --------------------------------------------------------------------------- vocabulary
EVENT_KINDS: tuple[str, ...] = ("note", "stage", "call", "email", "text", "tour", "document", "ai")
EVENT_SOURCES: tuple[str, ...] = ("you", "ai")
CONTACT_ROLES: tuple[str, ...] = ("landlord", "property manager", "leasing agent", "buyer's agent", "seller's agent", "other",
                                  "lender", "inspector", "title or closing", "seller")
CONTACT_LOG_KINDS: tuple[str, ...] = ("call", "email", "text", "in person")
DIRECTIONS: tuple[str, ...] = ("out", "in")
TOUR_STATUSES: tuple[str, ...] = ("booked", "done", "cancelled")
TOUR_ITEMS: tuple[str, ...] = ("water pressure", "hot water", "cell signal", "noise", "smells", "light", "appliances",
                               "laundry", "storage", "parking", "neighbors")
TOUR_STATES: tuple[str, ...] = ("ok", "issue", "")
DOCUMENT_KINDS: tuple[str, ...] = ("lease", "application", "disclosure", "inspection", "photo", "other",
                                   "offer", "purchase contract", "appraisal", "loan estimate")
DRAFT_KINDS: tuple[str, ...] = ("fit score", "red flags", "tour questions", "message")
CRITERION_KINDS: tuple[str, ...] = ("price", "beds", "baths", "sqft", "commute", "laundry", "dishwasher", "parking",
                                    "pets", "fenced_yard", "newer", "custom")
LAUNDRY_VALUES = ("in_unit", "in_building", "hookups", "none")
PARKING_VALUES = ("garage", "covered", "lot", "street", "none")
PETS_VALUES = ("cats", "dogs", "both", "none")
COMMUTE_MODES = ("walk", "bike", "transit", "drive")
COMMUTE_SOURCES = ("estimate", "you", "ai")
DEFAULT_CHECKLIST: tuple[tuple[str, str], ...] = (
    ("Photo ID ready", ""), ("Proof of income", "Pay stubs or an offer letter"),
    ("Last two landlord references", ""), ("Rental history", ""), ("Guarantor details", ""),
    ("Credit report", ""), ("Renter's insurance quote", ""), ("Pet records", ""),
)
DEFAULT_SETTINGS: dict[str, str] = {
    "ai_model": "claude-sonnet-5-5", "follow_up_days": "3", "map_tiles": "0", "geocode": "0", "show_photos": "0",
    "strict_scraping": "0", "down_payment_pct": "20", "mortgage_rate": "6.5", "loan_years": "30", "pmi_rate_pct": "0.5",
    "closing_cost_pct": "3",
}
DEFAULT_CHECKLIST_BUY: tuple[tuple[str, str], ...] = (
    ("Mortgage pre-approval letter", "From your lender. Sellers expect one with an offer"),
    ("Proof of funds", "Bank statements for the down payment and closing costs"),
    ("Inspector picked", "Someone to call as soon as an offer is accepted"),
    ("Homeowner's insurance quote", "Your lender will ask for proof of insurance"),
    ("Title company or closing attorney", ""), ("Buyer's agent chosen", ""),
    ("Recent pay stubs and tax returns", "Your lender will ask for these"), ("Photo ID ready", ""),
)
PLACE_DATE_KINDS_RENT: tuple[str, ...] = ("application_deadline", "application_sent", "move_in", "other")
PLACE_DATE_KINDS_BUY: tuple[str, ...] = ("offer_deadline", "inspection", "appraisal", "financing_deadline", "closing", "other")
PLACE_DATE_LABELS: dict[str, str] = {
    "application_deadline": "Application deadline", "application_sent": "Application sent", "move_in": "Move-in",
    "offer_deadline": "Offer deadline", "inspection": "Inspection", "appraisal": "Appraisal",
    "financing_deadline": "Financing deadline", "closing": "Closing", "other": "Other date",
}
MAX_PEOPLE = 20
STRICT_ADDS_PER_CALL = 5
STRICT_ADDS_PER_HOUR = 20
UPLOAD_LIMIT_BYTES = 20 * 1024 * 1024
PERSON_NAME_MAX = 40
OPINION_NOTE_MAX = 500

PLACE_TEXT = ("title", "address", "unit", "city", "state", "zip", "url", "source", "listing_text", "laundry", "parking",
              "pets", "utilities_included", "available_from", "lease_start", "lease_end", "notes", "ai_notes",
              "fit_notes", "red_flags", "pet_breed_note", "special_assessment_payer", "listing_agent", "tenant_pays")
PLACE_REAL = ("lat", "lng", "price", "beds", "baths", "parking_cost", "pet_rent", "pet_fee", "utilities_estimate", "pet_weight_limit", "pet_deposit",
              "deposit", "application_fee", "other_monthly_fees", "move_in_fees", "broker_fee", "hoa", "property_tax",
              "insurance", "special_assessment", "closing_costs")
PLACE_INT = ("sqft", "year_built", "lease_months", "rating", "fit_score", "pet_count_limit", "days_on_market", "months_up_front")
TENANT_PAYS_CHOICES = ("electric", "gas", "water", "trash", "internet", "heat")
PLACE_DATES = ("available_from", "lease_start", "lease_end")
PLACE_FIELDS: tuple[str, ...] = (PLACE_TEXT + PLACE_REAL + PLACE_INT + ("photo_urls", "dishwasher", "fenced_yard", "hidden", "is_sample"))
# What a form or the AI may set (stage goes through move_stage).
PLACE_EDITABLE: tuple[str, ...] = tuple(f for f in PLACE_FIELDS if f not in ("is_sample",))
TEXT_LIMITS = {"title": 300, "address": 300, "unit": 40, "city": 120, "state": 60, "zip": 20, "url": 2000, "source": 120,
               "listing_text": 200_000, "utilities_included": 300, "notes": 50_000, "ai_notes": 50_000,
               "fit_notes": 20_000, "red_flags": 5_000, "laundry": 20, "parking": 20, "pets": 20, "pet_breed_note": 300, "tenant_pays": 80}
PHOTOS_MAX = 30
AI_PROTECTED = ("notes", "rating", "hidden", "is_sample")  # fields an AI update never writes
AI_EVENT_TEXT_MAX = 2000
AI_NOTES_MAX = 50_000

# --------------------------------------------------------------------------- schema
_SCHEMA_V1 = """
CREATE TABLE searches (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'rent' CHECK (mode IN ('rent', 'buy')),
    area TEXT NOT NULL DEFAULT '',
    move_in TEXT,
    target_close TEXT,
    budget_max REAL,
    notes TEXT NOT NULL DEFAULT '',
    hide_dealbreakers INTEGER NOT NULL DEFAULT 1,
    is_sample INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    archived_at TEXT
);
CREATE TABLE criteria (
    id INTEGER PRIMARY KEY,
    search_id INTEGER NOT NULL REFERENCES searches(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    weight REAL NOT NULL DEFAULT 10,
    dealbreaker INTEGER NOT NULL DEFAULT 0,
    target TEXT NOT NULL DEFAULT '{}',
    sort_order INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_criteria_search ON criteria(search_id, sort_order);
CREATE TABLE anchors (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    address TEXT NOT NULL DEFAULT '',
    lat REAL,
    lng REAL,
    is_sample INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE places (
    id INTEGER PRIMARY KEY,
    search_id INTEGER NOT NULL REFERENCES searches(id) ON DELETE CASCADE,
    title TEXT NOT NULL DEFAULT '',
    address TEXT NOT NULL DEFAULT '',
    unit TEXT NOT NULL DEFAULT '',
    city TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL DEFAULT '',
    zip TEXT NOT NULL DEFAULT '',
    lat REAL,
    lng REAL,
    url TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    listing_text TEXT NOT NULL DEFAULT '',
    photo_urls TEXT NOT NULL DEFAULT '[]',
    price REAL,
    beds REAL,
    baths REAL,
    sqft INTEGER,
    laundry TEXT NOT NULL DEFAULT '',
    dishwasher INTEGER,
    parking TEXT NOT NULL DEFAULT '',
    parking_cost REAL,
    pets TEXT NOT NULL DEFAULT '',
    pet_rent REAL,
    pet_fee REAL,
    utilities_included TEXT NOT NULL DEFAULT '',
    utilities_estimate REAL,
    year_built INTEGER,
    available_from TEXT,
    lease_start TEXT,
    lease_end TEXT,
    lease_months INTEGER,
    deposit REAL,
    application_fee REAL,
    other_monthly_fees REAL,
    move_in_fees REAL,
    broker_fee REAL,
    hoa REAL,
    property_tax REAL,
    insurance REAL,
    stage TEXT NOT NULL DEFAULT 'Saved',
    stage_changed_at TEXT,
    rating INTEGER,
    notes TEXT NOT NULL DEFAULT '',
    ai_notes TEXT NOT NULL DEFAULT '',
    fit_score INTEGER,
    fit_notes TEXT NOT NULL DEFAULT '',
    red_flags TEXT NOT NULL DEFAULT '',
    hidden INTEGER NOT NULL DEFAULT 0,
    seen_at TEXT,
    is_sample INTEGER NOT NULL DEFAULT 0,
    archived_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_places_search ON places(search_id, stage);
CREATE UNIQUE INDEX idx_places_url ON places(url) WHERE url != '';
CREATE TABLE commutes (
    place_id INTEGER NOT NULL REFERENCES places(id) ON DELETE CASCADE,
    anchor_id INTEGER NOT NULL REFERENCES anchors(id) ON DELETE CASCADE,
    mode TEXT NOT NULL CHECK (mode IN ('walk', 'bike', 'transit', 'drive')),
    minutes REAL NOT NULL,
    source TEXT NOT NULL DEFAULT 'you' CHECK (source IN ('estimate', 'you', 'ai')),
    updated_at TEXT NOT NULL,
    UNIQUE (place_id, anchor_id, mode)
);
CREATE TABLE events (
    id INTEGER PRIMARY KEY,
    place_id INTEGER NOT NULL REFERENCES places(id) ON DELETE CASCADE,
    kind TEXT NOT NULL DEFAULT 'note',
    body TEXT NOT NULL DEFAULT '',
    at TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'you'
);
CREATE INDEX idx_events_place ON events(place_id, at);
CREATE TABLE tours (
    id INTEGER PRIMARY KEY,
    place_id INTEGER NOT NULL REFERENCES places(id) ON DELETE CASCADE,
    starts_at TEXT NOT NULL,
    duration_minutes INTEGER NOT NULL DEFAULT 30,
    with_whom TEXT NOT NULL DEFAULT '',
    where_note TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'booked' CHECK (status IN ('booked', 'done', 'cancelled')),
    checklist TEXT NOT NULL DEFAULT '{}',
    rating INTEGER,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX idx_tours_place ON tours(place_id, starts_at);
CREATE TABLE contacts (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'other',
    company TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    is_sample INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE place_contacts (
    place_id INTEGER NOT NULL REFERENCES places(id) ON DELETE CASCADE,
    contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    PRIMARY KEY (place_id, contact_id)
);
CREATE TABLE contact_log (
    id INTEGER PRIMARY KEY,
    contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    place_id INTEGER REFERENCES places(id) ON DELETE SET NULL,
    at TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'email',
    body TEXT NOT NULL DEFAULT '',
    direction TEXT NOT NULL DEFAULT 'out' CHECK (direction IN ('out', 'in'))
);
CREATE INDEX idx_contact_log ON contact_log(contact_id, at);
CREATE TABLE documents (
    id INTEGER PRIMARY KEY,
    place_id INTEGER NOT NULL REFERENCES places(id) ON DELETE CASCADE,
    stored_name TEXT NOT NULL,
    original_name TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'other',
    size INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX idx_documents_place ON documents(place_id);
CREATE TABLE checklist_items (
    id INTEGER PRIMARY KEY,
    label TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    done INTEGER NOT NULL DEFAULT 0,
    sort_order INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE ai_drafts (
    id INTEGER PRIMARY KEY,
    place_id INTEGER NOT NULL REFERENCES places(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX idx_drafts_place ON ai_drafts(place_id, created_at);
CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);
-- Not in DESIGN section 3: the 0 to 5 scores a person gives a "custom" criterion for one place.
CREATE TABLE custom_scores (
    place_id INTEGER NOT NULL REFERENCES places(id) ON DELETE CASCADE,
    criterion_id INTEGER NOT NULL REFERENCES criteria(id) ON DELETE CASCADE,
    score REAL NOT NULL,
    PRIMARY KEY (place_id, criterion_id)
);
"""

# Append-only: never edit an entry once released, add a new one at the end.
# Step 2: key dates per place (application deadline, inspection, closing...). Self-contained so it can be renumbered.
_SCHEMA_V2_PLACE_DATES = """
CREATE TABLE IF NOT EXISTS place_dates (
    id INTEGER PRIMARY KEY,
    place_id INTEGER NOT NULL REFERENCES places(id) ON DELETE CASCADE,
    kind TEXT NOT NULL DEFAULT 'other',
    date TEXT NOT NULL,
    time TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_place_dates_place ON place_dates(place_id, date);
"""

# How many people share the cost of a place (rent split, or a household buying). One self-contained step.
_MIGRATION_PEOPLE = "ALTER TABLE searches ADD COLUMN people INTEGER NOT NULL DEFAULT 1;"

# Pet limits on places, "your pets" on searches, and the per-place application checklist. One self-contained step.
_MIGRATION_PETS_APPLY = """
ALTER TABLE places ADD COLUMN pet_weight_limit REAL;
ALTER TABLE places ADD COLUMN pet_count_limit INTEGER;
ALTER TABLE places ADD COLUMN pet_breed_note TEXT NOT NULL DEFAULT '';
ALTER TABLE places ADD COLUMN pet_deposit REAL;
ALTER TABLE places ADD COLUMN fenced_yard INTEGER;
ALTER TABLE searches ADD COLUMN pet_kind TEXT NOT NULL DEFAULT '';
ALTER TABLE searches ADD COLUMN pet_weight REAL;
ALTER TABLE searches ADD COLUMN pet_count INTEGER;
CREATE TABLE IF NOT EXISTS place_checklist (
    place_id INTEGER NOT NULL REFERENCES places(id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES checklist_items(id) ON DELETE CASCADE,
    done_at TEXT NOT NULL,
    PRIMARY KEY (place_id, item_id)
);
"""

# Names for the people sharing a search, and each person's own rating and note per place. One self-contained step.
_MIGRATION_OPINIONS = """
ALTER TABLE searches ADD COLUMN people_names TEXT NOT NULL DEFAULT '[]';
CREATE TABLE IF NOT EXISTS place_opinions (
    place_id INTEGER NOT NULL REFERENCES places(id) ON DELETE CASCADE,
    person TEXT NOT NULL,
    rating INTEGER CHECK (rating IS NULL OR rating BETWEEN 1 AND 5),
    note TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (place_id, person)
);
"""

# Buyer facts on a place (days on market, one-time special assessment and who pays it, closing costs, listing agent).
# One self-contained step so it can be renumbered at merge time.
_MIGRATION_BUYER_FIELDS = """
ALTER TABLE places ADD COLUMN days_on_market INTEGER;
ALTER TABLE places ADD COLUMN special_assessment REAL;
ALTER TABLE places ADD COLUMN special_assessment_payer TEXT NOT NULL DEFAULT '';
ALTER TABLE places ADD COLUMN closing_costs REAL;
ALTER TABLE places ADD COLUMN listing_agent TEXT NOT NULL DEFAULT '';
"""

# Rent due before move-in (months) and the utilities the renter pays. One self-contained step so it can be renumbered at merge time.
_MIGRATION_RENT_UPFRONT = """
ALTER TABLE places ADD COLUMN months_up_front INTEGER;
ALTER TABLE places ADD COLUMN tenant_pays TEXT NOT NULL DEFAULT '';
"""

_MIGRATIONS: list[str] = [_SCHEMA_V1, _SCHEMA_V2_PLACE_DATES, _MIGRATION_PEOPLE, _MIGRATION_PETS_APPLY, _MIGRATION_OPINIONS, _MIGRATION_BUYER_FIELDS, _MIGRATION_RENT_UPFRONT]


class NotFound(LookupError):
    """The id asked for does not exist (a page turns this into a 404, a tool into a friendly message)."""


# Stages an AI may never move a place into: the won stages and Under contract (they commit the user to something).
AI_NEVER_ENTERS: tuple[str, ...] = (*st.WON_STAGES, "Under contract")


def ai_move_problem(mode: str, old: str, new: str, *, one_step: bool = True) -> str:
    """Why an AI may not move a place from ``old`` to ``new``, or "" when it may. Passed is always allowed from an
    open stage; otherwise one stage forward, never into AI_NEVER_ENTERS."""
    if new == old or (new == st.PASSED and old != st.PASSED):
        return ""
    if old == st.PASSED:
        return f"An AI can only move a place forward or to Passed, so {old} can't go back to {new}. Ask the user to move it in the app."
    if new in AI_NEVER_ENTERS:
        return f"An AI can't move a place to {new}. Ask the user to do this in the app."
    if not st.is_forward(mode, old, new):
        return f"An AI can only move a place forward or to Passed, so {old} can't go back to {new}. Ask the user to move it in the app."
    if one_step:
        stages = st.stages_for(mode)
        nxt = stages[st.stage_index(mode, old) + 1]
        if new != nxt:
            return f"An AI moves a place one stage at a time, so from {old} the next stage is {nxt}, not {new}. Move it to {nxt} first, or ask the user."
    return ""


class StageRuleError(ValueError):
    """A stage move the rules do not allow (an AI moving a place backward, or a stage the mode does not have)."""


# --------------------------------------------------------------------------- time helpers
def now_iso() -> str:
    """The one clock: now in UTC, ISO 8601, whole seconds."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def today_local() -> str:
    """Today's date on this computer's clock, ``YYYY-MM-DD``."""
    return date.today().isoformat()


def parse_iso(value: str | None) -> datetime | None:
    """A stored timestamp as an aware datetime (a plain date is midnight local time), or None."""
    v = (value or "").strip()
    if not v:
        return None
    try:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=_local_tz())


def calendar_days_ago(value: str | datetime | None, now: datetime | None = None) -> int | None:
    """Whole calendar days between a stored time and now, on this computer's clock (written 11 pm yesterday is 1 day
    ago). The one count Today, Contacts and the place page all use. None when the time can't be read."""
    dt = value if isinstance(value, datetime) else parse_iso(value)
    if dt is None:
        return None
    ref = (now or datetime.now(timezone.utc)).astimezone().date()
    return (ref - dt.astimezone().date()).days


def _local_tz() -> timezone:
    return datetime.now().astimezone().tzinfo  # type: ignore[return-value]


def to_utc_iso(value: Any) -> str:
    """A UTC ISO timestamp from a date, a datetime or text. A time with no zone is read as this computer's local time;
    a plain date is that day at 9:00 local. Raises ValueError for text that is not a date or time."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime(value.year, value.month, value.day, 9, 0)
    else:
        text = str(value or "").strip()
        if not text:
            raise ValueError("That needs a date and time.")
        try:
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
                dt = datetime.fromisoformat(text + "T09:00:00")
            else:
                dt = datetime.fromisoformat(text.replace("Z", "+00:00").replace(" ", "T", 1))
        except ValueError:
            raise ValueError(f"'{text}' isn't a date and time I can read. Use a form like 2027-07-31 14:30.") from None
    if dt.tzinfo is None:
        dt = dt.astimezone()  # naive means this computer's local time
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def clean_date(value: Any, what: str = "date") -> str | None:
    """``YYYY-MM-DD`` or None for blank. Raises ValueError for anything else."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        raise ValueError(f"The {what} needs to be a date like 2027-07-31.") from None


# --------------------------------------------------------------------------- value helpers
def _text(value: Any, limit: int = 1000) -> str:
    return ("" if value is None else str(value)).strip()[:limit]


def to_number(value: Any, what: str = "number") -> float | None:
    """A number from '$1,450', 1450 or '1.5'; None for blank. Raises ValueError for text that is not a number."""
    if value is None or isinstance(value, bool):
        if isinstance(value, bool):
            raise ValueError(f"The {what} needs to be a number.")
        return None
    if isinstance(value, (int, float)):
        out = float(value)
    else:
        text = str(value).strip().replace("$", "").replace(",", "").replace(" ", "")
        if not text:
            return None
        try:
            out = float(text)
        except ValueError:
            raise ValueError(f"The {what} needs to be a number, like 1450.") from None
    if out != out or out in (float("inf"), float("-inf")):
        raise ValueError(f"The {what} needs to be a number.")
    return out


def _tidy_num(x: Any) -> Any:
    if isinstance(x, float) and x == int(x) and abs(x) < 1e12:
        return int(x)
    return x


_ENUM_ALIASES: dict[str, dict[str, str]] = {
    "laundry": {"in unit": "in_unit", "in-unit": "in_unit", "in_unit": "in_unit", "inunit": "in_unit", "unit": "in_unit",
                "washer dryer": "in_unit", "washer/dryer": "in_unit", "w/d": "in_unit", "in unit washer dryer": "in_unit",
                "in unit washer/dryer": "in_unit", "washer and dryer": "in_unit",
                "in building": "in_building", "in-building": "in_building", "in_building": "in_building",
                "building": "in_building", "shared": "in_building", "on site": "in_building", "on-site": "in_building",
                "laundry room": "in_building", "common": "in_building", "community": "in_building",
                "hookups": "hookups", "hookup": "hookups", "hook-ups": "hookups", "hook ups": "hookups", "w/d hookups": "hookups",
                "w/d hookup": "hookups", "washer dryer hookups": "hookups", "washer/dryer hookups": "hookups",
                "none": "none", "no": "none", "no laundry": "none", "off site": "none"},
    "parking": {"garage": "garage", "covered": "covered", "carport": "covered", "lot": "lot", "surface": "lot",
                "off street": "lot", "off-street": "lot", "driveway": "lot", "driveway parking": "lot",
                "reserved": "lot", "reserved parking": "lot", "reserved spot": "lot", "reserved space": "lot",
                "assigned": "lot", "assigned parking": "lot", "assigned spot": "lot", "assigned space": "lot",
                "carport parking": "covered", "covered parking": "covered", "parking lot": "lot", "private lot": "lot", "street": "street", "on street": "street",
                "none": "none", "no": "none", "no parking": "none"},
    "pets": {"cats": "cats", "cat": "cats", "cats ok": "cats", "dogs": "dogs", "dog": "dogs", "dogs ok": "dogs",
             "both": "both", "cats and dogs": "both", "dogs and cats": "both", "pets ok": "both", "pet friendly": "both",
             "pet-friendly": "both", "pets allowed": "both", "yes": "both", "none": "none", "no": "none",
             "no pets": "none", "not allowed": "none"},
}
_ENUM_ALLOWED = {"laundry": LAUNDRY_VALUES, "parking": PARKING_VALUES, "pets": PETS_VALUES}


def clean_enum(field: str, value: Any) -> str:
    """The stored word for 'in unit', 'W/D', 'pet friendly'... or '' for blank. Raises ValueError otherwise."""
    raw = " ".join(str(value or "").replace("_", " ").split()).lower() if str(value or "").strip() else ""
    if not raw:
        return ""
    alias = _ENUM_ALIASES[field].get(raw) or _ENUM_ALIASES[field].get(raw.replace(" ", "_"))
    if alias is None and raw.replace(" ", "_") in _ENUM_ALLOWED[field]:
        alias = raw.replace(" ", "_")
    if alias is None:
        raise ValueError(f"{field.title()} needs to be one of: {', '.join(_ENUM_ALLOWED[field])}.")
    return alias


def clean_bool(value: Any) -> int | None:
    """1, 0 or None (unknown) from yes/no/true/false/1/0 or a bool."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return 1 if value else 0
    word = str(value).strip().lower()
    if word in ("1", "yes", "y", "true", "t", "on", "has one", "included"):
        return 1
    if word in ("0", "no", "n", "false", "f", "off", "none"):
        return 0
    if word in ("unknown", "?", "maybe"):
        return None
    raise ValueError("That needs to be yes or no.")


_TRACKING = re.compile(r"^(utm_.*|fbclid|gclid|mc_cid|mc_eid|ref|ref_src|referrer|source|src|cid|campaign|"
                       r"igshid|_hsenc|_hsmi|trk|trkid|spm|share|from)$", re.I)


def normalize_url(url: Any) -> str:
    """A listing link in one shape: https, lower-case host without www, no #fragment, no tracking parameters, no
    trailing slash. '' for blank or something that is not a web address. Never fetches anything."""
    text = _text(url, 2000)
    if not text:
        return ""
    if not re.match(r"^[a-z][a-z0-9+.-]*://", text, re.I):
        if " " in text or "." not in text.split("/")[0]:
            return ""
        text = "https://" + text
    try:
        parts = urlsplit(text)
    except ValueError:
        return ""
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        return ""
    host = parts.hostname.lower()
    host = host[4:] if host.startswith("www.") else host
    if parts.port and parts.port not in (80, 443):
        host = f"{host}:{parts.port}"
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _TRACKING.match(k)))
    path = parts.path.rstrip("/") or ""
    return urlunsplit(("https", host, path, query, ""))


_ADDRESS_WORDS = {"street": "st", "avenue": "ave", "road": "rd", "drive": "dr", "boulevard": "blvd", "lane": "ln",
                  "court": "ct", "place": "pl", "circle": "cir", "parkway": "pkwy", "highway": "hwy", "terrace": "ter",
                  "north": "n", "south": "s", "east": "e", "west": "w", "northeast": "ne", "northwest": "nw",
                  "southeast": "se", "southwest": "sw"}


def normalize_address(address: Any) -> str:
    """The street line of an address in one shape, for spotting the same place twice: lower case, no punctuation,
    'Street' -> 'st', city and state after the first comma dropped. '' for blank."""
    first = str(address or "").split(",")[0].lower()
    words = re.sub(r"[^a-z0-9 ]+", " ", first).split()
    words = [_ADDRESS_WORDS.get(w, w) for w in words]
    return " ".join(words)


def normalize_unit(unit: Any) -> str:
    text = re.sub(r"\b(apartment|apt|unit|suite|ste|number|no)\b|[#.\s-]", "", str(unit or "").lower())
    return text


def photo_list(value: Any) -> list[str]:
    """A list of http(s) photo links from a list, a JSON list or lines of text. At most PHOTOS_MAX. Never fetched."""
    if value is None or value == "":
        return []
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("["):
            try:
                value = json.loads(text)
            except ValueError:
                value = text.split()
        else:
            value = re.split(r"[\s,]+", text)
    out: list[str] = []
    for item in value if isinstance(value, (list, tuple)) else []:
        link = str(item or "").strip()
        if re.match(r"^https?://[^\s]+$", link, re.I) and link not in out:
            out.append(link[:2000])
    return out[:PHOTOS_MAX]


def _dict_factory(cursor: sqlite3.Cursor, row: tuple) -> dict[str, Any]:
    return {col[0]: row[i] for i, col in enumerate(cursor.description)}


def _place_out(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    row = {k: (_tidy_num(v) if isinstance(v, float) else v) for k, v in row.items()}
    try:
        row["photo_urls"] = photo_list(row.get("photo_urls") or "[]")
    except Exception:
        row["photo_urls"] = []
    return row


def _criterion_out(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    try:
        target = json.loads(row.get("target") or "{}")
    except ValueError:
        target = {}
    row = {k: (_tidy_num(v) if isinstance(v, float) else v) for k, v in row.items()}
    row["target"] = target if isinstance(target, dict) else {}
    return row


def _clean_target(kind: str, target: Any) -> dict[str, Any]:
    """Only the keys a criterion kind uses, numbers as numbers."""
    if target is None or target == "":
        target = {}
    if isinstance(target, str):
        try:
            target = json.loads(target)
        except ValueError:
            raise ValueError("The target needs to be a JSON object like {\"max\": 1600}.") from None
    if not isinstance(target, dict):
        raise ValueError("The target needs to be a JSON object like {\"max\": 1600}.")
    out: dict[str, Any] = {}
    if kind == "price":
        n = to_number(target.get("max"), "price limit")
        if n is not None:
            out["max"] = _tidy_num(n)
    elif kind in ("beds", "baths", "sqft"):
        n = to_number(target.get("min"), "minimum")
        if n is not None:
            out["min"] = _tidy_num(n)
    elif kind == "commute":
        if target.get("anchor_id") not in (None, ""):
            out["anchor_id"] = int(target["anchor_id"])
        mode = str(target.get("mode") or "bike").lower()
        if mode not in COMMUTE_MODES:
            raise ValueError(f"The commute needs a way to travel: {', '.join(COMMUTE_MODES)}.")
        out["mode"] = mode
        n = to_number(target.get("minutes"), "minutes")
        if n is not None:
            out["minutes"] = _tidy_num(n)
    elif kind == "laundry":
        out["want"] = clean_enum("laundry", target.get("want") or "in_unit") or "in_unit"
    elif kind == "parking":
        want = clean_enum("parking", target.get("want"))
        if want:
            out["want"] = want
    elif kind == "pets":
        want = clean_enum("pets", target.get("want"))
        if want:
            out["want"] = want
    elif kind == "newer":
        n = to_number(target.get("year"), "year")
        out["year"] = int(n) if n else 2000
    return out


def _json_default(o: Any) -> str:
    return str(o)


# --------------------------------------------------------------------------- the Store
class Store:
    """One SQLite connection to the database file. Thread-safe (one lock), so the web server's worker threads can
    share a Store. The MCP server opens its own Store on the same file."""

    no_delete = False

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._depth = 0
        self._open()

    # ------------------------------------------------------------------ infrastructure
    def _open(self) -> None:
        self._conn = sqlite3.connect(self.path, check_same_thread=False, timeout=10)
        self._conn.row_factory = _dict_factory
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA busy_timeout = 10000")
        self._conn.execute("PRAGMA secure_delete = ON")  # deleted text is overwritten, not left in the file
        if self.path != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.execute("PRAGMA synchronous = NORMAL")
        had_data = self._conn.execute("PRAGMA user_version").fetchone()["user_version"] >= 1
        self._migrate()
        if had_data and self._row("SELECT 1 FROM settings WHERE key = 'map_tiles'") is None:
            # Map pictures are off for a new data folder. A folder from before that change keeps what it had: on.
            with self._write():
                self._exec("INSERT OR IGNORE INTO settings(key, value) VALUES ('map_tiles', '1')")

    def _migrate(self) -> None:
        with self._lock:
            version = self._conn.execute("PRAGMA user_version").fetchone()["user_version"]
            if version >= len(_MIGRATIONS):
                return
            if version >= 1 and self.path != ":memory:":
                self._backup_before_upgrade()
            self._conn.execute("PRAGMA foreign_keys = OFF")
            try:
                for i, sql in enumerate(_MIGRATIONS[version:], start=version + 1):
                    self._conn.executescript("BEGIN;" + sql)
                    try:
                        if i == 1:
                            self._seed_checklist()
                        self._conn.execute(f"PRAGMA user_version = {i}")
                        self._conn.commit()
                    except Exception:
                        self._conn.rollback()
                        raise
            finally:
                self._conn.execute("PRAGMA foreign_keys = ON")

    @staticmethod
    def default_checklist(mode: str) -> tuple[tuple[str, str], ...]:
        """The starting checklist for a search mode: renters get ID, income and references; buyers get a pre-approval
        letter, proof of funds, an inspector and so on."""
        return DEFAULT_CHECKLIST_BUY if mode == "buy" else DEFAULT_CHECKLIST

    def _swap_untouched_checklist(self, items: tuple[tuple[str, str], ...]) -> None:
        """Only for the very first search of a fresh app: if the list is still exactly the renter starter list with
        nothing ticked, put ``items`` in its place. Any list the person has touched is left alone."""
        rows = self._rows("SELECT label, note, done FROM checklist_items ORDER BY sort_order, id")
        if [(r["label"], r["note"]) for r in rows] != list(DEFAULT_CHECKLIST) or any(r["done"] for r in rows):
            return
        self._exec("DELETE FROM checklist_items")
        for i, (label, note) in enumerate(items):
            self._exec("INSERT INTO checklist_items(label, note, done, sort_order) VALUES (?, ?, 0, ?)", (label, note, i))

    def add_default_checklist_items(self, mode: str) -> int:
        """Add the starter items of ``mode`` that the list doesn't have yet (matched by label). Returns how many."""
        have = {r["label"].strip().lower() for r in self.list_checklist()}
        n = 0
        for label, note in self.default_checklist(mode):
            if label.strip().lower() not in have:
                self.add_checklist_item(label, note)
                n += 1
        return n

    def _seed_checklist(self) -> None:
        for i, (label, note) in enumerate(DEFAULT_CHECKLIST):
            self._conn.execute("INSERT INTO checklist_items(label, note, done, sort_order) VALUES (?, ?, 0, ?)",
                               (label, note, i))

    def _backup_before_upgrade(self) -> None:
        """An older database is about to be upgraded in place: keep a copy first (best effort)."""
        try:
            from .backups import backup_before

            backup_before(self, reason="upgrade")
        except Exception:
            pass

    @property
    def schema_version(self) -> int:
        """The migration number this database is at (``PRAGMA user_version``)."""
        return self._conn.execute("PRAGMA user_version").fetchone()["user_version"]

    @contextmanager
    def _write(self) -> Iterator[None]:
        """One transaction. Writes made inside another _write() join it, so a multi-step change is all or nothing."""
        with self._lock:
            if self._depth:
                self._depth += 1
                try:
                    yield
                finally:
                    self._depth -= 1
                return
            self._depth = 1
            try:
                with self._conn:
                    yield
            finally:
                self._depth = 0

    def _rows(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        with self._lock:
            return self._conn.execute(sql, tuple(params)).fetchall()

    def _row(self, sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
        with self._lock:
            return self._conn.execute(sql, tuple(params)).fetchone()

    def _exec(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, tuple(params))
            if not self._depth:  # outside _write(): a lone statement commits at once
                self._conn.commit()
            return cur

    def checkpoint(self) -> None:
        """Copy the write-ahead log into the main file (so deleted text does not linger in the -wal file)."""
        if self.path == ":memory:":
            return
        with self._lock:
            try:
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
            except sqlite3.Error:
                pass

    def close(self) -> None:
        with self._lock:
            self.checkpoint()
            self._conn.close()

    def backup_to(self, dest: str | Path) -> None:
        """A consistent copy of the whole database, safe while another process writes."""
        with self._lock:
            target = sqlite3.connect(str(dest))
            try:
                self._conn.backup(target)
            finally:
                target.close()

    def restore_from(self, source: str | Path) -> None:
        """Put a backup file's data in place of this database's (the file itself stays put), then reopen."""
        if self.path == ":memory:":
            raise ValueError("There's no database file to restore into.")
        uri = Path(source).resolve().as_uri() + "?immutable=1"
        with self._lock:
            src = sqlite3.connect(uri, uri=True)
            try:
                src.backup(self._conn)
            finally:
                src.close()
            self._conn.close()
            self._open()
        self.checkpoint()

    NO_DELETE_METHODS: tuple[str, ...] = ("archive_place", "unarchive_place", "archive_search", "unarchive_search",
                                          "unlink_contact", "clear_commute")

    def enable_no_delete(self) -> None:
        """No-delete mode, set by the MCP server when it opens a store (design rule 3: the AI never deletes). Every
        method that deletes, removes or archives now raises a plain error on this Store object."""
        def refuse(*_a: Any, **_k: Any) -> Any:
            raise PermissionError("Deleting is not allowed here. Only the user can delete, from the Property Helper window.")

        names = {n for n in dir(type(self)) if n.startswith(("delete_", "remove_"))} | set(self.NO_DELETE_METHODS)
        for name in names:
            setattr(self, name, refuse)
        self.no_delete = True

    # ------------------------------------------------------------------ settings
    def get_setting(self, key: str, default: str | None = None) -> str | None:
        """A saved setting as text. Falls back to ``default`` (if given), else to the built-in default, else None."""
        row = self._row("SELECT value FROM settings WHERE key = ?", (key,))
        if row is not None:
            return row["value"]
        return default if default is not None else DEFAULT_SETTINGS.get(key)

    def get_setting_int(self, key: str, default: int = 0) -> int:
        try:
            return int(float(str(self.get_setting(key)).strip()))
        except ValueError:
            return default

    def get_setting_float(self, key: str, default: float = 0.0) -> float:
        try:
            return float(str(self.get_setting(key)).strip())
        except ValueError:
            return default

    def get_setting_bool(self, key: str, default: bool = False) -> bool:
        value = self.get_setting(key)
        if value is None:
            return default
        return str(value).strip().lower() in ("1", "true", "yes", "on")

    def set_setting(self, key: str, value: Any) -> None:
        """Save a setting (stored as text)."""
        key = _text(key, 100)
        if not key:
            raise ValueError("A setting needs a name.")
        with self._write():
            self._exec("INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                       (key, "" if value is None else str(value)))

    def all_settings(self) -> dict[str, str]:
        """Every setting, saved values over the built-in defaults."""
        out = dict(DEFAULT_SETTINGS)
        out.update({r["key"]: r["value"] for r in self._rows("SELECT key, value FROM settings")})
        return out

    def buy_settings(self) -> dict[str, str]:
        """down_payment_pct, mortgage_rate, loan_years and pmi_rate_pct as saved (text), for :mod:`money`."""
        s = self.all_settings()
        return {k: s[k] for k in ("down_payment_pct", "mortgage_rate", "loan_years", "pmi_rate_pct", "closing_cost_pct")}

    # ------------------------------------------------------------------ searches
    def _search_values(self, fields: dict[str, Any], partial: bool) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if "name" in fields or not partial:
            name = _text(fields.get("name"), 200)
            if not name:
                raise ValueError("A search needs a name, like 'UIUC 1-bed 2027'.")
            out["name"] = name
        if "mode" in fields or not partial:
            mode = _text(fields.get("mode") or "rent", 10).lower()
            if mode not in st.MODES:
                raise ValueError("A search is either rent or buy.")
            out["mode"] = mode
        if "area" in fields:
            out["area"] = _text(fields["area"], 300)
        if "notes" in fields:
            out["notes"] = _text(fields["notes"], 20_000)
        for key in ("move_in", "target_close"):
            if key in fields:
                out[key] = clean_date(fields[key], key.replace("_", " "))
        if "budget_max" in fields:
            n = to_number(fields["budget_max"], "budget")
            if n is not None and n < 0:
                raise ValueError("The budget can't be negative.")
            out["budget_max"] = n
        if "hide_dealbreakers" in fields:
            out["hide_dealbreakers"] = 1 if clean_bool(fields["hide_dealbreakers"]) else 0
        elif not partial:
            out["hide_dealbreakers"] = 0  # places that miss a deal-breaker stay visible (last, with a note)
        if "people" in fields:
            n = to_number(fields["people"], "the number of people")
            if n is None:
                n = 1
            if n != int(n) or not 1 <= n <= MAX_PEOPLE:
                raise ValueError(f"People sharing the cost is a whole number from 1 to {MAX_PEOPLE}.")
            out["people"] = int(n)
        if "pet_kind" in fields:
            kind = _text(fields["pet_kind"], 10).lower()
            if kind not in ("", "cat", "dog", "both", "none"):
                raise ValueError("Your pets are cat, dog, both or none.")
            out["pet_kind"] = kind
        if "pet_weight" in fields:
            n = to_number(fields["pet_weight"], "your dog's weight")
            if n is not None and not 0 < n <= 300:
                raise ValueError("Your dog's weight is in pounds, from 1 to 300.")
            out["pet_weight"] = n
        if "pet_count" in fields:
            n = to_number(fields["pet_count"], "the number of pets")
            if n is not None and (n != int(n) or not 1 <= n <= 20):
                raise ValueError("The number of pets is a whole number from 1 to 20.")
            out["pet_count"] = None if n is None else int(n)
        if "people_names" in fields:
            out["people_names"] = json.dumps(clean_people_names(fields["people_names"]))
        if "is_sample" in fields:
            out["is_sample"] = 1 if fields["is_sample"] else 0
        return out

    def add_search(self, name: str, mode: str = "rent", **fields: Any) -> dict[str, Any]:
        """Make a search. Other fields: area, move_in (rent), target_close (buy), budget_max, notes,
        hide_dealbreakers (default off), people (default 1), is_sample. The first search made becomes the current one."""
        values = self._search_values({**fields, "name": name, "mode": mode}, partial=False)
        now = now_iso()
        with self._write():
            cols = {**values, "created_at": now, "updated_at": now}
            cur = self._exec(f"INSERT INTO searches({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                             tuple(cols.values()))
            sid = cur.lastrowid
            if not self.get_setting("current_search_id", ""):
                self.set_setting("current_search_id", sid)
            if values.get("mode") == "buy" and not self._row("SELECT 1 AS x FROM searches WHERE id != ?", (sid,)):
                self._swap_untouched_checklist(DEFAULT_CHECKLIST_BUY)
        return self.get_search(sid)

    def get_search(self, search_id: int) -> dict[str, Any]:
        row = self._row("SELECT * FROM searches WHERE id = ?", (search_id,))
        if row is None:
            raise NotFound(f"Search {search_id} doesn't exist.")
        return _tidy_row(row)

    def update_search(self, search_id: int, **fields: Any) -> dict[str, Any]:
        """Change a search. Its mode can only change while it has no places (stages differ between rent and buy)."""
        current = self.get_search(search_id)
        values = self._search_values(fields, partial=True)
        if "mode" in values and values["mode"] != current["mode"]:
            if self.count_places(search_id=search_id, include_archived=True):
                raise ValueError("This search already has places, so its mode can't change. Make a new search instead.")
        if values:
            values["updated_at"] = now_iso()
            sets = ", ".join(f"{k} = ?" for k in values)
            with self._write():
                self._exec(f"UPDATE searches SET {sets} WHERE id = ?", (*values.values(), search_id))
                if "people_names" in values or "people" in values:
                    self._rename_opinion_people(current, self.get_search(search_id))
        return self.get_search(search_id)

    # ------------------------------------------------------------------ opinions (each person's own rating and note)
    def _rename_opinion_people(self, before: dict[str, Any], after: dict[str, Any]) -> None:
        """When a person is renamed (same position in the list), their saved opinions follow the new name. Opinions of
        a name that no longer exists are kept, so a typo never loses anyone's words, but they stop showing."""
        old, new = people_slots(before), people_slots(after)
        # Only a name that is gone from the list, replaced in the same position by a name that wasn't there: that is a
        # rename. Reordering or adding people leaves everyone's words where they are.
        pairs = [(o, n) for o, n in zip(old, new) if o != n and o not in new and n not in old]
        if not pairs:
            return
        for o, n in pairs:
            self._exec("UPDATE OR IGNORE place_opinions SET person = ? WHERE person = ? AND place_id IN "
                       "(SELECT id FROM places WHERE search_id = ?)", (n, o, after["id"]))

    def set_opinion(self, place_id: int, person: str, rating: Any = None, note: Any = "") -> dict[str, Any] | None:
        """Save one person's 1 to 5 rating and short note for a place (both blank clears it). ``person`` must be one of the
        names of the place's search (see ``people_slots``). These are the user's own words: the app window writes
        them, there is no AI tool for it. Returns the saved row, or None when it was cleared."""
        place = self._require_place(place_id)
        slots = people_slots(self.get_search(place["search_id"]))
        who = _text(person, PERSON_NAME_MAX)
        if who not in slots:
            raise ValueError("That isn't one of the people on this search. Name the people on the Search page first.")
        n = to_number(rating, "rating") if str(rating if rating is not None else "").strip() else None
        if n is not None:
            n = int(round(n))
            if not 1 <= n <= 5:
                raise ValueError("A rating is from 1 to 5.")
        text = _text(note, OPINION_NOTE_MAX)
        if n is None and not text:
            self._exec("DELETE FROM place_opinions WHERE place_id = ? AND person = ?", (place_id, who))
            return None
        self._exec("INSERT INTO place_opinions(place_id, person, rating, note, updated_at) VALUES (?, ?, ?, ?, ?) "
                   "ON CONFLICT(place_id, person) DO UPDATE SET rating = excluded.rating, note = excluded.note, "
                   "updated_at = excluded.updated_at", (place_id, who, n, text, now_iso()))
        return self._row("SELECT * FROM place_opinions WHERE place_id = ? AND person = ?", (place_id, who))

    def list_opinions(self, place_id: int) -> list[dict[str, Any]]:
        """Saved opinions of a place, in the order of the search's people. Names no longer on the search are left out."""
        place = self._require_place(place_id)
        slots = people_slots(self.get_search(place["search_id"]))
        rows = {r["person"]: r for r in self._rows("SELECT * FROM place_opinions WHERE place_id = ?", (place_id,))}
        return [rows[n] for n in slots if n in rows]

    def opinion_slots(self, place_id: int) -> list[dict[str, Any]]:
        """One entry per person on the place's search (empty when one person), each ``{"person", "rating", "note"}`` with
        the saved values or blanks. For the form on the place page."""
        place = self._require_place(place_id)
        slots = people_slots(self.get_search(place["search_id"]))
        rows = {r["person"]: r for r in self._rows("SELECT * FROM place_opinions WHERE place_id = ?", (place_id,))}
        return [{"person": n, "rating": rows[n]["rating"] if n in rows else None, "note": rows[n]["note"] if n in rows else ""} for n in slots]

    def opinion_stats(self, place_id: int) -> dict[str, Any] | None:
        """``{"count": how many people rated it, "average": mean of their ratings to one decimal}`` or None when nobody has."""
        rated = [o["rating"] for o in self.list_opinions(place_id) if o["rating"] is not None]
        if not rated:
            return None
        return {"count": len(rated), "average": round(sum(rated) / len(rated), 1)}

    def list_searches(self, include_archived: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM searches" + ("" if include_archived else " WHERE archived_at IS NULL") + " ORDER BY id"
        return [_tidy_row(r) for r in self._rows(sql)]

    def archive_search(self, search_id: int) -> dict[str, Any]:
        self.get_search(search_id)
        self._exec("UPDATE searches SET archived_at = ?, updated_at = ? WHERE id = ?", (now_iso(), now_iso(), search_id))
        if self.get_setting("current_search_id", "") == str(search_id):
            self.set_setting("current_search_id", "")
        return self.get_search(search_id)

    def unarchive_search(self, search_id: int) -> dict[str, Any]:
        self.get_search(search_id)
        self._exec("UPDATE searches SET archived_at = NULL, updated_at = ? WHERE id = ?", (now_iso(), search_id))
        return self.get_search(search_id)

    def delete_search(self, search_id: int) -> bool:
        """Delete a search with its criteria, places and everything on them. App window only."""
        self.get_search(search_id)
        with self._write():
            self._exec("DELETE FROM searches WHERE id = ?", (search_id,))
            if self.get_setting("current_search_id", "") == str(search_id):
                self.set_setting("current_search_id", "")
        return True

    def current_search(self) -> dict[str, Any] | None:
        """The search the app is showing: the saved one if it still exists and isn't archived, else the oldest open
        search, else None."""
        saved = self.get_setting("current_search_id", "")
        if saved and saved.isdigit():
            row = self._row("SELECT * FROM searches WHERE id = ? AND archived_at IS NULL", (int(saved),))
            if row:
                return _tidy_row(row)
        row = self._row("SELECT * FROM searches WHERE archived_at IS NULL ORDER BY id LIMIT 1")
        return _tidy_row(row) if row else None

    def set_current_search(self, search_id: int) -> dict[str, Any]:
        s = self.get_search(search_id)
        if s["archived_at"]:
            raise ValueError("That search is archived. Restore it first.")
        self.set_setting("current_search_id", search_id)
        return s

    # ------------------------------------------------------------------ criteria
    def add_criterion(self, search_id: int, kind: str, *, label: str = "", weight: Any = 10, dealbreaker: Any = False,
                      target: Any = None) -> dict[str, Any]:
        """Add a weighted criterion (kinds: see CRITERION_KINDS; targets: see DESIGN section 3)."""
        self.get_search(search_id)
        kind = _text(kind, 30).lower()
        if kind not in CRITERION_KINDS:
            raise ValueError(f"The kinds of thing that can matter are: {', '.join(CRITERION_KINDS)}.")
        w = self._weight(weight)
        tgt = _clean_target(kind, target)
        with self._write():
            order = self._row("SELECT COALESCE(MAX(sort_order), -1) + 1 AS n FROM criteria WHERE search_id = ?", (search_id,))["n"]
            cur = self._exec("INSERT INTO criteria(search_id, kind, label, weight, dealbreaker, target, sort_order) "
                             "VALUES (?, ?, ?, ?, ?, ?, ?)",
                             (search_id, kind, _text(label, 200), w, 1 if clean_bool(dealbreaker) else 0,
                              json.dumps(tgt), order))
            self._exec("UPDATE searches SET updated_at = ? WHERE id = ?", (now_iso(), search_id))
        return self.get_criterion(cur.lastrowid)

    @staticmethod
    def _weight(weight: Any) -> float:
        w = to_number(weight, "weight")
        if w is None:
            w = 10.0
        if not 0 <= w <= 100:
            raise ValueError("How much it matters is a number from 0 to 100.")
        return _tidy_num(w)

    def get_criterion(self, criterion_id: int) -> dict[str, Any]:
        row = _criterion_out(self._row("SELECT * FROM criteria WHERE id = ?", (criterion_id,)))
        if row is None:
            raise NotFound(f"Criterion {criterion_id} doesn't exist.")
        return row

    def update_criterion(self, criterion_id: int, **fields: Any) -> dict[str, Any]:
        """Change label, weight, dealbreaker, target or sort_order. The kind can't change (make a new criterion)."""
        cur = self.get_criterion(criterion_id)
        values: dict[str, Any] = {}
        if "label" in fields:
            values["label"] = _text(fields["label"], 200)
        if "weight" in fields:
            values["weight"] = self._weight(fields["weight"])
        if "dealbreaker" in fields:
            values["dealbreaker"] = 1 if clean_bool(fields["dealbreaker"]) else 0
        if "target" in fields:
            values["target"] = json.dumps(_clean_target(cur["kind"], fields["target"]))
        if "sort_order" in fields:
            values["sort_order"] = int(fields["sort_order"])
        if values:
            self._exec(f"UPDATE criteria SET {', '.join(f'{k} = ?' for k in values)} WHERE id = ?",
                       (*values.values(), criterion_id))
            self._exec("UPDATE searches SET updated_at = ? WHERE id = ?", (now_iso(), cur["search_id"]))
        return self.get_criterion(criterion_id)

    def list_criteria(self, search_id: int) -> list[dict[str, Any]]:
        return [_criterion_out(r) for r in self._rows(
            "SELECT * FROM criteria WHERE search_id = ? ORDER BY sort_order, id", (search_id,))]

    def delete_criterion(self, criterion_id: int) -> bool:
        cur = self.get_criterion(criterion_id)
        self._exec("DELETE FROM criteria WHERE id = ?", (criterion_id,))
        self._exec("UPDATE searches SET updated_at = ? WHERE id = ?", (now_iso(), cur["search_id"]))
        return True

    # ------------------------------------------------------------------ anchors
    def _anchor_values(self, fields: dict[str, Any], partial: bool) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if "name" in fields or not partial:
            name = _text(fields.get("name"), 120)
            if not name:
                raise ValueError("An important place needs a name, like 'Campus' or 'Work'.")
            out["name"] = name
        if "address" in fields:
            out["address"] = _text(fields["address"], 300)
        for key, low, high in (("lat", -90, 90), ("lng", -180, 180)):
            if key in fields:
                n = to_number(fields[key], key)
                if n is not None and not low <= n <= high:
                    raise ValueError(f"A {key} is between {low} and {high}.")
                out[key] = n
        if "is_sample" in fields:
            out["is_sample"] = 1 if fields["is_sample"] else 0
        return out

    def add_anchor(self, name: str, address: str = "", lat: Any = None, lng: Any = None, *, is_sample: bool = False) -> dict[str, Any]:
        values = self._anchor_values({"name": name, "address": address, "lat": lat, "lng": lng, "is_sample": is_sample}, False)
        cur = self._exec(f"INSERT INTO anchors({', '.join(values)}) VALUES ({', '.join('?' * len(values))})",
                         tuple(values.values()))
        return self.get_anchor(cur.lastrowid)

    def get_anchor(self, anchor_id: int) -> dict[str, Any]:
        row = self._row("SELECT * FROM anchors WHERE id = ?", (anchor_id,))
        if row is None:
            raise NotFound(f"Anchor {anchor_id} doesn't exist.")
        return _tidy_row(row)

    def update_anchor(self, anchor_id: int, **fields: Any) -> dict[str, Any]:
        self.get_anchor(anchor_id)
        values = self._anchor_values(fields, True)
        values.pop("is_sample", None)
        if values:
            self._exec(f"UPDATE anchors SET {', '.join(f'{k} = ?' for k in values)} WHERE id = ?", (*values.values(), anchor_id))
        return self.get_anchor(anchor_id)

    def list_anchors(self) -> list[dict[str, Any]]:
        return [_tidy_row(r) for r in self._rows("SELECT * FROM anchors ORDER BY id")]

    def delete_anchor(self, anchor_id: int) -> bool:
        """Delete an anchor and the commute times saved for it."""
        self.get_anchor(anchor_id)
        self._exec("DELETE FROM anchors WHERE id = ?", (anchor_id,))
        return True

    # ------------------------------------------------------------------ places
    def _clean_place(self, fields: dict[str, Any], partial: bool) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key in PLACE_TEXT:
            if key not in fields:
                continue
            raw = fields[key]
            if key in ("laundry", "parking", "pets"):
                out[key] = clean_enum(key, raw)
            elif key in PLACE_DATES:
                out[key] = clean_date(raw, key.replace("_", " "))
            elif key == "special_assessment_payer":
                word = " ".join(str(raw or "").lower().split())
                word = {"the seller": "seller", "the buyer": "buyer", "you": "buyer", "unknown": "", "not sure": ""}.get(word, word)
                if word not in ("", "seller", "buyer"):
                    raise ValueError("Who pays a special assessment is seller or buyer.")
                out[key] = word
            elif key == "tenant_pays":
                words = re.findall(r"[a-z]+", str(raw or "").lower())
                words = ["electric" if w == "electricity" else "internet" if w in ("wifi", "cable") else w for w in words]
                out[key] = ", ".join(w for w in TENANT_PAYS_CHOICES if w in words)
            elif key == "url":
                text = _text(raw, 2000)
                # Kept as typed (so a spreadsheet export shows "www.zillow.com"). Only duplicate checks use the
                # normalized form. A link typed without http(s):// gets https:// so it still opens.
                if text and not normalize_url(text):
                    raise ValueError("That link doesn't look like a web address (it should start with https://).")
                out[key] = text if not text or re.match(r"^[a-z][a-z0-9+.-]*://", text, re.I) else "https://" + text
            else:
                out[key] = _text(raw, TEXT_LIMITS.get(key, 500))
        for key in PLACE_REAL:
            if key in fields:
                n = to_number(fields[key], key.replace("_", " "))
                if key == "lat" and n is not None and not -90 <= n <= 90:
                    raise ValueError("A latitude is between -90 and 90.")
                if key == "lng" and n is not None and not -180 <= n <= 180:
                    raise ValueError("A longitude is between -180 and 180.")
                if key not in ("lat", "lng") and n is not None and n < 0:
                    raise ValueError(f"The {key.replace('_', ' ')} can't be negative.")
                out[key] = n
        for key in PLACE_INT:
            if key in fields:
                n = to_number(fields[key], key.replace("_", " "))
                if n is not None:
                    n = int(round(n))
                    if key == "rating" and not 1 <= n <= 5:
                        raise ValueError("A rating is from 1 to 5.")
                    if key == "months_up_front" and not 0 <= n <= 12:
                        raise ValueError("Months of rent due before move-in is a number from 0 to 12.")
                    if key == "fit_score" and not 0 <= n <= 100:
                        raise ValueError("A fit score is from 0 to 100.")
                    if n < 0:
                        raise ValueError(f"The {key.replace('_', ' ')} can't be negative.")
                out[key] = n
        if "photo_urls" in fields:
            out["photo_urls"] = json.dumps(photo_list(fields["photo_urls"]))
        if "dishwasher" in fields:
            out["dishwasher"] = clean_bool(fields["dishwasher"])
        if "fenced_yard" in fields:
            out["fenced_yard"] = clean_bool(fields["fenced_yard"])
        if "hidden" in fields:
            out["hidden"] = 1 if clean_bool(fields["hidden"]) else 0
        if "is_sample" in fields:
            out["is_sample"] = 1 if fields["is_sample"] else 0
        return out

    def _require_place(self, place_id: int) -> dict[str, Any]:
        row = self._row("SELECT * FROM places WHERE id = ?", (place_id,))
        if row is None:
            raise NotFound(f"Place {place_id} doesn't exist.")
        return row

    def _touch(self, place_id: int, when: str | None = None) -> None:
        self._exec("UPDATE places SET updated_at = ? WHERE id = ?", (when or now_iso(), place_id))

    def _mode_of(self, search_id: int) -> str:
        row = self._row("SELECT mode FROM searches WHERE id = ?", (search_id,))
        if row is None:
            raise NotFound(f"Search {search_id} doesn't exist.")
        return row["mode"]

    def place_mode(self, place_id: int) -> str:
        """The mode ("rent" or "buy") of the search a place belongs to."""
        return self._mode_of(self._require_place(place_id)["search_id"])

    def find_duplicate(self, search_id: int | None = None, *, url: str | None = None, address: str | None = None,
                       unit: str | None = None, exclude_id: int | None = None) -> dict[str, Any] | None:
        """The place a new one would repeat: the same normalized link (in any search, links are unique), else the same
        normalized street address plus unit in the same search. Archived places count."""
        norm = normalize_url(url)
        if norm:
            # Links are stored as typed, so compare the normalized form of each saved link.
            for row in self._rows("SELECT * FROM places WHERE url != '' AND id != ?", (exclude_id or 0,)):
                if normalize_url(row["url"]) == norm:
                    return _place_out(row)
        key = normalize_address(address)
        if key and search_id is not None:
            unit_key = normalize_unit(unit)
            for row in self._rows("SELECT * FROM places WHERE search_id = ? AND address != '' AND id != ?",
                                  (search_id, exclude_id or 0)):
                if normalize_address(row["address"]) == key and normalize_unit(row["unit"]) == unit_key:
                    return _place_out(row)
        return None

    def add_place(self, *, by: str = "you", search_id: int | None = None, stage: str | None = None,
                  **fields: Any) -> tuple[dict[str, Any], bool]:
        """Add a place, or update the one it repeats. Returns ``(place, created)``.

        Goes in the current search unless ``search_id`` is given. Needs a title, an address or a link (the title
        falls back to the address, then the site, then 'Untitled place'). Fields: see ``PLACE_FIELDS``. ``stage``
        defaults to the first stage ("Saved").

        Duplicates: the same normalized link, or the same street address and unit in the same search. On a match
        nothing new is created (``created`` is False) and only EMPTY fields are filled; the user's ``notes`` are never
        overwritten and a stage never moves. With ``by="ai"`` text meant for ``notes`` goes to ``ai_notes``."""
        by = "ai" if by == "ai" else "you"
        if search_id is None:
            cur = self.current_search()
            if cur is None:
                raise ValueError("Make a search first (Search page), so there is somewhere to put this place.")
            search_id = cur["id"]
        mode = self._mode_of(search_id)
        fields = dict(fields)
        if by == "ai":
            note = fields.pop("notes", None)
            if note and str(note).strip():
                fields["ai_notes"] = " ".join(filter(None, [str(fields.get("ai_notes") or ""), str(note)]))
            for key in ("rating", "hidden", "is_sample"):
                fields.pop(key, None)
        values = self._clean_place(fields, partial=True)
        if not (values.get("title") or values.get("address") or values.get("url")):
            raise ValueError("A place needs at least a title, an address or a link.")
        with self._write():
            existing = self.find_duplicate(search_id, url=values.get("url"), address=values.get("address"), unit=values.get("unit"))
            if existing is not None and bool(existing.get("is_sample")) != bool(values.get("is_sample")):
                # A real place never folds into a made-up sample (removing the samples would take it too), and
                # the other way round. The sample gives up a link they share.
                if existing.get("url") and normalize_url(existing["url"]) == normalize_url(values.get("url")):
                    self._exec("UPDATE places SET url = '' WHERE id = ?", (existing["id"],))
                existing = None
            if existing is not None:
                return self._merge_into(existing, values, by), False
            if not values.get("title"):
                values["title"] = self._fallback_title(values)
            new_stage = st.FIRST_STAGE
            if stage:
                norm = st.normalize_stage(mode, stage)
                if norm is None:
                    raise StageRuleError(f"A {mode} search has these stages: {', '.join(st.stages_for(mode))}.")
                new_stage = norm
                if by == "ai" and new_stage in AI_NEVER_ENTERS:
                    raise StageRuleError(f"{new_stage} is for the user to set. Ask the user to do this in the app.")
                if by == "ai" and ai_move_problem(mode, st.FIRST_STAGE, new_stage):
                    # the same rule as move_place, counted from Saved: one step forward, or Passed
                    nxt = st.stages_for(mode)[1]
                    raise StageRuleError(f"An AI moves a place one stage at a time, so a new place can be added as Saved, {nxt} or Passed, "
                                         f"not {new_stage}. Add it as Saved and move it forward step by step, or ask the user.")
            now = now_iso()
            cols = {"search_id": search_id, "stage": new_stage, "stage_changed_at": now, "created_at": now,
                    "updated_at": now, **values}
            cur = self._exec(f"INSERT INTO places({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                             tuple(cols.values()))
            pid = cur.lastrowid
            self._add_event(pid, "stage", f"Added as {new_stage}", now, by)
        return self.get_place(pid), True

    @staticmethod
    def _fallback_title(values: dict[str, Any]) -> str:
        if values.get("address"):
            return values["address"].split(",")[0][:300]
        if values.get("url"):
            host = urlsplit(values["url"]).hostname or ""
            return f"Listing on {host}" if host else "Untitled place"
        return "Untitled place"

    def _merge_into(self, existing: dict[str, Any], values: dict[str, Any], by: str) -> dict[str, Any]:
        """Fill only the empty fields of ``existing`` from ``values``. Returns the place."""
        filled: list[str] = []
        sets: dict[str, Any] = {}
        for key, new in values.items():
            if key in ("notes", "is_sample", "hidden", "rating") and existing.get(key) not in (None, "", 0):
                continue
            old = existing.get(key)
            if key == "photo_urls":
                old_list = existing.get("photo_urls") or []
                merged = list(old_list) + [u for u in json.loads(new) if u not in old_list]
                if merged != old_list:
                    sets[key] = json.dumps(merged[:PHOTOS_MAX])
                    filled.append("photos")
                continue
            empty_old = old is None or old == ""
            empty_new = new is None or new == ""
            if empty_old and not empty_new:
                sets[key] = new
                filled.append(key.replace("_", " "))
            elif key == "ai_notes" and not empty_new and new not in (old or ""):
                sets[key] = ((old + "\n") if old else "") + new
                filled.append("AI notes")
        pid = existing["id"]
        if sets:
            sets["updated_at"] = now_iso()
            self._exec(f"UPDATE places SET {', '.join(f'{k} = ?' for k in sets)} WHERE id = ?", (*sets.values(), pid))
        text = "Added again: filled in " + ", ".join(filled) + "." if filled else "Added again: nothing new to fill in."
        self._add_event(pid, "note", text, None, by)
        return self.get_place(pid)

    def get_place(self, place_id: int) -> dict[str, Any]:
        return _place_out(self._require_place(place_id))  # type: ignore[return-value]

    def update_place(self, place_id: int, *, by: str = "you", **fields: Any) -> dict[str, Any]:
        """Change facts on a place. ``stage`` is handled by :meth:`move_stage` (same rules). With ``by="ai"``:
        ``notes``, ``rating``, ``hidden`` are never written, text meant for ``notes`` is added to ``ai_notes``, and
        each value replaced is written to the timeline (kind ``ai``) so the user can put it back."""
        by = "ai" if by == "ai" else "you"
        existing = self.get_place(place_id)
        fields = dict(fields)
        stage = fields.pop("stage", None)
        fields.pop("is_sample", None)
        if by == "ai":
            text = existing["ai_notes"]
            notes = [fields.pop("notes", None), fields.pop("ai_notes", None)]
            for note in notes:  # both are the AI's own text: add it under what is already there
                if note and str(note).strip():
                    text = self._append_ai_note(text, note)
                    fields["ai_notes"] = text
            for key in AI_PROTECTED:
                fields.pop(key, None)
        values = self._clean_place(fields, partial=True)
        if "url" in values and values["url"]:
            other = self.find_duplicate(None, url=values["url"], exclude_id=place_id)
            if other:
                raise ValueError(f"Another place already has that link ({other['title']}).")
        changed = {k: v for k, v in values.items() if self._differs(existing, k, v)}
        with self._write():
            if changed:
                changed["updated_at"] = now_iso()
                self._exec(f"UPDATE places SET {', '.join(f'{k} = ?' for k in changed)} WHERE id = ?",
                           (*changed.values(), place_id))
                if by == "ai":
                    self._log_ai_overwrites(existing, changed)
            if stage is not None and stage != "" and stage != existing["stage"]:
                self.move_stage(place_id, stage, by_ai=(by == "ai"))
        return self.get_place(place_id)

    @staticmethod
    def _differs(existing: dict[str, Any], key: str, new: Any) -> bool:
        old = existing.get(key)
        if key == "photo_urls":
            return json.loads(new) != (old or [])
        if old is None and new is None:
            return False
        if isinstance(old, (int, float)) and isinstance(new, (int, float)):
            return float(old) != float(new)
        return (old if old is not None else "") != (new if new is not None else "")

    @staticmethod
    def _append_ai_note(old: str, new: Any) -> str:
        line = f"[AI, {today_local()}] {_text(new, 5000)}"
        text = ((old + "\n") if old else "") + line
        return text[-AI_NOTES_MAX:]

    def _log_ai_overwrites(self, existing: dict[str, Any], changed: dict[str, Any]) -> None:
        """Write the old values an AI update replaced to the timeline, so they can be put back by hand."""
        parts = []
        for key, new in changed.items():
            if key in ("updated_at", "ai_notes", "photo_urls", "listing_text"):
                continue
            old = existing.get(key)
            if old in (None, ""):
                continue  # filling an empty field replaces nothing
            parts.append(f"{key.replace('_', ' ')}: was {_ev_cut(_tidy_num(old), 200)}, now {_ev_cut(_tidy_num(new), 200)}")
        if parts:
            self._add_event(existing["id"], "ai", "AI changed " + "; ".join(parts), None, "ai")

    def move_stage(self, place_id: int, stage: str, *, by_ai: bool = False, note: str = "", auto: bool = False) -> dict[str, Any]:
        """Move a place to a stage of its search's mode. The user may move anywhere. With ``by_ai=True`` only one
        stage forward or to Passed is allowed (never backward, never out of Passed, never into Under contract or a
        won stage): anything else raises StageRuleError. ``auto`` is for the app's own follow-on moves (a booked tour
        moves a place to Tour booked), which may skip ahead but never past the AI limits above."""
        place = self._require_place(place_id)
        mode = self._mode_of(place["search_id"])
        new = st.normalize_stage(mode, stage)
        if new is None:
            raise StageRuleError(f"'{stage}' isn't a stage of a {mode} search. Stages: {', '.join(st.stages_for(mode))}.")
        old = place["stage"]
        if new == old:
            return self.get_place(place_id)
        if by_ai:
            problem = ai_move_problem(mode, old, new, one_step=not auto)
            if not problem and new == "Toured" and not auto:
                problem = self._future_tour_problem(place_id)
            if problem:
                raise StageRuleError(problem)
        now = now_iso()
        with self._write():
            self._exec("UPDATE places SET stage = ?, stage_changed_at = ?, updated_at = ?, seen_at = COALESCE(seen_at, ?) "
                       "WHERE id = ?", (new, now, now, now if not by_ai else None, place_id))
            self._add_event(place_id, "stage", f"Moved from {old} to {new}" + (f". {_text(note, 500)}" if note else ""),
                            now, "ai" if by_ai else "you")
        return self.get_place(place_id)

    def _future_tour_problem(self, place_id: int) -> str:
        """Why an AI may not mark a place Toured yet: its only tours (not cancelled) are still ahead. "" when it may
        (no tours at all, or at least one that is done or already past)."""
        now = now_iso()
        tours = [t for t in self.list_tours(place_id) if t["status"] != "cancelled"]
        if not tours or any(t["status"] == "done" or t["starts_at"] <= now for t in tours):
            return ""
        first = min(tours, key=lambda t: t["starts_at"])
        from . import helpers  # local import: helpers imports this module
        return f"That tour is on {helpers.day_text(first['starts_at'])}; move it to Toured after you go."

    def list_places(self, search_id: int | None = None, *, stage: str | Iterable[str] | None = None,
                    query: str | None = None, include_archived: bool = False, archived_only: bool = False,
                    include_hidden: bool = True, sort: str = "updated", limit: int | None = None) -> list[dict[str, Any]]:
        """Places, newest change first. ``sort``: updated, created, price, price_desc, title, stage."""
        where, params = [], []
        if search_id is not None:
            where.append("p.search_id = ?")
            params.append(search_id)
        if archived_only:
            where.append("p.archived_at IS NOT NULL")
        elif not include_archived:
            where.append("p.archived_at IS NULL")
        if not include_hidden:
            where.append("p.hidden = 0")
        if stage:
            stages = [stage] if isinstance(stage, str) else list(stage)
            where.append(f"p.stage IN ({','.join('?' * len(stages))})")
            params.extend(stages)
        for word in (query or "").split():
            like = f"%{word.lower()}%"
            where.append("(lower(p.title) LIKE ? OR lower(p.address) LIKE ? OR lower(p.city) LIKE ? OR lower(p.notes) LIKE ? "
                         "OR lower(p.source) LIKE ? OR lower(p.listing_text) LIKE ? OR lower(p.ai_notes) LIKE ?)")
            params.extend([like] * 7)
        order = {"updated": "p.updated_at DESC, p.id DESC", "created": "p.created_at DESC, p.id DESC",
                 "price": "COALESCE(p.price, 1e12), p.id", "price_desc": "COALESCE(p.price, -1) DESC, p.id",
                 "title": "lower(p.title), p.id", "stage": "p.stage_changed_at DESC, p.id"}.get(sort, "p.updated_at DESC, p.id DESC")
        sql = "SELECT p.* FROM places p" + (" WHERE " + " AND ".join(where) if where else "") + f" ORDER BY {order}"
        if limit:
            sql += f" LIMIT {int(limit)}"
        return [_place_out(r) for r in self._rows(sql, params)]  # type: ignore[misc]

    def protected_place_ids(self, search_id: int) -> set[int]:
        """Places that must never be hidden by a deal-breaker: they have a tour, a linked contact, or a stage past
        Saved. A person is already doing something with them."""
        rows = self._rows(
            "SELECT p.id FROM places p WHERE p.search_id = ? AND (p.stage <> 'Saved' "
            "OR EXISTS (SELECT 1 FROM tours t WHERE t.place_id = p.id) "
            "OR EXISTS (SELECT 1 FROM place_contacts pc WHERE pc.place_id = p.id))", (search_id,))
        return {r["id"] for r in rows}

    def count_places(self, search_id: int | None = None, include_archived: bool = False) -> int:
        sql, params = "SELECT COUNT(*) AS n FROM places WHERE 1 = 1", []
        if search_id is not None:
            sql += " AND search_id = ?"
            params.append(search_id)
        if not include_archived:
            sql += " AND archived_at IS NULL"
        return int(self._row(sql, params)["n"])

    def counts_by_stage(self, search_id: int) -> dict[str, int]:
        rows = self._rows("SELECT stage, COUNT(*) AS n FROM places WHERE search_id = ? AND archived_at IS NULL GROUP BY stage",
                          (search_id,))
        return {r["stage"]: r["n"] for r in rows}

    def archive_place(self, place_id: int) -> dict[str, Any]:
        self._require_place(place_id)
        self._exec("UPDATE places SET archived_at = ?, updated_at = ? WHERE id = ?", (now_iso(), now_iso(), place_id))
        return self.get_place(place_id)

    def unarchive_place(self, place_id: int) -> dict[str, Any]:
        self._require_place(place_id)
        self._exec("UPDATE places SET archived_at = NULL, updated_at = ? WHERE id = ?", (now_iso(), place_id))
        return self.get_place(place_id)

    def delete_place(self, place_id: int) -> bool:
        """Delete a place and its timeline, tours, commutes, documents rows and drafts. App window only. The files of
        its documents are not removed here (the page deletes the ``files/<id>`` folder)."""
        self._require_place(place_id)
        self._exec("DELETE FROM places WHERE id = ?", (place_id,))
        return True

    def mark_seen(self, place_id: int) -> None:
        """The user opened this place: it no longer counts as new on Today."""
        self._exec("UPDATE places SET seen_at = COALESCE(seen_at, ?) WHERE id = ?", (now_iso(), place_id))

    def new_places(self, search_id: int | None = None, limit: int = 20) -> list[dict[str, Any]]:
        """Places in the first stage the user hasn't opened yet."""
        sql = "SELECT * FROM places WHERE archived_at IS NULL AND seen_at IS NULL AND stage = 'Saved' AND hidden = 0"
        params: list[Any] = []
        if search_id is not None:
            sql += " AND search_id = ?"
            params.append(search_id)
        sql += " ORDER BY created_at DESC LIMIT ?"
        return [_place_out(r) for r in self._rows(sql, (*params, limit))]  # type: ignore[misc]

    # ------------------------------------------------------------------ commutes
    def set_commute(self, place_id: int, anchor_id: int, mode: str, minutes: Any, source: str = "you") -> dict[str, Any]:
        """Save a commute time. An ``estimate`` never replaces a ``you`` or ``ai`` value; a ``you`` value replaces
        anything; an ``ai`` value never replaces a ``you`` value."""
        self._require_place(place_id)
        self.get_anchor(anchor_id)
        mode = _text(mode, 20).lower()
        if mode not in COMMUTE_MODES:
            raise ValueError(f"A commute is one of: {', '.join(COMMUTE_MODES)}.")
        if source not in COMMUTE_SOURCES:
            raise ValueError("A commute comes from: estimate, you or ai.")
        mins = to_number(minutes, "minutes")
        if mins is None or mins < 0 or mins > 24 * 60:
            raise ValueError("Minutes needs to be a number between 0 and 1440.")
        old = self._row("SELECT * FROM commutes WHERE place_id = ? AND anchor_id = ? AND mode = ?", (place_id, anchor_id, mode))
        if old and source == "estimate" and old["source"] != "estimate":
            return old
        if old and source == "ai" and old["source"] == "you":
            return old
        self._exec("INSERT INTO commutes(place_id, anchor_id, mode, minutes, source, updated_at) VALUES (?, ?, ?, ?, ?, ?) "
                   "ON CONFLICT(place_id, anchor_id, mode) DO UPDATE SET minutes = excluded.minutes, source = excluded.source, "
                   "updated_at = excluded.updated_at", (place_id, anchor_id, mode, mins, source, now_iso()))
        self._touch(place_id)
        return self._row("SELECT * FROM commutes WHERE place_id = ? AND anchor_id = ? AND mode = ?", (place_id, anchor_id, mode))  # type: ignore[return-value]

    def list_commutes(self, place_id: int | None = None, anchor_id: int | None = None) -> list[dict[str, Any]]:
        where, params = [], []
        if place_id is not None:
            where.append("place_id = ?")
            params.append(place_id)
        if anchor_id is not None:
            where.append("anchor_id = ?")
            params.append(anchor_id)
        sql = "SELECT * FROM commutes" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY anchor_id, mode"
        return [{k: (_tidy_num(v) if isinstance(v, float) else v) for k, v in r.items()} for r in self._rows(sql, params)]

    def list_commutes_for_search(self, search_id: int) -> dict[int, list[dict[str, Any]]]:
        """``{place_id: [commute rows]}`` for every place of a search (one query, for boards and maps)."""
        out: dict[int, list[dict[str, Any]]] = {}
        for r in self._rows("SELECT c.* FROM commutes c JOIN places p ON p.id = c.place_id WHERE p.search_id = ?", (search_id,)):
            out.setdefault(r["place_id"], []).append({k: (_tidy_num(v) if isinstance(v, float) else v) for k, v in r.items()})
        return out

    def clear_commute(self, place_id: int, anchor_id: int, mode: str) -> bool:
        """Remove a saved time so the map estimate shows again. App window only."""
        self._exec("DELETE FROM commutes WHERE place_id = ? AND anchor_id = ? AND mode = ?", (place_id, anchor_id, mode))
        return True

    # ------------------------------------------------------------------ custom scores
    def set_custom_score(self, place_id: int, criterion_id: int, score: Any) -> None:
        """The user's 0 to 5 score for a "custom" criterion on one place. Blank removes it."""
        self._require_place(place_id)
        crit = self.get_criterion(criterion_id)
        if crit["kind"] != "custom":
            raise ValueError("Only the things you added yourself take a score you give by hand.")
        n = to_number(score, "score")
        if n is None:
            self._exec("DELETE FROM custom_scores WHERE place_id = ? AND criterion_id = ?", (place_id, criterion_id))
            return
        if not 0 <= n <= 5:
            raise ValueError("Your score is from 0 to 5.")
        self._exec("INSERT INTO custom_scores(place_id, criterion_id, score) VALUES (?, ?, ?) "
                   "ON CONFLICT(place_id, criterion_id) DO UPDATE SET score = excluded.score", (place_id, criterion_id, n))

    def custom_scores(self, place_id: int) -> dict[int, float]:
        return {r["criterion_id"]: _tidy_num(r["score"]) for r in
                self._rows("SELECT criterion_id, score FROM custom_scores WHERE place_id = ?", (place_id,))}

    # ------------------------------------------------------------------ events (a place's timeline)
    def _add_event(self, place_id: int, kind: str, body: str, at: str | None, source: str) -> int:
        kind = kind if kind in EVENT_KINDS else "note"
        source = "ai" if source == "ai" else "you"
        cur = self._exec("INSERT INTO events(place_id, kind, body, at, source) VALUES (?, ?, ?, ?, ?)",
                         (place_id, kind, _text(body, 20_000), at or now_iso(), source))
        return cur.lastrowid  # type: ignore[return-value]

    def add_event(self, place_id: int, kind: str = "note", body: str = "", at: Any = None, source: str = "you") -> dict[str, Any]:
        """Add a line to a place's timeline. ``kind``: note, stage, call, email, text, tour, document, ai."""
        self._require_place(place_id)
        if not _text(body):
            raise ValueError("Write something to add to the timeline.")
        if kind not in EVENT_KINDS:
            raise ValueError(f"A timeline line is one of: {', '.join(EVENT_KINDS)}.")
        with self._write():
            eid = self._add_event(place_id, kind, body, to_utc_iso(at) if at else None, source)
            self._touch(place_id)
        return self._row("SELECT * FROM events WHERE id = ?", (eid,))  # type: ignore[return-value]

    def list_events(self, place_id: int, newest_first: bool = True) -> list[dict[str, Any]]:
        order = "DESC" if newest_first else "ASC"
        return self._rows(f"SELECT * FROM events WHERE place_id = ? ORDER BY at {order}, id {order}", (place_id,))

    def delete_event(self, event_id: int) -> bool:
        self._exec("DELETE FROM events WHERE id = ?", (event_id,))
        return True

    def count_ai_adds_since(self, since_iso: str) -> int:
        """How many places the AI added (not updated) at or after ``since_iso``. Used by the stricter scraping guard
        to cap how many places the AI may add per hour."""
        row = self._row("SELECT COUNT(DISTINCT p.id) AS n FROM places p JOIN events e ON e.place_id = p.id "
                        "WHERE p.created_at >= ? AND e.source = 'ai' AND e.kind = 'stage' AND e.body LIKE 'Added as %'",
                        (since_iso,))
        return int(row["n"]) if row else 0

    # ------------------------------------------------------------------ tours
    def _tour_out(self, row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        try:
            cl = json.loads(row.get("checklist") or "{}")
        except ValueError:
            cl = {}
        row["checklist"] = cl if isinstance(cl, dict) else {}
        return row

    @staticmethod
    def default_tour_checklist() -> dict[str, dict[str, str]]:
        return {item: {"state": "", "note": ""} for item in TOUR_ITEMS}

    @staticmethod
    def _clean_checklist(value: Any) -> dict[str, dict[str, str]]:
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                raise ValueError("The tour checklist needs to be a JSON object.") from None
        if not isinstance(value, dict):
            raise ValueError("The tour checklist needs to be an object of item to ok / issue.")
        out: dict[str, dict[str, str]] = {}
        for item, v in list(value.items())[:60]:
            state, note = (v.get("state", ""), v.get("note", "")) if isinstance(v, dict) else (v, "")
            state = str(state or "").lower()
            if state not in TOUR_STATES:
                raise ValueError("Each tour checklist item is ok, issue or blank.")
            out[_text(item, 80)] = {"state": state, "note": _text(note, 500)}
        return out

    def add_tour(self, place_id: int, starts_at: Any, *, duration_minutes: Any = 30, with_whom: str = "", where_note: str = "",
                 status: str = "booked", checklist: Any = None, rating: Any = None, notes: str = "", by: str = "you",
                 advance: bool = True) -> dict[str, Any]:
        """Book a tour. A rent-mode place still before "Tour booked" moves there (``advance=False`` keeps it)."""
        place = self._require_place(place_id)
        if status not in TOUR_STATUSES:
            raise ValueError(f"A tour is: {', '.join(TOUR_STATUSES)}.")
        mins = to_number(duration_minutes, "duration")
        if mins is None or not 5 <= mins <= 600:
            raise ValueError("A tour lasts between 5 and 600 minutes.")
        cl = self._clean_checklist(checklist) if checklist is not None else self.default_tour_checklist()
        with self._write():
            cur = self._exec("INSERT INTO tours(place_id, starts_at, duration_minutes, with_whom, where_note, status, checklist, "
                             "rating, notes, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                             (place_id, to_utc_iso(starts_at), int(mins), _text(with_whom, 200), _text(where_note, 300), status,
                              json.dumps(cl), self._rating(rating), _text(notes, 10_000), now_iso()))
            self._add_event(place_id, "tour", f"Tour {status}" + (f" with {_text(with_whom, 100)}" if with_whom else ""), None, by)
            self._touch(place_id)
            if advance and status == "booked":
                self._advance_to(place, "Tour booked", by, "Because a tour was booked.")
        return self.get_tour(cur.lastrowid)

    @staticmethod
    def _rating(value: Any) -> int | None:
        n = to_number(value, "rating")
        if n is None:
            return None
        if not 1 <= n <= 5:
            raise ValueError("A rating is from 1 to 5.")
        return int(n)

    def _advance_to(self, place: dict[str, Any], stage: str, by: str, note: str = "") -> None:
        """Move a place forward to ``stage`` only if that is ahead of where it is (rent mode only)."""
        mode = self._mode_of(place["search_id"])
        fresh = self._require_place(place["id"])
        if mode == "rent" and stage in st.stages_for(mode) and st.is_forward(mode, fresh["stage"], stage):
            self.move_stage(place["id"], stage, by_ai=(by == "ai"), note=note, auto=True)

    def get_tour(self, tour_id: int) -> dict[str, Any]:
        row = self._tour_out(self._row("SELECT * FROM tours WHERE id = ?", (tour_id,)))
        if row is None:
            raise NotFound(f"Tour {tour_id} doesn't exist.")
        return row

    def update_tour(self, tour_id: int, *, by: str = "you", **fields: Any) -> dict[str, Any]:
        """Change a tour: starts_at, duration_minutes, with_whom, where_note, status, checklist, rating, notes."""
        cur = self.get_tour(tour_id)
        values: dict[str, Any] = {}
        if "starts_at" in fields:
            values["starts_at"] = to_utc_iso(fields["starts_at"])
        if "duration_minutes" in fields:
            mins = to_number(fields["duration_minutes"], "duration")
            if mins is None or not 5 <= mins <= 600:
                raise ValueError("A tour lasts between 5 and 600 minutes.")
            values["duration_minutes"] = int(mins)
        for key, limit in (("with_whom", 200), ("where_note", 300), ("notes", 10_000)):
            if key in fields:
                values[key] = _text(fields[key], limit)
        if "status" in fields:
            if fields["status"] not in TOUR_STATUSES:
                raise ValueError(f"A tour is: {', '.join(TOUR_STATUSES)}.")
            values["status"] = fields["status"]
        if "checklist" in fields:
            values["checklist"] = json.dumps(self._clean_checklist(fields["checklist"]))
        if "rating" in fields:
            values["rating"] = self._rating(fields["rating"])
        with self._write():
            if values:
                self._exec(f"UPDATE tours SET {', '.join(f'{k} = ?' for k in values)} WHERE id = ?", (*values.values(), tour_id))
                self._touch(cur["place_id"])
            if values.get("status") == "done" and cur["status"] != "done":
                self._add_event(cur["place_id"], "tour", "Tour done", None, by)
                self._advance_to(self._require_place(cur["place_id"]), "Toured", by, "Because the tour was marked done.")
        return self.get_tour(tour_id)

    def list_tours(self, place_id: int | None = None, *, start: Any = None, end: Any = None, status: str | None = None,
                   search_id: int | None = None) -> list[dict[str, Any]]:
        """Tours by start time. ``start``/``end`` (inclusive/exclusive) are dates or times; rows also carry the
        place's ``title``, ``address`` and ``search_id``."""
        where, params = ["p.archived_at IS NULL"], []
        if place_id is not None:
            where.append("t.place_id = ?")
            params.append(place_id)
        if search_id is not None:
            where.append("p.search_id = ?")
            params.append(search_id)
        if status:
            where.append("t.status = ?")
            params.append(status)
        if start:
            where.append("t.starts_at >= ?")
            params.append(to_utc_iso(start))
        if end:
            where.append("t.starts_at < ?")
            params.append(to_utc_iso(end))
        sql = ("SELECT t.*, p.title, p.address, p.search_id FROM tours t JOIN places p ON p.id = t.place_id WHERE "
               + " AND ".join(where) + " ORDER BY t.starts_at, t.id")
        return [self._tour_out(r) for r in self._rows(sql, params)]  # type: ignore[misc]

    def upcoming_tours(self, days: int = 7, now: datetime | None = None, search_id: int | None = None) -> list[dict[str, Any]]:
        """Booked tours starting from now to ``days`` days ahead."""
        now = now or datetime.now(timezone.utc)
        return self.list_tours(start=now, end=now + timedelta(days=days), status="booked", search_id=search_id)

    def delete_tour(self, tour_id: int) -> bool:
        self.get_tour(tour_id)
        self._exec("DELETE FROM tours WHERE id = ?", (tour_id,))
        return True

    def overlapping_tour(self, tour: dict[str, Any], buffer_minutes: int = 0) -> dict[str, Any] | None:
        """Another booked tour that overlaps ``tour``, or starts or ends within ``buffer_minutes`` of it. The web
        form uses 60 so a person is warned about two tours an hour apart; None when the way is clear."""
        start = parse_iso(tour["starts_at"])
        if start is None:
            return None
        end = start + timedelta(minutes=int(tour.get("duration_minutes") or 30))
        pad = timedelta(minutes=buffer_minutes)
        for o in self.list_tours(status="booked"):
            if o["id"] == tour["id"]:
                continue
            s2 = parse_iso(o["starts_at"])
            if s2 is not None and s2 < end + pad and s2 + timedelta(minutes=int(o["duration_minutes"])) > start - pad:
                return o
        return None

    # ------------------------------------------------------------------ key dates (per place)
    @staticmethod
    def date_kinds(mode: str) -> tuple[str, ...]:
        return PLACE_DATE_KINDS_BUY if mode == "buy" else PLACE_DATE_KINDS_RENT

    def add_place_date(self, place_id: int, kind: str, day: Any, *, time: str = "", note: str = "") -> dict[str, Any]:
        """Save a key date for a place. ``kind`` is one of the mode's kinds or 'other'; ``time`` is 'HH:MM' or blank."""
        place = self._require_place(place_id)
        kinds = self.date_kinds(self._mode_of(place["search_id"]))
        kind = str(kind or "other").strip().lower().replace(" ", "_")
        if kind not in kinds:
            raise ValueError("Pick one of: " + ", ".join(PLACE_DATE_LABELS[k].lower() for k in kinds) + ".")
        d = clean_date(day, "date")
        if not d:
            raise ValueError("Pick the day for this date.")
        t = str(time or "").strip()
        if t:
            try:
                datetime.strptime(t, "%H:%M")
            except ValueError:
                raise ValueError("Write the time like 14:30, or leave it blank.") from None
        with self._write():
            cur = self._exec("INSERT INTO place_dates(place_id, kind, date, time, note) VALUES (?, ?, ?, ?, ?)",
                             (place_id, kind, d, t, _text(note, 300)))
            self._add_event(place_id, "note", f"Added a date: {PLACE_DATE_LABELS[kind]} on {d}", None, "you")
            self._touch(place_id)
        return self._row("SELECT * FROM place_dates WHERE id = ?", (cur.lastrowid,))  # type: ignore[return-value]

    def get_place_date(self, date_id: int) -> dict[str, Any]:
        row = self._row("SELECT * FROM place_dates WHERE id = ?", (date_id,))
        if row is None:
            raise NotFound(f"Date {date_id} doesn't exist.")
        return row

    def delete_place_date(self, date_id: int) -> bool:
        self.get_place_date(date_id)
        self._exec("DELETE FROM place_dates WHERE id = ?", (date_id,))
        return True

    def list_place_dates(self, place_id: int | None = None, search_id: int | None = None) -> list[dict[str, Any]]:
        """Key dates by day. Rows also carry the place's ``title`` and ``stage``. Archived places are left out."""
        where, params = ["p.archived_at IS NULL"], []
        if place_id is not None:
            where.append("d.place_id = ?")
            params.append(place_id)
        if search_id is not None:
            where.append("p.search_id = ?")
            params.append(search_id)
        rows = self._rows("SELECT d.*, p.title, p.stage FROM place_dates d JOIN places p ON p.id = d.place_id WHERE "
                          + " AND ".join(where) + " ORDER BY d.date, d.time, d.id", params)
        for r in rows:
            r["label"] = PLACE_DATE_LABELS.get(r["kind"], "Date")
        return rows

    def upcoming_place_dates(self, days: int = 14, today: str | None = None, search_id: int | None = None) -> list[dict[str, Any]]:
        """Key dates from today through ``days`` days ahead, for places that are still open."""
        start = date.fromisoformat(today) if today else date.today()
        end = start + timedelta(days=days)
        return [r for r in self.list_place_dates(search_id=search_id)
                if r["stage"] != st.PASSED and start.isoformat() <= r["date"] <= end.isoformat()]

    # ------------------------------------------------------------------ contacts
    def add_contact(self, name: str, *, role: str = "other", company: str = "", email: str = "", phone: str = "",
                    notes: str = "", is_sample: bool = False) -> dict[str, Any]:
        name = _text(name, 200)
        if not name:
            raise ValueError("A contact needs a name.")
        role = _text(role or "other", 40).lower()
        if role not in CONTACT_ROLES:
            raise ValueError(f"A contact's role is one of: {', '.join(CONTACT_ROLES)}.")
        now = now_iso()
        cur = self._exec("INSERT INTO contacts(name, role, company, email, phone, notes, is_sample, created_at, updated_at) "
                         "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (name, role, _text(company, 200), _text(email, 320), _text(phone, 50), _text(notes, 20_000),
                          1 if is_sample else 0, now, now))
        return self.get_contact(cur.lastrowid)

    def get_contact(self, contact_id: int) -> dict[str, Any]:
        row = self._row("SELECT * FROM contacts WHERE id = ?", (contact_id,))
        if row is None:
            raise NotFound(f"Contact {contact_id} doesn't exist.")
        return row

    def update_contact(self, contact_id: int, **fields: Any) -> dict[str, Any]:
        self.get_contact(contact_id)
        values: dict[str, Any] = {}
        for key, limit in (("name", 200), ("company", 200), ("email", 320), ("phone", 50), ("notes", 20_000)):
            if key in fields:
                values[key] = _text(fields[key], limit)
        if "name" in values and not values["name"]:
            raise ValueError("A contact needs a name.")
        if "role" in fields:
            role = _text(fields["role"], 40).lower()
            if role not in CONTACT_ROLES:
                raise ValueError(f"A contact's role is one of: {', '.join(CONTACT_ROLES)}.")
            values["role"] = role
        if values:
            values["updated_at"] = now_iso()
            self._exec(f"UPDATE contacts SET {', '.join(f'{k} = ?' for k in values)} WHERE id = ?", (*values.values(), contact_id))
        return self.get_contact(contact_id)

    def list_contacts(self, query: str | None = None, place_id: int | None = None) -> list[dict[str, Any]]:
        where, params = [], []
        join = ""
        if place_id is not None:
            join = " JOIN place_contacts pc ON pc.contact_id = c.id"
            where.append("pc.place_id = ?")
            params.append(place_id)
        for word in (query or "").split():
            like = f"%{word.lower()}%"
            where.append("(lower(c.name) LIKE ? OR lower(c.company) LIKE ? OR lower(c.email) LIKE ? OR lower(c.notes) LIKE ?)")
            params.extend([like] * 4)
        sql = f"SELECT c.* FROM contacts c{join}" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY lower(c.name), c.id"
        return self._rows(sql, params)

    def delete_contact(self, contact_id: int) -> bool:
        self.get_contact(contact_id)
        self._exec("DELETE FROM contacts WHERE id = ?", (contact_id,))
        return True

    def link_contact(self, place_id: int, contact_id: int) -> None:
        self._require_place(place_id)
        self.get_contact(contact_id)
        self._exec("INSERT OR IGNORE INTO place_contacts(place_id, contact_id) VALUES (?, ?)", (place_id, contact_id))

    def unlink_contact(self, place_id: int, contact_id: int) -> None:
        self._exec("DELETE FROM place_contacts WHERE place_id = ? AND contact_id = ?", (place_id, contact_id))

    def contacts_for_place(self, place_id: int) -> list[dict[str, Any]]:
        return self.list_contacts(place_id=place_id)

    def places_for_contact(self, contact_id: int) -> list[dict[str, Any]]:
        return [_place_out(r) for r in self._rows(
            "SELECT p.* FROM places p JOIN place_contacts pc ON pc.place_id = p.id WHERE pc.contact_id = ? "
            "AND p.archived_at IS NULL ORDER BY p.title", (contact_id,))]  # type: ignore[misc]

    def log_contact(self, contact_id: int, kind: str = "email", body: str = "", *, direction: str = "out",
                    place_id: int | None = None, at: Any = None) -> dict[str, Any]:
        """Note a call, email, text or visit with a contact. ``direction`` out means you contacted them."""
        self.get_contact(contact_id)
        kind = _text(kind or "email", 20).lower()
        if kind not in CONTACT_LOG_KINDS:
            raise ValueError(f"A contact log entry is one of: {', '.join(CONTACT_LOG_KINDS)}.")
        if direction not in DIRECTIONS:
            raise ValueError("Direction is out (you wrote) or in (they wrote).")
        if place_id is not None:
            self._require_place(place_id)
        with self._write():
            cur = self._exec("INSERT INTO contact_log(contact_id, place_id, at, kind, body, direction) VALUES (?, ?, ?, ?, ?, ?)",
                             (contact_id, place_id, to_utc_iso(at) if at else now_iso(), kind, _text(body, 5000), direction))
            if place_id is not None:
                self.link_contact(place_id, contact_id)
                self._touch(place_id)
        return self._row("SELECT * FROM contact_log WHERE id = ?", (cur.lastrowid,))  # type: ignore[return-value]

    def list_contact_log(self, contact_id: int | None = None, place_id: int | None = None, newest_first: bool = True) -> list[dict[str, Any]]:
        where, params = [], []
        if contact_id is not None:
            where.append("contact_id = ?")
            params.append(contact_id)
        if place_id is not None:
            where.append("place_id = ?")
            params.append(place_id)
        order = "DESC" if newest_first else "ASC"
        sql = "SELECT * FROM contact_log" + (" WHERE " + " AND ".join(where) if where else "") + f" ORDER BY at {order}, id {order}"
        return self._rows(sql, params)

    def delete_contact_log(self, log_id: int) -> bool:
        self._exec("DELETE FROM contact_log WHERE id = ?", (log_id,))
        return True

    def waiting_on_reply(self, days: int | None = None, now: datetime | None = None) -> list[dict[str, Any]]:
        """Contacts whose latest log entry is one you sent (``out``) and is older than ``days`` (default: the
        follow_up_days setting). Each row: ``contact``, ``last`` (the log entry), ``place`` (or None), ``days``."""
        days = self.get_setting_int("follow_up_days", 3) if days is None else days
        now = now or datetime.now(timezone.utc)
        out = []
        for c in self.list_contacts():
            last = self._row("SELECT * FROM contact_log WHERE contact_id = ? ORDER BY at DESC, id DESC LIMIT 1", (c["id"],))
            if not last or last["direction"] != "out":
                continue
            when = parse_iso(last["at"])
            if when is None or now - when < timedelta(days=days):
                continue
            place = None
            if last["place_id"]:
                row = self._row("SELECT * FROM places WHERE id = ? AND archived_at IS NULL", (last["place_id"],))
                place = _place_out(row)
                if row is None:
                    continue
            out.append({"contact": c, "last": last, "place": place, "days": max(0, calendar_days_ago(when, now) or 0)})
        out.sort(key=lambda r: r["last"]["at"])
        return out

    # ------------------------------------------------------------------ documents (rows only; files are the page's job)
    def add_document(self, place_id: int, stored_name: str, original_name: str, kind: str = "other", size: int = 0) -> dict[str, Any]:
        self._require_place(place_id)
        if kind not in DOCUMENT_KINDS:
            raise ValueError(f"A document is one of: {', '.join(DOCUMENT_KINDS)}.")
        if size < 0 or size > UPLOAD_LIMIT_BYTES:
            raise ValueError("Files can be up to 20 MB.")
        stored = _text(stored_name, 200)
        if not stored or "/" in stored or "\\" in stored or stored.startswith("."):
            raise ValueError("That stored file name isn't safe.")
        with self._write():
            cur = self._exec("INSERT INTO documents(place_id, stored_name, original_name, kind, size, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                             (place_id, stored, _text(original_name, 300), kind, int(size), now_iso()))
            self._add_event(place_id, "document", f"Added {kind} document: {_text(original_name, 200)}", None, "you")
            self._touch(place_id)
        return self.get_document(cur.lastrowid)

    def get_document(self, document_id: int) -> dict[str, Any]:
        row = self._row("SELECT * FROM documents WHERE id = ?", (document_id,))
        if row is None:
            raise NotFound(f"Document {document_id} doesn't exist.")
        return row

    def update_document(self, document_id: int, *, kind: str | None = None, original_name: str | None = None) -> dict[str, Any]:
        self.get_document(document_id)
        if kind is not None:
            if kind not in DOCUMENT_KINDS:
                raise ValueError(f"A document is one of: {', '.join(DOCUMENT_KINDS)}.")
            self._exec("UPDATE documents SET kind = ? WHERE id = ?", (kind, document_id))
        if original_name is not None and _text(original_name):
            self._exec("UPDATE documents SET original_name = ? WHERE id = ?", (_text(original_name, 300), document_id))
        return self.get_document(document_id)

    def list_documents(self, place_id: int | None = None) -> list[dict[str, Any]]:
        if place_id is None:
            return self._rows("SELECT * FROM documents ORDER BY created_at DESC, id DESC")
        return self._rows("SELECT * FROM documents WHERE place_id = ? ORDER BY created_at DESC, id DESC", (place_id,))

    def delete_document(self, document_id: int) -> dict[str, Any]:
        """Remove the row and return it, so the caller can delete the file. App window only."""
        row = self.get_document(document_id)
        self._exec("DELETE FROM documents WHERE id = ?", (document_id,))
        return row

    # ------------------------------------------------------------------ application checklist
    def list_checklist(self) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM checklist_items ORDER BY sort_order, id")

    @staticmethod
    def _pet_item_hidden(row: dict[str, Any], search: dict[str, Any] | None) -> bool:
        """The untouched starter item "Pet records" only shows when the search has pets."""
        if search is None or search.get("pet_kind"):
            return False
        return row["label"].strip().lower() == "pet records" and not row["note"] and not row["done"]

    def visible_checklist(self, search: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """The list as a person sees it: without the starter "Pet records" item when the search has no pets."""
        search = search if search is not None else self.current_search()
        return [r for r in self.list_checklist() if not self._pet_item_hidden(r, search)]

    def add_checklist_item(self, label: str, note: str = "") -> dict[str, Any]:
        label = _text(label, 200)
        if not label:
            raise ValueError("A checklist item needs a label.")
        with self._write():
            order = self._row("SELECT COALESCE(MAX(sort_order), -1) + 1 AS n FROM checklist_items")["n"]
            cur = self._exec("INSERT INTO checklist_items(label, note, done, sort_order) VALUES (?, ?, 0, ?)",
                             (label, _text(note, 1000), order))
        return self.get_checklist_item(cur.lastrowid)

    def get_checklist_item(self, item_id: int) -> dict[str, Any]:
        row = self._row("SELECT * FROM checklist_items WHERE id = ?", (item_id,))
        if row is None:
            raise NotFound(f"Checklist item {item_id} doesn't exist.")
        return row

    def update_checklist_item(self, item_id: int, **fields: Any) -> dict[str, Any]:
        self.get_checklist_item(item_id)
        values: dict[str, Any] = {}
        if "label" in fields:
            values["label"] = _text(fields["label"], 200)
            if not values["label"]:
                raise ValueError("A checklist item needs a label.")
        if "note" in fields:
            values["note"] = _text(fields["note"], 1000)
        if "done" in fields:
            values["done"] = 1 if clean_bool(fields["done"]) else 0
        if values:
            self._exec(f"UPDATE checklist_items SET {', '.join(f'{k} = ?' for k in values)} WHERE id = ?", (*values.values(), item_id))
        return self.get_checklist_item(item_id)

    def move_checklist_item(self, item_id: int, direction: int) -> None:
        """Swap an item with its neighbour: -1 up, +1 down."""
        items = self.list_checklist()
        ids = [i["id"] for i in items]
        if item_id not in ids:
            raise NotFound(f"Checklist item {item_id} doesn't exist.")
        i, j = ids.index(item_id), ids.index(item_id) + (1 if direction > 0 else -1)
        if not 0 <= j < len(ids):
            return
        ids[i], ids[j] = ids[j], ids[i]
        with self._write():
            for order, iid in enumerate(ids):
                self._exec("UPDATE checklist_items SET sort_order = ? WHERE id = ?", (order, iid))

    def delete_checklist_item(self, item_id: int) -> bool:
        self.get_checklist_item(item_id)
        self._exec("DELETE FROM checklist_items WHERE id = ?", (item_id,))
        return True

    # ------------------------------------------------------------------ per-place application checklist
    def place_checklist(self, place_id: int) -> list[dict[str, Any]]:
        """The global checklist items with ``done_here`` (ticked for this place) and ``done_at``."""
        self._require_place(place_id)
        rows = self._rows("SELECT c.*, pc.done_at AS done_at FROM checklist_items c LEFT JOIN place_checklist pc "
                          "ON pc.item_id = c.id AND pc.place_id = ? ORDER BY c.sort_order, c.id", (place_id,))
        search = self.get_search(self.get_place(place_id)["search_id"])
        rows = [r for r in rows if not self._pet_item_hidden(r, search)]
        for r in rows:
            r["done_here"] = bool(r["done_at"])
        return rows

    def set_place_checklist(self, place_id: int, item_id: int, done: Any) -> None:
        """Tick or untick one checklist item for one place."""
        self._require_place(place_id)
        self.get_checklist_item(item_id)
        if clean_bool(done):
            self._exec("INSERT INTO place_checklist(place_id, item_id, done_at) VALUES (?, ?, ?) "
                       "ON CONFLICT(place_id, item_id) DO NOTHING", (place_id, item_id, now_iso()))
        else:
            self._exec("DELETE FROM place_checklist WHERE place_id = ? AND item_id = ?", (place_id, item_id))

    def application_deadline(self, place_id: int) -> dict[str, Any] | None:
        """The key date of kind application_deadline to show: the next one from today, else the latest one that passed."""
        rows = [r for r in self.list_place_dates(place_id) if r["kind"] == "application_deadline"]
        if not rows:
            return None
        today = date.today().isoformat()
        return next((r for r in rows if r["date"] >= today), rows[-1])

    def place_checklist_left(self, place_id: int) -> int:
        """How many checklist items are not ticked yet for this place."""
        return sum(1 for r in self.place_checklist(place_id) if not r["done_here"])

    # ------------------------------------------------------------------ AI drafts
    def add_draft(self, place_id: int, kind: str, body: str, model: str = "") -> dict[str, Any]:
        self._require_place(place_id)
        if kind not in DRAFT_KINDS:
            raise ValueError(f"A draft is one of: {', '.join(DRAFT_KINDS)}.")
        cur = self._exec("INSERT INTO ai_drafts(place_id, kind, body, model, created_at) VALUES (?, ?, ?, ?, ?)",
                         (place_id, kind, _text(body, 50_000), _text(model, 100), now_iso()))
        return self.get_draft(cur.lastrowid)

    def get_draft(self, draft_id: int) -> dict[str, Any]:
        row = self._row("SELECT * FROM ai_drafts WHERE id = ?", (draft_id,))
        if row is None:
            raise NotFound(f"Draft {draft_id} doesn't exist.")
        return row

    def list_drafts(self, place_id: int, kind: str | None = None) -> list[dict[str, Any]]:
        if kind:
            return self._rows("SELECT * FROM ai_drafts WHERE place_id = ? AND kind = ? ORDER BY created_at DESC, id DESC", (place_id, kind))
        return self._rows("SELECT * FROM ai_drafts WHERE place_id = ? ORDER BY created_at DESC, id DESC", (place_id,))

    def delete_draft(self, draft_id: int) -> bool:
        self._exec("DELETE FROM ai_drafts WHERE id = ?", (draft_id,))
        return True

    # ------------------------------------------------------------------ dates that matter
    def upcoming_dates(self, days: int = 14, today: str | None = None, search_id: int | None = None) -> list[dict[str, Any]]:
        """Application and lease dates inside the next ``days`` days: places with ``available_from`` or
        ``lease_start`` coming up, in stages from Applied on. Rows: ``{"place", "kind", "label", "date"}``."""
        start = date.fromisoformat(today) if today else date.today()
        end = start + timedelta(days=days)
        out = []
        for p in self.list_places(search_id):
            if p["stage"] in (st.PASSED,):
                continue
            mode = self._mode_of(p["search_id"])
            applied = st.stage_index(mode, p["stage"]) >= st.stage_index(mode, "Applied" if mode == "rent" else "Offer drafted")
            for key, label in (("lease_start", "Lease starts"), ("available_from", "Available")):
                value = p.get(key)
                if not value or (key == "available_from" and not applied):
                    continue
                try:
                    d = date.fromisoformat(value)
                except ValueError:
                    continue
                if start <= d <= end:
                    out.append({"place": p, "kind": key, "label": label, "date": value})
        out.sort(key=lambda r: r["date"])
        return out

    # ------------------------------------------------------------------ sample data
    def has_sample_data(self) -> bool:
        return bool(self._row("SELECT 1 AS x FROM searches WHERE is_sample = 1 UNION SELECT 1 FROM places WHERE is_sample = 1 "
                              "UNION SELECT 1 FROM anchors WHERE is_sample = 1 UNION SELECT 1 FROM contacts WHERE is_sample = 1 LIMIT 1"))

    def remove_sample_data(self) -> dict[str, int]:
        """Delete everything marked ``is_sample`` (searches with their criteria, places with everything on them,
        anchors, contacts). The user's own rows are never touched. App window only."""
        counts = {}
        with self._write():
            counts["places"] = self._exec("DELETE FROM places WHERE is_sample = 1").rowcount
            counts["searches"] = self._exec("DELETE FROM searches WHERE is_sample = 1").rowcount
            counts["anchors"] = self._exec("DELETE FROM anchors WHERE is_sample = 1").rowcount
            counts["contacts"] = self._exec("DELETE FROM contacts WHERE is_sample = 1").rowcount
            saved = self.get_setting("current_search_id", "")
            if saved and not self._row("SELECT 1 AS x FROM searches WHERE id = ?", (int(saved) if saved.isdigit() else -1,)):
                self.set_setting("current_search_id", "")
        return counts

    # ------------------------------------------------------------------ everything (for exports)
    def export_all(self) -> dict[str, list[dict[str, Any]]]:
        """Every row of the main tables, for a JSON or CSV export you read yourself. No settings and no AI key."""
        out: dict[str, list[dict[str, Any]]] = {}
        for table in ("searches", "criteria", "anchors", "places", "commutes", "events", "tours", "contacts", "place_contacts",
                      "contact_log", "documents", "checklist_items", "ai_drafts", "place_dates", "place_opinions"):
            out[table] = self._rows(f"SELECT * FROM {table}")
        return out


def _tidy_row(row: dict[str, Any]) -> dict[str, Any]:
    out = {k: (_tidy_num(v) if isinstance(v, float) else v) for k, v in row.items()}
    if isinstance(out.get("people_names"), str):
        try:
            names = json.loads(out["people_names"])
        except ValueError:
            names = []
        out["people_names"] = [str(n) for n in names] if isinstance(names, list) else []
    return out


def clean_people_names(value: Any) -> list[str]:
    """A list of names from a list or from text with one name per line or separated by commas. Blank names and
    repeats (ignoring case) are dropped, each name is cut to 40 characters, at most 20 names."""
    if value is None:
        return []
    items = value if isinstance(value, (list, tuple)) else re.split(r"[\n,;]", str(value))
    out: list[str] = []
    for raw in items:
        name = " ".join(str(raw or "").split())[:PERSON_NAME_MAX]
        if name and name.lower() not in (n.lower() for n in out):
            out.append(name)
    return out[:MAX_PEOPLE]


def people_slots(search: dict[str, Any]) -> list[str]:
    """The names of the people sharing a search: the names given, then 'Person 3' and so on up to ``people``.
    One person (or none) means no names are needed, so the list is empty."""
    n = int(search.get("people") or 1)
    if n < 2:
        return []
    names = list(search.get("people_names") or [])[:n]
    taken = {x.lower() for x in names}
    i = 1
    while len(names) < n:
        label = f"Person {i}"
        i += 1
        if label.lower() not in taken:
            names.append(label)
    return names


def _ev_cut(value: Any, limit: int = AI_EVENT_TEXT_MAX) -> str:
    text = str(value if value is not None else "").strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "..."
