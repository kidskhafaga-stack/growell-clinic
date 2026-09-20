"""القايمة التمانية بتاعت الطوارئ، وناقص إيه منها — GAHAR `ICD.03(e)`.

الملف ده بيجاوب السؤال اللي المراجِع فاتح الملف علشانه، والقايمة معاه في
إيده: **البند ده متسجّل ولا لأ**.

وستّة من التمانية بيتقروا من حاجات موجودة خلاص — التقييم من `Visit`،
والرعاية من الخدمات والملاحظات، والتشخيص من `Diagnosis` — **وما بتتنسخش
هنا**. نسخة تانية من تشخيص هي نسختين بيفرقوا، والملف اللي فيه اتنين
مختلفين أسوأ من اللي فيه واحد.
"""
from app.extensions import db
from app.models.emergency_visit import (ARRIVALS, DISPOSITIONS,
                                        EmergencyVisit)

#: البنود التمانية بأرقامها في النص. الأرقام مش زينة — دي اللي المراجِع
#: بيدوس عليها، والشاشة بتعرضها بيها علشان الاتنين يبصّوا على نفس القايمة.
ITEMS = ("triage", "assessment", "care", "times", "disposition",
         "diagnosis", "condition", "followup")


def open_visits(limit=100):
    """اللي في القسم دلوقتي، الأقدم الأول.

    الأقدم الأول مش الأحدث: الطفل اللي قاعد من ساعتين هو اللي محدّش
    بصّله، وده السؤال اللي الشاشة موجودة علشانه.
    """
    return (EmergencyVisit.query
            .filter(EmergencyVisit.departed_at.is_(None))
            .order_by(EmergencyVisit.arrived_at)
            .limit(limit).all())


def for_patient(patient_id, limit=50):
    """حضور الطفل ده في الطوارئ، الأحدث الأول."""
    if not patient_id:
        return []
    return (EmergencyVisit.query
            .filter(EmergencyVisit.patient_id == patient_id)
            .order_by(EmergencyVisit.arrived_at.desc(),
                      EmergencyVisit.id.desc())
            .limit(limit).all())


def untriaged(limit=100):
    """وصلوا ومحدّش فرزهم لسه.

    دي الحاجة اللي الشاشة الحيّة بتاعت القسم ما بتقدرش تقولها، لأنها
    بتقرا الأسرّة — والطفل ده لسه ماخدش سرير ويمكن ما ياخدش.
    """
    return [v for v in open_visits(limit) if v.triaged_at is None]


def _has_assessment(visit_id):
    """البند ii — تقييم طبيب أو تمريض، ولو إعادة واحدة.

    بيتقرا من الزيارة نفسها: فحص مكتوب، أو علامات حيوية اتاخدت، أو قراية
    متابعة. تلاتتهم «حد بصّ على الطفل ده وكتب»، والواحدة منهم تكفي.
    """
    from app.models import Observation, VitalSigns, Visit

    if not visit_id:
        return False
    visit = db.session.get(Visit, visit_id)
    if visit is None:
        return False
    if (visit.clinical_exam or "").strip() or (visit.chief_complaint
                                               or "").strip():
        return True
    if VitalSigns.query.filter_by(visit_id=visit_id).first() is not None:
        return True
    return (Observation.query
            .filter(Observation.patient_id == visit.patient_id)
            .first() is not None)


def _has_care(visit_id):
    """البند iii — الرعاية اللي اتقدّمت: خدمة، دوا، أو خطة مكتوبة."""
    from app.models import Visit, VisitMedication, VisitService

    if not visit_id:
        return False
    visit = db.session.get(Visit, visit_id)
    if visit is None:
        return False
    if (visit.plan or "").strip():
        return True
    if VisitService.query.filter_by(visit_id=visit_id).first() is not None:
        return True
    return (VisitMedication.query.filter_by(visit_id=visit_id).first()
            is not None)


def _has_diagnosis(row):
    """البند vi — التشخيص أو الخلاصة عند انتهاء العلاج."""
    from app.models import Diagnosis

    query = Diagnosis.query.filter(Diagnosis.patient_id == row.patient_id)
    if row.visit_id:
        query = query.filter(Diagnosis.visit_id == row.visit_id)
    return query.first() is not None


def missing(row):
    """أنهي بند من التمانية لسه ناقص في الحضور ده.

    **والوقت بيدخل في الحساب.** بنود زي المآل وحالة المغادرة ما بتبقاش
    ناقصة على طفل لسه قاعد في القسم — دي حاجات بتتكتب وهو ماشي، وعدّها
    ناقصة وهو لسه جوّه بيخلّي كل ملف مفتوح يبان أحمر وبيعلّم اللي بيقرا
    إنه يتجاهل اللون.
    """
    if row is None:
        return list(ITEMS)
    gaps = []
    if row.triaged_at is None or not (row.level or "").strip():
        gaps.append("triage")
    if not _has_assessment(row.visit_id):
        gaps.append("assessment")
    if not _has_care(row.visit_id):
        gaps.append("care")
    if not _has_diagnosis(row):
        gaps.append("diagnosis")
    if row.is_open:
        # الوصول متسجّل بالضرورة (العمود مش nullable)، والمغادرة لسه
        # ما حصلتش — فمفيش حاجة ناقصة في الوقت لحد ما يمشي.
        return gaps
    if row.departed_at is None:
        gaps.append("times")
    if not (row.disposition or "").strip():
        gaps.append("disposition")
    if not (row.condition or "").strip():
        gaps.append("condition")
    if not (row.followup_instructions or "").strip():
        gaps.append("followup")
    return gaps


def complete(row):
    """الحضور ده كامل بمقياس `ICD.03(e)`؟"""
    return row is not None and not row.is_open and not missing(row)


def incomplete_departed(limit=200):
    """حضور خلص وناقصه بند — الشغل اللي حد لازم يرجعله.

    مفتوح؟ مش شغل: الطفل لسه جوّه. مقفول وناقص؟ ده ملف المراجِع هيفتحه
    ويلاقيه ناقص، والفرق بين الاتنين هو الفرق بين قايمة بيتشتغل عليها
    وقايمة بتتجاهل.
    """
    rows = (EmergencyVisit.query
            .filter(EmergencyVisit.departed_at.isnot(None))
            .order_by(EmergencyVisit.departed_at.desc())
            .limit(limit).all())
    return [{"visit": r, "missing": missing(r)} for r in rows if missing(r)]


def arrive(patient, user=None, arrival=None, visit=None, at=None):
    """طفل وصل القسم. المتصل بيعمل commit.

    **ومحتاج سرير؟ لأ.** ده السطر اللي الشغلانة دي كلها عليه: `beds.admit`
    بيرفض من غير سرير، والطفل اللي بيتعالج ويمشي من غير ما ياخد واحد كان
    بيختفي من السجل خالص.
    """
    if patient is None:
        raise ValueError("no patient")
    how = arrival or ARRIVALS[0]
    if how not in ARRIVALS:
        raise ValueError("unknown arrival")
    row = EmergencyVisit(patient_id=patient.id, arrival=how,
                         visit_id=getattr(visit, "id", None),
                         by_id=getattr(user, "id", None),
                         arrived_at=at)
    if at is None:
        # العمود ليه default؛ تمريره `None` صراحةً بيشغّله برضه، بس
        # السطر ده مكتوب علشان يبان إن ده مقصود.
        row.arrived_at = None
    db.session.add(row)
    return row


def triage(row, level=None, scale=None, urgent=None, note=None, user=None,
           at=None):
    """الفرز ومستواه — البند i. المتصل بيعمل commit.

    المستوى **بكلام المستشفى**، والبرنامج بيقرا `urgent` بس. وبيترفض
    فرز من غير مستوى: «اتفرز» من غير «طلع إيه» هو نص السطر اللي المعيار
    بيطلبه، وصف كده بيخلّي الملف يقول إن الفرز اتعمل وهو ما اتعملش.
    """
    from datetime import datetime

    if row is None:
        raise ValueError("no visit")
    if not (level or "").strip():
        raise ValueError("no level")
    row.level = level.strip()[:60]
    row.scale = (scale or "").strip()[:120] or None
    row.urgent = urgent
    row.triage_note = (note or "").strip() or None
    row.triaged_by_id = getattr(user, "id", None)
    row.triaged_at = at or datetime.utcnow()
    return row


def depart(row, disposition, condition=None, followup=None, user=None,
           at=None, admission=None):
    """الطفل مشي — البنود iv و v و vii و viii. المتصل بيعمل commit."""
    from datetime import datetime

    if row is None:
        raise ValueError("no visit")
    if disposition not in DISPOSITIONS:
        raise ValueError("unknown disposition")
    row.disposition = disposition
    row.condition = (condition or "").strip()[:200] or None
    row.followup_instructions = (followup or "").strip() or None
    row.departed_at = at or datetime.utcnow()
    if admission is not None:
        row.admission_id = admission.id
    if user is not None and row.by_id is None:
        row.by_id = user.id
    return row
