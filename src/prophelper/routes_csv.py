"""CSV import (with a preview first) and CSV export of a search.

    GET  /import            the upload page
    POST /import            upload a file: read it, hold it in memory, show the preview (writes nothing)
    POST /import/preview    change the column matches and look again (writes nothing)
    POST /import/apply      do exactly what the preview showed
    GET  /places.csv        download a search's places (the current search, or ?search_id=; ?stage= and ?q= narrow it)

The uploaded file is held in memory for 30 minutes and never written to disk. Nothing here uses the network.
"""
from __future__ import annotations

import re
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from . import csv_io, enrich
from .deps import get_store, redirect, render
from .routes_data import TooBig, read_form
from .store import NotFound

router = APIRouter()
FILE_LIMIT = 5 * 1024 * 1024


def _searches(store):
    searches = store.list_searches()
    current = store.current_search()
    return searches, [(s["id"], s["name"]) for s in searches], (current["id"] if current else None)


def _upload_page(request: Request, *, error: str = "", status: int = 200, chosen: int | None = None) -> HTMLResponse:
    searches, options, current = _searches(get_store(request))
    return render(request, "import.html", status_code=status, searches=searches, search_options=options,
                  chosen=chosen or current, form_error=error)


def _preview_page(request: Request, token: str, state: dict, mapping: dict[int, str], *, error: str = "", status: int = 200) -> HTMLResponse:
    store = get_store(request)
    search = store.get_search(state["search_id"])
    plan = csv_io.plan_import(store, state["search_id"], state["headers"], state["rows"], mapping)
    shown = [p for p in plan if p["status"] != "new"][:60]
    new_sample = [p for p in plan if p["status"] == "new"][:8]
    examples = [next((r[i].strip()[:40] for r in state["rows"][:50] if i < len(r) and r[i].strip()), "") for i in range(len(state["headers"]))]
    unmatched = [h for i, h in enumerate(state["headers"]) if i not in mapping and h]
    return render(request, "import_preview.html", status_code=status, token=token, search=search, filename=state["filename"], examples=examples,
                  headers=state["headers"], mapping=mapping, field_options=list(csv_io.FIELD_LABELS.items()), plan=plan,
                  counts=csv_io.summarize(plan), others=shown, new_sample=new_sample, unmatched=unmatched,
                  total_rows=len(state["rows"]), form_error=error)


@router.get("/import", include_in_schema=False)
def import_page(request: Request):
    return _upload_page(request)


@router.post("/import", include_in_schema=False)
async def import_upload(request: Request):
    store = get_store(request)
    try:
        form = await read_form(request, FILE_LIMIT)
    except TooBig:
        return _upload_page(request, status=413, error="That file is bigger than 5 MB, which is far more than a list of places needs. Split it and try again.")
    sid = form.get("search_id")
    search_id = int(sid) if str(sid or "").isdigit() else None
    upload = form.get("file")
    if search_id is None:
        cur = store.current_search()
        search_id = cur["id"] if cur else None
    if search_id is None:
        return _upload_page(request, status=400, error="Make a search first (Search page), so there is somewhere to put the places.")
    try:
        store.get_search(search_id)
    except NotFound:
        return _upload_page(request, status=400, error="That search doesn't exist.")
    if upload is None or not hasattr(upload, "read"):
        return _upload_page(request, status=400, error="Choose a spreadsheet (CSV) file first.", chosen=search_id)
    data = await upload.read()
    if len(data) > FILE_LIMIT:
        return _upload_page(request, status=413, error="That file is bigger than 5 MB. Split it and try again.", chosen=search_id)
    try:
        headers, rows = csv_io.read_table(data)
    except csv_io.CsvProblem as exc:
        return _upload_page(request, status=400, error=str(exc), chosen=search_id)
    name = re.sub(r"[^\w .()-]+", "", str(getattr(upload, "filename", "") or "your file"))[:80] or "your file"
    token = csv_io.hold(search_id, name, headers, rows)
    return _preview_page(request, token, csv_io.held(token), csv_io.match_columns(headers))


def _mapping_from(form, headers: list[str]) -> dict[int, str]:
    """The column choices from the preview form. A field is used once; unknown choices count as 'don't use'."""
    mapping: dict[int, str] = {}
    used: set[str] = set()
    for i in range(len(headers)):
        choice = str(form.get(f"col_{i}") or "")
        if choice in csv_io.FIELD_LABELS and choice not in used:
            mapping[i] = choice
            used.add(choice)
    return mapping


@router.post("/import/preview", include_in_schema=False)
async def import_preview(request: Request):
    form = await request.form()
    token = str(form.get("token") or "")
    state = csv_io.held(token)
    if state is None:
        return _upload_page(request, status=410, error="That upload expired (files are only held for 30 minutes). Choose the file again.")
    return _preview_page(request, token, state, _mapping_from(form, state["headers"]))


@router.post("/import/apply", include_in_schema=False)
async def import_apply(request: Request):
    store = get_store(request)
    form = await request.form()
    token = str(form.get("token") or "")
    state = csv_io.held(token)
    if state is None:
        return _upload_page(request, status=410, error="That upload expired (files are only held for 30 minutes). Choose the file again.")
    mapping = _mapping_from(form, state["headers"])
    plan = csv_io.plan_import(store, state["search_id"], state["headers"], state["rows"], mapping)
    if not any(p["status"] in ("new", "match") for p in plan):
        return _preview_page(request, token, state, mapping, status=400, error="There is nothing to import with these column choices. Match at least a title, address or link column.")
    result = csv_io.apply_plan(store, state["search_id"], plan)
    csv_io.release(token)
    bits = []
    if result["added"]:
        bits.append(f"added {result['added']} place{'s' if result['added'] != 1 else ''}")
    if result["filled"]:
        bits.append(f"filled in empty details on {result['filled']} you already had")
    msg = "Import done: " + (", ".join(bits) or "nothing new") + "."
    if result["failed"]:
        msg += f" {len(result['failed'])} row{'s' if len(result['failed']) != 1 else ''} could not be saved ({result['failed'][0]})."
    store.set_current_search(state["search_id"])
    return redirect("/board", notice=msg)


@router.get("/places.csv", include_in_schema=False)
def places_csv(request: Request, search_id: int | None = None, stage: str = "", q: str = ""):
    store = get_store(request)
    if search_id is None:
        cur = store.current_search()
        search_id = cur["id"] if cur else None
    if search_id is None:
        return redirect("/search", error="Make a search first, then there is something to export.")
    try:
        search = store.get_search(search_id)
    except NotFound:
        return redirect("/", error="That search doesn't exist.")
    places = store.list_places(search_id, stage=stage or None, query=q or None)
    slug = re.sub(r"[^a-z0-9]+", "-", search["name"].lower()).strip("-")[:40] or "places"
    name = f"places-{slug}-{datetime.now().strftime('%Y-%m-%d')}.csv"
    rows = enrich.enrich_places(store, search, places)
    return Response(csv_io.export_csv(rows, store.list_anchors(), search.get("people") or 1), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})
