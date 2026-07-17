"""Unified currency formatting (the Financial Formatter).

One facility-wide currency setting (``currency_code``) drives how every
amount renders across the program: "1,250.00 ج.م" in Arabic, "EGP 1,250.00"
in English — with the right number of decimals per currency (KWD/BHD/OMR
use 3, most use 2). Exposed to templates as the ``money`` filter and the
``currency_symbol`` global.
"""
from flask import g

# code -> (arabic symbol, english label, decimals)
CURRENCIES = {
    "EGP": ("ج.م", "EGP", 2),
    "SAR": ("ر.س", "SAR", 2),
    "AED": ("د.إ", "AED", 2),
    "QAR": ("ر.ق", "QAR", 2),
    "KWD": ("د.ك", "KWD", 3),
    "BHD": ("د.ب", "BHD", 3),
    "OMR": ("ر.ع", "OMR", 3),
    "JOD": ("د.أ", "JOD", 3),
    "IQD": ("د.ع", "IQD", 0),
    "LYD": ("د.ل", "LYD", 3),
    "SDG": ("ج.س", "SDG", 2),
    "YER": ("ر.ي", "YER", 0),
    "MAD": ("د.م", "MAD", 2),
    "TND": ("د.ت", "TND", 3),
    "DZD": ("د.ج", "DZD", 2),
    "USD": ("$", "$", 2),
    "EUR": ("€", "€", 2),
    "GBP": ("£", "£", 2),
    "TRY": ("₺", "₺", 2),
}
DEFAULT_CODE = "EGP"


def current_code():
    try:
        from app.models import Setting

        code = (Setting.get("currency_code") or DEFAULT_CODE).upper()
    except Exception:  # noqa: BLE001 - settings table not ready
        code = DEFAULT_CODE
    return code if code in CURRENCIES else DEFAULT_CODE


def currency_symbol(lang=None):
    ar, en, _dec = CURRENCIES[current_code()]
    lang = lang or getattr(g, "lang", "ar")
    return ar if lang == "ar" else en


def format_money(amount, lang=None):
    """1250 → "1,250.00 ج.م" (ar) / "EGP 1,250.00" (en)."""
    ar, en, dec = CURRENCIES[current_code()]
    try:
        value = float(amount or 0)
    except (TypeError, ValueError):
        value = 0.0
    num = f"{value:,.{dec}f}"
    lang = lang or getattr(g, "lang", "ar")
    if lang == "ar":
        return f"{num} {ar}"
    return f"{en} {num}" if en.isalpha() else f"{en}{num}"


def init_app(app):
    app.jinja_env.filters["money"] = format_money

    @app.context_processor
    def _inject_money():
        return {"currency_symbol": currency_symbol,
                "currency_code": current_code}
