"""Cycle 11 joins: the notes refresh on add and edit reads a buy search's listing as a home for sale."""
from mcp_util import call, server, text


def test_buy_notes_survive_add_and_edit_without_rental_wording(store):
    s = store.add_search("Buy", "buy")
    text(call(server(store), "add_place", title="GV", search_id=s["id"],
              listing_text="3 bed home for sale $425,000. Taxes $4,600/yr. Move-in fee $1,200. Required deeded parking $120/mo."))
    notes = store.get_place(1)["reader_notes"]
    assert "$120/month" in notes and "$1,200 move-in fee" in notes
    store.update_place(1, beds=4)
    after = store.get_place(1)["reader_notes"]
    assert "$120/month" in after and "rental" not in after.lower() and "free-rent" not in after.lower()


def test_pipe_pet_line_mid_paragraph_reads_pet_rent():
    from prophelper.parsers import parse_listing
    got = parse_listing("Cozy 1BR. $1,150/mo. Pets: 1 pet, maximum 55 lbs., $300 deposit | $25 monthly")
    assert got["pet_deposit"] == 300 and got["pet_rent"] == 25 and "deposit" not in got
    assert "$25 monthly" not in got.get("found_in_listing", "")
