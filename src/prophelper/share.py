"""Sharing with other people: a comparison as one safe web page, and a search as a file a housemate can read back in.
No web framework code here (the routes are in ``routes_compare.py`` and ``routes_data.py``).

Two things go out of the app, and both leave things OUT on purpose:

* ``comparison_html``: one self-contained page (styles inline, no scripts, no outside links, no pictures, no map).
  Contacts, phone numbers, emails, AI notes and documents are never in it. The person's own notes only when they ask.
* ``export_search`` / ``read_export``: a JSON file with the search, what matters, the important places it uses and the
  places with their facts and listing text. No contacts, documents, notes, ratings, AI text, stage or AI key.

Everything that comes IN from a file is treated as untrusted text: size capped, shape checked, only known keys read,
every value cleaned again by the same rules as a form (see ``Store``).
"""
from __future__ import annotations

import json
import re
import secrets
import time
from datetime import date
from typing import Any

from . import compare, helpers
from .store import (COMMUTE_MODES, has_userinfo, PLACE_INT, PLACE_REAL, PLACE_TEXT, Store, normalize_url, people_slots)

FORMAT_NAME = "property-helper-search"
FORMAT_VERSION = 1
MAX_IMPORT_BYTES = 5 * 1024 * 1024
MAX_PLACES, MAX_CRITERIA, MAX_ANCHORS = 500, 60, 60

# What a shared file never carries: what the person wrote, what an AI wrote, and where they are in their search.
LEFT_OUT_PLACE_FIELDS = {"notes", "ai_notes", "fit_notes", "red_flags", "rating", "fit_score"}
SHARED_TEXT = tuple(f for f in PLACE_TEXT if f not in LEFT_OUT_PLACE_FIELDS)
SHARED_REAL = PLACE_REAL
SHARED_INT = tuple(f for f in PLACE_INT if f not in LEFT_OUT_PLACE_FIELDS)

# Rows of Compare that are about the person, not the place.
_PERSONAL_ROWS = {"stage", "rating", "opinions"}
_PROVENANCE = re.compile(r" \((?:you|added by Claude)\)")


def _is_personal(key: str) -> bool:
    """Each person's own rating row ("person-Sam") is as personal as the rating rows."""
    return key in _PERSONAL_ROWS or key.startswith("person-")


# --------------------------------------------------------------------------- the page to share
_URL_START = re.compile(r"(https?):(?=//)", re.IGNORECASE)


def defang(html: str) -> str:
    """Break 'http://' and 'https://' in the text of the page (a zero-width space after the colon) so the file holds no
    web address a browser or a person could follow by accident. The text still reads the same."""
    return _URL_START.sub(r"\1:&#8203;", html)


def _text_cell(text: str) -> dict[str, Any]:
    return compare._cell(text or None)


def comparison_sections(places: list[dict[str, Any]], include_notes: bool = False) -> list[dict[str, Any]]:
    """Compare's sections for these enriched places, without the personal rows, plus cash at move-in and the
    possible-scam marks. With ``include_notes`` the person's own notes and their people's ratings are added."""
    sections = []
    for sec in compare.build_rows(places):
        rows = [r for r in sec["rows"] if include_notes or not _is_personal(r["key"])]
        for r in rows:
            if r["key"].startswith("commute-"):  # who typed a commute (you, Claude) is not for the person reading a copy
                for c in r["cells"]:
                    c["text"] = _PROVENANCE.sub("", c["text"])
        if rows:
            sections.append({"title": sec["title"], "rows": rows})
    scam_cells = []
    for p in places:
        flags = list(p.get("flags") or [])
        if p.get("possible_scam"):
            scam_cells.append(_text_cell("Check first: possible scam. " + (" ".join(flags[:3]) if flags else "")))
        elif flags:
            scam_cells.append(_text_cell(" ".join(flags[:3])))
        else:
            scam_cells.append(_text_cell("Nothing found"))
    sections.append({"title": "Possible scam signs", "rows": [compare._row("scam", "What to check", scam_cells)]})
    if include_notes:
        note_cells = [_text_cell((p.get("notes") or "").strip()[:2000]) for p in places]
        opinion_cells = []
        for p in places:
            lines = [f"{o['person']}: {o['note']}" for o in p.get("opinion_rows") or [] if o["note"]]
            opinion_cells.append(_text_cell("\n".join(lines)))
        rows = [compare._row("notes", "My notes", note_cells, only_if_any=True),
                compare._row("people", "What each person wrote", opinion_cells, only_if_any=True)]
        rows = [r for r in rows if r]
        if rows:
            sections.append({"title": "My notes", "rows": rows})
    return sections


def comparison_html(templates: Any, places: list[dict[str, Any]], include_notes: bool = False) -> str:
    """The shareable page as one string. ``templates`` is the app's Jinja environment holder (``app.state.templates``)."""
    sections = comparison_sections(places, include_notes)
    summary = compare.summary_lines(places, sections)
    html = templates.get_template("share.html").render(places=places, sections=sections, summary=summary,
                                                       include_notes=include_notes, made_on=helpers.day_text(helpers.today(), True))
    return defang(html)


def comparison_filename() -> str:
    return f"property-helper-comparison-{date.today().isoformat()}.html"


# --------------------------------------------------------------------------- export a search
def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:40] or "search"


def export_filename(search: dict[str, Any]) -> str:
    return f"property-helper-search-{_slug(search['name'])}-{date.today().isoformat()}.json"


def export_search(store: Store, search_id: int) -> dict[str, Any]:
    """The search as a plain dict, ready for ``json.dumps``. See the module text for what is left out."""
    search = store.get_search(search_id)
    criteria = store.list_criteria(search_id)
    places = store.list_places(search_id)
    commutes = store.list_commutes_for_search(search_id)
    anchors_by_id = {a["id"]: a for a in store.list_anchors(search_id)}
    used: list[int] = []

    def anchor_index(anchor_id: Any) -> int | None:
        try:
            aid = int(anchor_id)
        except (TypeError, ValueError):
            return None
        if aid not in anchors_by_id:
            return None
        if aid not in used:
            used.append(aid)
        return used.index(aid)

    crit_out = []
    for c in criteria:
        target = dict(c["target"])
        if c["kind"] == "commute":
            idx = anchor_index(target.pop("anchor_id", None))
            if idx is not None:
                target["anchor"] = idx
        crit_out.append({"kind": c["kind"], "label": c["label"], "weight": c["weight"], "dealbreaker": bool(c["dealbreaker"]),
                         "target": target})
    places_out = []
    for p in places:
        item: dict[str, Any] = {}
        for key in (*SHARED_TEXT, *SHARED_REAL, *SHARED_INT):
            if p.get(key) not in (None, ""):
                item[key] = p[key]
        if p.get("photo_urls"):
            item["photo_urls"] = list(p["photo_urls"])
        if p.get("dishwasher") is not None:
            item["dishwasher"] = bool(p["dishwasher"])
        if p.get("application_fee_per_adult"):
            item["application_fee_per_adult"] = True
        cm = []
        for c in commutes.get(p["id"], []):
            idx = anchor_index(c["anchor_id"])
            if idx is not None:
                cm.append({"anchor": idx, "mode": c["mode"], "minutes": c["minutes"]})
        if cm:
            item["commutes"] = cm
        places_out.append(item)
    anchors_out = [{k: anchors_by_id[a][k] for k in ("name", "address", "lat", "lng")} for a in used]
    return {
        "format": FORMAT_NAME, "version": FORMAT_VERSION, "exported_on": date.today().isoformat(),
        "search": {"name": search["name"], "mode": search["mode"], "area": search["area"], "move_in": search["move_in"],
                   "target_close": search["target_close"], "budget_max": search["budget_max"],
                   "hide_dealbreakers": bool(search["hide_dealbreakers"]), "people": search["people"], "adults": search.get("adults"), "down_payment_pct": search.get("down_payment_pct"),
                   "people_names": list(search.get("people_names") or [])},
        "criteria": crit_out, "anchors": anchors_out, "places": places_out,
    }


def export_bytes(store: Store, search_id: int) -> bytes:
    return json.dumps(export_search(store, search_id), indent=1, ensure_ascii=False).encode("utf-8")


# --------------------------------------------------------------------------- read one back
class NotAnExport(ValueError):
    """Plain words for why a file can't be read as a shared search."""


def read_export(data: bytes) -> dict[str, Any]:
    """Check an uploaded file and return it as a dict with the same shape ``export_search`` makes. Nothing is written.
    Raises ``NotAnExport`` (plain words) for a file that is too big, not JSON, not from this app or too large inside."""
    if len(data) > MAX_IMPORT_BYTES:
        raise NotAnExport("That file is too big (limit 5 MB). A shared search is usually much smaller.")
    try:
        doc = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise NotAnExport("That isn't a shared search. Choose a file made by Export this search.") from None
    if not isinstance(doc, dict) or doc.get("format") != FORMAT_NAME:
        raise NotAnExport("That isn't a shared search from Property Helper. Choose a file made by Export this search.")
    version = doc.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version != FORMAT_VERSION:
        raise NotAnExport("That file was made by a different version of Property Helper, so it can't be read here.")
    search = doc.get("search")
    if not isinstance(search, dict):
        raise NotAnExport("That shared search file is damaged (it has no search in it), so nothing was added.")
    lists = []
    for key in ("criteria", "anchors", "places"):
        got = doc.get(key, [])
        lists.append(got if isinstance(got, list) else [])
    crits, anchors, places = lists
    if len(places) > MAX_PLACES or len(crits) > MAX_CRITERIA or len(anchors) > MAX_ANCHORS:
        raise NotAnExport(f"That file holds more than a search should (over {MAX_PLACES} places), so nothing was added.")
    # An item that isn't an object is left out and counted; the rest of the file is still used.
    doc["_not_objects"] = {"places": sum(1 for x in places if not isinstance(x, dict)),
                           "criteria": sum(1 for x in crits if not isinstance(x, dict)),
                           "anchors": sum(1 for x in anchors if not isinstance(x, dict))}
    doc["criteria"] = [x for x in crits if isinstance(x, dict)]
    doc["anchors"] = [x for x in anchors if isinstance(x, dict)]
    doc["places"] = [x for x in places if isinstance(x, dict)]
    return doc


IMPORT_SUFFIX = " (imported)"


def imported_name(name: Any) -> str:
    """The name the imported search gets: theirs plus " (imported)", so it is never mistaken for one of yours."""
    base = " ".join(str(name or "").split()) or "Shared search"
    return base[:200 - len(IMPORT_SUFFIX)].rstrip() + IMPORT_SUFFIX


def preview_text(doc: dict[str, Any], places: int | None = None, report: dict[str, Any] | None = None) -> str:
    """"Adds the search 'X (imported)' (renting) with 7 places, 2 things that matter and 1 important place." The name is
    cut to a sane length (the page escapes it). ``places`` is how many will really be added (from ``dry_run``); without it
    every readable place is counted. ``report`` (from ``dry_run``) makes the other counts agree with what will happen, and
    adds what can't be read. With no places to add, it says so plainly."""
    name = imported_name(doc["search"].get("name"))
    mode = "buying" if str(doc["search"].get("mode") or "rent") == "buy" else "renting"
    rep = report or {}
    n = len(doc["places"]) if places is None else places
    crit = max(0, len(doc.get("criteria") or []) - int(rep.get("criteria_skipped") or 0))
    anch = max(0, len(doc.get("anchors") or []) - int(rep.get("anchors_skipped") or 0))
    bad = int(rep.get("places_skipped") or 0)

    def count(k: int, one: str, many: str) -> str:
        return f"{k} {one if k == 1 else many}"

    if n == 0:
        text = f"Adds the search '{name}' ({mode}) but no places"
    else:
        text = f"Adds the search '{name}' ({mode}) with {count(n, 'place', 'places')}"
    text += f", {count(crit, 'thing that matters', 'things that matter')} and {count(anch, 'important place', 'important places')}."
    if bad:
        text += (f" {count(bad, 'place', 'places')} can't be read and will be left out."
                 if n else f" {'The place' if bad == 1 else 'All ' + str(bad) + ' places'} can't be read, so none will be added.")
    elif n == 0:
        text += " The file has no places."
    return text


def anchor_dropped_lines(report: dict[str, Any], *, done: bool = False) -> list[str]:
    """One line for each important place with coordinates (or an address) that can't be used, so it is left out."""
    out = []
    for item in report.get("anchors_dropped") or []:
        name = str(item.get("name") or "An important place")[:60]
        why = "has coordinates that can't be used" if item.get("coords") else "can't be read"
        out.append(f"The important place '{name}' {why}, so it {'was' if done else 'will be'} left out.")
    return out


def clean_photo_links(value: Any) -> tuple[list[str], int, int]:
    """``(links, dropped, upgraded)`` for the photo links of an imported place: a link with a user name or password, or one that
    isn't a web address, is dropped; a plain http:// link becomes https:// (pictures only load over https)."""
    if value in (None, ""):
        return [], 0, 0
    if isinstance(value, str):
        text = value.strip()
        try:
            value = json.loads(text) if text.startswith("[") else re.split(r"[\s,]+", text)
        except ValueError:
            value = text.split()
    kept: list[str] = []
    dropped = upgraded = 0
    for item in value if isinstance(value, (list, tuple)) else []:
        link = str(item or "").strip()
        if not link:
            continue
        if not re.match(r"^https?://[^\s/]+\S*$", link, re.I) or has_userinfo(link):
            dropped += 1
            continue
        if link[:5].lower() == "http:":
            link = "https:" + link[5:]
            upgraded += 1
        if link not in kept:
            kept.append(link)
    return kept, dropped, upgraded


def left_out_lines(report: dict[str, Any], *, done: bool = False) -> list[str]:
    """Plain words for what an import leaves out or cleans, from ``dry_run`` or ``apply_import`` numbers."""
    def n(k: str) -> int:
        return int(report.get(k) or 0)

    def s(k: str, one: str, many: str) -> str:
        return one if n(k) == 1 else many

    out = []
    # "will be left out" in a preview; "was/were left out" once it is done, agreeing with what is counted.
    def gone(k: str) -> str:
        return ("was" if n(k) == 1 else "were") if done else "will be"
    bad = [str(x) for x in report.get("fields_skipped") or []]
    if bad:
        out.append(f"The {', '.join(bad)} of the search can't be read and {('was' if len(bad) == 1 else 'were') if done else 'will be'} left out.")
    if n("places_skipped"):
        out.append(f"{n('places_skipped')} place{s('places_skipped', '', 's')} can't be read and {gone('places_skipped')} left out.")
    if n("criteria_skipped"):
        out.append(f"{n('criteria_skipped')} thing{s('criteria_skipped', '', 's')} that matter{s('criteria_skipped', 's', '')} can't be read and {gone('criteria_skipped')} left out.")
    if report.get("anchors_dropped") and n("anchors_skipped") == len(report["anchors_dropped"]):
        out.extend(anchor_dropped_lines(report, done=done))
    elif n("anchors_skipped"):
        out.append(f"{n('anchors_skipped')} important place{s('anchors_skipped', '', 's')} can't be read and {gone('anchors_skipped')} left out.")
    if n("link_unsafe"):
        out.append(f"{n('link_unsafe')} place{s('link_unsafe', ' has a link that isn' + chr(39) + 't', 's have links that aren' + chr(39) + 't')} a normal web address. "
                   f"{s('link_unsafe', 'The place ' + ('was' if done else 'is'), 'The places ' + ('were' if done else 'are'))} kept without {s('link_unsafe', 'its link', 'their links')}.")
    if n("link_userinfo"):
        out.append(f"{n('link_userinfo')} place{s('link_userinfo', ' has a link that has', 's have links that have')} a user name or password in {s('link_userinfo', 'it', 'them')}, "
                   f"so {s('link_userinfo', 'the link', 'the links')} {'was' if done and n('link_userinfo') == 1 else 'were' if done else 'will be'} left blank. "
                   f"{s('link_userinfo', 'The place ' + ('was' if done else 'is'), 'The places ' + ('were' if done else 'are'))} kept.")
    if n("link_dropped"):
        k = n("link_dropped")
        who = "that place" if k == 1 else "those places"
        verb = ("has" if k == 1 else "have") if done else "will have"
        out.append(f"{k} listing link{' is' if k == 1 else 's are'} already saved in another search, so {who} {verb} no link.")
    if n("photos_dropped"):
        k = n("photos_dropped")
        out.append(f"{k} photo link{' has' if k == 1 else 's have'} a user name or password in {'it' if k == 1 else 'them'}, or {'isn' + chr(39) + 't' if k == 1 else 'aren' + chr(39) + 't'} "
                   f"a web address, so {'it' if k == 1 else 'they'} {'was' if k == 1 else 'were'} left out." if done else
                   f"{k} photo link{' has' if k == 1 else 's have'} a user name or password in {'it' if k == 1 else 'them'}, or {'isn' + chr(39) + 't' if k == 1 else 'aren' + chr(39) + 't'} "
                   f"a web address, so {'it' if k == 1 else 'they'} will be left out.")
    if n("photos_upgraded"):
        k = n("photos_upgraded")
        out.append(f"{k} photo link{' was' if k == 1 else 's were'} plain http://, so {'it' if k == 1 else 'they'} {'was' if done and k == 1 else 'were' if done else 'will be'} "
                   f"saved as https:// (pictures only load over https).")
    return out


def dry_run(doc: dict[str, Any]) -> dict[str, Any]:
    """What ``apply_import`` would do, counted on a throwaway in-memory database. Writes nothing of yours. It runs the very
    same checks as the real import, so the preview can't promise what the import won't do. When the whole file would be
    refused the answer is ``{"failed": "<plain reason>"}``."""
    scratch = Store(":memory:")
    try:
        return apply_import(scratch, doc)
    except ValueError as exc:
        return {"failed": str(exc)}
    except Exception:  # noqa: BLE001
        return {"failed": "it has something this version can't read"}
    finally:
        scratch.close()


def apply_import(store: Store, doc: dict[str, Any]) -> dict[str, Any]:
    """Make a NEW search from a checked export. All or nothing for the search itself; a place or a criterion that
    can't be read is skipped and counted. Important places that match one you already have (same name and address)
    are reused. The new search's name gets " (imported)". Returns ``{"search", "places", "skipped", "link_dropped",
    "link_unsafe", "places_skipped", "criteria_skipped", "anchors_skipped"}`` (``skipped`` is the sum of the three kinds)."""
    s = doc["search"]
    not_obj = doc.get("_not_objects") or {}
    places_skipped = int(not_obj.get("places") or 0)
    criteria_skipped = int(not_obj.get("criteria") or 0)
    anchors_skipped = int(not_obj.get("anchors") or 0)
    dropped = unsafe = userinfo = 0
    photos_dropped = photos_upgraded = 0
    created = 0
    fields_skipped: list[str] = []
    anchors_dropped: list[dict[str, Any]] = []
    with store._write():
        mode = str(s.get("mode") or "rent")
        fields = {k: s.get(k) for k in ("area", "move_in", "target_close", "budget_max", "people", "adults", "people_names", "down_payment_pct") if s.get(k) not in (None, "")}
        fields["hide_dealbreakers"] = bool(s.get("hide_dealbreakers"))
        for key in [k for k in fields if k != "hide_dealbreakers"]:  # a value that can't be read is left out, the rest is kept
            try:
                store._search_values({key: fields[key]}, partial=True)  # noqa: SLF001
            except (ValueError, TypeError, OverflowError):
                fields.pop(key)
                fields_skipped.append({"move_in": "move-in date", "target_close": "closing date", "budget_max": "budget", "down_payment_pct": "down payment"}.get(key, key.replace("_", " ")))
        search = store.add_search(imported_name(s.get("name")), mode, **fields)
        sid = search["id"]
        existing = store.list_anchors(sid)
        anchor_ids: dict[int, int] = {}
        for i, a in enumerate(doc["anchors"]):
            name = " ".join(str(a.get("name") or "").split())
            if not name:
                continue
            addr = str(a.get("address") or "").strip()
            match = next((e for e in existing if e["name"].lower() == name.lower() and (e["address"] or "").lower() == addr.lower()), None)
            try:
                made = match or store.add_anchor(name, addr, a.get("lat"), a.get("lng"), search_id=sid)
            except ValueError:
                anchors_skipped += 1
                anchors_dropped.append({"name": name, "coords": a.get("lat") not in (None, "") or a.get("lng") not in (None, "")})
                continue
            if match is None:
                existing.append(made)
            anchor_ids[i] = made["id"]
        for c in doc["criteria"]:
            target = c.get("target") if isinstance(c.get("target"), dict) else {}
            target = dict(target)
            idx = target.pop("anchor", None)
            if idx is not None:
                if isinstance(idx, int) and not isinstance(idx, bool) and idx in anchor_ids:
                    target["anchor_id"] = anchor_ids[idx]
            try:
                store.add_criterion(sid, str(c.get("kind") or ""), label=str(c.get("label") or ""), weight=c.get("weight", 10),
                                    dealbreaker=c.get("dealbreaker"), target=target)
            except (ValueError, TypeError):
                criteria_skipped += 1
        for item in doc["places"]:
            fields = {k: item[k] for k in (*SHARED_TEXT, *SHARED_REAL, *SHARED_INT, "photo_urls", "dishwasher", "application_fee_per_adult") if k in item}
            if "url" in fields and not (isinstance(fields["url"], str) and normalize_url(fields["url"]) and not has_userinfo(fields["url"])):
                if isinstance(fields["url"], str) and has_userinfo(fields["url"]):
                    userinfo += 1  # the place is kept, the link is not
                elif fields["url"] not in (None, ""):
                    unsafe += 1  # the place is kept, the link is not
                fields.pop("url")
            if fields.get("url") and store.find_duplicate(url=str(fields["url"])) is not None:
                fields.pop("url")  # a link is saved once across all searches; this one is already in use
                dropped += 1
            if "photo_urls" in fields:
                fields["photo_urls"], d, u = clean_photo_links(fields["photo_urls"])
                photos_dropped += d
                photos_upgraded += u
            try:
                place, made_new = store.add_place(search_id=sid, by="you", **fields)
            except (ValueError, TypeError):
                places_skipped += 1
                continue
            if not made_new:
                places_skipped += 1
                continue
            created += 1
            for cm in item.get("commutes") or []:
                try:
                    idx = cm.get("anchor")
                    if isinstance(idx, int) and not isinstance(idx, bool) and idx in anchor_ids and str(cm.get("mode")) in COMMUTE_MODES:
                        store.set_commute(place["id"], anchor_ids[idx], str(cm["mode"]), cm.get("minutes"), "you")
                except (ValueError, TypeError, AttributeError):
                    pass  # a travel time that can't be read is simply not added
    return {"search": store.get_search(sid), "places": created, "link_dropped": dropped, "link_unsafe": unsafe, "link_userinfo": userinfo,
            "places_skipped": places_skipped, "criteria_skipped": criteria_skipped, "anchors_skipped": anchors_skipped,
            "fields_skipped": fields_skipped, "anchors_dropped": anchors_dropped, "photos_dropped": photos_dropped, "photos_upgraded": photos_upgraded, "skipped": places_skipped + criteria_skipped + anchors_skipped}


# --------------------------------------------------------------------------- a file waiting for "Add it"
_PENDING: dict[str, tuple[float, str, dict[str, Any]]] = {}
PENDING_SECONDS = 30 * 60
PENDING_MAX = 5


def hold(filename: str, doc: dict[str, Any]) -> str:
    """Keep a checked file in memory (never on disk) while the person looks at the preview. Returns its token."""
    now = time.monotonic()
    for t in [t for t, (at, _n, _d) in _PENDING.items() if now - at > PENDING_SECONDS]:
        del _PENDING[t]
    while len(_PENDING) >= PENDING_MAX:
        del _PENDING[min(_PENDING, key=lambda t: _PENDING[t][0])]
    token = secrets.token_urlsafe(16)
    _PENDING[token] = (now, filename, doc)
    return token


def held(token: str) -> tuple[str, dict[str, Any]] | None:
    got = _PENDING.get(token or "")
    if got is None or time.monotonic() - got[0] > PENDING_SECONDS:
        _PENDING.pop(token or "", None)
        return None
    return got[1], got[2]


def release(token: str) -> None:
    _PENDING.pop(token or "", None)


def opinions_for(store: Store, place_id: int) -> list[dict[str, Any]]:
    """The people's saved opinions of a place (for the 'include my notes' option)."""
    try:
        return store.list_opinions(place_id)
    except Exception:
        return []


__all__ = ["people_slots", "comparison_html", "export_bytes", "read_export", "apply_import", "dry_run", "left_out_lines", "imported_name"]
