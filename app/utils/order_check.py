"""الطلب بيقول هو مين وليه — GAHAR `ICD.17`.

> Orders and requests represent communication from a medical staff member
> directing that service to be provided to the patient … Information includes
> at least:
> a) Name of the ordering medical staff members.
> b) Date and time of order.
> c) Patient identification, age, and sex.
> d) Clinical reason for ordering and requesting a service.
> e) Site and laterality for medical imaging studies.
> f) Prompt authentication by the ordering medical staff members.

وقبل ما يتكتب حاجة: **أربعة من الستة كانوا في السجل أصلاً**، ومش محتاجين
حد يكتبهم تاني.

* (ب) `created_at` — من يوم ما الجدول اتعمل.
* (ج) الطفل: رقمه، وتاريخ ميلاده، ونوعه — من ملفه.
* (أ) مين طلب — **دلوقتي من اللوج**؛ والصفوف القديمة بتقرا طبيب الزيارة
  وبتقول إنه اتقرا منها.
* (د) السبب — ملاحظة الطلب لو اتكتبت، **وإلا تشخيص الزيارة نفسها**. طبيب
  كاتب «التهاب رئوي» فوق وطالب «أشعة صدر» تحت كتب السبب فعلاً؛ إجباره
  يكتبه تاني في خانة الطلب هو بالظبط «الطبيب يكتب كتير». والبرنامج ما
  بيخترعش سبب: بيقرا كلام الطبيب نفسه.

والاتنين اللي كانوا ناقصين فعلاً:

* (هـ) **الناحية للأشعة** — ما كانتش موجودة خالص.
* (و) **التوثيق** — ما كانش ينفع يتقال لأن محدّش كان بيسجّل مين دخّل الطلب.

---

**وده قارئ مش حارس.** الطلب بيتقبل ناقص ويتقال إنه ناقص — نفس اختيار
`drug_round` و`closures`: مستشفى الساعة تلاتة الفجر بتطلب الأشعة، وبرنامج
بيرفض بيتلفّ حواليه بالورق. والحتة اللي بتقفل الفجوة على نفس السطر اللي
بيقولها: الناحية بتتختار هناك، والتأكيد زرار هناك.
"""
from datetime import datetime, timedelta

from app.extensions import db
from app.models import User, VisitInvestigation
from app.models.visit import SIDES

#: البنود بترتيب المعيار — والشاشة بتقراها بنفس الترتيب.
ELEMENTS = ("orderer", "when", "patient", "reason", "side", "authenticated")


def _sees_patients(user):
    return user is not None and User.sees_patients(user.role,
                                                   user.is_practitioner)


def orderer(row):
    """``(user, source)`` — ``source`` واحد من ``entered`` أو ``visit``.

    **وبيقول جاي منين**: الصف القديم مالوش حد دخّله، وطبيب الزيارة هو
    الأقرب — بس ده قراية مش شهادة، والشاشة بتكتبها كده.
    """
    if row.orderer is not None:
        return row.orderer, "entered"
    visit = row.visit
    if visit is not None and visit.doctor is not None:
        return visit.doctor, "visit"
    return None, None


def reason(row):
    """``(text, source)`` — الملاحظة، وإلا تشخيص الزيارة، وإلا ولا حاجة.

    التشخيص النهائي قبل المبدئي: لو الطبيب قفل الزيارة على تشخيص، ده اللي
    بيبرّر الطلب. **والبرنامج ما بيكتبش حاجة من عنده** — ده كلام الطبيب.
    """
    note = (row.request_notes or "").strip()
    if note:
        return note, "note"
    visit = row.visit
    if visit is not None and visit.diagnoses:
        final = [d.title for d in visit.diagnoses if d.dx_type == "final"]
        titles = final or [d.title for d in visit.diagnoses]
        titles = [t for t in titles if (t or "").strip()]
        if titles:
            return "، ".join(titles), "diagnosis"
    return None, None


def authenticated(row):
    """``True`` / ``False`` / ``None`` — **تلات حالات، مش اتنين.**

    ``None`` = الصف قديم ومحدّش سجّل مين دخّله، فمش معروف. ده مش «ناقص»:
    العدّ بيقول «ناقص» على حاجة اتعرف إنها ناقصة، مش على فراغ في تاريخ
    قبل ما السؤال يتسأل.
    """
    if row.orderer is None:
        return None
    if _sees_patients(row.orderer):
        return True
    return row.confirmed_at is not None


def missing(row):
    """أسامي البنود الناقصة، بترتيب :data:`ELEMENTS`."""
    out = []
    if orderer(row)[0] is None:
        out.append("orderer")
    if row.created_at is None:
        out.append("when")
    kid = row.patient
    if kid is None or kid.date_of_birth is None or not kid.gender:
        out.append("patient")
    if reason(row)[0] is None:
        out.append("reason")
    if row.kind == "imaging" and row.laterality not in SIDES:
        out.append("side")
    if authenticated(row) is False:
        out.append("authenticated")
    return out


def needs_confirmation(row):
    """اتكتب بلوج حد مش طبيب ومحدّش أكّده."""
    return authenticated(row) is False


def confirm(row, user):
    """الطبيب بيأكّد طلب حد تاني دخّله. المتصل بيعمل commit.

    **واللي دخّل الطلب ما يأكّدوش** — نفس قاعدة `VerbalOrder`: التوقيع
    علشان طبيب يقول «أيوه ده طلبي»، ولو اللي كتب هو اللي وقّع مبقاش فيه
    حد تاني قال حاجة.
    """
    if not _sees_patients(user):
        raise PermissionError("only a practitioner confirms an order")
    if row.ordered_by is not None and row.ordered_by == user.id:
        raise PermissionError("the person who entered it cannot confirm it")
    if row.confirmed_at is None:
        row.confirmed_by = user.id
        row.confirmed_at = datetime.utcnow()
        db.session.flush()
    return row


def set_side(row, side):
    """(هـ) — للأشعة بس، ومن :data:`SIDES` بس."""
    side = (side or "").strip()
    if row.kind != "imaging":
        raise ValueError("only imaging has a side")
    if side not in SIDES:
        raise ValueError("unknown side")
    row.laterality = side
    db.session.flush()
    return row


def incomplete(days=30, limit=500):
    """الطلبات الناقصة في آخر ``days`` يوم، الأحدث الأول — `ICD.17` دليل ٣.

    > 3. There is a process to evaluate the completeness and accuracy of
    > orders and requests.

    **استعلام واحد للطلبات وكل اللي بتقراه** — الزيارة وتشخيصاتها، والطفل،
    واللي دخّل، وطبيب الزيارة — علشان الشاشة ما تسألش مرة لكل طلب.
    """
    from sqlalchemy.orm import selectinload

    from app.models import Visit

    since = datetime.utcnow() - timedelta(days=days)
    rows = (VisitInvestigation.query
            .options(selectinload(VisitInvestigation.visit)
                     .selectinload(Visit.diagnoses),
                     selectinload(VisitInvestigation.visit)
                     .selectinload(Visit.doctor),
                     selectinload(VisitInvestigation.patient),
                     selectinload(VisitInvestigation.orderer))
            .filter(VisitInvestigation.created_at >= since)
            .order_by(VisitInvestigation.created_at.desc(),
                      VisitInvestigation.id.desc())
            .limit(limit).all())
    out = []
    for row in rows:
        gaps = missing(row)
        if gaps:
            out.append((row, gaps))
    return out
