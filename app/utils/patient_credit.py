"""The patient's own account — taking money on it, using it, giving it back.

See `app/models/patient_credit.py` for what the account is. The rules here:

**Where it shows.** A hospital and a dental clinic are where families pay
ahead, so there it is on by itself; a clinic that has neither sees the screen
it always saw. The clinic can turn it on or off in the policies
(``patient_credit_mode``: blank = that default, ``on``, ``off``). And a family
that *has* a balance is shown it whatever the switch says — money the clinic
holds is never hidden by a setting.

**Never more than there is.** A bill is paid from the account up to what the
bill still owes and what the account holds, whichever is less; money is
handed back up to the balance. A refusal, never a quiet trim: the desk typed
a figure, and paying a different one is a decision somebody has to see.

**The drawer counts it.** Cash taken on account is in the drawer, and cash
handed back left it — both inside the shift, like any money at the desk. A
bill paid from the account moves no cash, so its payment carries no shift:
the drawer counted that money once, on the day it came in.
"""
from app.extensions import db


class CreditError(ValueError):
    """A refusal with a key the screen can name (``credit.err_<key>``)."""


MODE_KEY = "patient_credit_mode"


def enabled():
    """Whether this clinic uses the patient account."""
    from app.models import Setting
    from app.utils.facility import module_enabled

    mode = (Setting.get(MODE_KEY) or "").strip()
    if mode == "on":
        return True
    if mode == "off":
        return False
    return module_enabled("beds") or module_enabled("dentistry")


def balances(patient_ids):
    """``{patient_id: balance}`` for the ones that have rows, in one query."""
    from app.models import PatientCredit

    ids = [i for i in set(patient_ids or []) if i]
    if not ids:
        return {}
    sign = db.case((PatientCredit.kind == "in", PatientCredit.amount),
                   else_=-PatientCredit.amount)
    rows = (db.session.query(PatientCredit.patient_id, db.func.sum(sign))
            .filter(PatientCredit.patient_id.in_(ids))
            .group_by(PatientCredit.patient_id).all())
    return {pid: round(total or 0, 2) for pid, total in rows}


def balance(patient_id):
    return balances([patient_id]).get(patient_id, 0.0)


def shown_for(patient_id, held=None):
    """Whether this family's account belongs on the screen."""
    held = balance(patient_id) if held is None else held
    return enabled() or abs(held) > 0.009


def rows(patient_id):
    """The account's lines, newest first."""
    from app.models import PatientCredit

    return (PatientCredit.query.filter_by(patient_id=patient_id)
            .order_by(PatientCredit.created_at.desc(), PatientCredit.id.desc())
            .all())


def for_stay(admission):
    """``{"deposited", "charged", "paid", "owing", "held", "short"}`` for one
    stay: what the family put down for it, what the stay's bill has come to,
    and whether what they hold still covers what is owed."""
    from app.models import Invoice, PatientCredit

    deposited = round(sum(
        r.amount for r in PatientCredit.query.filter_by(
            admission_id=admission.id, kind="in").all()), 2)
    bills = Invoice.query.filter_by(admission_id=admission.id).all()
    charged = round(sum(i.total for i in bills), 2)
    owing = round(sum(i.balance for i in bills), 2)
    held = balance(admission.patient_id)
    return {"deposited": deposited, "charged": charged,
            "paid": round(sum(i.paid for i in bills), 2), "owing": owing,
            "held": held, "short": round(max(owing - held, 0.0), 2),
            "bills": bills}


def _amount(raw):
    try:
        value = round(float(raw), 2)
    except (TypeError, ValueError):
        raise CreditError("bad_amount") from None
    if value <= 0:
        raise CreditError("bad_amount")
    return value


def take(patient, amount, method="cash", user=None, shift_id=None,
         account_id=None, admission_id=None, note=None):
    """Money received on account. Returns the row."""
    from app.models import PAYMENT_METHODS, PatientCredit

    if patient is None:
        raise CreditError("no_patient")
    amount = _amount(amount)
    if method not in PAYMENT_METHODS:
        raise CreditError("bad_method")
    row = PatientCredit(patient_id=patient.id, kind="in", amount=amount,
                        method=method, account_id=account_id,
                        shift_id=shift_id if method == "cash" else None,
                        admission_id=admission_id,
                        note=(note or "").strip()[:200] or None,
                        created_by=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def apply_to(invoice, amount=None, user=None):
    """Pay ``invoice`` from its patient's account. ``None`` means as much as
    the bill owes and the account holds. Returns the payment on the bill."""
    from app.models import CREDIT_METHOD, Payment, PatientCredit

    if invoice is None or invoice.patient_id is None:
        raise CreditError("no_patient")
    if invoice.status == "refunded":
        raise CreditError("closed")
    held = balance(invoice.patient_id)
    owed = round(invoice.balance, 2)
    if amount in (None, ""):
        amount = min(held, owed)
        if amount <= 0:
            raise CreditError("nothing_held" if held <= 0 else "nothing_owed")
    amount = _amount(amount)
    if amount > held + 0.009:
        raise CreditError("over_held")
    if amount > owed + 0.009:
        raise CreditError("over_owed")
    payment = Payment(amount=amount, method=CREDIT_METHOD, kind="payment",
                      received_by=getattr(user, "id", None),
                      notes="من رصيد المريض")
    invoice.payments.append(payment)
    db.session.flush()
    db.session.add(PatientCredit(patient_id=invoice.patient_id, kind="applied",
                                 amount=amount, invoice_id=invoice.id,
                                 payment_id=payment.id,
                                 admission_id=invoice.admission_id,
                                 created_by=getattr(user, "id", None)))
    db.session.flush()
    invoice.recalc_status()
    return payment


def give_back(patient, amount, method="cash", user=None, shift_id=None,
              account_id=None, note=None):
    """Hand back part or all of what the account holds. Returns the row."""
    from app.models import PAYMENT_METHODS, PatientCredit

    if patient is None:
        raise CreditError("no_patient")
    amount = _amount(amount)
    if method not in PAYMENT_METHODS:
        raise CreditError("bad_method")
    if amount > balance(patient.id) + 0.009:
        raise CreditError("over_held")
    row = PatientCredit(patient_id=patient.id, kind="refund", amount=amount,
                        method=method, account_id=account_id,
                        shift_id=shift_id if method == "cash" else None,
                        note=(note or "").strip()[:200] or None,
                        created_by=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def cash_by_shift(shift_ids):
    """``{shift_id: net cash}`` the account moved through each drawer —
    taken in, less handed back."""
    from app.models import PatientCredit

    ids = [i for i in (shift_ids or []) if i]
    if not ids:
        return {}
    sign = db.case((PatientCredit.kind == "in", PatientCredit.amount),
                   else_=-PatientCredit.amount)
    found = (db.session.query(PatientCredit.shift_id, db.func.sum(sign))
             .filter(PatientCredit.shift_id.in_(ids),
                     PatientCredit.method == "cash",
                     PatientCredit.kind.in_(("in", "refund")))
             .group_by(PatientCredit.shift_id).all())
    return {sid: round(total or 0, 2) for sid, total in found}


def _ready():
    """The chart has its 2030 — an install seeded before the account existed
    gets it topped up here rather than posting nowhere."""
    from app.models import Account
    from app.utils import accounting

    if Account.query.filter_by(code="2030").first() is None \
            and Account.query.first() is not None:
        accounting.ensure_seeded()


def post(row, user_id=None):
    """The journal entry for money in or out of the account. Best effort, the
    way every money posting is: a ledger hiccup never undoes the money."""
    from app.utils import accounting

    try:
        _ready()
        who = row.patient.display_name("ar") if row.patient else ""
        till = accounting.till_code(row)
        if row.kind == "in":
            lines = [(till, row.amount, 0, who), ("2030", 0, row.amount, who)]
            memo = f"دفعة مقدّمة — {who}"
        elif row.kind == "refund":
            lines = [("2030", row.amount, 0, who), (till, 0, row.amount, who)]
            memo = f"رد رصيد — {who}"
        else:
            return None
        return accounting.post_entry("patient_credit", row.id, memo, lines,
                                     user_id=user_id)
    except Exception:  # noqa: BLE001
        db.session.rollback()
        return None


def post_applied(payment, user_id=None):
    """The bill's payment from the account: Dr 2030 / Cr patients."""
    from app.utils import billing

    try:
        _ready()
    except Exception:  # noqa: BLE001
        db.session.rollback()
    billing.post_to_ledger("payment", payment, user_id=user_id)
