"""Cycle 33 group G3: weight limits, soft limits, answered questions, breed notes, a deposit range after a pet sentence, no pets in the search."""
import os

import pytest

from mcp_util import call, server, text as mtext
from prophelper import enrich, scoring
from prophelper.parsers import parse_listing

HERE = os.path.join(os.path.dirname(__file__), "fixtures", "panel")


def P(text, kind="dog", **kw):
    return parse_listing(text, "", pet_kind=kind, **kw)


def F(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as fh:
        return fh.read()


def notes(r):
    return r.get("found_in_listing") or ""


def fit(text, kind="dog", weight=60, count=1):
    r = P(text, kind)
    place = dict(r)
    place["listing_text"] = text
    place["reader_notes"] = notes(r)
    want = {"cat": "cats", "dog": "dogs", "both": "both"}[kind]
    crit = {"kind": "pets", "weight": 15, "dealbreaker": True, "target": {"want": want}}
    return r, scoring._score_pets(crit, place, {"pets": {"kind": kind, "weight": weight, "count": count}})


# ---- a deposit range after a pet sentence is the security deposit, never the pet deposit (roommates l8)
@pytest.mark.parametrize("t", [
    "Rent $2,400. Pet policy: no aggressive breeds. Cats and dogs welcome, 2 max. Deposit $1,200 - $3,100.",
    "Rent $2,400. Pets: cats and dogs welcome, 2 max. Deposit $1,200 to $3,100.",
    "Rent $2,400. Pets welcome, 2 max. Deposit: $1,200 - $3,100",
    "Rent $2,400.\nPet policy: cats and dogs welcome, 2 max.\nDeposit $1,200 - $3,100.\n",
    "Rent $2,400. Pets OK (max 2). Deposit $1,200 - $3,100 based on credit.",
    "Rent $2,400. Pet policy: cats and dogs welcome | Deposit: $1,200-$3,100",
    "Rent $2,400. Deposit $1,200 - $3,100. Pet policy: cats and dogs welcome.",
])
def test_deposit_range_near_pets_is_the_security_deposit(t):
    r = P(t)
    assert r["deposit"] == 1200
    assert "pet_deposit" not in r
    assert "at least" in notes(r) and "$3,100" in notes(r)
    assert "pet deposit" not in notes(r)


def test_roommates_l8_whole_listing():
    r = P(F("r32-roommates-l8.txt"))
    assert (r["price"], r["deposit"], r["pets"], r["pet_count_limit"]) == (3100, 1200, "both", 2)
    assert "pet_deposit" not in r
    assert "pet deposit" not in notes(r)


@pytest.mark.parametrize("t,field,want", [
    ("Rent $2,400. Pet policy: dogs welcome. Pet deposit $300. Deposit $1,200 - $3,100.", "pet_deposit", 300),
    ("Rent $2,400. Pet policy: dogs welcome, 2 max. Deposit $1,200 - $3,100 | Pet deposit $300", "pet_deposit", 300),
    ("Rent $2,400. Pet policy: dogs welcome, deposit $300 - $500.", "pet_deposit", 300),
    ("Rent $2,400. Dogs welcome with a $400 pet deposit.", "pet_deposit", 400),
])
def test_a_deposit_that_names_the_pet_stays_the_pet_deposit(t, field, want):
    assert P(t)[field] == want


# ---- weight: "Dogs larger than 50 lbs not permitted" is a 50 lb limit (uiuc l11)
@pytest.mark.parametrize("t", [
    "Rent $1,500. Dogs larger than 50 lbs not permitted.",
    "Rent $1,500. Dogs over 50 lbs are not allowed.",
    "Rent $1,500. Dogs bigger than 50 lbs are not permitted.",
    "Rent $1,500. Dogs heavier than 50 pounds not accepted.",
    "Rent $1,500. No dogs larger than 50 lbs.",
    "Rent $1,500. We do not allow dogs larger than 50 lbs.",
    "Rent $1,500\nPets: 2 max\nDogs larger than 50 lbs not permitted\n",
    "Rent $1,500. No dogs weighing more than 50 lbs.",
])
def test_larger_than_n_lbs_not_permitted_is_a_limit(t):
    r = P(t)
    assert r["pet_weight_limit"] == 50
    _r, s = fit(t, "dog", 60)
    assert s["passes"] is False and "50" in s["detail"]
    _r, s = fit(t, "dog", 40)
    assert s["passes"] is not False


def test_uiuc_l11_whole_listing():
    t = F("r32-uiuc-l11.txt")
    r = P(t, "dog")
    assert (r["price"], r["pet_weight_limit"], r["pet_count_limit"], r["pet_fee"]) == (1420, 50, 2, 400)
    assert "left empty" not in notes(r).split("weight limit")[0][-80:] or "weight limit is left empty" not in notes(r)
    r = P(t, "cat")
    assert r["pet_fee"] == 250 and r["pet_weight_limit"] == 50


def test_a_weight_in_an_unrelated_line_is_no_limit():
    r = P("Rent $1,500. Dogs welcome. Elevator holds 2,000 lbs. Packages over 50 lbs are not allowed in the lobby.")
    assert "pet_weight_limit" not in r


# ---- soft limit: "larger dogs considered" never makes the limit a flat no (family, uiuc l3)
@pytest.mark.parametrize("t,limit", [
    ("Rent $1,500. Dogs under 25 lbs ok, larger dogs considered.", 25),
    ("Rent $1,500. Larger dogs considered. Dogs under 40 lbs welcome.", 40),
    ("Rent $1,500. Dogs OK up to 70 lbs. No breed restrictions. Larger dogs considered.", 70),
    ("Rent $1,500\nDogs: 30 lb max\nBigger dogs case by case\n", 30),
    ("Rent $1,500. Dogs 25 lb max; bigger dogs by approval.", 25),
    ("Rent $1,500. Dogs up to 50 lbs. Heavier dogs may be approved.", 50),
])
def test_larger_dogs_considered_is_a_soft_limit(t, limit):
    r = P(t)
    assert r["pet_weight_limit"] == limit
    assert "waived" in notes(r) or "larger" in notes(r).lower() or "bigger" in notes(r).lower() or "heavier" in notes(r).lower()
    _r, s = fit(t, "dog", limit + 30)
    assert s["passes"] is None and s["known"] is False
    assert "waived or needs approval" in s["detail"]
    _r, s = fit(t, "dog", limit - 5)
    assert s["passes"] is not False


def test_a_hard_limit_without_a_soft_word_still_fails_a_heavy_dog():
    for t in ("Rent $1,500. Dogs under 25 lbs only.", "Rent $1,500. Dogs max 25 lbs. No exceptions."):
        r, s = fit(t, "dog", 60)
        assert r["pet_weight_limit"] == 25 and s["passes"] is False


def test_uiuc_l3_whole_listing_soft_limit_note():
    r = P(F("r32-uiuc-l3.txt"), "dog")
    assert r["pet_weight_limit"] == 70 and r["pets"] == "dogs"
    assert "can be waived with approval" in notes(r)


# ---- a question followed by its answer is read as the answer (rule x), nontech l15
@pytest.mark.parametrize("t", [
    "Rent $1,500. Do you allow dogs? Yes up to 25 lb.",
    "Rent $1,500. Do you allow dogs? Yes, up to 25 lb.",
    "Rent $1,500\nDo you allow dogs? Yes up to 25 lb\n",
    "Rent $1,500. Are dogs allowed? Yes! Up to 25 lbs.",
    "Rent $1,500 | Do you allow dogs? Yes up to 25 lb. | Parking none",
    "Rent $1,500. DO YOU ALLOW DOGS? YES UP TO 25 LB.",
])
def test_answered_dog_question_is_the_answer(t):
    r = P(t)
    assert r["pets"] == "dogs" and r["pet_weight_limit"] == 25
    assert "question" not in notes(r)
    _r, s = fit(t, "dog", 60)
    assert s["passes"] is False
    _r, s = fit(t, "dog", 20)
    assert s["passes"] is True


def test_nontech_l15_whole_listing():
    r = P(F("r32-nontech-l15.txt"), "dog")
    assert (r["pets"], r["pet_weight_limit"], r["price"]) == ("both", 25, 1340)
    assert "question" not in notes(r)


@pytest.mark.parametrize("t,pets", [
    ("Rent $1,500. Do you allow pets? No.", "none"),
    ("Rent $1,500. Cats allowed? Yes. Dogs allowed? No.", "cats"),
    ("Rent $1,500. Are pets allowed? Yes, cats and dogs up to 40 lbs.", "both"),
])
def test_other_answered_pet_questions(t, pets):
    assert P(t)["pets"] == pets


@pytest.mark.parametrize("t", [
    "Rent $1,500. Do you allow dogs? Please inquire.",
    "Rent $1,500. Do you allow dogs? Ask us.",
    "Rent $1,500. Are pets allowed?",
    "Rent $1,500\nDo you allow dogs?\nCall for details\n",
    "Rent $1,500. Can the 40 lb limit be waived? Ask us.",
])
def test_a_question_with_no_answer_is_still_only_a_question(t):
    r = P(t)
    assert "pets" not in r and "pet_weight_limit" not in r
    assert "question" in notes(r)


# ---- "No breed restrictions apply to cats" is not a breed note for dogs (family l12)
@pytest.mark.parametrize("t", [
    "Rent $2,325. Pet policy: dogs considered, ask for details. No breed restrictions apply to cats.",
    "Rent $2,325. No breed restrictions apply to cats. Dogs ok up to 40 lbs.",
    "Rent $2,325\nNo breed restrictions for cats\nDogs ok up to 30 lbs\n",
    "Rent $2,325. Cats ok (no breed restrictions on cats). Dogs considered.",
])
def test_cat_only_breed_line_is_not_a_breed_note(t):
    assert "pet_breed_note" not in P(t, "dog")


@pytest.mark.parametrize("t,note", [
    ("Rent $2,325. Pets ok. No breed restrictions.", "No breed restrictions"),
    ("Rent $2,325. Cats ok. No breed restrictions for cats. Dogs: no pit bulls.", "Dogs: no pit bulls"),
    ("Rent $2,325. No breed restrictions apply to cats. Breed restrictions apply to dogs.", "Breed restrictions apply to dogs"),
])
def test_a_breed_line_about_dogs_or_pets_is_kept(t, note):
    assert P(t, "dog")["pet_breed_note"] == note


def test_family_l12_whole_listing():
    r = P(F("r32-family-l12.txt"), "dog")
    assert "pet_breed_note" not in r and "pets" not in r and r["price"] == 2325
    assert "not counted anywhere" not in notes(r) and "Only" not in notes(r)  # G4 may explain the matching $4,800 total plainly


# ---- no pets in the search: pet amounts are one quiet note, never a gap (uiuc l11)
def _flow(store, listing, pet_kind=None):
    s = store.add_search("C", "rent")
    if pet_kind:
        store.update_search(s["id"], pet_kind=pet_kind, pet_count=1)
    srv = server(store)
    call(srv, "add_place", title="A", address="1 Oak St, Champaign IL", price=1420, listing_text=listing)
    call(srv, "add_place", title="B", address="2 Oak St", price=900)
    e = enrich.enrich_places(store, store.get_search(s["id"]), [store.get_place(1)])[0]
    return srv, e


@pytest.mark.parametrize("t", [
    "Rent $1,420. 1 bed. Security deposit $1,420. Pet fee $400 for dogs, $250 for cats.",
    "Rent $1,420. 1 bed. Security deposit $1,420. Pet fee: $250 per cat, $400 per dog.",
    "Rent $1,420. 1 bed. Security deposit $1,420. Cat fee $250. Dog fee $400.",
    "Rent $1,420. 1 bed. Security deposit $1,420. Pet rent: $25 per cat, $50 per dog.",
    "Rent $1,420. 1 bed. Security deposit $1,420. Pet deposit $300 (cat), $500 (dog).",
])
def test_no_pets_in_search_leaves_pet_amounts_out_of_missing_and_fit(store, t):
    srv, e = _flow(store, t)
    out = mtext(call(srv, "get_place", place_id=1))
    assert "pet" not in out.split("Monthly cost")[1].split("\n")[0]
    assert "amounts in the listing notes" not in out and "$250 and $400" not in out and "$25 and $50" not in out
    cmp_ = mtext(call(srv, "compare_places", place_ids=[1, 2]))
    still = next(l for l in cmp_.split("\n") if l.startswith("Still unknown"))
    assert "pet" not in still.lower()


def test_a_cat_fee_for_a_dog_search_is_not_a_listed_missing_amount(store):
    srv, e = _flow(store, "Rent $1,420. 1 bed. Cats ok. Cat fee $300. Security deposit $1,420.", pet_kind="dog")
    out = mtext(call(srv, "get_place", place_id=1))
    assert "$300 amount" not in out


@pytest.mark.parametrize("t", [
    "Rent $2,325. Cats allowed, 2 max, no breed restrictions.",
    "Rent $2,325. Cat friendly (breed restrictions apply).",
])
def test_a_cat_only_listing_keeps_its_breed_line(t):
    assert "pet_breed_note" in P(t, "cat")
