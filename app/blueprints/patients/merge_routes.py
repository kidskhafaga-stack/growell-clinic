"""Two files for one child, made one — the logic is in ``utils/patient_merge``.

Admin only, every step: the list of files that look alike, the preview of
what would move, the merge (with a reason, and the dropped file's number
typed back), and the undo."""
from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.blueprints.patients import patients_bp
from app.extensions import db
from app.i18n import t
from app.models import ActivityLog, Patient
from app.utils import patient_merge as pm
from app.utils.decorators import client_ip


def _admin():
    if not pm.may_merge(current_user):
        abort(403, description=t("auth.no_permission"))


def _find(raw):
    """A file by its number, or by its id when a link carries one."""
    raw = (raw or "").strip()
    if not raw:
        return None
    row = Patient.query.filter(Patient.patient_number == raw).first()
    if row is None and raw.isdigit():
        row = db.session.get(Patient, int(raw))
    return row


@patients_bp.route("/merge")
@login_required
def merge_page():
    _admin()
    keep, drop = _find(request.args.get("keep")), _find(request.args.get("drop"))
    check = pm.preview(keep, drop) if (keep and drop) else None
    if (request.args.get("keep") or request.args.get("drop")) and not (keep and drop):
        flash(t("pmerge.err_missing"), "error")
    return render_template("patients/merge.html", keep=keep, drop=drop, check=check,
                           candidates=pm.candidates(), history=pm.history(),
                           moved_total=pm.moved_total, summary=pm.summary)


@patients_bp.route("/merge", methods=["POST"])
@login_required
def merge_do():
    _admin()
    keep = db.session.get(Patient, request.form.get("keep_id", type=int) or 0)
    drop = db.session.get(Patient, request.form.get("drop_id", type=int) or 0)
    back = url_for("patients.merge_page", keep=keep.id if keep else "",
                   drop=drop.id if drop else "")
    # The dropped file's number typed back: the one check a wrong pair
    # cannot pass by somebody pressing the button out of habit.
    if drop is None or (request.form.get("confirm") or "").strip() != (drop.patient_number or ""):
        flash(t("pmerge.err_confirm"), "error")
        return redirect(back)
    try:
        row = pm.merge(keep, drop, current_user, reason=request.form.get("reason"))
    except pm.MergeError as err:
        db.session.rollback()
        flash(t(f"pmerge.err_{err}"), "error")
        return redirect(back)
    ActivityLog.record("patient.merge", user_id=current_user.id, entity="patient",
                       entity_id=row.keep_id,
                       detail=f"{row.drop_number} -> {row.keep_id}"[:250],
                       ip_address=client_ip())
    db.session.commit()
    from app.utils import notifications
    notifications.invalidate()
    flash(t("pmerge.done", n=pm.moved_total(row)), "success")
    return redirect(url_for("patients.view", patient_id=row.keep_id))


@patients_bp.route("/merge/<int:merge_id>/undo", methods=["POST"])
@login_required
def merge_undo(merge_id):
    from app.models import PatientMerge

    _admin()
    row = db.get_or_404(PatientMerge, merge_id)
    try:
        pm.undo(row, current_user)
    except pm.MergeError as err:
        db.session.rollback()
        flash(t(f"pmerge.err_{err}"), "error")
        return redirect(url_for("patients.merge_page"))
    ActivityLog.record("patient.merge_undone", user_id=current_user.id, entity="patient",
                       entity_id=row.keep_id, detail=f"{row.drop_number}"[:250],
                       ip_address=client_ip())
    db.session.commit()
    from app.utils import notifications
    notifications.invalidate()
    flash(t("pmerge.undone"), "success")
    return redirect(url_for("patients.merge_page"))
