"""الرفض المستنير — قراية وكتابة، `PCC.10`.

**السؤال اللي الملف ده موجود علشانه مش «مين رفض»**، ده البرنامج عارفه من
زمان: `self_discharge` في مآلات الطوارئ ومخارج الإقامة. السؤال هو **حد
قالهم إيه اللي ممكن يحصل؟** — ودليل ٢ بيطلب الأربعة كلهم في الاستمارة.

فأقوى قراية هنا مش قايمة الرفضات، دي :func:`undocumented`: **الأطفال اللي
خرجوا ضد النصيحة ومفيش لهم استمارة أصلاً**. دي كانت مستحيلة تتسأل قبل ده،
لأن الطرف التاني من المقارنة مكانش موجود.
"""
from datetime import datetime

from app.extensions import db
from app.models.refusal import ELEMENTS, KINDS, Refusal


def record(patient, kind, user=None, admission=None, visit=None,
           emergency_visit=None, explained_by=None, at=None, **fields):
    """استمارة رفض. المتصل بيعمل commit.

    **مش بترفض لو ناقصة.** الأربعة بيتكتبوا وقت ما حد يعرفهم، واللي
    بيقف قدام أهل ماشيين مش هيملا أربع خانات الأول — ورفض اتسجّل ناقص
    أحسن من رفض ما اتسجّلش. و:func:`missing` هي اللي بتقول ناقص إيه.
    """
    if patient is None:
        raise ValueError("no patient")
    if kind not in KINDS:
        raise ValueError("unknown kind")
    row = Refusal(patient_id=patient.id, kind=kind,
                  admission_id=getattr(admission, "id", None),
                  visit_id=getattr(visit, "id", None),
                  emergency_visit_id=getattr(emergency_visit, "id", None),
                  explained_by_id=getattr(explained_by, "id", None),
                  recorded_by_id=getattr(user, "id", None))
    if at is not None:
        row.at = at
    describe(row, **fields)
    db.session.add(row)
    return row


def describe(row, **fields):
    """بنود الاستمارة. المتصل بيعمل commit.

    **الحقل اللي ما اتبعتش ما بيتغيّرش** — «الحقل مش موجود» و«الحقل
    اتفضّى» مش نفس الحاجة، وحفظ جزء من الشاشة كان بيمسح الباقي.
    """
    if row is None:
        raise ValueError("no refusal")
    for name in ELEMENTS:
        if name in fields and fields[name] is not None:
            setattr(row, name, (fields[name] or "").strip() or None)
    for name in ("guardian_name", "guardian_relation", "guardian_id_no"):
        if name in fields and fields[name] is not None:
            setattr(row, name, (fields[name] or "").strip()[:120] or None)
    return row


def sign(row, kind, path=None, at=None):
    """الدليل إن اللي رفض شاف الورقة. نفس الاتنين بتوع `Consent`.

    ``paper`` توقيع على ورقة مطبوعة واتصوّرت — أقوى شكل. و``drawn``
    توقيع على الشاشة — أضعف، والسجل بيقول إنه أضعف بدل ما يخلطهم.
    """
    if row is None:
        raise ValueError("no refusal")
    if kind not in ("paper", "drawn"):
        raise ValueError("unknown signature kind")
    row.signature_kind = kind
    row.signature_file = path or row.signature_file
    row.signature_at = at or datetime.utcnow()
    return row


def missing(row):
    """ناقص إيه من الأربعة — باسمه، مش «ناقصة»."""
    if row is None:
        return []
    return [name for name in ELEMENTS
            if not (getattr(row, name) or "").strip()]


def for_patient(patient_id, limit=50):
    if not patient_id:
        return []
    return (Refusal.query
            .filter(Refusal.patient_id == patient_id)
            .order_by(Refusal.at.desc(), Refusal.id.desc())
            .limit(limit).all())


def incomplete(limit=200):
    """استمارات ناقصها بند من الأربعة — دليل ٢."""
    rows = (Refusal.query
            .order_by(Refusal.at.desc())
            .limit(limit).all())
    return [{"record": r, "missing": missing(r)} for r in rows if missing(r)]


def unsigned(limit=200):
    """استمارات محدّش وقّع عليها — دليل ٣ عايزها **في الملف**، وورقة فيها
    اسم من غير توقيع دعوى مش مستند."""
    return (Refusal.query
            .filter(Refusal.signature_file.is_(None))
            .order_by(Refusal.at.desc())
            .limit(limit).all())


def undocumented(limit=200):
    """**خرجوا ضد النصيحة ومفيش لهم استمارة أصلاً.**

    وده السؤال اللي المعيار موجود علشانه، واللي مكانش ينفع يتسأل قبل ما
    الاستمارة تبقى موجودة: البرنامج كان عارف إن الطفل مشي — `self_discharge`
    موجودة من زمان — وما كانش عنده الطرف التاني من المقارنة.

    بيرجّع ``{"what": ..., "row": ..., "patient": ...}`` علشان الشاشة
    تعرف توصّل لكل واحد فيهم.
    """
    from app.models import Admission, EmergencyVisit

    out = []
    covered_stays = {r.admission_id for r in Refusal.query
                     .filter(Refusal.admission_id.isnot(None)).all()}
    covered_er = {r.emergency_visit_id for r in Refusal.query
                  .filter(Refusal.emergency_visit_id.isnot(None)).all()}

    for stay in (Admission.query
                 .filter(Admission.outcome == "self_discharge")
                 .order_by(Admission.id.desc()).limit(limit).all()):
        if stay.id not in covered_stays:
            out.append({"what": "discharge", "row": stay,
                        "patient": stay.patient})
    # والطوارئ فيها حالتين: خرج بنفسه، ومشي من غير ما حد يشوفه — والتانية
    # أوحش، لأن محدّش حتى قابله علشان يقوله حاجة.
    for er in (EmergencyVisit.query
               .filter(EmergencyVisit.disposition.in_(
                   ("self_discharge", "left_unseen")))
               .order_by(EmergencyVisit.id.desc()).limit(limit).all()):
        if er.id not in covered_er:
            out.append({"what": "emergency", "row": er,
                        "patient": er.patient})
    return out[:limit]
