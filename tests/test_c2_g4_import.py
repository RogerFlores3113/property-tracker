"""G4: spreadsheet import preview: skipped rows listed, honest button, plain number messages."""
from conftest import local_client

CSV = (b"Title,Address,Price,Beds,Notes\n"
       b"Elm,1 Elm St,abc,two,hi\n"
       b",,1200,2,price only\n"
       b",,,,only a note\n"
       b"Oak,2 Oak St,1300,2,\n")


def _preview(store):
    store.add_search("S")
    c = local_client(store)
    return c.post("/import", files={"file": ("p.csv", CSV, "text/csv")}).text


def test_rows_without_title_or_address_are_skipped_with_reason(store):
    html = _preview(store)
    assert "Row 3" in html and "Row 4" in html
    assert "no title, address or link" in html


def test_button_counts_real_additions(store):
    html = _preview(store)
    assert "Add 2 new places" in html
    assert "Import 4 rows" not in html


def test_number_messages_name_their_column(store):
    html = _preview(store)
    assert "Price needs to be a number, like 1450" in html
    assert "Beds needs to be a number, like 2" in html
    assert "like 1450. (left empty)" not in html
