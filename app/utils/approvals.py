"""Prior approvals from a payer, and the bill lines that wait for them.

Asked as *«ولو هو تعاقد لازم موافقات على حجات معينة لان دي بتتبعت مع
المطالبات»*. A contract may say that some items — a service, a category, or
everything in a department — are covered only with the payer's approval on
file (`PayerContractRule.needs_approval`).

* When a bill is priced, a line such a rule decides is matched to an approval
  that holds for that child, that payer and that item (or the child's stay),
  and carries its number.
* With none on file the line is **flagged**, not quietly moved onto the
  family: the cover stays as the contract says, the bill shows what is
  missing, and the bill waits out of the claim until the approval arrives.
* Recording the approval links it to every flagged line it answers, and the
  bill is claimable again — with the number the payer asked to see.
"""
from datetime import datetime

from app.extensions import db


def rule_asks(payer, service, day, setting):
    """Whether the contract's deciding rule asks for an approval."""
    if payer is None or service is None or not payer.contracts:
        return False
    contract = payer.active_contract(day)
    rule = contract.rule_for(service, setting) if contract is not None else None
    return bool(rule is not None and rule.needs_approval)


def find(patient_id, payer_id, service_id=None, admission_id=None, day=None):
    """An approval that holds for this item on ``day``, or ``None``: one for
    this very service first, then one for the child's stay as a whole."""
    from app.models import InsuranceApproval

    rows = (InsuranceApproval.query
            .filter(InsuranceApproval.patient_id == patient_id,
                    InsuranceApproval.payer_id == payer_id,
                    InsuranceApproval.status == "approved")
            .order_by(InsuranceApproval.id.desc()).all())
    rows = [a for a in rows if a.holds_on(day)]
    for a in rows:
        if service_id is not None and a.service_id == service_id:
            return a
    for a in rows:
        if a.service_id is None and admission_id and a.admission_id == admission_id:
            return a
    return None


def mark(item, invoice, payer, setting):
    """Give a covered line its approval, or flag that it has none."""
    item.approval_needed = None
    if not rule_asks(payer, item.service, invoice.invoice_date, setting):
        return
    found = find(invoice.patient_id, payer.id, item.service_id,
                 invoice.admission_id, invoice.invoice_date)
    if found is not None:
        item.approval_id = found.id
        item.approval_needed = False
    else:
        item.approval_id = None
        item.approval_needed = True


def link_waiting(approval):
    """Every flagged line this approval answers takes its number. Returns how
    many lines were linked."""
    from app.models import Invoice, InvoiceItem

    if approval is None or approval.status != "approved":
        return 0
    rows = (InvoiceItem.query.join(Invoice, InvoiceItem.invoice_id == Invoice.id)
            .filter(Invoice.patient_id == approval.patient_id,
                    Invoice.payer_id == approval.payer_id,
                    InvoiceItem.approval_needed.is_(True)).all())
    done = 0
    for item in rows:
        invoice = item.invoice
        if not approval.holds_on(invoice.invoice_date):
            continue
        if approval.service_id is not None:
            if item.service_id != approval.service_id:
                continue
        elif not (approval.admission_id and invoice.admission_id == approval.admission_id):
            continue
        item.approval_id = approval.id
        item.approval_needed = False
        if item.cover_note == "awaiting_approval":
            approval._collected = getattr(approval, "_collected", set()) | {invoice}
        done += 1
    db.session.flush()
    return done


def collects(contract, invoice):
    """Whether, while a line waits for its approval, the family pays it now
    (and is refunded on approval) — the contract's choice. **Never an urgent
    emergency child**: their care is not paid ahead, whatever is set."""
    if contract is None or (contract.approval_policy or "wait") != "collect":
        return False
    return not _urgent_emergency(invoice)


def _urgent_emergency(invoice):
    from app.models import EmergencyVisit

    if invoice is None or not invoice.visit_id:
        return False
    return EmergencyVisit.query.filter(EmergencyVisit.visit_id == invoice.visit_id,
                                       EmergencyVisit.urgent.is_(True)).first() is not None


def refund_collected(invoices, user=None):
    """The approval arrived: cover the bills again, and what the family paid
    beyond their share now goes to their own account — never left as a
    negative balance on a bill. Returns ``[(invoice, amount)]`` moved."""
    from app.models import CREDIT_METHOD, Payment, PatientCredit
    from app.utils import billing

    moved = []
    for invoice in invoices:
        if invoice is None or invoice.patient is None:
            continue
        billing.apply_coverage(invoice, invoice.patient)
        db.session.flush()
        surplus = round(invoice.paid - invoice.total, 2)
        if surplus > 0.009:
            pay = Payment(amount=surplus, method=CREDIT_METHOD, kind="refund",
                          received_by=getattr(user, "id", None),
                          notes="بعد الموافقة — للحساب الدائن")
            invoice.payments.append(pay)
            db.session.flush()
            db.session.add(PatientCredit(
                patient_id=invoice.patient_id, kind="in", amount=surplus,
                method="bill", invoice_id=invoice.id, payment_id=pay.id,
                note=f"بعد موافقة الجهة — {invoice.invoice_number}"[:200],
                created_by=getattr(user, "id", None)))
            moved.append((invoice, surplus, pay))
        invoice.recalc_status()
    db.session.flush()
    return moved


def decide(approval, approved, user, number=None, amount=None, valid_until=None,
           note=None):
    """The payer's answer. Approved, it is linked to what was waiting."""
    approval.status = "approved" if approved else "rejected"
    approval.approval_number = (number or "").strip()[:60] or None
    approval.approved_amount = amount
    approval.valid_until = valid_until
    if note:
        approval.note = note.strip()[:255]
    approval.decided_by = getattr(user, "id", None)
    approval.decided_at = datetime.utcnow()
    db.session.flush()
    if not approved:
        return 0
    linked = link_waiting(approval)
    # Lines the family paid while they waited: covered now, the difference
    # to the family's own account (`refund_collected`).
    approval.refunds = refund_collected(sorted(getattr(approval, "_collected", set()),
                                               key=lambda i: i.id), user)
    return linked
