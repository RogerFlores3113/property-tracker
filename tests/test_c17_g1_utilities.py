"""Cycle 17 G1: utilities reader. The reviewers' whole saved listings (inlined) plus other wordings of the same thing.
Figures for different utilities add up, a quarterly bill counts a third a month, a conflict stays unknown, and a utility amount
is never called a monthly fee."""
from __future__ import annotations

import pytest

from prophelper.money import rent_cost
from prophelper.parsers import parse_listing


UIUC_L1 = "Campus Edge Lofts - 1 Bed / 1 Bath - $1,495/mo\n312 E Green St #12, Champaign, IL 61820\nBuilt 2022. 1 bedroom, 1 bath, 640 sq ft. Washer and dryer in unit, dishwasher, quartz counters. Heated garage space available $85/mo. No pets allowed.\nAvailable August 1, 2027. 12-month lease. Security deposit $500. Application fee $45.\nTenant pays: electric and gas, avg $65 electric, $40 gas. Water/sewer/trash included. High-speed internet required, $60/mo. Monthly amenity fee $20.\nBike to Siebel Center in 9 minutes."
ROOM_L18 = "Humboldt Park 3BR 2BA $2,900/mo. 1100 N California Ave Chicago IL 60622. Electric about $60. Gas avg $75. Water billed quarterly, about $150 per quarter, passed through to tenants. Lease 12 months starting January 15, 2027. Deposit $2,900."
ROOM_L14 = "Andersonville 3BR 2BA $3,000/mo. 5300 N Clark St Chicago IL 60640. Water billed quarterly, about $150 per quarter, passed through to tenants. Electric about $60. Gas heat, tenant pays, avg $75 winter. 1 year lease starting January 15, 2027. Security deposit $3,000. Dogs and cats allowed, 2 pet max, 50 lb limit. $250 per pet deposit, $25/mo per pet. Pet application fee $35."
ROOM_L17 = "Uptown 3BR 2BA $3,000/mo. 4700 N Broadway Chicago IL 60640. Electric about $60. Gas heat, tenant pays, avg $75 winter. Water included. Lease 12 months starting January 15, 2027. Deposit $3,000."
UIUC_L3 = "The Grove at Neil - Studio & 1BR from $1,540\n1BR/1BA, 700 sf, in-unit washer/dryer, DW, built 2020. Parking included, optional garage $100/mo. Utilities: Tenant pays $55 electric, avg $70 gas. Water billed quarterly, about $96 per quarter. Trash passed through at $12/mo.\nFlat $75/mo fee covers trash, pest and valet. Second vehicle $40/mo. Pet limit 25 lbs, can be waived. Pet deposit $400 ($150 non-refundable). Pet application fee $35.\nAddress: 505 S Neil St, Champaign IL 61820. Lease start 9/1/2027, 12 months."
ROOM_L7 = "Logan Square 3BR/2BA for rent $3,100/mo. 2847 N Milwaukee Ave, Chicago, IL 60647. Tenant pays everything but water. Landlord pays everything but electric. Free street parking. Quarterly water bill passed through, around $150. Renters insurance required $14/month. Lease through 1/31/2028."
FAM_L3 = "## Beech Court Home\nRent $2,290. 3 bd / 2 ba. Gas cooking, electric tenant. Heat is gas, tenant pays. Water billed quarterly about $90. Budget around $90/mo for both electric and gas. Pets: one cat or small dog, approval only; large dogs not permitted. Weight limit 25 lbs. Shared courtyard. Lease through 2/28/2028. $0 deposit with approved credit. Cleaning fee at move-in $125. Application fee $40 per adult. 12 min bike to Beech Elementary. Boston, MA, 02118"
NON_L3 = "2 bedroom townhome Olde Towne East $1,380\nHeat is gas, tenant pays. Gas cooking, electric tenant. Budget around $90/mo for both.\nWater billed quarterly about $120. Pets: cats ok, per-pet rent $20.\nDeposit $0 with approved credit. $75 application each adult. Flat $75/mo fee for amenities.\nFenced backyard. Driveway parking. 12 min bike to Short North. \nRenter's insurance required $12/month."
UIUC_L13 = "1 bed 1 bath 9 Elm St, Champaign IL. $1,400 monthly. Utilities: electric ~$65/mo, gas ~$40/mo, water/sewer/trash included."
UIUC_L9 = "LUXE 1x1 | $1,585/mo | The Hub-style living\nUnit 410, 33 N Neil St, Champaign. W/D in unit * DW * heated garage $120/mo (required for all residents) * Water, sewer, trash all included * Electric not included, budget about $75 * pets welcome (dogs 40 lb max, 2 pets max) * built 2024 * 11-month lease available, also 12-month * Amenity package $35/month (pool, gym) *"
ROOM_L8 = "Pilsen 3 bed 2 bath 1,299 per bedroom, total 3,897? no, $3,200 total. 1850 S Blue Island Ave, Chicago IL 60608. HEAT INCL. electric $60. Deposit one month. Lease 13 months from 15-Jan-2027."
NON_L9 = "Zillow: 2 bd, 1 ba, 1,010 sqft - $1,495/mo\nBrookside Flats, 310 W Third Ave, Columbus, OH 43201\nLease runs through 7/31/2027, beginning 8/1/2026... new tenants start 2/1/2027. Rent $1,495/mo. Security deposit $1,495 (refundable). Tenant pays $55 water/sewer plus avg $70 electric. Heat is gas, included. Pets: cats only, 2 max, $250 deposit, $35 monthly pet rent per cat. Parking included, 1 space. Mandatory internet $50 monthly. Washer/dryer in unit, DW. Application fee $35. Renters insurance required."
NON_L4 = "Great duplex in Clintonville!! Must see. 2 bed 1 bath $1,299 a month. Landlord pays all utilities, tenant electric only total $110. First month and last month rent due at signing plus $350 deposit. Passed-through water charged quarterly. Pets negotiable. Off street parking included. Fenced yard. Available now."
ROOM_L2 = "Ravenswood 3 bed 2 bath, 4600 N Damen Ave, Chicago IL 60640. Rent $3,180/mo. Tenant pays: electric $55, avg $70 gas. Water/sewer/trash billed back via RUBS, about $85 total. Flat $75/mo fee for amenities. Parking available $150/mo per car. Cats ok, no dogs. Lease starting 1/15/2027, 12 months."
FAM_L11 = "Cedar Point Estates - 3 bd 2 ba, 1,600 sqft, $2,380 mo. All utilities included, total $180 per month paid by tenant to landlord. Landlord pays all utilities. Dog friendly (60 lb limit can be waived with approval). Fence around back. $400 pet fee, $40/mo pet rent. Application fee: $55 per adult. First and last month's rent due at move-in. Pay by wire to our attorney to hold unit. Garage $75/mo."
ROOM_L13 = "Beverly 3 bed 2 bath single-family home for rent 10400 S Longwood Dr Chicago IL 60643 - $2,800 a month. Tenant responsible for all utilities (gas, electric, water, approx $320 per month combined). Lawn care and snow removal by tenant. 2-car garage included. First, last and security deposit required ($2,800 each). Pets considered, $400 non-refundable pet fee. Available 1/15/27, 24 month lease."

RENT = "2 bed 1 bath $1,500/month\n"


def read(text: str) -> dict:
    out = parse_listing(text)
    out.pop("source", None)
    return out


def note(out: dict) -> str:
    return str(out.get("found_in_listing") or "")


def fields(out: dict) -> tuple:
    return tuple(out.get(k) for k in ("utilities_estimate", "utilities_included", "tenant_pays"))


def cost(listing: str) -> dict:
    out = parse_listing(listing)
    place = dict(out)
    place["listing_text"] = listing
    place["reader_notes"] = out.get("found_in_listing", "")
    return rent_cost(place)


# ---- 1. a lead-in names two utilities, then each gets its own figure
def test_lead_in_then_each_figure_reviewer_listing():
    out = read(UIUC_L1)
    assert fields(out) == (105, "water, sewer, trash", "electric, gas")
    assert "Only the figure that covers more" not in note(out)


@pytest.mark.parametrize("line", [
    "Tenant pays: electric and gas, avg $65 electric, $40 gas.",
    "Tenant pays electric and gas: about $65 electric, about $40 gas.",
    "Tenants pay electric and gas, around $65 for electric and $40 for gas.",
    "Tenant pays: electric and gas (avg $65 electric, $40 gas).",
    "Utilities: gas and electric, avg. $40 gas, $65 electric.",
])
def test_lead_in_then_each_figure_other_wordings(line):
    out = read(RENT + line + " Water/sewer/trash included.")
    assert out["utilities_estimate"] == 105
    assert out["tenant_pays"] == "electric, gas"
    assert "Only the figure that covers more" not in note(out)


def test_same_utility_twice_still_keeps_the_higher():
    out = read(RENT + "Electric about $60. Electric avg $80.")
    assert out["utilities_estimate"] == 80
    assert "$60" in note(out)  # the dropped figure is quoted


# ---- 2. electric and gas are added to a quarterly water bill
def test_quarterly_water_with_electric_and_gas_humboldt():
    out = read(ROOM_L18)
    assert fields(out) == (185, None, "electric, gas, water")
    assert "$150 per quarter" in note(out) and "$60" in note(out) and "$75" in note(out)


def test_quarterly_water_with_electric_and_gas_andersonville():
    out = read(ROOM_L14)
    assert fields(out) == (185, None, "electric, gas, water")


def test_no_water_line_stays_135():
    out = read(ROOM_L17)
    assert out["utilities_estimate"] == 135
    assert out["tenant_pays"] == "electric, gas"


@pytest.mark.parametrize("line", [
    "Electric about $60. Gas about $75. Water is billed every quarter, around $150 a quarter, passed through to tenants.",
    "Electric $60/mo, gas $75/mo. Quarterly water, $150 per quarter, billed to tenants.",
    "Electric about $60. Gas avg $75. Water bill is quarterly, usually $150 a quarter, tenant pays.",
])
def test_quarterly_water_with_electric_and_gas_other_wordings(line):
    out = read(RENT + line)
    assert fields(out) == (185, None, "electric, gas, water")


# ---- 3. a quarterly water bill counts a third a month
def test_quarterly_water_per_quarter_grove():
    out = read(RENT + "Water billed quarterly, about $96 per quarter.")
    assert fields(out) == (32, None, "water")


def test_quarterly_water_passed_through_logan():
    out = read(ROOM_L7)
    assert out["utilities_estimate"] == 50
    assert out["tenant_pays"] == "electric, water"
    assert "not counted anywhere" not in note(out)


@pytest.mark.parametrize("line", [
    "Quarterly water bill passed through, around $150.",
    "Water bill is passed through every three months, about $150 per quarter.",
    "Tenant pays water, billed quarterly at $150 per quarter.",
])
def test_quarterly_water_other_wordings(line):
    assert read(RENT + line)["utilities_estimate"] == 50


def test_quarterly_water_with_trash_billed_back_and_estimates():
    out = read(UIUC_L3)
    # cycle 18: a $75 flat fee already covers trash, so the $12 trash charge is noted and not added (it was 169 with the $12)
    assert out["utilities_estimate"] == 157
    assert out["tenant_pays"] == "electric, gas, water, trash"
    assert "flat fee already covers trash" in out["found_in_listing"]


def test_quarterly_water_plus_budget_for_both_family_beech():
    out = read(FAM_L3)
    assert out["utilities_estimate"] == 120
    assert out["tenant_pays"] == "electric, gas, water, heat"
    assert cost(FAM_L3)["missing"] == []


def test_quarterly_water_plus_budget_for_both_r15():
    out = read(NON_L3)
    assert out["utilities_estimate"] == 130


@pytest.mark.parametrize("line", [
    "Budget around $90/mo for both electric and gas. Water billed quarterly about $90.",
    "Electric and gas about $90 combined. Water: billed quarterly, $90 per quarter.",
])
def test_quarterly_water_plus_both_other_wordings(line):
    assert read(RENT + line)["utilities_estimate"] == 120


# ---- 4. plain utility lines are read
def test_plain_utilities_line_with_included_tail():
    out = read(UIUC_L13)
    assert fields(out) == (105, "water, sewer, trash", "electric, gas")
    assert "not counted anywhere" not in note(out)


def test_bullet_separated_budget_hub():
    out = read(UIUC_L9)
    assert out["utilities_estimate"] == 75
    assert out["utilities_included"] == "water, sewer, trash"
    assert out["tenant_pays"] == "electric"
    assert "monthly fee" not in note(out)


def test_electric_without_about_pilsen():
    out = read(ROOM_L8)
    assert fields(out) == (60, "heat", "electric")
    assert "not counted anywhere" not in note(out)


@pytest.mark.parametrize("line,expect", [
    ("Utilities: electric $65/mo, gas $40/mo, water/sewer/trash included.", 105),
    ("Water & trash included, electric ~$70/month, gas ~$35/month.", 105),
    ("Water, sewer, trash all included * Electric not included, about $75/mo * no pets", 75),
    ("Water included. Electric not included, budget $80 a month. Pets ok.", 80),
    ("Heat included. Tenant pays electric $60/mo.", 60),
    ("Water included. Electric: $55. No smoking.", 55),
])
def test_plain_lines_other_wordings(line, expect):
    out = read(RENT + line)
    assert out["utilities_estimate"] == expect
    assert "monthly fee" not in note(out)


def test_a_utility_amount_nobody_placed_is_never_a_monthly_fee():
    # an amount the readers cannot place keeps its quote, but never says "a monthly fee"
    out = read(RENT + "Gas furnace service plan $18/mo, electric not included.")
    assert "monthly fee" not in note(out)


# ---- 5. water/sewer plus electric, heat is gas and included
def test_water_sewer_plus_electric_nontech9():
    out = read(NON_L9)
    assert out["utilities_estimate"] == 125
    assert out["utilities_included"] in ("gas, heat", "heat, gas")
    assert out["tenant_pays"] == "electric, water, sewer, internet"
    assert "Only the figure" not in note(out)
    r = cost(NON_L9)
    assert [l for l in r["lines"] if l["key"] == "utilities"][0]["note"].startswith("From the listing")


@pytest.mark.parametrize("line", [
    "Tenant pays $55 for water and sewer, plus about $70 for electric. Gas heat is included.",
    "Tenant pays water/sewer $55 and electric avg $70. Heat (gas) included.",
    "You pay $55 water/sewer and around $70 electric. Heat is gas and included in rent.",
])
def test_water_sewer_plus_electric_other_wordings(line):
    out = read(RENT + line)
    assert out["utilities_estimate"] == 125
    assert out["tenant_pays"] == "electric, water, sewer"
    assert "heat" in out["utilities_included"]
    assert "Only the figure" not in note(out)


# ---- 6. landlord pays all, tenant electric only
def test_landlord_pays_all_tenant_electric_only_nontech4():
    out = read(NON_L4)
    assert out["utilities_estimate"] == 110
    assert "electric" not in out["utilities_included"]
    assert out["tenant_pays"] == "electric, water"  # the quarterly water has no amount, so it stays something you pay
    assert "electric is included" not in note(out).lower()
    assert cost(NON_L4)["missing"] == ["water"]


@pytest.mark.parametrize("line,estimate", [
    ("Owner pays all utilities, tenant pays electric only, about $90.", 90),
    ("Landlord pays all utilities; tenant pays only electric, avg $85.", 85),
    ("Landlord pays all utilities (tenant pays electric only).", None),
])
def test_landlord_pays_all_tenant_electric_other_wordings(line, estimate):
    out = read(RENT + line)
    assert out.get("utilities_estimate") == estimate
    assert out["tenant_pays"] == "electric"
    assert out["utilities_included"] == "gas, water, sewer, trash, heat"


@pytest.mark.parametrize("line", [
    "Landlord pays everything but electric.",
    "Landlord pays all utilities except electric.",
    "Landlord covers everything except electric.",
    "All utilities included but electric.",
    "Utilities included except electric.",
])
def test_everything_but_electric_never_says_electric_included(line):
    out = read(RENT + line)
    assert "electric" not in (out.get("utilities_included") or "")
    assert out.get("utilities_included") != "all"
    assert out["tenant_pays"] == "electric"
    assert "electric is included" not in note(out).lower()


@pytest.mark.parametrize("line", ["Landlord pays everything but electric.", "All utilities included but electric.",
                                  "Landlord pays all utilities, tenant electric only total $110."])
def test_everything_but_electric_through_the_mcp_add_place_path(store, line):
    from mcp_util import call, server, text
    srv = server(store)
    call(srv, "create_search", name="Rent", mode="rent", area="Columbus", budget_max=1600)
    call(srv, "add_place", title="Duplex", address="9 Elm St", price=1300, listing_text=RENT + line)
    place = store.get_place(1)
    assert "electric" not in str(place.get("utilities_included") or "")
    assert place.get("tenant_pays") == "electric"
    assert "electric is included" not in (str(place.get("reader_notes") or "") + text(call(srv, "get_place", place_id=1))).lower()


# ---- 7. RUBS next to separate figures
def test_rubs_plus_electric_and_gas_ravenswood():
    out = read(ROOM_L2)
    assert out["utilities_estimate"] == 210
    assert out["tenant_pays"] == "electric, gas, water, sewer, trash"
    n = note(out)
    assert "$55" in n and "$70" in n and "$85" in n


@pytest.mark.parametrize("line", [
    "Tenant pays: electric $55, gas avg $70. Water, sewer and trash billed back via RUBS, about $85 total.",
    "Water/sewer/trash billed back via RUBS about $85. Electric about $55, gas about $70.",
])
def test_rubs_plus_electric_and_gas_other_wordings(line):
    assert read(RENT + line)["utilities_estimate"] == 210


def test_rubs_with_no_named_utilities_next_to_a_figure_stays_unknown_and_quotes_both():
    out = read(RENT + "Utilities billed back via RUBS, avg $120/mo. Electric about $55.")
    assert out.get("utilities_estimate") is None
    assert "$120" in note(out) and "$55" in note(out)


# ---- 8. "all included" next to a fee the tenant pays
def test_all_included_but_tenant_pays_a_total_cedar():
    out = read(FAM_L11)
    assert out.get("utilities_estimate") is None
    assert not out.get("utilities_included")
    assert "$180" in note(out) and "don't agree" in note(out)
    assert "monthly fee" not in note(out)


@pytest.mark.parametrize("line", [
    "Landlord pays all utilities. Tenant pays landlord $180/month for utilities.",
    "Utilities all included in rent; $180 a month for utilities billed to tenant by the landlord.",
    "All utilities included. $180 per month utility charge paid by the tenant.",
])
def test_all_included_but_tenant_pays_other_wordings(line):
    out = read(RENT + line)
    assert out.get("utilities_estimate") is None
    assert not out.get("utilities_included")
    assert "$180" in note(out) and "don't agree" in note(out)


# ---- 9. missing-list noise
def test_pilsen_heat_included_no_gas_no_internet_not_missing():
    place = {"price": 3200, "utilities_included": "heat", "tenant_pays": "electric, gas, internet", "listing_text": ROOM_L8}
    r = rent_cost(place)
    assert not any(w in " ".join(r["missing"]) + " ".join(r["uncounted"]) for w in ("gas", "internet"))


def test_gas_and_internet_stay_missing_when_the_listing_mentions_them():
    place = {"price": 3200, "utilities_included": "heat", "tenant_pays": "electric, gas, internet",
             "listing_text": ROOM_L8 + " Gas cooking range. Internet by Xfinity."}
    r = rent_cost(place)
    assert "gas" in " ".join(r["uncounted"]) and "internet" in " ".join(r["uncounted"])


def test_beverly_all_utilities_combined_figure_counts_for_all():
    out = read(ROOM_L13)
    assert out["utilities_estimate"] == 320
    assert cost(ROOM_L13)["missing"] == []


@pytest.mark.parametrize("line", [
    "Tenant pays all utilities (electric, gas and water), about $300 combined.",
    "Tenant is responsible for all utilities: gas, electric, water, roughly $300 a month total.",
])
def test_all_utilities_combined_other_wordings(line):
    listing = RENT + line
    assert read(listing)["utilities_estimate"] == 300
    assert cost(listing)["missing"] == []


@pytest.mark.parametrize("line", [
    "Tenants pay electric (Ameren) and gas; water/sewer/trash is a flat $45 per month.",
    "Tenants pay electric and gas. Water, sewer and trash are a flat fee of $45 a month.",
])
def test_flat_utility_fee_is_counted_not_called_a_fee(line):
    out = read(RENT + line)
    assert out["utilities_estimate"] == 45
    assert "monthly fee" not in note(out)
