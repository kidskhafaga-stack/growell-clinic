"""احتياجات الطفل وتفضيلاته — القراية والكتابة. GAHAR `PCC.12`.

الموديل بيقول ليه الاحتياج حقيقة عن الطفل مش عن زيارة؛ ده بيقول إزاي
بيتسأل، وإزاي بيتقري.

**تلات حالات، مش اتنين** — نفس الدرس اللي الملف بيتعلّمه في كل معيار:

* ``unasked`` — محدّش سأل. **دي اللي المعيار بيدوّر عليها**: دليل ١
  بيقول *identify*، ومحدّش سأل يعني محدّش حدّد.
* ``none`` — سألنا، ومفيش حاجة. إجابة حقيقية، ومش ناقصة.
* ``some`` — فيه احتياجات شغّالة.

قايمة فاضية لوحدها ما بتفرّقش بين الأولى والتانية، فاللي سأل ولقى مفيش
بيسيب ختم على الملف.
"""
from datetime import datetime

from app.extensions import db
from app.models import Patient, PatientNeed
from app.models.patient_need import KINDS

UNASKED, NONE, SOME = "unasked", "none", "some"


def current(patient):
    """الشغّال بس، الأحدث الأول."""
    return [need for need in patient.needs if need.is_current]


def state(patient):
    """``unasked`` / ``none`` / ``some`` — شوف دوكسترينج الموديول."""
    if current(patient):
        return SOME
    if patient.needs_asked_at is not None:
        return NONE
    return UNASKED


def _stamp(patient, user):
    patient.needs_asked_at = datetime.utcnow()
    patient.needs_asked_by = getattr(user, "id", None)


def add(patient, kind, text, user=None):
    """يسجّل احتياج، **وبيختم إن السؤال اتسأل**. المتصل بيعمل commit.

    احتياج من غير كلام بيترفض — ده بالظبط الفراغ اللي الجدول اتعمل علشانه.
    والنوع لازم يكون من أنواع المعيار الأربعة.
    """
    text = (text or "").strip()[:300]
    if not text:
        raise ValueError("a need needs words")
    if kind not in KINDS:
        raise ValueError("unknown kind")
    row = PatientNeed(patient_id=patient.id, kind=kind, text=text,
                      recorded_by=getattr(user, "id", None))
    db.session.add(row)
    _stamp(patient, user)
    db.session.flush()
    return row


def asked_none(patient, user=None):
    """«سألنا — مفيش». بيختم الملف ومش بيكتب صف.

    **وما بيمسحش احتياج شغّال**: لو فيه حاجة متسجّلة، «مفيش» غلط، والرفض
    أحسن من إن الزرار يمسح كلام الأسرة بصمت.
    """
    if current(patient):
        raise ValueError("there are needs on file")
    _stamp(patient, user)
    db.session.flush()
    return patient


def end(need, user=None, reason=None):
    """الاحتياج خلص — **بيتقفل مش بيتمسح**، والسبب معاه."""
    if need.ended_at is None:
        need.ended_at = datetime.utcnow()
        need.ended_by = getattr(user, "id", None)
        need.end_reason = (reason or "").strip()[:200] or None
        db.session.flush()
    return need


def unasked_stays():
    """أطفال داخلين دلوقتي **ومحدّش سألهم** — دليل ١ للإقامة.

    الإقامة هي المكان اللي الاحتياجات دي بتفرق فيه أكتر: الأكل، والنضافة،
    والمواعيد (دليل ٤ و٥). واستعلام واحد، مش سؤال لكل طفل.
    """
    from sqlalchemy.orm import selectinload

    from app.models import Admission

    stays = (Admission.query
             .options(selectinload(Admission.patient)
                      .selectinload(Patient.needs))
             .filter(Admission.discharged_at.is_(None))
             .all())
    return [stay for stay in stays
            if stay.patient is not None and state(stay.patient) == UNASKED]
