"""A local, no-AI "things to check" pass over a place (keyword and price rules). Pure: no database, no web.

It never says a listing IS a scam. It lists signs worth a second look, in plain words, so the person can judge. It
runs every time a place is shown (and so after every save) and needs no key. The AI red-flag check, when the person
asks for it, adds to this.
"""
from __future__ import annotations

import re
from statistics import median
from typing import Any, Iterable

# Each rule: (name, pattern, message). The message says what it is and what to do, in plain words.
_PAYMENT = re.compile(
    r"\b(wire (?:the |me |us |it |your )?(?:deposit|money|funds|payment|rent|fee)|wiring (?:the |your )?(?:deposit|money|funds)|wire transfer|western union|money ?gram|"
    r"gift ?cards?|itunes card|bitcoin|btc|crypto(?:currency)?|apple pay only|"
    r"send (?:the |your )?(?:deposit|money|payment))\b", re.I)
_ZELLE_ONLY = re.compile(r"\b(zelle|cash ?app|venmo|paypal friends)\s*(?:only|is the only|payments? only)\b|"
                         r"\bonly (?:accept|take)s? (?:payment (?:by|through|via) )?(?:zelle|cash ?app|venmo|crypto|bitcoin)\b|"
                         r"\b(?:pay|payment|deposit)\b[^.\n]{0,30}\b(?:by|through|via|with)\s+(?:zelle|cash ?app|venmo)\s+only\b", re.I)
_PAY_APP = re.compile(r"\b(?:cash ?app|venmo)\b|\bzelle\b[^.\n]{0,40}\b(?:deposit|rent|pay|payment|hold|secure)\b|\b(?:deposit|rent|pay|payment|hold|secure)\b[^.\n]{0,40}\bzelle\b", re.I)
_ABROAD = re.compile(r"\b(out of (?:the )?(?:country|town|state|us|u\.s\.)|owner (?:is )?(?:abroad|overseas|traveling|travelling)|"
                     r"(?:living|working|stationed|serving|based) (?:abroad|overseas|in (?:africa|europe|asia|london|canada|spain|italy|dubai))|"
                     r"(?:abroad|overseas|missionary|mission trip|deployed)|can'?t (?:show|meet|tour)|unable to (?:show|meet|tour)|"
                     r"(?:cannot|can not) (?:show|meet|tour))\b", re.I)
_PRESSURE = re.compile(r"\b(act (?:now|fast|today|quickly)|decide today|(?:must|need to|have to) (?:decide|respond|pay|reply|send) (?:today|now|immediately|asap)|"
                       r"won'?t last|many (?:people|applicants) (?:are )?(?:interested|waiting|inquiring)|first come|hurry|"
                       r"(?:today|tonight) only|(?:rent|pay|respond|reply|send)[^.\n]{0,20}\b(?:today|immediately|right away|asap) (?:to|or|before)|"
                       r"going fast|last (?:unit|chance)|several (?:people|others) (?:are )?(?:looking|interested))\b", re.I)
_BEFORE_SHOWING = re.compile(r"\b(deposit|payment|fee|money|funds)\b[^.\n]{0,70}\b(before|prior to|to (?:secure|hold|reserve|see|view|get the keys))\b[^.\n]{0,40}"
                             r"\b(show|showing|viewing|tour|see|keys?|visit|inspect)|"
                             r"\b(?:no|without|skip)\s+(?:a\s+)?(?:showings?|viewings?|tours?|walk-?throughs?)\b|"
                             r"\b(?:showings?|viewings?|tours?) (?:are |is )?(?:not (?:possible|available|offered)|after (?:payment|you pay|the deposit|you send))", re.I)
_KEYS_MAIL = re.compile(r"\b(keys? (?:will be |are |can be )?(?:mailed|shipped|sent|couriered|delivered)|(?:mail|ship|send)(?:ed|ing)? (?:you )?the keys|"
                        r"keys? (?:by|via) (?:mail|post|courier|ups|fedex))\b", re.I)
_PRIVATE_INFO = re.compile(r"\b(?:send|email|text|provide) (?:me |us )?(?:your |a )?(?:ssn|social security|photo of your (?:id|license)|copy of your (?:id|license|passport)|"
                           r"bank (?:login|details|account)|passport)\b[^.\n]{0,40}\b(?:before|first|to (?:see|view|hold|apply))", re.I)
_OFF_PLATFORM = re.compile(r"\b(?:contact|reach|text|message) (?:me|us)?\s*(?:only )?(?:on|via|through|by) (?:whatsapp|telegram|hangouts|google chat|signal)\b|"
                           r"\b(?:email|text|message) (?:only|me only)\b|\bno (?:phone )?calls?\b|\b(?:whatsapp|telegram)\b", re.I)
_ADDRESS_HIDDEN = re.compile(r"\b(?:address|location) (?:upon|on|by) (?:request|inquiry|approval|contact)|\b(?:message|contact|email|inquire) (?:me |us )?(?:for|to get) (?:the )?(?:exact )?address\b|"
                             r"\baddress (?:will be|is) (?:given|provided|shared|sent) (?:after|upon|once|when)\b", re.I)
_NO_CHECKS = re.compile(r"\bno (?:credit|background|reference|income|application)s? (?:check|verification|needed|required)", re.I)
PRICE_FLOOR_RATIO = 0.55  # under this share of the typical price in the same search is "far under"


def _rules() -> list[tuple[re.Pattern[str], str]]:
    return [
        (_PAYMENT, "It asks for payment in a way that is hard to undo (wire, gift card, crypto or a payment app). "
                   "Real landlords take a check or a normal online portal after you have seen the place."),
        (_ZELLE_ONLY, "It says payment is by Zelle, Cash App or Venmo only. Those can't be taken back, so don't pay anything before you have "
                      "toured the place and read the lease."),
        (_BEFORE_SHOWING, "It asks for a deposit or fee before you have seen the place, or says there are no showings. "
                          "Don't pay before a showing and a lease you have read."),
        (_ABROAD, "The owner is away or can't show the place. A scam often says the owner is out of the country."),
        (_PRESSURE, "It pressures you to decide today. A real place can wait for a tour."),
        (_KEYS_MAIL, "It says the keys will be mailed to you. Don't pay for a place you can't visit."),
        (_PRIVATE_INFO, "It asks for your ID, Social Security number or bank details before you have seen the place. Share those only on a real application, after a tour."),
        (_OFF_PLATFORM, "It wants to talk only by email, text or a chat app like WhatsApp or Telegram, and not by phone or in person. That is common in scams, so ask for a call or a visit."),
        (_ADDRESS_HIDDEN, "It hides the address until you write back. Ask for the exact address before you go anywhere or pay anything."),
        (_NO_CHECKS, "It promises no credit, background or reference check. Real landlords nearly always screen renters, so be careful."),
    ]


def _text(place: dict[str, Any]) -> str:
    return " ".join(str(place.get(k) or "") for k in ("listing_text", "title", "notes", "ai_notes"))


def is_serious(place: dict[str, Any], peer_prices: Iterable[float] = ()) -> bool:
    """The one rule for "possible scam": payment that can't be undone (wire, gift card, Zelle, Cash App, Venmo), a deposit
    before a showing, an owner who is abroad, keys by mail, or private info (like a Social Security number) asked for
    before a tour. Scoring, Today and the Board all use this. ``peer_prices`` is kept for callers that pass it."""
    text = _text(place)
    return any(p.search(text) for p in (_PAYMENT, _ZELLE_ONLY, _PAY_APP, _BEFORE_SHOWING, _ABROAD, _KEYS_MAIL, _PRIVATE_INFO))


def local_flags(place: dict[str, Any], peer_prices: Iterable[float] = ()) -> list[str]:
    """Plain-words signs to check on this place. ``peer_prices``: prices of the other places in the same search."""
    text = " ".join(str(place.get(k) or "") for k in ("listing_text", "title", "notes", "ai_notes"))
    flags: list[str] = []
    for pattern, message in _rules():
        if pattern.search(text):
            flags.append(message)
    if _PAY_APP.search(text) and not _ZELLE_ONLY.search(text):
        flags.append("It mentions Cash App, Venmo or Zelle for the deposit or rent. Those payments can't be taken back. "
                     "Don't pay anything before you have toured the place and read the lease.")
    price = place.get("price")
    peers = [float(p) for p in peer_prices if p]
    try:
        price_f = float(price) if price else 0.0
    except (TypeError, ValueError):
        price_f = 0.0
    if price_f and len(peers) >= 2:
        typical = median(peers)
        if typical and price_f < PRICE_FLOOR_RATIO * typical:
            flags.append(f"The price is far under the other places in this search (about ${typical:,.0f} is typical here). "
                         "A price that is too good to be true often is.")
    address = str(place.get("address") or "").strip()
    if address and not re.search(r"\d", address.split(",")[0]):
        flags.append("The address has no street number. Ask for the exact address before you go anywhere or pay anything.")
    if not address and not place.get("lat") and (place.get("listing_text") or place.get("url")):
        flags.append("There is no address yet. Ask for one before you go anywhere or pay anything.")
    return flags
