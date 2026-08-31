"""What a dental plan does to the books, and what it refuses to do.

Three rules, in one place, because the plan is reachable from the chart, the
visit and the till and each of them would otherwise answer these for itself.

**Nothing here happens unless the clinic is a dental clinic.** The module gate
already answers 404 on every dental screen, and that is most of the promise —
but the promise was stated about the money specifically: *"لو مش متعلّم
يتعامل مع العيادة ولا يقبل دفعة مقدمة"*. A gate on the screens is a gate on
the way in; this is the rule itself, stated where the money is, so a future
caller that is not a screen cannot walk past it.

**Accepting a plan raises one invoice for the agreed total.** Once. An
accepted plan's invoice is the family's agreement, and re-raising it because
somebody pressed the button twice is how a child is billed for one crown
twice.

**A deposit is a payment against that invoice**, not a new kind of money. The
program already knows how to hold part-paid bills, print them on a statement
and age them; a second, parallel way to owe this clinic money would be a
second place for the running balance to be wrong.
"""
from app.extensions import db


class DentalMoneyError(ValueError):
    """A refusal with a key the screen can name."""


def enabled():
    """Whether this clinic has said it does dentistry."""
    from app.utils.facility import module_enabled

    return module_enabled("dentistry")


def _require_module():
    if not enabled():
        raise DentalMoneyError("module_off")


def minimum_deposit(total):
    """The smallest deposit this clinic will start work on, for ``total``.

    A percentage the clinic sets, and zero by default: a program that invented
    a figure would be making a commercial policy on the clinic's behalf, and
    the clinics that want one disagree about what it is.

    Advisory. Nothing here refuses a smaller payment — see
    :func:`take_deposit`. The number exists so the screen can say what the
    clinic asked for, and so somebody accepting less is doing it on purpose.
    """
    from app.models import Setting

    try:
        percent = float(Setting.get("dental_deposit_percent", "0") or 0)
    except (TypeError, ValueError):
        percent = 0.0
    percent = min(max(percent, 0.0), 100.0)
    return round(round(total or 0, 2) * percent / 100.0, 2)


def accept(plan, user_id=None):
    """Turn an agreed plan into a bill. Returns the invoice.

    The plan's items become the invoice's lines, priced as agreed, so the
    invoice reads back as the plan and not as a single lump nobody can check.
    """
    from app.models import Invoice, InvoiceItem
    from app.utils.finance import generate_invoice_number

    _require_module()
    if plan is None:
        raise DentalMoneyError("no_plan")
    if plan.invoice_id is not None:
        # Not an error worth stopping the day for — the bill exists, which is
        # what the caller wanted. Handing it back is the honest answer to
        # "accept this plan" when it has already been accepted.
        return plan.invoice
    items = plan.live_items
    if not items:
        raise DentalMoneyError("empty_plan")
    if plan.total <= 0:
        raise DentalMoneyError("nothing_to_bill")

    from datetime import datetime

    invoice = Invoice(invoice_number=generate_invoice_number(),
                      patient_id=plan.patient_id, doctor_id=plan.doctor_id,
                      created_by=user_id)
    db.session.add(invoice)
    db.session.flush()
    for item in items:
        db.session.add(InvoiceItem(
            invoice_id=invoice.id, service_id=item.service_id,
            description=_line_name(item), unit_price=item.price, quantity=1))
    plan.invoice_id = invoice.id
    plan.status = "accepted"
    plan.accepted_at = datetime.utcnow()
    db.session.flush()
    invoice.recalc_status()
    return invoice


def _line_name(item):
    """The bill says which tooth. A statement listing four identical
    "filling" lines is one a parent cannot check against their child's mouth.
    """
    if item.tooth:
        return f"{item.description} — {item.tooth}"[:200]
    return item.description[:200]


def take_deposit(plan, amount, method="cash", user_id=None, shift_id=None,
                 account_id=None):
    """Take money against an accepted plan. Returns the payment.

    A deposit is an ordinary payment on the plan's invoice. It is a separate
    function because it is a separate act at the desk — money taken *before*
    any work, on a bill for work not yet done — and because this is the one
    the clinic asked to be impossible when the module is off.

    **It does not enforce the clinic's minimum.** A parent who can pay half
    today and the rest on Sunday is a normal afternoon, and a program that
    refuses their money is a program the desk works around. The minimum is
    shown, and a smaller figure is a decision somebody makes rather than one
    the program makes for them.
    """
    from app.models import Payment

    _require_module()
    if plan is None or plan.invoice_id is None:
        raise DentalMoneyError("not_accepted")
    try:
        amount = round(float(amount), 2)
    except (TypeError, ValueError):
        raise DentalMoneyError("bad_amount") from None
    if amount <= 0:
        raise DentalMoneyError("bad_amount")

    invoice = plan.invoice
    # Never more than the bill. Change handed back at the counter is
    # `tendered`, which is a different column and a different fact; money
    # taken beyond what is owed is a credit this program has nowhere to keep.
    if amount > invoice.balance + 0.009:
        raise DentalMoneyError("over_balance")

    payment = Payment(invoice_id=invoice.id, amount=amount, method=method,
                      kind="payment", received_by=user_id, shift_id=shift_id,
                      account_id=account_id)
    db.session.add(payment)
    db.session.flush()
    invoice.recalc_status()
    return payment
