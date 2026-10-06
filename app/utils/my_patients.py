"""«مرضايا» — what a doctor has to do about their own children today.

The third board on the prototype the clinic agreed. Not a report about the
doctor; a work list for them: who they asked back and has not come, which of
their children with a long-standing problem has not been seen for a while,
whose vaccine is late — and, for their own reading, what they saw most.

**Whose children.** A child is a doctor's when that doctor saw them last.
Families move between doctors; the one who saw them last is the one whose
plan they are on, and a child counted under three doctors is followed by
none of them.

**Every rule is somebody else's, read from where it lives:**

* a follow-up's state is ``utils/followup`` — the same words the visit and
  the file use, so "missed" means one thing in the program;
* a late vaccine is ``vaccine_due.due_list`` — the clinic's own sweep, which
  only chases courses started here;
* a long-standing problem is the child's problem list (``PatientProblem``),
  and how long is too long without a visit is the doctor's choice on the
  screen, not a number the program invented.
"""
from collections import Counter
from datetime import timedelta

from app.extensions import db

#: The waits a doctor may pick for "not seen since", in months.
CHRONIC_MONTHS = (3, 6, 12)
DEFAULT_CHRONIC_MONTHS = 6
#: How many rows a work list shows per page.
PER_PAGE = 20
#: How far back a follow-up is still somebody's errand.
FOLLOWUP_LOOKBACK_DAYS = 365


def last_seen():
    """``{patient_id: (doctor_id, visit_date)}`` — who saw each child last."""
    from app.models import Visit

    latest = (db.session.query(Visit.patient_id, db.func.max(Visit.visit_date).label("d"))
              .group_by(Visit.patient_id).subquery())
    out = {}
    for pid, doc, day, vid in (db.session.query(Visit.patient_id, Visit.doctor_id,
                                                Visit.visit_date, Visit.id)
                               .join(latest, db.and_(latest.c.patient_id == Visit.patient_id,
                                                     latest.c.d == Visit.visit_date))
                               .order_by(Visit.id).all()):
        out[pid] = (doc, day)          # the last visit of that day wins
    return out


def mine(doctor_id, seen=None):
    """The active children this doctor saw last."""
    from app.models import Patient

    seen = seen if seen is not None else last_seen()
    ids = {pid for pid, (doc, _) in seen.items() if doc == doctor_id}
    if not ids:
        return set()
    return {pid for (pid,) in db.session.query(Patient.id)
            .filter(Patient.id.in_(ids), Patient.is_active.is_(True)).all()}


def _median(values):
    values = sorted(values)
    return values[len(values) // 2] if values else None


def figures(doctor_id, d_from, d_to):
    """The doctor's own numbers for a period — the medical board's row for
    them, plus how long their families waited."""
    from app.models import Appointment
    from app.utils import med_board

    row = next((r for r in med_board.doctors(d_from, d_to, on={})
                if r["doctor"].id == doctor_id), None)
    appts = (db.session.query(Appointment.status, Appointment.checked_in_at,
                              Appointment.started_at)
             .filter(Appointment.doctor_id == doctor_id,
                     Appointment.appt_date >= d_from, Appointment.appt_date <= d_to).all())
    waits = [(began - came).total_seconds() / 60 for _, came, began in appts
             if came and began and began >= came]
    booked = len(appts)
    return {
        "cases": row["cases"] if row else 0,
        "fresh": row["fresh"] if row else 0,
        "back_pct": row["back_pct"] if row else None,
        "consult": row["consult"] if row else None,
        "wait": _median(waits),
        "no_show_pct": (round(sum(1 for s, _, _ in appts if s == "no_show") * 100 / booked, 1)
                        if booked else None),
    }


def called_today(visit_ids, today=None):
    """The follow-ups somebody already rang about today."""
    from app.models import ActivityLog
    from app.utils.clock import local_today
    from app.utils.med_board import utc

    if not visit_ids:
        return set()
    today = today or local_today()
    start, end = utc(today, today)
    return {vid for (vid,) in db.session.query(ActivityLog.entity_id)
            .filter(ActivityLog.action == "followup.called",
                    ActivityLog.entity == "visit",
                    ActivityLog.entity_id.in_(list(visit_ids)),
                    ActivityLog.created_at >= start, ActivityLog.created_at < end).all()}


def followups(doctor_id, search=None, today=None):
    """The children this doctor asked back who have not come — latest first.

    ``[{visit, state, missed, late, called}]``. Only the latest instruction
    per child: a child told three times is one errand, about the last visit.
    """
    from app.models import Patient, Visit
    from app.utils import followup
    from app.utils.clock import local_today

    today = today or local_today()
    since = today - timedelta(days=FOLLOWUP_LOOKBACK_DAYS)
    query = (Visit.query
             .filter(Visit.doctor_id == doctor_id, Visit.visit_date >= since,
                     db.or_(Visit.followup_due.isnot(None),
                            Visit.followup_instructions.isnot(None))))
    search = (search or "").strip()
    if search:
        # The rule every patient search follows (`apply_patient_search`):
        # name, file, guardian, phone, date of birth.
        from app.utils.patients import apply_patient_search

        matched = apply_patient_search(db.session.query(Patient.id), search)
        query = query.filter(Visit.patient_id.in_(matched))
    visits = query.order_by(Visit.visit_date.desc(), Visit.id.desc()).all()
    latest = {}
    for v in visits:
        latest.setdefault(v.patient_id, v)
    rows = list(latest.values())
    states = followup.by_visit(rows)
    called = called_today([v.id for v in rows], today)
    out = []
    for v in rows:
        st = states.get(v.id, {})
        if st.get("state") not in followup.OUTSTANDING:
            continue
        due = v.followup_due or v.visit_date
        out.append({"visit": v, "state": st["state"], "missed": st.get("missed", 0),
                    "late": (today - due).days, "called": v.id in called})
    out.sort(key=lambda r: (-r["late"], r["visit"].id))
    return out


def found_elsewhere(search, limit=5):
    """The files a search matches when none of them is on the follow-up list
    — so «nobody by that name» is said only when there is nobody."""
    from app.models import Patient
    from app.utils.patients import apply_patient_search

    search = (search or "").strip()
    if not search:
        return []
    return (apply_patient_search(Patient.query.filter(Patient.is_active.is_(True)), search)
            .order_by(Patient.full_name).limit(limit).all())


def chronic_unseen(doctor_id, months=DEFAULT_CHRONIC_MONTHS, today=None, seen=None):
    """Children of this doctor with an active problem on their list who have
    not been seen for ``months`` — longest first."""
    from app.models import Patient
    from app.models.patient import PatientProblem
    from app.utils.clock import local_today
    from app.utils.vaccines import add_months

    today = today or local_today()
    months = months if months in CHRONIC_MONTHS else DEFAULT_CHRONIC_MONTHS
    cutoff = add_months(today, -months)
    seen = seen if seen is not None else last_seen()
    ids = {pid for pid in mine(doctor_id, seen) if seen[pid][1] <= cutoff}
    if not ids:
        return []
    problems = {}
    for pid, title in (db.session.query(PatientProblem.patient_id, PatientProblem.title)
                       .filter(PatientProblem.patient_id.in_(ids),
                               PatientProblem.status == "active")
                       .order_by(PatientProblem.id).all()):
        problems.setdefault(pid, []).append(title)
    people = {p.id: p for p in Patient.query.filter(Patient.id.in_(list(problems))).all()}
    out = [{"patient": people[pid], "problems": titles, "last": seen[pid][1],
            "days": (today - seen[pid][1]).days}
           for pid, titles in problems.items() if pid in people]
    out.sort(key=lambda r: -r["days"])
    return out


def late_vaccines(doctor_id, today=None, seen=None):
    """Overdue doses among this doctor's children — the clinic's own sweep,
    narrowed to them."""
    from app.utils.vaccine_due import due_list

    ids = mine(doctor_id, seen)
    if not ids:
        return []
    return [row for row in due_list(status="overdue", today=today)
            if row["patient"].id in ids]


def top_diagnoses(doctor_id, d_from, d_to, limit=5):
    """What this doctor wrote most — by code where there is one."""
    from app.models import Diagnosis, Visit

    counts = Counter()
    titles = {}
    for code, version, title, visit_id in (
            db.session.query(Diagnosis.code, Diagnosis.icd_version, Diagnosis.title,
                             Diagnosis.visit_id)
            .join(Visit, Diagnosis.visit_id == Visit.id)
            .filter(Visit.doctor_id == doctor_id, Visit.visit_date >= d_from,
                    Visit.visit_date <= d_to).distinct().all()):
        code = (code or "").strip()
        key = (code, version or "10") if code else ("", " ".join((title or "").split()).lower())
        counts[(key, visit_id)] = 1
        titles.setdefault(key, title)
    per = Counter(key for key, _ in counts)
    return [{"code": key[0], "version": key[1] if key[0] else None,
             "title": titles[key], "n": n} for key, n in per.most_common(limit)]


def top_drugs(doctor_id, d_from, d_to, limit=5):
    """What this doctor prescribed most, by the drug as written."""
    from app.models import Prescription, PrescriptionItem

    rows = (db.session.query(PrescriptionItem.drug_name,
                             db.func.count(PrescriptionItem.id))
            .join(Prescription, PrescriptionItem.prescription_id == Prescription.id)
            .filter(Prescription.doctor_id == doctor_id,
                    Prescription.rx_date >= d_from, Prescription.rx_date <= d_to)
            .group_by(PrescriptionItem.drug_name).all())
    merged = Counter()
    names = {}
    for name, n in rows:
        key = " ".join((name or "").split()).lower()
        if key:
            merged[key] += n
            names.setdefault(key, " ".join(name.split()))
    return [{"title": names[k], "n": n} for k, n in merged.most_common(limit)]
