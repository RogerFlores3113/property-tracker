"""Pure modules: stages, money, commute, scoring, parsers, red flags."""
import pytest

from prophelper import commute, money, parsers, redflags, scoring, stages


# ---- stages
def test_stage_lists():
    assert stages.stages_for("rent")[0] == "Saved" and stages.stages_for("rent")[-1] == "Passed"
    assert "Under contract" in stages.stages_for("buy")
    assert stages.normalize_stage("rent", "tour booked") == "Tour booked"
    assert stages.normalize_stage("rent", "Closing") is None


def test_ai_can_only_move_forward_or_pass():
    assert stages.ai_can_move("rent", "Saved", "Toured")
    assert stages.ai_can_move("rent", "Toured", "Passed")
    assert not stages.ai_can_move("rent", "Toured", "Saved")
    assert not stages.ai_can_move("rent", "Passed", "Saved")


# ---- money
def test_rent_cost_adds_everything_and_spreads_one_time_fees():
    place = {"price": 1000, "utilities_estimate": 100, "parking_cost": 50, "pet_rent": 25, "other_monthly_fees": 25,
             "application_fee": 60, "move_in_fees": 120, "pet_fee": 0, "broker_fee": 0, "deposit": 1000, "lease_months": 12}
    cost = money.true_monthly_cost(place, "rent")
    assert cost["total"] == pytest.approx(1200 + 15)  # 1200 monthly + 180/12
    assert cost["missing"] == []
    assert cost["deposit"] == 1000  # shown, never spread


def test_rent_cost_names_missing_numbers():
    cost = money.true_monthly_cost({"price": 1500}, "rent")
    assert cost["total"] == 1500
    assert "utilities estimate" in " ".join(cost["missing"]).lower()


def test_rent_cost_without_price_is_unknown():
    assert money.true_monthly_cost({}, "rent")["total"] is None


def test_buy_cost_uses_mortgage_tax_insurance_hoa():
    cost = money.true_monthly_cost({"price": 300000, "property_tax": 3600, "insurance": 1200, "hoa": 100}, "buy",
                                   {"down_payment_pct": 20, "mortgage_rate": 6, "loan_years": 30})
    pi = money.monthly_payment(240000, 6, 30)
    assert pi == pytest.approx(1438.92, abs=0.05)
    assert cost["total"] == pytest.approx(pi + 300 + 100 + 100, abs=0.05)


def test_monthly_payment_zero_rate():
    assert money.monthly_payment(120000, 0, 10) == pytest.approx(1000)


# ---- commute
def test_haversine_and_estimates():
    d = commute.haversine_miles(40.1074, -88.2272, 40.1100, -88.2272)
    assert 0.15 < d < 0.22
    walk = commute.estimate_minutes(1.0, "walk")
    bike = commute.estimate_minutes(1.0, "bike")
    drive = commute.estimate_minutes(1.0, "drive")
    assert walk > bike > drive > 0


def test_resolve_prefers_your_number_and_labels_estimates():
    place, anchor = {"lat": 40.11, "lng": -88.22}, {"id": 1, "name": "Campus", "lat": 40.1074, "lng": -88.2272}
    est = commute.resolve(place, anchor, "bike", [])
    assert est["source"] == "estimate" and "estimate" in est["label"]
    mine = commute.resolve(place, anchor, "bike", [{"anchor_id": 1, "mode": "bike", "minutes": 17, "source": "you"}])
    assert mine["minutes"] == 17 and mine["source"] == "you"
    assert commute.resolve({"lat": None, "lng": None}, anchor, "bike", []) is None


# ---- scoring
def _criteria():
    return [{"id": 1, "kind": "price", "label": "", "weight": 30, "dealbreaker": 1, "target": {"max": 1600}},
            {"id": 2, "kind": "laundry", "label": "", "weight": 20, "dealbreaker": 0, "target": {"want": "in_unit"}},
            {"id": 3, "kind": "beds", "label": "", "weight": 10, "dealbreaker": 0, "target": {"min": 1}}]


def test_score_is_weighted_and_unknown_counts_half():
    place = {"price": 1500, "laundry": "in_unit", "beds": None}
    cost = money.true_monthly_cost(place, "rent")
    r = scoring.score_place(place, _criteria(), mode="rent", cost=cost)
    # price 1.0*30 + laundry 1.0*20 + beds unknown 0.5*10 = 55 of 60
    assert r["total"] == round(100 * 55 / 60)
    assert r["unknown"] and not r["fails_dealbreaker"]


def test_dealbreaker_fail_is_flagged():
    place = {"price": 2500, "laundry": "none", "beds": 1}
    r = scoring.score_place(place, _criteria(), mode="rent", cost=money.true_monthly_cost(place, "rent"))
    assert r["fails_dealbreaker"] and r["failed"]


def test_unknown_dealbreaker_is_not_a_fail():
    r = scoring.score_place({}, _criteria(), mode="rent", cost=money.true_monthly_cost({}, "rent"))
    assert not r["fails_dealbreaker"]
    assert r["needs_check"]


def test_no_criteria_has_no_score():
    assert scoring.score_place({"price": 1}, [], mode="rent")["total"] is None
    assert scoring.score_band(None) == "" and scoring.score_band(85) == "good" and scoring.score_band(10) == "low"


# ---- parsers
def test_parse_listing_text():
    out = parsers.parse_listing("Sunny 2 bedroom, 1.5 bath, 900 sq ft. $1,850 a month. In-unit washer/dryer. "
                                "Dishwasher. Cats ok. Deposit $1,850. Application fee $45. 123 Oak Street, Champaign, IL 61820",
                                "https://www.example.com/listing/1")
    assert out["price"] == 1850 and out["beds"] == 2 and out["baths"] == 1.5 and out["sqft"] == 900
    assert out["laundry"] == "in_unit" and out["deposit"] == 1850 and out["application_fee"] == 45
    assert "123 Oak" in out["address"]


def test_parse_listing_empty_is_empty():
    assert parsers.parse_listing("", "") == {}


# ---- red flags
def test_red_flags_for_a_scam():
    flags = redflags.local_flags({"listing_text": "Owner is out of the country, wire the deposit by gift card before viewing",
                                  "price": 450, "address": "Lake View"}, [1500, 1600, 1550])
    assert len(flags) >= 3


def test_red_flags_quiet_for_a_normal_listing():
    assert redflags.local_flags({"listing_text": "Nice 1 bed near campus.", "price": 1500, "address": "410 Maple Row Lane"},
                                [1500, 1600]) == []
