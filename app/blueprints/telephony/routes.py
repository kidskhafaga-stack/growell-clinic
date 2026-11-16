"""The switchboard's doors (``CONNECTHUB_PLAN.md`` stage 6).

``POST /telephony/event`` — a call rang, was answered, or ended.
``GET /telephony/lookup?number=`` — the names on a number, for the handset.

Both need the clinic's telephone key (``Authorization: Bearer …``) and
answer 404 while the telephone is off or the messages module is.
"""
from flask import jsonify, request

from app.blueprints.telephony import telephony_bp
from app.extensions import db
from app.utils.rate_limit import limit

PER_MINUTE = 600


def _refused():
    from app.utils import telephony
    from app.utils.facility import module_enabled

    if not module_enabled("messages") or not telephony.enabled():
        return jsonify(error="not_found"), 404
    if not telephony.key_ok(request.headers.get("Authorization")):
        return jsonify(error="key"), 401
    return None


@telephony_bp.route("/event", methods=["POST"])
@limit("telephony", PER_MINUTE)
def event():
    from app.utils import telephony

    refused = _refused()
    if refused:
        return refused
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = request.form
    try:
        call = telephony.receive(data)
    except telephony.CallEventError as why:
        db.session.rollback()
        return jsonify(error=str(why)), 400
    db.session.commit()
    return jsonify(ok=True, id=call.id, status=call.status)


@telephony_bp.route("/lookup", methods=["GET"])
@limit("telephony", PER_MINUTE, methods=("GET",))
def lookup():
    from app.utils import telephony

    refused = _refused()
    if refused:
        return refused
    return jsonify(telephony.lookup(request.args.get("number")))
