"""التغذية — `ICD.13`.

**أقوى قراية هنا مش قايمة التقييمات ولا قايمة الأوامر.** دي
:func:`assessed_but_nothing_ordered`: طفل اتقيّم وطلع **محتاج نظام خاص**
ومحدّش كتبله أكل. النية بتقول إن التقييم *leads to a plan of care, or
intervention* — فتقييم ما أدّاش لحاجة مش سجل ناقص، ده **تقييم كامل محدّش
عمل بيه حاجة**، وده أسوأ لأنه بيبان مكتمل في أي جرد.

والتانية :func:`ordered_without_assessment`: أكل خاص اتكتب ومحدّش قيّم.
(ب) بيقول «معايير معرّفة لإشراك خدمات التغذية»، ونظام خاص من غير تقييم
يعني المعايير دي محدّش عدّى عليها.
"""
from datetime import datetime

from app.extensions import db
from app.models.nutrition import DIET_DOMAIN, DietOrder, NutritionAssessment


def diet_list(include_inactive=False):
    """قايمة الأنظمة الغذائية بتاعة العيادة — (د)(١).

    **بتبدأ فاضية عن قصد.** المعيار بيقول إن القايمة بتاعة المستشفى،
    و«حمية سكري» و«قليل الملح» مفردات إكلينيكية — اختراعها هنا نفس غلطة
    اختراع مقياس فرز.
    """
    from app.utils import lookups

    return lookups.options(DIET_DOMAIN, include_inactive=include_inactive)


def assess(patient, user=None, findings=None, needs=None, plan=None,
           admission=None, visit=None, at=None):
    """تقييم تغذية. المتصل بيعمل commit.

    ``needs`` بتلات حالات: ``None`` محدّش قال · ``False`` أكله عادي ·
    ``True`` محتاج نظام خاص.
    """
    if patient is None:
        raise ValueError("no patient")
    if needs is not None and not isinstance(needs, bool):
        raise ValueError("needs must be a three-state boolean")
    row = NutritionAssessment(
        patient_id=patient.id,
        admission_id=getattr(admission, "id", None),
        visit_id=getattr(visit, "id", None),
        assessed_by_id=getattr(user, "id", None),
        findings=(findings or "").strip() or None,
        needs_special_diet=needs,
        plan=(plan or "").strip() or None)
    if at is not None:
        row.at = at
    db.session.add(row)
    return row


def order(patient, diet_key, user=None, detail=None, meal_times=None,
          family_food=None, family_note=None, admission=None, visit=None,
          at=None):
    """أمر أكل — (د)(٣). المتصل بيعمل commit.

    ``diet_key`` **لازم يكون من قايمة العيادة**. مفتاح مش موجود معناه
    صف بيشاور على نظام محدّش عرّفه، وشاشة التسليم هتعرضه فاضي.
    """
    if patient is None:
        raise ValueError("no patient")
    key = (diet_key or "").strip()
    if not key:
        raise ValueError("no diet")
    if key not in {row.key for row in diet_list(include_inactive=True)}:
        raise ValueError("diet is not on the clinic's list")
    if family_food is not None and not isinstance(family_food, bool):
        raise ValueError("family_food must be a three-state boolean")
    row = DietOrder(
        patient_id=patient.id, diet_key=key,
        admission_id=getattr(admission, "id", None),
        visit_id=getattr(visit, "id", None),
        ordered_by_id=getattr(user, "id", None),
        detail=(detail or "").strip() or None,
        meal_times=(meal_times or "").strip()[:160] or None,
        family_food_allowed=family_food,
        family_food_note=(family_note or "").strip()[:200] or None)
    if at is not None:
        row.ordered_at = at
    db.session.add(row)
    return row


def stop(row, user=None, at=None):
    """الأمر وقف. **لحظة مش مسح** — الطفل كان على النظام ده فترة."""
    if row is None:
        raise ValueError("no order")
    if row.stopped_at is None:
        row.stopped_at = at or datetime.utcnow()
        row.stopped_by_id = getattr(user, "id", None)
    return row


def assessments_for(patient_id, limit=50):
    if not patient_id:
        return []
    return (NutritionAssessment.query
            .filter(NutritionAssessment.patient_id == patient_id)
            .order_by(NutritionAssessment.at.desc(),
                      NutritionAssessment.id.desc())
            .limit(limit).all())


def orders_for(patient_id, limit=50):
    if not patient_id:
        return []
    return (DietOrder.query
            .filter(DietOrder.patient_id == patient_id)
            .order_by(DietOrder.ordered_at.desc(), DietOrder.id.desc())
            .limit(limit).all())


def current_diet(patient_id):
    """اللي الطفل عليه دلوقتي، أو ``None``."""
    if not patient_id:
        return None
    return (DietOrder.query
            .filter(DietOrder.patient_id == patient_id,
                    DietOrder.stopped_at.is_(None))
            .order_by(DietOrder.ordered_at.desc(), DietOrder.id.desc())
            .first())


def latest_assessment(patient_id):
    rows = assessments_for(patient_id, limit=1)
    return rows[0] if rows else None


def assessed_but_nothing_ordered(limit=200):
    """**اتقيّم ومحتاج نظام خاص ومحدّش كتبله أكل.**

    ودي الحقيقة اللي المعيار موجود علشانها: *the assessment leads to a
    plan of care, or intervention*. تقييم ما أدّاش لحاجة **بيبان مكتمل**
    في أي جرد — مفيش خانة فاضية فيه — علشان كده محتاج قراية بتشوفه.
    """
    out, seen = [], set()
    rows = (NutritionAssessment.query
            .filter(NutritionAssessment.needs_special_diet.is_(True))
            .order_by(NutritionAssessment.at.desc())
            .limit(limit * 2).all())
    for row in rows:
        # أحدث تقييم للطفل هو اللي بيحكم — واحد قديم قال «محتاج» واتعالج
        # بعده مش نقص.
        if row.patient_id in seen:
            continue
        seen.add(row.patient_id)
        if latest_assessment(row.patient_id) is not row:
            continue
        if current_diet(row.patient_id) is None:
            out.append(row)
    return out[:limit]


def ordered_without_assessment(limit=200):
    """أكل خاص شغّال ومحدّش قيّم الطفل — (ب).

    «معايير معرّفة لإشراك خدمات التغذية»، ونظام خاص من غير تقييم يعني
    المعايير دي محدّش عدّى عليها.
    """
    out = []
    for row in (DietOrder.query
                .filter(DietOrder.stopped_at.is_(None))
                .order_by(DietOrder.ordered_at)
                .limit(limit).all()):
        if latest_assessment(row.patient_id) is None:
            out.append(row)
    return out


def unanswered_family_food(limit=200):
    """أمر شغّال ومحدّش قال أكل الأهل مسموح ولا لأ — (هـ).

    **وممنوع غير محدّش سأل.** التانية هي اللي بتحصل لما الأهل يجيبوا
    أكل ومحدّش يقول حاجة، وهي اللي المعيار عايز عملية ليها.
    """
    return (DietOrder.query
            .filter(DietOrder.stopped_at.is_(None),
                    DietOrder.family_food_allowed.is_(None))
            .order_by(DietOrder.ordered_at)
            .limit(limit).all())
