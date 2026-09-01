"""What has to travel with a newborn who is being sent on.

Phase 5 of EMERGENCY_NEWBORN_PLAN.md.

A clinic does not run a neonatal unit; it decides a baby needs one and sends
them. The referral for that already exists — `Visit.referred_to` and its note,
reversible, with a screen. What was missing is everything a receiving unit
asks on the phone and a clinic then reads out from four different places while
somebody holds a baby.

So this assembles it: gestation as it was written, birth weight, **hours** of
age rather than days, the bilirubin readings with the times they were drawn,
and what the clinic already recorded about feeding and risk.

**It gathers; it does not decide.** Nothing here says a baby should be
transferred, and nothing here produces a threshold — that is
`app/utils/jaundice.py`, and it answers only when a clinician has accepted its
table. What this adds is that the facts leave the building together and in the
same words the file holds them in.

**And it says what is missing, out loud.** A summary that silently omits the
gestation because nobody recorded it reads as a term baby. Every field this
cannot fill is named in `missing`, so the sheet says "not recorded" where a
unit would otherwise assume.
"""
WANTED = ("gestation", "birth_weight", "age_hours", "bilirubin")


def _bilirubin_series(patient, limit=6):
    """Readings with the hour each was drawn at, newest first.

    Taken from the measurements the clinic already records rather than a new
    place to type them: a second store would mean two answers to "what was his
    bilirubin yesterday", which is the argument this program keeps having with
    itself and keeps settling the same way.
    """
    from app.models import Measurement

    rows = (Measurement.query
            .filter(Measurement.patient_id == patient.id,
                    Measurement.code == "bilirubin")
            .order_by(Measurement.recorded_at.desc(),
                      Measurement.id.desc()).limit(limit).all())
    # `recorded_at`, which is when the reading was **taken** — not when the row
    # was created. On a value phoned in from a lab those are different days,
    # and a transfer sheet that dated a bilirubin by the moment somebody typed
    # it would put a rising baby's readings in the wrong order.
    return [{"value": row.value, "unit": row.unit,
             "taken_at": row.recorded_at} for row in rows]


def summary(patient, visit=None):
    """Everything the receiving unit needs, and a list of what is not there."""
    gestation = None
    if patient.gestation_weeks is not None:
        gestation = f"{patient.gestation_weeks}+{patient.gestation_days or 0}"

    hours = patient.age_hours
    readings = _bilirubin_series(patient)

    out = {
        "patient": patient,
        "gestation": gestation,
        "preterm": patient.is_preterm,
        "birth_weight": patient.birth_weight_kg,
        "age_hours": round(hours, 1) if hours is not None else None,
        "age_days": patient.age_days,
        "baseline_spo2": patient.baseline_spo2,
        "bilirubin": readings,
        "allergies": (patient.allergies or "").strip() or None,
        "chronic": (patient.chronic_diseases or "").strip() or None,
        "vitals": getattr(visit, "vitals", None) if visit else None,
        "reason": (getattr(visit, "referral_note", None) or "").strip() or None,
        "sent_to": (getattr(visit, "referred_to", None) or "").strip() or None,
    }

    # Named rather than left blank. A sheet that omits the gestation because
    # nobody wrote it down reads, to whoever receives it, as a term baby.
    out["missing"] = [name for name, value in (
        ("gestation", gestation),
        ("birth_weight", out["birth_weight"]),
        ("age_hours", out["age_hours"]),
        ("bilirubin", readings or None),
    ) if not value]
    return out
