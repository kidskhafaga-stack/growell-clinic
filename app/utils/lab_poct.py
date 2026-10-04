"""Point-of-care testing — GAHAR DAS.24.

*"Tests designed to be used at or near the site where the patient is
located … performed outside the physical facilities of the clinical
laboratories."* The five pieces of evidence:

1. **a competent person from the laboratory supervises POCT** — the
   hospital names them (``poct_supervisor``);
2. **a competent person performs it** — each device has its trained
   operators, with when they were trained and until when they are
   considered competent; a reading charted by somebody not on the list is
   kept and said;
3. **every POCT site and the tests done there** — the device list, with
   where each one is and what it measures;
4. **a defined process for performing and reporting** — the reading goes on
   the ward's own observation chart, with the meter it was read on;
5. **quality control recorded** — each device's control runs, with the
   action when one fails, and overdue against the laboratory's own
   frequency for that device.
"""
from datetime import date, datetime, timedelta

from app.extensions import db

SUPERVISOR_SETTING = "poct_supervisor"


class PoctError(ValueError):
    """A refusal with a key the screen can name (``lab_poct.err_<key>``)."""


def _day(raw):
    try:
        return date.fromisoformat((raw or "").strip())
    except ValueError:
        return None


def _int(raw):
    try:
        value = int((raw or "").strip())
    except ValueError:
        return None
    return value if value > 0 else None


def supervisor():
    from app.models import Setting, User

    raw = Setting.get(SUPERVISOR_SETTING) or ""
    return db.session.get(User, int(raw)) if raw.isdigit() else None


def set_supervisor(user_id):
    from app.models import Setting, User

    user = db.session.get(User, user_id) if user_id else None
    Setting.set(SUPERVISOR_SETTING, str(user.id) if user else "")
    return user


def active_devices():
    from app.models import PoctDevice

    try:
        return (PoctDevice.query.filter(PoctDevice.is_active.is_(True))
                .order_by(PoctDevice.name).all())
    except Exception:                   # noqa: BLE001 — table not there yet
        return []


def device_for(raw):
    from app.models import PoctDevice

    if not (raw or "").isdigit():
        return None
    row = db.session.get(PoctDevice, int(raw))
    return row if row is not None and row.is_active else None


def save_device(form, row=None):
    from app.models import PoctDevice, User

    name = (form.get("name") or "").strip()[:160]
    if not name:
        raise PoctError("need_name")
    if row is None:
        row = PoctDevice(name=name)
        db.session.add(row)
    row.name = name
    row.kind = (form.get("kind") or "").strip()[:80] or None
    row.serial = (form.get("serial") or "").strip()[:80] or None
    row.location = (form.get("location") or "").strip()[:120] or None
    row.tests = (form.get("tests") or "").strip()[:200] or None
    row.qc_every_days = _int(form.get("qc_every_days"))
    responsible = form.get("responsible_id")
    row.responsible_id = (int(responsible) if (responsible or "").isdigit()
                          and db.session.get(User, int(responsible)) else None)
    marks = form.getlist("is_active") if hasattr(form, "getlist") else []
    row.is_active = ("1" in marks) if marks else True
    db.session.flush()
    return row


def add_operator(device, form):
    from app.models import PoctOperator, User

    raw = form.get("user_id") or ""
    user = db.session.get(User, int(raw)) if raw.isdigit() else None
    if user is None:
        raise PoctError("need_user")
    row = next((o for o in device.operators if o.user_id == user.id), None)
    if row is None:
        row = PoctOperator(device_id=device.id, user_id=user.id)
        db.session.add(row)
    row.trained_on = _day(form.get("trained_on"))
    row.competent_until = _day(form.get("competent_until"))
    db.session.flush()
    return row


def is_operator(device, user, today=None):
    from app.utils.clock import local_today

    today = today or local_today()
    for row in device.operators:
        if row.user_id == getattr(user, "id", None):
            return row.competent_until is None or row.competent_until >= today
    return False


def record_qc(device, form, user=None, at=None):
    from app.models import PoctQc

    result = (form.get("result") or "").strip()[:80]
    if not result:
        raise PoctError("need_result")
    passed = form.get("passed", "1") != "0"
    action = (form.get("action") or "").strip()[:255] or None
    row = PoctQc(device_id=device.id, run_at=at or datetime.utcnow(),
                 run_by=getattr(user, "id", None),
                 level=(form.get("level") or "").strip()[:40] or None,
                 result=result, passed=passed, action=action)
    db.session.add(row)
    db.session.flush()
    return row


def qc_action(check, text):
    text = (text or "").strip()[:255]
    if not text:
        raise PoctError("need_action")
    check.action = text
    db.session.flush()
    return check


def qc_state(device, now=None):
    """``"failed"`` (last control failed with no action), ``"overdue"``
    (past the laboratory's own frequency), ``"ok"``, or ``None`` when there
    is nothing to judge."""
    last = device.checks[-1] if device.checks else None
    if last is not None and not last.passed and not last.action:
        return "failed"
    if device.qc_every_days:
        if last is None:
            return "overdue"
        if (now or datetime.utcnow()) - last.run_at > timedelta(days=device.qc_every_days):
            return "overdue"
    return "ok" if last is not None else None


def needing_attention():
    return sum(1 for d in active_devices() if qc_state(d) in ("failed", "overdue"))


def readings(device, limit=30):
    from app.models import Observation

    return (Observation.query.filter(Observation.poct_device_id == device.id)
            .order_by(Observation.taken_at.desc()).limit(limit).all())
