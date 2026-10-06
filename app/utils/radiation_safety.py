"""The radiation safety program — GAHAR DAS.09 / GSR.12. Models in
``app/models/radiation_safety.py``; the patient's own dose is
``utils/radiation``.

**The rules the records keep:**

* a TLD reading is recorded as the service reported it; it is called over
  only against the investigation level the hospital wrote — and then needs
  what was done beside it;
* the CBC is due six months after the last — the standard's «biannual»; a
  borderline or abnormal one needs the further investigation written;
* an area reading over the limit written beside it, and an apron that
  failed, need the action;
* the MRI questions are the hospital's own; without them nothing is asked,
  and any «yes» needs the decision written. Nothing here stops a scan.
"""
import json
from datetime import date

from app.extensions import db
from app.models.radiation_safety import (APRON_RESULTS, CBC_RESULTS,
                                         MRI_OUTCOMES, ApronCheck,
                                         AreaMeasurement, DoseBadgeReading,
                                         MriScreening, RadiationWorker,
                                         StaffBloodCount)

BADGE_LEVEL_SETTING = "radiation_badge_level_msv"
MRI_QUESTIONS_SETTING = "mri_screening_questions"
CBC_EVERY_MONTHS = 6


class SafetyError(ValueError):
    """A refusal with a key the screen can name (``radsafe.err_<key>``)."""


def _today():
    from app.utils.clock import local_today

    return local_today()


def _day(value, need=True):
    if isinstance(value, date):
        return value
    raw = (value or "").strip()
    if not raw:
        if need:
            raise SafetyError("need_date")
        return None
    try:
        on = date.fromisoformat(raw)
    except ValueError:
        raise SafetyError("bad_date") from None
    if on > _today():
        raise SafetyError("future")
    return on


def _number(value, need=True):
    raw = str(value or "").strip().replace(",", ".")
    if not raw:
        if need:
            raise SafetyError("need_number")
        return None
    try:
        out = float(raw)
    except ValueError:
        raise SafetyError("bad_number") from None
    if out < 0:
        raise SafetyError("bad_number")
    return out


def _text(value, limit=4000):
    return (str(value or "")).strip()[:limit] or None


def may_manage(user):
    """The radiation safety officer sits in radiology."""
    return bool(user is not None and (user.is_admin or user.can_access("imaging")))


# ================================================================ settings ==
def badge_level():
    from app.models import Setting

    raw = str(Setting.get(BADGE_LEVEL_SETTING, "") or "").strip()
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def mri_questions():
    from app.models import Setting

    raw = Setting.get(MRI_QUESTIONS_SETTING, "") or ""
    return [line.strip() for line in str(raw).splitlines() if line.strip()][:40]


def save_settings(form):
    from app.models import Setting

    raw = str(form.get("badge_level") or "").strip()
    if raw:
        if _number(raw) <= 0:
            raise SafetyError("bad_number")
    Setting.set(BADGE_LEVEL_SETTING, raw)
    lines = [line.strip()[:300] for line in str(form.get("mri_questions") or "").splitlines()
             if line.strip()]
    Setting.set(MRI_QUESTIONS_SETTING, "\n".join(lines[:40]))


# ================================================================= workers ==
def add_worker(form):
    from app.models import User

    raw = str(form.get("user_id") or "").strip()
    person = db.session.get(User, int(raw)) if raw.isdigit() else None
    if person is None:
        raise SafetyError("no_person")
    row = RadiationWorker.query.filter_by(user_id=person.id).first()
    if row is None:
        row = RadiationWorker(user_id=person.id)
        db.session.add(row)
    row.area = _text(form.get("area"), 120)
    row.badge_number = _text(form.get("badge_number"), 60)
    row.since = _day(form.get("since"), need=False)
    row.is_active = True
    db.session.flush()
    return row


def stop_worker(row):
    row.is_active = False


def _worker(user_id):
    row = RadiationWorker.query.filter_by(user_id=user_id, is_active=True).first()
    if row is None:
        raise SafetyError("not_worker")
    return row


# ================================================================ readings ==
def badge(user, form):
    worker = _worker(int(form.get("user_id") or 0) if str(form.get("user_id") or "").isdigit() else 0)
    start, end = _day(form.get("period_from")), _day(form.get("period_to"))
    if end < start:
        raise SafetyError("period_order")
    dose = _number(form.get("dose_msv"))
    action = _text(form.get("action"))
    level = badge_level()
    if level is not None and dose > level and not action:
        raise SafetyError("need_action")
    row = DoseBadgeReading(user_id=worker.user_id, period_from=start, period_to=end,
                           dose_msv=dose, reported_by=_text(form.get("reported_by"), 160),
                           action=action, recorded_by=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def blood_count(user, form):
    worker = _worker(int(form.get("user_id") or 0) if str(form.get("user_id") or "").isdigit() else 0)
    result = form.get("result")
    if result not in CBC_RESULTS:
        raise SafetyError("need_result")
    action = _text(form.get("action"))
    if result != "normal" and not action:
        raise SafetyError("need_followup")
    row = StaffBloodCount(user_id=worker.user_id, done_on=_day(form.get("done_on")),
                          result=result, note=_text(form.get("note")), action=action,
                          recorded_by=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def area(user, form):
    name = _text(form.get("area"), 120)
    if not name:
        raise SafetyError("need_area")
    row = AreaMeasurement(area=name, measured_on=_day(form.get("measured_on")),
                          value_usv_h=_number(form.get("value")),
                          limit_usv_h=_number(form.get("limit"), need=False),
                          action=_text(form.get("action")),
                          measured_by=_text(form.get("measured_by"), 160),
                          recorded_by=getattr(user, "id", None))
    if row.over and not row.action:
        raise SafetyError("need_action")
    db.session.add(row)
    db.session.flush()
    return row


def apron(user, form):
    label = _text(form.get("apron"), 80)
    if not label:
        raise SafetyError("need_apron")
    result = form.get("result")
    if result not in APRON_RESULTS:
        raise SafetyError("need_result")
    action = _text(form.get("action"))
    if result == "fail" and not action:
        raise SafetyError("need_action")
    row = ApronCheck(apron=label, checked_on=_day(form.get("checked_on")),
                     method=_text(form.get("method"), 120), result=result, action=action,
                     recorded_by=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


# ==================================================================== MRI ==
def is_mri(order):
    inv = getattr(order, "investigation", None)
    return bool(order is not None and order.kind == "imaging"
                and inv is not None and inv.modality == "mri")


def screen_mri(order, user, form):
    """One screening against today's questions. Every question answered;
    any «yes» needs the decision written. Recorded — never a lock."""
    if not is_mri(order):
        raise SafetyError("not_mri")
    questions = mri_questions()
    if not questions:
        raise SafetyError("no_questions")
    answers = []
    for i, question in enumerate(questions):
        value = form.get(f"q{i}")
        if value not in ("yes", "no"):
            raise SafetyError("unanswered")
        answers.append([question, value])
    outcome = form.get("outcome")
    if outcome not in MRI_OUTCOMES:
        raise SafetyError("need_outcome")
    decision = _text(form.get("decision"))
    if any(v == "yes" for _q, v in answers) and not decision:
        raise SafetyError("need_decision")
    row = MriScreening(order_id=order.id, answers=json.dumps(answers, ensure_ascii=False),
                       outcome=outcome, decision=decision, screened_by=user.id)
    db.session.add(row)
    db.session.flush()
    return row


def last_screening(order):
    if order is None:
        return None
    return (MriScreening.query.filter_by(order_id=order.id)
            .order_by(MriScreening.screened_at.desc(), MriScreening.id.desc()).first())


def answers_of(row):
    try:
        return json.loads(row.answers or "[]")
    except ValueError:
        return []


# ================================================================== board ==
def board(today=None):
    """Every active worker with their newest badge reading and blood count,
    and when the next count is due — overdue and never first."""
    from app.utils.vaccines import add_months

    today = today or _today()
    level = badge_level()
    rows = []
    for worker in (RadiationWorker.query.filter_by(is_active=True)
                   .order_by(RadiationWorker.id).all()):
        last_badge = (DoseBadgeReading.query.filter_by(user_id=worker.user_id)
                      .order_by(DoseBadgeReading.period_to.desc(),
                                DoseBadgeReading.id.desc()).first())
        last_cbc = (StaffBloodCount.query.filter_by(user_id=worker.user_id)
                    .order_by(StaffBloodCount.done_on.desc(),
                              StaffBloodCount.id.desc()).first())
        due = add_months(last_cbc.done_on, CBC_EVERY_MONTHS) if last_cbc else None
        state = "never" if last_cbc is None else ("overdue" if due < today else "ok")
        rows.append({"worker": worker, "badge": last_badge, "cbc": last_cbc,
                     "cbc_due": due, "cbc_state": state,
                     "badge_over": bool(level is not None and last_badge is not None
                                        and last_badge.dose_msv > level)})
    order = {"never": 0, "overdue": 1, "ok": 2}
    rows.sort(key=lambda r: (order[r["cbc_state"]], not r["badge_over"],
                             r["worker"].user.full_name or ""))
    return rows


def recent(model, field, limit=30):
    return model.query.order_by(getattr(model, field).desc(), model.id.desc()).limit(limit).all()
