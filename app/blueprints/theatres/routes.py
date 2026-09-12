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
                                REVIEW_KINDS, REVIEW_VERDICTS, Operation,
                                Theatre)
from app.utils import recovery as _recovery
from app.utils import theatres as theatre
from app.utils.clock import local_today, to_utc
from app.utils.decorators import module_required

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
