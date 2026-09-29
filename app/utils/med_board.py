"""The medical board: counts and illnesses from one date to another, no money.

Asked for with the management board and «مرضايا»; the prototype the clinic
agreed is the shape. What holds it together:

* **Every figure beside the same stretch just before**, so "up" and "down"
  mean something — never a target nobody set.
* **Diagnoses counted by their code**, ICD-10 and ICD-11 each marked, and
  never merged by a guess: the same illness under two versions is two rows,
  because deciding they are one is a clinical mapping this program was not
  given. What a doctor wrote without a code is counted by its words, and its
  share is shown — that share is a measure of the record's quality too.
* **Numbers, not verdicts.** What is rising is what rose; there is no line
  above which the program declares an outbreak, and no "good" or "bad"
  doctor — the table carries what was recorded.
* **Only what a clinic runs.** The inpatient, emergency and theatre parts
  appear when those parts of the program are switched on, so a clinic is
  not shown a hospital's empty boxes.

All of it is aggregated in the database, so a year of a busy hospital is
one query per block, not a loop over every visit.
"""
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from app.extensions import db

PRESETS = ("7", "30", "month", "90", "year")
DEFAULT_PRESET = "30"
#: The age groups the program already reports by (``reports.AGE_BUCKETS``).
AGE_BUCKETS = ["<1", "1-2", "2-5", "5-12", "12+"]
#: How many cases a drill-down shows per page.
CASES_PER_PAGE = 25
#: "Came back within a week": the same child seen again within this many days.
BACK_DAYS = 7
#: A readmission: admitted again within this many days of leaving.
READMIT_DAYS = 30


# ------------------------------------------------------------ the window ---
def window(raw_from=None, raw_to=None, preset=None, today=None):
    """The dates asked for, and the same length just before.

    Typed dates win over a preset; a preset nobody knows is the default. The
    dates are the clinic's own days — see :func:`utc` for the moments.
    """
    from app.utils.clock import local_today

    today = today or local_today()

    def parse(raw):
        try:
            return datetime.strptime((raw or "").strip(), "%Y-%m-%d").date()
        except ValueError:
            return None

    d_from, d_to = parse(raw_from), parse(raw_to)
    if d_from or d_to:
        preset = None
        d_to = d_to or today
        d_from = d_from or d_to - timedelta(days=29)
        if d_from > d_to:
            d_from, d_to = d_to, d_from
    else:
        preset = preset if preset in PRESETS else DEFAULT_PRESET
        d_to = today
        if preset == "month":
            d_from = today.replace(day=1)
        elif preset == "year":
            d_from = today.replace(month=1, day=1)
        else:
            d_from = today - timedelta(days=int(preset) - 1)
    days = (d_to - d_from).days + 1
    prev_to = d_from - timedelta(days=1)
    return {"from": d_from, "to": d_to, "days": days, "preset": preset,
            "prev_from": prev_to - timedelta(days=days - 1), "prev_to": prev_to}


def utc(d_from, d_to):
    """``(start, end)`` in stored UTC for the clinic's days — end exclusive."""
    from app.utils.clock import to_utc

    return (to_utc(datetime.combine(d_from, datetime.min.time())),
            to_utc(datetime.combine(d_to + timedelta(days=1), datetime.min.time())))


def parts():
    """Which of the hospital's parts this copy runs."""
    from app.utils.facility import module_enabled

    return {key: module_enabled(key) for key in ("beds", "emergency", "theatres")}


# --------------------------------------------------------------- figures ---
def counts(d_from, d_to, on=None):
    """The headline numbers. A part the clinic does not run is ``None``."""
    from app.models import Admission, Patient, PatientVaccine, Visit
    from app.models.emergency_visit import DIED, EmergencyVisit
    from app.models.theatre import Operation

    on = on if on is not None else parts()
    start, end = utc(d_from, d_to)
    out = {
        "visits": Visit.query.filter(Visit.visit_date >= d_from,
                                     Visit.visit_date <= d_to).count(),
        "new_patients": Patient.query.filter(Patient.created_at >= start,
                                             Patient.created_at < end).count(),
        "doses": PatientVaccine.query.filter(PatientVaccine.given_date >= d_from,
                                             PatientVaccine.given_date <= d_to).count(),
        "admissions": None, "discharges": None, "deaths": None,
        "emergency": None, "operations": None,
    }
    if on.get("beds"):
        out["admissions"] = Admission.query.filter(
            Admission.admitted_at >= start, Admission.admitted_at < end).count()
        left = Admission.query.filter(Admission.discharged_at >= start,
                                      Admission.discharged_at < end)
        out["discharges"] = left.count()
        out["deaths"] = left.filter(Admission.outcome == "died").count()
    if on.get("emergency"):
        out["emergency"] = EmergencyVisit.query.filter(
            EmergencyVisit.arrived_at >= start, EmergencyVisit.arrived_at < end).count()
        er_deaths = EmergencyVisit.query.filter(
            EmergencyVisit.disposition == DIED,
            EmergencyVisit.arrived_at >= start, EmergencyVisit.arrived_at < end).count()
        out["deaths"] = (out["deaths"] or 0) + er_deaths
    if on.get("theatres"):
        out["operations"] = Operation.query.filter(
            Operation.on_date >= d_from, Operation.on_date <= d_to,
            Operation.status == "done").count()
    return out


def change(now, before):
    """Percent change, or ``None`` when there is nothing to compare with."""
    if now is None or not before:
        return None
    return round((now - before) * 100 / before)


# ------------------------------------------------------------ diagnoses ----
def _coded_key(code, version):
    return f"{version or '10'}:{code}"


def diagnoses(d_from, d_to):
    """``{"coded": [...], "free": [...], "total": n}`` for the period.

    One row per visit and code — a working and a final diagnosis with the
    same code on one visit is one case, not two.
    """
    from app.models import Diagnosis, Visit

    base = (db.session.query(Diagnosis.code, Diagnosis.icd_version,
                             db.func.max(Diagnosis.title),
                             db.func.count(db.distinct(Diagnosis.visit_id)))
            .join(Visit, Diagnosis.visit_id == Visit.id)
            .filter(Visit.visit_date >= d_from, Visit.visit_date <= d_to))
    coded = [{"key": _coded_key(code, version), "code": code,
              "version": version or "10", "title": title, "n": n}
             for code, version, title, n in
             base.filter(Diagnosis.code.isnot(None), Diagnosis.code != "")
             .group_by(Diagnosis.code, Diagnosis.icd_version).all()]
    words = defaultdict(lambda: {"n": 0, "title": None})
    for title, n in (db.session.query(Diagnosis.title,
                                      db.func.count(db.distinct(Diagnosis.visit_id)))
                     .join(Visit, Diagnosis.visit_id == Visit.id)
                     .filter(Visit.visit_date >= d_from, Visit.visit_date <= d_to,
                             db.or_(Diagnosis.code.is_(None), Diagnosis.code == ""))
                     .group_by(Diagnosis.title).all()):
        key = " ".join((title or "").split()).lower()
        if not key:
            continue
        words[key]["n"] += n
        words[key]["title"] = words[key]["title"] or " ".join(title.split())
    free = [{"key": "t:" + key, "title": row["title"], "n": row["n"]}
            for key, row in words.items()]
    coded.sort(key=lambda r: (-r["n"], r["code"]))
    free.sort(key=lambda r: (-r["n"], r["title"]))
    total = sum(r["n"] for r in coded) + sum(r["n"] for r in free)
    return {"coded": coded, "free": free, "total": total,
            "free_share": round(sum(r["n"] for r in free) * 100 / total) if total else None}


def with_before(rows, before_rows):
    """Each row gains ``p``, its count in the period before."""
    was = {r["key"]: r["n"] for r in before_rows}
    for row in rows:
        row["p"] = was.get(row["key"], 0)
    return rows


def rising(rows, limit=5):
    """What went up most since the period before — by how many more cases,
    not by a percentage that makes one case into two look like a wave."""
    up = [r for r in rows if r["n"] > r.get("p", 0)]
    up.sort(key=lambda r: (-(r["n"] - r.get("p", 0)), -r["n"]))
    return up[:limit]


def _cases_query(d_from, d_to, key):
    """The visits behind one diagnosis row (``key`` from :func:`diagnoses`)."""
    from app.models import Diagnosis, Visit

    query = (db.session.query(Visit)
             .join(Diagnosis, Diagnosis.visit_id == Visit.id)
             .filter(Visit.visit_date >= d_from, Visit.visit_date <= d_to))
    kind, _, rest = (key or "").partition(":")
    if kind == "t":
        # Grouped by the words the way :func:`diagnoses` groups them.
        wanted = rest
        query = query.filter(db.or_(Diagnosis.code.is_(None), Diagnosis.code == ""))
        titles = [t for (t,) in query.with_entities(Diagnosis.title).distinct().all()
                  if " ".join((t or "").split()).lower() == wanted]
        if not titles:
            return None
        query = query.filter(Diagnosis.title.in_(titles))
    elif kind in ("10", "11") and rest:
        query = query.filter(Diagnosis.code == rest, Diagnosis.icd_version == kind)
    else:
        return None
    return query.distinct()


def _bucket(born, on):
    """The child's age group on the day they were seen."""
    if born is None:
        return None
    years = on.year - born.year - ((on.month, on.day) < (born.month, born.day))
    if years < 1:
        return "<1"
    if years < 2:
        return "1-2"
    if years < 5:
        return "2-5"
    if years < 12:
        return "5-12"
    return "12+"


def breakdown(d_from, d_to, key):
    """By age and by sex for one diagnosis row — counts only, no names."""
    from app.models import Patient, Visit

    query = _cases_query(d_from, d_to, key)
    if query is None:
        return None
    ages, sexes = Counter(), Counter()
    for visit_date, born, gender in (query.join(Patient, Patient.id == Visit.patient_id)
                                     .with_entities(Visit.visit_date, Patient.date_of_birth,
                                                    Patient.gender).all()):
        ages[_bucket(born, visit_date) or "?"] += 1
        sexes[gender or "?"] += 1
    return {"ages": [(b, ages.get(b, 0)) for b in AGE_BUCKETS],
            "sexes": dict(sexes), "total": sum(sexes.values())}


def cases(d_from, d_to, key, page=1, per_page=CASES_PER_PAGE):
    """``(visits, total)`` behind one diagnosis row, newest first."""
    from app.models import Visit

    query = _cases_query(d_from, d_to, key)
    if query is None:
        return [], 0
    total = query.count()
    page = max(1, page)
    rows = (query.order_by(Visit.visit_date.desc(), Visit.id.desc())
            .offset((page - 1) * per_page).limit(per_page).all())
    return rows, total


def all_cases(d_from, d_to, key):
    from app.models import Visit

    query = _cases_query(d_from, d_to, key)
    return [] if query is None else query.order_by(Visit.visit_date.desc(), Visit.id.desc()).all()


# ------------------------------------------------------------- the ages ----
def ages(d_from, d_to):
    """``[(bucket, boys, girls, other)]`` — each child once, at the age they
    were at their first visit in the period."""
    from app.models import Patient, Visit

    first = (db.session.query(Visit.patient_id, db.func.min(Visit.visit_date))
             .filter(Visit.visit_date >= d_from, Visit.visit_date <= d_to)
             .group_by(Visit.patient_id).subquery())
    table = {b: [0, 0, 0] for b in AGE_BUCKETS}
    for born, gender, seen in (db.session.query(Patient.date_of_birth, Patient.gender,
                                                first.c[1])
                               .join(first, first.c.patient_id == Patient.id).all()):
        bucket = _bucket(born, seen)
        if bucket is None:
            continue
        slot = 0 if gender == "male" else 1 if gender == "female" else 2
        table[bucket][slot] += 1
    return [(b, *table[b]) for b in AGE_BUCKETS]


# -------------------------------------------------------------- the wards --
def _first_units(admission_ids):
    """``{admission_id: unit_id}`` — the unit of the first bed each stay was in."""
    from app.models import BedStay
    from app.models.place import Bed, Space

    if not admission_ids:
        return {}
    first = (db.session.query(BedStay.admission_id, db.func.min(BedStay.since).label("s"))
             .filter(BedStay.admission_id.in_(admission_ids))
             .group_by(BedStay.admission_id).subquery())
    return dict(db.session.query(BedStay.admission_id, Space.unit_id)
                .join(first, db.and_(first.c.admission_id == BedStay.admission_id,
                                     first.c.s == BedStay.since))
                .join(Bed, BedStay.bed_id == Bed.id)
                .join(Space, Bed.space_id == Space.id).all())


def wards(d_from, d_to):
    """One row per unit: admissions, mean stay of those who left, how full it
    was, deaths, and readmissions within :data:`READMIT_DAYS`."""
    from app.models import Admission
    from app.models.place import Unit
    from app.utils import bed_map

    start, end = utc(d_from, d_to)
    came = Admission.query.filter(Admission.admitted_at >= start,
                                  Admission.admitted_at < end).all()
    left = Admission.query.filter(Admission.discharged_at >= start,
                                  Admission.discharged_at < end).all()
    unit_of = _first_units([a.id for a in came] + [a.id for a in left])
    # Readmission: an earlier stay of the same child that ended within
    # READMIT_DAYS before this one began.
    patients = {a.patient_id for a in came}
    ended = defaultdict(list)
    if patients:
        for pid, aid, out in (db.session.query(Admission.patient_id, Admission.id,
                                               Admission.discharged_at)
                              .filter(Admission.patient_id.in_(patients),
                                      Admission.discharged_at.isnot(None)).all()):
            ended[pid].append((aid, out))
    rows = {}

    def row(unit_id):
        return rows.setdefault(unit_id, {"admissions": 0, "stay_days": [], "deaths": 0,
                                         "readmitted": 0})

    for a in came:
        r = row(unit_of.get(a.id))
        r["admissions"] += 1
        if any(aid != a.id and out <= a.admitted_at
               and a.admitted_at - out <= timedelta(days=READMIT_DAYS)
               for aid, out in ended.get(a.patient_id, [])):
            r["readmitted"] += 1
    for a in left:
        r = row(unit_of.get(a.id))
        r["stay_days"].append((a.discharged_at - a.admitted_at).total_seconds() / 86400)
        if a.outcome == "died":
            r["deaths"] += 1
    full = bed_map.occupancy(days=(d_to - d_from).days + 1, now=end)
    names = {u.id: u for u in Unit.query.all()}
    out = []
    for unit_id, r in rows.items():
        unit = names.get(unit_id)
        stays = r["stay_days"]
        out.append({
            "unit": unit, "admissions": r["admissions"],
            "alos": round(sum(stays) / len(stays), 1) if stays else None,
            "discharges": len(stays),
            "occupancy": full.get(unit_id),
            "deaths": r["deaths"],
            "readmit_pct": (round(r["readmitted"] * 100 / r["admissions"], 1)
                            if r["admissions"] else None),
        })
    out.sort(key=lambda r: (r["unit"] is None, -(r["admissions"] or 0)))
    return out


# ------------------------------------------------------------- emergency --
def emergency(d_from, d_to):
    """Triage levels **as the hospital writes them** and where children went.

    The program has no triage scale of its own and invents none: a level is
    shown in the words it was recorded in, and "not triaged" is its own row.
    """
    from app.models.emergency_visit import DISPOSITIONS, EmergencyVisit

    start, end = utc(d_from, d_to)
    base = EmergencyVisit.query.filter(EmergencyVisit.arrived_at >= start,
                                       EmergencyVisit.arrived_at < end)
    levels = Counter()
    for level, n in (base.with_entities(EmergencyVisit.level, db.func.count())
                     .group_by(EmergencyVisit.level).all()):
        levels[(level or "").strip() or None] += n
    went = dict(base.with_entities(EmergencyVisit.disposition, db.func.count())
                .group_by(EmergencyVisit.disposition).all())
    total = sum(levels.values())
    return {
        "total": total,
        "levels": sorted(levels.items(), key=lambda kv: (kv[0] is None, str(kv[0]))),
        "dispositions": [(key, went.get(key, 0)) for key in DISPOSITIONS]
        + [(None, went.get(None, 0))],
    }


# --------------------------------------------------------------- doctors --
def doctors(d_from, d_to, place=None, on=None):
    """One row per doctor who saw anybody, from what was recorded.

    ``place`` narrows to where the case was: ``"clinic"`` (visits that were
    not an emergency attendance), ``"emergency"``, or ``"unit:<id>"`` (stays
    that began in that unit). Nothing here is a rating.
    """
    from app.models import Admission, Appointment, Diagnosis, User, Visit
    from app.models.emergency_visit import EmergencyVisit
    from app.models.responsibility import CareResponsibility

    on = on if on is not None else parts()
    er_visits = set()
    if on.get("emergency"):
        er_visits = {vid for (vid,) in db.session.query(EmergencyVisit.visit_id)
                     .filter(EmergencyVisit.visit_id.isnot(None)).all()}
    unit_filter = None
    if place and place.startswith("unit:"):
        try:
            unit_filter = int(place.split(":", 1)[1])
        except ValueError:
            unit_filter = -1

    # The visits, plus a week after, to see who came back.
    seen = (db.session.query(Visit.id, Visit.patient_id, Visit.doctor_id,
                             Visit.visit_date, Visit.appointment_id)
            .filter(Visit.visit_date >= d_from,
                    Visit.visit_date <= d_to + timedelta(days=BACK_DAYS)).all())
    by_patient = defaultdict(list)
    for v in seen:
        by_patient[v.patient_id].append(v.visit_date)
    first_ever = dict(db.session.query(Visit.patient_id, db.func.min(Visit.visit_date))
                      .filter(Visit.patient_id.in_({v.patient_id for v in seen} or {0}))
                      .group_by(Visit.patient_id).all())

    rows = defaultdict(lambda: {"cases": 0, "patients": set(), "fresh": 0, "back": 0,
                                "appts": [], "dx": 0, "nocode": 0,
                                "admissions": 0, "stays": []})
    visit_ids = []
    for v in seen:
        if not (d_from <= v.visit_date <= d_to) or unit_filter is not None:
            continue
        in_er = v.id in er_visits
        if (place == "clinic" and in_er) or (place == "emergency" and not in_er):
            continue
        r = rows[v.doctor_id]
        r["cases"] += 1
        r["patients"].add(v.patient_id)
        if first_ever.get(v.patient_id) == v.visit_date:
            r["fresh"] += 1
        if any(v.visit_date < other <= v.visit_date + timedelta(days=BACK_DAYS)
               for other in by_patient[v.patient_id]):
            r["back"] += 1
        if v.appointment_id:
            r["appts"].append(v.appointment_id)
        visit_ids.append((v.id, v.doctor_id))

    if visit_ids:
        doctor_of = dict(visit_ids)
        for vid, code in (db.session.query(Diagnosis.visit_id, Diagnosis.code)
                          .filter(Diagnosis.visit_id.in_(list(doctor_of))).all()):
            r = rows[doctor_of[vid]]
            r["dx"] += 1
            if not (code or "").strip():
                r["nocode"] += 1
        appt_ids = [a for r in rows.values() for a in r["appts"]]
        minutes = {}
        if appt_ids:
            for aid, began, done in (db.session.query(Appointment.id, Appointment.started_at,
                                                      Appointment.completed_at)
                                     .filter(Appointment.id.in_(appt_ids)).all()):
                if began and done and done >= began:
                    minutes[aid] = (done - began).total_seconds() / 60
        for r in rows.values():
            got = sorted(minutes[a] for a in r["appts"] if a in minutes)
            r["consult"] = got[len(got) // 2] if got else None

    if on.get("beds") and (not place or unit_filter is not None):
        start, end = utc(d_from, d_to)
        came = Admission.query.filter(Admission.admitted_at >= start,
                                      Admission.admitted_at < end).all()
        unit_of = _first_units([a.id for a in came])
        first_doc = {}
        for aid, doc, since in (db.session.query(CareResponsibility.admission_id,
                                                 CareResponsibility.doctor_id,
                                                 CareResponsibility.since)
                                .filter(CareResponsibility.admission_id.in_(
                                    [a.id for a in came] or [0]))
                                .order_by(CareResponsibility.since).all()):
            first_doc.setdefault(aid, doc)
        for a in came:
            if unit_filter is not None and unit_of.get(a.id) != unit_filter:
                continue
            doc = first_doc.get(a.id) or a.doctor_id
            if doc is None:
                continue
            r = rows[doc]
            r["admissions"] += 1
            if a.discharged_at:
                r["stays"].append((a.discharged_at - a.admitted_at).total_seconds() / 86400)

    people = {u.id: u for u in User.query.filter(User.id.in_(list(rows) or [0])).all()}
    out = []
    for doc_id, r in rows.items():
        if doc_id not in people:
            continue
        cases = r["cases"]
        out.append({
            "doctor": people[doc_id], "cases": cases, "patients": len(r["patients"]),
            "fresh": r["fresh"], "consult": r.get("consult"),
            "back_pct": round(r["back"] * 100 / cases, 1) if cases else None,
            "nocode_pct": round(r["nocode"] * 100 / r["dx"], 1) if r["dx"] else None,
            "admissions": r["admissions"] if on.get("beds") else None,
            "alos": (round(sum(r["stays"]) / len(r["stays"]), 1) if r["stays"] else None),
        })
    out.sort(key=lambda r: (-(r["cases"] + r["admissions"] if r["admissions"] else r["cases"]),
                            r["doctor"].full_name or ""))
    return out


def places(on=None):
    """The choices for the doctors' table: ``[(key, label_key_or_name)]``."""
    from app.models.place import Unit

    on = on if on is not None else parts()
    out = [("clinic", None)]
    if on.get("emergency"):
        out.append(("emergency", None))
    if on.get("beds"):
        out += [(f"unit:{u.id}", u) for u in
                Unit.query.filter(Unit.is_active.is_(True)).order_by(Unit.id).all()]
    return out


