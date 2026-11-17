"""Cycle 34 group G5: a link with a space in its host is refused (never saved as exa%20mple.com); the refusal to write the user's notes is an
error result, never an exception (so no traceback in a driver); both in the same process and over the protocol."""
import anyio
import pytest
from mcp.shared.memory import create_connected_server_and_client_session as connect
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import CallToolResult
from mcp_util import call, server, structured, text

from prophelper.mcp_server import build_server
from prophelper.store import link_host_problem, normalize_url, safe_link


@pytest.fixture(autouse=True)
def _search(store):
    store.add_search("S", "rent")


SPACED = [
    "https://exa mple.com/",
    "https://exa mple.com",
    "http://exa mple.com/listing/1",
    "https://www.exa mple.com/a?b=1",
    "https://exam ple.co.uk/x y",
    "https://example. com/",
    "https://example .com/path",
    "https://exa\tmple.com/",
    "https://exa mple.com/",
    "https://sub.exa mple.com:8080/",
]


@pytest.mark.parametrize("url", SPACED)
def test_space_in_host_is_refused(url):
    assert "space" in link_host_problem(url)
    assert normalize_url(url) == ""
    assert safe_link(url) == ""


@pytest.mark.parametrize("url,expected", [
    ("https://example.com/ok?a=b c", "https://example.com/ok?a=b+c"),
    ("https://example.com/a b", "https://example.com/a b"),
    ("https://www.zillow.com/homedetails/12-Main-St/1_zpid/", "https://zillow.com/homedetails/12-Main-St/1_zpid"),
    ("example.com/listing", "https://example.com/listing"),
])
def test_spaces_in_the_path_or_query_are_still_fine(url, expected):
    assert link_host_problem(url) == ""
    assert normalize_url(url) == expected


@pytest.mark.parametrize("url", SPACED[:6])
def test_store_refuses_a_spaced_host_link(store, url):
    with pytest.raises(ValueError) as e:
        store.add_place(title="A", address="1 A St", url=url)
    assert "space" in str(e.value)
    p, _ = store.add_place(title="B", address="2 A St")
    with pytest.raises(ValueError):
        store.update_place(p["id"], url=url)
    assert store.get_place(p["id"])["url"] == ""


@pytest.mark.parametrize("url", SPACED[:5])
def test_mcp_add_and_update_refuse_a_spaced_host_link(store, url):
    srv = server(store)
    with pytest.raises(ToolError) as e:
        call(srv, "add_place", title="A", address="1 A St", url=url)
    assert "space" in str(e.value) and "exa%20mple" not in str(e.value)
    r = structured(call(srv, "add_place", title="B", address="2 B St"))
    with pytest.raises(ToolError) as e:
        call(srv, "update_place", place_id=r["place_id"], url=url)
    assert "space" in str(e.value)
    assert store.get_place(r["place_id"])["url"] == ""
    assert not any("exa%20mple" in str(p.get("url")) for p in store.list_places())


def test_mcp_photo_link_with_a_spaced_host_is_dropped_with_a_note(store):
    srv = server(store)
    r = call(srv, "add_place", title="C", address="3 C St", photo_urls=["https://exa mple.com/a.jpg", "https://img.example.com/ok.jpg"])
    body = text(r)
    assert "space" in body
    p = store.get_place(structured(r)["place_id"])
    assert p["photo_urls"] == ["https://img.example.com/ok.jpg"]


# ---- the refusal to write the user's notes is an error result, not an exception
@pytest.mark.parametrize("tool,args", [
    ("update_place", {"notes": "my note"}),
    ("update_place", {"notes": "my note", "price": 1500}),
    ("update_place", {"price": 1500, "notes": "x", "ai_notes": "y"}),
    ("update_place", {"rating": 5}),
    ("update_place", {"hidden": True}),
    ("update_place", {"notes": ""}),
])
def test_notes_refusal_is_an_error_result_in_process(store, tool, args):
    p, _ = store.add_place(title="A", address="1 A St", price=1400)
    res = call(server(store), tool, place_id=p["id"], **args)
    assert isinstance(res, CallToolResult) and res.isError is True
    t = text(res)
    assert "Traceback" not in t and 'File "' not in t and "Exception" not in t and "could not finish" not in t
    assert "doesn't take" in t and "nothing was done" in t
    assert ("ai_notes" in t) if "notes" in args else True
    assert store.get_place(p["id"])["notes"] in ("", None)
    assert store.get_place(p["id"])["price"] == 1400


def test_add_place_notes_refusal_is_an_error_result(store):
    res = call(server(store), "add_place", title="A", address="1 A St", notes="mine")
    assert res.isError is True and "ai_notes" in text(res) and "Traceback" not in text(res)
    assert store.list_places() == []


def test_notes_refusal_over_the_protocol(store):
    p, _ = store.add_place(title="A", address="1 A St", price=1400)
    srv = build_server(store)

    async def go():
        async with connect(srv._mcp_server) as c:
            return await c.call_tool("update_place", {"place_id": p["id"], "notes": "x"})
    res = anyio.run(go)
    assert res.isError and "ai_notes" in res.content[0].text and "Traceback" not in res.content[0].text


def test_other_unknown_arguments_still_raise_the_normal_error(store):
    with pytest.raises(ToolError) as e:
        call(server(store), "update_place", place_id=1, bogus=1)
    assert "doesn't take bogus" in str(e.value)
    with pytest.raises(ToolError):
        call(server(store), "update_search", search_id=1, notes="x")
