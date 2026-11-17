"""Cycle 33 G6: buyer money. A one-time HOA charge is never the monthly HOA (item 1), closing parts keep their own labels (item 2), one-time buyer items
(first year of HOA dues up front, prepaid HOA, home warranty, recording) reach the cash to close, a split assessment is read, a closing date is read,
and a range saves the high figure."""
import os

import pytest

from prophelper import money
from prophelper.parsers import parse_listing

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "panel")
BASE = "Condo $300,000\n2 bed 2 bath, 1,000 sqft. "


def fixture(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


def read(text_):
    return parse_listing(text_, buying=True)


def full(text_):
    out = read(text_)
    place = {**out, "listing_text": text_}
    return out, place, money.cash_to_close(place)


def notes(out):
    return out.get("found_in_listing", "")


def parts(cash):
    return {p["label"]: p["amount"] for p in cash["parts"]}


# ---- 1. a transfer fee or a prepaid HOA is never the monthly HOA
@pytest.mark.parametrize("line", [
    "Maintenance fee $190/mo. Buyer pays $300 HOA transfer fee.",
    "Buyer pays $300 HOA transfer fee. Maintenance fee $190/mo.",
    "$300 HOA transfer fee paid by buyer; maintenance fee $190 per month",
    "HOA transfer fee: $300 (buyer). Monthly maintenance fee $190.",
    "Maintenance fee $190/mo\nBuyer pays $300 HOA transfer fee",
    "Buyer pays a $300 association transfer fee at closing, maintenance $190/month.",
    "Maintenance fee: $190/month | Buyer to pay $300 HOA transfer fee | Taxes $2,400/yr",
    "Maintenance fee $190 a month (buyer pays the $300 HOA transfer fee).",
])
def test_transfer_fee_is_not_the_monthly_hoa(line):
    out = read(BASE + line)
    assert out["hoa"] == 190
    assert "$300 a month" not in notes(out) and "HOA of $300" not in notes(out)


@pytest.mark.parametrize("line,hoa", [
    ("Prepaid HOA $630 (3 months). HOA $210 monthly.", 210),
    ("HOA $210 monthly. Prepaid HOA $630 (3 months).", 210),
    ("HOA dues $210/mo; prepaid HOA dues $630.", 210),
    ("$1,200 HOA dues up front. HOA $210/month.", 210),
    ("HOA $210/month. Buyer pays the first year of HOA dues up front, $2,520.", 210),
    ("HOA fee $210 per month plus a $300 transfer fee at closing.", 210),
    ("Association fee $210 monthly. Buyer also pays $450 HOA document fee.", 210),
])
def test_one_time_hoa_charge_beside_the_monthly_hoa(line, hoa):
    assert read(BASE + line)["hoa"] == hoa


@pytest.mark.parametrize("line", [
    "Buyer pays $300 HOA transfer fee.",
    "Prepaid HOA $630 (3 months).",
    "$1,200 HOA dues up front.",
    "HOA transfer fee: $300.",
])
def test_one_time_hoa_charge_alone_leaves_hoa_empty(line):
    assert read(BASE + line).get("hoa") in (None, "")


@pytest.mark.parametrize("line,hoa", [
    ("HOA $300/month.", 300),
    ("HOA $300 monthly. Close in 30 days.", 300),
    ("$300 HOA fee per month.", 300),
    ("Association dues: $300 a month.", 300),
])
def test_plain_monthly_hoa_is_still_read(line, hoa):
    assert read(BASE + line)["hoa"] == hoa


def test_l22_whole_listing():
    out = read(fixture("r32-buyer-l22.txt"))
    assert out["hoa"] == 190 and out["price"] == 229000 and out["property_tax"] == 1950 and out["insurance"] == 540 and out["seller_credit"] == 6870
    assert "$190" in notes(out) and "$300" in notes(out)


# ---- 2. each closing part keeps its own amount, in either order
L17_PARTS = [("lender origination", 1250), ("appraisal", 625), ("owner's title policy", 1400)]


def named(out_text):
    from prophelper.parsers import buyer_closing_items_stated
    return buyer_closing_items_stated(out_text)


@pytest.mark.parametrize("line", [
    "Buyer to pay $1,250 lender origination, $625 appraisal, and $1,400 for owner's title policy.",
    "Buyer to pay $1,250 lender origination, $625 appraisal and $1,400 for owner's title policy",
    "Buyer to pay lender origination $1,250, appraisal $625, and owner's title policy $1,400.",
    "Buyer pays $1,250 lender origination; $625 appraisal; $1,400 owner's title policy.",
    "Buyer to pay: $1,250 lender origination | $625 appraisal | $1,400 for owner's title policy",
    "Buyer to pay $1,250 lender origination, $625 appraisal, plus $1,400 for owner's title policy (seller keeps their own title costs).",
    "Buyer pays $1,250 lender origination\nBuyer pays $625 appraisal\nBuyer pays $1,400 for owner's title policy",
])
def test_closing_parts_keep_their_own_labels(line):
    assert named(BASE + line) == L17_PARTS


def test_closing_parts_labels_show_in_cash_to_close():
    out, place, cash = full(BASE + "Buyer to pay $1,250 lender origination, $625 appraisal, and $1,400 for owner's title policy.")
    label = [p["label"] for p in cash["parts"] if p["label"].startswith("Closing costs")][0]
    assert "$1,250 for lender origination" in label and "$625 for appraisal" in label and "$1,400 for owner's title policy" in label
    assert cash["total"] == 60000 + 9000
    assert "$625 for lender" not in label and "$1,400 for appraisal" not in label
    assert "$1,250" in notes(out) and "$3,275" in notes(out)


@pytest.mark.parametrize("line,expected", [
    ("Buyer pays lender fees $2,000; appraisal $550; title fees $1,100.", [("lender fees", 2000), ("appraisal", 550), ("title fees", 1100)]),
    ("Buyer pays title and recording about $1,900.", [("title and recording", 1900)]),
    ("Buyer's lender fees approx $3,100.", [("lender fees", 3100)]),
    ("Buyer pays survey of $450 plus $225 recording.", [("survey", 450), ("recording", 225)]),
])
def test_closing_part_older_layouts_still_read(line, expected):
    assert named(BASE + line) == expected


def test_closing_parts_negative_seller_pays_and_unlabelled_figures():
    assert named(BASE + "Seller pays $1,250 lender origination, $625 appraisal.") == []
    assert named(BASE + "Buyer to pay $1,250 for the pool table, $625 for the sofa.") == []


def test_l17_whole_listing():
    out, place, cash = full(fixture("r32-buyer-l17.txt"))
    assert out["price"] == 305000 and out["hoa"] == 395 and out["property_tax"] == 4100 and out["insurance"] == 780 and out["seller_credit"] == 7625
    assert out["special_assessment"] == 12000 and out["special_assessment_payer"] == "buyer"
    assert named(fixture("r32-buyer-l17.txt")) == L17_PARTS
    assert "$625 for lender" not in str(cash)


# ---- 3. an assessment split 50/50 over months is a monthly figure for the buyer's half
@pytest.mark.parametrize("line,share,months", [
    ("Assessment: $3,600 over 24 months, split 50/50 between buyer and seller.", 75, 24),
    ("Special assessment $3,600 over 24 months, split 50/50 between the buyer and seller.", 75, 24),
    ("Assessment of $3,600, payable over 24 months, split evenly between buyer and seller.", 75, 24),
    ("Assessment: $3,600 over 24 months. Split 50/50 between buyer and seller.", 75, 24),
    ("Special assessment (roof): $3,600 paid over 2 years, 50/50 buyer and seller.", 75, 24),
    ("Assessment $3,600 over 24 months (split 50/50 buyer/seller)", 75, 24),
    ("Assessment $4,800 in 24 monthly payments, buyer pays half.", 100, 24),
    ("Assessment: $3,600 over 24 months\nSplit 50/50 between buyer and seller", 75, 24),
])
def test_split_assessment_is_the_buyers_half_a_month(line, share, months):
    out, place, cash = full(BASE + "HOA $200/month. " + line)
    assert out["other_monthly_fees"] == share and out["hoa"] == 200
    assert out.get("special_assessment") in (None, "")
    assert not any("assessment" in p["label"].lower() for p in cash["parts"]) and not any("assessment" in x for x in cash["left_out"])
    assert f"{months} months" in notes(out) and "split 50/50" in notes(out) and "due at closing" not in notes(out)
    assert cash["total"] == 60000 + 9000


@pytest.mark.parametrize("line", [
    "Assessment: $3,600 over 24 months, split between unit owners.",
    "Assessment: $3,600 over 24 months. Buyer and seller to negotiate who pays.",
    "Special assessment $3,600 over 24 months, seller to pay.",
])
def test_split_assessment_negatives_are_not_a_buyer_half(line):
    out = read(BASE + "HOA $200/month. " + line)
    assert out.get("other_monthly_fees") in (None, "")


def test_l20_whole_listing_assessment_and_first_year_hoa():
    text_ = fixture("r32-buyer-l20.txt")
    out, place, cash = full(text_)
    assert out["other_monthly_fees"] == 75 and out["hoa"] == 340 and out["closing_costs"] == 8300 and out["seller_credit"] == 11160
    assert parts(cash)["One-time fee at closing (first year of HOA dues)"] == 1200
    assert "due at closing" not in notes(out)


# ---- 4/5. one-time buyer items reach the cash to close
@pytest.mark.parametrize("line,amount,label", [
    ("Buyer pays $1,200 for the first year of HOA dues up front.", 1200, "first year of HOA dues"),
    ("$1,200 first year HOA dues up front, buyer pays.", 1200, "first year of HOA dues"),
    ("Buyer to pay first year of HOA dues up front: $1,200.", 1200, "first year of HOA dues"),
    ("Prepaid HOA $630 (3 months).", 630, "prepaid HOA dues"),
    ("Prepaid HOA dues of $630 at closing.", 630, "prepaid HOA dues"),
    ("Closing: prepaid HOA dues $630 (3 months of dues)", 630, "prepaid HOA dues"),
    ("Home warranty $600 at closing.", 600, "home warranty"),
    ("Buyer pays $600 for a home warranty.", 600, "home warranty"),
    ("$600 home warranty due at closing.", 600, "home warranty"),
    ("Buyer pays: appraisal $525; home warranty $600 at closing.", 600, "home warranty"),
])
def test_one_time_item_in_cash_to_close(line, amount, label):
    out, place, cash = full(BASE + "HOA $200/month. " + line)
    got = [(l, a) for l, a in parts(cash).items() if l.startswith("One-time fee at closing")]
    assert got == [(f"One-time fee at closing ({label})", amount)]
    assert cash["total"] == 60000 + 9000 + amount
    assert out["hoa"] == 200 and not cash["left_out"]


@pytest.mark.parametrize("line", [
    "Seller provides a $600 home warranty at closing.",
    "Seller pays for a $600 home warranty.",
    "Home warranty $600 included, seller pays.",
])
def test_seller_warranty_is_not_a_buyer_cost(line):
    out, place, cash = full(BASE + "HOA $200/month. " + line)
    assert not [l for l in parts(cash) if l.startswith("One-time fee")]
    assert "$600" in notes(out) and "seller" in notes(out).lower()


def test_recording_and_survey_are_named_in_the_closing_line():
    out, place, cash = full(fixture("r32-buyer-l24.txt"))
    label = [p["label"] for p in cash["parts"] if p["label"].startswith("Closing costs")][0]
    assert "$450 for survey" in label and "$225 for recording" in label
    assert parts(cash)["One-time fee at closing (prepaid HOA dues)"] == 630
    assert out["hoa"] == 210 and out["seller_credit"] == 4000 and out["property_tax"] == 3300
    assert "$630" in notes(out)


def test_l27_whole_listing_home_warranty_and_assistance_program():
    out, place, cash = full(fixture("r32-buyer-l27.txt"))
    assert parts(cash)["One-time fee at closing (home warranty)"] == 600
    label = [p["label"] for p in cash["parts"] if p["label"].startswith("Closing costs")][0]
    assert "$1,500 for lender fee" in label and "$175 for recording" in label and "$525 for appraisal" in label
    assert "down payment assistance program" in notes(out) and "nothing is taken off" in notes(out)
    assert out["hoa"] == 360 and out["seller_credit"] == 6000


@pytest.mark.parametrize("line", [
    "Down payment assistance program available.",
    "DPA available for first-time buyers",
    "Down payment assistance available (ask lender)",
])
def test_down_payment_assistance_gets_a_note_and_no_cash_change(line):
    out, place, cash = full(BASE + "HOA $200/month. " + line)
    assert "assistance" in notes(out).lower() or "DPA" in notes(out)
    assert cash["total"] == 60000 + 9000 and not cash["left_out"]


def test_no_down_payment_assistance_is_not_an_offer():
    assert "assistance" not in notes(read(BASE + "HOA $200/month. No down payment assistance."))


# ---- 6. a closing date in the listing is the place's closing date
from prophelper.parsers import listing_closing_date  # noqa: E402


@pytest.mark.parametrize("line,day", [
    ("Closing date Feb 20, 2027.", "2027-02-20"),
    ("Close by March 1, 2027.", "2027-03-01"),
    ("Closing date: February 20th, 2027", "2027-02-20"),
    ("closing on 3/15/2027", "2027-03-15"),
    ("Closing: 2027-02-20 (flexible)", "2027-02-20"),
    ("Seller wants to close no later than Nov 3rd, 2026!", "2026-11-03"),
    ("Closing is set for 20 Feb 2027, with a quick close possible.", "2027-02-20"),
    ("Expected closing date - Sept 9, 2027", "2027-09-09"),
])
def test_closing_date_is_read(line, day):
    assert listing_closing_date(BASE + line)[0] == day
    assert "closing date" in notes(read(BASE + line)).lower()


@pytest.mark.parametrize("line", [
    "Closing in 45 days.",
    "Closing costs Feb 20, 2027 estimate.",
    "Can you close by March 1, 2027?",
    "Closing cost help available through March 1, 2027.",
    "Closing attorney will call Feb 20, 2027.",
])
def test_closing_date_negatives(line):
    assert listing_closing_date(BASE + line)[0] == ""


def test_closing_date_without_a_year_or_with_two_dates_saves_none():
    assert listing_closing_date(BASE + "Close by March 1.")[0] == ""
    assert "no year" in notes(read(BASE + "Close by March 1."))
    assert listing_closing_date(BASE + "Closing date Feb 20, 2027. Closing date Feb 27, 2027.")[0] == ""
    assert "two different closing dates" in notes(read(BASE + "Closing date Feb 20, 2027. Closing date Feb 27, 2027."))


@pytest.mark.parametrize("name,day", [("r32-buyer-l24.txt", "2027-02-20"), ("r32-buyer-l27.txt", "2027-03-01")])
def test_closing_date_whole_listings(name, day):
    assert listing_closing_date(fixture(name))[0] == day


def test_new_place_gets_the_closing_date_from_the_listing(store):
    s = store.add_search("Buy", "buy", target_close="2027-04-30")
    p, created = store.add_place(search_id=s["id"], title="Hilliard", address="3980 Main St", price=265000, listing_text=fixture("r32-buyer-l24.txt"))
    assert created
    dates = [(d["kind"], d["date"]) for d in store.list_place_dates(p["id"])]
    assert dates == [("closing", "2027-02-20")]


def test_closing_date_not_saved_for_a_rental_or_without_a_date(store):
    r = store.add_search("Rent", "rent")
    p, _ = store.add_place(search_id=r["id"], title="A", address="1 A St", price=1200, listing_text="Closing date Feb 20, 2027.")
    assert store.list_place_dates(p["id"]) == []
    b = store.add_search("Buy", "buy")
    p2, _ = store.add_place(search_id=b["id"], title="B", address="2 A St", price=250000, listing_text="Closing in 45 days.")
    assert store.list_place_dates(p2["id"]) == []


def test_closing_date_through_the_add_page_and_the_tool(store):
    from conftest import local_client
    from mcp_util import call, server
    s = store.add_search("Buy", "buy", target_close="2027-04-30")
    client = local_client(store)
    r = client.post("/add/save", data={"title": "Bexley", "address": "2100 E Main St", "price": "312000", "search_id": str(s["id"]), "listing_text": fixture("r32-buyer-l27.txt")}, follow_redirects=False)
    assert r.status_code in (302, 303)
    pid = [p for p in store.list_places(search_id=s["id"])][0]["id"]
    assert [(d["kind"], d["date"]) for d in store.list_place_dates(pid)] == [("closing", "2027-03-01")]
    call(server(store), "add_place", title="Hilliard", address="3980 Main St", listing_text=fixture("r32-buyer-l24.txt"), search_id=s["id"])
    other = [p for p in store.list_places(search_id=s["id"]) if p["title"] == "Hilliard"][0]
    assert [(d["kind"], d["date"]) for d in store.list_place_dates(other["id"])] == [("closing", "2027-02-20")]
