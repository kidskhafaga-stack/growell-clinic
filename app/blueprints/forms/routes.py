"""The clinic's own forms (``FORM_BUILDER_PLAN.md``).

Designing — ``/forms`` (the list), ``/forms/new``, ``/forms/<id>`` (the form
and its fields), behind ``forms_design``.

Filling — ``/forms/patient/<pid>`` (the forms this person may fill for this
child, here), ``/forms/<id>/fill``, ``/forms/entry/<id>`` (read and correct),
``/forms/entry/<id>/print``, by the form's own audience.

Counting — ``/forms/<id>/summary`` (and ``.csv``), for whoever may fill it.

Every rule is in ``utils/custom_forms``.
"""
import csv
import io
from datetime import timedelta

from flask import (Response, abort, flash, g, redirect, render_template,
                   request, url_for)
from flask_login import current_user, login_required

from app.blueprints.forms import forms_bp
from app.extensions import db
from app.i18n import t
from app.models import ActivityLog, CustomForm, FormEntry, Patient
from app.utils import custom_forms as cf
from app.utils.clock import local_today
from app.utils.decorators import client_ip, module_required


def _design_only():
    if not cf.may_design(current_user):
        abort(403)


def _say(err):
    if err.field:
        flash(f"{t(err.key)}: {cf.label(err.field)}", "danger")
    else:
        flash(t(err.key), "danger")


def _log(action, form, detail=None):
    ActivityLog.record(action, user_id=current_user.id, entity="custom_form",
                       entity_id=form.id, detail=detail,
                       ip_address=client_ip())


# ------------------------------------------------------------- design ----
@forms_bp.route("/")
@login_required
def index():
    designer = cf.may_design(current_user)
    rows = CustomForm.query.order_by(CustomForm.is_active.desc(),
                                     CustomForm.name_ar).all()
    if not designer:
        rows = [f for f in rows if f.is_active and cf.may_fill(current_user, f)]
        if not rows:
            abort(403)
    counts = {f.id: f.entries.count() for f in rows}
    return render_template("forms/index.html", rows=rows, counts=counts,
                           designer=designer, places=cf.places_offered())


@forms_bp.route("/new", methods=["POST"])
@login_required
def new():
    _design_only()
    try:
        form = cf.new_form(request.form, current_user)
        db.session.flush()
    except cf.FormError as err:
        db.session.rollback()
        _say(err)
        return redirect(url_for("forms.index"))
    _log("form.new", form, form.name_ar)
    db.session.commit()
    return redirect(url_for("forms.design", form_id=form.id))


@forms_bp.route("/<int:form_id>", methods=["GET", "POST"])
@login_required
def design(form_id):
    _design_only()
    form = db.get_or_404(CustomForm, form_id)
    if request.method == "POST":
        action = request.form.get("action")
        key = request.form.get("key")
        try:
            if action == "form":
                cf.edit_form(form, request.form)
            elif action == "add":
                cf.add_field(form, request.form)
            elif action == "field":
                cf.edit_field(form, key, request.form)
            elif action in ("up", "down"):
                cf.move_field(form, key, 1 if action == "down" else -1)
            elif action == "hide":
                cf.hide_field(form, key, True)
            elif action == "show":
                cf.hide_field(form, key, False)
            elif action in ("close", "open"):
                form.is_active = action == "open"
            else:
                abort(400)
        except cf.FormError as err:
            db.session.rollback()
            _say(err)
            return redirect(url_for("forms.design", form_id=form.id))
        _log(f"form.{action}", form, key)
        db.session.commit()
        flash(t("forms.saved"), "success")
        anchor = f"#f-{key}" if key and action not in ("hide",) else ""
        return redirect(url_for("forms.design", form_id=form.id) + anchor)
    return render_template("forms/design.html", form=form,
                           places=cf.places_offered(), types=cf.TYPES,
                           has_entries=form.entries.count() > 0)


# --------------------------------------------------------------- fill ----
def _context(patient):
    """The visit or stay a form is filled on, from the query string — and
    only this child's."""
    from app.models import Visit
    from app.models.admission import Admission

    visit = admission = None
    vid = request.values.get("visit_id", type=int)
    if vid:
        visit = db.session.get(Visit, vid)
        if visit is None or visit.patient_id != patient.id:
            abort(404)
    aid = request.values.get("admission_id", type=int)
    if aid:
        if "admission" not in cf.places_offered():
            abort(404)
        admission = db.session.get(Admission, aid)
        if admission is None or admission.patient_id != patient.id:
            abort(404)
    return visit, admission


@forms_bp.route("/patient/<int:patient_id>")
@module_required("patients")
def for_patient(patient_id):
    patient = db.get_or_404(Patient, patient_id)
    visit, admission = _context(patient)
    place = "admission" if admission else ("visit" if visit else "patient")
    forms = cf.forms_for(place, current_user)
    entries = (FormEntry.query.filter_by(patient_id=patient.id)
               .order_by(FormEntry.created_at.desc()).all())
    entries = [e for e in entries if cf.may_fill(current_user, e.form)]
    return render_template("forms/for_patient.html", patient=patient,
                           visit=visit, admission=admission, place=place,
                           forms=forms, entries=entries)


@forms_bp.route("/<int:form_id>/fill", methods=["GET", "POST"])
@module_required("patients")
def fill(form_id):
    form = db.get_or_404(CustomForm, form_id)
    if not cf.may_fill(current_user, form) or not form.is_active:
        abort(403)
    if form.place == "admission" and "admission" not in cf.places_offered():
        abort(404)
    patient = db.get_or_404(Patient, request.values.get("patient_id",
                                                        type=int))
    visit, admission = _context(patient)
    if request.method == "POST":
        try:
            entry = cf.fill(form, patient, request.form, current_user,
                            visit=visit, admission=admission)
            db.session.flush()
        except cf.FormError as err:
            db.session.rollback()
            _say(err)
            return render_template("forms/fill.html", form=form,
                                   fields=cf.live_fields(form),
                                   patient=patient, visit=visit,
                                   admission=admission, entry=None,
                                   values=request.form)
        _log("form.fill", form, f"entry {entry.id}")
        db.session.commit()
        flash(t("forms.filled"), "success")
        return redirect(url_for("forms.entry", entry_id=entry.id))
    return render_template("forms/fill.html", form=form,
                           fields=cf.live_fields(form), patient=patient,
                           visit=visit, admission=admission, entry=None,
                           values={})


def _entry_or_403(entry_id):
    entry = db.get_or_404(FormEntry, entry_id)
    if not current_user.can_access("patients") \
            or not cf.may_fill(current_user, entry.form):
        abort(403)
    return entry


@forms_bp.route("/entry/<int:entry_id>", methods=["GET", "POST"])
@module_required("patients")
def entry(entry_id):
    row = _entry_or_403(entry_id)
    editing = request.args.get("edit") == "1"
    if request.method == "POST":
        try:
            cf.amend(row, request.form, current_user)
        except cf.FormError as err:
            db.session.rollback()
            _say(err)
            return redirect(url_for("forms.entry", entry_id=row.id, edit=1))
        _log("form.amend", row.form, f"entry {row.id}")
        db.session.commit()
        flash(t("forms.saved"), "success")
        return redirect(url_for("forms.entry", entry_id=row.id))
    if editing:
        values = {f"a_{k}": v for k, v in row.answers.items()}
        return render_template("forms/fill.html", form=row.form,
                               fields=[f for f in row.snapshot
                                       if not f.get("hidden")],
                               patient=row.patient, visit=None,
                               admission=None, entry=row, values=values)
    return render_template("forms/entry.html", entry=row,
                           fields=row.snapshot, cf=cf)


@forms_bp.route("/entry/<int:entry_id>/print")
@module_required("patients")
def entry_print(entry_id):
    row = _entry_or_403(entry_id)
    return render_template("forms/print.html", entry=row,
                           fields=row.snapshot, cf=cf)


# -------------------------------------------------------------- count ----
def _period():
    end = local_today()
    days = min(max(request.args.get("days", type=int) or 30, 1), 3660)
    return end - timedelta(days=days - 1), end, days


@forms_bp.route("/<int:form_id>/summary")
@module_required("patients")
def summary(form_id):
    form = db.get_or_404(CustomForm, form_id)
    if not cf.may_fill(current_user, form) and not cf.may_design(current_user):
        abort(403)
    start, end, days = _period()
    got = cf.summary(form, start, end)
    return render_template("forms/summary.html", form=form, got=got,
                           days=days, start=start, end=end)


@forms_bp.route("/<int:form_id>/summary.csv")
@module_required("patients")
def summary_csv(form_id):
    form = db.get_or_404(CustomForm, form_id)
    if not cf.may_fill(current_user, form) and not cf.may_design(current_user):
        abort(403)
    start, end, _days = _period()
    got = cf.summary(form, start, end)
    lang = getattr(g, "lang", "ar")
    fields = [f for f in form.fields if f["type"] != "heading"]
    out = io.StringIO()
    out.write("﻿")
    writer = csv.writer(out)
    writer.writerow([t("forms.when"), t("forms.file")]
                    + [cf.label(f, lang) for f in fields])
    for row in got["rows"]:
        answers = row.answers
        writer.writerow([row.created_at.isoformat(timespec="minutes"),
                         row.patient.patient_number if row.patient else ""]
                        + [cf.shown_value(f, answers.get(f["key"]), lang)
                           for f in fields])
    ActivityLog.record("form.export", user_id=current_user.id,
                       entity="custom_form", entity_id=form.id,
                       detail=f"{start}..{end}", ip_address=client_ip())
    db.session.commit()
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition":
                             f"attachment; filename=form-{form.id}.csv"})
