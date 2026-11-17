"""True monthly cost for rent and for buying (DESIGN section 5). Pure: no database, no web.

Rent: price + utilities_estimate + parking_cost + pet_rent + other_monthly_fees + hoa (a tenant-paid HOA, unless it is in the rent)
      + (application_fee + move_in_fees + broker_fee + pet_fee) / lease_months (12 when empty).
The deposit is shown but not spread (it comes back).
Buy:  monthly principal and interest + PMI (when the down payment is under 20%) + property_tax / 12 + insurance / 12 + hoa.
      An estimate, not advice. ``cash_to_close`` is kept apart from the monthly cost: down payment + closing costs
      (the number entered, else an estimate of closing_cost_pct of the price) + a special assessment the buyer pays
      (treated as one amount, not billed monthly).

Each function returns ``{"total", "lines", "missing", "notes", ...}``. ``total`` is None when the main price is
missing. ``lines`` is ``[{"key", "label", "amount", "note"}]`` in display order, ``missing`` names the numbers that
are not filled in (so the page can say "add the utilities estimate"). ``uncounted`` names the costs left out of the
total in short words ("insurance", "utilities") and ``headline`` is the one line to show next to the total, such as
"$2,414/mo, insurance not counted yet". ``per_person`` is the total split over ``people`` (only when people > 1).
"""
from __future__ import annotations

import re
from typing import Any

DEFAULT_LEASE_MONTHS = 12
DEFAULT_BUY = {"down_payment_pct": 20.0, "mortgage_rate": 6.5, "loan_years": 30, "pmi_rate_pct": 0.5,
               "closing_cost_pct": 3.0}
PMI_BELOW_PCT = 20.0  # mortgage insurance is estimated when the down payment is under this share of the price
PRIVATE_PARKING = ("garage", "covered", "lot")


def num(value: Any) -> float | None:
    """A number from a stored value, or None for blank or not a number."""
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out else None  # NaN is not a number


def _r(x: float) -> float:
    return round(x + 1e-9, 2)


def _line(key: str, label: str, amount: float | None, note: str = "") -> dict[str, Any]:
    return {"key": key, "label": label, "amount": None if amount is None else _r(amount), "note": note}


def utilities_covered(place: dict[str, Any]) -> bool:
    text = str(place.get("utilities_included") or "").lower()
    return text.strip() == "all" or any(w in text for w in ("all utilities", "everything", "all included", "all inclusive", "all-inclusive"))


NO_PETS_NOTE = "not counted: you have no pets"
NOTHING_WORDS = ("none", "nothing", "n/a", "na")


def adult_count(adults: Any = None, people: Any = 1) -> int:
    """How many adults sign the lease: ``adults`` when it is 1 or more, else ``people``, else 1."""
    for v in (adults, people):
        n = num(v)
        if n is not None and n >= 1:
            return int(n)
    return 1


def application_fee_total(place: dict[str, Any], adults: int = 1) -> float:
    """The application fee for everyone who applies: the fee times the adults when it is charged per adult."""
    fee = num(place.get("application_fee")) or 0
    return fee * adults if fee and num(place.get("application_fee_per_adult")) and adults > 1 else fee


def tenant_pays_list(place: dict[str, Any]) -> list[str]:
    """The utilities the tenant pays, from ``tenant_pays`` (a comma list such as "gas, electric"). Empty when unset."""
    raw = str(place.get("tenant_pays") or "")
    return [w.strip().lower() for w in raw.replace(";", ",").replace(" and ", ",").split(",") if w.strip()]


def _cost_pays(place: dict[str, Any]) -> list[str]:
    """What the tenant pays, as the cost uses it. When the saved listing text is there, a utility the listing never mentions is not
    listed as missing: "internet" when no internet, wifi or cable word is in the text, and "gas" when the heat is included and
    the listing never talks about gas (a gas bill that is only for the heat is part of the heat)."""
    pays = tenant_pays_list(place)
    text = str(place.get("listing_text") or "")
    if not text or not pays:
        return pays
    if "internet" in pays and not re.search(r"\b(?:internet|wi-?fi|broadband|cable|fiber|fibre|isp)\b", text, re.I):
        pays = [w for w in pays if w != "internet"]
    inc = [w.strip().lower() for w in str(place.get("utilities_included") or "").split(",") if w.strip()]
    if "gas" in pays and ("heat" in inc or "heating" in inc) and not re.search(r"\bgas\b", re.sub(r"\bgas[ \t]+(?:heat(?:ing)?|furnace)\b|\bheat(?:ing)?[ \t]*(?:is|:|\()?[ \t]*(?:by[ \t]+)?gas\b", " ", text, flags=re.I), re.I):
        pays = [w for w in pays if w != "gas"]
    return pays


def _internet_counted(place: dict[str, Any]) -> bool:
    """True when the saved notes say the internet is counted in other monthly fees and that field holds an amount."""
    fees = num(place.get("other_monthly_fees"))
    return bool(fees) and any(re.search(r"\binternet\b", n, re.I) and re.search(r"\bcounted\b[^.]*other monthly fees", n, re.I)
                             and not re.search(r"not counted", n, re.I) for n in note_units(place.get("reader_notes")))


def _added_by_claude(place: dict[str, Any], util: float) -> bool:
    """True when the AI notes say Claude added this utilities amount itself (no source sent), so it is not called a guess."""
    for m in re.finditer(r"Utilities estimate \$([\d,]+(?:\.\d+)?)/month: added by Claude\.", str(place.get("ai_notes") or "")):
        if abs(float(m.group(1).replace(",", "")) - util) < 0.5:
            return True
    return False


def _estimate_from_listing(place: dict[str, Any], util: float) -> bool:
    """True when the utilities estimate is the monthly bill the saved listing text itself gives (read by the parser), so it
    is not a guess. No stored flag is needed: the listing text is kept, so the same reading is repeated here."""
    notes = str(place.get("ai_notes") or "")
    for m in re.finditer(r"Utilities estimate \$([\d,]+(?:\.\d+)?)/month: (?:billed back, )?from the listing\.", notes):
        if abs(float(m.group(1).replace(",", "")) - util) < 0.5:
            return True  # the AI said where the amount came from (and the listing text agreed when it was saved)
    text = str(place.get("listing_text") or "")
    if not text:
        return False
    try:
        from .parsers import listing_billed_amount
        amount = listing_billed_amount(text)
    except Exception:
        return False
    return amount is not None and abs(amount - util) < 0.5


def _billed_names(place: dict[str, Any]) -> list[str]:
    try:
        from .parsers import listing_billed_names
        return listing_billed_names(str(place.get("listing_text") or ""))
    except Exception:
        return []


_UTIL_NAME = r"(electric(?:ity)?|gas|water|sewer|trash|garbage|internet)"
_TENANT_WORD = r"(?:tenant|resident|renter)s?"
_TEXT_TENANT_PAYS = (
    re.compile(r"\b" + _UTIL_NAME + r"\b[ \t]*[:\-][ \t]*" + _TENANT_WORD + r"(?:[ \t]+(?:pays?|paid|responsible))?\b(?![^.\n;|]{0,25}\$)", re.I),
    re.compile(r"\b" + _TENANT_WORD + r"[ \t]+(?:pays?|is responsible for|are responsible for)[ \t]+(?:for[ \t]+)?" + _UTIL_NAME + r"\b(?![^.\n;|]{0,25}\$)", re.I),
)


def _text_tenant_unpriced(place: dict[str, Any]) -> list[str]:
    """Cycle 23: the last check behind "true cost", decided from the final values. A utility the saved listing text says the tenant pays
    ("Electric: tenant") with no price beside it, that the place's own fields do not hold as tenant-paid, included or priced, is still an unknown
    cost part, whatever a reader did with the line."""
    text = str(place.get("listing_text") or "")
    if not text:
        return []
    have = set(tenant_pays_list(place))
    have |= {w.strip().lower() for w in re.split(r"[,;]| and ", str(place.get("utilities_included") or "")) if w.strip()}
    found: list[str] = []
    for pat in _TEXT_TENANT_PAYS:
        for m in pat.finditer(text):
            w = m.group(1).lower()
            w = {"electricity": "electric", "garbage": "trash"}.get(w, w)
            if w not in have and w not in found:
                found.append(w)
    return found


def _unpriced_tenant_utilities(place: dict[str, Any]) -> list[str]:
    """What the tenant pays that the listing's billed-back amount does not cover ("electric, gas, internet" when only trash
    is billed back). Empty when the amount covers everything the tenant pays, or the listing text does not say what it covers."""
    try:
        from .parsers import listing_estimate_names
        rough = listing_estimate_names(str(place.get("listing_text") or ""))  # "Electric about $110": covers electric only
    except Exception:
        rough = []
    priced = {"water" if w == "hot water" else w for w in _billed_names(place) + rough}
    noted = _noted_unpriced(place)
    if not priced and not noted:
        return []
    if priced & {"gas", "heat"}:
        priced |= {"gas", "heat"}  # a gas bill is the heat bill: a gas figure counts the heat, a heat figure counts the gas
    left = [w for w in _cost_pays(place) if w not in priced and w not in NOTHING_WORDS]
    return list(dict.fromkeys(left + [w for w in noted if w not in left]))


_UNPRICED_NOTE = re.compile(r"\b((?:electric(?:ity)?|gas|water|sewer|trash|heat|internet)(?:(?:,| and|, and)\s+(?:electric(?:ity)?|gas|water|sewer|trash|heat|internet))*)\s+(?:is|are) listed as something you pay, with no amount", re.I)


def _noted_unpriced(place: dict[str, Any]) -> list[str]:
    """Cycle 22: utilities the saved notes say the tenant pays with no amount ("Electric and gas are listed as something you pay, with no
    amount"), whatever the listing text reading says the estimate covers: the cost line names them as missing."""
    out: list[str] = []
    for n in note_units(place.get("reader_notes")):
        m = _UNPRICED_NOTE.search(n)
        if m:
            out += ["electric" if w == "electricity" else w for w in re.findall(r"electric(?:ity)?|gas|water|sewer|trash|heat|internet", m.group(1).lower())]
    return list(dict.fromkeys(out))


def has_pets(pet_kind: Any) -> bool:
    """True when the search says the person has pets ("cat", "dog" or "both"). Empty or "none" means no pets."""
    return str(pet_kind or "").strip().lower() in ("cat", "dog", "both")


def _optional_parking_noted(place: dict[str, Any]) -> bool:
    """True when the saved listing notes say a garage or parking space is available for a price but looks optional (so it is not counted)."""
    return any(re.search(r"\b(?:parking|garage|carport|space)\b", n, re.I) and re.search(r"looks optional", n, re.I)
               for n in note_units(place.get("reader_notes")))


def rent_cost(place: dict[str, Any], pets: bool = True, adults: int = 1) -> dict[str, Any]:
    """The true monthly cost of renting this place, line by line. ``pets`` False (the search has no pets) leaves pet
    rent, the pet fee and the pet deposit out of the cost and the cash at move-in and says so on the pet line. ``adults``
    is how many adults apply: an application fee charged per adult is multiplied by it."""
    price = num(place.get("price"))
    missing: list[str] = []
    uncounted: list[str] = []
    notes: list[str] = []
    lines: list[dict[str, Any]] = []
    if price is None:
        missing.append("monthly rent")
    lines.append(_line("price", "Rent", price))

    util = num(place.get("utilities_estimate"))
    extra_unpriced = _text_tenant_unpriced(place)
    if util is None:
        pays = _cost_pays(place)
        pays = pays + [w for w in extra_unpriced if w not in pays]
        internet_done = bool(pays) and "internet" in pays and _internet_counted(place)
        if internet_done:
            pays = [w for w in pays if w != "internet"]  # the internet is already counted in other monthly fees: not unknown
        listed = str(place.get("utilities_included") or "").strip()
        if internet_done and not pays and not listed:
            lines.append(_line("utilities", "Utilities", 0, "internet is counted in other monthly fees"))
        elif utilities_covered(place) or (pays and all(w in NOTHING_WORDS for w in pays)):
            lines.append(_line("utilities", "Utilities", 0, "included in the rent"))
        elif listed and not pays and listed.lower() not in NOTHING_WORDS:
            # "Heat, water and trash included" and nothing the tenant pays: say what is included, don't call it unknown.
            lines.append(_line("utilities", "Utilities", 0, f"included in the rent: {listed}"))
        elif pays:
            names = _join_words(pays)
            missing.append("utilities estimate")
            uncounted.append(f"utilities ({names})")
            note = f"You pay {names}; not counted yet"
            # cycle 28: the cost line and the "Not counted yet because it is missing ... Fill it in under Facts" line already say this, so no third sentence
            lines.append(_line("utilities", "Utilities", None, note))
        else:
            missing.append("utilities estimate")
            uncounted.append("utilities")
            lines.append(_line("utilities", "Utilities", None, "not filled in"))
    else:
        from_listing = _estimate_from_listing(place, util)
        note = "From the listing" if from_listing else "A guess, not from the listing"
        if from_listing and (re.search(r"Utilities estimate \$[\d,.]+/month: billed back, from the listing", str(place.get("ai_notes") or ""))
                             or _billed_names(place)):
            note = "Billed back, from the listing"
            try:
                from .parsers import listing_utilities_flat_fee
                if listing_utilities_flat_fee(str(place.get("listing_text") or "")):
                    note = "Flat fee, from the listing"
            except Exception:
                pass
        if place.get("utilities_included"):
            note += f". The listing includes: {place['utilities_included']}"
        by_claude = not from_listing and _added_by_claude(place, util)
        if by_claude:
            note = note.replace("A guess, not from the listing", "Added by Claude, not read from the listing")
        line = _line("utilities", "Utilities" if from_listing else ("Utilities (added by Claude)" if by_claude else "Utilities (a guess)"), util, note)
        line["estimated"] = not from_listing  # an amount the listing states (or bills back) is not a guess
        unpriced = _unpriced_tenant_utilities(place) if from_listing else []
        if from_listing and extra_unpriced:
            try:
                from .parsers import listing_estimate_names
                covered = {"water" if w == "hot water" else w for w in _billed_names(place) + listing_estimate_names(str(place.get("listing_text") or ""))}
            except Exception:
                covered = set()
            unpriced = unpriced + [w for w in extra_unpriced if w not in covered and w not in unpriced]
        if unpriced:
            # The listing prices only part of what the tenant pays (for example trash billed back), so the rest is not counted yet.
            names = _join_words(unpriced)
            line["note"] = f"{note}. It covers only what the listing prices; you also pay {names}, not counted yet"
            missing.append(names)  # name only what is really missing ("electric and gas"), not the whole estimate
            uncounted.append(f"utilities ({names})")
            # cycle 26: the "Not counted yet because it is missing: ..." line (from ``missing``) already says this, so no second sentence for the same utilities
        lines.append(line)

    parking = num(place.get("parking_cost"))
    # An explicit $0 on a lot or street spot ("Parking included, optional garage $100") is the listing's answer for the included spot, and the garage is
    # the extra. A $0 on a garage or carport that the notes call optional is still "optional, ask what it costs".
    park_kind = str(place.get("parking") or "")
    optional_parking = (not parking and park_kind in PRIVATE_PARKING and _optional_parking_noted(place)
                        and (parking is None or park_kind in ("garage", "covered")))
    if optional_parking:
        # The listing offers parking as an extra it did not price into the cost: never "included $0".
        missing.append("parking cost")
        uncounted.append("parking")
        lines.append(_line("parking", "Parking", None, "optional parking is not counted; ask what it costs"))
    elif parking is None and str(place.get("parking") or "") in PRIVATE_PARKING:
        missing.append("parking cost")
        uncounted.append("parking")
        lines.append(_line("parking", "Parking", None, "not filled in"))
    else:
        parking_line = _line("parking", "Parking", parking or 0,
                             "included" if parking == 0 and str(place.get("parking") or "") in PRIVATE_PARKING else "")
        if parking is None and not place.get("parking"):
            parking_line["unset"] = True  # never filled in: shown as "Not known", not $0
        lines.append(parking_line)
    pet_rent_listed = num(place.get("pet_rent")) or 0
    pet_rent = pet_rent_listed if pets else 0
    other = num(place.get("other_monthly_fees")) or 0
    pet_line = _line("pet_rent", "Pet rent", pet_rent)
    if not pets and (pet_rent_listed or num(place.get("pet_fee")) or num(place.get("pet_deposit"))):
        listed = [f"{lab} {exact_dollars(v)}" for lab, v in (("pet rent", pet_rent_listed), ("pet fee", num(place.get("pet_fee"))),
                                                          ("pet deposit", num(place.get("pet_deposit")))) if v]
        pet_line["note"] = f"{NO_PETS_NOTE} ({', '.join(listed)} listed)"
        pet_line["not_counted"] = True
    if pets and place.get("pet_rent") in (None, "") and str(place.get("pets") or "") != "none":
        pet_line["unset"] = True
    lines.append(pet_line)
    other_line = _line("other", "Other monthly fees", other)
    if place.get("other_monthly_fees") in (None, ""):
        other_line["unset"] = True  # shown as "Not known", never as $0
    lines.append(other_line)
    hoa = num(place.get("hoa"))
    if hoa:
        # A rental HOA the tenant pays is part of what they pay each month. Dues the listing says are in the rent are not added twice.
        try:
            from .parsers import listing_hoa_in_rent
            in_rent = listing_hoa_in_rent(str(place.get("listing_text") or ""))
        except Exception:
            in_rent = False
        if in_rent:
            lines.append(_line("hoa", "HOA", 0, "included in the rent"))
        else:
            lines.append(_line("hoa", "HOA", hoa, "paid by the tenant, counted each month"))

    ins = num(place.get("insurance"))
    if ins:
        # The insurance field is a yearly amount (the same field buying uses), so a renter's share is a twelfth of it each month.
        lines.append(_line("insurance", "Insurance", _r(ins / 12), f"{_dollars(ins)} a year, counted as a twelfth each month"))

    months = place.get("lease_months")
    try:
        months = int(months) if months not in (None, "") and int(months) > 0 else DEFAULT_LEASE_MONTHS
    except (TypeError, ValueError):
        months = DEFAULT_LEASE_MONTHS
    one_time = {"application_fee": "Application fee", "move_in_fees": "Move-in fees", "broker_fee": "Broker fee",
                "pet_fee": "Pet fee"}
    if not pets:
        one_time.pop("pet_fee")
    app_total = application_fee_total(place, adults)
    amounts = {k: (app_total if k == "application_fee" else num(place.get(k)) or 0) for k in one_time}
    one_total = sum(amounts.values())
    spread = one_total / months
    detail = ", ".join(f"{label.lower()} {exact_dollars(amounts[k])}" for k, label in one_time.items() if amounts[k])
    app_fee = num(place.get("application_fee")) or 0
    if app_fee and app_total != app_fee:
        detail = detail.replace(f"application fee {exact_dollars(app_total)}", f"application fee {exact_dollars(app_total)} ({exact_dollars(app_fee)} each for {adults} adults)")
    one_line = _line("one_time", f"One-time fees spread over {months} months", spread, detail or "none entered")
    if all(place.get(k) in (None, "") for k in one_time):
        one_line["unset"] = True
    lines.append(one_line)
    if not place.get("lease_months"):
        notes.append(f"Lease length not filled in, so one-time fees are spread over {DEFAULT_LEASE_MONTHS} months.")
    deposit = num(place.get("deposit"))
    total = None if price is None else _r(sum(l["amount"] or 0 for l in lines))
    if deposit:
        notes.append(f"Deposit {exact_dollars(deposit)} is not included in the monthly cost because it comes back.")
    cash = cash_at_move_in(place, pets, adults)
    return {"mode": "rent", "total": total, "lines": lines, "missing": missing, "notes": notes, "deposit": deposit,
            "lease_months": months, "one_time_total": _r(one_total), "uncounted": uncounted,
            "pets_counted": pets, "cash_at_move_in": cash,
            "deposit_unknown": bool(cash and cash.get("deposit_unknown"))}


def months_up_front(place: dict[str, Any]) -> int:
    """Months of rent due before move-in (``places.months_up_front``, 1 when empty or not a whole number of 1 or more)."""
    n = num(place.get("months_up_front"))
    return int(n) if n is not None and n >= 1 and n == int(n) else 1


def cash_at_move_in(place: dict[str, Any], pets: bool = True, adults: int = 1) -> dict[str, Any] | None:
    """Cash needed on move-in day for a rental: the rent due up front (``months_up_front`` months, 1 by default; when
    the listing text asks for a last month and no count is saved, first plus last), deposit, application fee and the
    other one-time fees. Pet fee and pet deposit are left out when ``pets`` is False. Kept apart from the true monthly
    cost. ``deposit_unknown`` is True when no deposit is filled in (0 means "no deposit"), so the figure may be low.
    None when there is no rent to build it on."""
    rent = num(place.get("price"))
    if not rent:
        return None
    months = months_up_front(place)
    last = False
    if months == 1:
        try:
            from .parsers import _move_in_months
            last = bool(_move_in_months(str(place.get("listing_text") or ""))[0])
        except Exception:  # the listing text is only a hint
            pass
    each = None
    if months == 2 and not (num(place.get("price")) is None):
        try:
            from .parsers import _deposit_each, _move_in_months as _mim
            text_l = str(place.get("listing_text") or "")
            each = _deposit_each(text_l) if _mim(text_l)[0] == 2 else None
        except Exception:
            each = None
    if each and abs(each - rent) >= 1:  # "first, last and security deposit ($2,800 each)": the listing gives the amount, not the rent
        parts = [("First month's rent (as the listing says)", each), ("Last month's rent (as the listing says)", each)]
    elif months > 1:
        parts = [(f"Rent due up front ({months} months)", rent * months)]
    else:
        parts = [("First month's rent", rent)]
        if last:
            parts.append(("Last month's rent", rent))
    keys = [("deposit", "Deposit"), ("application_fee", "Application fee"), ("move_in_fees", "Move-in fees"),
            ("broker_fee", "Broker fee")]
    if pets:
        keys += [("pet_fee", "Pet fee"), ("pet_deposit", "Pet deposit")]
    for key, label in keys:
        v = num(place.get(key))
        if key == "pet_deposit" and v:
            # cycle 22: only say "comes back" when the listing says the pet deposit is refundable (the reader's note says not to count on it otherwise)
            try:
                from .parsers import _pet_deposit_says_refundable
                if _pet_deposit_says_refundable(str(place.get("listing_text") or ""), float(v)):
                    label = "Pet deposit (comes back)"
            except Exception:
                pass
        if key == "application_fee" and v:
            total_fee = application_fee_total(place, adults)
            if total_fee != v:
                label = f"Application fee ({exact_dollars(v)} each for {adults} adults)"
            v = total_fee
        if v:
            parts.append((label, v))
    unknown = num(place.get("deposit")) is None
    return {"total": _r(sum(v for _, v in parts)), "parts": [{"label": a, "amount": b} for a, b in parts],
            "deposit_unknown": unknown}


def _listing_cash_note(place: dict[str, Any], cash: dict[str, Any] | None) -> str:
    """"The listing says cash to close is about $55,000; ours is $41,200." Empty when the listing quotes none or there is no figure of ours."""
    if not cash:
        return ""
    try:
        from .parsers import listing_cash_to_close
        est = listing_cash_to_close(str(place.get("listing_text") or ""))
    except Exception:  # the listing text is only a hint
        return ""
    if not est:
        return ""
    ours = cash["total"]
    if abs(ours - est) < 1:
        return f"The listing says cash to close is about {_dollars(est)}, the same as ours."
    guess = " Ours uses a guess for the closing costs." if cash.get("has_estimate") else ""
    return (f"The listing says cash to close is about {_dollars(est)}; ours is {_dollars(ours)}.{guess} "
            "Ask what the listing's figure includes (for example a different down payment or loan costs).")


def _listing_estimate_note(place: dict[str, Any], total: float | None, lines: list[dict[str, Any]]) -> str:
    """"The listing estimates $2,310/mo; ours is $2,708 because it counts PMI and HOA." Empty when the listing quotes
    no payment of its own (it is read from the saved listing text, so no column is needed)."""
    text = str(place.get("listing_text") or "")
    if total is None or "pay" not in text.lower():
        return ""
    try:
        from .parsers import listing_estimated_payment
        est = listing_estimated_payment(text)
    except Exception:  # the listing text is only a hint
        return ""
    if not est:
        return ""
    names = {"pmi": "PMI", "tax": "property tax", "insurance": "insurance", "hoa": "HOA"}
    counted = [names[l["key"]] for l in lines if l["key"] in names and (l["amount"] or 0) > 0]
    if abs(total - est) < 1:
        return f"The listing estimates {_dollars(est)}/mo, about the same as ours."
    if total > est:
        why = f" because ours counts {_join_words(counted)}" if counted else ""
        return f"The listing estimates {_dollars(est)}/mo; ours is {_dollars(total)}{why}."
    return (f"The listing estimates {_dollars(est)}/mo; ours is {_dollars(total)}. "
            "Listings often count costs we don't know yet, so ask what theirs includes.")


def _assessment_payer_of(place: dict[str, Any]) -> str:
    """Who pays the special assessment: the saved payer, else what the saved listing text says outright ("Buyer to pay special assessment of
    $3,000 at closing", "due from buyer at close", "paid by the seller"). "" when neither says."""
    saved = str(place.get("special_assessment_payer") or "")
    if saved in ("buyer", "seller") or not num(place.get("special_assessment")):
        return saved
    text = str(place.get("listing_text") or "")
    if not text:
        return saved
    try:
        from .parsers import _special_assessment_facts
        _amount, payer, _sentence = _special_assessment_facts(text, True)
    except Exception:  # the listing text is only a hint
        return saved
    return payer or saved


def _listing_closing_percent(place: dict[str, Any], price: float) -> tuple[float, float] | None:
    """(percent, dollars) when the saved listing text gives the closing costs as a percent of the price and no dollar figure was saved."""
    text = str(place.get("listing_text") or "")
    if not text:
        return None
    try:
        from .parsers import _closing_costs_percent
        got = _closing_costs_percent(text, price)
    except Exception:  # the listing text is only a hint
        return None
    if not got or not got[0]:
        return None
    return round(got[0] / price * 100, 4), got[0]


def cash_to_close(place: dict[str, Any], cfg: dict[str, float] | None = None) -> dict[str, Any] | None:
    """Cash a buyer needs at closing: down payment, closing costs (entered, else a guess of closing_cost_pct of the
    price, marked ``estimated``) and a special assessment when the buyer pays it. None without a price."""
    cfg = cfg or dict(DEFAULT_BUY)
    price = num(place.get("price"))
    if not price:
        return None
    down = price * cfg["down_payment_pct"] / 100
    parts: list[dict[str, Any]] = [{"label": "Down payment", "amount": _r(down), "estimated": False}]
    closing = num(place.get("closing_costs"))
    from_listing = _listing_closing_percent(place, price) if closing is None else None
    if closing is None and from_listing:  # cycle 25: the listing itself gives a percent of the price ("Estimated closing: 3% of price"): not the app's guess
        parts.append({"label": f"Closing costs ({from_listing[0]:g}% of the price, from the listing)", "amount": _r(from_listing[1]), "estimated": False})
    elif closing is None:
        pct = cfg.get("closing_cost_pct", DEFAULT_BUY["closing_cost_pct"])
        guess = price * pct / 100
        try:  # cycle 28: the listing names closing items the buyer pays. They are inside the guess, never added on top of it.
            from .parsers import buyer_closing_items_stated
            stated = buyer_closing_items_stated(str(place.get("listing_text") or ""))
        except Exception:  # the listing text is only a hint
            stated = []
        stated_total = sum(a for _n, a in stated)
        names = _join_words([f"{_dollars(a)} for {n}" for n, a in stated])
        if stated and stated_total > guess:
            parts.append({"label": f"Closing costs (only what the listing names: {names}; the rest is not known)", "amount": _r(stated_total), "estimated": True})
        elif stated:
            parts.append({"label": f"Closing costs (a guess: {pct:g}% of the price, which includes the {names} the listing names)", "amount": _r(guess), "estimated": True})
        else:
            parts.append({"label": f"Closing costs (a guess: {pct:g}% of the price)", "amount": _r(guess), "estimated": True})
    else:
        parts.append({"label": "Closing costs", "amount": _r(closing), "estimated": False})
    left_out: list[str] = []
    try:  # cycle 29: closing items the listing calls additional ("title and recording $1,900 additional paid by buyer") come on top of the closing costs
        from .parsers import buyer_closing_items_additional
        addl_paid, addl_unclear = buyer_closing_items_additional(str(place.get("listing_text") or ""))
    except Exception:  # the listing text is only a hint
        addl_paid, addl_unclear = [], []
    for name, amount in addl_paid:
        parts.append({"label": f"Closing item on top of the closing costs ({name})", "amount": _r(amount), "estimated": False})
    for name, amount in addl_unclear:
        left_out.append(f"{_dollars(amount)} for {name} (called additional) isn't counted because who pays it isn't known")
    sa = num(place.get("special_assessment"))
    payer = _assessment_payer_of(place)
    if sa and payer == "buyer":
        parts.append({"label": "Special assessment (you pay it)", "amount": _r(sa), "estimated": False})
    try:  # one-time fees the listing says the buyer pays at closing (capital improvement, reserve contribution, move-in fee)
        from .parsers import buyer_one_time_fees
        paid, unclear = buyer_one_time_fees(str(place.get("listing_text") or ""))
    except Exception:  # the listing text is only a hint
        paid, unclear = [], []
    for label, amount in paid:
        parts.append({"label": f"One-time fee at closing ({label})", "amount": _r(amount), "estimated": False})
    for label, amount in unclear:
        left_out.append(f"a {_dollars(amount)} {label} isn't counted because who pays it isn't known")
    try:  # cycle 28: a fee stated as months of HOA ("capital improvement fee equal to two months of HOA") counts once the HOA is known
        from .parsers import buyer_hoa_month_fees
        hoa_paid, hoa_unclear = buyer_hoa_month_fees(str(place.get("listing_text") or ""))
    except Exception:  # the listing text is only a hint
        hoa_paid, hoa_unclear = [], []
    hoa_now = num(place.get("hoa"))
    for label, months in hoa_paid:
        words = f"{months:g} month{'s' if months != 1 else ''} of HOA"
        if hoa_now:
            parts.append({"label": f"One-time fee at closing ({label}, {words})", "amount": _r(hoa_now * months), "estimated": False})
        elif hoa_now is None:
            left_out.append(f"the {label} of {words} isn't counted because the HOA isn't known")
    for label, months in hoa_unclear:
        left_out.append(f"the {label} of {months:g} month{'s' if months != 1 else ''} of HOA isn't counted because who pays it isn't known")
    if sa and payer not in ("buyer", "seller"):
        left_out.append(f"a {_dollars(sa)} special assessment isn't counted because who pays it isn't known")
    credit = num(place.get("seller_credit"))
    credits: list[tuple[str, float]] = []
    if credit and credit > 0:
        credits.append(("Seller credit toward closing (comes off)", credit))
    try:  # cycle 27: a lender credit or an unnamed "closing credit" in the listing also comes off, once (never the same amount as the seller credit)
        from .parsers import lender_credits
        for amount, kind in lender_credits(str(place.get("listing_text") or "")):
            if kind == "closing" and credit and abs(credit - amount) < 0.005:
                continue
            credits.append(("Lender credit at closing (comes off)" if kind == "lender" else "Closing credit (comes off)", amount))
    except Exception:  # the listing text is only a hint
        pass
    if credits:
        # The seller pays part of the closing costs, so it lowers the cash you bring (never below zero overall).
        # Cycle 23: a credit only pays closing costs, so it can't lower the cash below the down payment. All credits together are capped at the closing costs line.
        closing_amount = next((p["amount"] for p in parts if p["label"].startswith("Closing costs")), 0)
        total_credit = sum(a for _l, a in credits)
        room = closing_amount
        for label, amount in credits:
            used = min(amount, room)
            room -= used
            if used:
                parts.append({"label": label, "amount": _r(-used), "estimated": False})
        if total_credit > closing_amount:
            extra = total_credit - closing_amount
            if len(credits) == 1:
                left_out.append(f"{_dollars(extra)} of the {_dollars(total_credit)} seller credit isn't counted, because a credit can only pay the {_dollars(closing_amount)} closing costs "
                                "and can't lower the cash below the down payment")
            else:
                left_out.append(f"{_dollars(extra)} of the {_dollars(total_credit)} in credits isn't counted, because credits can only pay the {_dollars(closing_amount)} closing costs "
                                "and can't lower the cash below the down payment")
    return {"total": _r(sum(p["amount"] for p in parts)), "parts": parts,
            "has_estimate": any(p["estimated"] for p in parts), "left_out": left_out}


def monthly_payment(principal: float, annual_rate_pct: float, years: float) -> float:
    """Principal and interest per month for a fixed-rate loan."""
    n = int(round(years * 12))
    if n <= 0 or principal <= 0:
        return 0.0
    r = annual_rate_pct / 100 / 12
    if r == 0:
        return principal / n
    return principal * r / (1 - (1 + r) ** -n)


def buy_settings(settings: dict[str, Any] | None = None) -> dict[str, float]:
    """The buyer defaults (down payment percent, mortgage rate, loan years) from settings, with fallbacks."""
    out: dict[str, float] = dict(DEFAULT_BUY)
    for k in DEFAULT_BUY:
        v = num((settings or {}).get(k))
        if v is not None and v >= 0:
            out[k] = v
    return out


def buy_cost(place: dict[str, Any], settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """The estimated monthly cost of buying: loan payment, property tax, insurance, HOA."""
    cfg = buy_settings(settings)
    price = num(place.get("price"))
    missing: list[str] = []
    uncounted: list[str] = []
    lines: list[dict[str, Any]] = []
    down = loan = pmi = None
    notes = ["An estimate to compare places, not financial advice."]
    if price is None:
        missing.append("asking price")
        lines.append(_line("loan", "Loan payment (principal and interest)", None, "needs the asking price"))
        pi = None
    else:
        down = price * cfg["down_payment_pct"] / 100
        loan = price - down
        pi = monthly_payment(loan, cfg["mortgage_rate"], cfg["loan_years"])
        lines.append(_line("loan", "Loan payment (principal and interest)", pi,
                           f"Loan {_dollars(loan)} after {_dollars(down)} down ({cfg['down_payment_pct']:g}%), "
                           f"{cfg['mortgage_rate']:g}% rate, {cfg['loan_years']:g} years"))
        if cfg["down_payment_pct"] < PMI_BELOW_PCT:
            pmi = loan * cfg["pmi_rate_pct"] / 100 / 12
            quoted = None
            try:  # cycle 29: a PMI figure the listing quotes is used instead of the app's own estimate
                from .parsers import listing_pmi_monthly
                quoted = listing_pmi_monthly(str(place.get("listing_text") or ""))
            except Exception:  # the listing text is only a hint
                quoted = None
            if quoted:
                guess = pmi
                pmi = quoted[0]
                lines.append(_line("pmi", "Mortgage insurance (PMI), quoted in the listing", pmi,
                                   f"{exact_dollars(pmi)} a month, as the listing quotes it (\"{quoted[1]}\")"))
                notes.append(f"PMI uses the {exact_dollars(pmi)} a month the listing quotes, not the app's own estimate of {_dollars(guess)}. Your lender's quote decides the real number.")
            else:
                lines.append(_line("pmi", "Mortgage insurance (PMI), an estimate", pmi,
                                   f"{cfg['pmi_rate_pct']:g}% of the loan a year, because the down payment is under {PMI_BELOW_PCT:g}%"))
                notes.append("PMI is a rough guess. Your lender's quote decides the real number.")
    tax, ins, hoa = num(place.get("property_tax")), num(place.get("insurance")), num(place.get("hoa"))
    for key, label, val, per in (("tax", "Property tax", tax, 12), ("insurance", "Insurance", ins, 12)):
        if val is None:
            missing.append(label.lower() + " (per year)")
            uncounted.append(label.lower())
            lines.append(_line(key, label, None, "not filled in"))
        else:
            lines.append(_line(key, label, val / per, f"${val:,.0f} a year"))
    if hoa is None:
        missing.append("HOA (per month)")
        uncounted.append("HOA")
        lines.append(_line("hoa", "HOA", None, "not filled in"))
    else:
        lines.append(_line("hoa", "HOA", hoa))
    other_fees = num(place.get("other_monthly_fees"))
    if other_fees:  # cycle 24: another monthly charge (capital reserve, amenity) entered on a buy place is part of the monthly cost
        lines.append(_line("other", "Other monthly fees", other_fees))
    total = None if pi is None else _r(sum(l["amount"] or 0 for l in lines))
    cash = cash_to_close(place, cfg)
    sa, payer = num(place.get("special_assessment")), _assessment_payer_of(place)
    if sa and payer == "buyer":
        notes.append(f"The special assessment ({_dollars(sa)}, paid by you) is counted once in the cash to close, not in the monthly cost.")
    elif sa and payer == "seller":
        notes.append(f"A special assessment of {_dollars(sa)} is paid by the seller, so it is not counted.")
    elif sa:
        notes.append(f"A special assessment of {_dollars(sa)} is listed but who pays it is not filled in, so it is not counted. Ask who pays it, then set Who pays on this page.")
    listing_note = " ".join(x for x in (_listing_estimate_note(place, total, lines), _listing_cash_note(place, cash)) if x)
    return {"mode": "buy", "listing_estimate_note": listing_note, "total": total, "lines": lines, "missing": missing, "uncounted": uncounted,
            "notes": notes, "deposit": None,
            "down_payment": None if down is None else _r(down), "loan_amount": None if loan is None else _r(loan),
            "pmi": None if pmi is None else _r(pmi), "settings": cfg, "cash_to_close": cash}


def _dollars(n: float) -> str:
    return f"${n:,.0f}"


def exact_dollars(n: float) -> str:
    """Cycle 24: a figure the listing gave, shown the way it was given: $42.50 keeps its cents, $1,200 does not. Totals worked out from several
    figures still use ``_dollars`` (rounded)."""
    try:
        n = float(n)
    except (TypeError, ValueError):
        return str(n)
    return f"${n:,.2f}" if abs(n - round(n)) >= 0.005 else f"${n:,.0f}"


def _join_words(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _short_unc(unc: list[str]) -> list[str]:
    """The names behind "not counted yet" kept to the essentials: when they run long, "utilities (electric, gas, water and sewer)" is just
    "utilities", and when that is still long a list of amounts in the listing notes is "some amounts in the listing notes" (the notes and the
    cost lines name them)."""
    if len(_join_words(unc)) <= 60:
        return unc
    short = list(dict.fromkeys(re.sub(r"\s*\([^)]*\)$", "", u) if u.startswith("utilities (") else u for u in unc))
    if len(_join_words(short)) > 80:
        short = [LISTING_NOTES_UNCOUNTED if re.search(r"amounts in the listing notes$", u) and len(re.findall(r"\$", u)) >= 2 else u for u in short]
    return list(dict.fromkeys(short))


def uncounted_display(cost: dict[str, Any]) -> list[str]:
    """Cycle 22: the "not counted yet" names of a cost result, with the generic "some amounts in the listing notes" replaced by what it is
    ("water and sewer", "the $200 amount in the listing notes"). Utilities the listing notes name are folded into a "utilities (...)" entry
    that is already there, so the line says "utilities (electric, internet, water and sewer)" and never lists a thing twice."""
    unc = list(cost.get("uncounted") or [])
    label = cost.get("listing_notes_label")
    if LISTING_NOTES_UNCOUNTED not in unc or not label:
        return unc
    names = [str(n) for n in cost.get("listing_notes_names") or []]
    names_only = bool(names) and label == _join_words(names)
    out: list[str] = []
    for u in unc:
        if u != LISTING_NOTES_UNCOUNTED:
            out.append(u)
        elif not names_only:
            out.append(label)
    if names:
        at = next((i for i, u in enumerate(out) if u.startswith("utilities (") and u.endswith(")")), None)
        if at is not None:
            have = [x for x in re.split(r",\s*|\s+and\s+", out[at][len("utilities ("):-1]) if x]
            out[at] = f"utilities ({_join_words(have + [n for n in names if n not in have])})"
        else:
            out.append(_join_words(names))
    return list(dict.fromkeys(out))


_AMOUNTS_LABEL = re.compile(r"^the (\$[\d,.]+(?:(?:, | and )\$[\d,.]+)+) amounts in the listing notes$")


def _plain_amounts_label(label: str) -> str:
    """Cycle 23: "utilities and the $99 and $1,490 amounts in the listing notes" has two "and"s that run together, so in the headline several
    amounts read "utilities and listing amounts ($99 and $1,490)"."""
    m = _AMOUNTS_LABEL.match(label)
    return f"listing amounts ({m.group(1)})" if m else label


def headline(cost: dict[str, Any], people: int = 1, noun: str = "people") -> str:
    """The one line next to the total: '$2,414/mo, insurance not counted yet' (and '$807 each' when people share it)."""
    total = cost.get("total")
    if total is None:
        return "Cost unknown"
    text = f"{_dollars(total)}/mo"
    unc = [_plain_amounts_label(u) for u in uncounted_display(cost)]
    if unc:
        text += f", {_join_words(_short_unc(unc))} not counted yet"
    if people and people > 1:
        text += f" ({_dollars(total / people)} each for {people} {noun})"
    return text


LISTING_NOTES_UNCOUNTED = "some amounts in the listing notes"
_NOTE_OPEN = re.compile(r"not counted|not saved|not used|no amount is saved|could not tell|couldn't tell|left (?:blank|empty)|add it to|fill it in|ask (?:what|if|who|whether|which)|is not filled", re.I)
_NOTE_MONEY = re.compile(r"\$\s?\d|\b(?:fee|fees|deposit|assessment|parking|garage|utilit\w*|rent|cost|costs|free|credit|hoa|tax|insurance)\b", re.I)


_NOTE_PLACED = re.compile(r"so nothing is counted for you|\bis saved as the\b|\bso it is counted\b|\bcounted as your\b|\bcounted in (?:other monthly fees|the monthly cost)\b", re.I)


_NOTE_CONTINUES = re.compile(r"(?:It|Only|No|Ask|Check|Add|Fill|I|Don't|Then|If|Read|So|They|This|That)\b")


_NOTE_CONTINUES_LEFT = re.compile(r"[A-Z][\w' ]{0,30}\b(?:is|are) (?:left (?:empty|blank)|not filled)\b")


def join_notes(notes: Any) -> str:
    """The notes as saved text: one note per line (a note keeps its own sentences together)."""
    return "\n".join(" ".join(str(n).split()) for n in notes if str(n).strip())


def note_units(text: str) -> list[str]:
    """The saved reader notes as whole notes. Notes are saved one per line, and then each line is one note. A paragraph saved
    the old way (or a single note) is cut into a sentence plus the sentences that carry on from it ("It is not counted.")."""
    lines = [" ".join(x.split()) for x in str(text or "").splitlines() if x.strip()]
    if len(lines) > 1:
        return lines
    units: list[str] = []
    for sentence in re.split(r"(?<!\.\.)(?<=[.!?])\s+(?=[A-Z])", " ".join(str(text or "").split())):  # cycle 28: "..." inside a quoted line is not a sentence end
        if units and (_NOTE_CONTINUES.match(sentence) or _NOTE_CONTINUES_LEFT.match(sentence)):
            units[-1] += " " + sentence
        elif sentence:
            units.append(sentence)
    return units


_CLOSING_ESTIMATE_SENTENCE = re.compile(r"[ \t]*The cash to close uses an estimate of the closing costs\.")


def without_stale_estimate(note: str, place: dict[str, Any] | None) -> str:
    """"The cash to close uses an estimate of the closing costs" stops being true once the closing costs are filled in: the sentence goes."""
    if place and num(place.get("closing_costs")) is not None and _CLOSING_ESTIMATE_SENTENCE.search(note):
        return "\n".join(" ".join(_CLOSING_ESTIMATE_SENTENCE.sub("", line).split()) for line in note.splitlines()).strip()
    return note


def display_note_units(place: dict[str, Any]) -> list[str]:
    """The saved reader notes as shown on the place page: each note, with a sentence about a field that is filled in now dropped."""
    return [n for n in note_units(without_stale_estimate(str(place.get("reader_notes") or ""), place)) if n]


# One-time amounts (a move-in total, a holding fee, a price cut, a one-time deal) are not in the monthly cost, so they never
# set the monthly "not counted yet" tag: they only matter for the cash due at move-in.
ONE_TIME_NOTE = re.compile(r"not in the monthly cost|not counted in the monthly cost|one-time cost|in total to move in|\bholding fee|\breservation (?:fee|deposit)|one-time (?:deal|amount)|"
                           r"price was cut|price (?:cut|drop|reduc\w*|lowered)|(?:cut|reduced|lowered|dropped) (?:by|to|from)\s+\$|\$\s?[\d,]+\s+off\b|rent concession|\bdiscount\b", re.I)
# A note about an optional extra with no price ("A carport is available but the listing gives no price. It looks optional") holds no amount.
NOT_A_COST_NOTE = re.compile(r"not a cost on top of the rent|\bis the old price and is not used\b|\bis another lease length option, so it is not added to the cost\b|\bThe rent saved is the (?:lowest|cheapest|matching)\b[^.]*\bplan\b|\bthe rent saved is\b[^.]*,\s*not the \"?starting at\"? price", re.I)
_NOTE_CLOSED = re.compile(r"\bcounted once\b|\bnot counted again\b|\balready counted\b|\bpaid through that flat fee\b|was a mistake or an old figure|\bthe HOA covers \w+ and also lists a \w+ charge of\b|\bIt is read as a deposit of [\d.]+ months? of rent\b", re.I)  # cycle 20 join: a figure the listing takes back is not open
_NOTE_CONDITIONAL = re.compile(r"only applies on that condition|only if (?:credit|your credit)", re.I)
# A note with no dollar amount names an open cost only when it names a cost word ("rent" and "free" alone are not: "Ask what the month to month terms and rent are").
_NOTE_COST_WORD = re.compile(r"\b(?:fee|fees|deposit|assessment|parking|garage|utilit\w*|hoa|tax|insurance)\b", re.I)
_NO_AMOUNT_OPTIONAL = re.compile(r"gives no price|no price is given|looks optional|is optional|\boptional\b", re.I)


# A note that names the other parking choices of a place that is already counted at one of them, and a warning about a wire: neither is a cost left out.
_NOTE_CHOICE = re.compile(r"gives more than one parking choice|more than one parking (?:choice|option)|also offers another parking choice", re.I)
_NOTE_WARNING = re.compile(r"can't be taken back|don't send money|do not send money", re.I)
_NOTE_BUY_PARKING = re.compile(r"The cost of buying does not count (?:parking|it)\b")
_RENT_RANGE_NOTE = re.compile(r"\brent range of \$", re.I)
RENT_RANGE_LABEL = "the rent (the listing gives a range)"


# Cycle 25: a figure that a note explains as another lease length, another plan, a move-in special, a one-time or pending amount or an old price is never a
# missing monthly amount. Decided by meaning, from the words around the figure (inside the quoted listing line when the note quotes one), so the wording of
# the note that holds it does not matter.
_FIG = re.compile(r"\$\s?(\d[\d,]*+(?:\.\d+)?+)(?!…)(?!(?:[ \t]\d\b){2,})")  # cycle 29: "$9999999…" (a shortened huge figure) and "$2 9 5 0" (digits with spaces) are no figure
_EXPL_FEE = re.compile(r"\bdeposit|\bfees?\b|\bdues\b|\btax|insurance|\bhoa\b|parking|garage|\bpets?\b|utilit|electric|\bwater\b|trash|internet|"
                       r"\bdrops?\b|\bdropped\b|reduc|discount|\boff\b|\bfree\b|concession|credit|rebate|waive|bonus", re.I)
_EXPL_LEASE_BEFORE = re.compile(r"\b\d{1,2}[- ]?(?:months?|mos?)\b(?:[- ]?(?:lease|term|contract))?[^$\n;]{0,25}$", re.I)
_EXPL_LEASE_AFTER = re.compile(r"^\s*(?:/\s*mo\w*\s*)?(?:for|on|with|if you sign)\s+(?:a\s+|an\s+)?\d{1,2}[- ]?(?:months?|mos?)\b", re.I)
_EXPL_LEASE_WORDS = re.compile(r"\bmonth[- ]to[- ]month\b|\bmtm\b|\blease (?:length|term)s?\b|\bother lease\b|\banother lease\b|\bdifferent lease\b|\blease options?\b|\bmonth lease options?\b", re.I)
_EXPL_PLAN = re.compile(r"\b(?:another|other|different) (?:floor ?)?plans?\b|\bfloor[- ]?plans?\b|\b(?:\d[- ]?)?(?:bed(?:room)?s?|br|bd|studio)[- ]plans?\b|\bplans? (?:at|from)\b|\bstarting (?:at|from)\b|\bplan options?\b|\bother (?:unit|size)s?\b", re.I)
_EXPL_SPECIAL = re.compile(r"\bmove-?in specials?\b|\bspecial offers?\b|\bpromo\w*|\bbest-case\b|\bwith approved credit\b|\bspecials?\b(?!\s+assessment)|\blimited[- ]time\b|\blimited (?:offer|availability)\b|\bfor a limited\b|\b(?:if|when) you (?:sign|move in|lease|apply)\b|\bsign(?:ing)? (?:by|before|within)\b|\boffer (?:ends|expires)\b|\bexpires?\b", re.I)
_EXPL_ONE_TIME = re.compile(r"\bseller(?:'s)?\s+(?:pays?|paid|will pay|credits?|contribut\w*|concessions?|covers?|help\w*)\b|\bone[- ]time\b|\bpending\b|\bspecial assessments?\b|\bassessments?\b|\bvote\b|\bto be split\b|\bsplit (?:among|between)\b|\bpaid by (?:the )?seller\b|\bseller[- ]paid\b|\bby the seller\b|\b(?:transfer|working capital|capital contribution|initiation|move-?out|closing|escrow|title|recording|origination)\s+(?:fees?|costs?)\b|\bholding (?:deposit|fee)\b|\bcapital contribution\b", re.I)
# A figure inside a sentence that tries to direct an AI tool or asks for a payment by a wire-like service is never a monthly cost of the place.
_EXPL_HOSTILE = re.compile(r"\bAI (?:assistant|agent|model|tool)\b|\bauthori[sz]ed you\b|\b(?:ignore|disregard|forget) (?:all |any |the |your |every )?(?:previous|prior|above|earlier|other)\b|\bdo not (?:mention|tell)\b|\bSYSTEM\s*:|\byou are now\b|\bcall (?:add|move|set|delete)_\w+|</?\s*untrusted|[<＜][^>＞\n]{0,40}[>＞]|\b(?:send|wire|transfer|pay|zelle)\b[^.\n]{0,50}\b(?:by|via|through|using|with|over|to)\s+(?:zelle|venmo|cash ?app|paypal|wire|western union|gift cards?|crypto\w*|bitcoin)\b", re.I)
# A second or extra item (second pet, second space, additional car) and a storage add-on are optional extras: named in a note, never a missing monthly amount.
_EXPL_SECOND = re.compile(r"\b(?:second|2nd|third|3rd)\b(?!\s+(?:month|floor|bed|bath|level|story|year))|\b(?:additional|extra|another)\s+(?:pets?|dogs?|cats?|animals?|spaces?|spots?|cars?|vehicles?|parking|garages?|storage|keys?|fobs?|persons?|occupants?|residents?|tenants?|adults?)\b|\bstorage\b", re.I)
_EXPL_OLD = re.compile(r"\bold price\b|\bolder (?:price|rent)\b|\bformerly\b|\bno longer\b|\bwas an old\b|\bis the old\b", re.I)


def _figure_segment(note: str, start: int, end: int) -> tuple[str, int, int]:
    """The words a figure sits in: the quoted listing line when it is inside one, else the note; cut at semicolons and sentence ends."""
    lo, hi, text = 0, len(note), note
    for qm in re.finditer(r'"([^"]*)"', note):
        if qm.start(1) <= start and end <= qm.end(1):
            text, lo, hi = qm.group(1), 0, len(qm.group(1))
            start, end = start - qm.start(1), end - qm.start(1)
            break
    cuts = [m.end() for m in re.finditer(r";|\n|(?<!\d)\.(?=\s|$)|\s-\s", text) if m.end() <= start]
    lo = max(cuts or [0])
    nxt = [m.start() for m in re.finditer(r";|\n|(?<!\d)\.(?=\s|$)|\s-\s", text) if m.start() >= end]
    hi = min(nxt or [len(text)])
    return text, lo, hi


def figure_explained(note: str, start: int, end: int) -> str:
    """"lease", "plan", "special", "one_time" or "old" when the note itself says the figure at note[start:end] is another lease length, another floor
    plan, a move-in special, a one-time or pending amount or an old price; "" otherwise (an unexplained figure stays a missing amount)."""
    text, lo, hi = _figure_segment(note, start, end)
    qs = [m for m in re.finditer(r'"([^"]*)"', note) if m.start(1) <= start and end <= m.end(1)]
    off = qs[0].start(1) if qs else 0
    s0, e0 = start - off, end - off
    seg = text[lo:hi]
    before, after = text[lo:s0], text[e0:hi]
    slo = max([0] + [m.end() for m in re.finditer(r"(?<!\d)\.(?=\s|$)|\n", text) if m.end() <= s0])
    shi = min([len(text)] + [m.start() for m in re.finditer(r"(?<!\d)\.(?=\s|$)|\n", text) if m.start() >= e0])
    sent = text[slo:shi]  # the whole sentence: "2 bedroom plans at $1,380; $1,520; $1,480" says "plans" once for every figure of the list
    if _EXPL_OLD.search(seg):
        return "old"
    if _EXPL_HOSTILE.search(sent):
        return "hostile"
    if _EXPL_ONE_TIME.search(seg) and not re.search(r"\bper\s+month\b|/\s*mo\b|\ba\s+month\b|\bmonthly\b|\beach\s+month\b", after[:18], re.I):
        return "one_time"
    if _EXPL_SPECIAL.search(seg) and not re.search(r"\bfees?\b|\bdues\b|\bhoa\b|\butilit", seg, re.I):
        return "special"
    if _EXPL_PLAN.search(sent) and not _EXPL_FEE.search(sent):
        return "plan"
    if not _EXPL_FEE.search(sent) and (_EXPL_LEASE_WORDS.search(sent) or _EXPL_LEASE_BEFORE.search(before[-40:]) or _EXPL_LEASE_AFTER.search(after[:40])):
        return "lease"
    return ""


# Cycle 26 (rule e): a figure set to $0, included, counted, optional (an upgrade, "if you want") or explained in another note is never named in the
# "missing" list or the monthly headline. Decided here, once, from the saved notes and fields, so every reader of the notes gets the same answer.
_OPTIONAL_NOTE = re.compile(r"\blooks optional\b|\bis optional\b|\bare optional\b|\bit is optional\b|\boptional,? so it is not counted\b|\bnot required\b|\bis optional for one car\b", re.I)


def _figure_piece(note: str, start: int, end: int) -> str:
    """The comma or semicolon item a figure sits in ("garage upgrade $130/mo" inside "reserved covered spot $55/mo, garage upgrade $130/mo")."""
    text, lo, hi = _figure_segment(note, start, end)
    off = 0
    for qm in re.finditer(r'"([^"]*)"', note):
        if qm.start(1) <= start and end <= qm.end(1):
            off = qm.start(1)
            break
    s0, e0 = start - off, end - off
    before = text[lo:s0]
    after = text[e0:hi]
    cut_b = max([m.end() for m in re.finditer(r"[,;(]|\bplus\b|\band\b", before)] or [0])
    cut_a = min([m.start() for m in re.finditer(r"[,;)]|\bplus\b|\band\b", after)] or [len(after)])
    return before[cut_b:] + text[s0:e0] + after[:cut_a]


def _amount_of(m: re.Match[str]) -> float:
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return -1.0


def _note_figures(note: str) -> list[re.Match[str]]:
    """The dollar figures of a note. A note that quotes a listing line holds the figure twice ("..$130/mo". Only $130 of that ..."): the quote's figure is the one."""
    figs = list(_FIG.finditer(note))
    qs = [m for m in re.finditer(r'"([^"]*)"', note)]
    if not qs:
        return figs
    inside = {_amount_of(f) for f in figs if any(q.start(1) <= f.start() and f.end() <= q.end(1) for q in qs)}
    return [f for f in figs if any(q.start(1) <= f.start() and f.end() <= q.end(1) for q in qs) or _amount_of(f) not in inside]


def _note_figures_loose(note: str) -> list[re.Match[str]]:
    """Like ``_note_figures`` for the looser figure pattern the missing-list code uses ("$ 35", "$1,200.")."""
    loose = list(re.finditer(r"\$\s?\d[\d,]*+(?:\.\d+)?+(?!…)(?!(?:[ \t]\d\b){2,})", note))
    qs = list(re.finditer(r'"([^"]*)"', note))
    if not qs:
        return loose
    def in_q(f: re.Match[str]) -> bool:
        return any(q.start(1) <= f.start() and f.end() <= q.end(1) for q in qs)
    inside = {f.group(0).replace(" ", "").rstrip(",.") for f in loose if in_q(f)}
    return [f for f in loose if in_q(f) or f.group(0).replace(" ", "").rstrip(",.") not in inside]


def optional_amounts(notes: list[str]) -> set[float]:
    """Amounts that some note says outright are optional (a second space, an upgrade): another note that quotes the same figure is explained."""
    out: set[float] = set()
    for n in notes:
        if _OPTIONAL_NOTE.search(n) and not re.search(r"\b(?:required|mandatory)\b", re.sub(r"\b(?:ask|check)\b[^.]{0,30}\bif\b[^.]{0,30}\b(?:required|mandatory)\b|\bif it is (?:required|mandatory)\b", " ", n, flags=re.I), re.I):
            out.update(_amount_of(m) for m in _FIG.finditer(n))
    return out


# Cycle 28: a figure the listing itself took back. The correction notes ("The listing corrects the HOA: it is now $385 a month. The earlier $340 a month is
# not used.", "...says the rent dropped from $1,500 to $1,450... the old $1,500 is not used", "It first said $X ... the $X is the old price") name the old
# figure as not used. That figure is then closed everywhere (missing list, headline, Unknowns, Compare, Today), whatever other note quotes it.
_CORRECTION_NOTE = re.compile(r"\bThe listing (?:corrects|says the (?:rent|price) (?:dropped|was cut))|\bcorrects itself\b|\bwas a mistake or an old figure\b|\bis the old price\b|\bfirst said\b|\bprice was cut from\b|\b(?:earlier|old|previous|first)\b[^.\n]{0,40}\b(?:is|are) not used\b", re.I)
_SUPERSEDED_BEFORE = re.compile(r"\b(?:earlier|old|older|previous|previously|first said|first|was|were|from|originally|formerly|not)\b[^$.\n]{0,24}$", re.I)
_SUPERSEDED_AFTER = re.compile(r"^[^$.\n]{0,40}?\b(?:is|are) (?:the )?(?:not used|old|an old|a mistake)\b|^[^$.\n]{0,40}?\bwas a mistake\b", re.I)
_NEW_BEFORE = re.compile(r"\b(?:now|then says|to|later value|current|new)\b[^$.\n]{0,12}$", re.I)


def superseded_amounts(notes: list[str]) -> set[float]:
    """The dollar figures that a correction note says are no longer used (see above). Decided from the saved correction notes only."""
    out: set[float] = set()
    for n in notes:
        if not _CORRECTION_NOTE.search(n):
            continue
        for m in _FIG.finditer(n):
            before = n[max(0, m.start() - 40):m.start()]
            after = n[m.end():m.end() + 60]
            if _NEW_BEFORE.search(before) and not _SUPERSEDED_AFTER.search(after):
                continue
            if _SUPERSEDED_BEFORE.search(before) or _SUPERSEDED_AFTER.search(after):
                out.add(_amount_of(m))
    return out


# Cycle 28: a figure the listing itself took back. The correction notes ("The listing corrects the HOA: it is now $385 a month. The earlier $340 a month is
# not used.", "...the rent dropped from $1,500 to $1,450... the old $1,500 is not used", "It first said $X ... the $X is the old price") name the old figure
# as not used. That figure is then closed everywhere (missing list, headline, Unknowns, Compare, Today), whatever other note quotes it.
_CORRECTION_NOTE = re.compile(r"\bThe listing (?:corrects|says the (?:rent|price) (?:dropped|was cut))|\bcorrects itself\b|\bwas a mistake or an old figure\b|\bis the old price\b|\bfirst said\b|\bprice was cut from\b|\b(?:earlier|old|previous|first)\b[^.\n]{0,40}\b(?:is|are) not used\b", re.I)
_SUPERSEDED_BEFORE = re.compile(r"\b(?:earlier|old|older|previous|previously|first said|first|was|were|from|originally|formerly)\b[^$.\n]{0,24}$", re.I)
_SUPERSEDED_AFTER = re.compile(r"^[^$.\n]{0,40}?\b(?:is|are) (?:the )?(?:not used|old|an old|a mistake)\b|^[^$.\n]{0,40}?\bwas a mistake\b", re.I)
_NEW_BEFORE = re.compile(r"\b(?:now|then says|to|later value|current|new)\b[^$.\n]{0,12}$", re.I)


def superseded_amounts(notes: list[str]) -> set[float]:
    """The dollar figures that a correction note says are no longer used (see above). Decided from the saved correction notes only."""
    out: set[float] = set()
    for n in notes:
        if not _CORRECTION_NOTE.search(n):
            continue
        for m in _FIG.finditer(n):
            before = n[max(0, m.start() - 40):m.start()]
            after = n[m.end():m.end() + 60]
            if _NEW_BEFORE.search(before) and not _SUPERSEDED_AFTER.search(after):
                continue
            if _SUPERSEDED_BEFORE.search(before) or _SUPERSEDED_AFTER.search(after):
                out.add(_amount_of(m))
    return out


def figure_closed(note: str, start: int, end: int, optional: set[float] | frozenset[float] = frozenset(), superseded: set[float] | frozenset[float] = frozenset()) -> str:
    """Why the figure ``m`` of ``note`` is never a missing monthly amount: "zero", "superseded", "deposit", "explained", "optional" or "" (still open)."""
    fm = _FIG.search(note[start:end])
    amount = _amount_of(fm) if fm else -1.0
    if amount == 0:
        return "zero"
    if amount in superseded:
        return "superseded"
    if figure_explained(note, start, end):
        return "explained"
    piece = _figure_piece(note, start, end)
    if re.search(r"\bdeposits?\b", piece, re.I) and not re.search(r"\b(?:zelle|venmo|cash ?app|paypal|wire|western union|gift cards?|crypto\w*|bitcoin|send|hold(?:ing)?|before|upfront|up front)\b", piece, re.I) and not re.search(r"^\s*(?:/\s*(?:mo|month)\b|per\s+month|a\s+month|monthly|each\s+month)", note[end:end + 20], re.I):
        return "deposit"  # cycle 28: a deposit is cash at move-in, never a monthly amount left out
    if _EXPL_SECOND.search(piece) and not re.search(r"\b(?:required|mandatory)\b", piece, re.I):
        return "optional"
    if re.search(r"\bupgrades?\b|\boptional\b|\bif you want\b|\byour choice\b|\bby request\b|\badd[- ]ons?\b", piece, re.I) and not re.search(r"\b(?:required|mandatory)\b", piece, re.I):
        return "optional"
    if amount in optional and not re.search(r"\b(?:required|mandatory)\b", re.sub(r"\b(?:ask|check)\b[^.]{0,30}\bif\b[^.]{0,30}\b(?:required|mandatory)\b", " ", note, flags=re.I), re.I):
        return "optional"
    return ""


def note_figures_explained(note: str, optional: set[float] | frozenset[float] = frozenset(), superseded: set[float] | frozenset[float] = frozenset()) -> bool:
    """True when the note has dollar figures and every one of them is closed: another lease length, another plan, a special, a one-time or pending
    amount, an old price, a $0, or an optional extra (see ``figure_closed``)."""
    figs = _note_figures(note)
    return bool(figs) and all(figure_closed(note, m.start(), m.end(), optional, superseded) for m in figs)


def _note_is_stale(note: str, place: dict[str, Any] | None) -> bool:
    """True when every dollar amount in an "it is not counted" note is a value the place now holds in a field (or part of a sum a
    field holds): the note repeats what was counted, so it must not set the tag."""
    if not place or not re.search(r"\$\s?\d", note):
        return False
    try:
        from .parsers import note_amounts_placed
        return note_amounts_placed(note, place)
    except Exception:
        return False


def open_listing_notes(reader_notes: Any, place: dict[str, Any] | None = None) -> list[str]:
    """The saved reader notes that still hold a money note that is open: an amount, fee or cost the reader saw and did
    not count or could not place. ``place`` (its saved fields) lets a note whose amounts are all counted in a field count as closed."""
    out: list[str] = []
    whole = " ".join(str(reader_notes or "").split())
    if "\n" not in str(reader_notes or "").strip() and _note_is_stale(whole, place):
        return out  # one saved note whose sentences were cut apart: judged as one note, every amount in it is already counted
    optional = optional_amounts(note_units(reader_notes))
    superseded = superseded_amounts(note_units(reader_notes))
    if "\n" not in str(reader_notes or "").strip() and note_figures_explained(whole, optional, superseded):
        return out  # cycle 25: one saved note whose every figure is explained (a best-case deposit special, another lease length): its sentences without a figure are the same note
    for note in note_units(reader_notes):
        if ONE_TIME_NOTE.search(note):
            continue
        if re.match(r"The listing corrects the (?:utilities|beds?|baths?|bedrooms?|bathrooms?|laundry|parking|pets?)\b", note) and not _FIG.search(note):
            continue  # cycle 29: a correction that names a fact and no figure ("the tenant now pays all of them. The earlier line is not used") leaves no amount open
        if NOT_A_COST_NOTE.search(note):
            continue  # cycle 24: the note says the figure is another plan's price, an older rent, a deposit alternative or another lease length: it stays a note, never "missing"
        if _NOTE_BUY_PARKING.search(note):
            continue  # cycle 22: parking is never part of the cost of buying, so it is not a missing cost part there
        if _NOTE_WARNING.search(note) or (_NOTE_CHOICE.search(note) and place is not None and num(place.get("parking_cost")) is not None):
            continue  # a wire warning, or the other parking choices of a place whose parking is counted: not a cost left out of the number
        if re.search(r"\boptional\b", note, re.I) and not re.search(r"\b(?:required|mandatory)\b", note, re.I):
            continue  # an optional carport, garage or pool fee is not a cost you have to pay
        if re.search(r"\bseller\b[^.]*\b(?:credit|toward closing|concessions?|closing costs?|pays?|paid|contribut\w*)\b", note, re.I) and not re.search(r"\b(?:parking|garage|fee|deposit|hoa)\b", note, re.I):
            continue  # what the seller gives toward closing is about the cash to close, not a monthly cost the buyer left out
        if _note_is_stale(note, place):
            continue
        if re.search(r"\bassessments?\b", note, re.I) and not re.search(r"\bmonthly\b|per month|/\s*mo\b|a month|\b(?:parking|garage|fee|deposit|hoa|dues|utilit\w*|insurance|tax)\b", re.sub(r"\bspecial assessments?\b", " ", note, flags=re.I), re.I):
            continue  # cycle 25: a special assessment (pending or not) is one-time money, handled by the cash to close, never a missing monthly amount
        if note_figures_explained(note, optional, superseded):
            continue  # cycle 25: every figure in the note is another lease length, another plan, a special, a one-time or pending amount or an old price
        if place is not None and _FIG.search(note):
            vals, used_, placed_ = _note_open_figures(note, place, optional, superseded)
            if not any(v not in placed_ and (_util_names_of(note, a) or round(v, 2) not in used_) for v, a in vals.items()):
                continue  # cycle 26: every figure is closed by meaning or placed by a field (a $35 electric counted, a $60 optional space): nothing is left out
        if _NOTE_CLOSED.search(note) and not re.search(r"\bOnly [^.]{1,80} of that\b", note):
            continue  # "counted once in other monthly fees", "not counted again": the note says the money IS counted
        zero_figs = [m.group(1).replace(",", "") for m in _FIG.finditer(note)]
        if zero_figs and all(re.fullmatch(r"0+(?:\.0+)?", z) for z in zero_figs):
            continue  # cycle 26: a $0 figure ("1-car garage included ($0)") is free, never a cost left out
        if _NOTE_CONDITIONAL.search(note):
            continue  # a deposit that only applies on a condition ("if credit is poor") is a question for the landlord, not a cost left out of the monthly number
        if _NOTE_PLACED.search(note) and not re.search(r"not counted|no amount|not saved", note, re.I):
            continue  # "The $25 credit check fee is saved as the application fee. Ask if each adult pays it.": the amount is placed
        if _NO_AMOUNT_OPTIONAL.search(note) and not re.search(r"\$\s?\d", note):
            continue  # an optional carport with no price: nothing to add up
        probe = note if re.search(r"\$\s?\d", note) else re.sub(r"\b(?:what|how much)\b[^.]{0,30}\bcosts?\b", " ", note, flags=re.I)  # "ask what they cost" is no amount
        if not re.search(r"\$\s?\d", note) and not _NOTE_COST_WORD.search(probe):
            continue  # no amount and no cost word: a lease-term question ("month to month") is not money left out
        if _NOTE_OPEN.search(note) and _NOTE_MONEY.search(probe):
            out.append(note)
    return out


def listing_notes_uncounted(reader_notes: Any, place: dict[str, Any] | None = None) -> bool:
    """True when the saved reader notes still hold a money note that is open. The one test behind the "some amounts in the
    listing notes aren't counted" tag."""
    return bool(open_listing_notes(reader_notes, place))


_OPEN_KIND = re.compile(r"\b(flat fee|amenity fee|pool fee|pool|trash fee|parking fee|parking|garage|deposit|hoa|insurance|assessment|pet fee|pet rent|application fee|move-in fee|fee)\b", re.I)


_OPEN_KIND_WORDS = {"parking": "parking cost", "garage": "garage cost", "pool": "pool fee", "hoa": "HOA", "assessment": "assessment", "deposit": "deposit"}


def _amount_list(amounts: list[str]) -> str:
    return amounts[0] if len(amounts) == 1 else ", ".join(amounts[:-1]) + " and " + amounts[-1]


_THING_STOP = frozenset("the a an and also says say of for per each every this that it is are be to in on at or with only extra any one two monthly month mo yearly year flat total about approx roughly est by".split())


def _quoted_line_holds(note: str, amount: str) -> bool:
    qm = re.search(r'"([^"]*)"', note)
    return bool(qm and amount in qm.group(1))


def _nearest_kind(note: str, amount: str) -> re.Match[str] | None:
    """The kind word (fee, deposit, parking...) that the listing gives this amount, inside the note's quote: the label right after it ("$35 monthly
    fee") or the one right in front of it ("Security deposit $1,380", "Deposit: $500"). A label that belongs to the figure next to it ("$300 deposit
    and $35 monthly fee": the deposit is the $300) is never the $35's. None when no label is the figure's own: the headline then says "amount"."""
    qm = re.search(r'"([^"]*)"', note)
    if not qm or amount not in qm.group(1):
        return None
    q = qm.group(1)
    at = q.index(amount)
    after = q[at + len(amount):]
    before = q[:at]
    m = _OPEN_KIND.match(re.sub(r"^\s*(?:/\s*mo\w*|per month|a month|monthly|each|one[- ]time|non-?refundable|refundable|flat|extra|annual|yearly)?\s*", "", after, count=1, flags=re.I))
    if not m:
        m = re.match(r"\s*(?:(?!and\b|or\b|plus\b|per\b)[A-Za-z-]+\s+){1,2}(?=" + _OPEN_KIND.pattern + ")", after, re.I)
        m = _OPEN_KIND.match(after[m.end():]) if m else None
    if m:
        return m
    b = re.search(r"(?:^|[\s,;(])(" + _OPEN_KIND.pattern[3:-3] + r")\s*(?:of|is|are|:|-|\()?\s*$", before, re.I)
    if b:
        return _OPEN_KIND.search(b.group(1))
    return None


_UTIL_WORDS = (("electric", re.compile(r"\b(?:electric(?:ity)?|power|pg&e)\b", re.I)), ("gas", re.compile(r"\bgas\b", re.I)), ("heat", re.compile(r"\bheat(?:ing)?\b", re.I)),
               ("water", re.compile(r"\bwater\b", re.I)), ("sewer", re.compile(r"\bsewer\b", re.I)), ("trash", re.compile(r"\b(?:trash|garbage)\b", re.I)),
               ("internet", re.compile(r"\b(?:internet|wi-?fi|cable)\b", re.I)))
_UTIL_ITEM_SPLIT = re.compile(r"[,;|\n]|\bplus\b|\band\b(?![ \t]*(?:sewer|trash|garbage|internet|gas))|[ \t][-\u2013\u2014][ \t]|[ \t]\*[ \t]|[ \t]~[ \t]|\.(?=\s|$)")
_NOT_UTIL_ITEM = re.compile(r"\b(?:fees?|parking|garage|carport|deposit|pets?|hoa|dues|insurance|application|admin|permit|locker|storage|valet|pest|lawn|amenity)\b", re.I)


def _util_names_of(note: str, amount: str) -> list[str]:
    """The utilities named by the item of the note's quote that holds ``amount`` ("Water/sewer $55 (bi-monthly $110)" gives water and sewer);
    [] when that item is not a utility item."""
    qm = re.search(r'"([^"]*)"', note)
    if not qm or amount not in qm.group(1):
        return []
    for item in _UTIL_ITEM_SPLIT.split(qm.group(1)):
        if amount in item and not _NOT_UTIL_ITEM.search(item):
            return [name for name, pat in _UTIL_WORDS if pat.search(item)]
    return []


def open_notes_util_names(reader_notes: Any, place: dict[str, Any] | None = None) -> list[str]:
    """Cycle 22: the utilities (water, sewer, internet...) whose amounts sit in the open notes and are not counted. [] when none."""
    names, _label = _open_notes_parts(reader_notes, place)
    return names


def open_notes_label(reader_notes: Any, place: dict[str, Any] | None = None) -> str:
    return _open_notes_parts(reader_notes, place)[1]


_RENT_LIKE_COST_WORD = re.compile(r"\bdeposit|\bfees?\b|\bdues\b|\btax|insurance|\bhoa\b|parking|garage|carport|\bpets?\b|\bdog|\bcats?\b|utilit|electric|\bgas\b|\bwater\b|sewer|trash|internet|cable|storage|locker|"
                                  r"amenity|package|valet|permit|admin|application|cleaning|\bkeys?\b|\bfobs?\b|\bgym\b|\bpool\b|\bspace\b|\bspot\b|concession|credit|\bmove-?in\b|assessment|closing|\bpaid\b|\bpays?\b", re.I)


def _rent_like_figure(note: str, start: int, end: int, place: dict[str, Any] | None) -> bool:
    """A figure with no cost word of its own ("Nice place $1,550") that sits near the saved rent is another rent or a price, not an extra monthly
    amount left out: the note still quotes it, the headline and the missing list do not name it."""
    price = num((place or {}).get("price"))
    fm = _FIG.search(note[start:end])
    if not price or not fm:
        return False
    amount = _amount_of(fm)
    if not (0.6 * price <= amount <= 1.6 * price) or amount == price:
        return False
    return not _RENT_LIKE_COST_WORD.search(_figure_piece(note, start, end))


def _note_open_figures(note: str, place: dict[str, Any] | None, optional: set[float] | frozenset[float] = frozenset(), superseded: set[float] | frozenset[float] = frozenset()) -> tuple[dict[float, str], set[float], set[float]]:
    """The figures of a note that are not closed by meaning (see ``figure_closed``), with the amounts the place's fields hold (``used``) and the
    ones its fields place for this note (``placed``)."""
    used: set[float] = set()
    placed: set[float] = set()
    values = {float(m.group(0).replace(" ", "").rstrip(",.").lstrip("$").replace(",", "")): m.group(0).replace(" ", "").rstrip(",.")
              for m in _note_figures_loose(note) if not figure_closed(note, m.start(), m.end(), optional, superseded) and not _rent_like_figure(note, m.start(), m.end(), place)}  # cycle 25: an explained figure is never named as missing
    if place:
        try:
            from .parsers import _CURRENT_EXTRA, _NET_NOTE, _NET_REAL_FIELDS, _field_sums, _net_used_numbers, placed_amounts
            fields = {k: v for k, v in place.items() if v is not None and k in _NET_REAL_FIELDS + _CURRENT_EXTRA}
            if place.get("listing_text"):
                fields["_text"] = str(place["listing_text"])
            used = {round(u, 2) for u in _net_used_numbers(fields, [], str(place.get("listing_text") or "")) | _field_sums(place)}
            placed = placed_amounts(set(values), used, _field_sums(place), note, fields, semantic=not _NET_NOTE.match(note))  # cycle 23: a last-check note is settled only by a field holding the figure itself
        except Exception:
            used, placed = set(), set()
    return values, used, placed


def _open_notes_parts(reader_notes: Any, place: dict[str, Any] | None = None) -> tuple[list[str], str]:
    """A few words for what is open in the notes, naming the amounts: "the $75 flat fee in the listing notes" for one amount,
    "the $96 and $40 amounts in the listing notes" for several (up to four), else the generic "some amounts in the listing notes"."""
    notes = open_listing_notes(reader_notes, place)
    if not notes:
        return [], LISTING_NOTES_UNCOUNTED
    ranges = [n for n in notes if _RENT_RANGE_NOTE.search(n)]
    if ranges:  # a rent range names the rent, not two loose amounts
        rest = [n for n in notes if n not in ranges]
        other = open_notes_label("\n".join(rest), place) if rest else ""
        return [], (RENT_RANGE_LABEL if not other else f"{other} and {RENT_RANGE_LABEL}")
    optional = optional_amounts(note_units(reader_notes))
    superseded = superseded_amounts(note_units(reader_notes))
    seen: dict[float, str] = {}
    unplaced: dict[float, str] = {}
    named: dict[float, list[str]] = {}
    for note in notes:
        values, used, placed = _note_open_figures(note, place, optional, superseded)
        values = {v: a for v, a in values.items() if v != 0}  # cycle 26 join: a $0 figure is free, never named as missing
        for value, amount in values.items():
            seen.setdefault(value, amount)
            util = _util_names_of(note, amount)
            if value not in placed and (util or round(value, 2) not in used):  # a utility figure is placed by the estimate only, never by an equal figure elsewhere
                unplaced.setdefault(value, amount)
                if util:
                    named.setdefault(value, util)
    amounts = [a for v, a in unplaced.items() if v not in named]  # an amount a field already counts is never named as left out
    names = list(dict.fromkeys(n for v in named for n in named[v]))
    if names and not amounts:
        return names, _amount_list(names)  # "water and sewer": the things, not the figures
    if len(amounts) == 1 and len(notes) == 1 and not names:
        kind = _nearest_kind(notes[0], amounts[0])
        if kind is None and not _quoted_line_holds(notes[0], amounts[0]):
            kind = _OPEN_KIND.search(notes[0])  # cycle 23: a quoted line gives the figure its own label or none ("the $35 amount"); only a note with no quote is searched whole
        kind_word = _OPEN_KIND_WORDS.get(kind.group(1).lower(), kind.group(1).lower()) if kind else "amount"
        if kind_word == "deposit":  # cycle 27: a deposit in a parking, pet, key or other named clause is that deposit, never the security deposit
            nd = re.search(r"\b(parking|pet|key|garage|holding|reservation|storage|fob|cleaning|gate|access|mailbox|locker|bike|pool|move-in)[ \t]+deposit\b[^\"]{0,6}" + re.escape(amounts[0]), notes[0], re.I)
            if nd:
                kind_word = f"{nd.group(1).lower()} deposit"
        return names, f"the {amounts[0]} {kind_word} in the listing notes"
    if 1 <= len(amounts) <= 4:
        return names, f"the {_amount_list(amounts)} amount{'s' if len(amounts) > 1 else ''} in the listing notes"
    if not amounts:
        kinds = []
        for note in notes:
            kind = _OPEN_KIND.search(note)
            word = _OPEN_KIND_WORDS.get(kind.group(1).lower(), kind.group(1).lower()) if kind else ""
            if word == "fee":
                fm = next((x for src in (note, " ".join(str(reader_notes or "").split())) for x in re.finditer(r"\b([A-Za-z][A-Za-z-]{2,})[ \t]+fees?\b", src)
                           if x.group(1).lower() not in _THING_STOP), None)
                if fm:
                    word = f"{fm.group(1).lower()} fee"  # "the broker fee in the listing notes", not "the fee"
            if word and word not in kinds:
                kinds.append(word)
        if kinds and len(kinds) <= 3:
            return names, f"the {_amount_list(kinds)} in the listing notes"
    return names, LISTING_NOTES_UNCOUNTED


def _label_already_named(label: str, out: dict[str, Any]) -> bool:
    """True when every thing a no-amount label ("the parking cost in the listing notes", "the broker fee and the parking cost in the listing
    notes") names is already named by the cost's own missing or not-counted list."""
    m = re.fullmatch(r"the (.+?) in the listing notes", label)
    if not m:
        return False
    have = " ".join([*(str(x) for x in out.get("missing") or []), *(str(x) for x in out.get("uncounted") or [])]).lower()
    things = [t.strip() for t in re.split(r",\s*|\s+and\s+", m.group(1)) if t.strip()]
    return bool(things) and all(t.lower() in have for t in things)


def true_monthly_cost(place: dict[str, Any], mode: str = "rent", settings: dict[str, Any] | None = None,
                      people: Any = 1, pets: bool = True, adults: Any = None) -> dict[str, Any]:
    """Rent or buy breakdown depending on the search's mode. ``people`` (people sharing the cost) adds
    ``people`` and, when more than one, ``per_person``. ``headline`` is the line to show next to the total.
    ``pets`` False means the search has no pets: pet charges are left out (see ``rent_cost``). Rent only.
    ``adults`` (adults who sign the lease, None = same as ``people``): the cost is split between them, so kids are not
    counted as paying, and a per-adult application fee is multiplied by it. ``people`` in the result is the number the
    cost is split between and ``split_noun`` is "adults" or "people"."""
    try:
        n = max(1, int(people or 1))
    except (TypeError, ValueError):
        n = 1
    a = num(adults)
    explicit = a is not None and a >= 1 and mode != "buy"
    n = int(a) if explicit else n
    out = buy_cost(place, settings) if mode == "buy" else rent_cost(place, pets, n)
    noun = "adults" if explicit and mode != "buy" else "people"
    names, label = ([], "")
    if listing_notes_uncounted(place.get("reader_notes"), place):
        names, label = _open_notes_parts(place.get("reader_notes"), place)
        if not names and "$" not in label and _label_already_named(label, out):
            label = ""  # cycle 30: "the parking cost in the listing notes" next to "parking cost": one unknown is named once
    if label:
        out["listing_notes_label"] = label
        out["listing_notes_names"] = names  # cycle 22: the utilities (water, internet) behind the label; the headline folds them into the utilities it already names
        out["uncounted"] = list(out.get("uncounted") or []) + [LISTING_NOTES_UNCOUNTED]  # see the place page: "From the listing when it was added"
        out["notes"] = list(out.get("notes") or []) + ["The listing had things this cost does not cover. See the listing notes on this page."]
    # "all in" is only said when nothing the listing gave is left out: a buyer's one-time fee that is not counted keeps it from reading "all in" too
    one_time_left = mode == "buy" and any(ONE_TIME_NOTE.search(u) and re.search(r"not counted|not saved|not used|not in the monthly cost", u, re.I) and re.search(r"\$\s?\d", u)
                                          and not _note_is_stale(u, place) for u in note_units(place.get("reader_notes")))
    out["all_in"] = not out.get("uncounted") and not out.get("missing") and not one_time_left
    out["people"] = n
    out["split_noun"] = noun
    out["per_person"] = _r(out["total"] / n) if out["total"] is not None and n > 1 else None
    out["headline"] = headline(out, 1)
    out["headline_each"] = headline(out, n, noun)
    return out
