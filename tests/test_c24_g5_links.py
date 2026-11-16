"""Cycle 24 G5 item 8: one-word hosts like http://corp/ are refused like .local; normal links still work."""
import pytest

from prophelper.store import PRIVATE_LINK_REASON, link_host_private, normalize_url, private_host


@pytest.mark.parametrize("link", ["http://corp/", "http://corp", "https://intranet/listing/5", "http://printer:8080/x", "HTTP://Corp/", "http://wiki/home",
                                  "http://localhost/", "http://localhost:3000/a", "http://box.local/", "http://x.internal/a", "http://127.0.0.1/", "http://192.168.1.5/a",
                                  "http://nas.lan/"])
def test_private_links_refused(link):
    assert link_host_private(link)
    assert normalize_url(link) == ""


@pytest.mark.parametrize("link,expected", [
    ("https://www.zillow.com/homedetails/1", "https://zillow.com/homedetails/1"),
    ("http://apartments.com/x", "https://apartments.com/x"),
    ("example.com/a", "https://example.com/a"),
    ("https://sub.example.co.uk/p", "https://sub.example.co.uk/p"),
    ("https://8.8.8.8/x", "https://8.8.8.8/x"),
])
def test_normal_links_work(link, expected):
    assert not link_host_private(link)
    assert normalize_url(link) == expected


def test_reason_mentions_one_word_names():
    assert "one-word name like corp" in PRIVATE_LINK_REASON
    assert private_host("corp", one_word=True) and not private_host("corp.com", one_word=True)


def test_saving_a_one_word_link_is_refused_with_the_reason(store):
    import pytest as _p
    s = store.add_search("C", "rent")
    with _p.raises(ValueError) as e:
        store.add_place(title="A", address="1 A St", url="http://corp/")
    assert "one-word name like corp" in str(e.value)
