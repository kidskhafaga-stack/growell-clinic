"""AI assistant module.

Landing page shows the configured provider and a lightweight chat assistant.
The provider/credentials are configured under Settings -> AI. All LLM calls go
through :mod:`app.utils.ai` so this view stays vendor-agnostic.
"""
from flask import g, jsonify, render_template, request, url_for

from app.blueprints.ai import ai_bp
from app.extensions import db
from app.models import Patient
from app.utils import ai as ai_utils
from app.utils.decorators import module_required

MODULE = "ai"

# Guard against runaway payloads from the chat box.
MAX_MESSAGES = 30
MAX_CHARS = 8000


@ai_bp.route("/lookup")
@module_required(MODULE)
def lookup():
    """Ask the register about a child, and get the register's own answer.

    "When did Omar last come" and "what has he had" are facts, not language.
    They are answered here from rows — no provider is called, so the answer is
    the same with the assistant switched off, costs nothing, and cannot be a
    plausible-looking wrong date. What the assistant is for is the third thing
    the clinic asked for, "write me a letter for the school", and the button
    that carries this child into the chat hands it these same rows to write
    from.

    Named ``lookup`` rather than ``ask`` for that reason: it looks things up.
    """
    from app.utils import ai_lookup

    term = (request.args.get("q") or "").strip()
    matches = ai_lookup.find_patients(term) if term else []
    chosen, data = None, None
    picked = request.args.get("patient_id", type=int)
    if picked:
        chosen = db.session.get(Patient, picked)
    elif len(matches) == 1:
        chosen = matches[0]
    if chosen is not None:
        data = ai_lookup.facts(chosen, getattr(g, "lang", "ar"))
    return render_template(
        "ai/lookup.html", term=term, matches=matches, chosen=chosen, data=data,
        # The chat continuation is only offered when the clinic opted in to
        # sending patient context. Reading the record on our own screen and
        # posting it to a vendor are different acts and have different answers.
        can_ask=(ai_utils.is_ready() and ai_utils.patient_context_enabled()),
        ready=ai_utils.is_ready(),
    )


@ai_bp.route("/")
@module_required(MODULE)
def index():
    cfg = ai_utils.get_config()
    return render_template(
        "ai/index.html",
        config=cfg,
        ready=ai_utils.is_ready(),
        # Which condition is missing, not just that one is. A grey badge with
        # no reason is what made a working key look like a broken program.
        missing=ai_utils.why_not_ready(cfg),
        # What it has cost, which is exact — never a guess at what is left,
        # which no provider tells us and which would be wrong in the direction
        # that hurts.
        usage=ai_utils.usage_summary(),
        keys_url=ai_utils.AI_PROVIDERS[cfg["provider"]].get("keys_url") or "",
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

    result = ai_utils.chat(messages, feature="chat")
    status = 200 if result.get("ok") else 502
    return jsonify(result), status


@ai_bp.route("/patient/<int:patient_id>/chat", methods=["POST"])
@module_required(MODULE)
def patient_chat(patient_id):
    """Ask the assistant about a specific patient (opt-in, privacy-aware)."""
    if not ai_utils.patient_context_enabled():
        return jsonify({"ok": False, "error": "patient_context_disabled"}), 403
    patient = db.get_or_404(Patient, patient_id)

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

    # The same fact sheet the lookup screen builds, and the same prohibition.
    # The old wording asked the model not to invent data as one clause among
    # several; a letter for a school is exactly the request that tempts it to
    # round a date or supply a plausible dose, so the rule is now stated as a
    # rule and the record is named as the only source.
    from app.utils import ai_lookup

    facts = ai_lookup.facts(patient, getattr(g, "lang", "ar"))
    system = (ai_lookup.SYSTEM
              + ai_lookup.fact_sheet(facts,
                                     anonymize=ai_utils.anonymize_enabled()))
    result = ai_utils.chat(messages, system=system, feature="patient_chat")
    status = 200 if result.get("ok") else 502
    return jsonify(result), status
