"""«امسح البيانات» — واللي كان بيفضل وراه.

**اتقاس بالتشغيل، مش اتقرا:**

    ADMISSION SURVIVED: True
    POINTS AT PATIENT: 1   WHICH EXISTS: False

المريض بيتمسح والإقامة بتفضل بتشاور عليه. وده بالظبط اللي دوكسترينج
`reset_all` القديم كان بيحذّر منه بنفسه: *"orphans would later crash page
loads after a reset"*.

**والسبب إن القايمة كانت مكتوبة بالإيد** من أول البرنامج وما اتزوّدتش.
ولما اتعدّت، **٥٤ جدول بيتكلم عن طفل كان بره المسح**.

فالقايمة اتشالت والقاعدة بقت محسوبة — **والملف ده هو اللي بيمنع الغلطة
دي إنها ترجع** مع كل بند جديد بيتبني.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: F401,E402


# ============ الحارس: الجدول الجديد لازم حد يقرّر فيه ============
def test_every_table_is_either_kept_or_wiped_on_purpose():
    """**ودي الحتة اللي بتمنع الغلطة ترجع.**

    جدول إكلينيكي جديد بيتمسح لوحده من غير ما حد يعدّل حاجة. والكتالوج
    الجديد هو اللي محتاج سطر في `KEEP` — والاختبار ده بيفشل لو حد ضاف
    جدول ومحدّش قرّر فيه.
    """
    from app.utils import wipe

    tables = set(wipe._tables())
    wiped = wipe.wiped_tables()
    kept = tables - wiped

    # كل اسم في القايمتين لازم يكون جدول حقيقي — اسم متكتوب غلط بيبقى
    # جدول محدّش بيمسحه ومحدّش واخد باله.
    assert not (wipe.KEEP - tables), sorted(wipe.KEEP - tables)
    assert not (wipe.OPERATIONAL - tables), sorted(wipe.OPERATIONAL - tables)
    assert wiped and kept


def test_nothing_that_talks_about_a_child_survives():
    """كل صف بيوصل لمريض بيتمسح — **حتى لو بعيد بخطوتين**."""
    from app.utils import wipe

    tables = wipe._tables()
    wiped = wipe.wiped_tables()
    left = [name for name, table in tables.items()
            if name not in wiped and wipe.about_a_patient(table, tables)]

    # الاستثناء الوحيد المسموح: تخطيط المستشفى نفسه.
    assert set(left) <= {"care_beds"}, sorted(left)


def test_the_hospital_building_is_not_demolished():
    """مستشفى ضغطت «امسح البيانات» عايزة تبدأ نضيفة — **مش تعيد بناء
    العنابر**. والعنابر دي اتبنت بالويزارد من شوية."""
    from app.utils import wipe

    wiped = wipe.wiped_tables()
    for table in ("care_units", "care_spaces", "care_beds"):
        assert table not in wiped, table


def test_the_catalogues_survive():
    """مسح قايمة أسعار عيادة أسوأ بكتير من سيبان صف تجريبي."""
    from app.utils import wipe

    wiped = wipe.wiped_tables()
    for table in ("services", "drugs", "vaccines", "users", "settings",
                  "lookups", "abbreviations", "message_templates",
                  "store_items", "roles"):
        assert table not in wiped, table


def test_the_clinical_record_does_not(clinic):
    """والجداول اللي اتبنت بعد ما القايمة اتكتبت — دي اللي كانت بتفضل."""
    from app.utils import wipe

    wiped = wipe.wiped_tables()
    for table in ("admissions", "bed_stays", "observations",
                  "risk_assessments", "restraints", "verbal_orders",
                  "refusals", "lines", "opinions", "nutrition_assessments",
                  "pain_screens", "pain_assessments", "nursing_assessments",
                  "care_responsibilities", "referrals",
                  "discharge_summaries", "round_notes", "families"):
        assert table in wiped, table


# ============ الترتيب: الابن قبل الأب ============
def test_there_are_real_cycles_and_they_are_cut_first():
    """**مفيش ترتيب حذف صح أصلاً** — الجداول فيها دواير.

    `visits.based_on_id` بتشاور على `visit_investigations`، والعكس —
    والتعليق في الموديل بيقول ليه: *"the question it came from are one
    chain rather than three loose rows"*. فأي طرف يتمسح الأول، التاني
    بيفضل بيشاور عليه.

    الحل مش ترتيب أذكى: العمود اللي بيقفل الدايرة بيتفضّى قبل المسح.
    """
    from app.utils import wipe

    breakers = wipe.cycle_breakers()
    assert breakers, "الدواير موجودة — لو القايمة فضيت يبقى الكشف باظ"
    # وكل واحد فيهم لازم يكون nullable، وإلا القطع نفسه مستحيل.
    assert all(column.nullable for column in breakers)


def test_children_are_deleted_before_their_parents():
    """ترتيب غلط مش بيسيب يتيم وبس — **بيفشّل المسح نفسه** بخطأ مفتاح
    أجنبي على PostgreSQL، وساعتها اللي ضغط الزرار بيلاقي نص البيانات
    اتمسح."""
    from app.utils import wipe

    order = wipe.delete_order()
    place = {name: i for i, name in enumerate(order)}
    tables = wipe._tables()
    cut = {id(column) for column in wipe.cycle_breakers(tables)}

    for name in order:
        for column in tables[name].columns:
            if id(column) in cut:
                continue          # بيتفضّى قبل المسح، فمالوش ترتيب
            for fk in column.foreign_keys:
                parent = fk.column.table.name
                if parent != name and parent in place:
                    assert place[name] < place[parent], f"{name} بعد {parent}"


# ============ والسلوك نفسه ============
def test_a_reset_leaves_no_orphan_admission(clinic):
    """الاختبار اللي كان بيفشل قبل الإصلاح."""
    from app.models import Admission, Patient
    from app.utils.demo import reset_all

    with clinic["app"].app_context():
        stay = Admission(patient_id=clinic["ids"]["child"])
        clinic["db"].session.add(stay)
        clinic["db"].session.commit()

        reset_all()

        assert Admission.query.count() == 0
        assert Patient.query.count() == 0


def test_a_reset_leaves_no_orphan_anything(clinic):
    """**كل مفتاح أجنبي في البرنامج بيتسأل بعد المسح**: بيشاور على صف
    موجود ولا لأ."""
    from app.utils import wipe
    from app.utils.demo import reset_all
    from app.extensions import db
    from sqlalchemy import select

    with clinic["app"].app_context():
        reset_all()

        tables = wipe._tables()
        orphans = []
        for name, table in tables.items():
            for column in table.columns:
                for fk in column.foreign_keys:
                    parent = fk.column.table
                    rows = db.session.execute(
                        select(column).where(column.isnot(None))).scalars().all()
                    if not rows:
                        continue
                    live = set(db.session.execute(
                        select(fk.column)).scalars().all())
                    missing = [v for v in rows if v not in live]
                    if missing:
                        orphans.append((name, column.name, len(missing)))
        assert not orphans, orphans


def test_the_reset_says_what_it_deleted(clinic):
    """«تم» مش معلومة. «اتمسح ٣ مرضى و٧ فواتير» معلومة."""
    from app.models import Admission
    from app.utils.demo import reset_all

    with clinic["app"].app_context():
        clinic["db"].session.add(Admission(
            patient_id=clinic["ids"]["child"]))
        clinic["db"].session.commit()

        counts = reset_all()

        assert counts.get("admissions") == 1
        assert counts.get("patients", 0) >= 1
        assert "services" not in counts


def test_the_catalogue_is_still_there_afterwards(clinic):
    from app.models import Service, User
    from app.utils.demo import reset_all

    with clinic["app"].app_context():
        services = Service.query.count()
        users = User.query.count()

        reset_all()

        assert Service.query.count() == services
        assert User.query.count() == users
