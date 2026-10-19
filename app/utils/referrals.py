"""قراية `ACT.14` — الورقة اللي راحت، واللي رجع منها.

دليل ٤ بيطلب **ورقة كاملة** بتمن بنود، ودليل ٥ بيطلب **الدايرة تتقفل**.
والملف ده بيجاوب على التلات أسئلة اللي مكانش حد بيسألهم:

* **راحت ومحدّش رد** → :func:`waiting`.
* **رجع رد ومحدّش راجعه** → :func:`unsigned` — وده أوحش نوع نقص،
  لأنه **بيبان مكتمل**: أي قايمة بتعدّ الردود بتشوفه رد. وهو بيحصل
  فعلاً، مش حالة نظرية: الاستقبال بياخد الورقة من الأهل ويحطّها في
  الملف، والطبيب اللي المفروض يقراها ما شفهاش.
* **ناقص إيه في الورقة نفسها** → :func:`missing`, **بالاسم**.

---

**ومفيش مهلة مخترعة.** `ACT.10` بيقول *within a **predefined** time frame*
فالبرنامج عمل إعداد للعيادة تكتبه. `ACT.14` **ما بيقولش** — فالقايمة
بتقول بقالها كام يوم وبس، ومفيش خط أحمر من عندنا. اختراع «أسبوعين»
هنا نفس اختراع مقياس فرز.

**والبندين (iii) و(iv) بيتجمّعوا وقت القراية مش بيتخزّنوا.** التقييمات
في الزيارة والدوا في الروشتة؛ نسخهم هنا معناه إجابتين لنفس السؤال،
ونسخة بتقدم أول ما الروشتة تتعدّل.
"""
from datetime import datetime

from app.extensions import db
from app.models.referral import DOCTOR, KINDS, REFERRAL, ExternalDoctor, Referral

#: البنود اللي **حد لازم يكتبها** — ودي اللي :func:`missing` بتعدّها.
#:
#: (i) تعريف المريض بيجي من الصف نفسه، و(ii) السبب مرفوض عند الباب من
#: غيره. و(iii) و(iv) بيتجمّعوا من الملف — و«مفيش دوا» حالة صحيحة مش
#: نقص، فعدّهم كان هيخلّي كل طفل مش واخد دوا يبان ورقته ناقصة.
WRITTEN = ("sent_to", "transport", "monitoring", "condition")


def refer(patient, reason, kind=REFERRAL, user=None, visit=None,
          admission=None, sent_to=None, transport=None, monitoring=None,
          condition=None, at=None):
    """ورقة جديدة. المتصل بيعمل commit.

    ``reason`` مطلوب: ورقة رايحة لمستشفى تانية من غير سبب هي طفل بيوصل
    لحد ما يعرف ليه جه.
    """
    if patient is None:
        raise ValueError("no patient")
    if kind not in KINDS:
        raise ValueError("unknown kind")
    why = (reason or "").strip()
    if not why:
        raise ValueError("no reason")
    row = Referral(
        patient_id=patient.id, kind=kind, reason=why,
        visit_id=getattr(visit, "id", None),
        admission_id=getattr(admission, "id", None),
        decided_by_id=getattr(user, "id", None),
        sent_to=(sent_to or "").strip()[:120] or None,
        transport=(transport or "").strip()[:120] or None,
        monitoring=(monitoring or "").strip() or None,
        condition=(condition or "").strip() or None)
    if at is not None:
        row.decided_at = at
    db.session.add(row)
    return row


def describe(row, **fields):
    """بنود بتتكتب بعد ما الورقة تمشي. اللي ما اتبعتش ما بيتغيّرش."""
    if row is None:
        raise ValueError("no referral")
    for name in ("monitoring", "condition"):
        if fields.get(name) is not None:
            setattr(row, name, (fields[name] or "").strip() or None)
    for name in ("sent_to", "transport"):
        if fields.get(name) is not None:
            setattr(row, name, (fields[name] or "").strip()[:120] or None)
    return row


def answer(row, text, user=None, at=None):
    """دليل ٥، النص الأول — الرد **اتسجّل**. المتصل بيعمل commit.

    **وده مش توقيع.** موظف الاستقبال بياخد الورقة من الأهل ويحطّها في
    الملف؛ ده *recorded*. والمعيار كاتب *reviewed, **signed*** جنبها،
    ودول بيحصلوا لما الطبيب يقراها — ممكن بعدها بيومين. :func:`review`
    هي دي.
    """
    if row is None:
        raise ValueError("no referral")
    body = (text or "").strip()
    if not body:
        raise ValueError("no feedback text")
    if row.feedback_at is None:
        row.feedback_at = at or datetime.utcnow()
    row.feedback = body
    row.recorded_by_id = getattr(user, "id", None)
    return row


def review(row, user=None, at=None):
    """دليل ٥، النص التاني — حد **قراه ووقّع**. المتصل بيعمل commit.

    ورقة من غير التوقيع ده هي الصف اللي :func:`unsigned` بيطلّعه: عنده
    كل حاجة إلا إن حد شافها.
    """
    if row is None:
        raise ValueError("no referral")
    if not (row.feedback or "").strip():
        # توقيع على لا حاجة. الصف ده بيبان بعدين «الدايرة اتقفلت»
        # وهي ما اتقفلتش.
        raise ValueError("nothing to review")
    row.reviewed_by_id = getattr(user, "id", None)
    row.reviewed_at = at or datetime.utcnow()
    return row


def cancel(row, at=None):
    """**مش مسح.** إحالة اتكتبت على الطفل الغلط بتحصل في نفس الدقايق
    دي، والصف بيفضل علشان يفضل مقروء."""
    if row is None:
        raise ValueError("no referral")
    row.cancelled_at = at or datetime.utcnow()
    return row


def missing(row):
    """ناقص إيه من الورقة — **بالاسم**، مش «غير مكتملة»."""
    if row is None:
        return []
    if row.kind == DOCTOR:
        # A doctor down the corridor or across town: no ambulance, no
        # monitoring on the way. Who it went to and why are taken at the
        # door, so only (viii) can still be missing.
        return [] if row.decided_by_id is not None else ["decided_by"]
    gaps = [name for name in WRITTEN
            if not (getattr(row, name, None) or "").strip()]
    # (viii) مش نص، فبيتسأل لوحده: **مين قرّر**. وده البند اللي
    # `ActivityLog` كان بيرد عليه، واللي بيستقبل الطفل ما بيفتحوش.
    if row.decided_by_id is None:
        gaps.append("decided_by")
    return gaps


def _live(query):
    return query.filter(Referral.cancelled_at.is_(None))


def for_patient(patient_id, limit=50):
    return (_live(Referral.query.filter_by(patient_id=patient_id))
            .order_by(Referral.decided_at.desc()).limit(limit).all())


def latest_for_visit(visit_id):
    """The emergency/hospital paper of this visit — not a referral to a
    doctor, which has its own card and its own cancel."""
    return (_live(Referral.query.filter(Referral.visit_id == visit_id,
                                        Referral.kind != DOCTOR))
            .order_by(Referral.decided_at.desc(), Referral.id.desc()).first())


def waiting(limit=200):
    """راحت ومحدّش رد — **الإحالات بس**.

    التحويل الطفل مشي فيه خلاص، وانتظار رد عليه بيملا القايمة بصفوف
    عمرها ما هتتقفل — وقايمة فيها صفوف مستحيلة بتعلّم اللي بيقراها
    إنه يتجاهلها.

    **وأقدم الأول**، زي كل قايمة انتظار في البرنامج: اللي بتحطّ النهاردة
    فوق هي اللي بتاعة الشهر اللي فات لسه فيها آخر السنة.
    """
    return (_live(Referral.query.filter(Referral.kind.in_((REFERRAL, DOCTOR)),
                                        Referral.feedback_at.is_(None)))
            .order_by(Referral.decided_at.asc()).limit(limit).all())


def unsigned(limit=200):
    """**رجع رد ومحدّش راجعه** — أوحش نوع نقص، لأنه بيبان مكتمل.

    الصف ده عنده كل حاجة: ورقة راحت، ورد رجع، ونص مكتوب. وأي جرد بيعدّ
    «الردود» بيشوفه رد. اللي ناقصه إن **حد شافه** — ودليل ٥ كاتب
    *reviewed, signed* جنب *recorded* بالظبط علشان كده.
    """
    return (_live(Referral.query.filter(Referral.feedback_at.isnot(None),
                                        Referral.reviewed_at.is_(None)))
            .order_by(Referral.feedback_at.asc()).limit(limit).all())


def incomplete(limit=200):
    """ورق ناقص بنود من التمانية — دليل ٤."""
    rows = (_live(Referral.query).order_by(Referral.decided_at.desc())
            .limit(limit).all())
    return [row for row in rows if missing(row)]


def sheet(row):
    """الورقة كاملة — واللي مش موجود فيها **باسمه**.

    (iii) و(iv) بيتجمّعوا من الملف هنا، مش من أعمدة متخزّنة. ولو الملف
    مفيهوش حاجة، الورقة بتقول كده بدل ما تسيب فراغ: فراغ بيتقرا عند
    المستقبِل «مفيش»، وده مش نفس «محدّش كتب».
    """
    if row is None:
        return None
    return {
        "referral": row,
        "patient": row.patient,                       # (i)
        "reason": row.reason,                         # (ii)
        "assessments": _assessments(row),             # (iii)
        "medicines": _medicines(row),                 # (iv)
        "transport": row.transport,                   # (v)
        "monitoring": row.monitoring,                 # (v)
        "condition": row.condition,                   # (vi)
        "sent_to": row.sent_to,                       # (vii)
        "decided_by": row.decided_by,                 # (viii)
        "missing": missing(row),
    }


def _assessments(row):
    """(iii) اللي اتجمع في الزيارة — مش نسخة منه."""
    visit = row.visit
    if visit is None:
        return {}
    return {name: value for name, value in (
        ("complaint", visit.chief_complaint),
        ("exam", visit.clinical_exam),
        ("plan", visit.plan),
        ("vitals", visit.vitals),
    ) if value}


def _medicines(row):
    """(iv) الدوا من الروشتة، بأسماء الأصناف زي ما اتكتبت.

    **ومفيش دوا مش نقص.** طفل مش واخد حاجة ورقته كاملة — وعدّها نقص
    كان هيخلّي القايمة تصرخ على كل ورقة.
    """
    from app.models import Prescription, PrescriptionItem

    query = (db.session.query(PrescriptionItem)
             .join(Prescription,
                   PrescriptionItem.prescription_id == Prescription.id)
             .filter(Prescription.patient_id == row.patient_id))
    if row.visit_id is not None:
        query = query.filter(Prescription.visit_id == row.visit_id)
    return [{"name": item.drug_name, "dose": item.dose,
             "frequency": item.frequency, "duration": item.duration}
            for item in query.order_by(PrescriptionItem.id).all()]


# ---- ب-٨: تحويل لطبيب -------------------------------------------------
def external_doctor(name, specialty=None, place=None, phone=None):
    """The clinic's book of outside doctors: the same name at the same
    place is the same doctor, kept once. ``None`` without a name."""
    name = " ".join((name or "").split())[:160]
    if not name:
        return None
    place = " ".join((place or "").split())[:200] or None
    row = (ExternalDoctor.query
           .filter(db.func.lower(ExternalDoctor.name) == name.lower())
           .filter(db.func.lower(db.func.coalesce(ExternalDoctor.place, ""))
                   == (place or "").lower())
           .first())
    if row is None:
        row = ExternalDoctor(name=name, place=place)
        db.session.add(row)
    spec = " ".join((specialty or "").split())[:160]
    if spec:
        row.specialty = spec
    tel = (phone or "").strip()[:40]
    if tel:
        row.phone = tel
    row.active = True
    return row


def external_doctors():
    return (ExternalDoctor.query.filter_by(active=True)
            .order_by(ExternalDoctor.name).all())


def _line(row, lang):
    parts = [row.doctor_name(lang)]
    if row.doctor_specialty():
        parts.append(row.doctor_specialty())
    if row.external_doctor is not None and row.external_doctor.place:
        parts.append(row.external_doctor.place)
    return " — ".join(p for p in parts if p)


def refer_to_doctor(visit, reason, user=None, to_doctor=None, external=None,
                    on_rx=False, at=None):
    """A referral to one doctor: inside the clinic (``to_doctor``, a user
    who sees patients) or outside it (``external``, from the book). The
    caller commits."""
    if visit is None:
        raise ValueError("no visit")
    if (to_doctor is None) == (external is None):
        raise ValueError("one doctor")
    row = refer(visit.patient, reason, kind=DOCTOR, user=user, visit=visit, at=at)
    row.to_doctor_id = getattr(to_doctor, "id", None)
    row.external_doctor_id = getattr(external, "id", None)
    row.to_doctor, row.external_doctor = to_doctor, external
    row.on_rx = bool(on_rx)
    # The ordinary «sent to» column too, so every list that already shows
    # where a paper went shows this one without knowing about doctors.
    row.sent_to = _line(row, "ar")[:120]
    return row


def doctor_line(row, lang="ar"):
    """«د. فلان — التخصص — المكان», as the prescription and lists print it."""
    return _line(row, lang)


def for_visit(visit_id):
    """This visit's referrals to doctors, newest first."""
    return (_live(Referral.query.filter_by(visit_id=visit_id, kind=DOCTOR))
            .order_by(Referral.decided_at.desc(), Referral.id.desc()).all())


def on_paper(visit_id):
    """The ones the doctor asked to appear on this visit's prescription."""
    if not visit_id:
        return []
    return [r for r in for_visit(visit_id) if r.on_rx]


def to_me(user_id, limit=200):
    """Children referred to this doctor who have no answer yet — oldest
    first, like every waiting list."""
    return (_live(Referral.query.filter(Referral.kind == DOCTOR,
                                        Referral.to_doctor_id == user_id,
                                        Referral.feedback_at.is_(None)))
            .order_by(Referral.decided_at.asc()).limit(limit).all())


def open_for(patient_id, doctor_id):
    """What this child was referred to this doctor for and is still
    waiting on — shown when the doctor opens the child's visit."""
    if not (patient_id and doctor_id):
        return []
    return (_live(Referral.query.filter(Referral.kind == DOCTOR,
                                        Referral.patient_id == patient_id,
                                        Referral.to_doctor_id == doctor_id,
                                        Referral.feedback_at.is_(None)))
            .order_by(Referral.decided_at.asc()).all())


def booking(row):
    """The appointment the child has with the doctor it was referred to,
    made on or after the referral — ``None`` when nothing is booked yet."""
    from app.models import Appointment

    if row is None or row.to_doctor_id is None:
        return None
    return (Appointment.query
            .filter(Appointment.patient_id == row.patient_id,
                    Appointment.doctor_id == row.to_doctor_id,
                    Appointment.appt_date >= row.decided_at.date(),
                    Appointment.status.notin_(("cancelled", "no_show")))
            .order_by(Appointment.appt_date.asc()).first())


def counts():
    """للوحة: كام مستنية رد، وكام رد محدّش وقّع عليه."""
    return {"waiting": len(waiting()), "unsigned": len(unsigned()),
            "incomplete": len(incomplete())}
