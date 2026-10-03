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
from flask import (abort, flash, g, jsonify, redirect, render_template,
                   request, url_for)
from flask_login import current_user

from app.blueprints import department_screen
from app.blueprints.emergency import emergency_bp
from app.extensions import db
from app.i18n import t
from app.models.admission import Admission
from app.models.emergency_visit import ARRIVALS, DISPOSITIONS
from app.utils import beds as ward
from app.utils.decorators import capability_required, module_required

MODULE = "emergency"
KIND = "emergency"


@emergency_bp.route("/")
@module_required(MODULE)
def index():
    """Who is in the department, worst first — in a bed, and without one.

    The children with no bed are the department too: «هو قاعد وملهوش علاج»
    is asked about the child on a chair as much as the one on a trolley. So
    the live board lists them above the beds, each with what they wait on.
    """
    from app.utils import emergency as er
    from app.utils import waiting_on

    bedless = [a for a in er.open_visits() if a.admission_id is None]
    return department_screen.render(
        MODULE, KIND, attendances=bedless,
        attendance_waiting=waiting_on.for_attendances(bedless))


def _reasons():
    from app.utils import leave_reasons

    return leave_reasons.options()


def _asked_on():
    from app.utils import leave_reasons

    return leave_reasons.ASKED_ON


@emergency_bp.route("/register")
@module_required(MODULE)
def register():
    """اللي في القسم دلوقتي، ومين خرج وملفه ناقص.

    **الشاشة الحيّة بتاعت القسم بتقرا الأسرّة**، والطفل اللي لسه ماخدش
    سرير — ويمكن ما ياخدش خالص — مش عليها. فالسجل ده بيقف جنبها مش
    مكانها: هي بتقول «الأسرّة فيها مين»، وده بيقول «القسم فيه مين».
    """
    from app.utils import emergency as er
    from app.utils import emergency_orders as eo

    from app.utils import waiting_on

    open_visits = er.open_visits()
    return render_template("emergency/register.html",
                           open_visits=open_visits,
                           waiting=waiting_on.for_attendances(open_visits),
                           order_states=eo.states_by_attendance(
                               [r.id for r in open_visits]),
                           mine_to_confirm=len(
                               eo.awaiting_confirmation(current_user)),
                           outside_waiting=len(eo.waiting_doctor()),
                           untriaged=er.untriaged(),
                           incomplete=er.incomplete_departed(),
                           dispositions=DISPOSITIONS, arrivals=ARRIVALS,
                           leave_reasons=_reasons(), asked_on=_asked_on())


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
        row = er.arrive(patient, user=current_user,
                        arrival=(request.form.get("arrival") or "").strip() or None,
                        treatment_only=bool(request.form.get("treatment_only")))
    except ValueError:
        db.session.rollback()
        return _back(t("emergency.not_saved"), "error")
    db.session.commit()
    flash(t("emergency.arrived_msg"), "success")
    # Straight to the child's own page: the next thing anybody does is
    # write what they came for.
    return redirect(url_for("emergency.attendance", attendance_id=row.id))


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

    from app.blueprints.beds.routes import _survey_after
    from app.utils import leave_reasons

    row = db.get_or_404(EmergencyVisit, visit_id)
    try:
        er.depart(row, (request.form.get("disposition") or "").strip(),
                  condition=request.form.get("condition"),
                  followup=request.form.get("followup"), user=current_user)
    except ValueError:
        db.session.rollback()
        return _back(t("emergency.not_saved"), "error")
    # Left against advice, or before being seen: why, in one tap.
    leave_reasons.record(row, row.disposition, request.form.get("leave_reason"),
                         request.form.get("leave_note"))
    db.session.commit()
    _survey_after(row.patient, row.disposition, centre_key="emergency",
                  emergency_visit=row)
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
    flash(message, level)
    return redirect(url_for("emergency.index"))


# ============================================ the child with no bed ======
# «الناس الى داخله الطوارئ تنفذ علاج معين ومش هتاخد اقامة». One page per
# attendance: what was written, on whose word, what was given — and the
# tests. The rules live in `utils/emergency_orders`; these are its doors.

@emergency_bp.route("/patient-search")
@module_required(MODULE)
def patient_search():
    """The arrival box's search — name, file number, national id or phone,
    by the rule every patient list uses. Its own address so an unrelated
    module switched off never empties it."""
    from app.models import Patient
    from app.utils.patients import apply_patient_search

    query = (request.args.get("q") or "").strip()
    if len(query) < 2:
        return jsonify([])
    rows = (apply_patient_search(
        Patient.query.filter(Patient.is_active.is_(True)), query)
        .limit(10).all())
    lang = getattr(g, "lang", "ar")
    return jsonify([{"id": p.id, "name": p.display_name(lang),
                     "file": p.patient_number} for p in rows])


@emergency_bp.route("/drug-search")
@module_required(MODULE)
def drug_search():
    """The drug box — the one search the prescription writer uses."""
    from app.utils.drug_search import search_drugs

    return jsonify(search_drugs(request.args.get("q"),
                                lang=getattr(g, "lang", "ar"), limit=12))


@emergency_bp.route("/investigation-search")
@module_required(MODULE)
def investigation_search():
    """The test box — the catalogue, active tests only."""
    from app.utils.stay_orders import search

    kind = (request.args.get("kind") or "").strip() or None
    lang = getattr(g, "lang", "ar")
    return jsonify([{"id": x.id, "name": x.display_name(lang), "kind": x.kind,
                     "in_house": x.in_house is not False}
                    for x in search(request.args.get("q"), kind)])


@emergency_bp.route("/attendance/<int:attendance_id>")
@module_required(MODULE)
def attendance(attendance_id):
    """One child in emergency: what was written for them and what was
    given."""
    from app.models import EmergencyVisit, Service
    from app.models.emergency_order import SOURCES
    from app.models.medication import ROUTES
    from app.utils import emergency as er
    from app.utils import emergency_orders as eo

    from app.utils.facility import module_enabled

    from app.utils import waiting_on

    row = db.get_or_404(EmergencyVisit, attendance_id)
    orders = eo.for_attendance(row)
    waiting = waiting_on.for_attendances([row]).get(row.id)
    session = waiting_on.running_session(orders)
    services = (Service.query.filter(Service.is_active.is_(True))
                .filter(~Service.service_type.in_(
                    ("consultation", "followup", "vaccination")))
                .order_by(Service.name).all())
    return render_template(
        "emergency/attendance.html", row=row, orders=orders,
        waiting=waiting, session=session,
        # The desk's door, for whoever may take the money: what was given
        # waits there as lines to check before anything is charged.
        may_collect=module_enabled("finance") and (
            current_user.can_access("finance") or current_user.can("cashier")),
        owed=len(eo.unbilled(row.patient_id)),
        tests=eo.tests_for(row), missing=er.missing(row),
        doctors=eo.doctors(), services=services,
        store_items=_shelf(), routes=ROUTES, sources=SOURCES,
        may_order=current_user.can("medication_order"),
        is_doctor=eo.is_doctor(current_user),
        dispositions=DISPOSITIONS, leave_reasons=_reasons(),
        asked_on=_asked_on())


def _shelf():
    """What the store holds that a dose could come off — drugs first."""
    from app.models import StoreItem

    return (StoreItem.query.filter(StoreItem.is_active.is_(True))
            .order_by((StoreItem.item_type != "drug"), StoreItem.name).all())


def _to_attendance(row_id):
    return redirect(url_for("emergency.attendance", attendance_id=row_id)
                    + "#orders")


@emergency_bp.route("/attendance/<int:attendance_id>/order", methods=["POST"])
@module_required(MODULE)
def write_order(attendance_id):
    """Write what to give — our doctor's order, or a paper somebody brought.

    Anybody in the department may enter a paper; only a doctor with the
    order right writes one of our own. Which of the two it is, is the
    ``source`` on the form.
    """
    from app.models import (Drug, EmergencyVisit, Service, StoreItem,
                            User)
    from app.models.emergency_order import OURS
    from app.utils import emergency_orders as eo

    row = db.get_or_404(EmergencyVisit, attendance_id)
    source = (request.form.get("source") or OURS).strip()
    if source == OURS and not current_user.can("medication_order"):
        abort(403, description=t("auth.no_permission"))

    def pick(model, field):
        wanted = request.form.get(field, type=int)
        return db.session.get(model, wanted) if wanted else None

    try:
        eo.write(row, current_user, source=source,
                 name=request.form.get("name"), drug=pick(Drug, "drug_id"),
                 service=pick(Service, "service_id"),
                 dose=request.form.get("dose"),
                 route=(request.form.get("route") or "").strip() or None,
                 store_item=pick(StoreItem, "store_item_id"),
                 units=request.form.get("units", type=int),
                 note=request.form.get("note"),
                 prescriber=pick(User, "prescriber_id"),
                 outside_doctor=request.form.get("outside_doctor"))
    except eo.Closed:
        db.session.rollback()
        flash(t("er_orders.closed"), "error")
        return _to_attendance(row.id)
    except eo.NotADoctor:
        db.session.rollback()
        flash(t("er_orders.needs_our_doctor"), "error")
        return _to_attendance(row.id)
    except ValueError as why:
        db.session.rollback()
        flash(t({"no name": "er_orders.needs_name",
                 "no outside doctor": "er_orders.needs_outside_doctor"}.get(
                     str(why), "er_orders.refused")), "error")
        return _to_attendance(row.id)
    db.session.commit()
    _refresh_bell()
    flash(t("er_orders.written"), "success")
    return _to_attendance(row.id)


def _order_or_404(order_id):
    from app.models import EmergencyOrder

    return db.get_or_404(EmergencyOrder, order_id)


@emergency_bp.route("/order/<int:order_id>/approve", methods=["POST"])
@module_required(MODULE)
@capability_required("medication_order")
def approve_order(order_id):
    """Our doctor saw the child and agrees to the outside paper."""
    from app.utils import emergency_orders as eo

    order = _order_or_404(order_id)
    try:
        eo.approve(order, current_user)
    except ValueError:
        db.session.rollback()
        flash(t("er_orders.refused"), "error")
        return _to_attendance(order.emergency_visit_id)
    db.session.commit()
    flash(t("er_orders.approved"), "success")
    return _to_attendance(order.emergency_visit_id)


@emergency_bp.route("/order/<int:order_id>/give", methods=["POST"])
@module_required(MODULE)
def give_order(order_id):
    """Given — by whoever stood at the child. Not behind the order right:
    giving is the nurse's act."""
    from app.utils import emergency_orders as eo

    order = _order_or_404(order_id)
    try:
        eo.give(order, current_user)
    except ValueError as why:
        db.session.rollback()
        flash(t("er_orders.needs_approval" if str(why) == "waiting_doctor"
                else "er_orders.refused"), "error")
        return _to_attendance(order.emergency_visit_id)
    db.session.commit()
    flash(t("er_orders.given"), "success")
    return _to_attendance(order.emergency_visit_id)


@emergency_bp.route("/order/<int:order_id>/cancel", methods=["POST"])
@module_required(MODULE)
def cancel_order(order_id):
    from app.utils import emergency_orders as eo

    order = _order_or_404(order_id)
    try:
        eo.cancel(order, current_user, reason=request.form.get("reason"))
    except ValueError:
        db.session.rollback()
        flash(t("er_orders.refused"), "error")
        return _to_attendance(order.emergency_visit_id)
    db.session.commit()
    _refresh_bell()
    flash(t("er_orders.cancelled"), "success")
    return _to_attendance(order.emergency_visit_id)


@emergency_bp.route("/order/<int:order_id>/confirm", methods=["POST"])
@module_required(MODULE)
def confirm_order(order_id):
    """The doctor on the paper says it is theirs."""
    from app.utils import emergency_orders as eo

    order = _order_or_404(order_id)
    try:
        eo.confirm(order, current_user)
    except eo.NotADoctor:
        db.session.rollback()
        abort(403, description=t("er_orders.not_your_paper"))
    except ValueError:
        db.session.rollback()
        flash(t("er_orders.refused"), "error")
        return redirect(url_for("emergency.confirmations"))
    db.session.commit()
    _refresh_bell()
    flash(t("er_orders.confirmed"), "success")
    if request.form.get("back") == "attendance":
        return _to_attendance(order.emergency_visit_id)
    return redirect(url_for("emergency.confirmations"))


@emergency_bp.route("/confirmations")
@module_required(MODULE)
def confirmations():
    """Papers given in my name while I was in the building, and the outside
    papers waiting for a doctor."""
    from app.utils import emergency_orders as eo

    return render_template(
        "emergency/confirmations.html",
        mine=eo.awaiting_confirmation(current_user),
        outside=eo.waiting_doctor(),
        may_order=current_user.can("medication_order"))


@emergency_bp.route("/attendance/<int:attendance_id>/test", methods=["POST"])
@module_required(MODULE)
@capability_required("medication_order")
def order_test(attendance_id):
    """A test or scan for a child in emergency — behind the order right,
    like the stay's."""
    from app.models import EmergencyVisit, Investigation
    from app.utils import emergency_orders as eo

    row = db.get_or_404(EmergencyVisit, attendance_id)
    wanted = request.form.get("investigation_id", type=int)
    investigation = db.session.get(Investigation, wanted) if wanted else None
    outside = request.form.get("done_outside")
    try:
        eo.order_test(row, current_user, investigation=investigation,
                      name=request.form.get("name"),
                      kind=request.form.get("kind"),
                      notes=request.form.get("notes"),
                      outside=(outside == "1") if outside in ("0", "1")
                      else None)
    except eo.Closed:
        db.session.rollback()
        flash(t("er_orders.closed"), "error")
        return _to_attendance(row.id)
    except ValueError:
        db.session.rollback()
        flash(t("er_orders.needs_name"), "error")
        return _to_attendance(row.id)
    db.session.commit()
    flash(t("stay_tests.ordered"), "success")
    return redirect(url_for("emergency.attendance", attendance_id=row.id)
                    + "#tests")


@emergency_bp.route("/attendance/<int:attendance_id>/test/<int:test_id>/done",
                    methods=["POST"])
@module_required(MODULE)
def test_done(attendance_id, test_id):
    """**Done at the bedside, now** — «رسم القلب بيتعمل على طول فى الطوارئ».

    An ECG in emergency is done by whoever is at the trolley, minutes after it
    is asked for; sending them to another room's list to say so is a trip
    nobody makes, and the order then sits «not done» on two screens. So the
    study is marked done here, the same event the studies' own screen writes
    (`performed_at`, never a sample time), and its report is written on the
    order screen like any other.

    Only the room's kinds, and only this child's own orders.
    """
    from app.models import EmergencyVisit, VisitInvestigation
    from app.utils import labs as bench

    row = db.get_or_404(EmergencyVisit, attendance_id)
    test = db.get_or_404(VisitInvestigation, test_id)
    if row.visit_id is None or test.visit_id != row.visit_id:
        abort(404)
    try:
        bench.perform(test, user=current_user)
    except ValueError:
        db.session.rollback()
        flash(t("imaging.not_a_scan") if test.kind not in bench.ROOMS
              else t("imaging.already_reported"), "warning")
        return redirect(url_for("emergency.attendance", attendance_id=row.id)
                        + "#tests")
    db.session.commit()
    flash(t("imaging.marked_done"), "success")
    return redirect(url_for("emergency.attendance", attendance_id=row.id)
                    + "#tests")


def _refresh_bell():
    try:
        from app.utils.notifications import invalidate

        invalidate()
    except Exception:  # noqa: BLE001
        pass
