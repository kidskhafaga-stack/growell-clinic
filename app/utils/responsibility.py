"""قراية `ACT.07` — مين مسؤول، ومين كان مسؤول، ومين في النص.

تلات أسئلة، والتالت هو اللي محدّش كان بيسأله:

* **مين مسؤول دلوقتي؟** → :func:`current`.
* **مين كان مسؤول يوم كذا؟** → :func:`history` — ودي اللي عمود واحد
  عمره ما هيجاوبها.
* **ومين في النص؟** → :func:`in_limbo`: طبيب سلّم ومحدّش استلم.
  **وده أوحش نوع نقص**، لأن الصف بيبان إنه اتسلّم: فيه وقت، وفيه
  خطوات معلّقة مكتوبة، وفيه اسم اللي سلّم. اللي ناقصه إن التاني قال
  «خدتها» — والأول ماشي وهو فاكر إنها مشيت.

و:func:`without_mrp` هي الفراغ اللي المصفوفة سمّته: إقامة مفتوحة
ومحدّش مسؤول عنها خالص.
"""
from datetime import datetime

from app.extensions import db
from app.models.responsibility import CareResponsibility


def current(admission_id):
    """المسؤول دلوقتي، أو `None`."""
    return (CareResponsibility.query
            .filter_by(admission_id=admission_id, until=None)
            .order_by(CareResponsibility.since.desc(),
                      CareResponsibility.id.desc()).first())


def history(admission_id):
    """كل الفترات، **أقدم الأول** — ده سجل مش قايمة انتظار."""
    return (CareResponsibility.query
            .filter_by(admission_id=admission_id)
            .order_by(CareResponsibility.since, CareResponsibility.id).all())


def responsible_at(admission_id, moment):
    """مين كان مسؤول في اللحظة دي.

    **ودي السؤال اللي الجدول اتعمل علشانه.** عمود واحد بيتكتب فوقه
    بيجاوب «مين دلوقتي» وبس، والسؤال ده بيتسأل بعد شهور.
    """
    for row in history(admission_id):
        if row.since <= moment and (row.until is None or moment < row.until):
            return row
    return None


def assign(admission, doctor, user=None, at=None):
    """أول مسؤول، أو مسؤول لإقامة محدّش كان مسؤول عنها. المتصل بيعمل commit.

    بترفض لو فيه مسؤول حالي: نقل المسؤولية ليه باب تاني
    (:func:`hand_over`)، لأنه بيطلب الخطوات المعلّقة وتوقيع الطرفين.
    """
    if admission is None:
        raise ValueError("no admission")
    if doctor is None:
        raise ValueError("no doctor")
    if current(admission.id) is not None:
        raise ValueError("already has a responsible physician")
    row = CareResponsibility(admission_id=admission.id, doctor_id=doctor.id,
                             assigned_by_id=getattr(user, "id", None))
    if at is not None:
        row.since = at
    db.session.add(row)
    return row


def hand_over(admission, to_doctor, pending=None, user=None, at=None):
    """طبيب بيسلّم لطبيب. المتصل بيعمل commit.

    **والصف القديم ما بيتقفلش هنا.** بيتكتب عليه إنه سلّم والخطوات
    المعلّقة، وبيفضل **مفتوح** لحد ما التاني يستلم — لأن المسؤولية
    ما بتمشيش بكلام طرف واحد، وإقامة من غير مسؤول بين التوقيعين هي
    بالظبط الفراغ اللي المعيار موجود علشانه.
    """
    if admission is None:
        raise ValueError("no admission")
    if to_doctor is None:
        raise ValueError("no doctor")
    row = current(admission.id)
    if row is None:
        raise ValueError("nobody is responsible yet")
    if row.doctor_id == to_doctor.id:
        # تسليم لنفسه مش تسليم، وبيملا السجل بصفوف مالهاش معنى.
        raise ValueError("already responsible")
    if row.handed_at is not None:
        raise ValueError("already handed over")
    row.handed_at = at or datetime.utcnow()
    row.handed_by_id = getattr(user, "id", None) or row.doctor_id
    row.handed_to_id = to_doctor.id
    row.pending = (pending or "").strip() or None
    # **ومفيش صف جديد لسه.** صف مسؤولية موجود معناه مسؤولية قايمة
    # فعلاً؛ وكتابته دلوقتي بيخلّي دكتور يبقى مسؤول عن طفل من غير ما
    # يعرف — وده بالظبط سوء الفهم اللي المعيار موجود علشانه.
    return row


def accept(admission, doctor, user=None, at=None):
    """(د) الطرف التاني بيستلم. المتصل بيعمل commit.

    **واللي سلّم ما يقدرش يستلم لنفسه.** نفس قاعدة `VerbalOrder`: توقيع
    واحد على الطرفين مش تسليم، ده صف بيقول إن حاجة حصلت ومحدّش شافها.
    """
    if admission is None:
        raise ValueError("no admission")
    if doctor is None:
        raise ValueError("no doctor")
    row = current(admission.id)
    if row is None or row.handed_at is None:
        raise ValueError("nothing was handed over")
    if doctor.id == row.doctor_id:
        raise ValueError("the outgoing physician cannot accept")
    # **واللي استلم ممكن يكون غير اللي اتعرضت عليه** — ورديّة بتتغيّر.
    # السجل بيكتب الاتنين بدل ما يرفض: الرفض هنا كان هيخلّي التسليم
    # يتعمل بره البرنامج، والسجل يقول إن الأول لسه مسؤول.
    moment = at or datetime.utcnow()
    row.until = moment
    row.accepted_at = moment
    row.accepted_by_id = doctor.id
    nxt = CareResponsibility(admission_id=admission.id, doctor_id=doctor.id,
                             since=moment,
                             assigned_by_id=getattr(user, "id", None))
    db.session.add(nxt)
    return nxt


def _open_admissions():
    from app.models import Admission

    return (Admission.query.filter(Admission.discharged_at.is_(None))
            .order_by(Admission.admitted_at).all())


def without_mrp(limit=50):
    """إقامة مفتوحة ومحدّش مسؤول عنها.

    **والعمود القديم بيتحسب.** عيادة شغّالة عندها إقامات اتكتب فيها
    `Admission.doctor_id` قبل ما الجدول ده يبقى موجود، ودي مش ناقصة —
    عدّها كان هيملا الشاشة بصفوف اتعملت صح.
    """
    out = []
    for stay in _open_admissions():
        if current(stay.id) is None and stay.doctor_id is None:
            out.append(stay)
            if len(out) >= limit:
                break
    return out


def in_limbo(limit=50):
    """سلّم ومحدّش استلم — وأقدم واحد فوق."""
    rows = (CareResponsibility.query
            .filter(CareResponsibility.until.is_(None),
                    CareResponsibility.handed_at.isnot(None),
                    CareResponsibility.accepted_at.is_(None))
            .order_by(CareResponsibility.handed_at).limit(limit).all())
    return [row for row in rows if row.admission is not None
            and row.admission.is_open]


def counts():
    return {"without_mrp": len(without_mrp()), "in_limbo": len(in_limbo())}
