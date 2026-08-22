"""An invoice nobody owes anything on is not an invoice somebody owes.

Reported from a real till: a staff member's child was seen on a 100% staff
discount, the invoice came to EGP 0.00, and it sat in the cashier's **who
still owes** list showing a balance of 0.00 with a Collect button that
answered *"the invoice is already fully settled — nothing left to collect"*
when it was pressed. Marked unpaid for ever, in a list of debts, owing
nothing.

The cause is one clause. `recalc_status` opened with `total > 0 and paid >=
total`, so a bill that came to nothing could never reach "paid": zero is not
greater than zero, no money arrived, and the else branch writes "unpaid".

The same fell out of deleting an invoice's last line — the screen offers an ×
on every line — which leaves a real invoice charging nothing.

So the question is only whether anything is **left to collect**. Nothing left
is settled, whether that is because the money came in or because there was
never any to come.

Three things had to change and each is tested here, because fixing only one
of them looks like fixing the bug:

* the rule, so it stops happening;
* the rows already written under the old rule, which no amount of fixing the
  rule reaches;
* the till, which trusted a word written months ago instead of asking the
  invoice in front of it.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


def _bill(clinic, tag, price=480, discount=None, percent=True, paid=0,
          lines=True, status=None):
    """One invoice, as the till would have written it."""
    from app.extensions import db
    from app.models import Invoice, InvoiceItem, Patient, Payment

    with clinic["app"].app_context():
        kid = Patient.query.first()
        if kid is None:
            kid = Patient(patient_number="B1", full_name="طفل", gender="male",
                          date_of_birth=date(2015, 1, 1), is_active=True)
            db.session.add(kid)
            db.session.flush()
        invoice = Invoice(invoice_number=tag, patient_id=kid.id)
        db.session.add(invoice)
        db.session.flush()
        if lines:
            db.session.add(InvoiceItem(
                invoice_id=invoice.id, description="كشف", unit_price=price,
                quantity=1, discount_value=discount or 0,
                discount_is_percent=percent))
        if paid:
            db.session.add(Payment(invoice_id=invoice.id, amount=paid))
        db.session.commit()
        if status is None:
            invoice.recalc_status()
        else:
            invoice.status = status      # as the old rule wrote it
        db.session.commit()
        return invoice.id


def _read(clinic, invoice_id):
    from app.extensions import db
    from app.models import Invoice

    return db.session.get(Invoice, invoice_id)


# --------------------------------------------------------------- the rule

def test_a_bill_that_came_to_nothing_is_settled(clinic):
    """The report, in one assertion."""
    invoice_id = _bill(clinic, "INV-STAFF", price=480, discount=100)

    with clinic["app"].app_context():
        invoice = _read(clinic, invoice_id)

        assert invoice.total == 0
        assert invoice.balance == 0
        assert invoice.status == "paid", \
            "a 100% discount is still being recorded as a debt"


def test_an_invoice_whose_last_line_was_deleted_is_not_a_debt(clinic):
    """The screen offers an × on every line, so this is reachable by hand."""
    invoice_id = _bill(clinic, "INV-EMPTY", lines=False)

    with clinic["app"].app_context():
        assert _read(clinic, invoice_id).status == "paid"


@pytest.mark.parametrize("tag,price,discount,paid,expected", [
    ("owing",     480, None, 0,   "unpaid"),
    ("part",      480, None, 240, "partial"),
    ("settled",   480, None, 480, "paid"),
    ("half-off",  480, 50,   0,   "unpaid"),
    ("half-paid", 480, 50,   240, "paid"),
])
def test_every_ordinary_bill_reads_as_it_always_did(clinic, tag, price,
                                                    discount, paid, expected):
    """The half that matters most. A rule loosened to fix one case is a rule
    that can quietly settle bills nobody has paid, and this is the assertion
    that would catch it."""
    invoice_id = _bill(clinic, f"INV-{tag}", price=price, discount=discount,
                       paid=paid)

    with clinic["app"].app_context():
        assert _read(clinic, invoice_id).status == expected


def test_money_taken_and_refunded_is_owed_again(clinic):
    """A refund puts the debt back. Nothing about "nothing left to collect"
    may make a refunded visit look settled."""
    from app.extensions import db
    from app.models import Payment

    invoice_id = _bill(clinic, "INV-REFUND", price=480, paid=480)

    with clinic["app"].app_context():
        invoice = _read(clinic, invoice_id)
        assert invoice.status == "paid"

        db.session.add(Payment(invoice_id=invoice.id, amount=480,
                               kind="refund"))
        db.session.commit()
        invoice.recalc_status()

        assert invoice.balance == 480
        assert invoice.status == "unpaid"


# ------------------------------------------- the rows already written wrong

def test_the_repair_heals_what_the_old_rule_stored(clinic):
    """Fixing the rule does nothing for the rows already in the database, and
    a clinic upgrading would still find last month's discounted visits sitting
    in the till. This is the half that reaches them."""
    from app.extensions import db
    from app.models.invoice import settle_what_has_nothing_left_to_collect

    stuck = _bill(clinic, "INV-OLD", price=480, discount=100, status="unpaid")
    real = _bill(clinic, "INV-REAL", price=480, status="unpaid")

    with clinic["app"].app_context():
        assert settle_what_has_nothing_left_to_collect() == 1
        db.session.commit()

        assert _read(clinic, stuck).status == "paid"
        assert _read(clinic, real).status == "unpaid", \
            "the repair settled a bill somebody actually owes"


def test_the_repair_can_be_run_twice(clinic):
    """It runs on every upgrade, not once, so a second pass has to be a
    no-op rather than a second helping of side effects."""
    from app.extensions import db
    from app.models.invoice import settle_what_has_nothing_left_to_collect

    _bill(clinic, "INV-TWICE", price=480, discount=100, status="unpaid")

    with clinic["app"].app_context():
        assert settle_what_has_nothing_left_to_collect() == 1
        db.session.commit()
        assert settle_what_has_nothing_left_to_collect() == 0


def test_the_upgrade_runs_it(clinic):
    """A repair nothing calls is a repair that never happens."""
    import inspect

    from app.utils import schema

    source = inspect.getsource(schema.apply_schema)

    assert "settle_what_has_nothing_left_to_collect" in source


def test_a_broken_repair_does_not_stop_the_program_starting(clinic,
                                                            monkeypatch):
    """Bookkeeping tidy-up is the least important thing an upgrade does, and
    it must not be able to take the columns the program needs down with it."""
    import app.models.invoice as invoice_module

    def explode():
        raise RuntimeError("the disk is gone")

    monkeypatch.setattr(invoice_module,
                        "settle_what_has_nothing_left_to_collect", explode)

    with clinic["app"].app_context():
        from app.utils.schema import apply_schema

        apply_schema()          # must not raise


# ----------------------------------------------------------------- the till

def test_the_till_asks_the_invoice_rather_than_the_stored_word(clinic):
    """Belt and braces, and the reason is the bug itself: the status is
    written when something happens to an invoice, so any rule that was ever
    wrong leaves rows behind. The balance is in the loaded row — the screen
    can simply look."""
    _bill(clinic, "INV-STALE", price=480, discount=100, status="unpaid")

    page = clinic["sign_in"]("boss").get(
        "/finance/cashier", follow_redirects=True).data.decode()

    assert "INV-STALE" not in page, \
        "a bill with nothing to collect is still listed as a debt"


def test_a_real_debt_is_still_listed(clinic):
    """Otherwise the filter could be "show nothing"."""
    _bill(clinic, "INV-DEBT", price=480)

    page = clinic["sign_in"]("boss").get(
        "/finance/cashier", follow_redirects=True).data.decode()

    assert "INV-DEBT" in page


# --------------------------------------------- the same rule, written twice

def test_the_appointment_board_agrees_with_the_invoice(clinic):
    """The identical fault, in a second file.

    The board computes its own paid/partial/unpaid from the invoices against a
    patient, and it opened with the same `total > 0` guard — so a staff
    member's child showed a red **Unpaid** and a Collect button on the day of
    their appointment, beside a family who owed nothing and had nothing to
    hand over. Reported that way: *"I collected from her, and today it shows
    as if I collected nothing."*

    One rule written out twice is one rule that can be fixed once and stay
    broken, so this asks the board rather than the invoice.
    """
    from datetime import time

    from app.extensions import db
    from app.models import Appointment, Invoice, InvoiceItem, Patient, User

    with clinic["app"].app_context():
        from app.utils.clock import local_today

        doctor = User.query.filter_by(role="doctor").first()

        kid = Patient(patient_number="BRD1", full_name="عمر", gender="male",
                      date_of_birth=date(2015, 1, 1), is_active=True)
        db.session.add(kid)
        db.session.flush()

        today = local_today()
        invoice = Invoice(invoice_number="INV-BOARD", patient_id=kid.id,
                          invoice_date=today)
        db.session.add(invoice)
        db.session.flush()
        db.session.add(InvoiceItem(invoice_id=invoice.id, description="كشف",
                                   unit_price=480, quantity=1,
                                   discount_value=100,
                                   discount_is_percent=True))
        appt = Appointment(patient_id=kid.id, doctor_id=doctor.id,
                           appt_date=today, appt_time=time(15, 0),
                           status="scheduled")
        db.session.add(appt)
        db.session.commit()
        invoice.recalc_status()
        db.session.commit()

        from app.blueprints.appointments.routes import _payment_status

        state = _payment_status([appt], today)[appt.id]

    assert state["total"] == 0 and state["balance"] == 0
    assert state["state"] == "paid", \
        f"the board is asking a family who owes nothing to pay: {state}"


def test_the_board_still_shows_a_real_debt(clinic):
    """The other side, for the same reason as everywhere else in this file."""
    from datetime import time

    from app.extensions import db
    from app.models import Appointment, Invoice, InvoiceItem, Patient, User

    with clinic["app"].app_context():
        from app.utils.clock import local_today

        doctor = User.query.filter_by(role="doctor").first()

        kid = Patient(patient_number="BRD2", full_name="سارة", gender="female",
                      date_of_birth=date(2016, 1, 1), is_active=True)
        db.session.add(kid)
        db.session.flush()

        today = local_today()
        invoice = Invoice(invoice_number="INV-BOARD2", patient_id=kid.id,
                          invoice_date=today)
        db.session.add(invoice)
        db.session.flush()
        db.session.add(InvoiceItem(invoice_id=invoice.id, description="كشف",
                                   unit_price=480, quantity=1))
        appt = Appointment(patient_id=kid.id, doctor_id=doctor.id,
                           appt_date=today, appt_time=time(15, 30),
                           status="scheduled")
        db.session.add(appt)
        db.session.commit()
        invoice.recalc_status()
        db.session.commit()

        from app.blueprints.appointments.routes import _payment_status

        state = _payment_status([appt], today)[appt.id]

    assert state["state"] == "unpaid" and state["balance"] == 480


# ------------------------------------------------ the door to the invoices

def test_reception_can_reach_the_invoice_list_from_the_till(clinic):
    """Asked directly: *"how will reception see the invoices, and where do
    they do a refund from?"*

    Both already worked. `/finance/invoices` takes the till capability rather
    than the finance module, and every invoice carries a refund form. What was
    missing was a door: reception's only finance screen is the till, and it
    linked to neither — so the answer was reachable by typing the address and
    in no other way. The same shape as everything else found this week:
    implemented, and unreachable.
    """
    from flask import url_for

    from app.i18n import t

    page = clinic["sign_in"]("boss").get(
        "/finance/cashier", follow_redirects=True).data.decode()

    # The exact href, closing quote and all. The bare path is a prefix of
    # `/finance/invoices/<id>/collect`, which this page is full of — measured:
    # the first version of this test passed with the link removed, because
    # every debtor's Collect button satisfied it.
    with clinic["app"].test_request_context("/"):
        exact = f'href="{url_for("finance.invoices")}"'
        label = t("cashier.all_invoices")

    assert exact in page, \
        "the till still offers no way through to the invoice list"
    assert label in page, "the link is there with nothing on it to read"


def test_the_till_capability_really_opens_that_list(clinic):
    """A link to a screen the person cannot open is worse than no link."""
    from app.extensions import db
    from app.models import User

    with clinic["app"].app_context():
        desk = User.query.filter_by(role="reception").first()
        assert desk is not None, "this clinic has no reception user to check"

    client = clinic["app"].test_client()
    client.post("/login", data={"username": desk.username,
                                "password": "secret"}, follow_redirects=True)
    answer = client.get("/finance/invoices", follow_redirects=False)

    assert answer.status_code == 200, \
        f"reception is refused the invoice list ({answer.status_code})"


# ------------------------------------- settled, and settled without money

def test_a_bill_that_came_to_nothing_does_not_claim_money_moved(clinic):
    """Asked directly, about services priced at zero: *"will they be like the
    full discount, or do we put 'free' next to them?"*

    Both. They are settled the same way — there is nothing left to collect, so
    they leave the debtors' list — and the word on the screen says which kind
    of settled it is. "Paid" is true about the collection and misleading about
    the money, because none moved.

    The **status** stays `paid`, so every filter, report and query keeps
    working unchanged. Only the label differs, and it is computed in one place
    because three screens render this idea.
    """
    staff = _bill(clinic, "INV-STAFF2", price=480, discount=100)
    free = _bill(clinic, "INV-FREE", price=0)
    real = _bill(clinic, "INV-REAL2", price=480, paid=480)

    with clinic["app"].app_context():
        assert _read(clinic, staff).status == "paid"
        assert _read(clinic, staff).status_label == "invoices.st_free"
        assert _read(clinic, free).status_label == "invoices.st_free"
        assert _read(clinic, real).status_label == "invoices.st_paid", \
            "an invoice somebody actually paid is being called free"


def test_a_part_paid_bill_is_not_free(clinic):
    """Money moved and money is still owed — neither half is "no charge"."""
    invoice_id = _bill(clinic, "INV-PART2", price=480, paid=240)

    with clinic["app"].app_context():
        assert _read(clinic, invoice_id).status_label == "invoices.st_partial"


def test_the_invoice_screen_says_no_charge(clinic):
    from app.i18n import t

    invoice_id = _bill(clinic, "INV-SHOW", price=480, discount=100)

    page = clinic["sign_in"]("boss").get(
        f"/finance/invoices/{invoice_id}", follow_redirects=True).data.decode()

    with clinic["app"].test_request_context("/"):
        assert t("invoices.st_free") in page
        assert t("invoices.st_paid") not in page


def test_the_appointment_board_says_it_too(clinic):
    """The same distinction where reception actually looks."""
    from datetime import time

    from app.extensions import db
    from app.models import Appointment, Invoice, InvoiceItem, Patient, User

    with clinic["app"].app_context():
        from app.utils.clock import local_today

        doctor = User.query.filter_by(role="doctor").first()
        kid = Patient(patient_number="FREE1", full_name="عمر", gender="male",
                      date_of_birth=date(2015, 1, 1), is_active=True)
        db.session.add(kid)
        db.session.flush()

        today = local_today()
        invoice = Invoice(invoice_number="INV-BFREE", patient_id=kid.id,
                          invoice_date=today)
        db.session.add(invoice)
        db.session.flush()
        db.session.add(InvoiceItem(invoice_id=invoice.id, description="كشف",
                                   unit_price=480, quantity=1,
                                   discount_value=100,
                                   discount_is_percent=True))
        appt = Appointment(patient_id=kid.id, doctor_id=doctor.id,
                           appt_date=today, appt_time=time(16, 0),
                           status="scheduled")
        db.session.add(appt)
        db.session.commit()
        invoice.recalc_status()
        db.session.commit()

        from app.blueprints.appointments.routes import _payment_status

        state = _payment_status([appt], today)[appt.id]

    assert state["state"] == "paid"
    assert state["free"] is True, \
        "the board would tell reception this family paid"


def test_a_real_payment_is_not_marked_free_on_the_board(clinic):
    from datetime import time

    from app.extensions import db
    from app.models import (Appointment, Invoice, InvoiceItem, Patient,
                            Payment, User)

    with clinic["app"].app_context():
        from app.utils.clock import local_today

        doctor = User.query.filter_by(role="doctor").first()
        kid = Patient(patient_number="FREE2", full_name="سارة",
                      gender="female", date_of_birth=date(2016, 1, 1),
                      is_active=True)
        db.session.add(kid)
        db.session.flush()

        today = local_today()
        invoice = Invoice(invoice_number="INV-BPAID", patient_id=kid.id,
                          invoice_date=today)
        db.session.add(invoice)
        db.session.flush()
        db.session.add(InvoiceItem(invoice_id=invoice.id, description="كشف",
                                   unit_price=480, quantity=1))
        db.session.add(Payment(invoice_id=invoice.id, amount=480))
        appt = Appointment(patient_id=kid.id, doctor_id=doctor.id,
                           appt_date=today, appt_time=time(16, 30),
                           status="scheduled")
        db.session.add(appt)
        db.session.commit()
        invoice.recalc_status()
        db.session.commit()

        from app.blueprints.appointments.routes import _payment_status

        state = _payment_status([appt], today)[appt.id]

    assert state["state"] == "paid" and state["free"] is False


def test_the_label_is_worked_out_in_one_place(clinic):
    """Three screens render this idea. Written out three times it would be
    right in two of them."""
    import re

    # Narrowed to the key built **from an invoice**. The list screen also
    # builds `invoices.st_` from its filter tabs, where the value is a status
    # name and not a row — measured, because the first version of this test
    # failed on that and would have been "fixed" by weakening it to nothing.
    pattern = re.compile(r"invoices\.st_'\s*~\s*(inv|invoice)\.status")

    here = os.path.dirname(os.path.abspath(__file__))
    for name in ("finance/invoice_view.html", "finance/invoices.html"):
        with open(os.path.join(here, "..", "app/templates", name),
                  encoding="utf-8") as fh:
            source = fh.read()
        assert not pattern.search(source), \
            f"{name} still builds an invoice's status wording key itself"


def test_the_free_wording_exists_in_both_languages(clinic):
    import json

    here = os.path.dirname(os.path.abspath(__file__))
    for lang in ("ar", "en"):
        with open(os.path.join(here, "..", "app/i18n/locales", f"{lang}.json"),
                  encoding="utf-8") as fh:
            data = json.load(fh)
        assert "st_free" in data["invoices"], lang
        assert "pay_free" in data["appointments"], lang
