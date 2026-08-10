"""Warehouse documentary cycle (W1): numbered store documents.

Every stock change is grouped under a numbered document — GRN (إذن إضافة),
ISS (إذن صرف), ADJ (تسوية جرد), WST (هالك) — so the store's audit trail reads
like paper: documents first, quantities inside them. Numbering follows the
same configurable idea as invoices: yearly series (GRN-2026-000001, default)
or one continuous series (``store_number_scheme`` = ``fixed``).
"""
from datetime import date, datetime

from flask_login import current_user

from app.extensions import db
from app.models import DOC_PREFIXES, Setting, StoreDocument
from app.utils.clock import local_today


def next_doc_number(kind):
    """The next serial for this document kind (per-year by default)."""
    base = DOC_PREFIXES.get(kind, "DOC")
    scheme = Setting.get("store_number_scheme", "yearly")
    prefix = f"{base}-" if scheme == "fixed" else f"{base}-{datetime.utcnow().year}-"
    top = 0
    rows = (StoreDocument.query
            .filter(StoreDocument.doc_number.like(prefix + "%"))
            .with_entities(StoreDocument.doc_number).all())
    for (num,) in rows:
        tail = num[len(prefix):]
        if tail.isdigit():
            top = max(top, int(tail))
    return f"{prefix}{top + 1:06d}"


def open_document(kind, reference=None, supplier_id=None, notes=None,
                  doc_date=None):
    """Create (and flush) a new numbered store document to hang changes on."""
    doc = StoreDocument(
        doc_number=next_doc_number(kind), kind=kind,
        doc_date=doc_date or local_today(),
        supplier_id=supplier_id, reference=reference, notes=notes,
        created_by=getattr(current_user, "id", None),
    )
    db.session.add(doc)
    db.session.flush()
    return doc
