"""What reception does, the doctor sees — without anyone pressing refresh.

The screens stay current by asking every few seconds whether anything they
show has changed, and reloading only when it has. That works exactly as far
as the fingerprint reaches: the doctor's board covered the appointments and
nothing else, while the board itself also shows **who has paid**. Reception
could raise the bill and take the money and the doctor's screen went on
saying "not billed".

A screen that looks live is worse than one that plainly isn't — nobody
refreshes a screen they believe.

The other half of the test is the quiet: a fingerprint that changes when
nothing happened reloads the doctor's page under their hands every few
seconds, which is how a clinic turns the feature off.
"""
import os
import sys
from datetime import date, time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# One clock. The program books, bills and lists "today" with
# ``local_today``; a test that builds or asserts with ``date.today``
# sits on a different day whenever the server's zone and the clinic's
# disagree — on a UTC server and a Cairo clinic, every night after
# 22:00. These twenty failed on the hour rather than on a change.
from app.utils.clock import local_today  # noqa: E402


import pytest  # noqa: E402


@pytest.fixture()
def board(clinic):
    """A booked patient on today's board, and reception signed in."""
    with clinic["app"].app_context():
        from app.models import Appointment

        appt = Appointment(patient_id=clinic["ids"]["child"],
                           doctor_id=clinic["ids"]["doctor"],
                           appt_date=local_today(), appt_time=time(10, 0),
                           status="scheduled", appt_type="consultation")
        clinic["db"].session.add(appt)
        clinic["db"].session.commit()
        clinic["ids"]["appt"] = appt.id

    desk = clinic["sign_in"]("boss")
    desk.post("/finance/shift/open", data={"opening_float": "0"},
              follow_redirects=True)
    clinic["desk"] = desk
    return clinic


def _fingerprint(board):
    resp = board["desk"].get(
        f"/appointments/poll?doctor_id={board['ids']['doctor']}")
    assert resp.status_code == 200
    return resp.get_json()["fp"]


def _bill(board, price="200", patient_id=None):
    """Raise a bill on the collection screen — the only one there is now."""
    pid = patient_id or board["ids"]["child"]
    return board["desk"].post(f"/finance/collect/{pid}", data={
        "doctor_id": board["ids"]["doctor"], "discount_id": "none",
        "line_service_id": [str(board["ids"]["exam"])],
        "line_desc": ["كشف"], "line_price": [price], "line_qty": ["1"],
        "line_no_commission": ["0"], "line_brand_id": [""],
        "line_dose_id": [""], "line_dose_number": [""], "line_vs_id": [""],
    }, follow_redirects=True)


def _invoice_id(board):
    from app.models import Invoice

    with board["app"].app_context():
        return Invoice.query.order_by(Invoice.id.desc()).first().id


# ------------------------------------------- the queue reaches the doctor --
def test_marking_the_patient_arrived_reaches_the_doctor(board):
    before = _fingerprint(board)
    board["desk"].post(f"/appointments/{board['ids']['appt']}/status",
                       data={"status": "waiting"}, follow_redirects=True)
    assert _fingerprint(board) != before


def test_a_new_booking_reaches_the_doctor(board):
    from app.models import Appointment

    before = _fingerprint(board)
    with board["app"].app_context():
        board["db"].session.add(Appointment(
            patient_id=board["ids"]["child"], doctor_id=board["ids"]["doctor"],
            appt_date=local_today(), appt_time=time(11, 0), status="scheduled",
            appt_type="consultation"))
        board["db"].session.commit()
    assert _fingerprint(board) != before


# ------------------------------------------- the money reaches him as well --
def test_raising_the_bill_reaches_the_doctor(board):
    """The board says who has been billed. An invoice touches no appointment
    row, so this was invisible to a fingerprint made of appointments."""
    before = _fingerprint(board)
    _bill(board)
    assert _fingerprint(board) != before, "the doctor's board still says unbilled"


def test_collecting_the_money_reaches_the_doctor(board):
    before_bill = _fingerprint(board)
    _bill(board)
    after_bill = _fingerprint(board)
    assert after_bill != before_bill

    board["desk"].post(f"/finance/invoices/{_invoice_id(board)}/payment",
                       data={"amount": "200", "method": "cash"},
                       follow_redirects=True)
    assert _fingerprint(board) != after_bill


def test_a_second_part_payment_reaches_him_too(board):
    """The hard case: 100 then 100 on a 200 bill. The invoice is "partial"
    after the first and only turns "paid" on the second — so a fingerprint
    built from invoice status alone would miss a payment entirely."""
    _bill(board)
    invoice = _invoice_id(board)
    board["desk"].post(f"/finance/invoices/{invoice}/payment",
                       data={"amount": "60", "method": "cash"},
                       follow_redirects=True)
    after_first = _fingerprint(board)

    board["desk"].post(f"/finance/invoices/{invoice}/payment",
                       data={"amount": "60", "method": "cash"},
                       follow_redirects=True)
    assert _fingerprint(board) != after_first, "a top-up went unnoticed"


def test_a_refund_reaches_him(board):
    _bill(board)
    invoice = _invoice_id(board)
    board["desk"].post(f"/finance/invoices/{invoice}/payment",
                       data={"amount": "200", "method": "cash"},
                       follow_redirects=True)
    before = _fingerprint(board)
    board["desk"].post(f"/finance/invoices/{invoice}/refund",
                       data={"amount": "50", "method": "cash"},
                       follow_redirects=True)
    assert _fingerprint(board) != before


# ------------------------------------------------------------- the quiet --
def test_nothing_happening_reads_as_nothing_happening(board):
    """A fingerprint that keeps changing reloads the doctor's page under
    their hands, and the clinic turns the feature off."""
    first = _fingerprint(board)
    for _ in range(4):
        assert _fingerprint(board) == first


def test_another_patients_bill_does_not_disturb_this_board(board):
    """A doctor's board is their own list. Somebody else's invoice must not
    reload it — on a clinic with three doctors that is a page that never sits
    still."""
    from app.models import Patient

    with board["app"].app_context():
        other = Patient(patient_number="P9", full_name="طفل تاني",
                        gender="female", date_of_birth=date(2024, 1, 1),
                        is_active=True)
        board["db"].session.add(other)
        board["db"].session.commit()
        other_id = other.id

    before = _fingerprint(board)
    _bill(board, patient_id=other_id)
    assert _fingerprint(board) == before


def test_yesterdays_money_does_not_disturb_todays_board(board):
    """Otherwise every board in the clinic reloads whenever anybody settles
    an old balance."""
    from datetime import timedelta

    from app.models import Invoice

    with board["app"].app_context():
        board["db"].session.add(Invoice(
            invoice_number="INV-OLD", patient_id=board["ids"]["child"],
            doctor_id=board["ids"]["doctor"],
            invoice_date=local_today() - timedelta(days=30)))
        board["db"].session.commit()

    first = _fingerprint(board)
    assert _fingerprint(board) == first


# ---------------------------------------------------------- and it's cheap --
def test_the_poll_is_cheap_enough_to_run_all_day(board):
    """Every open screen asks this every twelve seconds, all day. It has to
    stay a handful of column-only queries — the moment it loads objects, the
    clinic's own screens become its heaviest user."""
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    _bill(board)
    statements = []

    def record(conn, cursor, statement, params, context, many):
        statements.append(statement)

    event.listen(Engine, "before_cursor_execute", record)
    try:
        _fingerprint(board)
    finally:
        event.remove(Engine, "before_cursor_execute", record)

    assert len(statements) <= 12, f"the poll costs {len(statements)} queries"
    assert not any("SELECT patients.*" in s for s in statements)
