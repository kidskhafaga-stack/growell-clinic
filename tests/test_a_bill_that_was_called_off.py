"""A refunded visit that the program still asked the family to pay for.

Found while checking the money side was sound before building the dentistry
module, which turns every patient into a running account of part-payments.

Closing an invoice by refunding it was added last week: the service was
cancelled, the money went back, and the bill is finished. What was not
changed is the one line every screen reads to answer *"how much does this
family owe?"* —

    balance = total - paid

A cancelled visit that was paid for and refunded has ``total`` 200 and
``paid`` 0, because the payment and the refund cancel out. So the subtraction
said 200, on an invoice whose own status said ``refunded``. The same row
answered "this is settled" and "they owe you 200" at the same time, and every
screen that adds balances up believed the second one — the profile card, the
appointment board, the exports, and the statement printed for the family.

The status filters were right by accident: they ask for ``unpaid`` or
``partial``, and a closed invoice is neither. Anything that reached for the
number itself got the wrong answer.

The printed statement is the worst of them, because it is the one that leaves
the building. It does its own arithmetic — charge 200, pay 200, refund 200 —
and that genuinely adds to 200 owed unless the cancellation is on the page.
So it is put on the page, as its own line, rather than by quietly dropping
the three rows: a statement is a history as well as a total, and "billed,
paid, refunded, cancelled" is exactly what the reader needs to see.
"""
import re
from datetime import date, datetime

import pytest


def _bill(clinic, amount=200, number="INV-1"):
    from app.models import Invoice, InvoiceItem

    with clinic["app"].app_context():
        db = clinic["db"]
        invoice = Invoice(invoice_number=number,
                          patient_id=clinic["ids"]["child"],
                          invoice_date=date(2026, 8, 1))
        db.session.add(invoice)
        db.session.flush()
        db.session.add(InvoiceItem(invoice_id=invoice.id, description="كشف",
                                   unit_price=amount, quantity=1))
        db.session.commit()
        return invoice.id


def _pay(clinic, invoice_id, amount, kind="payment"):
    from app.models import Payment

    with clinic["app"].app_context():
        clinic["db"].session.add(Payment(
            invoice_id=invoice_id, amount=amount, kind=kind,
            paid_at=datetime(2026, 8, 2)))
        clinic["db"].session.commit()


def _close(clinic, invoice_id):
    """What a full refund does to the invoice."""
    from app.models import Invoice

    with clinic["app"].app_context():
        invoice = clinic["db"].session.get(Invoice, invoice_id)
        invoice.refunded_at = datetime(2026, 8, 2, 12)
        invoice.recalc_status()
        clinic["db"].session.commit()


def _state(clinic, invoice_id):
    from app.models import Invoice

    with clinic["app"].app_context():
        invoice = clinic["db"].session.get(Invoice, invoice_id)
        return {"status": invoice.status, "total": invoice.total,
                "paid": invoice.paid, "balance": invoice.balance}


def _statement_text(clinic):
    boss = clinic["sign_in"]("boss")
    page = boss.get(
        f"/reports/statement/{clinic['ids']['child']}").get_data(as_text=True)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page))


def _figure(text, label):
    """The number printed after ``label``, as a float.

    Read out rather than searched for. Asserting `"0.00" in tail` passes on
    "200.00" — the substring is right there in it — so two of these tests
    could not fail until the figure was parsed instead.
    """
    after = text.split(label)[-1]
    match = re.search(r"(-?[\d,]+\.\d\d)", after)
    assert match, f"no figure after {label!r}: {after[:80]!r}"
    return float(match.group(1).replace(",", ""))


@pytest.fixture
def cancelled(clinic):
    """The reported shape: billed, paid in full, refunded in full."""
    invoice = _bill(clinic)
    _pay(clinic, invoice, 200)
    _pay(clinic, invoice, 200, kind="refund")
    _close(clinic, invoice)
    return invoice


# ------------------------------------------------ the number every screen reads
def test_a_cancelled_bill_is_not_a_debt(clinic, cancelled):
    """The whole fault in one assertion."""
    assert _state(clinic, cancelled)["balance"] == 0.0


def test_the_invoice_does_not_contradict_itself(clinic, cancelled):
    """It said `refunded` and `owes 200` on the same row."""
    state = _state(clinic, cancelled)
    assert state["status"] == "refunded"
    assert state["balance"] == 0.0


def test_the_profile_does_not_add_it_to_what_the_family_owes(clinic, cancelled):
    """The card reception looks at when a family walks in.

    Asserted on the sum the route builds, which is what the card renders —
    scanning the page for "200" would also match the invoice's own total in
    the table below it, and pass whatever the card said.
    """
    from app.models import Invoice

    with clinic["app"].app_context():
        invoices = Invoice.query.filter_by(
            patient_id=clinic["ids"]["child"]).all()
        assert round(sum(i.balance for i in invoices), 2) == 0.0


# ------------------------------------------------------ a real debt survives --
def test_a_bill_still_owed_is_untouched(clinic):
    """The fix must not close anything else. Nothing was refunded here."""
    invoice = _bill(clinic, 200, "INV-OPEN")
    _pay(clinic, invoice, 80)
    assert _state(clinic, invoice)["balance"] == 120.0


def test_a_returned_deposit_leaves_the_bill_owing(clinic):
    """The case that decides this is measured against the total, not against
    what happened to be collected.

    Paid 80 of 200 and had that 80 back: everything they paid was returned,
    the invoice is *not* closed, and they still owe the whole 200. Closing it
    here would wipe a real debt on the strength of a returned deposit.
    """
    invoice = _bill(clinic, 200, "INV-DEP")
    _pay(clinic, invoice, 80)
    _pay(clinic, invoice, 80, kind="refund")
    state = _state(clinic, invoice)
    assert state["status"] != "refunded"
    assert state["balance"] == 200.0


# ------------------------------------------------- the page that leaves the building
def test_the_printed_statement_settles_at_nothing(clinic, cancelled):
    """It did its own arithmetic — charge 200, pay 200, refund 200 — and
    handed the family a bill for a visit that was called off."""
    assert _figure(_statement_text(clinic), "الرصيد المستحق") == 0.0


def test_the_statement_still_shows_what_happened(clinic, cancelled):
    """Settled at nothing, not silent about it. A statement is a history as
    well as a total, and a reader who sees a zero with no rows cannot tell a
    cancelled visit from a visit that never happened."""
    text = _statement_text(clinic)
    assert "فاتورة" in text
    assert "سداد" in text
    assert "إلغاء الفاتورة" in text


def test_the_cancelled_charge_is_not_counted_as_billed(clinic, cancelled):
    """The summary line at the foot. Counting it would say the clinic billed
    200 this period and collected nothing."""
    assert _figure(_statement_text(clinic), "إجمالي الفواتير") == 0.0


def test_an_ordinary_statement_is_unchanged(clinic):
    """No cancellation, no extra row, and the balance is what is owed."""
    invoice = _bill(clinic, 3000, "INV-PLAN")
    _pay(clinic, invoice, 1000)
    text = _statement_text(clinic)
    assert "إلغاء الفاتورة" not in text
    assert _figure(text, "الرصيد المستحق") == 2000.0
