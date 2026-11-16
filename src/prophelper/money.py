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
    if util is None:
        pays = _cost_pays(place)
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
            notes.append(note + ". Add a utilities estimate under Facts.")
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
        if unpriced:
            # The listing prices only part of what the tenant pays (for example trash billed back), so the rest is not counted yet.
            names = _join_words(unpriced)
            line["note"] = f"{note}. It covers only what the listing prices; you also pay {names}, not counted yet"
            missing.append(names)  # name only what is really missing ("electric and gas"), not the whole estimate
            uncounted.append(f"utilities ({names})")
            notes.append(f"You also pay {names}; not counted yet. Add them to your utilities estimate under Facts.")
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
        listed = [f"{lab} {_dollars(v)}" for lab, v in (("pet rent", pet_rent_listed), ("pet fee", num(place.get("pet_fee"))),
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
    detail = ", ".join(f"{label.lower()} ${amounts[k]:,.0f}" for k, label in one_time.items() if amounts[k])
    app_fee = num(place.get("application_fee")) or 0
    if app_fee and app_total != app_fee:
        detail = detail.replace(f"application fee ${app_total:,.0f}", f"application fee ${app_total:,.0f} (${app_fee:,.0f} each for {adults} adults)")
    one_line = _line("one_time", f"One-time fees spread over {months} months", spread, detail or "none entered")
    if all(place.get(k) in (None, "") for k in one_time):
        one_line["unset"] = True
    lines.append(one_line)
    if not place.get("lease_months"):
        notes.append(f"Lease length not filled in, so one-time fees are spread over {DEFAULT_LEASE_MONTHS} months.")
    deposit = num(place.get("deposit"))
    total = None if price is None else _r(sum(l["amount"] or 0 for l in lines))
    if deposit:
        notes.append(f"Deposit ${deposit:,.0f} is not included in the monthly cost because it comes back.")
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
                label = f"Application fee (${v:,.0f} each for {adults} adults)"
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
    if closing is None:
        pct = cfg.get("closing_cost_pct", DEFAULT_BUY["closing_cost_pct"])
        parts.append({"label": f"Closing costs (a guess: {pct:g}% of the price)", "amount": _r(price * pct / 100), "estimated": True})
    else:
        parts.append({"label": "Closing costs", "amount": _r(closing), "estimated": False})
    sa = num(place.get("special_assessment"))
    if sa and str(place.get("special_assessment_payer") or "") == "buyer":
        parts.append({"label": "Special assessment (you pay it)", "amount": _r(sa), "estimated": False})
    left_out: list[str] = []
    try:  # one-time fees the listing says the buyer pays at closing (capital improvement, reserve contribution, move-in fee)
        from .parsers import buyer_one_time_fees
        paid, unclear = buyer_one_time_fees(str(place.get("listing_text") or ""))
    except Exception:  # the listing text is only a hint
        paid, unclear = [], []
    for label, amount in paid:
        parts.append({"label": f"One-time fee at closing ({label})", "amount": _r(amount), "estimated": False})
    for label, amount in unclear:
        left_out.append(f"a {_dollars(amount)} {label} isn't counted because who pays it isn't known")
    if sa and str(place.get("special_assessment_payer") or "") not in ("buyer", "seller"):
        left_out.append(f"a {_dollars(sa)} special assessment isn't counted because who pays it isn't known")
    credit = num(place.get("seller_credit"))
    if credit and credit > 0:
        # The seller pays part of the closing costs, so it lowers the cash you bring (never below zero overall).
        # Cycle 23: a credit only pays closing costs, so it can't lower the cash below the down payment. It is capped at the closing costs line.
        closing_amount = next((p["amount"] for p in parts if p["label"].startswith("Closing costs")), 0)
        if credit > closing_amount:
            extra = credit - closing_amount
            left_out.append(f"{_dollars(extra)} of the {_dollars(credit)} seller credit isn't counted, because a credit can only pay the {_dollars(closing_amount)} closing costs "
                            "and can't lower the cash below the down payment")
            credit = closing_amount
        if credit:
            parts.append({"label": "Seller credit toward closing (comes off)", "amount": _r(-credit), "estimated": False})
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
    total = None if pi is None else _r(sum(l["amount"] or 0 for l in lines))
    cash = cash_to_close(place, cfg)
    sa, payer = num(place.get("special_assessment")), str(place.get("special_assessment_payer") or "")
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


def headline(cost: dict[str, Any], people: int = 1, noun: str = "people") -> str:
    """The one line next to the total: '$2,414/mo, insurance not counted yet' (and '$807 each' when people share it)."""
    total = cost.get("total")
    if total is None:
        return "Cost unknown"
    text = f"{_dollars(total)}/mo"
    unc = uncounted_display(cost)
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
    for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z])", " ".join(str(text or "").split())):
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
_NOTE_CLOSED = re.compile(r"\bcounted once\b|\bnot counted again\b|\balready counted\b|\bpaid through that flat fee\b|was a mistake or an old figure", re.I)  # cycle 20 join: a figure the listing takes back is not open
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
    for note in note_units(reader_notes):
        if ONE_TIME_NOTE.search(note):
            continue
        if _NOTE_BUY_PARKING.search(note):
            continue  # cycle 22: parking is never part of the cost of buying, so it is not a missing cost part there
        if _NOTE_WARNING.search(note) or (_NOTE_CHOICE.search(note) and place is not None and num(place.get("parking_cost")) is not None):
            continue  # a wire warning, or the other parking choices of a place whose parking is counted: not a cost left out of the number
        if re.search(r"\boptional\b", note, re.I) and not re.search(r"\b(?:required|mandatory)\b", note, re.I):
            continue  # an optional carport, garage or pool fee is not a cost you have to pay
        if re.search(r"\bseller\b[^.]*\b(?:credit|toward closing|concessions?|closing costs?)\b", note, re.I) and not re.search(r"\b(?:parking|garage|fee|deposit|hoa)\b", note, re.I):
            continue  # what the seller gives toward closing is about the cash to close, not a monthly cost the buyer left out
        if _note_is_stale(note, place):
            continue
        if _NOTE_CLOSED.search(note) and not re.search(r"\bOnly [^.]{1,80} of that\b", note):
            continue  # "counted once in other monthly fees", "not counted again": the note says the money IS counted
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


def _nearest_kind(note: str, amount: str) -> re.Match[str] | None:
    """The kind word (fee, deposit, parking...) closest to the amount inside the note's quote, so "$1,380 security deposit + $50 lease fee"
    names the $50 as a fee and never as the deposit. None when the note quotes nothing or no kind word sits beside the amount."""
    qm = re.search(r'"([^"]*)"', note)
    if not qm or amount not in qm.group(1):
        return None
    q = qm.group(1)
    at = q.index(amount)
    best = None
    for m in _OPEN_KIND.finditer(q):
        gap = at - m.end() if m.end() <= at else m.start() - (at + len(amount))
        if gap <= 25 and (best is None or gap < best[0]):
            best = (gap, m)
    return best[1] if best else None


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
    seen: dict[float, str] = {}
    unplaced: dict[float, str] = {}
    named: dict[float, list[str]] = {}
    for note in notes:
        used: set[float] = set()
        placed: set[float] = set()
        values = {float(r.replace(" ", "").rstrip(",.").lstrip("$").replace(",", "")): r.replace(" ", "").rstrip(",.") for r in re.findall(r"\$\s?\d[\d,]*(?:\.\d+)?", note)}
        if place:
            try:
                from .parsers import _CURRENT_EXTRA, _NET_REAL_FIELDS, _field_sums, _net_used_numbers, placed_amounts
                fields = {k: v for k, v in place.items() if v is not None and k in _NET_REAL_FIELDS + _CURRENT_EXTRA}
                if place.get("listing_text"):
                    fields["_text"] = str(place["listing_text"])
                used = {round(u, 2) for u in _net_used_numbers(fields, [], str(place.get("listing_text") or "")) | _field_sums(place)}
                placed = placed_amounts(set(values), used, _field_sums(place), note, fields)
            except Exception:
                used, placed = set(), set()
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
        kind = _nearest_kind(notes[0], amounts[0]) or _OPEN_KIND.search(notes[0])
        return names, f"the {amounts[0]} {_OPEN_KIND_WORDS.get(kind.group(1).lower(), kind.group(1).lower()) if kind else 'amount'} in the listing notes"
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
    if listing_notes_uncounted(place.get("reader_notes"), place):
        names, label = _open_notes_parts(place.get("reader_notes"), place)
        out["listing_notes_label"] = label
        out["listing_notes_names"] = names  # cycle 22: the utilities (water, internet) behind the label; the headline folds them into the utilities it already names
        out["uncounted"] = list(out.get("uncounted") or []) + [LISTING_NOTES_UNCOUNTED]  # see the place page: "From the listing when it was added"
        out["notes"] = list(out.get("notes") or []) + ["The listing had things this cost does not cover. See the listing notes on this page."]
    # "all in" is only said when nothing the listing gave is left out: a buyer's one-time fee that is not counted keeps it from reading "all in" too
    one_time_left = mode == "buy" and any(ONE_TIME_NOTE.search(u) and re.search(r"not counted|not saved|not used", u, re.I) and re.search(r"\$\s?\d", u)
                                          and not _note_is_stale(u, place) for u in note_units(place.get("reader_notes")))
    out["all_in"] = not out.get("uncounted") and not one_time_left
    out["people"] = n
    out["split_noun"] = noun
    out["per_person"] = _r(out["total"] / n) if out["total"] is not None and n > 1 else None
    out["headline"] = headline(out, 1)
    out["headline_each"] = headline(out, n, noun)
    return out
