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
                                Operation, Theatre)
from app.utils import theatres as theatre
from app.utils.clock import local_today, to_utc
from app.utils.decorators import module_required

MODULE = "theatres"


@theatres_bp.route("/")
@module_required(MODULE)
def index():
    """Today's list, room by room."""
    on_date = _a_date(request.args.get("date")) or local_today()
    return render_template("theatres/index.html",
                           on_date=on_date, rooms=theatre.day(on_date),
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
                           stops=CHECK_STOPS, items=CHECK_ITEMS,
                           statuses=OPERATION_STATUSES,
                           rooms=(Theatre.query
                                  .filter(Theatre.is_active.is_(True))
                                  .order_by(Theatre.sort_order, Theatre.id)
                                  .all()),
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
    db.session.commit()
    flash(t("theatre.saved"), "success")
    return redirect(url_for("theatres.operation", operation_id=row.id))


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
