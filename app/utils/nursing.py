"""قراية `ICD.07` — التقييم اللي معظمه موجود أصلاً.

**الملف ده قارئ أكتر منه كاتب.** تلاتة من ستة بنود المعيار مكتوبين في
الملف من قبل ما التقييم ده يتعمل: العلامات والقياسات، وتقييم السقوط،
والفرز (ألم · فراش · تغذية). :func:`assembled` بتجمعهم **من مصدرهم**،
و:func:`missing` بتسأل عن اللي حد لازم يكتبه بس.

ونسخهم كان هيخلّي نسختين من كل قراءة — والنسخة اللي على الورقة دي هي
اللي هتقدم، لأن الممرضة بتحدّث العلامات مش الورقة.

---

**ومهلتين مش واحدة.** دليل ٣ بيقول *upon admission **within the
timeframe** identified in the policy*، ودليل ٤ بيقول *at the **frequency**
identified*. دول رقمين مختلفين بيوصفوا حاجتين مختلفتين، وواحد للاتنين
كان هيخلّي واحد منهم يختفي.

**والاتنين إعدادات، وساكتين لحد ما العيادة تكتبهم** — زي `ACT.10`
و`ICD.09` بالظبط: «محدّش عمله» بتبان من غير رقم، و«اتأخر» لأ.
"""
from datetime import datetime, timedelta

from app.extensions import db
from app.models.nursing import ABCDE, INITIAL, KINDS, NursingAssessment

#: دليل ٣ — كام ساعة بعد الدخول لازم التقييم الأول يتعمل فيها.
INITIAL_SETTING = "nursing_initial_hours"
#: دليل ٤ — كل كام ساعة يتعاد.
REASSESS_SETTING = "nursing_reassess_hours"


def _hours(key):
    from app.models import Setting

    try:
        raw = (Setting.get(key) or "").strip()
    except Exception:                   # noqa: BLE001 — الإعدادات لسه
        return None
    try:
        hours = int(raw)
    except (TypeError, ValueError):
        return None
    return hours if hours > 0 else None


def initial_hours():
    return _hours(INITIAL_SETTING)


def reassess_hours():
    return _hours(REASSESS_SETTING)


def record(admission, kind=INITIAL, user=None, at=None, **fields):
    """تقييم تمريض. المتصل بيعمل commit.

    بيرفض تقييم أول تاني على نفس الإقامة: «الأول» واحد بالتعريف، والتاني
    إعادة — وصفّين اسمهم «أول» بيخلّوا سؤال «اتعمل في وقته؟» مالوش
    إجابة واحدة.
    """
    if admission is None:
        raise ValueError("no admission")
    if kind not in KINDS:
        raise ValueError("unknown kind")
    if kind == INITIAL and initial_for(admission.id) is not None:
        raise ValueError("already has an initial assessment")
    row = NursingAssessment(patient_id=admission.patient_id,
                            admission_id=admission.id, kind=kind,
                            by_id=getattr(user, "id", None))
    for name in ABCDE + ("outputs", "focus"):
        value = fields.get(name)
        if value is not None:
            setattr(row, name, (value or "").strip() or None)
    if at is not None:
        row.at = at
    db.session.add(row)
    return row


def describe(row, **fields):
    """بنود بتتكتب بعدين. اللي ما اتبعتش ما بيتغيّرش."""
    if row is None:
        raise ValueError("no assessment")
    for name in ABCDE + ("outputs", "focus"):
        if fields.get(name) is not None:
            setattr(row, name, (fields[name] or "").strip() or None)
    return row


def missing(row):
    """ناقص إيه **من اللي حد لازم يكتبه** — بالاسم.

    (أ) و(ب) و(ج) مش هنا: دول بيتجمّعوا من الملف، و:func:`assembled`
    بتقول اللي ناقص منهم في مكانه.

    **و(هـ) مش بيتعدّ**: نصّها *(as relevant)*، وطفل مالوش مخرجات تتقاس
    ورقته كاملة. عدّها كان هيخلّي القايمة تصرخ على كل تقييم، واللي
    بيقراها يتعلّم يتجاهلها.
    """
    if row is None:
        return []
    gaps = [name for name in ABCDE
            if not (getattr(row, name, None) or "").strip()]
    if not (row.focus or "").strip():
        gaps.append("focus")
    return gaps


def initial_for(admission_id):
    return (NursingAssessment.query
            .filter_by(admission_id=admission_id, kind=INITIAL)
            .order_by(NursingAssessment.at).first())


def latest_for(admission_id):
    return (NursingAssessment.query.filter_by(admission_id=admission_id)
            .order_by(NursingAssessment.at.desc(),
                      NursingAssessment.id.desc()).first())


def history(admission_id, limit=50):
    return (NursingAssessment.query.filter_by(admission_id=admission_id)
            .order_by(NursingAssessment.at).limit(limit).all())


def assembled(admission):
    """(أ) و(ب) و(ج) — **من مصدرهم، وقت القراية**.

    بيرجّع لكل بند: موجود ولا لأ، والصف نفسه لما يكون موجود. واللي مش
    موجود بيتقال **باسمه** — ورقة ساكتة عن تقييم السقوط بتتقرا عند اللي
    بيراجعها «مفيش خطر»، وده مش نفس «محدّش قاس».
    """
    if admission is None:
        return {}
    from app.models import Measurement, Observation, RiskAssessment
    from app.utils import nutrition as food
    from app.utils import pain as _pain

    since = admission.admitted_at
    kid = admission.patient_id

    # **`taken_at` مش `recorded_at`** — الملاحظة نفسها بتقول الفرق:
    # الأول هو لما الترمومتر خرج، والتاني لما حد كتبه. وتقييم التمريض
    # بيتكلم عن حالة الطفل، مش عن لحظة الكتابة.
    vitals = (Observation.query
              .filter(Observation.patient_id == kid,
                      Observation.taken_at >= since)
              .order_by(Observation.taken_at.desc()).first())
    growth = (Measurement.query
              .filter(Measurement.patient_id == kid,
                      Measurement.code.in_(("height", "weight")))
              .order_by(Measurement.recorded_at.desc()).first())
    risks = {row.kind: row for row in
             RiskAssessment.query
             .filter(RiskAssessment.admission_id == admission.id).all()}
    screen = _pain.latest_screen(kid)
    diet = food.latest_assessment(kid)

    return {
        "vitals": vitals,                       # (أ)
        "growth": growth,                       # (أ)
        "fall": risks.get("fall"),              # (ب)
        "pressure": risks.get("pressure"),      # (ج)
        "pain": screen,                         # (ج)
        "nutrition": diet,                      # (ج)
    }


def assembled_gaps(admission):
    """أنهي بند من (أ)/(ب)/(ج) لسه مالوش صف في الملف."""
    found = assembled(admission)
    if not found:
        return []
    return [name for name, row in found.items() if row is None]


def _open_admissions():
    from app.models import Admission

    return (Admission.query.filter(Admission.discharged_at.is_(None))
            .order_by(Admission.admitted_at).all())


def without_initial(limit=50):
    """دليل ٣ — إقامة مفتوحة ومحدّش عمل لها تقييم تمريض أول.

    **بتشتغل من غير رقم العيادة**: تقييم محدّش عمله مايبقاش مخفي علشان
    المستشفى ما كتبتش مهلتها لسه.
    """
    out = []
    for stay in _open_admissions():
        if initial_for(stay.id) is None:
            out.append(stay)
            if len(out) >= limit:
                break
    return out


def late_initial(hours=None, now=None, limit=50):
    """اللي عدّى عليهم مهلة العيادة ولسه من غير تقييم أول. **ساكتة من
    غير الرقم.**"""
    window = hours if hours is not None else initial_hours()
    if not window:
        return []
    cutoff = (now or datetime.utcnow()) - timedelta(hours=window)
    return [stay for stay in without_initial(limit=limit)
            if stay.admitted_at <= cutoff]


def overdue_reassessment(hours=None, now=None, limit=50):
    """دليل ٤ — عدّى وقت الإعادة. **ساكتة من غير الرقم.**"""
    window = hours if hours is not None else reassess_hours()
    if not window:
        return []
    cutoff = (now or datetime.utcnow()) - timedelta(hours=window)
    out = []
    for stay in _open_admissions():
        last = latest_for(stay.id)
        if last is not None and last.at <= cutoff:
            out.append(stay)
            if len(out) >= limit:
                break
    return out


def incomplete(limit=50):
    """تقييم ناقص بند من (د) أو (و)."""
    rows = (NursingAssessment.query
            .order_by(NursingAssessment.at.desc()).limit(limit * 2).all())
    return [row for row in rows if missing(row)][:limit]


def counts():
    return {"without_initial": len(without_initial()),
            "late": len(late_initial()),
            "overdue": len(overdue_reassessment())}
