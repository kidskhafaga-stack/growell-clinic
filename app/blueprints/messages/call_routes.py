"""The telephone's screens (``CONNECTHUB_PLAN.md`` stage 6).

* ``/messages/calls`` — the call log, and the missed calls nobody has
  returned yet, with a «call back» link and «returned» to tick;
* ``/messages/calls/ringing`` — what the layout asks every few seconds: the
  call ringing on this person's extension, with who is calling and the
  chat's own panel by this person's permissions;
* ``/messages/calls/setup`` — on/off, the switchboard's key, and which
  extension each person answers on (``messages_setup``).

The switchboard's own doors are ``/telephony/…`` (``blueprints/telephony``).
"""
from datetime import datetime, timedelta

from flask import (abort, flash, jsonify, redirect, render_template, request,
                   url_for)
from flask_login import current_user

from app.blueprints.messages import messages_bp
from app.extensions import db
from app.i18n import t
from app.utils.decorators import capability_required, module_required

MODULE = "messages"


@messages_bp.route("/calls")
@module_required(MODULE)
def calls():
    from app.models import PhoneCall, User
    from app.utils import telephony

    days = min(max(request.args.get("days", type=int) or 2, 1), 31)
    since = datetime.utcnow() - timedelta(days=days)
    rows = (PhoneCall.query.filter(PhoneCall.started_at >= since)
            .order_by(PhoneCall.started_at.desc()).limit(500).all())
    missed = telephony.missed()
    names = {}
    for call in rows + missed:
        key = call.raw_number or call.number
        if key and key not in names:
            names[key] = telephony.who(key)
    from flask import g

    lang = getattr(g, "lang", "ar")
    staff = {u.id: u.display_name(lang) for u in User.query.filter(
        User.id.in_({c.returned_by for c in rows if c.returned_by})).all()}
    return render_template("messages/calls.html", rows=rows, missed=missed,
                           names=names, staff=staff, days=days,
                           on=telephony.enabled(),
                           can_setup=current_user.can("messages_setup"))


@messages_bp.route("/calls/<int:call_id>/returned", methods=["POST"])
@module_required(MODULE)
def call_returned(call_id):
    from app.models import ActivityLog, PhoneCall
    from app.utils import telephony
    from app.utils.decorators import client_ip

    call = db.get_or_404(PhoneCall, call_id)
    try:
        telephony.mark_returned(call, current_user, request.form.get("note"))
    except telephony.CallEventError:
        abort(404)
    ActivityLog.record("call.returned", user_id=current_user.id,
                       entity="phone_call", entity_id=call.id,
                       detail=call.number, ip_address=client_ip())
    db.session.commit()
    flash(t("calls.returned_ok"), "success")
    return redirect(url_for("messages.calls"))


@messages_bp.route("/calls/ringing")
@module_required(MODULE)
def calls_ringing():
    """The pop-up's question. Empty when nothing rings for this person."""
    from app.utils import telephony

    if not telephony.enabled():
        return jsonify(ids=[], html="")
    ringing = telephony.ringing_for(current_user)
    if not ringing:
        return jsonify(ids=[], html="")
    cards = [telephony.card(call, current_user) for call in ringing[:3]]
    return jsonify(ids=[c["call"].id for c in cards],
                   html=render_template("messages/_ringing.html", cards=cards))


@messages_bp.route("/calls/setup", methods=["GET", "POST"])
@capability_required("messages_setup")
def calls_setup():
    from app.models import ActivityLog, User
    from app.utils import telephony
    from app.utils.decorators import client_ip

    new_key = None
    if request.method == "POST":
        action = request.form.get("action")
        if action == "toggle":
            telephony.set_enabled(request.form.get("on") == "1")
        elif action == "key":
            new_key = telephony.new_key()
        elif action == "extensions":
            for user in User.query.filter_by(is_active=True).all():
                raw = request.form.get(f"ext_{user.id}")
                if raw is not None:
                    user.phone_extension = raw.strip()[:20] or None
        else:
            abort(400)
        ActivityLog.record(f"telephony.{action}", user_id=current_user.id,
                           ip_address=client_ip())
        db.session.commit()
        if not new_key:
            flash(t("calls.setup_saved"), "success")
            return redirect(url_for("messages.calls_setup"))
    users = (User.query.filter_by(is_active=True)
             .order_by(User.full_name).all())
    return render_template("messages/calls_setup.html", users=users,
                           on=telephony.enabled(), new_key=new_key,
                           hint=telephony.key_hint(),
                           base=request.url_root.rstrip("/"))
