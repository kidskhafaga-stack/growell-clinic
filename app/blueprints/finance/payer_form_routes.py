"""The payers' own forms, and the approval asked for early and sent —
CONTRACTS_PLAN.md ع-٣, ع-٤, ع-٥ (``utils/payer_forms``).

* the forms and their designer: whoever runs the contracts (the finance
  module);
* the filled form, printed: from the visit (the doctor), the booking (the
  desk) and the approvals list (finance) — each by its own module;
* the request from a visit or a booking: by whoever stands at it;
* sending it to the payer: finance.
"""
from flask import abort, current_app, flash, g, redirect, render_template, request, url_for
from flask_login import current_user

from app.blueprints.finance import finance_bp
# The filled form is printed from the visit (the doctor), the booking (the
# desk) and the approvals (finance): a door shared by three modules, so it
# lives with the program's shared pages, not under one module's.
from app.blueprints.main import main_bp
from app.extensions import db
from app.i18n import t
from app.utils.decorators import module_required
from app.utils import payer_forms as pf

MODULE = "finance"


def _lang():
    return getattr(g, "lang", "ar")


@finance_bp.route("/payer-forms", methods=["GET", "POST"])
@module_required(MODULE)
def payer_forms():
    """Every payer's forms, and a new one."""
    from app.models import PayerEntity, PayerForm
    from app.utils.care_setting import SETTINGS

    if request.method == "POST":
        try:
            row = pf.save(None, request.form, request.files, current_user)
        except pf.FormError as why:
            db.session.rollback()
            flash(t("payer_form.err_" + str(why)), "error")
            return redirect(url_for("finance.payer_forms"))
        db.session.commit()
        flash(t("payer_form.made"), "success")
        return redirect(url_for("finance.payer_form", form_id=row.id))
    rows = PayerForm.query.order_by(PayerForm.payer_id, PayerForm.name).all()
    return render_template(
        "finance/payer_forms.html", rows=rows, settings=SETTINGS, pages=pf.PAGES,
        payers=PayerEntity.query.filter_by(is_active=True).order_by(PayerEntity.name).all())


@finance_bp.route("/payer-forms/<int:form_id>", methods=["GET", "POST"])
@module_required(MODULE)
def payer_form(form_id):
    """The designer: the blank form behind, the facts dragged onto it."""
    from app.models import PayerForm
    from app.utils.care_setting import SETTINGS

    row = db.get_or_404(PayerForm, form_id)
    if request.method == "POST":
        try:
            pf.save(row, request.form, request.files, current_user)
        except pf.FormError as why:
            db.session.rollback()
            flash(t("payer_form.err_" + str(why)), "error")
            return redirect(url_for("finance.payer_form", form_id=row.id))
        db.session.commit()
        flash(t("payer_form.saved"), "success")
        return redirect(url_for("finance.payer_form", form_id=row.id))
    return render_template("finance/payer_form_design.html", form=row, fields=pf.FIELDS,
                           settings=SETTINGS, pages=pf.PAGES, aligns=pf.ALIGNS)


def _may_print():
    user = current_user
    return user.is_authenticated and (user.is_admin or any(
        user.can_access(m) for m in ("finance", "visits", "appointments")))


def _filled(form_id):
    """The form and its values for the visit, booking or approval asked for
    — or, with none, the names of the facts (the designer's preview)."""
    from app.models import Appointment, InsuranceApproval, Patient, PayerForm, Visit

    if not _may_print():
        abort(403, description=t("auth.no_permission"))
    form = db.get_or_404(PayerForm, form_id)
    visit = db.session.get(Visit, request.args.get("visit", type=int) or 0)
    appt = db.session.get(Appointment, request.args.get("appointment", type=int) or 0)
    approval = db.session.get(InsuranceApproval, request.args.get("approval", type=int) or 0)
    patient = (visit.patient if visit is not None else appt.patient if appt is not None
               else approval.patient if approval is not None
               else db.session.get(Patient, request.args.get("patient", type=int) or 0))
    if patient is None:
        values = {k: t("payer_form.f_" + k) for k in pf.FIELDS}
    else:
        values = pf.facts(patient, form.payer, visit=visit, appointment=appt,
                          approval=approval, lang=_lang())
    return form, values


@main_bp.route("/payer-forms/<int:form_id>/print")
def payer_form_print(form_id):
    """The form filled for one visit, booking or approval — or, with none,
    with the names of the facts in their places (the designer's preview)."""
    from app.utils import pdf

    if not current_user.is_authenticated:
        return current_app.login_manager.unauthorized()
    form, values = _filled(form_id)
    background = (url_for("static", filename="uploads/patient_docs/" + form.background)
                  if form.background and form.print_background else "")
    return render_template("finance/payer_form_print.html", form=form, values=values,
                           background=background, standalone=False,
                           pdf_url=(url_for("main.payer_form_pdf", form_id=form.id,
                                            **request.args.to_dict())
                                    if pdf.available() else None))


@main_bp.route("/payer-forms/<int:form_id>/pdf")
def payer_form_pdf(form_id):
    """The same filled form as a PDF file — to save, attach or send."""
    from flask import Response

    if not current_user.is_authenticated:
        return current_app.login_manager.unauthorized()
    form, values = _filled(form_id)
    data = pf.page_pdf(form, values)
    if data is None:
        abort(404)
    name = "approval-request.pdf"
    return Response(data, mimetype="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{name}"'})


# ------------------------------------------------------------ early (ع-٤) --
@finance_bp.route("/approvals/ask", methods=["POST"])
def approval_ask():
    """«اطلب الموافقة» from the visit or the booking — by whoever is at it."""
    from app.models import Appointment, Service, Visit

    if not current_user.is_authenticated:
        return current_app.login_manager.unauthorized()
    visit = db.session.get(Visit, request.form.get("visit_id", type=int) or 0)
    appt = db.session.get(Appointment, request.form.get("appointment_id", type=int) or 0)
    need = "visits" if visit is not None else "appointments" if appt is not None else None
    if need is None:
        abort(404)
    if not (current_user.is_admin or current_user.can_access(need)
            or current_user.can_access(MODULE)):
        abort(403, description=t("auth.no_permission"))
    service = db.get_or_404(Service, request.form.get("service_id", type=int) or 0)
    patient = visit.patient if visit is not None else appt.patient
    try:
        row = pf.ask(patient, service, current_user, visit=visit, appointment=appt)
    except pf.FormError as why:
        db.session.rollback()
        flash(t("payer_form.err_" + str(why)), "error")
        return redirect(request.referrer or url_for("main.index"))
    db.session.commit()
    flash(t("payer_form.asked", service=service.name, payer=row.payer.name), "success")
    return redirect(request.referrer or url_for("main.index"))


# ------------------------------------------------------------- sent (ع-٥) --
@finance_bp.route("/approvals/<int:approval_id>/send", methods=["POST"])
@module_required(MODULE)
def approval_send(approval_id):
    """To the payer's approvals desk, by mail or on WhatsApp."""
    from app.models import InsuranceApproval

    row = db.get_or_404(InsuranceApproval, approval_id)
    try:
        address = pf.send(row, request.form.get("via"), current_user, _lang())
    except pf.FormError as why:
        db.session.rollback()
        flash(t("payer_form.err_" + str(why)), "error")
        return redirect(url_for("finance.approvals") + f"#a{row.id}")
    db.session.commit()
    flash(t("payer_form.sent", to=address), "success")
    return redirect(url_for("finance.approvals") + f"#a{row.id}")
