"""الأوامر الشفهية والتليفونية — قراية وكتابة، `ICD.18`.

الملف ده بيجاوب التلات أسئلة اللي المراجِع بيفتح الملف علشانهم، وكل واحد
فيهم سؤال مختلف:

* اتقرا بصوت عالي؟ (ج)
* اللي قاله أكّده؟ (د)
* واتكتب في المهلة؟ (دليل ٤)

**وواحد منهم مش بيرد على التاني.** أمر اتقرا بصوت عالي ومحدّش أكّده لسه
أمر مفتوح، وأمر اتأكّد من غير قراية لسه ما عدّاش على الحاجة اللي النية
بتقول إنها بتمنع الغلط.
"""
from datetime import datetime, timedelta

from app.extensions import db
from app.models.verbal_order import CHANNELS, VerbalOrder

#: المهلة — دليل ٤ بيقول *"within a **predefined** timeframe"*، يعني
#: المستشفى هي اللي بتعرّفها. نفس شكل فترات المراقبة: فاضية يعني العيادة
#: ما قالتش، وطول ما هي فاضية مفيش أمر بيتقال عليه إنه اتأخر.
TIMEFRAME_SETTING = "verbal_order_minutes"


def timeframe_minutes():
    from app.models import Setting

    try:
        raw = (Setting.get(TIMEFRAME_SETTING) or "").strip()
    except Exception:                   # noqa: BLE001 — الإعدادات لسه
        return None
    try:
        minutes = int(raw)
    except (TypeError, ValueError):
        return None
    return minutes if minutes > 0 else None


def record(patient, text, received_by, channel="spoken", ordered_by=None,
           ordered_by_name=None, spoken_at=None, admission=None, visit=None,
           at=None):
    """أمر اتقال واتكتب — (ب). المتصل بيعمل commit.

    ``received_by`` مطلوب لأن (ب) بتقول *documented **by the receiver***:
    أمر شفهي مالوش مستلِم هو أمر محدّش مسؤول عنه.
    """
    if patient is None:
        raise ValueError("no patient")
    body = (text or "").strip()
    if not body:
        # أمر فاضي مش أمر. وصف بيقول «فيه أمر شفهي» من غير ما يقول إيه
        # هو بيجاوب إن فيه حاجة حصلت وما بيجاوبش المعيار.
        raise ValueError("no order text")
    if received_by is None:
        raise ValueError("no receiver")
    if channel not in CHANNELS:
        raise ValueError("unknown channel")
    written = at or datetime.utcnow()
    row = VerbalOrder(
        patient_id=patient.id, text=body, channel=channel,
        admission_id=getattr(admission, "id", None),
        visit_id=getattr(visit, "id", None),
        received_by_id=received_by.id,
        ordered_by_id=getattr(ordered_by, "id", None),
        ordered_by_name=(ordered_by_name or "").strip()[:120] or None,
        written_at=written,
        # ما اتقالش إمتى؟ يبقى اتقال ساعة ما اتكتب. الافتراض ده بيخلّي
        # المهلة صفر، وهي فعلاً صفر: مفيش تأخير نعرفه.
        spoken_at=spoken_at or written)
    db.session.add(row)
    return row


def read_back(row, user=None, at=None):
    """(ج) اتقرا بصوت عالي واللي قاله سمعه. المتصل بيعمل commit.

    مرة واحدة: تاني ضغطة بتسيب أول لحظة، لأن الأولى هي اللي حصلت فعلاً.
    """
    if row is None:
        raise ValueError("no order")
    if row.read_back_at is None:
        row.read_back_at = at or datetime.utcnow()
    return row


def confirm(row, user, at=None):
    """(د) اللي قال الأمر أكّده. المتصل بيعمل commit.

    **واللي أكّد لازم يكون غير اللي كتب.** المعيار بيقول *the ordering
    physician*، واللي استلم الأمر بيأكّد كتابته هو نفسه مش تأكيد — ده
    بالظبط اللي القراية بصوت عالي موجودة علشان تمسكه. رفض بصوت أحسن من
    صف بيقول إن الأمر اتأكّد وهو ما اتأكّدش.
    """
    if row is None:
        raise ValueError("no order")
    if user is None:
        raise ValueError("no confirming user")
    if user.id == row.received_by_id:
        raise ValueError("the receiver cannot confirm their own write-down")
    if row.confirmed_at is None:
        row.confirmed_at = at or datetime.utcnow()
        row.confirmed_by_id = user.id
    return row


def for_patient(patient_id, limit=50):
    if not patient_id:
        return []
    return (VerbalOrder.query
            .filter(VerbalOrder.patient_id == patient_id)
            .order_by(VerbalOrder.spoken_at.desc(), VerbalOrder.id.desc())
            .limit(limit).all())


def open_orders(limit=200):
    """اللي لسه ناقصه قراية أو تأكيد — الشغل اللي حد لازم يقفله.

    الاتنين في قايمة واحدة لأن الاتنين نفس الحاجة للي بيقرا: أمر شفهي
    لسه مفتوح. والشاشة بتقول **ناقصه إيه** بالظبط.
    """
    return (VerbalOrder.query
            .filter(db.or_(VerbalOrder.read_back_at.is_(None),
                           VerbalOrder.confirmed_at.is_(None)))
            .order_by(VerbalOrder.spoken_at)
            .limit(limit).all())


def missing(row):
    """ناقصه إيه من التلاتة — باسمه، مش «ناقص»."""
    if row is None:
        return []
    gaps = []
    if row.read_back_at is None:
        gaps.append("read_back")
    if row.confirmed_at is None:
        gaps.append("confirm")
    return gaps


def late(minutes=None, limit=200):
    """أوامر اتكتبت بعد المهلة — دليل ٤. فاضية من غير رقم العيادة.

    **والمهلة بتتقاس من ساعة ما اتقال لحد ما اتكتب**، مش لحد دلوقتي:
    الأمر اللي اتقال من ساعة ولسه ما اتكتبش مالوش صف أصلاً — مفيش صف
    يعني مفيش كتابة، وده اللي قايمة المراجعة بتشوفه من ناحية تانية.
    """
    minutes = minutes if minutes is not None else timeframe_minutes()
    if not minutes:
        return []
    edge = timedelta(minutes=minutes)
    rows = (VerbalOrder.query
            .order_by(VerbalOrder.spoken_at.desc())
            .limit(limit).all())
    return [r for r in rows if (r.written_at - r.spoken_at) > edge]
