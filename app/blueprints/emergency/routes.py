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

from app.blueprints import department_screen
from app.blueprints.emergency import emergency_bp
from app.extensions import db
from app.i18n import t
from app.models.admission import Admission
from app.models.emergency_visit import ARRIVALS, DISPOSITIONS
from app.utils import beds as ward
from app.utils.decorators import module_required

MODULE = "emergency"
KIND = "emergency"


@emergency_bp.route("/")
@module_required(MODULE)
def index():
    """Who is in the department, worst first."""
    return department_screen.render(MODULE, KIND)


@emergency_bp.route("/register")
@module_required(MODULE)
def register():
    """اللي في القسم دلوقتي، ومين خرج وملفه ناقص.

    **الشاشة الحيّة بتاعت القسم بتقرا الأسرّة**، والطفل اللي لسه ماخدش
    سرير — ويمكن ما ياخدش خالص — مش عليها. فالسجل ده بيقف جنبها مش
    مكانها: هي بتقول «الأسرّة فيها مين»، وده بيقول «القسم فيه مين».
    """
    from app.utils import emergency as er

    return render_template("emergency/register.html",
                           open_visits=er.open_visits(),
                           untriaged=er.untriaged(),
                           incomplete=er.incomplete_departed(),
                           dispositions=DISPOSITIONS, arrivals=ARRIVALS)


@emergency_bp.route("/arrive", methods=["POST"])
@module_required(MODULE)
def arrive():
    """طفل وصل — البند iv، ومن غير ما يحتاج سرير."""
    from app.models import Patient
    from app.utils import emergency as er

    patient = db.session.get(Patient, request.form.get("patient_id", type=int))
    if patient is None:
        return _back(t("emergency.no_patient"), "error")
    try:
        er.arrive(patient, user=current_user,
                  arrival=(request.form.get("arrival") or "").strip() or None)
    except ValueError:
        db.session.rollback()
        return _back(t("emergency.not_saved"), "error")
    db.session.commit()
    return _back(t("emergency.arrived_msg"), "success")


@emergency_bp.route("/triage/<int:visit_id>", methods=["POST"])
@module_required(MODULE)
def triage(visit_id):
    """الفرز ومستواه — البند i.

    المستوى بكلام المستشفى، و«عاجل» بتلات حالات. وفرز من غير مستوى
    بيترفض بصوت: صف بيقول «اتفرز» ومفيهوش «طلع إيه» بيخلّي الملف يدّعي
    إن البند اتعمل وهو ما اتعملش.
    """
    from app.models import EmergencyVisit
    from app.utils import emergency as er

    row = db.get_or_404(EmergencyVisit, visit_id)
    try:
        er.triage(row, level=request.form.get("level"),
                  scale=request.form.get("scale"),
                  urgent=_tri(request.form.get("urgent")),
                  note=request.form.get("note"), user=current_user)
    except ValueError:
        db.session.rollback()
        return _back(t("emergency.needs_a_level"), "error")
    db.session.commit()
    return _back(t("emergency.triaged"), "success")


@emergency_bp.route("/depart/<int:visit_id>", methods=["POST"])
@module_required(MODULE)
def depart(visit_id):
    """الطفل مشي — البنود iv و v و vii و viii في حركة واحدة.

    واحدة لأنها لحظة واحدة: حد بيقول «ماشي فين» و«خرج على إيه» و«يعمل
    إيه بعد كده» وهو واقف قدّامه. تلات شاشات كانت هتخلّي اتنين منهم
    فاضيين في كل ملف.
    """
    from app.models import EmergencyVisit
    from app.utils import emergency as er

    row = db.get_or_404(EmergencyVisit, visit_id)
    try:
        er.depart(row, (request.form.get("disposition") or "").strip(),
                  condition=request.form.get("condition"),
                  followup=request.form.get("followup"), user=current_user)
    except ValueError:
        db.session.rollback()
        return _back(t("emergency.not_saved"), "error")
    db.session.commit()
    return _back(t("emergency.departed"), "success")


def _tri(raw):
    """أيوه · لأ · محدّش قال — والتالتة مش «لأ»."""
    value = (raw or "").strip().lower()
    if value in ("yes", "1", "true", "on"):
        return True
    if value in ("no", "0", "false"):
        return False
    return None


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
