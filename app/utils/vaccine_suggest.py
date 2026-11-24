"""Which optional vaccine to offer a child first — SMART_PATTERNS_PLAN ج-٥ (أ).

The vaccination unit's program ranked its suggestions with a score, and it
was tried on real data: a child whose older brother had a vaccine took it two
to four times as often (influenza 60 % against 25 %). The score is carried
over as it was:

* **the age** — suitable now 50 · its time has passed but it may still be
  given 35 · later 10. «Now» is a first dose falling due from 90 days ago to
  30 days ahead; earlier than that is «passed»; a dose the label no longer
  allows (``expired`` / ``not_eligible``) is not offered at all;
* **a brother or sister had it** +30. The unit's program guessed siblings
  from the father's name and the phone and scored a guess lower (+22, +14);
  here siblings are **linked in the family file** (``Family``), so only the
  certain link counts, and a guess is never a reason;
* **the clinic's pattern** — «اللي أخدوا A أخدوا X» — up to +25 (25 × the
  share), only for a pair kept by its conditions (``VaccinePattern``);
* **priority**: high from 75, medium from 55.

Only the optional schedule: a national vaccine is given at the government
unit, and «on demand» ones (rabies) are not offered by age. Nothing here
records anything — it orders what the doctor offers and says why.

The parents' message carries a line about the brother or sister only when
the link is in the family file, and the person sending it can change it.
"""
from collections import defaultdict
from datetime import datetime, timedelta

from app.extensions import db

AGE_NOW, AGE_LATE, AGE_LATER = 50, 35, 10
SIBLING = 30
PATTERN_MAX = 25
HIGH, MEDIUM = 75, 55
NOW_BEFORE, NOW_AFTER = 90, 30        # days around a first dose's due date

MIN_WITH_A = 150
MIN_SHARE = 0.35
MIN_LIFT = 1.5
TICK = "vaccine_patterns:computed_on"
OFFERABLE = ("suggested", "due", "overdue", "upcoming")


# ------------------------------------------------- the clinic's pattern ----
def refresh_patterns():
    """Count the pairs again from every dose given. Returns how many kept."""
    from app.models import PatientVaccine, VaccinePattern

    took = defaultdict(set)                       # vaccine → children
    for pid, vid in (PatientVaccine.query
                     .filter(PatientVaccine.event_type == "given")
                     .with_entities(PatientVaccine.patient_id,
                                    PatientVaccine.vaccine_id).distinct()):
        took[vid].add(pid)
    children = set().union(*took.values()) if took else set()
    VaccinePattern.query.delete()
    if not children:
        return 0
    kept = 0
    now = datetime.utcnow()
    for a, with_a in took.items():
        if len(with_a) < MIN_WITH_A:
            continue
        for x, with_x in took.items():
            if x == a:
                continue
            both = len(with_a & with_x)
            share = both / len(with_a)
            base = len(with_x) / len(children)
            if share >= MIN_SHARE and share >= MIN_LIFT * base:
                db.session.add(VaccinePattern(a_vaccine_id=a, x_vaccine_id=x,
                                              with_a=len(with_a), with_both=both,
                                              share=round(share, 4), base=round(base, 4),
                                              computed_at=now))
                kept += 1
    return kept


def maybe_refresh(today=None):
    """From the heartbeat: once a day, by one server process only, and only
    where the clinic gives vaccines."""
    from app.models import Setting
    from app.utils.clock import local_today
    from app.utils.facility import module_enabled

    if not module_enabled("vaccinations"):
        return False
    today = (today or local_today()).isoformat()
    last = Setting._read(TICK)
    if last == today:
        return False
    if not Setting.swap(TICK, last, today):
        db.session.rollback()
        return False
    db.session.commit()
    try:
        refresh_patterns()
        db.session.commit()
    except Exception:  # noqa: BLE001 — tomorrow's count tries again
        db.session.rollback()
        return False
    return True


# ------------------------------------------------------- for one child ----
def _as_date(value):
    from app.utils.vaccine_due import _as_date as parse

    return parse(value)


def _age_points(due, today):
    if due is None:
        return None
    if due > today + timedelta(days=NOW_AFTER):
        return AGE_LATER, "later"
    if due >= today - timedelta(days=NOW_BEFORE):
        return AGE_NOW, "now"
    return AGE_LATE, "late"


def _siblings_with(patient):
    """``{vaccine_id: [sibling]}`` — brothers and sisters **linked in the
    family file** who had a dose of it."""
    from app.models import Patient, PatientVaccine

    if not patient.family_id:
        return {}
    sibs = {p.id: p for p in Patient.query.filter(Patient.family_id == patient.family_id,
                                                  Patient.id != patient.id,
                                                  Patient.is_active.is_(True))}
    out = defaultdict(list)
    if not sibs:
        return out
    seen = set()
    for pid, vid in (PatientVaccine.query
                     .filter(PatientVaccine.patient_id.in_(sibs),
                             PatientVaccine.event_type == "given")
                     .with_entities(PatientVaccine.patient_id, PatientVaccine.vaccine_id)):
        if (pid, vid) not in seen:
            seen.add((pid, vid))
            out[vid].append(sibs[pid])
    return out


def _patterns_for(taken):
    """``{x_vaccine_id: best VaccinePattern}`` over what the child had."""
    from app.models import VaccinePattern

    if not taken:
        return {}
    best = {}
    for row in VaccinePattern.query.filter(VaccinePattern.a_vaccine_id.in_(taken)):
        if row.x_vaccine_id not in best or row.share > best[row.x_vaccine_id].share:
            best[row.x_vaccine_id] = row
    return best


def gender(patient):
    """``female`` or ``male`` — for the words, «أخدت» or «أخد»."""
    return "female" if (getattr(patient, "gender", "") or "") == "female" else "male"


def priority(score):
    return "high" if score >= HIGH else "medium" if score >= MEDIUM else "low"


def for_patient(patient, plan, on_plan=(), today=None):
    """``[{vaccine, score, priority, age, siblings, pattern, a_vaccine}]``
    for the optional vaccines this child has not started and nobody agreed
    yet, highest first."""
    from app.models import Vaccine
    from app.utils.clock import local_today

    today = today or local_today()
    taken = {item["vaccine"].id for item in plan
             if any(d.get("status") == "done" for d in item["doses"])}
    sibs = _siblings_with(patient)
    patterns = _patterns_for(taken)
    out = []
    for item in plan:
        v = item["vaccine"]
        if (v.is_mandatory or v.on_demand or not v.is_offered or v.id in taken
                or v.id in on_plan or item.get("started")):
            continue
        first = next((d for d in item["doses"] if d.get("status") != "done"), None)
        if first is None or first.get("status") not in OFFERABLE:
            continue
        age = _age_points(_as_date(first.get("due_date")), today)
        if age is None:
            continue
        score, age_key = age
        brothers = sibs.get(v.id, [])
        if brothers:
            score += SIBLING
        pat = patterns.get(v.id)
        pat_points = min(PATTERN_MAX, round(PATTERN_MAX * pat.share)) if pat else 0
        score += pat_points
        out.append({"vaccine": v, "score": score, "priority": priority(score),
                    "age": age_key, "siblings": brothers,
                    "pattern": pat, "pattern_points": pat_points,
                    "a_vaccine": db.session.get(Vaccine, pat.a_vaccine_id) if pat else None})
    out.sort(key=lambda s: (-s["score"], s["vaccine"].sort_order or 0))
    return out


def message(patient, suggestion, lang="ar"):
    """The parents' message, for the person sending it to read and change.
    The brother or sister line only when the family file links them."""
    from app.models import Setting
    from app.utils.whatsapp import first_name_of

    child = first_name_of(patient.display_name(lang))
    vaccine = suggestion["vaccine"].display_name(lang)
    from app.i18n import t

    clinic = Setting.get("clinic_name_ar") or Setting.get("clinic_name") or ""

    lines = [t("vsuggest.msg_open_" + suggestion["age"], child=child, vaccine=vaccine)]
    if suggestion["siblings"]:
        first = suggestion["siblings"][0]
        sib = first_name_of(first.display_name(lang))
        lines.append(t("vsuggest.msg_sibling_" + gender(first), sibling=sib, vaccine=vaccine))
    lines.append(clinic.strip())
    return "\n".join(x for x in lines if x)
