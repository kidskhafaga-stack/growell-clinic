"""The teaching module's screens — trainees, concerns and research (GAHAR
ATH; ``utils/teaching``). The research ethics committee's decision is
recorded by an administrator; everything else by whoever holds the module."""
from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.blueprints.teaching import teaching_bp
from app.extensions import db
from app.i18n import t
from app.models.teaching import (ASSESSMENT_TOOLS, CONCERN_KINDS, ORIENTATION_ITEMS, TRAINEE_KINDS,
                                 ResearchParticipant, ResearchProtocol, TeachingConcern, Trainee,
                                 TrainingRotation)
from app.utils import teaching as teach
from app.utils.clock import local_today
from app.utils.decorators import module_required

MODULE = "teaching"


def _go(fn, where):
    try:
        fn()
    except teach.TeachingError as err:
        db.session.rollback()
        flash(t(f"teach.err_{err}"), "error")
        return redirect(where)
    db.session.commit()
    flash(t("teach.saved"), "success")
    return redirect(where)


def _staff():
    from app.models import User

    return User.query.filter(User.is_active.is_(True)).order_by(User.full_name).all()


def _doctors():
    from app.utils.against_advice import doctors

    return doctors()


def _file():
    from app.utils.uploads import save_document

    file = request.files.get("file")
    if not file or not file.filename:
        return None
    stored = save_document(file)
    if stored is None:
        raise teach.TeachingError("bad_file")
    return stored


# ================================================================ trainees ==
@teaching_bp.route("/")
@module_required(MODULE)
def index():
    return render_template("teaching/index.html", data=teach.trainees_board(local_today()),
                           concerns=teach.concerns_board(), research=teach.research_board(local_today()),
                           kinds=TRAINEE_KINDS, concern_kinds=CONCERN_KINDS, staff=_staff(),
                           doctors=_doctors(), today=local_today())


@teaching_bp.route("/trainee", methods=["POST"])
@module_required(MODULE)
def trainee_new():
    holder = {}

    def save():
        holder["row"] = teach.save_trainee(request.form)

    response = _go(save, url_for("teaching.index"))
    if "row" in holder and holder["row"].id:
        return redirect(url_for("teaching.trainee", trainee_id=holder["row"].id))
    return response


@teaching_bp.route("/trainee/<int:trainee_id>")
@module_required(MODULE)
def trainee(trainee_id):
    row = db.get_or_404(Trainee, trainee_id)
    return render_template("teaching/trainee.html", tr=row, missing=teach.orientation_missing(row),
                           items=ORIENTATION_ITEMS, tools=ASSESSMENT_TOOLS, staff=_staff(), today=local_today())


@teaching_bp.route("/trainee/<int:trainee_id>/orient", methods=["POST"])
@module_required(MODULE)
def trainee_orient(trainee_id):
    row = db.get_or_404(Trainee, trainee_id)
    return _go(lambda: teach.orient(row, request.form), url_for("teaching.trainee", trainee_id=row.id))


@teaching_bp.route("/trainee/<int:trainee_id>/rotation", methods=["POST"])
@module_required(MODULE)
def trainee_rotation(trainee_id):
    row = db.get_or_404(Trainee, trainee_id)
    return _go(lambda: teach.add_rotation(row, request.form),
               url_for("teaching.trainee", trainee_id=row.id) + "#rotations")


@teaching_bp.route("/rotation/<int:rotation_id>/evaluate", methods=["POST"])
@module_required(MODULE)
def rotation_evaluate(rotation_id):
    rot = db.get_or_404(TrainingRotation, rotation_id)
    return _go(lambda: teach.evaluate_rotation(rot, request.form),
               url_for("teaching.trainee", trainee_id=rot.trainee_id) + "#rotations")


@teaching_bp.route("/trainee/<int:trainee_id>/assess", methods=["POST"])
@module_required(MODULE)
def trainee_assess(trainee_id):
    row = db.get_or_404(Trainee, trainee_id)
    return _go(lambda: teach.assess(row, current_user, request.form),
               url_for("teaching.trainee", trainee_id=row.id) + "#assessments")


@teaching_bp.route("/trainee/<int:trainee_id>/finish", methods=["POST"])
@module_required(MODULE)
def trainee_finish(trainee_id):
    row = db.get_or_404(Trainee, trainee_id)
    return _go(lambda: teach.finish(row), url_for("teaching.index"))


# ================================================================ concerns ==
@teaching_bp.route("/concerns", methods=["POST"])
@module_required(MODULE)
def concern_new():
    return _go(lambda: teach.raise_concern(current_user, request.form), url_for("teaching.index") + "#concerns")


@teaching_bp.route("/concern/<int:concern_id>", methods=["POST"])
@module_required(MODULE)
def concern_act(concern_id):
    row = db.get_or_404(TeachingConcern, concern_id)
    return _go(lambda: teach.act_on_concern(row, request.form), url_for("teaching.index") + "#concerns")


# ================================================================ research ==
@teaching_bp.route("/research", methods=["POST"])
@module_required(MODULE)
def protocol_new():
    return _go(lambda: teach.submit_protocol(request.form, file=_file()), url_for("teaching.index") + "#research")


@teaching_bp.route("/protocol/<int:protocol_id>")
@module_required(MODULE)
def protocol(protocol_id):
    row = db.get_or_404(ResearchProtocol, protocol_id)
    from app.models import Patient

    child = None
    pid = request.args.get("patient_id", type=int)
    if pid:
        child = db.session.get(Patient, pid)
    return render_template("teaching/protocol.html", p=row, open=teach.open_for_enrolment(row),
                           child=child, consents=teach.research_consents(child, row) if child else [],
                           today=local_today())


@teaching_bp.route("/protocol/<int:protocol_id>/decide", methods=["POST"])
@module_required(MODULE)
def protocol_decide(protocol_id):
    if not current_user.is_admin:
        abort(403, description=t("auth.no_permission"))
    row = db.get_or_404(ResearchProtocol, protocol_id)
    return _go(lambda: teach.decide(row, request.form), url_for("teaching.protocol", protocol_id=row.id))


@teaching_bp.route("/protocol/<int:protocol_id>/enroll", methods=["POST"])
@module_required(MODULE)
def protocol_enroll(protocol_id):
    from app.models import Patient

    row = db.get_or_404(ResearchProtocol, protocol_id)
    child = db.get_or_404(Patient, request.form.get("patient_id", type=int) or 0)
    return _go(lambda: teach.enroll(row, child, current_user, request.form),
               url_for("teaching.protocol", protocol_id=row.id) + "#participants")


@teaching_bp.route("/participant/<int:participant_id>/withdraw", methods=["POST"])
@module_required(MODULE)
def participant_withdraw(participant_id):
    part = db.get_or_404(ResearchParticipant, participant_id)
    return _go(lambda: teach.withdraw(part, request.form),
               url_for("teaching.protocol", protocol_id=part.protocol_id) + "#participants")


@teaching_bp.route("/participant/<int:participant_id>/safety", methods=["POST"])
@module_required(MODULE)
def participant_safety(participant_id):
    part = db.get_or_404(ResearchParticipant, participant_id)
    return _go(lambda: teach.safety_event(part, current_user, request.form),
               url_for("teaching.protocol", protocol_id=part.protocol_id) + "#participants")

