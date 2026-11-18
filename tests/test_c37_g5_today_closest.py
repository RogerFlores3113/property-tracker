"""Cycle 37 G5: Today's "Closest so far" never lists a place the listing firmly rules out for the dog (weight limit, no dogs) above or among places that
only miss on cost; a limit that can be waived stays."""
import pytest
from c37_g5_util import F, add
from conftest import local_client
from mcp_util import call, server, text

BASE = "{t} {n} Elm St Redwood City CA 94063. 3 bed 2 bath. ${r}/mo. {pets} Tenant pays electric and gas."


def _setup(store, hard_pets, hard_rent=3300):
    srv = server(store)
    call(srv, "create_search", name="Fam", mode="rent", budget_max=2400, pet_kind="dog", pet_weight=60, pet_count=1)
    s = store.list_searches()[-1]
    store.set_current_search(s["id"])
    a, _ = add(store, s, "Hard", BASE.format(t="Hard", n=1, r=hard_rent, pets=hard_pets))
    b, _ = add(store, s, "Cost2650", BASE.format(t="Cost2650", n=2, r=2650, pets="Dogs welcome up to 80 lbs."))
    c, _ = add(store, s, "Cost2500", BASE.format(t="Cost2500", n=3, r=2500, pets="Dogs ok."))
    return s, (a, b, c)


def _closest(store):
    out = text(call(server(store), "todays_list"))
    lines = out.splitlines()
    start = next((i for i, l in enumerate(lines) if l.startswith("Closest so far")), None)
    got = []
    if start is not None:
        for l in lines[start + 1:]:
            if not l.startswith("  - #"):
                break
            got.append(l)
    return out, got


HARD = ["Pets: dogs up to 40 lbs, NO exceptions.", "Dogs under 40 lb only, non-negotiable.", "Dog weight limit 35 lbs. Strictly enforced.", "No dogs.",
        "Pets: dogs not allowed.", "Dogs: 40 lb limit, will not be waived."]


@pytest.mark.parametrize("pets", HARD)
def test_hard_dog_fail_is_not_in_closest(store, pets):
    s, (a, b, c) = _setup(store, pets)
    out, got = _closest(store)
    assert any("Cost2500" in l for l in got) and any("Cost2650" in l for l in got), out
    assert not any("Hard" in l for l in got), got
    html = local_client(store).get("/today").text
    sec = html.split("Closest so far")[1].split("</section>")[0] if "Closest so far" in html else ""
    assert "Hard" not in sec


@pytest.mark.parametrize("pets", ["Dogs over 40 lbs need approval.", "Dog limit 40 lb, ask about exceptions.", "Dogs over 40 lb: case by case."])
def test_waivable_limit_is_not_a_firm_fail(store, pets):
    from prophelper import enrich, today
    s, (a, b, c) = _setup(store, pets, hard_rent=2500)
    p = enrich.enrich_places(store, s, [store.get_place(a)])[0]
    assert not today.hard_musthave_failed(p), p["score"]["fit_reasons"]


def test_cost_only_failure_stays_listed(store):
    s, (a, b, c) = _setup(store, "Dogs welcome up to 80 lbs.", hard_rent=2900)
    out, got = _closest(store)
    assert len(got) == 3 and "Hard" in got[-1], got  # ranked by score: the dearest is last, never first


def test_reviewer_family_listings(store):
    srv = server(store)
    call(srv, "create_search", name="Fam", mode="rent", budget_max=2400, pet_kind="dog", pet_weight=60, pet_count=1)
    s = store.list_searches()[-1]
    store.set_current_search(s["id"])
    ids = [add(store, s, f"L{n}", F(f"r36-family-l{n}.txt"))[0] for n in (1, 4, 5)]
    out, got = _closest(store)
    for pid in ids:
        assert f"#{pid} " not in " ".join(got), (pid, got)
