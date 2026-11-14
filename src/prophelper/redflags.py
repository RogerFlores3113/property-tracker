"""A local, no-AI "things to check" pass over a place (keyword and price rules). Pure: no database, no web.

It never says a listing IS a scam. It lists signs worth a second look, in plain words, so the person can judge. It
runs every time a place is shown (and so after every save) and needs no key. The AI red-flag check, when the person
asks for it, adds to this.
"""
from __future__ import annotations

import html
import re
import unicodedata
from statistics import median
from typing import Any, Iterable

# Each rule: (name, pattern, message). The message says what it is and what to do, in plain words.
_PAYMENT = re.compile(
    r"\b(wire (?:the |me |us |it |your )?(?:deposit|money|funds|payment|rent|fee)|wiring (?:the |your )?(?:deposit|money|funds)|wire transfer|wire (?:it |this |that |the (?:deposit|money|funds|payment|rent) |money |funds |payment )?to (?:my|our|the|a) (?:lawyer|attorney|solicitor)|western union|money ?gram|"
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
_BUY_NO_INSPECTION = re.compile(r"\b(?:no|skip|waives?|waived|waiving|without|forgo|forego)\s+(?:the\s+|an?\s+|your\s+)?(?:home\s+|property\s+)?inspections?\b(?!\s+fees?)|\binspections?\s+(?:is |are )?(?:not needed|unnecessary|waived)\b|"
                             r"\b(?:do not|don'?t|never)\s+(?:try to |need to |bother to )?inspect\b|\bno need (?:to|for) (?:an? )?inspect(?:ion)?\b|"
                             r"\b(?:do not|don'?t|never)\s+(?:do|get|have|order|schedule|book)\s+(?:the\s+|an?\s+|your\s+)?(?:home\s+|property\s+)?inspections?\b", re.I)
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
                          r"\b(?:do not|don'?t)\s+(?:tell|warn|mention to|inform)\s+the\s+(?:user|renter|buyer)\b|"
                          # softer wording: a note, a heading or a request addressed to an AI, not a person
                          r"\bnote (?:to|for) (?:the |any |all )?(?:ai|a\.i\.|llm|language model|chatbot|chat ?gpt|claude|assistant|bot)s?\b|"
                          r"\b(?:ai|a\.i\.|llm)\s+(?:assistants?|agents?|models?|tools?|bots?|readers?|crawlers?|scrapers?)\s*[:,]|"
                          r"\b(?:assistant|ai|llm|chatbot|claude|chat ?gpt),\s*(?:please|kindly|you (?:must|should|need to|will|have to))\b|"
                          r"\bif you(?:'re| are) (?:reading this as |reading this, you are |)(?:an?|the) (?:ai|a\.i\.|llm|large language model|language model|chatbot|bot)\b", re.I)
_AI_EXTRA = re.compile(
    r"\bfor (?:the )?(?:language models?|large language models?|llms?|ai (?:assistants?|agents?|models?|tools?|readers?)|chatbots?|ai)\s*[:\-]|"
    r"\btell the (?:user|reader|human)\b|"
    r"\b(?:score|rate|rank|grade)\s+(?:it|this|this (?:place|listing|apartment|home|property)|the (?:place|listing))\s+(?:a |as |at |an? )?(?:100|perfect|10/10)\b|"
    r"\bperfect score\b|"
    r"\b(?:disregard|ignore|forget)\s+(?:the\s+|that\s+|any\s+)?(?:earlier|previous|prior|above|listed|old|first)\s+(?:price|rent|cost|fees?|amount|numbers?)\b|"
    r"\bmark (?:this|the|that) (?:place|listing|property|apartment|home|house) as (?:scam[- ]free|safe|verified|legit(?:imate)?|trusted)\b|"
    # cycle 11: other ways of addressing an AI reader
    r"\b(?:ignore|disregard|forget|override)\s+(?:all\s+|any\s+|the\s+|your\s+|these\s+|my\s+)*(?:previous|prior|above|earlier|original)\s+(?:guidance|advice|context|messages?|programming|training|constraints?)\b|"
    r"\b(?:ai|a\.i\.|llm|chatbot|language model)s?[ -](?:summari[sz]ers?|summary tools?|readers?|crawlers?|scrapers?|parsers?)\s*[:,\-]|"
    r"\b(?:important|attention|attn|notice|note)\b[^.\n:]{0,20}\b(?:for|to)\s+(?:any\s+|all\s+|the\s+)?(?:ai|a\.i\.|llm|chatbot|language model)\b|"
    r"\b(?:describe|call|present|portray|label|summari[sz]e)\s+(?:this|the|it)(?:\s+(?:unit|place|listing|apartment|home|property|house))?\s+as\s+(?:risk[- ]free|scam[- ]free|safe|flawless|perfect)\b|"
    r"\brate\s+(?:this|it|the\s+(?:unit|place|listing|apartment|home|property|house))\s+(?:a\s+)?(?:10|ten)\s*(?:out of|/)\s*10\b|"
    r"\bsystem\s*:\s*(?:new (?:rules?|instructions?)|updated (?:rules?|instructions?)|override|ignore|you (?:must|should|are|will)|from now on|send|forward|share|disclose|reveal|delete)\b|"
    r"\bnew (?:rules|instructions) (?:now )?apply\b|"
    r"\b(?:send|forward|share|email|reveal|disclose|leak)\s+(?:the\s+|your\s+)?(?:user|renter|buyer)(?:'s|s'|’s)?\s+(?:contact|contacts|data|notes|personal|private|address book|files?|messages?)\b|"
    r"\b(?:mention|say|state|report|tell|inform|remind|assure)\s+(?:to\s+)?(?:your|the)\s+(?:user|human|operator)s?\b", re.I)
# cycle 12: polite and indirect ways of steering an AI reader. Each needs an AI-only tell (what you were told, prior guidance,
# an AI addressee, a score, "when summarising"), so ordinary sentences like "Please forget about street parking" stay clear.
_AI_SOFT = (
    r"\b(?:ignore|disregard|forget)\s+(?:everything|all)(?:\s+of)?(?:\s+the)?\s+(?:above|before this)(?![- ]?ground)\b|"
    r"\b(?:ignore|disregard|forget)\s+the\s+above(?![- ]?ground)\b(?=\s*(?:$|[.,;:!?]|and\b|then\b|&))|"
    r"\b(?:forget|ignore|disregard|set aside|put aside|put away|drop|override)\s+(?:everything|what|all that)\s+you(?:'ve| have| were| had been|'d been)?\s*(?:been\s+)?(?:told|instructed|given|asked|said)\b|"
    r"\b(?:would you (?:kindly|please)|kindly|please)\s+(?:set|put|lay|cast) aside\s+(?:all\s+|any\s+|your\s+|the\s+)*(?:prior|previous|earlier|above|original|existing)\s+\w+|"
    r"\bdear\s+(?:ai|a\.i\.|llm|chatbot|bot|assistant|language model|claude|chat ?gpt|gpt)(?:\s+[a-z]+)?\s*,|"
    r"\b(?:pretend|act as if|imagine|assume|behave as if)\s+(?:that\s+)?you(?:'re| are| were)\s+(?:now\s+)?(?:the|a|an|my)\s+(?:landlord|owner|property manager|leasing agent|seller|agent|realtor|broker)\b|"
    r"\b(?:set|put|lay|cast) aside\s+(?:whatever|anything|everything|all|what)\b[^.\n]{0,30}\byou(?:'ve|\s+have|\s+were|\s+had\s+been|\s+are)?\s*(?:been\s+)?(?:given|told|instructed|asked)\b|"
    r"\b(?:do not|don'?t|never|stop)\s+(?:follow|following|obey|obeying|heed|apply|applying|listen to)\s+(?:all\s+|any\s+|the\s+|your\s+|these\s+|my\s+)*(?:previous|prior|above|earlier|original|existing)\s+(?:instructions?|prompts?|rules|guidelines|guidance|directions)\b|"
    r"\b(?:pretend|act as if|imagine|assume|suppose)\s+(?:that\s+)?(?:the\s+|your\s+|all\s+|any\s+)*(?:earlier|previous|prior|original|above|existing)\s+(?:rules|instructions?|guidelines|guidance|constraints|restrictions)\s+(?:do(?:es)?\s+not|don'?t|no longer|never)\s+apply\b|"
    r"\boverride\s*:\s*(?:rate|score|rank|mark|give|report|say|tell|recommend|approve|describe)\b|"
    r"\bhidden\s+(?:note|message|instruction|prompt)s?\s*[:\-]|"
    r"\bscores?\s+(?:for|of)\s+this\s+(?:listing|place|property|apartment|home|unit|house)\s+(?:should|must|needs? to|has to|will)\s+(?:be|equal|read)\s+\$?\d+|"
    r"\bfrom now on,?\s+(?:you\s+)?(?:answer|respond|reply|only|always|say|write|describe|recommend|rate|rank|score|speak)\b|"
    r"\b(?:kindly|please)\s+(?:rank|rate|score|list|put|place|recommend)\s+(?:this|it)(?:\s+(?:property|listing|place|unit|apartment|home|house|one))?\s+(?:as\s+)?(?:first|top|highest|#1|number one|the best|best)\b|"
    r"\b(?:please|kindly|you (?:should|must|need to))\s+(?:overlook|omit|skip|leave out|don'?t mention|do not mention|ignore|hide|play down|downplay)\s+(?:the\s+|any\s+|that\s+)?[^.\n]{0,40}\bwhen\s+(?:you\s+)?(?:summari[sz]\w*|reporting|writing (?:up )?(?:a |the )?summary|reviewing|rating|ranking)\b"
)
_AI_EXTRA = re.compile(_AI_EXTRA.pattern + "|" + _AI_SOFT, re.I)
_SYSTEM_IN_COMMENT = re.compile(r"\b(?:system|assistant|developer)\s*:", re.I)
# "Payment plan for the deposit" plus a request to talk only through messages is a soft sign worth a look.
_PAY_PLAN = re.compile(r"\bpayment plans?\b[^.\n]{0,30}\b(?:deposit|rent|move[- ]in)\b|\b(?:deposit|rent|move[- ]in)\b[^.\n]{0,30}\bpayment plans?\b", re.I)
_PM_ONLY = re.compile(r"\b(?:pm|dm) me\b|\bmessage me (?:on|via|through) (?:facebook|fb|messenger|instagram|whatsapp|telegram)(?: only)?\b|\b(?:facebook|fb|messenger) only\b", re.I)

_ZERO_WIDTH = re.compile("[\u200b-\u200f\u202a-\u202e\u2060-\u2064\u00ad\ufeff\u180e]")
# "i g n o r e": four or more single letters split by single spaces become one word (a wider gap marks the next word)
_SPACED = re.compile(r"(?<![^\W\d_])(?:[^\W\d_][ \t]){3,}[^\W\d_](?![^\W\d_])")
# "i.g.n.o.r.e" / "i-g-n-o-r-e" / "i_g_n_o_r_e": five or more letters (so "U.S." and "a.k.a." stay as they are) split by one separator
_SEP_SPACED = re.compile(r"(?<![^\W\d_])(?:[^\W\d_][.\-_]){4,}[^\W\d_]\.?(?![^\W\d_])")  # one trailing dot goes with the word
# "i. g. n. o. r. e.": every letter followed by a dot and a space (five or more letters)
_DOT_SPACED = re.compile(r"(?<![^\W\d_])(?:[^\W\d_]\.[ \t]){4,}[^\W\d_]\.?(?![^\W\d_])")
# a hostile key word split once or twice by spaces ("ig nore", "instruc tions", "pre vious"). Only long, uncommon words are rejoined, and only when
# the pieces start and end on word edges, so "for get" and "over ride" stay as they are.
_SPLIT_KEYWORDS = tuple(re.compile(r"(?<![^\W\d_])" + r"[ \t]*".join(w) + r"(?![^\W\d_])", re.I)
                        for w in ("ignore", "previous", "instructions", "instruction", "disregard", "guidance", "guidelines"))
# "i  g  n  o  r  e": letters split by the same run of two spaces
_WIDE_SPACED = re.compile(r"(?<![^\W\d_])(?:[^\W\d_] {2}){3,}[^\W\d_](?![^\W\d_])")
# a whole phrase written with dots between every letter ("i.g.n.o.r.e a.l.l p.r.e.v.i.o.u.s"): short words of three letters or more are
# joined too, but only next to a dotted word of five letters or more, so "U.S.A" or "a.k.a" on their own stay as they are
_DOT_WORD = r"[^\W\d_](?:[.\-_][^\W\d_]){2,}\.?"
_DOT_PHRASE = re.compile(r"(?<![^\W\d_.\-_])" + _DOT_WORD + r"(?:[ \t]+" + _DOT_WORD + r")+(?![^\W\d_])")
_COMMENT = re.compile(r"<!--(.*?)(?:-->|$)", re.S)
_LETTERS = re.compile(r"[^\W\d_]+")
# Cyrillic and Greek letters that look like Latin ones (a small hand-written map, no packages)
_CONFUSABLES = {
    **dict(zip("аеорсухіјѕԁһԛԝ", "aeopcyxijsdhqw")),
    **dict(zip("АВЕКМНОРСТХІЈЅУ", "ABEKMHOPCTXIJSY")),
    **dict(zip("οαεινρτυκχνμ", "oaeinptykxvm")),
    **dict(zip("ΑΒΕΖΗΙΚΜΝΟΡΤΧΥ", "ABEZHIKMNOPTXY")),
}
_LEET = {"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"}
_LEET_WORD = re.compile(r"(?=[A-Za-z0-9@$]*[A-Za-z])(?=[A-Za-z0-9@$]*[0-9@$])[A-Za-z0-9@$]{4,}")


def _fold_all(text: str) -> str:
    return "".join(_CONFUSABLES.get(ch, ch) for ch in text)


def _fold_mixed(text: str) -> str:
    """Fold look-alike letters only inside a word that also has Latin letters (Ignоre with a Cyrillic о). A word that is
    all Cyrillic or all Greek, like ordinary Russian or Greek listing text, is left alone."""
    def word(m: re.Match[str]) -> str:
        w = m.group(0)
        if any(c in _CONFUSABLES for c in w) and any("a" <= c.lower() <= "z" for c in w):
            return _fold_all(w)
        return w
    return _LETTERS.sub(word, text)


def _unleet(text: str) -> str:
    return _LEET_WORD.sub(lambda m: "".join(_LEET.get(c, c) for c in m.group(0)), text)


AI_QUOTE_MARK = ' It says: "'


def without_quote(flag: str) -> str:
    """A hint with the quoted listing line cut off. Used wherever a hint goes to an AI tool, so the listing's own
    words never reach it outside the untrusted fence."""
    return flag.split(AI_QUOTE_MARK, 1)[0]


_TAG = re.compile(r"</?[A-Za-z!?][^>]*(?:>|$)|<\s*/\s*[A-Za-z][^>]*(?:>|$)")


def _quote(snippet: str, limit: int = 160) -> str:
    """A short, plain copy of a line for a hint: whole tags removed, no markup characters, quotes softened, cut at a word
    boundary with '...'."""
    clean = _TAG.sub(" ", snippet)
    clean = re.sub(r"[\x00-\x1f\x7f<>`{}\\]", " ", clean).replace('"', "'")
    clean = " ".join(clean.split())
    if len(clean) <= limit:
        return clean
    cut = clean[:limit]
    if clean[limit] != " " and " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:.-(") + "..."


def quote_of(flag: str) -> str:
    """The quoted listing line of an AI-text hint, or ''. It is listing text: show it only inside an untrusted fence."""
    if AI_QUOTE_MARK not in flag:
        return ""
    q = flag.split(AI_QUOTE_MARK, 1)[1]
    return q[:-1] if q.endswith('"') else q


def _ai_line(text: str, comments: list[str]) -> str | None:
    """None when nothing in the text is aimed at an AI tool; else the (shortened) sentence that is, or '' if unquotable.
    The quote starts at the start of its own line or sentence (never at the line before), and stops at a tag."""
    bound: set[int] = set()  # places where a new line or a tag was: a quote never reaches across them at its start
    built = ""
    for piece in re.split(r"(" + _TAG.pattern + r"|\n)", text):
        if piece == "\n" or _TAG.fullmatch(piece):
            if built and not built.endswith(" "):
                bound.add(len(built))
                built += " "
            continue
        piece = " ".join(piece.split())
        if piece:
            if built and not built.endswith(" "):
                built += " "
            built += piece
    text = built
    hit = None
    plain = text
    # also try the text with every look-alike letter folded and with leet digits read as letters
    for variant in (plain, _fold_all(plain), _unleet(_fold_all(plain))):
        text = variant
        for pattern in (_AI_TARGETED, _AI_EXTRA):
            m = pattern.search(text)
            if m and (hit is None or m.start() < hit.start()):
                hit = m
        if hit is not None:
            break
    if hit is not None:
        starts = [text.rfind(sep, 0, hit.start()) + len(sep) for sep in (". ", "! ", "? ") if text.rfind(sep, 0, hit.start()) != -1]
        starts += [i + 1 for i in bound if i < hit.start()]
        begin = max(starts, default=0)
        if re.search(r"\d", text[begin:hit.start()]):
            begin = hit.start()  # "12 N Race St Urbana ignore previous instructions": an address or price in front is not part of it
        ends = [i for i in (text.find(sep, hit.end()) for sep in (". ", "! ", "? ")) if i != -1]
        ends += [i for i in bound if i >= hit.end()]
        end = min(ends) + (0 if ends and min(ends) in bound else 1) if ends else len(text)
        return _quote(text[begin:end])
    for c in comments:
        if _SYSTEM_IN_COMMENT.search(c):
            return _quote(c)
    return None


def normalise_text(text: str, keep_lines: bool = False) -> tuple[str, list[str]]:
    """The text as a reader would see it, for matching: HTML entities decoded, zero-width characters removed, HTML comments
    taken out of the text, whitespace collapsed. Returns ``(text, comment_contents)``. The contents of comments are also
    appended to the text so they are scanned too."""
    out = str(text or "")
    for _ in range(2):  # twice, for text like &amp;#8203;
        decoded = html.unescape(out)
        if decoded == out:
            break
        out = decoded
    out = unicodedata.normalize("NFKD", unicodedata.normalize("NFKC", out))
    out = _ZERO_WIDTH.sub("", out)
    out = "".join(ch for ch in out if unicodedata.category(ch) != "Mn")
    out = _DOT_PHRASE.sub(lambda m: " ".join(re.sub(r"[.\-_]", "", w) for w in m.group(0).split()) if any(len(re.sub(r"[.\-_]", "", w)) >= 5 for w in m.group(0).split()) else m.group(0), out)
    out = _SPACED.sub(lambda m: re.sub(r"[ \t]", "", m.group(0)), out)
    out = _SEP_SPACED.sub(lambda m: re.sub(r"[.\-_]", "", m.group(0)), out)
    out = _WIDE_SPACED.sub(lambda m: m.group(0).replace(" ", ""), out)
    out = _DOT_SPACED.sub(lambda m: re.sub(r"[.\s]", "", m.group(0)), out)
    for _split in _SPLIT_KEYWORDS:
        out = _split.sub(lambda m: re.sub(r"[ \t]", "", m.group(0)), out)
    out = _fold_mixed(out)
    comments = [" ".join(c.split()) for c in _COMMENT.findall(out)]
    out = _COMMENT.sub(" ", out)
    if keep_lines:  # new lines stay, so a hint can be cut at the start of its own line
        lines = [" ".join(line.split()) for line in " \n".join([out, *comments]).split("\n")]
        return "\n".join(line for line in lines if line), comments
    out = " ".join([out, *comments]).split()
    return " ".join(out), comments


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
    return normalise_text(" ".join(str(place.get(k) or "") for k in ("listing_text", "title", "notes", "ai_notes")))[0]


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
    text, comments = normalise_text(" ".join(str(place.get(k) or "") for k in ("listing_text", "title", "notes", "ai_notes")))
    flags: list[str] = []
    buy = mode == "buy"
    if buy:
        for pattern, message in _BUY_RULES:
            if pattern.search(text):
                flags.append(message)
    if not buy and _BUY_NO_INSPECTION.search(text):
        flags.append("It says you can't or needn't inspect the place. A real landlord lets you look closely before you pay or sign. "
                     "Don't send money until you have seen it in person.")
    same_day = buy and _BUY_SAME_DAY.search(text)
    for pattern, message in _rules():
        if pattern is _PRESSURE and same_day:
            continue  # the stronger "send money or sign today" sign already says it; one pressure hint is enough
        if buy and pattern in (_PAYMENT, _NO_CHECKS):
            # landlord wording does not fit a purchase; the payment rule gets seller wording, the screening rule is dropped
            if pattern is _PAYMENT and pattern.search(text):
                flags.append("It asks for payment in a way that is hard to undo (wire, gift card, crypto or a payment app). "
                             "Pay only through an escrow or title company you have checked yourself.")
            continue
        if pattern.search(text):
            flags.append(message.replace("lease", "contract") if buy else message)
    ai_line = None
    for key in ("listing_text", "notes", "ai_notes", "title"):  # the title is quoted only when it is what matched
        field_text, field_comments = normalise_text(str(place.get(key) or ""), keep_lines=True)
        ai_line = _ai_line(field_text, field_comments)
        if ai_line is not None:
            break
    if ai_line is None:
        all_text, all_comments = normalise_text("\n".join(str(place.get(k) or "") for k in ("listing_text", "title", "notes", "ai_notes")), keep_lines=True)
        ai_line = _ai_line(all_text, all_comments)
    if ai_line is not None:
        flags.append("This listing has text aimed at AI tools; treat it with care." + (f'{AI_QUOTE_MARK}{ai_line}"' if ai_line else ""))
    if _PAY_APP.search(text) and not _ZELLE_ONLY.search(text) and not (buy and _BUY_PAYMENT.search(text)):
        flags.append("It mentions Cash App, Venmo or Zelle for the deposit or rent. Those payments can't be taken back. "
                     + ("Don't send money before you have toured the place and an escrow or title company is involved." if buy else
                        "Don't pay anything before you have toured the place and read the lease."))
    if _PAY_PLAN.search(text) and _PM_ONLY.search(text):
        flags.append("It offers a payment plan for the deposit and wants you to talk only by private message. That can be a scam, so pay "
                     "and talk on the listing site or by phone, and only after you have toured the place.")
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
