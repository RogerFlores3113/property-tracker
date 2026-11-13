"""Compare 2 to 4 places side by side.

    GET /compare                 a picker (checkboxes of the current search's places)
    GET /compare?ids=3,5,8       the comparison (also ?ids=3&ids=5 from the picker)

Nothing is written. Places from different searches can be compared; each one's cost uses its own search's mode.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from . import compare, enrich, share
from .deps import get_store, redirect, render
from .store import NotFound

router = APIRouter()


@router.get("/compare", include_in_schema=False)
def compare_page(request: Request, ids: list[str] | None = Query(default=None)):
    store = get_store(request)
    search = store.current_search()
    options = store.list_places(search["id"]) if search else []
    ctx: dict[str, Any] = {"search": search, "options": options, "picked": [], "places": [], "sections": [], "summary": [],
                           "problem": "", "missing": 0}
    if not ids:
        return render(request, "compare.html", **ctx)
    wanted: list[int] = []
    try:
        wanted = compare.parse_ids(ids)
        found, missing = [], 0
        for pid in wanted:
            try:
                found.append(store.get_place(pid))
            except NotFound:
                missing += 1
        compare.check_count(len(found))
    except compare.CompareError as exc:
        ctx.update(problem=str(exc), picked=wanted)
        return render(request, "compare.html", status_code=400, **ctx)
    places = []
    for p in found:
        places.append(enrich.enrich_places(store, store.get_search(p["search_id"]), [p])[0])
    for p in places:
        p["opinion_rows"] = share.opinions_for(store, p["id"])
    sections = compare.build_rows(places)
    ctx.update(places=places, sections=sections, summary=compare.summary_lines(places, sections), picked=[p["id"] for p in places],
               missing=missing)
    return render(request, "compare.html", **ctx)


# --------------------------------------------------------------------------- share a copy
@router.get("/compare/share.html", include_in_schema=False)
def compare_share(request: Request, ids: list[str] | None = Query(default=None), notes: int = 0):
    """Download the comparison as one self-contained page to send to someone (see ``share.py``). ``notes=1`` adds the
    person's own notes and their people's ratings; otherwise those, contacts and documents stay out."""
    store = get_store(request)
    try:
        found = []
        for pid in compare.parse_ids(ids or []):
            try:
                found.append(store.get_place(pid))
            except NotFound:
                pass
        compare.check_count(len(found))
    except compare.CompareError as exc:
        return redirect("/compare", error=str(exc))
    places = [enrich.enrich_places(store, store.get_search(p["search_id"]), [p])[0] for p in found]
    for p in places:
        p["opinion_rows"] = share.opinions_for(store, p["id"])  # shown only with notes=1 (see share.comparison_sections)
    html = share.comparison_html(request.app.state.templates, places, include_notes=bool(notes))
    return Response(html, media_type="text/html; charset=utf-8", headers={
        "Content-Disposition": f'attachment; filename="{share.comparison_filename()}"', "X-Content-Type-Options": "nosniff"})


# --------------------------------------------------------------------------- each person's opinion
@router.post("/places/{place_id}/opinions", include_in_schema=False)
async def save_opinions(request: Request, place_id: int):
    """Save every person's rating and note for a place (the app window only; these are the user's own words)."""
    if request.headers.get("x-prophelper-key"):  # the key header is for the command line and AI apps: never for these words
        return redirect(f"/places/{place_id}", error="Ratings and notes from your people can only be saved from the app window.")
    store = get_store(request)
    try:
        slots = store.opinion_slots(place_id)
    except NotFound:
        raise HTTPException(404, "That place doesn't exist (it may have been deleted).") from None
    form = await request.form()
    try:
        with store._write():
            for i, slot in enumerate(slots):
                store.set_opinion(place_id, slot["person"], form.get(f"rating_{i}", ""), form.get(f"note_{i}", ""))
    except ValueError as exc:
        return redirect(f"/places/{place_id}#opinions", error=str(exc))
    return redirect(f"/places/{place_id}#opinions", notice="Saved." if slots else "")
