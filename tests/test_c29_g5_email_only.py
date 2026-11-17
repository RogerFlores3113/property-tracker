"""Cycle 29 G5 item 4: "E-mail me only" is the same contact-only flag as "email only"."""
from __future__ import annotations

import os

import pytest

from prophelper import redflags as rf

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "panel")
CONTACT = "It wants to talk only by email, text or a chat app"


def _hits(t):
    return [f for f in rf.local_flags({"listing_text": t, "address": "1 A St", "price": 1000}) if f.startswith(CONTACT)]


@pytest.mark.parametrize("t", [
    "Nice 2 bed. E-mail me only.", "Nice 2 bed. Email me only.", "Nice 2 bed. e-mail only", "Nice 2 bed. E mail me only please.",
    "Nice 2 bed. Contact me by e-mail only.", "Nice 2 bed. Reach us via email only.", "Nice 2 bed. Only by e-mail.", "Nice 2 bed. Text me only.",
    "Nice 2 bed.\nE-mail me only\nRent $900", "Nice 2 bed (e-mail only, no calls)", "Nice 2 bed. SMS only.",
])
def test_flagged_once(t):
    assert len(_hits(t)) == 1


@pytest.mark.parametrize("t", [
    "Nice 2 bed. Call or e-mail the office to tour.", "Nice 2 bed. Email leasing@example.com or text 555-0100 for a tour.",
    "Nice 2 bed. Tenants get e-mail alerts. Mail only arrives to the lobby box.", "Questions? Message the office. Only pets under 30 lb.",
])
def test_ordinary_contact_lines_not_flagged(t):
    assert _hits(t) == []


def test_reviewer_listing_l42():
    t = open(os.path.join(FIX, "r28-nontech-l42.txt"), encoding="utf-8").read()
    assert len(_hits(t)) == 1
