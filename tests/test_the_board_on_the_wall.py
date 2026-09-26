"""The board on the wall — the day board, drawn for less.

The load test left one item open: the day board, drawn in full, took the
best part of a second on a copy with 120 bookings, and a third of that was
the collection card adding up the month by loading every invoice of the
month with every line and every payment. The visit-type panel did the same
with the month's appointments, only to count them.

Both now ask the database for the numbers, and the numbers are the same:

* ``Invoice.paid_and_share_for`` gives each invoice's collected money and
  doctor's share by the properties' own arithmetic — refunds negative,
  rounded per invoice — and is checked here against the properties;
* the board's collection card and visit-type panel are checked against the
  way they used to be worked out, on the same data.

The load test's wall screen was also wrong about what a wall screen does: the
real one asks a twelve-millisecond fingerprint every twelve seconds and draws
the board only when it changes. ``tools/loadtest/drive.py`` now does the
same.

And one fault that was already there: a board opened for a doctor id nobody
on the list has — a doctor since deactivated, a link kept on a wall screen —
failed to draw, every time it was asked.
"""
import os
import sys
from datetime import date, datetime, time, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from app.utils.clock import local_today  # noqa: E402


@pytest.fixture()
def month(clinic):
    """A month of bills and bookings with every awkward case in it."""
    from app.models import (Appointment, Invoice, InvoiceItem, Patient,
                            Payment)

    db = clinic["db"]
    ids = clinic["ids"]
    today = local_today()
    first = today.replace(day=1)
    with clinic["app"].app_context():
        kids = [ids["child"]]
        for n in range(3):
            kid = Patient(patient_number=f"M{n}", full_name=f"طفل {n}",
                          gender="female", date_of_birth=date(2023, 1, 1),
                          is_active=True)
            db.session.add(kid)
            db.session.flush()
            kids.append(kid.id)

        def bill(number, on, doctor, lines, payments):
            inv = Invoice(invoice_number=number, patient_id=kids[0],
                          doctor_id=doctor, invoice_date=on)
            db.session.add(inv)
            db.session.flush()
            for price, commission in lines:
                db.session.add(InvoiceItem(invoice_id=inv.id, description="بند",
                                           unit_price=price, quantity=1,
                                           commission_amount=commission))
            for amount, kind in payments:
                db.session.add(Payment(invoice_id=inv.id, amount=amount,
                                       kind=kind, method="cash"))

        doctor = ids["doctor"]
        bill("B1", today, doctor, [(200, 80.555), (150, 75)], [(350, "payment")])
        bill("B2", today, doctor, [(300, None)], [(300, "payment"), (100, "refund")])
        bill("B3", today, None, [(90, 10)], [])                   # nobody's
        bill("B4", today, doctor, [], [(50, "payment")])          # no lines
        bill("B5", first, doctor, [(120, 33.333)], [(120, "payment")])
        bill("B6", first - timedelta(days=1), doctor, [(999, 99)],
             [(999, "payment")])                                  # last month
        # Two payments whose float sum is not the 0.3 the money is.
        bill("B7", today, doctor, [(0.3, 0.1)], [(0.1, "payment"),
                                                  (0.2, "payment")])

        def book(kid, on, kind, status, hour):
            db.session.add(Appointment(patient_id=kid, doctor_id=doctor,
                                       appt_date=on, appt_time=time(hour, 0),
                                       appt_type=kind, status=status))

        book(kids[0], today, "new", "scheduled", 9)
        book(kids[1], today, "followup", "completed", 10)
        book(kids[0], today, "followup", "waiting", 13)            # 2nd of a type
        book(kids[2], today, "followup", "cancelled", 11)          # not seen
        book(kids[3], today, "vaccination", "no_show", 12)         # not seen
        book(kids[1], first, "new", "completed", 9)                # month
        book(kids[3], first - timedelta(days=40), "new", "completed", 9)
        db.session.commit()
    clinic["today"] = today
    return clinic


# ------------------------------------------------------------ the money ----
def test_batched_totals_are_the_properties(month):
    from app.models import Invoice

    with month["app"].app_context():
        invoices = Invoice.query.all()
        batched = Invoice.paid_and_share_for([i.id for i in invoices])
        for inv in invoices:
            expected = (inv.paid, inv.doctor_share_total)
            assert batched.get(inv.id, (0, 0)) == expected, inv.invoice_number
        # The awkward ones really are in there.
        by_number = {i.invoice_number: i for i in invoices}
        assert by_number["B2"].paid == 200            # the refund took 100
        assert by_number["B4"].doctor_share_total == 0
        assert batched[by_number["B7"].id][0] == 0.3


def _old_finance(doctor_id, on_date):
    """The collection card as it used to be worked out: every invoice loaded
    and summed through its properties."""
    from app.models import Invoice

    def agg(invoices):
        return {"collection": round(sum(i.paid for i in invoices), 2),
                "share": round(sum(i.doctor_share_total for i in invoices), 2)}

    base = Invoice.query
    if doctor_id:
        base = base.filter(Invoice.doctor_id == doctor_id)
    return {"today": agg(base.filter(Invoice.invoice_date == on_date).all()),
            "month": agg(base.filter(
                Invoice.invoice_date >= on_date.replace(day=1),
                Invoice.invoice_date <= on_date).all())}


@pytest.mark.parametrize("whose", ["clinic", "doctor"])
def test_the_collection_card_says_what_it_said(month, whose):
    from app.blueprints.appointments.routes import _finance_summary

    doctor_id = month["ids"]["doctor"] if whose == "doctor" else None
    with month["app"].test_request_context():
        assert _finance_summary(doctor_id, month["today"]) == \
            _old_finance(doctor_id, month["today"])
        # And it is not a comparison of noughts.
        assert _finance_summary(doctor_id, month["today"])["month"][
            "collection"] > 0


# ------------------------------------------------------------ the counts ----
def _old_breakdown(doctor_id, on_date):
    from collections import Counter

    from app.extensions import db
    from app.models import Appointment

    month_start = on_date.replace(day=1)
    base = Appointment.query.filter(
        Appointment.status.notin_(("cancelled", "no_show")))
    if doctor_id:
        base = base.filter(Appointment.doctor_id == doctor_id)
    day = base.filter(Appointment.appt_date == on_date).all()
    month = base.filter(Appointment.appt_date >= month_start,
                        Appointment.appt_date <= on_date).all()

    def newold(appts, start):
        pids = {a.patient_id for a in appts}
        if not pids:
            return {"new": 0, "old": 0, "total": 0}
        firsts = dict(db.session.query(Appointment.patient_id,
                                       db.func.min(Appointment.appt_date))
                      .filter(Appointment.patient_id.in_(pids),
                              Appointment.status.notin_(("cancelled",
                                                         "no_show")))
                      .group_by(Appointment.patient_id).all())
        new = sum(1 for p in pids
                  if firsts.get(p) and start <= firsts[p] <= on_date)
        return {"new": new, "old": len(pids) - new, "total": len(pids)}

    return {"day": Counter(a.appt_type for a in day),
            "month": Counter(a.appt_type for a in month),
            "total": {"day": len(day), "month": len(month)},
            "newold": {"day": newold(day, on_date),
                       "month": newold(month, month_start)}}


@pytest.mark.parametrize("whose", ["clinic", "doctor"])
def test_the_visit_panel_counts_what_it_counted(month, whose):
    from app.blueprints.appointments.routes import _visit_breakdown

    doctor_id = month["ids"]["doctor"] if whose == "doctor" else None
    with month["app"].test_request_context():
        new = _visit_breakdown(doctor_id, month["today"])
        old = _old_breakdown(doctor_id, month["today"])
    assert new["total"] == old["total"]
    assert new["newold"] == old["newold"]
    for row in new["rows"]:
        assert row["day"] == old["day"].get(row["key"], 0), row["key"]
        assert row["month"] == old["month"].get(row["key"], 0), row["key"]
    assert new["total"]["day"] == 3                  # cancelled, no-show out
    assert new["newold"]["day"]["total"] == 2        # two children


# ------------------------------------------------------------ the page ----
def test_a_board_for_a_doctor_nobody_has_still_draws(month):
    client = month["sign_in"]("boss")
    for doctor_id in (month["ids"]["doctor"], 999999):
        reply = client.get(f"/appointments/?doctor_id={doctor_id}")
        assert reply.status_code == 200, doctor_id


def test_the_card_and_the_panel_load_nothing_to_count_it(month):
    """What cost the time was not the number of questions — the old card
    asked six — but the answers: every invoice of the month, with its lines
    and payments, built as objects to be added up. Now not one is."""
    from sqlalchemy import event

    from app.blueprints.appointments.routes import (_finance_summary,
                                                    _visit_breakdown)
    from app.models import Appointment, Invoice, InvoiceItem, Payment

    built = []

    def seen(target, _context):
        built.append(type(target).__name__)

    kinds = (Invoice, InvoiceItem, Payment, Appointment)
    for kind in kinds:
        event.listen(kind, "load", seen)
    try:
        with month["app"].test_request_context():
            _finance_summary(None, month["today"])
            _finance_summary(month["ids"]["doctor"], month["today"])
            _visit_breakdown(None, month["today"])
    finally:
        for kind in kinds:
            event.remove(kind, "load", seen)
    assert built == []
