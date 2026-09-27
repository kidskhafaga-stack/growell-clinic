"""البيانات التجريبية — **على الأقسام المفتوحة**، قسم قسم.

اتطلبت كده: *«بيبص على الأقسام المفتوحة ويتعامل عليها، يحمّل فيها بيانات
تجريبية لاختبارها»*. قبلها كان الزرع حاجة واحدة ثابتة: عيادة، ومعاها
مستشفى صغيّرة **حتى في عيادة ما عندهاش أسرّة**، ولا حاجة لأي قسم تاني.

دلوقتي:

* **كل قسم ليه زرعه**، بيتحمّل بس لو القسم مفتوح (``module_enabled``) —
  والعيادة الأول، لأن كل قسم بيتبني على مرضاها.
* **كل قسم بيتسجّل لوحده في الكشف** (``demo_trace``) — فـ«امسح التجريبية
  بس» بيشيل اللي اتحمّل في أي قسم، مهما اتحمّل إمتى.
* **قسم اتفتح بعدين ياخد نصيبه بعدين**: «حمّل للأقسام اللي لسه مالهاش»
  بيحمّل للقسم الجديد بس، وما بيكرّرش العيادة.
* **وكل زرع بيعدّي من أدوات البرنامج نفسها** — الويزارد اللي بيبني العنابر،
  والدخول، وأوامر الدوا، وحجز العمليات، وجدول النوبتجيات — مش صفوف مكتوبة
  بإيد. زرع بيبني عنبر بطريقة تانية غير البرنامج كان هيبوظ من غير ما حد
  ياخد باله.

قسم مالقاش حاجة يتبني عليها — صيدلية العنابر من غير طفل داخل مثلاً —
**ما بيتعلّمش إنه اتحمّل**، فلما الأسرّة تتفتح بعدين بياخد نصيبه.
"""
from datetime import datetime, time, timedelta

from app.extensions import db
from app.models import Setting
from app.utils.clock import local_today

#: الأقسام اللي اتحمّلت، مفصولة بفصلة.
SEEDED = "demo_sections"


def _enabled(module):
    from app.utils.facility import module_enabled

    try:
        return module_enabled(module)
    except Exception:                               # noqa: BLE001
        return False


# ------------------------------------------------------------ helpers ----
def _demo_ids(table):
    from app.utils import demo_trace

    return demo_trace.manifest().get(table, [])


def _demo_patients(limit=None):
    from app.models import Patient

    ids = _demo_ids("patients")
    if not ids:
        return []
    rows = (Patient.query.filter(Patient.id.in_(ids), Patient.is_active)
            .order_by(Patient.id).all())
    return rows[:limit] if limit else rows


def _demo_admissions():
    from app.models import Admission

    ids = _demo_ids("admissions")
    if not ids:
        return []
    return (Admission.query.filter(Admission.id.in_(ids),
                                   Admission.discharged_at.is_(None))
            .order_by(Admission.id).all())


def _doctor():
    from app.utils.demo import _doctor as demo_doctor

    return demo_doctor()


# ------------------------------------------------------------ sections ----
def _clinic():
    from app.utils.demo import seed_clinic

    return seed_clinic()


#: الأقسام اللي عندها سرير، وإيه اسمها عند الويزارد.
_DEPARTMENTS = (("emergency", "emergency_care"), ("icu", "icu"),
                ("nicu", "nicu"), ("ward", "ward"))


def _wards():
    """الأقسام المفتوحة بس — عيادة فاتحة العناية لوحدها ما بتتبنيش لها
    حضّانات — وطفلين داخلين."""
    from app.utils.demo import seed_ward

    caps = [cap for module, cap in _DEPARTMENTS if _enabled(module)]
    made = seed_ward(_demo_patients(2), caps=caps or ["ward"])
    return None if made.get("skipped") else made


def _observations():
    """أوامر علامات حيوية للأطفال الداخلين — أو لطفلين من العيادة لو مفيش
    حد داخل."""
    from app.models import ObservationOrder

    who = [a.patient for a in _demo_admissions()] or _demo_patients(2)
    if not who:
        return None
    doctor = _doctor()
    for kid, every in zip(who[:2], (60, 240)):
        db.session.add(ObservationOrder(
            patient_id=kid.id, every_minutes=every,
            reason="متابعة حرارة وتنفّس",
            started_at=datetime.utcnow(), ordered_by=doctor.id))
    return {"orders": min(2, len(who))}


def _labs():
    """تلات طلبات تحليل: واحد مستني العيّنة، وواحد اتسحب، وواحد نتيجته
    طلعت — علشان كل عمود على بنش المعمل يبان."""
    from app.models import Investigation, Visit, VisitInvestigation
    from app.utils import labs

    doctor = _doctor()
    kids = _demo_patients(3)
    if not kids:
        return None
    test = (Investigation.query.filter_by(kind="lab", is_active=True).first()
            or Investigation(name_ar="صورة دم كاملة", name_en="CBC",
                             kind="lab", is_active=True))
    db.session.add(test)
    db.session.flush()
    rows = []
    for kid in kids:
        visit = (Visit.query.filter_by(patient_id=kid.id)
                 .order_by(Visit.id.desc()).first())
        if visit is None:
            visit = Visit(patient_id=kid.id, doctor_id=doctor.id,
                          visit_date=local_today(), status="open",
                          chief_complaint="حرارة")
            db.session.add(visit)
            db.session.flush()
        row = VisitInvestigation(
            visit_id=visit.id, patient_id=kid.id, investigation_id=test.id,
            kind="lab", name=test.name_ar, name_en=test.name_en,
            status="requested", ordered_by=doctor.id)
        db.session.add(row)
        db.session.flush()
        rows.append(row)
    if len(rows) > 1:
        labs.collect(rows[1], user=doctor)
    if len(rows) > 2:
        labs.collect(rows[2], user=doctor)
        labs.record(rows[2], value=11.8, unit="g/dL", low=11.0, high=14.5,
                    user=doctor)
    return {"orders": len(rows)}


def _pharmacy():
    """أوامر دوا للأطفال الداخلين، ومراجعة صيدلي على واحد منهم. من غير طفل
    داخل مفيش شغل صيدلية عنابر — والقسم بيستنى الأسرّة."""
    from app.utils import clinical_pharmacy, drug_round

    stays = _demo_admissions()
    if not stays:
        return None
    doctor = _doctor()
    orders = 0
    for stay, drugs in zip(stays, (("سيفترياكسون", "باراسيتامول"),
                                   ("أموكسيسيللين", "فنتولين"))):
        for name in drugs:
            drug_round.order(stay, name, user=doctor, dose="حسب الوزن",
                             route="oral", every_hours=8)
            orders += 1
    clinical_pharmacy.review(stays[0], user=doctor, note="مراجعة تجريبية")
    return {"orders": orders}


def _theatres():
    """غرفة عمليات (أو الموجودة) وعملية على قايمة بكرة."""
    from app.models import Theatre
    from app.utils import theatres

    kids = _demo_patients(1)
    if not kids:
        return None
    room = Theatre.query.filter_by(is_active=True).order_by(Theatre.id).first()
    if room is None:
        room = Theatre(name="غرفة عمليات ١", is_active=True)
        db.session.add(room)
        db.session.flush()
    theatres.book(kids[0], room, "استئصال اللوز",
                  on_date=local_today() + timedelta(days=1),
                  user=_doctor())
    return {"operations": 1}


def _dentistry():
    """خطة علاج أسنان لطفل، ببندين."""
    from app.models import TreatmentPlan, TreatmentPlanItem

    kids = _demo_patients(1)
    if not kids:
        return None
    doctor = _doctor()
    plan = TreatmentPlan(patient_id=kids[0].id, doctor_id=doctor.id,
                         title="خطة علاج تجريبية", created_by=doctor.id)
    db.session.add(plan)
    db.session.flush()
    for tooth, what, price in ((54, "حشو ضرس لبني", 350),
                               (64, "تنظيف وفلورايد", 200)):
        db.session.add(TreatmentPlanItem(plan_id=plan.id, tooth=tooth,
                                         description=what, price=price))
    return {"plans": 1}


def _duty():
    """نوبتجيتين في الجدول لو مفيش، والطبيب على نوبتجية النهارده."""
    from app.models import DutySlot
    from app.utils import duty

    slot = DutySlot.query.order_by(DutySlot.id).first()
    if slot is None:
        slot = DutySlot(name="صباحي", start_time=time(8, 0),
                        end_time=time(16, 0))
        db.session.add(slot)
        db.session.add(DutySlot(name="مسائي", start_time=time(16, 0),
                                end_time=time(23, 59)))
        db.session.flush()
    duty.assign(_doctor(), slot, on_date=local_today(),
                user=_doctor())
    return {"duties": 1}


#: (المفتاح، الأقسام اللي لازم تبقى مفتوحة، الزرع). بالترتيب: العيادة
#: الأول، والعنابر قبل اللي بيتبني على الأطفال الداخلين.
SECTIONS = (
    ("clinic", ("patients",), _clinic),
    ("wards", ("beds",), _wards),
    ("observations", ("observations",), _observations),
    ("labs", ("labs",), _labs),
    ("pharmacy", ("pharmacy",), _pharmacy),
    ("theatres", ("theatres",), _theatres),
    ("dentistry", ("dentistry",), _dentistry),
    ("duty", ("duty",), _duty),
)
KEYS = tuple(key for key, _modules, _seed in SECTIONS)


# ------------------------------------------------------------ the state ----
def seeded():
    """الأقسام اللي اتحمّلت. العيادة كمان لو اتحمّلت بالطريقة القديمة، قبل
    ما الأقسام يبقى ليها تسجيل."""
    done = {k for k in (Setting.get(SEEDED, "") or "").split(",") if k}
    if Setting.get("demo_seeded") == "1":
        done.add("clinic")
    # «امسح البيانات» بيسيب تخطيط المستشفى عن قصد، والعنبر التجريبي بيفضل
    # في الكشف. طول ما هو موجود القسم متحمّل — وإلا كان زرار «حمّل» هيفضل
    # ظاهر ومش بيعمل حاجة.
    if _demo_ids("care_units"):
        done.add("wards")
    return done


def _mark(keys):
    Setting.set(SEEDED, ",".join(k for k in KEYS if k in keys))


def clear():
    """بعد المسح: مفيش قسم متحمّل."""
    Setting.set(SEEDED, "")


def missing():
    """الأقسام المفتوحة اللي لسه مالهاش بيانات تجريبية — والعيادة نفسها لو
    لسه ما اتحمّلتش."""
    done = seeded()
    return [key for key, modules, _seed in SECTIONS
            if key not in done and all(_enabled(m) for m in modules)]


def _catalogue_first():
    """العيادة الفاضية بتاخد كتالوجها — الأدوية والتطعيمات والخدمات —
    **قبل** صورة الزرع، مش جوّاها. جوّاها كان الكتالوج هيتسجّل تجريبي،
    و«امسح التجريبية بس» كان هيشيل ٢٢ ألف دوا من تحت الروشتة."""
    from app.models import Service
    from app.utils.reference import seed_reference

    if Service.query.first() is None:
        seed_reference()
        db.session.flush()


def load():
    """حمّل لكل قسم مفتوح مالوش. بيرجّع ``{"sections": {قسم: ملخّص},
    "skipped": bool}`` — ومعاه ملخّص العيادة لو اتحمّلت دلوقتي."""
    from app.utils import demo_trace

    done = seeded()
    if "clinic" not in done:
        _catalogue_first()
    out = {}
    for key, modules, seed in SECTIONS:
        if key in done or not all(_enabled(m) for m in modules):
            continue
        if key != "clinic" and "clinic" not in done:
            continue                    # كل قسم بيتبني على مرضى العيادة
        before = demo_trace.snapshot()
        result = seed()
        if result is None:
            continue                    # مالقاش حاجة يتبني عليها — بعدين
        db.session.flush()
        demo_trace.record(before, merge=True)
        done.add(key)
        out[key] = result
    _mark(done)
    if "clinic" in done:
        Setting.set("demo_seeded", "1")
    db.session.commit()
    summary = dict(out.get("clinic") or {})
    summary.update({"sections": out, "skipped": not out})
    return summary
