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
         "days": (0, 3, 7, 14), "source": "WHO", "rig": True,
         "ar": "بعد التعرّض — منظمة الصحة العالمية (٤ جرعات عضل)",
         "en": "Post-exposure — WHO (4 doses IM)",
         "note_ar": "الجرعة الرابعة من يوم ١٤ لحد يوم ٢٨.",
         "note_en": "The fourth dose from day 14 up to day 28."},
        {"key": "pep_eg5", "kind": "pep", "previously": False,
         "days": (0, 3, 7, 14, 28), "source": "Egyptian Health Council", "rig": True,
         "ar": "بعد التعرّض — البروتوكول المصري (٥ جرعات)",
         "en": "Post-exposure — Egyptian protocol (5 doses)",
         "note_ar": "منشور عند المجلس الصحي المصري؛ نشرة هيئة الدواء ٢٠٢٥ فيها جدول مختلف — اتأكد من المصدر الرسمي الساري.",
         "note_en": "Published by the Egyptian Health Council; the 2025 EDA leaflet shows a different table — confirm the official source in force."},
        {"key": "pep_previous", "kind": "pep", "previously": True,
         "days": (0, 3), "source": "WHO", "rig": False,
         "ar": "بعد التعرّض — متطعّم قبل كده (جرعتين)",
         "en": "Post-exposure — previously vaccinated (2 doses)",
         "note_ar": "", "note_en": ""},
        {"key": "prep_who", "kind": "prep", "previously": None,
         "days": (0, 7), "source": "WHO", "rig": False,
         "ar": "قبل التعرّض — منظمة الصحة العالمية (جرعتين)",
         "en": "Pre-exposure — WHO (2 doses)",
         "note_ar": "", "note_en": ""},
    ],
}
_EG5_NOTE_AR = PROTOCOLS["RABIES"][1]["note_ar"]
#: A dose of a course counted in days is "due" from the day before its date —
#: not the thirty days a schedule in months uses, which would call every dose
#: of a 28-day course due on day 0 and remind about all of them at once.
COURSE_DUE_DAYS = 1
CATEGORIES = ("I", "II", "III")
RIG_STATES = ("assess", "needed", "given", "not_needed")
KINDS = ("pep", "prep")
#: The clinic's own protocols, ``{vaccine code: [protocol, ...]}`` as JSON.
#: Missing (or a code missing from it) means the protocols above.
SETTING_KEY = "vaccine_protocols"
MAX_DOSES = 10
MAX_DAY = 365


class CourseError(ValueError):
    """A refusal with a key (``vcourse.err_<key>``)."""


def _saved():
    import json

    from app.models import Setting

    raw = Setting.get(SETTING_KEY)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    out = {}
    for code, rows in (data or {}).items():
        if isinstance(rows, list):
            out[code] = [dict(r, days=tuple(int(d) for d in r.get("days") or ()))
                         for r in rows if isinstance(r, dict) and r.get("key")]
    return out


def protocols_by_code(code):
    """The protocols the doctor chooses from for this vaccine code: the
    clinic's own when it saved some, otherwise the ones written above."""
    code = code or ""
    saved = _saved()
    if code in saved:
        return saved[code]
    return [dict(p) for p in PROTOCOLS.get(code, [])]


def protocols_for(vaccine):
    return protocols_by_code(getattr(vaccine, "code", None))


def is_customised(vaccine):
    return (getattr(vaccine, "code", None) or "") in _saved()


def parse_days(text):
    """``"0, 3, 7, 14"`` → ``(0, 3, 7, 14)``, or :class:`CourseError` —
    day 0 first, each day after the one before, at most :data:`MAX_DOSES`."""
    import re

    parts = [x for x in re.split(r"[\s,،;]+", (text or "").translate(
        str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")).strip()) if x]
    try:
        days = tuple(int(x) for x in parts)
    except ValueError:
        raise CourseError("days") from None
    if not days or days[0] != 0 or len(days) > MAX_DOSES \
            or any(b <= a for a, b in zip(days, days[1:])) or days[-1] > MAX_DAY:
        raise CourseError("days")
    return days


def save_protocols(vaccine, rows):
    """Write the clinic's protocols for this vaccine. ``rows``: dicts with
    key (empty for a new one), ar, en, kind, previously ("1"/"0"/""), days
    (text), rig (bool), note_ar, note_en, source, delete (bool). A course
    already open keeps the days it was opened with. The caller commits."""
    import json
    import re

    from app.models import Setting

    out, seen = [], set()
    for r in rows:
        if r.get("delete"):
            continue
        ar = (r.get("ar") or "").strip()[:120]
        if not ar and not (r.get("days") or "").strip():
            continue                      # the empty "add one" row
        if not ar:
            raise CourseError("name")
        days = parse_days(r.get("days"))
        kind = r.get("kind") if r.get("kind") in KINDS else "pep"
        prev = r.get("previously")
        key = (r.get("key") or "").strip()[:30]
        if not key:
            base = re.sub(r"[^a-z0-9]+", "_", (r.get("en") or "").lower()).strip("_")[:20]
            key = f"c_{base or 'p'}"
        while key in seen:
            key = (key[:26] + "_" + str(len(seen)))[:30]
        seen.add(key)
        out.append({
            "key": key, "kind": kind,
            "previously": True if prev == "1" else False if prev == "0" else None,
            "days": list(days),
            "source": (r.get("source") or "").strip()[:80],
            "rig": bool(r.get("rig")),
            "ar": ar, "en": (r.get("en") or "").strip()[:120] or ar,
            "note_ar": (r.get("note_ar") or "").strip()[:300],
            "note_en": (r.get("note_en") or "").strip()[:300],
        })
    if not out:
        raise CourseError("none_left")
    data = _saved()
    data = {c: [dict(p, days=list(p["days"])) for p in ps] for c, ps in data.items()}
    data[vaccine.code] = out
    Setting.set(SETTING_KEY, json.dumps(data, ensure_ascii=False))


def reset_protocols(vaccine):
    """Back to the protocols written in the program."""
    import json

    from app.models import Setting

    data = {c: [dict(p, days=list(p["days"])) for p in ps] for c, ps in _saved().items()}
    data.pop(vaccine.code, None)
    Setting.set(SETTING_KEY, json.dumps(data, ensure_ascii=False))


def protocol(vaccine, key):
    return next((p for p in protocols_for(vaccine) if p["key"] == key), None)


def _snapshot(p):
    import json

    return json.dumps(dict(p, days=list(p["days"])), ensure_ascii=False)


def course_protocol(course, vaccine=None, code=None):
    """The protocol this course runs on — as it was when the course opened.

    The clinic can change a protocol's days later (or remove it); a child
    half-way through a course keeps the dates their doctor gave them. Courses
    opened before the protocol was kept on them read the current one."""
    import json

    if course is None:
        return None
    if course.protocol_data:
        try:
            p = json.loads(course.protocol_data)
            p["days"] = tuple(int(d) for d in p.get("days") or ())
            if p["days"]:
                return p
        except (ValueError, TypeError):
            pass
    if vaccine is not None:
        return protocol(vaccine, course.protocol)
    return next((p for p in protocols_by_code(code) if p["key"] == course.protocol), None)


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
        p = course_protocol(c, code=codes.get(c.vaccine_id))
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
    p = course_protocol(course, vaccine)
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
    if _rig_question(p, previously) and rig is None:
        # Never vaccinated after an exposure: the question of the
        # immunoglobulin is asked every time, and stays on the card until a
        # person answers it.
        rig = "assess"
    highest = (db.session.query(db.func.max(PatientVaccine.dose_number))
               .filter_by(patient_id=patient.id, vaccine_id=vaccine.id,
                          event_type="given").scalar()) or 0
    course = VaccineCourse(
        patient_id=patient.id, vaccine_id=vaccine.id, protocol=p["key"],
        protocol_data=_snapshot(p),
        start_date=start_on, first_dose_number=highest + 1,
        previously_vaccinated=previously, exposure_category=category, rig=rig,
        notes=(data.get("notes") or "").strip()[:300] or None,
        chosen_by=getattr(user, "id", None))
    db.session.add(course)
    db.session.flush()
    return course


def _asks_rig(p):
    """Whether this protocol raises the immunoglobulin question. Protocols
    kept before the clinic could set it: after exposure, never vaccinated."""
    if "rig" in p:
        return bool(p["rig"])
    return p.get("kind") == "pep" and p.get("previously") is False


def _rig_question(p, previously):
    """Is the immunoglobulin question open for this child on this protocol?
    Never after a vaccination before; always after an exposure in a child
    the doctor says was never vaccinated, whatever protocol was picked;
    otherwise as the protocol says."""
    if previously is True:
        return False
    if p.get("kind") == "pep" and previously is False:
        return True
    return _asks_rig(p)


def warnings(course, vaccine, lang="ar"):
    """What the card says out loud: a protocol that does not match what the
    doctor answered, and the immunoglobulin question while it is open."""
    p = course_protocol(course, vaccine) or {}
    out = []
    if p.get("kind") == "pep" and course.previously_vaccinated is not None \
            and p.get("previously") is not None \
            and p["previously"] != course.previously_vaccinated:
        out.append("mismatch_previous")
    if _rig_question(p, course.previously_vaccinated) \
            and course.rig in (None, "assess", "needed"):
        out.append("rig_" + (course.rig or "assess"))
    # Until the clinic writes its own note on the Egyptian protocol (the
    # circular it follows), the card keeps asking to confirm the source.
    if p.get("key") == "pep_eg5" and p.get("note_ar") == _EG5_NOTE_AR:
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


def cards(plan, patient_id=None):
    """One entry per vaccine that has protocols — what both the vaccinations
    page and the visit draw: the protocols to start from, or the open course
    with its next dose and what it has to say. ``plan`` is ``patient_plan``."""
    from app.models import Vaccine

    from app.models import PatientVaccine

    by_id = {item["vaccine"].id: item for item in plan}
    out = []
    for v in Vaccine.query.order_by(Vaccine.sort_order).all():
        protos = protocols_for(v)
        if not protos:
            continue
        item = by_id.get(v.id) or {}
        course = item.get("day_course")
        course_doses = [d for d in item.get("doses", []) if d.get("course_day") is not None]
        # Doses on file outside the open course — an earlier course, or
        # doses typed in from a card before courses existed (no protocol
        # recorded). Either way the child was most likely vaccinated before,
        # which changes the protocol.
        before = []
        pid = patient_id
        if pid:
            first = (course.first_dose_number or 1) if course is not None else None
            before = sorted(
                (pv.given_date for pv in PatientVaccine.query.filter_by(
                    patient_id=pid, vaccine_id=v.id, event_type="given").all()
                 if pv.given_date and (first is None or pv.dose_number < first)))
        out.append({
            "count_done": sum(1 for d in course_doses if d["status"] == "done"),
            "count_all": len(course_doses),
            "before": before,
            "vaccine": v, "protocols": protos, "course": course,
            "protocol": item.get("day_protocol"), "item": item,
            "warnings": warnings(course, v) if course is not None else [],
            "next": next((d for d in item.get("doses", [])
                          if d.get("course_day") is not None
                          and d["status"] != "done"), None),
            # The amount per injection differs by product (Verorab 0.5 mL,
            # Rabipur 1.0 mL) and is said where the dose is given.
            "brands": list(v.active_brands) or list(v.brands),
        })
    return out
