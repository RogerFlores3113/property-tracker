"""Cycle 35 G5: 'Tech package $=HYPERLINK("http://e.x") monthly' has a dollar sign where the amount should be and spreadsheet formula text after it. The odd text
is ignored, no amount is invented, and a plain note says an amount could not be read and what to ask."""
import os

import pytest

from prophelper.parsers import parse_listing

HERE = os.path.join(os.path.dirname(__file__), "fixtures", "panel")


def F(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as fh:
        return fh.read()


BASE = "Quay Row 41 Quay Rd Oakland CA 94601. 1 bed 1 bath $2,000/mo. Deposit $1,000."


def P(t):
    return parse_listing(t, "")


def fields(r):
    return {k: v for k, v in r.items() if k != "found_in_listing"}


def notes(r):
    return (r.get("found_in_listing") or "").split("\n")


CASES = [
    ('Tech package $=HYPERLINK("http://e.x") monthly @SUM(1+1)*cmd|\' /C calc\'!A0 extra.', "tech package"),
    ("Amenity package $=cmd|' /C calc'!A0 monthly.", "amenity package"),
    ("Valet trash $=SUM(A1:A2) per month.", "valet trash"),
    ('- Tech package: $=HYPERLINK("http://e.x") monthly', "tech package"),
    ('Gym fee $ =IMPORTXML("http://x.y","//a") monthly', "gym fee"),
    ("Parking $＝HYPERLINK(\"http://x.y\") /mo", "parking"),
    ('Internet $=WEBSERVICE("http://x.y") a month', "internet"),
    ('Pest control $=HYPERLINK("http://e.x")', "pest control"),
]


@pytest.mark.parametrize("line,label", CASES)
@pytest.mark.parametrize("layout", ["own_line", "after", "before", "pipes", "bullets"])
def test_unreadable_formula_amount_gets_a_plain_note(line, label, layout):
    if layout == "own_line":
        t = BASE + "\n" + line
    elif layout == "after":
        t = BASE + " " + line
    elif layout == "before":
        t = line + "\n" + BASE
    elif layout == "pipes":
        t = BASE + " | " + line + " | Pets ok."
    else:
        t = "- " + BASE.replace(". ", "\n- ") + "\n- " + line.lstrip("- ")
    r = P(t)
    base = P(BASE)
    assert r["price"] == 2000 and r["deposit"] == 1000
    assert fields(r).get("utilities_estimate") == base.get("utilities_estimate")
    hit = [n for n in notes(r) if "could not be read" in n]
    assert len(hit) == 1, notes(r)
    assert label in hit[0].lower(), hit
    assert "spreadsheet formula" in hit[0] and "Ask the landlord" in hit[0]
    assert "not counted" not in hit[0].lower() or "nothing is counted" in hit[0].lower()
    assert "$" not in hit[0].replace("$ ", "")  # no amount is invented or quoted


def test_the_reviewer_listing_privacy_l11():
    r = P(F("r34-privacy-l11.txt"))
    hit = [n for n in notes(r) if "could not be read" in n]
    assert len(hit) == 1 and "tech package" in hit[0].lower(), notes(r)


def test_the_reviewer_listing_privacy_l10_amenity_package():
    r = P(F("r34-privacy-l10.txt"))
    hit = [n for n in notes(r) if "could not be read" in n]
    assert len(hit) == 1 and "amenity package" in hit[0].lower(), notes(r)


def test_unlabelled_formula_amount_still_gets_a_note():
    r = P(BASE + '\nExtra $=HYPERLINK("http://e.x") monthly')
    assert any("could not be read" in n for n in notes(r)), notes(r)


# ---- negatives
def test_a_formula_next_to_a_real_figure_keeps_the_real_figure_note():
    t = BASE + '\nPets ok. =HYPERLINK("http://evil.example/x","click") Admin fee $45 monthly.'
    r = P(t)
    assert not any("could not be read" in n for n in notes(r)), notes(r)


@pytest.mark.parametrize("line", ["Parking $50/mo.", "Tech package $75 monthly.", "Rent includes a $ sign in the sign-up form."])
def test_plain_figures_get_no_unreadable_note(line):
    r = P(BASE + "\n" + line)
    assert not any("could not be read" in n for n in notes(r)), notes(r)
