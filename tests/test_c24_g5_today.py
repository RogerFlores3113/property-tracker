"""Cycle 24 G5 item 3: Today's cost check and "fit if unknowns check out" keep out scam-hinted and very-low-rent places."""
from pathlib import Path

from mcp_util import call, server, text
from prophelper import enrich, today

L9 = ("GREAT DEAL!! 3 bed house only $650/mo, fenced yard, dogs ok, no deposit. Contact owner by text only, "
      "123 Nowhere Ln, Foster City. Cashier check to hold.")


def _setup(store):
    s = store.add_search("Fam", "rent", pet_kind="dog")
    store.add_criterion(s["id"], "price", weight=50, dealbreaker=False, target={"max": 2500})
    srv = server(store)
    call(srv, "add_place", listing_text=L9, title="Scammy")
    call(srv, "add_place", title="Junk", address="5 B St", price=1, beds=3)
    call(srv, "add_place", title="Ok", address="6 B St", price=2000, beds=3, tenant_pays="electric")
    return s, srv


def _titles(items):
    return [(i["place"] if "place" in i else i)["title"] for i in items]


def test_cost_check_keeps_out_scam_hint_and_low_rent(store):
    s, srv = _setup(store)
    out = today.build(store, store.get_search(s["id"]))
    assert _titles(out["cost_check"]) == ["Ok"]
    assert _titles(out["unconfirmed"]) == ["Ok"] or out["unconfirmed"] == []
    assert not any(t in _titles(out["unconfirmed"]) for t in ("Scammy", "Junk"))
    listing = text(call(srv, "todays_list"))
    assert "Needs a cost check: #3" in listing
    assert "Needs a cost check: #1" not in listing and "Needs a cost check: #2" not in listing


def test_unconfirmed_keeps_out_scam_hint_and_low_rent(store):
    s, _ = _setup(store)
    rows = enrich.enrich_places(store, store.get_search(s["id"]))
    assert not any(t in _titles(today.unconfirmed(rows)) for t in ("Scammy", "Junk"))
    assert today.scam_hint_or_low_rent(next(p for p in rows if p["title"] == "Scammy"))
    assert today.scam_hint_or_low_rent(next(p for p in rows if p["title"] == "Junk"))
    assert not today.scam_hint_or_low_rent(next(p for p in rows if p["title"] == "Ok"))


def test_other_wordings_of_low_rent_and_hint(store):
    s = store.add_search("F", "rent")
    store.add_criterion(s["id"], "price", weight=50, dealbreaker=False, target={"max": 2500})
    srv = server(store)
    call(srv, "add_place", title="Cheap", address="1 A St", price=150, beds=2, tenant_pays="gas")
    call(srv, "add_place", title="Wa", address="2 A St", price=900, beds=2, tenant_pays="gas",
         listing_text="Nice 2 bed. Message me on WhatsApp only. Wire the deposit today.")
    rows = enrich.enrich_places(store, store.get_search(s["id"]))
    assert today.cost_check(rows) == []
