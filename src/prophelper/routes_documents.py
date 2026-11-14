"""Documents a person adds to a place. Only the app window does this (there is no AI tool for files).

    POST /places/{id}/documents     upload one file (up to 20 MB) with a kind: lease, application, disclosure, ...
    GET  /files/{document_id}       download it (always as an attachment; "/files/" is a protected download path)
    POST /documents/{id}/delete     delete the file and its row (tick box to confirm)

Files are stored under ``<data folder>/files/<place id>/`` with generated names (see ``docfiles.py``).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from . import docfiles
from .deps import get_store, redirect
from .routes_data import discard_body
from .store import DOCUMENT_KINDS, NotFound, Store

router = APIRouter()
OVERHEAD_BYTES = 256 * 1024  # form fields and boundaries around the file
DRAIN_BYTES = 2 * docfiles.LIMIT_BYTES + OVERHEAD_BYTES  # the most we read and discard from a too-big upload


def _place_or_404(store: Store, place_id: int) -> dict[str, Any]:
    try:
        return store.get_place(place_id)
    except NotFound:
        raise HTTPException(404, "That place doesn't exist (it may have been deleted).") from None


def _document_or_404(store: Store, document_id: int) -> dict[str, Any]:
    try:
        return store.get_document(document_id)
    except NotFound:
        raise HTTPException(404, "That file doesn't exist (it may have been deleted).") from None


@router.post("/places/{place_id}/documents", include_in_schema=False)
async def upload_document(request: Request, place_id: int):
    store = get_store(request)
    _place_or_404(store, place_id)
    target = f"/places/{place_id}#documents"
    try:  # a browser states the size up front: refuse a huge one before reading it
        declared = int(request.headers.get("content-length") or 0)
    except ValueError:
        declared = 0
    if declared > docfiles.LIMIT_BYTES + OVERHEAD_BYTES:
        # Refuse before keeping any of it, but read and discard the rest of what the browser is sending (up to twice the
        # limit), or the browser sees a reset connection instead of our friendly answer.
        await discard_body(request, DRAIN_BYTES)
        return redirect(target, error=docfiles.too_big_text())
    form = await request.form()
    upload = form.get("file")
    kind = str(form.get("kind") or "other")
    if kind not in DOCUMENT_KINDS:
        return redirect(target, error="Pick what kind of document it is.")
    if upload is None or isinstance(upload, str) or not getattr(upload, "filename", ""):
        return redirect(target, error="Choose a file first.")
    data = await upload.read(docfiles.LIMIT_BYTES + 1)  # one byte more than allowed is enough to know it is too big
    await upload.close()
    shown = docfiles.display_name(upload.filename)
    try:
        stored = docfiles.save(place_id, upload.filename, data)
    except ValueError as exc:
        return redirect(target, error=str(exc))
    try:
        store.add_document(place_id, stored, shown, kind, len(data))
    except ValueError as exc:
        docfiles.remove(place_id, stored)
        return redirect(target, error=str(exc))
    return redirect(target, notice=f"Added {shown}.")


@router.get("/files/{document_id}", include_in_schema=False)
def download_document(request: Request, document_id: int):
    store = get_store(request)
    doc = _document_or_404(store, document_id)
    path = docfiles.stored_path(doc["place_id"], doc["stored_name"])
    if path is None:
        raise HTTPException(404, "The file for this document is missing from the files folder.")
    return FileResponse(path, media_type="application/octet-stream", headers=docfiles.attachment_headers(doc["original_name"], path.stat().st_size))


@router.post("/documents/{document_id}/delete", include_in_schema=False)
async def delete_document(request: Request, document_id: int):
    store = get_store(request)
    doc = _document_or_404(store, document_id)
    form = await request.form()
    target = f"/places/{doc['place_id']}#documents"
    if str(form.get("confirm", "")) != "yes":
        return redirect(target, error="Tick the box to confirm. Deleting a file can't be undone.")
    store.delete_document(document_id)
    docfiles.remove(doc["place_id"], doc["stored_name"])
    store.add_event(doc["place_id"], "document", f"Removed {doc['kind']} document: {doc['original_name']}", source="you")
    return redirect(target, notice=f"Deleted {doc['original_name']}.")
