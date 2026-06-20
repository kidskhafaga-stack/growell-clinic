"""Finance helpers: invoice numbering."""
from app.extensions import db
from app.models import Invoice

INVOICE_PREFIX = "INV"


def generate_invoice_number():
    """Return the next sequential invoice number, e.g. ``INV-000123``."""
    last = (
        Invoice.query.order_by(Invoice.id.desc()).first()
    )
    seq = 1
    if last and last.invoice_number and "-" in last.invoice_number:
        try:
            seq = int(last.invoice_number.rsplit("-", 1)[1]) + 1
        except (ValueError, IndexError):
            seq = (last.id or 0) + 1
    return f"{INVOICE_PREFIX}-{seq:06d}"
