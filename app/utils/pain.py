"""قراية `ICD.09` — الفرز، والتقييم، وإعادة الفرز.

المعيار بيحطّ تلات كلمات في سطر واحد، والبرنامج كان عنده رقم واحد:

> Inpatients and outpatients are **screened** for pain, **assessed** whenever
> pain is present, and **managed** accordingly.

والملف ده بيجاوب على أربع أسئلة:

* **مين ما اتفرزش خالص؟** → :func:`unscreened_stays` — دليل ٣ بيقول
  *all inpatients and outpatients*.
* **مين طلع عنده ألم ومحدّش قيّمه؟** → :func:`positive_without_assessment`،
  **وده أوحش صف**: فيه أداة ورقم ووقت واسم — بيبان مكتمل.
* **وتقييم ناقص بند من الخمسة؟** → :func:`missing`، بالاسم.
* **ومين محدّش رجع له؟** → :func:`awaiting_reassessment`
  و:func:`overdue_reassessment`.

---

**ومفيش حدّ مخترع.** البرنامج ما بيحوّلش رقم الأداة لحكم «فيه ألم»: كل
أداة ليها مداها، و«٤ فأكتر» رقم إكلينيكي. اللي ماسك الأداة بيقراها ويقول،
والعمود بيسجّل قوله.

**والمهلة إعداد**، لأن (ج) بيقول *frequency of pain reassessments* —
يعني سياسة المستشفى. وزي `ACT.10` بالظبط: :func:`awaiting_reassessment`
بتشتغل من غير رقم (محدّش رجع خالص)، و:func:`overdue_reassessment` ساكتة
لحد ما العيادة تكتبه.
"""
from datetime import datetime, timedelta

from app.extensions import db
from app.models.pain import ELEMENTS, TOOL_DOMAIN, PainAssessment, PainScreen

#: نفس شكل مهلة الاستشارة والتقييد: رقم المستشفى بتقوله.
REASSESS_SETTING = "pain_reassess_hours"


def reassess_hours():
    from app.models import Setting

    try:
        raw = (Setting.get(REASSESS_SETTING) or "").strip()
    except Exception:                   # noqa: BLE001 — الإعدادات لسه
        return None
    try:
        hours = int(raw)
    except (TypeError, ValueError):
        return None
    return hours if hours > 0 else None


def tool_list():
    """أدوات العيادة. **فاضية لحد ما تكتبها.**"""
    from app.utils import lookups

    return lookups.options(TOOL_DOMAIN)


def screen(patient, has_pain, tool_key=None, score=None, user=None,
           visit=None, admission=None, observation=None, at=None):
    """فرز. المتصل بيعمل commit.

    ``has_pain`` **مطلوب صراحةً** — مش مستنتج من الرقم. ولو العيادة
    كتبت قايمة أدوات، الأداة مطلوبة: دليل ٣ بيقول *using a **valid and
    approved tool***، وفرز من غير أداة هو رأي مش فرز.
    """
    if patient is None:
        raise ValueError("no patient")
    if has_pain is None:
        raise ValueError("no answer")
    key = (tool_key or "").strip() or None
    tools = tool_list()
    if tools:
        if key is None:
            raise ValueError("no tool")
        if key not in {row.key for row in tools}:
            raise ValueError("unknown tool")
    row = PainScreen(patient_id=patient.id, has_pain=bool(has_pain),
                     tool_key=key, score=score,
                     visit_id=getattr(visit, "id", None),
                     admission_id=getattr(admission, "id", None),
                     observation_id=getattr(observation, "id", None),
                     by_id=getattr(user, "id", None))
    if at is not None:
        row.at = at
    db.session.add(row)
    return row


def assess(screen_row, user=None, at=None, **fields):
    """(ب) التقييم الكامل. المتصل بيعمل commit.

    بيرفض التقييم على فرز قال **مفيش ألم**: دليل ٤ بيقول إن التقييم
    بيتعمل *when pain is **identified from the screening***، وتقييم على
    فرز سالب بيخلّي «اتقيّم» تبقى كلمة مالهاش معنى في أي جرد.
    """
    if screen_row is None:
        raise ValueError("no screen")
    if not screen_row.has_pain:
        raise ValueError("the screening found no pain")
    if screen_row.assessment is not None:
        raise ValueError("already assessed")
    row = PainAssessment(patient_id=screen_row.patient_id,
                         screen_id=screen_row.id,
                         by_id=getattr(user, "id", None))
    for name in ELEMENTS:
        value = fields.get(name)
        if value is not None:
            setattr(row, name, (value or "").strip() or None)
    plan = fields.get("plan")
    if plan is not None:
        row.plan = (plan or "").strip() or None
    if at is not None:
        row.at = at
    db.session.add(row)
    return row


def describe(row, **fields):
    """بنود بتتكتب بعدين. اللي ما اتبعتش ما بيتغيّرش."""
    if row is None:
        raise ValueError("no assessment")
    for name in ELEMENTS:
        if fields.get(name) is not None:
            setattr(row, name, (fields[name] or "").strip() or None)
    if fields.get("plan") is not None:
        row.plan = (fields["plan"] or "").strip() or None
    return row


def missing(row):
    """ناقص إيه من الخمسة — **بالاسم**، وناقص الخطة كمان.

    الخطة بتتحسب معاهم لأن نص المعيار *assessed … **and managed
    accordingly***، وتقييم من غير خطة نص الجملة.
    """
    if row is None:
        return []
    gaps = [name for name in ELEMENTS
            if not (getattr(row, name, None) or "").strip()]
    if not row.managed:
        gaps.append("plan")
    return gaps


def for_patient(patient_id, limit=50):
    return (PainScreen.query.filter_by(patient_id=patient_id)
            .order_by(PainScreen.at.desc(), PainScreen.id.desc())
            .limit(limit).all())


def latest_screen(patient_id):
    return (PainScreen.query.filter_by(patient_id=patient_id)
            .order_by(PainScreen.at.desc(), PainScreen.id.desc()).first())


def positive_without_assessment(limit=50):
    """**اتفرز وطلع فيه ألم ومحدّش قيّمه.**

    الصف ده عنده كل حاجة: أداة، ورقم، ووقت، واسم — وأي جرد بيعدّ
    «الفرز» بيعدّه تمام. اللي ناقصه هو اللي المعيار بيسمّيه دليل ٤.

    **وأقدم الأول**: طفل عنده ألم من امبارح ومحدّش بصّ له أهم من واحد
    من نص ساعة.
    """
    rows = (PainScreen.query
            .outerjoin(PainAssessment,
                       PainAssessment.screen_id == PainScreen.id)
            .filter(PainScreen.has_pain.is_(True),
                    PainAssessment.id.is_(None))
            .order_by(PainScreen.at).limit(limit).all())
    return rows


def incomplete(limit=50):
    """تقييم ناقص بند من (ب) أو من غير خطة."""
    rows = (PainAssessment.query.order_by(PainAssessment.at.desc())
            .limit(limit).all())
    return [row for row in rows if missing(row)]


def _later_screen(row):
    """أول فرز بعد التقييم ده لنفس الطفل — **دي هي إعادة الفرز**.

    مخزّنة؟ لأ. إعادة الفرز مش نوع تاني من الصفوف، هي فرز تاني حصل
    بعدين — وعمود «اتعاد فرزه» كان هيبقى علامة حد لازم يفتكر يحطّها.
    """
    return (PainScreen.query
            .filter(PainScreen.patient_id == row.patient_id,
                    PainScreen.at > row.at)
            .order_by(PainScreen.at).first())


def awaiting_reassessment(limit=50):
    """اتقيّم ومحدّش رجع له خالص — **بيشتغل من غير رقم العيادة**."""
    rows = (PainAssessment.query.order_by(PainAssessment.at)
            .limit(limit * 4).all())
    out = [row for row in rows if _later_screen(row) is None]
    return out[:limit]


def overdue_reassessment(hours=None, now=None, limit=50):
    """عدّى وقت العيادة ومحدّش رجع له. **ساكتة من غير الرقم.**"""
    window = hours if hours is not None else reassess_hours()
    if not window:
        return []
    moment = now or datetime.utcnow()
    cutoff = moment - timedelta(hours=window)
    return [row for row in awaiting_reassessment(limit=limit)
            if row.at <= cutoff]


def unscreened_stays(limit=50):
    """دليل ٣ — *all inpatients*: إقامة مفتوحة ومحدّش فرزها خالص."""
    from app.models import Admission

    stays = (Admission.query.filter(Admission.discharged_at.is_(None))
             .order_by(Admission.admitted_at).all())
    out = []
    for stay in stays:
        seen = PainScreen.query.filter(
            PainScreen.patient_id == stay.patient_id,
            PainScreen.at >= stay.admitted_at).first()
        if seen is None:
            out.append(stay)
            if len(out) >= limit:
                break
    return out


def counts():
    return {"unassessed": len(positive_without_assessment()),
            "unscreened": len(unscreened_stays()),
            "awaiting": len(awaiting_reassessment())}
