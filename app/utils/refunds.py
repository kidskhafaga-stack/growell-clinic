"""Money going back out: what it closes, who must agree, and whose share moves.

Written after a clinic looked at one invoice carrying seven movements —
collect, refund, collect, refund, collect — and asked, reasonably, *"أنا خلاص
عملت استرداد، ينفع يبقى فيه تحصيل تاني في ساعته؟"*

Three rules live here, in one module, because the refund is reachable from
three screens and each of them used to answer these questions for itself.

**A full refund closes the invoice.** The service was cancelled. Charging for
it again is a new decision, and a new decision belongs on a new invoice —
otherwise the patient's statement is a column of numbers nobody can read back
into events. Before this, a fully refunded invoice had ``paid == 0`` and so
read as *unpaid*: back in the "who still owes" list, offering a Collect
button, with the money already handed over the counter.

**A full refund waits for a manager; a small partial one does not.** Handing
back fifty pounds of a vaccine difference should not stop the queue while
somebody is found. Handing back the whole visit should not be one person's
decision. The line between them is a figure the clinic sets, so a clinic that
wants every refund approved sets it to zero and gets exactly the behaviour it
had before.

**And the doctor's share follows the money.** A refund of half an invoice
takes half the doctor's share of it. This is the half that had no
implementation at all: ``commission_amount`` is a snapshot written when the
line was billed, and nothing subtracted from it, so a clinic that refunded a
visit still owed the doctor their cut of money it no longer had.
"""
from app.extensions import db

# Below this, a partial refund does not wait for anybody. A clinic that wants
# every refund approved sets it to 0.
DEFAULT_NO_APPROVAL_UNDER = 100.0


def approval_threshold():
    """The figure under which a partial refund goes through unapproved."""
    from app.models import Setting

    raw = Setting.get("refund_no_approval_under", str(DEFAULT_NO_APPROVAL_UNDER))
    try:
        return max(float(raw), 0.0)
    except (TypeError, ValueError):
        return DEFAULT_NO_APPROVAL_UNDER


def scope_of(invoice, amount):
    """``"full"`` or ``"partial"`` for refunding ``amount`` off ``invoice``.

    Full means nothing collected is left on it once this goes back: the
    cashier is handing back everything they hold against this bill, which is
    the act worth a manager's eye whatever the figure happens to be.

    **This is not the same question as whether the invoice closes.** A patient
    who paid 80 of a 200 bill and gets that 80 back has had a full refund of
    what they paid, and still owes 200 — see ``Invoice.fully_refunded``, which
    measures against the total. One decides who signs; the other decides
    whether the bill is finished.
    """
    return "full" if round((invoice.paid or 0) - (amount or 0), 2) <= 0 else "partial"


def needs_approval(invoice, amount, user):
    """Does this refund have to wait for a manager?

    An admin never waits — they *are* the approval. Everybody else waits for a
    full refund, and for a partial one at or above the clinic's threshold.

    The clinic can still turn the whole workflow off, which is the setting
    that was already here and is what a clinic without a manager on site needs.
    """
    from app.models import Setting

    if Setting.get("refund_approval_required", "1") == "0":
        return False
    if getattr(user, "is_admin", False):
        return False
    if scope_of(invoice, amount) == "full":
        return True
    return round(amount or 0, 2) >= approval_threshold()


def doctor_share_of(invoice, amount):
    """What refunding ``amount`` takes off the doctor's share of ``invoice``.

    Proportional, because that is the only split that holds together when an
    invoice carries several lines at different commission rates and the refund
    is not against any one of them. Refund a third of the money and a third of
    the doctor's share goes with it.

    Zero when the invoice has no doctor, or came to nothing — a share of
    nothing is nothing, and dividing by it is how this sort of helper
    announces itself in production.
    """
    total = round(invoice.total or 0, 2)
    share = round(invoice.doctor_share_total or 0, 2)
    if total <= 0 or share <= 0 or not amount:
        return 0.0
    return round(share * min(round(amount, 2), total) / total, 2)


def refunded_share(invoice):
    """The doctor's share of everything already refunded on this invoice."""
    return doctor_share_of(invoice, invoice.refunded)


def close_if_emptied(invoice):
    """Stamp the invoice closed when the last of its money has gone back.

    Called after the refund is on the invoice. Returns whether it closed, so
    the caller can say so — a cashier who has just refunded the whole visit
    needs to know the invoice will not take another payment, at the moment
    they do it and not when they next press Collect.
    """
    from datetime import datetime

    if invoice.refunded_at is not None:
        return False
    if not invoice.fully_refunded:
        return False
    invoice.refunded_at = datetime.utcnow()
    invoice.recalc_status()
    return True


def notify_doctor(invoice, payment, amount, *, scope, reason=None, user_id=None):
    """Write the doctor's copy of this refund. Returns the notice, or None.

    None when there is nobody to tell — an invoice with no doctor on it, a
    dressing done by the nurse. A refund on one of those is still a refund; it
    simply has no share to move and nobody whose account moved.
    """
    from app.models import RefundNotice

    if invoice.doctor_id is None:
        return None
    notice = RefundNotice(
        invoice_id=invoice.id,
        payment_id=payment.id if payment is not None else None,
        doctor_id=invoice.doctor_id,
        amount=round(amount or 0, 2),
        doctor_amount=doctor_share_of(invoice, amount),
        scope=scope if scope in ("full", "partial") else "partial",
        reason=(reason or "").strip()[:200] or None,
        refunded_by=user_id,
    )
    db.session.add(notice)
    return notice
