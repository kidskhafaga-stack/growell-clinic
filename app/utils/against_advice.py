"""Leaving against medical advice — DAMA from a stay, LAMA from emergency.

The program has long known *that* a family took their child away against
advice: ``self_discharge`` is an outcome of a stay and a disposition of an
emergency attendance, apart from going home, transfer and death, and
``left_unseen`` is a third thing again (nobody saw the child to advise
anything). What it did not hold, at the moment it happened, was the record a
hospital is judged on (GAHAR PCC.10) and a child is protected by:

* what the family refused and what they were told — the child's condition,
  the consequences, the alternatives — by a **doctor**, named;
* the doctor's own assessment at that moment: how ill the child is, whether
  leaving now is a serious danger, and whether the decision itself raises a
  concern for the child's safety;
* who signed, or that the guardian **refused to sign**, with a witness;
* what was arranged before they left — medicines, an appointment, the signs
  to come straight back for;
* and, when the doctor judged a serious danger or a safeguarding concern,
  **to whom it was escalated and when**.

A guardian's signature is evidence of what was explained. It is not a
release: a child in serious danger, or whose family's decision raises a
concern, is escalated whatever was signed. So the screen never treats the
form as the end of the hospital's duty, and the report keeps the escalations
apart.

**The hospital decides how strict this is** (``POLICY_SETTING``):

* ``record`` (the default — nothing changes for a hospital that has not
  chosen): choosing "against advice" closes the episode in one tap, as it
  always has, and opens the form; every missing element stays loud on the
  form, the ward's watch screen and the report until it is written;
* ``require``: choosing "against advice" opens the form without closing,
  and the episode does not close against advice until the four
  elements, the doctor, the guardian, a signature or a witnessed refusal to
  sign, and — when called for — the escalation are written.
"""
from datetime import datetime, time

from app.extensions import db
from app.models.refusal import DISCHARGE, ELEMENTS, EMERGENCY, Refusal

POLICY_SETTING = "ama_policy"
POLICIES = ("record", "require")
#: How an episode ends against advice, on either kind of record.
AGAINST_ADVICE = "self_discharge"


class AgainstAdviceError(ValueError):
    """A refusal to close, carrying what is missing (``missing``)."""

    def __init__(self, key, missing=None):
        super().__init__(key)
        self.missing = missing or []


def policy():
    from app.models import Setting

    value = (Setting.get(POLICY_SETTING) or "").strip()
    return value if value in POLICIES else "record"


def set_policy(value):
    from app.models import Setting

    if value not in POLICIES:
        raise AgainstAdviceError("policy")
    Setting.set(POLICY_SETTING, value)


def _text(raw, limit=None):
    s = (raw or "").strip()
    return (s[:limit] if limit else s) or None


def _yes(raw):
    return True if raw == "yes" else False if raw == "no" else None


def is_doctor(user):
    return bool(user is not None and getattr(user, "is_active", True)
                and (getattr(user, "role", None) == "doctor" or getattr(user, "is_practitioner", False)))


def doctors():
    from app.models import User

    return (User.query.filter(User.is_active.is_(True),
                              db.or_(User.role == "doctor", User.is_practitioner.is_(True)))
            .order_by(User.full_name).all())


# ------------------------------------------------------------ episodes --
def episode(kind, episode_id):
    """``(record, patient, refusal_kind)`` for a stay or an attendance."""
    from app.models import Admission, EmergencyVisit

    if kind == "stay":
        row = db.session.get(Admission, episode_id)
        return (row, row.patient if row else None, stay_kind(row)) if row else (None, None, None)
    if kind == "er":
        row = db.session.get(EmergencyVisit, episode_id)
        return (row, row.patient if row else None, EMERGENCY) if row else (None, None, None)
    return None, None, None


def stay_kind(admission):
    """A stay in an emergency bed is LAMA; any other stay is DAMA."""
    from app.utils.cost_centres import unit_on

    unit = unit_on(admission, None) if admission is not None else None
    return EMERGENCY if unit is not None and unit.kind == "emergency" else DISCHARGE


def is_open(kind, row):
    if row is None:
        return False
    return row.is_open if kind == "stay" else row.departed_at is None


def refusal_for(kind, row):
    if row is None:
        return None
    q = Refusal.query.filter(Refusal.admission_id == row.id) if kind == "stay" \
        else Refusal.query.filter(Refusal.emergency_visit_id == row.id)
    return q.order_by(Refusal.id.desc()).first()


# -------------------------------------------------------------- the form --
def missing(row):
    """Every element still to write, by name — the four of PCC.10 and the
    ones a departure against advice adds."""
    if row is None:
        return list(ELEMENTS) + ["doctor", "doctor_assessment", "guardian", "signature", "risk",
                                 "followup_plan"]
    out = [name for name in ELEMENTS if not (getattr(row, name) or "").strip()]
    if not is_doctor(row.explained_by):
        out.append("doctor")
    if not (row.doctor_assessment or "").strip():
        out.append("doctor_assessment")
    if not (row.guardian_name or "").strip():
        out.append("guardian")
    if not row.signature_file and not (row.signature_refused and (row.witness_name or "").strip()):
        out.append("signature")
    if row.serious_risk is None or row.safeguarding is None:
        out.append("risk")
    if row.needs_escalation and not row.escalated:
        out.append("escalation")
    if not (row.followup_plan or "").strip():
        out.append("followup_plan")
    return out


def save_form(kind, row, patient, refusal_kind, form, user):
    """Write (or update) the episode's form. Fields not sent are not
    touched; an empty one is cleared only when it was sent empty."""
    from app.models import User

    record = refusal_for(kind, row)
    if record is None:
        record = Refusal(patient_id=patient.id, kind=refusal_kind,
                         admission_id=row.id if kind == "stay" else None,
                         emergency_visit_id=row.id if kind == "er" else None,
                         recorded_by_id=getattr(user, "id", None))
        db.session.add(record)
    for name in ELEMENTS + ("doctor_assessment", "followup_plan"):
        if name in form:
            setattr(record, name, _text(form.get(name)))
    for name, limit in (("guardian_name", 120), ("guardian_relation", 20), ("guardian_id_no", 20),
                        ("witness_name", 120)):
        if name in form:
            setattr(record, name, _text(form.get(name), limit))
    if "explained_by" in form:
        doctor = db.session.get(User, form.get("explained_by", type=int) or 0)
        record.explained_by_id = doctor.id if is_doctor(doctor) else None
    elif record.explained_by_id is None and is_doctor(user):
        record.explained_by_id = user.id
    for name in ("serious_risk", "safeguarding", "signature_refused"):
        if name in form:
            setattr(record, name, _yes(form.get(name)))
    escalated = _text(form.get("escalated_to"), 160)
    record._escalated_now = bool(escalated and escalated != record.escalated_to)
    if record._escalated_now:
        record.escalated_to, record.escalated_at = escalated, datetime.utcnow()
        record.escalated_by = getattr(user, "id", None)
    db.session.flush()
    return record


def close(kind, row, patient, form, user, finish):
    """Save the form and, when the episode is still open, close it against
    advice through ``finish`` (the caller's own discharge path, so the bill
    and the survey follow as on every other discharge).

    Under ``require`` nothing closes while anything is missing; under
    ``record`` it closes and the gaps stay on the watch screen."""
    from app.models import ActivityLog

    _, _, refusal_kind = episode(kind, row.id)
    record = save_form(kind, row, patient, refusal_kind, form, user)
    gaps = missing(record)
    if is_open(kind, row) and form.get("close") == "1":
        if policy() == "require" and gaps:
            raise AgainstAdviceError("incomplete", gaps)
        finish()
        ActivityLog.record("discharge.against_advice", user_id=getattr(user, "id", None),
                           entity="admission" if kind == "stay" else "emergency_visit", entity_id=row.id,
                           detail=f"{refusal_kind}; missing={','.join(gaps) or '-'}")
    else:
        ActivityLog.record("refusal.update", user_id=getattr(user, "id", None), entity="refusal",
                           entity_id=record.id, detail=",".join(gaps) or "-")
    if getattr(record, "_escalated_now", False):
        ActivityLog.record("refusal.escalated", user_id=getattr(user, "id", None), entity="refusal",
                           entity_id=record.id, detail=record.escalated_to)
    db.session.flush()
    return record, gaps


def holds_the_exit():
    """Whether choosing "against advice" on the ward or in emergency waits
    for the form. Under ``record`` (the default) it never does — the family
    is not held at the door, the episode closes with its reason in one tap
    as it always has, and the screen then opens the form so it is written
    while they are still there; under ``require`` the form closes it."""
    return policy() == "require"


def closed_by_one_tap(kind, row, user):
    """The audit line for an episode closed against advice from the ward
    or emergency screen, before its form was written."""
    from app.models import ActivityLog

    _, _, refusal_kind = episode(kind, row.id)
    gaps = missing(refusal_for(kind, row))
    ActivityLog.record("discharge.against_advice", user_id=getattr(user, "id", None),
                       entity="admission" if kind == "stay" else "emergency_visit", entity_id=row.id,
                       detail=f"{refusal_kind}; one-tap; missing={','.join(gaps) or '-'}")


# ---------------------------------------------------------------- report --
def report(start, end):
    """Every departure against advice in a period, each with the state of
    its record: DAMA (stays), LAMA (emergency — a bed or the chairs), and
    left-before-being-seen kept apart, because nobody could advise them."""
    from app.models import Admission, EmergencyVisit
    from app.utils.clock import to_utc

    since = to_utc(datetime.combine(start, time.min))
    until = to_utc(datetime.combine(end, time.max))
    rows = []
    for stay in (Admission.query.filter(Admission.outcome == AGAINST_ADVICE,
                                        Admission.discharged_at >= since, Admission.discharged_at <= until)
                 .order_by(Admission.discharged_at.desc()).all()):
        rec = refusal_for("stay", stay)
        rows.append({"what": "lama" if stay_kind(stay) == EMERGENCY else "dama", "kind": "stay",
                     "row": stay, "patient": stay.patient, "at": stay.discharged_at, "refusal": rec,
                     "missing": missing(rec)})
    unseen = []
    for er in (EmergencyVisit.query.filter(EmergencyVisit.disposition.in_((AGAINST_ADVICE, "left_unseen")),
                                           EmergencyVisit.departed_at >= since,
                                           EmergencyVisit.departed_at <= until)
               .order_by(EmergencyVisit.departed_at.desc()).all()):
        if er.disposition == "left_unseen":
            unseen.append(er)
            continue
        rec = refusal_for("er", er)
        rows.append({"what": "lama", "kind": "er", "row": er, "patient": er.patient, "at": er.departed_at,
                     "refusal": rec, "missing": missing(rec)})
    rows.sort(key=lambda r: r["at"] or datetime.min, reverse=True)
    complete = [r for r in rows if not r["missing"]]
    return {"rows": rows, "unseen": unseen,
            "dama": sum(1 for r in rows if r["what"] == "dama"),
            "lama": sum(1 for r in rows if r["what"] == "lama"),
            "complete": len(complete),
            "no_form": sum(1 for r in rows if r["refusal"] is None),
            "escalations": [r for r in rows if r["refusal"] is not None and r["refusal"].needs_escalation],
            "not_escalated": [r for r in rows if r["refusal"] is not None and r["refusal"].needs_escalation
                              and not r["refusal"].escalated]}


__all__ = ["AGAINST_ADVICE", "AgainstAdviceError", "POLICIES", "POLICY_SETTING", "close", "closed_by_one_tap",
           "doctors", "episode", "holds_the_exit", "is_doctor", "is_open", "missing", "policy", "refusal_for", "report", "save_form", "set_policy",
           "stay_kind"]
