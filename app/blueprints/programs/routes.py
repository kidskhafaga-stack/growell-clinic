"""The special care programmes — dialysis, chemotherapy, rehabilitation
(GAHAR CSS.06, CSS.07, CSS.10; ``utils/care_program``)."""
from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.blueprints.programs import programs_bp
from app.extensions import db
from app.i18n import t
from app.models.care_program import PROGRAMS, ProgramEnrollment
from app.utils import care_program as cp
from app.utils.decorators import module_required

MODULE = "programs"


def _refused(err, where):
    db.session.rollback()
    flash(t("prog.err_" + str(err)), "error")
    return redirect(where)


@programs_bp.route("/")
@module_required(MODULE)
def index():
    program = request.args.get("p") if request.args.get("p") in PROGRAMS else "dialysis"
    return render_template("programs/index.html", program=program, programs=PROGRAMS,
                           rows=cp.board(program), marker_days=cp.marker_days())


@programs_bp.route("/enroll", methods=["POST"])
@module_required(MODULE)
def enroll():
    try:
        row = cp.enroll(request.form, current_user)
    except cp.ProgramError as err:
        return _refused(err, url_for("programs.index", p=request.form.get("program")))
    db.session.commit()
    flash(t("prog.saved"), "success")
    return redirect(url_for("programs.enrollment", enr_id=row.id))


@programs_bp.route("/<int:enr_id>")
@module_required(MODULE)
def enrollment(enr_id):
    enr = db.get_or_404(ProgramEnrollment, enr_id)
    markers = cp.markers_for(enr.patient_id) if enr.program == "dialysis" else []
    return render_template("programs/enrollment.html", enr=enr, sessions=enr.sessions.all(),
                           markers=markers, sero=cp.seroconverted(markers),
                           due=cp.markers_due(enr.patient_id) if enr.program == "dialysis" else None)


@programs_bp.route("/<int:enr_id>/<what>", methods=["POST"])
@module_required(MODULE)
def act(enr_id, what):
    enr = db.get_or_404(ProgramEnrollment, enr_id)
    back = url_for("programs.enrollment", enr_id=enr.id)
    try:
        if what == "session":
            cp.record_session(enr, request.form, current_user)
        elif what == "educate":
            cp.educate(enr, request.form)
        elif what == "end":
            cp.end(enr, request.form)
        elif what == "markers" and enr.program == "dialysis":
            cp.add_markers(enr.patient_id, request.form, current_user)
        else:
            abort(404)
    except cp.ProgramError as err:
        return _refused(err, back)
    db.session.commit()
    flash(t("prog.saved"), "success")
    return redirect(back)


@programs_bp.route("/marker-days", methods=["POST"])
@module_required(MODULE)
def marker_days():
    """The hospital's interval between dialysis viral-marker panels."""
    from app.models import Setting

    if not current_user.is_admin:
        abort(403, description=t("auth.no_permission"))
    raw = (request.form.get("days") or "").strip()
    if raw and not (raw.isdigit() and int(raw) > 0):
        return _refused("days", url_for("programs.index", p="dialysis"))
    Setting.set(cp.MARKER_DAYS_SETTING, raw)
    db.session.commit()
    flash(t("prog.saved"), "success")
    return redirect(url_for("programs.index", p="dialysis"))
