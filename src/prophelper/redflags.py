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
# Buyer-side signs (earnest money, inspection pressure, cash only, same-day pressure).
_BUY_PAYMENT = re.compile(
    r"\b(?:earnest money|good faith deposit|deposit|down ?payment|closing (?:costs?|funds))\b[^.\n]{0,80}\b(?:zelle|venmo|cash ?app|gift ?cards?|crypto(?:currency)?|bitcoin|btc|wire(?:d)?|western union)\b|"
    r"\b(?:zelle|venmo|cash ?app|gift ?cards?|crypto(?:currency)?|bitcoin|btc|wire(?:d)?|western union)\b[^.\n]{0,80}\b(?:earnest money|good faith deposit|deposit|down ?payment)\b|"
    r"\bwire\b[^.\n]{0,60}\b(?:escrow|earnest)\b", re.I)
_BUY_NO_INSPECTION = re.compile(r"\b(?:no|skip|waives?|waived|waiving|without|forgo|forego)\s+(?:the\s+|an?\s+|your\s+)?(?:home\s+|property\s+)?inspections?\b|\binspections?\s+(?:is |are )?(?:not needed|unnecessary|waived)\b", re.I)
_BUY_AS_IS = re.compile(r"\bas[- ]is\b", re.I)
_BUY_CASH_ONLY = re.compile(r"\bcash[ -]only\b|\bcash (?:buyers?|offers?) only\b|\bonly (?:accept|take)s? cash\b", re.I)
_BUY_SAME_DAY = re.compile(r"\b(?:today|tonight|same[- ]day|within 24 hours|right away|immediately|asap)\b[^.\n]{0,40}\b(?:wire|send|pay|deposit|earnest|close|sign|offer)|"
                           r"\b(?:wire|send|pay|deposit|earnest|sign|offer)\b[^.\n]{0,40}\b(?:today|tonight|same[- ]day|within 24 hours|right away|immediately|asap)\b", re.I)
# Text written to steer an AI tool, not a person.
_AI_TARGETED = re.compile(r"\b(?:ignore|disregard|forget)\s+(?:all\s+|any\s+|the\s+|your\s+)?(?:previous|prior|above|earlier)\s+(?:instructions?|prompts?|rules?)\b|"
                          r"\b(?:delete|remove|erase|wipe)\s+(?:all|every|my)\s+(?:the\s+)?(?:places?|listings?|data|notes|searches)\b|"
                          r"\b(?:system prompt|you are now|new instructions?:|as an ai (?:assistant|agent)|assistant,? (?:please |you must ))|"
                          r"\b(?:ignore|disregard|forget|override|bypass)\s+(?:all\s+|any\s+|the\s+|your\s+|these\s+|my\s+)*(?:previous\s+|prior\s+|above\s+|earlier\s+|original\s+|current\s+)?(?:instructions?|prompts?|rules|guidelines|directions)\b|"
                          r"\b(?:ai|a\.i\.|llm|claude|chatgpt|gpt|language model|chatbot|bot|assistant)\s*(?:assistant|agent|model|tool)?\s*[:,]\s*(?:please\s+)?(?:tell|say|report|respond|reply|write|mark|move|delete|send|approve|rate|call|ignore|forget|you (?:must|should|will|are))\b|"
                          r"\b(?:tell|inform|assure|convince|say to)\s+the\s+(?:user|renter|reader|buyer|person)\s+(?:that\s+)?(?:this|it|the (?:place|listing))\s+(?:is|looks|seems)\s+(?:safe|legit|legitimate|real|fine|trustworthy|verified)\b|"
                          r"\b(?:move|mark|set|change|put|send)\s+(?:every|all|each)\s+(?:the\s+)?(?:place|listing|apartment|home)s?\s+(?:to|as)\b|"
                          r"\b(?:if you are|as|when you are)\s+an?\s+(?:ai|llm|language model|chatbot|assistant that is reading)\b|"
                          r"\b(?:do not|don'?t)\s+(?:tell|warn|mention to|inform)\s+the\s+(?:user|renter|buyer)\b", re.I)
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
    return any(p.search(text) for p in (_PAYMENT, _ZELLE_ONLY, _PAY_APP, _BEFORE_SHOWING, _ABROAD, _KEYS_MAIL, _PRIVATE_INFO, _BUY_PAYMENT, _BUY_NO_INSPECTION))


_BUY_RULES = [
    (_BUY_PAYMENT, "It asks for earnest money or a deposit by wire, Zelle, Venmo, Cash App, gift card or crypto, to a person or an account you can't verify. "
                   "Earnest money normally goes to an escrow or title company you have checked yourself, through its published phone number."),
    (_BUY_NO_INSPECTION, "It pushes you to skip or waive the inspection. A real seller lets you inspect. Get a home inspection before you commit."),
    (_BUY_AS_IS, "It is sold as-is, so the seller may not fix anything that turns up. Get an inspection and ask what the seller will repair before you commit."),
    (_BUY_CASH_ONLY, "It says cash only. Real sales close through an escrow or title company, so ask how the closing will be handled."),
    (_BUY_SAME_DAY, "It pressures you to send money or sign today. A real sale can wait while an escrow or title company and your agent check it."),
]


def local_flags(place: dict[str, Any], peer_prices: Iterable[float] = (), mode: str = "rent") -> list[str]:
    """Plain-words signs to check on this place. ``peer_prices``: prices of the other places in the same search."""
    text = " ".join(str(place.get(k) or "") for k in ("listing_text", "title", "notes", "ai_notes"))
    flags: list[str] = []
    buy = mode == "buy"
    if buy:
        for pattern, message in _BUY_RULES:
            if pattern.search(text):
                flags.append(message)
    for pattern, message in _rules():
        if buy and pattern in (_PAYMENT, _NO_CHECKS):
            # landlord wording does not fit a purchase; the payment rule gets seller wording, the screening rule is dropped
            if pattern is _PAYMENT and pattern.search(text):
                flags.append("It asks for payment in a way that is hard to undo (wire, gift card, crypto or a payment app). "
                             "Pay only through an escrow or title company you have checked yourself.")
            continue
        if pattern.search(text):
            flags.append(message.replace("lease", "contract") if buy else message)
    if _AI_TARGETED.search(text):
        flags.append("This listing has text aimed at AI tools; treat it with care.")
    if _PAY_APP.search(text) and not _ZELLE_ONLY.search(text) and not (buy and _BUY_PAYMENT.search(text)):
        flags.append("It mentions Cash App, Venmo or Zelle for the deposit or rent. Those payments can't be taken back. "
                     + ("Don't send money before you have toured the place and an escrow or title company is involved." if buy else
                        "Don't pay anything before you have toured the place and read the lease."))
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
