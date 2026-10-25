"""A teaching hospital's learners and its research — GAHAR ATH. Models in
``app/models/teaching.py``.

**The rules the records keep:**

* no trainee without the supervisor who answers for them and the scope they
  work within (ATH.02 ev. 5, ATH.06 ev. 2) — supervision is a name, not a box;
* the orientation is read item by item (ATH.06 a–g), and what is missing
  shows;
* a rotation that has ended without its evaluation is listed (ATH.06 a);
* an assessment names its assessor and its tool, and nobody assesses
  themselves (ATH.07 ev. 4);
* a learner's concern stays open until what was done is written (ATH.05);
* **no child is enrolled in a study** that the research ethics committee has
  not approved, past its approval, or without the guardian's signed research
  consent on the child's own file (ATH.08 ev. 4, ATH.09 ev. 3);
* a family withdraws without giving a reason (ATH.09 d);
* a safety issue during a study is written with the day the family was told
  and what was done (ATH.09 ev. 4).
"""
from datetime import datetime

from app.extensions import db
from app.models.teaching import (ASSESSMENT_TOOLS, CONCERN_KINDS, ORIENTATION_ITEMS, TRAINEE_KINDS,
                                 ResearchParticipant, ResearchProtocol, ResearchSafetyEvent,
                                 TeachingConcern, Trainee, TraineeAssessment, TrainingRotation)
from app.utils.facility_safety import _day, _list, _text


class TeachingError(ValueError):
    """A refusal with a key the screen can name (``teach.err_<key>``)."""


def _today():
    from app.utils.clock import local_today

    return local_today()


def _when(raw, need=True, future_ok=False):
    from app.utils.facility_safety import FacilityError

    try:
        return _day(raw, need=need, future_ok=future_ok)
    except FacilityError as err:
        raise TeachingError(str(err)) from None


def _staff(raw):
    from app.models import User

    try:
        uid = int(raw or 0)
    except (TypeError, ValueError):
        return None
    user = db.session.get(User, uid) if uid else None
    return user if user is not None and user.is_active else None


# ================================================================ trainees ==
def save_trainee(form, row=None):
    kind = form.get("kind")
    if kind not in TRAINEE_KINDS:
        raise TeachingError("need_kind")
    learner = _staff(form.get("user_id"))
    name = _text(form.get("name"), 160) or (learner.full_name if learner else None)
    if not name:
        raise TeachingError("need_name")
    supervisor = _staff(form.get("supervisor_id"))
    if supervisor is None:
        raise TeachingError("need_supervisor")
    if learner is not None and supervisor.id == learner.id:
        raise TeachingError("own_supervisor")
    scope = _text(form.get("scope"))
    if not scope:
        raise TeachingError("need_scope")
    starts, ends = _when(form.get("starts_on"), future_ok=True), _when(form.get("ends_on"), need=False,
                                                                      future_ok=True)
    if ends and ends < starts:
        raise TeachingError("bad_dates")
    mentor = _staff(form.get("mentor_id"))
    row = row or Trainee(orientation={})
    row.user_id = learner.id if learner else None
    row.name, row.kind, row.scope = name, kind, scope
    row.programme = _text(form.get("programme"), 200)
    row.starts_on, row.ends_on = starts, ends
    row.supervisor_id, row.mentor_id = supervisor.id, (mentor.id if mentor else None)
    row.protected_time = _text(form.get("protected_time"), 120)
    if row.id is None:
        db.session.add(row)
    db.session.flush()
    return row


def orient(trainee, form):
    """Tick the orientation items done, each with the day it was done."""
    on = _when(form.get("on"))
    done = dict(trainee.orientation or {})
    for item in _list(form, "items"):
        if item in ORIENTATION_ITEMS and item not in done:
            done[item] = on.isoformat()
    trainee.orientation = done
    db.session.flush()
    return trainee


def orientation_missing(trainee):
    done = trainee.orientation or {}
    return [i for i in ORIENTATION_ITEMS if i not in done]


def add_rotation(trainee, form):
    department = _text(form.get("department"), 160)
    if not department:
        raise TeachingError("need_department")
    starts, ends = _when(form.get("starts_on"), future_ok=True), _when(form.get("ends_on"), future_ok=True)
    if ends < starts:
        raise TeachingError("bad_dates")
    supervisor = _staff(form.get("supervisor_id"))
    if supervisor is None:
        raise TeachingError("need_supervisor")
    row = TrainingRotation(trainee_id=trainee.id, department=department, starts_on=starts, ends_on=ends,
                           supervisor_id=supervisor.id)
    db.session.add(row)
    db.session.flush()
    return row


def evaluate_rotation(rotation, form):
    evaluation = _text(form.get("evaluation"))
    if not evaluation:
        raise TeachingError("need_evaluation")
    rotation.evaluation = evaluation
    rotation.feedback = _text(form.get("feedback"))
    rotation.evaluated_at = datetime.utcnow()
    db.session.flush()
    return rotation


def assess(trainee, assessor, form):
    tool = form.get("tool")
    if tool not in ASSESSMENT_TOOLS:
        raise TeachingError("need_tool")
    result = _text(form.get("result"), 120)
    if not result:
        raise TeachingError("need_result")
    if assessor is None or (trainee.user_id and assessor.id == trainee.user_id):
        raise TeachingError("own_assessment")
    row = TraineeAssessment(trainee_id=trainee.id, on=_when(form.get("on")), tool=tool,
                            assessor_id=assessor.id, result=result, comments=_text(form.get("comments")))
    db.session.add(row)
    db.session.flush()
    return row


def trainees_board(today=None):
    today = today or _today()
    rows = (Trainee.query.filter_by(is_active=True)
            .order_by(Trainee.kind, Trainee.name).all())
    out = []
    for tr in rows:
        out.append({"trainee": tr, "missing": orientation_missing(tr),
                    "unevaluated": [r for r in tr.rotations if r.ends_on < today and not r.evaluation],
                    "current": next((r for r in tr.rotations if r.starts_on <= today <= r.ends_on), None),
                    "finished": bool(tr.ends_on and tr.ends_on < today)})
    return {"rows": out,
            "not_oriented": [r for r in out if r["missing"]],
            "unevaluated": [rot for r in out for rot in r["unevaluated"]]}


def finish(trainee):
    trainee.is_active = False
    db.session.flush()


# ================================================================ concerns ==
def raise_concern(user, form):
    kind = form.get("kind")
    if kind not in CONCERN_KINDS:
        raise TeachingError("need_kind")
    concern = _text(form.get("concern"))
    if not concern:
        raise TeachingError("need_text")
    row = TeachingConcern(kind=kind, raised_on=_when(form.get("raised_on")), concern=concern,
                          raised_by=_text(form.get("raised_by"), 160),
                          recorded_by=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def act_on_concern(row, form):
    action = _text(form.get("action"))
    if not action:
        raise TeachingError("need_action")
    row.action = action
    raw = (form.get("incident_number") or "").strip()
    if raw:
        from app.models import Incident

        incident = Incident.query.filter_by(number=raw).first()
        if incident is None:
            raise TeachingError("no_incident")
        row.incident_id = incident.id
    if form.get("closed_on"):
        row.closed_on = _when(form.get("closed_on"))
    db.session.flush()
    return row


def concerns_board():
    rows = TeachingConcern.query.order_by(TeachingConcern.raised_on.desc()).all()
    return {"rows": rows, "open": [r for r in rows if r.closed_on is None]}


# ================================================================ research ==
def submit_protocol(form, file=None):
    from app.utils.against_advice import is_doctor

    title = _text(form.get("title"), 255)
    eligibility = _text(form.get("eligibility"))
    if not title or not eligibility:
        raise TeachingError("need_protocol")
    investigator = _staff(form.get("investigator_id"))
    if investigator is None or not is_doctor(investigator):
        raise TeachingError("need_investigator")
    row = ResearchProtocol(title=title, investigator_id=investigator.id, eligibility=eligibility,
                           involves_children=form.get("involves_children") != "no", file=file)
    db.session.add(row)
    db.session.flush()
    return row


def decide(protocol, form):
    """The research ethics committee's decision, as the committee gave it.
    An approval carries its reference and the day it was given; a validity
    date is written when the committee set one."""
    state = form.get("state")
    if state not in ("approved", "rejected", "suspended", "closed"):
        raise TeachingError("need_state")
    if state == "approved":
        ref = _text(form.get("rec_reference"), 60)
        if not ref:
            raise TeachingError("need_reference")
        protocol.rec_reference = ref
        protocol.approved_on = _when(form.get("approved_on"))
        protocol.valid_until = _when(form.get("valid_until"), need=False, future_ok=True)
        # Whether the committee allowed a review of past records — what the
        # research export may read beyond the consented participants (ت-٧).
        protocol.record_review = form.get("record_review") == "1"
    protocol.state = state
    protocol.decision_note = _text(form.get("decision_note")) or protocol.decision_note
    db.session.flush()
    return protocol


def open_for_enrolment(protocol, today=None):
    today = today or _today()
    return (protocol.state == "approved" and protocol.approved_on is not None
            and (protocol.valid_until is None or protocol.valid_until >= today))


def research_consents(patient, protocol=None):
    """The guardian's signed research consents on the child's file — signed
    on or after the study's approval when a study is named."""
    from app.models import Consent

    q = Consent.query.filter_by(patient_id=patient.id, consent_type="research")
    if protocol is not None and protocol.approved_on is not None:
        q = q.filter(Consent.signed_date >= protocol.approved_on)
    return q.order_by(Consent.signed_date.desc()).all()


def enroll(protocol, patient, user, form):
    from app.models import Consent

    if not open_for_enrolment(protocol):
        raise TeachingError("not_approved")
    consent = db.session.get(Consent, int(form.get("consent_id") or 0) or 0)
    if consent is None or consent.id not in {c.id for c in research_consents(patient, protocol)}:
        raise TeachingError("need_consent")
    existing = ResearchParticipant.query.filter_by(protocol_id=protocol.id, patient_id=patient.id).first()
    if existing is not None:
        raise TeachingError("already_enrolled")
    row = ResearchParticipant(protocol_id=protocol.id, patient_id=patient.id, consent_id=consent.id,
                              enrolled_on=_when(form.get("enrolled_on")), enrolled_by=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def withdraw(participant, form):
    """ATH.09 (d) — a family leaves a study without giving a reason; the
    note is theirs to give or not."""
    if participant.withdrawn_on is not None:
        raise TeachingError("already_withdrawn")
    participant.withdrawn_on = _when(form.get("withdrawn_on"))
    participant.withdrawn_note = _text(form.get("note"), 255)
    db.session.flush()
    return participant


def safety_event(participant, user, form):
    what, action = _text(form.get("what")), _text(form.get("action"))
    told = _when(form.get("family_told_on"), need=False)
    if not what or not action or told is None:
        raise TeachingError("need_safety")
    row = ResearchSafetyEvent(participant_id=participant.id, on=_when(form.get("on")), what=what,
                              family_told_on=told, action=action, recorded_by=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def research_board(today=None):
    today = today or _today()
    rows = ResearchProtocol.query.order_by(ResearchProtocol.created_at.desc()).all()
    out = []
    for p in rows:
        active = [x for x in p.participants if x.withdrawn_on is None]
        out.append({"protocol": p, "open": open_for_enrolment(p, today), "active": active,
                    "lapsed": p.state == "approved" and p.valid_until is not None and p.valid_until < today})
    return {"rows": out, "awaiting": [r for r in out if r["protocol"].state == "submitted"],
            "lapsed_with_children": [r for r in out if r["lapsed"] and r["active"]]}


def studies_of(patient):
    """The studies a child is in — for the child's own file."""
    return (ResearchParticipant.query.filter_by(patient_id=patient.id)
            .order_by(ResearchParticipant.enrolled_on.desc()).all())


__all__ = ["TeachingError", "act_on_concern", "add_rotation", "assess", "concerns_board", "decide",
           "enroll", "evaluate_rotation", "finish", "open_for_enrolment", "orient", "orientation_missing",
           "raise_concern", "research_board", "research_consents", "safety_event", "save_trainee",
           "studies_of", "submit_protocol", "trainees_board", "withdraw"]
