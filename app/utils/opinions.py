"""الاستشارة والرأي التاني — `ACT.10` و`ACT.09`.

نية `ACT.10` بتسمّي أشكال الفشل بالنص، والملف ده بيجاوب عليهم واحد واحد:

* **«السبب مش مكتوب بوضوح»** → مطلوب عند الباب، الطلب من غيره مرفوض.
* **«من غير خلفية كافية»** → :func:`missing` بتقوله باسمه.
* **«رد متأخّر»** → :func:`overdue`، بمهلة العيادة.

**والمهلة إعداد**، لأن نص المعيار بيقول *within a **predefined** time
frame* — يعني المستشفى هي اللي بتعرّفها، والشاشة ساكتة لحد ما تكتبها.
"""
from datetime import datetime, timedelta

from app.extensions import db
from app.models.opinion import (CONSULTATION, KINDS, Opinion,
                                SECOND_OPINION, URGENCIES, required_for)

#: نفس شكل مهلة الأوامر الشفهية: رقم المستشفى بتقوله، وفاضي يعني ما
#: قالتش — وطول ما هو فاضي مفيش طلب بيتقال عليه إنه اتأخر.
TIMEFRAME_SETTING = "consultation_minutes"


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


def ask(patient, kind, reason, user=None, asked_of=None, background=None,
        urgency=None, admission=None, visit=None, at=None):
    """طلب رأي. المتصل بيعمل commit.

    ``reason`` مطلوب: النية بتسمّي «السبب مش مكتوب بوضوح» كشكل فشل
    بالنص، وطلب من غير سبب بيحطّ المستشار في نفس المكان اللي المعيار
    موجود علشان يطلّعه منه.
    """
    if patient is None:
        raise ValueError("no patient")
    if kind not in KINDS:
        raise ValueError("unknown kind")
    why = (reason or "").strip()
    if not why:
        raise ValueError("no reason")
    if urgency is not None and urgency not in URGENCIES:
        raise ValueError("unknown urgency")
    # والعجلة بند الاستشارة لوحدها — كتابتها على رأي تاني بتخلّي عمود
    # معناه «مش منطبق» يبان زي «محدّش قال».
    row = Opinion(patient_id=patient.id, kind=kind, reason=why,
                  admission_id=getattr(admission, "id", None),
                  visit_id=getattr(visit, "id", None),
                  requested_by_id=getattr(user, "id", None),
                  asked_of=(asked_of or "").strip()[:120] or None,
                  background=(background or "").strip() or None,
                  urgency=urgency if kind == CONSULTATION else None)
    if at is not None:
        row.requested_at = at
    db.session.add(row)
    return row


def describe(row, **fields):
    """بنود بتتكتب بعد الطلب. الحقل اللي ما اتبعتش ما بيتغيّرش."""
    if row is None:
        raise ValueError("no request")
    for name in ("background", "alternative"):
        if name in fields and fields[name] is not None:
            setattr(row, name, (fields[name] or "").strip() or None)
    if "asked_of" in fields and fields["asked_of"] is not None:
        row.asked_of = (fields["asked_of"] or "").strip()[:120] or None
    if "urgency" in fields and fields["urgency"] is not None:
        value = fields["urgency"]
        if value not in URGENCIES:
            raise ValueError("unknown urgency")
        if row.kind == CONSULTATION:
            row.urgency = value
    return row


def answer(row, text, user=None, name=None, at=None):
    """(هـ) الرد. المتصل بيعمل commit.

    **نص مطلوب.** دليل ٥ بيقول إن التبادل لازم يكون *comprehensive*،
    وصف بيقول «اترد عليه الساعة تلاتة» ومفيش كلام مش بيجاوب حاجة.
    """
    if row is None:
        raise ValueError("no request")
    body = (text or "").strip()
    if not body:
        raise ValueError("no response text")
    if row.responded_at is None:
        row.responded_at = at or datetime.utcnow()
    row.response = body
    # **واللي كتب غير اللي قال.** ``user`` هو اللي قاعد قدام الشاشة؛
    # لو كاتب اسم حد من بره، يبقى الرأي بتاع اللي بره وهو بيكتبه بس.
    # عمود واحد للاتنين كان بينسب رأي استشاري بره لدكتور جوّه.
    outside = (name or "").strip()[:120] or None
    row.recorded_by_id = getattr(user, "id", None)
    row.responded_by_name = outside
    row.responded_by_id = None if outside else getattr(user, "id", None)
    return row


def missing(row):
    """ناقص إيه من قايمة النوع ده — باسمه."""
    if row is None:
        return []
    # كل بنود القايمتين نصوص، فالفحص واحد: فاضي أو فراغات يعني ناقص.
    gaps = [name for name in required_for(row.kind)
            if not (getattr(row, name, None) or "").strip()]
    # **و(و) شرطية، مش بند دايماً مطلوب.** نصّها: *actions to be taken
    # **when** the hospital can't provide a second opinion* — ودليل ٤
    # بيقول إن الأهل بيتقالهم على البدايل **لما** ما ينفعش. فطلب رجع
    # برأي مش ناقصه «البديل»: البديل بند اللي ما جاش. عدّه دايماً كان
    # هيخلّي كل رأي تاني كامل يبان ناقص، وده بيعلّم اللي بيقرا إنه
    # يتجاهل القايمة.
    if row.kind == SECOND_OPINION and "alternative" in gaps and row.answered:
        gaps.remove("alternative")
    # والعكس: ما جاش رأي ومفيش بديل اتقال — ساعتها الاتنين ناقصين،
    # وده بالظبط الصف اللي المعيار عايز حد يشوفه.
    return gaps


def for_patient(patient_id, limit=50):
    if not patient_id:
        return []
    return (Opinion.query
            .filter(Opinion.patient_id == patient_id)
            .order_by(Opinion.requested_at.desc(), Opinion.id.desc())
            .limit(limit).all())


def waiting(limit=200):
    """طلبات محدّش رد عليها، أقدم الأول.

    وأقدم الأول لأن أطول واحد مستنّي هو اللي المعيار قلقان منه.

    **والشرط هنا زي `Opinion.answered` بالظبط: الوقت والنص مع بعض.**
    كان `responded_at IS NULL` وبس — يعني صف فيه وقت ونصّه فاضي كان
    بيختفي من القايمة وهو مش مردود عليه بحسب الخاصية. تعريفين لنفس
    الكلمة بيفرقوا أول ما صف يتكتب من استيراد أو تصليح في الداتابيز.
    """
    return (Opinion.query
            .filter(db.or_(Opinion.responded_at.is_(None),
                           Opinion.response.is_(None)))
            .order_by(Opinion.requested_at)
            .limit(limit).all())


def overdue(minutes=None, now=None, limit=200):
    """طلبات عدّت مهلة العيادة ولسه من غير رد — فاضية من غير رقم.

    **والمستعجل بياخد نفس المهلة هنا عن قصد.** المعيار بيطلب مهلة
    واحدة معرّفة، ومهلتين من عندنا هيبقوا رقمين البرنامج اخترعهم.
    العيادة اللي عايزة تفرّق بتكتب ده في سياستها، والشاشة بتقول
    **مستعجل** جنب السطر علشان اللي بيقرا يرتّب بنفسه.
    """
    minutes = minutes if minutes is not None else timeframe_minutes()
    if not minutes:
        return []
    edge = (now or datetime.utcnow()) - timedelta(minutes=minutes)
    return (Opinion.query
            .filter(db.or_(Opinion.responded_at.is_(None),
                           Opinion.response.is_(None)),
                    Opinion.requested_at < edge)
            .order_by(Opinion.requested_at)
            .limit(limit).all())


def incomplete(limit=200):
    """طلبات اترد عليها وناقصها بند من قايمتها — دليل ٥.

    وبعد الرد بس: طلب لسه مستنّي ناقصه الرد بالبداهة، وعدّه هنا بيخلط
    «لسه» بـ«ناقص» — وده بيغرق القايمة اللي المفروض تتقفل.
    """
    rows = (Opinion.query
            .filter(Opinion.responded_at.isnot(None),
                    Opinion.response.isnot(None))
            .order_by(Opinion.requested_at.desc())
            .limit(limit).all())
    return [{"record": r, "missing": missing(r)} for r in rows if missing(r)]
