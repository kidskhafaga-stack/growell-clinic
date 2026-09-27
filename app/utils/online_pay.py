"""Asking for a payment through a gateway, and believing the answer.

The same for every gateway (``app/utils/gateways``), and written once on
purpose: the rules here are the ones that decide whether money is counted.

* **Believed only when proved.** A callback the gateway cannot be shown to
  have sent is refused before anything is read (the gateway's ``prove``). A
  page the family's browser lands on afterwards is never taken as proof —
  anybody can type that address.
* **Once.** Gateways send the same confirmation more than once, by design;
  the second changes nothing. The reference is claimed in the database, so
  two copies arriving together are still one payment.
* **The amount that was asked.** A proved payment of a different amount or
  currency is not written onto the bill. It is kept, marked ``mismatch``,
  and put in front of a person — the plan's rule that "unconfirmed" is a
  state of its own, not an exception.
* **Where the desk's money goes.** A proved payment is an ordinary
  :class:`Payment` on the invoice, in the gateway's own "under collection"
  account — like card takings, it is owed to the clinic until the gateway
  settles into the bank — and posted to the ledger by the same call the till
  uses.
"""
import secrets
from datetime import datetime

from app.extensions import db
from app.models import ActivityLog, Invoice, OnlinePayment, Payment, Setting
from app.models.online_payment import ONLINE_METHOD
from app.utils.gateways import GatewayError

#: Money is compared to the piastre.
_CENT = 0.005

#: States a proved payment may still be written from.
PAYABLE_FROM = ("created", "pending", "failed", "expired", "cancelled")


def new_reference():
    """Ours, unguessable, and short enough to read over the phone."""
    return "PP" + secrets.token_hex(6).upper()


def balance(invoice):
    """What is still owed on the bill — what a link asks for."""
    return round((invoice.total or 0) - (invoice.paid or 0), 2)


def ask(invoice, gateway, user_id, return_url, notify_url):
    """Open a payment for what is left on ``invoice`` with ``gateway``.

    Returns the :class:`OnlinePayment`. It is saved whatever the gateway
    said — a refusal is kept with the gateway's words, so the desk can see
    what happened and nothing is left half-asked.
    """
    owed = balance(invoice)
    if owed <= 0:
        raise ValueError("nothing_owed")
    row = OnlinePayment(invoice_id=invoice.id, provider=gateway.name,
                        reference=new_reference(), amount=owed,
                        currency=Setting.get("currency", "EGP") or "EGP",
                        status="created", created_by=user_id)
    db.session.add(row)
    db.session.flush()
    try:
        got = gateway.checkout(row, return_url(row), notify_url(row))
    except GatewayError as exc:
        row.status, row.error = "failed", str(exc)[:300]
    else:
        row.status = "pending"
        row.checkout_url = got.url
        row.pay_code = got.code
        row.expires_at = got.expires_at
        row.provider_ref = got.provider_ref
    ActivityLog.record("online_payment.ask", user_id=user_id,
                       entity="invoice", entity_id=invoice.id,
                       detail=f"{row.provider} {row.reference} {row.amount} "
                              f"{row.status}")
    db.session.commit()
    return row


def receive(gateway, event):
    """Act on a proved :class:`~app.utils.gateways.Event`. Returns what was
    done: ``paid``, ``again``, ``mismatch``, ``closed``, ``noted`` or
    ``unknown``.

    ``gateway`` is the one whose webhook it arrived at: a reference opened
    with another gateway is not this one's to settle.
    """
    row = OnlinePayment.query.filter_by(reference=event.reference,
                                        provider=gateway.name).first()
    if row is None:
        return "unknown"
    if row.status == "paid":
        return "again"
    if event.status != "paid":
        if event.status in ("failed", "expired") and row.is_open:
            _claim(row, event.status, event)
            db.session.commit()
            return "closed"
        return "noted"

    if not _same_money(row, event):
        if _claim(row, "mismatch", event, PAYABLE_FROM):
            ActivityLog.record(
                "online_payment.mismatch", entity="invoice",
                entity_id=row.invoice_id,
                detail=f"{row.reference}: asked {row.amount} {row.currency}, "
                       f"gateway says {event.amount} {event.currency}")
        db.session.commit()
        return "mismatch"

    # Claimed before anything is written: of two copies of the same
    # confirmation arriving together, one finds the row still unclaimed.
    # From a closed row too — a first attempt that failed, a link we let
    # expire: if the gateway proves the money arrived after all, it arrived,
    # and a bill left owing money the family has paid is the worse mistake.
    # Only ``mismatch`` stays with the person looking at it.
    if not _claim(row, "paid", event, PAYABLE_FROM):
        db.session.rollback()
        return "again"
    invoice = db.session.get(Invoice, row.invoice_id)
    payment = Payment(amount=row.amount, method=ONLINE_METHOD,
                      account_id=clearing_till(gateway).id,
                      notes=f"{gateway.name} {row.reference}"[:200])
    invoice.payments.append(payment)
    db.session.flush()
    row.payment_id = payment.id
    invoice.recalc_status()
    ActivityLog.record("online_payment.paid", entity="invoice",
                       entity_id=invoice.id,
                       detail=f"{gateway.name} {row.reference} {row.amount}")
    db.session.commit()
    from app.utils.billing import post_to_ledger

    post_to_ledger("payment", payment)
    db.session.commit()
    return "paid"


def _same_money(row, event):
    if event.amount is None:
        return False
    if abs(float(event.amount) - float(row.amount)) > _CENT:
        return False
    return (event.currency or row.currency).upper() == row.currency.upper()


def _claim(row, status, event, allowed=("created", "pending")):
    """Move ``row`` to ``status``, only if it is still in one of ``allowed``.
    True if this call did it."""
    changed = (OnlinePayment.query
               .filter(OnlinePayment.id == row.id,
                       OnlinePayment.status.in_(allowed))
               .update({"status": status,
                        "provider_ref": event.provider_ref or row.provider_ref,
                        "reported_amount": event.amount,
                        "reported_currency": event.currency,
                        "paid_at": datetime.utcnow()
                        if status == "paid" else None},
                       synchronize_session=False))
    db.session.refresh(row)
    return changed == 1


def clearing_till(gateway):
    """The gateway's "under collection" account: made the first time money
    comes through it, with its place in the chart of accounts, and settling
    into the bank like card takings do."""
    from app.models import CashAccount
    from app.utils import accounting

    key = f"pay_{gateway.name}_till"
    till_id = Setting.get(key, "")
    till = db.session.get(CashAccount, int(till_id)) if till_id.isdigit() \
        else None
    if till is not None:
        return till
    bank = CashAccount.query.filter_by(code="1020").first()
    till = CashAccount(
        code=accounting.next_till_code(),
        name=f"{gateway.label_ar} — تحت التحصيل",
        name_en=f"{gateway.label_en} — under collection",
        kind="clearing", is_active=True,
        settles_into_id=bank.id if bank else None,
        sort_order=(db.session.query(db.func.max(CashAccount.sort_order))
                    .scalar() or 0) + 1)
    db.session.add(till)
    db.session.flush()
    accounting.ensure_till_account(till)
    Setting.set(key, str(till.id))
    return till
