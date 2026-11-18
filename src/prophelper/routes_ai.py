"""AI help on the place page (bring your own key): fit score, red-flag check, tour questions, message draft.

    GET  /ai                              A short explainer page
    GET  /ai/status                       Whether a key is set (JSON; never the key)
    POST /ai/test-key                     One tiny request to check the saved key (sends no place data), then back to the page
    GET  /places/{id}/ai                  The AI panel for a place (an HTMX fragment for #ai-panel; a whole page without HTMX)
    POST /places/{id}/ai/{feature}        Run one feature (fit, flags, questions, message) and return the panel

``_place_ai.html`` is included on the place page; it fetches the panel itself. Drafts are saved; the app sends nothing.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from . import ai, enrich
from .deps import back, get_store, is_htmx, render
from .store import NotFound, Store

router = APIRouter()


def panel_context(store: Store, place_id: int, **extra: Any) -> dict[str, Any]:
    """Everything the AI panel needs for the filled-in panel."""
    place = store.get_place(place_id)
    search = store.get_search(place["search_id"])
    latest: dict[str, dict[str, Any]] = {}
    for draft in store.list_drafts(place_id):  # newest first
        latest.setdefault(draft["kind"], draft)
    buy = search["mode"] == "buy"
    features = [{"slug": slug, **info, **({"help": info["help_buy"]} if buy and info.get("help_buy") else {})} for slug, info in ai.FEATURES.items()]
    key = ai.key_status()
    prompts: dict[str, str] = {}
    if key["set"]:  # the exact text that goes to Anthropic, so nothing is a surprise
        for f in features:
            try:
                system, prompt, _ = ai.build_prompt(store, place_id, f["slug"])
                prompts[f["slug"]] = system + "\n\n" + prompt
            except ValueError:
                continue
    panel = {"key": key, "features": features, "latest": latest, "prompts": prompts, "result": None, "error": "", "active": "",
             "purposes": [(slug, label) for slug, (label, _) in ai.purposes_for(search["mode"]).items()], "purpose": ai.DEFAULT_PURPOSE,
             "model": store.get_setting("ai_model") or ai.DEFAULT_MODEL, "has_listing": bool((place.get("listing_text") or "").strip())}
    panel.update(extra)
    full = enrich.enrich_places(store, search, [place])[0]
    return {"place": full, "search": search, "ai": panel}


def _panel_response(request: Request, place_id: int, **extra: Any):
    ctx = panel_context(get_store(request), place_id, **extra)
    if is_htmx(request):
        return render(request, "_place_ai_panel.html", **ctx)
    return render(request, "place_ai.html", **ctx)


def _not_found(request: Request):
    return render(request, "message.html", status_code=404, title="Not found", message="That place doesn't exist (it may have been deleted).")


@router.get("/ai", include_in_schema=False)
def ai_home(request: Request):
    status = ai.key_status()
    msg = ("Open any place and use the AI help box: a fit score, a red-flag check, questions for a tour and a message you can send. "
           + ("Your own key is set, so it works inside the app."
              if status["set"] else "Add your own Anthropic key in Settings, or copy the prompt into Claude."))
    return render(request, "message.html", title="AI help", message=msg)


@router.get("/ai/status", include_in_schema=False)
def ai_status():
    status = ai.key_status()
    return JSONResponse({"key_set": status["set"], "source": status["source"], "hint": status["hint"]})


@router.post("/ai/test-key", include_in_schema=False)
def ai_test_key(request: Request):
    """One tiny request to check the saved key. It sends the word "OK" and no place, note or listing."""
    store = get_store(request)
    if not ai.key_status()["set"]:
        return back(request, "/settings#ai", error="No key is saved yet. Paste your key above and save it first.")
    try:
        message = ai.check_key(store.get_setting("ai_model") or ai.DEFAULT_MODEL)
    except ai.AIError as exc:
        return back(request, "/settings#ai", error=str(exc))
    return back(request, "/settings#ai", notice=message)


@router.get("/places/{place_id}/ai", include_in_schema=False)
def place_ai_panel(request: Request, place_id: int):
    try:
        return _panel_response(request, place_id)
    except NotFound:
        return _not_found(request)


@router.post("/places/{place_id}/ai/{feature}", include_in_schema=False)
async def place_ai_run(request: Request, place_id: int, feature: str):
    store = get_store(request)
    if ai.feature_info(feature) is None:
        return render(request, "message.html", status_code=404, title="Not found", message="That AI feature doesn't exist.")
    form = await request.form()
    purpose = str(form.get("purpose") or ai.DEFAULT_PURPOSE)
    if purpose not in ai.PURPOSES:
        purpose = ai.DEFAULT_PURPOSE
    result, error = None, ""
    try:
        store.get_place(place_id)
        result = ai.run_feature(store, place_id, feature, purpose)
    except NotFound:
        return _not_found(request)
    except (ai.AIError, ValueError) as exc:
        error = str(exc)
    return _panel_response(request, place_id, result=result, error=error, active=feature, purpose=purpose)
