"""Cycle 24 G5 item 9: a wire to a place outside the country says so in the flag."""
import pytest

from prophelper.redflags import OVERSEAS_WIRE_NOTE, local_flags

BASE = "2 bed condo, $305,000. 1300 Grandview Ave #405, Columbus OH 43212. "


def pay_flags(text, mode):
    return [f for f in local_flags({"listing_text": BASE + text}, mode=mode) if "hard to undo" in f]


@pytest.mark.parametrize("sentence", [
    "Wire the earnest money $5,000 to my attorney's trust account in Lagos before the weekend.",
    "Wire the earnest money $5,000 to my lawyer in Nigeria.",
    "Please wire $5,000 earnest money to an overseas account.",
    "Send the earnest money by wire to a bank in Dubai.",
    "Wire the deposit to my attorney's account in London.",
])
def test_buy_wire_abroad_gets_overseas_wording(sentence):
    flags = pay_flags(sentence, "buy")
    assert len(flags) == 1 and flags[0].endswith(OVERSEAS_WIRE_NOTE)
    assert "outside the country" in flags[0]


@pytest.mark.parametrize("sentence", [
    "Wire the earnest money $5,000 to my attorney's trust account.",
    "Wire the earnest money $5,000 to the title company in Columbus.",
    "Send earnest money by Zelle.",
])
def test_buy_wire_at_home_unchanged(sentence):
    flags = pay_flags(sentence, "buy")
    assert len(flags) == 1 and OVERSEAS_WIRE_NOTE not in flags[0]


def test_foreign_word_in_another_sentence_does_not_count():
    flags = pay_flags("Wire the earnest money $5,000 to the title company. The owner grew up in London.", "buy")
    assert len(flags) == 1 and OVERSEAS_WIRE_NOTE not in flags[0]


def test_rent_wire_abroad_too():
    flags = [f for f in local_flags({"listing_text": "Nice flat. Wire the deposit to my attorney in Nigeria."}, mode="rent") if "hard to undo" in f]
    assert flags and flags[0].endswith(OVERSEAS_WIRE_NOTE)
