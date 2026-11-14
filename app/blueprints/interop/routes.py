"""The FHIR interface's screens (``utils/fhir_api``).

* ``/interop/`` — the administrator: the switch, the receivers and their
  keys (each shown once), revoking, and the last reads;
* ``/interop/patient/<id>`` — from the child's file: which receivers may
  read this child, until when, and stopping it. The same people who may take
  the record away as a file (``patient_medical``).
"""
from datetime import datetime

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.blueprints.interop import interop_bp
from app.extensions import db
from app.i18n import t
from app.models import ActivityLog, Patient, Setting
from app.models.interop import SCOPES, FhirReceiver, FhirShare
from app.utils import fhir_api as api
from app.utils.decorators import admin_required, capability_required, client_ip


@interop_bp.route("/", methods=["GET", "POST"])
@login_required
@admin_required
def index():
    new_key = None
    made = None
    if request.method == "POST":
        action = request.form.get("action")
        if action == "switch":
            on = request.form.get("enabled") == "1"
            Setting.set(api.KEY_SETTING, "1" if on else "0")
            ActivityLog.record("fhir_api.switch", user_id=current_user.id,
                               detail="on" if on else "off", ip_address=client_ip())
            db.session.commit()
            flash(t("interop.switched_on") if on else t("interop.switched_off"), "success")
            return redirect(url_for("interop.index"))
        if action == "add":
            try:
                made, new_key = api.new_receiver(request.form.get("name"),
                                                 request.form.get("scope"),
                                                 request.form.get("purpose"), current_user)
            except ValueError:
                flash(t("interop.name_needed"), "danger")
                return redirect(url_for("interop.index"))
            ActivityLog.record("fhir_api.receiver_add", user_id=current_user.id,
                               entity="fhir_receiver", entity_id=made.id,
                               detail=f"{made.name} ({made.scope})", ip_address=client_ip())
            db.session.commit()
            # The key is shown on this page, this once — never in a flash,
            # which would carry it in the session cookie.
    receivers = FhirReceiver.query.order_by(FhirReceiver.revoked_at.isnot(None),
                                            FhirReceiver.created_at.desc()).all()
    now = datetime.utcnow()
    open_counts = {r.id: FhirShare.query.filter(FhirShare.receiver_id == r.id,
                                                FhirShare.revoked_at.is_(None),
                                                FhirShare.until > now).count()
                   for r in receivers}
    return render_template("interop/index.html", enabled=api.enabled(), receivers=receivers,
                           open_counts=open_counts, scopes=SCOPES, new_key=new_key, made=made,
                           reads=api.recent(), base_url=url_for("fhir_api.metadata", _external=True)
                           .rsplit("/metadata", 1)[0])


@interop_bp.route("/receiver/<int:receiver_id>/revoke", methods=["POST"])
@login_required
@admin_required
def revoke(receiver_id):
    row = db.get_or_404(FhirReceiver, receiver_id)
    if row.is_active:
        api.revoke(row, current_user)
        ActivityLog.record("fhir_api.receiver_revoke", user_id=current_user.id,
                           entity="fhir_receiver", entity_id=row.id, detail=row.name,
                           ip_address=client_ip())
        db.session.commit()
        flash(t("interop.revoked", name=row.name), "success")
    return redirect(url_for("interop.index"))



@interop_bp.route("/patient/<int:patient_id>", methods=["GET", "POST"])
@login_required
@capability_required("patient_medical")
def patient(patient_id):
    child = db.get_or_404(Patient, patient_id)
    receivers = FhirReceiver.query.filter(FhirReceiver.revoked_at.is_(None)) \
        .order_by(FhirReceiver.name).all()
    if request.method == "POST":
        if not api.enabled():
            flash(t("interop.off_now"), "warning")
            return redirect(url_for("interop.patient", patient_id=child.id))
        receiver = db.session.get(FhirReceiver, request.form.get("receiver_id", type=int))
        if receiver is None or not receiver.is_active:
            flash(t("common.not_found"), "danger")
            return redirect(url_for("interop.patient", patient_id=child.id))
        row = api.share(receiver, child, current_user, request.form.get("days"),
                        request.form.get("reason"))
        db.session.flush()
        ActivityLog.record("fhir_api.share", user_id=current_user.id, entity="patient",
                           entity_id=child.id,
                           detail=f"{receiver.name} until {row.until:%Y-%m-%d}",
                           ip_address=client_ip())
        db.session.commit()
        flash(t("interop.shared", name=receiver.name), "success")
        return redirect(url_for("interop.patient", patient_id=child.id))
    fhir_id = api.logical_id(child)
    db.session.commit()      # the clinic's namespace, made on first use, must stay
    return render_template("interop/patient.html", patient=child, receivers=receivers,
                           shares=api.shares_of(child), enabled=api.enabled(),
                           now=datetime.utcnow(), default_days=api.DEFAULT_DAYS,
                           max_days=api.MAX_DAYS, patient_id_fhir=fhir_id)


@interop_bp.route("/share/<int:share_id>/stop", methods=["POST"])
@login_required
@capability_required("patient_medical")
def stop(share_id):
    row = db.get_or_404(FhirShare, share_id)
    if row.revoked_at is None:
        row.revoked_at = datetime.utcnow()
        row.revoked_by = current_user.id
        ActivityLog.record("fhir_api.unshare", user_id=current_user.id, entity="patient",
                           entity_id=row.patient_id, detail=row.receiver.name,
                           ip_address=client_ip())
        db.session.commit()
        flash(t("interop.stopped", name=row.receiver.name), "success")
    return redirect(url_for("interop.patient", patient_id=row.patient_id))
