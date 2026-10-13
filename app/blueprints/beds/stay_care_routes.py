"""The stay's continuity records — ICD.06 the initial medical assessment,
ICD.08 the needs screen, ACT.11 the multidisciplinary meeting, ACT.14 the
temporary discharge, PCC.05 the family's questions and PCC.14 belongings and
lost and found (``utils/medical_assessment``, ``utils/needs_screen``,
``utils/stay_care``)."""
from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.blueprints.beds import beds_bp
from app.extensions import db
from app.i18n import t
from app.models.admission import Admission
from app.models.belonging import Belonging, LostItem
from app.models.family_question import FamilyQuestion
from app.models.needs_screen import KINDS as NEED_KINDS
from app.models.needs_screen import NeedsScreen
from app.models.stay_leave import StayLeave
from app.utils import medical_assessment as medass
from app.utils import needs_screen as needs
from app.utils import stay_care as care
from app.utils.decorators import module_required

def _back(stay_id, anchor, prefix=None, err=None):
    if err is not None:
        db.session.rollback()
        flash(t(f"{prefix}.err_{err}"), "error")
    else:
        db.session.commit()
        flash(t("staycare.saved"), "success")
    return redirect(url_for("beds.admission", admission_id=stay_id) + "#" + anchor)


def _stay(admission_id):
    return db.get_or_404(Admission, admission_id)


# ================================================================ ICD.06 ==
@beds_bp.route("/admission/<int:admission_id>/medical-initial", methods=["POST"])
@module_required("beds")
def medical_initial(admission_id):
    stay = _stay(admission_id)
    try:
        medass.save(stay, request.form, current_user)
    except medass.AssessmentError as err:
        return _back(stay.id, "medical-initial", "medass", err)
    return _back(stay.id, "medical-initial")


# ================================================================ ICD.08 ==
@beds_bp.route("/admission/<int:admission_id>/needs", methods=["POST"])
@module_required("beds")
def needs_screen(admission_id):
    stay = _stay(admission_id)
    try:
        needs.screen(stay, request.form, current_user)
    except needs.NeedsError as err:
        return _back(stay.id, "needs", "needscreen", err)
    return _back(stay.id, "needs")


@beds_bp.route("/needs/<int:row_id>/refer", methods=["POST"])
@module_required("beds")
def needs_refer(row_id):
    row = db.get_or_404(NeedsScreen, row_id)
    try:
        needs.refer(row, request.form)
    except needs.NeedsError as err:
        return _back(row.admission_id, "needs", "needscreen", err)
    return _back(row.admission_id, "needs")


@beds_bp.route("/needs/<int:row_id>/seen", methods=["POST"])
@module_required("beds")
def needs_seen(row_id):
    row = db.get_or_404(NeedsScreen, row_id)
    try:
        needs.seen(row, request.form, current_user)
    except needs.NeedsError as err:
        return _back(row.admission_id, "needs", "needscreen", err)
    return _back(row.admission_id, "needs")


@beds_bp.route("/needs/criteria", methods=["GET", "POST"])
@module_required("beds")
def needs_criteria():
    """(b) the hospital's criteria per need, and (c) its timeframe — written
    by an administrator; read by everybody who screens."""
    if request.method == "POST":
        if not current_user.is_admin:
            abort(403)
        try:
            needs.save_settings(request.form)
        except needs.NeedsError as err:
            db.session.rollback()
            flash(t("needscreen.err_" + str(err)), "error")
            return redirect(url_for("beds.needs_criteria"))
        db.session.commit()
        flash(t("staycare.saved"), "success")
        return redirect(url_for("beds.needs_criteria"))
    return render_template("beds/needs_criteria.html", criteria=needs.criteria(),
                           hours=needs.hours(), kinds=NEED_KINDS)


# ================================================================ ACT.11 ==
@beds_bp.route("/admission/<int:admission_id>/mdt", methods=["POST"])
@module_required("beds")
def mdt_add(admission_id):
    stay = _stay(admission_id)
    try:
        care.add_mdt(stay, request.form, current_user)
    except care.StayCareError as err:
        return _back(stay.id, "mdt", "staycare", err)
    return _back(stay.id, "mdt")


# ================================================================ ACT.14 ==
@beds_bp.route("/admission/<int:admission_id>/leave", methods=["POST"])
@module_required("beds")
def leave_start(admission_id):
    stay = _stay(admission_id)
    try:
        care.start_leave(stay, request.form, current_user)
    except care.StayCareError as err:
        return _back(stay.id, "leave", "staycare", err)
    return _back(stay.id, "leave")


@beds_bp.route("/leave/<int:row_id>/back", methods=["POST"])
@module_required("beds")
def leave_back(row_id):
    row = db.get_or_404(StayLeave, row_id)
    try:
        care.end_leave(row, request.form)
    except care.StayCareError as err:
        return _back(row.admission_id, "leave", "staycare", err)
    return _back(row.admission_id, "leave")


# ================================================================ PCC.05 ==
@beds_bp.route("/admission/<int:admission_id>/question", methods=["POST"])
@module_required("beds")
def family_question(admission_id):
    stay = _stay(admission_id)
    try:
        care.ask(stay, request.form, current_user)
    except care.StayCareError as err:
        return _back(stay.id, "family-questions", "staycare", err)
    return _back(stay.id, "family-questions")


@beds_bp.route("/question/<int:row_id>/answer", methods=["POST"])
@module_required("beds")
def family_answer(row_id):
    row = db.get_or_404(FamilyQuestion, row_id)
    try:
        care.answer(row, request.form, current_user)
    except care.StayCareError as err:
        return _back(row.admission_id, "family-questions", "staycare", err)
    return _back(row.admission_id, "family-questions")


@beds_bp.route("/question-hours", methods=["POST"])
@module_required("beds")
def family_question_hours():
    if not current_user.is_admin:
        abort(403)
    stay_id = request.form.get("admission_id", type=int)
    try:
        care.set_number(care.QUESTION_HOURS_SETTING, request.form.get("hours"))
    except care.StayCareError as err:
        return _back(stay_id, "family-questions", "staycare", err)
    return _back(stay_id, "family-questions")


# ================================================================ PCC.14 ==
@beds_bp.route("/admission/<int:admission_id>/belongings", methods=["POST"])
@module_required("beds")
def belongings_keep(admission_id):
    stay = _stay(admission_id)
    try:
        care.keep(stay, request.form, current_user)
    except care.StayCareError as err:
        return _back(stay.id, "belongings", "staycare", err)
    return _back(stay.id, "belongings")


@beds_bp.route("/belongings/<int:row_id>/returned", methods=["POST"])
@module_required("beds")
def belongings_returned(row_id):
    row = db.get_or_404(Belonging, row_id)
    try:
        care.give_back(row, request.form, current_user)
    except care.StayCareError as err:
        if row.admission_id:
            return _back(row.admission_id, "belongings", "staycare", err)
        db.session.rollback()
        flash(t("staycare.err_" + str(err)), "error")
        return redirect(url_for("beds.lost_found"))
    if row.admission_id and request.form.get("back") != "board":
        return _back(row.admission_id, "belongings")
    db.session.commit()
    flash(t("staycare.saved"), "success")
    return redirect(url_for("beds.lost_found"))


def _board_back(err=None):
    if err is not None:
        db.session.rollback()
        flash(t("staycare.err_" + str(err)), "error")
    else:
        db.session.commit()
        flash(t("staycare.saved"), "success")
    return redirect(url_for("beds.lost_found"))


@beds_bp.route("/lost-found", methods=["GET", "POST"])
@module_required("beds")
def lost_found():
    if request.method == "POST":
        try:
            if request.form.get("what") == "days":
                if not current_user.is_admin:
                    abort(403)
                care.set_number(care.LOST_DAYS_SETTING, request.form.get("days"))
            else:
                care.found(request.form, current_user)
        except care.StayCareError as err:
            return _board_back(err)
        return _board_back()
    return render_template("beds/lost_found.html", data=care.lost_board())


@beds_bp.route("/lost/<int:row_id>/<what>", methods=["POST"])
@module_required("beds")
def lost_item(row_id, what):
    row = db.get_or_404(LostItem, row_id)
    try:
        if what == "returned":
            care.lost_returned(row, request.form)
        elif what == "closed":
            care.lost_closed(row, request.form)
        else:
            abort(404)
    except care.StayCareError as err:
        return _board_back(err)
    return _board_back()


# ================================================================ ICD.21 ==
@beds_bp.route("/transfusion/<int:bag_id>/reported", methods=["POST"])
@module_required("beds")
def transfusion_reported(bag_id):
    """A reaction reported to the blood bank and quality — to whom, and when."""
    from datetime import datetime

    from app.models.blood import Transfusion

    bag = db.get_or_404(Transfusion, bag_id)
    stay_id = bag.request.admission_id if bag.request else None
    to = (request.form.get("reported_to") or "").strip()[:160]
    if not bag.reaction or bag.reported_at is not None or not to:
        flash(t("blood.err_report"), "error")
    else:
        bag.reported_to, bag.reported_at, bag.reported_by = to, datetime.utcnow(), current_user.id
        db.session.commit()
        flash(t("staycare.saved"), "success")
    if stay_id:
        return redirect(url_for("beds.admission", admission_id=stay_id) + "#blood")
    return redirect(url_for("beds.index"))
