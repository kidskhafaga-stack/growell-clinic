"""مين اتشرحله إيه، وفهم ولا لأ — PCC.07.

اقرا `models/patient_education.py` الأول للسبب في تلات أعمدة بدل بوليان.

الملف ده بيجاوب السؤال اللي المراجِع بيفتح الملف علشانه — *"review a sample
of patients' medical records to check the **completion** of patient and
family education records"* — وكلمة **completion** هي اللي بتخلّيه موجود: مش
«فيه تثقيف؟» لأ، **«ناقص إيه؟»**.

---

**والناقص نوعين، والفرق بينهم هو التصميم.**

التلات مواضيع اللي (أ) بيسمّيها *"for **all** patients"* — التشخيص، خطة
الرعاية، تعليمات الخروج — ناقصة لأي طفل مالهوش صف فيها. خلاص.

والباقي **مشروط بالسجل**: طفل محدّش لقاه معرّض للسقوط مش محتاج تثقيف سقوط،
وقايمة بتطلبه منه برضه هي قايمة الورديّة بتتعلّم تدوس عليها من غير ما تقراها.
فالمواضيع دي بتتحسب من اللي حصل فعلاً: تقييم خطر قال «معرّض» · طلب دم ·
موافقة اتوقّعت. **ومحدّش بيسجّل إنها مطلوبة — البرنامج بيشوفها.**

**وفهم ولا لأ هو الفرق بين «اتقال» و«اتعمل».** صف فيه كلام ومحدّش أكّد الفهم
بيتحسب موجود-وناقص، مش موجود.
"""
from app.extensions import db
from app.models.patient_education import (BLOOD, CONSENT, FALL, METHODS,
                                          PRESSURE, REQUIRED_TOPICS, TOPICS,
                                          VERBAL, VTE, PatientEducation)

#: Where one topic stands for one child.
#:
#: ``none``      nobody has taught it
#: ``unchecked`` taught, and nobody confirmed they understood
#: ``again``     confirmed **not** understood — somebody has to go back
#: ``done``      taught and understood
NONE, UNCHECKED, AGAIN, DONE = ("none", "unchecked", "again", "done")
TOPIC_STATES = (NONE, UNCHECKED, AGAIN, DONE)

#: The conditional topics, and the question in the record that calls for each.
#: A tuple rather than three ifs so the reasons stay listed in one place.
RISK_TOPICS = ((FALL, "fall"), (PRESSURE, "pressure"), (VTE, "vte"))


def given(patient_id, limit=200):
    """This child's education, newest first."""
    if not patient_id:
        return []
    return (PatientEducation.query
            .filter(PatientEducation.patient_id == patient_id)
            .order_by(PatientEducation.at.desc(), PatientEducation.id.desc())
            .limit(limit).all())


def state(rows, topic):
    """Where one topic stands, from rows already read.

    **The best row wins, not the newest.** A family taught twice — once
    without a check and once with — has been taught; reading only the latest
    would let a hurried second entry undo a confirmed first one. And ``again``
    outranks ``unchecked`` because "they did not understand" is somebody's
    errand while "nobody asked" is only a gap.
    """
    mine = [r for r in rows if r.topic == topic]
    if not mine:
        return NONE
    if any(r.understood is True for r in mine):
        return DONE
    if any(r.understood is False for r in mine):
        return AGAIN
    return UNCHECKED


def owed(patient_id, rows=None):
    """Which topics this child is owed, and where each stands.

    The required three always, plus the conditional ones the record gives a
    reason for. See the module docstring on why a topic nothing calls for is
    left out rather than listed and ignored.
    """
    topics = list(REQUIRED_TOPICS)
    for topic in _because_of_the_record(patient_id):
        if topic not in topics:
            topics.append(topic)
    rows = given(patient_id) if rows is None else rows
    return [{"topic": t, "state": state(rows, t)} for t in topics]


def _because_of_the_record(patient_id):
    """The conditional topics this child's own record asks for.

    Each one is a standard that names `PCC.07` in its related list, and each
    is read from the thing that would have prompted the teaching — never from
    a flag somebody had to remember to set.
    """
    out = list(_risk_topics(patient_id))
    if _has_blood(patient_id):
        out.append(BLOOD)
    if _has_consent(patient_id):
        out.append(CONSENT)
    return out


def _risk_topics(patient_id):
    """`ICD.10`/`ICD.11`/`ICD.12` — but only where a child was **found** at
    risk. Evidence 5 is about *"the families of patients who are at higher
    risk"*, so a completed assessment that found nothing asks for nothing."""
    from app.models.risk_assessment import RiskAssessment

    try:
        rows = (db.session.query(RiskAssessment.kind)
                .filter(RiskAssessment.patient_id == patient_id,
                        RiskAssessment.at_risk.is_(True))
                .distinct().all())
    except Exception:                   # noqa: BLE001 — table not ready yet
        return []
    found = {r[0] for r in rows}
    return [topic for topic, kind in RISK_TOPICS if kind in found]


def _has_blood(patient_id):
    """`ICD.20` (ب) — *"Education of patient and family about proposed
    transfusion."* Asked from the request, because the teaching belongs
    **before** the bag goes up."""
    from app.models.blood import BloodRequest

    try:
        return (BloodRequest.query
                .filter(BloodRequest.patient_id == patient_id)
                .first() is not None)
    except Exception:                   # noqa: BLE001
        return False


def _has_consent(patient_id):
    """`PCC.08` names `PCC.07` in its related list: a signature on something
    nobody explained is the thing informed consent exists to prevent."""
    from app.models import Consent

    try:
        return (Consent.query.filter(Consent.patient_id == patient_id)
                .first() is not None)
    except Exception:                   # noqa: BLE001
        return False


def missing(patient_id, rows=None):
    """The topics with nothing taught at all — the plain gaps."""
    return [item["topic"] for item in owed(patient_id, rows)
            if item["state"] == NONE]


def not_understood(patient_id, rows=None):
    """The topics somebody taught and the family did **not** understand.

    A finding rather than a gap: it names a person who has to go back, and it
    exists only because the confirmation is its own column.
    """
    return [item["topic"] for item in owed(patient_id, rows)
            if item["state"] == AGAIN]


def said_told_but_never_taught(patient_id):
    """Where a tick says the family knows and no teaching was ever recorded.

    **The reason this module is worth more than its own table.** Three screens
    already ask «الأهل اتقالهم؟» as a yes/no beside the thing it was about —
    a risk assessment, a blood request, a plan of care. That tick answers its
    own standard's evidence and it cannot answer `PCC.07` (د), which wants the
    content, the method and the confirmation.

    So a ``True`` there with no education row for the matching topic is a real
    gap that nothing could see before: somebody ticked, and the record holds
    nothing a surveyor could read.
    """
    from app.models.blood import BloodRequest
    from app.models.risk_assessment import RiskAssessment

    rows = given(patient_id)
    out = []
    try:
        ticked = {r[0] for r in db.session.query(RiskAssessment.kind).filter(
            RiskAssessment.patient_id == patient_id,
            RiskAssessment.family_told.is_(True)).distinct().all()}
    except Exception:                   # noqa: BLE001
        ticked = set()
    for topic, kind in RISK_TOPICS:
        if kind in ticked and state(rows, topic) == NONE:
            out.append(topic)
    try:
        blood_ticked = (BloodRequest.query.filter(
            BloodRequest.patient_id == patient_id,
            BloodRequest.family_told.is_(True)).first() is not None)
    except Exception:                   # noqa: BLE001
        blood_ticked = False
    if blood_ticked and state(rows, BLOOD) == NONE:
        out.append(BLOOD)
    return out


def record(patient, topic, user=None, detail=None, method=None,
           understood=None, interpreter=False, visit=None, admission=None,
           at=None):
    """Write one piece of teaching. Caller commits.

    Raises ``ValueError`` for a topic or a method the screen cannot draw — a
    word no screen shows is a record nobody will ever read again.

    **Nothing else is required, not even the detail.** A nurse who showed a
    mother how to use a spacer and ticked «فهمت» has recorded something true;
    refusing it without a paragraph would send the commonest teaching in the
    clinic to nowhere.
    """
    if patient is None:
        raise ValueError("no patient")
    if topic not in TOPICS:
        raise ValueError("unknown topic")
    how = method or VERBAL
    if how not in METHODS:
        raise ValueError("unknown method")
    row = PatientEducation(
        patient_id=patient.id,
        visit_id=getattr(visit, "id", None),
        admission_id=getattr(admission, "id", None),
        topic=topic,
        detail=(detail or "").strip() or None,
        method=how,
        interpreter=bool(interpreter),
        understood=understood,
        by_id=getattr(user, "id", None))
    # Set only when a moment was given, so the column's own default stands
    # otherwise. Assigning ``None`` would beat the default and leave a row
    # with no time on it, and the column is not nullable.
    if at is not None:
        row.at = at
    db.session.add(row)
    return row
