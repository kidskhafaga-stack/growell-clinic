"""مين مربوط دلوقتي، ومين أمره خلص وهو لسه مربوط — GAHAR `CSS.12`.

**السؤال التاني هو اللي الملف ده موجود علشانه.** البند (ز) بيقول إن تجديد
أمر التقييد بيبقى *"based on continuing needs"* — يعني الأمر بيخلص. وأمر
خلص والطفل لسه مربوط مش «ورقة ناقصة»: ده تقييد بقى **من غير إذن**، وبيعدّي
من غير ما حد يلاحظ لأن مفيش حاجة بتتغيّر على أي شاشة لما ساعة تعدّي.

والباقي بيتقرا من حاجات موجودة: المراقبة ملاحظات متعلّمة، والوقت مشتقّ من
تاريخين، ومفيش عمود حالة يقدر يخالف أي واحد فيهم.
"""
from datetime import datetime, timedelta

from app.extensions import db
from app.models.restraint import KINDS, Restraint

#: البنود اللي الملف هو اللي بيثبتها، بحروفها في النص.
ELEMENTS = ("order", "reason", "alternatives", "limit", "monitoring", "end")


def on_now(limit=200):
    """اللي مربوطين دلوقتي، الأقدم الأول."""
    return (Restraint.query
            .filter(Restraint.ended_at.is_(None))
            .order_by(Restraint.started_at)
            .limit(limit).all())


def for_patient(patient_id, limit=50):
    """تقييدات الطفل ده، الأحدث الأول."""
    if not patient_id:
        return []
    return (Restraint.query
            .filter(Restraint.patient_id == patient_id)
            .order_by(Restraint.started_at.desc(), Restraint.id.desc())
            .limit(limit).all())


def expired(now=None, limit=200):
    """**أمر خلص والتقييد لسه شغّال.**

    الشغلانة اللي الملف ده اتكتب علشانها. بتتقرا من الجدول مباشرة — مش
    بمسح كل الأطفال — فعيادة كبيرة بتدفع تمن اللي مربوطين بس.
    """
    moment = now or datetime.utcnow()
    return (Restraint.query
            .filter(Restraint.ended_at.is_(None),
                    Restraint.valid_until.isnot(None),
                    Restraint.valid_until < moment)
            .order_by(Restraint.valid_until)
            .limit(limit).all())


def no_limit_set(limit=200):
    """مربوط ومحدّش حطّ للأمر مدة.

    مش نفس اللي فوق، **وبيتعدّوا لوحدهم عن قصد**: أمر عدّى مدته حاجة حصلت
    ولازم تتصرّف فيها دلوقتي، وأمر من غير مدة أصلاً هو ورقة ناقصة من ساعة
    ما اتكتبت. خلطهم في رقم واحد بيخلّي الاتنين يتأجّلوا.
    """
    return (Restraint.query
            .filter(Restraint.ended_at.is_(None),
                    Restraint.valid_until.is_(None))
            .order_by(Restraint.started_at)
            .limit(limit).all())


def last_check(restraint_id):
    """آخر ملاحظة اتاخدت أثناء التقييد ده، أو ``None``."""
    from app.models import Observation

    row = (Observation.query
           .filter(Observation.restraint_id == restraint_id)
           .order_by(Observation.taken_at.desc(), Observation.id.desc())
           .first())
    return row.taken_at if row is not None else None


def unwatched(minutes=30, now=None, limit=200):
    """مربوط ومحدّش بصّ عليه من كذا دقيقة.

    **والرقم بييجي من العيادة مش من هنا.** المعيار (و) بيقول «مراقبة وإعادة
    تقييم» وما بيقولش كل قد إيه — وده مقصود منه، لأن الفترة بتختلف بنوع
    التقييد وبسن الطفل. فالدالة دي بتاخد الرقم، واللي بينده عليها بيجيبه
    من إعدادات العيادة.
    """
    moment = now or datetime.utcnow()
    edge = moment - timedelta(minutes=minutes)
    out = []
    for row in on_now(limit):
        if row.started_at > edge:
            continue            # لسه ما عدّاش الوقت من أول ما اتربط
        seen = last_check(row.id)
        if seen is None or seen < edge:
            out.append({"restraint": row, "last": seen})
    return out


def missing(row):
    """أنهي بند من اللي الملف بيثبتها لسه ناقص.

    والوقت بيدخل في الحساب زي الطوارئ: سبب الإنهاء ما بيبقاش ناقص على طفل
    **لسه مربوط** — دي حاجة بتتكتب وهو بيتفكّ.
    """
    if row is None:
        return list(ELEMENTS)
    gaps = []
    if row.ordered_by_id is None:
        gaps.append("order")
    if not (row.reason or "").strip():
        gaps.append("reason")
    if not (row.alternatives or "").strip():
        gaps.append("alternatives")
    if row.valid_until is None:
        gaps.append("limit")
    if last_check(row.id) is None:
        gaps.append("monitoring")
    if row.is_on:
        return gaps
    if not (row.ended_reason or "").strip():
        gaps.append("end")
    return gaps


def start(patient, kind, reason, ordered_by, method=None, alternatives=None,
          valid_until=None, applied_by=None, admission=None, visit=None,
          at=None, renews=None):
    """أمر تقييد جديد. المتصل بيعمل commit.

    بيترفض من غير **سبب** ومن غير **أمر طبيب**، لأن الاتنين دول نص البندين
    (أ) و(ب) — وصف من غير واحد فيهم بيخلّي الملف يقول إن التقييد اتعمل صح
    وهو مش عارف مين سمح بيه ولا ليه.
    """
    if patient is None:
        raise ValueError("no patient")
    if kind not in KINDS:
        raise ValueError("unknown kind")
    if not (reason or "").strip():
        raise ValueError("no reason")
    if ordered_by is None:
        raise ValueError("no order")
    row = Restraint(
        patient_id=patient.id, kind=kind, reason=reason.strip(),
        method=(method or "").strip()[:120] or None,
        alternatives=(alternatives or "").strip() or None,
        ordered_by_id=ordered_by.id,
        applied_by_id=getattr(applied_by, "id", None),
        admission_id=getattr(admission, "id", None),
        visit_id=getattr(visit, "id", None),
        valid_until=valid_until,
        renews_id=getattr(renews, "id", None))
    if at is not None:
        row.started_at = at
        row.ordered_at = at
    db.session.add(row)
    return row


def renew(row, ordered_by, valid_until=None, reason=None, at=None):
    """تجديد — **صف جديد**، والقديم بيتقفل. المتصل بيعمل commit.

    تمديد `valid_until` على نفس الصف كان هيمسح إن حد قرّر مرتين، والبند (ز)
    بيطلب إن التجديد يبقى قرار قايم بذاته مش تاريخ اتغيّر.
    """
    if row is None:
        raise ValueError("no restraint")
    fresh = start(row.patient, row.kind, reason or row.reason, ordered_by,
                  method=row.method, alternatives=row.alternatives,
                  valid_until=valid_until, at=at, renews=row)
    # المكان بيتنقل بالأرقام مش بعلاقات: التقييد بيخصّ الطفل، والإقامة أو
    # الزيارة تفصيلة فيه — وعلاقة اتعملت علشان سطر واحد هي علاقة هتفضل
    # محمّلة في كل استعلام تاني عمره ما احتاجها.
    fresh.admission_id = row.admission_id
    fresh.visit_id = row.visit_id
    end(row, ordered_by, reason="renewed", at=at)
    return fresh


def end(row, user=None, reason=None, at=None):
    """فكّ التقييد — البند (ط). المتصل بيعمل commit."""
    if row is None:
        raise ValueError("no restraint")
    if not row.is_on:
        return row
    row.ended_at = at or datetime.utcnow()
    row.ended_by_id = getattr(user, "id", None)
    row.ended_reason = (reason or "").strip()[:200] or None
    return row
