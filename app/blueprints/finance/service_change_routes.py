"""The service-change wizard — «غيّر الخدمة» on a bill, for whoever may.

``MONEY_SAFETY_PLAN.md`` ف-٨. The owner: *«الى عنده صلاحية انا عايز ادخله فى
ويزر ويطبع ايصال بالارجاع او بدفع فرق الفلوس فى حال تغيير الخدمة ويبقى متضمن
رقم ايصال الخدمة الاصلية ورقم الارجاع»*.

Three steps on one screen:

1. **which line, and what it really was** — any service line on any bill,
   the clinic's or a stay's; reached from the bill, and from the
   appointments board with the visit's line already chosen;
2. **what that does to the money** — the line before and after (price, the
   payer's share, the family's discount, what the family pays) priced the
   way the till prices it, and the one sentence: give back so much, collect
   so much, or nothing;
3. **the money and the paper** — the refund (or the request a manager
   approves, as every refund) or the collection, then a numbered voucher
   that names the original bill's number and its own.

Behind the ``service_change`` capability *and* the till: changing what a
family was charged is a price decision, not a collection.
"""
from flask import (abort, flash, g, redirect, render_template, request,
                   url_for)
from flask_login import current_user

from app.blueprints.finance import finance_bp
from app.extensions import db
from app.i18n import t
from app.models import (ActivityLog, Invoice, InvoiceItem, PAYMENT_METHODS,
                        RefundRequest, Service, ServiceChange, Setting)
from app.utils.decorators import cashier_access, client_ip
from app.utils.money import format_money


def _may_change():
    return current_user.is_admin or current_user.can("service_change")


def _service_choices():
    lang = getattr(g, "lang", "ar")
    rows = (Service.query.filter_by(is_active=True)
            .order_by(Service.category, Service.name).all())
    return [{"id": s.id, "name": (s.name_en if lang == "en" and s.name_en
                                  else s.name),
             "price": format_money(s.price or 0)} for s in rows]


def _lines(invoice):
    """The lines a service can be changed on: ones that bill a service."""
    return [i for i in invoice.items if i.service_id]


def _resolve(invoice):
    """The chosen line and service from the request, or ``(None, None)``."""
    from app.utils import service_settlement as settle

    item_id = request.values.get("item_id", type=int)
    item = db.session.get(InvoiceItem, item_id) if item_id else None
    if item is not None and item.invoice_id != invoice.id:
        item = None
    if item is None:
        appt_id = request.values.get("appt", type=int)
        if appt_id:
            from app.models import Appointment

            appt = db.session.get(Appointment, appt_id)
            found = settle.line_for(appt) if appt is not None else None
            if found is not None and found.invoice_id == invoice.id:
                item = found
    if item is None and len(_lines(invoice)) == 1:
        item = _lines(invoice)[0]
    service_id = request.values.get("service_id", type=int)
    service = db.session.get(Service, service_id) if service_id else None
    return item, service


@finance_bp.route("/invoices/<int:invoice_id>/change-service",
                  methods=["GET", "POST"])
@cashier_access
def service_change_wizard(invoice_id):
    from app.utils import service_settlement as settle

    if not _may_change():
        abort(403, description=t("auth.no_permission"))
    invoice = db.get_or_404(Invoice, invoice_id)
    item, service = _resolve(invoice)
    proposal = (settle.propose_line_change(item, service)
                if item is not None and service is not None else None)

    if request.method == "POST":
        return _apply(invoice, item, service, proposal)

    from app.blueprints.finance.routes import _till_choices
    from app.utils import refunds

    approval = (proposal is not None and proposal.verdict == "refund"
                and refunds.needs_approval(invoice, proposal.amount,
                                           current_user))
    return render_template(
        "finance/service_change.html", invoice=invoice, lines=_lines(invoice),
        item=item, service=service, proposal=proposal,
        services=_service_choices(), methods=PAYMENT_METHODS,
        tills=_till_choices(), approval=approval,
        appt=request.values.get("appt", type=int),
        changes=(ServiceChange.query.filter_by(invoice_id=invoice.id)
                 .order_by(ServiceChange.id).all()))


def _back(invoice, item=None, service=None):
    return redirect(url_for("finance.service_change_wizard",
                            invoice_id=invoice.id,
                            item_id=getattr(item, "id", None),
                            service_id=getattr(service, "id", None)))


def _apply(invoice, item, service, proposal):
    from app.blueprints.finance import routes as fin
    from app.models.service_change import next_number
    from app.utils import holds, refunds
    from app.utils import service_settlement as settle
    from app.utils.sequences import claim

    if item is None or service is None or proposal is None \
            or proposal.verdict == "unbilled":
        flash(t("svcfix.pick_both"), "warning")
        return _back(invoice, item, service)
    if proposal.blocked or fin._period_blocked(invoice.invoice_date):
        return _back(invoice, item, service)
    reason = (request.form.get("reason") or "").strip()[:255]
    if not reason:
        flash(t("svcfix.reason_required"), "warning")
        return _back(invoice, item, service)
    if proposal.verdict == "nothing" and item.service_id == service.id:
        flash(t("svcfix.says_nothing"), "info")
        return _back(invoice, item, service)
    method = (request.form.get("method") or "cash").strip()
    if method not in PAYMENT_METHODS:
        method = "cash"
    collect_now = bool(request.form.get("collect_now"))
    # Cash only enters a drawer inside an open shift — refused before the
    # bill is touched, so a refusal leaves nothing half done.
    if (proposal.verdict == "collect" and collect_now
            and fin._shift_gate_blocked([method])):
        flash(t("shifts.gate_blocked"), "warning")
        return _back(invoice, item, service)

    # Held, then read again: a second change or a payment at the same moment
    # is measured against this one (`utils/holds`).
    holds.bill(invoice)
    before = dict(proposal.before)
    old_service_id = item.service_id
    collected = round(invoice.paid or 0, 2)
    if settle.apply(proposal, service=service, user_id=current_user.id) is None:
        db.session.rollback()
        flash(t("svcfix.cannot_apply"), "danger")
        return _back(invoice, item, service)
    after = settle._state(item)

    change = ServiceChange(
        invoice_id=invoice.id, item_id=item.id,
        old_service_id=old_service_id, old_description=before["description"],
        old_price=before["price"], old_payer=before["payer"],
        old_family=before["family"],
        new_service_id=service.id, new_description=after["description"],
        new_price=after["price"], new_payer=after["payer"],
        new_family=after["family"], collected=collected,
        difference=round((invoice.total or 0) - collected, 2),
        reason=reason, status="nothing", created_by=current_user.id)
    claim(change, "number", next_number)
    note = f"{change.number} — {reason}"[:200]
    payment = None

    if change.difference < 0:
        amount = round(min(-change.difference, invoice.paid or 0), 2)
        if amount > 0 and refunds.needs_approval(invoice, amount,
                                                 current_user):
            req = RefundRequest(invoice_id=invoice.id, amount=amount,
                                method=method, reason=note,
                                requested_by=current_user.id)
            db.session.add(req)
            db.session.flush()
            change.refund_request_id = req.id
            change.status = "awaiting_approval"
        elif amount > 0:
            payment, _scope, _closed = fin._post_refund(
                invoice, amount, method, note, user_id=current_user.id)
            change.status = "settled"
    elif change.difference > 0:
        change.status = "owed"
        if collect_now:
            payment, _left, _change = fin._take_payment(
                invoice, str(change.difference), method, change.difference,
                fin._current_shift_id(), notes=note,
                account_id=request.form.get("account_id", type=int))
            if payment is not None:
                change.status = "settled"
    if payment is not None:
        db.session.flush()
        change.payment_id = payment.id
    invoice.recalc_status()

    fin._log_invoice_change(
        invoice, "service_change",
        f"{change.number}: {before['description']} {before['family']} → "
        f"{after['description']} {after['family']}")
    ActivityLog.record("service_change.done", user_id=current_user.id,
                       entity="invoice", entity_id=invoice.id,
                       detail=f"{change.number} {invoice.invoice_number} "
                              f"{change.difference}",
                       ip_address=client_ip())
    db.session.commit()
    # The bill's journal entry follows the corrected bill, and the money
    # its own entry — the same two calls the till makes.
    fin._post_journal_safe("invoice", invoice)
    if payment is not None:
        fin._post_journal_safe("payment", payment)

    flash(t("svcfix.done_" + change.status, number=change.number,
            v=format_money(change.amount)),
          "info" if change.status in ("awaiting_approval", "owed")
          else "success")
    return redirect(url_for("finance.service_change_receipt",
                            change_id=change.id))


@finance_bp.route("/service-changes/<int:change_id>/receipt")
@cashier_access
def service_change_receipt(change_id):
    """The voucher: the original bill's number, this change's number, the
    service before and after, and the money that followed."""
    change = db.get_or_404(ServiceChange, change_id)
    return render_template(
        "finance/service_change_receipt.html", change=change,
        invoice=change.invoice,
        thermal_footer=(Setting.get("thermal_footer_text") or "").strip(),
        back_url=url_for("finance.invoice_view", invoice_id=change.invoice_id))


def settle_request(req, approved, payment=None):
    """A manager decided a refund a service change asked for: the change's
    voucher now says so. Called from the refund-request decision."""
    for change in ServiceChange.query.filter_by(refund_request_id=req.id):
        if approved:
            change.status = "settled"
            change.payment_id = getattr(payment, "id", None)
        else:
            change.status = "rejected"
