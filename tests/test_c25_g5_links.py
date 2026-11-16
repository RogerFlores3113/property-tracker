"""Cycle 25 G5 item 3: a link whose host has a bidi/control character or percent codes is refused, each with its own reason."""
import pytest

from prophelper.store import HOST_CONTROL_REASON, HOST_PERCENT_REASON, link_host_problem, normalize_url


@pytest.mark.parametrize("link", ["https://exa‮mple.com/x", "https://exa​mple.com/x", "https://example⁦.com/x", "http://ex­ample.com", "https://exa\u0007mple.com/"])
def test_control_hosts_refused(link):
    assert link_host_problem(link) == HOST_CONTROL_REASON
    assert normalize_url(link) == ""


@pytest.mark.parametrize("link", ["https://ex%61mple.com/x", "https://www.ex%2Dample.com", "http://example%2ecom/", "https://user.ex%61mple.com:8080/a"])
def test_percent_hosts_refused(link):
    assert link_host_problem(link) == HOST_PERCENT_REASON
    assert normalize_url(link) == ""


@pytest.mark.parametrize("link", ["https://example.com/a%61b?q=%20", "https://example.com/x‮", "example.com/path", "https://sub.example.co.uk:8443/p"])
def test_ok_links_still_work(link):
    assert link_host_problem(link) == ""


@pytest.mark.parametrize("link,reason,word", [("https://exa‮mple.com/x", HOST_CONTROL_REASON, "hidden"), ("https://ex%61mple.com/x", HOST_PERCENT_REASON, "percent")])
def test_saving_gives_the_right_reason(store, link, reason, word):
    store.add_search("C", "rent")
    with pytest.raises(ValueError) as e:
        store.add_place(title="A", address="1 A St", url=link)
    assert str(e.value) == reason and word in reason and "private network" not in str(e.value)
