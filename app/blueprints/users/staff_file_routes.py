"""GAHAR WFM.04–09, WFM.13, WFM.14 — the staff file (``utils/staff_file``).
Confidential: the admin's."""
from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.blueprints.users import users_bp
from app.extensions import db
from app.i18n import t
from app.models import User
from app.models.staff_file import StaffCredential, StaffJob
from app.utils import staff_file as sf
from app.utils.clock import local_today
from app.utils.decorators import admin_required


@users_bp.route("/files")
@admin_required
def staff_files():
    users = (User.query.filter(User.is_active.is_(True), User.is_vendor.is_(False))
             .order_by(User.full_name).all())
    return render_template("users/staff_files.html", rows=sf.board(users, local_today()))


@users_bp.route("/<int:user_id>/file")
@admin_required
def staff_file(user_id):
    user = db.get_or_404(User, user_id)
    data = sf.file_for(user)
    return render_template("users/staff_file.html", u=user, data=data,
                           gaps=sf.gaps(user, local_today(), data), today=local_today())


@users_bp.route("/<int:user_id>/file/<what>", methods=["POST"])
@admin_required
def staff_file_add(user_id, what):
    user = db.get_or_404(User, user_id)
    back = url_for("users.staff_file", user_id=user.id) + f"#{what}"
    try:
        if what == "credential":
            sf.add_credential(user, request.form)
        elif what == "verify":
            cred = db.get_or_404(StaffCredential, request.form.get("credential_id", type=int) or 0)
            if cred.user_id != user.id:
                abort(404)
            sf.verify(cred, request.form, current_user)
        elif what == "job":
            sf.add_job(user, request.form)
        elif what == "jd_signed":
            job = db.get_or_404(StaffJob, request.form.get("job_id", type=int) or 0)
            if job.user_id != user.id:
                abort(404)
            sf.jd_signed(job, request.form)
        elif what == "orientation":
            sf.add_orientation(user, request.form)
        elif what == "education":
            sf.add_education(user, request.form)
        elif what == "evaluation":
            sf.add_evaluation(user, request.form)
        else:
            abort(404)
    except sf.StaffFileError as err:
        db.session.rollback()
        flash(t("sfile.err_" + str(err)), "error")
        return redirect(back)
    db.session.commit()
    flash(t("sfile.saved"), "success")
    return redirect(back)
