"""«Medical History Record» — the stay's admission history on paper.

The owner brought the hospital form (MR 4-1): the child, the room, the
treating doctor, the department, the date of admission, the diet, weight
and height; the nature and duration of the complaints «include circumstance
of admission»; the history of present illness; past, family and nutritional
history; the physician's signature and date. Its second page: the
medication reconciliation (drug, dose, continued · modify · stopped, the
drug-related problems, remarks) and the review of systems, sixteen of them,
«write detailed description even if no abnormality is detected».

Most of it is already written on the stay — the initial assessment (ICD.06),
the reconciliation at admission (MMS.10), the clinical pharmacist's
interventions, the diet order, the bed. The nutritional history and the
review of systems had nowhere to go, and now have ``HistoryReview``.

**Nothing on the page is the program's own words.** What the record holds
is printed with the hospital's own wording; what it does not is ruled lines
for a pen.
"""


def _diet(stay):
    """The diet ordered on this stay — the latest — or, while it is open,
    the one the child is on now. A record printed after discharge (the
    usual time) still says what the child ate."""
    from app.models.nutrition import DietOrder
    from app.utils import nutrition

    row = (DietOrder.query.filter(DietOrder.admission_id == stay.id)
           .order_by(DietOrder.ordered_at.desc(), DietOrder.id.desc()).first())
    if row is None and stay.is_open:
        row = nutrition.current_diet(stay.patient_id)
    return row


def _bed(stay):
    """The bed now, or the last one the child had."""
    if stay.bed is not None:
        return stay.bed
    stays = list(stay.stays or [])
    return stays[-1].bed if stays else None


def _reconciliation(stay):
    """The decisions at admission, one per medicine — the latest for each,
    in the order the medicines were first decided."""
    from app.utils import med_reconciliation as mr

    rows = list(reversed(mr.decisions(stay, mr.ADMISSION)))
    latest = {}
    for row in rows:
        latest[row.item_key] = row
    seen, out = set(), []
    for row in rows:
        if row.item_key not in seen:
            seen.add(row.item_key)
            out.append(latest[row.item_key])
    return out


def build(stay, lang="ar"):
    from app.models.pharmacy_intervention import PharmacyIntervention
    from app.utils import medical_assessment as medass

    known = medass.assembled(stay)
    review = medass.review_for(stay.id)
    row = medass.for_stay(stay.id)
    from app.utils import measurements

    weight, height = measurements.during(stay.patient_id, stay.admitted_at,
                                         stay.discharged_at, which="first")
    bed = _bed(stay)
    unit = getattr(getattr(bed, "space", None), "unit", None)
    complaint = known.get("complaint", (None, None))[1]
    circumstance = (stay.reason or "").strip() or None
    diet = _diet(stay)

    def text(element):
        got = known.get(element)
        return got[1] if got else None

    return {
        "patient": stay.patient,
        "doctor": stay.responsible_doctor,
        "room": bed.place_name(lang) if bed is not None else None,
        "department": unit.display_name(lang) if unit is not None else None,
        "diet": diet.diet_name(lang) if diet is not None else None,
        "weight": weight, "height": height,
        "complaint": complaint,
        # «include circumstance of admission» — the reason for admission,
        # when it is not already the complaint printed above it.
        "circumstance": circumstance if circumstance and circumstance != complaint else None,
        "present_illness": text("present_illness"),
        "past_history": text("past_history"),
        "family": text("family"),
        "nutrition": (medass.nutrition_history(stay, review) or (None, None))[1],
        "assessed_by": row.by if row is not None else None,
        "assessed_at": row.at if row is not None else None,
        "reconciliation": _reconciliation(stay),
        "drps": (PharmacyIntervention.query.filter_by(admission_id=stay.id)
                 .order_by(PharmacyIntervention.created_at).all()),
        "systems": review.systems if review is not None else {},
        "reviewed_by": review.by if review is not None else None,
        "reviewed_at": (review.updated_at or review.at) if review is not None else None,
    }
