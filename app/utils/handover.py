"""قراية وكتابة التسليم — GAHAR `ACT.08` / `GSR.04`.

الأدلة اللي البرنامج يقدر يشيلها:

* **دليل ٣** — تسليم بين الورديات في نفس القسم (:func:`hand_over`)، وبين
  قسمين (:func:`on_move`: أي نقل لسرير في قسم تاني بيفتح تسليم مستني
  القسم التاني يستلم).
* **دليل ٤** — موثّق بأداة ثابتة: الشكل اللي المستشفى اختارته
  (:data:`METHOD_SETTING`)، وكارت كل طفل متصوّر وقت التسليم.
* **دليل ٥** — المتابعة (:func:`report`): كام تسليم، كام ما اتستلمش،
  الوقت لحد الاستلام، الأسئلة، والأيام اللي اتسلّم فيها أقل من عدد
  الورديات **اللي المستشفى كتبته** — ومن غير الرقم ده البرنامج ما بيحكمش.

و«فرصة للسؤال والإجابة» اللي في نص البند: المستلم يسأل عن أي طفل،
واللي سلّم يرد، و**الاستلام ما بيتقفلش وفيه سؤال من غير رد** — سؤال
اتسأل ومحدّش رد عليه وبعدين اتمضى على الاستلام هو بالظبط سوء الفهم اللي
البند موجود علشانه.

**ومفيش حاجة بتستنى التسليم.** الطفل بيتنقل والدوا بيتدّي والوردية
بتتقفل؛ التسليم المفتوح بيبان على شاشة المتابعة، ما بيقفلش حاجة.
"""
import json
from datetime import datetime, time, timedelta

from app.extensions import db
from app.models.handover import (DISCIPLINES, MEDICAL, METHODS, NURSING,
                                 SEVERITIES, SHIFT, TRANSFER, Handover,
                                 HandoverItem)

#: الشكل لكل نوع تسليم: ``handover_method:medical`` و``:nursing``
#: و``:transfer``. فاضي = SBAR.
METHOD_SETTING = "handover_method:{}"
#: كام وردية في اليوم — **رقم المستشفى**. فاضي = التقرير بيعدّ وبس.
PER_DAY_SETTING = "handover_per_day:{}"
#: الأنواع اللي ليها إعداد شكل.
KINDS = DISCIPLINES + (TRANSFER,)


class HandoverError(ValueError):
    """رفض بمفتاح الشاشة تقدر تسمّيه (``handover.err_<key>``)."""


# ---- الإعدادات -----------------------------------------------------------
def method_for(kind):
    from app.models import Setting

    value = (Setting.get(METHOD_SETTING.format(kind)) or "").strip()
    return value if value in METHODS else "sbar"


def per_day(discipline):
    from app.models import Setting

    value = (Setting.get(PER_DAY_SETTING.format(discipline)) or "").strip()
    try:
        number = int(value)
    except ValueError:
        return None
    return number if number > 0 else None


def save_settings(methods, counts):
    from app.models import Setting

    for kind in KINDS:
        value = (methods.get(kind) or "").strip()
        Setting.set(METHOD_SETTING.format(kind),
                    value if value in METHODS else "sbar")
    for discipline in DISCIPLINES:
        raw = str(counts.get(discipline) or "").strip()
        number = int(raw) if raw.isdigit() and 0 < int(raw) <= 12 else None
        Setting.set(PER_DAY_SETTING.format(discipline),
                    str(number) if number else "")


# ---- مين بيستلم -----------------------------------------------------------
def may_receive(user, row):
    """تسليم الأطباء لطبيب، وتسليم التمريض لممرضة؛ والنقل لأي حد غير اللي نقل."""
    if user is None or row is None:
        return False
    if row.discipline == MEDICAL:
        return user.sees_patients(user.role, user.is_practitioner)
    if row.discipline == NURSING:
        return user.role == "nursing"
    return True


def default_discipline(user):
    return NURSING if getattr(user, "role", None) == "nursing" else MEDICAL


# ---- الأطفال -----------------------------------------------------------
def stays_in(unit_id=None):
    """الإقامات المفتوحة في القسم ده (أو في كل الأقسام)، بترتيب السرير."""
    from sqlalchemy.orm import selectinload

    from app.models.admission import Admission, BedStay
    from app.models.place import Bed, Space, Unit

    query = (Admission.query
             .join(BedStay, db.and_(BedStay.admission_id == Admission.id,
                                    BedStay.until.is_(None)))
             .join(Bed, BedStay.bed_id == Bed.id)
             .join(Space, Bed.space_id == Space.id)
             .join(Unit, Space.unit_id == Unit.id)
             .filter(Admission.discharged_at.is_(None))
             .options(selectinload(Admission.patient)))
    if unit_id:
        query = query.filter(Unit.id == unit_id)
    return query.order_by(Unit.sort_order, Unit.id, Space.sort_order,
                          Space.id, Bed.sort_order, Bed.id).all()


def _both(obj, attr="display_name"):
    if obj is None:
        return None
    fn = getattr(obj, attr)
    return {"ar": fn("ar"), "en": fn("en")}


def _iso(moment):
    return moment.isoformat(timespec="minutes") if moment else None


def cards(admissions, now=None):
    """``{admission_id: card}`` — كل اللي الملف بيعرفه، متجمّع مرة واحدة.

    الكارت dict بسيط يتحفظ JSON، بأسماء بالعربي والإنجليزي، علشان يتقرا
    بعد شهور زي ما اتقرا ساعتها وبأي لغة.
    """
    from app.models import Observation, VisitInvestigation
    from app.utils import discharge_summary, drug_round, lines, risks
    from app.utils import responsibility, stay_orders, vital_bands
    from app.utils.dosing import age_months_of

    now = now or datetime.utcnow()
    admissions = [a for a in admissions if a is not None]
    drugs = drug_round.for_admissions([a.id for a in admissions], now)
    out = {}
    for stay in admissions:
        patient = stay.patient
        bed = stay.bed
        unit = bed.space.unit if bed is not None and bed.space else None
        months = age_months_of(patient)
        latest = (Observation.query
                  .filter(Observation.patient_id == patient.id)
                  .order_by(Observation.taken_at.desc(),
                            Observation.id.desc()).first())
        readings = vital_bands.read(latest, months) if latest else {}
        worst = vital_bands.worst(latest, months)[0] if latest else None
        tests = [row for row in stay_orders.for_stay(stay)]
        waiting = [row for row in tests if row.status != "resulted"]
        unseen = [row for row in tests if row.critical_at is not None
                  and row.critical_seen_at is None]
        who = responsibility.current(stay.id)
        doctor = who.doctor if who is not None else stay.doctor
        meds = drugs.get(stay.id) or {"orders": []}
        days = ((now - stay.admitted_at).days if stay.admitted_at else None)
        out[stay.id] = {
            "name": {"ar": patient.display_name("ar"),
                     "en": patient.display_name("en")},
            "number": patient.patient_number,
            "dob": patient.date_of_birth.isoformat()
            if patient.date_of_birth else None,
            "age": list(patient.age_parts),
            "gender": patient.gender,
            "provisional": bool(getattr(patient, "identity_provisional",
                                        False)),
            "bed": _both(bed),
            "unit": _both(unit),
            "isolation": bool(bed is not None and bed.is_isolation),
            "admitted_at": _iso(stay.admitted_at),
            "days": days,
            "doctor": _both(doctor),
            "reason": stay.reason,
            "diagnoses": [_both(d, "display_title")
                          for d in discharge_summary.provisional_diagnoses(stay)],
            "allergies": (patient.allergies or "").strip() or None,
            "chronic": (patient.chronic_diseases or "").strip() or None,
            "lines": [{"kind": line.kind, "site": line.site,
                       "days": (now - line.inserted_at).days
                       if line.inserted_at else None}
                      for line in lines.map_for(patient.id)],
            "vitals_at": _iso(latest.taken_at) if latest else None,
            "vitals": {kind: [value, level]
                       for kind, (value, level) in readings.items()
                       if value is not None},
            "worst": worst,
            "risks_unassessed": list(risks.unassessed(risks.panel(stay))),
            "critical": [_both(row) for row in unseen],
            "tests": [{"name": _both(row), "status": row.status,
                       "urgent": bool(getattr(row, "urgent", False))}
                      for row in waiting],
            "meds": [{"name": entry["order"].label(),
                      "level": entry["state"]["level"],
                      "due_at": _iso(entry["state"]["due_at"])}
                     for entry in meds["orders"]
                     if entry["state"]["level"] in (drug_round.LATE,
                                                     drug_round.DUE)
                     or entry["state"]["due_at"] is not None],
            "pending": (who.pending if who is not None and who.handed_at
                        else None),
        }
    return out


def _snapshot(card):
    return json.dumps(card, ensure_ascii=False, default=str)


# ---- التسليم بين الورديات --------------------------------------------------
def open_for(unit_id, discipline):
    return (Handover.query
            .filter(Handover.occasion == SHIFT,
                    Handover.discipline == discipline,
                    Handover.unit_id.is_(None) if not unit_id
                    else Handover.unit_id == unit_id,
                    Handover.accepted_at.is_(None))
            .order_by(Handover.handed_at.desc()).first())


def last_for(unit_id, discipline):
    return (Handover.query
            .filter(Handover.occasion == SHIFT,
                    Handover.discipline == discipline,
                    Handover.unit_id.is_(None) if not unit_id
                    else Handover.unit_id == unit_id)
            .order_by(Handover.handed_at.desc(), Handover.id.desc()).first())


def hand_over(unit_id, discipline, user, notes=None, severities=None,
              offered_to=None, note=None, at=None):
    """الوردية بتسلّم القسم. كل طفل في القسم بيدخل التسليم — اللي اتكتب
    عنه واللي ما اتكتبش — لأن «الطفل ده ما اتقالش عليه حاجة» حقيقة
    المستلم محتاج يعرفها. المتصل بيعمل commit."""
    if discipline not in DISCIPLINES:
        raise HandoverError("discipline")
    if user is None:
        raise HandoverError("who")
    if open_for(unit_id, discipline) is not None:
        raise HandoverError("already_open")
    notes = notes or {}
    severities = severities or {}
    method = method_for(discipline)
    stays = stays_in(unit_id)
    if method == "ipass":
        missing = [s for s in stays
                   if (severities.get(s.id) or "") not in SEVERITIES]
        if missing:
            raise HandoverError("need_severity")
    row = Handover(occasion=SHIFT, discipline=discipline, method=method,
                   unit_id=unit_id or None, handed_by=user.id,
                   handed_at=at or datetime.utcnow(),
                   offered_to=getattr(offered_to, "id", offered_to) or None,
                   note=(note or "").strip() or None)
    db.session.add(row)
    built = cards(stays)
    for stay in stays:
        severity = severities.get(stay.id) or None
        row.items.append(HandoverItem(
            admission_id=stay.id, patient_id=stay.patient_id,
            snapshot=_snapshot(built[stay.id]),
            watch=(notes.get(stay.id) or "").strip() or None,
            severity=severity if severity in SEVERITIES else None))
    db.session.flush()
    return row


def withdraw(row, user):
    """اللي سلّم يرجّع تسليم محدّش استلمه — غلط فيه، أو سلّم القسم الغلط."""
    if row is None or not row.is_open:
        raise HandoverError("not_open")
    if user is None or user.id != row.handed_by:
        raise HandoverError("not_yours")
    db.session.delete(row)


def ask(item, text, user, at=None):
    text = (text or "").strip()
    if item is None or not item.handover.is_open:
        raise HandoverError("not_open")
    if not text:
        raise HandoverError("need_question")
    if user is None or user.id == item.handover.handed_by:
        raise HandoverError("own_question")
    item.question = text[:1000]
    item.asked_by = user.id
    item.asked_at = at or datetime.utcnow()
    item.answer = item.answered_by = item.answered_at = None
    return item


def answer(item, text, user, at=None):
    text = (text or "").strip()
    if item is None or not item.question:
        raise HandoverError("no_question")
    if not text:
        raise HandoverError("need_answer")
    if user is None or user.id == item.asked_by:
        raise HandoverError("own_answer")
    item.answer = text[:1000]
    item.answered_by = user.id
    item.answered_at = at or datetime.utcnow()
    return item


def accept(row, user, synthesis=False, at=None):
    """الطرف التاني استلم. **واللي سلّم ما يستلمش لنفسه** — نفس قاعدة
    `VerbalOrder` و`CareResponsibility`."""
    if row is None or not row.is_open:
        raise HandoverError("not_open")
    if user is None or user.id == row.handed_by:
        raise HandoverError("own_handover")
    if not may_receive(user, row):
        raise HandoverError("wrong_discipline")
    if row.open_questions:
        raise HandoverError("open_questions")
    if row.method == "ipass" and not synthesis:
        raise HandoverError("need_synthesis")
    row.accepted_by = user.id
    row.accepted_at = at or datetime.utcnow()
    row.synthesis = bool(synthesis) if row.method == "ipass" else None
    return row


# ---- التسليم بين قسمين -----------------------------------------------------
def on_move(admission, old_bed, new_bed, user=None, note=None, at=None):
    """طفل اتنقل لسرير في **قسم تاني** — تسليم مستني القسم ده يستلمه.

    نقل في نفس القسم مش تسليم: نفس الفريق ماسكه. والدخول الأول مش نقل:
    مفيش قسم سلّم. **والنقل نفسه ما بيستناش حد** — الطفل بيتنقل، والتسليم
    المفتوح بيبان.
    """
    if admission is None or old_bed is None or new_bed is None:
        return None
    old_unit = old_bed.space.unit_id if old_bed.space else None
    new_unit = new_bed.space.unit_id if new_bed.space else None
    if not old_unit or not new_unit or old_unit == new_unit:
        return None
    if user is None or getattr(user, "id", None) is None:
        return None
    row = Handover(occasion=TRANSFER, method=method_for(TRANSFER),
                   unit_id=new_unit, from_unit_id=old_unit,
                   handed_by=user.id, handed_at=at or datetime.utcnow())
    db.session.add(row)
    built = cards([admission]).get(admission.id) or {}
    # الإقامة لسه شايفة السرير القديم في الذاكرة؛ الكارت بيقول اللي اتنقل له.
    built["bed"] = _both(new_bed)
    built["unit"] = _both(new_bed.space.unit if new_bed.space else None)
    built["isolation"] = bool(new_bed.is_isolation)
    row.items.append(HandoverItem(
        admission_id=admission.id, patient_id=admission.patient_id,
        snapshot=_snapshot(built),
        watch=(note or "").strip() or None))
    return row


# ---- القرايات ------------------------------------------------------------
def waiting(limit=50):
    """التسليمات اللي محدّش استلمها — أقدم الأول."""
    return (Handover.query.filter(Handover.accepted_at.is_(None))
            .order_by(Handover.handed_at).limit(limit).all())


def for_admission(admission_id, limit=20):
    return (Handover.query.join(HandoverItem)
            .filter(HandoverItem.admission_id == admission_id)
            .order_by(Handover.handed_at.desc()).limit(limit).all())


def report(start, end):
    """دليل ٥ — ``{"groups": [...], "short_days": [...], "waiting": [...]}``.

    مجموعة لكل (قسم، نوع): العدد، اللي اتستلم، وسيط الدقايق لحد
    الاستلام، وأطولها، والأسئلة. و``short_days`` بس لنوع المستشفى كتبت
    له عدد ورديات.
    """
    from app.utils.clock import to_local, to_utc

    since = to_utc(datetime.combine(start, time.min))
    until = to_utc(datetime.combine(end, time.max))
    rows = (Handover.query
            .filter(Handover.handed_at >= since, Handover.handed_at <= until)
            .order_by(Handover.handed_at).all())
    groups = {}
    per_day_seen = {}
    for row in rows:
        kind = row.discipline or TRANSFER
        key = (row.unit_id or 0, kind)
        entry = groups.setdefault(key, {
            "unit": row.unit, "kind": kind, "count": 0, "accepted": 0,
            "minutes": [], "questions": 0, "method": set()})
        entry["count"] += 1
        entry["method"].add(row.method)
        if row.accepted_at is not None:
            entry["accepted"] += 1
            entry["minutes"].append(row.minutes_to_accept())
        entry["questions"] += sum(1 for item in row.items if item.question)
        if row.occasion == SHIFT:
            day = to_local(row.handed_at).date()
            per_day_seen[(row.unit_id or 0, kind, day)] = \
                per_day_seen.get((row.unit_id or 0, kind, day), 0) + 1
    out = []
    for entry in groups.values():
        minutes = sorted(entry.pop("minutes"))
        entry["median"] = minutes[len(minutes) // 2] if minutes else None
        entry["slowest"] = minutes[-1] if minutes else None
        entry["method"] = sorted(entry["method"])
        out.append(entry)
    out.sort(key=lambda e: (e["unit"].sort_order if e["unit"] else -1,
                            e["unit"].id if e["unit"] else 0, e["kind"]))

    # **والقسم اللي ما اتسلّمش خالص لازم يبان.** العدّ من الأقسام الشغّالة
    # مش من التسليمات اللي حصلت — وإلا القسم اللي محدّش سلّمه أبداً هو
    # بالظبط اللي مش هيظهر. وتسليم «كل الأقسام» بيتحسب لكل قسم.
    from app.models.place import Unit

    units = (Unit.query.filter(Unit.is_active.is_(True))
             .order_by(Unit.sort_order, Unit.id).all())
    short = []
    for discipline in DISCIPLINES:
        expected = per_day(discipline)
        if not expected:
            continue
        day = start
        while day <= end:
            everywhere = per_day_seen.get((0, discipline, day), 0)
            for unit in units:
                done = everywhere + per_day_seen.get(
                    (unit.id, discipline, day), 0)
                if done < expected:
                    short.append({"day": day, "unit": unit,
                                  "kind": discipline, "done": done,
                                  "expected": expected})
            day += timedelta(days=1)
    return {"groups": out, "short_days": short,
            "waiting": [r for r in waiting(200)
                        if since <= r.handed_at <= until]}
