"""The application checklist: one reusable list of what a landlord (or, for a buyer, a lender and seller) usually asks for.
A fresh list starts with renter items, or buyer items when the very first search is a buy search; lists you already have are never changed.

    GET  /checklist                      the list, with how many are ready
    POST /checklist/defaults             add the usual items for rent or buy that the list doesn't have yet
    POST /checklist/items                add an item
    POST /checklist/items/{id}           save its label and note
    POST /checklist/items/{id}/done      tick it or untick it (value=1 or 0)
    POST /checklist/items/{id}/move      move it up or down (direction=up or down)
    POST /checklist/items/{id}/delete    remove it
    POST /places/{place_id}/checklist/{item_id}   tick or untick an item for one place (value=1 or 0)

The app keeps the list, not copies of the documents.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from .deps import get_store, redirect, render
from .store import NotFound, Store

router = APIRouter()


def _item_or_404(store: Store, item_id: int) -> dict[str, Any]:
    try:
        return store.get_checklist_item(item_id)
    except NotFound:
        raise HTTPException(404, "That checklist item doesn't exist (it may have been removed).") from None


@router.get("/checklist", include_in_schema=False)
def checklist_page(request: Request):
    store = get_store(request)
    search = store.current_search()
    mode = search["mode"] if search else "rent"
    items = store.visible_checklist(search)
    have = {i["label"].strip().lower() for i in store.list_checklist()}
    has_pets = bool(search and search.get("pet_kind"))
    missing = [label for label, _n in store.default_checklist(mode)
               if label.strip().lower() not in have and (has_pets or label.strip().lower() != "pet records")]
    places = store.list_places(search["id"]) if search and mode != "buy" else []
    return render(request, "checklist.html", items=items, done=sum(1 for i in items if i["done"]), mode=mode, missing=missing,
                  places=places[:12])


@router.post("/checklist/defaults", include_in_schema=False)
async def add_defaults(request: Request):
    store = get_store(request)
    form = await request.form()
    mode = "buy" if str(form.get("mode", "")) == "buy" else "rent"
    n = store.add_default_checklist_items(mode)
    return redirect("/checklist", notice=f"Added {n} item{'s' if n != 1 else ''}." if n else "You already have all of those.")


@router.post("/checklist/items", include_in_schema=False)
async def add_item(request: Request):
    store = get_store(request)
    form = await request.form()
    try:
        store.add_checklist_item(str(form.get("label", "")), str(form.get("note", "")))
    except ValueError as exc:
        return redirect("/checklist", error=str(exc))
    return redirect("/checklist#add", notice="Added.")


@router.post("/checklist/items/{item_id}", include_in_schema=False)
async def save_item(request: Request, item_id: int):
    store = get_store(request)
    _item_or_404(store, item_id)
    form = await request.form()
    try:
        store.update_checklist_item(item_id, label=str(form.get("label", "")), note=str(form.get("note", "")))
    except ValueError as exc:
        return redirect(f"/checklist#item-{item_id}", error=str(exc))
    return redirect(f"/checklist#item-{item_id}", notice="Saved.")


@router.post("/checklist/items/{item_id}/done", include_in_schema=False)
async def set_done(request: Request, item_id: int):
    store = get_store(request)
    _item_or_404(store, item_id)
    form = await request.form()
    on = str(form.get("value", "1")) == "1"
    store.update_checklist_item(item_id, done=on)
    return redirect(f"/checklist#item-{item_id}", notice="Marked ready." if on else "Marked not ready.")


@router.post("/checklist/items/{item_id}/move", include_in_schema=False)
async def move_item(request: Request, item_id: int):
    store = get_store(request)
    _item_or_404(store, item_id)
    form = await request.form()
    store.move_checklist_item(item_id, -1 if str(form.get("direction", "")) == "up" else 1)
    return redirect(f"/checklist#item-{item_id}")


@router.post("/checklist/items/{item_id}/delete", include_in_schema=False)
def delete_item(request: Request, item_id: int):
    store = get_store(request)
    item = _item_or_404(store, item_id)
    store.delete_checklist_item(item_id)
    return redirect("/checklist", notice=f"Removed {item['label']}.")


@router.post("/places/{place_id}/checklist/{item_id}", include_in_schema=False)
async def set_place_done(request: Request, place_id: int, item_id: int):
    store = get_store(request)
    try:
        store.get_place(place_id)
    except NotFound:
        raise HTTPException(404, "That place doesn't exist (it may have been deleted).") from None
    item = _item_or_404(store, item_id)
    form = await request.form()
    on = str(form.get("value", "1")) == "1"
    store.set_place_checklist(place_id, item_id, on)
    return redirect(f"/places/{place_id}#apply-item-{item_id}",
                    notice=f"{item['label']}: done for this place." if on else f"{item['label']}: not done for this place.")
