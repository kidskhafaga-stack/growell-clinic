"""ناقص إيه من قايمة التخدير أو التسكين — GAHAR `SAS.18` و`SAS.23` و`SAS.24`.

تلات قوايم صريحة، ودي تاني مرة الكتاب بيعدّد محتويات سجل بالنص بعد قايمة
الطوارئ. والملف ده بيجاوب نفس السؤال اللي المراجِع فاتح الملف علشانه:
**البند ده متسجّل ولا لأ**، والقايمة المطلوبة بتتغيّر بنوع الحلقة.

**والوقت جزء من الحساب.** حاجات زي «حالته قبل ما يسيب المسرح» و«المآل»
بتتكتب وهو بيخرج — عدّها ناقصة وهو لسه على الترابيزة بيخلّي كل حالة شغّالة
تبان ملف ناقص، وبيعلّم اللي بيقرا إنه يتجاهل اللون.
"""
from datetime import datetime, timedelta

from app.extensions import db
from app.models.sedation import (ANAESTHESIA, DISPOSITIONS, KINDS,
                                 RECOVERY_ITEMS, SedationRecord,
                                 required_for)

#: نفس إعداد الدم والتقييد: كل قد إيه المفروض تتاخد قراية أثناء الحلقة.
#: `SAS.17` بيقول *"regularly according to the approved guidelines"* وما
#: بيدّيش رقم — فالعيادة هي اللي بتكتبه، والشاشة ساكتة لحد ما تكتبه.
INTERVAL_SETTING = "sedation_watch_minutes"


def interval_minutes():
    from app.models import Setting

    try:
        raw = (Setting.get(INTERVAL_SETTING) or "").strip()
    except Exception:                   # noqa: BLE001 — الإعدادات لسه
        return None
    try:
        minutes = int(raw)
    except (TypeError, ValueError):
        return None
    return minutes if minutes > 0 else None


def live(limit=100):
    """اللي لسه تحت التخدير أو في الإفاقة، الأقدم الأول.

    **الفلترة بتخلص في بايثون مش في الاستعلام**، لأن «خلصت» مش عمود:
    الحلقة اللي ليها عملية بتقرا وقتها من العملية، واللي راحت البيت من
    المسرح على طول عمرها ما هيتكتبلها وقت خروج من الإفاقة. الاستعلام
    بيجيب مجموعة أوسع مضمون إنها شاملة، والخاصية هي اللي بتقرر.
    """
    rows = (SedationRecord.query
            .filter(SedationRecord.recovery_left_at.is_(None))
            .order_by(SedationRecord.started_at)
            .limit(limit * 2).all())
    return [r for r in rows if not r.over][:limit]


def for_patient(patient_id, limit=50):
    if not patient_id:
        return []
    return (SedationRecord.query
            .filter(SedationRecord.patient_id == patient_id)
            .order_by(SedationRecord.started_at.desc(),
                      SedationRecord.id.desc())
            .limit(limit).all())


def readings(record_id):
    """القراءات اللي اتاخدت أثناء الحلقة دي، أقدم الأول — `SAS.17` دليل ٣."""
    from app.models import Observation

    return (Observation.query
            .filter(Observation.sedation_id == record_id)
            .order_by(Observation.taken_at)
            .all())


def last_reading(record_id):
    rows = readings(record_id)
    return rows[-1].taken_at if rows else None


def unwatched(minutes=None, now=None, limit=100):
    """حلقة شغّالة ومحدّش أخد قراية من كذا دقيقة — فاضية من غير رقم العيادة."""
    minutes = minutes if minutes is not None else interval_minutes()
    if not minutes:
        return []
    moment = now or datetime.utcnow()
    edge = moment - timedelta(minutes=minutes)
    out = []
    for row in live(limit):
        if row.started_at > edge:
            continue
        seen = last_reading(row.id)
        if seen is None or seen < edge:
            out.append({"record": row, "last": seen})
    return out


def _filled(value):
    return bool((value or "").strip()) if isinstance(value, str) else bool(value)


def missing(row):
    """أنهي بند من القايمة لسه ناقص، حسب نوع الحلقة."""
    if row is None:
        return []
    have = {
        "status": bool(readings(row.id)),
        "start": row.started_at is not None,
        "technique": _filled(row.technique),
        "score": _filled(row.score),
        "drugs": _filled(row.drugs),
        "fluids": row.fluids_in_ml is not None or row.fluids_out_ml is not None,
        "blood": _filled(row.blood_given),
        "event": _filled(row.unusual_event),
        "condition": _filled(row.condition_on_leaving),
        "disposition": _filled(row.disposition),
        "transfer": row.theatre_out is not None,
        "signature": row.signed_by_id is not None,
    }
    # وهو لسه في المسرح، البنود اللي بتتكتب وهو بيخرج مش ناقصة — دي
    # حاجات لسه ما جاش وقتها.
    #
    # **و«وقت النقل» في القايمتين ما بيبانش ناقص أبداً، وده مقصود.** الوقت
    # هو اللي بيقفل المرحلة: طول ما هو فاضي الطفل لسه جوّه فالبند ما جاش
    # وقته، وأول ما يتكتب البند اتعمل. يعني البند مضمون **بالبناء** مش
    # بالفحص — وده أقوى من فاحص، بس مكتوب هنا علشان اللي بيقرا ما يدوّرش
    # على حالة الفاحص ده بيمسكها.
    at_the_door = ("condition", "disposition", "transfer", "signature")
    gaps = [item for item in required_for(row.kind)
            if not have.get(item)
            and not (row.in_theatre and item in at_the_door)]
    if row.in_theatre:
        return gaps
    # ورعاية ما بعد التسكين بتبدأ من ساعة ما يوصل الإفاقة — `SAS.24`.
    if row.disposition and row.disposition != "recovery":
        return gaps                     # ما دخلش إفاقة أصلاً
    recovery = {
        "recovery_status": bool(readings(row.id)),
        "recovery_event": _filled(row.recovery_event),
        "recovery_score": _filled(row.recovery_score),
        "recovery_disposition": _filled(row.recovery_disposition),
        "recovery_transfer": row.recovery_out is not None,
        "recovery_signature": row.recovery_signed_by_id is not None,
    }
    if row.in_recovery:
        # لسه في الإفاقة: اللي بيتكتب وهو بيخرج منها لسه ما جاش وقته.
        leaving = ("recovery_score", "recovery_disposition",
                   "recovery_transfer", "recovery_signature")
        return gaps + [i for i in RECOVERY_ITEMS
                       if not recovery[i] and i not in leaving]
    return gaps + [i for i in RECOVERY_ITEMS if not recovery[i]]


def complete(row):
    """خلصت وما ناقصهاش حاجة.

    ``over`` مش ``not in_theatre``: طفل قاعد في الإفاقة لسه بنود بتتكتب
    عليه، وقول إن سجله كامل وهو لسه هناك بيقفل الملف بدري.
    """
    return row is not None and row.over and not missing(row)


def incomplete(limit=200):
    """حلقات خلصت وناقصها بند — الشغل اللي حد لازم يرجعله.

    ونفس سبب :func:`live`: «خلصت» خاصية مش عمود.
    """
    rows = (SedationRecord.query
            .order_by(SedationRecord.started_at.desc())
            .limit(limit).all())
    return [{"record": r, "missing": missing(r)}
            for r in rows if r.over and missing(r)]


def start(patient, kind, user=None, operation=None, admission=None,
          visit=None, at=None):
    """حلقة تخدير أو تسكين بدأت. المتصل بيعمل commit."""
    if patient is None:
        raise ValueError("no patient")
    if kind not in KINDS:
        raise ValueError("unknown kind")
    row = SedationRecord(patient_id=patient.id, kind=kind,
                         operation_id=getattr(operation, "id", None),
                         admission_id=getattr(admission, "id", None),
                         visit_id=getattr(visit, "id", None),
                         signed_by_id=getattr(user, "id", None))
    if at is not None:
        row.started_at = at
    db.session.add(row)
    return row


def describe(row, **fields):
    """البنود اللي بتتكتب أثناء الحلقة. المتصل بيعمل commit.

    **الحقل اللي ما اتبعتش ما بيتغيّرش.** حفظ جزء من الشاشة كان بيمسح
    الباقي، ودي الغلطة اللي وقعت في تعليمات المتابعة قبل كده: «الحقل مش
    موجود» و«الحقل اتفضّى» مش نفس الحاجة.
    """
    if row is None:
        raise ValueError("no record")
    for name in ("technique", "score", "drugs", "blood_given",
                 "unusual_event", "condition_on_leaving"):
        if name in fields and fields[name] is not None:
            value = (fields[name] or "").strip() or None
            setattr(row, name, value)
    for name in ("fluids_in_ml", "fluids_out_ml"):
        if name in fields and fields[name] is not None:
            setattr(row, name, fields[name])
    return row


def leave_theatre(row, disposition, condition=None, user=None, at=None):
    """ساب المسرح — (ح)–(ك) في التخدير، و(ز)–(ي) في التسكين.

    **ووقت واحد للحظة واحدة**: ده «وقت النقل» في قايمة التخدير و«وقت
    استلام المريض» في قايمة ما بعد التسكين.
    """
    if row is None:
        raise ValueError("no record")
    if disposition not in DISPOSITIONS:
        raise ValueError("unknown disposition")
    row.disposition = disposition
    # (ح) «حالته قبل ما يسيب المسرح» بتتكتب في نفس اللحظة دي بالنص — شاشة
    # تانية ليها كانت هتخلّيها البند اللي بيفضل فاضي في كل ملف.
    if condition is not None:
        row.condition_on_leaving = (condition or "").strip()[:200] or None
    moment = at or datetime.utcnow()
    # **اللحظة بتتكتب في مكان واحد.** لو الحلقة ليها عملية، `Operation`
    # عنده `recovery_at` من قبل السجل ده وشاشة الإفاقة بتقراه — فالكتابة
    # بتروحله، والسجل بيقراه. كتابتها في الاتنين كانت هتخلّيهم يختلفوا،
    # والشاشتين يقولوا وقتين مختلفين لنفس الخروجة.
    if row.operation is not None:
        from app.utils import recovery as room

        room.to_recovery(row.operation, user=user, at=moment)
    else:
        row.left_theatre_at = moment
    if user is not None:
        row.signed_by_id = user.id
        # اللحظة نفسها، مش العمود — العمود بيفضل فاضي لما يكون فيه عملية،
        # وساعتها السجل كان بيقول مين وقّع ومش بيقول إمتى.
        row.signed_at = moment
    return row


def leave_recovery(row, disposition, score=None, event=None, user=None,
                   at=None):
    """ساب الإفاقة — `SAS.24` (د)–(ز)."""
    if row is None:
        raise ValueError("no record")
    if disposition not in DISPOSITIONS:
        raise ValueError("unknown disposition")
    if row.theatre_out is None:
        # ما وصلش الإفاقة أصلاً. رفض بصوت أحسن من صف بيقول إنه ساب مكان
        # عمره ما دخله.
        raise ValueError("never reached recovery")
    row.recovery_disposition = disposition
    if score is not None:
        row.recovery_score = (score or "").strip()[:60] or None
    if event is not None:
        row.recovery_event = (event or "").strip() or None
    # **والخروجة من الإفاقة مش بتتاخد من هنا لما يكون فيه عملية.**
    # `recovery.discharge` بيرفض من غير قرار المتابعة عن قصد — علشان «مش
    # محتاج متابعة» و«محدّش سأل» ما يبقوش نفس الحاجة — وده قرار تاني خالص
    # غير بنود `SAS.24`. فالسجل بيكتب بنوده، والوقت بيقراه من العملية لما
    # الشاشة بتاعتها تصرف الطفل بقرارها. ولحد ما ده يحصل، `missing` بيقول
    # إن «وقت النقل» ناقص — وهو ناقص فعلاً.
    if row.operation is None:
        row.recovery_left_at = at or datetime.utcnow()
    if user is not None:
        row.recovery_signed_by_id = user.id
    return row


def kinds_note():
    """اللي بيفرق بين القايمتين، في مكان واحد علشان الشاشة تقراه."""
    return {ANAESTHESIA: ("technique", "blood"), "sedation": ("score",)}
