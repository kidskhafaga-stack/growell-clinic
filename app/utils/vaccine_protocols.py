"""Courses counted in days from the first dose — rabies (``VaccineCourse``).

The protocols are the owner's decision, written down as they gave them:

* **after exposure, never vaccinated — WHO, intramuscular:** 4 doses on days
  0, 3, 7 and 14 (WHO allows the fourth between day 14 and 28);
* **after exposure, never vaccinated — the Egyptian protocol** published by
  the Egyptian Health Council: 5 doses on days 0, 3, 7, 14 and 28. The EDA
  leaflet of 2025 shows a different table, so the screen says to confirm the
  official source in force; the doctor chooses;
* **after exposure, vaccinated before:** 2 doses, days 0 and 3;
* **before exposure (pre-exposure), WHO:** 2 doses, days 0 and 7.

The intradermal schedules are a different regimen and are not mixed in here.
The number of doses never comes from the child's age; the program never picks
the protocol and never swaps one for another.
"""
from datetime import timedelta

from app.extensions import db

#: Per vaccine code: the protocols the doctor chooses from, in order.
PROTOCOLS = {
    "RABIES": [
        {"key": "pep_who4", "kind": "pep", "previously": False,
         "days": (0, 3, 7, 14), "source": "WHO",
         "ar": "بعد التعرّض — منظمة الصحة العالمية (٤ جرعات عضل)",
         "en": "Post-exposure — WHO (4 doses IM)",
         "note_ar": "الجرعة الرابعة من يوم ١٤ لحد يوم ٢٨.",
         "note_en": "The fourth dose from day 14 up to day 28."},
        {"key": "pep_eg5", "kind": "pep", "previously": False,
         "days": (0, 3, 7, 14, 28), "source": "Egyptian Health Council",
         "ar": "بعد التعرّض — البروتوكول المصري (٥ جرعات)",
         "en": "Post-exposure — Egyptian protocol (5 doses)",
         "note_ar": "منشور عند المجلس الصحي المصري؛ نشرة هيئة الدواء ٢٠٢٥ فيها جدول مختلف — اتأكد من المصدر الرسمي الساري.",
         "note_en": "Published by the Egyptian Health Council; the 2025 EDA leaflet shows a different table — confirm the official source in force."},
        {"key": "pep_previous", "kind": "pep", "previously": True,
         "days": (0, 3), "source": "WHO",
         "ar": "بعد التعرّض — متطعّم قبل كده (جرعتين)",
         "en": "Post-exposure — previously vaccinated (2 doses)",
         "note_ar": "", "note_en": ""},
        {"key": "prep_who", "kind": "prep", "previously": None,
         "days": (0, 7), "source": "WHO",
         "ar": "قبل التعرّض — منظمة الصحة العالمية (جرعتين)",
         "en": "Pre-exposure — WHO (2 doses)",
         "note_ar": "", "note_en": ""},
    ],
}
#: A dose of a course counted in days is "due" from the day before its date —
#: not the thirty days a schedule in months uses, which would call every dose
#: of a 28-day course due on day 0 and remind about all of them at once.
COURSE_DUE_DAYS = 1
CATEGORIES = ("I", "II", "III")
RIG_STATES = ("assess", "needed", "given", "not_needed")


class CourseError(ValueError):
    """A refusal with a key (``vcourse.err_<key>``)."""


def protocols_for(vaccine):
    return PROTOCOLS.get(getattr(vaccine, "code", None) or "", [])


def protocol(vaccine, key):
    return next((p for p in protocols_for(vaccine) if p["key"] == key), None)


def open_course(patient_id, vaccine_id):
    from app.models.vaccine_course import VaccineCourse

    return (VaccineCourse.query.filter_by(patient_id=patient_id, vaccine_id=vaccine_id)
            .filter(VaccineCourse.closed_at.is_(None))
            .order_by(VaccineCourse.id.desc()).first())


def open_by_vaccine(patient_id):
    """``{vaccine_id: course}`` — the child's open courses."""
    from app.models.vaccine_course import VaccineCourse

    rows = (VaccineCourse.query.filter_by(patient_id=patient_id)
            .filter(VaccineCourse.closed_at.is_(None)).all())
    return {c.vaccine_id: c for c in rows}


def open_by_patient(patient_ids):
    """``{patient_id: {vaccine_id: (start, days, first_number)}}`` for the
    register-wide sweep — plain values, the shape ``scan_due`` takes."""
    from app.models import Vaccine
    from app.models.vaccine_course import VaccineCourse

    if not patient_ids:
        return {}
    codes = dict(db.session.query(Vaccine.id, Vaccine.code).all())
    out = {}
    for c in (VaccineCourse.query.filter(VaccineCourse.patient_id.in_(list(patient_ids)),
                                         VaccineCourse.closed_at.is_(None)).all()):
        p = next((x for x in PROTOCOLS.get(codes.get(c.vaccine_id) or "", [])
                  if x["key"] == c.protocol), None)
        if p is not None:
            out.setdefault(c.patient_id, {})[c.vaccine_id] = (
                c.start_date, p["days"], c.first_dose_number or 1)
    return out


def course_rota(days, first_number):
    """``[(dose_number, None)]`` — the course's doses, numbered from
    ``first_number``; no age, because none of them is due by age."""
    return [(first_number + i, None) for i in range(len(days))]


def course_dates(start, days, first_number, given, planned, today):
    """``{dose_number: (due_date, status)}`` — the same shape as
    ``vaccines.course_dates``. Day 0 is the first dose's real date once it is
    given; every other dose is day 0 plus its day. A dose the doctor
    pencilled in for a date wins, as everywhere else."""
    anchor = given.get(first_number) or start
    out = {}
    for i, offset in enumerate(days):
        number = first_number + i
        due = anchor + timedelta(days=offset)
        if planned.get(number) and number not in given:
            due = planned[number]
        if given.get(number) is not None:
            status = "done"
        elif due < today:
            status = "overdue"
        elif (due - today).days <= COURSE_DUE_DAYS:
            status = "due"
        else:
            status = "upcoming"
        out[number] = (due, status)
    return out


def next_number(patient_id, vaccine):
    """The course's next dose number to give, or None when there is no open
    course (the ordinary rule applies) — ``0`` when the course is complete."""
    from app.models import PatientVaccine

    course = open_course(patient_id, vaccine.id)
    if course is None:
        return None
    p = protocol(vaccine, course.protocol)
    if p is None:
        return None
    given = {pv.dose_number for pv in PatientVaccine.query.filter_by(
        patient_id=patient_id, vaccine_id=vaccine.id, event_type="given").all()}
    for number, _ in course_rota(p["days"], course.first_dose_number or 1):
        if number not in given:
            return number
    return 0


def start(patient, vaccine, data, user):
    """Open a course. ``data``: protocol, start_date, previously_vaccinated
    ("1"/"0"/""), exposure_category, rig, notes. The caller commits."""
    from datetime import date, datetime

    from app.models import PatientVaccine
    from app.models.vaccine_course import VaccineCourse
    from app.utils.clock import local_today

    p = protocol(vaccine, data.get("protocol"))
    if p is None:
        raise CourseError("protocol")
    current = open_course(patient.id, vaccine.id)
    if current is not None:
        # A finished course closes itself when the next one begins — a second
        # bite years later. One still owing doses is the doctor's to stop.
        if next_number(patient.id, vaccine) == 0:
            current.closed_at = datetime.utcnow()
            current.close_reason = "completed"
            current.closed_by = getattr(user, "id", None)
        else:
            raise CourseError("already_open")
    try:
        start_on = date.fromisoformat(data.get("start_date") or "") \
            if data.get("start_date") else local_today()
    except ValueError:
        raise CourseError("date") from None
    if start_on > local_today():
        raise CourseError("future")
    prev = data.get("previously_vaccinated")
    previously = True if prev == "1" else False if prev == "0" else None
    category = data.get("exposure_category") if data.get("exposure_category") in CATEGORIES else None
    rig = data.get("rig") if data.get("rig") in RIG_STATES else None
    if p["kind"] == "pep" and not previously and rig is None:
        # Never vaccinated after an exposure: the question of the
        # immunoglobulin is asked every time, and stays on the card until a
        # person answers it.
        rig = "assess"
    highest = (db.session.query(db.func.max(PatientVaccine.dose_number))
               .filter_by(patient_id=patient.id, vaccine_id=vaccine.id,
                          event_type="given").scalar()) or 0
    course = VaccineCourse(
        patient_id=patient.id, vaccine_id=vaccine.id, protocol=p["key"],
        start_date=start_on, first_dose_number=highest + 1,
        previously_vaccinated=previously, exposure_category=category, rig=rig,
        notes=(data.get("notes") or "").strip()[:300] or None,
        chosen_by=getattr(user, "id", None))
    db.session.add(course)
    db.session.flush()
    return course


def warnings(course, vaccine, lang="ar"):
    """What the card says out loud: a protocol that does not match what the
    doctor answered, and the immunoglobulin question while it is open."""
    p = protocol(vaccine, course.protocol) or {}
    out = []
    if p.get("kind") == "pep" and course.previously_vaccinated is not None \
            and p.get("previously") is not None \
            and p["previously"] != course.previously_vaccinated:
        out.append("mismatch_previous")
    if p.get("kind") == "pep" and course.rig in (None, "assess", "needed"):
        out.append("rig_" + (course.rig or "assess"))
    if p.get("key") == "pep_eg5":
        out.append("confirm_source")
    return out


def set_rig(course, state, on_date=None):
    if state not in RIG_STATES:
        raise CourseError("rig")
    course.rig = state
    course.rig_given_on = on_date if state == "given" else None


def close(course, reason, user):
    from datetime import datetime

    if not course.is_open:
        raise CourseError("closed")
    reason = (reason or "").strip()[:200]
    if not reason:
        raise CourseError("reason")
    course.closed_at = datetime.utcnow()
    course.close_reason = reason
    course.closed_by = getattr(user, "id", None)
