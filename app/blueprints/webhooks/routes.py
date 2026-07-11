"""Public inbound WhatsApp webhooks (no login).

* Meta Cloud API:  GET verify challenge + POST receive.
* WaPilot v2:      POST receive, protected by a secret path token (WaPilot v2
                   has no signature secret in its public contract).

Both are gated by the ``wa_inbound_enabled`` setting; when off they accept and
ignore (200) so providers don't retry forever.
"""
from flask import abort, jsonify, request

from app.blueprints.webhooks import webhooks_bp
from app.extensions import db
from app.models import Setting
from app.utils import inbound


def _enabled():
    return Setting.get("wa_inbound_enabled", "0") == "1"


@webhooks_bp.route("/meta", methods=["GET"])
def meta_verify():
    """Meta webhook verification handshake."""
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    expected = Setting.get("wa_meta_verify_token", "")
    if mode == "subscribe" and expected and token == expected:
        return challenge or "", 200
    abort(403)


@webhooks_bp.route("/meta", methods=["POST"])
def meta_receive():
    if not _enabled():
        return "", 200
    payload = request.get_json(silent=True) or {}
    for item in inbound.normalize_meta(payload):
        inbound.handle_inbound(item, "cloud_api")
    db.session.commit()
    return jsonify(ok=True)


@webhooks_bp.route("/wapilot/<secret>", methods=["POST"])
def wapilot_receive(secret):
    configured = Setting.get("wa_webhook_secret", "")
    if not configured or secret != configured:
        abort(403)
    if not _enabled():
        return "", 200
    payload = request.get_json(silent=True) or {}
    for item in inbound.normalize_wapilot(payload):
        inbound.handle_inbound(item, "wapilot")
    db.session.commit()
    return jsonify(ok=True)
