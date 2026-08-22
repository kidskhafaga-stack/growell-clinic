"""The follow-up the doctor already booked, on the paper the parent takes home.

Asked for as: show the consultation appointment on the prescription if the
doctor has made one — and make it a tick, on or off per doctor.

Per doctor is what the template already is: a doctor is assigned one
(``User.rx_template_id``), so a switch on the template is a switch on the
doctor. That is why this is not a new concept, only a new flag.
"""
import os
import sys
from datetime import date, time, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

RX_DATE = date(2026, 8, 16)


def _template(clinic, **kw):
    from app.extensions import db
    from app.models import RxPrintTemplate

    flags = {f: f not in RxPrintTemplate.OFF_BY_DEFAULT
             for f in RxPrintTemplate.BOOLS}
    flags.update(kw)
    tpl = RxPrintTemplate(name="t", mode="white", page_size="A4", font_size=14,
                          margin_mm=12, top_offset_mm=0, **flags)
    db.session.add(tpl)
    db.session.flush()
    return tpl


def _rx(clinic):
    from app.extensions import db
    from app.models import Patient, Prescription, PrescriptionItem, User

    doc = User.query.filter_by(username="doc").first()
    kid = Patient.query.first()
    rx = Prescription(patient_id=kid.id, doctor_id=doc.id, rx_date=RX_DATE,
                      diagnosis="التهاب رئوي")
    db.session.add(rx)
    db.session.flush()
    db.session.add(PrescriptionItem(prescription_id=rx.id,
                                    drug_name="Augmentin", printed=True))
    return rx


def _book(clinic, when, at=time(9, 0), status="scheduled", doctor=None,
          reason=None):
    from app.extensions import db
    from app.models import Appointment, Patient, User

    kid = Patient.query.first()
    who = doctor or User.query.filter_by(username="doc").first()
    appt = Appointment(patient_id=kid.id, doctor_id=who.id, appt_date=when,
                       appt_time=at, status=status, reason=reason)
    db.session.add(appt)
    db.session.flush()
    return appt


def _page(clinic, build):
    """Build the world inside one app context, then fetch **the paper**.

    The printable sheet only, not the screen around it. The page's own chrome
    carries today's date in its bar, and a test asking "is this appointment on
    the paper?" by searching the whole document finds that instead on any day
    the two happen to be equal.

    Which is not hypothetical: this file books its follow-up for a fixed
    2026-08-23, and on 2026-08-23 the negative test — *the doctor switched it
    off, so it must not be printed* — went red against the date in the
    topbar. One day in the calendar, and it would have been read as a bug in
    the prescription.
    """
    from app.extensions import db

    with clinic["app"].app_context():
        rx, tpl = build()
        db.session.commit()
        rx_id, tpl_id = rx.id, tpl.id
    page = clinic["sign_in"]("boss").get(
        f"/prescriptions/{rx_id}?template={tpl_id}").data.decode()
    return _sheet(page)


def _sheet(page):
    """The printable area of a prescription page, or the whole thing if the
    marker ever moves — a helper that silently returns nothing would turn
    every assertion here green."""
    marker = 'id="rxPaper"'
    at = page.find(marker)
    assert at != -1, "the printable sheet is not on the page any more"
    return page[at:]


# --------------------------------------------------------------- it prints

def test_a_booked_follow_up_reaches_the_paper(clinic):
    def build():
        rx = _rx(clinic)
        _book(clinic, RX_DATE + timedelta(days=7))
        return rx, _template(clinic)

    page = _page(clinic, build)

    assert "2026-08-23" in page, "the booked follow-up is not on the paper"


def test_the_time_prints_too(clinic):
    """"Come back Tuesday" and "Tuesday at nine" are different instructions."""
    def build():
        rx = _rx(clinic)
        _book(clinic, RX_DATE + timedelta(days=3), at=time(14, 30))
        return rx, _template(clinic)

    page = _page(clinic, build)

    assert "14:30" in page, "the paper gives a day and no time"


def test_the_doctor_can_turn_it_off(clinic):
    """The tick that was asked for. A template is per doctor."""
    def build():
        rx = _rx(clinic)
        _book(clinic, RX_DATE + timedelta(days=7))
        return rx, _template(clinic, show_next_appointment=False)

    page = _page(clinic, build)

    assert "2026-08-23" not in page, \
        "the appointment printed on a template that switched it off"


def test_nothing_is_printed_when_nothing_is_booked(clinic):
    """A heading with nothing under it teaches people to stop reading them."""
    def build():
        return _rx(clinic), _template(clinic)

    page = _page(clinic, build)

    assert "الموعد القادم" not in page, \
        "an empty appointment heading printed with no appointment under it"


# ------------------------------------------------ which one it picks, and why

def test_a_cancelled_booking_is_not_a_date_to_come_back_on(clinic):
    def build():
        rx = _rx(clinic)
        _book(clinic, RX_DATE + timedelta(days=2), status="cancelled")
        _book(clinic, RX_DATE + timedelta(days=9))
        return rx, _template(clinic)

    page = _page(clinic, build)

    assert "2026-08-18" not in page, "a cancelled booking was printed"
    assert "2026-08-25" in page, "the real booking after it was skipped"


def test_a_booking_that_has_already_been_and_gone_is_not_the_next_one(clinic):
    def build():
        rx = _rx(clinic)
        _book(clinic, RX_DATE - timedelta(days=5))
        _book(clinic, RX_DATE + timedelta(days=5))
        return rx, _template(clinic)

    page = _page(clinic, build)

    assert "2026-08-11" not in page, "a past booking was printed as the next one"
    assert "2026-08-21" in page


def test_the_soonest_one_wins(clinic):
    """Inserted late-first, so insertion order and date order disagree."""
    def build():
        rx = _rx(clinic)
        _book(clinic, RX_DATE + timedelta(days=30))
        _book(clinic, RX_DATE + timedelta(days=4))
        _book(clinic, RX_DATE + timedelta(days=60))
        return rx, _template(clinic)

    page = _page(clinic, build)

    assert "2026-08-20" in page, "the soonest booking is not the one printed"
    assert "2026-09-15" not in page


def test_two_on_the_same_day_are_settled_by_the_clock(clinic):
    """Ordering on the date alone prints 4pm at a patient expected at 9.

    Inserted afternoon-first for the same reason as above.
    """
    def build():
        rx = _rx(clinic)
        day = RX_DATE + timedelta(days=6)
        _book(clinic, day, at=time(16, 0))
        _book(clinic, day, at=time(9, 15))
        return rx, _template(clinic)

    page = _page(clinic, build)

    assert "09:15" in page, "the later of two bookings on one day was printed"
    assert "16:00" not in page


# ------------------------------------------------------------- and elsewhere

def test_the_copy_the_family_opens_carries_it_too(clinic):
    """The one bug this feature cannot afford is two different papers."""
    from app.extensions import db

    with clinic["app"].app_context():
        rx = _rx(clinic)
        _book(clinic, RX_DATE + timedelta(days=7))
        _template(clinic)
        token = rx.share_link_token()
        db.session.commit()

    page = clinic["app"].test_client().get(
        f"/prescriptions/copy/{token}").data.decode()

    assert "2026-08-23" in page, \
        "the family's copy is missing the appointment the printed one has"


def test_the_test_print_shows_the_line(clinic):
    """A layout checked without this block is a layout that was not checked."""
    from app.extensions import db

    with clinic["app"].app_context():
        tpl = _template(clinic)
        db.session.commit()
        tpl_id = tpl.id

    page = clinic["sign_in"]("boss").get(
        f"/prescriptions/templates/{tpl_id}/test-print").data.decode()

    assert "الموعد القادم" in page, \
        "the test print cannot show whether this block fits"


def test_it_is_a_switch_on_the_template_screen(clinic):
    """Asked for explicitly: it has to be tickable."""
    from app.extensions import db

    with clinic["app"].app_context():
        _template(clinic)
        db.session.commit()

    page = clinic["sign_in"]("boss").get("/prescriptions/templates").data.decode()

    assert 'name="show_next_appointment"' in page, \
        "there is no tick for it on the template screen"


def test_saving_the_screen_keeps_the_answer(clinic):
    """A switch that cannot be turned off is not a switch."""
    from app.extensions import db
    from app.models import RxPrintTemplate

    with clinic["app"].app_context():
        tpl = _template(clinic)
        db.session.commit()
        tpl_id = tpl.id

    client = clinic["sign_in"]("boss")
    client.post(f"/prescriptions/templates/{tpl_id}/edit", data={"name": "t"})

    with clinic["app"].app_context():
        # The session outlives the request here, so it has to be told to look
        # again — otherwise this reads back the object it already had, and
        # passes whatever the route did or did not do.
        db.session.expire_all()
        assert db.session.get(RxPrintTemplate, tpl_id).show_next_appointment is False

    client.post(f"/prescriptions/templates/{tpl_id}/edit",
                data={"name": "t", "show_next_appointment": "1"})

    with clinic["app"].app_context():
        db.session.expire_all()
        assert db.session.get(RxPrintTemplate, tpl_id).show_next_appointment is True


def test_a_broken_booking_never_stops_a_prescription_printing(clinic):
    """This is one line on a page whose whole job is to print."""
    from app.utils import appointments

    def build():
        return _rx(clinic), _template(clinic)

    with clinic["app"].app_context():
        from app.extensions import db
        rx, tpl = build()
        db.session.commit()
        rx_id, tpl_id = rx.id, tpl.id

    def explode(*a, **k):
        raise RuntimeError("the appointments table is unreadable")

    original = appointments.next_booked
    appointments.next_booked = explode
    try:
        answer = clinic["sign_in"]("boss").get(
            f"/prescriptions/{rx_id}?template={tpl_id}")
        assert answer.status_code == 200, \
            "a failing booking lookup took the prescription down with it"
        assert "Augmentin" in answer.data.decode()
    finally:
        appointments.next_booked = original


@pytest.mark.parametrize("column", ["show_next_appointment"])
def test_the_new_column_is_in_the_additive_migration(clinic, column):
    """A new column on an existing table upgrades nobody unless it is listed."""
    from app.utils.schema import ADDITIONS

    assert any(t == "rx_print_templates" and c == column
               for t, c, _sql in ADDITIONS), \
        f"{column} will be missing on every clinic that already has a database"
