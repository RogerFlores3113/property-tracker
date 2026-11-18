"""Cycle 37 G5 helpers: paste a whole listing through the MCP add_place and read what the person would see (get_place, compare, today)."""
import os

from mcp_util import call, server, text

HERE = os.path.join(os.path.dirname(__file__), "fixtures", "panel")


def F(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as fh:
        return fh.read()


def search(store, **kw):
    s = store.add_search("Test", kw.pop("mode", "rent"), **kw)
    store.set_current_search(s["id"])
    return s


def add(store, s, title, listing, **kw):
    """Add a place by listing text; returns (place_id, add reply)."""
    out = text(call(server(store), "add_place", title=title, listing_text=listing, search_id=s["id"], **kw))
    pid = max(p["id"] for p in store.list_places(s["id"]))
    return pid, out


def view(store, pid):
    return text(call(server(store), "get_place", place_id=pid))


def line(out, head):
    return next((x for x in out.splitlines() if x.startswith(head)), "")
