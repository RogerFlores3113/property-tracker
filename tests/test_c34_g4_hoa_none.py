"""Cycle 34, G4: "HOA none" next to the rent never makes an HOA note that names the rent (nontech l26)."""
from __future__ import annotations

import os

import pytest

from prophelper import parsers as P

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "panel")


def fixture(name: str) -> str:
    with open(os.path.join(FIX, name), encoding="utf-8") as fh:
        return fh.read()


def read(text: str) -> dict:
    return P.parse_listing(text, "")


def notes(r: dict) -> str:
    return r.get("found_in_listing") or ""


@pytest.mark.parametrize("line", [
    "Grandview Heights 2BR House. Rent $1,500 HOA none",
    "Grandview Heights 2BR House. Rent $1,500, HOA none.",
    "Grandview Heights 2BR House. Rent $1,500 | HOA n/a",
    "Grandview Heights 2BR House. Rent $1,500 (HOA none)",
    "Grandview Heights 2BR House. Rent $1,500\nHOA none\nPets ok",
    "Grandview Heights 2BR House. Rent $1,500; HOA fee none; pets ok",
    "Grandview Heights 2BR House. Rent $1,500 HOA: none",
    "Grandview Heights 2BR House. RENT $1,500 HOA NONE",
    "Grandview Heights 2BR House. Rent $1,500 HOA $0",
    "Grandview Heights 2BR House. Rent $1,500 - HOA N/A",
    "Grandview Heights 2BR House. Rent $1,500/mo HOA none",
])
def test_hoa_none_next_to_rent(line):
    r = read(line)
    assert r["price"] == 1500, notes(r)
    assert r["hoa"] == 0, notes(r)
    assert "HOA" not in notes(r) and "$1,500" not in notes(r), notes(r)


def test_nontech_l26_whole_listing():
    r = read(fixture("r33-nontech-l26.txt"))
    assert r["price"] == 1450 and r["hoa"] == 0
    assert r["deposit"] == 1500 and r["pet_deposit"] == 400 and r["utilities_estimate"] == 230
    n = notes(r)
    assert "HOA or condo fee" not in n and "passed on to the tenant" not in n, n
    assert "tenant pays it" not in n, n


@pytest.mark.parametrize("text,hoa", [
    ("Condo for rent. Rent $1,800/mo, $250 HOA paid by tenant.", 250),
    ("Condo for rent. Rent $1,800/mo. HOA $150/mo, tenant pays.", 150),
])
def test_real_hoa_still_read(text, hoa):
    r = read(text)
    assert r["price"] == 1800 and r["hoa"] == hoa, notes(r)


def test_hoa_info_missing_is_not_zero():
    r = read("Condo for rent. Rent $1,800/mo. HOA info not provided.")
    assert r["price"] == 1800 and not r.get("hoa"), notes(r)


def test_title_line_price_before_hoa_none():
    r = read("Grandview Heights 2BR House $1,500 HOA none")
    assert r["price"] == 1500 and r["hoa"] == 0, notes(r)
    assert "HOA or condo fee" not in notes(r)
