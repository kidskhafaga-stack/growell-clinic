"""Who is due a dose, across the whole clinic — and what to order for them.

Per-patient reminders already existed; what did not was the same question asked
of the clinic instead of the child. That is a different job, because the answers
are used differently: a list of names is for calling families, and the *same*
list totalled by brand is a purchase order.

Two rules carried over from the rest of the program.

**Only courses started here.** A clinic never chases a vaccine it never gave —
the child may be getting it somewhere else, and a reminder for a course this
clinic knows nothing about is a phone call that annoys a family.

**And the ordering question is not the reminder question.** A dose due in three
weeks belongs in the order (the vial has to be on the shelf when the child
arrives) but not in today's calling list. So the screen filters by *when*, and
the order is built from whatever the filter currently shows — the same
discipline as the invoice export: what you hand over is what you were looking
at.
"""
from datetime import date, timedelta
from app.utils.clock import local_today


def due_list(start=None, end=None, vaccine_id=None, brand_id=None,
             status=None, lang="ar", today=None):
    """Every pending dose in the clinic, newest urgency first.

    ``[{patient, vaccine, brand, dose_number, due_date, status}]``.

    ``start``/``end`` bound the **due date**, which is what makes this usable
    for two different jobs from one screen: "who do I call this week" and "what
    will I need next month". A row with no due date — a seasonal recall — is
    kept whatever the range, because its whole point is that it is due now.
    """
    from app.extensions import db
    from app.models import Patient, PatientVaccine
    from app.utils.vaccines import scan_due

    today = today or local_today()

    # ── Read flat, build objects for the survivors ────────────────────
    #
    # This walks every child who has ever had a dose here — on a clinic that
    # imported its history, that is the whole register — and returns a few
    # hundred rows. Loading it as model objects cost 22µs apiece in
    # change-tracking and lazy-load machinery for records nothing here
    # modifies: 15,000 patients and 75,000 doses is 90,000 objects and about
    # four seconds, to answer a question about a few hundred.
    #
    # So the sweep reads columns, and the patients that actually come out of it
    # are loaded properly in one more query. Callers still get a `Patient` and
    # can ask it for the family's phone number; what changed is that we no
    # longer build one for the fourteen thousand children with nothing due.
    #
    # The schedule itself is untouched: `scan_due` and the patient's own file
    # both run `course_dates`, and `test_flat_scan_agrees` holds them to the
    # same answer.
    # Who the sweep has anything to say about: a child who has had a dose
    # here, **or** one the doctor agreed a plan with. The second is the whole
    # point of a plan — its first dose can be late before any dose exists.
    from app.models.vaccine_plan import VaccinePlanItem, planned_by_patient

    rows = db.session.query(
        Patient.id, Patient.date_of_birth).filter(
        Patient.is_active.is_(True),
        db.or_(
            Patient.id.in_(
                db.session.query(PatientVaccine.patient_id)
                .filter(PatientVaccine.event_type == "given").distinct()),
            Patient.id.in_(
                db.session.query(VaccinePlanItem.patient_id).distinct()))).all()
    if not rows:
        return []

    doses = db.session.query(
        PatientVaccine.patient_id, PatientVaccine.vaccine_id,
        PatientVaccine.brand_id, PatientVaccine.dose_number,
        PatientVaccine.given_date, PatientVaccine.event_type).filter(
        PatientVaccine.patient_id.in_([r[0] for r in rows])).all()

    by_patient = {}
    for pid, vid, bid, dose_number, given_date, event_type in doses:
        by_patient.setdefault(pid, []).append(
            (vid, bid, dose_number, given_date, event_type))

    agreed = planned_by_patient([r[0] for r in rows])

    found = []
    for patient_id, dob in rows:
        for row in scan_due(dob, by_patient.get(patient_id, []), today,
                            agreed=agreed.get(patient_id, set())):
            if vaccine_id and row["vaccine"].id != int(vaccine_id):
                continue
            if brand_id and (not row["brand"] or row["brand"].id != int(brand_id)):
                continue
            if status and row["status"] != status:
                continue
            when = _as_date(row.get("due_date"))
            if when is not None:
                if start and when < start:
                    continue
                if end and when > end:
                    continue
            found.append((patient_id, {**row, "due": when}))

    if not found:
        return []
    people = {p.id: p for p in Patient.query.filter(
        Patient.id.in_({pid for pid, _ in found})).all()}

    out = [{**row, "patient": people[pid]} for pid, row in found
           if pid in people]
    out.sort(key=_urgency)
    return out


def _as_date(value):
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


_ORDER = {"overdue": 0, "due": 1, "seasonal": 2}


def _urgency(row):
    return (_ORDER.get(row["status"], 3), row["due"] or date.max)


def order_suggestion(rows, cover_days=None, today=None):
    """Turn a due list into "how many of each to buy".

    ``[{brand, vaccine, needed, in_stock, to_order}]``, biggest shortfall first.

    ``to_order`` is what is missing, not what is needed: a clinic that already
    has nine Rotarix on the shelf and eleven children due should be told to buy
    **two**. An order screen that restates the demand and ignores the fridge is
    one somebody has to redo by hand, which is the same as not having it.

    ``cover_days`` narrows the rows to doses due within that many days, so the
    same list answers "order for this month" without re-running anything.
    """
    today = today or local_today()
    horizon = today + timedelta(days=cover_days) if cover_days else None

    needed = {}
    for row in rows:
        brand = row.get("brand")
        if brand is None:
            continue                # no brand chosen yet — nothing to order
        if horizon and row["due"] and row["due"] > horizon:
            continue
        slot = needed.setdefault(brand.id, {
            "brand": brand, "vaccine": row["vaccine"], "needed": 0})
        slot["needed"] += 1

    out = []
    for slot in needed.values():
        stock = slot["brand"].stock or 0
        out.append({**slot, "in_stock": stock,
                    "to_order": max(slot["needed"] - stock, 0)})
    out.sort(key=lambda r: (-r["to_order"], -r["needed"]))
    return out


def summarise(rows):
    """Counts per status, for the chips at the top of the screen."""
    counts = {"overdue": 0, "due": 0, "seasonal": 0}
    for row in rows:
        if row["status"] in counts:
            counts[row["status"]] += 1
    counts["patients"] = len({row["patient"].id for row in rows})
    counts["total"] = len(rows)
    return counts
