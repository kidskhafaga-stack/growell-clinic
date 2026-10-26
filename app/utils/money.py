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


# ---------------------------------------------------------------------------
# Arithmetic to the piastre (MONEY_SAFETY_PLAN.md ف-٤)
#
# Measured on the owner's own test sheet: an invoice, a discount, three part
# payments and two refunds all came out exact — every figure was rounded to
# two places as it went. What did not was a **percentage**: 15% of 0.50 is
# 0.075, which a float holds as 0.07499999…, so `round(…, 2)` said 0.07
# where the rule everybody uses says 0.08. One piastre, on about one price
# and percentage in thirteen, on a discount, a doctor's share, an insurer's
# share, a card fee, a tax line. And an amount typed with three decimals was
# rounded without a word.
#
# So money is worked in **whole piastres** here: a figure is read to the
# piastre (half up), percentages are taken of whole piastres with Decimal and
# rounded half up, sums are sums of integers, and what goes back to the
# program is the float of an exact two-place figure. What is stored does not
# change shape — a two-place figure read back from the database through
# `str()` is the exact figure it was — so no clinic's file has to be moved.
# ---------------------------------------------------------------------------
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation  # noqa: E402

_ONE = Decimal(1)
_HUNDRED = Decimal(100)
_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


class MoneyError(ValueError):
    """An amount that cannot be taken as it was written: ``not_a_number`` or
    ``too_precise`` (more than two places after the point)."""


def _decimal(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    try:
        # `str()` of a float is its shortest exact spelling: 0.1 → "0.1",
        # never 0.1000000000000000055…
        d = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise MoneyError("not_a_number") from exc
    if not d.is_finite():
        raise MoneyError("not_a_number")
    return d


def to_piastres(value, strict=True):
    """Pounds → whole piastres. ``strict``: a third place is refused
    (``too_precise``) rather than rounded; otherwise it is rounded half up —
    for figures the program itself worked out and stored."""
    if value is None or value == "":
        return 0
    scaled = _decimal(value) * _HUNDRED
    whole = scaled.to_integral_value(rounding=ROUND_HALF_UP)
    if strict and whole != scaled:
        raise MoneyError("too_precise")
    return int(whole)


def piastres(value):
    """A stored or computed figure, to the piastre (half up). Never raises
    on a number; ``None`` is nought."""
    try:
        return to_piastres(value, strict=False)
    except MoneyError:
        return 0


def pounds(whole_piastres):
    """Whole piastres → the program's float, an exact two-place figure."""
    return int(whole_piastres) / 100


def percent_piastres(whole_piastres, percent):
    """``percent`` of an amount already in piastres, rounded half up."""
    if not percent:
        return 0
    share = Decimal(int(whole_piastres)) * _decimal(percent) / _HUNDRED
    return int(share.to_integral_value(rounding=ROUND_HALF_UP))


def percent(amount, rate):
    """``rate`` percent of ``amount`` in pounds, to the piastre, half up —
    the one way every share, discount, fee and tax line is worked out."""
    return pounds(percent_piastres(piastres(amount), rate))


def times_piastres(whole_piastres, quantity):
    """A price in piastres times a quantity, rounded half up."""
    product = Decimal(int(whole_piastres)) * _decimal(quantity or 0)
    return int(product.to_integral_value(rounding=ROUND_HALF_UP))


def total(values):
    """An exact sum of figures in pounds: added as whole piastres."""
    return pounds(sum(piastres(v) for v in values))


def parse_amount(text):
    """An amount as somebody typed it → pounds (float), exact to the piastre.

    Arabic-Indic digits and «٫» are read as they are meant; a thousands comma
    is dropped. More than two places after the point is **refused**
    (``MoneyError("too_precise")``), never rounded behind the person's back.
    """
    if text is None:
        raise MoneyError("not_a_number")
    raw = str(text).translate(_ARABIC_DIGITS).strip().replace("٫", ".")
    if raw.count(".") <= 1:
        raw = raw.replace(",", "").replace("٬", "")
    if not raw:
        raise MoneyError("not_a_number")
    return pounds(to_piastres(raw, strict=True))
