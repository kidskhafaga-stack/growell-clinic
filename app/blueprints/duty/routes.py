"""The rota — who is covering, and what the clinic owes for it.

Its own module and not a corner of ``beds``, for a reason that came from the
clinics rather than from the code: *"موضوع الشيفتات بتاع الأطباء المقيمين
موجود وليهم حسابات في العيادات الخارجية — في الشيفتات الليلية"*. A clinic with
no wards and one resident covering the night is the ordinary case, not the
edge one, and putting this behind the inpatient module would have hidden it
from most of the people who asked for it.

Opt-in like every other module here, because a single-doctor clinic with no
cover has nobody to roster and should not find a rota after an update.
"""
from datetime import timedelta

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.blueprints.duty import duty_bp
from app.extensions import db
from app.i18n import t
from app.models.duty import Duty, DutyRate, DutySlot
from app.utils import duty as rota
from app.utils.clock import local_today
from app.utils.decorators import module_required

MODULE = "duty"


def _admin_only():
    """Only an admin edits the shifts and their rates.

    The same line the theatre rooms and the price list are behind: what a
    night pays is the clinic's money, and the person working the night is not
    the person who decides what it is worth.
    """
    if not current_user.is_admin:
        from flask import abort

        abort(403)


def _a_date(raw, fallback=None):
    from datetime import datetime

    if not raw:
        return fallback
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return fallback


def _doctors():
    """Everybody who can be rostered.

    Not "role == doctor": a clinic that made a role called ``registrar`` — and
    roles are data here — would find its registrars unrosterable. Anyone
    active who is not the reception desk can hold a duty, and the clinic
    chooses.
    """
    from app.models import User

    return (User.query.filter(User.is_active.is_(True))
            .order_by(User.full_name).all())


@duty_bp.route("/")
@module_required(MODULE)
def index():
    """The week's rota: a row per shift, a column per day."""
    anchor = _a_date(request.args.get("date"), local_today())
    start, end = rota.week_of(anchor)
    unit_id = request.args.get("unit_id", type=int)

    duties = rota.roster(start, end, unit_id=unit_id)
    grid = {}
    for duty in duties:
        grid.setdefault((duty.slot_id, duty.on_date), []).append(duty)

    from app.models.place import Unit

    return render_template(
        "duty/index.html",
        start=start, end=end, anchor=anchor,
        days=[start + timedelta(days=i) for i in range(7)],
        slots=rota.slots(), grid=grid,
        counts=rota.counts(start, end, unit_id=unit_id),
        waiting=rota.unconfirmed(),
        units=Unit.query.filter(Unit.is_active.is_(True))
                 .order_by(Unit.sort_order, Unit.id).all(),
        unit_id=unit_id, doctors=_doctors(),
        prev=start - timedelta(days=7), next=start + timedelta(days=7),
        may_edit=current_user.is_admin)


@duty_bp.route("/assign", methods=["POST"])
@module_required(MODULE)
def assign():
    """Put somebody on the rota for one shift on one day."""
    _admin_only()
    doctor_id = request.form.get("doctor_id", type=int)
    slot_id = request.form.get("slot_id", type=int)
    on_date = _a_date(request.form.get("on_date"))
    unit_id = request.form.get("unit_id", type=int)

    from app.models import User

    doctor = db.session.get(User, doctor_id) if doctor_id else None
    slot = db.session.get(DutySlot, slot_id) if slot_id else None
    if doctor is None or slot is None or on_date is None:
        flash(t("duty.pick_all"), "danger")
        return redirect(url_for("duty.index", date=request.form.get("on_date")))

    try:
        rota.assign(doctor, slot, on_date, unit=unit_id, user=current_user,
                    note=request.form.get("note"))
        db.session.commit()
        flash(t("duty.assigned"), "success")
    except Exception:  # noqa: BLE001 — the unique constraint, said plainly
        db.session.rollback()
        flash(t("duty.already_on"), "warning")
    return redirect(url_for("duty.index", date=on_date.isoformat(),
                            unit_id=unit_id or None))


@duty_bp.route("/<int:duty_id>/happened", methods=["POST"])
@module_required(MODULE)
def happened(duty_id):
    """Say the duty was worked — the press that makes it payable."""
    _admin_only()
    duty = db.get_or_404(Duty, duty_id)
    rota.confirm(duty, user=current_user)
    db.session.commit()
    flash(t("duty.confirmed"), "success")
    return redirect(url_for("duty.index", date=duty.on_date.isoformat()))


@duty_bp.route("/<int:duty_id>/absent", methods=["POST"])
@module_required(MODULE)
def absent(duty_id):
    """Say it did not happen. Pays nothing, and keeps the row."""
    _admin_only()
    duty = db.get_or_404(Duty, duty_id)
    rota.mark_absent(duty, user=current_user, note=request.form.get("note"))
    db.session.commit()
    flash(t("duty.marked_absent"), "info")
    return redirect(url_for("duty.index", date=duty.on_date.isoformat()))


@duty_bp.route("/slots")
@module_required(MODULE)
def slots():
    """The shifts themselves, and what each pays — typed here, never shipped."""
    _admin_only()
    return render_template("duty/slots.html",
                           slots=rota.slots(include_inactive=True),
                           doctors=_doctors())


@duty_bp.route("/slots/add", methods=["POST"])
@module_required(MODULE)
def slot_add():
    _admin_only()
    from datetime import datetime as _dt

    name = (request.form.get("name") or "").strip()
    start = (request.form.get("start_time") or "").strip()
    end = (request.form.get("end_time") or "").strip()
    if not name or not start or not end:
        flash(t("duty.slot_needs_hours"), "danger")
        return redirect(url_for("duty.slots"))
    try:
        start_t = _dt.strptime(start, "%H:%M").time()
        end_t = _dt.strptime(end, "%H:%M").time()
    except ValueError:
        flash(t("duty.slot_needs_hours"), "danger")
        return redirect(url_for("duty.slots"))

    db.session.add(DutySlot(name=name[:40], start_time=start_t, end_time=end_t,
                            rate=request.form.get("rate", type=float),
                            sort_order=request.form.get("sort_order",
                                                        type=int) or 0))
    db.session.commit()
    flash(t("duty.slot_added"), "success")
    return redirect(url_for("duty.slots"))


@duty_bp.route("/slots/<int:slot_id>/set", methods=["POST"])
@module_required(MODULE)
def slot_set(slot_id):
    """Edit a shift: its rate, or whether the clinic still runs it."""
    _admin_only()
    slot = db.get_or_404(DutySlot, slot_id)
    if "rate" in request.form:
        slot.rate = request.form.get("rate", type=float)
    if "is_active" in request.form:
        slot.is_active = request.form.get("is_active") == "1"
    db.session.commit()
    flash(t("common.saved"), "success")
    return redirect(url_for("duty.slots"))


@duty_bp.route("/slots/<int:slot_id>/rate", methods=["POST"])
@module_required(MODULE)
def slot_rate(slot_id):
    """One doctor's own rate for this shift — or clearing it back to the slot's.

    An empty box means "use the shift's rate", not "this doctor works for
    nothing": a clinic correcting a mistake must be able to get back to the
    default without deleting and re-adding the person.
    """
    _admin_only()
    slot = db.get_or_404(DutySlot, slot_id)
    doctor_id = request.form.get("doctor_id", type=int)
    if not doctor_id:
        flash(t("duty.pick_all"), "danger")
        return redirect(url_for("duty.slots"))

    amount = request.form.get("amount", type=float)
    row = DutyRate.query.filter_by(slot_id=slot.id, doctor_id=doctor_id).first()
    if amount is None:
        if row is not None:
            db.session.delete(row)
    elif row is None:
        db.session.add(DutyRate(slot_id=slot.id, doctor_id=doctor_id,
                                amount=amount))
    else:
        row.amount = amount
    db.session.commit()
    flash(t("common.saved"), "success")
    return redirect(url_for("duty.slots"))
