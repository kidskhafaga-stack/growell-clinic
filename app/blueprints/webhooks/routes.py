"""Public inbound WhatsApp webhooks (no login).

These are the only endpoints in the clinic open to the whole internet, and
what comes through them is written onto patients' records. Every request is
therefore proved to have come from the provider before a single row is
written — see ``app/utils/webhook_auth.py`` for how each provider proves it.

* Meta Cloud API:  GET verify challenge + POST receive, signed with the app
                   secret (``X-Hub-Signature-256``).
* WaPilot v2:      POST receive, proved by a long secret token in the path —
                   WaPilot v2 publishes no signing secret.

Both are gated by the ``wa_inbound_enabled`` setting; when off they accept and
ignore (200) so providers don't retry forever. Unauthenticated requests get
403 whether inbound is on or not: there is nothing to tell a forger.
"""
from flask import abort, jsonify, request

from app.blueprints.webhooks import webhooks_bp
from app.extensions import db
from app.models import Setting
from app.utils import inbound
from app.utils.webhook_auth import (meta_signature_ok, path_secret_ok,
                                    verify_token_ok)


def _enabled():
    return Setting.get("wa_inbound_enabled", "0") == "1"


@webhooks_bp.route("/meta", methods=["GET"])
def meta_verify():
    """Meta webhook verification handshake."""
    challenge = request.args.get("hub.challenge")
    if (request.args.get("hub.mode") == "subscribe"
            and verify_token_ok(request.args.get("hub.verify_token"),
                                Setting.get("wa_meta_verify_token", ""))):
        return challenge or "", 200
    abort(403)


@webhooks_bp.route("/meta", methods=["POST"])
def meta_receive():
    # Proved first, read second. The signature covers the raw bytes, so it has
    # to be checked before anything parses or re-serialises them.
    if not meta_signature_ok(request.get_data(),
                             request.headers.get("X-Hub-Signature-256"),
                             Setting.get("wa_meta_app_secret", "")):
        abort(403)
    if not _enabled():
        return "", 200
    payload = request.get_json(silent=True) or {}
    for item in inbound.normalize_meta(payload):
        inbound.handle_inbound(item, "cloud_api")
    db.session.commit()
    return jsonify(ok=True)


@webhooks_bp.route("/wapilot/<secret>", methods=["POST"])
def wapilot_receive(secret):
    if not path_secret_ok(secret, Setting.get("wa_webhook_secret", "")):
        abort(403)
    if not _enabled():
        return "", 200
    payload = request.get_json(silent=True) or {}
    for item in inbound.normalize_wapilot(payload):
        inbound.handle_inbound(item, "wapilot")
    db.session.commit()
    return jsonify(ok=True)
