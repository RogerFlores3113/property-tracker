"""Cycle 34 group G5: parking criteria accept 'garage or covered'; update_search can take a criterion out of the score (never deletes);
a repeated criterion is not added twice."""
import pytest

from mcp_util import call, server, text
from prophelper import scoring
from prophelper.mcp_server import ToolError
from prophelper.store import clean_enum


@pytest.fixture
def srv(store):
    s = store.add_search("S", "rent", budget_max=1500)
    store.set_current_search(s["id"])
    srv_ = server(store)
    call(srv_, "update_search", add_criteria_list=[{"kind": "laundry", "weight": 40, "target": {"want": "in_unit"}}, {"kind": "dishwasher", "weight": 10}])
    return srv_, s


@pytest.mark.parametrize("label", ["Garage or covered parking", "Garage/covered parking", "covered or garage", "Either a garage or a carport",
                                   "garage, covered or carport", "Garage or carport"])
def test_either_wordings_mean_covered(label):
    assert scoring.parking_either(label)
    assert scoring.infer_parking_want(label) == "covered"


@pytest.mark.parametrize("label", ["Garage", "Covered garage parking", "Garage with a roof", "Street parking", "Carport"])
def test_negatives_are_not_either(label):
    assert not scoring.parking_either(label)


def test_negative_garage_stays_garage():
    assert scoring.infer_parking_want("Garage") == "garage"
    assert scoring.infer_parking_want("Covered garage parking") == "garage"


@pytest.mark.parametrize("want", ["garage or covered", "garage, covered or carport", "covered or garage"])
def test_clean_enum_either(want):
    assert clean_enum("parking", want) == "covered"


def test_add_criterion_garage_or_covered(srv, store):
    server_, s = srv
    call(server_, "update_search", add_criteria_list=[{"kind": "parking", "label": "Garage or covered parking", "weight": 30, "target": {"want": "garage or covered"}}])
    row = [c for c in store.list_criteria(s["id"]) if c["kind"] == "parking"][-1]
    assert '"covered"' in row["target"] or "covered" in str(row["target"])


def test_remove_criteria_is_soft(srv, store):
    server_, s = srv
    crit = store.list_criteria(s["id"])
    cid = crit[0]["id"]
    n = len(crit)
    out = text(call(server_, "update_search", remove_criteria=[cid]))
    assert "Took" in out and "nothing was deleted" in out
    after = {c["id"]: c for c in store.list_criteria(s["id"])}
    assert len(after) == n and after[cid]["weight"] == 0 and not after[cid]["dealbreaker"]
    again = text(call(server_, "update_search", remove_criteria=[cid]))
    assert "already out of the score" in again


def test_remove_unknown_id_is_a_problem(srv):
    server_, _ = srv
    with pytest.raises(ToolError) as e:
        call(server_, "update_search", remove_criteria=[99999])
    assert "is not in search" in str(e.value)


def test_reweight_and_remove_same_id(srv, store):
    server_, s = srv
    cid = store.list_criteria(s["id"])[0]["id"]
    with pytest.raises(ToolError) as e:
        call(server_, "update_search", remove_criteria=[cid], reweight=[{"id": cid, "weight": 5}])
    assert "Do one or the other" in str(e.value)


def test_exact_duplicate_not_added(srv, store):
    server_, s = srv
    call(server_, "update_search", add_criteria_list=[{"kind": "beds", "weight": 10, "target": {"min": 2}}])
    n = len(store.list_criteria(s["id"]))
    out = text(call(server_, "update_search", add_criteria_list=[{"kind": "beds", "weight": 10, "target": {"min": 2}}]))
    assert "did not add it again" in out and len(store.list_criteria(s["id"])) == n


def test_same_kind_other_target_warns(srv, store):
    server_, s = srv
    call(server_, "update_search", add_criteria_list=[{"kind": "beds", "weight": 10, "target": {"min": 2}}])
    n = len(store.list_criteria(s["id"]))
    out = text(call(server_, "update_search", add_criteria_list=[{"kind": "beds", "weight": 10, "target": {"min": 3}}]))
    assert "both count" in out and len(store.list_criteria(s["id"])) == n + 1
