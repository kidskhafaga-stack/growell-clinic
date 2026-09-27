"""التجريبية اللي اتحمّلت **قبل الكشف** — بتتلاقي بالوقت، وبتتشاف قبل ما تتمسح.

عيادة حمّلت بيانات تجريبية قبل ما الزرع يسجّل صفوفه: ``demo_seeded = 1``
ومفيش كشف، فزرار «امسح التجريبية بس» ما بيظهرش. اتطلب إن البرنامج يدوّر
عليها **من لحظة التحميل** اللي في سجل النشاط، ويعرض اللي لقاه، وصاحب
العيادة يأكّد قبل ما حاجة تتمسح.

اللي بيتمسك هنا:

* **بيلاقي اللي الزرع عمله بالظبط** — نفس اللي كان الكشف هيقوله؛
* **اللي اتعمل بعدين ما بيتلمسش** — مريض حقيقي، وزيارة حقيقية لطفل
  تجريبي؛
* **الكتالوج وسجل النشاط وحساب المدير ما بيترشّحوش** حتى لو في نفس
  الدقيقة؛
* **من غير لحظة في السجل مفيش تخمين**؛
* **مفيش مسح من غير عرض**: صاحب العيادة بس، والعدد اللي اتعرض لازم
  يطابق اللي هيتمسح.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: F401,E402


def _old_demo(clinic, logged="data.seed_demo", ago=timedelta(days=3)):
    """حمّل تجريبية زي ما كانت بتتحمّل قبل الكشف: الصفوف موجودة، والكشف
    فاضي. وكل حاجة اتعملت ``ago`` قبل كده — علشان «بعدين» يبقى بعدين
    بجد. بيرجّع الكشف اللي الزرع كان هيكتبه."""
    from app.extensions import db
    from app.models import ActivityLog, Setting
    from app.utils import demo_sections, demo_trace, wipe

    with clinic["app"].app_context():
        before = datetime.utcnow()
        if logged == "settings.facility_setup":
            ActivityLog.record(logged, entity="settings")
            db.session.flush()
        demo_sections.load()
        truth = demo_trace.manifest()
        if logged == "data.seed_demo":
            ActivityLog.record(logged, entity="system")
            db.session.flush()
        # نرجّع الزرع ``ago`` لورا — والعيادة اللي كانت قبله يوم كمان، زي
        # الحقيقة: الطبيب والخدمات موجودين قبل التجريبية.
        from app.utils.old_demo import _stamp

        tables = wipe._tables()
        for name, table in tables.items():
            column = _stamp(table)
            if column is None:
                continue
            rows = db.session.execute(
                db.select(table.c.id, column).where(column.isnot(None))).all()
            for row_id, at in rows:
                back = ago if at >= before else ago + timedelta(days=1)
                db.session.execute(table.update().where(table.c.id == row_id)
                                   .values({column.name: at - back}))
        Setting.set(demo_trace.MANIFEST, "")
        Setting.set(demo_sections.SEEDED, "")
        db.session.commit()
    return truth


def _preview(clinic):
    from app.utils import old_demo

    with clinic["app"].app_context():
        return old_demo.preview()


# ------------------------------------------------------------ finding ----
#: اللي الوقت مايقدرش يلاقيه كله: نسبة طبيب على خدمة كانوا الاتنين
#: موجودين قبل التجريبية — الصف نفسه مالوش تاريخ ولا بيشاور على حاجة
#: تجريبية. إعداد صغير بيفضل، ومش بيتخمّن.
UNFINDABLE = {"doctor_service_commissions"}


def _same(found, truth):
    """زي الكشف بالظبط — إلا الكتالوج اللي ما بيترشّحش أبداً، واللي الوقت
    مايقدرش يوصل له."""
    from app.utils.old_demo import NEVER

    for name in set(found) | set(truth):
        got, made = set(found.get(name, [])), set(truth.get(name, []))
        if name in NEVER:
            assert not got, name
        elif name in UNFINDABLE:
            assert got <= made, name
        else:
            assert got == made, name


def test_it_finds_what_the_seed_made(clinic):
    truth = _old_demo(clinic)
    _same(_preview(clinic)["found"], truth)


def test_a_hospital_demo_too(clinic):
    from app.models import Setting

    with clinic["app"].app_context():
        for module in ("beds", "ward", "icu", "observations", "labs",
                       "pharmacy", "theatres", "dentistry", "duty"):
            Setting.set(f"mod_enabled:{module}", "1")
        clinic["db"].session.commit()
    truth = _old_demo(clinic)
    found = _preview(clinic)["found"]
    _same(found, truth)
    assert "admissions" in found and "care_units" in found


def test_the_wizard_logs_before_it_seeds(clinic):
    """الويزارد بيكتب السطر **قبل** ما يزرع، فالصفوف بعده. ولو الزرع خد
    دقيقة، شبّاك «قبل السطر» ما يلاقيش ولا طفل."""
    from app.models import ActivityLog

    truth = _old_demo(clinic, logged="settings.facility_setup")
    with clinic["app"].app_context():
        row = ActivityLog.query.filter_by(
            action="settings.facility_setup").one()
        row.created_at -= timedelta(minutes=1)
        clinic["db"].session.commit()
    found = _preview(clinic)["found"]
    assert sorted(found["patients"]) == sorted(truth["patients"])


def test_it_shows_names_and_counts(clinic):
    _old_demo(clinic)
    shown = _preview(clinic)
    assert shown["patients"]
    assert shown["total"] == sum(rows for _name, rows in shown["tables"])
    assert dict(shown["tables"])["patients"] == len(shown["found"]["patients"])


# ------------------------------------------------------------ not touching ----
def _real_work(clinic):
    """مريض حقيقي النهارده، وزيارة حقيقية لطفل تجريبي، وعلامات حيوية —
    من غير تاريخ — على الزيارة دي."""
    from app.extensions import db
    from app.models import Patient, Visit, VitalSigns
    from app.utils import demo_trace  # noqa: F401

    with clinic["app"].app_context():
        demo_kid = Patient.query.filter(
            Patient.created_at < datetime.utcnow() - timedelta(days=1)
        ).order_by(Patient.id.desc()).first()
        real = Patient(patient_number="P-REAL", full_name="طفل حقيقي",
                       gender="male",
                       date_of_birth=datetime.utcnow().date() - timedelta(days=400))
        db.session.add(real)
        visit = Visit(patient_id=demo_kid.id, doctor_id=clinic["ids"]["doctor"],
                      visit_date=datetime.utcnow().date(), status="open",
                      chief_complaint="كحة")
        db.session.add(visit)
        db.session.flush()
        db.session.add(VitalSigns(visit_id=visit.id, temperature_c=38.2))
        db.session.commit()
        return real.id, demo_kid.id, visit.id


def test_what_was_made_afterwards_is_not_a_candidate(clinic):
    _old_demo(clinic)
    real, demo_kid, visit = _real_work(clinic)
    found = _preview(clinic)["found"]
    assert real not in found["patients"]
    assert visit not in found.get("visits", [])
    from app.models import VitalSigns

    with clinic["app"].app_context():
        vitals = VitalSigns.query.filter_by(visit_id=visit).one().id
    assert vitals not in found.get("vital_signs", [])
    # والطفل التجريبي نفسه لسه مرشّح — المسح هو اللي بيسيبه.
    assert demo_kid in found["patients"]


def test_a_real_row_on_a_demo_row_and_a_real_one_is_not_a_candidate(clinic):
    """نسبة طبيب حقيقي اتعيّن النهارده على خدمة تجريبية: بتشاور على مرشّح،
    بس كمان على حاجة اتعملت بعد الشبّاك — يبقى شغل حقيقي."""
    from app.extensions import db
    from app.models import DoctorServiceCommission, User

    truth = _old_demo(clinic)
    with clinic["app"].app_context():
        new_doctor = User(username="doc9", full_name="د. جديد", role="doctor",
                          is_active=True)
        new_doctor.set_password("x")
        db.session.add(new_doctor)
        db.session.flush()
        share = DoctorServiceCommission(doctor_id=new_doctor.id,
                                        service_id=truth["services"][0],
                                        commission_type="percent",
                                        commission_value=10)
        db.session.add(share)
        db.session.commit()
        share_id = share.id
    found = _preview(clinic)["found"]
    assert share_id not in found.get("doctor_service_commissions", [])


def test_the_catalogue_the_log_and_the_owner_are_never_candidates(clinic):
    from app.extensions import db
    from app.models import ActivityLog, Drug, User

    with clinic["app"].app_context():
        boss = User.query.filter_by(username="boss").one()
        boss.is_super_admin = True
        db.session.commit()
    truth = _old_demo(clinic)
    with clinic["app"].app_context():
        # في نفس الدقيقة: مدير جديد، ودوا في الكتالوج.
        at = ActivityLog.query.filter_by(action="data.seed_demo").one() \
            .created_at - timedelta(seconds=1)
        admin = User(username="admin2", full_name="مدير", role="admin",
                     is_active=True, created_at=at)
        admin.set_password("x")
        db.session.add(admin)
        db.session.add(Drug(trade_name="Trialamol", created_at=at))
        db.session.commit()
        admin_id = admin.id
    found = _preview(clinic)["found"]
    for table in ("activity_log", "vaccines", "drugs", "lookups"):
        assert table not in found, table
    assert admin_id not in found.get("users", [])
    assert set(found.get("users", [])) == set(truth.get("users", []))


def test_no_moment_no_guess(clinic):
    from app.models import ActivityLog

    _old_demo(clinic)
    with clinic["app"].app_context():
        ActivityLog.query.filter_by(action="data.seed_demo").delete()
        clinic["db"].session.commit()
    assert _preview(clinic) is None


def test_a_moment_with_no_patients_in_it_is_passed_over(clinic):
    """الويزارد اتشغّل تاني من غير تجريبية: اللحظة الأحدث مفيهاش مرضى،
    فبيتعدّى عليها للّي فيها."""
    from app.models import ActivityLog

    truth = _old_demo(clinic)
    with clinic["app"].app_context():
        ActivityLog.record("settings.facility_setup", entity="settings")
        clinic["db"].session.commit()
    assert sorted(_preview(clinic)["found"]["patients"]) == \
        sorted(truth["patients"])


# ------------------------------------------------------------ the screen ----
def _owner(clinic):
    from app.extensions import db
    from app.models import Setting, User

    with clinic["app"].app_context():
        boss = User.query.filter_by(username="boss").one()
        boss.is_super_admin = True
        Setting.set("facility_configured", "1")
        db.session.commit()
    return clinic["sign_in"]("boss")


def test_the_data_page_points_to_it_only_when_it_applies(clinic):
    client = _owner(clinic)
    assert "data-old-demo" not in client.get("/settings/data").get_data(as_text=True)
    _old_demo(clinic)
    assert "data-old-demo" in client.get("/settings/data").get_data(as_text=True)


def test_shown_then_removed(clinic):
    from app.models import ActivityLog, Patient, Setting

    truth = _old_demo(clinic)
    real, demo_kid, _visit = _real_work(clinic)
    client = _owner(clinic)
    page = client.get("/settings/data/old-demo").get_data(as_text=True)
    total = _preview(clinic)["total"]
    assert f'data-old-demo-total="{total}"' in page
    reply = client.post("/settings/data/old-demo", data={"expected": str(total)})
    assert reply.status_code == 302
    with clinic["app"].app_context():
        left = {p.id for p in Patient.query.all()}
        assert real in left
        # الطفل التجريبي اللي اتعمل له زيارة حقيقية بيتساب.
        assert demo_kid in left
        assert not (set(truth["patients"]) - {demo_kid}) & left
        assert Setting.get("demo_seeded") == "0"
        assert ActivityLog.query.filter_by(action="data.remove_old_demo").count() == 1


def test_a_count_that_changed_removes_nothing(clinic):
    from app.models import Patient

    _old_demo(clinic)
    client = _owner(clinic)
    with clinic["app"].app_context():
        before = Patient.query.count()
    client.post("/settings/data/old-demo", data={"expected": "1"})
    client.post("/settings/data/old-demo", data={})
    with clinic["app"].app_context():
        assert Patient.query.count() == before


def test_only_the_owner(clinic):
    from app.models import Patient

    _old_demo(clinic)
    total = str(_preview(clinic)["total"])
    with clinic["app"].app_context():
        before = Patient.query.count()
    for who in ("boss", "doc", "desk"):         # boss here is a plain admin
        reply = clinic["sign_in"](who).post("/settings/data/old-demo",
                                            data={"expected": total})
        assert reply.status_code in (302, 403)
    with clinic["app"].app_context():
        assert Patient.query.count() == before


def test_with_a_manifest_it_does_not_apply(clinic):
    from app.utils import demo_sections, old_demo

    with clinic["app"].app_context():
        demo_sections.load()
        assert not old_demo.applies()


# ------------------------------------------------------------ the catalogue ----
def test_a_first_demo_in_an_empty_clinic_does_not_record_the_catalogue(clinic):
    """عيادة من غير خدمات: الكتالوج بيتحمّل مع أول تجريبية — **قبل**
    صورتها، فمش في الكشف، و«امسح التجريبية» ما بيشيلوش."""
    from app.extensions import db
    from app.models import Service
    from app.utils import demo_sections, demo_trace

    with clinic["app"].app_context():
        db.session.execute(db.text("PRAGMA foreign_keys=OFF"))
        for table in ("doctor_service_commissions", "services"):
            db.session.execute(db.text(f"DELETE FROM {table}"))
        db.session.commit()
        assert Service.query.first() is None
        demo_sections.load()
        plan = demo_trace.manifest()
        assert Service.query.first() is not None
        for table in ("drugs", "vaccines", "generic_drugs"):
            assert table not in plan, table
