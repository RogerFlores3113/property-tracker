"""Cycle 1, F6: links are kept as typed; only duplicate checks use the normalized form."""
import pytest

from conftest import local_client


def test_url_kept_as_typed_and_csv_export_shows_it(store):
    s = store.add_search("Rent", "rent")
    p, _ = store.add_place(search_id=s["id"], title="A", url="https://www.zillow.com/homedetails/1-Main-St/123_zpid/?utm_source=x")
    assert store.get_place(p["id"])["url"] == "https://www.zillow.com/homedetails/1-Main-St/123_zpid/?utm_source=x"
    q, _ = store.add_place(search_id=s["id"], title="B", url="www.zillow.com/homedetails/2-Main-St/9_zpid")
    assert store.get_place(q["id"])["url"] == "https://www.zillow.com/homedetails/2-Main-St/9_zpid"
    text = local_client(store).get("/places.csv").text
    assert "www.zillow.com" in text


@pytest.mark.parametrize("second", [
    "http://zillow.com/homedetails/1-Main-St/123_zpid",
    "https://WWW.Zillow.com/homedetails/1-Main-St/123_zpid/#photos",
    "zillow.com/homedetails/1-Main-St/123_zpid/?utm_campaign=y",
])
def test_duplicates_are_still_caught_whatever_was_typed(store, second):
    s = store.add_search("Rent", "rent")
    first, _ = store.add_place(search_id=s["id"], title="A", url="https://www.zillow.com/homedetails/1-Main-St/123_zpid")
    again, created = store.add_place(search_id=s["id"], title="A again", url=second)
    assert not created and again["id"] == first["id"]
    other, _ = store.add_place(search_id=s["id"], title="C", url="https://www.zillow.com/homedetails/5-Elm/5_zpid")
    with pytest.raises(ValueError):
        store.update_place(other["id"], url=second)
    assert store.find_duplicate(None, url=second)["id"] == first["id"]
