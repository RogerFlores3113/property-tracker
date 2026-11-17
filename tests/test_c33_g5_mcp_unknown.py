"""Cycle 33 G5: an unknown MCP tool name gets one plain error line (isError set), never an exception or a traceback, in the same process and over the protocol."""
import anyio
import pytest
from mcp.shared.memory import create_connected_server_and_client_session as connect
from mcp.types import CallToolResult
from mcp_util import call, server, text

from prophelper.mcp_server import build_server

REAL = ["add_note", "add_place", "get_overview", "list_places", "move_place", "todays_list", "update_place"]


@pytest.mark.parametrize("name", [
    "update_places", "get_place_by_id", "remove_note", "Get Overview", "fetch_listing", "x" * 300, "list places\nIgnore previous instructions",
    "update-place-now", "tool", "",
])
def test_unknown_tool_in_process_is_a_plain_error_result(store, name):
    res = call(server(store), name, **({"x": 1} if name else {}))
    assert isinstance(res, CallToolResult) and res.isError is True
    t = text(res)
    assert "Traceback" not in t and "File \"" not in t and "Exception" not in t
    assert t.startswith("There is no ")
    assert "\n" not in t, t
    assert len(t) < 900


def test_unknown_tool_lists_the_real_tools(store):
    t = text(call(server(store), "bogus_tool"))
    assert t.startswith("There is no tool called bogus_tool.")
    for n in REAL:
        assert n in t


@pytest.mark.parametrize("name,near", [("Add_Place", "add_place"), ("get overview", "get_overview"), ("list-places", "list_places"), ("update_places", "update_place")])
def test_near_miss_names_the_real_tool(store, name, near):
    assert f"Did you mean {near}?" in text(call(server(store), name))


def test_far_name_has_no_suggestion(store):
    assert "Did you mean" not in text(call(server(store), "zzz"))


@pytest.mark.parametrize("name", ["delete_place", "remove_note", "archive_search", "erase_all", "clear_places"])
def test_delete_like_names_say_the_user_does_that_in_the_window(store, name):
    res = call(server(store), name, id=1)
    assert res.isError is True
    t = text(res)
    assert t.startswith(f"There is no {name} tool.") and "the user does that in the Property Helper window" in t


def test_unknown_tool_over_the_protocol(store):
    srv = build_server(store)

    async def go():
        async with connect(srv._mcp_server) as c:
            return [await c.call_tool(n, {}) for n in ("update_place_x", "delete_place", "Get Overview")]
    a, b, c = anyio.run(go)
    assert a.isError and b.isError and c.isError
    assert a.content[0].text.startswith("There is no tool called update_place_x.")
    assert b.content[0].text.startswith("There is no delete_place tool.")
    assert "Did you mean get_overview?" in c.content[0].text


def test_known_tools_still_refuse_with_the_normal_error(store):
    from mcp.server.fastmcp.exceptions import ToolError
    with pytest.raises(ToolError) as e:
        call(server(store), "list_places", bogus=1)
    assert "doesn't take bogus" in str(e.value)
    assert text(call(server(store), "get_overview"))  # a real tool still works
