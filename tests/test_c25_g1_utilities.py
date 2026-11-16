"""Cycle 25 group G1: a figure covers only the utilities in its own item; slash groups; trash is $12/mo; paid by tenant;
"except" lists; counted figures are not "not counted"; HOA vs charge; gas and heat are one unknown."""
import pytest

from prophelper.parsers import parse_listing

HEAD = "Rent $1,800. "


def P(text):
    return parse_listing(text, "")


def notes(r):
    return r.get("found_in_listing") or ""


def pays(r):
    return {w.strip() for w in (r.get("tenant_pays") or "").split(",") if w.strip()}


def inc(r):
    return {w.strip() for w in (r.get("utilities_included") or "").split(",") if w.strip()}


# ---- 1. a flat or estimated figure covers only its own item
@pytest.mark.parametrize("text", [
    "Lakeview 3 Bed / 2 Bath | $3,200 reduced from $3,400 | 3500 N Broadway Chicago IL 60657 | Utilities not included - tenant pays gas, electric (Peoples Gas / ComEd), water flat $40/mo | Move in Jan 15 2027",
    HEAD + "Tenant pays gas, electric, water flat $40/mo.",
    HEAD + "Utilities: tenant pays gas, electric, water about $40 a month.",
    HEAD + "Tenant pays electric, gas (Nicor), water: flat $40/mo",
    HEAD + "Tenant pays:\n- gas\n- electric\n- water flat $40/mo",
])
def test_flat_figure_covers_only_water(text):
    r = P(text)
    assert r["utilities_estimate"] == 40
    assert pays(r) >= {"electric", "gas", "water"}
    assert "Gas, electric, water" not in notes(r) and "Gas and electric" not in notes(r)
    assert "Water is" in notes(r)


def test_sentence_form_still_right():
    r = P("Lakeview 3 Bed / 2 Bath | Rent: $3,200 | 3900 N Broadway Chicago IL 60657 | Tenant pays gas and electric. Water flat $40/mo. | Move in Jan 15 2027")
    assert r["price"] == 3200 and r["utilities_estimate"] == 40
    assert "Water is covered by a flat fee of $40/month" in notes(r)


@pytest.mark.parametrize("text", [
    "Half of a duplex. Rent 1450. Tenant pays electric and gas, water is split with the other half, usually around $30. Cat okay.",
    "$1,450 duplex. Tenant pays electric and gas, water is split with the neighbor, around $30. Cat okay.",
    "$1,450 duplex. Tenant pays electric and gas; water is split with the other half, usually around $30.",
    "$1,450 duplex.\nTenant pays electric and gas.\nWater is split with the other half, usually around $30.",
])
def test_split_water_estimate_is_for_water_only(text):
    r = P(text)
    assert r["utilities_estimate"] == 30
    assert "Electric, gas and water are about $30" not in notes(r)
    assert "Water is about $30" in notes(r)
    assert {"electric", "gas"} <= pays(r)


@pytest.mark.parametrize("text,amount", [
    (HEAD + "Tenant pays electric, gas and water about $140 a month.", 140),   # one list joined by and: the figure is the list's
    (HEAD + "Water, sewer, trash $65/month. Tenant pays electric and gas.", 65),  # a label list without payer words
    (HEAD + "Tenant pays electric $55, gas avg $70.", 125),
])
def test_lists_that_cover_the_whole_list_still_do(text, amount):
    assert P(text)["utilities_estimate"] == amount


def test_figure_in_its_own_brackets():
    r = P("Ranch. Rent: $2,325/mo. Resident pays gas, electric and water (about $55/mo water).")
    assert r["utilities_estimate"] == 55 and "Water is about $55" in notes(r)


# ---- 2. slash groups
@pytest.mark.parametrize("text", [
    HEAD + "Tenant pays PG&E, water/sewer/trash $95 flat monthly.",
    HEAD + "Tenant pays gas and electric, water/sewer/trash $95 flat monthly.",
    HEAD + "Tenant pays electric, gas. Water/sewer/trash flat $95/mo.",
])
def test_slash_group_figure_covers_the_group(text):
    r = P(text)
    assert r["utilities_estimate"] == 95
    assert "Water, sewer, trash are covered by a flat fee of $95/month" in notes(r)
    assert "for trash only" not in notes(r)
    assert {"water", "sewer", "trash"} <= pays(r)


def test_slash_group_flat_without_a_period_is_counted_once_in_fees():
    r = P(HEAD + "Tenant pays:\n* electric and gas\n* water/sewer/trash $95 flat")
    assert r["other_monthly_fees"] == 95 and "utilities_estimate" not in r
    assert pays(r) == {"electric", "gas"}


# ---- 3. "trash is $12/mo"
@pytest.mark.parametrize("text", [
    "ONE BEDROOM. $1,275/mo. Tenant covers electric (about $44) & gas (about $22). Water and sewer paid by landlord; trash is $12/mo.",
    HEAD + "Water and sewer paid by landlord. Trash costs $12 a month.",
    HEAD + "Tenant pays electric about $50. Water and sewer included. Trash is $12 per month.",
])
def test_trash_is_a_monthly_amount(text):
    r = P(text)
    assert r["other_monthly_fees"] == 12
    assert {"water", "sewer"} <= inc(r)
    assert "not counted anywhere" not in notes(r)


# ---- 4. paid by tenant, and a scope bracket
@pytest.mark.parametrize("text", [
    "Pilsen sunny 3BR 2BA $3,180 | Cable/internet: Spectrum, approx $65 per month paid by tenant | Water/sewer/trash (water and trash only) $60/mo flat | Gas heat $95 avg | Electric ~$55.50 | Lease 12 mo",
    "Pilsen 3BR $3,180. Internet (Spectrum), approx $65 per month paid by tenant. Water, trash $60/mo flat. Gas heat $95 avg. Electric ~$55.50.",
    "Pilsen 3BR $3,180\n- Internet: Comcast, $65/mo, paid by the tenant\n- Gas $95 avg\n- Electric ~$55.50\n",
])
def test_internet_paid_by_tenant_is_counted(text):
    r = P(text)
    assert "internet" in pays(r)
    assert "does not say you must pay it" not in notes(r)
    assert r["utilities_estimate"] >= 65 + 95 + 55.5


def test_only_scope_bracket_matches_tenant_pays():
    r = P("Pilsen 3BR $3,180 | Water/sewer/trash (water and trash only) $60/mo flat | Electric ~$55.50")
    assert r["utilities_estimate"] == 115.5
    assert "sewer" not in pays(r) and {"water", "trash", "electric"} <= pays(r)
    assert "sewer is left unknown" in notes(r)
    r2 = P(HEAD + "Water/sewer/trash (water only) $60/mo flat.")
    assert pays(r2) == {"water"} and r2["utilities_estimate"] == 60


# ---- 5. "all except" with a price
def test_all_except_leaves_the_two_out():
    r = P("4BR/2BA home - 880 Elm St, Belmont - $2,450 monthly. Utilities: tenant pays all except internet and electric (electric avg $40... actually, ask). Lease 12 months.")
    assert "utilities_estimate" not in r
    assert pays(r) == {"gas", "water", "sewer", "trash", "heat"}
    assert "internet and electric are left unknown" in notes(r)


@pytest.mark.parametrize("text", [
    HEAD + "Tenant pays all utilities except internet and electric (electric avg $40, ask).",
    HEAD + "Utilities: tenant pays everything except electric and internet (electric about $40?).",
])
def test_all_except_other_layouts(text):
    r = P(text)
    assert "utilities_estimate" not in r
    assert not ({"electric", "internet"} & pays(r))


# ---- 6. a figure counted anywhere is not "not counted yet"
@pytest.mark.parametrize("text", [
    "Updated listing. Was $2,500, now $2,350/mo. Tenant pays electric and gas, water $45 flat. Deposit: $2,350.",
    HEAD + "Tenant pays electric, gas and water. Water flat $45.",
    HEAD + "Tenant pays electric and gas.\n- Water $45 flat",
])
def test_counted_water_is_not_in_tenant_pays(text):
    r = P(text)
    counted = r.get("other_monthly_fees") == 45 or r.get("utilities_estimate") == 45
    assert counted
    assert "water" not in pays(r)
    assert pays(r) == {"electric", "gas"}


# ---- 7. HOA covers water and a water charge
@pytest.mark.parametrize("text", [
    "Willow Pointe 1BR - $1,455. Utilities: Tenant pays electric $40, gas $30. HOA covers water, and there is also a $25 water charge each month.",
    "1BR $1,455. Tenant pays electric $40, gas $30. HOA covers water. There is also a $25 water charge each month.",
    "1BR $1,455. Tenant pays electric $40, gas $30. HOA covers water, but a $25/mo water fee is charged.",
])
def test_hoa_water_and_water_charge_agree(text):
    r = P(text)
    assert "water" not in inc(r)
    assert "water" in pays(r)
    assert r["utilities_estimate"] == 70
    assert notes(r).count("HOA covers water") == 1
    assert "Water is not counted and not marked included" in notes(r)


# ---- 8. gas and heat are one unknown
@pytest.mark.parametrize("text", [
    "$1,375 - 2bd. Rent $1,375. Tenant pays all utilities (est. $140/mo electric, gas incl. in rent?). Trash pickup included.",
    "$1,375 - 2bd. Rent $1,375. Tenant pays all utilities (about $150/mo for electric; gas included in rent?).",
    "$1,375 - 2bd. Rent $1,375. Tenant pays all utilities, electric about $140. Is gas included?",
])
def test_gas_and_heat_one_unknown(text):
    r = P(text)
    assert "gas" in pays(r) and "heat" not in pays(r)


def test_all_utilities_without_gas_word_keeps_heat():
    r = P("3 bed $2,100/mo. Tenant pays all utilities. Approx $180/month")
    assert pays(r) == {"electric", "gas", "water", "sewer", "trash", "heat"}
