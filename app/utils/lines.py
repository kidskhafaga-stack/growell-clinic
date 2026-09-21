"""خريطة اللي مركّب في الطفل — `CSS.03`.

**الخريطة قراية مش جدول.** (د) بيطلب *catheter maps as part of handover
communications*، وخريطة متخزّنة كانت هتفرق عن الصفوف أول مرة حد ينسى
يحدّثها — وساعتها التسليم بيتقرا من الحاجة الغلط. فـ:func:`map_for` بتتحسب
من الصفوف كل مرة.

**وأهم قراية هنا مش الخريطة**، دي :func:`unlabelled_high_risk`: قسطرة
شريانية أو فوق الجافية من غير ملصق. النية بتقول العاقبة بالنص —
*"administration of the wrong material via the **wrong route**, resulting in
**grave consequences**"* — والملصق هو اللي بيمنعها.
"""
from datetime import datetime

from app.extensions import db
from app.models.line import HIGH_RISK, KINDS, Line, OTHER


def insert(patient, kind, user=None, site=None, size=None, label=None,
           kind_note=None, admission=None, visit=None, at=None):
    """قسطرة أو أنبوبة اتركّبت. المتصل بيعمل commit."""
    if patient is None:
        raise ValueError("no patient")
    if kind not in KINDS:
        raise ValueError("unknown kind")
    row = Line(patient_id=patient.id, kind=kind,
               admission_id=getattr(admission, "id", None),
               visit_id=getattr(visit, "id", None),
               inserted_by_id=getattr(user, "id", None),
               site=(site or "").strip()[:80] or None,
               size=(size or "").strip()[:20] or None,
               label=(label or "").strip()[:80] or None,
               kind_note=(kind_note or "").strip()[:80] or None)
    if at is not None:
        row.inserted_at = at
    db.session.add(row)
    return row


def label(row, text):
    """(ب) الملصق. المتصل بيعمل commit."""
    if row is None:
        raise ValueError("no line")
    row.label = (text or "").strip()[:80] or None
    return row


def remove(row, user=None, reason=None, at=None):
    """اتشالت. **لحظة مش مسح** — مدة بقائها سؤال الملف محتاج إجابته.

    ومرة واحدة: تاني ضغطة بتسيب أول لحظة، لأن الأولى هي اللي حصلت.
    """
    if row is None:
        raise ValueError("no line")
    if row.removed_at is None:
        row.removed_at = at or datetime.utcnow()
        row.removed_by_id = getattr(user, "id", None)
        row.removal_reason = (reason or "").strip()[:120] or None
    return row


def for_patient(patient_id, limit=100):
    """كل اللي اتركّب للطفل ده، أحدث الأول — اللي مركّب واللي اتشال."""
    if not patient_id:
        return []
    return (Line.query
            .filter(Line.patient_id == patient_id)
            .order_by(Line.inserted_at.desc(), Line.id.desc())
            .limit(limit).all())


def map_for(patient_id):
    """**خريطة القساطر** — اللي مركّب دلوقتي بس، أقدم الأول.

    أقدم الأول عن قصد: القسطرة اللي بقالها أطول هي اللي السؤال عليها في
    التسليم، مش آخر واحدة اتركّبت.
    """
    if not patient_id:
        return []
    return (Line.query
            .filter(Line.patient_id == patient_id,
                    Line.removed_at.is_(None))
            .order_by(Line.inserted_at)
            .all())


# **ومفيش `in_place()` تجيب كل اللي مركّب في المكان كله.** كتبتها
# بالتماثل مع باقي الوحدات، والحارس وقفها: `CSS.03` بيطلب **خريطة
# للطفل** (د) مش جرد للمبنى، ومفيش شاشة محتاجة القايمة دي — الممرضة
# بتبصّ على خريطة مريضها، ولوحة المتابعة بتبصّ على **اللي غلط** مش على
# كل حاجة مركّبة. مكتوبة هنا علشان حد ما يرجّعهاش بالتماثل تاني.


def unlabelled_high_risk(limit=200):
    """**قسطرة عالية الخطورة من غير ملصق** — `CSS.03` (ب).

    وده أخطر صف في الملف ده: النية بتقول إن الخطر هو دخول المادة الغلط
    من **الطريق الغلط**، والملصق هو اللي بيمنعه. وقايمة زي دي مكانش
    ينفع تتعمل من غير ما القساطر نفسها تبقى متسجّلة.
    """
    return [row for row in (Line.query
                            .filter(Line.removed_at.is_(None),
                                    Line.kind.in_(HIGH_RISK))
                            .order_by(Line.inserted_at)
                            .limit(limit).all())
            if not row.labelled]


def unnamed_other(limit=200):
    """نوع «تاني» ومحدّش كتب هو إيه.

    الخانة دي موجودة علشان العيادة تكتب اللي إحنا ما نعرفوش — وصف
    مكتوب فيه «تاني» وبس مش بيقول حاجة لحد بيقرا خريطة تسليم.
    """
    return [row for row in (Line.query
                            .filter(Line.removed_at.is_(None),
                                    Line.kind == OTHER)
                            .order_by(Line.inserted_at)
                            .limit(limit).all())
            if not (row.kind_note or "").strip()]


def still_in_after_discharge(limit=200):
    """قسطرة لسه مكتوبة «مركّبة» والطفل خرج.

    **وده سؤال مش اتهام.** يا إما حد نسي يسجّل الشيل، يا إما الطفل راح
    البيت وهي فيه فعلاً — والاتنين محتاجين حد يبصّ، والاتنين ما كانش
    ليهم شاشة.
    """
    from app.models import Admission

    rows = (db.session.query(Line, Admission)
            .join(Admission, Line.admission_id == Admission.id)
            .filter(Line.removed_at.is_(None),
                    Admission.discharged_at.isnot(None))
            .order_by(Line.inserted_at)
            .limit(limit).all())
    return [{"line": line, "stay": stay} for line, stay in rows]
