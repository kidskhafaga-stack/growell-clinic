from flask import Blueprint

# Public inbound WhatsApp webhooks (no login) — Meta + WaPilot.
webhooks_bp = Blueprint("webhooks", __name__, url_prefix="/wa/webhook")

from app.blueprints.webhooks import routes  # noqa: E402,F401
