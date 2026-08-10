"""A note that a family does not pay — written carefully, because it is one.

Reception, a doctor or the office can record that a family does not pay or pays
only after chasing. It shows where the decisions are made and comes off when
the behaviour changes.

Everything unusual here exists because **this is an accusation about a named
person, written by a colleague and read by the whole staff**:

* it is *cleared*, never deleted, so a family who was wronged has something to
  point at and a flag cannot be put back on a bad morning with no trace;
* raising and clearing are different permissions, in both directions;
* ``block`` stops a booking only until somebody with financial authority
  decides — and that decision is recorded with their name;
* and it never, ever prints.

The last one is the test that matters most. A family reading "does not pay" on
their own receipt is the single outcome here that cannot be undone.
"""
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


def _raise(clinic, who="desk", level="warn", reason="متأخر في الدفع من زيارتين"):
    client = clinic["sign_in"](who)
    response = client.post(
        f"/patients/{clinic['ids']['child']}/flag",
        data={"level": level, "reason": reason}, follow_redirects=True)
    return client, response


def _flag(clinic):
    from app.utils.patient_flags import active
    return active(clinic["ids"]["child"])


# --- raising and clearing --------------------------------------------------

def test_the_desk_can_record_it(clinic):
    """The people who meet the problem are the people who can write it down."""
    _raise(clinic)
    with clinic["app"].app_context():
        flag = _flag(clinic)
        assert flag is not None
        assert flag.level == "warn"
        assert "متأخر" in flag.reason
        assert flag.raised_by is not None, "nobody's name is on it"


def test_a_flag_with_no_reason_is_refused(clinic):
    """A note nobody can judge, argue with, or fairly clear."""
    _raise(clinic, reason="   ")
    with clinic["app"].app_context():
        assert _flag(clinic) is None


def test_the_desk_cannot_take_it_off_again(clinic):
    """Raising and clearing are different permissions, on purpose.

    Both directions matter: it stops a flag being lifted quietly by whoever
    put it there, and it stops one being lifted by somebody who does not know
    whether the money ever arrived.
    """
    desk, _ = _raise(clinic)
    desk.post(f"/patients/{clinic['ids']['child']}/flag/clear",
              data={"clear_reason": "خلاص"}, follow_redirects=True)

    with clinic["app"].app_context():
        assert _flag(clinic) is not None, "reception cleared its own flag"


@pytest.mark.parametrize("who", ["boss", "acct"])
def test_financial_authority_can_clear_it(clinic, who):
    """Admin, or whoever holds finance_manage."""
    _raise(clinic)
    clinic["sign_in"](who).post(
        f"/patients/{clinic['ids']['child']}/flag/clear",
        data={"clear_reason": "دفع المتأخر"}, follow_redirects=True)

    with clinic["app"].app_context():
        assert _flag(clinic) is None


def test_clearing_keeps_the_row_and_records_who_and_why(clinic):
    """A note like this that can vanish without a trace is one that can be put
    back on a bad morning."""
    _raise(clinic)
    clinic["sign_in"]("boss").post(
        f"/patients/{clinic['ids']['child']}/flag/clear",
        data={"clear_reason": "دفع المتأخر بالكامل"}, follow_redirects=True)

    with clinic["app"].app_context():
        from app.utils.patient_flags import history
        rows = history(clinic["ids"]["child"])
        assert len(rows) == 1, "the flag was deleted rather than cleared"
        assert rows[0].cleared_at is not None
        assert rows[0].cleared_by is not None
        assert "دفع المتأخر" in rows[0].clear_reason


def test_raising_twice_does_not_stack_two_stories(clinic):
    """Two open flags mean two accounts of the same family and no way to tell
    which is current."""
    _raise(clinic, reason="أول ملاحظة")
    _raise(clinic, level="block", reason="بقى متأخر ٣ شهور")

    with clinic["app"].app_context():
        from app.models import PatientFlag
        open_rows = PatientFlag.query.filter_by(
            patient_id=clinic["ids"]["child"], cleared_at=None).all()
        assert len(open_rows) == 1
        assert open_rows[0].level == "block", "the escalation was lost"


# --- what each level actually does ----------------------------------------

def test_a_warning_does_not_stop_anything(clinic):
    """A sick child is not turned away over their father's account.

    The warning is there so a person decides with the facts, not so a screen
    decides for them.
    """
    from app.utils.patient_flags import blocks_booking

    _raise(clinic, level="warn")
    with clinic["app"].app_context():
        assert blocks_booking(clinic["ids"]["child"]) is False


def test_a_block_stops_the_booking(clinic):
    from datetime import time, timedelta

    from app.utils.clock import local_today

    with clinic["app"].app_context():
        from app.models import DoctorSchedule
        db = clinic["db"]
        for weekday in range(7):
            db.session.add(DoctorSchedule(
                doctor_id=clinic["ids"]["doctor"], weekday=weekday,
                start_time=time(9, 0), end_time=time(17, 0),
                slot_minutes=30, is_active=True))
        db.session.commit()
        when = local_today() + timedelta(days=3)

    desk, _ = _raise(clinic, level="block", reason="مديون من سنة")
    desk.post("/appointments/new", data={
        "patient_id": clinic["ids"]["child"],
        "doctor_id": clinic["ids"]["doctor"],
        "appt_date": when.isoformat(), "appt_time": "10:00",
        "appt_type": "new", "reason": "كشف",
    }, follow_redirects=True)

    with clinic["app"].app_context():
        from app.models import Appointment
        assert Appointment.query.filter_by(appt_date=when).count() == 0, (
            "a blocked file was booked anyway")


def test_the_block_is_lifted_by_a_person_not_worked_around(clinic):
    """The point is that somebody who can decide, decides — and is named.

    Reception ticking the override themselves would make the block a
    formality; an admin ticking it is the clinic making a choice.
    """
    from datetime import time, timedelta

    from app.utils.clock import local_today

    with clinic["app"].app_context():
        from app.models import DoctorSchedule
        db = clinic["db"]
        for weekday in range(7):
            db.session.add(DoctorSchedule(
                doctor_id=clinic["ids"]["doctor"], weekday=weekday,
                start_time=time(9, 0), end_time=time(17, 0),
                slot_minutes=30, is_active=True))
        db.session.commit()
        when = local_today() + timedelta(days=4)

    _raise(clinic, level="block", reason="مديون")
    payload = {
        "patient_id": clinic["ids"]["child"],
        "doctor_id": clinic["ids"]["doctor"],
        "appt_date": when.isoformat(), "appt_time": "11:00",
        "appt_type": "new", "reason": "كشف", "flag_override": "1",
    }

    # Reception ticking it themselves changes nothing.
    clinic["sign_in"]("desk").post("/appointments/new", data=payload,
                                   follow_redirects=True)
    with clinic["app"].app_context():
        from app.models import Appointment
        assert Appointment.query.filter_by(appt_date=when).count() == 0

    # The admin's override goes through, and is recorded.
    clinic["sign_in"]("boss").post("/appointments/new", data=payload,
                                   follow_redirects=True)
    with clinic["app"].app_context():
        from app.models import ActivityLog, Appointment
        assert Appointment.query.filter_by(appt_date=when).count() == 1
        assert ActivityLog.query.filter_by(
            action="appointment.flag_override").count() == 1, (
            "the override went unrecorded")


# --- the one that cannot be undone -----------------------------------------

def test_it_never_reaches_anything_the_family_is_handed(clinic):
    """The single outcome here that cannot be taken back.

    Asserted against the print stylesheet as well as the markup: the banner
    carries ``no-print``, and ``no-print`` is what print.css hides. Checking
    only the class would pass if the rule were ever renamed.
    """
    profile = open("app/templates/patients/profile.html", encoding="utf-8").read()
    banner = profile.split("payment_flag")[1][:400]
    assert "no-print" in banner, "the payment flag is not marked no-print"

    css = open("app/static/css/print.css", encoding="utf-8").read()
    # The rule, not a comment mentioning it.
    rules = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    hidden = re.search(r"([^{}]*\.no-print[^{}]*)\{([^}]*)\}", rules)
    assert hidden is not None, "print.css no longer hides .no-print"
    assert "display" in hidden.group(2) and "none" in hidden.group(2)


def test_the_family_facing_documents_do_not_carry_it(clinic):
    """Invoice, receipt and prescription templates must not mention it at all.

    A class can be overridden; not being in the template cannot.
    """
    import pathlib

    root = pathlib.Path("app/templates")
    family_facing = list(root.glob("finance/*receipt*.html")) + \
        list(root.glob("finance/invoice_print*.html")) + \
        list(root.glob("prescriptions/*print*.html")) + \
        list(root.glob("prescriptions/public*.html"))
    offenders = [str(p) for p in family_facing
                 if "payment_flag" in p.read_text(encoding="utf-8")]
    assert offenders == [], f"the payment flag appears on: {offenders}"
