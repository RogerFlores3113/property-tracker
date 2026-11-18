"""Cycle 37 G5 (rule oo): a roommate share and a per-semester price never appear in Missing, Unknowns, Compare's Still unknown or the
"cheaper, but" line, and the parking note does not call a per-semester price "a monthly fee"."""
import pytest
from c37_g5_util import F, add, line, search, view
from mcp_util import call, server, text

BASE = "South Loop 3 bed 2 bath condo, 1400 S Michigan Ave 1204, Chicago IL 60605\n$3,290 a month. Deposit $1,000.\nIncluded: water, sewer. Tenant pays: electric, gas, internet.\n"
SHARES = ["Roommate share $1,097 each.", "Roommate share: $1,097 each", "Each person's share would be about $1,097.", "Split three ways that is a roommate share of $1,097 each.",
          "(roommate share $1,097 per person)", "Roommate share $1,097 per room."]
TERMS = ["Garage parking $225/mo or per-semester pass $600.", "Garage parking $225/mo, per semester pass $600.", "Garage parking $225 a month; $600 per semester option.",
         "Garage parking $225/mo | semester pass $600 |", "- Garage parking: $225/mo\n- Per-semester pass: $600"]


def _cell_clean(out):
    for head in ("Monthly cost so far", "Unknowns to fill"):
        l = line(out, head)
        assert "$1,097" not in l and "$600" not in l and "listing notes" not in l, l


@pytest.mark.parametrize("share", SHARES)
@pytest.mark.parametrize("term", TERMS)
def test_share_and_semester_stay_out_of_missing(store, share, term):
    s = search(store)
    pid, reply = add(store, s, "A", BASE + share + "\n" + term)
    out = view(store, pid)
    _cell_clean(out)
    _cell_clean(reply)
    assert "missing: electric, gas and internet" in out
    assert "Only $600 of that is a monthly fee" not in out
    p = store.get_place(pid)
    assert p["price"] == 3290 and p["parking_cost"] == 225


def test_reviewer_listing_l7_compare_and_today(store):
    s = search(store)
    pid, _ = add(store, s, "South", F("r36-roommates-l7.txt"))
    other, _ = add(store, s, "Other", "Other 9 Other St Chicago IL. 3 bed $3,500 a month. Tenant pays electric.")
    out = text(call(server(store), "compare_places", place_ids=[pid, other]))
    still = line(out, "Still unknown")
    assert "$1,097" not in still and "$600" not in still and "listing notes" not in still, still
    for l in out.splitlines():
        if l.startswith("Lowest") or "cheaper, but" in l:
            assert "$1,097" not in l and "$600" not in l
    notes = view(store, pid)
    assert "per-semester or per-term price, so it is not a monthly cost" in notes
    assert "Only $600 of that is a monthly fee" not in notes


def test_negative_monthly_parking_still_counted_and_unknown_fee_still_missing(store):
    s = search(store)
    pid, _ = add(store, s, "N", BASE + "Garage parking $225/mo.\nMystery building fee $40.")
    out = view(store, pid)
    assert store.get_place(pid)["parking_cost"] == 225
    assert "$40" in line(out, "Monthly cost so far") or "$40" in line(out, "Cost lines")


def test_negative_semester_figure_is_not_rent(store):
    s = search(store)
    pid, _ = add(store, s, "N2", BASE + "Parking $600 per semester.")
    p = store.get_place(pid)
    assert p["price"] == 3290 and not p.get("parking_cost")
