"""Cycle 4, G6: places.csv fills the computed columns from the place page's own checks, matches its commute, counts
places on import, round-trips the new fields and the calendar notes overlapping tours."""
import csv
import io
from datetime import datetime, timedelta, timezone

from conftest import local_client
from prophelper import csv_io, enrich, today


def _table(text):
    t = list(csv.reader(io.StringIO(text)))
    return t[0], [dict(zip(t[0], r)) for r in t[1:]]


def test_flags_fit_and_ratings_are_filled(store):
    s = store.add_search("Rent", "rent")
    store.update_search(s["id"], people=2, people_names=["Ana", "Ben"])
    store.add_criterion(s["id"], "beds", weight=10, target={"min": 1})
    scam, _ = store.add_place(search_id=s["id"], by="you", title="Too good", address="1 A St", price=300, beds=2,
                              listing_text="Wire the deposit by Western Union before you see it. I am out of the country.")
    ok, _ = store.add_place(search_id=s["id"], by="you", title="Fine", address="2 B St", price=1000, beds=1, rating=4)
    third, _ = store.add_place(search_id=s["id"], by="you", title="Rated", address="3 C St", price=1100, beds=1)
    store.set_opinion(third["id"], "Ana", 5)
    store.set_opinion(third["id"], "Ben", 3)
    full = {p["title"]: p for p in enrich.enrich_places(store, store.get_search(s["id"]))}
    assert full["Too good"]["flags"], "setup: the place page lists a flag for this one"
    head, rows = _table(local_client(store).get(f"/places.csv?search_id={s['id']}").text)
    by = {r["Title"]: r for r in rows}
    assert by["Too good"]["Red flags"] and by["Too good"]["Red flags"].split("; ")[0] == full["Too good"]["flags"][0]
    assert by["Fine"]["Red flags"] == ""
    assert by["Fine"]["Fit score"] == str(full["Fine"]["score_total"]) != ""
    assert "Ana's rating" in head and "Ben's rating" in head and "Rating" in head
    assert by["Rated"]["Ana's rating"] == "5" and by["Rated"]["Ben's rating"] == "3" and by["Rated"]["Rating"] == "4"
    assert by["Fine"]["Rating"] == "4" and by["Fine"]["Ana's rating"] == ""


def test_formula_guard_still_holds_on_new_columns(store):
    s = store.add_search("Rent", "rent")
    store.update_search(s["id"], people=2, people_names=["=Ana", "Ben"])
    store.add_place(search_id=s["id"], by="you", title="=1+1", address="1 A St", red_flags="=HYPERLINK(1)")
    head, rows = _table(local_client(store).get(f"/places.csv?search_id={s['id']}").text)
    assert "'=Ana's rating" in head
    assert rows[0]["Title"] == "'=1+1" and rows[0]["Red flags"].startswith("'=")


def test_commute_matches_the_place_page_and_names_the_way(store):
    s = store.add_search("Rent", "rent")
    a = store.add_anchor("Campus", "1 Main St", 40.1, -88.2)
    store.add_criterion(s["id"], "commute", weight=10, target={"anchor_id": a["id"], "mode": "transit", "max_minutes": 30})
    p, _ = store.add_place(search_id=s["id"], by="you", title="Far", address="9 Z St", lat=40.11, lng=-88.21)
    store.set_commute(p["id"], a["id"], "transit", 54)
    store.set_commute(p["id"], a["id"], "drive", 5)
    page = local_client(store).get(f"/places/{p['id']}").text
    assert "54" in page
    _, rows = _table(local_client(store).get(f"/places.csv?search_id={s['id']}").text)
    assert rows[0]["Commute to Campus (minutes)"] == "54"
    assert rows[0]["Commute to Campus (way)"] == "transit (your time)"


def test_import_summary_counts_places_not_lines(store):
    s = store.add_search("Rent", "rent")
    data = ("Title,Address,Price\nA,1 Main St,1000\nB,2 Main St,1100\nA again,1 Main St,1000\n,,\n,,\n").encode()
    headers, rows = csv_io.read_table(data)
    plan = csv_io.plan_import(store, s["id"], headers, rows, csv_io.match_columns(headers))
    c = csv_io.summarize(plan)
    assert (c["new"], c["repeat"], c["skip"], c["blank"], c["places"]) == (2, 1, 0, 2, 3)
    assert "row 4" in csv_io.left_out_text(plan) and "repeats row 2" in csv_io.left_out_text(plan)
    client = local_client(store)
    r = client.post("/import", files={"file": ("x.csv", data, "text/csv")}, data={"search_id": str(s["id"])})
    assert "lists 3 places" in " ".join(r.text.split()) and "2 empty rows, left out" in " ".join(r.text.split())


def test_round_trip_keeps_new_fields_and_ignores_computed_ones(store):
    s = store.add_search("Rent", "rent")
    store.add_anchor("Campus", "1 Main St", 40.1, -88.2)
    for i in range(5):
        store.add_place(search_id=s["id"], by="you", title=f"P{i}", address=f"{i} Main St", price=1000 + i, months_up_front=2 + i % 2,
                        tenant_pays="gas, electric", pets="dogs", pet_rent=35, pet_fee=300, pet_deposit=200, pet_weight_limit=40,
                        pet_count_limit=2, pet_breed_note="No pit bulls", notes="line one\nline two" if i == 1 else "",
                        listing_text="Wire money by Western Union please" if i == 0 else "")
    text = local_client(store).get(f"/places.csv?search_id={s['id']}").text
    headers, rows = csv_io.read_table(text.encode())
    other = store.add_search("Copy", "rent")
    mapping = csv_io.match_columns(headers)
    plan = csv_io.plan_import(store, other["id"], headers, rows, mapping)
    c = csv_io.summarize(plan)
    assert c["new"] == 5 and c["skip"] == 0 and c["repeat"] == 0 and c["places"] == 5
    assert all(not p["warnings"] for p in plan)
    csv_io.apply_plan(store, other["id"], plan)
    got = {p["title"]: p for p in store.list_places(other["id"])}
    for k in ("months_up_front", "tenant_pays", "pets", "pet_rent", "pet_fee", "pet_deposit", "pet_weight_limit", "pet_count_limit", "pet_breed_note"):
        assert got["P0"][k] is not None, k
    assert got["P1"]["months_up_front"] == 3 and got["P0"]["months_up_front"] == 2
    assert got["P0"]["tenant_pays"] == "electric, gas" and got["P0"]["pet_breed_note"] == "No pit bulls" and got["P0"]["pet_weight_limit"] == 40
    assert got["P0"]["red_flags"] == "" and got["P0"]["fit_score"] is None  # computed columns are never read back
    ignored = [h for h in headers if csv_io.is_computed_header(h)]
    assert {"Fit score", "Red flags", "True monthly cost", "Commute to Campus (minutes)", "Commute to Campus (way)"} <= set(ignored)
    page = " ".join(local_client(store).post("/import", files={"file": ("x.csv", text.encode(), "text/csv")}, data={"search_id": str(other["id"])}).text.split())
    assert "5 places" in page and "Worked out by the app" in page


def test_overlap_note_uses_tour_length():
    base = datetime(2030, 5, 6, 17, 0, tzinfo=timezone.utc)
    t = [{"id": 1, "starts_at": base.isoformat(), "duration_minutes": 45},
         {"id": 2, "starts_at": (base + timedelta(minutes=30)).isoformat(), "duration_minutes": 30}]
    note = today.close_tour_notes(t)[2]
    assert "overlap" in note and "45 minutes" in note
    t[0]["duration_minutes"] = 20
    assert "overlap" not in today.close_tour_notes(t)[2]
    del t[0]["duration_minutes"]  # no length: the usual 30, which ends exactly when the next starts
    assert "overlap" not in today.close_tour_notes(t)[2]


def test_calendar_page_shows_overlap(store):
    s = store.add_search("Rent", "rent")
    store.set_current_search(s["id"])
    a, _ = store.add_place(search_id=s["id"], title="A", address="1 A St")
    b, _ = store.add_place(search_id=s["id"], title="B", address="2 B St")
    day = (datetime.now(timezone.utc) + timedelta(days=3)).replace(hour=15, minute=0, second=0, microsecond=0)
    store.add_tour(a["id"], day.isoformat(), duration_minutes=45)
    store.add_tour(b["id"], (day + timedelta(minutes=30)).isoformat())
    html = local_client(store).get(f"/calendar?month={day.astimezone().strftime('%Y-%m')}").text
    assert "overlap" in html
