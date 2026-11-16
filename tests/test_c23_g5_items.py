"""Cycle 23, G5: Today never lists places that already fail, ties by cost, short Check first reasons, sublets, low rent,
photo links, stale notes after update_place, Compare notes and special assessment wording, restored notes."""
import sqlite3

import pytest

from mcp_util import call, server, text
from prophelper import backups, compare, enrich, today


def _rows(store, s):
    return enrich.enrich_places(store, store.get_search(s["id"]))


def _rent(store, dealbreaker=True, move_in=None, budget=1500):
    s = store.add_search("R", "rent", **({"move_in": move_in} if move_in else {}))
    store.add_criterion(s["id"], "price", weight=50, dealbreaker=dealbreaker, target={"max": budget})
    return s


# ---------------------------------------------------------------- 1 failing places never in Needs a cost check
@pytest.mark.parametrize("dealbreaker", [True, False])
@pytest.mark.parametrize("price", [1688, 1694, 1747])
def test_over_budget_place_is_not_a_cost_check_or_best_fit(store, dealbreaker, price):
    s = _rent(store, dealbreaker)
    a, _ = store.add_place(title="Over", address="1 A St", price=price, beds=1, tenant_pays="electric, gas")
    ok, _ = store.add_place(title="Fine", address="2 A St", price=1300, beds=1, tenant_pays="electric, gas")
    rows = _rows(store, s)
    assert [c["place"]["title"] for c in today.cost_check(rows, {a["id"]})] == ["Fine"]
    assert today.best_fits(rows) == []
    out = text(call(server(store), "todays_list"))
    assert f"Needs a cost check: #{a['id']}" not in out and f"Needs a cost check: #{ok['id']}" in out


def test_over_budget_with_no_cost_unknowns_is_not_listed_either(store):
    s = _rent(store)
    store.add_place(title="Over", address="1 A St", price=1700, beds=1, utilities_estimate=50)
    data = today.build(store, store.get_search(s["id"]))
    assert data["fits"] == [] and data["cost_check"] == [] and data["unconfirmed"] == []


# ---------------------------------------------------------------- 2 a hard limit is never a near miss
def _commute_setup(store, hard):
    s = store.add_search("Roomies", "rent", people=2)
    store.add_criterion(s["id"], "price", weight=50, dealbreaker=False, target={"max": 3000})
    a = store.add_anchor("Hospital", "x", 40.0, -88.0, search_id=s["id"])
    t = {"mode": "drive", "minutes": 40, "anchor_id": a["id"]}
    if hard:
        t["hard"] = True
    store.add_criterion(s["id"], "commute", weight=40, dealbreaker=hard, target=t)
    return s, a


@pytest.mark.parametrize("minutes", [41, 42, 55])
def test_hard_limit_failure_is_not_under_closest(store, minutes):
    s, a = _commute_setup(store, True)
    p, _ = store.add_place(title="Hyde Park", address="1 A St", price=2000, beds=2, utilities_estimate=100)
    store.set_commute(p["id"], a["id"], "drive", minutes, "you")
    rows = _rows(store, s)
    assert rows[0]["score"]["fit"] == "doesnt_fit" and today.hard_limit_failed(rows[0])
    data = today.build(store, store.get_search(s["id"]))
    assert data["closest"] == [] and data["near_miss"] == [] and data["cost_check"] == []
    assert "FAILS" in text(call(server(store), "list_places"))
    assert "Closest" not in text(call(server(store), "todays_list"))


def test_a_place_that_meets_the_hard_limit_passes(store):
    s, a = _commute_setup(store, True)
    p, _ = store.add_place(title="Ok", address="1 A St", price=2000, beds=2, utilities_estimate=100)
    store.set_commute(p["id"], a["id"], "drive", 40, "you")
    assert not today.hard_limit_failed(_rows(store, s)[0])


# ---------------------------------------------------------------- 3 ties by monthly cost
def test_same_score_orders_by_monthly_cost_lowest_first(store):
    s = _rent(store, budget=5000)
    store.add_place(title="A big", address="1 A St", price=2703, beds=1, utilities_estimate=0)
    store.add_place(title="B mid", address="2 A St", price=1820, beds=1, utilities_estimate=0)
    store.add_place(title="C small", address="3 A St", price=1528, beds=1, utilities_estimate=0)
    rows = _rows(store, s)
    assert {p["score_total"] for p in rows} == {100}
    assert [p["title"] for p in today.best_fits(rows, limit=5)] == ["C small", "B mid", "A big"]
    out = text(call(server(store), "todays_list"))
    assert out.index("C small") < out.index("B mid") < out.index("A big")


# ---------------------------------------------------------------- 4 short Check first reasons
@pytest.mark.parametrize("mode", ["rent", "buy"])
def test_check_first_is_short_and_per_place(store, mode):
    s = store.add_search("S", mode)
    flags = "Owner is abroad. Wire the deposit before a showing. Zelle only. Send your SSN first."
    for i in range(4):
        store.add_place(title=f"Scam {i}", address=f"{i + 1} A St", price=1000 if mode == "rent" else 250000, beds=1, listing_text=flags)
    data = today.build(store, store.get_search(s["id"]))
    texts = [c["text"] for c in data["check_first"]]
    assert len(texts) == 4
    for t in texts:
        assert len(t) < 330, t
        assert "Real landlords take a check" not in t and "Earnest money normally goes" not in t
    if mode == "buy":
        assert "contract" in texts[0] and "escrow" in texts[0]
    else:
        assert texts[0].endswith("Tour it and read the lease before you pay anything.")


def test_check_first_rent_exact_text(store):
    s = store.add_search("S", "rent")
    store.add_place(title="Scam", address="1 A St", price=1000, beds=1, listing_text="Owner is abroad. Wire the deposit before a showing.")
    data = today.build(store, store.get_search(s["id"]))
    assert data["check_first"][0]["text"] == ("It asks for payment in a way that is hard to undo (wire, gift card, crypto or a payment app). "
                                              "It asks for a deposit or fee before you have seen the place, or says there are no showings. "
                                              "Tour it and read the lease before you pay anything.")
    page = store.get_place(store.list_places(s["id"])[0]["id"])
    assert "Real landlords take a check" in " ".join(enrich.enrich_place(store, page, store.get_search(s["id"]))["flags"])


# ---------------------------------------------------------------- 5 sublets and short leases
SUBLET = "Subletting my 1 bed from June - Aug 2027 because I'm moving. $1,100 per month, 205 E Daniel St Champaign IL. Utilities about $90."


@pytest.mark.parametrize("words", [SUBLET, "Sublease available May to August 2027, 1 bed, $1,100 a month.", "Short-term lease Jun 2027 - Aug 2027. $1,100 per month."])
def test_sublet_not_in_best_fits(store, words):
    s = _rent(store, move_in="2027-08-01", budget=2000)
    store.add_place(title="Sub", address="1 A St", price=1100, beds=1, utilities_estimate=90, listing_text=words)
    store.add_place(title="Year", address="2 A St", price=1300, beds=1, utilities_estimate=90, listing_text="12 month lease. $1,300.")
    rows = _rows(store, s)
    sub = next(p for p in rows if p["title"] == "Sub")
    assert "does not cover a lease year from your move-in date" in sub["score"]["lease_gap"]
    assert [p["title"] for p in today.best_fits(rows)] == ["Year"]
    data = today.build(store, store.get_search(s["id"]))
    assert [l["place"]["title"] for l in data["late"]] == ["Sub"]


def test_sublet_note_exact_text(store):
    s = _rent(store, move_in="2027-08-01", budget=2000)
    store.add_place(title="Sub", address="1 A St", price=1100, beds=1, utilities_estimate=90, listing_text=SUBLET)
    sub = _rows(store, s)[0]
    assert sub["score"]["lease_gap"] == "This is a sublet (Jun 1, 2027 to Aug 31, 2027) and does not cover a lease year from your move-in date. Ask whether it can be extended"
    assert sub["score"]["fit_label"] == "Fits, but check"


def test_saved_lease_dates_are_used_and_a_covering_sublet_is_fine(store):
    s = _rent(store, move_in="2027-08-01", budget=2000)
    store.add_place(title="Short", address="1 A St", price=1100, beds=1, utilities_estimate=90, lease_start="2027-06-01", lease_end="2027-08-31")
    store.add_place(title="Covers", address="2 A St", price=1100, beds=1, utilities_estimate=90, lease_start="2027-08-01", lease_end="2028-07-31",
                    listing_text="Sublet for the full year.")
    rows = {p["title"]: p for p in _rows(store, s)}
    assert rows["Short"]["score"]["lease_gap"].startswith("This is a short lease (Jun 1, 2027 to Aug 31, 2027)")
    assert rows["Covers"]["score"]["lease_gap"] == ""
    assert [p["title"] for p in today.best_fits(list(rows.values()))] == ["Covers"]


def test_sublet_with_no_dates_asks_to_check(store):
    s = _rent(store, budget=2000)
    store.add_place(title="Sub", address="1 A St", price=1100, beds=1, utilities_estimate=90, listing_text="This is a sublet, $1,100 a month.")
    assert _rows(store, s)[0]["score"]["lease_gap"] == "This listing says it is a sublet. Check that the dates cover your move-in date and a whole lease year"


def test_buy_has_no_lease_gap(store):
    s = store.add_search("B", "buy")
    store.add_place(title="H", address="1 A St", price=250000, listing_text="sublet")
    assert _rows(store, s)[0]["score"]["lease_gap"] == ""


# ---------------------------------------------------------------- 6 a rent far below normal
LOW = ("the rent of $1 a month is far below normal for a rental, so the monthly cost looks too low. "
       "Confirm the real rent before you count on it")


@pytest.mark.parametrize("price,fired", [(1, True), (95, True), (199, True), (200, False), (900, False)])
def test_low_rent_function(price, fired):
    got = today.low_rent({"price": price}, "rent")
    assert bool(got) is fired
    assert today.low_rent({"price": price}, "buy") == ""


def test_low_rent_warns_on_add_place_page_and_today(store, client):
    s = _rent(store, budget=2000)
    srv = server(store)
    out = text(call(srv, "add_place", title="Cheap", address="5 A St", price=1, listing_text="x"))
    assert "Warning: " + LOW + "." in out
    pid = store.list_places(s["id"])[0]["id"]
    assert LOW[0].upper() + LOW[1:] in client.get(f"/places/{pid}").text
    data = today.build(store, store.get_search(s["id"]))
    assert data["fits"] == [] and "far below normal for a rental" in data["cost_check"][0]["text"]
    assert "far below normal for a rental" in text(call(srv, "todays_list"))
    ok = text(call(srv, "add_place", title="Fine", address="6 A St", price=1400, utilities_estimate=50))
    assert "far below normal" not in ok


def test_low_rent_warns_on_update_and_add_places(store):
    store.add_search("R", "rent")
    srv = server(store)
    out = text(call(srv, "add_places", places=[{"title": "Cheap", "address": "5 A St", "price": 50}]))
    assert "far below normal for a rental" in out
    pid = store.list_places(store.current_search()["id"])[0]["id"]
    assert "far below normal for a rental" not in text(call(srv, "update_place", place_id=pid, price=1200))
    assert "far below normal for a rental" in text(call(srv, "update_place", place_id=pid, price=80))


# ---------------------------------------------------------------- 7 photo links
def _photos(store, title):
    return next(p["photo_urls"] for p in store.list_places(store.current_search()["id"]) if p["title"] == title)


def test_photo_link_with_a_space_is_encoded_not_refused(store):
    store.add_search("R", "rent")
    out = text(call(server(store), "add_place", title="P", address="1 A St", photo_urls=["https://cdn.example/my photo.jpg"]))
    assert out.startswith("Added") and _photos(store, "P") == ["https://cdn.example/my%20photo.jpg"]


@pytest.mark.parametrize("bad,why", [("https://u:pw@cdn.example/x.jpg", "user name or password"), ("javascript:alert(1)", "isn't a web address"),
                                     ("https://192.168.0.5/a.jpg", "")])
def test_a_bad_photo_is_dropped_alone_and_the_add_is_saved(store, bad, why):
    store.add_search("R", "rent")
    out = text(call(server(store), "add_place", title="P", address="1 A St", price=1000, photo_urls=["https://cdn.example/a b.jpg", bad]))
    assert out.startswith("Added") and "I did not save the photo link" in out and "pw" not in out
    assert why in out
    assert _photos(store, "P") == ["https://cdn.example/a%20b.jpg"]


def test_update_place_with_only_bad_photos_keeps_the_saved_ones(store):
    s = store.add_search("R", "rent")
    p, _ = store.add_place(title="P", address="1 A St", photo_urls=["https://cdn.example/keep.jpg"])
    out = text(call(server(store), "update_place", place_id=p["id"], photo_urls=["javascript:alert(1)"]))
    assert "I did not save the photo link" in out
    assert store.get_place(p["id"])["photo_urls"] == ["https://cdn.example/keep.jpg"]


def test_add_places_drops_only_the_bad_photo(store):
    store.add_search("R", "rent")
    out = text(call(server(store), "add_places", places=[{"title": "A", "address": "1 A St", "photo_urls": ["data:text/html,x"]},
                                                         {"title": "B", "address": "2 A St", "photo_urls": ["https://cdn.example/b c.jpg"]}]))
    assert out.startswith("Added 2") and "Place 1" in out
    assert _photos(store, "A") == [] and _photos(store, "B") == ["https://cdn.example/b%20c.jpg"]


# ---------------------------------------------------------------- 8 stale notes after update_place
L21 = ("Campustown Collective | Efficiency/1 Bed | Starting at $1,250\nFloor plans: A1 1BR/1BA 640 sf $1,395; A2 1BR/1BA 702 sf $1,445\n"
       "611 E Green St, Champaign, IL 61820. New in 2025.\nW/D in every unit. Stainless dishwasher. Garage parking: $150/month. Bike storage included.\n"
       "Utilities: Flat utility package $85/mo (water, sewer, trash, internet). Electric separate, around $40.\n"
       "Application fee $50 (non-refundable). Admin fee $100. Deposit: $300 or Surety Bond ($35/mo).\nNo pets.")


def test_update_place_drops_the_starting_at_note_and_the_missing_amount(store):
    s = store.add_search("U", "rent")
    srv = server(store)
    call(srv, "add_place", title="Campustown", listing_text=L21)
    pid = store.list_places(s["id"])[0]["id"]
    assert '"starting at" $1,250' in store.get_place(pid)["reader_notes"]
    out = text(call(srv, "update_place", place_id=pid, price=1395))
    notes = store.get_place(pid)["reader_notes"]
    assert "starting at" not in notes and "$1,250" not in notes and "$35" in notes  # the other stated amount stays
    assert "$1,250" not in out and "missing: the $35 deposit in the listing notes" in out


def test_a_later_update_does_not_bring_the_old_note_back(store):
    s = store.add_search("U", "rent")
    srv = server(store)
    call(srv, "add_place", title="Campustown", listing_text=L21)
    pid = store.list_places(s["id"])[0]["id"]
    call(srv, "update_place", place_id=pid, price=1395)
    call(srv, "update_place", place_id=pid, beds=1)
    assert "starting at" not in store.get_place(pid)["reader_notes"]


def test_update_place_keeps_notes_when_price_is_the_starting_price(store):
    s = store.add_search("U", "rent")
    srv = server(store)
    call(srv, "add_place", title="Campustown", listing_text=L21)
    pid = store.list_places(s["id"])[0]["id"]
    call(srv, "update_place", place_id=pid, beds=1)
    assert '"starting at" $1,250' in store.get_place(pid)["reader_notes"]


# ---------------------------------------------------------------- 9 Compare listing notes
NOTES = ("Application fee is charged per adult, $50 each.\nA $75 admin fee is charged at move-in.\nPet rent is $25 a month, not counted.\n"
         "Free rent: one month off a 13 month lease.\nPlease tour in person.")


def test_compare_listing_notes_show_three_then_more():
    p = {"reader_notes": NOTES}
    got = compare.listing_notes_text(p)
    shown = [x for x in ("Application fee is charged per adult", "A $75 admin fee", "Pet rent is $25", "Free rent", "Please tour") if x in got]
    assert len(shown) == 3 and got.endswith(" and 2 more on the place page.")


def test_compare_listing_notes_two_notes_show_both():
    got = compare.listing_notes_text({"reader_notes": "A $75 admin fee is charged at move-in.\nPlease tour in person."})
    assert "$75 admin fee" in got and "Please tour" in got and "more" not in got


# ---------------------------------------------------------------- 10 special assessment wording
def _assess(store, listing):
    s = store.add_search("B", "buy")
    store.add_place(title="H", address="1 A St", price=250000, beds=2, listing_text=listing)
    p = _rows(store, s)[0]
    return compare._assessment_cell(p)


def test_hoa_assessment_is_not_a_special_assessment(store):
    cell = _assess(store, "Condo. Monthly HOA assessment: $310. Built 1999.")
    assert "Mentioned in the listing" not in str(cell.get("text")) and not cell.get("incomplete")


@pytest.mark.parametrize("words", ["There is a special assessment coming.", "Assessment: special, details to come.", "Special building assessment pending."])
def test_special_assessment_word_still_says_so(store, words):
    cell = _assess(store, "Condo. " + words)
    assert cell["text"] == "Mentioned in the listing, amount not entered" and cell["incomplete"]


# ---------------------------------------------------------------- 9b restored notes are cleaned like new ones
def test_restored_notes_lose_invisible_characters(store, tmp_path):
    s = store.add_search("S", "rent")
    a, _ = store.add_place(search_id=s["id"], title="A", address="1 A St", reader_notes="Quote: ig‌nore‍ this")
    path = tmp_path / "b.db"
    store.backup_to(path) if hasattr(store, "backup_to") else None
    if not path.exists():
        conn = sqlite3.connect(path)
        store._conn.backup(conn)
        conn.close()
    conn = sqlite3.connect(path)
    conn.execute("UPDATE places SET reader_notes = ? WHERE id = ?", ("Quote: ig‌nore‍ this", a["id"]))
    conn.commit()
    conn.close()
    backups.restore_from_upload(store, path.read_bytes())
    assert store.get_place(a["id"])["reader_notes"] == "Quote: ignore this"
