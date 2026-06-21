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
        "default_model": "claude-sonnet-4-6",
        "models": [
            "claude-opus-4-8",
            "claude-sonnet-4-6",
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
        "default_model": "gemini-2.0-flash",
        "models": ["gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash"],
        "keys_url": "https://aistudio.google.com/app/apikey",
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
        "api_key": (rows.get("ai_api_key") or "").strip(),
        "model": (rows.get("ai_model") or "").strip() or meta["default_model"],
        "base_url": (rows.get("ai_base_url") or "").strip() or meta["base_url"],
        "system_prompt": (rows.get("ai_system_prompt") or "").strip(),
    }


def is_ready():
    """True when AI is enabled and the minimum credentials are present."""
    cfg = get_config()
    return bool(cfg["enabled"] and cfg["api_key"] and cfg["base_url"] and cfg["model"])


def chat(messages, system=None, config=None):
    """Send a chat conversation to the configured provider.

    ``messages`` is a list of ``{"role": "user"|"assistant", "content": str}``.
    Returns ``{"ok": True, "text": ...}`` or ``{"ok": False, "error": ...}``.
    Networking/SDK errors never raise out of here — callers get a clean dict.
    """
    cfg = config or get_config()
    if not cfg["enabled"]:
        return {"ok": False, "error": "disabled"}
    if not cfg["api_key"] or not cfg["base_url"] or not cfg["model"]:
        return {"ok": False, "error": "not_configured"}

    try:
        import requests
    except ImportError:  # pragma: no cover - requests is in requirements
        return {"ok": False, "error": "requests library not installed"}

    api = AI_PROVIDERS[cfg["provider"]]["api"]
    system_prompt = system or cfg["system_prompt"] or None
    try:
        if api == "anthropic":
            return _chat_anthropic(requests, cfg, messages, system_prompt)
        if api == "gemini":
            return _chat_gemini(requests, cfg, messages, system_prompt)
        return _chat_openai(requests, cfg, messages, system_prompt)
    except requests.exceptions.RequestException as exc:  # network/timeout
        return {"ok": False, "error": f"network: {exc}"}
    except (KeyError, ValueError, IndexError) as exc:  # unexpected payload
        return {"ok": False, "error": f"bad response: {exc}"}


def _chat_openai(requests, cfg, messages, system_prompt):
    payload_msgs = list(messages)
    if system_prompt:
        payload_msgs = [{"role": "system", "content": system_prompt}] + payload_msgs
    resp = requests.post(
        cfg["base_url"],
        headers={
            "Authorization": f"Bearer {cfg['api_key']}",
            "Content-Type": "application/json",
        },
        json={"model": cfg["model"], "messages": payload_msgs},
        timeout=REQUEST_TIMEOUT,
    )
    if not resp.ok:
        return {"ok": False, "error": _http_error(resp)}
    data = resp.json()
    return {"ok": True, "text": data["choices"][0]["message"]["content"]}


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
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=REQUEST_TIMEOUT,
    )
    if not resp.ok:
        return {"ok": False, "error": _http_error(resp)}
    data = resp.json()
    parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
    return {"ok": True, "text": "".join(parts)}


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
    return {"ok": True, "text": "".join(p.get("text", "") for p in parts)}


def _http_error(resp):
    """Compact, user-safe error string from a failed HTTP response."""
    snippet = (resp.text or "").strip()
    if len(snippet) > 300:
        snippet = snippet[:300] + "…"
    return f"HTTP {resp.status_code}: {snippet}"
