"""الديسك: التسجيل السريع لخدمة واحدة، والبحث في الدراسات، والفئات العمرية،
وأسماء الأقسام بلغة الشاشة.

اتطلب كده: «لو كذا خدمة او اخد خدمة واحدة ومشى وجه تانى لازم استكمال البيانات
ويطلعله بوب اب لاستكمال البيانات وحفظ» — و«ممكن البحث يا اسم المريض او رقم
التليفون ونوحد طريقة البحث» — و«الفئات العمرية الى كنت عاملها بمفتاحها» —
و«ظهور العربي فى الشاشة الانجليزي ده بيبقى مش حلو».

* **مقفولة لحد ما العيادة تشغّلها** — التحديث ما يغيّرش حاجة؛
* خدمة واحدة بالتسجيل السريع مقبولة؛ قبل التانية (حجز تاني، فاتورة تانية،
  أكتر من خدمة في فاتورة، أو دراسة) شباك يسأل عن الناقص بس؛
* **عمرها ما بتوقف طفل في الطوارئ أو محجوز**؛
* الدراسات: رقم الملف أو الاسم أو التليفون، والتسجيل السريع جنبها؛
* اللوحة الطبية بفئات العيادة ومفتاحها، وبـ«كل الملفات»؛
* اسم القسم في الشاشة الإنجليزي بالإنجليزي.
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from app.utils.clock import local_today  # noqa: E402


@pytest.fixture()
def desk(clinic):
    """A child registered the quick way — name, sex, birth date, nothing more."""
    from app.models import Patient, Setting

    with clinic["app"].app_context():
        Setting.set("mod_enabled:appointments", "1")
        kid = Patient(patient_number="Q1", full_name="طفل سريع", gender="male",
                      date_of_birth=date(2023, 5, 1), is_active=True)
        clinic["db"].session.add(kid)
        clinic["db"].session.commit()
        clinic["ids"]["quick"] = kid.id
    return clinic


def _policy(c, on=True):
    from app.models import Setting

    with c["app"].app_context():
        Setting.set("patient_basics_one_service", "1" if on else "0")
        c["db"].session.commit()


def _visit(c, days_ago):
    from app.models import Visit

    with c["app"].app_context():
        c["db"].session.add(Visit(patient_id=c["ids"]["quick"], doctor_id=c["ids"]["doctor"],
                                  visit_date=local_today() - timedelta(days=days_ago)))
        c["db"].session.commit()


def _needs(c, services_now=1):
    from app.models import Patient
    from app.utils import patient_basics as basics

    with c["app"].app_context():
        return basics.needs_completion(c["db"].session.get(Patient, c["ids"]["quick"]),
                                       services_now=services_now)


# ------------------------------------------------------------ the policy --
def test_off_until_the_clinic_switches_it_on(desk):
    _visit(desk, 10)
    assert _needs(desk) == [], "an update changes nothing"
    _policy(desk)
    assert _needs(desk) == ["phone", "guardian"]


def test_one_service_is_enough_the_second_asks(desk):
    _policy(desk)
    assert _needs(desk) == [], "no service yet"
    _visit(desk, 0)
    assert _needs(desk) == [], "today's first visit is the one service"
    assert _needs(desk, services_now=2) == ["phone", "guardian"], "two on one bill"
    _visit(desk, 7)
    assert _needs(desk) == ["phone", "guardian"], "came back another day"


def test_a_child_in_the_emergency_department_is_never_held(desk):
    from app.models.emergency_visit import EmergencyVisit

    _policy(desk)
    _visit(desk, 7)
    with desk["app"].app_context():
        desk["db"].session.add(EmergencyVisit(patient_id=desk["ids"]["quick"]))
        desk["db"].session.commit()
    assert _needs(desk) == []


def test_the_window_writes_only_what_is_missing(desk):
    from app.models import Patient

    _policy(desk)
    _visit(desk, 7)
    boss = desk["sign_in"]()
    page = boss.get(f"/patients/{desk['ids']['quick']}/complete?next=/visits/").get_data(as_text=True)
    assert "data-complete-window" in page and 'name="guardian_name"' in page
    assert 'name="national_id"' not in page, "only what this clinic asks for"
    boss.post(f"/patients/{desk['ids']['quick']}/complete",
              data={"next": "/visits/", "guardian_name": "أبو الطفل", "phone": "12"})
    with desk["app"].app_context():
        assert desk["db"].session.get(Patient, desk["ids"]["quick"]).family is None, "bad phone"
    got = boss.post(f"/patients/{desk['ids']['quick']}/complete",
                    data={"next": "//evil.example", "guardian_name": "أبو الطفل",
                          "guardian_relation": "father", "phone": "01001234567"})
    assert "evil.example" not in got.headers["Location"]
    with desk["app"].app_context():
        kid = desk["db"].session.get(Patient, desk["ids"]["quick"])
        assert kid.primary_guardian.full_name == "أبو الطفل"
        assert kid.contact_phone == "01001234567"
    assert _needs(desk) == []


def test_the_booking_waits_for_the_window_and_keeps_what_was_typed(desk):
    from datetime import time

    from app.models import Appointment, DoctorSchedule

    with desk["app"].app_context():
        for weekday in range(7):
            desk["db"].session.add(DoctorSchedule(
                doctor_id=desk["ids"]["doctor"], weekday=weekday, start_time=time(9, 0),
                end_time=time(17, 0), slot_minutes=30, is_active=True))
        desk["db"].session.commit()
    _policy(desk)
    _visit(desk, 7)
    form = {"patient_id": str(desk["ids"]["quick"]), "doctor_id": str(desk["ids"]["doctor"]),
            "appt_date": (local_today() + timedelta(days=1)).isoformat(),
            "appt_time": "10:00", "appt_type": "checkup"}
    page = desk["sign_in"]("desk").post("/appointments/new", data=form).get_data(as_text=True)
    assert "data-complete-window" in page
    with desk["app"].app_context():
        assert Appointment.query.count() == 0
    got = desk["sign_in"]("desk").post(
        f"/patients/{desk['ids']['quick']}/complete.json",
        json={"guardian_name": "الأم", "guardian_relation": "mother", "phone": "01112223334"})
    assert got.get_json() == {"ok": True, "missing": []}
    desk["sign_in"]("desk").post("/appointments/new", data=form)
    with desk["app"].app_context():
        assert Appointment.query.count() == 1


def test_a_study_asks_first_and_the_search_finds_by_name_or_phone(desk):
    from app.models import Family, Parent

    with desk["app"].app_context():
        fam = Family(family_name="عيلة")
        desk["db"].session.add(fam)
        desk["db"].session.flush()
        desk["db"].session.add(Parent(family_id=fam.id, relation="mother", full_name="ماما",
                                      phone="01009998887", is_primary_contact=True))
        from app.models import Patient

        desk["db"].session.get(Patient, desk["ids"]["quick"]).family_id = fam.id
        desk["db"].session.commit()
    doc = desk["sign_in"]("doc")
    by_phone = doc.get("/visits/studies/start?q=01009998887")
    assert f"/visits/studies/new/{desk['ids']['quick']}" in by_phone.headers["Location"]
    by_name = doc.get("/visits/studies/start?q=طفل سريع")
    assert f"/visits/studies/new/{desk['ids']['quick']}" in by_name.headers["Location"]
    none = doc.get("/visits/studies/start?q=مفيش حد كده", follow_redirects=True).get_data(as_text=True)
    assert "data-device-quick" in none
    # The policy: a file that already had a service and lacks its basics.
    with desk["app"].app_context():
        from app.models import Patient

        kid = desk["db"].session.get(Patient, desk["ids"]["quick"])
        kid.family_id = None
        desk["db"].session.commit()
    _policy(desk)
    _visit(desk, 7)
    gate = doc.get(f"/visits/studies/new/{desk['ids']['quick']}")
    assert "/complete" in gate.headers["Location"]


def test_a_quick_registration_from_the_studies_screen(desk):
    from app.models import Patient

    got = desk["sign_in"]("doc").post("/visits/studies/quick", data={
        "full_name": "طفل الإيكو", "gender": "female", "date_of_birth": "2024-02-02"})
    with desk["app"].app_context():
        kid = Patient.query.filter_by(full_name="طفل الإيكو").one()
        assert f"/visits/studies/new/{kid.id}" in got.headers["Location"]


# ------------------------------------------------------- the age groups --
def test_the_medical_board_uses_the_clinic_s_age_groups_and_their_key(desk):
    from app.utils import med_board

    _visit(desk, 0)
    with desk["app"].app_context():
        keys = [row[0] for row in med_board.ages(local_today(), local_today())]
        assert keys == ["newborn", "infant", "toddler", "school", "adolescent", "over"]
        roster = dict((row[0], sum(row[1:])) for row in
                      med_board.ages(local_today(), local_today(), roster=True))
        assert sum(roster.values()) >= 2, "every active file"
    page = desk["sign_in"]().get("/reports/medical?preset=30").get_data(as_text=True)
    assert "data-ages-key" in page and "من شهر حتى سنتين" in page
    assert "data-ages-all" in page
    page = desk["sign_in"]().get("/reports/medical?preset=30&ages=all").get_data(as_text=True)
    assert "كل ملفات المرضى" in page


def test_a_unit_is_named_in_the_screen_s_language(desk):
    from app.models import Setting
    from app.models.place import Unit

    with desk["app"].app_context():
        Setting.set("mod_enabled:beds", "1")
        desk["db"].session.add(Unit(name="الرعاية النهارية", name_en="Day care", kind="ward"))
        desk["db"].session.commit()
    boss = desk["sign_in"]()
    boss.get("/lang/en")
    page = boss.get("/reports/medical?preset=30").get_data(as_text=True)
    assert "Day care" in page and "الرعاية النهارية" not in page


def test_the_till_asks_before_a_second_bill(desk):
    from app.models import Invoice
    from app.utils import accounting as acct

    with desk["app"].app_context():
        acct.ensure_seeded()
        desk["db"].session.add(Invoice(patient_id=desk["ids"]["quick"], invoice_number="OLD-1",
                                       created_by=desk["ids"]["admin"]))
        desk["db"].session.commit()
    boss = desk["sign_in"]()
    assert "data-complete-window" not in boss.get(
        f"/finance/collect/{desk['ids']['quick']}").get_data(as_text=True), "off"
    _policy(desk)
    page = boss.get(f"/finance/collect/{desk['ids']['quick']}").get_data(as_text=True)
    assert "data-complete-window" in page
    got = boss.post(f"/finance/collect/{desk['ids']['quick']}", data={
        "line_desc": ["كشف"], "line_price": ["100"], "line_qty": ["1"]})
    assert got.status_code == 302 and "complete=1" in got.headers["Location"]
    with desk["app"].app_context():
        assert Invoice.query.count() == 1, "nothing billed while the window waits"
