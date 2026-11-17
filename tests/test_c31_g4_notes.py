"""Cycle 31, group G4: the "Only $X of that" note, the vague "an amount from the listing notes", and Compare's "not counted" naming.
Reviewer listings are read from tests/fixtures/panel (paths built from this file)."""
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
    return P.parse_listing(text, "", buying=True) if buying else P.parse_listing(text, "")


def notes_of(r: dict) -> str:
    return str(r.get("found_in_listing") or "")


def place_of(text: str, buying: bool = False) -> dict:
    r = read(text, buying)
    pl = dict(r, reader_notes=r.get("found_in_listing"), listing_text=text)
    pl["cost"] = money.true_monthly_cost(pl, "buy" if buying else "rent")
    pl["score"] = {"unknown": []}
    return pl


# ---------------------------------------------------------------- 1. "Only $50 of that" says what is left out first

class TestOnlyNote:
    def test_nontech_l7(self):
        n = notes_of(read(fixture("r30-nontech-l7.txt")))
        assert ('The listing also says "One-time move-in: application $45, deposit $600, key fob $50". '
                "Only $50 of that is not counted: it is a one-time cost, so it is not in the monthly cost; "
                "the other amounts in that line are counted. Check what it is for.") in n
        assert "Only $50 of that is a one-time cost" not in n

    def test_nontech_l14(self):
        r = read(fixture("r30-nontech-l14.txt"))
        n = notes_of(r)
        assert r["move_in_fees"] == 150 and r["deposit"] == 1490
        assert ('"HOA move-in fee $150, association move-in deposit $200". Only $200 of that is not counted: '
                "it is a one-time cost, so it is not in the monthly cost; the other amounts in that line are counted.") in n

    @pytest.mark.parametrize("text,left", [
        ("2BR/1BA, $1,260/mo. Landlord pays all utilities.\nAt move-in you pay: application $45, deposit $600, key fob $50.", "$50"),
        ("2 bed 1 bath $1,260. Landlord pays all utilities. Move-in: $45 application, $600 security deposit, $50 gate remote, $40 mailbox key.", "$40 and $50"),
        ("2 bed 1 bath $1,300. Landlord pays all utilities. One-time move-in: application $45, deposit $650, parking decal $30.", "$30"),
    ])
    def test_other_wordings(self, text, left):
        r = read(text)
        n = notes_of(r)
        assert f"Only {left} of that " in n
        assert re.search(rf"Only {re.escape(left)} of that (?:is|are) not counted", n), n
        assert not re.search(r"Only \$\d+ of that is a one-time cost", n)
        assert r["application_fee"] == 45 and r["deposit"] in (600, 650)

    def test_short_form_kept_when_the_kind_says_not_counted_anywhere(self):
        r = read("2BR/1BA, $1,260/mo. Landlord pays all utilities.\nAt move-in you pay: application $45, deposit $600, key fob $50.")
        assert "Only $50 of that is not counted anywhere; the other amounts in that line are counted." in notes_of(r)


# ---------------------------------------------------------------- 2. "an amount from the listing notes" names the amount or goes

class TestMissingAmountPhrase:
    @pytest.mark.parametrize("name", ["r30-buyer-l1.txt", "r30-buyer-l4.txt", "r30-buyer-l5.txt", "r30-buyer-l9.txt"])
    def test_reviewer_listings(self, name):
        p = place_of(fixture(name), buying=True)
        assert p["cost"]["all_in"] is True
        assert "an amount from the listing notes" not in " ".join(compare.cost_unknowns(p))
        assert "an amount from the listing notes" not in (p["cost"].get("headline") or "")
        assert compare._left_out_of_notes(p) == []

    @pytest.mark.parametrize("extra,amounts,phrase", [
        ("Reservation deposit $1,000 and $750 survey fee, one-time.", ["$1,000", "$750"], "the $1,000 and $750 one-time amounts in the listing notes"),
        ("Holding fee $500.", ["$500"], "the $500 one-time amount in the listing notes"),
    ])
    def test_a_real_left_out_amount_is_named(self, extra, amounts, phrase):
        p = place_of("Home for sale $410,000, 3 bed 2 bath. Taxes $4,000/yr. Insurance $1,100/yr. HOA $40/mo. " + extra, buying=True)
        assert p["cost"]["one_time_left"] == amounts
        assert compare.cost_unknowns(p) == [phrase]

    def test_price_cut_alone_leaves_nothing_out(self):
        p = place_of("Home for sale $410,000, 3 bed 2 bath. Taxes $4,000/yr. Insurance $1,100/yr. HOA $40/mo. Price reduced $10,000.", buying=True)
        assert p["cost"]["all_in"] is True and compare._left_out_of_notes(p) == []


# ---------------------------------------------------------------- 8. Compare names only what is not counted

class TestCompareNamesOnlyUncounted:
    def test_kenwood_only_internet(self):
        p = place_of(fixture("r30-roommates-l11.txt"))
        assert compare._short_parts(p) == "internet"
        assert compare._leaves_out_clause(p) == ", and its internet isn't counted"
        sent = compare.skipped_unknown_sentences({"skipped_unknown": [p]}, lambda x: "Kenwood")
        assert sent == ["Kenwood looks cheaper, but its internet is not counted."], sent

    @pytest.mark.parametrize("text,expect", [
        ("2 bed $1,500. Heat and water included. Tenant pays electric (est $70) and gas, internet.", ["gas", "internet"]),
        ("3 bed $2,100. Water, heat and trash covered by landlord, tenant pays electricity, estimated $80/mo. Cable and wifi extra.", ["internet"]),
        ("2 bed $1,400. Tenant pays electric about $60/mo and gas, plus water.", ["gas", "water"]),
    ])
    def test_other_listings(self, text, expect):
        p = place_of(text)
        parts = compare._short_parts(p)
        for w in expect:
            assert w in parts
        assert "electric" not in parts and "utilities" not in parts


# ---------------------------------------------------------------- 3. a title is never cut at the dash of "1 - 2 Beds"

class TestBedRangeTitle:
    def test_roommates_l20(self):
        r = read(fixture("r30-roommates-l20.txt"))
        assert r["beds"] == 3 and r["price"] == 3980
        assert r["title"] == "111 W Monroe St"
        assert r["address"] == "111 W Monroe St"

    @pytest.mark.parametrize("text,title", [
        ("Sunny 1 - 2 Bedroom Apartments in Wicker Park\n2 Bed 2 Bath $1,950/mo\n1530 N Damen Ave", "Sunny 1 - 2 Bedroom Apartments in Wicker Park"),
        ("NEW 2 - 3 BR\n3 Bed 2 Bath $2,450/mo\n88 Oak St Columbus OH", "88 Oak St"),
        ("Spacious 1 - 2 Bedroom Apartments. 2 BR 2 BA $1,700. 15 Elm St Austin TX", "15 Elm St"),
        ("Modern 1 - 2 Beds, 1 - 2 Baths near campus. 2 BR 2 BA: $1,640/mo. 202 E Green St Champaign IL", "202 E Green St"),
    ])
    def test_other_wordings(self, text, title):
        r = read(text)
        assert r["title"] == title
        assert r["title"] not in ("Brand-new 1", "Sunny 1", "Spacious 1", "NEW 2", "Modern 1")

    def test_a_name_before_a_dash_still_cuts(self):
        assert read("Riverside Lofts - 2 bed 2 bath $1,800")["title"] == "Riverside Lofts"
        assert read("Lakeview Lofts 1 - 3 Beds from $1,500\n3 Bed 2 Bath 1,200 sqft $2,450/mo")["title"] == "Lakeview Lofts"


# ---------------------------------------------------------------- 4. a site label is stripped from a sent title too

class TestSiteLabelInSentTitle:
    @pytest.mark.parametrize("sent,kept", [
        ("Zillow-ish listing - Stadium View | 1 Bed | Rent $1,350", "Stadium View | 1 Bed | Rent $1,350"),
        ("Zillow-ish: Stadium View 2BR", "Stadium View 2BR"),
        ("Craigslist post - Cozy 2 bed in Linden", "Cozy 2 bed in Linden"),
        ("Apartments.com style: Maple Court Apartments", "Maple Court Apartments"),
        ("Stadium View", "Stadium View"),
        ("Zillow - ", "Zillow - "),
    ])
    def test_strip_site_label(self, sent, kept):
        assert P.strip_site_label(sent) == kept

    def test_saved_title(self, store):
        s = store.add_search("S", "rent")
        store.set_current_search(s["id"])
        pl, _ = store.add_place(title="Zillow-ish listing - Stadium View 2BR", address="5 Oak St")
        assert pl["title"] == "Stadium View 2BR"
        pl2, _ = store.add_place(title="Redfin: Cedar Court", address="6 Oak St")
        assert pl2["title"] == "Cedar Court"
        pl3, _ = store.add_place(title="Craigslist - Cozy 2 bed in Linden", address="7 Oak St")
        assert pl3["title"] == "Cozy 2 bed in Linden"

    def test_pasted_first_line_with_pipes(self):
        r = read("Zillow-ish listing - Stadium View | 1 Bed | Rent $1,350\nRent $1,350. 12 Oak St Austin TX")
        assert r["title"] == "Stadium View"


# ---------------------------------------------------------------- 5. "3300 Broadway Unit C, Grove City" keeps the street

class TestUnitWithoutStreetSuffix:
    def test_buyer_l10(self):
        r = read(fixture("r30-buyer-l10.txt"), buying=True)
        assert r["address"] == "3300 Broadway" and r["unit"] == "C" and r["city"] == "Grove City" and r["zip"] == "43123"

    @pytest.mark.parametrize("line,street,unit", [
        ("Condo $275,000\n3300 Broadway Unit C, Grove City, OH 43123", "3300 Broadway", "C"),
        ("Condo for rent $1,400\n3300 Broadway Apt C, Grove City, OH", "3300 Broadway", "C"),
        ("Condo $1,500\n450 Main Suite 2B, Dublin, OH 43017", "450 Main", "2B"),
        ("Townhome $1,500\n12 N High Unit A, Columbus, OH", "12 N High", "A"),
    ])
    def test_paste_variants(self, line, street, unit):
        r = read(line)
        assert r["address"] == street and r["unit"] == unit

    @pytest.mark.parametrize("line,street,unit,city", [
        ("3300 Broadway Unit C, Grove City", "3300 Broadway", "Unit C", "Grove City"),
        ("3300 Broadway Apt C, Grove City", "3300 Broadway", "Apt C", "Grove City"),
        ("450 Main St Unit C, Grove City", "450 Main St", "Unit C", "Grove City"),
        ("3300 Broadway #C, Grove City", "3300 Broadway", "#C", "Grove City"),
    ])
    def test_sent_address(self, line, street, unit, city):
        d = P.split_full_address(line)
        assert (d["address"], d["unit"], d["city"]) == (street, unit, city)

    def test_not_a_city(self):
        assert P.split_full_address("12 Main St Apt 4, Call Now")["address"] == "12 Main St Apt 4, Call Now"
        assert P.split_full_address("12 Main St, Apt 4") == {"address": "12 Main St", "unit": "Apt 4"}


# ---------------------------------------------------------------- 6. the raw title line is not repeated as a note

class TestTitleLineNotANote:
    def test_family_l6(self):
        r = read(fixture("r30-family-l6.txt"))
        assert r["title"] == "Spacious 3/2 Home" and r["pet_weight_limit"] == 40
        assert "SPACIOUS" not in notes_of(r) and "!!!" not in notes_of(r)

    @pytest.mark.parametrize("text,limit", [
        ("Sunny 2 bed - No dogs over 30 lbs\n12 Oak St, Dublin OH\nRent $1,500", 30),
        ("LOVELY 2BR HOME - NO PETS OVER 25 LBS!!\n12 Oak St, Dublin OH\nRent $1,500", 25),
        ("Lovely 2BR | Cats and dogs OK, no dogs over 35 lbs\n12 Oak St, Dublin OH\nRent $1,500", 35),
    ])
    def test_other_headlines(self, text, limit):
        r = read(text)
        assert r["pet_weight_limit"] == limit
        n = notes_of(r)
        assert "Sunny 2 bed" not in n and "LOVELY" not in n and "Lovely 2BR" not in n

    def test_a_pet_rule_with_more_in_it_is_still_a_note(self):
        r = read("Nice place - Pets: dogs under 40 lbs, no aggressive breeds\n12 Oak St, Dublin OH\nRent $1,500")
        assert "no aggressive breeds" in notes_of(r).lower() or r.get("pet_breed_note")


# ---------------------------------------------------------------- 7. a deposit range makes the cash "at least"

class TestDepositRangeCash:
    def _cash(self, text):
        pl = place_of(text)
        return pl["cost"]["cash_at_move_in"]

    def test_nontech_l13(self):
        pl = place_of(fixture("r30-nontech-l13.txt"))
        c = pl["cost"]["cash_at_move_in"]
        assert pl["deposit"] == 300 and c["deposit_up_to"] == 600
        cell = compare._cash_cell(pl)
        assert cell["text"].startswith("at least $") and "up to $600" in cell["text"] and cell["incomplete"] is True

    @pytest.mark.parametrize("text,up_to", [
        ("2 bed $1,400/mo. Security deposit: $300 to $600 based on credit.", 600),
        ("2 bed $1,400/mo. Deposit $500-$1,000 depending on credit score.", 1000),
        ("2 bed $1,400/mo. Deposit: $300 - $600. Pets ok.", 600),
    ])
    def test_other_wordings(self, text, up_to):
        c = self._cash(text)
        assert c["deposit_up_to"] == up_to
        low = {600: 300, 1000: 500}[up_to]
        assert c["total"] == 1400 + low

    @pytest.mark.parametrize("text", [
        "2 bed $1,400/mo. Deposit $700.",
        "2 bed $1,400/mo. Deposit $700. Pet deposit $300 to $500.",
    ])
    def test_a_plain_deposit_has_no_range(self, text):
        assert "deposit_up_to" not in self._cash(text) or self._cash(text)["deposit_up_to"] is None


# ---------------------------------------------------------------- 9. the guard: a link is never quoted, the low end of a range is not a silent drop

class TestGuardLeaks:
    def test_privacy_l5_quotes_no_link(self):
        r = read(fixture("r30-privacy-l5.txt"))
        n = notes_of(r)
        assert "evil.test" not in n and "http" not in n
        assert 'The listing mentions utilities ("Utilities estimate =HYPERLINK"), but I could not tell who pays.' in n

    @pytest.mark.parametrize("text", [
        "2 bed $1,500/mo. Laundry on site. Utilities https://evil.test/x then more text. Landlord pays water.",
        "2 bed $1,500/mo. Parking: see www.evil.test/page for details.",
    ])
    def test_no_link_in_any_quote(self, text):
        assert not re.search(r"https?:|www\.", " ".join(re.findall(r'"([^"]*)"', notes_of(read(text)))))

    def test_family_l7_range_low_end(self):
        import c20_guard as g
        assert g.unaccounted(fixture("r30-family-l7.txt"), True) == []
        assert g.quotes_clean(fixture("r30-privacy-l5.txt")) == []

    @pytest.mark.parametrize("text,est", [
        ("2 bed $1,500/mo. Tenant pays water ($60-$80/mo).", 80),
        ("2 bed $1,500/mo. Tenant pays electric and water, $70 to $90 a month.", 90),
    ])
    def test_other_ranges(self, text, est):
        import c20_guard as g
        assert read(text)["utilities_estimate"] == est
        assert g.unaccounted(text, True) == []
