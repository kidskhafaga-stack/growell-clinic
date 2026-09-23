"""«امسح البيانات التجريبية بس» — وإزاي البرنامج يعرف أنهي صف تجريبي.

**الصف التجريبي شكله زي الحقيقي بالظبط.** `seed_demo` بيعمل مرضى
وفواتير ومواعيد، وبعد ما يخلص مفيش حاجة فيهم بتقول إنهم جم من هناك.

والمسح بالاسم بيصيب: «يوسف الشريف» اسم تجريبي، وممكن يكون كمان اسم طفل
حقيقي. فالزارع هو اللي بيسجّل اللي عمله — **بالفرق**، مش بتغليف كل سطر
بيكتب.

**وصف تجريبي حد بنى عليه شغل حقيقي ما بيتمسحش** — بيتساب، **وبيتقال
إنه اتساب**.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: F401,E402


# ============ الأقسام التجريبية ============
def test_the_demo_now_builds_a_ward(clinic):
    """كانت بتعمل مرضى وفواتير ومواعيد — **ولا سرير واحد**."""
    from app.models import Admission, Bed, Space, Unit
    from app.utils.demo import seed_demo

    with clinic["app"].app_context():
        out = seed_demo()

        assert out["ward"]["units"] == 4
        assert Unit.query.count() == 4
        assert Space.query.count() > 0
        assert Bed.query.count() > 0
        # وطفلين داخلين، علشان اللوحة ما تبقاش فاضية وهي بتتعرض.
        assert Admission.query.count() == 2


def test_the_ward_is_built_by_the_same_wizard_the_clinic_uses(clinic):
    """**مش بكود تاني.** طريقتين لبناء عنبر كانوا هيفترقوا بصمت — ولو
    الويزارد باظ يوم، البيانات التجريبية تبوظ معاه ويتمسك."""
    source = open("app/utils/demo.py", encoding="utf-8").read()
    assert "ward_plan.build(" in source
    assert "ward_plan.field(" in source


def test_the_unit_names_match_the_clinic_s_own_words(clinic):
    """الأسامي من ملف اللغة بنفس مفاتيح الويزارد — مش مكتوبة في الكود."""
    import json

    from app.models import Unit
    from app.utils.demo import seed_demo

    ar = json.load(open("app/i18n/locales/ar.json", encoding="utf-8"))

    with clinic["app"].app_context():
        seed_demo()
        names = {u.name for u in Unit.query.all()}

        assert ar["ward_wizard"]["name_unit_emergency"] in names
        assert ar["ward_wizard"]["name_unit_nicu"] in names


def test_seeding_twice_does_not_build_a_second_hospital(clinic):
    from app.models import Unit
    from app.utils.demo import seed_ward

    with clinic["app"].app_context():
        seed_ward([])
        clinic["db"].session.commit()
        again = seed_ward([])

        assert again.get("skipped") is True
        assert Unit.query.count() == 4


# ============ الكشف ============
def test_the_seeder_records_what_it_made(clinic):
    from app.utils import demo_trace
    from app.utils.demo import seed_demo

    with clinic["app"].app_context():
        seed_demo()
        plan = demo_trace.manifest()

        assert plan
        assert "patients" in plan and "care_beds" in plan
        assert all(isinstance(ids, list) and ids for ids in plan.values())


def test_the_manifest_is_ids_not_names(clinic):
    """**المسح بالاسم بيصيب.** «يوسف الشريف» ممكن يكون طفل حقيقي كمان."""
    from app.utils import demo_trace
    from app.utils.demo import seed_demo

    with clinic["app"].app_context():
        seed_demo()
        for ids in demo_trace.manifest().values():
            assert all(isinstance(value, int) for value in ids)


def test_the_manifest_watches_more_tables_than_the_wipe_empties(clinic):
    """**والفرق ده مقصود.** «امسح البيانات» بيسيب العنابر عن قصد —
    المبنى مش الشغل اللي حصل فيه. لكن العنبر اللي الزرع بناه هو نفسه
    تجريبي. فلو الاتنين استعملوا نفس المجموعة، واحد فيهم هيبقى غلط:
    يا «امسح البيانات» بيهدّ العنابر، يا «امسح التجريبية» بيسيب مستشفى
    وهمية ورا."""
    from app.utils import demo_trace, wipe

    with clinic["app"].app_context():
        tracked = demo_trace.tracked_tables()
        wiped = wipe.wiped_tables()

        assert wiped < tracked
        for name in ("care_units", "care_spaces", "care_beds"):
            assert name in tracked, name
            assert name not in wiped, name


def test_the_manifest_does_not_track_settings(clinic):
    """**إعداد مش بيانات.** والكشف نفسه متخزّن هناك — يعني لو اتتبّع،
    يمسح نفسه."""
    from app.utils import demo_trace

    with clinic["app"].app_context():
        assert "settings" not in demo_trace.tracked_tables()


def test_a_clinic_that_never_seeded_has_no_manifest(clinic):
    from app.utils import demo_trace

    with clinic["app"].app_context():
        assert demo_trace.manifest() == {}
        assert demo_trace.remove() == ({}, {})


# ============ المسح الانتقائي ============
def test_removing_the_demo_leaves_the_real_data(clinic):
    """**دي الحتة كلها.** `reset_all` بيمسح كل حاجة تشغيلية؛ ده بيشيل
    اللي الزرع عمله وبس."""
    from datetime import date

    from app.models import Patient
    from app.utils import demo_trace
    from app.utils.demo import seed_demo

    with clinic["app"].app_context():
        real = Patient(full_name="طفل حقيقي", patient_number="P-REAL",
                       gender="male", date_of_birth=date(2024, 1, 1))
        clinic["db"].session.add(real)
        clinic["db"].session.commit()
        real_id = real.id
        # **العدد اللي قبل الزرع**، مش رقم مكتوب: العيادة في الاختبار
        # عندها أطفال من قبل، ورقم ثابت هنا بيقيس الفكستشر مش المسح.
        before = Patient.query.count()

        seed_demo()
        assert Patient.query.count() > before

        demo_trace.remove()
        clinic["db"].session.commit()

        assert clinic["db"].session.get(Patient, real_id) is not None
        # رجعت زي ما كانت بالظبط.
        assert Patient.query.count() == before


def test_the_ward_goes_with_it(clinic):
    from app.models import Admission, Bed, Unit
    from app.utils import demo_trace
    from app.utils.demo import seed_demo

    with clinic["app"].app_context():
        seed_demo()
        demo_trace.remove()
        clinic["db"].session.commit()

        assert Unit.query.count() == 0
        assert Bed.query.count() == 0
        assert Admission.query.count() == 0


def test_a_demo_row_real_work_was_built_on_is_kept(clinic):
    """**والصف ده مش فشل.** مريض تجريبي اتعملت له زيارة حقيقية — مسحه
    كان هيسيب الزيارة بتشاور على حد مش موجود، وهو نفس اليُتم اللي
    «امسح البيانات» كان واقع فيه."""
    from app.models import Patient, User, Visit
    from app.utils import demo_trace
    from app.utils.demo import seed_demo
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        seed_demo()
        kid = Patient.query.filter(
            Patient.id.in_(demo_trace.manifest()["patients"])).first()
        doctor = User.query.filter_by(role="doctor").first()
        clinic["db"].session.add(Visit(patient_id=kid.id,
                                       doctor_id=doctor.id,
                                       visit_date=local_today()))
        clinic["db"].session.commit()
        kid_id = kid.id

        removed, kept = demo_trace.remove()
        clinic["db"].session.commit()

        assert clinic["db"].session.get(Patient, kid_id) is not None
        assert kept.get("patients", 0) >= 1
        assert removed


def test_children_go_before_parents(clinic):
    """لو الأب اتمسح الأول، ابنه التجريبي بيفضل بيشاور عليه — وهو نفس
    اليُتم اللي بنصلّحه."""
    from app.utils import demo_trace, wipe
    from app.utils.demo import seed_demo

    with clinic["app"].app_context():
        seed_demo()
        demo_trace.remove()
        clinic["db"].session.commit()

        tables = wipe._tables()
        from sqlalchemy import select
        for name, table in tables.items():
            for column in table.columns:
                for fk in column.foreign_keys:
                    rows = clinic["db"].session.execute(
                        select(column).where(column.isnot(None))
                    ).scalars().all()
                    if not rows:
                        continue
                    live = set(clinic["db"].session.execute(
                        select(fk.column)).scalars().all())
                    assert all(v in live for v in rows), (name, column.name)


def test_a_demo_row_that_points_at_its_own_child_still_goes(clinic):
    """**اللفّة الواحدة مش كفاية، واتقاس.**

    `visits.based_on_id` بتشاور على `visit_investigations`، و
    `visit_investigations.visit_id` بتشاور على `visits` — والتعليق في
    الموديل بيقول ليه: *"the answer, the decision and the question it
    came from are one chain rather than three loose rows"*.

    فأي ترتيب بيسيب طرف بيشاور على التاني وقت ما نعدّي عليه، والطرف ده
    بيتحسب «حد بنى عليه شغل حقيقي» ويتساب بالغلط. واللفّة اللي بعدها
    بتلاقيه فاضي.

    من غير التكرار، القياس كان: أربع جداول اتسابت — الزيارة، والتحليل،
    والمريض ورا الاتنين، وعيلته.
    """
    from app.models import Visit, VisitInvestigation
    from app.utils import demo_trace
    from app.utils.demo import seed_demo

    with clinic["app"].app_context():
        seed_demo()
        plan = demo_trace.manifest()

        probe = VisitInvestigation.query.filter(
            VisitInvestigation.id.in_(plan["visit_investigations"])).first()
        follow_up = Visit.query.filter(
            Visit.id.in_(plan["visits"]),
            Visit.id != probe.visit_id).first()
        follow_up.based_on_id = probe.id
        clinic["db"].session.commit()

        removed, kept = demo_trace.remove()
        clinic["db"].session.commit()

        assert kept == {}
        assert removed["visits"] == len(plan["visits"])
        assert removed["visit_investigations"] == len(
            plan["visit_investigations"])


def test_a_full_wipe_drops_the_manifest_rows_it_emptied(clinic):
    """**الأرقام بتترد.** «امسح البيانات» بيفضّي المرضى، وSQLite بيدّي
    المريض الحقيقي الجديد أول رقم فاضي — يعني رقم كان لمريض تجريبي. لو
    الكشف فضل مكانه، «امسح التجريبية» بعدها كان هيمسح طفل مالوش دعوة."""
    from app.utils import demo_trace
    from app.utils.demo import reset_all, seed_demo

    with clinic["app"].app_context():
        seed_demo()
        assert "patients" in demo_trace.manifest()

        reset_all()
        plan = demo_trace.manifest()

        assert "patients" not in plan
        assert "invoices" not in plan


def test_but_the_ward_stays_in_the_manifest(clinic):
    """لأن «امسح البيانات» **ما بيهدّش العنابر** — المبنى مش الشغل اللي
    حصل فيه. فالعنبر التجريبي بيعيش المسح، ولسه ينفع يتشال لوحده."""
    from app.models import Unit
    from app.utils import demo_trace
    from app.utils.demo import reset_all, seed_demo

    with clinic["app"].app_context():
        seed_demo()
        reset_all()

        assert Unit.query.count() == 4
        assert "care_units" in demo_trace.manifest()

        demo_trace.remove()
        clinic["db"].session.commit()
        assert Unit.query.count() == 0


def test_the_count_it_reports_is_what_the_database_deleted(clinic):
    """صف الكشف ممكن يكون اتشال قبل كده بإيد حد. «اتمسح ٢٠ صف» وإحنا
    مسحنا واحد رقم بيكدب على اللي قدام الشاشة."""
    from app.models import Appointment
    from app.utils import demo_trace
    from app.utils.demo import seed_demo

    with clinic["app"].app_context():
        seed_demo()
        listed = len(demo_trace.manifest()["appointments"])
        assert listed > 1

        # حد شال ميعاد تجريبي بإيده من الشاشة.
        gone = Appointment.query.filter(
            Appointment.id.in_(demo_trace.manifest()["appointments"])).first()
        clinic["db"].session.delete(gone)
        clinic["db"].session.commit()

        removed, _kept = demo_trace.remove()
        clinic["db"].session.commit()

        assert removed["appointments"] == listed - 1


def test_the_manifest_is_cleared_afterwards(clinic):
    from app.utils import demo_trace
    from app.utils.demo import seed_demo

    with clinic["app"].app_context():
        seed_demo()
        demo_trace.remove()
        clinic["db"].session.commit()

        assert demo_trace.manifest() == {}


# ============ الشاشة ============
def _owner(clinic):
    from app.models import Setting, User

    with clinic["app"].app_context():
        boss = User.query.filter_by(username="boss").one()
        boss.is_super_admin = True
        # من غير ده كل شاشة بتحوّل على «تجهيز المنشأة»، والصفحة اللي
        # بنقراها بتبقى صفحة تحويل — اللي بندوّر عليه مش فيها، والاختبار
        # بينجح وهو ما شافش الشاشة أصلاً.
        Setting.set("facility_configured", "1")
        clinic["db"].session.commit()
    return clinic["sign_in"]("boss")


def _data_page(clinic):
    page = _owner(clinic).get("/settings/data")
    # **الشاشة اتفتحت فعلاً.** «مش موجود» في صفحة تحويل مش إجابة.
    assert page.status_code == 200
    body = page.get_data(as_text=True)
    assert "/settings/data/reset" in body
    return body


def test_the_button_is_not_drawn_before_anything_was_seeded(clinic):
    """زرار مش هيعمل حاجة بيعلّم اللي قدام الشاشة إن الأزرار بتكدب."""
    assert "data-remove-demo" not in _data_page(clinic)


def test_the_button_appears_once_there_is_demo_data(clinic):
    from app.utils.demo import seed_demo

    with clinic["app"].app_context():
        seed_demo()

    assert "data-remove-demo" in _data_page(clinic)


def test_removing_from_the_screen_works(clinic):
    from app.models import Unit
    from app.utils.demo import seed_demo

    with clinic["app"].app_context():
        seed_demo()

    client = _owner(clinic)
    page = client.post("/settings/data/remove-demo",
                       follow_redirects=True).get_data(as_text=True)

    with clinic["app"].app_context():
        assert Unit.query.count() == 0
    # **وبيقول عمل إيه.** «تم» مش إجابة على زرار بيمسح.
    assert "صف تجريبي" in page
    # والزرار اختفى، لأن مفيش تجريبي تاني.
    assert "data-remove-demo" not in page


def test_only_the_owner_may_remove_it(clinic):
    """نفس قاعدة «امسح البيانات» — ده قرار على مستوى المنشأة."""
    assert clinic["sign_in"]("boss").post(
        "/settings/data/remove-demo").status_code == 403


def test_every_word_of_the_screen_is_written_in_both_languages(clinic):
    import json

    ar = json.load(open("app/i18n/locales/ar.json", encoding="utf-8"))
    en = json.load(open("app/i18n/locales/en.json", encoding="utf-8"))

    for key in ("remove_demo_btn", "remove_demo_hint", "remove_demo_warn",
                "demo_removed", "demo_kept", "no_demo"):
        assert (ar["data_tools"].get(key) or "").strip(), key
        assert (en["data_tools"].get(key) or "").strip(), key
