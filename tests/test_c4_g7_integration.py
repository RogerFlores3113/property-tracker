"""Cycle 4 integration: the pieces the six groups built have to work together."""
import csv
import io

from mcp_util import call, server, structured, text
from prophelper import csv_io, enrich


def test_mcp_search_adults_and_per_adult_wording(store):
    s = server(store)
    out = call(s, "create_search", name="Pair", mode="rent", budget_max=2000, people=4, adults=2)
    sid = structured(out)["search_id"]
    assert "2 adults" in text(out)
    assert store.get_search(sid)["adults"] == 2
    call(s, "add_place", title="Elm", price=1800, application_fee=50, application_fee_per_adult=True, search_id=sid)
    p = store.list_places(sid)[0]
    assert p["application_fee_per_adult"] == 1
    got = text(call(s, "get_place", place_id=p["id"]))
    assert "each for 2 adults" in got
    call(s, "update_search", search_id=sid, adults=3)
    assert store.get_search(sid)["adults"] == 3
    assert "each for 3 adults" in text(call(s, "get_place", place_id=p["id"]))


def test_mcp_buy_seller_credit(store):
    s = server(store)
    sid = structured(call(s, "create_search", name="Buy", mode="buy"))["search_id"]
    call(s, "add_place", title="House", price=300000, seller_credit=5000, search_id=sid)
    assert store.list_places(sid)[0]["seller_credit"] == 5000
    pid = store.list_places(sid)[0]["id"]
    call(s, "update_place", place_id=pid, seller_credit=7000)
    assert store.get_place(pid)["seller_credit"] == 7000


def test_csv_round_trip_new_fields_and_per_adult_cost(store):
    s = store.add_search("Pair", "rent", budget_max=2000, people=4, adults=2)
    store.add_place(search_id=s["id"], title="Elm", price=1800, application_fee=50, application_fee_per_adult=1, seller_credit=250)
    rows = enrich.enrich_places(store, store.get_search(s["id"]))
    data = csv_io.export_csv(rows, [], 4)
    table = list(csv.reader(io.StringIO(data)))
    head, row = table[0], table[1]
    assert row[head.index("Seller credit")] == "250.0" or row[head.index("Seller credit")] == "250"
    assert row[head.index("Application fee charged per adult")] == "yes"
    total = float(row[head.index("True monthly cost")])
    assert float(row[head.index("Cost per person per month")]) == round(total / 2, 2)
    assert csv_io.SYNONYMS["seller credit"] == "seller_credit"
    assert csv_io.SYNONYMS["application fee charged per adult"] == "application_fee_per_adult"


def test_budget_edit_updates_the_automatic_rule_only(client, store):
    s = store.add_search("A", "rent", budget_max=1500)
    from prophelper import scoring
    for c in scoring.starter_criteria("rent", 1500, None):
        store.add_criterion(s["id"], c["kind"], label=c["label"], weight=c["weight"], dealbreaker=True, target=c["target"])
    own = store.add_criterion(s["id"], "beds", label="Beds", weight=10, dealbreaker=False, target={"min": 2})
    client.post(f"/search/{s['id']}", data={"budget_max": "1800", "name": "A"})
    crit = {c["kind"]: c for c in store.list_criteria(s["id"])}
    assert crit["price"]["target"]["max"] == 1800 and "1,800" in crit["price"]["label"]
    assert crit["beds"]["target"] == {"min": 2}


def test_mcp_budget_edit_leaves_a_users_own_rule(store):
    s = server(store)
    sid = structured(call(s, "create_search", name="B", mode="rent", budget_max=1500, bedrooms=1))["search_id"]
    own = store.add_search("C", "rent", budget_max=1500)
    store.add_criterion(own["id"], "price", label="Mine", weight=50, dealbreaker=True, target={"max": 1400})
    call(s, "update_search", search_id=sid, budget_max=1700)
    crit = {c["kind"]: c for c in store.list_criteria(sid)}
    assert crit["price"]["target"]["max"] == 1700
    assert crit["beds"]["target"]["min"] == 1
    call(s, "update_search", search_id=own["id"], budget_max=1900)
    assert store.list_criteria(own["id"])[0]["target"]["max"] == 1400


def test_strict_setting_name_matches_the_app(store, client):
    from prophelper.mcp_server import STRICT_RULE
    assert "Stricter rules when Claude reads websites" in STRICT_RULE
    assert "Stricter rules when Claude reads websites" in client.get("/privacy").text


def test_negative_money_puts_the_minus_before_the_dollar_sign():
    from prophelper.helpers import money
    assert money(-8000) == "-$8,000" and money(-12.5, cents=True) == "-$12.50" and money(0) == "$0" and money(-0.2) == "$0"
