"""Data quality — one score, per department and in all (SMART_PATTERNS_PLAN ج-١).

The owner brought the method from the vaccination unit's program: a score
0–100 that is a weighted average of checks, each check with a door to the
records behind it and a sheet of them, and the score kept day by day so the
improvement shows. The method moved here; the checks did not — most of that
program's sixteen cannot happen in PediaPro (a date of birth and a sex are
required here, doctors are accounts, file numbers are ours), so each
department declares its own, in ``app/data/dq_checks.json``.

* **Every check counts the records that need fixing** among the records it
  looks at — a «higher is better» check (files with a phone) counts the
  ones without. A check with nothing to look at has no score, and is left
  out of the average rather than counted as perfect or as zero.
* **The score:** «higher is better» = the share that is right; «lower is
  better» = 100 − 5 × the share that is wrong, never below 0. The five makes
  2 % wrong cost ten points instead of vanishing in an average. (The
  vaccination program switched to 100 − share above 20 %, which scores 19 %
  wrong at 5 and 21 % at 79; the straight line keeps «worse» meaning
  «lower».)
* **A department shows only where its module runs** (``facility``): a
  clinic sees its clinics and vaccinations, a hospital every department it
  has.
* **The overall score:** the patient file carries 30; the other 70 are
  shared among the departments shown by their work in the window — visits,
  doses, attendances. A department with nothing to score shares nothing.
* **The program fixes nothing.** Each check lists its records, each record
  opens where it is fixed, and a person fixes it.
"""
import json
import os
from datetime import datetime, timedelta

from app.extensions import db

_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data",
                     "dq_checks.json")
WEIGHTS_KEY = "dq_weights"
#: The «lower is better» multiplier, and the colours' edges.
STEEP = 5
GREEN, AMBER = 90, 60
HISTORY_DAYS = 120
LIST_LIMIT = 500


def config():
    with open(_FILE, encoding="utf-8") as fh:
        return json.load(fh)


def _weights_override():
    from app.models import Setting

    try:
        got = json.loads(Setting.get(WEIGHTS_KEY, "") or "{}")
    except ValueError:
        return {}
    return {k: v for k, v in got.items() if isinstance(v, (int, float)) and v >= 0} \
        if isinstance(got, dict) else {}


def set_weights(form, known):
    """The administrator's weights, by check key; a blank keeps the default."""
    from app.models import Setting

    out = {}
    for key in known:
        raw = (form.get(f"w_{key}") or "").strip()
        if not raw:
            continue
        try:
            value = int(raw)
        except ValueError:
            continue
        if 0 <= value <= 100:
            out[key] = value
    Setting.set(WEIGHTS_KEY, json.dumps(out))
    return out


def sections():
    """The sections this copy shows, with each check's weight in force."""
    from app.utils.facility import module_enabled

    override = _weights_override()
    out = []
    for sec in config()["sections"]:
        if sec.get("module") and not module_enabled(sec["module"]):
            continue
        checks = [dict(c, weight=override.get(c["key"], c["weight"]))
                  for c in sec["checks"]]
        out.append(dict(sec, checks=checks))
    return out


def check_by_key(key):
    for sec in sections():
        for c in sec["checks"]:
            if c["key"] == key:
                return sec, c
    return None, None


# ---------------------------------------------------------------- scoring ---
def score_of(bad, total, better):
    """``None`` when there is nothing to look at."""
    if not total:
        return None
    pct = 100.0 * bad / total
    if better == "higher":
        return round(100.0 - pct, 1)
    return round(max(0.0, 100.0 - STEEP * pct), 1)


def colour(score):
    if score is None:
        return "none"
    return "green" if score >= GREEN else ("amber" if score >= AMBER else "red")


def weighted(pairs):
    """Average of ``(score, weight)``, the ones with no score left out."""
    pairs = [(s, w) for s, w in pairs if s is not None and w > 0]
    total = sum(w for _, w in pairs)
    return round(sum(s * w for s, w in pairs) / total, 1) if total else None


# ----------------------------------------------------------------- checks ---
def _since(cfg=None):
    from app.utils.clock import local_today

    days = (cfg or config()).get("window_days", 90)
    return local_today() - timedelta(days=days)


def _since_moment(cfg=None):
    return datetime.utcnow() - timedelta(days=(cfg or config()).get("window_days", 90))


def _blank(col):
    return (col.is_(None)) | (db.func.trim(col) == "")


def _patients():
    from app.models import Patient

    return Patient.query.filter(Patient.is_active.is_(True))


def patient_no_phone():
    from app.models import Parent, Patient

    has_parent_phone = db.session.query(Parent.id).filter(
        Parent.family_id == Patient.family_id, Patient.family_id.isnot(None),
        ~_blank(Parent.phone)).exists()
    base = _patients()
    return base, base.filter(_blank(Patient.own_phone), ~has_parent_phone)


def patient_duplicates():
    from app.models import Patient
    from app.utils import patient_merge

    ids = {p.id for a, b, _ in patient_merge.candidates(limit=LIST_LIMIT)
           for p in (a, b)}
    base = _patients()
    return base, base.filter(Patient.id.in_(ids or [0]))


def patient_provisional():
    from app.models import Patient

    base = _patients()
    return base, base.filter(Patient.identity_provisional.is_(True))


def patient_dob_estimated():
    from app.models import Patient

    base = _patients()
    return base, base.filter(Patient.dob_estimated.is_(True))


def patient_no_family():
    from app.models import Patient

    base = _patients()
    return base, base.filter(Patient.family_id.is_(None))


def _clinic_visits(completed=True):
    from app.models import Visit

    q = Visit.query.filter(Visit.channel == "clinic", Visit.visit_date >= _since())
    return q.filter(Visit.status == "completed") if completed else q


def visit_no_diagnosis():
    from app.models import Diagnosis, Visit

    base = _clinic_visits()
    has_dx = db.session.query(Diagnosis.id).filter(Diagnosis.visit_id == Visit.id).exists()
    return base, base.filter(~has_dx)


def visit_diagnosis_no_code():
    from app.models import Diagnosis, Visit

    base = (Diagnosis.query.join(Visit, Diagnosis.visit_id == Visit.id)
            .filter(Visit.channel == "clinic", Visit.visit_date >= _since()))
    return base, base.filter(_blank(Diagnosis.code))


def visit_no_weight():
    from app.models import GrowthRecord, Visit, VitalSigns

    base = _clinic_visits()
    vitals = db.session.query(VitalSigns.id).filter(
        VitalSigns.visit_id == Visit.id, VitalSigns.weight_kg.isnot(None)).exists()
    growth = db.session.query(GrowthRecord.id).filter(
        GrowthRecord.patient_id == Visit.patient_id,
        GrowthRecord.record_date == Visit.visit_date,
        GrowthRecord.weight_kg.isnot(None)).exists()
    return base, base.filter(~vitals, ~growth)


def visit_left_open():
    from app.models import Visit
    from app.utils.clock import local_today

    base = _clinic_visits(completed=False)
    return base, base.filter(Visit.status == "open", Visit.visit_date < local_today())


def _doses():
    from app.models import PatientVaccine

    return PatientVaccine.query.filter(
        PatientVaccine.event_type == "given",
        PatientVaccine.given_outside.is_(False),
        PatientVaccine.given_date >= _since())


def dose_no_lot():
    from app.models import PatientVaccine

    base = _doses()
    return base, base.filter(_blank(PatientVaccine.lot_number))


def dose_same_day():
    from app.models import PatientVaccine

    base = _doses()
    twice = (base.with_entities(PatientVaccine.patient_id, PatientVaccine.vaccine_id,
                                PatientVaccine.given_date)
             .group_by(PatientVaccine.patient_id, PatientVaccine.vaccine_id,
                       PatientVaccine.given_date)
             .having(db.func.count(PatientVaccine.id) > 1).all())
    if not twice:
        return base, base.filter(PatientVaccine.id.in_([0]))
    cond = db.or_(*[db.and_(PatientVaccine.patient_id == p, PatientVaccine.vaccine_id == v,
                            PatientVaccine.given_date == d) for p, v, d in twice])
    return base, base.filter(cond)


def dose_before_birth():
    from app.models import Patient, PatientVaccine

    base = _doses()
    return base, (base.join(Patient, PatientVaccine.patient_id == Patient.id)
                  .filter(PatientVaccine.given_date < Patient.date_of_birth))


def dose_no_doctor():
    from app.models import PatientVaccine

    base = _doses()
    return base, base.filter(PatientVaccine.doctor_id.is_(None))


def _attendances(seen_matters=False):
    from app.models import EmergencyVisit

    q = EmergencyVisit.query.filter(EmergencyVisit.departed_at.isnot(None),
                                    EmergencyVisit.arrived_at >= _since_moment())
    if seen_matters:
        # A child who left before being seen was never triaged or examined
        # by a doctor: not a record somebody forgot to complete.
        q = q.filter(db.or_(EmergencyVisit.disposition.is_(None),
                            EmergencyVisit.disposition != "left_unseen"))
    return q


def er_no_triage():
    from app.models import EmergencyVisit

    base = _attendances(seen_matters=True)
    return base, base.filter(EmergencyVisit.triaged_at.is_(None))


def er_not_seen():
    from app.models import EmergencyVisit

    base = _attendances(seen_matters=True)
    return base, base.filter(EmergencyVisit.seen_at.is_(None))


def er_no_disposition():
    from app.models import EmergencyVisit

    base = _attendances()
    return base, base.filter(_blank(EmergencyVisit.disposition))


def er_no_diagnosis():
    from app.models import Diagnosis, EmergencyVisit

    base = _attendances(seen_matters=True)
    has_dx = db.session.query(Diagnosis.id).filter(
        Diagnosis.visit_id == EmergencyVisit.visit_id).exists()
    return base, base.filter(db.or_(EmergencyVisit.visit_id.is_(None), ~has_dx))


KINDS = {f.__name__: f for f in (
    patient_no_phone, patient_duplicates, patient_provisional, patient_dob_estimated,
    patient_no_family, visit_no_diagnosis, visit_diagnosis_no_code, visit_no_weight,
    visit_left_open, dose_no_lot, dose_same_day, dose_before_birth, dose_no_doctor,
    er_no_triage, er_not_seen, er_no_disposition, er_no_diagnosis)}


# --------------------------------------------------------------- the board ---
def _workload(key):
    """How much a section did in the window — its share of the 70."""
    if key == "clinic":
        return _clinic_visits(completed=False).count()
    if key == "vaccines":
        return _doses().count()
    if key == "emergency":
        return _attendances().count()
    return 0


def run_check(check):
    total_q, bad_q = KINDS[check["kind"]]()
    total, bad = total_q.count(), bad_q.count()
    return {**check, "total": total, "bad": bad,
            "score": score_of(bad, total, check["better"])}


def board():
    """``{"sections": [...], "overall": score, "weights": {section: share}}``."""
    cfg = config()
    secs = []
    for sec in sections():
        checks = [run_check(c) for c in sec["checks"]]
        score = weighted((c["score"], c["weight"]) for c in checks)
        for c in checks:
            c["colour"] = colour(c["score"])
        secs.append({**sec, "checks": checks, "score": score, "colour": colour(score),
                     "work": _workload(sec["key"])})
    patient_w = cfg.get("patient_weight", 30)
    others = [s for s in secs if s["key"] != "patient" and s["score"] is not None]
    work = sum(s["work"] for s in others)
    shares = {}
    for s in secs:
        if s["key"] == "patient":
            shares[s["key"]] = patient_w if s["score"] is not None else 0
        elif s["score"] is None:
            shares[s["key"]] = 0
        elif work:
            shares[s["key"]] = round((100 - patient_w) * s["work"] / work, 1)
        else:
            shares[s["key"]] = round((100 - patient_w) / len(others), 1)
    for s in secs:
        s["share"] = shares[s["key"]]
    overall = weighted((s["score"], shares[s["key"]]) for s in secs)
    return {"sections": secs, "overall": overall, "colour": colour(overall)}


def record_today(data=None):
    """Keep today's scores — once a day, the latest reading of the day."""
    from app.models.data_quality import DqDaily
    from app.utils.clock import local_today

    data = data or board()
    today = local_today()
    rows = [("all", data["overall"])] + [(s["key"], s["score"]) for s in data["sections"]]
    for key, score in rows:
        row = DqDaily.query.filter_by(day=today, section=key).first()
        if row is None:
            db.session.add(DqDaily(day=today, section=key, score=score))
        else:
            row.score = score
    db.session.flush()


def history(section="all", days=HISTORY_DAYS):
    from app.models.data_quality import DqDaily
    from app.utils.clock import local_today

    since = local_today() - timedelta(days=days)
    return (DqDaily.query.filter(DqDaily.section == section, DqDaily.day >= since)
            .order_by(DqDaily.day).all())


# ------------------------------------------------------------- the records ---
def records(check, limit=LIST_LIMIT):
    """The records behind a check: ``[{"patient", "when", "endpoint", "kwargs",
    "anchor"}]`` — each opens where it is fixed."""
    from app.models import Diagnosis, EmergencyVisit, Patient, PatientVaccine, Visit

    _, bad_q = KINDS[check["kind"]]()
    out = []
    for row in bad_q.limit(limit).all():
        if isinstance(row, Patient):
            out.append({"patient": row, "when": row.created_at,
                        "endpoint": "patients.view", "kwargs": {"patient_id": row.id},
                        "anchor": ""})
        elif isinstance(row, Visit):
            out.append({"patient": row.patient, "when": row.visit_date,
                        "endpoint": "visits.record", "kwargs": {"visit_id": row.id},
                        "anchor": ""})
        elif isinstance(row, Diagnosis):
            visit = db.session.get(Visit, row.visit_id)
            out.append({"patient": visit.patient if visit else None,
                        "when": visit.visit_date if visit else None,
                        "endpoint": "visits.record", "kwargs": {"visit_id": row.visit_id},
                        "anchor": "", "detail": row.title})
        elif isinstance(row, PatientVaccine):
            out.append({"patient": db.session.get(Patient, row.patient_id),
                        "when": row.given_date, "endpoint": "vaccinations.view",
                        "kwargs": {"patient_id": row.patient_id}, "anchor": ""})
        elif isinstance(row, EmergencyVisit):
            out.append({"patient": row.patient, "when": row.arrived_at,
                        "endpoint": "emergency.attendance",
                        "kwargs": {"attendance_id": row.id}, "anchor": ""})
    return out
