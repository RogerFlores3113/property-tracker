"""Cycle 1, fixer F2: CSV import preview and export."""
import csv
import io

from conftest import local_client
from prophelper import csv_io

SHEET = (
    "Name,Street Address,Link,Rent,Pet Rent,Pet Fee\n"
    "Maple Court Apartments,410 Maple Row Lane,,\"$1,450\",35,300\n"
    ",,https://example.test/call-us,Call for pricing,,\n"
    ",,,Ask us,,\n"
    "Oak House,12 Oak Street,,call us,,\n"
)


def _setup(store):
    s = store.add_search("UIUC", "rent")
    store.set_current_search(s["id"])
    return s


def test_pet_columns_are_matched():
    headers, _ = csv_io.read_table(SHEET.encode())
    mapped = {headers[i]: f for i, f in csv_io.match_columns(headers).items()}
    assert mapped["Pet Rent"] == "pet_rent" and mapped["Pet Fee"] == "pet_fee"
    assert "pet_rent" in csv_io.FIELD_LABELS and "pet_fee" in csv_io.FIELD_LABELS
    for head, field in (("Pet rent per month", "pet_rent"), ("Monthly pet rent", "pet_rent"), ("One time pet fee", "pet_fee"), ("Pet fee", "pet_fee"), ("Pet deposit", "pet_deposit")):
        assert csv_io.match_columns([head]) == {0: field}, head


def test_row_with_no_name_and_a_junk_price_is_skipped_with_a_reason(store):
    s = _setup(store)
    headers, rows = csv_io.read_table(SHEET.encode())
    plan = csv_io.plan_import(store, s["id"], headers, rows, csv_io.match_columns(headers))
    assert [p["status"] for p in plan] == ["new", "skip", "skip", "new"]
    assert "isn't a number" in plan[1]["reason"] and "Call for pricing" in plan[1]["reason"]
    assert plan[3]["warnings"]  # a named place is still kept, with the price left empty
    assert csv_io.summarize(plan)["skip"] == 2
    assert plan[0]["values"]["pet_rent"] == 35 and plan[0]["values"]["pet_fee"] == 300


def test_export_has_cost_score_and_commute_columns(store):
    s = _setup(store)
    store.update_search(s["id"], people=2) if "people" in store.get_search(s["id"]) else None
    store.add_criterion(s["id"], "beds", weight=10, target={"min": 1})
    anchor = store.add_anchor("Campus", "1 Main St", 40.1, -88.2)
    place, _ = store.add_place(by="you", search_id=s["id"], title="Maple Court Apartments", address="410 Maple Row Lane", price=1400,
                               url="https://www.zillow.com/homedetails/x", lat=40.11, lng=-88.21)
    store.set_commute(place["id"], anchor["id"], "walk", 12)
    store.set_commute(place["id"], anchor["id"], "drive", 5)
    c = local_client(store)
    r = c.get(f"/places.csv?search_id={s['id']}")
    table = list(csv.reader(io.StringIO(r.text)))
    head, row = table[0], dict(zip(table[0], table[1]))
    assert {"True monthly cost", "Cost per person per month", "Score out of 100"} <= set(head)
    assert row["Commute to Campus (minutes, fastest way)"] == "5"
    assert float(row["True monthly cost"]) >= 1400
    people = store.get_search(s["id"]).get("people") or 1
    assert abs(float(row["Cost per person per month"]) - float(row["True monthly cost"]) / people) < 0.01
    assert row["Score out of 100"] != ""


def test_export_still_reads_back_on_import(store):
    s = _setup(store)
    store.add_place(by="you", search_id=s["id"], title="Elm Flats", address="9 Elm St", price=1000)
    text = csv_io.export_csv(__import__("prophelper.enrich", fromlist=["x"]).enrich_places(store, s))
    headers, rows = csv_io.read_table(text.encode())
    mapped = set(csv_io.match_columns(headers).values())
    assert "True monthly cost" not in headers[0:0] and "price" in mapped
    assert not any(h.startswith(("True monthly", "Cost per person", "Score out of")) and csv_io.SYNONYMS.get(csv_io._norm_header(h)) for h in headers)
