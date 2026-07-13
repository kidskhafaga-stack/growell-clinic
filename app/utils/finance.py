"""Finance helpers: configurable invoice/receipt document numbering (F1).

The printed receipt carries the invoice's number, so this is the single
document sequence for the revenue cycle. Prefix, scheme and starting number
are settings (no code changes needed per clinic):

* ``invoice_number_prefix``  — default ``INV``.
* ``invoice_number_scheme``  — ``fixed`` (INV-000123, continuous) or
  ``yearly`` (INV-2026-0001, resets each year).
* ``invoice_number_start``   — first sequence number to use (e.g. continue
  from a previous paper/system series).
"""
from datetime import datetime

from app.models import Invoice

DEFAULT_PREFIX = "INV"


def _numbering_config():
    from app.models import Setting

    prefix = (Setting.get("invoice_number_prefix") or DEFAULT_PREFIX).strip() or DEFAULT_PREFIX
    scheme = Setting.get("invoice_number_scheme", "fixed")
    try:
        start = max(int(Setting.get("invoice_number_start", "1")), 1)
    except (TypeError, ValueError):
        start = 1
    return prefix, scheme, start


def generate_invoice_number():
    """Next sequential document number under the configured series.

    Scans the current series' highest trailing number (robust against rows
    imported from other formats) and never returns a duplicate.
    """
    prefix, scheme, start = _numbering_config()
    if scheme == "yearly":
        base = f"{prefix}-{datetime.utcnow().year}-"
        width = 4
    else:
        base = f"{prefix}-"
        width = 6

    top = 0
    rows = (Invoice.query.filter(Invoice.invoice_number.like(base + "%"))
            .with_entities(Invoice.invoice_number).all())
    for (num,) in rows:
        tail = num[len(base):]
        if tail.isdigit():
            top = max(top, int(tail))

    seq = max(top + 1, start)
    candidate = f"{base}{seq:0{width}d}"
    while Invoice.query.filter_by(invoice_number=candidate).first() is not None:
        seq += 1
        candidate = f"{base}{seq:0{width}d}"
    return candidate
