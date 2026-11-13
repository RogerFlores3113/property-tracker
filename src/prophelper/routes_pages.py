"""The core pages: Today, Board, Place, Search and Add.

    GET  /today                          what needs you now (tours, replies, dates, new places)
    GET  /board                          one column per stage of the current search; ?show_hidden=1 shows hidden cards
    POST /places/{id}/stage              move a place (JSON for the board's drag, a redirect otherwise)
    GET  /places/{id}                    the place page; POST /places/{id} saves the facts form
    POST /places/{id}/note               add a note to the timeline
    POST /places/{id}/commute            save your own minutes for an anchor and mode (+ /commute/clear)
    POST /places/{id}/custom-score       your 0 to 5 score for a "custom" criterion
    POST /places/{id}/archive | unarchive | hide | delete
    GET  /search                         searches, criteria and anchors; POST under /search/... and /criteria/... and /anchors/...
    GET  /add                            paste a link and/or listing text; POST /add/parse, POST /add/save
    GET  /                               (web.py) goes to /today

Other pages (map, calendar, compare, contacts, documents, checklist, AI, CSV) live in their own ``routes_*`` modules
(see ``web.OPTIONAL_ROUTERS``). The place page includes the optional templates ``_place_tours.html``,
``_place_contacts.html``, ``_place_documents.html``, ``_place_ai.html`` and ``_place_extra.html`` when they exist.
"""
from __future__ import annotations

import shutil
from urllib.parse import quote
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from . import backups, commute, enrich, helpers, movein, parsers, paths, redflags, scoring, stages, today
from .routes_geocode import lookup_for_anchor
from .deps import get_store, is_htmx, redirect, render
from .store import COMMUTE_MODES, CRITERION_KINDS, NotFound, StageRuleError, Store

router = APIRouter()

# The fields the facts form and the Add page post (everything a person can edit by hand).
FORM_FIELDS = (
    "title", "address", "unit", "city", "state", "zip", "lat", "lng", "url", "source", "listing_text", "price", "beds", "baths",
    "sqft", "laundry", "dishwasher", "parking", "parking_cost", "pets", "pet_rent", "pet_fee", "utilities_included",
    "utilities_estimate", "year_built", "available_from", "lease_start", "lease_end", "lease_months", "deposit",
    "application_fee", "other_monthly_fees", "move_in_fees", "broker_fee", "hoa", "property_tax", "insurance", "rating", "notes",
    "pet_weight_limit", "pet_count_limit", "pet_breed_note", "pet_deposit", "fenced_yard",
    "days_on_market", "special_assessment", "special_assessment_payer", "closing_costs", "listing_agent",
    "months_up_front", "tenant_pays")


def _form_fields(form: Any, names: tuple[str, ...] = FORM_FIELDS) -> dict[str, str]:
    return {n: str(form.get(n)) for n in names if n in form}


def _place_or_404(store: Store, place_id: int) -> dict[str, Any]:
    try:
        return store.get_place(place_id)
    except NotFound:
        raise HTTPException(404, "That place doesn't exist (it may have been deleted).") from None


def _search_of(store: Store, place: dict[str, Any]) -> dict[str, Any]:
    return store.get_search(place["search_id"])


# --------------------------------------------------------------------------- Today
@router.get("/today", include_in_schema=False)
def today_page(request: Request):
    store = get_store(request)
    search = store.current_search()
    all_searches = store.list_searches(include_archived=True)
    if search is None:
        return render(request, "today.html", search=None, first_run=not all_searches, fits=[], near_miss=[], coming=[], waiting=[], new=[],
                      late=[], no_criteria=False, place_count=0, coming_days=today.COMING_UP_DAYS)
    sid = search["id"]
    data = today.build(store, search)
    criteria = store.list_criteria(sid)
    return render(request, "today.html", search=search, first_run=False, fits=data["fits"], near_miss=data["near_miss"], coming=data["coming"],
                  waiting=data["waiting"], new=data["new"], late=data["late"], no_criteria=not criteria,
                  place_count=store.count_places(search_id=sid), follow_up_days=store.get_setting_int("follow_up_days", 3),
                  coming_days=today.COMING_UP_DAYS)


# --------------------------------------------------------------------------- Board
@router.get("/board", include_in_schema=False)
def board_page(request: Request, show_hidden: int = 0):
    store = get_store(request)
    search = store.current_search()
    if search is None:
        return render(request, "board.html", search=None, columns={}, totals={}, stages=(), hidden_dealbreaker=0, hidden_hand=0,
                      show_hidden=False, total=0)
    rows = enrich.enrich_places(store, search)
    mode_stages = stages.stages_for(search["mode"])
    shown, hidden_deal, hidden_hand = [], 0, 0
    for p in rows:
        if p["hidden"]:
            hidden_hand += 1
            if not show_hidden:
                continue
        elif p["hidden_by_dealbreaker"]:
            hidden_deal += 1
            if not show_hidden:
                continue
        shown.append(p)
    columns = {s: [] for s in mode_stages}
    for p in shown:
        columns.setdefault(p["stage"], []).append(p)
    for cards in columns.values():
        cards.sort(key=scoring.sort_key)  # places that fit first, then the ones that miss a deal-breaker or need a check
    totals = {s: len(c) for s, c in columns.items()}
    return render(request, "board.html", search=search, columns=columns, totals=totals, stages=mode_stages,
                  hidden_dealbreaker=hidden_deal, hidden_hand=hidden_hand, show_hidden=bool(show_hidden), total=len(rows))


def _toured_hint(store: Store, place: dict[str, Any]) -> str:
    """Moving to Toured with no tour logged is allowed; this is the gentle note that offers to log one."""
    if place["stage"] != "Toured" or any(t["status"] != "cancelled" for t in store.list_tours(place["id"])):
        return ""
    return "You haven't logged a tour for it. Add the tour on the place page if you want its checklist and notes kept."


FINAL_STEP_NOTES = {
    "Lease signed": "This says you signed the lease here. The place goes to the end of the board as won. You can move it back later.",
    "Closed": "This says the sale closed and the home is yours. The place goes to the end of the board as won. You can move it back later.",
    "Passed": "This says you decided against this place. It goes to the end of the board and stops showing up in your reminders. You can move it back later.",
}


@router.get("/places/{place_id}/stage-confirm", include_in_schema=False)
async def stage_confirm(request: Request, place_id: int, stage: str = ""):
    store = get_store(request)
    current = _place_or_404(store, place_id)
    target = stages.normalize_stage(_search_of(store, current)["mode"], stage)
    if not target or target == current["stage"] or not stages.is_closed(target):
        return redirect(f"/places/{place_id}")
    return render(request, "stage_confirm.html", place=current, target=target, note="", meaning=FINAL_STEP_NOTES[target])


@router.post("/places/{place_id}/stage", include_in_schema=False)
async def move_place(request: Request, place_id: int):
    store = get_store(request)
    form = await request.form()
    stage = str(form.get("stage", ""))
    note = str(form.get("note", ""))
    current = _place_or_404(store, place_id)
    if str(form.get("confirm", "")) != "yes":
        # Lease signed, Closed and Passed end the hunt for a place: ask first (a page, so it works without scripts).
        target = stages.normalize_stage(_search_of(store, current)["mode"], stage)
        if target and target != current["stage"] and stages.is_closed(target):
            if is_htmx(request):  # the board's drag or dropdown: refuse here and send the person to the confirm page
                return JSONResponse({"ok": False, "confirm_url": f"/places/{place_id}/stage-confirm?stage={quote(target)}",
                                     "error": f"Moving to {target} needs one more click on its own page."}, status_code=409)
            return render(request, "stage_confirm.html", place=current, target=target, note=note,
                          meaning=FINAL_STEP_NOTES[target])
    try:
        place = store.move_stage(place_id, stage, note=note)
        hint = _toured_hint(store, place)
    except (StageRuleError, ValueError) as exc:
        if is_htmx(request):
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        return redirect(f"/places/{place_id}", error=str(exc))
    if is_htmx(request):
        return JSONResponse({"ok": True, "stage": place["stage"], "days": helpers.days_in_stage(place), "note": hint})
    return redirect(f"/places/{place_id}" if "place" in (request.headers.get("referer") or "") else "/board",
                    notice=f"Moved {place['title']} to {place['stage']}." + (" " + hint if hint else ""))


# --------------------------------------------------------------------------- Place
def _place_page(request: Request, place_id: int, *, status: int = 200, form_values: dict[str, str] | None = None,
                error: str = ""):
    store = get_store(request)
    place = _place_or_404(store, place_id)
    search = _search_of(store, place)
    full = enrich.enrich_places(store, search, [place])[0]
    # Peers for the "far under the others" rule are the search's other prices; enrich_places already did that.
    anchors = store.list_anchors()
    stored = {(c["anchor_id"], c["mode"]): c for c in store.list_commutes(place_id)}
    commute_rows = []
    from . import commute as cm

    for a in anchors:
        for mode in COMMUTE_MODES:
            found = cm.resolve(place, a, mode, store.list_commutes(place_id))
            saved = stored.get((a["id"], mode))
            commute_rows.append({"anchor": a, "mode": mode, "found": found, "saved": saved})
    criteria = store.list_criteria(search["id"])
    return render(request, "place.html", status_code=status, place=full, search=search,
                  avail_warning=movein.gap_warning(place, search), stages=stages.stages_for(search["mode"]),
                  events=store.list_events(place_id), commute_rows=commute_rows, anchors=anchors, criteria=criteria,
                  custom_scores=store.custom_scores(place_id), form_values=form_values or {}, form_error=error,
                  all_searches=store.list_searches(), listing_has_text=bool(place["listing_text"]),
                  show_photos=store.get_setting_bool("show_photos"))


@router.get("/places/{place_id}", include_in_schema=False)
def place_page(request: Request, place_id: int):
    store = get_store(request)
    _place_or_404(store, place_id)
    store.mark_seen(place_id)
    return _place_page(request, place_id)


@router.post("/places/{place_id}", include_in_schema=False)
async def save_place(request: Request, place_id: int):
    store = get_store(request)
    _place_or_404(store, place_id)
    form = await request.form()
    values = _form_fields(form)
    try:
        store.update_place(place_id, by="you", **values)
    except ValueError as exc:
        return _place_page(request, place_id, status=400, form_values=values, error=str(exc))
    store.mark_seen(place_id)
    return redirect(f"/places/{place_id}", notice="Saved.")


@router.post("/places/{place_id}/note", include_in_schema=False)
async def add_note(request: Request, place_id: int):
    store = get_store(request)
    _place_or_404(store, place_id)
    form = await request.form()
    kind = str(form.get("kind") or "note")
    try:
        store.add_event(place_id, kind if kind in ("note", "call", "email", "text") else "note", str(form.get("body", "")), source="you")
    except ValueError as exc:
        return redirect(f"/places/{place_id}#timeline", error=str(exc))
    return redirect(f"/places/{place_id}#timeline", notice="Added to the timeline.")


@router.post("/places/{place_id}/commute", include_in_schema=False)
async def save_commute(request: Request, place_id: int):
    store = get_store(request)
    _place_or_404(store, place_id)
    form = await request.form()
    try:
        store.set_commute(place_id, int(form.get("anchor_id") or 0), str(form.get("mode", "")), form.get("minutes"), "you")
    except (ValueError, NotFound) as exc:
        return redirect(f"/places/{place_id}#commutes", error=str(exc))
    return redirect(f"/places/{place_id}#commutes", notice="Saved. Your time is used instead of the map estimate.")


@router.post("/places/{place_id}/commute/clear", include_in_schema=False)
async def clear_commute(request: Request, place_id: int):
    store = get_store(request)
    _place_or_404(store, place_id)
    form = await request.form()
    try:
        store.clear_commute(place_id, int(form.get("anchor_id") or 0), str(form.get("mode", "")))
    except ValueError as exc:
        return redirect(f"/places/{place_id}#commutes", error=str(exc))
    return redirect(f"/places/{place_id}#commutes", notice="Back to the map estimate.")


@router.post("/places/{place_id}/custom-score", include_in_schema=False)
async def custom_score(request: Request, place_id: int):
    store = get_store(request)
    _place_or_404(store, place_id)
    form = await request.form()
    try:
        store.set_custom_score(place_id, int(form.get("criterion_id") or 0), form.get("score"))
    except (ValueError, NotFound) as exc:
        return redirect(f"/places/{place_id}#score", error=str(exc))
    return redirect(f"/places/{place_id}#score", notice="Saved.")


@router.post("/places/{place_id}/archive", include_in_schema=False)
def archive_place(request: Request, place_id: int):
    store = get_store(request)
    place = _place_or_404(store, place_id)
    store.archive_place(place_id)
    return redirect("/board", notice=f"Archived {place['title']}. It is out of the way but not deleted.")


@router.post("/places/{place_id}/unarchive", include_in_schema=False)
def unarchive_place(request: Request, place_id: int):
    store = get_store(request)
    place = _place_or_404(store, place_id)
    store.unarchive_place(place_id)
    return redirect(f"/places/{place_id}", notice=f"Brought {place['title']} back.")


@router.post("/places/{place_id}/hide", include_in_schema=False)
async def hide_place(request: Request, place_id: int):
    store = get_store(request)
    place = _place_or_404(store, place_id)
    form = await request.form()
    on = str(form.get("on", "1")) == "1"
    store.update_place(place_id, by="you", hidden=on)
    return redirect(f"/places/{place_id}", notice=(f"{place['title']} is hidden from the board." if on else f"{place['title']} shows on the board again."))


@router.post("/places/{place_id}/delete", include_in_schema=False)
async def delete_place(request: Request, place_id: int):
    store = get_store(request)
    place = _place_or_404(store, place_id)
    form = await request.form()
    if str(form.get("confirm", "")) != "yes":
        return redirect(f"/places/{place_id}#danger", error="Tick the box to confirm. Deleting can't be undone (a backup is saved first).")
    try:
        backups.backup_before(store, reason="delete")
    except ValueError as exc:
        return redirect(f"/places/{place_id}#danger", error=str(exc))
    store.delete_place(place_id)
    shutil.rmtree(paths.data_dir() / "files" / str(place_id), ignore_errors=True)
    return redirect("/board", notice=f"Deleted {place['title']}.")


# --------------------------------------------------------------------------- Search
KIND_TARGET_KEYS = {"price": ("max",), "beds": ("min",), "baths": ("min",), "sqft": ("min",),
                    "commute": ("anchor_id", "mode", "minutes"), "laundry": ("want",), "parking": ("want",),
                    "pets": ("want",), "newer": ("year",), "fenced_yard": ()}


def _target_from_form(kind: str, form: Any) -> dict[str, Any]:
    """Only the boxes this kind of criterion uses. The Add form has one choice box per kind (``t_want_laundry`` and so on);
    the edit form has ``t_want``."""
    t: dict[str, Any] = {}
    for key in KIND_TARGET_KEYS.get(kind, ()):
        for name in (f"t_{key}_{kind}", f"t_{key}"):
            if name in form and str(form.get(name)).strip() != "":
                t[key] = str(form.get(name)).strip()
                break
    return t


def _commute_target(store: Store, target: dict[str, Any]) -> dict[str, Any]:
    """A commute with no place chosen means the first important place: say which one, so the label can name it."""
    if target.get("anchor_id") in (None, ""):
        anchors = store.list_anchors()
        if anchors:
            target = {**target, "anchor_id": anchors[0]["id"]}
    return target


def _commute_label(store: Store, target: dict[str, Any]) -> str:
    try:
        a = store.get_anchor(int(target["anchor_id"]))
    except (KeyError, ValueError, TypeError, NotFound):
        return ""
    try:
        mins = float(target.get("minutes")) if target.get("minutes") not in (None, "") else None
    except (TypeError, ValueError):
        mins = None
    return commute.commute_label(str(target.get("mode") or "bike"), mins, a["name"])


def _same_target(a: dict[str, Any], b: dict[str, Any]) -> bool:
    def norm(t: dict[str, Any]) -> dict[str, str]:
        out = {}
        for k, v in t.items():
            try:
                out[k] = f"{float(v):g}"
            except (TypeError, ValueError):
                out[k] = str(v).strip().lower()
        return out
    return norm(a) == norm(b)


@router.get("/search", include_in_schema=False)
def search_page(request: Request, id: int | None = None):
    store = get_store(request)
    current = store.current_search()
    try:
        shown = store.get_search(id) if id else current
    except NotFound:
        raise HTTPException(404, "That search doesn't exist.") from None
    anchors = store.list_anchors()
    criteria = store.list_criteria(shown["id"]) if shown else []
    ctx = {"anchors": {a["id"]: a for a in anchors}}
    crit_labels = {c["id"]: scoring._auto_label(c["kind"], c["target"], ctx) for c in criteria}
    return render(request, "search.html", current=current, shown=shown, searches=store.list_searches(include_archived=True),
                  criteria=criteria, crit_labels=crit_labels, anchors=anchors,
                  place_counts={s["id"]: store.count_places(search_id=s["id"]) for s in store.list_searches(include_archived=True)})


@router.post("/search", include_in_schema=False)
async def create_search(request: Request):
    store = get_store(request)
    form = await request.form()
    try:
        s = store.add_search(str(form.get("name", "")), str(form.get("mode", "rent")), area=form.get("area", ""),
                             move_in=form.get("move_in", ""), target_close=form.get("target_close", ""),
                             budget_max=form.get("budget_max", ""), notes=form.get("notes", ""),
                             **({"people": form.get("people")} if form.get("people") else {}))
        store.set_current_search(s["id"])
    except ValueError as exc:
        return redirect("/search", error=str(exc))
    return redirect(f"/search?id={s['id']}", notice=f"Made the search '{s['name']}' and switched to it. Add what you want below.")


@router.post("/search/{search_id}", include_in_schema=False)
async def update_search(request: Request, search_id: int):
    store = get_store(request)
    form = await request.form()
    values: dict[str, Any] = {k: form.get(k) for k in ("name", "mode", "area", "move_in", "target_close", "budget_max", "notes", "people", "pet_kind", "pet_weight", "pet_count", "people_names") if k in form}
    values["hide_dealbreakers"] = "1" if form.get("hide_dealbreakers") == "1" else "0"
    try:
        store.update_search(search_id, **values)
    except NotFound:
        raise HTTPException(404, "That search doesn't exist.") from None
    except ValueError as exc:
        return redirect(f"/search?id={search_id}", error=str(exc))
    return redirect(f"/search?id={search_id}", notice="Saved.")


@router.post("/search/{search_id}/switch", include_in_schema=False)
def switch_search(request: Request, search_id: int):
    store = get_store(request)
    try:
        s = store.set_current_search(search_id)
    except NotFound:
        raise HTTPException(404, "That search doesn't exist.") from None
    except ValueError as exc:
        return redirect("/search", error=str(exc))
    return redirect("/board", notice=f"Now showing '{s['name']}'.")


@router.post("/search/{search_id}/archive", include_in_schema=False)
def archive_search(request: Request, search_id: int):
    store = get_store(request)
    try:
        s = store.archive_search(search_id)
    except NotFound:
        raise HTTPException(404, "That search doesn't exist.") from None
    return redirect("/search", notice=f"Archived '{s['name']}'. Its places are kept.")


@router.post("/search/{search_id}/unarchive", include_in_schema=False)
def unarchive_search(request: Request, search_id: int):
    store = get_store(request)
    try:
        s = store.unarchive_search(search_id)
    except NotFound:
        raise HTTPException(404, "That search doesn't exist.") from None
    return redirect(f"/search?id={search_id}", notice=f"Brought '{s['name']}' back.")


@router.post("/search/{search_id}/delete", include_in_schema=False)
async def delete_search(request: Request, search_id: int):
    store = get_store(request)
    form = await request.form()
    try:
        s = store.get_search(search_id)
    except NotFound:
        raise HTTPException(404, "That search doesn't exist.") from None
    if str(form.get("confirm", "")) != "yes":
        return redirect(f"/search?id={search_id}#danger", error="Tick the box to confirm. Deleting a search deletes its places too.")
    try:
        backups.backup_before(store, reason="delete")
    except ValueError as exc:
        return redirect(f"/search?id={search_id}#danger", error=str(exc))
    place_ids = [p["id"] for p in store.list_places(search_id, include_archived=True)]
    store.delete_search(search_id)
    for pid in place_ids:
        shutil.rmtree(paths.data_dir() / "files" / str(pid), ignore_errors=True)
    return redirect("/search", notice=f"Deleted '{s['name']}' and its places.")


@router.post("/search/{search_id}/criteria", include_in_schema=False)
async def add_criterion(request: Request, search_id: int):
    store = get_store(request)
    form = await request.form()
    kind = str(form.get("kind", ""))
    target = _target_from_form(kind, form)
    label = str(form.get("label", "")).strip()
    try:
        search = store.get_search(search_id)
        if kind not in CRITERION_KINDS:
            plain = ", ".join(("Price" if k == "price" and search["mode"] == "buy" else scoring.KIND_LABELS.get(k, k)) for k in CRITERION_KINDS)
            return redirect(f"/search?id={search_id}#criteria", error=f"Pick what kind of thing matters: {plain}.")
        if kind == "commute":
            if not store.list_anchors():
                return redirect(f"/search?id={search_id}#anchors", error="A commute needs a place to travel to. Add an important place first, like Work or Campus, then add the commute.")
            target = _commute_target(store, target)
            label = label or _commute_label(store, target)
        existing = store.list_criteria(search_id)
        dupe = any(c["kind"] == kind and _same_target(c["target"], target) for c in existing) if kind != "custom" else False
        store.add_criterion(search_id, kind, label=label, weight=form.get("weight") or 10,
                            dealbreaker=form.get("dealbreaker") == "1", target=target)
    except NotFound:
        raise HTTPException(404, "That search doesn't exist.") from None
    except ValueError as exc:
        return redirect(f"/search?id={search_id}#criteria", error=str(exc))
    note = "Added."
    if dupe:
        note += " Heads up: you already have one just like it, so it will count twice. Remove one if that was not what you meant."
    return redirect(f"/search?id={search_id}#criteria", notice=note)


@router.post("/criteria/{criterion_id}", include_in_schema=False)
async def update_criterion(request: Request, criterion_id: int):
    store = get_store(request)
    form = await request.form()
    try:
        c = store.get_criterion(criterion_id)
        target = _target_from_form(c["kind"], form)
        label = str(form.get("label", "")).strip()
        if c["kind"] == "commute":
            target = _commute_target(store, target)
            auto_before = _commute_label(store, c["target"]) or c["label"]
            if not label or label == auto_before:  # a name they never changed follows the new place, way and minutes
                label = _commute_label(store, target)
        store.update_criterion(criterion_id, label=label, weight=form.get("weight") or 0,
                               dealbreaker=form.get("dealbreaker") == "1", target=target)
    except NotFound:
        raise HTTPException(404, "That item doesn't exist.") from None
    except ValueError as exc:
        return redirect(f"/search?id={c['search_id']}#criteria", error=str(exc))
    return redirect(f"/search?id={c['search_id']}#criteria", notice="Saved.")


@router.post("/criteria/{criterion_id}/delete", include_in_schema=False)
def delete_criterion(request: Request, criterion_id: int):
    store = get_store(request)
    try:
        c = store.get_criterion(criterion_id)
    except NotFound:
        raise HTTPException(404, "That item doesn't exist.") from None
    store.delete_criterion(criterion_id)
    return redirect(f"/search?id={c['search_id']}#criteria", notice="Removed.")


def _anchors_back(form: Any) -> str:
    sid = str(form.get("search_id") or "")
    return f"/search?id={sid}#anchors" if sid.isdigit() else "/search#anchors"


NO_LOCATION_NOTE = "Commutes need a location. Press Find on map from address next to it, or enter coordinates yourself."


@router.post("/anchors", include_in_schema=False)
async def add_anchor(request: Request):
    store = get_store(request)
    form = await request.form()
    back = _anchors_back(form)
    try:
        name = str(form.get("name", "")).strip()
        dupe = any(a["name"].strip().lower() == name.lower() for a in store.list_anchors()) if name else False
        a = store.add_anchor(name, str(form.get("address", "")), form.get("lat"), form.get("lng"))
    except ValueError as exc:
        return redirect(back, error=str(exc))
    if form.get("find") == "1":
        return lookup_for_anchor(request, store, a, search_id=str(form.get("search_id") or ""))
    note = f"Added {a['name']}."
    if dupe:
        note += " Heads up: you already had one with that name."
    if a["lat"] is None or a["lng"] is None:
        note += " " + NO_LOCATION_NOTE
    return redirect(back, notice=note)


@router.post("/anchors/{anchor_id}", include_in_schema=False)
async def update_anchor(request: Request, anchor_id: int):
    store = get_store(request)
    form = await request.form()
    back = _anchors_back(form)
    try:
        name = str(form.get("name", "")).strip()
        dupe = any(o["id"] != anchor_id and o["name"].strip().lower() == name.lower() for o in store.list_anchors()) if name else False
        a = store.update_anchor(anchor_id, name=name, address=form.get("address", ""), lat=form.get("lat"), lng=form.get("lng"))
    except NotFound:
        raise HTTPException(404, "That important place doesn't exist.") from None
    except ValueError as exc:
        return redirect(back, error=str(exc))
    note = "Saved."
    if dupe:
        note += " Heads up: you have another one with that name."
    if a["lat"] is None or a["lng"] is None:
        note += " " + NO_LOCATION_NOTE
    return redirect(back, notice=note)


@router.post("/anchors/{anchor_id}/delete", include_in_schema=False)
async def delete_anchor(request: Request, anchor_id: int):
    store = get_store(request)
    form = await request.form()
    back = _anchors_back(form)
    try:
        store.delete_anchor(anchor_id)
    except NotFound:
        raise HTTPException(404, "That important place doesn't exist.") from None
    return redirect(back, notice="Removed. Commute times saved for it are gone too.")


# --------------------------------------------------------------------------- Add
def _add_page(request: Request, *, values: dict[str, Any] | None = None, parsed: bool = False, text: str = "", url: str = "",
              status: int = 200, error: str = "", search_id: int | None = None):
    store = get_store(request)
    searches = store.list_searches()
    current = store.current_search()
    flags = redflags.local_flags(values) if parsed and values else []  # the same hints the place page shows, before you save
    return render(request, "add.html", status_code=status, values=values or {}, parsed=parsed, text=text, url=url, flags=flags,
                  searches=searches, search_options=[(s["id"], s["name"]) for s in searches], chosen=search_id or (current["id"] if current else None), form_error=error,
                  found=sorted((values or {}).keys()) if parsed else [])


@router.get("/add", include_in_schema=False)
def add_page(request: Request, manual: int = 0):
    return _add_page(request, parsed=bool(manual))


@router.post("/add/parse", include_in_schema=False)
async def add_parse(request: Request):
    form = await request.form()
    url, text = str(form.get("url", "")).strip(), str(form.get("text", ""))
    if not url and not text.strip():
        return _add_page(request, status=400, error="Paste a link, the listing text, or both first.")
    values = parsers.parse_listing(text, url)
    if url:
        values["url"] = url
    if text.strip():
        values["listing_text"] = text
    if not values.get("title") and values.get("address"):
        values["title"] = str(values["address"]).split(",")[0]
    sid = form.get("search_id")
    store = get_store(request)
    try:
        chosen = store.get_search(int(sid)) if str(sid or "").isdigit() else store.current_search()
    except NotFound:
        chosen = store.current_search()
    if chosen and int(chosen.get("people") or 1) > 1:
        parsers.app_fee_note_for_people(values, int(chosen["people"]))
    return _add_page(request, values=values, parsed=True, text=text, url=url, search_id=int(sid) if str(sid or "").isdigit() else None)


@router.post("/add/save", include_in_schema=False)
async def add_save(request: Request):
    store = get_store(request)
    form = await request.form()
    values = _form_fields(form)
    sid = form.get("search_id")
    try:
        place, created = store.add_place(by="you", search_id=int(sid) if str(sid or "").isdigit() else None, **values)
    except ValueError as exc:
        return _add_page(request, values=values, parsed=True, text=values.get("listing_text", ""), url=values.get("url", ""),
                         status=400, error=str(exc), search_id=int(sid) if str(sid or "").isdigit() else None)
    if created:
        return redirect(f"/places/{place['id']}", notice=f"Saved {place['title']}.")
    return redirect(f"/places/{place['id']}", notice=f"You already had {place['title']}, so I filled in anything that was empty and changed nothing else.")
