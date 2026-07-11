"""Lightweight key-based internationalisation for GROWELL CLINIC.

Every user-facing string flows through ``t("some.key")`` rather than being
hard-coded. Translations live in JSON files under ``locales/`` (one per
language) so non-developers can extend them and medical terms can be curated
in both Arabic and English.

Design goals:
* Bilingual (Arabic / English) from day one.
* RTL / LTR direction derived from the active language.
* Graceful fallback: missing key -> English -> the key itself, so the UI never
  shows a blank label and missing translations are easy to spot.
* Simple ``{name}`` style parameter interpolation.
"""
import json
import os

from flask import current_app, g, request, session

LOCALES_DIR = os.path.join(os.path.dirname(__file__), "locales")

# Languages that render right-to-left.
RTL_LANGUAGES = {"ar"}

# Loaded lazily and cached for the process lifetime.
_translations = {}


def _load_translations():
    """Load every ``<lang>.json`` file from the locales directory once."""
    if _translations:
        return _translations

    for filename in os.listdir(LOCALES_DIR):
        if not filename.endswith(".json"):
            continue
        lang = filename[: -len(".json")]
        with open(os.path.join(LOCALES_DIR, filename), encoding="utf-8") as fh:
            _translations[lang] = json.load(fh)
    return _translations


def available_languages():
    return current_app.config.get("LANGUAGES", ["ar", "en"])


def default_language():
    return current_app.config.get("DEFAULT_LANGUAGE", "ar")


def get_locale():
    """Resolve the active language for the current request.

    Order of precedence: explicit session choice -> browser preference ->
    configured default.
    """
    if "lang" in session and session["lang"] in available_languages():
        return session["lang"]

    best = request.accept_languages.best_match(available_languages())
    return best or default_language()


def set_locale(lang):
    """Persist a language choice in the session if it is supported."""
    if lang in available_languages():
        session["lang"] = lang
        return True
    return False


def get_direction(lang=None):
    lang = lang or get_locale()
    return "rtl" if lang in RTL_LANGUAGES else "ltr"


def _lookup(translations, lang, key):
    """Return the raw string for ``key`` in ``lang`` or ``None``.

    Keys are dotted paths into the nested JSON structure (``"nav.patients"``).
    """
    node = translations.get(lang)
    if node is None:
        return None
    for part in key.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return None
    return node if isinstance(node, str) else None


def translate(key, **params):
    """Translate ``key`` into the active language with ``{param}`` support."""
    translations = _load_translations()
    lang = getattr(g, "lang", None) or get_locale()

    text = _lookup(translations, lang, key)
    if text is None:
        # Fall back to English, then to the key itself.
        text = _lookup(translations, "en", key)
    if text is None:
        return key

    if params:
        try:
            return text.format(**params)
        except (KeyError, IndexError):
            return text
    return text


# Short alias used throughout templates and views.
t = translate


def init_app(app):
    """Wire i18n helpers into the application and Jinja environment."""

    @app.before_request
    def _resolve_language():
        g.lang = get_locale()
        g.direction = get_direction(g.lang)

    @app.context_processor
    def _inject_i18n():
        return {
            "t": translate,
            "current_lang": getattr(g, "lang", default_language()),
            "direction": getattr(g, "direction", "rtl"),
            "available_languages": available_languages(),
        }

    # Make translations reload-able in debug without restarting the process.
    if app.debug:
        _translations.clear()
