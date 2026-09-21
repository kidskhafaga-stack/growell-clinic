"""سجل الإنعاش، والرقم اللي الكتاب نفسه بيحطّه — GAHAR `CSS.05`.

الملف ده بيجاوب تلات أسئلة، والتلاتة بيتقروا من نفس التلات أوقات:

* **اتسجّل ولا لأ** — دليل ٦، وده اللي المراجِع بيفتح الملف علشانه.
* **الفريق وصل في قد إيه** — دليل ٣، والرقم (خمس دقايق) **مكتوب في
  المعيار**، مش عتبة بنخترعها ولا بنطلبها من العيادة.
* **وإيه اللي لسه شغّال دلوقتي** — لأن إنعاش مفتوح من ساعة مش سجل ناقص،
  ده إنعاش محدّش قفله، والاتنين شكلهم واحد على شاشة ما بتفرّقش.
"""
from datetime import datetime

from app.extensions import db
from app.models.resuscitation import ALS_MINUTES, OUTCOMES, Resuscitation

#: البنود اللي الملف بيثبتها، بحروفها في النص.
ELEMENTS = ("called", "team", "management", "outcome")


def running(limit=100):
    """إنعاش لسه مفتوح — الأقدم الأول."""
    return (Resuscitation.query
            .filter(Resuscitation.ended_at.is_(None))
            .order_by(Resuscitation.recognised_at)
            .limit(limit).all())


def for_patient(patient_id, limit=50):
    if not patient_id:
        return []
    return (Resuscitation.query
            .filter(Resuscitation.patient_id == patient_id)
            .order_by(Resuscitation.recognised_at.desc(),
                      Resuscitation.id.desc())
            .limit(limit).all())


def late_responses(limit=200):
    """الحالات اللي الفريق المتقدّم عدّى فيها الخمس دقايق.

    **الرقم من `CSS.05` دليل ٣**، والفلترة بتتعمل في بايثون مش في SQL
    عن قصد: طرح تاريخين في SQLite وPostgres مش نفس الجملة، والعدد هنا
    عدد حالات التوقّف في المستشفى — مش عدد المرضى.
    """
    rows = (Resuscitation.query
            .filter(Resuscitation.team_at.isnot(None))
            .order_by(Resuscitation.recognised_at.desc())
            .limit(limit).all())
    return [r for r in rows if r.late_team]


def never_answered(limit=200):
    """إنعاش محدّش سجّل إن الفريق وصل فيه.

    مش نفس «اتأخر»، وبيتعدّوا لوحدهم: اللي اتأخر فيه رقم، واللي مفيهوش
    وصول أصلاً مفيهوش رقم — وحطّه مع اللي في الميعاد بيخلّي حالة الفريق
    ما جاش فيها تبان سليمة.
    """
    return (Resuscitation.query
            .filter(Resuscitation.team_at.is_(None))
            .order_by(Resuscitation.recognised_at.desc())
            .limit(limit).all())


def missing(row):
    """أنهي بند لسه ناقص في السجل ده."""
    if row is None:
        return list(ELEMENTS)
    gaps = []
    if row.called_at is None:
        gaps.append("called")
    if row.team_at is None:
        gaps.append("team")
    if not (row.management or "").strip():
        gaps.append("management")
    if row.is_running:
        # النتيجة بتتكتب وهو بيخلص. عدّها ناقصة وهو شغّال بيخلّي كل إنعاش
        # جارٍ يبان ملف ناقص.
        return gaps
    if not (row.outcome or "").strip():
        gaps.append("outcome")
    return gaps


def start(patient, user=None, place=None, at=None, admission=None,
          visit=None):
    """توقّف اتعرف. المتصل بيعمل commit.

    **ومفيش حاجة تانية مطلوبة دلوقتي.** اللحظة دي اللي الناس بتجري فيها،
    وشاشة بتطلب عشر خانات قبل ما تفتح السجل هي شاشة هتتملّى بعد ساعة من
    الذاكرة — والأوقات اللي المعيار بيطلبها هي بالظبط اللي الذاكرة
    بتضيّعها.
    """
    if patient is None:
        raise ValueError("no patient")
    row = Resuscitation(patient_id=patient.id,
                        place=(place or "").strip()[:120] or None,
                        started_by_id=getattr(user, "id", None),
                        recorded_by_id=getattr(user, "id", None),
                        admission_id=getattr(admission, "id", None),
                        visit_id=getattr(visit, "id", None))
    if at is not None:
        row.recognised_at = at
    db.session.add(row)
    return row


def called(row, at=None):
    """الاستغاثة اتبعتت — (هـ). المتصل بيعمل commit."""
    if row is None:
        raise ValueError("no resuscitation")
    row.called_at = at or datetime.utcnow()
    return row


def team_arrived(row, lead=None, at=None):
    """الفريق وصل — (و). المتصل بيعمل commit."""
    if row is None:
        raise ValueError("no resuscitation")
    row.team_at = at or datetime.utcnow()
    if lead is not None:
        row.team_lead_id = lead.id
    return row


def finish(row, outcome, management=None, user=None, at=None):
    """خلص — النتيجة واللي اتعمل. المتصل بيعمل commit."""
    if row is None:
        raise ValueError("no resuscitation")
    if outcome not in OUTCOMES:
        raise ValueError("unknown outcome")
    row.outcome = outcome
    if management is not None:
        row.management = management.strip() or None
    row.ended_at = at or datetime.utcnow()
    if user is not None and row.recorded_by_id is None:
        row.recorded_by_id = user.id
    return row


def standard_minutes():
    """الخمس دقايق، من مكان واحد — علشان الشاشة والاختبار والقارئ يقولوا
    نفس الرقم، ولو الكتاب اتغيّر يتغيّر في مكان واحد."""
    return ALS_MINUTES
