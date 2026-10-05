"""التسليم بين الورديات وبين الأقسام — GAHAR `ACT.08` / `GSR.04`.

الصفحات: قايمة الأقسام وتسليماتها، ورقة التسليم متملية من الملف، صفحة
التسليم نفسه (سؤال ورد واستلام)، وتقرير المتابعة. المنطق كله في
``app/utils/handover.py``.
"""
from datetime import timedelta

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.blueprints.beds import beds_bp
from app.extensions import db
from app.i18n import t
from app.models.handover import (DISCIPLINES, METHODS, SEVERITIES, Handover,
                                 HandoverItem)
from app.models.place import Unit
from app.utils import handover as ho
from app.utils.clock import local_today
from app.utils.decorators import module_required

MODULE = "beds"


def _unit_or_404(unit_id):
    """``None`` يعني كل الأقسام."""
    if not unit_id:
        return None
    return db.get_or_404(Unit, unit_id)


def _guard(unit_id):
    """قسم ليه فريق مقفول على فريقه — نفس قاعدة شاشة الإقامة."""
    from app.utils import unit_access

    if unit_id and not unit_access.is_open_to(current_user, unit_id):
        abort(403)


def _refused(error):
    flash(t(f"handover.err_{error}"), "error")


def _users(discipline=None):
    from app.models import User

    query = User.query.filter(User.is_active.is_(True))
    if discipline == "medical":
        query = query.filter(db.or_(User.role == "doctor",
                                    User.is_practitioner.is_(True)))
    elif discipline == "nursing":
        query = query.filter(User.role == "nursing")
    return query.order_by(User.full_name).all()


@beds_bp.route("/handover")
@module_required(MODULE)
def handovers():
    """كل قسم: آخر تسليم ومفتوح لكل نوع، والنقل اللي مستني يتستلم."""
    units = (Unit.query.filter(Unit.is_active.is_(True))
             .order_by(Unit.sort_order, Unit.id).all())
    rows = []
    for unit in [None] + units:
        unit_id = unit.id if unit else None
        rows.append({
            "unit": unit,
            "count": len(ho.stays_in(unit_id)),
            "kinds": {d: {"open": ho.open_for(unit_id, d),
                          "last": ho.last_for(unit_id, d)}
                      for d in DISCIPLINES},
        })
    return render_template(
        "beds/handovers.html", rows=rows, waiting=ho.waiting(),
        methods={k: ho.method_for(k) for k in ho.KINDS},
        per_day={d: ho.per_day(d) for d in DISCIPLINES},
        all_methods=METHODS, kinds=ho.KINDS, disciplines=DISCIPLINES)


@beds_bp.route("/handover/settings", methods=["POST"])
@module_required(MODULE)
def handover_settings():
    """شكل التسليم لكل نوع، وعدد الورديات — إعداد المستشفى."""
    if not current_user.is_admin:
        abort(403)
    ho.save_settings({k: request.form.get(f"method_{k}") for k in ho.KINDS},
                     {d: request.form.get(f"per_day_{d}") for d in DISCIPLINES})
    db.session.commit()
    flash(t("handover.settings_saved"), "success")
    return redirect(url_for("beds.handovers"))


@beds_bp.route("/handover/new")
@module_required(MODULE)
def handover_new():
    """ورقة التسليم: كل طفل في القسم بكارته متملي من الملف."""
    unit_id = request.args.get("unit", type=int) or None
    unit = _unit_or_404(unit_id)
    _guard(unit_id)
    discipline = request.args.get("discipline") or ho.default_discipline(current_user)
    if discipline not in DISCIPLINES:
        abort(404)
    stays = ho.stays_in(unit_id)
    previous = ho.last_for(unit_id, discipline)
    before = ({item.admission_id: item for item in previous.items}
              if previous is not None else {})
    return render_template(
        "beds/handover_new.html", unit=unit, discipline=discipline,
        method=ho.method_for(discipline), stays=stays,
        cards=ho.cards(stays), before=before,
        open_row=ho.open_for(unit_id, discipline),
        severities=SEVERITIES, people=_users(discipline))


@beds_bp.route("/handover/new", methods=["POST"])
@module_required(MODULE)
def handover_create():
    unit_id = request.form.get("unit_id", type=int) or None
    _unit_or_404(unit_id)
    _guard(unit_id)
    discipline = request.form.get("discipline")
    notes, severities = {}, {}
    for key, value in request.form.items():
        if key.startswith("watch_") and key[6:].isdigit():
            notes[int(key[6:])] = value
        elif key.startswith("severity_") and key[9:].isdigit():
            severities[int(key[9:])] = value
    try:
        row = ho.hand_over(unit_id, discipline, current_user, notes=notes,
                           severities=severities,
                           offered_to=request.form.get("offered_to", type=int),
                           note=request.form.get("note"))
    except ho.HandoverError as error:
        db.session.rollback()
        _refused(error)
        return redirect(url_for("beds.handover_new", unit=unit_id or 0,
                                discipline=discipline))
    db.session.commit()
    flash(t("handover.handed"), "success")
    return redirect(url_for("beds.handover_view", handover_id=row.id))


@beds_bp.route("/handover/<int:handover_id>")
@module_required(MODULE)
def handover_view(handover_id):
    row = db.get_or_404(Handover, handover_id)
    _guard(row.unit_id)
    return render_template("beds/handover_view.html", row=row,
                           may_receive=ho.may_receive(current_user, row))


@beds_bp.route("/handover/item/<int:item_id>/ask", methods=["POST"])
@module_required(MODULE)
def handover_ask(item_id):
    item = db.get_or_404(HandoverItem, item_id)
    _guard(item.handover.unit_id)
    try:
        ho.ask(item, request.form.get("question"), current_user)
    except ho.HandoverError as error:
        db.session.rollback()
        _refused(error)
    else:
        db.session.commit()
        flash(t("handover.asked"), "success")
    return redirect(url_for("beds.handover_view",
                            handover_id=item.handover_id) + f"#item-{item.id}")


@beds_bp.route("/handover/item/<int:item_id>/answer", methods=["POST"])
@module_required(MODULE)
def handover_answer(item_id):
    item = db.get_or_404(HandoverItem, item_id)
    _guard(item.handover.unit_id)
    try:
        ho.answer(item, request.form.get("answer"), current_user)
    except ho.HandoverError as error:
        db.session.rollback()
        _refused(error)
    else:
        db.session.commit()
        flash(t("handover.answered"), "success")
    return redirect(url_for("beds.handover_view",
                            handover_id=item.handover_id) + f"#item-{item.id}")


@beds_bp.route("/handover/<int:handover_id>/accept", methods=["POST"])
@module_required(MODULE)
def handover_accept(handover_id):
    row = db.get_or_404(Handover, handover_id)
    _guard(row.unit_id)
    try:
        ho.accept(row, current_user, synthesis=bool(request.form.get("synthesis")))
    except ho.HandoverError as error:
        db.session.rollback()
        _refused(error)
    else:
        db.session.commit()
        flash(t("handover.accepted"), "success")
    return redirect(url_for("beds.handover_view", handover_id=row.id))


@beds_bp.route("/handover/<int:handover_id>/withdraw", methods=["POST"])
@module_required(MODULE)
def handover_withdraw(handover_id):
    row = db.get_or_404(Handover, handover_id)
    try:
        ho.withdraw(row, current_user)
    except ho.HandoverError as error:
        db.session.rollback()
        _refused(error)
        return redirect(url_for("beds.handover_view", handover_id=row.id))
    db.session.commit()
    flash(t("handover.withdrawn"), "success")
    return redirect(url_for("beds.handovers"))


@beds_bp.route("/handover/report")
@module_required(MODULE)
def handover_report():
    """دليل ٥ — المتابعة بالفترة."""
    from app.utils.appointments import parse_date_arg

    end = parse_date_arg(request.args.get("to"), local_today())
    raw = request.args.get("from")
    start = parse_date_arg(raw) if raw else end - timedelta(days=6)
    if start > end:
        start, end = end, start
    return render_template("beds/handover_report.html", start=start, end=end,
                           data=ho.report(start, end),
                           per_day={d: ho.per_day(d) for d in DISCIPLINES})
