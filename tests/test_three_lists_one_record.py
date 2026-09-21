"""تلات قوايم صريحة، وسجل واحد — GAHAR `SAS.18` · `SAS.23` · `SAS.24`.

**دي تاني مرة الكتاب بيعدّد محتويات سجل بالنص** بعد قايمة الطوارئ
`ICD.03(e)`. وحطّ القايمتين الأولانيتين جنب بعض بيوري إنهم نفس القايمة:
إحدى عشر بند وعشرة، والفرق **تلات بنود بس** — التخدير فيه نوع التخدير
والدم، والتسكين فيه درجة التسكين.

فسجل واحد، والقايمة المطلوبة بتتغيّر بالنوع. وجدولين كانوا هيبقوا نسختين
من نفس الحاجة بيفرقوا مع الوقت.

و`SAS.24` مرحلة تانية من نفس الحلقة: (ي) «وقت النقل» في قايمة التخدير
و(ب) «وقت استلام المريض» في قايمة الإفاقة **لحظة واحدة**، وعمودين ليها
كانوا هيقدروا يختلفوا.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def theatre(clinic):
    from app.models import Patient, Setting
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        Setting.set("mod_enabled:beds", "1")
        other = Patient(patient_number="SD-2", full_name="طفل تاني",
                        gender="female", is_active=True,
                        date_of_birth=local_today() - timedelta(days=1500))
        clinic["db"].session.add(other)
        clinic["db"].session.commit()
        clinic["ids"]["other_child"] = other.id
    return clinic


def _open(theatre, kind="sedation", patient_id=None, at=None):
    from app.models import Patient, User
    from app.utils import sedation as sed

    with theatre["app"].app_context():
        patient = theatre["db"].session.get(
            Patient, patient_id or theatre["ids"]["child"])
        doc = theatre["db"].session.get(User, theatre["ids"]["doctor"])
        row = sed.start(patient, kind, user=doc, at=at)
        theatre["db"].session.commit()
        return row.id


def _row(theatre, rid):
    from app.models import SedationRecord

    return theatre["db"].session.get(SedationRecord, rid)


def _missing(theatre, rid):
    from app.utils import sedation as sed

    with theatre["app"].app_context():
        return sed.missing(_row(theatre, rid))


def _reading(theatre, rid, minutes_ago=0, patient_id=None):
    from app.models import Observation

    with theatre["app"].app_context():
        theatre["db"].session.add(Observation(
            patient_id=patient_id or theatre["ids"]["child"], sedation_id=rid,
            taken_at=datetime.utcnow() - timedelta(minutes=minutes_ago),
            spo2=98))
        theatre["db"].session.commit()


# --------------------------- القايمتين نفس القايمة، والفرق تلاتة ----
def test_the_two_lists_differ_by_exactly_three_items(theatre):
    """اللي المعيارين بيقولوه لما تحطّهم جنب بعض — والسبب اللي خلّى ده سجل
    واحد مش اتنين."""
    from app.models.sedation import required_for

    anaes = set(required_for("anaesthesia"))
    sedate = set(required_for("sedation"))

    assert anaes - sedate == {"technique", "blood"}
    assert sedate - anaes == {"score"}
    assert len(anaes) == 11 and len(sedate) == 10


def test_an_anaesthetic_is_asked_for_its_own_two(theatre):
    rid = _open(theatre, "anaesthesia")

    gaps = _missing(theatre, rid)

    assert "technique" in gaps and "blood" in gaps
    assert "score" not in gaps


def test_a_sedation_is_asked_for_its_own_one(theatre):
    rid = _open(theatre, "sedation")

    gaps = _missing(theatre, rid)

    assert "score" in gaps
    assert "technique" not in gaps and "blood" not in gaps


def test_a_kind_the_record_does_not_know_is_refused(theatre):
    from app.models import Patient
    from app.utils import sedation as sed

    with theatre["app"].app_context():
        patient = theatre["db"].session.get(Patient, theatre["ids"]["child"])
        with pytest.raises(ValueError):
            sed.start(patient, "hypnosis")


# ------------------------------------- الوقت جزء من حساب الناقص ----
def test_a_child_still_on_the_table_is_not_missing_the_leaving_items(theatre):
    """«حالته قبل ما يسيب المسرح» و«المآل» و«التوقيع» بيتكتبوا وهو بيخرج.

    عدّهم ناقصين وهو لسه على الترابيزة بيخلّي كل حالة شغّالة تبان ملف
    ناقص، وبيعلّم اللي بيقرا إنه يتجاهل اللون.
    """
    rid = _open(theatre)

    gaps = _missing(theatre, rid)

    for item in ("condition", "disposition", "transfer", "signature"):
        assert item not in gaps


def test_leaving_the_theatre_is_what_makes_them_count(theatre):
    from app.models import User
    from app.utils import sedation as sed

    rid = _open(theatre)
    with theatre["app"].app_context():
        doc = theatre["db"].session.get(User, theatre["ids"]["doctor"])
        sed.leave_theatre(_row(theatre, rid), "recovery", user=doc)
        theatre["db"].session.commit()

    assert "condition" in _missing(theatre, rid)


def test_the_condition_is_written_at_the_moment_of_leaving(theatre):
    """شاشة تانية ليها كانت هتخلّيها البند اللي بيفضل فاضي في كل ملف."""
    from app.models import User
    from app.utils import sedation as sed

    rid = _open(theatre)
    with theatre["app"].app_context():
        doc = theatre["db"].session.get(User, theatre["ids"]["doctor"])
        sed.leave_theatre(_row(theatre, rid), "recovery",
                          condition="فايق ومستقر", user=doc)
        theatre["db"].session.commit()

    assert "condition" not in _missing(theatre, rid)


def test_a_child_still_in_recovery_is_not_missing_its_leaving_items(theatre):
    from app.models import User
    from app.utils import sedation as sed

    rid = _open(theatre)
    with theatre["app"].app_context():
        doc = theatre["db"].session.get(User, theatre["ids"]["doctor"])
        sed.leave_theatre(_row(theatre, rid), "recovery", user=doc)
        theatre["db"].session.commit()

    gaps = _missing(theatre, rid)

    for item in ("recovery_score", "recovery_disposition",
                 "recovery_transfer", "recovery_signature"):
        assert item not in gaps


def test_a_child_who_never_went_to_recovery_is_not_asked_about_it(theatre):
    """راح البيت من المسرح على طول. بنود الإفاقة مالهاش معنى عليه، وطلبها
    منه بيخلّي كل ملف يبان ناقص ستّ بنود."""
    from app.models import User
    from app.utils import sedation as sed

    rid = _open(theatre)
    with theatre["app"].app_context():
        doc = theatre["db"].session.get(User, theatre["ids"]["doctor"])
        sed.leave_theatre(_row(theatre, rid), "home", condition="تمام",
                          user=doc)
        theatre["db"].session.commit()

    gaps = _missing(theatre, rid)

    assert not [g for g in gaps if g.startswith("recovery_")]


# ------------------------- وقت واحد للحظة واحدة (SAS.18-ي = SAS.24-ب) ----
def test_the_transfer_out_and_the_arrival_in_are_one_moment(theatre):
    """عمودين ليها كانوا هيقدروا يختلفوا، وساعتها الملف بيقول إن الطفل ساب
    المسرح الساعة تلاتة ووصل الإفاقة الساعة اتنين."""
    from app.models import SedationRecord, User
    from app.utils import sedation as sed

    rid = _open(theatre)
    with theatre["app"].app_context():
        doc = theatre["db"].session.get(User, theatre["ids"]["doctor"])
        sed.leave_theatre(_row(theatre, rid), "recovery", user=doc)
        theatre["db"].session.commit()
        row = _row(theatre, rid)

        assert row.left_theatre_at is not None
        assert row.in_recovery
        columns = {c.name for c in SedationRecord.__table__.columns}

    assert "recovery_started_at" not in columns
    assert "recovery_received_at" not in columns


def test_a_disposition_the_record_cannot_draw_is_refused_at_both_doors(theatre):
    """«راح فين» بيتكتب مرتين — خارج من المسرح وخارج من الإفاقة — والاتنين
    بيرفضوا كلمة الشاشة مش عارفة ترسمها.

    وطفرة عاشت على الباب الأول لأن الاختبارات كانت بتجرّب الرفض على
    التاني بس: نفس الحارس مكتوب في مكانين، وواحد فيهم مكانش متغطّى.
    """
    from app.models import User
    from app.utils import sedation as sed

    rid = _open(theatre)
    with theatre["app"].app_context():
        doc = theatre["db"].session.get(User, theatre["ids"]["doctor"])
        with pytest.raises(ValueError):
            sed.leave_theatre(_row(theatre, rid), "the_moon", user=doc)
        theatre["db"].session.rollback()

        sed.leave_theatre(_row(theatre, rid), "recovery", user=doc)
        theatre["db"].session.commit()
        with pytest.raises(ValueError):
            sed.leave_recovery(_row(theatre, rid), "the_moon")


def test_leaving_recovery_without_ever_reaching_it_is_refused(theatre):
    """صف بيقول إنه ساب مكان عمره ما دخله."""
    from app.utils import sedation as sed

    rid = _open(theatre)
    with theatre["app"].app_context():
        with pytest.raises(ValueError):
            sed.leave_recovery(_row(theatre, rid), "home")


def test_the_recovery_stay_is_read_from_the_two_times(theatre):
    from app.models import User
    from app.utils import sedation as sed

    rid = _open(theatre)
    with theatre["app"].app_context():
        doc = theatre["db"].session.get(User, theatre["ids"]["doctor"])
        assert _row(theatre, rid).recovery_minutes is None
        sed.leave_theatre(_row(theatre, rid), "recovery", user=doc)
        theatre["db"].session.commit()

        assert _row(theatre, rid).recovery_minutes is not None


# ------------------- لحظة واحدة، ومصدر واحد لما يكون فيه عملية ----
def _case(theatre):
    """عملية خلصت — علشان `Operation.recovery_at` يبقى ليه معنى."""
    from app.models import Operation, Theatre
    from app.utils.clock import local_today

    with theatre["app"].app_context():
        room = Theatre(name="مسرح ١")
        theatre["db"].session.add(room)
        theatre["db"].session.flush()
        op = Operation(patient_id=theatre["ids"]["child"],
                       theatre_id=room.id, on_date=local_today(),
                       status="done", procedure="ختان")
        theatre["db"].session.add(op)
        theatre["db"].session.commit()
        return op.id


def test_a_linked_record_reads_the_operations_own_times(theatre):
    """**مصدرين لنفس اللحظة كانوا هيقدروا يختلفوا.**

    `Operation.recovery_at` موجود من قبل السجل ده، وشاشة الإفاقة بتقراه.
    فلو السجل خزّن نسخته، الشاشتين كانوا هيقولوا وقتين مختلفين لنفس
    الخروجة — وده اللي البرنامج ده بيشيله كل مرة.
    """
    from app.models import Operation, SedationRecord, User
    from app.utils import sedation as sed

    op_id = _case(theatre)
    with theatre["app"].app_context():
        from app.models import Patient

        patient = theatre["db"].session.get(Patient, theatre["ids"]["child"])
        doc = theatre["db"].session.get(User, theatre["ids"]["doctor"])
        op = theatre["db"].session.get(Operation, op_id)
        row = sed.start(patient, "anaesthesia", user=doc, operation=op)
        theatre["db"].session.commit()
        rid = row.id

        sed.leave_theatre(_row(theatre, rid), "recovery", user=doc)
        theatre["db"].session.commit()

        row = theatre["db"].session.get(SedationRecord, rid)
        op = theatre["db"].session.get(Operation, op_id)

        # الوقت اتكتب على العملية، والسجل بيقراه — ومفيش نسخة تانية.
        assert op.recovery_at is not None
        assert row.theatre_out == op.recovery_at
        assert row.left_theatre_at is None


def test_the_record_does_not_send_the_child_home_on_somebodys_behalf(theatre):
    """**السجل بيكتب بنوده، وما بياخدش قرار غيره.**

    `recovery.discharge` بيرفض من غير قرار المتابعة عن قصد — علشان «مش
    محتاج متابعة» و«محدّش سأل» ما يبقوش نفس الحاجة. وده قرار تاني خالص غير
    بنود `SAS.24`، فتسجيل الإفاقة ما بيصرفش الطفل: بيكتب الدرجة والحدث
    والتوقيع، و«وقت النقل» بيفضل ناقص لحد ما شاشة الإفاقة تصرفه بقرارها —
    **وهو ناقص فعلاً**.
    """
    from app.models import Operation, Patient, SedationRecord, User
    from app.utils import recovery as room
    from app.utils import sedation as sed

    op_id = _case(theatre)
    with theatre["app"].app_context():
        patient = theatre["db"].session.get(Patient, theatre["ids"]["child"])
        doc = theatre["db"].session.get(User, theatre["ids"]["doctor"])
        op = theatre["db"].session.get(Operation, op_id)
        row = sed.start(patient, "anaesthesia", user=doc, operation=op)
        theatre["db"].session.commit()
        rid = row.id
        sed.leave_theatre(_row(theatre, rid), "recovery", user=doc)
        sed.leave_recovery(_row(theatre, rid), "home", score="Aldrete 10",
                           user=doc)
        theatre["db"].session.commit()

        row = theatre["db"].session.get(SedationRecord, rid)
        op = theatre["db"].session.get(Operation, op_id)

        # بنود SAS.24 اتكتبت، والطفل لسه ما اتصرفش.
        assert row.recovery_score == "Aldrete 10"
        assert op.discharged_at is None
        assert row.in_recovery

        # ولما شاشة الإفاقة تصرفه بقرارها، السجل بيقرا وقتها.
        room.discharge(op, user=doc, followup=False)
        theatre["db"].session.commit()
        row = theatre["db"].session.get(SedationRecord, rid)

        assert row.recovery_out == op.discharged_at
        assert row.recovery_left_at is None
        assert not row.in_recovery


def test_the_transfer_times_are_guaranteed_by_construction(theatre):
    """**«وقت النقل» ما بيبانش ناقص أبداً، وده مقصود.**

    الوقت هو اللي بيقفل المرحلة: طول ما هو فاضي الطفل لسه جوّه فالبند ما
    جاش وقته، وأول ما يتكتب البند اتعمل. يعني البند مضمون بالبناء مش
    بالفحص — وده أقوى من فاحص، والاختبار ده بيثبت الضمانة بدل ما يسيب
    حالة فاحص عمرها ما بتيجي.
    """
    from app.models import User
    from app.utils import sedation as sed

    rid = _open(theatre)
    with theatre["app"].app_context():
        doc = theatre["db"].session.get(User, theatre["ids"]["doctor"])
        assert "transfer" not in sed.missing(_row(theatre, rid))

        sed.leave_theatre(_row(theatre, rid), "recovery", user=doc)
        theatre["db"].session.commit()
        row = _row(theatre, rid)

        assert row.theatre_out is not None
        assert "transfer" not in sed.missing(row)


def test_a_record_with_no_operation_keeps_its_own_times(theatre):
    """تسكين لرنين أو كرسي أسنان — مفيش عملية، فالسجل بيشيل وقته."""
    from app.models import User
    from app.utils import sedation as sed

    rid = _open(theatre)
    with theatre["app"].app_context():
        doc = theatre["db"].session.get(User, theatre["ids"]["doctor"])
        sed.leave_theatre(_row(theatre, rid), "recovery", user=doc)
        theatre["db"].session.commit()
        row = _row(theatre, rid)

        assert row.left_theatre_at is not None
        assert row.theatre_out == row.left_theatre_at


# ------------------------------------------------- المراقبة ----
def test_the_physiological_status_is_the_childs_own_readings_tagged(theatre):
    """تالت استعمال لنفس الشكل بعد الدم والتقييد. تلات جداول منفصلة كانوا
    هيخلّوا شارت الطفل ناقص تلات مرات."""
    rid = _open(theatre)

    assert "status" in _missing(theatre, rid)

    _reading(theatre, rid)

    assert "status" not in _missing(theatre, rid)


def test_another_childs_reading_is_not_this_records_monitoring(theatre):
    from app.utils import sedation as sed

    rid = _open(theatre)
    other = _open(theatre, patient_id=theatre["ids"]["other_child"])
    _reading(theatre, other, patient_id=theatre["ids"]["other_child"])

    with theatre["app"].app_context():
        assert sed.readings(rid) == []
        assert len(sed.readings(other)) == 1


def test_nothing_is_unwatched_until_the_clinic_writes_the_interval(theatre):
    """`SAS.17` بيقول *regularly according to the approved guidelines* وما
    بيدّيش رقم — فالعيادة بتكتبه، والشاشة ساكتة لحد ما تكتبه."""
    from app.utils import sedation as sed

    _open(theatre, at=datetime.utcnow() - timedelta(hours=2))

    with theatre["app"].app_context():
        assert sed.interval_minutes() is None
        assert sed.unwatched() == []


def test_writing_the_interval_is_what_turns_it_on(theatre):
    from app.models import Setting
    from app.utils import sedation as sed

    _open(theatre, at=datetime.utcnow() - timedelta(hours=2))

    with theatre["app"].app_context():
        Setting.set(sed.INTERVAL_SETTING, "10")
        theatre["db"].session.commit()

        assert len(sed.unwatched()) == 1


def test_a_case_that_only_just_started_is_not_overdue(theatre):
    from app.models import Setting
    from app.utils import sedation as sed

    _open(theatre)

    with theatre["app"].app_context():
        Setting.set(sed.INTERVAL_SETTING, "10")
        theatre["db"].session.commit()

        assert sed.unwatched() == []


# ------------------------------------------------- الباقي ----
def test_a_part_save_does_not_wipe_what_it_did_not_send(theatre):
    """«الحقل مش موجود» و«الحقل اتفضّى» مش نفس الحاجة — ودي الغلطة اللي
    وقعت في تعليمات المتابعة قبل كده."""
    from app.utils import sedation as sed

    rid = _open(theatre)
    with theatre["app"].app_context():
        sed.describe(_row(theatre, rid), drugs="ميدازولام ٢ مجم")
        theatre["db"].session.commit()
        sed.describe(_row(theatre, rid), score="Ramsay 3")
        theatre["db"].session.commit()
        row = _row(theatre, rid)

    assert row.drugs == "ميدازولام ٢ مجم"
    assert row.score == "Ramsay 3"


def test_fluids_are_two_numbers_because_the_difference_is_the_point(theatre):
    from app.utils import sedation as sed

    rid = _open(theatre)
    with theatre["app"].app_context():
        sed.describe(_row(theatre, rid), fluids_in_ml=250, fluids_out_ml=80)
        theatre["db"].session.commit()
        row = _row(theatre, rid)

    assert (row.fluids_in_ml, row.fluids_out_ml) == (250, 80)
    assert "fluids" not in _missing(theatre, rid)


def test_a_finished_record_with_a_gap_is_on_the_short_list(theatre):
    from app.models import User
    from app.utils import sedation as sed

    rid = _open(theatre)
    with theatre["app"].app_context():
        doc = theatre["db"].session.get(User, theatre["ids"]["doctor"])
        sed.leave_theatre(_row(theatre, rid), "recovery", user=doc)
        sed.leave_recovery(_row(theatre, rid), "home", user=doc)
        theatre["db"].session.commit()

        short = sed.incomplete()

    assert [i["record"].id for i in short] == [rid]


def test_a_complete_record_is_not(theatre):
    from app.models import User
    from app.utils import sedation as sed

    rid = _open(theatre)
    _reading(theatre, rid)
    with theatre["app"].app_context():
        doc = theatre["db"].session.get(User, theatre["ids"]["doctor"])
        sed.describe(_row(theatre, rid), score="Ramsay 3", drugs="ميدازولام",
                     fluids_in_ml=100, unusual_event="مفيش")
        sed.leave_theatre(_row(theatre, rid), "recovery", condition="فايق",
                          user=doc)
        sed.leave_recovery(_row(theatre, rid), "home", score="Aldrete 10",
                           event="مفيش", user=doc)
        theatre["db"].session.commit()

        assert sed.missing(_row(theatre, rid)) == []
        assert sed.complete(_row(theatre, rid))
        assert sed.incomplete() == []


def test_another_childs_episode_is_not_this_ones(theatre):
    from app.utils import sedation as sed

    _open(theatre, patient_id=theatre["ids"]["other_child"])

    with theatre["app"].app_context():
        assert sed.for_patient(theatre["ids"]["child"]) == []
        assert len(sed.for_patient(theatre["ids"]["other_child"])) == 1
