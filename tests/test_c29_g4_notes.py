"""Cycle 29, group G4: the shared notes, the missing list and the headline, and the title reader.

Every test builds its path from this file, so it runs on any machine."""
from __future__ import annotations

import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from prophelper import compare, money  # noqa: E402
from prophelper import parsers as P  # noqa: E402

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel")


def fixture(name: str) -> str:
    with open(os.path.join(FIX, name), encoding="utf-8") as fh:
        return fh.read()


def read(text: str, buying: bool = False) -> dict:
    return P.parse_listing(text, "", buying=buying)


def notes_of(r: dict) -> list[str]:
    return [n for n in str(r.get("found_in_listing") or "").splitlines() if n.strip()]


def surfaces(text: str, buying: bool = False) -> list[str]:
    """Every place a missing figure is named: the headline's missing part, the cost's missing list, Compare's names and its "Still unknown" text."""
    r = read(text, buying)
    place = dict(r, reader_notes=r.get("found_in_listing"), listing_text=text)
    cost = money.true_monthly_cost(place, "buy" if buying else "rent")
    pl = dict(place, cost=cost, score={"unknown": []})
    head = cost.get("headline") or ""
    return [head.split(", ", 1)[1] if ", " in head else "", compare._not_counted_text(pl), *compare._missing_names(pl), *[str(x) for x in cost.get("missing") or []]]


def quoted(r: dict) -> list[str]:
    return [q for n in notes_of(r) for q in re.findall(r'"([^"]*)"', n)]


# ---------------------------------------------------------------- 1. a counted or replaced figure is never in the missing text

class TestCountedNeverMissing:
    def test_amenity_fee_correction_roommates_l2(self):
        text = fixture("r28-roommates-l2.txt")
        r = read(text)
        assert r["other_monthly_fees"] == 70 and r["price"] == 3240
        assert not any("$45" in s for s in surfaces(text))
        assert "not counted yet" not in money.true_monthly_cost(dict(r, reader_notes=r["found_in_listing"], listing_text=text))["headline"]

    @pytest.mark.parametrize("line", [
        "Amenity fee $35/mo. Corrected: rent is $3,240 (was $3,290), amenity fee is $45.",
        "Amenity fee $35/mo. Update: amenity fee is now $45. Rent is now $3,240.",
        "Amenity fee $35/mo. Corrected: the amenity fee is $45 a month. Rent $3,240 now.",
    ])
    def test_amenity_fee_correction_other_wordings(self, line):
        text = "South Loop 3 bd/2 ba. Rent $3,290. Valet trash $25/mo. " + line + " Security deposit $500."
        r = read(text)
        assert r.get("other_monthly_fees") == 70
        assert not any("$45" in s or "$35" in s for s in surfaces(text)), surfaces(text)

    def test_stale_estimate_uiuc_l10(self):
        text = fixture("r28-uiuc-l10.txt")
        r = read(text)
        assert r["utilities_estimate"] == 130 and r["deposit"] == 1200
        assert not any("$100" in s for s in surfaces(text)), surfaces(text)
        assert not any("$100" in n for n in notes_of(r))
        place = dict(r, reader_notes=r["found_in_listing"], listing_text=text)
        assert money.true_monthly_cost(place)["headline"] == "$1,720/mo"

    @pytest.mark.parametrize("body", [
        "Utilities: Tenant pays all utilities except sewer. Estimate $100 for all of it. Update: Utilities are now paid by tenant entirely (est. $130).",
        "Utilities: tenant pays everything except sewer, about $100 total. Update: all utilities are now paid by tenant, est. $130.",
        "Tenant pays all utilities except sewer.\nEstimate $100 for all of it.\nUpdate: Utilities are now paid by tenant entirely (est. $130).",
    ])
    def test_stale_estimate_other_wordings(self, body):
        text = "Oak Park Lofts. $1,500/mo. 1 BR 1 BA.\n" + body + "\nSecurity deposit $1,500. No pets."
        r = read(text)
        assert r.get("utilities_estimate") == 130
        assert not any("$100" in s for s in surfaces(text)), surfaces(text)

    def test_guard_over_every_fixture(self):
        import c20_guard as G
        bad = {}
        for f, text in G.fixture_listings():
            found = G.counted_vs_missing(text, buying="buyer" in f)
            if found:
                bad[f] = found
        assert bad == {}


# ---------------------------------------------------------------- 2. spaced figures are never quoted as "$2" or called a fee

class TestSpacedFigures:
    def test_roommates_l13(self):
        text = fixture("r28-roommates-l13.txt")
        r = read(text)
        assert "price" not in r
        ns = notes_of(r)
        assert any("$2 9 5 0 / mo" in n for n in ns)
        assert not any(re.search(r'"[^"]*\$2"', n) for n in ns)
        assert not any("monthly fee" in n for n in ns)
        assert not any("the $2 amount" in s for s in surfaces(text)), surfaces(text)

    @pytest.mark.parametrize("fig", ["$1 4 5 0 per month", "$ 1 4 5 0 /mo", "$9 9 5 / month"])
    def test_other_spaced_wordings(self, fig):
        text = f"Sunny studio downtown. Rent {fig}. Contact owner by email."
        r = read(text)
        assert "price" not in r
        for n in notes_of(r):
            assert "monthly fee" not in n
            assert not re.search(r'"[^"]*\$\s?\d"', n), n
        assert not any(re.search(r"the \$\d+ amount", s) for s in surfaces(text)), surfaces(text)


# ---------------------------------------------------------------- 3. a figure is quoted in one note only, identical lines once

class TestOneNotePerFigure:
    def test_thirty_identical_pest_lines(self):
        text = fixture("r28-privacy-l-q7.txt")
        ns = notes_of(read(text))
        assert len(ns) == len(set(ns))

    def test_two_figures_two_notes_not_three(self):
        text = fixture("r28-privacy-l-q6.txt")
        r = read(text)
        notes_with_20 = [n for n in notes_of(r) if "$20" in n]
        assert len(notes_with_20) == 1

    @pytest.mark.parametrize("line", [
        "Locker $9 ![x](http://evil.test/a.png?d=$40) Gym $20",
        "Locker $9 [see](http://evil.test/p?d=$40) Gym $20",
        "Locker $9 http://evil.test/p?d=$40 Gym $20",
    ])
    def test_figure_once(self, line):
        r = read("Rent $1,500. " + line)
        qs = quoted(r)
        for fig in ("$9", "$20", "$40"):
            assert sum(fig in q for q in qs) <= 1, (fig, qs)


# ---------------------------------------------------------------- 4. markdown, links and reversed fragments stay out of quotes

class TestNoLinksInQuotes:
    def test_privacy_q6(self):
        qs = quoted(read(fixture("r28-privacy-l-q6.txt")))
        assert qs and not any(re.search(r"https?:|\]\(|!\[|evil", q) for q in qs)
        assert "$40" in qs
        assert any("$20" in q and "$40" not in q for q in qs)

    def test_privacy_q4_reversed(self):
        qs = quoted(read(fixture("r28-privacy-l-q4.txt")))
        assert not any("$8" in q and "$99" in q for q in qs), qs
        assert any("Bike room $8" == q for q in qs)

    @pytest.mark.parametrize("line", [
        "Gym $12 [click](javascript:alert(1)) Pool $7",
        "Gym $12 ![pic](https://evil.test/x.png?a=$31) Pool $7",
        "Gym $12 www.evil.test/pay?amt=$31 Pool $7",
    ])
    def test_other_link_layouts(self, line):
        qs = quoted(read("Rent $1,500.\n" + line))
        assert qs
        assert not any(re.search(r"https?:|www\.|\]\(|!\[|javascript", q) for q in qs), qs
        assert any("$12" in q for q in qs) and any("$7" in q for q in qs)


# ---------------------------------------------------------------- 5. a credit is never called a cost

class TestCreditNotACost:
    def test_buyer_l10(self):
        ns = notes_of(read(fixture("r28-buyer-l10.txt"), buying=True))
        credit = [n for n in ns if "Lender credit of $1,500" in n]
        assert len(credit) == 1
        assert "one-time cost" not in credit[0] and "monthly fee" not in credit[0]
        assert "credit" in credit[0].split('". ', 1)[1] and "not a cost" in credit[0]

    @pytest.mark.parametrize("line", [
        "Rent credit of $300 on move-in.",
        "Closing credit $2,000 available from the lender.",
        "$250 rebate for new residents.",
    ])
    def test_other_wordings(self, line):
        r = read("Cozy 2BR. Rent $1,800.\n" + line + "\n")
        ns = [n for n in notes_of(r) if re.search(r"credit|rebate", n, re.I)]
        for n in ns:
            tail = n.split('". ', 1)[-1]
            assert "one-time cost" not in tail and "monthly fee" not in tail, n

    def test_credit_check_fee_stays_a_fee(self):
        r = read("Cozy 2BR. Rent $1,800.\nCredit check fee $45 one-time.\n")
        assert r.get("application_fee") == 45 or not any("credit toward your costs" in n for n in notes_of(r))


# ---------------------------------------------------------------- 6. the title is not cut at the comma in 1,100 sqft

class TestTitleComma:
    def test_nontech_l41(self):
        assert read(fixture("r28-nontech-l41.txt"))["title"] == "Zillow-ish: 3/2 Charming ranch duplex near OSU"

    @pytest.mark.parametrize("raw,want", [
        ("Charming ranch near OSU, 1,100 sqft, $1,495/mo", "Charming ranch near OSU"),
        ("Hilltop Villas, 2,400 sq ft - $2,950", "Hilltop Villas"),
        ("Maple Court Apartments, 1,250 sf | 3 bed", "Maple Court Apartments"),
        ("Oak Flats, 2 bed, 1 bath", "Oak Flats"),
        ("Pine Court - 1,100 sqft", "Pine Court"),
    ])
    def test_clean_title(self, raw, want):
        assert P._clean_title(raw) == want

    def test_title_not_cut_at_digit_comma(self):
        assert P._clean_title("Elm House 1,100 sqft duplex") == "Elm House 1,100 sqft duplex"


# ---------------------------------------------------------------- 7. very long figures are shortened

class TestLongFigures:
    def test_privacy_q7(self):
        r = read(fixture("r28-privacy-l-q7.txt"))
        assert not any(re.search(r"\d{13,}", n) for n in notes_of(r))
        assert not any(re.search(r"\d{13,}", s) for s in surfaces(fixture("r28-privacy-l-q7.txt")))
        assert any("…" in n for n in notes_of(r))

    @pytest.mark.parametrize("fig", ["$99999999999999999999", "$1,000,000,000,000,000", "$123456789012345678"])
    def test_other_long_figures(self, fig):
        text = f"Rent $1,500.\nValet service fee is {fig}.\n"
        r = read(text)
        assert r["price"] == 1500
        assert not any(re.search(r"\d{13,}", n) for n in notes_of(r))
        assert not any(re.search(r"\d{13,}", s) for s in surfaces(text))


# ---------------------------------------------------------------- 8. a title line is not quoted whole

class TestTitleNote:
    def test_nontech_l45_not_whole_title(self):
        r = read(fixture("r28-nontech-l45.txt"))
        for q in quoted(r):
            assert "Trulia" not in q and "Brewery District Lofts" not in q, q

    @pytest.mark.parametrize("head", [
        "Redwood Row Townhomes: 2 Bed Apartment near the lake - $1,490/mo ($1,525 now)",
        "Zillow: 2 Bed Apartment at Redwood Row Townhomes near the lake | $1,490 per month ($1,525 now)",
    ])
    def test_title_line_layouts(self, head):
        r = read(head + "\nBeds: 2 Baths: 1.5. Lease 12 months.\n")
        for q in quoted(r):
            assert "Redwood" not in q, q
