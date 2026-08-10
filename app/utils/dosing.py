"""Paediatric dose calculation — by weight, by age, with the ceilings.

The arithmetic is the easy half; the half that matters is refusing to be
confidently wrong. Every result carries its warnings: below the minimum age
(ibuprofen under 6 months), above the daily ceiling (the classic Augmentin
overdose when a child is dosed like an adult), an adult maximum reached, no
weight recorded. The caller shows them — nothing here writes a prescription.
"""

WARN_MIN_AGE = "min_age"
WARN_MAX_AGE = "max_age"
WARN_MIN_WEIGHT = "min_weight"
WARN_DAILY_CAP = "daily_cap"
WARN_ADULT_CAP = "adult_cap"
WARN_NO_WEIGHT = "no_weight"
WARN_NO_RULE = "no_rule"


def _round_dose(mg):
    """Doses are read aloud and drawn in a syringe: 2 decimals, no float dust."""
    if mg is None:
        return None
    return round(mg + 1e-9, 2)


def calculate(generic, weight_kg=None, age_months=None, product=None,
              conc_mg_per_ml=None):
    """Work out one dose for this child.

    ``generic``  — a ``GenericDrug`` (the dosing rule lives there).
    ``product``  — an optional ``Drug`` row, used for its concentration so the
                   answer can be given in millilitres of that syrup.

    Returns a dict: ``dose_mg`` / ``daily_mg`` / ``ml`` / ``doses_per_day`` /
    ``band`` (matching age band, if any) / ``warnings`` (list of codes) /
    ``capped`` (True when a ceiling cut the dose down).
    """
    out = {
        "dose_mg": None, "dose_mg_max": None, "daily_mg": None, "ml": None,
        "ml_max": None, "doses_per_day": generic.doses_per_day if generic else None,
        "band": None, "warnings": [], "capped": False,
        "conc_mg_per_ml": None,
    }
    if generic is None:
        out["warnings"].append(WARN_NO_RULE)
        return out

    # --- eligibility --------------------------------------------------
    if age_months is not None:
        if generic.min_age_months is not None and age_months < generic.min_age_months:
            out["warnings"].append(WARN_MIN_AGE)
        if generic.max_age_months is not None and age_months > generic.max_age_months:
            out["warnings"].append(WARN_MAX_AGE)
        out["band"] = generic.band_for(age_months)
    if weight_kg is not None and generic.min_weight_kg is not None \
            and weight_kg < generic.min_weight_kg:
        out["warnings"].append(WARN_MIN_WEIGHT)

    # --- the arithmetic -----------------------------------------------
    per_day = generic.doses_per_day or 1
    if not generic.dose_per_kg:
        # Dosed by age band only (most syrups sold by the spoon).
        if out["band"] is not None:
            out["doses_per_day"] = out["band"].doses_per_day or per_day
            if out["band"].dose_mg:
                out["dose_mg"] = _round_dose(out["band"].dose_mg)
                out["daily_mg"] = _round_dose(out["band"].dose_mg
                                              * (out["doses_per_day"] or 1))
        else:
            out["warnings"].append(WARN_NO_RULE)
    elif weight_kg is None:
        out["warnings"].append(WARN_NO_WEIGHT)
    else:
        low, high = generic.dose_per_kg, generic.dose_per_kg_max or generic.dose_per_kg
        if generic.dose_basis == "per_day":
            dose_lo = weight_kg * low / per_day
            dose_hi = weight_kg * high / per_day
        else:
            dose_lo = weight_kg * low
            dose_hi = weight_kg * high

        # Ceilings, in order: mg/kg/day → adult per-dose → adult per-day.
        if generic.max_per_kg_day:
            # A hair of tolerance, because these two numbers are written to
            # agree and floating point disagrees. Adrenaline is 0.01 mg/kg a
            # dose with a 0.03 mg/kg/day ceiling over 3 doses: 0.03/3 is
            # 0.009999999999999998, so the anaphylaxis dose was reported as
            # *above its own daily ceiling* at 5, 10 and 20 kg — and not at 15
            # or 30, which is how a rounding bug looks from the outside.
            #
            # A false ceiling warning on the one drug where hesitating is what
            # kills is worse than no warning at all.
            cap = weight_kg * generic.max_per_kg_day / per_day
            cap_limit = cap * (1 + 1e-9)
            if dose_hi > cap_limit:
                dose_hi = cap
                out["capped"] = True
            if dose_lo > cap_limit:
                dose_lo = cap
                out["capped"] = True
                out["warnings"].append(WARN_DAILY_CAP)
        if generic.max_single_dose_mg:
            for key, value in (("lo", dose_lo), ("hi", dose_hi)):
                if value > generic.max_single_dose_mg:
                    out["capped"] = True
                    out["warnings"].append(WARN_ADULT_CAP)
            dose_lo = min(dose_lo, generic.max_single_dose_mg)
            dose_hi = min(dose_hi, generic.max_single_dose_mg)
        if generic.max_daily_dose_mg:
            per_dose_cap = generic.max_daily_dose_mg / per_day
            if dose_hi > per_dose_cap:
                out["capped"] = True
                if WARN_ADULT_CAP not in out["warnings"]:
                    out["warnings"].append(WARN_ADULT_CAP)
            dose_lo = min(dose_lo, per_dose_cap)
            dose_hi = min(dose_hi, per_dose_cap)

        out["dose_mg"] = _round_dose(dose_lo)
        out["dose_mg_max"] = _round_dose(dose_hi) if dose_hi != dose_lo else None
        out["daily_mg"] = _round_dose(dose_lo * per_day)
        out["doses_per_day"] = per_day

    # --- millilitres of the chosen syrup ------------------------------
    conc = conc_mg_per_ml or (product.conc_mg_per_ml if product is not None else None)
    if conc and out["dose_mg"]:
        out["conc_mg_per_ml"] = conc
        out["ml"] = round(out["dose_mg"] / conc, 2)
        if out["dose_mg_max"]:
            out["ml_max"] = round(out["dose_mg_max"] / conc, 2)
    # De-duplicate while keeping order (the UI prints them in this order).
    seen, warns = set(), []
    for w in out["warnings"]:
        if w not in seen:
            seen.add(w)
            warns.append(w)
    out["warnings"] = warns
    return out


def age_months_of(patient, on_date=None):
    """A patient's age in whole months (the unit every dosing table uses)."""
    from datetime import date

    if patient is None or not patient.date_of_birth:
        return None
    ref = on_date or date.today()
    dob = patient.date_of_birth
    months = (ref.year - dob.year) * 12 + (ref.month - dob.month)
    if ref.day < dob.day:
        months -= 1
    return max(months, 0)


def latest_weight_record(patient):
    """The most recent growth record carrying a weight, or ``None``.

    The row rather than the bare number, because a weight without its date is
    not something anybody can act on: 12 kg measured this morning and 12 kg
    measured last winter are the same number and a different dose. Whoever
    shows a weight to a human being needs the date beside it.
    """
    try:
        from app.models import GrowthRecord
        return (GrowthRecord.query
                .filter(GrowthRecord.patient_id == patient.id,
                        GrowthRecord.weight_kg.isnot(None))
                .order_by(GrowthRecord.record_date.desc()).first())
    except Exception:                                       # pragma: no cover
        return None


def latest_weight(patient):
    """The most recent recorded weight (kg), if the clinic has one."""
    row = latest_weight_record(patient)
    return row.weight_kg if row else None
