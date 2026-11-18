"""Cycle 37 G5: a fee written as a spreadsheet formula gets one plain note that matches the cost lines: the $50 of "$50 admin fee =HYPERLINK(...)" is counted
and the note says so; a formula with no readable figure ("=SUM(A1:A9) application fee", 'Application fee: =HYPERLINK("x","$40")') says nothing is counted and
no "$40 not counted anywhere" note or missing amount appears."""
import pytest
from c37_g5_util import F, add, line, search, view

from prophelper.parsers import parse_listing

BASE = "Quay Row 41 Quay Rd Oakland CA 94601. 1 bed 1 bath $2,000/mo. Deposit $1,000."


def _notes(r):
    return (r.get("found_in_listing") or "").split("\n")


NO_FIGURE = [
    ("=SUM(A1:A9) application fee", "application fee"),
    ("Application fee: =SUM(A1:A9)", "application fee"),
    ('Application fee: =HYPERLINK("http://x.example","$40").', "application fee"),
    ("- Admin fee =SUM(B2:B3)", "admin fee"),
    ('Pet fee: =IMPORTXML("http://x.y","//a")', "pet fee"),
    ("Application fee =SUM(1+1) per applicant", "application fee"),
]


@pytest.mark.parametrize("l,label", NO_FIGURE)
@pytest.mark.parametrize("layout", ["own_line", "after", "before", "pipes"])
def test_formula_with_no_readable_figure_one_plain_note(l, label, layout):
    t = {"own_line": BASE + "\n" + l, "after": BASE + " " + l, "before": l + "\n" + BASE, "pipes": BASE + " | " + l + " | Pets ok."}[layout]
    r = parse_listing(t, "")
    n = _notes(r)
    hit = [x for x in n if "spreadsheet formula" in x]
    assert len(hit) == 1, n
    assert label in hit[0].lower() and "Nothing is counted for it" in hit[0]
    assert not [x for x in n if x.startswith("The listing also says") and "$40" in x], n
    assert r["price"] == 2000 and r["deposit"] == 1000
    assert not r.get("application_fee")


@pytest.mark.parametrize("l", [
    'Rent includes a $50 admin fee =HYPERLINK("http://evil.example","click") per month.',
    '$50 admin fee =HYPERLINK("http://evil.example","click")',
    'Admin fee $50 =HYPERLINK("http://evil.example","click") monthly',
])
def test_figure_beside_formula_note_agrees_with_counting(l):
    r = parse_listing(BASE + "\n" + l, "")
    n = [x for x in _notes(r) if "spreadsheet formula" in x]
    assert len(n) == 1, _notes(r)
    assert "could not be read" not in n[0]
    counted = r.get("move_in_fees") == 50 or r.get("other_monthly_fees") == 50
    assert ("The $50 is counted in the cost." in n[0]) == counted, (n, r)
    assert ("The $50 is not counted." in n[0]) == (not counted)


def test_reviewer_listings(store):
    for name, label in (("r36-nontech-l4.txt", "application fee"), ("r36-nontech-l10.txt", "application fee"), ("r36-uiuc-l10.txt", "admin fee")):
        r = parse_listing(F(name), "")
        n = [x for x in _notes(r) if "spreadsheet formula" in x]
        assert len(n) == 1, (name, _notes(r))
        assert label in n[0]
    r = parse_listing(F("r36-nontech-l10.txt"), "")
    assert not [x for x in _notes(r) if "$40" in x]
    s = search(store)
    pid, _ = add(store, s, "L10", F("r36-nontech-l10.txt"))
    assert "$40" not in line(view(store, pid), "Monthly cost")
    pid, _ = add(store, s, "U10", F("r36-uiuc-l10.txt"))
    out = view(store, pid)
    assert "Nothing is counted for it" not in out and "The $50 is counted in the cost." in out
    assert "fees spread $4" in line(out, "Monthly cost")


@pytest.mark.parametrize("l", ["Application fee $45.", "Admin fee: $50 per month.", "Tech package $35 monthly (=1+1 is not a formula).", "Please email x=SUM now."])
def test_negative_plain_fees_have_no_formula_note(l):
    r = parse_listing(BASE + "\n" + l, "")
    assert not [x for x in _notes(r) if "spreadsheet formula" in x], _notes(r)
