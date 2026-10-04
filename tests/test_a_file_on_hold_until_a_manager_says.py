"""A file on hold until the finance manager or the manager on duty says so.

Asked as *«وقف حالة من الحجز او التعامل عليها لحين وجود موافقة مدير المالى
او المدير المناوب فى المستشفى عندها مشكلة فى الحساب عندها مشكلة مع الاهل
ويبقى تنبيه»*.

**Two gaps found on the way.** The financial note already had a «hold» level
that stopped a booking — but nothing on any screen could *raise* one (the
route was listed as an orphan writer), and the booking accepted a manager's
«go ahead» that no screen could send. What is held here:

* a note is raised from the patient file, with why: the account, or the
  family;
* a hold stops a booking and a planned admission; the finance manager or the
  manager on duty — a new capability — lets it go ahead, by name;
* **an emergency is never held** — a child sent up from it is admitted with
  the hold shown, decree 1063/2014;
* the hold shows on the stay, the emergency and the till, and the managers
  have a list and a bell for the files on hold that are here today.
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from app.utils.clock import local_today  # noqa: E402


@pytest.fixture()
def ward(clinic):
    from app.models import Setting
    from app.models.place import Bed, Space, Unit

    with clinic["app"].app_context():
        db = clinic["db"]
        Setting.set("mod_enabled:beds", "1")
        unit = Unit(name="الداخلي", kind="ward")
        db.session.add(unit)
        db.session.flush()
        space = Space(unit_id=unit.id, name="غرفة", kind="room")
        db.session.add(space)
        db.session.flush()
        bed = Bed(space_id=space.id, name="سرير", kind="bed")
        db.session.add(bed)
        db.session.commit()
        clinic["ids"]["bed"] = bed.id
    return clinic


def _hold(c, level="block", kind="family", who="desk"):
    return c["sign_in"](who).post(f"/patients/{c['ids']['child']}/flag",
                                  data={"level": level, "kind": kind,
                                        "reason": "الأهل رافضين يوقّعوا"})


def _admitted(c):
    from app.models import Admission

    with c["app"].app_context():
        return Admission.query.filter_by(patient_id=c["ids"]["child"]).count()


def _admit(c, who="boss", **extra):
    return c["sign_in"](who).post(f"/beds/admit/{c['ids']['child']}",
                                  data=dict(bed_id=c["ids"]["bed"], **extra))


def test_a_note_is_raised_from_the_file_with_its_reason(ward):
    from app.models import PatientFlag

    page = ward["sign_in"]("desk").get(f"/patients/{ward['ids']['child']}").get_data(as_text=True)
    assert "data-flag-raise" in page
    _hold(ward)
    with ward["app"].app_context():
        row = PatientFlag.query.one()
        assert (row.level, row.kind) == ("block", "family")


def _night_manager(c):
    """A nurse who carries the night's duty — granted the capability, not
    made an admin or an accountant."""
    from app.models import User
    from app.models.user_capability import UserCapability

    with c["app"].app_context():
        db = c["db"]
        night = User(username="night", full_name="المدير المناوب", role="nursing",
                     is_active=True)
        night.set_password("secret")
        db.session.add(night)
        db.session.flush()
        db.session.add(UserCapability(user_id=night.id, capability="duty_manager",
                                      granted_by=c["ids"]["admin"]))
        db.session.commit()
        return night.id


def test_a_hold_stops_a_planned_admission_until_a_manager_says(ward):
    from app.models import ActivityLog

    _hold(ward)
    _admit(ward, who="desk", flag_override="1")
    assert _admitted(ward) == 0, "a desk without the authority went past the hold"
    _admit(ward)
    assert _admitted(ward) == 0, "admitted without anyone saying go ahead"
    _admit(ward, flag_override="1")
    assert _admitted(ward) == 1
    with ward["app"].app_context():
        assert ActivityLog.query.filter_by(action="admission.flag_override").count() == 1


def test_the_manager_on_duty_may_say_go_ahead(ward):
    from app.models import User
    from app.models.permissions import CAPABILITIES
    from app.utils import patient_flags as flags

    assert "duty_manager" in CAPABILITIES
    night = _night_manager(ward)
    with ward["app"].app_context():
        assert flags.can_clear(ward["db"].session.get(User, night)) is True
        nurse = User.query.filter_by(role="nursing").filter(User.id != night).first()
        assert nurse is None or flags.can_clear(nurse) is False
    page = ward["sign_in"]("night").get("/beds/").get_data(as_text=True)
    assert "data-admit-override" in page
    desk = ward["sign_in"]("desk").get("/beds/").get_data(as_text=True)
    assert "data-admit-override" not in desk


def test_an_emergency_is_never_held(ward):
    from app.models import Patient
    from app.utils import emergency as util

    _hold(ward)
    with ward["app"].app_context():
        util.arrive(ward["db"].session.get(Patient, ward["ids"]["child"]), at=datetime.utcnow())
        ward["db"].session.commit()
    _admit(ward, who="boss")
    assert _admitted(ward) == 1, "a child from the emergency waited for a manager"


def test_the_hold_shows_on_the_stay_the_emergency_and_the_till(ward):
    from app.models import Admission, EmergencyVisit, Patient, Setting
    from app.utils import emergency as util

    with ward["app"].app_context():
        Setting.set("mod_enabled:emergency", "1")
        ward["db"].session.commit()
    _hold(ward, level="warn", kind="account")
    _admit(ward)
    boss = ward["sign_in"]("boss")
    with ward["app"].app_context():
        stay = Admission.query.one().id
        util.arrive(ward["db"].session.get(Patient, ward["ids"]["child"]), at=datetime.utcnow())
        ward["db"].session.commit()
        attendance = EmergencyVisit.query.one().id
    assert 'data-hold-banner="warn"' in boss.get(f"/beds/admission/{stay}").get_data(as_text=True)
    er = boss.get(f"/emergency/attendance/{attendance}").get_data(as_text=True)
    assert 'data-hold-banner="warn"' in er
    till = boss.get(f"/finance/collect/{ward['ids']['child']}").get_data(as_text=True)
    assert 'data-hold-banner="warn"' in till


def test_the_booking_offers_the_go_ahead_to_whoever_may_give_it(ward):
    from datetime import time, timedelta

    from app.models import Appointment, DoctorSchedule

    with ward["app"].app_context():
        for weekday in range(7):
            ward["db"].session.add(DoctorSchedule(
                doctor_id=ward["ids"]["doctor"], weekday=weekday, start_time=time(9, 0),
                end_time=time(17, 0), slot_minutes=30, is_active=True))
        ward["db"].session.commit()
    _hold(ward)
    boss = ward["sign_in"]("boss")
    form = {"patient_id": ward["ids"]["child"], "doctor_id": ward["ids"]["doctor"],
            "appt_date": (local_today() + timedelta(days=1)).isoformat(),
            "appt_time": "10:00"}
    page = boss.post("/appointments/new", data=form).get_data(as_text=True)
    assert "data-flag-override" in page
    desk = ward["sign_in"]("desk").post("/appointments/new", data=form).get_data(as_text=True)
    assert "data-flag-override" not in desk
    with ward["app"].app_context():
        assert Appointment.query.count() == 0
    boss.post("/appointments/new", data=dict(form, flag_override="1"))
    with ward["app"].app_context():
        assert Appointment.query.count() == 1


def test_the_managers_list_and_bell(ward):
    from app.utils import patient_flags as flags

    _hold(ward)
    _admit(ward, flag_override="1")
    boss = ward["sign_in"]("boss")
    page = boss.get("/patients/holds").get_data(as_text=True)
    assert f'data-hold="{ward["ids"]["child"]}"' in page and "data-hold-today" in page
    with ward["app"].app_context():
        assert flags.held_today() == {ward["ids"]["child"]}
    assert "data-holds-link" in boss.get("/patients/").get_data(as_text=True)
