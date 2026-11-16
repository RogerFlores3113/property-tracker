"""Cycle 24 G5 item 6: a pets rule with no target is refused with the allowed values, unless the search has pets."""
import pytest

from mcp_util import call, server, text


def _err(store, **kw):
    srv = server(store)
    try:
        r = call(srv, "create_search", name="U", **kw)
    except Exception as exc:  # noqa: BLE001
        return str(exc)
    return text(r)


@pytest.mark.parametrize("crit", [
    {"kind": "pets", "weight": 10},
    {"kind": "pets", "weight": 10, "target": {}},
    {"kind": "pets", "label": "No pets", "dealbreaker": True},
])
def test_pets_rule_with_no_target_refused(store, crit):
    out = _err(store, criteria=[crit])
    assert "a pets rule needs to know which pets" in out
    assert '"want": "cats"' in out and '"want": "dogs"' in out and '"want": "both"' in out
    assert store.list_searches() == []  # nothing saved


def test_pets_rule_with_none_pet_kind_refused(store):
    assert "needs to know which pets" in _err(store, pet_kind="none", criteria=[{"kind": "pets"}])
    assert store.list_searches() == []


@pytest.mark.parametrize("kw", [
    {"criteria": [{"kind": "pets", "target": {"want": "dogs"}}]},
    {"criteria": [{"kind": "pets", "target": "cats"}]},
    {"pet_kind": "dog", "criteria": [{"kind": "pets"}]},
    {"pet_kind": "both", "criteria": [{"kind": "pets", "weight": 20}]},
])
def test_pets_rule_with_a_target_or_pets_is_saved(store, kw):
    out = _err(store, **kw)
    assert out.startswith("Created search")


def test_update_search_add_pets_rule(store):
    srv = server(store)
    call(srv, "create_search", name="U")
    with pytest.raises(Exception) as e:
        call(srv, "update_search", add_criteria_list=[{"kind": "pets"}])
    assert "needs to know which pets" in str(e.value)
    assert not any(c["kind"] == "pets" for c in store.list_criteria(1))
    call(srv, "update_search", add_criteria_list=[{"kind": "pets", "target": {"want": "cats"}}])
    assert any(c["kind"] == "pets" for c in store.list_criteria(1))
    call(srv, "create_search", name="V", pet_kind="dog")
