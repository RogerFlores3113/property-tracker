"""Cycle 25 G5 item 7: a refused update_place (notes, a backward move) is a plain ToolError message, never a crash; over the wire it is an error result."""
import anyio
import pytest
from mcp.server.fastmcp.exceptions import ToolError

from mcp_util import call, server


def _place(store):
    s = store.add_search("S", "rent")
    p = store.add_place(title="A", address="1 A St", price=1500)
    p = p[0] if isinstance(p, tuple) else p
    return s, p


def test_backward_move_is_a_plain_error(store):
    s, p = _place(store)
    srv = server(store)
    call(srv, "move_place", place_id=p["id"], stage="Contacted")
    with pytest.raises(ToolError) as e:
        call(srv, "move_place", place_id=p["id"], stage="Interested")
    msg = str(e.value)
    assert "Traceback" not in msg and "could not finish" not in msg and msg.strip()


def test_update_with_notes_refusal_is_plain(store):
    s, p = _place(store)
    srv = server(store)
    with pytest.raises(ToolError) as e:
        call(srv, "update_place", place_id=p["id"], notes="x", price=-5)
    msg = str(e.value)
    assert "Traceback" not in msg and "could not finish" not in msg and msg.strip()


def test_refusal_over_the_protocol_is_an_error_result_not_a_crash(store):
    s, p = _place(store)
    srv = server(store)

    async def go():
        from mcp.shared.memory import create_connected_server_and_client_session
        async with create_connected_server_and_client_session(srv._mcp_server) as client:
            return await client.call_tool("update_place", {"place_id": p["id"], "notes": "x", "price": -5})
    res = anyio.run(go)
    assert res.isError
    body = "".join(c.text for c in res.content)
    assert "Traceback" not in body and body.strip()
