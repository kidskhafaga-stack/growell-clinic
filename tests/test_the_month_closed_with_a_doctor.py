"""A running balance is not a settlement, and a settlement has to stop moving.

The program could already say what a doctor has earned since the clinic opened
and what has been handed to them. That is the right answer to *"where do we
stand"* and the wrong answer to the thing a clinic actually does at the end of
a month: sit with somebody, agree a figure, and pay it. Asked for in one line:
*"وفى استشاري بيتحاسب اخر الشهر"*.

**The difference is stopping.** A screen that recomputes is honest and useless
here — an invoice edited in October changes what September's figure would have
been, and a doctor who agreed 12,400 and finds 12,150 next week stops trusting
every number the program shows them. So a closed statement carries its own
figures, copied at the moment it closed, and nothing afterwards touches them.

**Two bases, because two agreements exist.** Cash work is collected at the
desk the same hour, so billed and collected are one number and the distinction
costs a single-doctor clinic nothing. Contract work is paid when the insurer
sends the money, and settling that at billing pays a doctor out of money the
clinic has not got. Which applies is the agreement with that doctor — a column
on them, not a rule in any file — and unset means **billed**, which is what
every figure in this program has always meant.

**And a period is settled once.** Two statements over one fortnight pay it
twice, and both look right on their own.
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from app.utils.clock import local_today  # noqa: E402


@pytest.fixture()
def earned(clinic):
    """A doctor with 80 of share on a bill the family has not paid yet."""
    from app.models import Invoice, InvoiceItem, Service

    db = clinic["db"]
    with clinic["app"].app_context():
        service = db.session.get(Service, clinic["ids"]["exam"])
        invoice = Invoice(patient_id=clinic["ids"]["child"],
                          doctor_id=clinic["ids"]["doctor"],
                          invoice_number="INV-S1", invoice_date=local_today(),
                          status="unpaid")
        db.session.add(invoice)
        db.session.flush()
        item = InvoiceItem(invoice_id=invoice.id, service_id=service.id,
                           description="كشف", quantity=1, unit_price=200,
                           discount_value=0)
        db.session.add(item)
        db.session.flush()
        item.commission_amount = service.doctor_share(item.net, None)
        db.session.commit()
        clinic["invoice"] = invoice.id
    return clinic


def _month():
    today = local_today()
    return today.replace(day=1), today


def _draw(fx, basis=None, date_from=None, date_to=None):
    from app.models import User
    from app.utils import settlement as settle

    start, end = _month()
    db = fx["db"]
    with fx["app"].app_context():
        doctor = db.session.get(User, fx["ids"]["doctor"])
        row = settle.draw(doctor, date_from or start, date_to or end,
                          basis=basis)
        db.session.commit()
        return row.id


def _get(fx, settlement_id):
    from app.models import Settlement

    with fx["app"].app_context():
        row = fx["db"].session.get(Settlement, settlement_id)
        return {"status": row.status, "basis": row.basis,
                "lines": row.lines_amount, "duty": row.duty_amount,
                "vaccines": row.vaccine_amount, "gross": row.gross_amount,
                "advances": row.advances, "net": row.net_due,
                "awaiting": row.awaiting, "number": row.number}


# ------------------------------------------------------------ what it adds up

def test_the_statement_carries_what_was_earned_in_the_period(earned):
    row = _get(earned, _draw(earned))
    assert row["lines"] == 80.0
    assert row["gross"] == 80.0
    assert row["net"] == 80.0


def test_work_outside_the_period_is_not_on_it(earned):
    """A statement answers for its own days and no others."""
    start = local_today() - timedelta(days=60)
    row = _get(earned, _draw(earned, date_from=start,
                             date_to=start + timedelta(days=5)))
    assert row["gross"] == 0.0


def test_money_already_handed_over_in_the_period_is_subtracted(earned):
    """An advance on the fifteenth. Ignored, the month is paid twice — and
    the second payment looks exactly as right as the first."""
    from app.models import DoctorPayout

    db = earned["db"]
    with earned["app"].app_context():
        db.session.add(DoctorPayout(doctor_id=earned["ids"]["doctor"],
                                    amount=30, paid_on=local_today(),
                                    method="cash"))
        db.session.commit()
    row = _get(earned, _draw(earned))
    assert row["gross"] == 80.0
    assert row["advances"] == 30.0
    assert row["net"] == 50.0


def test_money_handed_over_outside_the_period_is_not_subtracted(earned):
    """A payment in June is not an advance against September. Counted, the
    doctor is short by an amount that was already settled once."""
    from app.models import DoctorPayout

    db = earned["db"]
    with earned["app"].app_context():
        db.session.add(DoctorPayout(doctor_id=earned["ids"]["doctor"],
                                    amount=500,
                                    paid_on=local_today() - timedelta(days=90),
                                    method="cash"))
        db.session.commit()
    row = _get(earned, _draw(earned))
    assert row["advances"] == 0.0
    assert row["net"] == 80.0


def test_one_doctors_month_carries_only_their_own_work(earned):
    """Two doctors billing in the same month. Without the filter each of them
    is settled for the other's work as well as their own — the same failure
    the rota and the collections both had, in a third place."""
    from app.models import Invoice, InvoiceItem, Service, User

    db = earned["db"]
    with earned["app"].app_context():
        other = User(username="doc7", full_name="د. رابع", role="doctor",
                     is_active=True)
        other.set_password("secret")
        db.session.add(other)
        db.session.flush()
        service = db.session.get(Service, earned["ids"]["exam"])
        invoice = Invoice(patient_id=earned["ids"]["child"],
                          doctor_id=other.id, invoice_number="INV-OTHER",
                          invoice_date=local_today(), status="unpaid")
        db.session.add(invoice)
        db.session.flush()
        db.session.add(InvoiceItem(
            invoice_id=invoice.id, service_id=service.id, description="كشف",
            quantity=1, unit_price=200, discount_value=0,
            commission_amount=90))
        db.session.commit()

    assert _get(earned, _draw(earned))["lines"] == 80.0


def test_a_basis_nobody_recognises_falls_back_to_the_default(earned):
    """Data typed by hand, an old row, a future value this version has never
    heard of. Any of them settling on an unknown rule would pay a doctor by
    arithmetic nobody in the building can name."""
    from app.models import User
    from app.utils import settlement as settle

    db = earned["db"]
    with earned["app"].app_context():
        doctor = db.session.get(User, earned["ids"]["doctor"])
        doctor.settlement_basis = "whatever"
        db.session.commit()
        assert settle.basis_for(doctor) == "billed"

    assert _get(earned, _draw(earned))["basis"] == "billed"


def test_the_nights_and_the_doses_are_their_own_lines(clinic):
    """Three shapes of money on one piece of paper, each still traceable —
    folding them together makes a total nobody can check."""
    from datetime import time

    from app.models import Setting, User
    from app.models.duty import DutySlot
    from app.utils import duty

    db = clinic["db"]
    with clinic["app"].app_context():
        Setting.set("mod_enabled:duty", "1")
        night = DutySlot(name="ليلي", start_time=time(22, 0),
                         end_time=time(8, 0), rate=700)
        db.session.add(night)
        db.session.commit()
        row = duty.assign(db.session.get(User, clinic["ids"]["doctor"]), night)
        duty.confirm(row)
        db.session.commit()

    got = _get(clinic, _draw(clinic))
    assert got["duty"] == 700.0
    assert got["lines"] == 0.0
    assert got["gross"] == 700.0


# --------------------------------------------------------------- the freezing

def test_a_draft_follows_the_data(earned):
    """It is a working figure and says so — redrawn every time it is opened."""
    from app.models import Invoice, InvoiceItem, Settlement
    from app.utils import settlement as settle

    settlement_id = _draw(earned)
    db = earned["db"]
    with earned["app"].app_context():
        invoice = db.session.get(Invoice, earned["invoice"])
        db.session.add(InvoiceItem(invoice_id=invoice.id, description="زيادة",
                                   quantity=1, unit_price=100,
                                   discount_value=0, commission_amount=40))
        db.session.commit()
        settle.refresh(db.session.get(Settlement, settlement_id))
        db.session.commit()
    assert _get(earned, settlement_id)["gross"] == 120.0


def test_a_closed_statement_does_not_move_when_a_bill_is_edited(earned):
    """The whole reason the document exists. A figure that shifts after it was
    agreed is worse than no figure at all."""
    from app.models import Invoice, InvoiceItem, Settlement
    from app.utils import settlement as settle

    settlement_id = _draw(earned)
    db = earned["db"]
    with earned["app"].app_context():
        settle.close(db.session.get(Settlement, settlement_id))
        db.session.commit()

        invoice = db.session.get(Invoice, earned["invoice"])
        db.session.add(InvoiceItem(invoice_id=invoice.id, description="زيادة",
                                   quantity=1, unit_price=100,
                                   discount_value=0, commission_amount=40))
        db.session.commit()
        settle.refresh(db.session.get(Settlement, settlement_id))
        db.session.commit()

    row = _get(earned, settlement_id)
    assert row["status"] == "closed"
    assert row["gross"] == 80.0


def test_closing_takes_the_figures_as_they_are_at_that_moment(earned):
    """Not as they were when the draft was drawn.

    Found by breaking it: every test drew and closed in the same breath, so a
    ``close`` that froze last week's numbers passed all of them. A statement
    left open over a working month and then agreed would have been agreed at
    the wrong figure — and it is the figure both people signed.
    """
    from app.models import Invoice, InvoiceItem, Settlement
    from app.utils import settlement as settle

    settlement_id = _draw(earned)
    db = earned["db"]
    with earned["app"].app_context():
        invoice = db.session.get(Invoice, earned["invoice"])
        db.session.add(InvoiceItem(invoice_id=invoice.id, description="زيادة",
                                   quantity=1, unit_price=100,
                                   discount_value=0, commission_amount=40))
        db.session.commit()
        settle.close(db.session.get(Settlement, settlement_id))
        db.session.commit()
    assert _get(earned, settlement_id)["gross"] == 120.0


def test_reopening_puts_it_back_on_the_data(earned):
    """A mistake found before the money goes is a correction."""
    from app.models import Invoice, InvoiceItem, Settlement
    from app.utils import settlement as settle

    settlement_id = _draw(earned)
    db = earned["db"]
    with earned["app"].app_context():
        settle.close(db.session.get(Settlement, settlement_id))
        invoice = db.session.get(Invoice, earned["invoice"])
        db.session.add(InvoiceItem(invoice_id=invoice.id, description="زيادة",
                                   quantity=1, unit_price=100,
                                   discount_value=0, commission_amount=40))
        db.session.commit()
        settle.reopen(db.session.get(Settlement, settlement_id))
        db.session.commit()

    row = _get(earned, settlement_id)
    assert row["status"] == "draft"
    assert row["gross"] == 120.0


def test_a_paid_statement_cannot_be_reopened(earned):
    """The same edit after the doctor has been paid is a second set of books.
    The difference belongs on the next statement."""
    from app.models import Settlement
    from app.utils import settlement as settle

    settlement_id = _draw(earned)
    db = earned["db"]
    with earned["app"].app_context():
        statement = db.session.get(Settlement, settlement_id)
        settle.close(statement)
        settle.mark_paid(statement)
        db.session.commit()
        settle.reopen(db.session.get(Settlement, settlement_id))
        db.session.commit()
    assert _get(earned, settlement_id)["status"] == "paid"


# ------------------------------------------------------------ settled once

def test_a_period_already_settled_is_refused(earned):
    """Two statements over one fortnight pay it twice, and both look right on
    their own."""
    from app.models import User
    from app.utils import settlement as settle

    _draw(earned)
    start, end = _month()
    db = earned["db"]
    with earned["app"].app_context():
        doctor = db.session.get(User, earned["ids"]["doctor"])
        with pytest.raises(ValueError):
            settle.draw(doctor, start, end)
        db.session.rollback()


def test_even_a_partial_overlap_is_refused(earned):
    """One day shared is one day paid twice."""
    from app.models import User
    from app.utils import settlement as settle

    start, end = _month()
    _draw(earned)
    db = earned["db"]
    with earned["app"].app_context():
        doctor = db.session.get(User, earned["ids"]["doctor"])
        with pytest.raises(ValueError):
            settle.draw(doctor, end, end + timedelta(days=20))
        db.session.rollback()


def test_a_period_that_touches_nothing_is_allowed(earned):
    """The next month is the next month."""
    from app.models import User
    from app.utils import settlement as settle

    start, end = _month()
    _draw(earned)
    db = earned["db"]
    with earned["app"].app_context():
        doctor = db.session.get(User, earned["ids"]["doctor"])
        row = settle.draw(doctor, end + timedelta(days=1),
                          end + timedelta(days=30))
        db.session.commit()
        assert row.id is not None


def test_another_doctors_month_is_not_this_doctors(earned):
    """The overlap rule is per person, not per calendar."""
    from app.models import User
    from app.utils import settlement as settle

    start, end = _month()
    _draw(earned)
    db = earned["db"]
    with earned["app"].app_context():
        other = User(username="doc9", full_name="د. تاني", role="doctor",
                     is_active=True)
        other.set_password("secret")
        db.session.add(other)
        db.session.flush()
        row = settle.draw(other, start, end)
        db.session.commit()
        assert row.id is not None


def test_a_period_running_backwards_is_refused(earned):
    from app.models import User
    from app.utils import settlement as settle

    start, end = _month()
    db = earned["db"]
    with earned["app"].app_context():
        doctor = db.session.get(User, earned["ids"]["doctor"])
        with pytest.raises(ValueError):
            settle.draw(doctor, end, start - timedelta(days=1))
        db.session.rollback()


# ----------------------------------------------------------------- the basis

def test_the_default_basis_is_what_the_program_always_meant(earned):
    """A clinic that sets nothing settles exactly as it did yesterday."""
    assert _get(earned, _draw(earned))["basis"] == "billed"


def test_a_doctors_own_agreement_is_followed(earned):
    from app.models import User

    db = earned["db"]
    with earned["app"].app_context():
        db.session.get(User, earned["ids"]["doctor"]).settlement_basis = \
            "collected"
        db.session.commit()
    assert _get(earned, _draw(earned))["basis"] == "collected"


def test_on_a_collected_basis_uncollected_work_is_not_due(earned):
    """The bill in the fixture has not been paid. On a collected agreement the
    doctor is not owed it yet — and the statement says how much is still out
    rather than leaving them to ask."""
    row = _get(earned, _draw(earned, basis="collected"))
    assert row["lines"] == 0.0
    assert row["net"] == 0.0
    assert row["awaiting"] == 80.0


def test_collected_work_is_due_on_either_basis(earned):
    from app.models import Invoice, Payment

    db = earned["db"]
    with earned["app"].app_context():
        db.session.add(Payment(invoice_id=earned["invoice"], amount=200,
                               method="cash"))
        db.session.get(Invoice, earned["invoice"]).recalc_status()
        db.session.commit()
    row = _get(earned, _draw(earned, basis="collected"))
    assert row["net"] == 80.0
    assert row["awaiting"] == 0.0


def test_a_night_is_due_even_on_a_collected_agreement(clinic):
    """Cover is owed by the clinic itself with nobody in between. Holding it
    back would be the clinic refusing its own debt because somebody else has
    not paid theirs."""
    from datetime import time

    from app.models import Setting, User
    from app.models.duty import DutySlot
    from app.utils import duty

    db = clinic["db"]
    with clinic["app"].app_context():
        Setting.set("mod_enabled:duty", "1")
        night = DutySlot(name="ليلي", start_time=time(22, 0),
                         end_time=time(8, 0), rate=700)
        db.session.add(night)
        db.session.commit()
        row = duty.assign(db.session.get(User, clinic["ids"]["doctor"]), night)
        duty.confirm(row)
        db.session.commit()

    assert _get(clinic, _draw(clinic, basis="collected"))["net"] == 700.0


# ---------------------------------------------------------------- the screens

def test_the_statement_is_reachable_and_prints_its_figure(earned):
    settlement_id = _draw(earned)
    page = earned["sign_in"]("boss").get(
        f"/finance/settlement/{settlement_id}").get_data(as_text=True)
    assert "80.0" in page
    assert "مسوّدة" in page


def test_the_list_is_linked_from_the_finance_hub(earned):
    """A document nothing links to is a document nobody draws."""
    page = earned["sign_in"]("boss").get("/finance/").get_data(as_text=True)
    assert 'href="/finance/settlements"' in page


def test_drawing_one_from_the_screen_works(earned):
    from app.models import Settlement

    start, end = _month()
    earned["sign_in"]("boss").post(
        "/finance/settlements/draw",
        data={"doctor_id": earned["ids"]["doctor"],
              "date_from": start.isoformat(), "date_to": end.isoformat()},
        follow_redirects=True)
    with earned["app"].app_context():
        assert Settlement.query.count() == 1


def test_the_screen_says_why_it_refused_an_overlap(earned):
    """Silence would leave somebody pressing a button that does nothing, and
    the reason it does nothing is the most useful sentence on the screen."""
    start, end = _month()
    client = earned["sign_in"]("boss")
    data = {"doctor_id": earned["ids"]["doctor"],
            "date_from": start.isoformat(), "date_to": end.isoformat()}
    client.post("/finance/settlements/draw", data=data, follow_redirects=True)
    page = client.post("/finance/settlements/draw", data=data,
                       follow_redirects=True).get_data(as_text=True)
    assert "هتتدفع مرتين" in page

    from app.models import Settlement

    with earned["app"].app_context():
        assert Settlement.query.count() == 1


def test_paying_from_the_statement_ties_the_money_to_the_paper(earned):
    """The question somebody asks in March about a payment made in January."""
    from app.models import DoctorPayout, Settlement
    from app.utils import settlement as settle

    settlement_id = _draw(earned)
    db = earned["db"]
    with earned["app"].app_context():
        settle.close(db.session.get(Settlement, settlement_id))
        db.session.commit()

    earned["sign_in"]("boss").post(
        "/finance/doctor-payouts/pay",
        data={"doctor_id": earned["ids"]["doctor"], "amount": "80",
              "method": "cash", "settlement_id": settlement_id},
        follow_redirects=True)

    with earned["app"].app_context():
        payout = DoctorPayout.query.first()
        assert payout.settlement_id == settlement_id
        assert db.session.get(Settlement, settlement_id).status == "paid"


def test_a_payment_that_settles_nothing_is_still_a_payment(earned):
    """An advance on a Tuesday is not a month being closed, and attaching it
    to a document nobody drew would be a lie about what happened."""
    from app.models import DoctorPayout

    earned["sign_in"]("boss").post(
        "/finance/doctor-payouts/pay",
        data={"doctor_id": earned["ids"]["doctor"], "amount": "50",
              "method": "cash"}, follow_redirects=True)
    with earned["app"].app_context():
        payout = DoctorPayout.query.first()
        assert payout is not None and payout.settlement_id is None


def test_a_payout_cannot_be_pinned_to_another_doctors_statement(earned):
    """Otherwise one doctor's payment closes another's month."""
    from app.models import DoctorPayout, Settlement, User
    from app.utils import settlement as settle

    settlement_id = _draw(earned)
    db = earned["db"]
    with earned["app"].app_context():
        settle.close(db.session.get(Settlement, settlement_id))
        other = User(username="doc8", full_name="د. تالت", role="doctor",
                     is_active=True)
        other.set_password("secret")
        db.session.add(other)
        db.session.commit()
        other_id = other.id

    earned["sign_in"]("boss").post(
        "/finance/doctor-payouts/pay",
        data={"doctor_id": other_id, "amount": "80", "method": "cash",
              "settlement_id": settlement_id}, follow_redirects=True)

    with earned["app"].app_context():
        assert db.session.get(Settlement, settlement_id).status == "closed"
        assert DoctorPayout.query.first().settlement_id is None
