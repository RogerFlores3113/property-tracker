"""Cycle 35 G5: when no place is a best fit but some places are only held back by an unsettled cost, Today says "No place fits all your must-haves yet; N places
are close and need a cost check" (page and Claude's list), not a bare "No place fits yet"."""
import pytest
from conftest import local_client
from mcp_util import call, server, text

from prophelper import today


def _buy(store, complete, partial):
    s = store.add_search("C", "buy", budget_max=400000)
    store.add_criterion(s["id"], "price", weight=50, dealbreaker=False, target={"max": 400000})
    ids = []
    for i in range(complete + partial):
        kw = dict(title=f"Condo {i}", address=f"{i + 1} Oak St", price=300000 + i * 1000, beds=2, property_tax=3600, hoa=0, search_id=s["id"])
        if i < complete:
            kw["insurance"] = 1200
        p, _ = store.add_place(**kw)
        ids.append(p["id"])
    store.set_current_search(s["id"])
    return s, ids


def _section(html):
    return html.split('id="fits-h"')[1].split("</section>")[0]


def _plural(n):
    return "1 place is close and needs a cost check" if n == 1 else f"{n} places are close and need a cost check"


@pytest.mark.parametrize("n", [1, 2, 3, 4, 6])
def test_page_says_how_many_places_are_close(store, n):
    _buy(store, 0, n)
    html = local_client(store).get("/today").text
    sec = _section(html)
    assert f"No place fits all your must-haves yet; {_plural(n)}." in sec, sec
    assert "No place fits yet" not in html
    assert '<span class="count">%d</span>' % n in html.split('id="cost-check-h"')[1]  # the same number as the Needs a cost check heading


@pytest.mark.parametrize("n", [1, 2, 3, 5])
def test_claudes_list_says_the_same(store, n):
    _buy(store, 0, n)
    out = text(call(server(store), "todays_list"))
    assert f"No place fits all your must-haves yet; {_plural(n)}." in out, out
    assert out.count("Needs a cost check:") == n
    assert "Best fits right now: none yet." in out  # the old line stays, the new one explains it


def test_the_page_keeps_the_note_about_the_board(store):
    _buy(store, 0, 2)
    sec = _section(local_client(store).get("/today").text)
    assert "Places that miss a must have or look risky stay on the" in sec


def test_the_data_carries_the_line(store):
    s, _ = _buy(store, 0, 3)
    d = today.build(store, store.get_search(s["id"]))
    assert today.close_text(d) == "No place fits all your must-haves yet; 3 places are close and need a cost check."


# ---- negatives: the old line stays when nothing is close, and nothing changes when a place does fit
def test_no_close_place_keeps_the_plain_line(store):
    s = store.add_search("C", "buy", budget_max=100000)
    store.add_criterion(s["id"], "price", weight=50, dealbreaker=True, target={"max": 100000})
    store.add_place(title="Too dear", address="1 Oak St", price=400000, beds=2, property_tax=3600, hoa=0, insurance=1200, search_id=s["id"])
    store.set_current_search(s["id"])
    html = local_client(store).get("/today").text
    assert "No place fits yet." in html and "No place fits all your must-haves yet" not in html
    out = text(call(server(store), "todays_list"))
    assert "No place fits all your must-haves yet" not in out


def test_a_best_fit_means_no_such_line(store):
    _buy(store, 2, 2)
    html = local_client(store).get("/today").text
    assert "No place fits" not in html
    out = text(call(server(store), "todays_list"))
    assert "No place fits all your must-haves yet" not in out
    d = today.build(store, store.get_current_search() if hasattr(store, "get_current_search") else store.current_search())
    assert today.close_text(d) == ""
