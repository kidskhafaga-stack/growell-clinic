"""The theatre list, and the checklist that stands in front of the knife.

Two screens. **The day** is a list somebody prints and pins to a wall: which
room, which child, what is being done, who is doing it. **The case** is the
one that matters, and its centre is the WHO Surgical Safety Checklist rather
than a form about times — ``HOSPITAL_PLAN.md`` ٤-ج is explicit that the
schedule is the easy half.

**Where a case comes from.** Two doors, because there are two kinds of
operation and one door would have hidden the other kind: a day case is booked
from the theatre day itself, and a child already in a bed is booked from their
stay, where whoever is looking after them is standing. Both land on the same
list.

**What the program refuses.** Exactly one thing: starting a case whose sign-in
has not been signed. Everything else it records as it happened, including a
stop signed with items unticked — which is stored with the unticked ones named
rather than rounded up to "done".
"""
from datetime import datetime

from flask import (abort, flash, g, jsonify, redirect, render_template,
                   request, url_for)
from flask_login import current_user

from app.blueprints.theatres import theatres_bp
from app.extensions import db
from app.i18n import t
from app.models import Patient
from app.models.admission import Admission
from app.models.theatre import (CHECK_ITEMS, CHECK_STOPS, OPERATION_STATUSES,
                                ANAESTHESIA_TYPES, IDENTITY_WITH, PRECAUTIONS,
                                SITE_SIDES,
                                REVIEW_KINDS, REVIEW_VERDICTS, Operation,
                                Theatre)
from app.utils import privileges as _privileges
from app.utils import surgical_counts as _counts
from app.utils import operative_report as _report
from app.utils import recovery as _recovery
from app.utils import theatres as theatre
from app.utils.clock import local_today, to_utc
from app.utils.decorators import admin_required, module_required

MODULE = "theatres"


@theatres_bp.route("/")
@module_required(MODULE)
def index():
    """Today's list, room by room."""
    on_date = _a_date(request.args.get("date")) or local_today()
    # Whose list. `mine` is the shortcut a doctor presses; an explicit id is
    # what the coordinator picks from the dropdown. Both land here, because
    # "my list" is not a different screen — it is this one, shorter.
    who = request.args.get("who", type=int)
    if request.args.get("mine") and current_user.is_authenticated:
        who = current_user.id
    return render_template("theatres/index.html",
                           # What kinds of case this clinic prices
                           # differently, for the booking form.
                           case_kinds=_case_kinds(),
                           on_date=on_date, rooms=theatre.day(on_date, who=who),
                           who=who,
                           # How many are waiting, on the button that opens
                           # the queue. A queue nobody can see the length of
                           # is a queue nobody clears.
                           waiting=len(theatre.unreviewed()),
                           # How many are still in recovery, on the button
                           # that opens it. A room nobody can see the count
                           # of is a room somebody forgets a child in.
                           in_recovery=len(_recovery.in_recovery()),
                           # Who this day has, so the dropdown lists the
                           # people who actually have a case on it rather
                           # than every doctor in the clinic.
                           on_today=theatre.people_on(on_date),
                           # Which of today's cases need more than the usual
                           # infection precautions (SAS.06 ح). **This is the
                           # one place that answer does work instead of being
                           # filed**: whoever draws up the order of the list
                           # has to know before they draw it up, and the room
                           # is turned over differently afterwards.
                           precaution_cases=theatre.precaution_cases(on_date),
                           # The booking form's room picker reads this, not
                           # the filtered day: a doctor looking at their own
                           # list must still be able to book into any room,
                           # and looping the filtered list would have left
                           # them only the rooms they already have a case in.
                           all_rooms=(Theatre.query
                                      .filter(Theatre.is_active.is_(True))
                                      .order_by(Theatre.sort_order, Theatre.id)
                                      .all()),
                           stops=CHECK_STOPS,
                           surgeons=_surgeons(),
                           services=_procedures(),
                           may_build=current_user.is_admin)


@theatres_bp.route("/setup")
@module_required(MODULE)
def setup():
    """Where the rooms are added — from the screen, never from a release."""
    _admin_only()
    return render_template("theatres/setup.html",
                           rooms=(Theatre.query
                                  .order_by(Theatre.sort_order, Theatre.id)
                                  .all()))


@theatres_bp.route("/room", methods=["POST"])
@module_required(MODULE)
def room():
    _admin_only()
    name = (request.form.get("name") or "").strip()[:80]
    if not name:
        flash(t("theatre.need_name"), "error")
        return redirect(url_for("theatres.setup"))
    db.session.add(Theatre(name=name,
                           sort_order=request.form.get("sort_order", type=int) or 0,
                           note=(request.form.get("note") or "").strip()[:160]
                           or None))
    db.session.commit()
    flash(t("theatre.room_added"), "success")
    return redirect(url_for("theatres.setup"))


@theatres_bp.route("/room/<int:room_id>/toggle", methods=["POST"])
@module_required(MODULE)
def toggle_room(room_id):
    """Out of use, and back. Never deleted — last month's list of what was
    done in this room is a thing a hospital reports on."""
    _admin_only()
    row = Theatre.query.get_or_404(room_id)
    row.is_active = not row.is_active
    row.note = ((request.form.get("note") or "").strip()[:160] or None
                if not row.is_active else None)
    db.session.commit()
    return redirect(url_for("theatres.setup"))


def _case_kinds():
    """The kinds a case can be, for the pickers.

    Empty stays empty: a clinic that switched every kind off never sees the
    field, and every case it books prices at the doctor's ordinary rate —
    exactly as it did before any of this existed.
    """
    from app.utils import case_types

    return case_types.active_types()


def _a_case_type(raw):
    """A posted kind of case, or ``None``.

    Checked against the catalogue rather than stored as typed: this string
    decides which rate a surgeon is paid at, and a value nothing matches
    would silently fall back to the ordinary rate while the screen showed a
    kind somebody chose.
    """
    from app.utils import case_types

    key = (raw or "").strip()
    if not key:
        return None
    return key if key in {row.key for row in case_types.all_types()} else None


# ------------------------------------------------------------ booking it ---
@theatres_bp.route("/book", methods=["POST"])
@module_required(MODULE)
def book():
    """Put a case on the list, from either door."""
    patient = Patient.query.get(request.form.get("patient_id", type=int))
    room = Theatre.query.get(request.form.get("theatre_id", type=int))
    admission = Admission.query.get(request.form.get("admission_id", type=int))
    try:
        row = theatre.book(
            patient, room, request.form.get("procedure"),
            on_date=_a_date(request.form.get("date")),
            user=current_user,
            admission_id=admission.id if admission else None,
            service_id=request.form.get("service_id", type=int),
            surgeon_id=request.form.get("surgeon_id", type=int),
            anaesthetist_id=request.form.get("anaesthetist_id", type=int),
            start_time=_a_time(request.form.get("start_time")),
            minutes=request.form.get("minutes", type=int),
            case_type=_a_case_type(request.form.get("case_type")),
            team=(request.form.get("team") or "").strip()[:255])
    except ValueError as why:
        db.session.rollback()
        # Which refusal it was, because "no child", "no room" and "no
        # procedure" send whoever is booking to three different next steps.
        flash(t({"no patient": "theatre.need_patient",
                 "no procedure": "theatre.need_procedure"}
                .get(str(why), "theatre.need_room")), "error")
        return redirect(request.referrer or url_for("theatres.index"))
    db.session.commit()
    flash(t("theatre.booked"), "success")
    return redirect(url_for("theatres.operation", operation_id=row.id))


@theatres_bp.route("/operation/<int:operation_id>")
@module_required(MODULE)
def operation(operation_id):
    """One case, with the checklist at the centre of it."""
    row = Operation.query.get_or_404(operation_id)
    return render_template("theatres/operation.html", operation=row,
                           safety=theatre.safety(row),
                           # The pre-operative answers belong beside the
                           # checklist, not on a screen of their own: whoever
                           # is about to sign the case in is the person who
                           # most needs to read "not fit — chest infection".
                           reviews=theatre.reviews(row),
                           blocking=theatre.blocking(row),
                           kinds=REVIEW_KINDS, verdicts=REVIEW_VERDICTS,
                           stops=CHECK_STOPS, items=CHECK_ITEMS,
                           statuses=OPERATION_STATUSES,
                           rooms=(Theatre.query
                                  .filter(Theatre.is_active.is_(True))
                                  .order_by(Theatre.sort_order, Theatre.id)
                                  .all()),
                           case_kinds=_case_kinds(),
                           # What this procedure's instructions say, and when
                           # it would usually be seen again — both shown
                           # *before* the discharge is pressed, because that
                           # is when somebody can still fix a blank one.
                           # Which document covers this case, and what is
                           # on the child's file to choose from — including
                           # the unsigned ones, because the person linking
                           # has to be able to see that.
                           consent_state=theatre.consent_state(row),
                           # The anaesthetist's half: the assessment made in
                           # the anaesthetic room, and the six-element plan.
                           pre_induction=theatre.pre_induction_state(row),
                           # The site and the blood — the two remaining
                           # sign-in items the standard asks be *verified*.
                           site_state=theatre.site_state(row),
                           site_sides=SITE_SIDES,
                           # Who this child is — the other half of the
                           # never-event. The guardians already on file are
                           # offered so confirming is one click rather than
                           # a name typed again, and only the identifiers
                           # the program actually holds for this child are
                           # offered at all.
                           identity_state=theatre.identity_state(row),
                           identity_with=IDENTITY_WITH,
                           identity_options=theatre.identity_options(row),
                           identity_matched=theatre.identity_matched_keys(row),
                           # The investigations this case waits on (SAS.06 هـ).
                           # Whoever is attaching has to see the child's other
                           # orders *with* their results, so an answer that is
                           # not back yet is visible before it is relied on.
                           workup_state=theatre.workup_state(row),
                           imaging_state=theatre.workup_state(row,
                                                              kind="imaging"),
                           workup_orders=theatre.workup_orders(row),
                           workup_choices=theatre.workup_choices(row),
                           # What this case needs beyond the usual (SAS.06 ح).
                           infection_state=theatre.infection_state(row),
                           precautions=PRECAUTIONS,
                           chosen_precautions=theatre.precautions_of(row),
                           # What the case needs in the room, and what was
                           # found (SAS.06 ب). Two facts per item — there, and
                           # works — because a stack whose light is dead is not
                           # equipment this case has.
                           equipment_state=theatre.equipment_state(row),
                           equipment=theatre.equipment_for(row),
                           # What happened in the room (SAS.08). Five of
                           # its nine elements are already in the record, so
                           # the screen asks for four and a signature.
                           report_state=_report.state(row),
                           report=_report.for_operation(row),
                           report_elements=_report.assemble(row),
                           report_missing=_report.missing(row),
                           report_late=_report.late(row),
                           report_staff=_report.staff(row),
                           report_implants=_report.implants(row),
                           # The sponges, needles and instruments (SAS.09).
                           # Three moments, two people, and the numbers — and
                           # the checklist box now reads off these rather than
                           # being tickable.
                           count_state=_counts.state(row),
                           counts=_counts.counts_for(row),
                           count_moments=_counts.MOMENTS,
                           count_items=_counts.ITEMS,
                           count_signed=_counts.signed(row),
                           open_miscounts=_counts.open_miscounts(row),
                           # What this case plans to implant, and what went in
                           # (SAS.06 ز / SAS.11). Two moments, kept apart.
                           implant_state=theatre.implant_state(row),
                           implants=theatre.implants_for(row),
                           # Is this booking inside the surgeon's privileges
                           # (SAS.02 أ)? Derived, and judged against the day of
                           # the operation.
                           privilege_state=theatre.privilege_state(row),
                           privilege_rows=_privileges.matching(
                               row.surgeon_id, row.service, row.on_date),
                           # The clock the unit runs on (SAS.02 هـ): from the
                           # call to the room being cleaned, with the gaps.
                           timeline=theatre.timeline(row),
                           waited=theatre.waited_minutes(row),
                           turnover=theatre.turnover_minutes(row),
                           # How long it was booked for against how long it
                           # took (SAS.02 ب). Shown, never graded: the
                           # "international surgery times" the standard names
                           # are a reference this program does not hold.
                           time_plan=theatre.time_plan(row),
                           blood_state=theatre.blood_state(row),
                           plan=theatre.plan_for(row),
                           anaesthesia_types=ANAESTHESIA_TYPES,
                           consent_choices=theatre.consent_choices(row),
                           post_op_text=_recovery.instructions_for(row),
                           followup_default=_recovery.followup_default(row),
                           surgeons=_surgeons(), services=_procedures())


@theatres_bp.route("/operation/<int:operation_id>/sign", methods=["POST"])
@module_required(MODULE)
def sign(operation_id):
    """Sign off one stop of the checklist, with whatever was actually ticked."""
    row = Operation.query.get_or_404(operation_id)
    stop = (request.form.get("stop") or "").strip()
    try:
        check = theatre.sign(row, stop, items=request.form.getlist("item"),
                             user=current_user,
                             note=request.form.get("note"), at=_happened_at())
    except ValueError:
        db.session.rollback()
        flash(t("theatre.unknown_stop"), "error")
        return redirect(url_for("theatres.operation", operation_id=row.id))
    db.session.commit()
    # A stop signed short says so out loud. Silence would let a checklist that
    # was not finished read exactly like one that was, which is the single
    # failure a safety checklist exists to prevent.
    flash(t("theatre.signed_short", n=len(check.missed))
          if check.missed else t("theatre.signed"),
          "info" if check.missed else "success")
    return redirect(url_for("theatres.operation", operation_id=row.id))


@theatres_bp.route("/preop")
@module_required(MODULE)
def preop():
    """The cases nobody has looked at yet — the anaesthetist's working list.

    A screen of its own rather than a column on the day, because the point of
    moving the question earlier is that somebody can **sit down and clear
    it**. A column would mean opening the list every morning and scanning for
    gaps, which is the reading the checklist's own sign-in stop already does
    badly at the worst possible moment.

    Filtered to one kind on request, because the surgeon and the anaesthetist
    are answering different questions and neither wants the other's queue.
    """
    kind = request.args.get("kind")
    kind = kind if kind in REVIEW_KINDS else None
    return render_template(
        "theatres/preop.html",
        rows=theatre.unreviewed(kind=kind),
        reviews_of=theatre.reviews,
        kind=kind, kinds=REVIEW_KINDS, verdicts=REVIEW_VERDICTS,
        today=local_today())


@theatres_bp.route("/operation/<int:operation_id>/review", methods=["POST"])
@module_required(MODULE)
def review(operation_id):
    """Record the surgeon's or the anaesthetist's answer on one case."""
    row = Operation.query.get_or_404(operation_id)
    try:
        theatre.review(row, (request.form.get("kind") or "").strip(),
                       (request.form.get("verdict") or "").strip(),
                       user=current_user, note=request.form.get("note"))
    except ValueError as why:
        db.session.rollback()
        # Three refusals and three different next steps: a reason is typed, a
        # kind is picked, a verdict is picked. One message for all of them
        # would send somebody hunting.
        flash(t({"needs a reason": "theatre.review_needs_reason",
                 "unknown verdict": "theatre.review_pick_verdict"}
                .get(str(why), "theatre.review_pick_kind")), "error")
        return redirect(request.referrer or url_for("theatres.preop"))
    db.session.commit()
    flash(t("theatre.reviewed"), "success")
    return redirect(request.referrer
                    or url_for("theatres.operation", operation_id=row.id))


@theatres_bp.route("/operation/<int:operation_id>/start", methods=["POST"])
@module_required(MODULE)
def start(operation_id):
    """Take the child in — the one address in this module that says no."""
    row = Operation.query.get_or_404(operation_id)
    try:
        theatre.start(row, user=current_user, when=_happened_at())
    except theatre.NotSafeYet:
        db.session.rollback()
        flash(t("theatre.not_signed_in"), "error")
        return redirect(url_for("theatres.operation", operation_id=row.id))
    except ValueError:
        db.session.rollback()
        flash(t("theatre.not_scheduled"), "error")
        return redirect(url_for("theatres.operation", operation_id=row.id))
    db.session.commit()
    flash(t("theatre.started"), "success")
    return redirect(url_for("theatres.operation", operation_id=row.id))


@theatres_bp.route("/operation/<int:operation_id>/finish", methods=["POST"])
@module_required(MODULE)
def finish(operation_id):
    """The case is over. The sign-out is asked for and never forced."""
    row = Operation.query.get_or_404(operation_id)
    try:
        theatre.finish(row, user=current_user,
                       findings=request.form.get("findings"),
                       when=_happened_at())
    except ValueError:
        db.session.rollback()
        flash(t("theatre.not_started"), "error")
        return redirect(url_for("theatres.operation", operation_id=row.id))
    db.session.commit()
    flash(t("theatre.finished"), "success")
    if row.check_for("sign_out") is None:
        # Kept saying it rather than refusing the finish: a gap that is
        # visible is worth more than a refusal that gets worked around.
        flash(t("theatre.sign_out_missing"), "error")
    return redirect(url_for("theatres.operation", operation_id=row.id))


@theatres_bp.route("/operation/<int:operation_id>/edit", methods=["POST"])
@module_required(MODULE)
def edit(operation_id):
    """Correct the booking.

    **Without this the module had a one-way door.** A case is often put on the
    list before anybody knows who is operating or what it will be charged as —
    the clerk books "Tuesday, theatre two" and the rest is settled at the
    morning meeting. Set only at booking, an operation with no surgeon and no
    service could never be given either, so it could never be billed and the
    share could never reach anybody.

    Locked once it has been charged: the surgeon and the service are what the
    bill was built from, and changing them afterwards would leave an invoice
    line nothing on this screen accounts for. The procedure text and the notes
    stay editable, because those are the record rather than the price.
    """
    row = Operation.query.get_or_404(operation_id)
    procedure = (request.form.get("procedure") or "").strip()[:200]
    if procedure:
        row.procedure = procedure
    row.team = (request.form.get("team") or "").strip()[:255] or None

    if row.invoice_item_id is not None:
        db.session.commit()
        flash(t("theatre.locked_billed"), "info")
        return redirect(url_for("theatres.operation", operation_id=row.id))

    theatre_id = request.form.get("theatre_id", type=int)
    if theatre_id and Theatre.query.get(theatre_id) is not None:
        row.theatre_id = theatre_id
    on_date = _a_date(request.form.get("date"))
    if on_date is not None:
        row.on_date = on_date
    row.start_time = _a_time(request.form.get("start_time")) or row.start_time
    row.minutes = request.form.get("minutes", type=int) or row.minutes
    # These three may be *cleared*, so an empty box means "nobody" rather than
    # "leave it as it was" — a booking made with the wrong surgeon on it has
    # to be able to end up with none.
    row.service_id = request.form.get("service_id", type=int)
    row.surgeon_id = request.form.get("surgeon_id", type=int)
    row.anaesthetist_id = request.form.get("anaesthetist_id", type=int)
    # Cleared the same way, and for the same reason: a case booked as private
    # by mistake has to be able to end up as a case nobody classified, which
    # is a real state and not "private with the label removed".
    row.case_type = _a_case_type(request.form.get("case_type"))
    db.session.commit()
    flash(t("theatre.saved"), "success")
    return redirect(url_for("theatres.operation", operation_id=row.id))


@theatres_bp.route("/operation/<int:operation_id>/site", methods=["POST"])
@module_required(MODULE)
def mark_site(operation_id):
    """Record which side, and who says so.

    The never-event one: a box saying "site marked" with no record of *which*
    site is how a wrong-side operation gets a signature saying it was
    verified.
    """
    row = Operation.query.get_or_404(operation_id)
    if theatre.mark_site(row, (request.form.get("side") or "").strip(),
                         current_user,
                         note=request.form.get("site_note")) is None:
        flash(t("theatre.site_needs_side"), "warning")
        return redirect(url_for("theatres.operation", operation_id=row.id))
    db.session.commit()
    flash(t("theatre.site_marked_ok"), "success")
    return redirect(url_for("theatres.operation", operation_id=row.id))


@theatres_bp.route("/operation/<int:operation_id>/identity", methods=["POST"])
@module_required(MODULE)
def verify_identity(operation_id):
    """Record that somebody confirmed this child, and who stood with them.

    SAS.06 (أ). The half of the never-event the site marking does not cover:
    right patient, right procedure. A blank answer for who took part is
    refused rather than read as "nobody was there" — *not asked* and *nobody
    came* are two different mornings, and this program does not let one empty
    value stand for two facts.
    """
    row = Operation.query.get_or_404(operation_id)
    done = theatre.verify_identity(
        row, (request.form.get("with_whom") or "").strip(),
        name=request.form.get("with_name"),
        matched=request.form.getlist("matched"),
        user=current_user)
    if done is None:
        flash(t("theatre.identity_needs_who"), "warning")
        return redirect(url_for("theatres.operation", operation_id=row.id))
    db.session.commit()
    flash(t("theatre.identity_ok"), "success")
    return redirect(url_for("theatres.operation", operation_id=row.id))


@theatres_bp.route("/operation/<int:operation_id>/call", methods=["POST"])
@module_required(MODULE)
def call_patient(operation_id):
    """Call the child for the case, and start the clock.

    SAS.02 (هـ). Recorded once — a second call is somebody chasing, not a new
    beginning — and the screen says so rather than silently doing nothing.
    """
    row = Operation.query.get_or_404(operation_id)
    if theatre.call_patient(row, to=request.form.get("called_to"),
                            user=current_user) is None:
        flash(t("theatre.call_already"), "warning")
        return redirect(url_for("theatres.operation", operation_id=row.id))
    db.session.commit()
    flash(t("theatre.call_recorded"), "success")
    return redirect(url_for("theatres.operation", operation_id=row.id))


@theatres_bp.route("/operation/<int:operation_id>/cleaned", methods=["POST"])
@module_required(MODULE)
def mark_cleaned(operation_id):
    """The room is ready for the next case — the end of the clock.

    Refused before the case has finished: a stamp that can land out of order
    makes every turnover figure computed from it wrong.
    """
    row = Operation.query.get_or_404(operation_id)
    if theatre.mark_cleaned(row, user=current_user) is None:
        flash(t("theatre.cleaned_not_yet"), "warning")
        return redirect(url_for("theatres.operation", operation_id=row.id))
    db.session.commit()
    flash(t("theatre.cleaned_recorded"), "success")
    return redirect(url_for("theatres.operation", operation_id=row.id))


@theatres_bp.route("/operation/<int:operation_id>/privilege", methods=["POST"])
@module_required(MODULE)
def acknowledge_privilege(operation_id):
    """Accept a booking outside the surgeon's privileges — with a reason.

    The reason is the point. "Somebody clicked accept" is the tick this module
    keeps replacing; the sentence they typed is the only part of this a review
    afterwards can use.
    """
    row = Operation.query.get_or_404(operation_id)
    if theatre.acknowledge_privilege(row, request.form.get("reason"),
                                     user=current_user) is None:
        flash(t("theatre.privilege_needs_reason"), "warning")
        return redirect(url_for("theatres.operation", operation_id=row.id))
    db.session.commit()
    flash(t("theatre.privilege_acknowledged_ok"), "success")
    return redirect(url_for("theatres.operation", operation_id=row.id))


@theatres_bp.route("/operation/<int:operation_id>/implants", methods=["POST"])
@module_required(MODULE)
def implants(operation_id):
    """Plan, confirm and record what goes into this child.

    SAS.06 (ز) — is it here — and SAS.11 — what went in, with its batch. One
    screen because it is one row seen at two moments, and separating them
    would have somebody retype a serial number.
    """
    from app.models.theatre import OperationImplant

    row = Operation.query.get_or_404(operation_id)
    raw = (request.form.get("needed") or "").strip()
    if raw in ("yes", "no"):
        theatre.set_implants_needed(row, raw == "yes", user=current_user)

    theatre.add_implant(row, request.form.get("new_name"),
                        lot=request.form.get("new_lot"),
                        manufacturer=request.form.get("new_manufacturer"),
                        serial=request.form.get("new_serial"),
                        size=request.form.get("new_size"))
    db.session.flush()

    complained = False
    for item in theatre.implants_for(row):
        action = request.form.get(f"do_{item.id}")
        if action == "here":
            theatre.confirm_implant(item, user=current_user)
        elif action == "in":
            if theatre.record_implanted(
                    item, lot=request.form.get(f"lot_{item.id}"),
                    serial=request.form.get(f"serial_{item.id}"),
                    user=current_user) is None:
                # Refused, and the person has to be told why: a child with an
                # implant and no batch number is a child a recall cannot find.
                complained = True
        elif action == "drop":
            theatre.remove_implant(item)
    db.session.commit()
    flash(t("theatre.implant_needs_lot") if complained
          else t("common.saved"), "warning" if complained else "success")
    return redirect(url_for("theatres.operation", operation_id=row.id))


@theatres_bp.route("/privileges", methods=["GET", "POST"])
@module_required(MODULE)
@admin_required
def privileges_screen():
    """What each doctor is authorised to do here (GAHAR WFM.12).

    Admin-only to write, because granting a privilege is a credentialing
    decision and the standard says so: *"approved by the medical staff
    committee"*. Reading it is not restricted the same way — whoever books
    has to see it, which is the fourth item of evidence.
    """
    from app.models import PRIVILEGE_KINDS, Service, ServiceType, User
    from app.utils import privileges as priv

    doctors = (User.query.filter(User.is_active.is_(True),
                                 User.role.in_(("doctor", "admin")))
               .order_by(User.full_name).all())
    who = request.args.get("doctor", type=int) or (doctors[0].id if doctors
                                                   else None)

    if request.method == "POST":
        action = (request.form.get("action") or "").strip()
        if action == "withdraw":
            from app.models import ClinicalPrivilege
            row = ClinicalPrivilege.query.get_or_404(
                request.form.get("privilege_id", type=int))
            if priv.withdraw(row, reason=request.form.get("reason")) is None:
                flash(t("privileges.already_withdrawn"), "warning")
            else:
                db.session.commit()
                flash(t("privileges.withdrawn"), "success")
        else:
            scope = (request.form.get("scope") or "").strip()
            granted = priv.grant(
                request.form.get("doctor_id", type=int),
                service_id=(request.form.get("service_id", type=int)
                            if scope == "service" else None),
                service_type=(request.form.get("service_type")
                              if scope == "type" else None),
                kind=(request.form.get("kind") or "standard").strip(),
                supervisor_id=request.form.get("supervisor_id", type=int),
                supervision=request.form.get("supervision"),
                valid_from=_a_date(request.form.get("valid_from")),
                valid_until=_a_date(request.form.get("valid_until")),
                note=request.form.get("note"), user=current_user)
            if granted is None:
                # Named rather than a generic "could not save": the two ways
                # this fails send somebody to two different corrections.
                flash(t("privileges.needs_one_scope"), "warning")
            else:
                db.session.commit()
                flash(t("privileges.granted"), "success")
        return redirect(url_for("theatres.privileges_screen", doctor=who))

    return render_template(
        "theatres/privileges.html", doctors=doctors, who=who,
        rows=priv.all_for(who), kinds=PRIVILEGE_KINDS,
        today=local_today(),
        # Only what a theatre actually books against.
        services=(Service.query.filter(Service.is_active.is_(True))
                  .order_by(Service.name).all()),
        types=(ServiceType.query.filter(ServiceType.is_active.is_(True))
               .order_by(ServiceType.sort_order, ServiceType.id).all()))


@theatres_bp.route("/implants/recall")
@module_required(MODULE)
def implant_recall():
    """Which children have one of these.

    *"There is a process for the recall of a patient who has an implantable
    device when necessary."* Its own screen, because when it is needed it is
    needed in a hurry and nobody should be hunting for it inside a case.
    """
    terms = {k: (request.args.get(k) or "").strip()
             for k in ("name", "lot", "serial", "manufacturer")}
    asked = any(terms.values())
    return render_template(
        "theatres/recall.html", terms=terms, asked=asked,
        # Nothing is listed until somebody asks something: a screen that opens
        # with every implant the clinic ever used is a list nobody reads, and
        # the question a recall asks is always narrow.
        hits=theatre.recall(**terms) if asked else [])


@theatres_bp.route("/operation/<int:operation_id>/equipment", methods=["POST"])
@module_required(MODULE)
def equipment(operation_id):
    """What this case needs in the room, and what was found.

    SAS.06 (ب): *"The availability and functioning of needed equipment"*,
    verified **before calling for the patient**. Blank is refused rather than
    read as "needs nothing".
    """
    row = Operation.query.get_or_404(operation_id)
    raw = (request.form.get("needed") or "").strip()
    if raw not in ("yes", "no"):
        flash(t("theatre.equipment_needs_answer"), "warning")
        return redirect(url_for("theatres.operation", operation_id=row.id))
    theatre.set_equipment_needed(row, raw == "yes", user=current_user)

    # One more thing this list does not carry — most theatres, most days.
    theatre.add_equipment(row, request.form.get("new_item"))
    db.session.flush()

    # What was found, item by item. A box nobody touched stays unknown: the
    # form posts an explicit answer per item, and an absent one is not "no".
    answers = {}
    for item in theatre.equipment_for(row):
        found = request.form.get(f"present_{item.id}")
        if found not in ("yes", "no"):
            continue
        answers[item.id] = {"present": found == "yes",
                            "working": request.form.get(
                                f"working_{item.id}") == "yes",
                            "note": request.form.get(f"note_{item.id}")}
    if answers:
        theatre.check_equipment(row, answers, user=current_user)
    db.session.commit()
    flash(t("common.saved"), "success")
    return redirect(url_for("theatres.operation", operation_id=row.id))


@theatres_bp.route("/operation/<int:operation_id>/precautions",
                  methods=["POST"])
@module_required(MODULE)
def precautions(operation_id):
    """Record what this case needs beyond what every case gets.

    SAS.06 (ح): *"Special precautions for infection control preparation."*
    Nothing ticked is refused rather than stored as "standard" — *nobody
    asked* and *this case needs nothing extra* are two different answers, and
    the whole point of the field is to tell them apart.
    """
    row = Operation.query.get_or_404(operation_id)
    if theatre.note_precautions(
            row, request.form.getlist("precaution"),
            note=request.form.get("infection_note"),
            empiric=bool(request.form.get("empiric")),
            user=current_user) is None:
        flash(t("theatre.precautions_need_answer"), "warning")
        return redirect(url_for("theatres.operation", operation_id=row.id))
    db.session.commit()
    flash(t("common.saved"), "success")
    return redirect(url_for("theatres.operation", operation_id=row.id))


@theatres_bp.route("/operation/<int:operation_id>/workup", methods=["POST"])
@module_required(MODULE)
def workup(operation_id):
    """Whether this case waits on investigations, and which ones.

    SAS.06 (هـ). Blank is refused rather than read as "none needed": on this
    question the difference is a child anaesthetised before anybody read the
    result.
    """
    from app.models.visit import VisitInvestigation

    row = Operation.query.get_or_404(operation_id)
    raw = (request.form.get("needed") or "").strip()
    if raw not in ("yes", "no"):
        flash(t("theatre.workup_needs_answer"), "warning")
        return redirect(url_for("theatres.operation", operation_id=row.id))
    theatre.set_workup(row, raw == "yes", user=current_user)

    # Which of this child's orders this case waits on. The whole set is
    # rewritten from what was ticked, so unticking one detaches it — and
    # detaching never deletes the order, which is a request somebody really
    # made.
    wanted = set(request.form.getlist("order", type=int))
    for order in theatre.workup_choices(row):
        if order.id in wanted:
            theatre.link_investigation(row, order)
        elif order.operation_id == row.id:
            theatre.unlink_investigation(order)
    # Ticking "no" and leaving orders attached is a contradiction; the answer
    # somebody just gave wins, and the orders go back to being the child's.
    if raw == "no":
        for order in VisitInvestigation.query.filter_by(
                operation_id=row.id).all():
            theatre.unlink_investigation(order)
    db.session.commit()
    flash(t("common.saved"), "success")
    return redirect(url_for("theatres.operation", operation_id=row.id))


@theatres_bp.route("/operation/<int:operation_id>/blood", methods=["POST"])
@module_required(MODULE)
def blood(operation_id):
    """Whether this case needs blood, and whether it is actually reserved."""
    row = Operation.query.get_or_404(operation_id)
    raw = (request.form.get("needed") or "").strip()
    if raw not in ("yes", "no"):
        # Blank is refused rather than read as "no": on this question
        # "nobody asked" and "none needed" are not the same sentence.
        flash(t("theatre.blood_needs_answer"), "warning")
        return redirect(url_for("theatres.operation", operation_id=row.id))
    theatre.set_blood(row, raw == "yes",
                      units=request.form.get("units", type=int),
                      reserved=bool(request.form.get("reserved")),
                      user=current_user)
    db.session.commit()
    flash(t("common.saved"), "success")
    return redirect(url_for("theatres.operation", operation_id=row.id))


@theatres_bp.route("/operation/<int:operation_id>/plan", methods=["POST"])
@module_required(MODULE)
def anaesthesia_plan(operation_id):
    """Record the six-element anaesthesia plan.

    The headings are the standard's (GAHAR SAS.16 EOC 2); every word under
    them is the anaesthetist's. A program that filled in a dose would be
    inventing a clinical number.
    """
    row = Operation.query.get_or_404(operation_id)
    theatre.write_plan(
        row, current_user,
        kind=request.form.get("kind"),
        induction=request.form.get("induction"),
        airway=request.form.get("airway"),
        fluids=request.form.get("fluids"),
        given_during=request.form.get("given_during"),
        events=request.form.get("events"))
    db.session.commit()
    flash(t("theatre.plan_saved"), "success")
    return redirect(url_for("theatres.operation", operation_id=row.id))


@theatres_bp.route("/operation/<int:operation_id>/consent", methods=["POST"])
@module_required(MODULE)
def link_consent(operation_id):
    """Name which signed document covers this case.

    Linked by a person, never matched by the program: it does not know what
    the guardian was told, and guessing that a «procedure» consent from March
    covers September's tonsillectomy would produce exactly the false green
    tick this exists to remove.
    """
    row = Operation.query.get_or_404(operation_id)
    raw = (request.form.get("consent_id") or "").strip()
    if not raw:
        row.consent_id = None
        db.session.commit()
        flash(t("theatre.consent_unlinked"), "info")
        return redirect(url_for("theatres.operation", operation_id=row.id))

    # Only this child's own consents. A posted id is a number anybody can
    # type, and this one answers a surgical safety item.
    allowed = {c.id for c in theatre.consent_choices(row)}
    try:
        chosen = int(raw)
    except (TypeError, ValueError):
        chosen = 0
    if chosen not in allowed:
        flash(t("theatre.consent_not_this_child"), "warning")
        return redirect(url_for("theatres.operation", operation_id=row.id))

    row.consent_id = chosen
    db.session.commit()
    state = theatre.consent_state(row)
    flash(t("theatre.consent_linked") if state == "linked"
          else t("theatre.consent_" + state), "success" if state == "linked"
          else "warning")
    return redirect(url_for("theatres.operation", operation_id=row.id))


@theatres_bp.route("/operation/<int:operation_id>/recovery", methods=["POST"])
@module_required(MODULE)
def to_recovery(operation_id):
    """The child has left theatre. One press, by whoever wheeled them out."""
    from app.utils import recovery

    row = Operation.query.get_or_404(operation_id)
    if recovery.to_recovery(row, current_user) is None:
        flash(t("recovery.not_done_yet"), "warning")
        return redirect(url_for("theatres.operation", operation_id=row.id))
    db.session.commit()
    flash(t("recovery.in_recovery"), "success")
    return redirect(url_for("theatres.operation", operation_id=row.id))


@theatres_bp.route("/operation/<int:operation_id>/discharge", methods=["POST"])
@module_required(MODULE)
def discharge(operation_id):
    """Send a day case home — and answer the one question that cannot be
    skipped.

    The follow-up decision is refused when blank rather than defaulted,
    because «مش محتاج» and «محدش سأل» stop being the same sentence only if
    the screen makes somebody say which.
    """
    from app.utils import recovery

    row = Operation.query.get_or_404(operation_id)
    raw = (request.form.get("followup") or "").strip()
    if raw not in ("yes", "no"):
        flash(t("recovery.need_followup_answer"), "warning")
        return redirect(url_for("theatres.operation", operation_id=row.id))

    out = recovery.discharge(
        row, current_user,
        note=request.form.get("discharge_note"),
        followup=(raw == "yes"),
        followup_on=_a_date(request.form.get("followup_on")))
    if out is None:
        flash(t("recovery.cannot_discharge"), "warning")
        return redirect(url_for("theatres.operation", operation_id=row.id))

    # The instructions go with them, not later: the family is at the door, and
    # a message sent tomorrow is a message read after the night they needed it.
    sent = recovery.send_instructions(row, current_user)
    db.session.commit()
    flash(t("recovery.discharged"), "success")
    if sent is None and recovery.instructions_for(row) is None:
        # Said out loud rather than passed over. A procedure with no written
        # instructions is a gap in the price list, and the person discharging
        # is the one who can see it.
        flash(t("recovery.no_instructions"), "info")
    return redirect(url_for("theatres.operation", operation_id=row.id))


@theatres_bp.route("/recovery")
@module_required(MODULE)
def recovery_room():
    """Who is in recovery, and who finished and has not been sent home.

    The second list is the one that matters: a case nobody marked into
    recovery is a case nobody is counting, and a screen built only from the
    room itself would never show it.
    """
    from app.utils import recovery

    on_date = _a_date(request.args.get("date")) or local_today()
    return render_template("theatres/recovery.html", on_date=on_date,
                           here=recovery.in_recovery(),
                           waiting=recovery.awaiting_discharge(),
                           expecting=recovery.expecting(),
                           undecided=recovery.undecided())


@theatres_bp.route("/operation/<int:operation_id>/note", methods=["POST"])
@module_required(MODULE)
def note(operation_id):
    """The operation note — the one document the next doctor reads."""
    row = Operation.query.get_or_404(operation_id)
    row.findings = (request.form.get("findings") or "").strip() or None
    row.notes = (request.form.get("notes") or "").strip() or None
    db.session.commit()
    flash(t("theatre.note_saved"), "success")
    return redirect(url_for("theatres.operation", operation_id=row.id))


@theatres_bp.route("/operation/<int:operation_id>/cancel", methods=["POST"])
@module_required(MODULE)
def cancel(operation_id):
    """Called off — kept on the list, marked."""
    row = Operation.query.get_or_404(operation_id)
    theatre.cancel(row, reason=request.form.get("reason"), user=current_user)
    db.session.commit()
    flash(t("theatre.cancelled"), "info")
    return redirect(url_for("theatres.operation", operation_id=row.id))


@theatres_bp.route("/operation/<int:operation_id>/report", methods=["POST"])
@module_required(MODULE)
def write_report(operation_id):
    """The operative report — SAS.08.

    Four boxes and two notes. The other five of the standard's nine elements
    are read off the record, so nobody types a start time or an implant's lot
    number twice.
    """
    row = Operation.query.get_or_404(operation_id)

    def _tri(name):
        """`yes` · `no` · nothing said. A checkbox cannot carry three."""
        raw = (request.form.get(name) or "").strip()
        return True if raw == "yes" else (False if raw == "no" else None)

    def _number(name):
        """A number, or nobody measured. **Nought is an answer; minus is not.**

        The box says ``min="0"``, so a negative can only arrive from a browser
        that ignored it — and filing it as nought would turn a typo into «no
        measurable blood loss», which is a measurement somebody has to have
        taken.
        """
        raw = (request.form.get(name) or "").strip()
        if not raw:
            return None
        try:
            number = int(raw)
        except ValueError:
            return None
        return number if number >= 0 else None

    _report.write(row, user=current_user,
                  pre_diagnosis=request.form.get("pre_diagnosis"),
                  post_diagnosis=request.form.get("post_diagnosis"),
                  complications=_tri("complications"),
                  complications_note=request.form.get("complications_note"),
                  specimen=_tri("specimen"),
                  specimen_note=request.form.get("specimen_note"),
                  blood_loss_ml=_number("blood_loss_ml"),
                  transfused_units=_number("transfused_units"))
    db.session.commit()
    short = _report.missing(row)
    flash(t("op_report.saved_short", n=len(short)) if short else t("op_report.saved"),
          "warning" if short else "success")
    return redirect(url_for("theatres.operation", operation_id=row.id))


@theatres_bp.route("/operation/<int:operation_id>/report/sign", methods=["POST"])
@module_required(MODULE)
def sign_report(operation_id):
    """Element (i) — the performing physician's signature."""
    row = Operation.query.get_or_404(operation_id)
    if _report.sign(row, user=current_user) is None:
        flash(t("op_report.nothing_to_sign"), "warning")
        return redirect(url_for("theatres.operation", operation_id=row.id))
    db.session.commit()
    flash(t("op_report.signed"), "success")
    return redirect(url_for("theatres.operation", operation_id=row.id))


@theatres_bp.route("/operation/<int:operation_id>/count", methods=["POST"])
@module_required(MODULE)
def record_count(operation_id):
    """One counting event — SAS.09.

    Two people, and the second is the control the standard asks for: a witness
    who is the same person is refused rather than stored.
    """
    row = Operation.query.get_or_404(operation_id)
    numbers = {}
    for item in _counts.ITEMS:
        expected = request.form.get("expected_%s" % item, type=int)
        found = request.form.get("found_%s" % item, type=int)
        if expected is None and found is None:
            continue
        numbers[item] = (expected or 0, found or 0)
    try:
        written = _counts.record(
            row, (request.form.get("moment") or "").strip(), numbers,
            counted_by=current_user,
            witnessed_by=request.form.get("witness_id", type=int),
            note=request.form.get("note"))
    except _counts.NotTwoPeople:
        flash(t("counts.needs_two_people"), "warning")
        return redirect(url_for("theatres.operation", operation_id=row.id))
    if written is None:
        # Nothing was counted. An event with no items would make the state
        # read `ok` for a case nobody counted, which is the tick again.
        flash(t("counts.needs_numbers"), "warning")
        return redirect(url_for("theatres.operation", operation_id=row.id))
    db.session.commit()
    flash(t("counts.short_by_one") if not written.agrees else t("common.saved"),
          "error" if not written.agrees else "success")
    return redirect(url_for("theatres.operation", operation_id=row.id))


@theatres_bp.route("/count/<int:count_id>/miscount", methods=["POST"])
@module_required(MODULE)
def handle_miscount(count_id):
    """What the team did about a miscount — SAS.09 evidence 4.

    The intent names the steps: *"conduct re-counting, check the missing item,
    make provisions using imaging studies, and report the miscount."*
    """
    from app.models.surgical_count import SurgicalCount

    row = SurgicalCount.query.get_or_404(count_id)
    # Only what the form actually carried. A checkbox that is absent means
    # "not ticked" on a form that showed it, so each is read as a tri-state
    # from an explicit select rather than a checkbox.
    def _said(name):
        raw = (request.form.get(name) or "").strip()
        return True if raw == "yes" else (False if raw == "no" else None)

    _counts.handle_miscount(row, recounted=_said("recounted"),
                            imaging=_said("imaging"),
                            resolution=request.form.get("resolution"),
                            user=current_user)
    if request.form.get("report") == "1":
        _counts.report(row, user=current_user)
    db.session.commit()
    flash(t("common.saved"), "success")
    return redirect(url_for("theatres.operation",
                            operation_id=row.operation_id))


@theatres_bp.route("/operation/<int:operation_id>/count/sign", methods=["POST"])
@module_required(MODULE)
def sign_counts(operation_id):
    """The performing physician signs the count record — SAS.09 evidence 3."""
    row = Operation.query.get_or_404(operation_id)
    if _counts.sign(row, user=current_user) is None:
        flash(t("counts.nothing_to_sign"), "warning")
        return redirect(url_for("theatres.operation", operation_id=row.id))
    db.session.commit()
    flash(t("counts.signed"), "success")
    return redirect(url_for("theatres.operation", operation_id=row.id))


@theatres_bp.route("/operation/<int:operation_id>/postpone", methods=["POST"])
@module_required(MODULE)
def postpone(operation_id):
    """Moved to another day — not the same thing as called off.

    SAS.02's fourth item of evidence asks a theatre to analyse *"postponed
    and canceled"* procedures, which it can only do if the two were ever told
    apart. Its own button beside the cancel one, because a postponement typed
    into the cancel box is a cancellation for ever after.
    """
    row = Operation.query.get_or_404(operation_id)
    try:
        moved = theatre.postpone(row, _a_date(request.form.get("date")),
                                 reason=request.form.get("reason"),
                                 user=current_user)
    except ValueError:
        db.session.rollback()
        flash(t("theatre.postpone_needs_date"), "warning")
        return redirect(url_for("theatres.operation", operation_id=row.id))
    if moved is None:
        # Nothing open to move: already done, or already called off once.
        flash(t("theatre.postpone_not_open"), "warning")
        return redirect(url_for("theatres.operation", operation_id=row.id))
    db.session.commit()
    flash(t("theatre.postponed"), "success")
    # The new case, because that is the one somebody now has work on.
    return redirect(url_for("theatres.operation", operation_id=moved.id))


@theatres_bp.route("/call-offs")
@module_required(MODULE)
def call_offs():
    """What the theatre lost in a period, and why.

    *"There is a process for analyzing postponed and canceled procedures, and
    action is taken to improve them."* The program's half of that is the
    counting; the action is the clinic's, and nothing here grades it.
    """
    today = local_today()
    start = _a_date(request.args.get("start")) or today.replace(day=1)
    end = _a_date(request.args.get("end")) or today
    return render_template("theatres/calloffs.html",
                           start=start, end=end,
                           summary=theatre.calloff_analysis(start, end),
                           rows=theatre.call_offs(start, end))


@theatres_bp.route("/patient-search")
@module_required(MODULE)
def patient_search():
    """Autocomplete for the booking box.

    A thin route of its own rather than borrowing the appointments one, for
    the reason the ward's drug search has its own: that address sits behind a
    different module, and a theatre whose patient search stops working because
    somebody changed an unrelated setting is a bug waiting to happen.
    """
    from app.utils.patients import apply_patient_search

    query = (request.args.get("q") or "").strip()
    if len(query) < 2:
        return jsonify([])
    rows = (apply_patient_search(
        Patient.query.filter(Patient.is_active.is_(True)), query)
        .limit(10).all())
    lang = getattr(g, "lang", "ar")
    return jsonify([{"id": p.id, "name": p.display_name(lang),
                     "file": p.file_number} for p in rows])


# ------------------------------------------------------------- helpers -----
def _admin_only():
    if not current_user.is_admin:
        abort(403, description=t("auth.no_permission"))


def _surgeons():
    """Whoever may be named as operating. Doctors, from the clinic's own list
    of users — never a typed name, because a share of the fee is read against
    this person."""
    from app.models import User

    return (User.query.filter(User.is_active.is_(True),
                              User.role.in_(("doctor", "admin")))
            .order_by(User.full_name).all())


def _procedures():
    """What an operation may be charged as: the clinic's own services."""
    from app.models.service import Service

    return (Service.query.filter(Service.is_active.is_(True))
            .order_by(Service.name).all())


def _a_date(raw):
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


def _a_time(raw):
    raw = (raw or "").strip()
    if not raw:
        return None
    for shape in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(raw, shape).time()
        except ValueError:
            continue
    return None


def _happened_at():
    """When it happened, in UTC.

    The screen prefills the clinic's own wall clock, because a nurse signing
    the time-out at ten past is recording a stop the team made at ten.
    Comparing a local time against stored UTC is the mistake this program has
    already paid for in four money reports, so the conversion is not optional.
    """
    raw = (request.form.get("at") or "").strip()
    if raw:
        for shape in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"):
            try:
                return to_utc(datetime.strptime(raw, shape))
            except ValueError:
                continue
    return datetime.utcnow()
