"""The doors the laboratory's middleware knocks on (LAB_GLAB360_PLAN.md م-٢ ب).

``POST /lab-intake/<device>/message`` — one finished message from the
analyser, as it spoke it (ASTM or HL7). Read onto its tubes by the same road
as a result file: nothing released, and anything that cannot be placed is
held for a person.

``POST /lab-intake/<device>/alive`` — every minute: the middleware runs, and
whether the analyser answers (``{"linked": true}``).

Both need the device's key (``Authorization: Bearer …``), and answer 404 when
the laboratory module is off.
"""
from flask import jsonify, request

from app.blueprints.lab_intake import lab_intake_bp
from app.extensions import db
from app.utils.rate_limit import limit

PER_MINUTE = 600


def _device(device_id):
    from app.utils import lab_device_import as imp
    from app.utils.facility import module_enabled

    if not module_enabled("labs"):
        return None, (jsonify(error="not_found"), 404)
    device = imp.device_for(device_id, request.headers.get("Authorization"))
    if device is None:
        return None, (jsonify(error="key"), 401)
    return device, None


@lab_intake_bp.route("/<int:device_id>/message", methods=["POST"])
@limit("lab_intake", PER_MINUTE)
def message(device_id):
    from app.models import ActivityLog
    from app.utils import lab_device_import as imp

    device, refused = _device(device_id)
    if refused:
        return refused
    if (device.protocol or "file") not in ("astm", "hl7"):
        return jsonify(error="no_protocol"), 400
    data = request.get_data(cache=False)
    try:
        run = imp.run(device, data[: imp.MAX_BYTES + 1],
                      filename=f"{device.protocol}-message")
    except imp.ImportError_ as why:
        db.session.rollback()
        return jsonify(error=str(why)), 400
    imp.alive(device, True)
    ActivityLog.record("lab.device_message", entity="lab_import_run", entity_id=run.id,
                       detail=device.name[:120])
    db.session.commit()
    states = {}
    for line in run.lines:
        states[line.state] = states.get(line.state, 0) + 1
    return jsonify(run=run.id, states=states)


@lab_intake_bp.route("/<int:device_id>/alive", methods=["POST"])
@limit("lab_intake", PER_MINUTE)
def alive(device_id):
    from app.utils import lab_device_import as imp

    device, refused = _device(device_id)
    if refused:
        return refused
    body = request.get_json(silent=True) or {}
    imp.alive(device, body.get("linked"))
    db.session.commit()
    return jsonify(ok=True)
