"""AI assistant module.

Landing page shows the configured provider and a lightweight chat assistant.
The provider/credentials are configured under Settings -> AI. All LLM calls go
through :mod:`app.utils.ai` so this view stays vendor-agnostic.
"""
from flask import jsonify, render_template, request, url_for

from app.blueprints.ai import ai_bp
from app.utils import ai as ai_utils
from app.utils.decorators import module_required

MODULE = "ai"

# Guard against runaway payloads from the chat box.
MAX_MESSAGES = 30
MAX_CHARS = 8000


@ai_bp.route("/")
@module_required(MODULE)
def index():
    cfg = ai_utils.get_config()
    return render_template(
        "ai/index.html",
        config=cfg,
        ready=ai_utils.is_ready(),
        settings_url=url_for("settings.index"),
    )


@ai_bp.route("/chat", methods=["POST"])
@module_required(MODULE)
def chat():
    """Relay a short conversation to the configured provider (JSON in/out)."""
    data = request.get_json(silent=True) or {}
    raw = data.get("messages") or []
    messages = []
    for item in raw[-MAX_MESSAGES:]:
        role = item.get("role")
        content = (item.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content[:MAX_CHARS]})

    if not messages:
        return jsonify({"ok": False, "error": "empty"}), 400

    result = ai_utils.chat(messages)
    status = 200 if result.get("ok") else 502
    return jsonify(result), status
