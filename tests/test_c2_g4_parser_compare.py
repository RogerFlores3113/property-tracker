"""G4: listing reader (first and last, building after "at", tenant pays, parking words) and compare wording."""
import pytest

from conftest import local_client
from prophelper import compare, money, parsers
from prophelper.store import clean_enum


@pytest.mark.parametrize("phrase", ["First and last month due at move-in", "first & last month required",
                                    "1st and last month rent due", "First, last month's rent due"])
def test_first_and_last_counted_in_cash_at_move_in(phrase):
    text = f"2BR apartment\n$1,450/mo\nDeposit $500\n{phrase}"
    found = parsers.parse_listing(text)
    assert "First and last month" in found["found_in_listing"]
    cash = money.cash_at_move_in({"price": 1450, "deposit": 500, "listing_text": text})
    labels = [p["label"] for p in cash["parts"]]
    assert "Last month's rent" in labels
    assert cash["total"] == 1450 * 2 + 500


def test_building_name_after_at_becomes_title():
    assert parsers.parse_listing("Beautiful 2BR/2BA at Olentangy Commons\n$1450/mo")["title"] == "Olentangy Commons"
    # a street after "at" is not a building
    assert parsers.parse_listing("Cozy unit at Green Street $900")["title"] != "Green Street"


def test_tenant_pays_gas_and_electric_is_recorded_and_nothing_included():
    found = parsers.parse_listing("2BR apartment. $1200/mo. Tenant pays gas and electric.")
    assert "utilities_included" not in found
    assert "Tenant pays gas, electric" in found["found_in_listing"]
    cost = money.rent_cost({"price": 1200, "utilities_estimate": 90})
    line = next(l for l in cost["lines"] if l["key"] == "utilities")
    assert "guess" in line["label"].lower()


@pytest.mark.parametrize("word,want", [("reserved", "lot"), ("assigned", "lot"), ("Assigned parking", "lot"),
                                       ("carport", "covered"), ("driveway", "lot")])
def test_parking_words_accepted(word, want):
    assert clean_enum("parking", word) == want


def test_still_unknown_lists_guesses(store):
    search = store.add_search("S")
    places = []
    for t in ("A", "B"):
        p, _ = store.add_place(search_id=search["id"], title=t, address=f"1 {t} St", price=1000, utilities_estimate=80)
        places.append(p)
    html = local_client(store).get(f"/compare?ids={places[0]['id']},{places[1]['id']}").text
    assert "Utilities (a guess)" in html
    assert "nothing, everything is filled in" not in html.split("Still unknown")[1].split("</tr>")[0]


def test_compare_commutes_one_row_per_important_place(store):
    search = store.add_search("S")
    for n, (lat, lng) in enumerate([(40.1, -88.2), (40.11, -88.21), (40.12, -88.22)]):
        store.add_anchor(f"Place{n}", lat=lat, lng=lng)
    ids = []
    for t in ("A", "B"):
        p, _ = store.add_place(search_id=search["id"], title=t, address=f"1 {t} St", price=1000, lat=40.105, lng=-88.205)
        ids.append(str(p["id"]))
    html = local_client(store).get("/compare?ids=" + ",".join(ids)).text
    section = html.split("Commutes")[1].split("</tbody>")[0]
    assert section.count('<tr class=') == 3
