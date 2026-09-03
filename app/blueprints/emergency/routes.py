"""The emergency department, as a screen rather than as a word.

``emergency_care`` has been a capability since the facility wizard existed,
and until now it mapped to "the visits module" — a name with no screen, the
same shape dentistry had before it got a front door.

**Everything under it was already built.** Triage is ``red_flags``; the
repeated readings are ``Observation``; the place and the stay are ``Unit`` /
``Bed`` / ``Admission``. What was missing is the one question those three
cannot answer separately: **who do I look at first, and who has been here too
long without anybody touching them.** That is ``utils/department.live``, and
this blueprint is a screen over it.

**The exit is the point.** An emergency stay is not finished by time passing;
it ends in a decision — home, admitted upstairs, or sent to another hospital.
Both of those already exist (``beds.discharge`` and ``beds.move``), so the
screen surfaces them rather than growing a third way to end a stay.

Opt-in, and off until a clinic says it runs an emergency.
"""
from flask import redirect, render_template, request, url_for
from flask_login import current_user

from app.blueprints.emergency import emergency_bp
from app.extensions import db
from app.i18n import t
from app.models.admission import OUTCOMES, Admission
from app.utils import beds as ward
from app.utils import department
from app.utils.decorators import module_required

MODULE = "emergency"
KIND = "emergency"


@emergency_bp.route("/")
@module_required(MODULE)
def index():
    """Who is in the department, worst first."""
    from app.models.place import Unit

    units = (Unit.query.filter(Unit.kind == KIND, Unit.is_active.is_(True))
             .order_by(Unit.sort_order, Unit.id).all())
    return render_template(
        "departments/board.html",
        kind=KIND, module=MODULE, rows=department.live(KIND), units=units,
        # Where a child goes when the decision is "upstairs". Offered from
        # here because the alternative is telling somebody to find the bed
        # board, remember the child's name, and start again.
        free=ward.free_beds(), outcomes=OUTCOMES,
        levels=department, may_build=current_user.is_admin)


@emergency_bp.route("/decide/<int:admission_id>", methods=["POST"])
@module_required(MODULE)
def decide(admission_id):
    """End an emergency stay, or move it upstairs.

    One control for what is really one decision. "Admitted" is a move to a bed
    in another unit and the stay carries on — the child does not leave and
    come back, and a discharge followed by an admission would put two stays on
    one continuous piece of care.
    """
    row = db.get_or_404(Admission, admission_id)
    bed_id = request.form.get("bed_id", type=int)
    outcome = (request.form.get("outcome") or "").strip()

    if outcome == "admitted":
        from app.models.place import Bed

        try:
            ward.move(row, db.session.get(Bed, bed_id), user=current_user,
                      note=(request.form.get("note") or "").strip() or None)
        except ward.BedTaken:
            db.session.rollback()
            return _back(t("beds.refused_occupied"), "error")
        db.session.commit()
        return _back(t("emergency.admitted_upstairs"), "success")

    ward.discharge(row, outcome, user=current_user,
                   note=request.form.get("note"))
    db.session.commit()
    return _back(t("emergency.decided"), "success")


def _back(message, level):
    from flask import flash

    flash(message, level)
    return redirect(url_for("emergency.index"))
