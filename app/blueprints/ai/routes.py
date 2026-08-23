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


@ai_bp.route("/lookup/search")
@module_required(MODULE)
def lookup_search():
    """The same lookup, answered as you type.

    Pressing a button and waiting for a page was the whole interaction, and on
    a phone number shared by three siblings that is three round trips to find
    out which Khafaga you meant. Typing narrows it in place.

    **It calls the same** :func:`ai_lookup.find_patients` **the page does.** Two
    searches that disagree — one while typing, one after Enter — would be a
    child appearing and then vanishing, and this file has learned that lesson
    on schedules already: one question, one function.

    Returns only what the list shows: the name, the file number, and where
    clicking goes. Not the phone it may have matched on, not the address, not
    an age. A search box is not a reason to put a row of the register on the
    wire, and the URL is built here so the page never assembles one itself.
    """
    from app.utils import ai_lookup

    term = (request.args.get("q") or "").strip()
    lang = getattr(g, "lang", "ar")
    return jsonify({"patients": [
        {"id": p.id,
         "name": p.display_name(lang),
         "number": p.patient_number,
         "url": url_for("ai.lookup", q=term, patient_id=p.id)}
        for p in ai_lookup.find_patients(term)]})


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


def _reply(result, status=None):
    """One JSON shape for every answer, with the failure already in words.

    `message` is what the screen shows. It exists because the screen used to
    build its own sentence out of whatever `error` happened to hold, and what
    `error` held for a clinic that had run out of credit was the provider's
    raw JSON — an English object quoting a vendor's field names, rendered into
    a right-to-left Arabic page. `error` is still there and still the machine-
    readable key; it is no longer the thing anybody reads.
    """
    return (jsonify(ai_utils.as_json(result)),
            status or (200 if result.get("ok") else 502))


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
        return _reply({"ok": False, "error": "empty"}, 400)

    # Told who it is working for. Asked "معلومات العيادة" with no system
    # prompt at all, it invented a whole clinic — an address, a phone, opening
    # hours, an insurer list and an email at a domain belonging to nobody —
    # and every line of it was the sort of thing somebody reads out to a
    # parent. See :mod:`app.utils.ai_clinic`.
    from app.utils import ai_clinic

    result = ai_utils.chat(messages,
                           system=ai_clinic.system_prompt(getattr(g, "lang", "ar")),
                           feature="chat")
    return _reply(result)


@ai_bp.route("/patient/<int:patient_id>/chat", methods=["POST"])
@module_required(MODULE)
def patient_chat(patient_id):
    """Ask the assistant about a specific patient (opt-in, privacy-aware)."""
    if not ai_utils.patient_context_enabled():
        return _reply({"ok": False, "error": "patient_context_disabled"}, 403)
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
        return _reply({"ok": False, "error": "empty"}, 400)

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
    return _reply(result)


@ai_bp.route("/patient/<int:patient_id>/discuss", methods=["POST"])
@module_required(MODULE)
def patient_discuss(patient_id):
    """Discuss a case: differential and plan, as a colleague and not a record.

    A separate route from :func:`patient_chat` rather than a flag on it, and
    the reason is the prompt each carries. That one is locked to the file —
    *never estimate, infer or fill in a diagnosis that is not written here* —
    because its job is letters and summaries, and a rounded date in a letter
    reads as competence. This one is asked to reason past the file on purpose.
    Those two instructions cannot live in one place, and a doctor has to be
    able to tell which of them answered.

    Two switches, both required. ``ai_patient_context`` because the record
    still leaves the building, and ``ai_discussion`` because wanting your own
    notes written up is not the same as wanting a machine to offer a
    differential — see :func:`ai.discussion_enabled`.
    """
    if not ai_utils.patient_context_enabled():
        return _reply({"ok": False, "error": "patient_context_disabled"}, 403)
    if not ai_utils.discussion_enabled():
        return _reply({"ok": False, "error": "discussion_disabled"}, 403)
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
        return _reply({"ok": False, "error": "empty"}, 400)

    from app.utils import ai_discuss

    system = ai_discuss.SYSTEM + ai_discuss.brief(
        patient, getattr(g, "lang", "ar"),
        anonymize=ai_utils.anonymize_enabled())
    result = ai_utils.chat(messages, system=system, feature="discussion")

    # Recorded like the visit summary is. A clinic ought to be able to answer
    # "was the assistant consulted about this child, and when" from its own
    # log rather than from somebody's memory — and a mode that offers
    # differentials is the one where that question gets asked.
    if result.get("ok"):
        from flask_login import current_user

        from app.models import ActivityLog
        from app.utils.decorators import client_ip

        ActivityLog.record("ai.discuss", user_id=current_user.id,
                           entity="patient", entity_id=patient.id,
                           ip_address=client_ip())
        db.session.commit()
    return _reply(result)
