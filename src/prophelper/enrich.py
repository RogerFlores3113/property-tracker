"""Everything a page needs to show a place: its true monthly cost, score, commutes and next date.

Pages, the map, the calendar and compare all call :func:`enrich_places` so they agree. It reads the store and does
the pure maths in ``money``, ``scoring``, ``commute`` and ``redflags``; it writes nothing.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from . import commute as commute_mod
from . import helpers, money, redflags, scoring
from .store import Store


def _next_date(place: dict[str, Any], tours: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The soonest thing coming up for a place: a booked tour, else a lease start, else the move-in date."""
    now = datetime.now(timezone.utc).isoformat()
    for t in tours:
        if t["status"] == "booked" and t["starts_at"] >= now:
            return {"kind": "tour", "text": "Tour " + helpers.local_time(t["starts_at"]), "date": helpers.local_date(t["starts_at"]),
                    "rel": helpers.until(helpers.local_date(t["starts_at"]))}
    today = date.today().isoformat()
    for key, label in (("lease_start", "Lease starts"), ("available_from", "Available")):
        value = place.get(key)
        if value and value >= today:
            return {"kind": key, "text": f"{label} {helpers.day_text(value)}", "date": value, "rel": helpers.until(value)}
    return None


def enrich_place(store: Store, place: dict[str, Any], search: dict[str, Any], *, anchors: list[dict[str, Any]] | None = None,
                 commutes: list[dict[str, Any]] | None = None, criteria: list[dict[str, Any]] | None = None,
                 tours: list[dict[str, Any]] | None = None, peer_prices: list[float] | None = None,
                 settings: dict[str, Any] | None = None, protected: bool | None = None) -> dict[str, Any]:
    """One place with the extra keys: ``cost`` (money breakdown), ``cost_total``, ``score`` (scoring result),
    ``score_total``, ``band``, ``commutes`` (all resolved), ``top_commute``, ``next``, ``flags`` (things to check),
    ``hidden_by_dealbreaker``, ``people`` and ``per_person`` (the cost split, when more than one person shares it).
    A place is never hidden by a deal-breaker when it has a tour, a linked contact or a stage past Saved
    (``protected``; looked up when left as None)."""
    anchors = store.list_anchors() if anchors is None else anchors
    commutes = store.list_commutes(place["id"]) if commutes is None else commutes
    criteria = store.list_criteria(search["id"]) if criteria is None else criteria
    tours = store.list_tours(place["id"]) if tours is None else tours
    settings = store.buy_settings() if settings is None else settings
    people = int(search.get("people") or 1)
    cost = money.true_monthly_cost(place, search["mode"], settings, people, pets=money.has_pets(search.get("pet_kind")))
    flags = redflags.local_flags(place, peer_prices or [])
    serious = redflags.is_serious(place, peer_prices or [])
    score = scoring.score_place(place, criteria, mode=search["mode"], anchors=anchors, commutes=commutes,
                                custom_scores=store.custom_scores(place["id"]), budget_max=search.get("budget_max"),
                                settings=settings, cost=cost, serious_flag=serious, people=people,
                                pets={"kind": (search.get("pet_kind") or "") if money.has_pets(search.get("pet_kind")) else "", "weight": search.get("pet_weight"), "count": search.get("pet_count")})
    if protected is None:
        protected = place["id"] in store.protected_place_ids(search["id"])
    prefer = next((c["target"].get("mode") for c in criteria if c["kind"] == "commute"), None)
    by_id = {a["id"]: a for a in anchors}
    first_anchor = anchors[0]["id"] if anchors else None
    commute_tops = []
    for c in criteria:
        if c["kind"] != "commute":
            continue
        anchor = by_id.get(c["target"].get("anchor_id") or first_anchor)
        mode = c["target"].get("mode") or "bike"
        found = commute_mod.pick_for_anchor(place, anchor, commutes, mode)[1] if anchor else None
        if found and not any(t["anchor_id"] == anchor["id"] for t in commute_tops):
            commute_tops.append({"anchor": anchor["name"], "anchor_id": anchor["id"], **found,
                                 "short": f"{anchor['name']} {found['minutes']:.0f} min {found['mode']}"})
    # One commute per anchor for Compare and the place page: the mode of that anchor's commute criterion, else the fastest way.
    crit_rows = commute_mod.place_rows(place, anchors, commutes, criteria)
    commute_all = [{"anchor": r["anchor"]["name"], "anchor_id": r["anchor"]["id"], **r["found"]} for r in crit_rows if r["found"]]
    out = dict(place)
    out.update({
        "commute_all": commute_all, "commute_rows": crit_rows,
        "cost": cost, "cost_total": cost["total"], "score": score, "score_total": score["total"],
        "band": scoring.score_band(score["total"]),
        "commutes": commute_mod.resolve_all(place, anchors, commutes),
        "top_commute": commute_mod.top_commute(place, anchors, commutes, prefer),
        "commute_tops": commute_tops,
        "next": _next_date(place, tours),
        "flags": flags, "possible_scam": serious,
        "hidden_by_dealbreaker": bool(search.get("hide_dealbreakers") and score["fails_dealbreaker"] and not protected),
        "people": people, "per_person": cost.get("per_person"),
        "opinions": store.opinion_stats(place["id"]) if people > 1 else None,  # {"count", "average"} of the people's own ratings
    })
    return out


def enrich_places(store: Store, search: dict[str, Any], places: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Enrich many places of one search with the shared lookups done once. ``places`` defaults to the search's
    open (not archived) places."""
    places = store.list_places(search["id"]) if places is None else places
    anchors = store.list_anchors()
    criteria = store.list_criteria(search["id"])
    commutes = store.list_commutes_for_search(search["id"])
    tours_by: dict[int, list[dict[str, Any]]] = {}
    for t in store.list_tours(search_id=search["id"]):
        tours_by.setdefault(t["place_id"], []).append(t)
    settings = store.buy_settings()
    protected = store.protected_place_ids(search["id"])
    all_prices = [p["price"] for p in store.list_places(search["id"]) if p.get("price")]
    out = []
    for p in places:
        peers = list(all_prices)
        if p.get("price") in peers:
            peers.remove(p["price"])
        out.append(enrich_place(store, p, search, anchors=anchors, commutes=commutes.get(p["id"], []), criteria=criteria,
                                tours=tours_by.get(p["id"], []), peer_prices=peers, settings=settings,
                                protected=p["id"] in protected))
    return out
