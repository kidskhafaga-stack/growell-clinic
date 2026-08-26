"""Money handed to a doctor, written down.

Asked for in one line — *"سجل صرف للطبيب — هو اللي هيخلّي «فاضلي قد إيه» رقم
بدل تخمين"* — and it is exactly right: the doctor's own screen carried a
sentence explaining why it could not answer that question, because **earning
and being paid were two different events and only one of them was recorded.**

Every invoice line already carries the doctor's share, so what a doctor has
earned has always been computable. What left the clinic and reached them was
nowhere: paying a doctor was, at best, a "salaries" expense with no doctor on
it. Earned minus nothing is not a balance.

**It is a running account, not a settlement of a month.** A payout carries no
period. One clinic pays a round number on the fifteenth and the rest later,
another pays weekly, another clears an old balance in one go — tie each payment
to a month and all of them have to be forced into the shape only one of them
has. So earned-ever minus paid-ever is the balance, and the window a screen is
showing is never mixed into it.

**And it is money leaving a drawer**, which is the half that is easy to forget
and expensive to get wrong: pay 2,000 out of the reception till without saying
so and the drawer comes up 2,000 short at close, with the variance landing on
the cashier for doing what they were told.
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def owed(clinic):
    """A doctor who has earned 80 on an invoice line and 25 on a dose."""
    from app.extensions import db
    from app.models import (CashAccount, Invoice, InvoiceItem, Patient,
                            PatientVaccine, Service, User, VaccineBrand)
    from app.utils.accounting import ensure_seeded
    from app.utils.clock import local_today
    from app.utils.treasury import seed_accounts

    with clinic["app"].app_context():
        ensure_seeded()
        seed_accounts()
        doctor = User.query.filter_by(username="doc").first()
        exam = Service.query.filter_by(name="كشف").first()
        today = local_today()

        invoice = Invoice(patient_id=clinic["ids"]["child"],
                          doctor_id=doctor.id, invoice_number="INV-1",
                          invoice_date=today, status="paid")
        db.session.add(invoice)
        db.session.flush()
        line = InvoiceItem(invoice_id=invoice.id, service_id=exam.id,
                           description=exam.name, quantity=1,
                           unit_price=exam.price, discount_value=0)
        db.session.add(line)
        db.session.flush()
        line.commission_amount = exam.doctor_share(line.net, doctor)

        # The other shape the money comes in: a fee on the brand, recorded
        # against the dose. Left out of the fixture, half of `earned_ever`
        # would be untested.
        brand = db.session.get(VaccineBrand, clinic["ids"]["brand"])
        brand.doctor_fee = 25
        jab = Patient(patient_number="V9", full_name="طفل تطعيم",
                      gender="female", date_of_birth=date(2024, 6, 1),
                      is_active=True)
        db.session.add(jab)
        db.session.flush()
        db.session.add(PatientVaccine(
            patient_id=jab.id, vaccine_id=clinic["ids"]["pcv"],
            brand_id=brand.id, dose_number=1, given_date=today,
            doctor_id=doctor.id, given_outside=False, event_type="given"))
        db.session.commit()

        clinic["doctor_id"] = doctor.id
        clinic["earned"] = round(exam.price * 0.4 + 25, 2)      # 80 + 25
        clinic["drawer"] = CashAccount.query.filter_by(code="1010").first().id
    return clinic


def _account(owed, doctor_id=None):
    from app.utils import doctor_work

    with owed["app"].app_context():
        return doctor_work.account(doctor_id or owed["doctor_id"])


def _pay(owed, who="boss", **form):
    data = {"doctor_id": owed["doctor_id"], "amount": "50", "method": "cash"}
    data.update(form)
    return owed["sign_in"](who).post("/finance/doctor-payouts/pay", data=data,
                                     follow_redirects=True)


# ------------------------------------------------------------ the balance

def test_earned_is_lines_plus_doses(owed):
    """Both shapes the doctor's cut comes in. A total that only knew about
    invoice lines would shorten a paediatrician's pay by the whole vaccine
    round."""
    from app.utils import doctor_work

    with owed["app"].app_context():
        assert doctor_work.earned_ever(owed["doctor_id"]) == owed["earned"]


def test_owed_is_earned_minus_handed_over(owed):
    """The subtraction the screen could not do."""
    _pay(owed, amount="60")

    standing = _account(owed)

    assert standing["earned"] == owed["earned"]
    assert standing["paid"] == 60
    assert standing["balance"] == round(owed["earned"] - 60, 2)


def test_a_doctor_paid_ahead_reads_as_a_minus(owed):
    """A real state, not an error: a clinic advances money against next month.
    Clamping it at zero would hide an advance nobody could then account for."""
    _pay(owed, amount="500")

    assert _account(owed)["balance"] < 0


def test_one_doctor_is_not_paid_out_of_another_doctors_balance(owed):
    from app.models import User

    with owed["app"].app_context():
        boss = User.query.filter_by(username="boss").first().id
    _pay(owed, amount="50")

    assert _account(owed, boss)["paid"] == 0


# ------------------------------- all time and this window are not the same

def test_the_window_and_the_balance_are_never_mixed(owed):
    """*Earned this month minus paid ever* is not a number, and it looks like
    one. The screen shows the window's activity beside an all-time balance and
    labels which is which."""
    from app.utils import doctor_work
    from app.utils.clock import local_today

    today = local_today()
    long_ago = (today - timedelta(days=200)).isoformat()
    _pay(owed, amount="70", paid_on=long_ago)

    with owed["app"].test_request_context():
        work = doctor_work.summary(owed["doctor_id"],
                                   today.replace(day=1), today)

    assert work["money"]["paid"] == 0, \
        "a payment from months ago was counted into this month's activity"
    assert work["account"]["paid"] == 70, \
        "the all-time balance forgot a payment because of the screen's window"


# --------------------------------------------------- money leaving a drawer

def test_paying_a_doctor_takes_the_money_out_of_the_till(owed):
    """Otherwise the drawer's statement says the cash is still in it."""
    from app.models import CashAccount
    from app.utils import treasury

    _pay(owed, amount="90", account_id=owed["drawer"])

    with owed["app"].app_context():
        drawer = CashAccount.query.filter_by(code="1010").first()
        rows = treasury.movements(drawer)
        payouts = [r for r in rows if r["kind"] == "doctor"]

        assert payouts, "the payout is missing from the till's statement"
        assert payouts[0]["amount"] == -90, "it went in instead of out"
        assert treasury.account_balance(drawer) == -90


def test_the_shift_expects_the_money_to_be_gone(owed):
    """The failure this record exists to prevent. Cash handed to a doctor out
    of the open drawer has to come off what the shift expects to count, or the
    cashier is short by exactly what the clinic told them to hand over."""
    from app.extensions import db
    from app.models import CashierShift

    with owed["app"].app_context():
        shift = CashierShift(shift_number="S1", opening_float=1000,
                             account_id=owed["drawer"],
                             opened_by=owed["ids"]["desk"], status="open")
        db.session.add(shift)
        db.session.commit()
        before = shift.expected_cash

    # Recorded by the manager, but against the open desk shift: the money
    # comes out of that drawer whoever pressed the button.
    _pay(owed, amount="200", account_id=owed["drawer"])

    with owed["app"].app_context():
        shift = CashierShift.query.first()
        assert shift.expected_cash == before - 200, \
            "the drawer still expects money that was handed to a doctor"


def test_a_transfer_is_not_cash_out_of_a_drawer(owed):
    """A doctor paid by bank transfer took nothing out of the till, and
    charging it to the open shift would invent a shortage."""
    from app.extensions import db
    from app.models import CashierShift, DoctorPayout

    with owed["app"].app_context():
        db.session.add(CashierShift(shift_number="S2", opening_float=1000,
                                    account_id=owed["drawer"],
                                    opened_by=owed["ids"]["desk"],
                                    status="open"))
        db.session.commit()

    _pay(owed, amount="300", method="transfer")

    with owed["app"].app_context():
        assert DoctorPayout.query.first().shift_id is None


def test_it_reaches_the_income_statement(owed):
    """Money that left the drawer and never reached the books makes a clinic's
    profit read higher than it is by exactly what it pays its doctors — which
    in most clinics is the largest number on the page."""
    from app.models import JournalLine

    _pay(owed, amount="120", account_id=owed["drawer"])

    with owed["app"].app_context():
        debits = [ln for ln in JournalLine.query.all()
                  if ln.account.code == "5030" and ln.debit == 120]
        credits = [ln for ln in JournalLine.query.all()
                   if ln.account.code == "1010" and ln.credit == 120]

        assert debits, "the payout is not an expense anywhere"
        assert credits, "the money left no till in the ledger"


# ------------------------------------------------------------- the screens

def test_nothing_is_written_for_nothing(owed):
    from app.models import DoctorPayout

    _pay(owed, amount="0")

    with owed["app"].app_context():
        assert DoctorPayout.query.count() == 0


def test_a_receptionist_is_not_a_doctor_to_pay(owed):
    """An id that is not a practitioner would take money out of the till and
    reach the ledger, and then never appear on this screen again — cash gone
    from the drawer with nowhere in the program that shows it."""
    from app.models import DoctorPayout

    _pay(owed, doctor_id=owed["ids"]["desk"], amount="500")

    with owed["app"].app_context():
        assert DoctorPayout.query.count() == 0


def test_the_shift_report_shows_the_money_it_subtracted(owed):
    """The reconcile table listed the float and the cash collected and then an
    expected figure smaller than their sum, with nothing on screen to explain
    the difference."""
    from app.extensions import db
    from app.models import CashierShift

    with owed["app"].app_context():
        db.session.add(CashierShift(shift_number="S3", opening_float=1000,
                                    account_id=owed["drawer"],
                                    opened_by=owed["ids"]["desk"],
                                    status="open"))
        db.session.commit()

    _pay(owed, amount="150", account_id=owed["drawer"])

    with owed["app"].app_context():
        shift_id = CashierShift.query.first().id
    page = owed["sign_in"]("boss").get(
        f"/finance/shift/{shift_id}").get_data(as_text=True)

    assert "cashier.cash_paid_out" not in page, \
        "the strings are keys, not translations"
    assert "150" in page, \
        "the report subtracts the payout without showing it"


def test_the_screen_opens_and_shows_the_three_numbers(owed):
    _pay(owed, amount="30")

    page = owed["sign_in"]("boss").get(
        "/finance/doctor-payouts").get_data(as_text=True)

    assert "payouts.title" not in page, "the strings are keys, not translations"
    assert "د. أحمد" in page
    for figure in ("105", "30", "75"):        # earned, paid, owed
        assert figure in page, f"the screen does not show {figure}"


def test_there_is_a_way_in(owed):
    """This program keeps building screens nothing links to."""
    page = owed["sign_in"]("boss").get("/finance/").get_data(as_text=True)

    assert "/finance/doctor-payouts" in page


def test_the_doctors_own_screen_now_answers_the_question(owed):
    """*"فاضلي قد إيه"* — the sentence that used to explain why it could not."""
    _pay(owed, amount="40")

    page = owed["sign_in"]("doc").get("/my-clinic").get_data(as_text=True)

    assert "65" in page, "the doctor's screen does not show what is still owed"
    assert "لسه مابيسجّلش صرف" not in page, \
        "the screen still says the program cannot record a payout"


def test_reception_cannot_open_it(owed):
    answer = owed["sign_in"]("desk").get("/finance/doctor-payouts")

    assert answer.status_code in (302, 403)
