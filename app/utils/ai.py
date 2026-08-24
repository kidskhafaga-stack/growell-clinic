"""AI provider configuration and a unified chat helper.

The clinic is not locked to a single AI vendor. An admin picks a provider in
Settings -> AI (Claude, OpenAI/ChatGPT, Gemini, DeepSeek, Grok, Mistral, or any
OpenAI-compatible endpoint) and supplies an API key + model. Every feature that
needs an LLM goes through :func:`chat` so the rest of the app stays
provider-agnostic.

Settings keys (stored as strings in the ``settings`` table):
* ``ai_enabled``   -> "1"/"0"
* ``ai_provider``  -> a key from :data:`AI_PROVIDERS`
* ``ai_api_key``   -> the secret API key
* ``ai_model``     -> model id (free text; suggestions per provider)
* ``ai_base_url``  -> override endpoint (required for the "custom" provider)
"""
from __future__ import annotations

# Provider registry. ``api`` is the request "shape" the helper speaks:
#   * "openai"    -> POST /chat/completions  (OpenAI and all compatibles)
#   * "anthropic" -> POST /v1/messages       (Claude)
#   * "gemini"    -> POST .../{model}:generateContent (Google)
# ``models`` are suggestions shown in a datalist; users may type any model id.
AI_PROVIDERS = {
    "claude": {
        "label": "Anthropic Claude",
        "api": "anthropic",
        "base_url": "https://api.anthropic.com/v1/messages",
        "default_model": "claude-sonnet-5",
        "models": [
            "claude-sonnet-5",
            "claude-opus-4-8",
            "claude-haiku-4-5",
        ],
        "keys_url": "https://console.anthropic.com/settings/keys",
    },
    "openai": {
        "label": "OpenAI (ChatGPT / GPT)",
        "api": "openai",
        "base_url": "https://api.openai.com/v1/chat/completions",
        "default_model": "gpt-4o",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4.1", "o4-mini"],
        "keys_url": "https://platform.openai.com/api-keys",
    },
    "gemini": {
        "label": "Google Gemini",
        "api": "gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/models",
        "default_model": "gemini-2.5-flash",
        "models": ["gemini-2.5-flash", "gemini-2.5-pro",
                   "gemini-2.5-flash-lite", "gemini-2.0-flash"],
        "keys_url": "https://aistudio.google.com/app/apikey",
        # A key from Google AI Studio costs nothing to create, which is what
        # makes this the one to point a clinic at when it wants to *try* the
        # assistant before deciding anything. The quota is Google's and it
        # changes; nothing here quotes a number it would go stale on.
        "free": True,
    },
    "deepseek": {
        "label": "DeepSeek",
        "api": "openai",
        "base_url": "https://api.deepseek.com/v1/chat/completions",
        "default_model": "deepseek-chat",
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "keys_url": "https://platform.deepseek.com/api_keys",
    },
    "grok": {
        "label": "xAI Grok",
        "api": "openai",
        "base_url": "https://api.x.ai/v1/chat/completions",
        "default_model": "grok-2-latest",
        "models": ["grok-2-latest", "grok-2-vision-latest"],
        "keys_url": "https://console.x.ai",
    },
    "mistral": {
        "label": "Mistral AI",
        "api": "openai",
        "base_url": "https://api.mistral.ai/v1/chat/completions",
        "default_model": "mistral-large-latest",
        "models": ["mistral-large-latest", "mistral-small-latest"],
        "keys_url": "https://console.mistral.ai/api-keys",
    },
    "groq": {
        "label": "Groq (fast, free key)",
        "api": "openai",
        # Groq speaks the OpenAI shape at an /openai/v1 path, so it needs no
        # code of its own — this entry is the whole integration.
        "base_url": "https://api.groq.com/openai/v1/chat/completions",
        "default_model": "openai/gpt-oss-20b",
        # Suggestions, not a catalogue, and this entry is the proof.
        #
        # `llama-3.1-70b-versatile` was the obvious name and went. The comment
        # written when it went said `llama-3.3-70b-versatile` would survive;
        # it did not, and a clinic met it as `HTTP 404 — the model does not
        # exist or you do not have access to it` on a setup that had been
        # working. So this list is only ever what fills the box before anybody
        # has a key: the settings screen's "fetch the available models" button
        # asks the key what it may actually use, and that answer beats this
        # one every time.
        "models": ["openai/gpt-oss-20b", "openai/gpt-oss-120b",
                   "llama-3.1-8b-instant", "qwen/qwen3-32b"],
        "keys_url": "https://console.groq.com/keys",
        # Free in the sense this flag means: the key costs nothing and asks
        # for no card. There is a rate limit, it is Groq's, and it changes —
        # which is exactly why nothing here quotes a number.
        "free": True,
    },
    "github": {
        # **This is the one to read carefully if you came looking for
        # "Copilot".** The Copilot in an editor and the Copilot at
        # copilot.microsoft.com have no API a program like this may call —
        # they are products, not endpoints, and no amount of configuration
        # here reaches them. What Microsoft *does* publish for this is GitHub
        # Models: the same families of model, an OpenAI-shaped endpoint, and a
        # plain GitHub personal access token for a key.
        #
        # So a clinic that wants "Copilot" gets this, and the label says
        # GitHub Models rather than Copilot on purpose. A settings screen that
        # offered "Copilot" and quietly meant something else is the kind of
        # small lie that costs an afternoon when the token does not work.
        "label": "GitHub Models (Copilot models, GitHub token)",
        "api": "openai",
        "base_url": "https://models.github.ai/inference/chat/completions",
        "default_model": "openai/gpt-4o-mini",
        # Publisher-prefixed ids, which is this endpoint's own convention and
        # not a typo: `openai/gpt-4o-mini`, not `gpt-4o-mini`.
        "models": ["openai/gpt-4o-mini", "openai/gpt-4o",
                   "meta/Llama-3.3-70B-Instruct", "microsoft/Phi-4",
                   "mistral-ai/Mistral-Large-2411",
                   "deepseek/DeepSeek-V3-0324"],
        "keys_url": "https://github.com/settings/personal-access-tokens",
        "free": True,
    },
    "aihubmix": {
        "label": "AiHubMix (many models, one key)",
        "api": "openai",
        "base_url": "https://aihubmix.com/v1/chat/completions",
        "default_model": "gpt-4o-mini",
        # An aggregator: one key reaches many vendors' models. These are just
        # a few suggestions — any model id the account can access works.
        "models": ["gpt-4o-mini", "gpt-4o", "gemini-2.0-flash",
                   "deepseek-chat", "claude-3-5-haiku-20241022"],
        "keys_url": "https://aihubmix.com/token",
    },
    "puter": {
        "label": "Puter (one token, many models)",
        "api": "openai",
        # Puter speaks the OpenAI shape and takes the token as a normal Bearer
        # header, so it needs no code of its own — only this entry. That is
        # also the reason to be careful about it: a provider this cheap to add
        # is a provider nobody looks at twice.
        "base_url": "https://api.puter.com/puterai/openai/v1/chat/completions",
        "default_model": "gpt-4o-mini",
        # Suggestions only, and short on purpose. The token can ask the
        # account which models it may actually use (the "refresh" button on
        # the settings screen), and an aggregator's catalogue moves faster
        # than any list written here.
        "models": ["gpt-4o-mini", "gpt-4o", "claude-sonnet-4",
                   "gemini-2.5-flash", "deepseek-chat"],
        "keys_url": "https://puter.com/settings/api-keys",
        # Not marked ``free``. Puter's pitch is that the *end user* pays, which
        # is a sound model for a public website and the wrong one to describe
        # to a clinic: here the account holder is the clinic, and a badge
        # saying "free" would be read as "this costs the clinic nothing"
        # — a promise this program is in no position to make on someone
        # else's pricing page.
    },
    "ollama": {
        "label": "Local — Ollama (offline, private)",
        "api": "openai",
        "base_url": "http://localhost:11434/v1/chat/completions",
        "default_model": "llama3.1",
        "models": ["llama3.1", "qwen2.5", "mistral", "gemma2", "phi3"],
        "keys_url": "",
        "local": True,   # runs on the clinic machine — data never leaves
        "free": True,
    },
    "lmstudio": {
        "label": "Local — LM Studio (offline, private)",
        "api": "openai",
        "base_url": "http://localhost:1234/v1/chat/completions",
        "default_model": "",
        "models": [],
        "keys_url": "",
        "local": True,
        "free": True,
    },
    "custom": {
        "label": "Custom (OpenAI-compatible)",
        "api": "openai",
        "base_url": "",  # user must supply ai_base_url (Ollama, LM Studio, ...)
        "default_model": "",
        "models": [],
        "keys_url": "",
    },
}

DEFAULT_PROVIDER = "claude"
REQUEST_TIMEOUT = 60
ANTHROPIC_VERSION = "2023-06-01"


def get_config():
    """Read the saved AI settings into a plain dict (with sensible defaults)."""
    from app.models import Setting

    rows = {r.key: r.value for r in Setting.query.all()}
    provider = rows.get("ai_provider") or DEFAULT_PROVIDER
    if provider not in AI_PROVIDERS:
        provider = DEFAULT_PROVIDER
    meta = AI_PROVIDERS[provider]
    return {
        "enabled": rows.get("ai_enabled") == "1",
        "provider": provider,
        "provider_label": meta["label"],
        "local": bool(meta.get("local")),
        "api_key": (rows.get("ai_api_key") or "").strip(),
        "model": (rows.get("ai_model") or "").strip() or meta["default_model"],
        "base_url": (rows.get("ai_base_url") or "").strip() or meta["base_url"],
        "system_prompt": (rows.get("ai_system_prompt") or "").strip(),
    }


def is_ready():
    """True when AI is enabled and the minimum config is present.

    Local providers (Ollama / LM Studio) don't need an API key — the model
    runs on the clinic machine, so credentials aren't required.
    """
    cfg = get_config()
    if not (cfg["enabled"] and cfg["base_url"] and cfg["model"]):
        return False
    return cfg["local"] or bool(cfg["api_key"])


# The provider a clinic is pointed at when it wants to try the assistant
# without buying anything first. Gemini rather than a local model because
# "install Ollama" is a different afternoon.
TRIAL_PROVIDER = "gemini"


def free_providers():
    """The ids whose key costs nothing — for the badge on the settings screen.

    Said as a fact about the *key*, not about a quota. Free tiers move, and a
    screen that quotes "60 requests a minute" is a screen that is wrong later
    and blamed for it.
    """
    return [pid for pid, meta in AI_PROVIDERS.items() if meta.get("free")]


def trial_defaults():
    """Provider, model and URL for "just let me try it" — everything but the key.

    Every clinic brings **its own** free key. That is what makes this a
    feature rather than a service: no shared account to meter, no per-clinic
    budget to police, and nobody else's patients on the same quota.
    """
    meta = AI_PROVIDERS[TRIAL_PROVIDER]
    return {"provider": TRIAL_PROVIDER, "model": meta["default_model"],
            "base_url": meta["base_url"], "keys_url": meta["keys_url"]}


def test_connection(config=None):
    """Ask the provider one trivial question and report exactly what came back.

    The gap this closes is not cosmetic. Until now a clinic saved its settings
    and found out whether they worked when a doctor pressed "suggest a dose"
    mid-consultation and nothing happened — with no way to tell a wrong key
    from a wrong model from a firewall. Somebody setting this up alone, in
    another clinic, needs the answer at the moment they type it.
    """
    cfg = config or get_config()
    if not cfg["base_url"] or not cfg["model"]:
        return {"ok": False, "error": "not_configured"}
    if not cfg["api_key"] and not cfg["local"]:
        return {"ok": False, "error": "no_key"}

    # Enabled is a separate decision from working: somebody testing before
    # switching it on is the normal order, and refusing them would make the
    # button useless exactly when it is wanted.
    probe = dict(cfg, enabled=True)
    reply = chat([{"role": "user", "content": "Reply with the single word: ok"}],
                 system="You are a connection test. Answer in one word.",
                 config=probe)
    if reply.get("ok"):
        return {"ok": True, "text": (reply.get("text") or "").strip()[:200],
                "provider": cfg["provider_label"], "model": cfg["model"]}
    return {"ok": False, "error": reply.get("error") or "unknown"}


def patient_context_enabled():
    """Whether the clinic opted in to sharing patient context with the AI."""
    from app.models import Setting

    return Setting.get("ai_patient_context") == "1"


def discussion_enabled():
    """Whether the clinic switched the discussion mode on. Off until it does.

    Its own switch, separate from ``ai_patient_context``, because they are
    different decisions. A clinic can want its own records read back and
    written up — letters, summaries, "when did he last come" — without wanting
    a machine to offer differentials. Folding the two together would mean a
    clinic that turned the first one on for correspondence got the second one
    as a side effect, which is not a thing anybody should acquire by accident.

    Default off for the same reason: a suggestion about what a child might
    have is not a feature to arrive switched on.
    """
    from app.models import Setting

    return Setting.get("ai_discussion") == "1"


def anonymize_enabled():
    from app.models import Setting

    return Setting.get("ai_anonymize", "1") != "0"


def build_patient_summary(patient, anonymize=True):
    """Build a concise clinical summary of a patient for the AI assistant.

    When ``anonymize`` is True, direct identifiers (name, file number, national
    id) are omitted so only clinical context leaves the clinic.
    """
    lines = []
    years, months = patient.age_parts
    age = f"{years}y {months}m" if years else f"{months}m"
    if anonymize:
        lines.append(f"Patient: (anonymized) — {age}, {patient.gender}")
    else:
        lines.append(
            f"Patient: {patient.display_name()} (#{patient.patient_number}) — "
            f"{age}, {patient.gender}"
        )
    if patient.allergies:
        lines.append(f"Allergies: {patient.allergies}")
    if patient.chronic_diseases:
        lines.append(f"Chronic conditions: {patient.chronic_diseases}")

    # Latest vitals + recent visits / diagnoses.
    try:
        from app.models import Prescription, Visit

        visits = (
            Visit.query.filter_by(patient_id=patient.id)
            .order_by(Visit.visit_date.desc()).limit(3).all()
        )
        latest_vitals = next((v.vitals for v in visits if v.vitals), None)
        if latest_vitals and latest_vitals.weight_kg:
            lines.append(f"Latest weight: {latest_vitals.weight_kg} kg")
        for v in visits:
            dxs = ", ".join(d.title for d in v.final_diagnoses()) or "—"
            lines.append(f"Visit {v.visit_date}: dx={dxs}"
                         + (f"; plan={v.plan}" if v.plan else ""))

        rxs = (Prescription.query.filter_by(patient_id=patient.id)
               .order_by(Prescription.id.desc()).limit(2).all())
        for rx in rxs:
            drugs = ", ".join(it.drug_name for it in rx.items) or "—"
            lines.append(f"Rx {rx.rx_date}: {drugs}")
    except Exception:  # noqa: BLE001 - context is best-effort
        pass

    # Vaccination status snapshot.
    try:
        from app.utils.vaccines import patient_plan, plan_summary

        s = plan_summary(patient_plan(patient))
        lines.append(
            f"Vaccinations: {s['done']} done, {s['due']} due, {s['overdue']} overdue"
        )
    except Exception:  # noqa: BLE001
        pass

    return "\n".join(lines)


def chat(messages, system=None, config=None, feature=None):
    """Send a chat conversation to the configured provider.

    ``messages`` is a list of ``{"role": "user"|"assistant", "content": str}``.
    Returns ``{"ok": True, "text": ...}`` or ``{"ok": False, "error": ...}``.
    Networking/SDK errors never raise out of here — callers get a clean dict.

    ``feature`` names the part of the program that is spending, and is what
    makes the usage screen worth looking at: a clinic can act on "the visit
    summaries are three quarters of the bill" and can do nothing at all with
    one monthly total from the vendor. It is metered here, in the one place
    every AI call already passes through, so a feature added later is counted
    without anybody remembering to count it.
    """
    cfg = config or get_config()
    if not cfg["enabled"]:
        return {"ok": False, "error": "disabled"}
    # Local providers (Ollama / LM Studio) don't need an API key.
    if not cfg["base_url"] or not cfg["model"] or (not cfg["api_key"] and not cfg["local"]):
        return {"ok": False, "error": "not_configured"}

    try:
        import requests
    except ImportError:  # pragma: no cover - requests is in requirements
        return {"ok": False, "error": "err_library"}

    api = AI_PROVIDERS[cfg["provider"]]["api"]
    system_prompt = system or cfg["system_prompt"] or None
    try:
        if api == "anthropic":
            result = _chat_anthropic(requests, cfg, messages, system_prompt)
        elif api == "gemini":
            result = _chat_gemini(requests, cfg, messages, system_prompt)
        else:
            result = _chat_openai(requests, cfg, messages, system_prompt)
    except requests.exceptions.RequestException as exc:  # network/timeout
        return {"ok": False, "error": _network_error(exc)}
    except (KeyError, ValueError, IndexError) as exc:  # unexpected payload
        return {"ok": False, "error": _reply_error(exc)}
    _record_usage(cfg, result, feature)
    return result


def _record_usage(cfg, result, feature):
    """Bank the token count the provider just handed back.

    Wrapped in its own try: a metering table is never a reason for the doctor
    to lose an answer they already have. If the write fails the reply still
    returns and the clinic is short one row in a report.
    """
    usage = (result or {}).get("usage") or {}
    if not result.get("ok") or not (usage.get("prompt") or usage.get("completion")):
        return
    try:
        from flask_login import current_user

        from app.extensions import db
        from app.models import AiUsage

        who = getattr(current_user, "id", None) if current_user else None
        db.session.add(AiUsage(
            feature=(feature or "chat")[:40], provider=cfg["provider"],
            model=cfg["model"][:80], user_id=who,
            prompt_tokens=int(usage.get("prompt") or 0),
            completion_tokens=int(usage.get("completion") or 0)))
        db.session.commit()
    except Exception:                   # noqa: BLE001 - metering is not the job
        try:
            from app.extensions import db
            db.session.rollback()
        except Exception:               # noqa: BLE001
            pass


def _chat_openai(requests, cfg, messages, system_prompt):
    payload_msgs = list(messages)
    if system_prompt:
        payload_msgs = [{"role": "system", "content": system_prompt}] + payload_msgs
    headers = {"Content-Type": "application/json"}
    if cfg["api_key"]:  # local servers (Ollama) accept no auth header
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    resp = requests.post(
        cfg["base_url"], headers=headers,
        json={"model": cfg["model"], "messages": payload_msgs},
        timeout=REQUEST_TIMEOUT,
    )
    if not resp.ok:
        return {"ok": False, "error": _http_error(resp)}
    data = resp.json()
    usage = data.get("usage") or {}
    return {"ok": True, "text": data["choices"][0]["message"]["content"],
            "usage": {"prompt": usage.get("prompt_tokens") or 0,
                      "completion": usage.get("completion_tokens") or 0}}


def _chat_anthropic(requests, cfg, messages, system_prompt):
    body = {
        "model": cfg["model"],
        "max_tokens": 1024,
        "messages": [
            {"role": m["role"], "content": m["content"]} for m in messages
        ],
    }
    if system_prompt:
        body["system"] = system_prompt
    resp = requests.post(
        cfg["base_url"],
        headers={
            "x-api-key": cfg["api_key"],
            "anthropic-version": ANTHROPIC_VERSION,
            "Content-Type": "application/json",
        },
        json=body,
        timeout=REQUEST_TIMEOUT,
    )
    if not resp.ok:
        return {"ok": False, "error": _http_error(resp)}
    data = resp.json()
    parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
    usage = data.get("usage") or {}
    return {"ok": True, "text": "".join(parts),
            "usage": {"prompt": usage.get("input_tokens") or 0,
                      "completion": usage.get("output_tokens") or 0}}


def _chat_gemini(requests, cfg, messages, system_prompt):
    url = f"{cfg['base_url'].rstrip('/')}/{cfg['model']}:generateContent"
    contents = [
        {
            "role": "model" if m["role"] == "assistant" else "user",
            "parts": [{"text": m["content"]}],
        }
        for m in messages
    ]
    body = {"contents": contents}
    if system_prompt:
        body["systemInstruction"] = {"parts": [{"text": system_prompt}]}
    resp = requests.post(
        url,
        headers={"Content-Type": "application/json"},
        params={"key": cfg["api_key"]},
        json=body,
        timeout=REQUEST_TIMEOUT,
    )
    if not resp.ok:
        return {"ok": False, "error": _http_error(resp)}
    data = resp.json()
    parts = data["candidates"][0]["content"]["parts"]
    usage = data.get("usageMetadata") or {}
    return {"ok": True, "text": "".join(p.get("text", "") for p in parts),
            "usage": {"prompt": usage.get("promptTokenCount") or 0,
                      "completion": usage.get("candidatesTokenCount") or 0}}


def list_models(config=None):
    """Ask the provider which models **this key** may actually use.

    Added because the bundled list went stale in the way bundled lists always
    do: a clinic pressed "use the free setup", pasted a fresh key, and got
    ``HTTP 404: this model is no longer available to new users``. The id was
    right when it was written and wrong by the time somebody set the program
    up — and a list of suggestions that 404s is worse than no list, because
    the person has no way to know which of the two is out of date.

    Vendors retire models on their own schedule; nobody is going to ship a
    release of this program every time Google does. So the truth is fetched
    from the account that will be billed for it, and the bundled names are
    only what fills the box before anyone has a key.

    Returns ``{"ok": True, "models": [...]}`` or ``{"ok": False, "error": ...}``.
    """
    cfg = config or get_config()
    if not cfg["base_url"]:
        return {"ok": False, "error": "not_configured"}
    if not cfg["api_key"] and not cfg["local"]:
        return {"ok": False, "error": "no_key"}

    try:
        import requests
    except ImportError:  # pragma: no cover - requests is in requirements
        return {"ok": False, "error": "err_library"}

    api = AI_PROVIDERS[cfg["provider"]]["api"]
    try:
        if api == "gemini":
            return _models_gemini(requests, cfg)
        if api == "anthropic":
            return _models_anthropic(requests, cfg)
        return _models_openai(requests, cfg)
    except requests.exceptions.RequestException as exc:
        return {"ok": False, "error": _network_error(exc)}
    except (KeyError, ValueError, IndexError, TypeError) as exc:
        return {"ok": False, "error": _reply_error(exc)}


def _models_gemini(requests, cfg):
    # base_url already points at ".../v1beta/models" — the same collection the
    # chat call posts into, so one setting stays one setting.
    resp = requests.get(cfg["base_url"].rstrip("/"),
                        params={"key": cfg["api_key"]},
                        timeout=REQUEST_TIMEOUT)
    if not resp.ok:
        return {"ok": False, "error": _http_error(resp)}
    out = []
    for row in resp.json().get("models") or []:
        name = (row.get("name") or "").split("/")[-1]
        # Only the ones that can answer a chat. The same endpoint lists
        # embedding models, and offering one as an assistant is a support call.
        methods = row.get("supportedGenerationMethods") or []
        if name and (not methods or "generateContent" in methods):
            out.append(name)
    return {"ok": True, "models": sorted(set(out))}


def _models_openai(requests, cfg):
    url = _sibling_url(cfg["base_url"], "models")
    headers = {}
    if cfg["api_key"]:
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    if not resp.ok:
        return {"ok": False, "error": _http_error(resp)}
    data = resp.json()
    rows = data.get("data") if isinstance(data, dict) else data
    out = [r.get("id") for r in (rows or []) if isinstance(r, dict) and r.get("id")]
    return {"ok": True, "models": sorted(set(out))}


def _models_anthropic(requests, cfg):
    url = _sibling_url(cfg["base_url"], "models")
    resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers={
        "x-api-key": cfg["api_key"], "anthropic-version": ANTHROPIC_VERSION})
    if not resp.ok:
        return {"ok": False, "error": _http_error(resp)}
    out = [r.get("id") for r in (resp.json().get("data") or []) if r.get("id")]
    return {"ok": True, "models": sorted(set(out))}


def _sibling_url(base_url, leaf):
    """``https://host/v1/chat/completions`` → ``https://host/v1/models``.

    The clinic configures one URL — the chat endpoint — and this derives the
    listing one from it, so a custom or self-hosted server needs no second
    setting to fill in wrongly.
    """
    trimmed = base_url.rstrip("/")
    for suffix in ("/chat/completions", "/messages", "/completions"):
        if trimmed.endswith(suffix):
            return trimmed[: -len(suffix)] + "/" + leaf
    return trimmed + "/" + leaf


# What a provider's HTTP status actually means for the clinic.
#
# Not "compact and user-safe", which is what the old wording claimed and what
# it was not. A clinic whose account ran out of credit was shown, in the
# middle of an Arabic right-to-left screen:
#
#     HTTP 429: {"error": {"message": "You exceeded your current quota,
#     please check your plan and billing details", "type":
#     "insufficient_quota", "param": null, "code": "insufficient_quota"}}
#
# — a JSON object, in English, quoting a vendor's internal field names, saying
# something the person reading it could do nothing about. Truncating it to 300
# characters made it shorter; it never made it a sentence.
_STATUS_MEANING = {
    400: "err_request",
    401: "err_key",
    403: "err_key",
    404: "err_model",
    408: "err_timeout",
    413: "err_too_long",
    429: "err_rate",
    500: "err_provider",
    502: "err_provider",
    503: "err_provider",
    504: "err_provider",
}

# 429 is two completely different problems wearing one status code, and the
# difference is the only thing the clinic can act on. "Too many requests just
# now" fixes itself in a minute. "Your account has no credit left" never fixes
# itself, and telling somebody to wait and try again sends them back to the
# same screen for a week. Every provider says which it is in the body.
_OUT_OF_CREDIT = ("quota", "insufficient", "billing", "credit", "balance",
                  "payment", "exceeded your current")


def _network_error(exc):
    """Could not reach the provider at all. The exception text names a host
    and a port and belongs in the log, not on a screen."""
    _log_provider_error("network", str(exc))
    return "err_network"


def _reply_error(exc):
    """The provider answered with something this program could not read."""
    _log_provider_error("reply", str(exc))
    return "err_reply"


def _http_error(resp):
    """Why the provider refused, as a key the screen can put in a sentence.

    The body still goes to the program log — somebody debugging a firewall or
    a wrong endpoint wants the vendor's exact words, and that is the place for
    them.
    """
    body = (resp.text or "").strip()
    key = _STATUS_MEANING.get(resp.status_code, "err_http")
    if key == "err_rate" and any(p in body.lower() for p in _OUT_OF_CREDIT):
        key = "err_quota"
    _log_provider_error(resp.status_code, body)
    return key


def _log_provider_error(status, body):
    """The vendor's own words, for the log and not for the screen."""
    try:
        from flask import current_app

        current_app.logger.warning(
            "AI provider refused: HTTP %s %s", status, (body or "")[:500])
    except Exception:  # noqa: BLE001 - a log line never breaks an answer
        pass


# Every failure the assistant can report, and the sentence it becomes.
#
# A map rather than a prefix rule, so that adding a failure without adding its
# wording is a test failure and not a screen showing a bare identifier to a
# receptionist. `test_the_assistant_speaks_in_sentences` walks this module and
# checks that every error it can return is listed here.
ERROR_KEYS = {
    "disabled": "ai.err_disabled",
    "not_configured": "ai.err_not_configured",
    "no_key": "ai.err_no_key",
    "empty": "ai.err_empty",
    "patient_context_disabled": "ai.err_patient_context",
    # Its own sentence rather than sharing the one above, because the two
    # switches are two decisions and pointing somebody at the wrong one costs
    # them a settings screen and a guess.
    "discussion_disabled": "ai.err_discussion_off",
    "err_request": "ai.err_request",
    "err_key": "ai.err_key",
    "err_model": "ai.err_model",
    "err_timeout": "ai.err_timeout",
    "err_too_long": "ai.err_too_long",
    "err_rate": "ai.err_rate",
    "err_quota": "ai.err_quota",
    "err_provider": "ai.err_provider",
    "err_http": "ai.err_http",
    "err_network": "ai.err_network",
    "err_reply": "ai.err_reply",
    "err_library": "ai.err_library",
    "unknown": "ai.err_unknown",
}


def as_json(result):
    """A result dict with its failure already in words, ready for a browser.

    Every screen that talks to the assistant used to build its own sentence
    out of whatever `error` happened to hold, in five slightly different ways,
    and all five printed the provider's raw body when it held one. The key
    stays on the wire for anything that wants to branch on it; `message` is
    what a person reads.
    """
    if result.get("ok"):
        return result
    return dict(result, message=error_sentence(result.get("error")))


def error_sentence(error):
    """The clinic-facing sentence for whatever the layer below returned.

    Anything unrecognised becomes the general sentence rather than being shown
    as itself: a string that reaches here unlisted is a bug in this module,
    and the person in front of the screen is not the one who can fix it.
    """
    from app.i18n import translate

    key = ERROR_KEYS.get(str(error or ""), "ai.err_unknown")
    try:
        return translate(key)
    except RuntimeError:
        # Resolving a language needs a request, and this is also called from
        # a background job and a command line. Falling back to the clinic's
        # default is better than an unhandled error in a path whose whole
        # purpose is reporting one.
        from app.i18n import _load_translations, _lookup, default_language

        loaded = _load_translations()
        return (_lookup(loaded, default_language(), key)
                or _lookup(loaded, "en", key) or key)


def why_not_ready(cfg=None):
    """Which condition is missing, as keys the screen can translate.

    "Not ready" on its own is what produced *"it says not ready while it is
    connected and working"*: the assistant answers a test perfectly, the page
    still shows a grey badge, and nothing on it says which of four different
    things is missing. Most often nothing is wrong with the credentials at all
    — the test button reads the **unsaved** form on purpose, so somebody can
    paste a key and find out before committing it, and a key that tested fine
    but was never saved leaves exactly this impression.
    """
    cfg = cfg or get_config()
    missing = []
    if not cfg["enabled"]:
        missing.append("disabled")
    if not cfg["model"]:
        missing.append("no_model")
    if not cfg["base_url"]:
        missing.append("no_url")
    if not cfg["local"] and not cfg["api_key"]:
        missing.append("no_key")
    return missing


def usage_summary(days=30):
    """What the assistant has cost, by feature, over a window of days.

    Deliberately *not* called "remaining". No provider tells a chat request how
    much quota is left on the key — that number is in the vendor's billing
    console and depends on a plan the program has never been told about. A
    screen that guessed would be wrong in the direction that hurts: a clinic
    that trusts "plenty left" and stops mid-consultation. So this reports what
    was spent, which is exact, and links to the vendor for what is not.

    Split by feature because that is the only shape anybody can act on. Knowing
    the month cost 400,000 tokens tells a clinic nothing; knowing that visit
    summaries are three quarters of it tells them what to turn off.
    """
    from datetime import datetime, timedelta

    from sqlalchemy import func

    from app.extensions import db
    from app.models import AiUsage

    since = datetime.utcnow() - timedelta(days=days)
    rows = (db.session.query(
        AiUsage.feature,
        func.count(AiUsage.id),
        func.sum(AiUsage.prompt_tokens),
        func.sum(AiUsage.completion_tokens))
        .filter(AiUsage.created_at >= since)
        .group_by(AiUsage.feature)
        .all())
    features = [{"feature": feature or "chat", "calls": calls,
                 "prompt": int(prompt or 0), "completion": int(completion or 0),
                 "total": int(prompt or 0) + int(completion or 0)}
                for feature, calls, prompt, completion in rows]
    features.sort(key=lambda row: row["total"], reverse=True)
    return {"days": days, "features": features,
            "calls": sum(row["calls"] for row in features),
            "total": sum(row["total"] for row in features)}


def same_as_saved(cfg):
    """Whether a config is what the clinic actually has stored.

    Used to tell somebody their successful test was of unsaved values — the
    difference between "it works" and "it works and will keep working".
    """
    saved = get_config()
    return all(cfg.get(k) == saved.get(k)
               for k in ("provider", "api_key", "model", "base_url"))
