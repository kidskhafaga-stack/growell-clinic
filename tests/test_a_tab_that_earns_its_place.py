"""تبويب لازم يستاهل مكانه.

الملف فيه أربع تبويبات مشروطة، وجنب كل واحدة فيهم تعليق بيقول نفس الجملة:
تبويب مكتوب عليه حاجة الطفل عمره ما عملها هو **أثاث**. الأسنان والعمليات
والإقامات والدم وخطة الرعاية كلهم ماشيين على القاعدة دي.

**واتنين كانوا استثناء من غير سبب:** «فحوصات الأجهزة» و«التحاليل والأشعة»
كانوا بيترسموا دايماً، فعيادة طبيب واحد مالهاش إيكو ولا معمل كانت بتفتح كل
ملف على أوضتين فاضيتين. ودي اتلقت لما المالك سأل «الملف بيختلف بين عيادة
ومستشفى صح؟» — والإجابة الصح كانت: **بيختلف باللي الطفل عنده، مش باللي
المكان هو**، وهما الاتنين دول كانوا بيكسروا القاعدة دي.

`studies` عندها بند زيادة: عيادة عندها جهاز بتشوف التبويب قبل أول دراسة،
لأن ده المكان اللي أول واحدة بتتعمل منه.
"""
import os
import re
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


def _tabs(clinic, patient_id=None, who="doc"):
    body = clinic["sign_in"](who).get(
        f"/patients/{patient_id or clinic['ids']['child']}"
    ).get_data(as_text=True)
    return re.findall(r'data-tab="([a-z_]+)"', body)


@pytest.fixture()
def bare(clinic):
    """The conftest clinic, with the one visit's child kept as-is."""
    return clinic


def _plain_child(clinic):
    """A child with nothing on their file at all."""
    from app.models import Patient
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        child = Patient(patient_number="TAB-1", full_name="طفل نضيف",
                        gender="male", is_active=True,
                        date_of_birth=local_today() - timedelta(days=400))
        clinic["db"].session.add(child)
        clinic["db"].session.commit()
        return child.id


# ------------------------------------------------------ what every file has ----
def test_the_tabs_every_file_has_whatever_kind_of_place_this_is(bare):
    """A child is seen, measured, vaccinated, prescribed for, and things are
    filed about them. Those never depend on the building."""
    found = _tabs(bare, _plain_child(bare))

    assert found == ["overview", "family", "visits", "growth", "vaccinations",
                     "prescriptions", "documents"]


def test_a_clinic_with_no_machine_is_not_shown_a_device_tab(bare):
    assert "studies" not in _tabs(bare, _plain_child(bare))


def test_a_child_with_no_test_on_file_has_no_labs_tab(bare):
    assert "labs" not in _tabs(bare, _plain_child(bare))


# ------------------------------------------------------- when it is earned ----
def test_a_clinic_that_owns_a_machine_keeps_the_studies_tab(bare):
    """Before the first study, because that is where the first one is started
    from. A tab that appeared only after a study could never be used to make
    one."""
    from app.models.device import MedicalDevice

    child = _plain_child(bare)
    with bare["app"].app_context():
        bare["db"].session.add(MedicalDevice(name="إيكو", device_type="echo",
                                             is_active=True))
        bare["db"].session.commit()

    assert "studies" in _tabs(bare, child)


def test_a_machine_that_was_retired_does_not_keep_the_tab(bare):
    """A clinic that sold the echo is a clinic with no echo. `is_active` is
    what the devices screen sets, and reading rows regardless would leave the
    tab standing for ever after the machine left the building."""
    from app.models.device import MedicalDevice

    child = _plain_child(bare)
    with bare["app"].app_context():
        bare["db"].session.add(MedicalDevice(name="إيكو قديم",
                                             device_type="echo",
                                             is_active=False))
        bare["db"].session.commit()

    assert "studies" not in _tabs(bare, child)


def test_a_child_who_had_a_study_keeps_the_tab_without_a_machine(bare):
    """The record outlives the equipment: a study done two years ago on a
    machine the clinic no longer owns is still on this child's file, and the
    tab is the only way to it."""
    from app.models.device import DeviceStudy, MedicalDevice
    from app.utils.clock import local_today

    child = _plain_child(bare)
    with bare["app"].app_context():
        device = MedicalDevice(name="سبيروميتر", device_type="spirometry",
                               is_active=False)
        bare["db"].session.add(device)
        bare["db"].session.flush()
        bare["db"].session.add(DeviceStudy(patient_id=child,
                                           device_id=device.id,
                                           study_date=local_today()))
        bare["db"].session.commit()

    assert "studies" in _tabs(bare, child)


def test_a_test_on_the_file_earns_the_labs_tab(bare):
    from app.models import Visit, VisitInvestigation
    from app.utils.clock import local_today

    child = _plain_child(bare)
    with bare["app"].app_context():
        visit = Visit(patient_id=child, doctor_id=bare["ids"]["doctor"],
                      visit_date=local_today())
        bare["db"].session.add(visit)
        bare["db"].session.flush()
        bare["db"].session.add(VisitInvestigation(
            visit_id=visit.id, patient_id=child, name="صورة دم كاملة"))
        bare["db"].session.commit()

    assert "labs" in _tabs(bare, child)


def test_another_childs_test_does_not_earn_this_childs_labs_tab(bare):
    from app.models import Visit, VisitInvestigation
    from app.utils.clock import local_today

    mine = _plain_child(bare)
    theirs = bare["ids"]["child"]
    with bare["app"].app_context():
        visit = Visit(patient_id=theirs, doctor_id=bare["ids"]["doctor"],
                      visit_date=local_today())
        bare["db"].session.add(visit)
        bare["db"].session.flush()
        bare["db"].session.add(VisitInvestigation(
            visit_id=visit.id, patient_id=theirs, name="صورة دم"))
        bare["db"].session.commit()

    assert "labs" not in _tabs(bare, mine)
    assert "labs" in _tabs(bare, theirs)


# ------------------------------------- the file varies by data, not by place ----
def test_switching_every_ward_module_on_changes_nothing_by_itself(bare):
    """**The answer to «الملف بيختلف بين عيادة ومستشفى صح؟»**

    It varies by what the child has, not by what the place is — and that is
    the design, not an oversight. A hospital that has just registered a child
    has the same file as a clinic, because nothing has happened to them yet.
    """
    from app.models import Setting

    child = _plain_child(bare)
    before = _tabs(bare, child)
    with bare["app"].app_context():
        for module in ("beds", "ward", "icu", "nicu", "emergency", "theatres",
                       "labs", "observations", "panels", "pharmacy"):
            Setting.set(f"mod_enabled:{module}", "1")
        bare["db"].session.commit()

    assert _tabs(bare, child) == before


def test_the_repeated_observations_are_not_on_a_clinic_file(bare):
    """`Observation` is the ward's monitoring — a person sitting with a child.
    `VitalSigns` is one reading taken as they come in, and that is the clinic's.
    The file has never carried the first, and this says so out loud so that a
    later change cannot quietly put it there.
    """
    body = bare["sign_in"]("doc").get(
        f"/patients/{_plain_child(bare)}").get_data(as_text=True)

    assert "data-observation" not in body
    assert "observation_orders" not in body


def test_the_device_question_costs_one_query_and_not_one_per_file_read(bare):
    """Asked once per request. A clinic with no devices is the common case and
    the answer is an EXISTS, not a catalogue."""
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    child = _plain_child(bare)
    seen = []

    def record(conn, cursor, statement, params, context, many):
        if "medical_devices" in statement:
            seen.append(statement)

    client = bare["sign_in"]("doc")
    event.listen(Engine, "before_cursor_execute", record)
    try:
        client.get(f"/patients/{child}")
    finally:
        event.remove(Engine, "before_cursor_execute", record)
    assert len(seen) <= 2, f"{len(seen)} device queries for one file"
