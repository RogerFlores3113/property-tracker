"""Cycle 31 G5 item 1: Today's near-miss footer gives the real percent (or none), never a wrong "under 3 percent"."""
import pytest

from prophelper import enrich, today


def _setup(store, budget, places, dealbreaker=True):
    s = store.add_search("C", "rent")
    store.add_criterion(s["id"], "price", weight=50, dealbreaker=dealbreaker, target={"max": budget})
    for i, kw in enumerate(places):
        store.add_place(title=f"Place {i}", address=f"{i + 1} A St", beds=1, **kw)
    return s


def _near(store, s):
    rows = enrich.enrich_places(store, store.get_search(s["id"]))
    return today.near_misses(rows)


def test_guess_near_miss_over_three_percent_gets_real_percent(store):
    s = _setup(store, 2400, [{"price": 2350, "utilities_estimate": 170}])  # $120 over (5 percent), only because of the guess
    near = _near(store, s)
    assert near, "setup must give a near miss"
    pct = today.price_over_pct(near[0]["place"])
    assert pct and pct > 0.03
    foot = today.near_miss_footer(near)
    assert "under 3 percent" not in foot
    assert f"about {pct * 100:.0f} percent over your budget" in foot


def test_small_price_only_near_miss_keeps_under_three_percent(store):
    s = _setup(store, 1600, [{"price": 1620, "utilities_estimate": 0}])
    near = _near(store, s)
    assert today.near_miss_footer(near) == "These miss your budget by under 3 percent and nothing else. They are not in Best fits."


@pytest.mark.parametrize("budget,rent,util", [(2400, 2300, 204), (2000, 1900, 140), (3000, 2800, 260)])
def test_other_wordings_never_say_under_three_when_bigger(store, budget, rent, util):
    s = _setup(store, budget, [{"price": rent, "utilities_estimate": util}])
    near = _near(store, s)
    if not near:
        pytest.skip("not a near miss in this setup")
    foot = today.near_miss_footer(near)
    pct = today.price_over_pct(near[0]["place"])
    assert ("under 3 percent" in foot) == (pct < 0.03)


def test_mixed_list_uses_the_biggest(store):
    s = _setup(store, 2400, [{"price": 2300, "utilities_estimate": 227}, {"price": 2420, "utilities_estimate": 0}], dealbreaker=False)
    near = _near(store, s)
    foot = today.near_miss_footer(near)
    big = max(today.price_over_pct(n["place"]) for n in near)
    assert f"about {big * 100:.0f} percent" in foot and "under 3 percent" not in foot


def test_no_near_miss_no_footer():
    assert today.near_miss_footer([]) == ""


def test_page_shows_footer(store, client):
    s = _setup(store, 2400, [{"price": 2300, "utilities_estimate": 227}], dealbreaker=False)  # 5.4 percent over, price is not a must-have
    html = client.get("/today").text
    assert "under 3 percent and nothing else" not in html
    assert "over your budget. They are not in Best fits." in html
