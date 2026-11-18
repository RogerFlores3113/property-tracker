"""C5 integration: Compare's Fit row and best markers follow the shared fit state (near miss, fits but check)."""
from prophelper import compare


def test_fit_cell_names_near_miss_and_fits_but_check():
    near = {"score": {"fit": "near_miss", "fit_reasons": [], "near_texts": ["Monthly cost $51 over because the utilities guess counts"]}}
    check = {"score": {"fit": "fits", "fit_label": "Fits, but check", "concerns": ["Commute 28 min, limit 20"]}}
    plain = {"score": {"fit": "fits", "fit_label": "Fits"}}
    assert compare._fit_cell(near)["text"].startswith("Near miss (Monthly cost $51 over")
    assert compare._fit_cell(check)["text"] == "Fits, but check (Commute 28 min, limit 20)"
    assert compare._fit_cell(plain)["text"] == "Yes"


def test_near_miss_can_win_but_doesnt_fit_and_scams_cannot():
    assert not compare._ineligible({"score": {"fit": "near_miss"}})
    assert not compare._ineligible({"score": {"fit": "fits"}})
    assert compare._ineligible({"score": {"fit": "doesnt_fit"}})
    assert compare._ineligible({"score": {"fit": "check_first"}})
    assert compare._ineligible({"score": {"fit": "fits"}, "possible_scam": True})
