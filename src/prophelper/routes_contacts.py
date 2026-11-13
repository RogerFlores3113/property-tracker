"""Contacts: landlords, agents and leasing offices, who you talked to, and who still owes you a reply.

    GET  /contacts                              the list (?q= searches), with "waiting on a reply" marked; POST /contacts adds one
    GET  /contacts/{id}                         one contact: details, places, conversation log
    POST /contacts/{id}                         save the details
    POST /contacts/{id}/delete                  delete (tick box to confirm)
    POST /contacts/{id}/log                     log a call, email, text or visit (out: you wrote; in: they wrote)
    POST /contacts/{id}/link | /unlink          link the contact to a place or take it off
    POST /contact-log/{id}/delete               remove one log line
    POST /places/{id}/contacts                  (place page) add a contact and link it to this place
    POST /places/{id}/contacts/link             (place page) link an existing contact
    POST /places/{id}/contacts/log              (place page) log a conversation about this place
    POST /places/{id}/contacts/{cid}/unlink     (place page) take a contact off this place

"Waiting on a reply" comes from ``Store.waiting_on_reply``: a contact whose latest log line is one you sent and is older
than the follow-up days setting (3 by default).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from .deps import back, get_store, redirect, render
from .store import NotFound, Store

router = APIRouter()


def _contact_or_404(store: Store, contact_id: int) -> dict[str, Any]:
    try:
        return store.get_contact(contact_id)
    except NotFound:
        raise HTTPException(404, "That contact doesn't exist (it may have been deleted).") from None


def _place_or_404(store: Store, place_id: int) -> dict[str, Any]:
    try:
        return store.get_place(place_id)
    except NotFound:
        raise HTTPException(404, "That place doesn't exist (it may have been deleted).") from None


def _optional_id(value: Any) -> int | None:
    text = str(value or "").strip()
    return int(text) if text.isdigit() and int(text) > 0 else None


def waiting_by_contact(store: Store) -> dict[int, dict[str, Any]]:
    """Contact id -> the ``waiting_on_reply`` row, for contacts who owe a reply right now."""
    return {w["contact"]["id"]: w for w in store.waiting_on_reply()}


# --------------------------------------------------------------------------- the list
@router.get("/contacts", include_in_schema=False)
def contacts_page(request: Request, q: str = ""):
    store = get_store(request)
    contacts = store.list_contacts(query=q)
    waiting = waiting_by_contact(store)
    rows = []
    for c in contacts:
        log = store.list_contact_log(contact_id=c["id"])
        rows.append({"contact": c, "last": log[0] if log else None, "waiting": waiting.get(c["id"]),
                     "places": store.places_for_contact(c["id"])})
    rows.sort(key=lambda r: (r["waiting"] is None, r["contact"]["name"].lower()))
    return render(request, "contacts.html", rows=rows, q=q, waiting_count=len(waiting), total=len(store.list_contacts()),
                  follow_up_days=store.get_setting_int("follow_up_days", 3))


@router.post("/contacts", include_in_schema=False)
async def add_contact(request: Request):
    store = get_store(request)
    form = await request.form()
    try:
        c = store.add_contact(str(form.get("name", "")), role=str(form.get("role") or "other"), company=str(form.get("company", "")),
                              email=str(form.get("email", "")), phone=str(form.get("phone", "")), notes=str(form.get("notes", "")))
    except ValueError as exc:
        return redirect("/contacts", error=str(exc))
    place_id = _optional_id(form.get("place_id"))
    if place_id:
        try:
            store.link_contact(place_id, c["id"])
        except NotFound:
            pass
    return redirect(f"/contacts/{c['id']}", notice=f"Added {c['name']}.")


# --------------------------------------------------------------------------- one contact
@router.get("/contacts/{contact_id}", include_in_schema=False)
def contact_page(request: Request, contact_id: int):
    store = get_store(request)
    contact = _contact_or_404(store, contact_id)
    linked = store.places_for_contact(contact_id)
    linked_ids = {p["id"] for p in linked}
    search = store.current_search()
    options = [p for p in (store.list_places(search["id"]) if search else []) if p["id"] not in linked_ids]
    titles = {p["id"]: p["title"] for p in linked + options}
    log = store.list_contact_log(contact_id=contact_id)
    for entry in log:
        if entry["place_id"] and entry["place_id"] not in titles:
            try:
                titles[entry["place_id"]] = store.get_place(entry["place_id"])["title"]
            except NotFound:
                pass
    return render(request, "contact.html", contact=contact, places=linked, options=options, log=log, titles=titles,
                  waiting=waiting_by_contact(store).get(contact_id), follow_up_days=store.get_setting_int("follow_up_days", 3))


@router.post("/contacts/{contact_id}", include_in_schema=False)
async def save_contact(request: Request, contact_id: int):
    store = get_store(request)
    _contact_or_404(store, contact_id)
    form = await request.form()
    try:
        store.update_contact(contact_id, **{k: str(form.get(k, "")) for k in ("name", "role", "company", "email", "phone", "notes") if k in form})
    except ValueError as exc:
        return redirect(f"/contacts/{contact_id}", error=str(exc))
    return redirect(f"/contacts/{contact_id}", notice="Saved.")


@router.post("/contacts/{contact_id}/delete", include_in_schema=False)
async def delete_contact(request: Request, contact_id: int):
    store = get_store(request)
    contact = _contact_or_404(store, contact_id)
    form = await request.form()
    if str(form.get("confirm", "")) != "yes":
        return redirect(f"/contacts/{contact_id}", error="Tick the box to confirm. Deleting a contact also deletes its conversation log.")
    store.delete_contact(contact_id)
    return redirect("/contacts", notice=f"Deleted {contact['name']}.")


@router.post("/contacts/{contact_id}/log", include_in_schema=False)
async def log_conversation(request: Request, contact_id: int):
    store = get_store(request)
    _contact_or_404(store, contact_id)
    form = await request.form()
    day = str(form.get("day", "")).strip()
    try:
        store.log_contact(contact_id, str(form.get("kind", "email")), str(form.get("body", "")),
                          direction=str(form.get("direction", "out")), place_id=_optional_id(form.get("place_id")), at=day or None)
    except (ValueError, NotFound) as exc:
        return redirect(f"/contacts/{contact_id}#log", error=str(exc))
    return redirect(f"/contacts/{contact_id}#log", notice="Added to the log.")


@router.post("/contact-log/{log_id}/delete", include_in_schema=False)
def delete_log(request: Request, log_id: int):
    store = get_store(request)
    store.delete_contact_log(log_id)
    return back(request, "/contacts", notice="Removed that line from the log.")


@router.post("/contacts/{contact_id}/link", include_in_schema=False)
async def link_place(request: Request, contact_id: int):
    store = get_store(request)
    _contact_or_404(store, contact_id)
    form = await request.form()
    try:
        store.link_contact(_optional_id(form.get("place_id")) or 0, contact_id)
    except NotFound as exc:
        return redirect(f"/contacts/{contact_id}#places", error=str(exc))
    return redirect(f"/contacts/{contact_id}#places", notice="Linked.")


@router.post("/contacts/{contact_id}/unlink", include_in_schema=False)
async def unlink_place(request: Request, contact_id: int):
    store = get_store(request)
    _contact_or_404(store, contact_id)
    form = await request.form()
    store.unlink_contact(_optional_id(form.get("place_id")) or 0, contact_id)
    return redirect(f"/contacts/{contact_id}#places", notice="Taken off that place.")


# --------------------------------------------------------------------------- from the place page
@router.post("/places/{place_id}/contacts", include_in_schema=False)
async def place_add_contact(request: Request, place_id: int):
    store = get_store(request)
    _place_or_404(store, place_id)
    form = await request.form()
    try:
        c = store.add_contact(str(form.get("name", "")), role=str(form.get("role") or "other"), company=str(form.get("company", "")),
                              email=str(form.get("email", "")), phone=str(form.get("phone", "")))
    except ValueError as exc:
        return redirect(f"/places/{place_id}#contacts", error=str(exc))
    store.link_contact(place_id, c["id"])
    return redirect(f"/places/{place_id}#contacts", notice=f"Added {c['name']} to this place.")


@router.post("/places/{place_id}/contacts/link", include_in_schema=False)
async def place_link_contact(request: Request, place_id: int):
    store = get_store(request)
    _place_or_404(store, place_id)
    form = await request.form()
    try:
        store.link_contact(place_id, _optional_id(form.get("contact_id")) or 0)
    except NotFound:
        return redirect(f"/places/{place_id}#contacts", error="Pick a contact to link.")
    return redirect(f"/places/{place_id}#contacts", notice="Linked.")


@router.post("/places/{place_id}/contacts/log", include_in_schema=False)
async def place_log(request: Request, place_id: int):
    store = get_store(request)
    _place_or_404(store, place_id)
    form = await request.form()
    cid = _optional_id(form.get("contact_id"))
    if not cid:
        return redirect(f"/places/{place_id}#contacts", error="Pick who it was with.")
    try:
        store.log_contact(cid, str(form.get("kind", "email")), str(form.get("body", "")), direction=str(form.get("direction", "out")),
                          place_id=place_id)
    except (ValueError, NotFound) as exc:
        return redirect(f"/places/{place_id}#contacts", error=str(exc))
    return redirect(f"/places/{place_id}#contacts", notice="Added to the log.")


@router.post("/places/{place_id}/contacts/{contact_id}/unlink", include_in_schema=False)
def place_unlink(request: Request, place_id: int, contact_id: int):
    store = get_store(request)
    _place_or_404(store, place_id)
    store.unlink_contact(place_id, contact_id)
    return redirect(f"/places/{place_id}#contacts", notice="Taken off this place.")
